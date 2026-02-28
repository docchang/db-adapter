"""Tests for Step 9: Generalize Schema Fix Module.

Verifies that fix.py is free of hardcoded MC-specific code, accepts
caller-provided parameters, and uses the DatabaseClient.execute()
Protocol method for DDL operations.
"""

import ast
import asyncio  # noqa: F401 -- used in test_supabase_adapter_execute_raises
import inspect
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_adapter.schema.fix import (
    ColumnFix,
    FixPlan,
    FixResult,
    TableFix,
    _get_table_create_sql,
    _parse_fk_dependencies,
    _topological_sort,
    apply_fixes,
    generate_fix_plan,
)
from db_adapter.schema.models import ColumnDiff, SchemaValidationResult

# Path to the source file for AST/source inspection
FIX_PY = Path(__file__).parent.parent / "src" / "db_adapter" / "schema" / "fix.py"
BASE_PY = Path(__file__).parent.parent / "src" / "db_adapter" / "adapters" / "base.py"
POSTGRES_PY = Path(__file__).parent.parent / "src" / "db_adapter" / "adapters" / "postgres.py"
SUPABASE_PY = Path(__file__).parent.parent / "src" / "db_adapter" / "adapters" / "supabase.py"


# ------------------------------------------------------------------
# MC-specific code removal
# ------------------------------------------------------------------


class TestMCCodeRemoved:
    """Verify all MC-specific code is removed from fix.py."""

    def test_no_column_definitions_dict(self):
        """COLUMN_DEFINITIONS dict does not exist in fix.py."""
        source = FIX_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "COLUMN_DEFINITIONS":
                        pytest.fail("COLUMN_DEFINITIONS dict still exists in fix.py")

    def test_no_mc_coupled_imports(self):
        """No MC-coupled bare imports (from db import, from adapters import, etc.)."""
        source = FIX_PY.read_text()
        tree = ast.parse(source)
        forbidden_modules = {"db", "adapters", "config"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top_module = node.module.split(".")[0]
                if top_module in forbidden_modules:
                    pytest.fail(f"MC-coupled import found: from {node.module} import ...")

    def test_no_backup_import(self):
        """No from backup.backup_restore import ... in fix.py."""
        source = FIX_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "backup" in node.module and "backup_restore" in node.module:
                    pytest.fail(f"Backup import found: from {node.module} import ...")

    def test_no_profile_name_in_fixplan(self):
        """FixPlan dataclass has no profile_name field."""
        plan = FixPlan()
        assert not hasattr(plan, "profile_name"), "FixPlan still has profile_name field"

    def test_no_profile_name_in_fixresult(self):
        """FixResult Pydantic model has no profile_name field."""
        assert "profile_name" not in FixResult.model_fields, "FixResult still has profile_name field"

    def test_no_hardcoded_mc_table_names(self):
        """No hardcoded MC table names (projects, milestones, tasks) in fix.py."""
        source = FIX_PY.read_text()
        # Check for hardcoded MC table name strings (not in comments/docstrings)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.lower()
                if val in ("projects", "milestones", "tasks"):
                    pytest.fail(f"Hardcoded MC table name found: '{node.value}'")


# ------------------------------------------------------------------
# Function signatures
# ------------------------------------------------------------------


class TestFunctionSignatures:
    """Verify function signatures match the plan specification."""

    def test_generate_fix_plan_params(self):
        """generate_fix_plan accepts (validation_result, column_definitions, schema_file)."""
        sig = inspect.signature(generate_fix_plan)
        params = list(sig.parameters.keys())
        assert params == ["validation_result", "column_definitions", "schema_file"]

    def test_generate_fix_plan_not_async(self):
        """generate_fix_plan is sync (pure logic, no network I/O)."""
        assert not inspect.iscoroutinefunction(generate_fix_plan)

    def test_apply_fixes_is_async(self):
        """apply_fixes is async def."""
        assert inspect.iscoroutinefunction(apply_fixes)

    def test_apply_fixes_params(self):
        """apply_fixes accepts adapter, plan, callback params, dry_run, confirm."""
        sig = inspect.signature(apply_fixes)
        params = list(sig.parameters.keys())
        assert "adapter" in params
        assert "plan" in params
        assert "backup_fn" in params
        assert "restore_fn" in params
        assert "verify_fn" in params
        assert "dry_run" in params
        assert "confirm" in params

    def test_get_table_create_sql_requires_schema_file(self):
        """_get_table_create_sql requires schema_file (no None default)."""
        sig = inspect.signature(_get_table_create_sql)
        param = sig.parameters["schema_file"]
        assert param.default is inspect.Parameter.empty, (
            "schema_file has a default value -- should be required"
        )

    def test_generate_fix_plan_no_profile_name_param(self):
        """generate_fix_plan does not accept profile_name."""
        sig = inspect.signature(generate_fix_plan)
        assert "profile_name" not in sig.parameters

    def test_apply_fixes_no_profile_name_param(self):
        """apply_fixes does not accept profile_name."""
        sig = inspect.signature(apply_fixes)
        assert "profile_name" not in sig.parameters


# ------------------------------------------------------------------
# DatabaseClient Protocol execute method
# ------------------------------------------------------------------


class TestDatabaseClientExecute:
    """Verify execute method on DatabaseClient Protocol and adapters."""

    def test_protocol_has_execute(self):
        """DatabaseClient Protocol defines execute method."""
        from db_adapter.adapters.base import DatabaseClient

        assert hasattr(DatabaseClient, "execute"), "DatabaseClient has no execute method"

    def test_protocol_execute_is_async(self):
        """DatabaseClient.execute is async."""
        from db_adapter.adapters.base import DatabaseClient

        source = BASE_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "DatabaseClient":
                for item in node.body:
                    if isinstance(item, ast.AsyncFunctionDef) and item.name == "execute":
                        return
        pytest.fail("execute is not an async method on DatabaseClient Protocol")

    def test_protocol_execute_signature(self):
        """DatabaseClient.execute has correct signature (sql, params)."""
        from db_adapter.adapters.base import DatabaseClient

        # Inspect the Protocol class method
        source = BASE_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "DatabaseClient":
                for item in node.body:
                    if isinstance(item, ast.AsyncFunctionDef) and item.name == "execute":
                        param_names = [arg.arg for arg in item.args.args]
                        assert "self" in param_names
                        assert "sql" in param_names
                        assert "params" in param_names
                        return
        pytest.fail("execute method not found on DatabaseClient")

    def test_postgres_adapter_has_execute(self):
        """AsyncPostgresAdapter implements execute."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert hasattr(AsyncPostgresAdapter, "execute")
        assert inspect.iscoroutinefunction(AsyncPostgresAdapter.execute)

    def test_supabase_adapter_execute_raises(self):
        """AsyncSupabaseAdapter.execute raises NotImplementedError."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        adapter = AsyncSupabaseAdapter(url="https://x.supabase.co", key="fake")
        with pytest.raises(NotImplementedError, match="DDL operations not supported"):
            asyncio.run(adapter.execute("CREATE TABLE t (id INT)"))

    def test_protocol_has_six_methods(self):
        """DatabaseClient Protocol now has 6 async methods (select, insert, update, delete, execute, close)."""
        source = BASE_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "DatabaseClient":
                async_methods = [
                    item.name
                    for item in node.body
                    if isinstance(item, ast.AsyncFunctionDef)
                ]
                expected = {"select", "insert", "update", "delete", "execute", "close"}
                assert set(async_methods) == expected, (
                    f"Expected {expected}, got {set(async_methods)}"
                )
                return
        pytest.fail("DatabaseClient class not found")


# ------------------------------------------------------------------
# ColumnFix and TableFix
# ------------------------------------------------------------------


class TestColumnFix:
    """Verify ColumnFix.to_sql() generates correct ALTER TABLE."""

    def test_simple_column(self):
        """Simple column generates correct ALTER TABLE."""
        fix = ColumnFix(table="users", column="email", definition="TEXT")
        assert fix.to_sql() == "ALTER TABLE users ADD COLUMN email TEXT;"

    def test_not_null_stripped(self):
        """NOT NULL is stripped from non-FK column definitions."""
        fix = ColumnFix(table="users", column="name", definition="VARCHAR(100) NOT NULL")
        sql = fix.to_sql()
        assert "NOT NULL" not in sql
        assert sql == "ALTER TABLE users ADD COLUMN name VARCHAR(100);"

    def test_primary_key_stripped(self):
        """PRIMARY KEY is stripped from column definitions."""
        fix = ColumnFix(table="users", column="id", definition="SERIAL PRIMARY KEY")
        sql = fix.to_sql()
        assert "PRIMARY KEY" not in sql

    def test_references_kept(self):
        """REFERENCES clause is kept for FK columns."""
        fix = ColumnFix(
            table="tasks",
            column="project_id",
            definition="INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
        )
        sql = fix.to_sql()
        assert "REFERENCES projects(id)" in sql
        assert "NOT NULL" in sql  # FK columns keep NOT NULL

    def test_default_value_kept(self):
        """DEFAULT values are preserved."""
        fix = ColumnFix(table="users", column="status", definition="VARCHAR(20) DEFAULT 'active'")
        sql = fix.to_sql()
        assert "DEFAULT 'active'" in sql


class TestTableFix:
    """Verify TableFix.to_sql() returns CREATE TABLE SQL."""

    def test_returns_create_sql(self):
        """to_sql returns the stored create_sql."""
        create = "CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);"
        fix = TableFix(table="users", create_sql=create)
        assert fix.to_sql() == create

    def test_is_recreate_flag(self):
        """is_recreate flag defaults to False."""
        fix = TableFix(table="users", create_sql="CREATE TABLE users ();")
        assert fix.is_recreate is False

        fix2 = TableFix(table="users", create_sql="CREATE TABLE users ();", is_recreate=True)
        assert fix2.is_recreate is True


# ------------------------------------------------------------------
# FixPlan dataclass
# ------------------------------------------------------------------


class TestFixPlan:
    """Verify FixPlan structure and properties."""

    def test_has_fixes_empty(self):
        """Empty plan has no fixes."""
        plan = FixPlan()
        assert not plan.has_fixes
        assert plan.fix_count == 0

    def test_has_fixes_with_tables(self):
        """Plan with missing tables has fixes."""
        plan = FixPlan(missing_tables=[TableFix(table="t", create_sql="CREATE TABLE t ();")])
        assert plan.has_fixes
        assert plan.fix_count == 1

    def test_has_drop_order_and_create_order(self):
        """FixPlan has drop_order and create_order fields."""
        plan = FixPlan()
        assert hasattr(plan, "drop_order")
        assert hasattr(plan, "create_order")
        assert isinstance(plan.drop_order, list)
        assert isinstance(plan.create_order, list)

    def test_no_profile_name_field(self):
        """FixPlan has no profile_name field."""
        import dataclasses

        field_names = [f.name for f in dataclasses.fields(FixPlan)]
        assert "profile_name" not in field_names


# ------------------------------------------------------------------
# FixResult model
# ------------------------------------------------------------------


class TestFixResult:
    """Verify FixResult Pydantic model."""

    def test_no_profile_name_field(self):
        """FixResult has no profile_name field."""
        assert "profile_name" not in FixResult.model_fields

    def test_default_values(self):
        """FixResult defaults are correct."""
        result = FixResult()
        assert result.success is False
        assert result.backup_path is None
        assert result.tables_created == 0
        assert result.tables_recreated == 0
        assert result.columns_added == 0
        assert result.error is None


# ------------------------------------------------------------------
# _get_table_create_sql
# ------------------------------------------------------------------


class TestGetTableCreateSQL:
    """Verify _get_table_create_sql reads from schema file."""

    def test_finds_create_table(self, tmp_path):
        """Finds CREATE TABLE statement in schema file."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL
            );

            CREATE TABLE posts (
                id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(id)
            );
        """))
        sql = _get_table_create_sql("users", schema)
        assert "CREATE TABLE users" in sql
        assert "id SERIAL PRIMARY KEY" in sql

    def test_finds_if_not_exists(self, tmp_path):
        """Finds CREATE TABLE IF NOT EXISTS statements."""
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE IF NOT EXISTS users (id INT);")
        sql = _get_table_create_sql("users", schema)
        assert "users" in sql

    def test_raises_file_not_found(self, tmp_path):
        """Raises FileNotFoundError for missing schema file."""
        with pytest.raises(FileNotFoundError, match="Schema file not found"):
            _get_table_create_sql("users", tmp_path / "nonexistent.sql")

    def test_raises_value_error_unknown_table(self, tmp_path):
        """Raises ValueError for unknown table name."""
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE users (id INT);")
        with pytest.raises(ValueError, match="CREATE TABLE for posts not found"):
            _get_table_create_sql("posts", schema)


# ------------------------------------------------------------------
# FK dependency parsing and topological sort
# ------------------------------------------------------------------


class TestFKDependencies:
    """Verify FK dependency parsing from schema files."""

    def test_parses_single_reference(self, tmp_path):
        """Parses a single REFERENCES clause."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE parents (id SERIAL PRIMARY KEY);
            CREATE TABLE children (
                id SERIAL PRIMARY KEY,
                parent_id INT REFERENCES parents(id)
            );
        """))
        deps = _parse_fk_dependencies(schema)
        assert deps["children"] == {"parents"}
        assert deps["parents"] == set()

    def test_parses_multiple_references(self, tmp_path):
        """Parses multiple REFERENCES clauses in one table."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE a (id SERIAL PRIMARY KEY);
            CREATE TABLE b (id SERIAL PRIMARY KEY);
            CREATE TABLE c (
                id SERIAL PRIMARY KEY,
                a_id INT REFERENCES a(id),
                b_id INT REFERENCES b(id)
            );
        """))
        deps = _parse_fk_dependencies(schema)
        assert deps["c"] == {"a", "b"}
        assert deps["a"] == set()
        assert deps["b"] == set()

    def test_nonexistent_file_returns_empty(self, tmp_path):
        """Returns empty dict for nonexistent schema file."""
        deps = _parse_fk_dependencies(tmp_path / "nonexistent.sql")
        assert deps == {}


class TestTopologicalSort:
    """Verify topological sort of tables by FK dependencies."""

    def test_forward_order_parents_first(self):
        """Forward topological sort: parent tables before children."""
        deps = {"children": {"parents"}, "parents": set()}
        result = _topological_sort(deps, ["children", "parents"])
        assert result.index("parents") < result.index("children")

    def test_reverse_order_for_drops(self):
        """Reverse of topological sort: children before parents (for DROP)."""
        deps = {"children": {"parents"}, "parents": set()}
        forward = _topological_sort(deps, ["children", "parents"])
        drop_order = list(reversed(forward))
        assert drop_order.index("children") < drop_order.index("parents")

    def test_three_level_hierarchy(self):
        """Three-level hierarchy: grandparent -> parent -> child."""
        deps = {
            "grandparent": set(),
            "parent": {"grandparent"},
            "child": {"parent"},
        }
        result = _topological_sort(deps, ["child", "parent", "grandparent"])
        assert result.index("grandparent") < result.index("parent")
        assert result.index("parent") < result.index("child")

    def test_independent_tables(self):
        """Independent tables (no deps) are all included."""
        deps = {"a": set(), "b": set(), "c": set()}
        result = _topological_sort(deps, ["c", "b", "a"])
        assert set(result) == {"a", "b", "c"}

    def test_handles_cycle_gracefully(self):
        """Handles circular dependencies without infinite loop."""
        deps = {"a": {"b"}, "b": {"a"}}
        result = _topological_sort(deps, ["a", "b"])
        assert set(result) == {"a", "b"}


# ------------------------------------------------------------------
# generate_fix_plan
# ------------------------------------------------------------------


class TestGenerateFixPlan:
    """Verify generate_fix_plan logic."""

    def test_no_fixes_needed(self, tmp_path):
        """Returns empty plan when no errors."""
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE users (id INT);")
        result = SchemaValidationResult(
            valid=True,
            missing_tables=[],
            missing_columns=[],
            extra_tables=[],
        )
        plan = generate_fix_plan(result, {}, schema)
        assert not plan.has_fixes
        assert plan.error is None

    def test_missing_table(self, tmp_path):
        """Detects and plans for missing table."""
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);")
        result = SchemaValidationResult(
            valid=False,
            missing_tables=["users"],
            missing_columns=[],
            extra_tables=[],
        )
        plan = generate_fix_plan(result, {}, schema)
        assert len(plan.missing_tables) == 1
        assert plan.missing_tables[0].table == "users"
        assert "CREATE TABLE users" in plan.missing_tables[0].create_sql

    def test_single_missing_column_uses_alter(self, tmp_path):
        """Single missing column -> ALTER ADD COLUMN (not DROP+CREATE)."""
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE users (id INT);")
        result = SchemaValidationResult(
            valid=False,
            missing_tables=[],
            missing_columns=[ColumnDiff(table="users", column="email", message="Missing")],
            extra_tables=[],
        )
        col_defs = {"users.email": "TEXT NOT NULL"}
        plan = generate_fix_plan(result, col_defs, schema)
        assert len(plan.missing_columns) == 1
        assert plan.missing_columns[0].column == "email"
        assert plan.tables_to_recreate == []

    def test_two_missing_columns_uses_recreate(self, tmp_path):
        """Two+ missing columns -> DROP+CREATE (not ALTER)."""
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE users (id INT, name TEXT, email TEXT);")
        result = SchemaValidationResult(
            valid=False,
            missing_tables=[],
            missing_columns=[
                ColumnDiff(table="users", column="name", message="Missing"),
                ColumnDiff(table="users", column="email", message="Missing"),
            ],
            extra_tables=[],
        )
        col_defs = {"users.name": "TEXT", "users.email": "TEXT"}
        plan = generate_fix_plan(result, col_defs, schema)
        assert len(plan.tables_to_recreate) == 1
        assert plan.tables_to_recreate[0].table == "users"
        assert plan.tables_to_recreate[0].is_recreate is True
        assert plan.missing_columns == []

    def test_unknown_column_definition_error(self, tmp_path):
        """Error when column definition not provided."""
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE users (id INT);")
        result = SchemaValidationResult(
            valid=False,
            missing_tables=[],
            missing_columns=[ColumnDiff(table="users", column="unknown_col", message="Missing")],
            extra_tables=[],
        )
        plan = generate_fix_plan(result, {}, schema)
        assert plan.error is not None
        assert "Unknown column definition" in plan.error

    def test_topological_order_computed(self, tmp_path):
        """generate_fix_plan computes drop_order and create_order."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE parents (
                id SERIAL PRIMARY KEY
            );
            CREATE TABLE children (
                id SERIAL PRIMARY KEY,
                parent_id INT REFERENCES parents(id)
            );
        """))
        result = SchemaValidationResult(
            valid=False,
            missing_tables=["parents", "children"],
            missing_columns=[],
            extra_tables=[],
        )
        plan = generate_fix_plan(result, {}, schema)
        # Create order: parents before children
        assert plan.create_order.index("parents") < plan.create_order.index("children")
        # Drop order: children before parents
        assert plan.drop_order.index("children") < plan.drop_order.index("parents")


# ------------------------------------------------------------------
# apply_fixes
# ------------------------------------------------------------------


class TestApplyFixes:
    """Verify async apply_fixes behavior."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter with execute method."""
        adapter = AsyncMock()
        adapter.execute = AsyncMock()
        return adapter

    @pytest.fixture
    def simple_plan(self):
        """Create a simple fix plan with one missing table."""
        return FixPlan(
            missing_tables=[
                TableFix(table="users", create_sql="CREATE TABLE users (id INT);")
            ],
        )

    async def test_dry_run_no_execute(self, mock_adapter, simple_plan):
        """Dry run reports counts without executing DDL."""
        result = await apply_fixes(mock_adapter, simple_plan, dry_run=True)
        assert result.success is True
        assert result.tables_created == 1
        mock_adapter.execute.assert_not_called()

    async def test_requires_confirm(self, mock_adapter, simple_plan):
        """Non-dry-run without confirm returns error."""
        result = await apply_fixes(mock_adapter, simple_plan, dry_run=False, confirm=False)
        assert result.success is False
        assert "confirm=True" in result.error

    async def test_creates_missing_table(self, mock_adapter, simple_plan):
        """Executes CREATE TABLE for missing tables."""
        result = await apply_fixes(mock_adapter, simple_plan, dry_run=False, confirm=True)
        assert result.success is True
        assert result.tables_created == 1
        mock_adapter.execute.assert_called_once_with(
            "CREATE TABLE users (id INT);"
        )

    async def test_adds_missing_column(self, mock_adapter):
        """Executes ALTER TABLE for missing columns."""
        plan = FixPlan(
            missing_columns=[
                ColumnFix(table="users", column="email", definition="TEXT")
            ],
        )
        result = await apply_fixes(mock_adapter, plan, dry_run=False, confirm=True)
        assert result.success is True
        assert result.columns_added == 1
        mock_adapter.execute.assert_called_once()

    async def test_recreates_table(self, mock_adapter):
        """DROP+CREATE for tables with 2+ missing columns."""
        plan = FixPlan(
            tables_to_recreate=[
                TableFix(
                    table="users",
                    create_sql="CREATE TABLE users (id INT, name TEXT);",
                    is_recreate=True,
                )
            ],
        )
        result = await apply_fixes(mock_adapter, plan, dry_run=False, confirm=True)
        assert result.success is True
        assert result.tables_recreated == 1
        # Should have called DROP then CREATE
        calls = [call.args[0] for call in mock_adapter.execute.call_args_list]
        assert any("DROP TABLE" in c for c in calls)
        assert any("CREATE TABLE" in c for c in calls)

    async def test_not_implemented_raises_runtime_error(self):
        """Adapter that raises NotImplementedError -> RuntimeError with correct message."""
        adapter = AsyncMock()
        adapter.execute = AsyncMock(side_effect=NotImplementedError("not supported"))
        plan = FixPlan(
            missing_tables=[
                TableFix(table="t", create_sql="CREATE TABLE t (id INT);")
            ],
        )
        with pytest.raises(RuntimeError, match="DDL operations not supported for this adapter type"):
            await apply_fixes(adapter, plan, dry_run=False, confirm=True)

    async def test_empty_plan_succeeds(self, mock_adapter):
        """Empty plan (no fixes needed) returns success."""
        plan = FixPlan()
        result = await apply_fixes(mock_adapter, plan, dry_run=False, confirm=True)
        assert result.success is True
        mock_adapter.execute.assert_not_called()

    async def test_plan_with_error(self, mock_adapter):
        """Plan with error returns error without executing."""
        plan = FixPlan(error="Something went wrong")
        result = await apply_fixes(mock_adapter, plan, dry_run=False, confirm=True)
        assert result.success is False
        assert result.error == "Something went wrong"
        mock_adapter.execute.assert_not_called()

    async def test_backup_fn_called_for_recreate(self):
        """backup_fn is called before DROP+CREATE."""
        adapter = AsyncMock()
        adapter.execute = AsyncMock()
        backup_fn = AsyncMock(return_value="/tmp/backup.json")
        plan = FixPlan(
            tables_to_recreate=[
                TableFix(table="users", create_sql="CREATE TABLE users ();", is_recreate=True)
            ],
        )
        result = await apply_fixes(
            adapter, plan, backup_fn=backup_fn, dry_run=False, confirm=True,
        )
        assert result.success is True
        backup_fn.assert_called_once()
        assert result.backup_path == "/tmp/backup.json"

    async def test_restore_fn_called_after_recreate(self):
        """restore_fn is called after DROP+CREATE."""
        adapter = AsyncMock()
        adapter.execute = AsyncMock()
        backup_fn = AsyncMock(return_value="/tmp/backup.json")
        restore_fn = AsyncMock()
        plan = FixPlan(
            tables_to_recreate=[
                TableFix(table="users", create_sql="CREATE TABLE users ();", is_recreate=True)
            ],
        )
        result = await apply_fixes(
            adapter, plan, backup_fn=backup_fn, restore_fn=restore_fn,
            dry_run=False, confirm=True,
        )
        assert result.success is True
        restore_fn.assert_called_once()

    async def test_verify_fn_called_after_fixes(self):
        """verify_fn is called after all fixes are applied."""
        adapter = AsyncMock()
        adapter.execute = AsyncMock()
        verify_fn = AsyncMock(return_value=True)
        plan = FixPlan(
            missing_columns=[ColumnFix(table="users", column="email", definition="TEXT")],
        )
        result = await apply_fixes(
            adapter, plan, verify_fn=verify_fn, dry_run=False, confirm=True,
        )
        assert result.success is True
        verify_fn.assert_called_once()

    async def test_verify_fn_failure(self):
        """verify_fn returning False sets error."""
        adapter = AsyncMock()
        adapter.execute = AsyncMock()
        verify_fn = AsyncMock(return_value=False)
        plan = FixPlan(
            missing_columns=[ColumnFix(table="users", column="email", definition="TEXT")],
        )
        result = await apply_fixes(
            adapter, plan, verify_fn=verify_fn, dry_run=False, confirm=True,
        )
        assert result.success is False
        assert "verification failed" in result.error

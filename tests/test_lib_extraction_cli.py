"""Tests for Step 12: Modernize CLI.

Verifies that the CLI module:
- Uses ``db-adapter`` as program name (not ``python -m schema``)
- Contains no ``Mission Control`` strings
- Contains no ``MC_DB_PROFILE`` references
- Contains no ``COLUMN_DEFINITIONS`` or ``fk_drop_order``/``fk_create_order`` dicts
- Wraps async calls via ``asyncio.run()``
- Has ``--env-prefix`` global option
- Has ``--tables`` and ``--user-id`` arguments on sync
- Has ``--schema-file`` and ``--column-defs`` arguments on fix
- ``_parse_expected_columns()`` correctly parses CREATE TABLE SQL
"""

import argparse
import ast
import asyncio
import inspect
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_adapter.cli import (
    _async_backup,
    _async_connect,
    _async_fix,
    _async_restore,
    _async_status,
    _async_sync,
    _async_validate,
    _load_backup_schema,
    _parse_expected_columns,
    _print_table_counts,
    _resolve_backup_schema_path,
    _resolve_user_id,
    _validate_backup,
    cmd_backup,
    cmd_connect,
    cmd_fix,
    cmd_profiles,
    cmd_restore,
    cmd_status,
    cmd_sync,
    cmd_validate,
    main,
)

# Paths to source files for AST/source inspection
CLI_INIT_PY = (
    Path(__file__).parent.parent / "src" / "db_adapter" / "cli" / "__init__.py"
)

# ------------------------------------------------------------------
# MC-specific code removal
# ------------------------------------------------------------------


class TestMCCodeRemoved:
    """Verify all MC-specific code is removed from CLI files."""

    def test_no_mission_control_in_cli_init(self):
        """'Mission Control' does not appear in cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        assert "Mission Control" not in source, (
            "Found 'Mission Control' in cli/__init__.py"
        )

    def test_no_python_m_schema_in_cli(self):
        """'python -m schema' does not appear in cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        assert "python -m schema" not in source, (
            "Found 'python -m schema' in cli/__init__.py"
        )

    def test_no_mc_db_profile_in_cli(self):
        """MC_DB_PROFILE does not appear in cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        assert "MC_DB_PROFILE" not in source, (
            "Found 'MC_DB_PROFILE' in cli/__init__.py"
        )

    def test_no_column_definitions_import(self):
        """COLUMN_DEFINITIONS is not imported in cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        assert "COLUMN_DEFINITIONS" not in source, (
            "Found 'COLUMN_DEFINITIONS' in cli/__init__.py"
        )

    def test_no_hardcoded_fk_order_dicts(self):
        """fk_drop_order and fk_create_order dicts do not exist."""
        source = CLI_INIT_PY.read_text()
        assert "fk_drop_order" not in source, (
            "Found 'fk_drop_order' in cli/__init__.py"
        )
        assert "fk_create_order" not in source, (
            "Found 'fk_create_order' in cli/__init__.py"
        )

    def test_no_get_dev_user_id(self):
        """get_dev_user_id is not referenced in cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        assert "get_dev_user_id" not in source, (
            "Found 'get_dev_user_id' in cli/__init__.py"
        )

    def test_no_subprocess_in_cli(self):
        """subprocess is not imported in cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "subprocess", (
                        "subprocess is still imported in cli/__init__.py"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    pytest.fail(
                        "subprocess is still imported in cli/__init__.py"
                    )

    def test_no_show_profile_data(self):
        """_show_profile_data helper is removed from cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        assert "_show_profile_data" not in source, (
            "Found '_show_profile_data' in cli/__init__.py"
        )

    def test_no_show_profile_comparison(self):
        """_show_profile_comparison helper is removed from cli/__init__.py."""
        source = CLI_INIT_PY.read_text()
        assert "_show_profile_comparison" not in source, (
            "Found '_show_profile_comparison' in cli/__init__.py"
        )

    def test_no_hardcoded_table_names(self):
        """No hardcoded MC table names (projects, milestones, tasks) as
        string literals in the CLI source, excluding help text and comments."""
        source = CLI_INIT_PY.read_text()
        tree = ast.parse(source)

        # Check for hardcoded table name lists like ["projects", "milestones", "tasks"]
        for node in ast.walk(tree):
            if isinstance(node, ast.List):
                str_elements = [
                    elt.value
                    for elt in node.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
                if set(str_elements) == {"projects", "milestones", "tasks"}:
                    pytest.fail(
                        "Found hardcoded ['projects', 'milestones', 'tasks'] "
                        "list in cli/__init__.py"
                    )


# ------------------------------------------------------------------
# Program name and description
# ------------------------------------------------------------------


class TestProgramName:
    """Verify CLI uses db-adapter as program name."""

    def test_prog_is_db_adapter(self):
        """ArgumentParser prog is 'db-adapter'."""
        source = CLI_INIT_PY.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Match argparse.ArgumentParser(...)
                if isinstance(func, ast.Attribute) and func.attr == "ArgumentParser":
                    for kw in node.keywords:
                        if kw.arg == "prog":
                            assert isinstance(kw.value, ast.Constant), (
                                "prog value is not a string constant"
                            )
                            assert kw.value.value == "db-adapter", (
                                f"prog is '{kw.value.value}', expected 'db-adapter'"
                            )
                            return

        pytest.fail("ArgumentParser with prog keyword not found")

    def test_description_is_generic(self):
        """ArgumentParser description does not mention Mission Control."""
        source = CLI_INIT_PY.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "ArgumentParser":
                    for kw in node.keywords:
                        if kw.arg == "description":
                            if isinstance(kw.value, ast.Constant):
                                assert "Mission Control" not in kw.value.value
                            return


# ------------------------------------------------------------------
# Async wrapping
# ------------------------------------------------------------------


class TestAsyncWrapping:
    """Verify cmd_* functions wrap async via asyncio.run()."""

    def test_cmd_connect_calls_asyncio_run(self):
        """cmd_connect wraps _async_connect via asyncio.run()."""
        import inspect
        source = inspect.getsource(cmd_connect)
        assert "asyncio.run" in source, (
            "cmd_connect does not call asyncio.run()"
        )

    def test_cmd_validate_calls_asyncio_run(self):
        """cmd_validate wraps _async_validate via asyncio.run()."""
        import inspect
        source = inspect.getsource(cmd_validate)
        assert "asyncio.run" in source

    def test_cmd_fix_calls_asyncio_run(self):
        """cmd_fix wraps _async_fix via asyncio.run()."""
        import inspect
        source = inspect.getsource(cmd_fix)
        assert "asyncio.run" in source

    def test_cmd_sync_calls_asyncio_run(self):
        """cmd_sync wraps _async_sync via asyncio.run()."""
        import inspect
        source = inspect.getsource(cmd_sync)
        assert "asyncio.run" in source

    def test_cmd_status_delegates_to_async(self):
        """cmd_status wraps _async_status via asyncio.run()."""
        import inspect
        source = inspect.getsource(cmd_status)
        assert "asyncio.run" in source, (
            "cmd_status does not call asyncio.run()"
        )

    def test_cmd_profiles_is_sync(self):
        """cmd_profiles does not call asyncio.run() (reads local files only)."""
        import inspect
        source = inspect.getsource(cmd_profiles)
        assert "asyncio.run" not in source

    def test_async_connect_is_async(self):
        """_async_connect is an async function."""
        from db_adapter.cli import _async_connect
        assert inspect.iscoroutinefunction(_async_connect)

    def test_async_validate_is_async(self):
        """_async_validate is an async function."""
        from db_adapter.cli import _async_validate
        assert inspect.iscoroutinefunction(_async_validate)

    def test_async_fix_is_async(self):
        """_async_fix is an async function."""
        from db_adapter.cli import _async_fix
        assert inspect.iscoroutinefunction(_async_fix)

    def test_async_sync_is_async(self):
        """_async_sync is an async function."""
        from db_adapter.cli import _async_sync
        assert inspect.iscoroutinefunction(_async_sync)

    def test_async_status_is_async(self):
        """_async_status is an async function."""
        assert inspect.iscoroutinefunction(_async_status)


# ------------------------------------------------------------------
# CLI argument structure
# ------------------------------------------------------------------


class TestCLIArguments:
    """Verify CLI argument structure matches spec."""

    def test_env_prefix_global_option(self):
        """--env-prefix is a global option on the main parser."""
        source = CLI_INIT_PY.read_text()
        # Check that --env-prefix is added before subparsers
        assert "--env-prefix" in source

    def test_sync_has_tables_argument(self):
        """sync command has --tables argument."""
        source = CLI_INIT_PY.read_text()
        assert '"--tables"' in source

    def test_sync_has_user_id_argument(self):
        """sync command has --user-id argument."""
        source = CLI_INIT_PY.read_text()
        assert '"--user-id"' in source

    def test_fix_has_schema_file_argument(self):
        """fix command has --schema-file argument."""
        source = CLI_INIT_PY.read_text()
        assert '"--schema-file"' in source

    def test_fix_has_column_defs_argument(self):
        """fix command has --column-defs argument."""
        source = CLI_INIT_PY.read_text()
        assert '"--column-defs"' in source

    def test_parser_creation(self):
        """Parser can be created without error and has expected prog."""
        # We test by calling main with --help-like inspection
        # Use parse_args with a valid command to verify structure
        import argparse

        with patch("sys.argv", ["db-adapter", "--env-prefix", "MC_", "status"]):
            with patch("db_adapter.cli.cmd_status", return_value=0) as mock_status:
                result = main()
                assert result == 0
                # Verify env_prefix was parsed
                call_args = mock_status.call_args[0][0]
                assert call_args.env_prefix == "MC_"

    def test_sync_parser_tables_is_optional(self):
        """sync command does not require --tables (defaults to None,
        falls back to config at runtime)."""
        with patch("sys.argv", ["db-adapter", "sync", "--from", "rds", "--user-id", "abc"]):
            with patch("db_adapter.cli.cmd_sync", return_value=0) as mock_sync:
                result = main()
        assert result == 0
        call_args = mock_sync.call_args[0][0]
        assert call_args.tables is None
        assert call_args.user_id == "abc"

    def test_sync_parser_user_id_is_optional(self):
        """sync command does not require --user-id (defaults to None,
        falls back to config/env at runtime)."""
        with patch("sys.argv", ["db-adapter", "sync", "--from", "rds", "--tables", "t1"]):
            with patch("db_adapter.cli.cmd_sync", return_value=0) as mock_sync:
                result = main()
        assert result == 0
        call_args = mock_sync.call_args[0][0]
        assert call_args.user_id is None
        assert call_args.tables == "t1"

    def test_fix_parser_schema_file_is_optional(self):
        """fix command does not require --schema-file (defaults to None,
        falls back to config at runtime)."""
        with patch("sys.argv", ["db-adapter", "fix", "--column-defs", "d.json"]):
            with patch("db_adapter.cli.cmd_fix", return_value=0) as mock_fix:
                result = main()
        assert result == 0
        call_args = mock_fix.call_args[0][0]
        assert call_args.schema_file is None
        assert call_args.column_defs == "d.json"

    def test_fix_parser_column_defs_is_optional(self):
        """fix command does not require --column-defs (defaults to None,
        falls back to config at runtime)."""
        with patch("sys.argv", ["db-adapter", "fix", "--schema-file", "s.sql"]):
            with patch("db_adapter.cli.cmd_fix", return_value=0) as mock_fix:
                result = main()
        assert result == 0
        call_args = mock_fix.call_args[0][0]
        assert call_args.column_defs is None
        assert call_args.schema_file == "s.sql"


# ------------------------------------------------------------------
# _parse_expected_columns
# ------------------------------------------------------------------


class TestParseExpectedColumns:
    """Tests for the _parse_expected_columns helper."""

    def test_basic_parse(self, tmp_path):
        """Parses a simple CREATE TABLE statement."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                name TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """))

        result = _parse_expected_columns(schema)
        assert "users" in result
        assert result["users"] == {"id", "email", "name", "created_at"}

    def test_multiple_tables(self, tmp_path):
        """Parses multiple CREATE TABLE statements."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL
            );

            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                project_id TEXT REFERENCES projects(id)
            );
        """))

        result = _parse_expected_columns(schema)
        assert len(result) == 2
        assert result["projects"] == {"id", "name", "slug"}
        assert result["tasks"] == {"id", "title", "project_id"}

    def test_if_not_exists(self, tmp_path):
        """Handles CREATE TABLE IF NOT EXISTS."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL
            );
        """))

        result = _parse_expected_columns(schema)
        assert "users" in result
        assert result["users"] == {"id", "email"}

    def test_skips_constraints(self, tmp_path):
        """Skips constraint lines (PRIMARY KEY, FOREIGN KEY, UNIQUE, etc.)."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE orders (
                id TEXT,
                user_id TEXT,
                total NUMERIC,
                PRIMARY KEY (id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE (user_id, id)
            );
        """))

        result = _parse_expected_columns(schema)
        assert result["orders"] == {"id", "user_id", "total"}

    def test_file_not_found(self, tmp_path):
        """Raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            _parse_expected_columns(tmp_path / "nonexistent.sql")

    def test_uppercase_identifiers(self, tmp_path):
        """Uppercase table and column names are returned as lowercase."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE ITEMS (
                A TEXT PRIMARY KEY,
                B TEXT NOT NULL
            );
        """))

        result = _parse_expected_columns(schema)
        assert "items" in result
        assert result["items"] == {"a", "b"}

    def test_mixed_case_identifiers(self, tmp_path):
        """Mixed-case table and column names are returned as lowercase."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE Items (
                Id TEXT PRIMARY KEY,
                NAME TEXT NOT NULL,
                createdAt TIMESTAMP DEFAULT NOW()
            );
        """))

        result = _parse_expected_columns(schema)
        assert "items" in result
        assert result["items"] == {"id", "name", "createdat"}

    def test_no_create_table(self, tmp_path):
        """Raises ValueError when no CREATE TABLE found."""
        schema = tmp_path / "empty.sql"
        schema.write_text("-- just a comment\nSELECT 1;\n")

        with pytest.raises(ValueError, match="No CREATE TABLE"):
            _parse_expected_columns(schema)


class TestParseExpectedColumnsSqlparseEdgeCases:
    """Edge-case tests for sqlparse-based _parse_expected_columns."""

    def test_schema_qualified_table_name(self, tmp_path):
        """Handles CREATE TABLE public.users (schema-qualified)."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE public.users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL
            );
        """))
        result = _parse_expected_columns(schema)
        assert "users" in result
        assert result["users"] == {"id", "email"}

    def test_quoted_identifier_table_name(self, tmp_path):
        """Handles CREATE TABLE "Items" (quoted identifier)."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE "Items" (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
        """))
        result = _parse_expected_columns(schema)
        assert "items" in result
        assert result["items"] == {"id", "name"}

    def test_commented_out_create_table_ignored(self, tmp_path):
        """Ignores -- CREATE TABLE fake (...) line comments."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            -- CREATE TABLE fake (x TEXT);
            CREATE TABLE real_table (
                id TEXT PRIMARY KEY,
                name TEXT
            );
        """))
        result = _parse_expected_columns(schema)
        assert "fake" not in result
        assert "real_table" in result
        assert result["real_table"] == {"id", "name"}

    def test_block_comment_in_body_stripped(self, tmp_path):
        """Strips /* block comments */ inside column body."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                /* this is a block comment */
                email TEXT NOT NULL
            );
        """))
        result = _parse_expected_columns(schema)
        assert result["users"] == {"id", "email"}

    def test_ignores_create_index(self, tmp_path):
        """Does not confuse CREATE INDEX with CREATE TABLE."""
        schema = tmp_path / "schema.sql"
        schema.write_text(textwrap.dedent("""\
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL
            );
            CREATE INDEX idx_users_email ON users (email);
        """))
        result = _parse_expected_columns(schema)
        assert len(result) == 1
        assert "users" in result


# ------------------------------------------------------------------
# _get_table_row_counts
# ------------------------------------------------------------------


class TestGetTableRowCounts:
    """Tests for the _get_table_row_counts async helper."""

    async def test_successful_row_count_retrieval(self):
        """Returns dict with table names and counts when DB is reachable."""
        from db_adapter.cli import _get_table_row_counts

        # Mock cursor that returns table names, then counts
        mock_cursor = AsyncMock()

        # First call: information_schema query returns table names
        # Subsequent calls: COUNT(*) for each table
        mock_cursor.fetchall = AsyncMock(
            return_value=[("users",), ("orders",), ("items",)]
        )
        mock_cursor.fetchone = AsyncMock(side_effect=[(10,), (25,), (42,)])

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cursor),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch(
            "db_adapter.cli._helpers.AsyncConnection.connect",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            result = await _get_table_row_counts("postgresql://localhost/test")

        assert result == {"items": 42, "orders": 25, "users": 10}

    async def test_result_sorted_alphabetically(self):
        """Returned dict has keys sorted alphabetically."""
        from db_adapter.cli import _get_table_row_counts

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[("zebra",), ("alpha",), ("middle",)]
        )
        mock_cursor.fetchone = AsyncMock(side_effect=[(1,), (2,), (3,)])

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cursor),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch(
            "db_adapter.cli._helpers.AsyncConnection.connect",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            result = await _get_table_row_counts("postgresql://localhost/test")

        assert list(result.keys()) == ["alpha", "middle", "zebra"]

    async def test_connection_failure_returns_empty_dict(self):
        """Returns empty dict when connection fails."""
        from db_adapter.cli import _get_table_row_counts

        with patch(
            "db_adapter.cli._helpers.AsyncConnection.connect",
            side_effect=ConnectionError("connection refused"),
        ):
            result = await _get_table_row_counts("postgresql://bad-host/test")

        assert result == {}

    async def test_query_error_returns_empty_dict(self):
        """Returns empty dict when a query raises an exception."""
        from db_adapter.cli import _get_table_row_counts

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(side_effect=Exception("query failed"))

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cursor),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch(
            "db_adapter.cli._helpers.AsyncConnection.connect",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            result = await _get_table_row_counts("postgresql://localhost/test")

        assert result == {}

    async def test_excludes_system_tables(self):
        """System tables (schema_migrations, pg_stat_statements, spatial_ref_sys) are excluded."""
        from db_adapter.cli import _get_table_row_counts, _EXCLUDED_TABLES

        # Verify the constant has the expected tables
        assert _EXCLUDED_TABLES == {
            "schema_migrations",
            "pg_stat_statements",
            "spatial_ref_sys",
        }

        # Mock DB returning system tables mixed with real tables
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                ("users",),
                ("schema_migrations",),
                ("pg_stat_statements",),
                ("spatial_ref_sys",),
                ("orders",),
            ]
        )
        mock_cursor.fetchone = AsyncMock(side_effect=[(5,), (100,)])

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cursor),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch(
            "db_adapter.cli._helpers.AsyncConnection.connect",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            result = await _get_table_row_counts("postgresql://localhost/test")

        # Only real tables should be in the result
        assert "schema_migrations" not in result
        assert "pg_stat_statements" not in result
        assert "spatial_ref_sys" not in result
        assert "users" in result
        assert "orders" in result

    async def test_empty_database_returns_empty_dict(self):
        """Returns empty dict when database has no tables."""
        from db_adapter.cli import _get_table_row_counts

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_cursor),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch(
            "db_adapter.cli._helpers.AsyncConnection.connect",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            result = await _get_table_row_counts("postgresql://localhost/test")

        assert result == {}

    def test_get_table_row_counts_is_async(self):
        """_get_table_row_counts is an async coroutine function."""
        from db_adapter.cli import _get_table_row_counts
        import inspect
        assert inspect.iscoroutinefunction(_get_table_row_counts)

    def test_uses_sql_identifier_not_fstrings(self):
        """_get_table_row_counts uses psycopg.sql.Identifier for table quoting."""
        import inspect
        from db_adapter.cli import _get_table_row_counts
        source = inspect.getsource(_get_table_row_counts)
        assert "Identifier(" in source
        assert "SQL(" in source


# ------------------------------------------------------------------
# _print_table_counts display helper
# ------------------------------------------------------------------


class TestPrintTableCounts:
    """Tests for the _print_table_counts display helper."""

    def test_empty_dict_produces_no_output(self):
        """Empty counts dict produces no console output."""
        from io import StringIO

        from rich.console import Console

        buffer = StringIO()
        test_console = Console(file=buffer, width=80)

        with patch("db_adapter.cli._helpers.console", test_console):
            _print_table_counts({})

        output = buffer.getvalue()
        assert output == ""

    def test_populated_dict_renders_table(self):
        """Populated counts dict renders a Rich table with correct content."""
        from io import StringIO

        from rich.console import Console

        buffer = StringIO()
        test_console = Console(file=buffer, width=80)

        with patch("db_adapter.cli._helpers.console", test_console):
            _print_table_counts({"users": 3, "orders": 15})

        output = buffer.getvalue()
        assert "Table Data" in output
        assert "users" in output
        assert "orders" in output
        assert "3" in output
        assert "15" in output

    def test_rows_sorted_alphabetically(self):
        """Table rows are sorted alphabetically by table name."""
        from io import StringIO

        from rich.console import Console

        buffer = StringIO()
        test_console = Console(file=buffer, width=80)

        with patch("db_adapter.cli._helpers.console", test_console):
            _print_table_counts({"zebra": 1, "alpha": 2, "middle": 3})

        output = buffer.getvalue()
        alpha_pos = output.index("alpha")
        middle_pos = output.index("middle")
        zebra_pos = output.index("zebra")
        assert alpha_pos < middle_pos < zebra_pos

    def test_rows_column_right_justified(self):
        """Rows column uses right justification."""
        source = inspect.getsource(_print_table_counts)
        assert 'justify="right"' in source

    def test_comma_formatting_for_large_numbers(self):
        """Large row counts include comma formatting."""
        from io import StringIO

        from rich.console import Console

        buffer = StringIO()
        test_console = Console(file=buffer, width=80)

        with patch("db_adapter.cli._helpers.console", test_console):
            _print_table_counts({"big_table": 1_500_000})

        output = buffer.getvalue()
        assert "1,500,000" in output

    def test_table_title_is_table_data(self):
        """Table title is 'Table Data'."""
        source = inspect.getsource(_print_table_counts)
        assert 'title="Table Data"' in source


# ------------------------------------------------------------------
# _async_connect config-driven validation
# ------------------------------------------------------------------


class TestAsyncConnectConfigDriven:
    """Tests for config-driven schema validation in _async_connect()."""

    def _make_connection_result(
        self,
        *,
        success: bool = True,
        profile_name: str = "dev",
        schema_valid: bool | None = None,
        schema_report: object | None = None,
        error: str | None = None,
    ) -> MagicMock:
        """Create a mock ConnectionResult with the given fields."""
        result = MagicMock()
        result.success = success
        result.profile_name = profile_name
        result.schema_valid = schema_valid
        result.schema_report = schema_report
        result.error = error
        return result

    def test_validate_on_connect_true_with_schema_file(self, tmp_path):
        """Config with validate_on_connect=True and valid schema file
        calls connect_and_validate with expected_columns."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.validate_on_connect = True
        mock_config.schema_file = str(schema)

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=True,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        # Verify expected_columns was passed
        call_kwargs = mock_connect.call_args[1]
        assert "expected_columns" in call_kwargs
        assert call_kwargs["expected_columns"] == {"users": {"id", "email"}}

    def test_validate_on_connect_false(self):
        """Config with validate_on_connect=False calls connect_and_validate
        without expected_columns."""
        mock_config = MagicMock()
        mock_config.validate_on_connect = False

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=None,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        # Verify expected_columns was NOT passed (is None)
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["expected_columns"] is None

    def test_missing_db_toml_still_connects(self):
        """Missing db.toml (FileNotFoundError from load_db_config) still
        connects successfully in connect-only mode."""
        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=None,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        # Verify expected_columns was NOT passed (is None)
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["expected_columns"] is None

    def test_missing_schema_file_still_connects(self, tmp_path):
        """Missing schema file (FileNotFoundError from _parse_expected_columns)
        still connects, with validation skipped."""
        mock_config = MagicMock()
        mock_config.validate_on_connect = True
        mock_config.schema_file = str(tmp_path / "nonexistent.sql")

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=None,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["expected_columns"] is None

    def test_schema_validation_passed_message(self, tmp_path, capsys):
        """'Schema validation: PASSED' only prints when validation actually
        occurred and passed (schema_valid is True)."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.validate_on_connect = True
        mock_config.schema_file = str(schema)

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=True,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        # Find the call that contains "PASSED"
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("PASSED" in s for s in printed), (
            "Expected 'PASSED' in output when schema_valid is True"
        )

    def test_no_passed_message_when_validation_skipped(self):
        """'Schema validation: PASSED' does NOT print when validation was
        skipped (schema_valid is None)."""
        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=None,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert not any("PASSED" in s for s in printed), (
            "'PASSED' should not appear when validation was skipped"
        )

    def test_connection_failure_returns_1(self):
        """Connection failure (result.success is False) returns 1."""
        mock_result = self._make_connection_result(
            success=False,
            error="Connection refused",
            schema_report=None,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("no config"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 1

    def test_schema_drift_returns_1_with_report(self):
        """Schema drift (success=False with schema_report) returns 1 and
        displays the schema report."""
        mock_report = MagicMock()
        mock_report.format_report.return_value = "Missing: users.email"

        mock_result = self._make_connection_result(
            success=False,
            profile_name="dev",
            schema_valid=False,
            schema_report=mock_report,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("no config"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 1
        mock_report.format_report.assert_called_once()

    def test_malformed_config_still_connects(self):
        """Malformed db.toml (ValidationError from Pydantic) still connects
        in connect-only mode."""
        from pydantic import ValidationError

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=None,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=Exception("Validation error"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["expected_columns"] is None

    def test_profile_switch_notice(self):
        """Profile switch notice shows when previous profile differs."""
        mock_result = self._make_connection_result(
            success=True,
            profile_name="production",
            schema_valid=None,
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("no config"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Switched from" in s for s in printed)


# ------------------------------------------------------------------
# Connect row counts integration
# ------------------------------------------------------------------


class TestConnectRowCountsIntegration:
    """Tests for row counts integration in _async_connect()."""

    def _make_connection_result(
        self,
        *,
        success: bool = True,
        profile_name: str = "dev",
        schema_valid: bool | None = None,
        schema_report: object | None = None,
        error: str | None = None,
    ) -> MagicMock:
        """Create a mock ConnectionResult with the given fields."""
        result = MagicMock()
        result.success = success
        result.profile_name = profile_name
        result.schema_valid = schema_valid
        result.schema_report = schema_report
        result.error = error
        return result

    def _make_config_with_profile(
        self, profile_name: str = "dev"
    ) -> MagicMock:
        """Create a mock config with a real profiles dict containing the given profile."""
        mock_profile = MagicMock()
        mock_config = MagicMock()
        mock_config.profiles = {profile_name: mock_profile}
        mock_config.validate_on_connect = False
        return mock_config

    def test_successful_connect_calls_get_table_row_counts(self):
        """Successful connect with config calls _get_table_row_counts with resolved URL."""
        mock_config = self._make_config_with_profile("dev")
        mock_result = self._make_connection_result(
            success=True, profile_name="dev", schema_valid=None
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "db_adapter.cli._connection.resolve_url",
                return_value="postgresql://localhost/testdb",
            ) as mock_resolve,
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
                return_value={"items": 50, "users": 10},
            ) as mock_counts,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        mock_resolve.assert_called_once_with(mock_config.profiles["dev"])
        mock_counts.assert_called_once_with("postgresql://localhost/testdb")

    def test_successful_connect_displays_row_counts(self):
        """Successful connect displays Table Data when counts are non-empty."""
        mock_config = self._make_config_with_profile("dev")
        mock_result = self._make_connection_result(
            success=True, profile_name="dev", schema_valid=None
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "db_adapter.cli._connection.resolve_url",
                return_value="postgresql://localhost/testdb",
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
                return_value={"items": 50, "users": 10},
            ),
            patch("db_adapter.cli._connection._print_table_counts") as mock_print_counts,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        mock_print_counts.assert_called_once_with({"items": 50, "users": 10})

    def test_successful_connect_empty_counts_skips_display(self):
        """Successful connect with empty counts does not call _print_table_counts."""
        mock_config = self._make_config_with_profile("dev")
        mock_result = self._make_connection_result(
            success=True, profile_name="dev", schema_valid=None
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "db_adapter.cli._connection.resolve_url",
                return_value="postgresql://localhost/testdb",
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("db_adapter.cli._connection._print_table_counts") as mock_print_counts,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        mock_print_counts.assert_not_called()

    def test_failed_connect_does_not_attempt_row_counts(self):
        """Failed connect (result.success=False) does not call _get_table_row_counts."""
        mock_config = self._make_config_with_profile("dev")
        mock_result = self._make_connection_result(
            success=False, error="Connection refused"
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
            ) as mock_counts,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 1
        mock_counts.assert_not_called()

    def test_connect_with_no_config_skips_row_counts(self):
        """Connect with config=None (FileNotFoundError) does not attempt row counts."""
        mock_result = self._make_connection_result(
            success=True, profile_name="dev", schema_valid=None
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
            ) as mock_counts,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        mock_counts.assert_not_called()

    def test_connect_with_profile_not_in_config_skips_row_counts(self):
        """Connect where profile_name is not in config.profiles skips row counts."""
        mock_config = self._make_config_with_profile("production")
        mock_result = self._make_connection_result(
            success=True, profile_name="dev", schema_valid=None
        )

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
            ) as mock_counts,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        mock_counts.assert_not_called()


# ------------------------------------------------------------------
# Status row counts integration
# ------------------------------------------------------------------


class TestStatusRowCountsIntegration:
    """Tests for row counts integration in _async_status()."""

    def _make_config_with_profile(
        self, profile_name: str = "dev"
    ) -> MagicMock:
        """Create a mock config with a real profiles dict containing the given profile."""
        mock_profile = MagicMock()
        mock_profile.provider = "postgres"
        mock_profile.description = "Test database"
        mock_config = MagicMock()
        mock_config.profiles = {profile_name: mock_profile}
        return mock_config

    def test_status_with_reachable_db_shows_row_counts(self):
        """Status with valid profile and reachable DB calls _get_table_row_counts and _print_table_counts."""
        mock_config = self._make_config_with_profile("dev")

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._connection.resolve_url",
                return_value="postgresql://localhost/testdb",
            ) as mock_resolve,
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
                return_value={"items": 50, "users": 10},
            ) as mock_counts,
            patch("db_adapter.cli._connection._print_table_counts") as mock_print_counts,
        ):
            rc = asyncio.run(_async_status(args))

        assert rc == 0
        mock_resolve.assert_called_once_with(mock_config.profiles["dev"])
        mock_counts.assert_called_once_with("postgresql://localhost/testdb")
        mock_print_counts.assert_called_once_with({"items": 50, "users": 10})

    def test_status_with_unreachable_db_returns_zero(self):
        """Status with unreachable DB (empty counts) returns 0 without error."""
        mock_config = self._make_config_with_profile("dev")

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._connection.resolve_url",
                return_value="postgresql://localhost/testdb",
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("db_adapter.cli._connection._print_table_counts") as mock_print_counts,
        ):
            rc = asyncio.run(_async_status(args))

        assert rc == 0
        mock_print_counts.assert_not_called()

    def test_status_with_no_profile_returns_zero(self):
        """Status with no validated profile returns 0 and does not attempt row counts."""
        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
            ) as mock_counts,
        ):
            rc = asyncio.run(_async_status(args))

        assert rc == 0
        mock_counts.assert_not_called()

    def test_status_with_no_config_returns_zero(self):
        """Status with FileNotFoundError for db.toml returns 0 and skips row counts."""
        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
            ) as mock_counts,
        ):
            rc = asyncio.run(_async_status(args))

        assert rc == 0
        mock_counts.assert_not_called()

    def test_status_with_profile_not_in_config_skips_row_counts(self):
        """Status where profile is not in config.profiles skips row counts."""
        mock_config = self._make_config_with_profile("production")

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
            ) as mock_counts,
        ):
            rc = asyncio.run(_async_status(args))

        assert rc == 0
        mock_counts.assert_not_called()

    def test_status_empty_counts_skips_print(self):
        """Status with DB returning empty counts does not call _print_table_counts."""
        mock_config = self._make_config_with_profile("dev")

        args = argparse.Namespace(env_prefix="")

        with (
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._connection.resolve_url",
                return_value="postgresql://localhost/testdb",
            ),
            patch(
                "db_adapter.cli._connection._get_table_row_counts",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("db_adapter.cli._connection._print_table_counts") as mock_print_counts,
        ):
            rc = asyncio.run(_async_status(args))

        assert rc == 0
        mock_print_counts.assert_not_called()


# ------------------------------------------------------------------
# _async_validate config-driven validation
# ------------------------------------------------------------------


class TestAsyncValidateConfigDriven:
    """Tests for config-driven schema validation in _async_validate()."""

    def _make_connection_result(
        self,
        *,
        success: bool = True,
        profile_name: str = "dev",
        schema_valid: bool | None = None,
        schema_report: object | None = None,
        error: str | None = None,
    ) -> MagicMock:
        """Create a mock ConnectionResult with the given fields."""
        result = MagicMock()
        result.success = success
        result.profile_name = profile_name
        result.schema_valid = schema_valid
        result.schema_report = schema_report
        result.error = error
        return result

    def test_validate_with_config_schema_file(self, tmp_path):
        """validate with config schema file calls connect_and_validate
        with expected_columns and validate_only=True."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=True,
        )

        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 0
        call_kwargs = mock_connect.call_args[1]
        assert "expected_columns" in call_kwargs
        assert call_kwargs["expected_columns"] == {"users": {"id", "email"}}
        assert call_kwargs["validate_only"] is True

    def test_validate_schema_file_override(self, tmp_path):
        """validate --schema-file override.sql uses the CLI-provided file
        instead of config."""
        override_schema = tmp_path / "override.sql"
        override_schema.write_text(
            "CREATE TABLE orders (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    total NUMERIC NOT NULL\n"
            ");\n"
        )

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=True,
        )

        args = argparse.Namespace(
            env_prefix="", schema_file=str(override_schema)
        )

        with (
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch("db_adapter.cli._connection.load_db_config") as mock_load_config,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 0
        # load_db_config should NOT be called when --schema-file is provided
        mock_load_config.assert_not_called()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["expected_columns"] == {"orders": {"id", "total"}}
        assert call_kwargs["validate_only"] is True

    def test_validate_no_schema_source_returns_1(self):
        """validate with no schema source (no --schema-file, no config)
        returns 1 with informative error."""
        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch(
                "db_adapter.cli._connection.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No schema file available" in s for s in printed)

    def test_validate_config_schema_file_missing_returns_1(self, tmp_path):
        """validate when config provides a schema file path that does not
        exist returns 1 with error referencing the missing file."""
        mock_config = MagicMock()
        mock_config.schema_file = str(tmp_path / "nonexistent.sql")

        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("nonexistent.sql" in s for s in printed)

    def test_validate_no_profile_returns_1(self):
        """validate with no validated profile returns 1."""
        args = argparse.Namespace(env_prefix="", schema_file=None)

        with patch("db_adapter.cli._connection.read_profile_lock", return_value=None):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1

    def test_validate_connection_failure_returns_1(self, tmp_path):
        """validate when connection fails returns 1 with error message."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)

        mock_result = self._make_connection_result(
            success=False,
            error="Connection refused",
            schema_report=None,
        )

        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Connection refused" in s for s in printed)

    def test_validate_schema_drift_returns_1_with_report(self, tmp_path):
        """validate when schema has drifted (success=False with schema_report)
        returns 1 and displays the schema report."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)

        mock_report = MagicMock()
        mock_report.format_report.return_value = "Missing: users.email"

        mock_result = self._make_connection_result(
            success=False,
            profile_name="dev",
            schema_valid=False,
            schema_report=mock_report,
        )

        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        mock_report.format_report.assert_called_once()

    def test_validate_schema_valid_false_returns_1(self, tmp_path):
        """validate when result.success is True but schema_valid is False
        returns 1 and shows drift report."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)

        mock_report = MagicMock()
        mock_report.format_report.return_value = "Missing: users.email"

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=False,
            schema_report=mock_report,
        )

        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("drifted" in s for s in printed)

    def test_validate_schema_valid_none_returns_1(self, tmp_path):
        """validate when result.schema_valid is None (defensive case)
        returns 1 with informational message."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)

        mock_result = self._make_connection_result(
            success=True,
            profile_name="dev",
            schema_valid=None,
        )

        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._connection.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("could not be performed" in s for s in printed)

    def test_validate_config_with_none_schema_file(self):
        """validate when config loads but schema_file is None (not configured)
        returns 1 with 'No schema file available' error."""
        mock_config = MagicMock()
        mock_config.schema_file = None

        args = argparse.Namespace(env_prefix="", schema_file=None)

        with (
            patch("db_adapter.cli._connection.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._connection.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli._connection.console") as mock_console,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No schema file available" in s for s in printed)


# ------------------------------------------------------------------
# _async_sync .errors attribute fix
# ------------------------------------------------------------------


class TestAsyncSyncErrors:
    """Tests for _async_sync() using .errors list instead of .error string."""

    def test_sync_compare_failure_uses_errors_list(self):
        """_async_sync() accesses result.errors (list) not result.error
        when compare_profiles returns a failure."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.errors = ["Connection to source failed", "Timeout"]

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables="users,orders",
            user_id="abc",
            dry_run=False,
            confirm=True,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        # Should show all errors joined with "; "
        assert any("Connection to source failed; Timeout" in s for s in printed)

    def test_sync_data_failure_uses_errors_list(self):
        """_async_sync() accesses sync_result.errors (list) not .error
        when sync_data returns a failure."""
        # compare_profiles succeeds
        compare_result = MagicMock()
        compare_result.success = True
        compare_result.source_counts = {"users": 10}
        compare_result.dest_counts = {"users": 5}
        compare_result.sync_plan = {"users": {"new": 5, "update": 0}}

        # sync_data fails
        sync_result = MagicMock()
        sync_result.success = False
        sync_result.errors = ["Insert failed on users.id=3", "FK constraint"]

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables="users",
            user_id="abc",
            dry_run=False,
            confirm=True,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch(
                "db_adapter.cli._data_sync.sync_data",
                new_callable=AsyncMock,
                return_value=sync_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any(
            "Insert failed on users.id=3; FK constraint" in s for s in printed
        )

    def test_sync_compare_failure_empty_errors_shows_unknown(self):
        """_async_sync() shows 'Unknown error' when errors list is empty."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.errors = []

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables="users",
            user_id="abc",
            dry_run=False,
            confirm=True,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Unknown error" in s for s in printed)

    def test_sync_source_code_has_no_dot_error(self):
        """_async_sync() source code has no reference to .error attribute
        (only .errors list)."""
        import inspect

        source = inspect.getsource(_async_sync)
        # Should not find .error (but .errors is OK)
        # Use a regex to match .error NOT followed by 's'
        import re

        matches = re.findall(r"\.error\b(?!s)", source)
        assert len(matches) == 0, (
            f"Found {len(matches)} reference(s) to .error in _async_sync() "
            f"(should be .errors)"
        )


# ------------------------------------------------------------------
# _async_fix config fallback for --schema-file
# ------------------------------------------------------------------


class TestAsyncFixConfigFallback:
    """Tests for _async_fix() config fallback when --schema-file is omitted."""

    def test_fix_uses_config_schema_file_when_flag_omitted(self, tmp_path):
        """fix without --schema-file falls back to config.schema_file."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )
        col_defs = tmp_path / "defs.json"
        col_defs.write_text('{"users.email": "TEXT NOT NULL"}')

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)

        mock_result = MagicMock()
        mock_result.schema_valid = True

        args = argparse.Namespace(
            env_prefix="",
            schema_file=None,
            column_defs=str(col_defs),
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli._schema_fix.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        # Verify expected_columns was derived from config schema file
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["expected_columns"] == {"users": {"id", "email"}}

    def test_fix_uses_explicit_schema_file_over_config(self, tmp_path):
        """fix --schema-file explicit.sql uses the provided file,
        not config's schema_file."""
        schema = tmp_path / "explicit.sql"
        schema.write_text(
            "CREATE TABLE orders (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    total NUMERIC NOT NULL\n"
            ");\n"
        )
        col_defs = tmp_path / "defs.json"
        col_defs.write_text('{"orders.total": "NUMERIC NOT NULL"}')

        mock_config = MagicMock()
        mock_config.schema_file = str(tmp_path / "config_schema.sql")
        mock_config.column_defs = None

        mock_result = MagicMock()
        mock_result.schema_valid = True

        args = argparse.Namespace(
            env_prefix="",
            schema_file=str(schema),
            column_defs=str(col_defs),
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch("db_adapter.cli._schema_fix.load_db_config", return_value=mock_config),
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        # CLI --schema-file takes precedence over config.schema_file
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["expected_columns"] == {"orders": {"id", "total"}}

    def test_fix_no_schema_source_returns_1(self):
        """fix with no --schema-file and no config returns 1 with error."""
        args = argparse.Namespace(
            env_prefix="",
            schema_file=None,
            column_defs="defs.json",
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli._schema_fix.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No schema file available" in s for s in printed)

    def test_fix_config_with_none_schema_file_returns_1(self):
        """fix when config loads but schema_file is None returns 1."""
        mock_config = MagicMock()
        mock_config.schema_file = None

        args = argparse.Namespace(
            env_prefix="",
            schema_file=None,
            column_defs="defs.json",
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli._schema_fix.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._schema_fix.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No schema file available" in s for s in printed)


# ------------------------------------------------------------------
# _async_fix() column_defs config fallback
# ------------------------------------------------------------------


class TestAsyncFixColumnDefsResolution:
    """Tests for _async_fix() column_defs resolution: CLI -> config -> error."""

    def test_fix_column_defs_from_config(self, tmp_path):
        """fix without --column-defs resolves column_defs from config."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )
        col_defs = tmp_path / "config-defs.json"
        col_defs.write_text('{"users.email": "TEXT NOT NULL"}')

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)
        mock_config.column_defs = str(col_defs)

        mock_result = MagicMock()
        mock_result.schema_valid = True

        args = argparse.Namespace(
            env_prefix="",
            schema_file=None,
            column_defs=None,
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli._schema_fix.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0

    def test_fix_cli_column_defs_overrides_config(self, tmp_path):
        """fix --column-defs cli.json uses CLI value over config."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )
        cli_defs = tmp_path / "cli-defs.json"
        cli_defs.write_text('{"users.email": "TEXT NOT NULL"}')
        config_defs = tmp_path / "config-defs.json"
        config_defs.write_text('{"users.email": "TEXT"}')

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)
        mock_config.column_defs = str(config_defs)

        mock_result = MagicMock()
        mock_result.schema_valid = True

        args = argparse.Namespace(
            env_prefix="",
            schema_file=None,
            column_defs=str(cli_defs),
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli._schema_fix.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            rc = asyncio.run(_async_fix(args))

        # CLI --column-defs should be used (cli-defs.json), not config-defs.json
        assert rc == 0

    def test_fix_no_column_defs_source_returns_1(self):
        """fix with no --column-defs and no config.column_defs returns 1."""
        args = argparse.Namespace(
            env_prefix="",
            schema_file=None,
            column_defs=None,
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli._schema_fix.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        # Should fail on schema file first since both are missing
        assert any("No schema file available" in s for s in printed)

    def test_fix_schema_from_cli_column_defs_from_config(self, tmp_path):
        """fix --schema-file provided but --column-defs omitted loads
        config for column_defs fallback."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )
        col_defs = tmp_path / "config-defs.json"
        col_defs.write_text('{"users.email": "TEXT NOT NULL"}')

        mock_config = MagicMock()
        mock_config.schema_file = None
        mock_config.column_defs = str(col_defs)

        mock_result = MagicMock()
        mock_result.schema_valid = True

        args = argparse.Namespace(
            env_prefix="",
            schema_file=str(schema),
            column_defs=None,
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli._schema_fix.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0

    def test_fix_config_has_none_column_defs_returns_1(self, tmp_path):
        """fix when config loads but column_defs is None returns 1 with
        clear error message."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )

        mock_config = MagicMock()
        mock_config.schema_file = str(schema)
        mock_config.column_defs = None

        args = argparse.Namespace(
            env_prefix="",
            schema_file=None,
            column_defs=None,
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli._schema_fix.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._schema_fix.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No column definitions available" in s for s in printed)


# ------------------------------------------------------------------
# _async_fix() auto-backup before applying fixes
# ------------------------------------------------------------------


class TestAsyncFixAutoBackup:
    """Tests for auto-backup logic in _async_fix() when --confirm is used."""

    def _make_fix_args(
        self, tmp_path, confirm=True, no_backup=False, column_defs=None
    ):
        """Create args and mock setup for fix --confirm tests."""
        schema = tmp_path / "schema.sql"
        schema.write_text(
            "CREATE TABLE users (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");\n"
        )
        col_defs = tmp_path / "defs.json"
        col_defs.write_text('{"users.email": "TEXT NOT NULL"}')

        args = argparse.Namespace(
            env_prefix="",
            schema_file=str(schema),
            column_defs=column_defs or str(col_defs),
            confirm=confirm,
            no_backup=no_backup,
        )
        return args

    def _make_fix_mocks(self, *, backup_schema_path=None, user_id=None):
        """Create standard mocks for fix with schema drift detected."""
        mock_config = MagicMock()
        mock_config.schema_file = None
        mock_config.column_defs = None
        mock_config.backup_schema = backup_schema_path
        mock_config.user_id_env = None

        # connect_and_validate returns drift
        mock_connect_result = MagicMock()
        mock_connect_result.schema_valid = False
        mock_connect_result.schema_report = MagicMock()
        mock_connect_result.schema_report.extra_tables = []

        # generate_fix_plan returns a plan with fixes
        mock_plan = MagicMock()
        mock_plan.has_fixes = True
        mock_plan.error = None
        mock_plan.missing_tables = []
        mock_plan.tables_to_recreate = []
        mock_plan.missing_columns = [
            MagicMock(table="users", column="email", definition="TEXT NOT NULL")
        ]
        mock_plan.create_order = []
        mock_plan.drop_order = []

        # apply_fixes returns success
        mock_fix_result = MagicMock()
        mock_fix_result.success = True
        mock_fix_result.tables_created = 0
        mock_fix_result.tables_recreated = 0
        mock_fix_result.columns_added = 1

        mock_adapter = AsyncMock()

        return {
            "config": mock_config,
            "connect_result": mock_connect_result,
            "plan": mock_plan,
            "fix_result": mock_fix_result,
            "adapter": mock_adapter,
        }

    def test_fix_confirm_with_backup_schema_calls_backup_database(
        self, tmp_path, monkeypatch
    ):
        """fix --confirm with backup_schema configured calls
        backup_database() before apply_fixes()."""
        bs_file = tmp_path / "bs.json"
        bs_file.write_text('{"tables": [{"name": "users"}]}')

        args = self._make_fix_args(tmp_path, confirm=True, no_backup=False)
        mocks = self._make_fix_mocks(
            backup_schema_path=str(bs_file), user_id=None
        )
        mocks["config"].user_id_env = "TEST_UID"

        call_order = []

        async def track_backup(*a, **kw):
            call_order.append("backup_database")
            return str(tmp_path / "backup.json")

        async def track_apply(*a, **kw):
            call_order.append("apply_fixes")
            return mocks["fix_result"]

        # Use tmp_path as CWD so backups/ dir is created there
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                return_value=mocks["config"],
            ),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mocks["connect_result"],
            ),
            patch(
                "db_adapter.schema.fix.generate_fix_plan",
                return_value=mocks["plan"],
            ),
            patch("db_adapter.schema.fix.apply_fixes", side_effect=track_apply),
            patch(
                "db_adapter.cli._schema_fix.get_adapter",
                new_callable=AsyncMock,
                return_value=mocks["adapter"],
            ),
            patch(
                "db_adapter.cli._schema_fix.backup_database", side_effect=track_backup
            ),
            patch.dict("os.environ", {"TEST_UID": "user-123"}),
            patch("db_adapter.cli._schema_fix.console"),
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        assert call_order == ["backup_database", "apply_fixes"]

    def test_fix_confirm_no_backup_flag_skips_backup(self, tmp_path):
        """fix --confirm --no-backup does not call backup_database()."""
        bs_file = tmp_path / "bs.json"
        bs_file.write_text('{"tables": [{"name": "users"}]}')

        args = self._make_fix_args(tmp_path, confirm=True, no_backup=True)
        mocks = self._make_fix_mocks(backup_schema_path=str(bs_file))

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                return_value=mocks["config"],
            ),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mocks["connect_result"],
            ),
            patch(
                "db_adapter.schema.fix.generate_fix_plan",
                return_value=mocks["plan"],
            ),
            patch(
                "db_adapter.schema.fix.apply_fixes",
                new_callable=AsyncMock,
                return_value=mocks["fix_result"],
            ),
            patch(
                "db_adapter.cli._schema_fix.get_adapter",
                new_callable=AsyncMock,
                return_value=mocks["adapter"],
            ),
            patch(
                "db_adapter.cli._schema_fix.backup_database",
                new_callable=AsyncMock,
            ) as mock_backup,
            patch("db_adapter.cli._schema_fix.console"),
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        mock_backup.assert_not_called()

    def test_fix_confirm_without_backup_schema_warns_and_continues(
        self, tmp_path
    ):
        """fix --confirm without backup_schema warns and continues
        to apply fixes."""
        args = self._make_fix_args(tmp_path, confirm=True, no_backup=False)
        mocks = self._make_fix_mocks(backup_schema_path=None)

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                return_value=mocks["config"],
            ),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mocks["connect_result"],
            ),
            patch(
                "db_adapter.schema.fix.generate_fix_plan",
                return_value=mocks["plan"],
            ),
            patch(
                "db_adapter.schema.fix.apply_fixes",
                new_callable=AsyncMock,
                return_value=mocks["fix_result"],
            ),
            patch(
                "db_adapter.cli._schema_fix.get_adapter",
                new_callable=AsyncMock,
                return_value=mocks["adapter"],
            ),
            patch(
                "db_adapter.cli._schema_fix.backup_database",
                new_callable=AsyncMock,
            ) as mock_backup,
            patch("db_adapter.cli._schema_fix.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        mock_backup.assert_not_called()
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No backup_schema configured" in s for s in printed)

    def test_fix_confirm_without_user_id_warns_and_continues(self, tmp_path):
        """fix --confirm without user_id warns and continues to apply fixes."""
        bs_file = tmp_path / "bs.json"
        bs_file.write_text('{"tables": [{"name": "users"}]}')

        args = self._make_fix_args(tmp_path, confirm=True, no_backup=False)
        mocks = self._make_fix_mocks(backup_schema_path=str(bs_file))

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                return_value=mocks["config"],
            ),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mocks["connect_result"],
            ),
            patch(
                "db_adapter.schema.fix.generate_fix_plan",
                return_value=mocks["plan"],
            ),
            patch(
                "db_adapter.schema.fix.apply_fixes",
                new_callable=AsyncMock,
                return_value=mocks["fix_result"],
            ),
            patch(
                "db_adapter.cli._schema_fix.get_adapter",
                new_callable=AsyncMock,
                return_value=mocks["adapter"],
            ),
            patch(
                "db_adapter.cli._schema_fix.backup_database",
                new_callable=AsyncMock,
            ) as mock_backup,
            patch("db_adapter.cli._schema_fix.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        mock_backup.assert_not_called()
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No user_id available" in s for s in printed)

    def test_fix_confirm_backup_failure_aborts_fix(
        self, tmp_path, monkeypatch
    ):
        """fix --confirm aborts (returns 1) when backup_database() fails."""
        bs_file = tmp_path / "bs.json"
        bs_file.write_text('{"tables": [{"name": "users"}]}')

        args = self._make_fix_args(tmp_path, confirm=True, no_backup=False)
        mocks = self._make_fix_mocks(backup_schema_path=str(bs_file))
        mocks["config"].user_id_env = "TEST_UID"

        # Use tmp_path as CWD so backups/ dir is created there
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                return_value=mocks["config"],
            ),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mocks["connect_result"],
            ),
            patch(
                "db_adapter.schema.fix.generate_fix_plan",
                return_value=mocks["plan"],
            ),
            patch(
                "db_adapter.schema.fix.apply_fixes",
                new_callable=AsyncMock,
                return_value=mocks["fix_result"],
            ) as mock_apply,
            patch(
                "db_adapter.cli._schema_fix.get_adapter",
                new_callable=AsyncMock,
                return_value=mocks["adapter"],
            ),
            patch(
                "db_adapter.cli._schema_fix.backup_database",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Disk full"),
            ),
            patch.dict("os.environ", {"TEST_UID": "user-123"}),
            patch("db_adapter.cli._schema_fix.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 1
        mock_apply.assert_not_called()
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Auto-backup failed" in s for s in printed)
        assert any("Aborting fix" in s for s in printed)

    def test_fix_preview_no_confirm_does_not_trigger_backup(self, tmp_path):
        """fix without --confirm (preview only) does not trigger backup."""
        bs_file = tmp_path / "bs.json"
        bs_file.write_text('{"tables": [{"name": "users"}]}')

        args = self._make_fix_args(tmp_path, confirm=False, no_backup=False)
        mocks = self._make_fix_mocks(backup_schema_path=str(bs_file))
        mocks["config"].user_id_env = "TEST_UID"

        with (
            patch(
                "db_adapter.cli._schema_fix.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli._schema_fix.load_db_config",
                return_value=mocks["config"],
            ),
            patch(
                "db_adapter.cli._schema_fix.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mocks["connect_result"],
            ),
            patch(
                "db_adapter.schema.fix.generate_fix_plan",
                return_value=mocks["plan"],
            ),
            patch(
                "db_adapter.cli._schema_fix.backup_database",
                new_callable=AsyncMock,
            ) as mock_backup,
            patch(
                "db_adapter.cli._schema_fix.get_adapter",
                new_callable=AsyncMock,
            ) as mock_get_adapter,
            patch.dict("os.environ", {"TEST_UID": "user-123"}),
            patch("db_adapter.cli._schema_fix.console"),
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        mock_backup.assert_not_called()
        # Should not even create an adapter when not confirming
        mock_get_adapter.assert_not_called()


# ------------------------------------------------------------------
# _resolve_user_id() shared helper
# ------------------------------------------------------------------


class TestResolveUserId:
    """Tests for _resolve_user_id() shared helper function."""

    def test_returns_cli_flag_when_provided(self):
        """_resolve_user_id() returns CLI --user-id value when set."""
        args = argparse.Namespace(user_id="cli-user-123")
        config = MagicMock()
        config.user_id_env = "MY_USER_ID"

        result = _resolve_user_id(args, config)
        assert result == "cli-user-123"

    def test_returns_env_var_when_cli_absent(self):
        """_resolve_user_id() reads env var from config.user_id_env
        when CLI flag is not provided."""
        args = argparse.Namespace(user_id=None)
        config = MagicMock()
        config.user_id_env = "TEST_USER_ID"

        with patch.dict("os.environ", {"TEST_USER_ID": "env-user-456"}):
            result = _resolve_user_id(args, config)

        assert result == "env-user-456"

    def test_returns_none_when_neither_available(self):
        """_resolve_user_id() returns None when neither CLI flag nor
        env var is available."""
        args = argparse.Namespace(user_id=None)
        config = MagicMock()
        config.user_id_env = "MISSING_VAR"

        with patch.dict("os.environ", {}, clear=True):
            result = _resolve_user_id(args, config)

        assert result is None

    def test_empty_env_var_treated_as_not_provided(self):
        """_resolve_user_id() treats empty-string env var as
        'not provided'."""
        args = argparse.Namespace(user_id=None)
        config = MagicMock()
        config.user_id_env = "EMPTY_VAR"

        with patch.dict("os.environ", {"EMPTY_VAR": ""}):
            result = _resolve_user_id(args, config)

        assert result is None

    def test_returns_none_when_config_is_none(self):
        """_resolve_user_id() returns None when config is None and
        CLI flag is absent."""
        args = argparse.Namespace(user_id=None)

        result = _resolve_user_id(args, None)
        assert result is None

    def test_safe_access_on_args_without_user_id(self):
        """_resolve_user_id() uses getattr so args without user_id
        attribute work safely."""
        args = argparse.Namespace()  # no user_id attribute
        config = MagicMock()
        config.user_id_env = None

        result = _resolve_user_id(args, config)
        assert result is None

    def test_cli_flag_takes_precedence_over_env(self):
        """_resolve_user_id() returns CLI flag even when env var is set."""
        args = argparse.Namespace(user_id="cli-value")
        config = MagicMock()
        config.user_id_env = "TEST_USER_ID"

        with patch.dict("os.environ", {"TEST_USER_ID": "env-value"}):
            result = _resolve_user_id(args, config)

        assert result == "cli-value"

    def test_config_without_user_id_env_returns_none(self):
        """_resolve_user_id() returns None when config has no
        user_id_env and CLI flag absent."""
        args = argparse.Namespace(user_id=None)
        config = MagicMock()
        config.user_id_env = None

        result = _resolve_user_id(args, config)
        assert result is None


# ------------------------------------------------------------------
# _async_sync() config defaults for tables and user_id
# ------------------------------------------------------------------


class TestAsyncSyncConfigDefaults:
    """Tests for _async_sync() config fallbacks for tables and user_id."""

    def test_sync_resolves_tables_from_config(self):
        """_async_sync() uses config.sync_tables when --tables not provided."""
        mock_config = MagicMock()
        mock_config.sync_tables = ["users", "orders"]
        mock_config.user_id_env = "TEST_UID"

        compare_result = MagicMock()
        compare_result.success = True
        compare_result.source_counts = {"users": 5, "orders": 3}
        compare_result.dest_counts = {"users": 5, "orders": 3}
        compare_result.sync_plan = None

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables=None,
            user_id="abc",
            dry_run=True,
            confirm=False,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ) as mock_compare,
            patch("db_adapter.cli._data_sync.console"),
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        # Verify tables from config were used
        call_kwargs = mock_compare.call_args[1]
        assert call_kwargs["tables"] == ["users", "orders"]

    def test_sync_cli_tables_overrides_config(self):
        """_async_sync() uses CLI --tables value over config.sync_tables."""
        mock_config = MagicMock()
        mock_config.sync_tables = ["users", "orders"]
        mock_config.user_id_env = None

        compare_result = MagicMock()
        compare_result.success = True
        compare_result.source_counts = {"items": 10}
        compare_result.dest_counts = {"items": 8}
        compare_result.sync_plan = None

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables="items",
            user_id="abc",
            dry_run=True,
            confirm=False,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ) as mock_compare,
            patch("db_adapter.cli._data_sync.console"),
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        # CLI --tables should override config
        call_kwargs = mock_compare.call_args[1]
        assert call_kwargs["tables"] == ["items"]

    def test_sync_missing_tables_returns_1(self):
        """_async_sync() returns 1 when tables cannot be resolved."""
        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables=None,
            user_id="abc",
            dry_run=False,
            confirm=False,
        )

        with (
            patch(
                "db_adapter.cli._data_sync.load_db_config",
                side_effect=FileNotFoundError,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No tables specified" in s for s in printed)

    def test_sync_missing_user_id_returns_1(self):
        """_async_sync() returns 1 when user_id cannot be resolved."""
        mock_config = MagicMock()
        mock_config.sync_tables = ["users"]
        mock_config.user_id_env = None

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables=None,
            user_id=None,
            dry_run=False,
            confirm=False,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No user ID available" in s for s in printed)

    def test_sync_user_id_from_env_var(self):
        """_async_sync() resolves user_id from env var via config."""
        mock_config = MagicMock()
        mock_config.sync_tables = ["users"]
        mock_config.user_id_env = "DEV_USER_ID"

        compare_result = MagicMock()
        compare_result.success = True
        compare_result.source_counts = {"users": 5}
        compare_result.dest_counts = {"users": 5}
        compare_result.sync_plan = None

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables=None,
            user_id=None,
            dry_run=True,
            confirm=False,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch.dict("os.environ", {"DEV_USER_ID": "env-user-789"}),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ) as mock_compare,
            patch("db_adapter.cli._data_sync.console"),
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        call_kwargs = mock_compare.call_args[1]
        assert call_kwargs["user_id"] == "env-user-789"

    def test_sync_missing_user_id_shows_env_hint(self):
        """_async_sync() error message includes env var name when
        config.user_id_env is configured."""
        mock_config = MagicMock()
        mock_config.sync_tables = ["users"]
        mock_config.user_id_env = "MY_APP_USER"

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables=None,
            user_id=None,
            dry_run=False,
            confirm=False,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=mock_config),
            patch.dict("os.environ", {}, clear=True),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("MY_APP_USER" in s for s in printed)

    def test_sync_config_none_sync_tables_returns_1(self):
        """_async_sync() returns 1 when config loads but sync_tables is None
        and --tables not provided."""
        mock_config = MagicMock()
        mock_config.sync_tables = None
        mock_config.user_id_env = None

        args = argparse.Namespace(
            env_prefix="",
            source="rds",
            tables=None,
            user_id="abc",
            dry_run=False,
            confirm=False,
        )

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No tables specified" in s for s in printed)


# ------------------------------------------------------------------
# _load_backup_schema() and _resolve_backup_schema_path() helpers
# ------------------------------------------------------------------


class TestLoadBackupSchema:
    """Tests for _load_backup_schema() JSON loading and validation."""

    def test_valid_json_returns_backup_schema(self, tmp_path):
        """_load_backup_schema() with valid JSON returns a BackupSchema."""
        schema_file = tmp_path / "backup-schema.json"
        schema_file.write_text(
            '{"tables": ['
            '{"name": "authors", "pk": "id", "slug_field": "slug", "user_field": "user_id"},'
            '{"name": "books", "pk": "id", "slug_field": "slug", "user_field": "user_id",'
            ' "parent": {"table": "authors", "field": "author_id"}}'
            "]}"
        )

        result = _load_backup_schema(str(schema_file))

        from db_adapter.backup.models import BackupSchema

        assert isinstance(result, BackupSchema)
        assert len(result.tables) == 2
        assert result.tables[0].name == "authors"
        assert result.tables[1].name == "books"
        assert result.tables[1].parent is not None
        assert result.tables[1].parent.table == "authors"

    def test_invalid_json_raises_error(self, tmp_path):
        """_load_backup_schema() with invalid JSON raises JSONDecodeError."""
        import json

        schema_file = tmp_path / "invalid.json"
        schema_file.write_text("{not valid json}")

        with pytest.raises(json.JSONDecodeError):
            _load_backup_schema(str(schema_file))

    def test_missing_file_raises_file_not_found(self):
        """_load_backup_schema() with missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            _load_backup_schema("/nonexistent/path/missing.json")

    def test_valid_json_invalid_schema_raises_validation_error(self, tmp_path):
        """_load_backup_schema() with valid JSON but invalid schema raises
        ValidationError."""
        from pydantic import ValidationError

        schema_file = tmp_path / "bad-schema.json"
        # Valid JSON but missing required 'tables' field
        schema_file.write_text('{"not_tables": []}')

        with pytest.raises(ValidationError):
            _load_backup_schema(str(schema_file))

    def test_valid_json_with_defaults(self, tmp_path):
        """_load_backup_schema() uses Pydantic defaults for optional fields."""
        schema_file = tmp_path / "minimal.json"
        schema_file.write_text('{"tables": [{"name": "items"}]}')

        result = _load_backup_schema(str(schema_file))
        assert len(result.tables) == 1
        assert result.tables[0].name == "items"
        assert result.tables[0].pk == "id"  # default
        assert result.tables[0].slug_field == "slug"  # default
        assert result.tables[0].parent is None  # default


class TestResolveBackupSchemaPath:
    """Tests for _resolve_backup_schema_path() resolution order."""

    def test_returns_cli_flag_when_provided(self):
        """_resolve_backup_schema_path() returns CLI --backup-schema when set."""
        args = argparse.Namespace(backup_schema="cli-schema.json")
        config = MagicMock()
        config.backup_schema = "config-schema.json"

        result = _resolve_backup_schema_path(args, config)
        assert result == "cli-schema.json"

    def test_returns_config_path_when_flag_absent(self):
        """_resolve_backup_schema_path() returns config.backup_schema when
        CLI flag is not provided."""
        args = argparse.Namespace()  # no backup_schema attribute
        config = MagicMock()
        config.backup_schema = "config-schema.json"

        result = _resolve_backup_schema_path(args, config)
        assert result == "config-schema.json"

    def test_returns_none_when_neither_available(self):
        """_resolve_backup_schema_path() returns None when neither CLI flag
        nor config provides a path."""
        args = argparse.Namespace()
        config = MagicMock()
        config.backup_schema = None

        result = _resolve_backup_schema_path(args, config)
        assert result is None

    def test_returns_none_when_config_is_none(self):
        """_resolve_backup_schema_path() returns None when config is None
        and CLI flag is absent."""
        args = argparse.Namespace()

        result = _resolve_backup_schema_path(args, None)
        assert result is None

    def test_cli_flag_takes_precedence_over_config(self):
        """_resolve_backup_schema_path() returns CLI flag even when config
        also has a value."""
        args = argparse.Namespace(backup_schema="override.json")
        config = MagicMock()
        config.backup_schema = "default.json"

        result = _resolve_backup_schema_path(args, config)
        assert result == "override.json"

    def test_args_with_none_backup_schema_falls_to_config(self):
        """_resolve_backup_schema_path() falls back to config when
        args.backup_schema is explicitly None."""
        args = argparse.Namespace(backup_schema=None)
        config = MagicMock()
        config.backup_schema = "from-config.json"

        result = _resolve_backup_schema_path(args, config)
        assert result == "from-config.json"

    def test_config_with_empty_string_returns_none(self):
        """_resolve_backup_schema_path() returns None when config.backup_schema
        is an empty string (truthy check)."""
        args = argparse.Namespace()
        config = MagicMock()
        config.backup_schema = ""

        result = _resolve_backup_schema_path(args, config)
        assert result is None


# ------------------------------------------------------------------
# backup/restore subcommand parsers and sync wrappers
# ------------------------------------------------------------------


class TestBackupSubparser:
    """Tests for backup subcommand argparse structure."""

    def test_backup_parses_all_flags(self):
        """backup subcommand accepts --backup-schema, --user-id, --output,
        --tables, and --validate flags."""
        with patch(
            "sys.argv",
            [
                "db-adapter",
                "backup",
                "--backup-schema",
                "bs.json",
                "--user-id",
                "uid1",
                "--output",
                "out.json",
                "--tables",
                "t1,t2",
            ],
        ):
            with patch("db_adapter.cli.cmd_backup", return_value=0) as mock_backup:
                result = main()

        assert result == 0
        call_args = mock_backup.call_args[0][0]
        assert call_args.backup_schema == "bs.json"
        assert call_args.user_id == "uid1"
        assert call_args.output == "out.json"
        assert call_args.tables == "t1,t2"
        assert call_args.validate is None

    def test_backup_validate_flag(self):
        """backup --validate backup.json parses without error."""
        with patch(
            "sys.argv",
            ["db-adapter", "backup", "--validate", "backup.json"],
        ):
            with patch("db_adapter.cli.cmd_backup", return_value=0) as mock_backup:
                result = main()

        assert result == 0
        call_args = mock_backup.call_args[0][0]
        assert call_args.validate == "backup.json"

    def test_backup_short_output_flag(self):
        """backup -o out.json uses the short form of --output."""
        with patch(
            "sys.argv",
            ["db-adapter", "backup", "-o", "out.json"],
        ):
            with patch("db_adapter.cli.cmd_backup", return_value=0) as mock_backup:
                result = main()

        assert result == 0
        call_args = mock_backup.call_args[0][0]
        assert call_args.output == "out.json"

    def test_backup_all_flags_default_to_none(self):
        """backup with no flags has all optional fields defaulting to None."""
        with patch("sys.argv", ["db-adapter", "backup"]):
            with patch("db_adapter.cli.cmd_backup", return_value=0) as mock_backup:
                result = main()

        assert result == 0
        call_args = mock_backup.call_args[0][0]
        assert call_args.backup_schema is None
        assert call_args.user_id is None
        assert call_args.output is None
        assert call_args.tables is None
        assert call_args.validate is None

    def test_backup_dispatches_to_cmd_backup(self):
        """backup subcommand dispatches to cmd_backup handler."""
        with patch("sys.argv", ["db-adapter", "backup"]):
            with patch("db_adapter.cli.cmd_backup", return_value=0) as mock_backup:
                main()

        mock_backup.assert_called_once()


class TestRestoreSubparser:
    """Tests for restore subcommand argparse structure."""

    def test_restore_parses_all_flags(self):
        """restore subcommand accepts positional backup_path and all flags."""
        with patch(
            "sys.argv",
            [
                "db-adapter",
                "restore",
                "backup.json",
                "--backup-schema",
                "bs.json",
                "--user-id",
                "uid1",
                "--mode",
                "overwrite",
                "--dry-run",
                "--yes",
            ],
        ):
            with patch("db_adapter.cli.cmd_restore", return_value=0) as mock_restore:
                result = main()

        assert result == 0
        call_args = mock_restore.call_args[0][0]
        assert call_args.backup_path == "backup.json"
        assert call_args.backup_schema == "bs.json"
        assert call_args.user_id == "uid1"
        assert call_args.mode == "overwrite"
        assert call_args.dry_run is True
        assert call_args.yes is True

    def test_restore_requires_backup_path(self):
        """restore subcommand requires positional backup_path argument."""
        with patch("sys.argv", ["db-adapter", "restore"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2

    def test_restore_mode_defaults_to_skip(self):
        """restore --mode defaults to 'skip' when not specified."""
        with patch(
            "sys.argv", ["db-adapter", "restore", "backup.json"]
        ):
            with patch("db_adapter.cli.cmd_restore", return_value=0) as mock_restore:
                result = main()

        assert result == 0
        call_args = mock_restore.call_args[0][0]
        assert call_args.mode == "skip"

    def test_restore_mode_choices(self):
        """restore --mode rejects invalid choices."""
        with patch(
            "sys.argv",
            ["db-adapter", "restore", "backup.json", "--mode", "invalid"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2

    def test_restore_short_flags(self):
        """restore -m and -y short forms work."""
        with patch(
            "sys.argv",
            ["db-adapter", "restore", "backup.json", "-m", "fail", "-y"],
        ):
            with patch("db_adapter.cli.cmd_restore", return_value=0) as mock_restore:
                result = main()

        assert result == 0
        call_args = mock_restore.call_args[0][0]
        assert call_args.mode == "fail"
        assert call_args.yes is True

    def test_restore_dry_run_and_yes_default_false(self):
        """restore --dry-run and --yes default to False."""
        with patch(
            "sys.argv", ["db-adapter", "restore", "backup.json"]
        ):
            with patch("db_adapter.cli.cmd_restore", return_value=0) as mock_restore:
                result = main()

        assert result == 0
        call_args = mock_restore.call_args[0][0]
        assert call_args.dry_run is False
        assert call_args.yes is False

    def test_restore_dispatches_to_cmd_restore(self):
        """restore subcommand dispatches to cmd_restore handler."""
        with patch(
            "sys.argv", ["db-adapter", "restore", "backup.json"]
        ):
            with patch("db_adapter.cli.cmd_restore", return_value=0) as mock_restore:
                main()

        mock_restore.assert_called_once()


class TestCmdBackupWrapper:
    """Tests for cmd_backup() sync wrapper dispatch logic."""

    def test_cmd_backup_calls_asyncio_run_for_create(self):
        """cmd_backup calls asyncio.run(_async_backup) when --validate
        is not provided."""
        args = argparse.Namespace(
            validate=None,
            backup_schema=None,
            user_id=None,
            output=None,
            tables=None,
            env_prefix="",
        )

        with patch("db_adapter.cli._backup.asyncio") as mock_asyncio:
            mock_asyncio.run.return_value = 0
            result = cmd_backup(args)

        assert result == 0
        mock_asyncio.run.assert_called_once()

    def test_cmd_backup_calls_validate_for_validate_mode(self):
        """cmd_backup calls _validate_backup when --validate is provided."""
        args = argparse.Namespace(
            validate="backup.json",
            backup_schema=None,
            env_prefix="",
        )

        with patch("db_adapter.cli._backup._validate_backup", return_value=0) as mock_validate:
            result = cmd_backup(args)

        assert result == 0
        mock_validate.assert_called_once_with(args)

    def test_cmd_backup_does_not_call_asyncio_for_validate(self):
        """cmd_backup does NOT call asyncio.run when --validate is provided."""
        args = argparse.Namespace(
            validate="backup.json",
            backup_schema=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup._validate_backup", return_value=0),
            patch("db_adapter.cli._backup.asyncio") as mock_asyncio,
        ):
            cmd_backup(args)

        mock_asyncio.run.assert_not_called()

    def test_cmd_backup_source_has_asyncio_run(self):
        """cmd_backup source code contains asyncio.run()."""
        source = inspect.getsource(cmd_backup)
        assert "asyncio.run" in source


class TestCmdRestoreWrapper:
    """Tests for cmd_restore() sync wrapper."""

    def test_cmd_restore_calls_asyncio_run(self):
        """cmd_restore calls asyncio.run(_async_restore)."""
        args = argparse.Namespace(
            backup_path="backup.json",
            backup_schema=None,
            user_id=None,
            mode="skip",
            dry_run=False,
            yes=False,
            env_prefix="",
        )

        with patch("db_adapter.cli._backup.asyncio") as mock_asyncio:
            mock_asyncio.run.return_value = 0
            result = cmd_restore(args)

        assert result == 0
        mock_asyncio.run.assert_called_once()

    def test_cmd_restore_source_has_asyncio_run(self):
        """cmd_restore source code contains asyncio.run()."""
        source = inspect.getsource(cmd_restore)
        assert "asyncio.run" in source


class TestBackupHandlerSignatures:
    """Verify async/sync signatures of backup handler functions."""

    def test_async_backup_is_async(self):
        """_async_backup is an async function."""
        assert inspect.iscoroutinefunction(_async_backup)

    def test_async_restore_is_async(self):
        """_async_restore is an async function."""
        assert inspect.iscoroutinefunction(_async_restore)

    def test_validate_backup_is_sync(self):
        """_validate_backup is a regular (sync) function."""
        assert not inspect.iscoroutinefunction(_validate_backup)


class TestAsyncBackup:
    """Tests for _async_backup() full implementation."""

    def _make_backup_schema_file(self, tmp_path):
        """Create a valid backup schema JSON file and return its path."""
        schema_file = tmp_path / "backup-schema.json"
        schema_file.write_text(
            '{"tables": ['
            '{"name": "authors", "pk": "id", "slug_field": "slug", "user_field": "user_id"},'
            '{"name": "books", "pk": "id", "slug_field": "slug", "user_field": "user_id",'
            ' "parent": {"table": "authors", "field": "author_id"}}'
            "]}"
        )
        return str(schema_file)

    def test_backup_success_calls_backup_database(self, tmp_path):
        """_async_backup with valid schema + mock adapter returns 0 and
        calls backup_database."""
        schema_path = self._make_backup_schema_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        args = argparse.Namespace(
            backup_schema=schema_path,
            user_id="test-user",
            output=str(tmp_path / "out.json"),
            tables=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.backup_database",
                new_callable=AsyncMock,
                return_value=str(tmp_path / "out.json"),
            ) as mock_backup_db,
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 0
        mock_backup_db.assert_called_once()
        # Verify correct args passed to backup_database
        call_args = mock_backup_db.call_args
        assert call_args[0][0] is mock_adapter  # adapter
        assert call_args[0][2] == "test-user"  # user_id
        assert call_args[1]["output_path"] == str(tmp_path / "out.json")

    def test_backup_missing_backup_schema_returns_1(self):
        """_async_backup returns 1 when backup_schema path is not available."""
        args = argparse.Namespace(
            backup_schema=None,
            user_id="test-user",
            output=None,
            tables=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No backup schema available" in s for s in printed)

    def test_backup_missing_user_id_returns_1(self, tmp_path):
        """_async_backup returns 1 when user_id is not available."""
        schema_path = self._make_backup_schema_file(tmp_path)

        args = argparse.Namespace(
            backup_schema=schema_path,
            user_id=None,
            output=None,
            tables=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No user ID available" in s for s in printed)

    def test_backup_tables_filter(self, tmp_path):
        """_async_backup with --tables passes a filtered BackupSchema."""
        schema_path = self._make_backup_schema_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        args = argparse.Namespace(
            backup_schema=schema_path,
            user_id="test-user",
            output=str(tmp_path / "out.json"),
            tables="authors",
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.backup_database",
                new_callable=AsyncMock,
                return_value=str(tmp_path / "out.json"),
            ) as mock_backup_db,
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 0
        # Verify filtered schema was passed
        call_args = mock_backup_db.call_args
        schema_arg = call_args[0][1]
        assert len(schema_arg.tables) == 1
        assert schema_arg.tables[0].name == "authors"

    def test_backup_tables_warns_missing_parent(self, tmp_path):
        """_async_backup with --tables warns when child table included
        without parent."""
        schema_path = self._make_backup_schema_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        args = argparse.Namespace(
            backup_schema=schema_path,
            user_id="test-user",
            output=str(tmp_path / "out.json"),
            tables="books",  # child without parent "authors"
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.backup_database",
                new_callable=AsyncMock,
                return_value=str(tmp_path / "out.json"),
            ),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("parent" in s and "authors" in s for s in printed)

    def test_backup_adapter_always_closed(self, tmp_path):
        """_async_backup closes the adapter in finally block even on error."""
        schema_path = self._make_backup_schema_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        args = argparse.Namespace(
            backup_schema=schema_path,
            user_id="test-user",
            output=str(tmp_path / "out.json"),
            tables=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.backup_database",
                new_callable=AsyncMock,
                side_effect=RuntimeError("disk full"),
            ),
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 1
        mock_adapter.close.assert_awaited_once()

    def test_backup_schema_file_not_found_returns_1(self):
        """_async_backup returns 1 when backup schema file does not exist."""
        args = argparse.Namespace(
            backup_schema="/nonexistent/schema.json",
            user_id="test-user",
            output=None,
            tables=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("not found" in s for s in printed)

    def test_backup_uses_config_fallbacks(self, tmp_path):
        """_async_backup resolves backup_schema and user_id from config."""
        schema_path = self._make_backup_schema_file(tmp_path)

        mock_config = MagicMock()
        mock_config.backup_schema = schema_path
        mock_config.user_id_env = "TEST_UID"

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        args = argparse.Namespace(
            backup_schema=None,  # fallback to config
            user_id=None,  # fallback to env
            output=str(tmp_path / "out.json"),
            tables=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", return_value=mock_config),
            patch.dict("os.environ", {"TEST_UID": "env-user-123"}),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.backup_database",
                new_callable=AsyncMock,
                return_value=str(tmp_path / "out.json"),
            ) as mock_backup_db,
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_backup(args))

        assert rc == 0
        call_args = mock_backup_db.call_args
        assert call_args[0][2] == "env-user-123"  # user_id from env


class TestAsyncRestore:
    """Tests for _async_restore() full implementation."""

    def _make_backup_schema_file(self, tmp_path):
        """Create a valid backup schema JSON file and return its path."""
        schema_file = tmp_path / "backup-schema.json"
        schema_file.write_text(
            '{"tables": ['
            '{"name": "authors", "pk": "id", "slug_field": "slug", "user_field": "user_id"}'
            "]}"
        )
        return str(schema_file)

    def _make_backup_file(self, tmp_path):
        """Create a minimal backup JSON file and return its path."""
        backup_file = tmp_path / "backup.json"
        backup_file.write_text(
            '{"metadata": {"created_at": "2026-01-01", "user_id": "u1",'
            ' "backup_type": "full", "version": "1.1"},'
            ' "authors": [{"id": "a1", "slug": "auth1", "user_id": "u1"}]}'
        )
        return str(backup_file)

    def test_restore_success_calls_restore_database(self, tmp_path):
        """_async_restore with valid inputs returns 0 and calls
        restore_database."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_path = self._make_backup_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        restore_result = {
            "dry_run": False,
            "authors": {"inserted": 1, "updated": 0, "skipped": 0, "failed": 0},
        }

        args = argparse.Namespace(
            backup_path=backup_path,
            backup_schema=schema_path,
            user_id="test-user",
            mode="skip",
            dry_run=False,
            yes=True,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.restore_database",
                new_callable=AsyncMock,
                return_value=restore_result,
            ) as mock_restore_db,
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 0
        mock_restore_db.assert_called_once()

    def test_restore_dry_run_passes_dry_run_true(self, tmp_path):
        """_async_restore with --dry-run passes dry_run=True to
        restore_database."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_path = self._make_backup_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        restore_result = {
            "dry_run": True,
            "authors": {"inserted": 1, "updated": 0, "skipped": 0, "failed": 0},
        }

        args = argparse.Namespace(
            backup_path=backup_path,
            backup_schema=schema_path,
            user_id="test-user",
            mode="skip",
            dry_run=True,
            yes=False,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.restore_database",
                new_callable=AsyncMock,
                return_value=restore_result,
            ) as mock_restore_db,
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 0
        call_kwargs = mock_restore_db.call_args[1]
        assert call_kwargs["dry_run"] is True

    def test_restore_mode_overwrite_passes_mode(self, tmp_path):
        """_async_restore with --mode overwrite passes mode='overwrite'."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_path = self._make_backup_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        restore_result = {
            "dry_run": False,
            "authors": {"inserted": 0, "updated": 1, "skipped": 0, "failed": 0},
        }

        args = argparse.Namespace(
            backup_path=backup_path,
            backup_schema=schema_path,
            user_id="test-user",
            mode="overwrite",
            dry_run=False,
            yes=True,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.restore_database",
                new_callable=AsyncMock,
                return_value=restore_result,
            ) as mock_restore_db,
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 0
        call_kwargs = mock_restore_db.call_args[1]
        assert call_kwargs["mode"] == "overwrite"

    def test_restore_missing_backup_schema_returns_1(self):
        """_async_restore returns 1 when backup_schema is not available."""
        args = argparse.Namespace(
            backup_path="backup.json",
            backup_schema=None,
            user_id="test-user",
            mode="skip",
            dry_run=False,
            yes=True,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No backup schema available" in s for s in printed)

    def test_restore_missing_user_id_returns_1(self, tmp_path):
        """_async_restore returns 1 when user_id is not available."""
        schema_path = self._make_backup_schema_file(tmp_path)

        args = argparse.Namespace(
            backup_path="backup.json",
            backup_schema=schema_path,
            user_id=None,
            mode="skip",
            dry_run=False,
            yes=True,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No user ID available" in s for s in printed)

    def test_restore_backup_file_not_found_returns_1(self, tmp_path):
        """_async_restore returns 1 when backup file does not exist."""
        schema_path = self._make_backup_schema_file(tmp_path)

        args = argparse.Namespace(
            backup_path=str(tmp_path / "nonexistent.json"),
            backup_schema=schema_path,
            user_id="test-user",
            mode="skip",
            dry_run=False,
            yes=True,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("not found" in s for s in printed)

    def test_restore_adapter_always_closed(self, tmp_path):
        """_async_restore closes the adapter in finally block even on error."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_path = self._make_backup_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        args = argparse.Namespace(
            backup_path=backup_path,
            backup_schema=schema_path,
            user_id="test-user",
            mode="skip",
            dry_run=False,
            yes=True,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.restore_database",
                new_callable=AsyncMock,
                side_effect=RuntimeError("restore error"),
            ),
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 1
        mock_adapter.close.assert_awaited_once()

    def test_restore_confirmation_prompt_aborted(self, tmp_path):
        """_async_restore aborts when user does not confirm."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_path = self._make_backup_file(tmp_path)

        args = argparse.Namespace(
            backup_path=backup_path,
            backup_schema=schema_path,
            user_id="test-user",
            mode="skip",
            dry_run=False,
            yes=False,  # require confirmation
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("builtins.input", return_value="no"),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Aborted" in s for s in printed)

    def test_restore_confirmation_prompt_accepted(self, tmp_path):
        """_async_restore proceeds when user confirms with 'yes'."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_path = self._make_backup_file(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.close = AsyncMock()

        restore_result = {
            "dry_run": False,
            "authors": {"inserted": 1, "updated": 0, "skipped": 0, "failed": 0},
        }

        args = argparse.Namespace(
            backup_path=backup_path,
            backup_schema=schema_path,
            user_id="test-user",
            mode="skip",
            dry_run=False,
            yes=False,  # require confirmation
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("builtins.input", return_value="yes"),
            patch(
                "db_adapter.cli._backup.get_adapter",
                new_callable=AsyncMock,
                return_value=mock_adapter,
            ),
            patch(
                "db_adapter.cli._backup.restore_database",
                new_callable=AsyncMock,
                return_value=restore_result,
            ),
            patch("db_adapter.cli._backup.console"),
        ):
            rc = asyncio.run(_async_restore(args))

        assert rc == 0


class TestValidateBackup:
    """Tests for _validate_backup() full implementation."""

    def _make_backup_schema_file(self, tmp_path):
        """Create a valid backup schema JSON file and return its path."""
        schema_file = tmp_path / "backup-schema.json"
        schema_file.write_text(
            '{"tables": ['
            '{"name": "authors", "pk": "id", "slug_field": "slug", "user_field": "user_id"}'
            "]}"
        )
        return str(schema_file)

    def test_validate_valid_backup_returns_0(self, tmp_path):
        """_validate_backup with valid backup file returns 0."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_file = tmp_path / "backup.json"
        backup_file.write_text(
            '{"metadata": {"created_at": "2026-01-01", "user_id": "u1",'
            ' "backup_type": "full", "version": "1.1"},'
            ' "authors": [{"id": "a1", "slug": "auth1", "user_id": "u1"}]}'
        )

        args = argparse.Namespace(
            validate=str(backup_file),
            backup_schema=schema_path,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console"),
        ):
            rc = _validate_backup(args)

        assert rc == 0

    def test_validate_invalid_backup_returns_1(self, tmp_path):
        """_validate_backup with invalid backup file returns 1."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_file = tmp_path / "bad-backup.json"
        # Missing required 'authors' key and wrong version
        backup_file.write_text(
            '{"metadata": {"created_at": "2026-01-01", "user_id": "u1",'
            ' "backup_type": "full", "version": "0.9"}}'
        )

        args = argparse.Namespace(
            validate=str(backup_file),
            backup_schema=schema_path,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console"),
        ):
            rc = _validate_backup(args)

        assert rc == 1

    def test_validate_missing_backup_schema_returns_1(self):
        """_validate_backup returns 1 when backup_schema is not available."""
        args = argparse.Namespace(
            validate="backup.json",
            backup_schema=None,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = _validate_backup(args)

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No backup schema available" in s for s in printed)

    def test_validate_missing_backup_file_returns_1(self, tmp_path):
        """_validate_backup returns 1 when backup file does not exist."""
        schema_path = self._make_backup_schema_file(tmp_path)

        args = argparse.Namespace(
            validate=str(tmp_path / "nonexistent.json"),
            backup_schema=schema_path,
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", side_effect=FileNotFoundError),
            patch("db_adapter.cli._backup.console") as mock_console,
        ):
            rc = _validate_backup(args)

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("not found" in s or "invalid" in s.lower() for s in printed)

    def test_validate_uses_config_backup_schema(self, tmp_path):
        """_validate_backup resolves backup_schema from config."""
        schema_path = self._make_backup_schema_file(tmp_path)
        backup_file = tmp_path / "backup.json"
        backup_file.write_text(
            '{"metadata": {"created_at": "2026-01-01", "user_id": "u1",'
            ' "backup_type": "full", "version": "1.1"},'
            ' "authors": [{"id": "a1", "slug": "auth1", "user_id": "u1"}]}'
        )

        mock_config = MagicMock()
        mock_config.backup_schema = schema_path

        args = argparse.Namespace(
            validate=str(backup_file),
            backup_schema=None,  # fallback to config
            env_prefix="",
        )

        with (
            patch("db_adapter.cli._backup.load_db_config", return_value=mock_config),
            patch("db_adapter.cli._backup.console"),
        ):
            rc = _validate_backup(args)

        assert rc == 0


# ------------------------------------------------------------------
# Import style verification
# ------------------------------------------------------------------


class TestImportStyle:
    """Verify all imports use db_adapter.* package paths."""

    def test_no_bare_imports_in_cli_init(self):
        """cli/__init__.py uses only db_adapter.* imports (no bare imports)."""
        source = CLI_INIT_PY.read_text()
        tree = ast.parse(source)

        # Bare imports to check: from adapters import, from schema import, etc.
        forbidden_modules = {
            "adapters",
            "config",
            "schema",
            "factory",
            "backup",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top_level = node.module.split(".")[0]
                if top_level in forbidden_modules:
                    pytest.fail(
                        f"Found bare import 'from {node.module} import ...' "
                        f"in cli/__init__.py (should use db_adapter.* path)"
                    )


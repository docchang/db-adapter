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
- ``cli/backup.py`` has no MC-specific references
"""

import ast
import asyncio
import inspect
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_adapter.cli import (
    _parse_expected_columns,
    cmd_connect,
    cmd_fix,
    cmd_profiles,
    cmd_status,
    cmd_sync,
    cmd_validate,
    main,
)

# Paths to source files for AST/source inspection
CLI_INIT_PY = (
    Path(__file__).parent.parent / "src" / "db_adapter" / "cli" / "__init__.py"
)
CLI_BACKUP_PY = (
    Path(__file__).parent.parent / "src" / "db_adapter" / "cli" / "backup.py"
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

    def test_no_mission_control_in_cli_backup(self):
        """'Mission Control' does not appear in cli/backup.py."""
        source = CLI_BACKUP_PY.read_text()
        assert "Mission Control" not in source, (
            "Found 'Mission Control' in cli/backup.py"
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

    def test_cmd_status_is_sync(self):
        """cmd_status does not call asyncio.run() (reads local files only)."""
        import inspect
        source = inspect.getsource(cmd_status)
        assert "asyncio.run" not in source

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

    def test_sync_parser_requires_tables(self):
        """sync command requires --tables argument."""
        with patch("sys.argv", ["db-adapter", "sync", "--from", "rds", "--user-id", "abc"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2  # argparse error

    def test_sync_parser_requires_user_id(self):
        """sync command requires --user-id argument."""
        with patch("sys.argv", ["db-adapter", "sync", "--from", "rds", "--tables", "t1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    def test_fix_parser_requires_schema_file(self):
        """fix command requires --schema-file argument."""
        with patch("sys.argv", ["db-adapter", "fix", "--column-defs", "d.json"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    def test_fix_parser_requires_column_defs(self):
        """fix command requires --column-defs argument."""
        with patch("sys.argv", ["db-adapter", "fix", "--schema-file", "s.sql"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2


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

    def test_no_create_table(self, tmp_path):
        """Raises ValueError when no CREATE TABLE found."""
        schema = tmp_path / "empty.sql"
        schema.write_text("-- just a comment\nSELECT 1;\n")

        with pytest.raises(ValueError, match="No CREATE TABLE"):
            _parse_expected_columns(schema)


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

    def test_no_bare_imports_in_cli_backup(self):
        """cli/backup.py uses only db_adapter.* imports."""
        source = CLI_BACKUP_PY.read_text()
        tree = ast.parse(source)

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
                        f"in cli/backup.py (should use db_adapter.* path)"
                    )

    def test_backup_py_imports_from_db_adapter(self):
        """cli/backup.py imports from db_adapter.backup.backup_restore."""
        source = CLI_BACKUP_PY.read_text()
        assert "from db_adapter.backup.backup_restore import" in source


# ------------------------------------------------------------------
# CLI backup.py modernization
# ------------------------------------------------------------------


class TestBackupCLI:
    """Verify cli/backup.py is modernized."""

    def test_no_mission_control_in_description(self):
        """argparse description does not mention Mission Control."""
        source = CLI_BACKUP_PY.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "ArgumentParser":
                    for kw in node.keywords:
                        if kw.arg == "description":
                            if isinstance(kw.value, ast.Constant):
                                assert "Mission Control" not in kw.value.value, (
                                    "backup.py argparse description still mentions "
                                    "Mission Control"
                                )

    def test_no_mission_control_in_docstring(self):
        """Module docstring does not mention Mission Control."""
        source = CLI_BACKUP_PY.read_text()
        tree = ast.parse(source)

        if tree.body and isinstance(tree.body[0], ast.Expr):
            if isinstance(tree.body[0].value, ast.Constant):
                docstring = tree.body[0].value.value
                assert "Mission Control" not in docstring, (
                    "backup.py module docstring still mentions Mission Control"
                )

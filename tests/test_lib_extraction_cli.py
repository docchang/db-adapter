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

import argparse
import ast
import asyncio
import inspect
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_adapter.cli import (
    _async_connect,
    _async_fix,
    _async_sync,
    _async_validate,
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
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
                "db_adapter.cli.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
                "db_adapter.cli.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
                "db_adapter.cli.load_db_config",
                side_effect=FileNotFoundError("no config"),
            ),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
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
                "db_adapter.cli.load_db_config",
                side_effect=FileNotFoundError("no config"),
            ),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
                "db_adapter.cli.load_db_config",
                side_effect=Exception("Validation error"),
            ),
            patch("db_adapter.cli.read_profile_lock", return_value=None),
            patch(
                "db_adapter.cli.connect_and_validate",
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
                "db_adapter.cli.load_db_config",
                side_effect=FileNotFoundError("no config"),
            ),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
        ):
            rc = asyncio.run(_async_connect(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Switched from" in s for s in printed)


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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.connect_and_validate",
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
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch("db_adapter.cli.load_db_config") as mock_load_config,
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
                "db_adapter.cli.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli.console") as mock_console,
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli.console") as mock_console,
        ):
            rc = asyncio.run(_async_validate(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("nonexistent.sql" in s for s in printed)

    def test_validate_no_profile_returns_1(self):
        """validate with no validated profile returns 1."""
        args = argparse.Namespace(env_prefix="", schema_file=None)

        with patch("db_adapter.cli.read_profile_lock", return_value=None):
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.connect_and_validate",
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch("db_adapter.cli.console") as mock_console,
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
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.compare_profiles",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch(
                "db_adapter.cli.sync_data",
                new_callable=AsyncMock,
                return_value=sync_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
            patch("db_adapter.cli.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli.compare_profiles",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("db_adapter.cli.console") as mock_console,
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
                "db_adapter.cli.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch(
                "db_adapter.cli.connect_and_validate",
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
        not config."""
        schema = tmp_path / "explicit.sql"
        schema.write_text(
            "CREATE TABLE orders (\n"
            "    id TEXT PRIMARY KEY,\n"
            "    total NUMERIC NOT NULL\n"
            ");\n"
        )
        col_defs = tmp_path / "defs.json"
        col_defs.write_text('{"orders.total": "NUMERIC NOT NULL"}')

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
                "db_adapter.cli.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli.connect_and_validate",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch("db_adapter.cli.load_db_config") as mock_load_config,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 0
        # load_db_config should NOT be called when --schema-file is provided
        mock_load_config.assert_not_called()
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
                "db_adapter.cli.get_active_profile_name",
                return_value="dev",
            ),
            patch(
                "db_adapter.cli.load_db_config",
                side_effect=FileNotFoundError("db.toml not found"),
            ),
            patch("db_adapter.cli.console") as mock_console,
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
                "db_adapter.cli.get_active_profile_name",
                return_value="dev",
            ),
            patch("db_adapter.cli.load_db_config", return_value=mock_config),
            patch("db_adapter.cli.console") as mock_console,
        ):
            rc = asyncio.run(_async_fix(args))

        assert rc == 1
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("No schema file available" in s for s in printed)


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

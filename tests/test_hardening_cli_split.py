"""Tests for Step 1: CLI File Split.

Verifies that the CLI module has been correctly split into sub-modules
with proper re-exports, no circular imports, and all files present.
"""

import pathlib
import subprocess
import sys
import types

import pytest

SRC_CLI = pathlib.Path(__file__).resolve().parent.parent / "src" / "db_adapter" / "cli"


class TestSubModuleFilesExist:
    """Verify all 5 new sub-module files exist and are non-empty."""

    @pytest.mark.parametrize(
        "filename",
        [
            "_helpers.py",
            "_connection.py",
            "_schema_fix.py",
            "_data_sync.py",
            "_backup.py",
        ],
    )
    def test_submodule_exists(self, filename: str) -> None:
        """Sub-module file exists under cli package."""
        path = SRC_CLI / filename
        assert path.exists(), f"Missing: {path}"

    @pytest.mark.parametrize(
        "filename",
        [
            "_helpers.py",
            "_connection.py",
            "_schema_fix.py",
            "_data_sync.py",
            "_backup.py",
        ],
    )
    def test_submodule_non_empty(self, filename: str) -> None:
        """Sub-module file is non-empty."""
        path = SRC_CLI / filename
        content = path.read_text()
        assert len(content) > 100, f"{filename} is too short ({len(content)} chars)"


class TestReExportedSymbols:
    """Verify all 24 re-exported symbols are importable from db_adapter.cli."""

    EXPECTED_SYMBOLS = [
        # From _helpers.py (8)
        "console",
        "_EXCLUDED_TABLES",
        "_get_table_row_counts",
        "_print_table_counts",
        "_parse_expected_columns",
        "_resolve_user_id",
        "_load_backup_schema",
        "_resolve_backup_schema_path",
        # From _connection.py (7)
        "_async_connect",
        "_async_validate",
        "_async_status",
        "cmd_connect",
        "cmd_status",
        "cmd_profiles",
        "cmd_validate",
        # From _schema_fix.py (2)
        "_async_fix",
        "cmd_fix",
        # From _data_sync.py (2)
        "_async_sync",
        "cmd_sync",
        # From _backup.py (5)
        "_async_backup",
        "_async_restore",
        "_validate_backup",
        "cmd_backup",
        "cmd_restore",
    ]

    @pytest.mark.parametrize("symbol", EXPECTED_SYMBOLS)
    def test_symbol_importable(self, symbol: str) -> None:
        """Re-exported symbol is accessible on db_adapter.cli."""
        from db_adapter import cli

        assert hasattr(cli, symbol), (
            f"'{symbol}' not accessible on db_adapter.cli"
        )

    def test_total_count(self) -> None:
        """Exactly 24 symbols are expected."""
        assert len(self.EXPECTED_SYMBOLS) == 24

    def test_main_defined_in_init(self) -> None:
        """main() is defined in __init__.py, not re-exported from a sub-module."""
        from db_adapter.cli import main

        assert callable(main)
        # main should be defined in __init__.py (its module is db_adapter.cli)
        assert main.__module__ == "db_adapter.cli"


class TestMainCallable:
    """Verify main() works with --help (no import errors)."""

    def test_main_help_succeeds(self) -> None:
        """main() with --help exits cleanly."""
        result = subprocess.run(
            [sys.executable, "-c", "from db_adapter.cli import main; main()"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "COLUMNS": "120"},
            input="--help\n",
        )
        # main() calls sys.argv which won't have --help, so use subprocess with args
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv = ['db-adapter', '--help']; from db_adapter.cli import main; main()",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "db-adapter" in result.stdout or "usage" in result.stdout.lower()

    def test_cli_entry_point_help(self) -> None:
        """db-adapter --help via entry point works."""
        result = subprocess.run(
            ["uv", "run", "db-adapter", "--help"],
            capture_output=True,
            text=True,
            cwd=str(SRC_CLI.parent.parent.parent.parent),
        )
        assert result.returncode == 0
        assert "connect" in result.stdout
        assert "status" in result.stdout
        assert "profiles" in result.stdout


class TestNoCircularImports:
    """Verify no circular imports between CLI sub-modules."""

    def test_import_helpers_alone(self) -> None:
        """_helpers imports cleanly in a fresh process."""
        result = subprocess.run(
            [sys.executable, "-c", "import db_adapter.cli._helpers"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_import_connection_alone(self) -> None:
        """_connection imports cleanly."""
        result = subprocess.run(
            [sys.executable, "-c", "import db_adapter.cli._connection"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_import_schema_fix_alone(self) -> None:
        """_schema_fix imports cleanly."""
        result = subprocess.run(
            [sys.executable, "-c", "import db_adapter.cli._schema_fix"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_import_data_sync_alone(self) -> None:
        """_data_sync imports cleanly."""
        result = subprocess.run(
            [sys.executable, "-c", "import db_adapter.cli._data_sync"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_import_backup_alone(self) -> None:
        """_backup imports cleanly."""
        result = subprocess.run(
            [sys.executable, "-c", "import db_adapter.cli._backup"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_import_all_submodules_together(self) -> None:
        """All sub-modules import together without circular dependency."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import db_adapter.cli._helpers; "
                    "import db_adapter.cli._connection; "
                    "import db_adapter.cli._schema_fix; "
                    "import db_adapter.cli._data_sync; "
                    "import db_adapter.cli._backup; "
                    "import db_adapter.cli"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_import_reverse_order(self) -> None:
        """Sub-modules import cleanly in reverse order."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import db_adapter.cli._backup; "
                    "import db_adapter.cli._data_sync; "
                    "import db_adapter.cli._schema_fix; "
                    "import db_adapter.cli._connection; "
                    "import db_adapter.cli._helpers"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"


class TestImportGraph:
    """Verify the import graph is acyclic per the plan specification."""

    def test_helpers_does_not_import_cli_submodules(self) -> None:
        """_helpers.py does not import from any other cli sub-module."""
        content = (SRC_CLI / "_helpers.py").read_text()
        for mod in ["_connection", "_schema_fix", "_data_sync", "_backup"]:
            assert f"from db_adapter.cli.{mod}" not in content, (
                f"_helpers.py imports from {mod} -- breaks acyclic import graph"
            )

    def test_submodules_import_from_helpers(self) -> None:
        """Each command sub-module imports from _helpers."""
        for mod in ["_connection.py", "_schema_fix.py", "_data_sync.py", "_backup.py"]:
            content = (SRC_CLI / mod).read_text()
            assert "from db_adapter.cli._helpers import" in content, (
                f"{mod} does not import from _helpers"
            )

    def test_submodules_do_not_cross_import(self) -> None:
        """Command sub-modules do not import from each other."""
        modules = ["_connection", "_schema_fix", "_data_sync", "_backup"]
        for mod_file in modules:
            content = (SRC_CLI / f"{mod_file}.py").read_text()
            for other in modules:
                if other == mod_file:
                    continue
                assert f"from db_adapter.cli.{other}" not in content, (
                    f"{mod_file}.py imports from {other} -- cross-import"
                )


class TestFacadeSize:
    """Verify __init__.py is reduced to facade size."""

    def test_init_line_count(self) -> None:
        """__init__.py is reduced to facade size (under 350 lines)."""
        content = (SRC_CLI / "__init__.py").read_text()
        line_count = len(content.splitlines())
        # Facade includes docstring + re-exports + main() + argparse setup
        # Original was 1842 lines; reduced to ~310 lines
        assert 200 <= line_count <= 350, (
            f"__init__.py has {line_count} lines, expected 200-350"
        )

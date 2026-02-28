"""Step 14: Final Validation tests.

Verifies all success criteria are met across the entire extraction:
- Zero MC-specific imports in source
- Zero hardcoded MC table names in source
- Zero orphaned REMOVED comments
- All public API imports work
- CLI entry point uses correct program name
- uv sync succeeds
"""

import ast
import importlib
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).parent.parent / "src" / "db_adapter"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_all_python_files(directory: Path) -> list[Path]:
    """Return all .py files under a directory, recursively."""
    return sorted(directory.rglob("*.py"))


def _get_all_source_content(directory: Path) -> dict[str, str]:
    """Return a dict of {relative_path: file_content} for all .py files."""
    result = {}
    for py_file in _get_all_python_files(directory):
        rel = py_file.relative_to(directory)
        result[str(rel)] = py_file.read_text()
    return result


def _get_all_imports_ast(file_path: Path) -> list[str]:
    """Extract all import module names from a Python file using AST."""
    source = file_path.read_text()
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


# ===========================================================================
# Test: Zero MC-Specific Imports
# ===========================================================================


class TestNoMCImports:
    """Verify zero MC-specific imports remain in library source."""

    FORBIDDEN_MODULES = [
        "fastmcp",
        "creational.common",
        "creational",
        "mcp.server",
        "schema.db_models",
    ]

    def test_no_forbidden_imports_ast(self):
        """AST scan: no MC-specific import statements in any source file."""
        violations = []
        for py_file in _get_all_python_files(SRC_DIR):
            imports = _get_all_imports_ast(py_file)
            for imp in imports:
                for forbidden in self.FORBIDDEN_MODULES:
                    if imp == forbidden or imp.startswith(forbidden + "."):
                        rel = py_file.relative_to(SRC_DIR)
                        violations.append(f"{rel}: import {imp}")

        assert violations == [], (
            f"Found {len(violations)} forbidden MC-specific imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_no_forbidden_imports_grep(self):
        """Grep scan: no MC-specific import patterns in source files."""
        result = subprocess.run(
            [
                "grep", "-rEn",
                "from fastmcp|from creational|from mcp.server|from schema.db_models"
                "|import fastmcp|import creational|import mcp\\.server|import schema\\.db_models",
                str(SRC_DIR),
            ],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found MC-specific imports in source:\n{result.stdout}"
        )


# ===========================================================================
# Test: Zero Hardcoded MC Table Names
# ===========================================================================


class TestNoHardcodedMCTableNames:
    """Verify no hardcoded MC-specific table names in library source."""

    MC_TABLE_NAMES = {"projects", "milestones", "tasks"}

    def test_no_mc_table_name_string_literals_ast(self):
        """AST scan: no string literals matching MC table names in source."""
        violations = []
        for py_file in _get_all_python_files(SRC_DIR):
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in self.MC_TABLE_NAMES:
                        rel = py_file.relative_to(SRC_DIR)
                        violations.append(
                            f"{rel}:{node.lineno}: string literal \"{node.value}\""
                        )

        assert violations == [], (
            f"Found {len(violations)} hardcoded MC table name string literals:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_no_mc_table_name_grep(self):
        """Grep scan: no MC table name string literals in source files."""
        result = subprocess.run(
            [
                "grep", "-rEn",
                '"projects"|"milestones"|"tasks"',
                str(SRC_DIR),
                "--include=*.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found hardcoded MC table names in source:\n{result.stdout}"
        )


# ===========================================================================
# Test: Zero Orphaned REMOVED Comments
# ===========================================================================


class TestNoOrphanedRemovedComments:
    """Verify no orphaned # REMOVED: comments remain from Step 2."""

    def test_no_removed_comments_grep(self):
        """Grep scan: no # REMOVED: comments in source files."""
        result = subprocess.run(
            ["grep", "-rn", "# REMOVED:", str(SRC_DIR)],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found orphaned # REMOVED: comments:\n{result.stdout}"
        )


# ===========================================================================
# Test: Public API Imports
# ===========================================================================


class TestPublicAPIImports:
    """Verify all public API names are importable from top-level and subpackages."""

    def test_top_level_imports(self):
        """All key names importable from db_adapter."""
        from db_adapter import (
            AsyncPostgresAdapter,
            BackupSchema,
            DatabaseClient,
            DatabaseConfig,
            DatabaseProfile,
            ProfileNotFoundError,
            connect_and_validate,
            get_adapter,
            load_db_config,
            resolve_url,
            validate_schema,
        )

        # Verify they are actual classes/functions, not None
        assert AsyncPostgresAdapter is not None
        assert DatabaseClient is not None
        assert get_adapter is not None
        assert connect_and_validate is not None
        assert BackupSchema is not None
        assert ProfileNotFoundError is not None
        assert resolve_url is not None
        assert validate_schema is not None
        assert load_db_config is not None
        assert DatabaseProfile is not None
        assert DatabaseConfig is not None

    def test_adapters_subpackage_imports(self):
        """Adapters subpackage exports correct names."""
        from db_adapter.adapters import AsyncPostgresAdapter, DatabaseClient

        assert inspect.isclass(AsyncPostgresAdapter)
        # DatabaseClient is a Protocol
        assert hasattr(DatabaseClient, "select")

    def test_config_subpackage_imports(self):
        """Config subpackage exports correct names."""
        from db_adapter.config import DatabaseConfig, DatabaseProfile, load_db_config

        assert inspect.isclass(DatabaseProfile)
        assert inspect.isclass(DatabaseConfig)
        assert callable(load_db_config)

    def test_schema_subpackage_imports(self):
        """Schema subpackage exports correct names."""
        from db_adapter.schema import (
            ColumnDiff,
            SchemaIntrospector,
            SchemaValidationResult,
            apply_fixes,
            compare_profiles,
            generate_fix_plan,
            sync_data,
            validate_schema,
        )

        assert callable(validate_schema)
        assert inspect.isclass(SchemaIntrospector)
        assert inspect.isclass(SchemaValidationResult)
        assert inspect.isclass(ColumnDiff)

    def test_backup_subpackage_imports(self):
        """Backup subpackage exports correct names."""
        from db_adapter.backup import (
            BackupSchema,
            ForeignKey,
            TableDef,
            backup_database,
            restore_database,
            validate_backup,
        )

        assert inspect.isclass(BackupSchema)
        assert inspect.isclass(TableDef)
        assert inspect.isclass(ForeignKey)
        assert callable(backup_database)
        assert callable(restore_database)
        assert callable(validate_backup)

    def test_no_circular_imports(self):
        """Importing all subpackages in sequence does not cause circular imports."""
        # Force fresh imports by ensuring all are loaded
        import db_adapter
        import db_adapter.adapters
        import db_adapter.backup
        import db_adapter.config
        import db_adapter.schema

        assert db_adapter is not None
        assert db_adapter.adapters is not None
        assert db_adapter.config is not None
        assert db_adapter.schema is not None
        assert db_adapter.backup is not None


# ===========================================================================
# Test: Async Method Signatures
# ===========================================================================


class TestAsyncSignatures:
    """Verify key interfaces have correct async signatures."""

    def test_database_client_methods_async(self):
        """All DatabaseClient Protocol methods are async."""
        from db_adapter.adapters.base import DatabaseClient

        for method_name in ("select", "insert", "update", "delete", "close", "execute"):
            method = getattr(DatabaseClient, method_name)
            assert inspect.iscoroutinefunction(method), (
                f"DatabaseClient.{method_name} should be async"
            )

    def test_get_adapter_is_async(self):
        """get_adapter() is an async function."""
        from db_adapter.factory import get_adapter

        assert inspect.iscoroutinefunction(get_adapter)

    def test_connect_and_validate_is_async(self):
        """connect_and_validate() is an async function."""
        from db_adapter.factory import connect_and_validate

        assert inspect.iscoroutinefunction(connect_and_validate)

    def test_introspector_methods_async(self):
        """SchemaIntrospector query methods are async."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async_methods = [
            "test_connection", "introspect", "get_column_names",
            "_get_tables", "_get_columns", "_get_constraints",
            "_get_indexes", "_get_triggers", "_get_functions",
        ]
        for method_name in async_methods:
            method = getattr(SchemaIntrospector, method_name)
            assert inspect.iscoroutinefunction(method), (
                f"SchemaIntrospector.{method_name} should be async"
            )


# ===========================================================================
# Test: CLI Entry Point
# ===========================================================================


class TestCLIEntryPoint:
    """Verify CLI entry point works correctly."""

    def test_cli_help_shows_db_adapter_program_name(self):
        """db-adapter --help shows 'db-adapter' as program name."""
        result = subprocess.run(
            ["uv", "run", "db-adapter", "--help"],
            capture_output=True,
            text=True,
            cwd=str(SRC_DIR.parent.parent),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert "db-adapter" in result.stdout, (
            f"CLI help does not show 'db-adapter' as program name:\n{result.stdout}"
        )

    def test_cli_has_expected_subcommands(self):
        """CLI has all expected subcommands."""
        result = subprocess.run(
            ["uv", "run", "db-adapter", "--help"],
            capture_output=True,
            text=True,
            cwd=str(SRC_DIR.parent.parent),
        )
        for cmd in ("connect", "status", "profiles", "validate", "sync", "fix"):
            assert cmd in result.stdout, f"Missing subcommand '{cmd}' in CLI help"

    def test_cli_has_env_prefix_option(self):
        """CLI has --env-prefix global option."""
        result = subprocess.run(
            ["uv", "run", "db-adapter", "--help"],
            capture_output=True,
            text=True,
            cwd=str(SRC_DIR.parent.parent),
        )
        assert "--env-prefix" in result.stdout, (
            f"Missing --env-prefix option in CLI help:\n{result.stdout}"
        )


# ===========================================================================
# Test: Constructor Parameters (not class constants)
# ===========================================================================


class TestConstructorParameters:
    """Verify configurable parameters are constructor args, not class constants."""

    def test_jsonb_columns_is_constructor_param(self):
        """AsyncPostgresAdapter accepts jsonb_columns as constructor parameter."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        sig = inspect.signature(AsyncPostgresAdapter.__init__)
        assert "jsonb_columns" in sig.parameters, (
            "AsyncPostgresAdapter.__init__ should accept jsonb_columns parameter"
        )

    def test_validate_schema_two_params(self):
        """validate_schema() accepts actual_columns and expected_columns."""
        from db_adapter.schema.comparator import validate_schema

        sig = inspect.signature(validate_schema)
        params = list(sig.parameters.keys())
        assert "actual_columns" in params
        assert "expected_columns" in params

    def test_introspector_excluded_tables_param(self):
        """SchemaIntrospector accepts excluded_tables as constructor parameter."""
        from db_adapter.schema.introspector import SchemaIntrospector

        sig = inspect.signature(SchemaIntrospector.__init__)
        assert "excluded_tables" in sig.parameters


# ===========================================================================
# Test: Success Criteria Checklist
# ===========================================================================


class TestSuccessCriteria:
    """Verify all success criteria from the plan are met."""

    def test_uv_sync_succeeds(self):
        """uv sync installs without errors."""
        result = subprocess.run(
            ["uv", "sync", "--extra", "dev", "--extra", "supabase"],
            capture_output=True,
            text=True,
            cwd=str(SRC_DIR.parent.parent),
        )
        assert result.returncode == 0, f"uv sync failed: {result.stderr}"

    def test_no_duplicate_models(self):
        """No duplicate model classes across config/models.py and schema/models.py."""
        config_models_path = SRC_DIR / "config" / "models.py"
        schema_models_path = SRC_DIR / "schema" / "models.py"

        config_tree = ast.parse(config_models_path.read_text())
        schema_tree = ast.parse(schema_models_path.read_text())

        config_classes = {
            node.name
            for node in ast.walk(config_tree)
            if isinstance(node, ast.ClassDef)
        }
        schema_classes = {
            node.name
            for node in ast.walk(schema_tree)
            if isinstance(node, ast.ClassDef)
        }

        overlap = config_classes & schema_classes
        assert overlap == set(), (
            f"Duplicate model classes found in both config/models.py and schema/models.py: {overlap}"
        )

    def test_backup_schema_model_preserved(self):
        """BackupSchema, TableDef, ForeignKey models exist."""
        from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef

        assert inspect.isclass(BackupSchema)
        assert inspect.isclass(TableDef)
        assert inspect.isclass(ForeignKey)

    def test_database_profile_model_preserved(self):
        """DatabaseProfile and DatabaseConfig models exist."""
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        assert inspect.isclass(DatabaseProfile)
        assert inspect.isclass(DatabaseConfig)

    def test_all_init_files_have_all_list(self):
        """All __init__.py files define __all__."""
        init_files = [
            SRC_DIR / "__init__.py",
            SRC_DIR / "adapters" / "__init__.py",
            SRC_DIR / "config" / "__init__.py",
            SRC_DIR / "schema" / "__init__.py",
            SRC_DIR / "backup" / "__init__.py",
        ]
        for init_file in init_files:
            content = init_file.read_text()
            assert "__all__" in content, (
                f"{init_file.relative_to(SRC_DIR)} does not define __all__"
            )

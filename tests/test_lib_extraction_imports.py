"""Tests for Step 2: Fix Package Imports.

Verifies that all bare module imports have been converted to proper
db_adapter.* package imports, MC-specific imports are removed/commented,
and all subpackages import cleanly.
"""

import ast
import pathlib
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "db_adapter"


def _get_all_python_files() -> list[pathlib.Path]:
    """Return all .py files under src/db_adapter/."""
    return sorted(SRC_ROOT.rglob("*.py"))


# ============================================================================
# Test: No bare imports remain in any source file
# ============================================================================


class TestNoBareImports:
    """Verify all bare imports have been converted to db_adapter.* paths.

    Uses AST inspection to check actual import statements, avoiding false
    positives from docstrings, comments, and string literals.
    """

    @staticmethod
    def _collect_bare_imports(
        module_prefixes: list[str],
        exclude_prefix: str = "db_adapter.",
    ) -> list[str]:
        """Scan all .py files under SRC_ROOT for bare from-imports.

        An import is 'bare' if its module starts with one of the given
        prefixes but does NOT start with the exclude_prefix.

        Returns a list of 'file:lineno: from X import Y' strings.
        """
        bare: list[str] = []
        for py_file in _get_all_python_files():
            try:
                tree = ast.parse(py_file.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    if any(mod == pfx or mod.startswith(pfx + ".") for pfx in module_prefixes):
                        if not mod.startswith(exclude_prefix):
                            bare.append(
                                f"{py_file}:{node.lineno}: from {mod} import ..."
                            )
        return bare

    def test_no_bare_from_adapters(self) -> None:
        """No bare 'from adapters' import statements in source."""
        bare = self._collect_bare_imports(["adapters"])
        assert bare == [], f"Bare 'from adapters' imports found:\n" + "\n".join(bare)

    def test_no_bare_from_config(self) -> None:
        """No bare 'from config' import statements in source."""
        bare = self._collect_bare_imports(["config"])
        assert bare == [], f"Bare 'from config' imports found:\n" + "\n".join(bare)

    def test_no_bare_from_schema(self) -> None:
        """No bare 'from schema.*' import statements in source."""
        bare = self._collect_bare_imports(["schema"])
        assert bare == [], f"Bare 'from schema.*' imports found:\n" + "\n".join(bare)

    def test_no_bare_from_backup(self) -> None:
        """No bare 'from backup.*' import statements in source."""
        bare = self._collect_bare_imports(["backup"])
        assert bare == [], f"Bare 'from backup.*' imports found:\n" + "\n".join(bare)

    def test_no_bare_from_db(self) -> None:
        """No bare 'from db import' statements in source."""
        bare = self._collect_bare_imports(["db"])
        assert bare == [], f"Bare 'from db import' found:\n" + "\n".join(bare)


# ============================================================================
# Test: MC-specific imports are removed/commented
# ============================================================================


class TestMCImportsRemoved:
    """Verify MC-specific external imports are removed or commented out."""

    def test_no_active_fastmcp_import(self) -> None:
        """No active 'from fastmcp' import in source."""
        result = subprocess.run(
            ["grep", "-rn", "from fastmcp", str(SRC_ROOT), "--include=*.py"],
            capture_output=True,
            text=True,
        )
        active = [
            line
            for line in result.stdout.strip().splitlines()
            if line and "# REMOVED" not in line
        ]
        assert active == [], f"Active fastmcp imports found:\n" + "\n".join(active)

    def test_no_active_creational_common_import(self) -> None:
        """No active 'from creational.common' import in source."""
        result = subprocess.run(
            ["grep", "-rn", "from creational.common", str(SRC_ROOT), "--include=*.py"],
            capture_output=True,
            text=True,
        )
        active = [
            line
            for line in result.stdout.strip().splitlines()
            if line and "# REMOVED" not in line
        ]
        assert active == [], f"Active creational.common imports found:\n" + "\n".join(active)

    def test_no_active_mcp_server_auth_import(self) -> None:
        """No active 'from mcp.server.auth' import in source."""
        result = subprocess.run(
            ["grep", "-rn", "from mcp.server.auth", str(SRC_ROOT), "--include=*.py"],
            capture_output=True,
            text=True,
        )
        active = [
            line
            for line in result.stdout.strip().splitlines()
            if line and "# REMOVED" not in line
        ]
        assert active == [], f"Active mcp.server.auth imports found:\n" + "\n".join(active)

    def test_no_active_schema_db_models_import(self) -> None:
        """No active 'from schema.db_models' import in source."""
        result = subprocess.run(
            ["grep", "-rn", "from schema.db_models", str(SRC_ROOT), "--include=*.py"],
            capture_output=True,
            text=True,
        )
        active = [
            line
            for line in result.stdout.strip().splitlines()
            if line and "# REMOVED" not in line
        ]
        assert active == [], f"Active schema.db_models imports found:\n" + "\n".join(active)


# ============================================================================
# Test: All subpackages import cleanly at runtime
# ============================================================================


class TestSubpackageImports:
    """Verify all subpackages import without ModuleNotFoundError."""

    def test_import_db_adapter(self) -> None:
        """Top-level 'import db_adapter' succeeds."""
        import db_adapter

        assert hasattr(db_adapter, "__version__")

    def test_import_config_models(self) -> None:
        """Config models importable from canonical location."""
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        assert DatabaseProfile is not None
        assert DatabaseConfig is not None

    def test_import_schema_models(self) -> None:
        """Schema models importable from canonical location."""
        from db_adapter.schema.models import (
            ColumnDiff,
            ColumnSchema,
            ConnectionResult,
            SchemaValidationResult,
        )

        assert ColumnDiff is not None
        assert ColumnSchema is not None
        assert ConnectionResult is not None
        assert SchemaValidationResult is not None

    def test_import_backup_models(self) -> None:
        """Backup models importable from canonical location."""
        from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef

        assert BackupSchema is not None
        assert TableDef is not None
        assert ForeignKey is not None

    def test_import_adapters_package(self) -> None:
        """Adapters package exports DatabaseClient and AsyncPostgresAdapter."""
        from db_adapter.adapters import AsyncPostgresAdapter, DatabaseClient

        assert DatabaseClient is not None
        assert AsyncPostgresAdapter is not None

    def test_import_adapters_base(self) -> None:
        """Protocol importable from db_adapter.adapters.base."""
        from db_adapter.adapters.base import DatabaseClient

        assert DatabaseClient is not None

    def test_import_adapters_postgres(self) -> None:
        """AsyncPostgresAdapter importable from db_adapter.adapters.postgres."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert AsyncPostgresAdapter is not None

    def test_import_adapters_supabase(self) -> None:
        """AsyncSupabaseAdapter importable from db_adapter.adapters.supabase."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        assert AsyncSupabaseAdapter is not None

    def test_import_config_loader(self) -> None:
        """Config loader importable."""
        from db_adapter.config.loader import load_db_config

        assert callable(load_db_config)

    def test_import_factory(self) -> None:
        """Factory module imports cleanly."""
        from db_adapter.factory import (
            ProfileNotFoundError,
            connect_and_validate,
            get_active_profile_name,
            get_adapter,
            read_profile_lock,
            write_profile_lock,
        )

        assert callable(connect_and_validate)
        assert callable(get_adapter)
        assert callable(read_profile_lock)
        assert callable(write_profile_lock)

    def test_import_schema_comparator(self) -> None:
        """Schema comparator imports cleanly."""
        from db_adapter.schema.comparator import validate_schema

        assert callable(validate_schema)

    def test_import_schema_introspector(self) -> None:
        """Schema introspector imports cleanly."""
        from db_adapter.schema.introspector import SchemaIntrospector

        assert SchemaIntrospector is not None

    def test_import_schema_fix(self) -> None:
        """Schema fix module imports cleanly."""
        from db_adapter.schema.fix import FixPlan, FixResult, apply_fixes, generate_fix_plan

        assert callable(generate_fix_plan)
        assert callable(apply_fixes)

    def test_import_schema_sync(self) -> None:
        """Schema sync module imports cleanly."""
        from db_adapter.schema.sync import SyncResult, compare_profiles, sync_data

        assert callable(compare_profiles)
        assert callable(sync_data)

    def test_import_backup_restore(self) -> None:
        """Backup/restore module imports cleanly."""
        from db_adapter.backup.backup_restore import (
            backup_database,
            restore_database,
            validate_backup,
        )

        assert callable(backup_database)
        assert callable(restore_database)
        assert callable(validate_backup)

    def test_import_cli_module(self) -> None:
        """CLI module imports cleanly."""
        from db_adapter.cli import main

        assert callable(main)

    def test_import_cli_backup(self) -> None:
        """CLI backup module imports cleanly."""
        from db_adapter.cli.backup import main as backup_main

        assert callable(backup_main)


# ============================================================================
# Test: adapters/__init__.py references correct module names
# ============================================================================


class TestAdaptersInitCorrectness:
    """Verify adapters/__init__.py imports from correct module names."""

    def test_imports_from_postgres_not_postgres_adapter(self) -> None:
        """adapters/__init__.py must import from db_adapter.adapters.postgres,
        not db_adapter.adapters.postgres_adapter."""
        init_path = SRC_ROOT / "adapters" / "__init__.py"
        content = init_path.read_text()
        assert "postgres_adapter" not in content, (
            "adapters/__init__.py still references 'postgres_adapter' module name"
        )
        assert "db_adapter.adapters.postgres" in content

    def test_imports_from_db_adapter_adapters_base(self) -> None:
        """adapters/__init__.py must import from db_adapter.adapters.base."""
        init_path = SRC_ROOT / "adapters" / "__init__.py"
        content = init_path.read_text()
        assert "db_adapter.adapters.base" in content


# ============================================================================
# Test: sys.path workaround removed from cli/backup.py
# ============================================================================


class TestSysPathRemoved:
    """Verify sys.path.insert workaround is removed."""

    def test_no_sys_path_insert_in_cli_backup(self) -> None:
        """cli/backup.py must not have sys.path.insert workaround."""
        backup_path = SRC_ROOT / "cli" / "backup.py"
        content = backup_path.read_text()
        assert "sys.path.insert" not in content, (
            "cli/backup.py still has sys.path.insert workaround"
        )


# ============================================================================
# Test: Model import canonical locations updated correctly
# ============================================================================


class TestModelImportLocations:
    """Verify that files importing models point to canonical locations."""

    def test_factory_imports_database_profile_from_config(self) -> None:
        """factory.py imports DatabaseProfile from db_adapter.config.models."""
        factory_path = SRC_ROOT / "factory.py"
        content = factory_path.read_text()
        assert "from db_adapter.config.models import DatabaseProfile" in content

    def test_factory_imports_connection_result_from_schema(self) -> None:
        """factory.py imports ConnectionResult from db_adapter.schema.models."""
        factory_path = SRC_ROOT / "factory.py"
        content = factory_path.read_text()
        assert "from db_adapter.schema.models import ConnectionResult" in content

    def test_introspector_imports_from_db_adapter_schema_models(self) -> None:
        """introspector.py uses db_adapter.schema.models imports."""
        introspector_path = SRC_ROOT / "schema" / "introspector.py"
        content = introspector_path.read_text()
        assert "from db_adapter.schema.models import" in content
        assert "from schema.models import" not in content

    def test_comparator_imports_from_db_adapter_schema_models(self) -> None:
        """comparator.py uses db_adapter.schema.models imports."""
        comparator_path = SRC_ROOT / "schema" / "comparator.py"
        content = comparator_path.read_text()
        assert "from db_adapter.schema.models import" in content

    def test_config_loader_imports_from_db_adapter_config_models(self) -> None:
        """config/loader.py imports from db_adapter.config.models."""
        loader_path = SRC_ROOT / "config" / "loader.py"
        content = loader_path.read_text()
        assert "from db_adapter.config.models import DatabaseConfig, DatabaseProfile" in content

"""Tests for package exports and public API (Step 13).

Verifies that all __init__.py files export the expected names, that
__all__ lists are defined and accurate, and that top-level convenience
imports work correctly.
"""

import importlib
import types


# ============================================================================
# Top-level package exports
# ============================================================================


class TestTopLevelExports:
    """Tests for src/db_adapter/__init__.py exports."""

    def test_version_defined(self) -> None:
        """Package __version__ is defined and is a string."""
        import db_adapter

        assert hasattr(db_adapter, "__version__")
        assert isinstance(db_adapter.__version__, str)
        assert db_adapter.__version__ == "0.1.0"

    def test_all_defined(self) -> None:
        """Package __all__ is defined and is a list."""
        import db_adapter

        assert hasattr(db_adapter, "__all__")
        assert isinstance(db_adapter.__all__, list)
        assert len(db_adapter.__all__) > 0

    def test_all_names_are_importable(self) -> None:
        """Every name in __all__ is actually accessible on the module."""
        import db_adapter

        for name in db_adapter.__all__:
            assert hasattr(db_adapter, name), (
                f"'{name}' is in __all__ but not accessible on db_adapter"
            )

    def test_adapter_exports(self) -> None:
        """DatabaseClient and AsyncPostgresAdapter importable from top level."""
        from db_adapter import AsyncPostgresAdapter, DatabaseClient

        assert isinstance(DatabaseClient, type)
        assert isinstance(AsyncPostgresAdapter, type)

    def test_config_exports(self) -> None:
        """Config models importable from top level."""
        from db_adapter import DatabaseConfig, DatabaseProfile, load_db_config

        assert isinstance(DatabaseProfile, type)
        assert isinstance(DatabaseConfig, type)
        assert callable(load_db_config)

    def test_factory_exports(self) -> None:
        """Factory functions and errors importable from top level."""
        from db_adapter import (
            ProfileNotFoundError,
            connect_and_validate,
            get_adapter,
            resolve_url,
        )

        assert callable(get_adapter)
        assert callable(connect_and_validate)
        assert callable(resolve_url)
        assert issubclass(ProfileNotFoundError, Exception)

    def test_schema_exports(self) -> None:
        """validate_schema importable from top level."""
        from db_adapter import validate_schema

        assert callable(validate_schema)

    def test_backup_model_exports(self) -> None:
        """Backup models importable from top level."""
        from db_adapter import BackupSchema, ForeignKey, TableDef

        assert isinstance(BackupSchema, type)
        assert isinstance(TableDef, type)
        assert isinstance(ForeignKey, type)

    def test_optional_supabase_no_error(self) -> None:
        """Importing db_adapter does not error even if supabase is optional."""
        import db_adapter

        # If supabase is installed, it should be in __all__
        # If not installed, it should not be in __all__ and should not error
        # Either way, the import should succeed (already tested by importing above)
        assert db_adapter is not None

    def test_supabase_conditional_export(self) -> None:
        """AsyncSupabaseAdapter is in __all__ only if supabase is installed."""
        import db_adapter

        try:
            import supabase  # noqa: F401

            supabase_available = True
        except ImportError:
            supabase_available = False

        if supabase_available:
            assert "AsyncSupabaseAdapter" in db_adapter.__all__
            assert hasattr(db_adapter, "AsyncSupabaseAdapter")
        else:
            assert "AsyncSupabaseAdapter" not in db_adapter.__all__


# ============================================================================
# Adapters subpackage exports
# ============================================================================


class TestAdaptersSubpackageExports:
    """Tests for db_adapter/adapters/__init__.py exports."""

    def test_all_defined(self) -> None:
        """adapters.__all__ is defined."""
        from db_adapter import adapters

        assert hasattr(adapters, "__all__")
        assert isinstance(adapters.__all__, list)

    def test_all_names_are_importable(self) -> None:
        """Every name in adapters.__all__ is accessible."""
        from db_adapter import adapters

        for name in adapters.__all__:
            assert hasattr(adapters, name), (
                f"'{name}' is in adapters.__all__ but not accessible"
            )

    def test_required_exports(self) -> None:
        """DatabaseClient and AsyncPostgresAdapter always in adapters.__all__."""
        from db_adapter import adapters

        assert "DatabaseClient" in adapters.__all__
        assert "AsyncPostgresAdapter" in adapters.__all__

    def test_import_from_subpackage(self) -> None:
        """Direct import from adapters subpackage works."""
        from db_adapter.adapters import AsyncPostgresAdapter, DatabaseClient

        assert isinstance(DatabaseClient, type)
        assert isinstance(AsyncPostgresAdapter, type)


# ============================================================================
# Config subpackage exports
# ============================================================================


class TestConfigSubpackageExports:
    """Tests for db_adapter/config/__init__.py exports."""

    def test_all_defined(self) -> None:
        """config.__all__ is defined."""
        from db_adapter import config

        assert hasattr(config, "__all__")
        assert isinstance(config.__all__, list)

    def test_all_names_are_importable(self) -> None:
        """Every name in config.__all__ is accessible."""
        from db_adapter import config

        for name in config.__all__:
            assert hasattr(config, name), (
                f"'{name}' is in config.__all__ but not accessible"
            )

    def test_required_exports(self) -> None:
        """Expected names are in config.__all__."""
        from db_adapter import config

        expected = {"load_db_config", "DatabaseProfile", "DatabaseConfig"}
        assert expected.issubset(set(config.__all__))

    def test_import_from_subpackage(self) -> None:
        """Direct import from config subpackage works."""
        from db_adapter.config import DatabaseConfig, DatabaseProfile, load_db_config

        assert isinstance(DatabaseProfile, type)
        assert isinstance(DatabaseConfig, type)
        assert callable(load_db_config)


# ============================================================================
# Schema subpackage exports
# ============================================================================


class TestSchemaSubpackageExports:
    """Tests for db_adapter/schema/__init__.py exports."""

    def test_all_defined(self) -> None:
        """schema.__all__ is defined."""
        from db_adapter import schema

        assert hasattr(schema, "__all__")
        assert isinstance(schema.__all__, list)

    def test_all_names_are_importable(self) -> None:
        """Every name in schema.__all__ is accessible."""
        from db_adapter import schema

        for name in schema.__all__:
            assert hasattr(schema, name), (
                f"'{name}' is in schema.__all__ but not accessible"
            )

    def test_required_exports(self) -> None:
        """Expected names are in schema.__all__."""
        from db_adapter import schema

        expected = {
            "validate_schema",
            "SchemaIntrospector",
            "SchemaValidationResult",
            "ColumnDiff",
            "ConnectionResult",
            "ColumnSchema",
            "ConstraintSchema",
            "IndexSchema",
            "TriggerSchema",
            "FunctionSchema",
            "TableSchema",
            "DatabaseSchema",
            "compare_profiles",
            "sync_data",
            "SyncResult",
            "generate_fix_plan",
            "apply_fixes",
            "FixPlan",
            "FixResult",
            "ColumnFix",
            "TableFix",
        }
        actual = set(schema.__all__)
        missing = expected - actual
        assert not missing, f"Missing from schema.__all__: {missing}"

    def test_import_comparator(self) -> None:
        """validate_schema importable from schema subpackage."""
        from db_adapter.schema import validate_schema

        assert callable(validate_schema)

    def test_import_introspector(self) -> None:
        """SchemaIntrospector importable from schema subpackage."""
        from db_adapter.schema import SchemaIntrospector

        assert isinstance(SchemaIntrospector, type)

    def test_import_models(self) -> None:
        """Schema models importable from schema subpackage."""
        from db_adapter.schema import (
            ColumnDiff,
            ColumnSchema,
            ConnectionResult,
            ConstraintSchema,
            DatabaseSchema,
            FunctionSchema,
            IndexSchema,
            SchemaValidationResult,
            TableSchema,
            TriggerSchema,
        )

        for cls in [
            ColumnDiff,
            ColumnSchema,
            ConnectionResult,
            ConstraintSchema,
            DatabaseSchema,
            FunctionSchema,
            IndexSchema,
            SchemaValidationResult,
            TableSchema,
            TriggerSchema,
        ]:
            assert isinstance(cls, type)

    def test_import_fix(self) -> None:
        """Fix module exports importable from schema subpackage."""
        from db_adapter.schema import (
            ColumnFix,
            FixPlan,
            FixResult,
            TableFix,
            apply_fixes,
            generate_fix_plan,
        )

        assert callable(generate_fix_plan)
        assert callable(apply_fixes)
        assert isinstance(FixResult, type)
        # ColumnFix, TableFix, FixPlan are dataclasses (type)
        assert isinstance(ColumnFix, type)
        assert isinstance(TableFix, type)
        assert isinstance(FixPlan, type)

    def test_import_sync(self) -> None:
        """Sync module exports importable from schema subpackage."""
        from db_adapter.schema import SyncResult, compare_profiles, sync_data

        assert callable(compare_profiles)
        assert callable(sync_data)
        assert isinstance(SyncResult, type)


# ============================================================================
# Backup subpackage exports
# ============================================================================


class TestBackupSubpackageExports:
    """Tests for db_adapter/backup/__init__.py exports."""

    def test_all_defined(self) -> None:
        """backup.__all__ is defined."""
        from db_adapter import backup

        assert hasattr(backup, "__all__")
        assert isinstance(backup.__all__, list)

    def test_all_names_are_importable(self) -> None:
        """Every name in backup.__all__ is accessible."""
        from db_adapter import backup

        for name in backup.__all__:
            assert hasattr(backup, name), (
                f"'{name}' is in backup.__all__ but not accessible"
            )

    def test_required_exports(self) -> None:
        """Expected names are in backup.__all__."""
        from db_adapter import backup

        expected = {
            "BackupSchema",
            "TableDef",
            "ForeignKey",
            "backup_database",
            "restore_database",
            "validate_backup",
        }
        actual = set(backup.__all__)
        missing = expected - actual
        assert not missing, f"Missing from backup.__all__: {missing}"

    def test_import_models(self) -> None:
        """Backup models importable from backup subpackage."""
        from db_adapter.backup import BackupSchema, ForeignKey, TableDef

        assert isinstance(BackupSchema, type)
        assert isinstance(TableDef, type)
        assert isinstance(ForeignKey, type)

    def test_import_functions(self) -> None:
        """Backup functions importable from backup subpackage."""
        from db_adapter.backup import (
            backup_database,
            restore_database,
            validate_backup,
        )

        assert callable(backup_database)
        assert callable(restore_database)
        assert callable(validate_backup)


# ============================================================================
# CLI subpackage (not in public API, but verify it's importable)
# ============================================================================


class TestCliSubpackageImportable:
    """Tests that cli subpackage is importable without errors."""

    def test_cli_module_importable(self) -> None:
        """CLI module can be imported without errors."""
        from db_adapter import cli

        assert isinstance(cli, types.ModuleType)

    def test_cli_main_callable(self) -> None:
        """CLI main() function is accessible."""
        from db_adapter.cli import main

        assert callable(main)


# ============================================================================
# Cross-package consistency
# ============================================================================


class TestCrossPackageConsistency:
    """Verify names resolve to the same objects via different import paths."""

    def test_database_client_same_object(self) -> None:
        """DatabaseClient from top-level is same as from adapters."""
        from db_adapter import DatabaseClient as top
        from db_adapter.adapters import DatabaseClient as sub
        from db_adapter.adapters.base import DatabaseClient as mod

        assert top is sub
        assert sub is mod

    def test_async_postgres_adapter_same_object(self) -> None:
        """AsyncPostgresAdapter from top-level is same as from adapters."""
        from db_adapter import AsyncPostgresAdapter as top
        from db_adapter.adapters import AsyncPostgresAdapter as sub
        from db_adapter.adapters.postgres import AsyncPostgresAdapter as mod

        assert top is sub
        assert sub is mod

    def test_database_profile_same_object(self) -> None:
        """DatabaseProfile from top-level is same as from config."""
        from db_adapter import DatabaseProfile as top
        from db_adapter.config import DatabaseProfile as sub
        from db_adapter.config.models import DatabaseProfile as mod

        assert top is sub
        assert sub is mod

    def test_validate_schema_same_object(self) -> None:
        """validate_schema from top-level is same as from schema."""
        from db_adapter import validate_schema as top
        from db_adapter.schema import validate_schema as sub
        from db_adapter.schema.comparator import validate_schema as mod

        assert top is sub
        assert sub is mod

    def test_backup_schema_same_object(self) -> None:
        """BackupSchema from top-level is same as from backup."""
        from db_adapter import BackupSchema as top
        from db_adapter.backup import BackupSchema as sub
        from db_adapter.backup.models import BackupSchema as mod

        assert top is sub
        assert sub is mod

    def test_load_db_config_same_object(self) -> None:
        """load_db_config from top-level is same as from config."""
        from db_adapter import load_db_config as top
        from db_adapter.config import load_db_config as sub
        from db_adapter.config.loader import load_db_config as mod

        assert top is sub
        assert sub is mod

    def test_profile_not_found_error_same_object(self) -> None:
        """ProfileNotFoundError from top-level is same as from factory."""
        from db_adapter import ProfileNotFoundError as top
        from db_adapter.factory import ProfileNotFoundError as mod

        assert top is mod


# ============================================================================
# No circular imports
# ============================================================================


class TestNoCircularImports:
    """Verify importing subpackages in any order does not cause circular imports."""

    def test_import_order_schema_then_backup(self) -> None:
        """Importing schema then backup does not error."""
        importlib.reload(importlib.import_module("db_adapter.schema"))
        importlib.reload(importlib.import_module("db_adapter.backup"))

    def test_import_order_backup_then_schema(self) -> None:
        """Importing backup then schema does not error."""
        importlib.reload(importlib.import_module("db_adapter.backup"))
        importlib.reload(importlib.import_module("db_adapter.schema"))

    def test_import_order_config_then_factory(self) -> None:
        """Importing config then factory does not error."""
        importlib.reload(importlib.import_module("db_adapter.config"))
        importlib.reload(importlib.import_module("db_adapter.factory"))

    def test_import_all_subpackages(self) -> None:
        """All subpackages can be imported together."""
        from db_adapter import adapters, backup, cli, config, schema  # noqa: F401

        assert adapters is not None
        assert config is not None
        assert schema is not None
        assert backup is not None
        assert cli is not None

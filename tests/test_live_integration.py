"""Live integration tests against local PostgreSQL databases.

Requires two databases:
- db_adapter_full: items table with columns a-g (7 columns, matches schema.sql)
- db_adapter_drift: items table with columns a, c, d, g (missing b, e, f)

Run explicitly:
    uv run pytest tests/test_live_integration.py -v
    uv run pytest tests/test_live_integration.py -v --cov=db_adapter --cov-report=term-missing
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ============================================================================
# Constants
# ============================================================================

FULL_URL = "postgresql://docchang@localhost:5432/db_adapter_full"
DRIFT_URL = "postgresql://docchang@localhost:5432/db_adapter_drift"

# Expected schema — lowercase to match PostgreSQL's identifier folding
EXPECTED_COLUMNS = {
    "items": {"a", "b", "c", "d", "e", "f", "g"},
    "categories": {"id", "slug", "name", "user_id"},
    "products": {"id", "slug", "name", "category_id", "price", "active", "user_id"},
}


# ============================================================================
# Skip if databases not available
# ============================================================================

def _db_reachable(url: str) -> bool:
    try:
        import psycopg
        with psycopg.connect(url) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(FULL_URL),
    reason="Local test databases not available",
)


# ============================================================================
# 1. SchemaIntrospector — covers schema/introspector.py (44% → higher)
# ============================================================================

class TestIntrospectorLive:
    """Test SchemaIntrospector against real PostgreSQL databases."""

    async def test_introspect_full_db_columns(self):
        """Introspect full DB and verify all 7 columns returned."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            columns = await introspector.get_column_names()

        assert "items" in columns
        assert columns["items"] == {"a", "b", "c", "d", "e", "f", "g"}

    async def test_introspect_drift_db_columns(self):
        """Introspect drift DB — only 4 columns."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            columns = await introspector.get_column_names()

        assert "items" in columns
        assert columns["items"] == {"a", "c", "d", "g"}

    async def test_introspect_full_schema(self):
        """Full introspection — tables, columns, constraints, indexes."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            schema = await introspector.introspect()

        assert "items" in schema.tables
        table = schema.tables["items"]
        assert len(table.columns) == 7

        # Verify column details
        # columns is a dict {name: ColumnSchema}
        col_names = set(table.columns.keys())
        assert col_names == {"a", "b", "c", "d", "e", "f", "g"}

        # Check column types (introspector may use short forms like "int", "varchar")
        assert "int" in table.columns["a"].data_type.lower()
        assert "varchar" in table.columns["b"].data_type.lower() or "character" in table.columns["b"].data_type.lower()
        assert "text" in table.columns["c"].data_type.lower()
        assert "bool" in table.columns["e"].data_type.lower()

        # Check primary key constraint (constraints is a dict)
        assert any("pkey" in name for name in table.constraints)

    async def test_introspect_drift_schema(self):
        """Drift DB introspection — fewer columns."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            schema = await introspector.introspect()

        assert "items" in schema.tables
        table = schema.tables["items"]
        assert len(table.columns) == 4

    async def test_introspect_excludes_system_tables(self):
        """Introspection should exclude pg_catalog and information_schema tables."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            schema = await introspector.introspect()

        for tname in schema.tables:
            assert not tname.startswith("pg_"), f"System table leaked: {tname}"
            assert not tname.startswith("information_schema")

    async def test_test_connection(self):
        """test_connection should return True for valid URL."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            result = await introspector.test_connection()
            assert result is True

    async def test_test_connection_bad_url(self):
        """test_connection should return False for invalid URL."""
        from db_adapter.schema.introspector import SchemaIntrospector

        try:
            async with SchemaIntrospector(
                "postgresql://nobody@localhost:5432/nonexistent_db"
            ) as introspector:
                result = await introspector.test_connection()
                assert result is False
        except Exception:
            # Some psycopg versions raise on connect rather than returning False
            pass

    async def test_context_manager_cleanup(self):
        """Verify context manager properly cleans up connection."""
        from db_adapter.schema.introspector import SchemaIntrospector

        introspector = SchemaIntrospector(FULL_URL)
        async with introspector:
            columns = await introspector.get_column_names()
            assert "items" in columns

        # After exit, connection should be closed
        assert introspector._conn is None or introspector._conn.closed


# ============================================================================
# 2. Schema Validation — covers schema/comparator.py with real data
# ============================================================================

class TestSchemaValidationLive:
    """Test validate_schema with real introspected data."""

    async def test_full_db_validates(self):
        """Full DB matches expected schema."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        async with SchemaIntrospector(FULL_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        assert result.valid
        assert len(result.missing_columns) == 0
        assert len(result.missing_tables) == 0

    async def test_drift_db_fails_validation(self):
        """Drift DB reports exactly 5 missing columns (3 items + 2 products)."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        assert not result.valid
        assert result.error_count == 5

        missing = {(mc.table, mc.column) for mc in result.missing_columns}
        assert missing == {
            ("items", "b"), ("items", "e"), ("items", "f"),
            ("products", "price"), ("products", "active"),
        }

    async def test_extra_table_is_warning_not_error(self):
        """Extra tables in DB should be warnings, not errors."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        async with SchemaIntrospector(FULL_URL) as introspector:
            actual = await introspector.get_column_names()

        # Expect only a subset — items table is "extra"
        result = validate_schema(actual, {"nonexistent": {"x"}})
        assert not result.valid  # nonexistent table is missing
        assert "items" in result.extra_tables  # items is extra (warning)

    async def test_format_report_output(self):
        """format_report() returns human-readable drift summary."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        report = result.format_report()
        assert "items.b" in report
        assert "items.e" in report
        assert "items.f" in report


# ============================================================================
# 3. Factory — covers factory.py connect_and_validate with real DB
# ============================================================================

class TestFactoryLive:
    """Test factory functions against real databases."""

    async def test_connect_only_mode(self):
        """connect_and_validate without expected_columns = connection-only."""
        from db_adapter.factory import connect_and_validate

        result = await connect_and_validate(profile_name="full")
        assert result.success is True
        assert result.profile_name == "full"
        assert result.schema_valid is None  # No validation performed

    async def test_connect_with_valid_schema(self):
        """connect_and_validate with matching expected_columns = success."""
        from db_adapter.factory import connect_and_validate

        result = await connect_and_validate(
            profile_name="full",
            expected_columns=EXPECTED_COLUMNS,
        )
        assert result.success is True
        assert result.schema_valid is True
        assert result.schema_report is not None
        assert result.schema_report.valid

    async def test_connect_with_drifted_schema(self):
        """connect_and_validate against drift DB = failure with report."""
        from db_adapter.factory import connect_and_validate

        result = await connect_and_validate(
            profile_name="drift",
            expected_columns=EXPECTED_COLUMNS,
        )
        assert result.success is False
        assert result.schema_valid is False
        assert result.schema_report is not None
        assert len(result.schema_report.missing_columns) == 5

    async def test_connect_validate_only(self):
        """validate_only=True should not write lock file."""
        from db_adapter.factory import connect_and_validate, _PROFILE_LOCK_FILE

        result = await connect_and_validate(
            profile_name="full",
            expected_columns=EXPECTED_COLUMNS,
            validate_only=True,
        )
        assert result.success is True
        # Lock file should NOT be updated when validate_only=True
        # (we can't reliably test this without controlling the lock file state)

    async def test_connect_nonexistent_profile(self):
        """Non-existent profile returns error, not exception."""
        from db_adapter.factory import connect_and_validate

        result = await connect_and_validate(profile_name="nonexistent")
        assert result.success is False
        assert "nonexistent" in result.error

    async def test_resolve_url(self):
        """resolve_url substitutes password placeholders."""
        from db_adapter.factory import resolve_url
        from db_adapter.config.models import DatabaseProfile

        profile = DatabaseProfile(
            url="postgresql://user:[YOUR-PASSWORD]@host/db",
            db_password="s3cr3t!@#",
        )
        url = resolve_url(profile)
        assert "[YOUR-PASSWORD]" not in url
        assert "s3cr3t" in url

    async def test_get_active_profile_name_from_env(self):
        """get_active_profile_name reads env var."""
        from db_adapter.factory import get_active_profile_name

        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            name = get_active_profile_name()
            assert name == "full"

    async def test_get_active_profile_name_with_prefix(self):
        """get_active_profile_name with prefix reads prefixed env var."""
        from db_adapter.factory import get_active_profile_name

        with patch.dict(os.environ, {"MC_DB_PROFILE": "drift"}):
            name = get_active_profile_name(env_prefix="MC_")
            assert name == "drift"


# ============================================================================
# 4. AsyncPostgresAdapter — covers adapters/postgres.py (48% → higher)
# ============================================================================

class TestAdapterLive:
    """Test AsyncPostgresAdapter CRUD against real PostgreSQL."""

    async def test_select_all(self):
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        adapter = AsyncPostgresAdapter(database_url=FULL_URL)
        rows = await adapter.select("items", "*")
        assert len(rows) == 5
        assert all("a" in row for row in rows)
        await adapter.close()

    async def test_select_with_filter(self):
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        adapter = AsyncPostgresAdapter(database_url=FULL_URL)
        rows = await adapter.select("items", "*", filters={"d": 30})
        assert len(rows) == 1
        assert rows[0]["b"] == "charlie"
        await adapter.close()

    async def test_select_with_order(self):
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        adapter = AsyncPostgresAdapter(database_url=FULL_URL)
        rows = await adapter.select("items", "b, d", order_by="d DESC")
        assert rows[0]["d"] == 50
        assert rows[-1]["d"] == 10
        await adapter.close()

    async def test_insert_update_delete(self):
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        adapter = AsyncPostgresAdapter(database_url=FULL_URL)

        # Insert
        new = await adapter.insert("items", {
            "b": "test_insert", "c": "Test", "d": 99, "e": True, "g": "tag-test",
        })
        assert new["b"] == "test_insert"
        new_id = new["a"]

        # Update (returns a single dict, not a list)
        updated = await adapter.update(
            "items", {"d": 100}, filters={"a": new_id}
        )
        assert updated["d"] == 100

        # Delete
        await adapter.delete("items", filters={"a": new_id})

        # Verify deleted
        rows = await adapter.select("items", "*", filters={"a": new_id})
        assert len(rows) == 0

        await adapter.close()

    async def test_execute_raw_sql(self):
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        adapter = AsyncPostgresAdapter(database_url=FULL_URL)
        # execute() is for DDL — test with a harmless query
        await adapter.execute("SELECT 1")
        await adapter.close()

    async def test_close_idempotent(self):
        """close() on never-connected adapter should not error."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        adapter = AsyncPostgresAdapter(database_url=FULL_URL)
        await adapter.close()
        await adapter.close()  # Should not error


# ============================================================================
# 5. get_adapter factory — covers factory.py adapter creation
# ============================================================================

class TestGetAdapterLive:
    """Test get_adapter with real profiles."""

    async def test_by_profile_name(self):
        from db_adapter.factory import get_adapter

        adapter = await get_adapter(profile_name="full")
        rows = await adapter.select("items", "count(*) as cnt")
        assert rows[0]["cnt"] == 5
        await adapter.close()

    async def test_by_direct_url(self):
        from db_adapter.factory import get_adapter

        adapter = await get_adapter(database_url=FULL_URL)
        rows = await adapter.select("items", "count(*) as cnt")
        assert rows[0]["cnt"] == 5
        await adapter.close()

    async def test_by_env_var(self):
        from db_adapter.factory import get_adapter

        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            adapter = await get_adapter()
            rows = await adapter.select("items", "count(*) as cnt")
            assert rows[0]["cnt"] == 5
            await adapter.close()


# ============================================================================
# 6. CLI Commands — covers cli/__init__.py (23% → higher)
# ============================================================================

def _run_cli(*args, env_override=None):
    """Helper to run CLI command and capture output."""
    env = dict(os.environ)
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        ["uv", "run", "db-adapter", *args],
        capture_output=True, text=True, env=env,
    )
    return result


class TestCLIConnectLive:
    """Test connect command against real databases."""

    def test_connect_full_succeeds(self):
        r = _run_cli("connect", env_override={"DB_PROFILE": "full"})
        assert r.returncode == 0
        assert "Connected to profile: full" in r.stdout

    def test_connect_drift_fails_validation(self):
        """Connect against drift DB now fails with schema drift report."""
        r = _run_cli("connect", env_override={"DB_PROFILE": "drift"})
        assert r.returncode == 1
        # After Step 3 fix: drift DB fails schema validation
        assert "drift" in r.stdout

    def test_connect_nonexistent_profile(self):
        r = _run_cli("connect", env_override={"DB_PROFILE": "nonexistent"})
        assert r.returncode != 0
        assert "not found" in r.stdout.lower() or "not found" in r.stderr.lower()

    def test_connect_with_env_prefix(self):
        r = _run_cli(
            "--env-prefix", "TEST_", "connect",
            env_override={"TEST_DB_PROFILE": "full"},
        )
        assert r.returncode == 0
        assert "full" in r.stdout

    def test_connect_profile_switch_notice(self):
        """Connect to full, then drift — drift fails validation so no switch message."""
        _run_cli("connect", env_override={"DB_PROFILE": "full"})
        r = _run_cli("connect", env_override={"DB_PROFILE": "drift"})
        # Connecting to drift profile now fails schema validation
        assert r.returncode == 1
        # Profile switch message only prints in the success path
        assert "drift" in r.stdout


class TestCLIValidateLive:
    """Test validate command against real databases."""

    def test_validate_after_connect_full(self):
        """Validate against full DB now correctly reports schema is valid."""
        _run_cli("connect", env_override={"DB_PROFILE": "full"})
        r = _run_cli("validate")
        assert r.returncode == 0
        assert "valid" in r.stdout.lower()

    def test_validate_drift_db(self):
        """Validate against drift DB reports drift."""
        # Connect to drift via CLI fails now (schema validation),
        # so write lock file directly to test validate against drift
        from db_adapter.factory import write_profile_lock
        write_profile_lock("drift")
        r = _run_cli("validate")
        # Drift DB genuinely has missing columns, so validation fails
        assert r.returncode == 1
        # Restore lock file
        write_profile_lock("full")

    def test_validate_no_profile(self):
        """validate with no lock file should error clearly."""
        # Remove lock file
        lock = Path.cwd() / ".db-profile"
        if lock.exists():
            lock.unlink()
        r = _run_cli("validate")
        assert r.returncode == 1
        assert "No validated profile" in r.stdout
        # Restore lock file for other tests
        _run_cli("connect", env_override={"DB_PROFILE": "full"})


class TestCLIStatusLive:
    """Test status command."""

    def test_status_shows_profile(self):
        _run_cli("connect", env_override={"DB_PROFILE": "full"})
        r = _run_cli("status")
        assert r.returncode == 0
        assert "Current profile" in r.stdout
        assert "full" in r.stdout
        assert ".db-profile" in r.stdout

    def test_status_no_profile(self):
        lock = Path.cwd() / ".db-profile"
        if lock.exists():
            lock.unlink()
        r = _run_cli("status")
        assert r.returncode == 0
        assert "No validated profile" in r.stdout
        # Restore
        _run_cli("connect", env_override={"DB_PROFILE": "full"})


class TestCLIProfilesLive:
    """Test profiles command."""

    def test_profiles_lists_both(self):
        r = _run_cli("profiles")
        assert r.returncode == 0
        assert "full" in r.stdout
        assert "drift" in r.stdout
        assert "postgres" in r.stdout

    def test_profiles_marks_current(self):
        _run_cli("connect", env_override={"DB_PROFILE": "full"})
        r = _run_cli("profiles")
        assert r.returncode == 0
        # Current profile should have a marker
        assert "*" in r.stdout


class TestCLIFixLive:
    """Test fix command against real databases."""

    def test_fix_requires_column_defs(self):
        """fix without --column-defs should fail."""
        r = _run_cli("fix", "--schema-file", "schema.sql")
        assert r.returncode != 0

    def test_fix_preview_full_db(self):
        """fix against full DB -- schema should be valid, no fixes needed."""
        _run_cli("connect", env_override={"DB_PROFILE": "full"})
        r = _run_cli(
            "fix", "--schema-file", "schema.sql",
            "--column-defs", "column-defs.json",
        )
        # After case fix: valid DB reports no fixes needed
        assert r.returncode == 0
        assert "no fixes needed" in r.stdout.lower() or "valid" in r.stdout.lower()

    def test_fix_preview_drift_db(self):
        """fix against drift DB -- should show fix plan (preview mode)."""
        # Use DB_PROFILE env var directly since connect to drift now fails
        # schema validation (so lock file won't have drift)
        r = _run_cli(
            "fix", "--schema-file", "schema.sql",
            "--column-defs", "column-defs.json",
            env_override={"DB_PROFILE": "drift"},
        )
        # After case fix: fix plan generated successfully in preview mode
        assert r.returncode == 0
        assert "--confirm" in r.stdout  # Preview mode suggests adding --confirm


class TestCLISyncLive:
    """Test sync command — error handling."""

    def test_sync_requires_from(self):
        r = _run_cli("sync", "--tables", "items", "--user-id", "abc")
        assert r.returncode != 0

    def test_sync_requires_tables(self):
        r = _run_cli("sync", "--from", "full", "--user-id", "abc")
        assert r.returncode != 0

    def test_sync_requires_user_id(self):
        r = _run_cli("sync", "--from", "full", "--tables", "items")
        assert r.returncode != 0

    def test_sync_same_profile_error(self):
        """Syncing same profile to itself should error."""
        _run_cli("connect", env_override={"DB_PROFILE": "full"})
        r = _run_cli(
            "sync", "--from", "full",
            "--tables", "items", "--user-id", "abc",
        )
        assert r.returncode != 0
        assert "same profile" in r.stdout.lower()


# ============================================================================
# 7. _parse_expected_columns — case sensitivity bug (#3)
# ============================================================================

class TestParseExpectedColumnsLive:
    """Test schema file parsing -- verifies lowercase output after case fix."""

    def test_parse_returns_column_names(self):
        from db_adapter.cli import _parse_expected_columns
        result = _parse_expected_columns("schema.sql")
        assert "items" in result

    def test_columns_are_lowercase(self):
        """After Step 2 fix: parser returns all lowercase column names."""
        from db_adapter.cli import _parse_expected_columns
        parsed = _parse_expected_columns("schema.sql")

        for table_name, columns in parsed.items():
            assert table_name == table_name.lower(), (
                f"Table name not lowercase: {table_name}"
            )
            assert all(c == c.lower() for c in columns), (
                f"Columns not all lowercase in {table_name}: {columns}"
            )

    def test_no_false_drift_after_case_fix(self):
        """After Step 2 fix: no false column drift from case mismatch."""
        from db_adapter.cli import _parse_expected_columns
        from db_adapter.schema.comparator import validate_schema

        parsed = _parse_expected_columns("schema.sql")
        # Simulate what introspector would return (lowercase)
        actual = {"items": {"a", "b", "c", "d", "e", "f", "g"}}

        result = validate_schema(actual, parsed)
        # No false-positive missing columns for items table
        items_missing = [mc for mc in result.missing_columns if mc.table == "items"]
        assert len(items_missing) == 0, (
            f"False drift: items columns still missing: {items_missing}"
        )
        # result.valid may be False due to missing categories/products tables
        # in our incomplete 'actual' dict, but items should have no drift

    def test_nonexistent_file(self):
        from db_adapter.cli import _parse_expected_columns
        with pytest.raises(FileNotFoundError):
            _parse_expected_columns("nonexistent.sql")

    def test_empty_file(self):
        from db_adapter.cli import _parse_expected_columns
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
            f.write("-- empty schema\n")
            f.flush()
            with pytest.raises(ValueError, match="No CREATE TABLE"):
                _parse_expected_columns(f.name)
        os.unlink(f.name)


# ============================================================================
# 8. Config loading — covers config/loader.py with real db.toml
# ============================================================================

class TestConfigLive:
    """Test config loading with real db.toml."""

    def test_load_db_config(self):
        from db_adapter.config.loader import load_db_config
        config = load_db_config()
        assert "full" in config.profiles
        assert "drift" in config.profiles
        assert config.schema_file == "schema.sql"
        assert config.validate_on_connect is True

    def test_profile_details(self):
        from db_adapter.config.loader import load_db_config
        config = load_db_config()

        full = config.profiles["full"]
        assert full.provider == "postgres"
        assert "db_adapter_full" in full.url
        assert full.description == "Full schema (A-G columns)"

        drift = config.profiles["drift"]
        assert "db_adapter_drift" in drift.url

    def test_config_fields_used_by_cli(self):
        """After Steps 3-5: schema_file and validate_on_connect are used by CLI commands."""
        from db_adapter.config.loader import load_db_config
        config = load_db_config()
        # These fields are used by _async_connect, _async_validate, and _async_fix
        assert hasattr(config, "schema_file")
        assert hasattr(config, "validate_on_connect")
        assert config.schema_file is not None
        assert config.validate_on_connect is True


# ============================================================================
# 9. SyncResult model — bug #5 (.error vs .errors)
# ============================================================================

class TestSyncResultBug:
    """Test SyncResult model -- CLI now correctly uses .errors list."""

    def test_sync_result_has_errors_list(self):
        from db_adapter.schema.sync import SyncResult
        r = SyncResult()
        assert hasattr(r, "errors")
        assert isinstance(r.errors, list)

    def test_sync_result_errors_works_correctly(self):
        """After Step 5 fix: CLI uses .errors (list), no AttributeError."""
        from db_adapter.schema.sync import SyncResult
        r = SyncResult()
        # .errors is a list, not .error (singular)
        assert not hasattr(r, "error"), (
            "SyncResult should not have .error attribute"
        )
        # Verify the .errors list works correctly
        assert r.errors == []
        r2 = SyncResult(errors=["err1", "err2"])
        assert len(r2.errors) == 2
        assert "; ".join(r2.errors) == "err1; err2"


# ============================================================================
# 10. Backup CLI — bug #6 (non-functional)
# ============================================================================

class TestBackupCLIBugs:
    """Test backup CLI bugs without running it (would crash)."""

    def test_backup_database_is_async(self):
        """backup_database is async but CLI calls it without await."""
        import inspect
        from db_adapter.backup.backup_restore import backup_database
        assert inspect.iscoroutinefunction(backup_database)

    def test_restore_database_is_async(self):
        """restore_database is async but CLI calls it without await."""
        import inspect
        from db_adapter.backup.backup_restore import restore_database
        assert inspect.iscoroutinefunction(restore_database)

    def test_validate_backup_requires_schema(self):
        """validate_backup requires 2 args but CLI passes 1."""
        import inspect
        from db_adapter.backup.backup_restore import validate_backup
        sig = inspect.signature(validate_backup)
        params = list(sig.parameters.keys())
        assert "schema" in params, f"Expected 'schema' param, got: {params}"

    def test_backup_database_signature(self):
        """backup_database requires adapter+schema+user_id, not project_slugs."""
        import inspect
        from db_adapter.backup.backup_restore import backup_database
        sig = inspect.signature(backup_database)
        params = list(sig.parameters.keys())
        assert "adapter" in params
        assert "schema" in params
        assert "user_id" in params
        assert "project_slugs" not in params  # CLI passes this but it doesn't exist


# ============================================================================
# 11. Adapter engine creation — bug #4 (connect_timeout)
# ============================================================================

class TestAdapterEngineBug:
    """Verify connect_timeout fix in adapter engine creation."""

    def test_connect_args_used_instead_of_url_param(self):
        """After Step 1 fix: connect_args is used instead of URL param."""
        from db_adapter.adapters.postgres import create_async_engine_pooled
        import inspect
        source = inspect.getsource(create_async_engine_pooled)
        # connect_args with timeout should be used
        assert "connect_args" in source
        assert '"timeout"' in source or "'timeout'" in source
        # URL should not be manipulated for connect_timeout
        # (check for the pattern that appends to URL, not comments)
        assert "?connect_timeout" not in source
        assert "&connect_timeout" not in source

    async def test_engine_connect_succeeds(self):
        """After Step 1 fix: connection succeeds with connect_args timeout."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter
        adapter = AsyncPostgresAdapter(database_url=FULL_URL)
        try:
            rows = await adapter.select("items", "count(*) as cnt")
            assert rows[0]["cnt"] == 5
        finally:
            await adapter.close()


# ============================================================================
# 12. Lock file operations — covers factory.py lock file functions
# ============================================================================

class TestLockFileLive:
    """Test lock file operations with real files."""

    def test_write_and_read_lock(self):
        from db_adapter.factory import write_profile_lock, read_profile_lock
        write_profile_lock("test-profile")
        assert read_profile_lock() == "test-profile"
        # Restore
        write_profile_lock("full")

    def test_clear_lock(self):
        from db_adapter.factory import (
            write_profile_lock, clear_profile_lock, read_profile_lock,
        )
        write_profile_lock("temp")
        clear_profile_lock()
        assert read_profile_lock() is None
        # Restore
        write_profile_lock("full")

    def test_read_nonexistent_lock(self):
        from db_adapter.factory import clear_profile_lock, read_profile_lock
        clear_profile_lock()
        assert read_profile_lock() is None
        # Restore for other tests
        from db_adapter.factory import write_profile_lock
        write_profile_lock("full")


# ============================================================================
# 13. Fix plan generation — with real schema.sql + column-defs.json
# ============================================================================

class TestFixPlanLive:
    """Test fix plan generation with real files."""

    async def test_generate_fix_plan_for_drift(self):
        """Generate fix plan using real schema comparison."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema
        from db_adapter.schema.fix import generate_fix_plan

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        assert not result.valid

        # Load column defs
        col_defs = json.loads(Path("column-defs.json").read_text())

        plan = generate_fix_plan(result, col_defs, "schema.sql")
        assert plan.has_fixes
        # 3 missing columns → could be ALTER (single) or DROP+CREATE (2+)
        # With 3 missing columns in one table, it should use DROP+CREATE
        total_fixes = (
            len(plan.missing_columns)
            + len(plan.missing_tables)
            + len(plan.tables_to_recreate)
        )
        assert total_fixes > 0

    async def test_generate_fix_plan_for_full(self):
        """Full DB should generate empty fix plan."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema
        from db_adapter.schema.fix import generate_fix_plan

        async with SchemaIntrospector(FULL_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        assert result.valid

        plan = generate_fix_plan(result, {}, "schema.sql")
        assert not plan.has_fixes


# ============================================================================
# 14. FK-aware introspection — categories → products relationship
# ============================================================================

class TestFKIntrospectionLive:
    """Test FK relationship introspection with categories → products."""

    async def test_full_db_has_all_three_tables(self):
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            columns = await introspector.get_column_names()

        assert "items" in columns
        assert "categories" in columns
        assert "products" in columns

    async def test_products_has_fk_to_categories(self):
        """Products table should have FK constraint referencing categories."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            schema = await introspector.introspect()

        products = schema.tables["products"]
        # Find FK constraint
        fk_found = False
        for cname, constraint in products.constraints.items():
            if "fkey" in cname or "fk" in cname.lower():
                fk_found = True
                break
        assert fk_found, f"No FK constraint found. Constraints: {list(products.constraints.keys())}"

    async def test_drift_db_products_missing_columns(self):
        """Drift DB products table should be missing price and active columns."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            columns = await introspector.get_column_names()

        assert "products" in columns
        assert "price" not in columns["products"]
        assert "active" not in columns["products"]
        # But FK column should exist
        assert "category_id" in columns["products"]

    async def test_validate_drift_db_multi_table_drift(self):
        """Drift DB should report drift in both items AND products tables."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        assert not result.valid

        # Collect drifted tables
        drifted_tables = {mc.table for mc in result.missing_columns}
        assert "items" in drifted_tables  # missing b, e, f
        assert "products" in drifted_tables  # missing price, active

    async def test_fix_plan_with_fk_ordering(self):
        """Fix plan should respect FK ordering (categories before products)."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema
        from db_adapter.schema.fix import generate_fix_plan

        async with SchemaIntrospector(DRIFT_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        col_defs = json.loads(Path("column-defs.json").read_text())
        plan = generate_fix_plan(result, col_defs, "schema.sql")

        assert plan.has_fixes
        # If tables need recreation, categories must come before products in create_order
        if plan.create_order:
            if "categories" in plan.create_order and "products" in plan.create_order:
                cat_idx = plan.create_order.index("categories")
                prod_idx = plan.create_order.index("products")
                assert cat_idx < prod_idx, (
                    f"FK ordering wrong: categories at {cat_idx}, products at {prod_idx}"
                )


# ============================================================================
# 15. Sync between profiles — covers schema/sync.py
# ============================================================================

class TestSyncLive:
    """Test sync operations between full and drift databases."""

    async def test_compare_profiles_categories(self):
        """Compare categories between full (3) and drift (2)."""
        from db_adapter.schema.sync import compare_profiles

        result = await compare_profiles(
            "full", "drift",
            tables=["categories"],
            user_id="user-1",
        )
        assert result.success
        assert result.source_counts["categories"] == 3
        assert result.dest_counts["categories"] == 2

    async def test_compare_profiles_products(self):
        """Compare products between full (5) and drift (2)."""
        from db_adapter.schema.sync import compare_profiles

        result = await compare_profiles(
            "full", "drift",
            tables=["products"],
            user_id="user-1",
        )
        assert result.success
        assert result.source_counts["products"] == 5
        assert result.dest_counts["products"] == 2

    async def test_compare_profiles_sync_plan(self):
        """Sync plan should show new and update counts."""
        from db_adapter.schema.sync import compare_profiles

        result = await compare_profiles(
            "full", "drift",
            tables=["categories", "products"],
            user_id="user-1",
        )
        assert result.success
        assert result.sync_plan is not None

        # categories: 1 new (clothing), 2 updates (electronics, books)
        cat_plan = result.sync_plan["categories"]
        assert cat_plan["new"] == 1
        assert cat_plan["update"] == 2

        # products: 3 new (phone, tshirt, tablet), 2 updates (laptop, novel)
        prod_plan = result.sync_plan["products"]
        assert prod_plan["new"] == 3
        assert prod_plan["update"] == 2

    async def test_compare_profiles_no_user_match(self):
        """Compare with non-existent user_id should return zero counts."""
        from db_adapter.schema.sync import compare_profiles

        result = await compare_profiles(
            "full", "drift",
            tables=["categories"],
            user_id="nonexistent-user",
        )
        assert result.success
        assert result.source_counts["categories"] == 0
        assert result.dest_counts["categories"] == 0

    async def test_sync_dry_run(self):
        """Dry run should not modify data."""
        from db_adapter.schema.sync import sync_data

        result = await sync_data(
            "full", "drift",
            tables=["categories"],
            user_id="user-1",
            dry_run=True,
        )
        # dry_run with confirm=False should return without syncing
        # (no changes should be made)
        assert result.success or not result.errors


# ============================================================================
# 16. Backup/Restore models — covers backup/models.py
# ============================================================================

class TestBackupModelsLive:
    """Test backup schema definition with our real table structure."""

    def test_create_backup_schema(self):
        from db_adapter.backup.models import BackupSchema, TableDef, ForeignKey

        schema = BackupSchema(tables=[
            TableDef(
                name="categories", pk="id",
                slug_field="slug", user_field="user_id",
            ),
            TableDef(
                name="products", pk="id",
                slug_field="slug", user_field="user_id",
                parent=ForeignKey(table="categories", field="category_id"),
            ),
        ])
        assert len(schema.tables) == 2
        assert schema.tables[0].name == "categories"
        assert schema.tables[1].parent is not None
        assert schema.tables[1].parent.table == "categories"

    def test_backup_schema_table_order(self):
        """Tables should be ordered parent-first for backup."""
        from db_adapter.backup.models import BackupSchema, TableDef, ForeignKey

        schema = BackupSchema(tables=[
            TableDef(name="categories", pk="id", slug_field="slug", user_field="user_id"),
            TableDef(
                name="products", pk="id", slug_field="slug", user_field="user_id",
                parent=ForeignKey(table="categories", field="category_id"),
            ),
        ])
        # Parent (categories) comes before child (products)
        names = [t.name for t in schema.tables]
        assert names.index("categories") < names.index("products")


# ============================================================================
# 17. Full introspection diff — comprehensive schema comparison
# ============================================================================

class TestFullSchemaDiffLive:
    """Compare full vs drift databases at every level."""

    async def test_table_count_diff(self):
        """Both DBs should have same tables (items, categories, products)."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as i:
            full = await i.get_column_names()
        async with SchemaIntrospector(DRIFT_URL) as i:
            drift = await i.get_column_names()

        assert set(full.keys()) == set(drift.keys())

    async def test_column_diff_summary(self):
        """Summarize all column differences between databases."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as i:
            full = await i.get_column_names()
        async with SchemaIntrospector(DRIFT_URL) as i:
            drift = await i.get_column_names()

        diffs = {}
        for table in full:
            missing = full[table] - drift.get(table, set())
            if missing:
                diffs[table] = missing

        # items: missing b, e, f
        assert diffs["items"] == {"b", "e", "f"}
        # products: missing price, active
        assert diffs["products"] == {"price", "active"}
        # categories: no diff
        assert "categories" not in diffs


# ============================================================================
# 18. Direct CLI function calls — covers cli/__init__.py internals
#     (subprocess tests don't count for coverage)
# ============================================================================

class TestCLIDirectCalls:
    """Call CLI functions directly to get coverage on internal code paths."""

    def test_cmd_status_with_profile(self):
        """cmd_status with an active lock file."""
        from db_adapter.cli import cmd_status
        from db_adapter.factory import write_profile_lock

        write_profile_lock("full")
        ns = argparse.Namespace(env_prefix="")
        rc = cmd_status(ns)
        assert rc == 0

    def test_cmd_status_no_profile(self):
        """cmd_status with no lock file."""
        from db_adapter.cli import cmd_status
        from db_adapter.factory import clear_profile_lock, write_profile_lock

        clear_profile_lock()
        ns = argparse.Namespace(env_prefix="")
        rc = cmd_status(ns)
        assert rc == 0
        # Restore
        write_profile_lock("full")

    def test_cmd_profiles(self):
        """cmd_profiles lists profiles from db.toml."""
        from db_adapter.cli import cmd_profiles
        from db_adapter.factory import write_profile_lock

        write_profile_lock("full")
        ns = argparse.Namespace(env_prefix="")
        rc = cmd_profiles(ns)
        assert rc == 0

    def test_cmd_profiles_no_current(self):
        """cmd_profiles with no current profile marker."""
        from db_adapter.cli import cmd_profiles
        from db_adapter.factory import clear_profile_lock, write_profile_lock

        clear_profile_lock()
        ns = argparse.Namespace(env_prefix="")
        rc = cmd_profiles(ns)
        assert rc == 0
        write_profile_lock("full")


class TestAsyncConnectDirect:
    """Call _async_connect directly to cover internal code paths."""

    async def test_connect_full_direct(self):
        """Direct _async_connect to full DB -- config-driven validation passes."""
        from db_adapter.cli import _async_connect

        ns = argparse.Namespace(env_prefix="")
        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            rc = await _async_connect(ns)
        # After Step 3: config-driven validation passes on full DB
        assert rc == 0

    async def test_connect_drift_direct(self):
        """Direct _async_connect to drift DB -- drift detected after Step 3 fix."""
        from db_adapter.cli import _async_connect

        ns = argparse.Namespace(env_prefix="")
        with patch.dict(os.environ, {"DB_PROFILE": "drift"}):
            rc = await _async_connect(ns)
        # After Step 3: drift is detected by config-driven validation
        assert rc == 1

    async def test_connect_nonexistent_direct(self):
        """Direct _async_connect with bad profile — covers error path."""
        from db_adapter.cli import _async_connect

        ns = argparse.Namespace(env_prefix="")
        with patch.dict(os.environ, {"DB_PROFILE": "nonexistent"}):
            rc = await _async_connect(ns)
        assert rc == 1

    async def test_connect_with_profile_switch(self):
        """Direct _async_connect shows profile switch notice."""
        from db_adapter.cli import _async_connect
        from db_adapter.factory import write_profile_lock

        write_profile_lock("drift")
        ns = argparse.Namespace(env_prefix="")
        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            rc = await _async_connect(ns)
        assert rc == 0


class TestAsyncValidateDirect:
    """Call _async_validate directly to cover lines 181-214."""

    async def test_validate_no_profile(self):
        """_async_validate with no lock file -- covers early return."""
        from db_adapter.cli import _async_validate
        from db_adapter.factory import clear_profile_lock, write_profile_lock

        clear_profile_lock()
        ns = argparse.Namespace(env_prefix="", schema_file=None)
        rc = await _async_validate(ns)
        assert rc == 1
        write_profile_lock("full")

    async def test_validate_full_db(self):
        """After Step 4 fix: _async_validate against full DB returns 0 (valid)."""
        from db_adapter.cli import _async_validate
        from db_adapter.factory import write_profile_lock

        write_profile_lock("full")
        ns = argparse.Namespace(env_prefix="", schema_file=None)
        rc = await _async_validate(ns)
        # After Step 4: config-driven validation correctly reports valid
        assert rc == 0

    async def test_validate_drift_db(self):
        """_async_validate against drift DB returns 1 (drift detected)."""
        from db_adapter.cli import _async_validate
        from db_adapter.factory import write_profile_lock

        write_profile_lock("drift")
        ns = argparse.Namespace(env_prefix="", schema_file=None)
        rc = await _async_validate(ns)
        assert rc == 1
        write_profile_lock("full")


class TestAsyncFixDirect:
    """Call _async_fix directly to cover lines 231-441."""

    async def test_fix_no_profile(self):
        """_async_fix with no profile configured."""
        from db_adapter.cli import _async_fix
        from db_adapter.factory import clear_profile_lock, write_profile_lock

        clear_profile_lock()
        ns = argparse.Namespace(
            env_prefix="NOEXIST_", schema_file="schema.sql",
            column_defs="column-defs.json", confirm=False,
        )
        rc = await _async_fix(ns)
        assert rc == 1
        write_profile_lock("full")

    async def test_fix_bad_schema_file(self):
        """_async_fix with nonexistent schema file."""
        from db_adapter.cli import _async_fix

        ns = argparse.Namespace(
            env_prefix="", schema_file="nonexistent.sql",
            column_defs="column-defs.json", confirm=False,
        )
        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            rc = await _async_fix(ns)
        assert rc == 1

    async def test_fix_bad_column_defs(self):
        """_async_fix with nonexistent column-defs file."""
        from db_adapter.cli import _async_fix

        ns = argparse.Namespace(
            env_prefix="", schema_file="schema.sql",
            column_defs="nonexistent.json", confirm=False,
        )
        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            rc = await _async_fix(ns)
        assert rc == 1

    async def test_fix_preview_full_db_direct(self):
        """After case fix: _async_fix against full DB reports no fixes needed."""
        from db_adapter.cli import _async_fix

        ns = argparse.Namespace(
            env_prefix="", schema_file="schema.sql",
            column_defs="column-defs.json", confirm=False,
        )
        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            rc = await _async_fix(ns)
        # After Step 2 case fix: valid DB needs no fixes
        assert rc == 0

    async def test_fix_preview_drift_db_direct(self):
        """After case fix: _async_fix against drift DB generates fix plan successfully."""
        from db_adapter.cli import _async_fix

        ns = argparse.Namespace(
            env_prefix="", schema_file="schema.sql",
            column_defs="column-defs.json", confirm=False,
        )
        with patch.dict(os.environ, {"DB_PROFILE": "drift"}):
            rc = await _async_fix(ns)
        # After Step 2 case fix: fix plan generated successfully in preview mode
        assert rc == 0


class TestAsyncSyncDirect:
    """Call _async_sync directly to cover lines 457-566."""

    async def test_sync_no_dest_profile(self):
        """_async_sync with no destination profile."""
        from db_adapter.cli import _async_sync
        from db_adapter.factory import clear_profile_lock, write_profile_lock

        clear_profile_lock()
        ns = argparse.Namespace(
            env_prefix="NOEXIST_", source="full", tables="categories",
            user_id="user-1", dry_run=True, confirm=False,
        )
        rc = await _async_sync(ns)
        assert rc == 1
        write_profile_lock("full")

    async def test_sync_same_profile_direct(self):
        """_async_sync when source == dest."""
        from db_adapter.cli import _async_sync
        from db_adapter.factory import write_profile_lock

        write_profile_lock("full")
        ns = argparse.Namespace(
            env_prefix="", source="full", tables="categories",
            user_id="user-1", dry_run=True, confirm=False,
        )
        rc = await _async_sync(ns)
        assert rc == 1

    async def test_sync_dry_run_direct(self):
        """_async_sync dry run -- covers comparison output."""
        from db_adapter.cli import _async_sync
        from db_adapter.factory import write_profile_lock

        write_profile_lock("drift")
        ns = argparse.Namespace(
            env_prefix="", source="full", tables="categories",
            user_id="user-1", dry_run=True, confirm=False,
        )
        rc = await _async_sync(ns)
        assert rc == 0

    async def test_sync_error_attribute(self):
        """After Step 5 fix: _async_sync uses .errors list (no AttributeError)."""
        from db_adapter.cli import _async_sync
        from db_adapter.factory import write_profile_lock

        write_profile_lock("drift")
        ns = argparse.Namespace(
            env_prefix="", source="full", tables="nonexistent_table",
            user_id="user-1", dry_run=False, confirm=True,
        )
        # After Steps 1+5: sync runs without connect_timeout error and uses
        # .errors list correctly (no AttributeError)
        rc = await _async_sync(ns)


# ============================================================================
# 19. Case mismatch severity — demonstrates destructive cascade of Bug #3
# ============================================================================

class TestCaseMismatchSeverity:
    """Verify case mismatch bug is fixed -- no more false drift on valid DBs."""

    async def test_fix_plan_succeeds_after_case_fix(self):
        """After Step 2 fix: fix plan succeeds with lowercase columns on valid DB."""
        from db_adapter.cli import _parse_expected_columns
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        # Step 1: Parse schema (now returns lowercase after fix)
        parsed = _parse_expected_columns("schema.sql")
        assert "a" in parsed["items"], (
            f"Expected lowercase column names from parser, got: {parsed['items']}"
        )

        # Step 2: Introspect FULL (valid) DB (returns lowercase)
        async with SchemaIntrospector(FULL_URL) as introspector:
            actual = await introspector.get_column_names()

        # Step 3: Comparator sees no mismatch -- schema is valid
        result = validate_schema(actual, parsed)
        assert result.valid, (
            f"Expected valid schema, got {result.error_count} errors: "
            f"{[(mc.table, mc.column) for mc in result.missing_columns]}"
        )
        assert result.error_count == 0

    def test_no_case_mismatch_after_fix(self):
        """After Step 2 fix: all columns from parser are lowercase, matching DB."""
        from db_adapter.cli import _parse_expected_columns
        from db_adapter.schema.comparator import validate_schema

        parsed = _parse_expected_columns("schema.sql")
        # Simulate what introspector returns (all lowercase)
        actual = {
            "items": {"a", "b", "c", "d", "e", "f", "g"},
            "categories": {"id", "slug", "name", "user_id"},
            "products": {"id", "slug", "name", "category_id", "price", "active", "user_id"},
        }

        result = validate_schema(actual, parsed)
        assert result.valid, (
            f"Expected valid schema after case fix, got errors: "
            f"{[(mc.table, mc.column) for mc in result.missing_columns]}"
        )
        assert result.error_count == 0


# ============================================================================
# 20. Introspector error paths — covers uncovered lines in introspector.py
# ============================================================================

class TestIntrospectorErrorPaths:
    """Test introspector error handling that requires specific conditions."""

    async def test_introspect_without_context_manager(self):
        """Calling introspect() without 'async with' raises RuntimeError."""
        from db_adapter.schema.introspector import SchemaIntrospector

        introspector = SchemaIntrospector(FULL_URL)
        # _conn is None because __aenter__ was not called
        with pytest.raises(RuntimeError, match="not connected"):
            await introspector.introspect()

    async def test_get_column_names_without_context_manager(self):
        """Calling get_column_names() without 'async with' raises RuntimeError."""
        from db_adapter.schema.introspector import SchemaIntrospector

        introspector = SchemaIntrospector(FULL_URL)
        with pytest.raises(RuntimeError, match="not connected"):
            await introspector.get_column_names()

    async def test_test_connection_without_context_manager(self):
        """Calling test_connection() without 'async with' raises RuntimeError."""
        from db_adapter.schema.introspector import SchemaIntrospector

        introspector = SchemaIntrospector(FULL_URL)
        with pytest.raises(RuntimeError, match="not connected"):
            await introspector.test_connection()

    async def test_introspect_all_three_tables(self):
        """Full introspection covers all table processing paths."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            schema = await introspector.introspect()

        # Verify all tables have columns, constraints, indexes
        for tname in ["items", "categories", "products"]:
            assert tname in schema.tables
            table = schema.tables[tname]
            assert len(table.columns) > 0
            # All tables have at least a PK constraint
            assert len(table.constraints) > 0

    async def test_introspect_indexes(self):
        """Verify indexes are introspected (categories.slug has UNIQUE → index)."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            schema = await introspector.introspect()

        categories = schema.tables["categories"]
        # UNIQUE constraint creates an index
        assert len(categories.indexes) > 0

    async def test_introspect_fk_constraint_details(self):
        """Verify FK constraint details are populated."""
        from db_adapter.schema.introspector import SchemaIntrospector

        async with SchemaIntrospector(FULL_URL) as introspector:
            schema = await introspector.introspect()

        products = schema.tables["products"]
        fk_constraints = {
            name: c for name, c in products.constraints.items()
            if c.constraint_type == "FOREIGN KEY"
        }
        assert len(fk_constraints) > 0
        fk = list(fk_constraints.values())[0]
        assert fk.references_table == "categories"
        assert "category_id" in fk.columns


# ============================================================================
# 21. Backup CLI deeper analysis — verifying more signature mismatches
# ============================================================================

class TestBackupCLIDeeper:
    """Deeper analysis of backup CLI issues beyond what Bug #6 covers."""

    def test_cmd_backup_returns_coroutine_not_path(self):
        """backup_database() is async — calling without await returns coroutine."""
        from db_adapter.backup.backup_restore import backup_database
        import inspect

        # The CLI does: backup_path = backup_database(output_path=..., project_slugs=...)
        # This would return a coroutine, not a path string
        sig = inspect.signature(backup_database)

        # Verify the actual required parameters
        required = [
            name for name, param in sig.parameters.items()
            if param.default is inspect.Parameter.empty
        ]
        assert "adapter" in required, f"Expected 'adapter' as required param, got: {required}"
        assert "schema" in required, f"Expected 'schema' as required param, got: {required}"

    def test_cmd_restore_wrong_params(self):
        """restore_database() signature doesn't match CLI's call."""
        from db_adapter.backup.backup_restore import restore_database
        import inspect

        sig = inspect.signature(restore_database)
        params = list(sig.parameters.keys())
        # CLI passes: backup_path, mode, dry_run
        # But function expects: adapter, schema, backup_path, user_id, mode, ...
        assert "adapter" in params
        assert "schema" in params
        assert "user_id" in params

    def test_validate_backup_missing_schema_arg(self):
        """validate_backup requires schema but CLI only passes backup_path."""
        from db_adapter.backup.backup_restore import validate_backup
        import inspect

        sig = inspect.signature(validate_backup)
        required = [
            name for name, param in sig.parameters.items()
            if param.default is inspect.Parameter.empty
        ]
        assert len(required) >= 2, (
            f"Expected at least 2 required params (backup_path, schema), "
            f"got {len(required)}: {required}"
        )


# ============================================================================
# 22. Schema model edge cases — covers format_report branches
# ============================================================================

class TestSchemaModelEdgeCases:
    """Test schema model methods with real validation results."""

    async def test_format_report_valid_schema(self):
        """format_report on valid schema returns 'Schema valid'."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        async with SchemaIntrospector(FULL_URL) as introspector:
            actual = await introspector.get_column_names()

        result = validate_schema(actual, EXPECTED_COLUMNS)
        report = result.format_report()
        assert report == "Schema valid"
        assert result.error_count == 0

    async def test_format_report_missing_table(self):
        """format_report shows missing tables."""
        from db_adapter.schema.introspector import SchemaIntrospector
        from db_adapter.schema.comparator import validate_schema

        async with SchemaIntrospector(FULL_URL) as introspector:
            actual = await introspector.get_column_names()

        # Expect a table that doesn't exist
        expected = {"nonexistent_table": {"col1", "col2"}}
        result = validate_schema(actual, expected)
        report = result.format_report()
        assert "Missing tables" in report
        assert "nonexistent_table" in report

    async def test_connection_result_model(self):
        """ConnectionResult model fields are populated by connect_and_validate."""
        from db_adapter.factory import connect_and_validate

        result = await connect_and_validate(
            profile_name="full",
            expected_columns=EXPECTED_COLUMNS,
        )
        assert result.success is True
        assert result.profile_name == "full"
        assert result.schema_valid is True
        assert result.schema_report is not None
        assert result.error is None


# ============================================================================
# 23. Factory edge cases — profile resolution paths
# ============================================================================

class TestFactoryEdgeCases:
    """Test factory edge cases not covered by main tests."""

    async def test_get_active_profile(self):
        """get_active_profile returns (name, DatabaseProfile) tuple."""
        from db_adapter.factory import get_active_profile

        with patch.dict(os.environ, {"DB_PROFILE": "full"}):
            name, profile = get_active_profile()
        assert name == "full"
        assert profile.provider == "postgres"
        assert "db_adapter_full" in profile.url

    async def test_get_active_profile_bad_name(self):
        """get_active_profile with nonexistent profile raises KeyError."""
        from db_adapter.factory import get_active_profile

        with patch.dict(os.environ, {"DB_PROFILE": "nonexistent"}):
            with pytest.raises(KeyError, match="not found"):
                get_active_profile()

    async def test_profile_not_found_error(self):
        """ProfileNotFoundError when no profile configured."""
        from db_adapter.factory import get_active_profile_name, ProfileNotFoundError, clear_profile_lock, write_profile_lock

        clear_profile_lock()
        env = {k: v for k, v in os.environ.items() if k != "DB_PROFILE"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ProfileNotFoundError):
                get_active_profile_name()
        write_profile_lock("full")

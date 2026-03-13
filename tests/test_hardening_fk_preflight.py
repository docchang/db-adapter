"""Tests for Step 6: FK Pre-Flight Warning in CLI Sync.

Verifies that ``_async_sync()`` emits a warning when direct sync targets
tables with FK constraints and ``backup_schema`` is not configured.
"""

import argparse
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_adapter.cli._data_sync import _async_sync
from db_adapter.config.models import DatabaseConfig, DatabaseProfile
from db_adapter.schema.models import (
    ConstraintSchema,
    DatabaseSchema,
    TableSchema,
)


def _make_config(
    backup_schema: str | None = None,
    sync_tables: list[str] | None = None,
    profiles: dict[str, DatabaseProfile] | None = None,
) -> DatabaseConfig:
    """Build a DatabaseConfig with sensible defaults for tests."""
    if profiles is None:
        profiles = {
            "dev": DatabaseProfile(url="postgresql://localhost:5432/dev"),
            "rds": DatabaseProfile(url="postgresql://localhost:5432/rds"),
        }
    return DatabaseConfig(
        profiles=profiles,
        backup_schema=backup_schema,
        sync_tables=sync_tables,
    )


def _make_db_schema(
    tables_with_fk: list[str] | None = None,
    tables_without_fk: list[str] | None = None,
) -> DatabaseSchema:
    """Build a DatabaseSchema with FK constraints on specified tables."""
    schema = DatabaseSchema()
    for table_name in (tables_with_fk or []):
        table = TableSchema(name=table_name)
        table.constraints[f"{table_name}_fk"] = ConstraintSchema(
            name=f"{table_name}_fk",
            constraint_type="FOREIGN KEY",
            columns=["parent_id"],
            references_table="parent",
            references_columns=["id"],
        )
        schema.tables[table_name] = table
    for table_name in (tables_without_fk or []):
        table = TableSchema(name=table_name)
        table.constraints[f"{table_name}_pk"] = ConstraintSchema(
            name=f"{table_name}_pk",
            constraint_type="PRIMARY KEY",
            columns=["id"],
        )
        schema.tables[table_name] = table
    return schema


def _make_args(
    source: str = "rds",
    tables: str = "orders",
    user_id: str = "user-123",
    dry_run: bool = True,
    confirm: bool = False,
) -> argparse.Namespace:
    """Build CLI args namespace for sync tests."""
    return argparse.Namespace(
        env_prefix="",
        source=source,
        tables=tables,
        user_id=user_id,
        dry_run=dry_run,
        confirm=confirm,
    )


def _compare_result_ok(tables: list[str]) -> MagicMock:
    """Build a successful compare_profiles result."""
    result = MagicMock()
    result.success = True
    result.source_counts = {t: 10 for t in tables}
    result.dest_counts = {t: 5 for t in tables}
    result.sync_plan = None
    return result


class TestFKPreFlightWarning:
    """FK pre-flight warning emitted when direct sync targets tables with FK."""

    def test_warning_printed_when_fk_on_target_tables(self):
        """Warning is printed when target tables have FK constraints and
        backup_schema is not configured."""
        config = _make_config(backup_schema=None, sync_tables=["orders"])
        db_schema = _make_db_schema(tables_with_fk=["orders"])
        compare_result = _compare_result_ok(["orders"])
        args = _make_args(tables="orders")

        mock_introspector = AsyncMock()
        mock_introspector.introspect = AsyncMock(return_value=db_schema)
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch("db_adapter.cli._data_sync.resolve_url", return_value="postgresql://fake"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Warning:" in s and "orders" in s for s in printed), (
            f"Expected FK warning with 'orders', got: {printed}"
        )
        assert any("foreign key constraints" in s for s in printed)

    def test_warning_includes_table_names_with_fk(self):
        """Warning message includes names of tables that have FK constraints."""
        config = _make_config(backup_schema=None)
        db_schema = _make_db_schema(
            tables_with_fk=["orders", "items"],
            tables_without_fk=["users"],
        )
        compare_result = _compare_result_ok(["users", "orders", "items"])
        args = _make_args(tables="users,orders,items")

        mock_introspector = AsyncMock()
        mock_introspector.introspect = AsyncMock(return_value=db_schema)
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch("db_adapter.cli._data_sync.resolve_url", return_value="postgresql://fake"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        # Should include both FK tables but not the one without FK
        warning_lines = [s for s in printed if "Warning:" in s]
        assert len(warning_lines) == 1, f"Expected one warning, got: {warning_lines}"
        warning_text = warning_lines[0]
        assert "orders" in warning_text
        assert "items" in warning_text
        # "users" should NOT be in the warning (no FK)
        # But "users" might appear in other print calls (like table listing)
        # so only check the warning line specifically
        assert "users" not in warning_text

    def test_no_warning_when_backup_schema_configured(self):
        """No FK warning when backup_schema is configured (FK-aware path)."""
        config = _make_config(
            backup_schema="backup-schema.json",
            sync_tables=["orders"],
        )
        compare_result = _compare_result_ok(["orders"])
        args = _make_args(tables="orders")

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            # SchemaIntrospector should NOT be called at all
            with patch(
                "db_adapter.cli._data_sync.SchemaIntrospector"
            ) as mock_si:
                rc = asyncio.run(_async_sync(args))

        assert rc == 0
        mock_si.assert_not_called()
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert not any("Warning:" in s and "foreign key" in s for s in printed)

    def test_no_warning_when_no_fk_constraints(self):
        """No FK warning when target tables have no FK constraints."""
        config = _make_config(backup_schema=None, sync_tables=["users"])
        db_schema = _make_db_schema(tables_without_fk=["users"])
        compare_result = _compare_result_ok(["users"])
        args = _make_args(tables="users")

        mock_introspector = AsyncMock()
        mock_introspector.introspect = AsyncMock(return_value=db_schema)
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch("db_adapter.cli._data_sync.resolve_url", return_value="postgresql://fake"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert not any("Warning:" in s and "foreign key" in s for s in printed)

    def test_sync_proceeds_after_warning(self):
        """Sync continues normally after FK warning (not blocking)."""
        config = _make_config(backup_schema=None, sync_tables=["orders"])
        db_schema = _make_db_schema(tables_with_fk=["orders"])

        compare_result = _compare_result_ok(["orders"])
        sync_result = MagicMock()
        sync_result.success = True

        args = _make_args(tables="orders", dry_run=False, confirm=True)

        mock_introspector = AsyncMock()
        mock_introspector.introspect = AsyncMock(return_value=db_schema)
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch("db_adapter.cli._data_sync.resolve_url", return_value="postgresql://fake"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch(
                "db_adapter.cli._data_sync.sync_data",
                new_callable=AsyncMock,
                return_value=sync_result,
            ) as mock_sync_data,
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        # Warning was printed
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("Warning:" in s and "orders" in s for s in printed)
        # sync_data was still called
        mock_sync_data.assert_called_once()
        # Success message was printed
        assert any("Sync complete" in s for s in printed)

    def test_no_warning_when_config_is_none(self):
        """FK detection is skipped entirely when config is None."""
        compare_result = _compare_result_ok(["orders"])
        args = _make_args(tables="orders")

        with (
            patch(
                "db_adapter.cli._data_sync.load_db_config",
                side_effect=FileNotFoundError,
            ),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            with patch(
                "db_adapter.cli._data_sync.SchemaIntrospector"
            ) as mock_si:
                rc = asyncio.run(_async_sync(args))

        assert rc == 0
        mock_si.assert_not_called()
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert not any("Warning:" in s and "foreign key" in s for s in printed)

    def test_graceful_degradation_on_introspection_failure(self):
        """FK warning is silently skipped when SchemaIntrospector raises."""
        config = _make_config(backup_schema=None, sync_tables=["orders"])
        compare_result = _compare_result_ok(["orders"])
        args = _make_args(tables="orders")

        mock_introspector = AsyncMock()
        mock_introspector.__aenter__ = AsyncMock(
            side_effect=ConnectionError("cannot connect")
        )
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch("db_adapter.cli._data_sync.resolve_url", return_value="postgresql://fake"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        # Sync proceeds despite introspection failure
        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        # No FK warning (introspection failed)
        assert not any("Warning:" in s and "foreign key" in s for s in printed)
        # But sync did proceed (compare results shown)
        assert any("Comparing" in s for s in printed)

    def test_graceful_degradation_on_introspect_exception(self):
        """FK warning is skipped when introspect() itself raises."""
        config = _make_config(backup_schema=None, sync_tables=["orders"])
        compare_result = _compare_result_ok(["orders"])
        args = _make_args(tables="orders")

        mock_introspector = AsyncMock()
        mock_introspector.introspect = AsyncMock(
            side_effect=RuntimeError("introspection failed")
        )
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch("db_adapter.cli._data_sync.resolve_url", return_value="postgresql://fake"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert not any("Warning:" in s and "foreign key" in s for s in printed)

    def test_warning_message_format(self):
        """Warning message matches the expected format with yellow prefix."""
        config = _make_config(backup_schema=None)
        db_schema = _make_db_schema(tables_with_fk=["orders"])
        compare_result = _compare_result_ok(["orders"])
        args = _make_args(tables="orders")

        mock_introspector = AsyncMock()
        mock_introspector.introspect = AsyncMock(return_value=db_schema)
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch("db_adapter.cli._data_sync.resolve_url", return_value="postgresql://fake"),
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console") as mock_console,
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        printed = [str(call) for call in mock_console.print.call_args_list]
        warning_lines = [s for s in printed if "Warning:" in s]
        assert len(warning_lines) == 1
        warning = warning_lines[0]
        assert "[yellow]Warning:[/yellow]" in warning
        assert "backup_schema" in warning
        assert "FK remapping" in warning

    def test_resolve_url_called_with_dest_profile(self):
        """FK detection resolves URL via resolve_url(profile) for dest profile."""
        config = _make_config(backup_schema=None)
        db_schema = _make_db_schema(tables_without_fk=["orders"])
        compare_result = _compare_result_ok(["orders"])
        args = _make_args(tables="orders")

        mock_introspector = AsyncMock()
        mock_introspector.introspect = AsyncMock(return_value=db_schema)
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db_adapter.cli._data_sync.load_db_config", return_value=config),
            patch("db_adapter.cli._data_sync.read_profile_lock", return_value="dev"),
            patch(
                "db_adapter.cli._data_sync.SchemaIntrospector",
                return_value=mock_introspector,
            ),
            patch(
                "db_adapter.cli._data_sync.resolve_url",
                return_value="postgresql://resolved",
            ) as mock_resolve,
            patch(
                "db_adapter.cli._data_sync.compare_profiles",
                new_callable=AsyncMock,
                return_value=compare_result,
            ),
            patch("db_adapter.cli._data_sync.console"),
        ):
            rc = asyncio.run(_async_sync(args))

        assert rc == 0
        # resolve_url was called with the dev profile (dest)
        mock_resolve.assert_called_once_with(config.profiles["dev"])

"""Tests for Step 5: Transaction Wrapping for Consumers.

Verifies that:
- restore_database() wraps multi-table loop in adapter.transaction()
- restore_database() rolls back on unrecoverable errors
- restore_database() commits with failure_details in skip/overwrite mode
- apply_fixes() wraps fix sequence in transaction inside try/except
- apply_fixes() rolls back on exception during DDL
- apply_fixes() commits atomically on success
- _sync_direct() wraps per-table insert loop in transaction
- _sync_direct() rolls back per-table on FK violation
- All three consumers work without transaction support (hasattr guard)
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_adapter.backup.backup_restore import restore_database
from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef
from db_adapter.schema.fix import (
    ColumnFix,
    FixPlan,
    TableFix,
    apply_fixes,
)
from db_adapter.schema.sync import sync_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_schema() -> BackupSchema:
    """A 2-table schema for testing."""
    return BackupSchema(
        tables=[
            TableDef(
                name="authors",
                pk="id",
                slug_field="slug",
                user_field="user_id",
            ),
            TableDef(
                name="books",
                pk="id",
                slug_field="slug",
                user_field="user_id",
                parent=ForeignKey(table="authors", field="author_id"),
            ),
        ]
    )


def _valid_backup_data() -> dict:
    """Minimal valid backup data for 2-table schema."""
    return {
        "metadata": {
            "created_at": "2026-01-01T00:00:00",
            "user_id": "u1",
            "backup_type": "full",
            "version": "1.1",
        },
        "authors": [
            {"id": "a1", "slug": "alice", "user_id": "u1"},
        ],
        "books": [
            {"id": "b1", "slug": "book1", "user_id": "u1", "author_id": "a1"},
        ],
    }


def _make_mock_adapter_with_transaction():
    """Create a mock adapter that supports transaction().

    Returns (adapter, transaction_ctx) where transaction_ctx is the
    mock async context manager so tests can inspect __aenter__/__aexit__.
    """
    adapter = AsyncMock()

    # Transaction context manager
    transaction_ctx = AsyncMock()
    transaction_ctx.__aenter__ = AsyncMock(return_value=None)
    transaction_ctx.__aexit__ = AsyncMock(return_value=False)

    adapter.transaction = MagicMock(return_value=transaction_ctx)

    return adapter, transaction_ctx


def _make_mock_adapter_without_transaction():
    """Create a mock adapter that does NOT have transaction().

    Uses spec to restrict attributes to the explicitly defined ones,
    ensuring that ``adapter.transaction()`` raises ``AttributeError``.
    """
    adapter = AsyncMock()

    # Make transaction() raise AttributeError (simulating missing method)
    adapter.transaction = MagicMock(side_effect=AttributeError("no transaction"))

    return adapter


# ============================================================================
# restore_database() -- transaction wrapping
# ============================================================================


class TestRestoreTransaction:
    """Verify restore_database() wraps multi-table loop in transaction."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    def _write_backup(self, path: str, data: dict) -> None:
        with open(path, "w") as f:
            json.dump(data, f)

    async def test_transaction_used_when_available(self, schema, tmp_path):
        """restore_database() calls adapter.transaction() when available."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, _valid_backup_data())

        adapter, transaction_ctx = _make_mock_adapter_with_transaction()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)

        await restore_database(adapter, schema, backup_file, user_id="u1")

        # transaction() was called
        adapter.transaction.assert_called_once()
        # Context manager was entered and exited
        transaction_ctx.__aenter__.assert_awaited_once()
        transaction_ctx.__aexit__.assert_awaited_once()

    async def test_rollback_on_unrecoverable_error(self, schema, tmp_path):
        """Unrecoverable error propagates out of transaction -> rollback."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, _valid_backup_data())

        adapter, transaction_ctx = _make_mock_adapter_with_transaction()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        # Insert raises ValueError (mode=fail) which propagates
        async def _insert(table, data):
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)

        with pytest.raises(ValueError, match="already exists"):
            # Use mode="fail" -- when authors already exist, ValueError raises
            # But we need the select to return existing records for mode=fail
            async def _select_with_existing(table, columns="*", filters=None, order_by=None):
                if table == "authors":
                    return [{"id": "existing-a1"}]
                return []

            adapter.select = AsyncMock(side_effect=_select_with_existing)

            await restore_database(
                adapter, schema, backup_file, user_id="u1", mode="fail"
            )

        # Transaction __aexit__ was called with exception info (rollback)
        exit_args = transaction_ctx.__aexit__.call_args
        assert exit_args[0][0] is ValueError

    async def test_commit_with_failure_details_in_skip_mode(self, schema, tmp_path):
        """Per-row failures in skip mode are captured but transaction commits."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, _valid_backup_data())

        adapter, transaction_ctx = _make_mock_adapter_with_transaction()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        call_count = {"val": 0}

        async def _insert(table, data):
            call_count["val"] += 1
            if table == "authors":
                raise RuntimeError("Connection lost for row")
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)

        summary = await restore_database(
            adapter, schema, backup_file, user_id="u1", mode="skip"
        )

        # Author insert failed, captured in failure_details
        assert summary["authors"]["failed"] == 1
        assert len(summary["authors"]["failure_details"]) == 1
        assert "RuntimeError" in summary["authors"]["failure_details"][0]["error"]

        # Transaction committed (clean __aexit__ with no exception)
        exit_args = transaction_ctx.__aexit__.call_args
        assert exit_args[0] == (None, None, None)

    async def test_works_without_transaction_support(self, schema, tmp_path):
        """restore_database() works when adapter lacks transaction()."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, _valid_backup_data())

        adapter = _make_mock_adapter_without_transaction()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)

        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        # Should work normally without transaction
        assert summary["authors"]["inserted"] == 1
        assert summary["books"]["inserted"] == 1


# ============================================================================
# apply_fixes() -- transaction wrapping
# ============================================================================


class TestApplyFixesTransaction:
    """Verify apply_fixes() wraps fix sequence in transaction."""

    async def test_transaction_used_when_available(self):
        """apply_fixes() calls adapter.transaction() when available."""
        adapter, transaction_ctx = _make_mock_adapter_with_transaction()
        adapter.execute = AsyncMock()

        plan = FixPlan(
            missing_tables=[
                TableFix(table="users", create_sql="CREATE TABLE users (id INT);")
            ],
        )

        result = await apply_fixes(adapter, plan, dry_run=False, confirm=True)

        assert result.success is True
        adapter.transaction.assert_called_once()
        transaction_ctx.__aenter__.assert_awaited_once()

    async def test_rollback_on_ddl_exception(self):
        """Exception during DDL propagates out of transaction -> rollback."""
        adapter, transaction_ctx = _make_mock_adapter_with_transaction()

        # execute raises an error for CREATE TABLE
        adapter.execute = AsyncMock(side_effect=Exception("DDL failed"))

        plan = FixPlan(
            missing_tables=[
                TableFix(table="users", create_sql="CREATE TABLE users (id INT);")
            ],
        )

        result = await apply_fixes(adapter, plan, dry_run=False, confirm=True)

        # Error captured in result
        assert result.success is False
        assert "Failed to apply fixes" in result.error
        assert "DDL failed" in result.error

        # Transaction __aexit__ called with exception info (rollback)
        exit_args = transaction_ctx.__aexit__.call_args
        assert exit_args[0][0] is not None  # exc_type was passed

    async def test_successful_fix_commits_atomically(self):
        """Successful fix sequence commits via clean transaction exit."""
        adapter, transaction_ctx = _make_mock_adapter_with_transaction()
        adapter.execute = AsyncMock()

        plan = FixPlan(
            missing_columns=[
                ColumnFix(table="users", column="email", definition="TEXT"),
                ColumnFix(table="users", column="bio", definition="TEXT"),
            ],
        )

        result = await apply_fixes(adapter, plan, dry_run=False, confirm=True)

        assert result.success is True
        assert result.columns_added == 2

        # Transaction committed (clean exit)
        exit_args = transaction_ctx.__aexit__.call_args
        assert exit_args[0] == (None, None, None)

    async def test_runtime_error_propagates_through_transaction(self):
        """RuntimeError from DDL-unsupported adapter propagates through transaction."""
        adapter, transaction_ctx = _make_mock_adapter_with_transaction()
        adapter.execute = AsyncMock(side_effect=NotImplementedError("not supported"))

        plan = FixPlan(
            missing_tables=[
                TableFix(table="t", create_sql="CREATE TABLE t (id INT);")
            ],
        )

        with pytest.raises(RuntimeError, match="DDL operations not supported"):
            await apply_fixes(adapter, plan, dry_run=False, confirm=True)

    async def test_works_without_transaction_support(self):
        """apply_fixes() works when adapter lacks transaction()."""
        adapter = _make_mock_adapter_without_transaction()
        adapter.execute = AsyncMock()

        plan = FixPlan(
            missing_tables=[
                TableFix(table="users", create_sql="CREATE TABLE users (id INT);")
            ],
        )

        result = await apply_fixes(adapter, plan, dry_run=False, confirm=True)

        assert result.success is True
        assert result.tables_created == 1
        adapter.execute.assert_called_once()

    async def test_noop_transaction_on_ddl_failure_without_support(self):
        """Without transaction support, DDL failure is still caught by try/except."""
        adapter = _make_mock_adapter_without_transaction()
        adapter.execute = AsyncMock(side_effect=Exception("DDL failed"))

        plan = FixPlan(
            missing_tables=[
                TableFix(table="users", create_sql="CREATE TABLE users (id INT);")
            ],
        )

        result = await apply_fixes(adapter, plan, dry_run=False, confirm=True)

        assert result.success is False
        assert "Failed to apply fixes" in result.error


# ============================================================================
# _sync_direct() -- per-table transaction wrapping
# ============================================================================


class TestSyncDirectTransaction:
    """Verify _sync_direct() wraps per-table insert loop in transaction."""

    def _make_sync_adapters(self, *, with_transaction=True):
        """Create source and dest mock adapters for sync tests.

        Args:
            with_transaction: If True, dest_adapter has transaction().
        """
        source_adapter = AsyncMock()
        source_adapter.close = AsyncMock()

        if with_transaction:
            dest_adapter, transaction_ctx = _make_mock_adapter_with_transaction()
        else:
            dest_adapter = _make_mock_adapter_without_transaction()
            transaction_ctx = None

        dest_adapter.close = AsyncMock()

        return source_adapter, dest_adapter, transaction_ctx

    async def test_transaction_used_per_table(self):
        """_sync_direct() calls dest_adapter.transaction() per table."""
        source_adapter, dest_adapter, transaction_ctx = self._make_sync_adapters()

        # Source has 1 new row per table
        async def _source_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 1}]
            if columns == "slug":
                return [{"slug": "new-item"}]
            return [{"id": "1", "slug": "new-item", "user_id": "u1"}]

        # Dest has no rows
        async def _dest_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            if columns == "slug":
                return []
            return []

        source_adapter.select = AsyncMock(side_effect=_source_select)
        dest_adapter.select = AsyncMock(side_effect=_dest_select)

        async def _insert(table, data):
            return dict(data)

        dest_adapter.insert = AsyncMock(side_effect=_insert)

        # compare_profiles creates adapters, then _sync_direct creates adapters
        adapter_sequence = [
            source_adapter, dest_adapter,  # compare_profiles
            source_adapter, dest_adapter,  # _sync_direct
        ]
        adapter_iter = iter(adapter_sequence)

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapter_iter),
        ):
            result = await sync_data(
                "src", "dst",
                tables=["items", "widgets"],
                user_id="u1",
                dry_run=False,
                confirm=True,
            )

        assert result.success
        # transaction() called once per table (2 tables)
        assert dest_adapter.transaction.call_count == 2

    async def test_per_table_rollback_on_fk_violation(self):
        """FK violation during insert propagates -> per-table rollback."""
        source_adapter, dest_adapter, transaction_ctx = self._make_sync_adapters()

        async def _source_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 1}]
            if columns == "slug":
                return [{"slug": "new-item"}]
            return [{"id": "1", "slug": "new-item", "user_id": "u1"}]

        async def _dest_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            if columns == "slug":
                return []
            return []

        source_adapter.select = AsyncMock(side_effect=_source_select)
        dest_adapter.select = AsyncMock(side_effect=_dest_select)

        # Raise a ForeignKey error on insert
        class ForeignKeyViolation(Exception):
            pass

        dest_adapter.insert = AsyncMock(
            side_effect=ForeignKeyViolation("FK constraint failed")
        )

        adapter_sequence = [
            source_adapter, dest_adapter,
            source_adapter, dest_adapter,
        ]
        adapter_iter = iter(adapter_sequence)

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapter_iter),
        ):
            with pytest.raises(ValueError, match="FK constraint violation"):
                await sync_data(
                    "src", "dst",
                    tables=["items"],
                    user_id="u1",
                    dry_run=False,
                    confirm=True,
                )

        # Transaction __aexit__ was called with exception (rollback)
        exit_args = transaction_ctx.__aexit__.call_args
        assert exit_args[0][0] is not None  # exc_type was passed

    async def test_works_without_transaction_support(self):
        """_sync_direct() works when dest_adapter lacks transaction()."""
        source_adapter, dest_adapter, _ = self._make_sync_adapters(
            with_transaction=False
        )

        async def _source_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 1}]
            if columns == "slug":
                return [{"slug": "new-item"}]
            return [{"id": "1", "slug": "new-item", "user_id": "u1"}]

        async def _dest_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            if columns == "slug":
                return []
            return []

        source_adapter.select = AsyncMock(side_effect=_source_select)
        dest_adapter.select = AsyncMock(side_effect=_dest_select)

        async def _insert(table, data):
            return dict(data)

        dest_adapter.insert = AsyncMock(side_effect=_insert)

        adapter_sequence = [
            source_adapter, dest_adapter,
            source_adapter, dest_adapter,
        ]
        adapter_iter = iter(adapter_sequence)

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapter_iter),
        ):
            result = await sync_data(
                "src", "dst",
                tables=["items"],
                user_id="u1",
                dry_run=False,
                confirm=True,
            )

        assert result.success
        assert result.synced_count == 1

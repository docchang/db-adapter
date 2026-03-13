"""Tests for Step 3: Restore Failure Details.

Verifies that _restore_table() captures per-row error details in
failure_details list and that logger.warning is called on each failure.
Also verifies that failure_details is absent when no failures occur.
"""

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

from db_adapter.backup.backup_restore import restore_database
from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef


# ------------------------------------------------------------------
# Helper: sample schema and backup data
# ------------------------------------------------------------------


def _sample_schema() -> BackupSchema:
    """A 2-table schema for testing failure details."""
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
            {"id": "a2", "slug": "bob", "user_id": "u1"},
            {"id": "a3", "slug": "carol", "user_id": "u1"},
        ],
        "books": [],
    }


def _write_backup(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f)


def _make_adapter_that_fails_on_insert(fail_on_table: str, fail_on_pk: str) -> AsyncMock:
    """Create a mock adapter that raises RuntimeError for a specific row insert."""
    adapter = AsyncMock()

    async def _select(table, columns="*", filters=None, order_by=None):
        return []  # Nothing exists -- all inserts

    adapter.select = AsyncMock(side_effect=_select)

    async def _insert(table, data):
        if table == fail_on_table and data.get("id") == fail_on_pk:
            raise RuntimeError(f"Simulated DB error for {fail_on_pk}")
        return dict(data)

    adapter.insert = AsyncMock(side_effect=_insert)
    adapter.update = AsyncMock()
    adapter.close = AsyncMock()

    return adapter


# ------------------------------------------------------------------
# Single failure: failure_details present with correct fields
# ------------------------------------------------------------------


class TestSingleFailure:
    """Verify failure_details for a single failed row."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_failure_details_present_on_single_failure(self, schema, tmp_path):
        """When one row fails, failure_details contains one entry."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = _make_adapter_that_fails_on_insert("authors", "a2")
        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        assert summary["authors"]["failed"] == 1
        assert "failure_details" in summary["authors"]
        details = summary["authors"]["failure_details"]
        assert len(details) == 1

    async def test_failure_detail_has_correct_row_index(self, schema, tmp_path):
        """failure_details entry has correct row_index (0-based)."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        # a2 is the second author (index 1)
        adapter = _make_adapter_that_fails_on_insert("authors", "a2")
        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        detail = summary["authors"]["failure_details"][0]
        assert detail["row_index"] == 1

    async def test_failure_detail_has_correct_old_pk(self, schema, tmp_path):
        """failure_details entry has correct old_pk value."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = _make_adapter_that_fails_on_insert("authors", "a2")
        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        detail = summary["authors"]["failure_details"][0]
        assert detail["old_pk"] == "a2"

    async def test_failure_detail_has_error_with_exception_class(self, schema, tmp_path):
        """failure_details error string includes exception class name."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = _make_adapter_that_fails_on_insert("authors", "a2")
        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        detail = summary["authors"]["failure_details"][0]
        assert detail["error"].startswith("RuntimeError: ")
        assert "Simulated DB error for a2" in detail["error"]

    async def test_non_failed_rows_still_inserted(self, schema, tmp_path):
        """Rows that succeed are still inserted despite one failure."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = _make_adapter_that_fails_on_insert("authors", "a2")
        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        # 3 authors total: a1 inserted, a2 failed, a3 inserted
        assert summary["authors"]["inserted"] == 2
        assert summary["authors"]["failed"] == 1


# ------------------------------------------------------------------
# Multiple failures
# ------------------------------------------------------------------


class TestMultipleFailures:
    """Verify failure_details with multiple failed rows."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_multiple_failures_captured(self, schema, tmp_path):
        """Multiple failures produce multiple entries in failure_details."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        # Fail on a1 and a3 (indices 0 and 2)
        async def _insert(table, data):
            if table == "authors" and data.get("id") in ("a1", "a3"):
                raise RuntimeError(f"DB error for {data['id']}")
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)
        adapter.close = AsyncMock()

        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        assert summary["authors"]["failed"] == 2
        details = summary["authors"]["failure_details"]
        assert len(details) == 2
        assert details[0]["row_index"] == 0
        assert details[0]["old_pk"] == "a1"
        assert details[1]["row_index"] == 2
        assert details[1]["old_pk"] == "a3"


# ------------------------------------------------------------------
# No failures: failure_details absent
# ------------------------------------------------------------------


class TestNoFailures:
    """Verify failure_details is absent when no failures occur."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_failure_details_absent_when_no_failures(self, schema, tmp_path):
        """When all rows succeed, failure_details key is not present."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)
        adapter.close = AsyncMock()

        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        assert summary["authors"]["failed"] == 0
        assert "failure_details" not in summary["authors"]
        assert "failure_details" not in summary["books"]


# ------------------------------------------------------------------
# Missing PK field: old_pk defaults to "<unknown>"
# ------------------------------------------------------------------


class TestMissingPKField:
    """Verify old_pk defaults to '<unknown>' when PK field is absent from row.

    Note: validate_backup() rejects rows with missing PK fields before
    restore runs. To test the safe .get() default in _restore_table(),
    we use a row that has a PK but the adapter returns a result without
    the PK key (causing KeyError on id_maps assignment).
    """

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_insert_result_missing_pk_uses_safe_old_pk(self, schema, tmp_path):
        """When adapter.insert returns dict without PK, the row fails
        gracefully and old_pk is captured correctly."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            if table == "authors" and data.get("id") == "a2":
                # Return result without the "id" key -- this triggers
                # KeyError on result[table_def.pk] inside _restore_table
                return {"slug": data.get("slug")}
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)
        adapter.close = AsyncMock()

        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        assert summary["authors"]["failed"] == 1
        details = summary["authors"]["failure_details"]
        assert len(details) == 1
        # old_pk was read safely via .get() before the try block
        assert details[0]["old_pk"] == "a2"
        assert details[0]["row_index"] == 1
        assert "KeyError" in details[0]["error"]


# ------------------------------------------------------------------
# Logger.warning called on failure
# ------------------------------------------------------------------


class TestLoggerWarning:
    """Verify logger.warning is called with correct arguments on failure."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_logger_warning_called_on_failure(self, schema, tmp_path):
        """logger.warning called once per failed row."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = _make_adapter_that_fails_on_insert("authors", "a2")

        with patch("db_adapter.backup.backup_restore.logger") as mock_logger:
            await restore_database(adapter, schema, backup_file, user_id="u1")

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            # Format string is the first positional arg
            fmt_string = call_args[0][0]
            assert "Restore failed for %s row %d (pk=%s): %s" == fmt_string
            # Positional args after format string
            assert call_args[0][1] == "authors"  # table_name
            assert call_args[0][2] == 1  # row index (a2 is index 1)
            assert call_args[0][3] == "a2"  # old_pk

    async def test_logger_warning_not_called_when_no_failures(self, schema, tmp_path):
        """logger.warning is not called when all rows succeed."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)
        adapter.close = AsyncMock()

        with patch("db_adapter.backup.backup_restore.logger") as mock_logger:
            await restore_database(adapter, schema, backup_file, user_id="u1")
            mock_logger.warning.assert_not_called()

    async def test_multiple_warnings_for_multiple_failures(self, schema, tmp_path):
        """logger.warning called once per failed row when multiple fail."""
        backup_file = str(tmp_path / "backup.json")
        _write_backup(backup_file, _valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            if table == "authors":
                raise RuntimeError(f"DB error for {data.get('id')}")
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)
        adapter.close = AsyncMock()

        with patch("db_adapter.backup.backup_restore.logger") as mock_logger:
            await restore_database(adapter, schema, backup_file, user_id="u1")
            # 3 authors, all fail
            assert mock_logger.warning.call_count == 3

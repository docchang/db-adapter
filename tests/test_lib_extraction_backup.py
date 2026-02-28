"""Tests for Step 10: Generalize Backup/Restore.

Verifies that backup_restore.py is free of hardcoded MC-specific code,
uses BackupSchema for table iteration and FK remapping, has async
backup/restore functions, sync validate_backup, and produces correct
backup JSON format with version "1.1".
"""

import ast
import inspect
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from db_adapter.backup.backup_restore import (
    _find_table_def,
    backup_database,
    restore_database,
    validate_backup,
)
from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef

# Path to source files for AST/source inspection
BACKUP_RESTORE_PY = (
    Path(__file__).parent.parent
    / "src"
    / "db_adapter"
    / "backup"
    / "backup_restore.py"
)
MODELS_PY = (
    Path(__file__).parent.parent
    / "src"
    / "db_adapter"
    / "backup"
    / "models.py"
)


# ------------------------------------------------------------------
# Helper: sample BackupSchema for tests
# ------------------------------------------------------------------


def _sample_schema() -> BackupSchema:
    """A 3-table schema for testing (generic names, no MC references)."""
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
            TableDef(
                name="chapters",
                pk="id",
                slug_field="slug",
                user_field="user_id",
                parent=ForeignKey(table="books", field="book_id"),
                optional_refs=[ForeignKey(table="authors", field="editor_id")],
            ),
        ]
    )


def _make_mock_adapter(select_results: dict | None = None) -> AsyncMock:
    """Create an AsyncMock adapter that returns predictable results.

    Args:
        select_results: mapping of (table, filters_key) -> result list.
            When None, select returns empty list by default.
    """
    adapter = AsyncMock()

    # Default: select returns empty list
    async def _select(table, columns="*", filters=None, order_by=None):
        return []

    adapter.select = AsyncMock(side_effect=_select)

    # Default: insert returns the data with same id
    async def _insert(table, data):
        return dict(data)

    adapter.insert = AsyncMock(side_effect=_insert)
    adapter.update = AsyncMock()
    adapter.delete = AsyncMock()
    adapter.close = AsyncMock()

    return adapter


# ------------------------------------------------------------------
# MC-specific code removal
# ------------------------------------------------------------------


class TestMCCodeRemoved:
    """Verify all MC-specific code is removed from backup_restore.py."""

    def test_no_hardcoded_table_names(self):
        """No hardcoded 'projects', 'milestones', 'tasks' string literals."""
        source = BACKUP_RESTORE_PY.read_text()
        tree = ast.parse(source)
        mc_tables = {"projects", "milestones", "tasks"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in mc_tables:
                    pytest.fail(
                        f"Hardcoded MC table name '{node.value}' "
                        f"found in backup_restore.py"
                    )

    def test_no_mc_imports(self):
        """No MC-coupled imports (from db import, from config import, etc.)."""
        source = BACKUP_RESTORE_PY.read_text()
        tree = ast.parse(source)
        forbidden = {"db", "config"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in forbidden:
                    pytest.fail(f"MC-coupled import: from {node.module} import ...")

    def test_no_removed_comments(self):
        """No '# REMOVED:' comments left over from Step 2."""
        source = BACKUP_RESTORE_PY.read_text()
        for i, line in enumerate(source.splitlines(), 1):
            if "# REMOVED:" in line:
                pytest.fail(f"'# REMOVED:' comment on line {i}")

    def test_no_print_statements(self):
        """No print() calls in the module (callers handle output)."""
        source = BACKUP_RESTORE_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "print":
                    pytest.fail("print() call found in backup_restore.py")

    def test_no_get_db_adapter_or_get_dev_user_id(self):
        """No references to get_db_adapter or get_dev_user_id."""
        source = BACKUP_RESTORE_PY.read_text()
        for name in ("get_db_adapter", "get_dev_user_id", "get_settings"):
            if name in source:
                pytest.fail(f"'{name}' found in backup_restore.py")

    def test_no_db_provider_in_metadata(self):
        """No 'db_provider' field written in backup metadata."""
        source = BACKUP_RESTORE_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "db_provider":
                pytest.fail(
                    "'db_provider' string literal found in backup_restore.py"
                )

    def test_models_docstring_no_mc_tables(self):
        """backup/models.py docstring uses generic table names, not MC-specific."""
        source = MODELS_PY.read_text()
        mc_tables = ["projects", "milestones", "tasks"]
        # Only check the module docstring (first triple-quoted string)
        tree = ast.parse(source)
        docstring = ast.get_docstring(tree)
        assert docstring is not None, "models.py missing module docstring"
        for table in mc_tables:
            if table in docstring:
                pytest.fail(
                    f"MC table name '{table}' in models.py docstring"
                )


# ------------------------------------------------------------------
# Function signatures
# ------------------------------------------------------------------


class TestFunctionSignatures:
    """Verify function signatures match the plan specification."""

    def test_backup_database_is_async(self):
        """backup_database is async def."""
        assert inspect.iscoroutinefunction(backup_database)

    def test_restore_database_is_async(self):
        """restore_database is async def."""
        assert inspect.iscoroutinefunction(restore_database)

    def test_validate_backup_is_sync(self):
        """validate_backup is NOT async (sync -- local file read only)."""
        assert not inspect.iscoroutinefunction(validate_backup)

    def test_backup_database_params(self):
        """backup_database accepts the expected parameters."""
        sig = inspect.signature(backup_database)
        params = list(sig.parameters.keys())
        assert "adapter" in params
        assert "schema" in params
        assert "user_id" in params
        assert "output_path" in params
        assert "table_filters" in params
        assert "metadata" in params

    def test_restore_database_params(self):
        """restore_database accepts the expected parameters."""
        sig = inspect.signature(restore_database)
        params = list(sig.parameters.keys())
        assert "adapter" in params
        assert "schema" in params
        assert "backup_path" in params
        assert "user_id" in params
        assert "mode" in params
        assert "dry_run" in params

    def test_validate_backup_params(self):
        """validate_backup accepts backup_path and schema parameters."""
        sig = inspect.signature(validate_backup)
        params = list(sig.parameters.keys())
        assert "backup_path" in params
        assert "schema" in params

    def test_backup_database_return_type(self):
        """backup_database return annotation is str."""
        sig = inspect.signature(backup_database)
        assert sig.return_annotation is str

    def test_restore_database_return_type(self):
        """restore_database return annotation is dict."""
        sig = inspect.signature(restore_database)
        assert sig.return_annotation is dict


# ------------------------------------------------------------------
# backup_database tests
# ------------------------------------------------------------------


class TestBackupDatabase:
    """Test backup_database iterates BackupSchema.tables."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_iterates_schema_tables(self, schema, tmp_path):
        """backup_database calls adapter.select() for each table in schema."""
        adapter = _make_mock_adapter()
        output = str(tmp_path / "backup.json")
        await backup_database(adapter, schema, user_id="u1", output_path=output)

        # adapter.select called once per table
        call_tables = [
            call.args[0] for call in adapter.select.call_args_list
        ]
        assert "authors" in call_tables
        assert "books" in call_tables
        assert "chapters" in call_tables

    async def test_backup_json_format(self, schema, tmp_path):
        """Backup JSON has metadata, version 1.1, and table-name keys."""
        adapter = _make_mock_adapter()
        output = str(tmp_path / "backup.json")
        await backup_database(adapter, schema, user_id="u1", output_path=output)

        with open(output) as f:
            data = json.load(f)

        assert data["metadata"]["version"] == "1.1"
        assert data["metadata"]["user_id"] == "u1"
        assert "authors" in data
        assert "books" in data
        assert "chapters" in data
        # No db_provider
        assert "db_provider" not in data["metadata"]

    async def test_backup_counts_in_metadata(self, schema, tmp_path):
        """Metadata includes per-table counts."""
        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            if table == "authors":
                return [
                    {"id": "a1", "slug": "alice", "user_id": "u1"},
                    {"id": "a2", "slug": "bob", "user_id": "u1"},
                ]
            return []

        adapter.select = AsyncMock(side_effect=_select)

        output = str(tmp_path / "backup.json")
        await backup_database(adapter, schema, user_id="u1", output_path=output)

        with open(output) as f:
            data = json.load(f)

        assert data["metadata"]["authors_count"] == 2
        assert data["metadata"]["books_count"] == 0
        assert data["metadata"]["chapters_count"] == 0

    async def test_child_filtered_by_parent_pks(self, schema, tmp_path):
        """Child rows are filtered to only those whose parent FK is in parent PKs."""
        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            if table == "authors":
                return [{"id": "a1", "slug": "alice", "user_id": "u1"}]
            if table == "books":
                return [
                    {"id": "b1", "slug": "book1", "user_id": "u1", "author_id": "a1"},
                    {"id": "b2", "slug": "book2", "user_id": "u1", "author_id": "a999"},
                ]
            return []

        adapter.select = AsyncMock(side_effect=_select)

        output = str(tmp_path / "backup.json")
        await backup_database(adapter, schema, user_id="u1", output_path=output)

        with open(output) as f:
            data = json.load(f)

        # Only book1 (author_id=a1) should be in backup; book2 (author_id=a999) filtered out
        assert len(data["books"]) == 1
        assert data["books"][0]["id"] == "b1"

    async def test_table_filters_applied(self, schema, tmp_path):
        """table_filters dict is merged into per-table select filters."""
        adapter = AsyncMock()

        select_calls = []

        async def _select(table, columns="*", filters=None, order_by=None):
            select_calls.append((table, filters))
            return []

        adapter.select = AsyncMock(side_effect=_select)

        output = str(tmp_path / "backup.json")
        await backup_database(
            adapter,
            schema,
            user_id="u1",
            output_path=output,
            table_filters={"authors": {"status": "active"}},
        )

        # Find the authors call
        authors_call = [c for c in select_calls if c[0] == "authors"]
        assert len(authors_call) == 1
        assert authors_call[0][1]["status"] == "active"
        assert authors_call[0][1]["user_id"] == "u1"

    async def test_custom_metadata_merged(self, schema, tmp_path):
        """Custom metadata dict is merged into backup metadata."""
        adapter = _make_mock_adapter()
        output = str(tmp_path / "backup.json")
        await backup_database(
            adapter,
            schema,
            user_id="u1",
            output_path=output,
            metadata={"environment": "staging", "notes": "test run"},
        )

        with open(output) as f:
            data = json.load(f)

        assert data["metadata"]["environment"] == "staging"
        assert data["metadata"]["notes"] == "test run"

    async def test_default_output_path(self, schema, monkeypatch, tmp_path):
        """When output_path is None, generates timestamped path under ./backups/."""
        adapter = _make_mock_adapter()
        monkeypatch.chdir(tmp_path)
        path = await backup_database(adapter, schema, user_id="u1")
        assert "backups" in path
        assert "backup-" in path
        assert path.endswith(".json")
        assert Path(path).exists()

    async def test_returns_output_path(self, schema, tmp_path):
        """backup_database returns the output path string."""
        adapter = _make_mock_adapter()
        output = str(tmp_path / "test-backup.json")
        result = await backup_database(adapter, schema, user_id="u1", output_path=output)
        assert result == output


# ------------------------------------------------------------------
# restore_database tests
# ------------------------------------------------------------------


class TestRestoreDatabase:
    """Test restore_database performs FK remapping via id_maps."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    def _write_backup(self, path: str, data: dict) -> None:
        with open(path, "w") as f:
            json.dump(data, f)

    def _valid_backup_data(self) -> dict:
        """Minimal valid backup data for 3-table schema."""
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
            "chapters": [
                {
                    "id": "c1",
                    "slug": "ch1",
                    "user_id": "u1",
                    "book_id": "b1",
                    "editor_id": "a1",
                },
            ],
        }

    async def test_inserts_parent_first(self, schema, tmp_path):
        """Restore inserts parent tables before children."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, self._valid_backup_data())

        insert_order = []
        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []  # Nothing exists -- all inserts

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            insert_order.append(table)
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)

        await restore_database(adapter, schema, backup_file, user_id="u1")

        assert insert_order == ["authors", "books", "chapters"]

    async def test_fk_remapping_parent(self, schema, tmp_path):
        """Parent FK is remapped from old ID to new ID."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, self._valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        inserted_data = {}

        async def _insert(table, data):
            if table == "authors":
                result = dict(data)
                result["id"] = "new-a1"  # New PK assigned by DB
                inserted_data[table] = result
                return result
            if table == "books":
                inserted_data[table] = dict(data)
                return dict(data)
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)

        await restore_database(adapter, schema, backup_file, user_id="u1")

        # books.author_id should be remapped from "a1" to "new-a1"
        books_insert_call = [
            c for c in adapter.insert.call_args_list
            if c.args[0] == "books"
        ]
        assert len(books_insert_call) == 1
        book_data = books_insert_call[0].kwargs.get("data") or books_insert_call[0].args[1]
        assert book_data["author_id"] == "new-a1"

    async def test_optional_ref_nulled_when_missing(self, schema, tmp_path):
        """Optional ref is nulled out when referenced row not in id_maps."""
        backup_data = self._valid_backup_data()
        # Set editor_id to a value that won't be in id_maps
        backup_data["chapters"][0]["editor_id"] = "unknown-author"
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, backup_data)

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            result = dict(data)
            if table == "authors":
                result["id"] = "a1"
            elif table == "books":
                result["id"] = "b1"
            return result

        adapter.insert = AsyncMock(side_effect=_insert)

        await restore_database(adapter, schema, backup_file, user_id="u1")

        chapter_insert = [
            c for c in adapter.insert.call_args_list
            if c.args[0] == "chapters"
        ]
        assert len(chapter_insert) == 1
        ch_data = chapter_insert[0].kwargs.get("data") or chapter_insert[0].args[1]
        assert ch_data["editor_id"] is None

    async def test_optional_ref_remapped_when_found(self, schema, tmp_path):
        """Optional ref is remapped when referenced row IS in id_maps."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, self._valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            result = dict(data)
            if table == "authors":
                result["id"] = "new-a1"
            elif table == "books":
                result["id"] = "new-b1"
            return result

        adapter.insert = AsyncMock(side_effect=_insert)

        await restore_database(adapter, schema, backup_file, user_id="u1")

        chapter_insert = [
            c for c in adapter.insert.call_args_list
            if c.args[0] == "chapters"
        ]
        ch_data = chapter_insert[0].kwargs.get("data") or chapter_insert[0].args[1]
        # editor_id was "a1" -> should be remapped to "new-a1"
        assert ch_data["editor_id"] == "new-a1"

    async def test_skip_mode_skips_existing(self, schema, tmp_path):
        """Skip mode increments skipped count and does not insert/update."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, self._valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            if table == "authors":
                return [{"id": "existing-a1"}]
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            result = dict(data)
            if table == "books":
                result["id"] = "b1"
            return result

        adapter.insert = AsyncMock(side_effect=_insert)

        summary = await restore_database(
            adapter, schema, backup_file, user_id="u1", mode="skip"
        )

        assert summary["authors"]["skipped"] == 1
        assert summary["authors"]["inserted"] == 0

    async def test_overwrite_mode_updates_existing(self, schema, tmp_path):
        """Overwrite mode calls adapter.update for existing records."""
        backup_data = {
            "metadata": {
                "created_at": "2026-01-01T00:00:00",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [
                {"id": "a1", "slug": "alice", "user_id": "u1", "bio": "updated"},
            ],
            "books": [],
            "chapters": [],
        }
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, backup_data)

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            if table == "authors":
                return [{"id": "existing-a1"}]
            return []

        adapter.select = AsyncMock(side_effect=_select)

        summary = await restore_database(
            adapter, schema, backup_file, user_id="u1", mode="overwrite"
        )

        assert summary["authors"]["updated"] == 1
        adapter.update.assert_called_once()
        call_args = adapter.update.call_args
        assert call_args.args[0] == "authors"

    async def test_fail_mode_raises_on_existing(self, schema, tmp_path):
        """Fail mode raises ValueError when record already exists."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, self._valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            if table == "authors":
                return [{"id": "existing-a1"}]
            return []

        adapter.select = AsyncMock(side_effect=_select)

        with pytest.raises(ValueError, match="already exists"):
            await restore_database(
                adapter, schema, backup_file, user_id="u1", mode="fail"
            )

    async def test_dry_run_does_not_write(self, schema, tmp_path):
        """Dry run does not call insert or update."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, self._valid_backup_data())

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        summary = await restore_database(
            adapter, schema, backup_file, user_id="u1", dry_run=True
        )

        adapter.insert.assert_not_called()
        adapter.update.assert_not_called()
        assert summary["dry_run"] is True
        # All rows counted as inserted in dry run
        assert summary["authors"]["inserted"] == 1
        assert summary["books"]["inserted"] == 1
        assert summary["chapters"]["inserted"] == 1

    async def test_user_id_overridden(self, schema, tmp_path):
        """Restored rows get current user_id, not backup user_id."""
        backup_data = self._valid_backup_data()
        backup_data["metadata"]["user_id"] = "old-user"
        backup_data["authors"][0]["user_id"] = "old-user"
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, backup_data)

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            return dict(data)

        adapter.insert = AsyncMock(side_effect=_insert)

        await restore_database(adapter, schema, backup_file, user_id="new-user")

        author_insert = [
            c for c in adapter.insert.call_args_list
            if c.args[0] == "authors"
        ]
        author_data = author_insert[0].kwargs.get("data") or author_insert[0].args[1]
        assert author_data["user_id"] == "new-user"

    async def test_summary_has_dynamic_table_names(self, schema, tmp_path):
        """Summary dict keys match schema table names, not hardcoded MC names."""
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, self._valid_backup_data())

        adapter = _make_mock_adapter()
        summary = await restore_database(
            adapter, schema, backup_file, user_id="u1", dry_run=True
        )

        # Should have schema table names
        assert "authors" in summary
        assert "books" in summary
        assert "chapters" in summary
        # Should NOT have MC table names
        assert "projects" not in summary
        assert "milestones" not in summary
        assert "tasks" not in summary

    async def test_child_skipped_when_parent_missing_from_id_maps(
        self, schema, tmp_path
    ):
        """Child row is skipped when parent FK value is not in id_maps."""
        backup_data = self._valid_backup_data()
        # book references author "a999" which is not in the backup
        backup_data["books"][0]["author_id"] = "a999"
        backup_file = str(tmp_path / "backup.json")
        self._write_backup(backup_file, backup_data)

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        async def _insert(table, data):
            result = dict(data)
            if table == "authors":
                result["id"] = "a1"
            return result

        adapter.insert = AsyncMock(side_effect=_insert)

        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        assert summary["books"]["skipped"] == 1
        assert summary["books"]["inserted"] == 0


# ------------------------------------------------------------------
# validate_backup tests
# ------------------------------------------------------------------


class TestValidateBackup:
    """Test validate_backup checks against schema table names."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    def _write_backup(self, path: str, data: dict) -> None:
        with open(path, "w") as f:
            json.dump(data, f)

    def test_valid_backup(self, schema, tmp_path):
        """A valid backup passes validation."""
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [{"id": "a1", "slug": "alice"}],
            "books": [{"id": "b1", "slug": "book1", "author_id": "a1"}],
            "chapters": [{"id": "c1", "slug": "ch1", "book_id": "b1"}],
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_missing_table_key(self, schema, tmp_path):
        """Missing table key (from schema) is an error."""
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [],
            "books": [],
            # "chapters" missing
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        assert result["valid"] is False
        assert any("chapters" in e for e in result["errors"])

    def test_wrong_version_rejected(self, schema, tmp_path):
        """Version '1.0' is rejected (require '1.1')."""
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.0",
            },
            "authors": [],
            "books": [],
            "chapters": [],
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        assert result["valid"] is False
        assert any("1.0" in e or "version" in e.lower() for e in result["errors"])

    def test_version_1_1_accepted(self, schema, tmp_path):
        """Version '1.1' is accepted."""
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [],
            "books": [],
            "chapters": [],
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        assert result["valid"] is True

    def test_file_not_found(self, schema):
        """Non-existent file produces error."""
        result = validate_backup("/nonexistent/backup.json", schema)
        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_invalid_json(self, schema, tmp_path):
        """Invalid JSON produces error."""
        path = str(tmp_path / "bad.json")
        Path(path).write_text("not json {{{")
        result = validate_backup(path, schema)
        assert result["valid"] is False
        assert any("JSON" in e for e in result["errors"])

    def test_missing_pk_in_row(self, schema, tmp_path):
        """Row missing PK field is an error."""
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [{"slug": "alice"}],  # missing "id"
            "books": [],
            "chapters": [],
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        assert result["valid"] is False
        assert any("'id'" in e for e in result["errors"])

    def test_orphaned_child_warning(self, schema, tmp_path):
        """Child with parent FK not in backup produces warning."""
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [{"id": "a1", "slug": "alice"}],
            "books": [{"id": "b1", "slug": "book1", "author_id": "a999"}],
            "chapters": [],
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        # Orphaned child is a warning, not an error
        assert result["valid"] is True
        assert any("Orphaned" in w for w in result["warnings"])

    def test_checks_schema_table_names_not_hardcoded(self, schema, tmp_path):
        """validate_backup uses schema table names, not hardcoded MC names."""
        # Create a backup with MC names -- should fail validation
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "projects": [],  # MC name, not in schema
            "milestones": [],
            "tasks": [],
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        # Should be invalid because schema tables (authors, books, chapters) are missing
        assert result["valid"] is False

    def test_missing_slug_field_in_row(self, schema, tmp_path):
        """Row missing slug field is an error."""
        data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [{"id": "a1"}],  # missing "slug"
            "books": [],
            "chapters": [],
        }
        path = str(tmp_path / "backup.json")
        self._write_backup(path, data)

        result = validate_backup(path, schema)
        assert result["valid"] is False
        assert any("'slug'" in e for e in result["errors"])


# ------------------------------------------------------------------
# Round-trip backup/restore
# ------------------------------------------------------------------


class TestRoundTrip:
    """Test round-trip backup and restore preserves data."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_round_trip_preserves_data(self, schema, tmp_path):
        """Data backed up can be restored with correct FK remapping."""
        # Setup: adapter with data
        original_data = {
            "authors": [
                {"id": "a1", "slug": "alice", "user_id": "u1", "bio": "Writer"},
            ],
            "books": [
                {"id": "b1", "slug": "book1", "user_id": "u1", "author_id": "a1", "title": "Novel"},
            ],
            "chapters": [
                {"id": "c1", "slug": "ch1", "user_id": "u1", "book_id": "b1", "editor_id": "a1"},
            ],
        }

        backup_adapter = AsyncMock()

        async def _backup_select(table, columns="*", filters=None, order_by=None):
            return original_data.get(table, [])

        backup_adapter.select = AsyncMock(side_effect=_backup_select)

        # Step 1: Backup
        backup_path = str(tmp_path / "roundtrip.json")
        await backup_database(
            backup_adapter, schema, user_id="u1", output_path=backup_path
        )

        # Step 2: Verify backup file
        with open(backup_path) as f:
            backup_data = json.load(f)
        assert len(backup_data["authors"]) == 1
        assert len(backup_data["books"]) == 1
        assert len(backup_data["chapters"]) == 1

        # Step 3: Restore to "new" database
        restore_adapter = AsyncMock()

        async def _restore_select(table, columns="*", filters=None, order_by=None):
            return []  # Empty database

        restore_adapter.select = AsyncMock(side_effect=_restore_select)

        new_id_counter = {"n": 0}

        async def _restore_insert(table, data):
            new_id_counter["n"] += 1
            result = dict(data)
            result["id"] = f"new-{new_id_counter['n']}"
            return result

        restore_adapter.insert = AsyncMock(side_effect=_restore_insert)

        summary = await restore_database(
            restore_adapter, schema, backup_path, user_id="u1"
        )

        assert summary["authors"]["inserted"] == 1
        assert summary["books"]["inserted"] == 1
        assert summary["chapters"]["inserted"] == 1

        # Verify FK remapping happened: books.author_id should be "new-1" (new author id)
        book_insert = [
            c for c in restore_adapter.insert.call_args_list
            if c.args[0] == "books"
        ]
        book_data = book_insert[0].kwargs.get("data") or book_insert[0].args[1]
        assert book_data["author_id"] == "new-1"

        # Verify chapters.book_id remapped to new book id
        ch_insert = [
            c for c in restore_adapter.insert.call_args_list
            if c.args[0] == "chapters"
        ]
        ch_data = ch_insert[0].kwargs.get("data") or ch_insert[0].args[1]
        assert ch_data["book_id"] == "new-2"
        # editor_id (optional ref) remapped to new author id
        assert ch_data["editor_id"] == "new-1"


# ------------------------------------------------------------------
# _find_table_def helper
# ------------------------------------------------------------------


class TestFindTableDef:
    """Test the _find_table_def helper."""

    def test_finds_existing_table(self):
        schema = _sample_schema()
        result = _find_table_def(schema, "books")
        assert result is not None
        assert result.name == "books"

    def test_returns_none_for_missing_table(self):
        schema = _sample_schema()
        result = _find_table_def(schema, "nonexistent")
        assert result is None


# ------------------------------------------------------------------
# id_maps structure
# ------------------------------------------------------------------


class TestIdMaps:
    """Test that id_maps is built generically keyed by table name."""

    @pytest.fixture
    def schema(self):
        return _sample_schema()

    async def test_id_maps_built_per_table(self, schema, tmp_path):
        """id_maps tracks old->new PK mapping for each table."""
        backup_data = {
            "metadata": {
                "created_at": "2026-01-01",
                "user_id": "u1",
                "backup_type": "full",
                "version": "1.1",
            },
            "authors": [
                {"id": "old-a1", "slug": "alice", "user_id": "u1"},
                {"id": "old-a2", "slug": "bob", "user_id": "u1"},
            ],
            "books": [],
            "chapters": [],
        }
        backup_file = str(tmp_path / "backup.json")
        with open(backup_file, "w") as f:
            json.dump(backup_data, f)

        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        id_counter = {"n": 0}

        async def _insert(table, data):
            id_counter["n"] += 1
            result = dict(data)
            result["id"] = f"new-{id_counter['n']}"
            return result

        adapter.insert = AsyncMock(side_effect=_insert)

        summary = await restore_database(adapter, schema, backup_file, user_id="u1")

        assert summary["authors"]["inserted"] == 2
        # Both old authors mapped to new IDs
        assert adapter.insert.call_count == 2

"""Tests for Step 11: Generalize Sync Module.

Verifies that sync.py is free of hardcoded MC-specific code (no
``"projects"``, ``"milestones"``, ``"tasks"`` string literals), uses
caller-declared table lists, has async ``compare_profiles`` and
``sync_data`` functions, and supports dual-path sync (direct insert
vs backup/restore).
"""

import ast
import inspect
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef
from db_adapter.schema.sync import (
    SyncResult,
    _get_data_counts,
    _get_slugs,
    compare_profiles,
    sync_data,
)

# Path to source file for AST/source inspection
SYNC_PY = (
    Path(__file__).parent.parent
    / "src"
    / "db_adapter"
    / "schema"
    / "sync.py"
)


# ------------------------------------------------------------------
# Helper: sample data and mocks
# ------------------------------------------------------------------


def _sample_schema() -> BackupSchema:
    """A 2-table schema for testing (generic names)."""
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


def _make_mock_adapter(select_results: dict[str, list] | None = None) -> AsyncMock:
    """Create an AsyncMock adapter that returns predictable results.

    Args:
        select_results: mapping of table name -> result list.
            When None, select returns empty list by default.
    """
    adapter = AsyncMock()
    _select_results = select_results or {}

    async def _select(table, columns="*", filters=None, order_by=None):
        return list(_select_results.get(table, []))

    adapter.select = AsyncMock(side_effect=_select)

    _insert_counter = {"val": 100}

    async def _insert(table, data):
        _insert_counter["val"] += 1
        result = dict(data)
        result["id"] = f"new-{_insert_counter['val']}"
        return result

    adapter.insert = AsyncMock(side_effect=_insert)
    adapter.update = AsyncMock()
    adapter.delete = AsyncMock()
    adapter.close = AsyncMock()

    return adapter


# ==================================================================
# Test Group 1: SyncResult model -- no hardcoded defaults
# ==================================================================


class TestSyncResultModel:
    """Verify SyncResult has no hardcoded table name defaults."""

    def test_source_counts_default_empty(self) -> None:
        """SyncResult.source_counts defaults to empty dict."""
        result = SyncResult()
        assert result.source_counts == {}

    def test_dest_counts_default_empty(self) -> None:
        """SyncResult.dest_counts defaults to empty dict."""
        result = SyncResult()
        assert result.dest_counts == {}

    def test_sync_plan_default_empty(self) -> None:
        """SyncResult.sync_plan defaults to empty dict."""
        result = SyncResult()
        assert result.sync_plan == {}

    def test_errors_default_empty_list(self) -> None:
        """SyncResult.errors defaults to empty list."""
        result = SyncResult()
        assert result.errors == []

    def test_synced_count_default_zero(self) -> None:
        """SyncResult.synced_count defaults to 0."""
        result = SyncResult()
        assert result.synced_count == 0

    def test_skipped_count_default_zero(self) -> None:
        """SyncResult.skipped_count defaults to 0."""
        result = SyncResult()
        assert result.skipped_count == 0

    def test_no_hardcoded_table_names_in_defaults(self) -> None:
        """SyncResult defaults contain no pre-populated table names."""
        result = SyncResult()
        # All dict fields must be empty
        assert len(result.source_counts) == 0
        assert len(result.dest_counts) == 0
        assert len(result.sync_plan) == 0

    def test_dynamic_table_names(self) -> None:
        """SyncResult accepts arbitrary table names."""
        result = SyncResult(
            source_counts={"widgets": 5, "gadgets": 3},
            dest_counts={"widgets": 2, "gadgets": 1},
            sync_plan={
                "widgets": {"new": 3, "update": 2},
                "gadgets": {"new": 2, "update": 1},
            },
        )
        assert result.source_counts["widgets"] == 5
        assert result.sync_plan["gadgets"]["new"] == 2


# ==================================================================
# Test Group 2: AST-based source inspection (no MC-specific code)
# ==================================================================


class TestSyncNoMCReferences:
    """Verify sync.py has zero hardcoded MC-specific string literals."""

    def _get_string_literals(self) -> list[str]:
        """Extract all string literals from sync.py AST."""
        source = SYNC_PY.read_text()
        tree = ast.parse(source)
        literals = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.append(node.value)
        return literals

    def test_no_projects_literal(self) -> None:
        """No 'projects' string literal in sync.py."""
        literals = self._get_string_literals()
        assert "projects" not in literals

    def test_no_milestones_literal(self) -> None:
        """No 'milestones' string literal in sync.py."""
        literals = self._get_string_literals()
        assert "milestones" not in literals

    def test_no_tasks_literal(self) -> None:
        """No 'tasks' string literal in sync.py."""
        literals = self._get_string_literals()
        assert "tasks" not in literals

    def test_no_get_dev_user_id_import(self) -> None:
        """No 'get_dev_user_id' import in sync.py."""
        source = SYNC_PY.read_text()
        assert "get_dev_user_id" not in source

    def test_no_from_db_import(self) -> None:
        """No 'from db import' in sync.py."""
        source = SYNC_PY.read_text()
        assert "from db import" not in source

    def test_no_subprocess_import(self) -> None:
        """No 'subprocess' usage in sync.py."""
        source = SYNC_PY.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "subprocess"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "subprocess"


# ==================================================================
# Test Group 3: Function signatures are async with correct params
# ==================================================================


class TestSyncFunctionSignatures:
    """Verify async signatures and parameter lists."""

    def test_compare_profiles_is_async(self) -> None:
        """compare_profiles is an async function."""
        assert inspect.iscoroutinefunction(compare_profiles)

    def test_sync_data_is_async(self) -> None:
        """sync_data is an async function."""
        assert inspect.iscoroutinefunction(sync_data)

    def test_get_data_counts_is_async(self) -> None:
        """_get_data_counts is an async function."""
        assert inspect.iscoroutinefunction(_get_data_counts)

    def test_get_slugs_is_async(self) -> None:
        """_get_slugs is an async function."""
        assert inspect.iscoroutinefunction(_get_slugs)

    def test_compare_profiles_accepts_tables(self) -> None:
        """compare_profiles has a 'tables' parameter."""
        sig = inspect.signature(compare_profiles)
        assert "tables" in sig.parameters

    def test_compare_profiles_accepts_user_id(self) -> None:
        """compare_profiles has a 'user_id' parameter."""
        sig = inspect.signature(compare_profiles)
        assert "user_id" in sig.parameters

    def test_compare_profiles_accepts_user_field(self) -> None:
        """compare_profiles has a 'user_field' parameter with default."""
        sig = inspect.signature(compare_profiles)
        param = sig.parameters["user_field"]
        assert param.default == "user_id"

    def test_compare_profiles_accepts_slug_field(self) -> None:
        """compare_profiles has a 'slug_field' parameter with default."""
        sig = inspect.signature(compare_profiles)
        param = sig.parameters["slug_field"]
        assert param.default == "slug"

    def test_compare_profiles_accepts_env_prefix(self) -> None:
        """compare_profiles has an 'env_prefix' parameter with default."""
        sig = inspect.signature(compare_profiles)
        param = sig.parameters["env_prefix"]
        assert param.default == ""

    def test_sync_data_accepts_tables(self) -> None:
        """sync_data has a 'tables' parameter."""
        sig = inspect.signature(sync_data)
        assert "tables" in sig.parameters

    def test_sync_data_accepts_schema(self) -> None:
        """sync_data has a 'schema' parameter."""
        sig = inspect.signature(sync_data)
        assert "schema" in sig.parameters

    def test_sync_data_accepts_dry_run(self) -> None:
        """sync_data has a 'dry_run' parameter with default True."""
        sig = inspect.signature(sync_data)
        param = sig.parameters["dry_run"]
        assert param.default is True

    def test_sync_data_accepts_confirm(self) -> None:
        """sync_data has a 'confirm' parameter with default False."""
        sig = inspect.signature(sync_data)
        param = sig.parameters["confirm"]
        assert param.default is False


# ==================================================================
# Test Group 4: _get_data_counts iterates dynamic table list
# ==================================================================


class TestGetDataCounts:
    """Verify _get_data_counts uses caller-provided table list."""

    @pytest.mark.asyncio
    async def test_iterates_provided_tables(self) -> None:
        """_get_data_counts queries each table in the provided list."""
        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return [{"cnt": 10}]

        adapter.select = AsyncMock(side_effect=_select)

        tables = ["widgets", "gadgets", "sprockets"]
        counts = await _get_data_counts(adapter, "u1", tables, "user_id")

        assert set(counts.keys()) == {"widgets", "gadgets", "sprockets"}
        assert all(v == 10 for v in counts.values())

    @pytest.mark.asyncio
    async def test_uses_user_field_parameter(self) -> None:
        """_get_data_counts uses the provided user_field for filtering."""
        adapter = AsyncMock()
        calls: list[dict] = []

        async def _select(table, columns="*", filters=None, order_by=None):
            calls.append({"table": table, "filters": filters})
            return [{"cnt": 5}]

        adapter.select = AsyncMock(side_effect=_select)

        await _get_data_counts(adapter, "u1", ["items"], "owner_id")

        assert calls[0]["filters"] == {"owner_id": "u1"}

    @pytest.mark.asyncio
    async def test_empty_result_returns_zero(self) -> None:
        """_get_data_counts returns 0 when select returns empty list."""
        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            return []

        adapter.select = AsyncMock(side_effect=_select)

        counts = await _get_data_counts(adapter, "u1", ["items"], "user_id")
        assert counts["items"] == 0


# ==================================================================
# Test Group 5: _get_slugs uses flat slug per table
# ==================================================================


class TestGetSlugs:
    """Verify _get_slugs uses flat slug resolution (no hierarchical)."""

    @pytest.mark.asyncio
    async def test_flat_slugs_per_table(self) -> None:
        """_get_slugs returns flat slug values, not project_slug/slug."""
        adapter = AsyncMock()

        async def _select(table, columns="*", filters=None, order_by=None):
            if table == "authors":
                return [{"slug": "alice"}, {"slug": "bob"}]
            if table == "books":
                return [{"slug": "book-1"}, {"slug": "book-2"}]
            return []

        adapter.select = AsyncMock(side_effect=_select)

        slugs = await _get_slugs(
            adapter, "u1", ["authors", "books"], "slug", "user_id"
        )

        assert slugs["authors"] == {"alice", "bob"}
        assert slugs["books"] == {"book-1", "book-2"}
        # No hierarchical slugs (no "/" in values)
        for table_slugs in slugs.values():
            for s in table_slugs:
                assert "/" not in s

    @pytest.mark.asyncio
    async def test_uses_custom_slug_field(self) -> None:
        """_get_slugs queries the provided slug_field column."""
        adapter = AsyncMock()
        calls: list[dict] = []

        async def _select(table, columns="*", filters=None, order_by=None):
            calls.append({"table": table, "columns": columns})
            return [{"code": "A1"}]

        adapter.select = AsyncMock(side_effect=_select)

        slugs = await _get_slugs(
            adapter, "u1", ["items"], "code", "user_id"
        )

        assert calls[0]["columns"] == "code"
        assert slugs["items"] == {"A1"}

    @pytest.mark.asyncio
    async def test_uses_custom_user_field(self) -> None:
        """_get_slugs filters by the provided user_field."""
        adapter = AsyncMock()
        calls: list[dict] = []

        async def _select(table, columns="*", filters=None, order_by=None):
            calls.append({"filters": filters})
            return []

        adapter.select = AsyncMock(side_effect=_select)

        await _get_slugs(adapter, "u1", ["items"], "slug", "owner_id")
        assert calls[0]["filters"] == {"owner_id": "u1"}


# ==================================================================
# Test Group 6: compare_profiles integration (mocked adapters)
# ==================================================================


class TestCompareProfiles:
    """Verify compare_profiles creates adapters and compares data."""

    @pytest.mark.asyncio
    async def test_compare_with_dynamic_tables(self) -> None:
        """compare_profiles uses caller-provided table list."""
        source_adapter = _make_mock_adapter({
            "widgets": [{"cnt": 5}],
        })
        dest_adapter = _make_mock_adapter({
            "widgets": [{"cnt": 3}],
        })

        # Override select to return both count and slug queries
        call_idx = {"val": 0}

        async def _source_select(table, columns="*", filters=None, order_by=None):
            call_idx["val"] += 1
            if columns == "count(*) as cnt":
                return [{"cnt": 5}]
            return [{"slug": "w1"}, {"slug": "w2"}, {"slug": "w3"},
                    {"slug": "w4"}, {"slug": "w5"}]

        async def _dest_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 3}]
            return [{"slug": "w1"}, {"slug": "w2"}, {"slug": "w3"}]

        source_adapter.select = AsyncMock(side_effect=_source_select)
        dest_adapter.select = AsyncMock(side_effect=_dest_select)

        adapters = iter([source_adapter, dest_adapter])

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapters),
        ):
            result = await compare_profiles(
                "src", "dst",
                tables=["widgets"],
                user_id="u1",
            )

        assert result.success
        assert result.source_counts["widgets"] == 5
        assert result.dest_counts["widgets"] == 3
        assert result.sync_plan["widgets"]["new"] == 2
        assert result.sync_plan["widgets"]["update"] == 3

    @pytest.mark.asyncio
    async def test_compare_source_error(self) -> None:
        """compare_profiles handles source adapter creation failure."""
        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=Exception("Connection refused"),
        ):
            result = await compare_profiles(
                "bad-src", "dst",
                tables=["items"],
                user_id="u1",
            )

        assert not result.success
        assert len(result.errors) > 0
        assert "source" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_compare_dest_error(self) -> None:
        """compare_profiles handles dest adapter creation failure."""
        source_adapter = _make_mock_adapter()
        call_count = {"val": 0}

        async def _create(name, prefix=""):
            call_count["val"] += 1
            if call_count["val"] == 1:
                return source_adapter
            raise Exception("Connection refused")

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=_create,
        ):
            result = await compare_profiles(
                "src", "bad-dst",
                tables=["items"],
                user_id="u1",
            )

        assert not result.success
        assert len(result.errors) > 0
        assert "destination" in result.errors[0].lower()
        # Source adapter should be closed
        source_adapter.close.assert_awaited_once()


# ==================================================================
# Test Group 7: sync_data -- direct insert path
# ==================================================================


class TestSyncDataDirect:
    """Verify sync_data direct insert path (schema=None)."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_comparison(self) -> None:
        """sync_data with dry_run=True returns comparison without changes."""
        source_adapter = _make_mock_adapter()
        dest_adapter = _make_mock_adapter()

        async def _select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            return []

        source_adapter.select = AsyncMock(side_effect=_select)
        dest_adapter.select = AsyncMock(side_effect=_select)

        adapters = iter([source_adapter, dest_adapter])

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapters),
        ):
            result = await sync_data(
                "src", "dst",
                tables=["items"],
                user_id="u1",
                dry_run=True,
            )

        assert result.success
        # No insert calls in dry run
        dest_adapter.insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirm_required(self) -> None:
        """sync_data without confirm=True refuses to sync."""
        source_adapter = _make_mock_adapter()
        dest_adapter = _make_mock_adapter()

        async def _select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            return []

        source_adapter.select = AsyncMock(side_effect=_select)
        dest_adapter.select = AsyncMock(side_effect=_select)

        adapters = iter([source_adapter, dest_adapter])

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapters),
        ):
            result = await sync_data(
                "src", "dst",
                tables=["items"],
                user_id="u1",
                dry_run=False,
                confirm=False,
            )

        assert not result.success
        assert any("confirm" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_direct_insert_new_rows(self) -> None:
        """Direct sync inserts rows not present in destination."""
        # Source has 2 rows, dest has 0
        source_adapter = _make_mock_adapter()
        dest_adapter = _make_mock_adapter()

        source_call_count = {"val": 0}

        async def _source_select(table, columns="*", filters=None, order_by=None):
            source_call_count["val"] += 1
            if columns == "count(*) as cnt":
                return [{"cnt": 2}]
            if columns == "slug":
                return [{"slug": "a"}, {"slug": "b"}]
            # columns == "*"
            return [
                {"id": "1", "slug": "a", "name": "Alice", "user_id": "u1"},
                {"id": "2", "slug": "b", "name": "Bob", "user_id": "u1"},
            ]

        async def _dest_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            if columns == "slug":
                return []  # No existing slugs
            return []

        source_adapter.select = AsyncMock(side_effect=_source_select)
        dest_adapter.select = AsyncMock(side_effect=_dest_select)

        # For compare_profiles (first call pair) and sync_data (second call pair)
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
                tables=["items"],
                user_id="u1",
                dry_run=False,
                confirm=True,
            )

        assert result.success
        assert result.synced_count == 2
        assert result.skipped_count == 0

    @pytest.mark.asyncio
    async def test_direct_insert_skips_existing_slugs(self) -> None:
        """Direct sync skips rows whose slug already exists in dest."""
        source_adapter = _make_mock_adapter()
        dest_adapter = _make_mock_adapter()

        async def _source_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 2}]
            if columns == "slug":
                return [{"slug": "a"}, {"slug": "b"}]
            return [
                {"id": "1", "slug": "a", "name": "Alice", "user_id": "u1"},
                {"id": "2", "slug": "b", "name": "Bob", "user_id": "u1"},
            ]

        async def _dest_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 1}]
            if columns == "slug":
                return [{"slug": "a"}]  # "a" already exists
            return []

        source_adapter.select = AsyncMock(side_effect=_source_select)
        dest_adapter.select = AsyncMock(side_effect=_dest_select)

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
        assert result.synced_count == 1  # Only "b" inserted
        assert result.skipped_count == 1  # "a" skipped


# ==================================================================
# Test Group 8: sync_data -- backup/restore path
# ==================================================================


class TestSyncDataBackupRestore:
    """Verify sync_data backup/restore path (schema provided)."""

    @pytest.mark.asyncio
    async def test_backup_restore_path_called(self) -> None:
        """When schema is provided, sync uses backup/restore functions."""
        source_adapter = _make_mock_adapter()
        dest_adapter = _make_mock_adapter()

        async def _select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            return []

        source_adapter.select = AsyncMock(side_effect=_select)
        dest_adapter.select = AsyncMock(side_effect=_select)

        adapter_sequence = [
            source_adapter, dest_adapter,  # compare_profiles
            source_adapter, dest_adapter,  # _sync_via_backup
        ]
        adapter_iter = iter(adapter_sequence)

        schema = _sample_schema()

        mock_backup = AsyncMock(return_value="/tmp/test-backup.json")
        mock_restore = AsyncMock(return_value={
            "dry_run": False,
            "authors": {"inserted": 2, "updated": 0, "skipped": 0, "failed": 0},
            "books": {"inserted": 3, "updated": 1, "skipped": 0, "failed": 0},
        })

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapter_iter),
        ), patch(
            "db_adapter.backup.backup_restore.backup_database",
            mock_backup,
        ), patch(
            "db_adapter.backup.backup_restore.restore_database",
            mock_restore,
        ):
            result = await sync_data(
                "src", "dst",
                tables=["authors", "books"],
                user_id="u1",
                schema=schema,
                dry_run=False,
                confirm=True,
            )

        assert result.success
        assert result.synced_count == 6  # 2+3 inserted + 1 updated
        assert result.skipped_count == 0

    @pytest.mark.asyncio
    async def test_backup_restore_error_handling(self) -> None:
        """Backup/restore path handles errors gracefully."""
        source_adapter = _make_mock_adapter()
        dest_adapter = _make_mock_adapter()

        async def _select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                return [{"cnt": 0}]
            return []

        source_adapter.select = AsyncMock(side_effect=_select)
        dest_adapter.select = AsyncMock(side_effect=_select)

        adapter_sequence = [
            source_adapter, dest_adapter,
            source_adapter, dest_adapter,
        ]
        adapter_iter = iter(adapter_sequence)

        schema = _sample_schema()

        mock_backup = AsyncMock(side_effect=Exception("Backup failed"))

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapter_iter),
        ), patch(
            "db_adapter.backup.backup_restore.backup_database",
            mock_backup,
        ), patch(
            "db_adapter.backup.backup_restore.restore_database",
            AsyncMock(),
        ):
            result = await sync_data(
                "src", "dst",
                tables=["authors", "books"],
                user_id="u1",
                schema=schema,
                dry_run=False,
                confirm=True,
            )

        assert not result.success
        assert any("backup/restore" in e.lower() for e in result.errors)


# ==================================================================
# Test Group 9: Internal adapter creation uses correct imports
# ==================================================================


class TestInternalAdapterCreation:
    """Verify sync.py uses db_adapter imports for adapter creation."""

    def test_uses_resolve_url_from_factory(self) -> None:
        """sync.py imports resolve_url from db_adapter.factory."""
        source = SYNC_PY.read_text()
        assert "from db_adapter.factory import resolve_url" in source

    def test_uses_load_db_config_from_loader(self) -> None:
        """sync.py imports load_db_config from db_adapter.config.loader."""
        source = SYNC_PY.read_text()
        assert "from db_adapter.config.loader import load_db_config" in source

    def test_uses_async_postgres_adapter(self) -> None:
        """sync.py imports AsyncPostgresAdapter from db_adapter.adapters.postgres."""
        source = SYNC_PY.read_text()
        assert "from db_adapter.adapters.postgres import AsyncPostgresAdapter" in source

    def test_uses_backup_restore_imports(self) -> None:
        """sync.py imports backup_database and restore_database."""
        source = SYNC_PY.read_text()
        assert "from db_adapter.backup.backup_restore import backup_database" in source
        assert "restore_database" in source


# ==================================================================
# Test Group 10: No subprocess usage
# ==================================================================


class TestNoSubprocessUsage:
    """Verify subprocess is not used in sync.py."""

    def test_no_subprocess_run(self) -> None:
        """No subprocess.run() calls in sync.py."""
        source = SYNC_PY.read_text()
        assert "subprocess.run" not in source
        assert "subprocess.call" not in source
        assert "subprocess.Popen" not in source

    def test_no_subprocess_in_ast(self) -> None:
        """No subprocess module usage detected via AST."""
        source = SYNC_PY.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                    pytest.fail(f"Found subprocess.{node.attr} in sync.py")


# ==================================================================
# Test Group 11: Multiple tables in compare and sync
# ==================================================================


class TestMultipleTablesSync:
    """Verify sync works correctly with multiple tables."""

    @pytest.mark.asyncio
    async def test_compare_multiple_tables(self) -> None:
        """compare_profiles handles multiple tables correctly."""
        source_adapter = _make_mock_adapter()
        dest_adapter = _make_mock_adapter()

        async def _source_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                counts = {"authors": 3, "books": 7}
                return [{"cnt": counts.get(table, 0)}]
            slugs = {
                "authors": [{"slug": "a1"}, {"slug": "a2"}, {"slug": "a3"}],
                "books": [{"slug": "b1"}, {"slug": "b2"}, {"slug": "b3"},
                          {"slug": "b4"}, {"slug": "b5"}, {"slug": "b6"}, {"slug": "b7"}],
            }
            return slugs.get(table, [])

        async def _dest_select(table, columns="*", filters=None, order_by=None):
            if columns == "count(*) as cnt":
                counts = {"authors": 1, "books": 2}
                return [{"cnt": counts.get(table, 0)}]
            slugs = {
                "authors": [{"slug": "a1"}],
                "books": [{"slug": "b1"}, {"slug": "b2"}],
            }
            return slugs.get(table, [])

        source_adapter.select = AsyncMock(side_effect=_source_select)
        dest_adapter.select = AsyncMock(side_effect=_dest_select)

        adapters = iter([source_adapter, dest_adapter])

        with patch(
            "db_adapter.schema.sync._create_adapter_for_profile",
            side_effect=lambda name, prefix="": next(adapters),
        ):
            result = await compare_profiles(
                "src", "dst",
                tables=["authors", "books"],
                user_id="u1",
            )

        assert result.success
        assert result.source_counts == {"authors": 3, "books": 7}
        assert result.dest_counts == {"authors": 1, "books": 2}
        assert result.sync_plan["authors"]["new"] == 2
        assert result.sync_plan["authors"]["update"] == 1
        assert result.sync_plan["books"]["new"] == 5
        assert result.sync_plan["books"]["update"] == 2

"""Tests for Step 6: Convert Adapters to Async.

Verifies that DatabaseClient Protocol, AsyncPostgresAdapter, and
AsyncSupabaseAdapter are fully async, that old sync class names are
removed, and that JSONB_COLUMNS is a constructor parameter.
"""

import ast
import asyncio
import inspect
import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "db_adapter"
ADAPTERS_DIR = SRC_ROOT / "adapters"
BASE_PATH = ADAPTERS_DIR / "base.py"
POSTGRES_PATH = ADAPTERS_DIR / "postgres.py"
SUPABASE_PATH = ADAPTERS_DIR / "supabase.py"
INIT_PATH = ADAPTERS_DIR / "__init__.py"


# ============================================================================
# Test: Old Sync Classes/Functions Removed
# ============================================================================


class TestOldNamesRemoved:
    """Verify old sync class and function names no longer exist."""

    def _get_top_level_names(self, filepath: pathlib.Path) -> set[str]:
        """Get all top-level class, function, and assignment names."""
        tree = ast.parse(filepath.read_text())
        names: set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        return names

    def test_no_postgres_adapter_class(self) -> None:
        """PostgresAdapter class must not exist (replaced by AsyncPostgresAdapter)."""
        names = self._get_top_level_names(POSTGRES_PATH)
        assert "PostgresAdapter" not in names

    def test_async_postgres_adapter_exists(self) -> None:
        """AsyncPostgresAdapter class must exist."""
        names = self._get_top_level_names(POSTGRES_PATH)
        assert "AsyncPostgresAdapter" in names

    def test_no_create_mc_engine(self) -> None:
        """create_mc_engine function must not exist (replaced by create_async_engine_pooled)."""
        names = self._get_top_level_names(POSTGRES_PATH)
        assert "create_mc_engine" not in names

    def test_create_async_engine_pooled_exists(self) -> None:
        """create_async_engine_pooled function must exist."""
        names = self._get_top_level_names(POSTGRES_PATH)
        assert "create_async_engine_pooled" in names

    def test_no_supabase_adapter_class(self) -> None:
        """SupabaseAdapter class must not exist (replaced by AsyncSupabaseAdapter)."""
        names = self._get_top_level_names(SUPABASE_PATH)
        assert "SupabaseAdapter" not in names

    def test_async_supabase_adapter_exists(self) -> None:
        """AsyncSupabaseAdapter class must exist."""
        names = self._get_top_level_names(SUPABASE_PATH)
        assert "AsyncSupabaseAdapter" in names

    def test_no_jsonb_columns_class_constant(self) -> None:
        """JSONB_COLUMNS must not appear as a class constant in source."""
        source = POSTGRES_PATH.read_text()
        assert "JSONB_COLUMNS = frozenset" not in source


# ============================================================================
# Test: DatabaseClient Protocol is Async
# ============================================================================


class TestDatabaseClientProtocol:
    """Verify DatabaseClient Protocol defines async methods."""

    def test_protocol_select_is_async(self) -> None:
        """DatabaseClient.select must be async def."""
        from db_adapter.adapters.base import DatabaseClient

        method = getattr(DatabaseClient, "select")
        assert inspect.iscoroutinefunction(method), "select must be async def"

    def test_protocol_insert_is_async(self) -> None:
        """DatabaseClient.insert must be async def."""
        from db_adapter.adapters.base import DatabaseClient

        method = getattr(DatabaseClient, "insert")
        assert inspect.iscoroutinefunction(method), "insert must be async def"

    def test_protocol_update_is_async(self) -> None:
        """DatabaseClient.update must be async def."""
        from db_adapter.adapters.base import DatabaseClient

        method = getattr(DatabaseClient, "update")
        assert inspect.iscoroutinefunction(method), "update must be async def"

    def test_protocol_delete_is_async(self) -> None:
        """DatabaseClient.delete must be async def."""
        from db_adapter.adapters.base import DatabaseClient

        method = getattr(DatabaseClient, "delete")
        assert inspect.iscoroutinefunction(method), "delete must be async def"

    def test_protocol_close_is_async(self) -> None:
        """DatabaseClient.close must be async def."""
        from db_adapter.adapters.base import DatabaseClient

        method = getattr(DatabaseClient, "close")
        assert inspect.iscoroutinefunction(method), "close must be async def"

    def test_protocol_has_exactly_six_methods(self) -> None:
        """Protocol defines exactly 6 methods: select, insert, update, delete, execute, close."""
        tree = ast.parse(BASE_PATH.read_text())
        # Find the DatabaseClient class and extract method names
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef) and node.name == "DatabaseClient":
                method_names = [
                    child.name
                    for child in ast.iter_child_nodes(node)
                    if isinstance(child, ast.AsyncFunctionDef)
                ]
                assert set(method_names) == {"select", "insert", "update", "delete", "execute", "close"}
                return
        pytest.fail("DatabaseClient class not found in base.py")


# ============================================================================
# Test: AsyncPostgresAdapter Methods are Async
# ============================================================================


class TestAsyncPostgresAdapterMethods:
    """Verify AsyncPostgresAdapter has all async CRUD methods."""

    def test_select_is_async(self) -> None:
        """AsyncPostgresAdapter.select must be async def."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert inspect.iscoroutinefunction(AsyncPostgresAdapter.select)

    def test_insert_is_async(self) -> None:
        """AsyncPostgresAdapter.insert must be async def."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert inspect.iscoroutinefunction(AsyncPostgresAdapter.insert)

    def test_update_is_async(self) -> None:
        """AsyncPostgresAdapter.update must be async def."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert inspect.iscoroutinefunction(AsyncPostgresAdapter.update)

    def test_delete_is_async(self) -> None:
        """AsyncPostgresAdapter.delete must be async def."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert inspect.iscoroutinefunction(AsyncPostgresAdapter.delete)

    def test_close_is_async(self) -> None:
        """AsyncPostgresAdapter.close must be async def."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert inspect.iscoroutinefunction(AsyncPostgresAdapter.close)

    def test_test_connection_is_async(self) -> None:
        """AsyncPostgresAdapter.test_connection must be async def."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        assert inspect.iscoroutinefunction(AsyncPostgresAdapter.test_connection)


# ============================================================================
# Test: AsyncPostgresAdapter URL Rewriting
# ============================================================================


class TestAsyncPostgresAdapterURLRewrite:
    """Verify URL normalization from postgresql:// to postgresql+asyncpg://."""

    def test_postgresql_to_asyncpg(self) -> None:
        """postgresql:// is converted to postgresql+asyncpg://."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch("db_adapter.adapters.postgres.create_async_engine_pooled") as mock_create:
            mock_create.return_value = MagicMock()
            adapter = AsyncPostgresAdapter("postgresql://user:pass@localhost/db")
            # Check the URL passed to create_async_engine_pooled
            call_url = mock_create.call_args[0][0]
            assert call_url.startswith("postgresql+asyncpg://")
            assert "user:pass@localhost/db" in call_url

    def test_postgres_alias_to_asyncpg(self) -> None:
        """postgres:// (Heroku/Railway alias) is normalized to postgresql+asyncpg://."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch("db_adapter.adapters.postgres.create_async_engine_pooled") as mock_create:
            mock_create.return_value = MagicMock()
            adapter = AsyncPostgresAdapter("postgres://user:pass@host/db")
            call_url = mock_create.call_args[0][0]
            assert call_url.startswith("postgresql+asyncpg://")

    def test_asyncpg_url_unchanged(self) -> None:
        """postgresql+asyncpg:// URL is passed through without modification."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch("db_adapter.adapters.postgres.create_async_engine_pooled") as mock_create:
            mock_create.return_value = MagicMock()
            adapter = AsyncPostgresAdapter("postgresql+asyncpg://user:pass@host/db")
            call_url = mock_create.call_args[0][0]
            assert call_url.startswith("postgresql+asyncpg://")
            # Should NOT double-prefix
            assert "postgresql+asyncpg://postgresql+asyncpg://" not in call_url


# ============================================================================
# Test: JSONB_COLUMNS Constructor Parameter
# ============================================================================


class TestJSONBColumnsConstructorParam:
    """Verify JSONB_COLUMNS is a constructor parameter, not a class constant."""

    def test_constructor_accepts_jsonb_columns(self) -> None:
        """AsyncPostgresAdapter.__init__ accepts jsonb_columns parameter."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        sig = inspect.signature(AsyncPostgresAdapter.__init__)
        assert "jsonb_columns" in sig.parameters
        assert sig.parameters["jsonb_columns"].default is None

    def test_jsonb_columns_stored_as_frozenset(self) -> None:
        """jsonb_columns are stored internally as a frozenset."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch("db_adapter.adapters.postgres.create_async_engine_pooled") as mock_create:
            mock_create.return_value = MagicMock()
            adapter = AsyncPostgresAdapter(
                "postgresql://user:pass@host/db",
                jsonb_columns=["metadata", "tags"],
            )
            assert adapter._jsonb_columns == frozenset(["metadata", "tags"])

    def test_empty_jsonb_columns_default(self) -> None:
        """When jsonb_columns=None, stored as empty frozenset."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch("db_adapter.adapters.postgres.create_async_engine_pooled") as mock_create:
            mock_create.return_value = MagicMock()
            adapter = AsyncPostgresAdapter("postgresql://user:pass@host/db")
            assert adapter._jsonb_columns == frozenset()

    def test_no_class_level_jsonb_constant(self) -> None:
        """No class-level JSONB_COLUMNS attribute on AsyncPostgresAdapter."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        # Check that JSONB_COLUMNS is not a class attribute (only instance attribute)
        assert not hasattr(AsyncPostgresAdapter, "JSONB_COLUMNS"), (
            "JSONB_COLUMNS should not be a class attribute"
        )


# ============================================================================
# Test: AsyncPostgresAdapter Uses Async SQLAlchemy
# ============================================================================


class TestAsyncSQLAlchemyImports:
    """Verify postgres.py uses async SQLAlchemy imports."""

    def test_imports_create_async_engine(self) -> None:
        """postgres.py imports create_async_engine from sqlalchemy.ext.asyncio."""
        source = POSTGRES_PATH.read_text()
        assert "from sqlalchemy.ext.asyncio import" in source
        assert "create_async_engine" in source

    def test_imports_async_engine(self) -> None:
        """postgres.py imports AsyncEngine type."""
        source = POSTGRES_PATH.read_text()
        assert "AsyncEngine" in source

    def test_no_sync_create_engine(self) -> None:
        """postgres.py must not import sync create_engine."""
        tree = ast.parse(POSTGRES_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
                imported_names = [alias.name for alias in node.names]
                assert "create_engine" not in imported_names, (
                    "postgres.py still imports sync create_engine from sqlalchemy"
                )

    def test_uses_async_with_engine_connect(self) -> None:
        """All engine.connect() calls must use 'async with'."""
        source = POSTGRES_PATH.read_text()
        # Verify no sync 'with self._engine.connect()' exists
        assert "with self._engine.connect()" not in source.replace("async with", "___")

    def test_uses_async_with_engine_begin(self) -> None:
        """All engine.begin() calls must use 'async with'."""
        source = POSTGRES_PATH.read_text()
        # Verify no sync 'with self._engine.begin()' exists
        assert "with self._engine.begin()" not in source.replace("async with", "___")


# ============================================================================
# Test: AsyncSupabaseAdapter
# ============================================================================


class TestAsyncSupabaseAdapter:
    """Verify AsyncSupabaseAdapter uses async client with lazy init."""

    def test_uses_acreate_client_import(self) -> None:
        """supabase.py imports acreate_client from supabase."""
        source = SUPABASE_PATH.read_text()
        assert "acreate_client" in source

    def test_uses_async_client_import(self) -> None:
        """supabase.py imports AsyncClient from supabase."""
        source = SUPABASE_PATH.read_text()
        assert "AsyncClient" in source

    def test_no_sync_client_import(self) -> None:
        """supabase.py must not import sync Client or create_client."""
        tree = ast.parse(SUPABASE_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "supabase":
                imported_names = [alias.name for alias in node.names]
                assert "Client" not in imported_names, (
                    "supabase.py still imports sync Client"
                )
                assert "create_client" not in imported_names, (
                    "supabase.py still imports sync create_client"
                )

    def test_has_asyncio_lock(self) -> None:
        """AsyncSupabaseAdapter.__init__ creates an asyncio.Lock."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        adapter = AsyncSupabaseAdapter(url="https://example.supabase.co", key="test-key")
        assert hasattr(adapter, "_lock")
        assert isinstance(adapter._lock, asyncio.Lock)

    def test_client_is_none_initially(self) -> None:
        """Client is None until first use (lazy init)."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        adapter = AsyncSupabaseAdapter(url="https://example.supabase.co", key="test-key")
        assert adapter._client is None

    def test_get_client_is_async(self) -> None:
        """_get_client() must be async def."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        assert inspect.iscoroutinefunction(AsyncSupabaseAdapter._get_client)

    def test_all_crud_methods_are_async(self) -> None:
        """All CRUD + close methods must be async def."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        for method_name in ["select", "insert", "update", "delete", "close"]:
            method = getattr(AsyncSupabaseAdapter, method_name)
            assert inspect.iscoroutinefunction(method), (
                f"{method_name} must be async def"
            )

    def test_close_is_noop_when_client_not_initialized(self) -> None:
        """close() should be a no-op when _client is None."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        adapter = AsyncSupabaseAdapter(url="https://example.supabase.co", key="test-key")
        # Should not raise -- client is None, so close is a no-op
        asyncio.run(adapter.close())
        assert adapter._client is None


# ============================================================================
# Test: adapters/__init__.py Exports
# ============================================================================


class TestAdaptersInitExports:
    """Verify adapters/__init__.py exports the correct names."""

    def test_exports_database_client(self) -> None:
        """DatabaseClient is importable from db_adapter.adapters."""
        from db_adapter.adapters import DatabaseClient

        assert DatabaseClient is not None

    def test_exports_async_postgres_adapter(self) -> None:
        """AsyncPostgresAdapter is importable from db_adapter.adapters."""
        from db_adapter.adapters import AsyncPostgresAdapter

        assert AsyncPostgresAdapter is not None

    def test_exports_async_supabase_adapter(self) -> None:
        """AsyncSupabaseAdapter is importable from db_adapter.adapters (with extra)."""
        from db_adapter.adapters import AsyncSupabaseAdapter

        assert AsyncSupabaseAdapter is not None

    def test_no_postgres_adapter_export(self) -> None:
        """PostgresAdapter must not be importable from db_adapter.adapters."""
        import db_adapter.adapters as adapters_module

        assert not hasattr(adapters_module, "PostgresAdapter")

    def test_no_supabase_adapter_export(self) -> None:
        """SupabaseAdapter must not be importable from db_adapter.adapters."""
        import db_adapter.adapters as adapters_module

        assert not hasattr(adapters_module, "SupabaseAdapter")

    def test_conditional_supabase_import(self) -> None:
        """adapters/__init__.py uses try/except for AsyncSupabaseAdapter."""
        source = INIT_PATH.read_text()
        assert "try:" in source
        assert "except ImportError:" in source
        assert "AsyncSupabaseAdapter" in source


# ============================================================================
# Test: Factory Updated References
# ============================================================================


class TestFactoryUpdatedReferences:
    """Verify factory.py references AsyncPostgresAdapter, not PostgresAdapter."""

    def test_factory_imports_async_postgres_adapter(self) -> None:
        """factory.py imports AsyncPostgresAdapter."""
        factory_path = SRC_ROOT / "factory.py"
        source = factory_path.read_text()
        assert "AsyncPostgresAdapter" in source

    def test_factory_no_postgres_adapter_reference(self) -> None:
        """factory.py does not reference PostgresAdapter."""
        factory_path = SRC_ROOT / "factory.py"
        source = factory_path.read_text()
        # Ensure 'PostgresAdapter' does not appear as a standalone word
        # (AsyncPostgresAdapter contains it, so check more carefully)
        import re

        matches = re.findall(r"\bPostgresAdapter\b", source)
        # Filter out occurrences inside "AsyncPostgresAdapter"
        standalone = [m for m in matches if True]
        # Better approach: check lines
        for line in source.splitlines():
            if "PostgresAdapter" in line and "AsyncPostgresAdapter" not in line:
                pytest.fail(f"factory.py references PostgresAdapter: {line.strip()}")

    async def test_get_adapter_creates_async_adapter(self) -> None:
        """get_adapter() creates AsyncPostgresAdapter, not PostgresAdapter."""
        from db_adapter.adapters.postgres import AsyncPostgresAdapter
        from db_adapter.factory import get_adapter

        with patch.object(AsyncPostgresAdapter, "__init__", return_value=None):
            adapter = await get_adapter(database_url="postgresql://user:pass@localhost/db")
            assert isinstance(adapter, AsyncPostgresAdapter)


# ============================================================================
# Test: create_async_engine_pooled Function
# ============================================================================


class TestCreateAsyncEnginePooled:
    """Verify create_async_engine_pooled function."""

    def test_function_signature(self) -> None:
        """create_async_engine_pooled accepts database_url and **kwargs."""
        from db_adapter.adapters.postgres import create_async_engine_pooled

        sig = inspect.signature(create_async_engine_pooled)
        params = list(sig.parameters.keys())
        assert "database_url" in params
        assert "kwargs" in params

    def test_returns_async_engine(self) -> None:
        """create_async_engine_pooled returns an AsyncEngine."""
        from sqlalchemy.ext.asyncio import AsyncEngine

        from db_adapter.adapters.postgres import create_async_engine_pooled

        with patch("db_adapter.adapters.postgres.create_async_engine") as mock_create:
            mock_engine = MagicMock(spec=AsyncEngine)
            mock_create.return_value = mock_engine
            result = create_async_engine_pooled("postgresql+asyncpg://user:pass@host/db")
            assert result is mock_engine

    def test_passes_pool_settings(self) -> None:
        """create_async_engine_pooled passes pool settings to create_async_engine."""
        from db_adapter.adapters.postgres import create_async_engine_pooled

        with patch("db_adapter.adapters.postgres.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            create_async_engine_pooled("postgresql+asyncpg://user:pass@host/db")
            _, kwargs = mock_create.call_args
            assert kwargs["pool_size"] == 5
            assert kwargs["max_overflow"] == 10
            assert kwargs["pool_pre_ping"] is True
            assert kwargs["pool_recycle"] == 300

    def test_caller_kwargs_override_defaults(self) -> None:
        """Caller kwargs override default pool settings."""
        from db_adapter.adapters.postgres import create_async_engine_pooled

        with patch("db_adapter.adapters.postgres.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            create_async_engine_pooled(
                "postgresql+asyncpg://user:pass@host/db",
                pool_size=20,
            )
            _, kwargs = mock_create.call_args
            assert kwargs["pool_size"] == 20

    def test_appends_connect_timeout(self) -> None:
        """Appends connect_timeout=5 when not already in URL."""
        from db_adapter.adapters.postgres import create_async_engine_pooled

        with patch("db_adapter.adapters.postgres.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            create_async_engine_pooled("postgresql+asyncpg://user:pass@host/db")
            call_url = mock_create.call_args[0][0]
            assert "connect_timeout=5" in call_url

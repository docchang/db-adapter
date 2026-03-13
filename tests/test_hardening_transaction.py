"""Tests for Step 4: Transaction Support -- Protocol and Adapter Implementation.

Verifies that:
- DatabaseClient Protocol has a `transaction()` method
- AsyncPostgresAdapter implements transaction() using contextvars
- CRUD operations within a transaction share a connection
- Clean exit commits, exception triggers rollback
- Nested transactions raise RuntimeError
- CRUD without transaction behaves identically (backward compatible)
- AsyncSupabaseAdapter.transaction() raises NotImplementedError
"""

import ast
import contextvars
import inspect
import pathlib
from contextlib import AbstractAsyncContextManager
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter():
    """Create an AsyncPostgresAdapter with a mocked engine."""
    from db_adapter.adapters.postgres import AsyncPostgresAdapter

    with patch("db_adapter.adapters.postgres.create_async_engine_pooled") as mock_create:
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        adapter = AsyncPostgresAdapter("postgresql://user:pass@localhost/db")
    return adapter, mock_engine


def _mock_result(rows=None, col_names=None):
    """Create a mock result object that behaves like a SQLAlchemy CursorResult."""
    mock = MagicMock()
    if col_names is None:
        col_names = ["id", "name"]
    mock.keys.return_value = col_names
    if rows is not None:
        mock.fetchall.return_value = rows
        mock.fetchone.return_value = rows[0] if rows else None
    else:
        mock.fetchall.return_value = []
        mock.fetchone.return_value = None
    return mock


# ============================================================================
# Test: Protocol has transaction() method
# ============================================================================


class TestProtocolTransactionMethod:
    """Verify DatabaseClient Protocol includes transaction()."""

    def test_protocol_has_transaction_method(self) -> None:
        """DatabaseClient Protocol must define a transaction() method."""
        from db_adapter.adapters.base import DatabaseClient

        assert hasattr(DatabaseClient, "transaction"), (
            "DatabaseClient Protocol must have transaction() method"
        )

    def test_protocol_transaction_is_sync(self) -> None:
        """transaction() on Protocol must be a regular def (not async def)."""
        from db_adapter.adapters.base import DatabaseClient

        method = getattr(DatabaseClient, "transaction")
        assert not inspect.iscoroutinefunction(method), (
            "transaction() must be def, not async def"
        )

    def test_protocol_has_six_async_methods_and_one_sync(self) -> None:
        """Protocol defines 6 async methods + 1 sync method (transaction)."""
        tree = ast.parse(BASE_PATH.read_text())
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef) and node.name == "DatabaseClient":
                async_methods = [
                    child.name
                    for child in ast.iter_child_nodes(node)
                    if isinstance(child, ast.AsyncFunctionDef)
                ]
                sync_methods = [
                    child.name
                    for child in ast.iter_child_nodes(node)
                    if isinstance(child, ast.FunctionDef)
                ]
                assert set(async_methods) == {
                    "select", "insert", "update", "delete", "execute", "close"
                }
                assert "transaction" in sync_methods
                return
        pytest.fail("DatabaseClient class not found in base.py")

    def test_protocol_transaction_return_type_annotation(self) -> None:
        """transaction() return type annotation references AbstractAsyncContextManager."""
        source = BASE_PATH.read_text()
        assert "AbstractAsyncContextManager" in source


# ============================================================================
# Test: AsyncPostgresAdapter transaction() implementation
# ============================================================================


class TestPostgresTransactionInit:
    """Verify AsyncPostgresAdapter initializes _transaction_conn ContextVar."""

    def test_has_transaction_conn_contextvar(self) -> None:
        """AsyncPostgresAdapter instance has _transaction_conn ContextVar."""
        adapter, _ = _make_adapter()
        assert hasattr(adapter, "_transaction_conn")
        assert isinstance(adapter._transaction_conn, contextvars.ContextVar)

    def test_transaction_conn_default_is_none(self) -> None:
        """ContextVar default is None (no active transaction)."""
        adapter, _ = _make_adapter()
        assert adapter._transaction_conn.get(None) is None

    def test_per_instance_contextvar_names(self) -> None:
        """Two adapter instances have distinct ContextVar names (per-instance isolation)."""
        adapter1, _ = _make_adapter()
        adapter2, _ = _make_adapter()
        # ContextVar names are based on id(self), so should differ
        assert adapter1._transaction_conn is not adapter2._transaction_conn


class TestPostgresTransactionBehavior:
    """Verify AsyncPostgresAdapter.transaction() commit/rollback behavior."""

    async def test_transaction_commits_on_clean_exit(self) -> None:
        """Clean exit from transaction() block triggers commit."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_result = _mock_result(rows=[("id1", "Alice")], col_names=["id", "name"])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        # engine.begin() returns async context manager yielding conn
        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            await adapter.insert("users", {"name": "Alice"})

        # engine.begin().__aexit__ called with no exception (clean exit -> commit)
        exit_args = mock_begin_ctx.__aexit__.call_args
        assert exit_args[0] == (None, None, None), (
            "Clean exit should pass (None, None, None) to __aexit__"
        )

    async def test_transaction_rolls_back_on_exception(self) -> None:
        """Exception within transaction() block triggers rollback."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        with pytest.raises(ValueError, match="boom"):
            async with adapter.transaction():
                raise ValueError("boom")

        # engine.begin().__aexit__ called with exception info (rollback)
        exit_args = mock_begin_ctx.__aexit__.call_args
        assert exit_args[0][0] is ValueError
        assert exit_args[0][1] is not None

    async def test_nested_transaction_raises_runtime_error(self) -> None:
        """Nested transaction() calls raise RuntimeError."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        with pytest.raises(RuntimeError, match="Nested transactions are not supported"):
            async with adapter.transaction():
                async with adapter.transaction():
                    pass  # Should never reach here

    async def test_contextvar_reset_after_transaction(self) -> None:
        """ContextVar is reset to None after transaction() exits."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            assert adapter._transaction_conn.get(None) is mock_conn

        assert adapter._transaction_conn.get(None) is None

    async def test_contextvar_reset_after_exception(self) -> None:
        """ContextVar is reset to None even when transaction() exits via exception."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        with pytest.raises(ValueError):
            async with adapter.transaction():
                raise ValueError("boom")

        assert adapter._transaction_conn.get(None) is None


# ============================================================================
# Test: CRUD operations share connection within transaction
# ============================================================================


class TestPostgresTransactionCRUDSharing:
    """Verify CRUD operations within a transaction share the transaction connection."""

    async def test_select_uses_transaction_conn(self) -> None:
        """select() uses transaction connection instead of engine.connect()."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_result = _mock_result(rows=[("id1", "Alice")], col_names=["id", "name"])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            result = await adapter.select("users", "id, name")

        # Connection.execute was called on the transaction connection
        assert mock_conn.execute.called
        # engine.connect() was NOT called (only engine.begin() for the transaction)
        assert not mock_engine.connect.called

    async def test_insert_uses_transaction_conn(self) -> None:
        """insert() uses transaction connection instead of engine.begin()."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_result = _mock_result(rows=[("id1", "Alice")], col_names=["id", "name"])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            result = await adapter.insert("users", {"name": "Alice"})

        # engine.begin() called exactly once (for the transaction), not again for insert
        assert mock_engine.begin.call_count == 1
        assert mock_conn.execute.called

    async def test_update_uses_transaction_conn(self) -> None:
        """update() uses transaction connection instead of engine.begin()."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_result = _mock_result(rows=[("id1", "Alice")], col_names=["id", "name"])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            result = await adapter.update("users", {"name": "Bob"}, {"id": "id1"})

        assert mock_engine.begin.call_count == 1
        assert mock_conn.execute.called

    async def test_delete_uses_transaction_conn(self) -> None:
        """delete() uses transaction connection instead of engine.begin()."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            await adapter.delete("users", {"id": "id1"})

        assert mock_engine.begin.call_count == 1
        assert mock_conn.execute.called

    async def test_execute_uses_transaction_conn(self) -> None:
        """execute() uses transaction connection instead of engine.begin()."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            await adapter.execute("CREATE TABLE test (id INT)")

        assert mock_engine.begin.call_count == 1
        assert mock_conn.execute.called

    async def test_multiple_crud_ops_share_same_connection(self) -> None:
        """Multiple CRUD operations within a transaction all use the same connection object."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_result = _mock_result(rows=[("id1", "Alice")], col_names=["id", "name"])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        async with adapter.transaction():
            await adapter.select("users", "id, name")
            await adapter.insert("users", {"name": "Alice"})
            await adapter.delete("users", {"id": "id1"})
            await adapter.execute("SELECT 1")

        # All 4 operations used the same connection
        assert mock_conn.execute.call_count == 4
        # engine.begin() only called once (for the transaction itself)
        assert mock_engine.begin.call_count == 1


# ============================================================================
# Test: CRUD without transaction (backward compatibility)
# ============================================================================


class TestPostgresBackwardCompatibility:
    """Verify CRUD methods work identically without transaction() (backward compatible)."""

    async def test_select_without_transaction_uses_engine_connect(self) -> None:
        """select() without transaction uses engine.connect() as before."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_result = _mock_result(rows=[("id1", "Alice")], col_names=["id", "name"])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_connect_ctx = AsyncMock()
        mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = mock_connect_ctx

        result = await adapter.select("users", "id, name")

        assert mock_engine.connect.called
        assert result == [{"id": "id1", "name": "Alice"}]

    async def test_insert_without_transaction_uses_engine_begin(self) -> None:
        """insert() without transaction uses engine.begin() as before."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_result = _mock_result(rows=[("id1", "Alice")], col_names=["id", "name"])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        result = await adapter.insert("users", {"name": "Alice"})

        assert mock_engine.begin.called
        assert result == {"id": "id1", "name": "Alice"}

    async def test_delete_without_transaction_uses_engine_begin(self) -> None:
        """delete() without transaction uses engine.begin() as before."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        await adapter.delete("users", {"id": "id1"})

        assert mock_engine.begin.called

    async def test_execute_without_transaction_uses_engine_begin(self) -> None:
        """execute() without transaction uses engine.begin() as before."""
        adapter, mock_engine = _make_adapter()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.begin.return_value = mock_begin_ctx

        await adapter.execute("CREATE TABLE test (id INT)")

        assert mock_engine.begin.called


# ============================================================================
# Test: Supabase adapter transaction() raises NotImplementedError
# ============================================================================


class TestSupabaseTransactionNotSupported:
    """Verify AsyncSupabaseAdapter.transaction() raises NotImplementedError."""

    def test_supabase_transaction_raises_not_implemented(self) -> None:
        """transaction() raises NotImplementedError for Supabase adapter."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        adapter = AsyncSupabaseAdapter(url="https://example.supabase.co", key="test-key")
        with pytest.raises(NotImplementedError, match="Transactions not supported"):
            adapter.transaction()

    def test_supabase_has_transaction_method(self) -> None:
        """AsyncSupabaseAdapter has transaction() method."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        assert hasattr(AsyncSupabaseAdapter, "transaction")

    def test_supabase_transaction_is_sync(self) -> None:
        """Supabase transaction() is a regular def (not async def)."""
        from db_adapter.adapters.supabase import AsyncSupabaseAdapter

        method = getattr(AsyncSupabaseAdapter, "transaction")
        assert not inspect.iscoroutinefunction(method)


# ============================================================================
# Test: Source file imports
# ============================================================================


class TestTransactionImports:
    """Verify correct imports were added for transaction support."""

    def test_base_imports_abstract_async_context_manager(self) -> None:
        """base.py imports AbstractAsyncContextManager from contextlib."""
        source = BASE_PATH.read_text()
        assert "from contextlib import AbstractAsyncContextManager" in source

    def test_postgres_imports_contextvars(self) -> None:
        """postgres.py imports contextvars."""
        source = POSTGRES_PATH.read_text()
        assert "import contextvars" in source

    def test_postgres_imports_asynccontextmanager(self) -> None:
        """postgres.py imports asynccontextmanager from contextlib."""
        source = POSTGRES_PATH.read_text()
        assert "from contextlib import asynccontextmanager" in source

    def test_postgres_imports_async_connection(self) -> None:
        """postgres.py imports AsyncConnection from sqlalchemy.ext.asyncio."""
        source = POSTGRES_PATH.read_text()
        assert "AsyncConnection" in source

    def test_supabase_imports_abstract_async_context_manager(self) -> None:
        """supabase.py imports AbstractAsyncContextManager from contextlib."""
        source = SUPABASE_PATH.read_text()
        assert "from contextlib import AbstractAsyncContextManager" in source

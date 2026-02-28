"""Tests for Step 7: Convert Schema Introspector to Async.

Verifies that SchemaIntrospector uses async patterns:
- psycopg.AsyncConnection instead of psycopg.connect()
- __aenter__/__aexit__ instead of __enter__/__exit__
- All query methods are async def (except _normalize_data_type)
- EXCLUDED_TABLES is a configurable constructor parameter
- test_connection() async method exists
"""

import ast
import asyncio
import inspect
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
import pytest

from db_adapter.schema.introspector import SchemaIntrospector


# ----- Source file path -----

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "db_adapter"
INTROSPECTOR_FILE = SRC_ROOT / "schema" / "introspector.py"


# ============================================================
# Test: Sync patterns removed
# ============================================================


class TestSyncPatternsRemoved:
    """Verify all sync patterns have been removed from introspector.py."""

    def test_no_psycopg_connect(self) -> None:
        """psycopg.connect() should not appear in introspector.py."""
        source = INTROSPECTOR_FILE.read_text()
        # psycopg.connect( should not appear -- the async version uses AsyncConnection.connect()
        assert "psycopg.connect(" not in source

    def test_no_sync_enter(self) -> None:
        """__enter__ should not appear as a method definition."""
        source = INTROSPECTOR_FILE.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__enter__":
                pytest.fail("Found sync __enter__ method -- should use __aenter__")

    def test_no_sync_exit(self) -> None:
        """__exit__ should not appear as a method definition."""
        source = INTROSPECTOR_FILE.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__exit__":
                pytest.fail("Found sync __exit__ method -- should use __aexit__")

    def test_no_sync_connection_import(self) -> None:
        """Should not import sync Connection from psycopg."""
        source = INTROSPECTOR_FILE.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module == "psycopg":
                    for alias in node.names:
                        if alias.name == "Connection":
                            pytest.fail(
                                "Found 'from psycopg import Connection' -- should use AsyncConnection"
                            )

    def test_grep_sync_patterns_absent(self) -> None:
        """grep should find no sync patterns."""
        result = subprocess.run(
            ["grep", "-En", r"psycopg\.connect|def __enter__|def __exit__",
             str(INTROSPECTOR_FILE)],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"Sync patterns found in introspector.py:\n{result.stdout}"
        )


# ============================================================
# Test: Async patterns present
# ============================================================


class TestAsyncPatternsPresent:
    """Verify async patterns are correctly implemented."""

    def test_has_aenter(self) -> None:
        """SchemaIntrospector should have __aenter__ method."""
        assert hasattr(SchemaIntrospector, "__aenter__")

    def test_has_aexit(self) -> None:
        """SchemaIntrospector should have __aexit__ method."""
        assert hasattr(SchemaIntrospector, "__aexit__")

    def test_aenter_is_coroutine(self) -> None:
        """__aenter__ should be an async def."""
        assert asyncio.iscoroutinefunction(SchemaIntrospector.__aenter__)

    def test_aexit_is_coroutine(self) -> None:
        """__aexit__ should be an async def."""
        assert asyncio.iscoroutinefunction(SchemaIntrospector.__aexit__)

    def test_uses_async_connection(self) -> None:
        """grep should find AsyncConnection in introspector.py."""
        result = subprocess.run(
            ["grep", "AsyncConnection", str(INTROSPECTOR_FILE)],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() != "", (
            "AsyncConnection not found in introspector.py"
        )

    def test_no_sync_enter_exit(self) -> None:
        """Should not have __enter__ or __exit__ (only async versions)."""
        assert not hasattr(SchemaIntrospector, "__enter__"), (
            "__enter__ should not exist -- use __aenter__"
        )
        assert not hasattr(SchemaIntrospector, "__exit__"), (
            "__exit__ should not exist -- use __aexit__"
        )


# ============================================================
# Test: Query methods are async
# ============================================================


class TestQueryMethodsAsync:
    """Verify all query methods are async def."""

    ASYNC_METHODS = [
        "test_connection",
        "introspect",
        "get_column_names",
        "_get_tables",
        "_get_columns",
        "_get_constraints",
        "_get_indexes",
        "_get_triggers",
        "_get_functions",
    ]

    @pytest.mark.parametrize("method_name", ASYNC_METHODS)
    def test_method_is_coroutine(self, method_name: str) -> None:
        """Each query method should be an async def (coroutine function)."""
        method = getattr(SchemaIntrospector, method_name, None)
        assert method is not None, f"{method_name} not found on SchemaIntrospector"
        assert asyncio.iscoroutinefunction(method), (
            f"{method_name} should be async def, got regular def"
        )


class TestNormalizeDataTypeSync:
    """Verify _normalize_data_type remains a regular sync method."""

    def test_not_coroutine(self) -> None:
        """_normalize_data_type should NOT be async (pure logic)."""
        assert not asyncio.iscoroutinefunction(SchemaIntrospector._normalize_data_type)

    def test_basic_normalization(self) -> None:
        """Verify _normalize_data_type maps verbose types correctly."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        assert introspector._normalize_data_type("character varying") == "varchar"
        assert introspector._normalize_data_type("character") == "char"
        assert introspector._normalize_data_type("timestamp with time zone") == "timestamptz"
        assert introspector._normalize_data_type("timestamp without time zone") == "timestamp"
        assert introspector._normalize_data_type("integer") == "int"
        assert introspector._normalize_data_type("boolean") == "bool"
        assert introspector._normalize_data_type("text") == "text"
        assert introspector._normalize_data_type("jsonb") == "jsonb"

    def test_case_insensitive(self) -> None:
        """Normalization should be case-insensitive."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        assert introspector._normalize_data_type("CHARACTER VARYING") == "varchar"
        assert introspector._normalize_data_type("Integer") == "int"


# ============================================================
# Test: Constructor parameters
# ============================================================


class TestConstructorParameters:
    """Verify constructor accepts configurable parameters."""

    def test_excluded_tables_default(self) -> None:
        """EXCLUDED_TABLES defaults to EXCLUDED_TABLES_DEFAULT when None."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        assert introspector._excluded_tables == {
            "schema_migrations",
            "pg_stat_statements",
            "spatial_ref_sys",
        }

    def test_excluded_tables_custom(self) -> None:
        """Caller can provide custom excluded_tables."""
        custom = {"migrations", "audit_log"}
        introspector = SchemaIntrospector(
            "postgresql://localhost/test",
            excluded_tables=custom,
        )
        assert introspector._excluded_tables == custom

    def test_excluded_tables_empty(self) -> None:
        """Caller can pass empty set to exclude no tables."""
        introspector = SchemaIntrospector(
            "postgresql://localhost/test",
            excluded_tables=set(),
        )
        assert introspector._excluded_tables == set()

    def test_connect_timeout_default(self) -> None:
        """Connect timeout defaults to 10."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        assert introspector._connect_timeout == 10

    def test_connect_timeout_custom(self) -> None:
        """Caller can set a custom connect_timeout."""
        introspector = SchemaIntrospector(
            "postgresql://localhost/test",
            connect_timeout=30,
        )
        assert introspector._connect_timeout == 30

    def test_excluded_tables_not_class_constant(self) -> None:
        """EXCLUDED_TABLES should NOT be used as instance attribute directly.
        The instance should use _excluded_tables (from constructor param)."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        # Instance uses _excluded_tables, not EXCLUDED_TABLES
        assert hasattr(introspector, "_excluded_tables")

    def test_excluded_tables_default_is_class_attr(self) -> None:
        """EXCLUDED_TABLES_DEFAULT should exist as a class attribute for reference."""
        assert hasattr(SchemaIntrospector, "EXCLUDED_TABLES_DEFAULT")
        assert isinstance(SchemaIntrospector.EXCLUDED_TABLES_DEFAULT, set)

    def test_constructor_signature(self) -> None:
        """Constructor should accept database_url, excluded_tables, connect_timeout."""
        sig = inspect.signature(SchemaIntrospector.__init__)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "database_url" in params
        assert "excluded_tables" in params
        assert "connect_timeout" in params


# ============================================================
# Test: Connection not established errors
# ============================================================


class TestConnectionNotEstablished:
    """Verify methods raise RuntimeError when not connected."""

    def test_introspect_requires_connection(self) -> None:
        """introspect() should raise RuntimeError if not connected."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        with pytest.raises(RuntimeError, match="not connected"):
            asyncio.run(introspector.introspect())

    def test_get_column_names_requires_connection(self) -> None:
        """get_column_names() should raise RuntimeError if not connected."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        with pytest.raises(RuntimeError, match="not connected"):
            asyncio.run(introspector.get_column_names())

    def test_test_connection_requires_connection(self) -> None:
        """test_connection() should raise RuntimeError if not connected."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        with pytest.raises(RuntimeError, match="not connected"):
            asyncio.run(introspector.test_connection())


# ============================================================
# Test: test_connection method
# ============================================================


class TestTestConnection:
    """Verify test_connection() async method behavior."""

    def test_is_async(self) -> None:
        """test_connection should be an async method."""
        assert asyncio.iscoroutinefunction(SchemaIntrospector.test_connection)

    def test_success_with_mock(self) -> None:
        """test_connection returns True when SELECT 1 succeeds."""
        introspector = SchemaIntrospector("postgresql://localhost/test")

        # Mock the async cursor
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = (1,)

        # Mock the async connection -- cursor() returns an async context manager
        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_ctx

        introspector._conn = mock_conn

        result = asyncio.run(introspector.test_connection())
        assert result is True
        mock_cursor.execute.assert_awaited_once_with("SELECT 1")

    def test_raises_connection_error_on_failure(self) -> None:
        """test_connection raises ConnectionError on psycopg error."""
        introspector = SchemaIntrospector("postgresql://localhost/test")

        # Mock the async cursor that raises on execute
        mock_cursor = AsyncMock()
        mock_cursor.execute.side_effect = psycopg.Error("connection lost")

        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_ctx

        introspector._conn = mock_conn

        with pytest.raises(ConnectionError, match="Connection test failed"):
            asyncio.run(introspector.test_connection())


# ============================================================
# Test: Async context manager behavior
# ============================================================


class TestAsyncContextManager:
    """Verify __aenter__ and __aexit__ behavior with mocks."""

    def test_aenter_opens_connection(self) -> None:
        """__aenter__ should call AsyncConnection.connect()."""
        introspector = SchemaIntrospector(
            "postgresql://localhost/test",
            connect_timeout=15,
        )

        mock_conn = AsyncMock()

        with patch(
            "db_adapter.schema.introspector.psycopg.AsyncConnection.connect",
            new_callable=AsyncMock,
            return_value=mock_conn,
        ) as mock_connect:
            asyncio.run(introspector.__aenter__())

            mock_connect.assert_awaited_once_with(
                "postgresql://localhost/test",
                connect_timeout=15,
            )
            assert introspector._conn is mock_conn

    def test_aexit_closes_connection(self) -> None:
        """__aexit__ should close the connection and set it to None."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        mock_conn = AsyncMock()
        introspector._conn = mock_conn

        asyncio.run(introspector.__aexit__(None, None, None))

        mock_conn.close.assert_awaited_once()
        assert introspector._conn is None

    def test_aexit_noop_when_no_connection(self) -> None:
        """__aexit__ should be a no-op when connection is None."""
        introspector = SchemaIntrospector("postgresql://localhost/test")
        introspector._conn = None

        # Should not raise
        asyncio.run(introspector.__aexit__(None, None, None))
        assert introspector._conn is None


# ============================================================
# Test: AST verification of source structure
# ============================================================


class TestSourceStructure:
    """Verify source file structure via AST inspection."""

    def _get_class_methods(self) -> dict[str, ast.AST]:
        """Parse introspector.py and return SchemaIntrospector method nodes."""
        source = INTROSPECTOR_FILE.read_text()
        tree = ast.parse(source)
        methods = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SchemaIntrospector":
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods[item.name] = item
        return methods

    def test_all_query_methods_are_async_func_def(self) -> None:
        """All query methods should use AsyncFunctionDef in AST."""
        methods = self._get_class_methods()
        async_required = [
            "__aenter__", "__aexit__", "test_connection",
            "introspect", "get_column_names",
            "_get_tables", "_get_columns", "_get_constraints",
            "_get_indexes", "_get_triggers", "_get_functions",
        ]
        for name in async_required:
            assert name in methods, f"{name} not found in SchemaIntrospector"
            assert isinstance(methods[name], ast.AsyncFunctionDef), (
                f"{name} should be AsyncFunctionDef, got {type(methods[name]).__name__}"
            )

    def test_normalize_data_type_is_sync_func_def(self) -> None:
        """_normalize_data_type should be FunctionDef (not AsyncFunctionDef)."""
        methods = self._get_class_methods()
        assert "_normalize_data_type" in methods
        assert isinstance(methods["_normalize_data_type"], ast.FunctionDef), (
            "_normalize_data_type should be FunctionDef (sync), got AsyncFunctionDef"
        )

    def test_no_old_excluded_tables_constant_usage(self) -> None:
        """Method bodies should reference self._excluded_tables, not self.EXCLUDED_TABLES."""
        source = INTROSPECTOR_FILE.read_text()
        tree = ast.parse(source)
        # Check method bodies (not __init__) for self.EXCLUDED_TABLES references
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SchemaIntrospector":
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name == "__init__":
                            continue  # __init__ legitimately references EXCLUDED_TABLES_DEFAULT
                        # Check for Attribute nodes like self.EXCLUDED_TABLES
                        for child in ast.walk(item):
                            if (
                                isinstance(child, ast.Attribute)
                                and child.attr == "EXCLUDED_TABLES"
                                and isinstance(child.value, ast.Name)
                                and child.value.id == "self"
                            ):
                                pytest.fail(
                                    f"Method {item.name} uses self.EXCLUDED_TABLES "
                                    f"-- should use self._excluded_tables"
                                )

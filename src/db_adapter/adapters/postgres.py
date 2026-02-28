"""Async PostgreSQL database adapter.

Provides ``AsyncPostgresAdapter``, an async implementation of the
``DatabaseClient`` protocol using SQLAlchemy's async engine with the
``asyncpg`` driver.

Usage:
    from db_adapter.adapters.postgres import AsyncPostgresAdapter

    adapter = AsyncPostgresAdapter(
        "postgresql://user:pass@localhost:5432/mydb",
        jsonb_columns=["metadata", "tags"],
    )

    rows = await adapter.select("users", "id, name")
    await adapter.close()
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_async_engine_pooled(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Create an async SQLAlchemy engine with connection pooling.

    Default pool settings:

    - ``pool_size=5``: Reasonable default for typical workloads.
    - ``max_overflow=10``: Allow burst connections.
    - ``pool_pre_ping=True``: Validate connections before checkout.
    - ``pool_recycle=300``: Recycle connections every 5 minutes.

    Args:
        database_url: PostgreSQL connection URL with ``postgresql+asyncpg://``
            scheme.
        **kwargs: Additional keyword arguments forwarded to
            ``create_async_engine``.

    Returns:
        Configured ``AsyncEngine``.

    Example:
        engine = create_async_engine_pooled(
            "postgresql+asyncpg://user:pass@localhost/mydb"
        )
    """
    # Append connect_timeout if not already in URL
    if "connect_timeout" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}connect_timeout=5"

    defaults: dict[str, Any] = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "echo": False,
    }
    # Caller kwargs override defaults
    merged = {**defaults, **kwargs}

    return create_async_engine(database_url, **merged)


class AsyncPostgresAdapter:
    """Async PostgreSQL implementation of the ``DatabaseClient`` protocol.

    Uses SQLAlchemy's async engine with the ``asyncpg`` driver for
    connection pooling, automatic stale connection detection
    (``pool_pre_ping``), and proactive connection recycling.

    JSONB columns are configured via the constructor -- there is no
    class-level constant.

    Args:
        database_url: PostgreSQL connection URL.  Accepts ``postgres://``,
            ``postgresql://``, or ``postgresql+asyncpg://`` schemes.  The
            URL is normalized to ``postgresql+asyncpg://`` automatically.
        jsonb_columns: Optional list of column names that should receive
            JSONB serialization (``CAST(:param AS jsonb)``).
        **engine_kwargs: Additional keyword arguments forwarded to
            ``create_async_engine_pooled``.

    Example:
        adapter = AsyncPostgresAdapter(
            "postgresql://user:pass@localhost:5432/mydb",
            jsonb_columns=["metadata"],
        )
        rows = await adapter.select("items", "id, name")
        await adapter.close()
    """

    def __init__(
        self,
        database_url: str,
        jsonb_columns: list[str] | None = None,
        **engine_kwargs: Any,
    ) -> None:
        # Normalize URL scheme:
        # 1. postgres:// -> postgresql:// (Heroku, Railway, Supabase alias)
        # 2. postgresql:// -> postgresql+asyncpg://
        url = database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]

        self._jsonb_columns: frozenset[str] = frozenset(jsonb_columns or [])
        self._engine: AsyncEngine = create_async_engine_pooled(url, **engine_kwargs)

    # ------------------------------------------------------------------
    # CRUD Methods
    # ------------------------------------------------------------------

    async def select(
        self,
        table: str,
        columns: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> list[dict]:
        """Select rows from table using raw SQL."""
        # Build WHERE clause with named parameters
        params: dict[str, Any] = {}
        if filters:
            conditions: list[str] = []
            for i, (k, v) in enumerate(filters.items()):
                param_name = f"p_{i}"
                conditions.append(f"{k} = :{param_name}")
                params[param_name] = v
            where_clause = " WHERE " + " AND ".join(conditions)
        else:
            where_clause = ""

        # Build ORDER BY clause if provided
        order_clause = f" ORDER BY {order_by}" if order_by else ""

        query = text(f"SELECT {columns} FROM {table}{where_clause}{order_clause}")

        async with self._engine.connect() as conn:
            result = await conn.execute(query, params)
            col_names = list(result.keys())
            rows = result.fetchall()
            return [self._serialize_row(dict(zip(col_names, row))) for row in rows]

    async def insert(self, table: str, data: dict) -> dict:
        """Insert row and return created row with all fields.

        Filters out metadata fields (starting with ``_``) before insertion.
        Handles JSONB fields by serializing to JSON strings with ``CAST()``.
        Uses ``engine.begin()`` for automatic commit on success, rollback on
        error.
        """
        # Remove metadata fields (e.g., _project_slug for multi-DB FK resolution)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        columns = list(clean_data.keys())

        # Build parameter placeholders with CAST for JSONB columns
        placeholders: list[str] = []
        for col in columns:
            if col in self._jsonb_columns:
                placeholders.append(f"CAST(:{col} AS jsonb)")
            else:
                placeholders.append(f":{col}")

        query = text(f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({", ".join(placeholders)})
            RETURNING *
        """)

        # Prepare values
        params: dict[str, Any] = {}
        for col, val in clean_data.items():
            if isinstance(val, dict):
                params[col] = json.dumps(val)
            elif isinstance(val, list) and col in self._jsonb_columns:
                params[col] = json.dumps(val)
            else:
                params[col] = val

        async with self._engine.begin() as conn:
            result = await conn.execute(query, params)
            row = result.fetchone()
            col_names = list(result.keys())
            return self._serialize_row(dict(zip(col_names, row)))

    async def update(self, table: str, data: dict, filters: dict[str, Any]) -> dict:
        """Update rows and return first updated row.

        Handles JSONB fields by serializing to JSON strings with ``CAST()``.
        Uses ``engine.begin()`` for automatic commit on success, rollback on
        error.
        """
        # Build SET clause with named parameters
        set_parts: list[str] = []
        params: dict[str, Any] = {}

        for i, (k, v) in enumerate(data.items()):
            param_name = f"set_{i}"
            if k in self._jsonb_columns:
                set_parts.append(f"{k} = CAST(:{param_name} AS jsonb)")
            else:
                set_parts.append(f"{k} = :{param_name}")

            if isinstance(v, dict):
                params[param_name] = json.dumps(v)
            elif isinstance(v, list) and k in self._jsonb_columns:
                params[param_name] = json.dumps(v)
            else:
                params[param_name] = v

        set_clause = ", ".join(set_parts)

        # Build WHERE clause with named parameters
        where_parts: list[str] = []
        for i, (k, v) in enumerate(filters.items()):
            param_name = f"where_{i}"
            where_parts.append(f"{k} = :{param_name}")
            params[param_name] = v

        where_clause = " AND ".join(where_parts)

        query = text(f"""
            UPDATE {table}
            SET {set_clause}
            WHERE {where_clause}
            RETURNING *
        """)

        async with self._engine.begin() as conn:
            result = await conn.execute(query, params)
            row = result.fetchone()
            if row is None:
                raise ValueError(f"No rows matched filters: {filters}")
            col_names = list(result.keys())
            return self._serialize_row(dict(zip(col_names, row)))

    async def delete(self, table: str, filters: dict[str, Any]) -> None:
        """Delete rows from table.

        Uses ``engine.begin()`` for automatic commit on success, rollback on
        error.
        """
        params: dict[str, Any] = {}
        where_parts: list[str] = []

        for i, (k, v) in enumerate(filters.items()):
            param_name = f"p_{i}"
            where_parts.append(f"{k} = :{param_name}")
            params[param_name] = v

        where_clause = " AND ".join(where_parts)
        query = text(f"DELETE FROM {table} WHERE {where_clause}")

        async with self._engine.begin() as conn:
            await conn.execute(query, params)

    async def execute(self, sql: str, params: dict | None = None) -> None:
        """Execute a raw SQL statement (DDL or other non-query operations).

        Uses ``engine.begin()`` for automatic commit on success, rollback
        on error.  Suitable for DDL statements like CREATE TABLE, ALTER
        TABLE, DROP TABLE, etc.

        Args:
            sql: Raw SQL statement to execute.
            params: Optional dict of named parameters for the SQL statement.

        Example:
            await adapter.execute(
                "ALTER TABLE users ADD COLUMN email VARCHAR(255)"
            )
            await adapter.execute(
                "CREATE TABLE items (id SERIAL PRIMARY KEY, name TEXT)"
            )
        """
        async with self._engine.begin() as conn:
            await conn.execute(text(sql), params or {})

    async def close(self) -> None:
        """Close the async engine and dispose of the connection pool."""
        if self._engine:
            await self._engine.dispose()

    # ------------------------------------------------------------------
    # Connection Test
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """Test database connection health.

        Runs ``SELECT 1`` via the async engine to verify the connection
        is alive.

        Returns:
            ``True`` if the database connection succeeds.

        Raises:
            Exception: If the database connection fails.
        """
        async with self._engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1

    # ------------------------------------------------------------------
    # Serialization Helpers
    # ------------------------------------------------------------------

    def _serialize_value(self, value: Any) -> Any:
        """Serialize PostgreSQL result values to JSON-compatible types.

        Converts UUID to string and datetime to ISO format for compatibility
        with Pydantic models that expect string types.
        """
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _serialize_row(self, row: dict) -> dict:
        """Serialize all values in a row dict."""
        return {k: self._serialize_value(v) for k, v in row.items()}

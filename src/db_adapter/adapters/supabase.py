"""Async Supabase database adapter.

Provides ``AsyncSupabaseAdapter``, an async implementation of the
``DatabaseClient`` protocol using the supabase-py async client.

The client is initialized lazily on first use with an ``asyncio.Lock``
to ensure thread-safe initialization.

Usage:
    from db_adapter.adapters.supabase import AsyncSupabaseAdapter

    adapter = AsyncSupabaseAdapter(
        url="https://xyzproject.supabase.co",
        key="eyJ...",
    )

    rows = await adapter.select("users", "id, name")
    await adapter.close()
"""

import asyncio
from typing import Any

from supabase import AsyncClient, acreate_client


class AsyncSupabaseAdapter:
    """Async Supabase implementation of the ``DatabaseClient`` protocol.

    Wraps the Supabase Python async client to match the ``DatabaseClient``
    interface.  The client is initialized lazily on first CRUD call
    using ``acreate_client`` protected by an ``asyncio.Lock``.

    Args:
        url: Supabase project URL.
        key: Supabase API key (anon or service key).

    Example:
        adapter = AsyncSupabaseAdapter(
            url="https://xyzproject.supabase.co",
            key="eyJhbGciOiJIUzI1NiIs...",
        )
        rows = await adapter.select("users", "id, name")
        await adapter.close()
    """

    def __init__(self, url: str, key: str) -> None:
        self._url: str = url
        self._key: str = key
        self._client: AsyncClient | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def _get_client(self) -> AsyncClient:
        """Get or create the async Supabase client.

        Uses an ``asyncio.Lock`` to ensure the client is created exactly
        once, even under concurrent access.

        Returns:
            Initialized ``AsyncClient``.
        """
        if self._client is None:
            async with self._lock:
                # Double-check after acquiring lock
                if self._client is None:
                    self._client = await acreate_client(self._url, self._key)
        return self._client

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
        """Select rows from table using Supabase query builder."""
        client = await self._get_client()
        query = client.table(table).select(columns)

        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)

        if order_by:
            query = query.order(order_by)

        result = await query.execute()
        return result.data

    async def insert(self, table: str, data: dict) -> dict:
        """Insert row and return created row.

        Filters out metadata fields (starting with ``_``) before insertion.
        """
        client = await self._get_client()
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        result = await client.table(table).insert(clean_data).execute()
        return result.data[0]

    async def update(self, table: str, data: dict, filters: dict[str, Any]) -> dict:
        """Update rows and return first updated row."""
        client = await self._get_client()
        query = client.table(table).update(data)

        for key, value in filters.items():
            query = query.eq(key, value)

        result = await query.execute()
        return result.data[0]

    async def delete(self, table: str, filters: dict[str, Any]) -> None:
        """Delete rows matching filters."""
        client = await self._get_client()
        query = client.table(table).delete()

        for key, value in filters.items():
            query = query.eq(key, value)

        await query.execute()

    async def execute(self, sql: str, params: dict | None = None) -> None:
        """Execute a raw SQL statement.

        Not supported by the Supabase client -- DDL operations require
        direct PostgreSQL access.

        Raises:
            NotImplementedError: Always.  Use ``AsyncPostgresAdapter`` for
                DDL operations.
        """
        raise NotImplementedError(
            "DDL operations not supported for this adapter type"
        )

    async def close(self) -> None:
        """Close the Supabase async client.

        If the client was never initialized (no CRUD calls were made),
        this is a no-op.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

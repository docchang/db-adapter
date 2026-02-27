"""Supabase database adapter."""

from typing import Any

from supabase import Client, create_client


class SupabaseAdapter:
    """Supabase implementation of DatabaseClient protocol.

    Wraps the Supabase Python client to match the DatabaseClient interface.
    """

    def __init__(self, url: str, key: str):
        """Initialize Supabase adapter.

        Args:
            url: Supabase project URL
            key: Supabase API key (anon or service key)
        """
        self._client: Client = create_client(url, key)

    def select(
        self,
        table: str,
        columns: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> list[dict]:
        """Select rows from table using Supabase query builder."""
        query = self._client.table(table).select(columns)

        # Apply filters if provided
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)

        # Apply ordering if provided
        if order_by:
            query = query.order(order_by)

        result = query.execute()
        return result.data

    def insert(self, table: str, data: dict) -> dict:
        """Insert row and return created row.

        Filters out metadata fields (starting with _) before insertion.
        """
        # Remove metadata fields (e.g., _project_slug for multi-DB FK resolution)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        result = self._client.table(table).insert(clean_data).execute()
        return result.data[0]

    def update(self, table: str, data: dict, filters: dict[str, Any]) -> dict:
        """Update rows and return first updated row."""
        query = self._client.table(table).update(data)

        # Apply filters
        for key, value in filters.items():
            query = query.eq(key, value)

        result = query.execute()
        return result.data[0]

    def delete(self, table: str, filters: dict[str, Any]) -> None:
        """Delete rows matching filters."""
        query = self._client.table(table).delete()

        # Apply filters
        for key, value in filters.items():
            query = query.eq(key, value)

        query.execute()

    def close(self) -> None:
        """Close Supabase connection.

        Note: Supabase client manages connections internally.
        This is a no-op for compatibility with the protocol.
        """
        # Supabase client handles cleanup automatically
        pass

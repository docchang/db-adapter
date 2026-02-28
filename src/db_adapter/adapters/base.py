"""Database client protocol definition.

Defines the ``DatabaseClient`` Protocol that all adapters must implement.
All methods are ``async def`` -- the library is async-first.

Usage:
    from db_adapter.adapters.base import DatabaseClient

    async def do_work(client: DatabaseClient) -> None:
        rows = await client.select("users", "id, name")
        await client.insert("users", {"name": "Alice"})
        await client.execute("CREATE INDEX idx_name ON users (name)")
        await client.close()
"""

from typing import Any, Protocol


class DatabaseClient(Protocol):
    """Database client interface that all adapters must implement.

    This Protocol ensures type safety and consistent behavior across
    different database backends (PostgreSQL, Supabase, etc.).

    All methods are async -- callers must ``await`` every operation.
    """

    async def select(
        self,
        table: str,
        columns: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> list[dict]:
        """Select rows from table.

        Args:
            table: Table name.
            columns: Comma-separated column names (e.g., ``"id, name, status"``).
            filters: Optional dict of field=value filters (all must match via AND).
            order_by: Optional column name to sort by.

        Returns:
            List of dicts, one per row.  Empty list if no matches.

        Example:
            rows = await client.select(
                "users",
                "id, name, status",
                filters={"status": "active"},
                order_by="name",
            )
        """
        ...

    async def insert(self, table: str, data: dict) -> dict:
        """Insert row into table and return the created row.

        Args:
            table: Table name.
            data: Dict of field=value pairs to insert.

        Returns:
            Dict representing the created row (includes id, timestamps, etc.).

        Raises:
            Exception: If duplicate key or constraint violation.

        Example:
            row = await client.insert("users", {
                "name": "Alice",
                "email": "alice@example.com",
            })
        """
        ...

    async def update(self, table: str, data: dict, filters: dict[str, Any]) -> dict:
        """Update rows in table and return the first updated row.

        Args:
            table: Table name.
            data: Dict of field=value pairs to update.
            filters: Dict of field=value filters (all must match via AND).

        Returns:
            Dict representing the updated row.

        Raises:
            Exception: If no rows match filters.

        Example:
            row = await client.update(
                "users",
                {"status": "inactive"},
                {"id": "abc-123"},
            )
        """
        ...

    async def delete(self, table: str, filters: dict[str, Any]) -> None:
        """Delete rows from table.

        Args:
            table: Table name.
            filters: Dict of field=value filters (all must match via AND).

        Example:
            await client.delete("users", {"id": "abc-123"})
        """
        ...

    async def execute(self, sql: str, params: dict | None = None) -> None:
        """Execute a raw SQL statement (DDL or other non-query operations).

        Used for schema management operations like CREATE TABLE, ALTER TABLE,
        DROP TABLE, etc.  Not all adapters support DDL -- those that don't
        should raise ``NotImplementedError``.

        Args:
            sql: Raw SQL statement to execute.
            params: Optional dict of named parameters for the SQL statement.

        Raises:
            NotImplementedError: If the adapter does not support DDL.

        Example:
            await client.execute(
                "ALTER TABLE users ADD COLUMN email VARCHAR(255)"
            )
        """
        ...

    async def close(self) -> None:
        """Close database connection and clean up resources.

        Call this when done with the adapter, especially in long-running
        processes.
        """
        ...

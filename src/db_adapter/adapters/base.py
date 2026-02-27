"""Database client protocol definition."""

from typing import Any, Protocol


class DatabaseClient(Protocol):
    """Database client interface that all adapters must implement.

    This Protocol ensures type safety and consistent behavior across
    different database backends (Supabase, PostgreSQL, etc.).
    """

    def select(
        self,
        table: str,
        columns: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> list[dict]:
        """Select rows from table.

        Args:
            table: Table name
            columns: Comma-separated column names (e.g., "id, name, status")
            filters: Optional dict of field=value filters (all must match via AND)
            order_by: Optional column name to sort by

        Returns:
            List of dicts, one per row. Empty list if no matches.

        Example:
            rows = client.select(
                "projects",
                "slug, name, status",
                filters={"user_id": "123", "status": "active"},
                order_by="priority"
            )
        """
        ...

    def insert(self, table: str, data: dict) -> dict:
        """Insert row into table and return the created row.

        Args:
            table: Table name
            data: Dict of field=value pairs to insert

        Returns:
            Dict representing the created row (includes id, timestamps, etc.)

        Raises:
            Exception: If duplicate key or constraint violation

        Example:
            row = client.insert("projects", {
                "user_id": "123",
                "slug": "my-project",
                "name": "My Project"
            })
        """
        ...

    def update(self, table: str, data: dict, filters: dict[str, Any]) -> dict:
        """Update rows in table and return the first updated row.

        Args:
            table: Table name
            data: Dict of field=value pairs to update
            filters: Dict of field=value filters (all must match via AND)

        Returns:
            Dict representing the updated row

        Raises:
            Exception: If no rows match filters

        Example:
            row = client.update(
                "projects",
                {"status": "complete", "completion": 100},
                {"user_id": "123", "slug": "my-project"}
            )
        """
        ...

    def delete(self, table: str, filters: dict[str, Any]) -> None:
        """Delete rows from table.

        Args:
            table: Table name
            filters: Dict of field=value filters (all must match via AND)

        Example:
            client.delete("projects", {"user_id": "123", "slug": "old-project"})
        """
        ...

    def close(self) -> None:
        """Close database connection and clean up resources.

        Call this when done with the adapter, especially in long-running processes.
        """
        ...

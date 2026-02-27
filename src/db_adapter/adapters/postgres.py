"""PostgreSQL database adapter."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def create_mc_engine(database_url: str) -> Engine:
    """Create SQLAlchemy engine with connection pooling.

    Configuration matches Video Professor's proven approach:
    - pool_size=5: Reasonable default for MCP workload
    - max_overflow=10: Allow burst connections
    - pool_pre_ping=True: Validate connections before checkout (key fix)
    - pool_recycle=300: Recycle connections every 5 minutes

    Args:
        database_url: PostgreSQL connection URL

    Returns:
        Configured SQLAlchemy Engine
    """
    # Append connect_timeout if not already in URL
    if "connect_timeout" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}connect_timeout=5"

    return create_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False,
    )


class PostgresAdapter:
    """PostgreSQL implementation of DatabaseClient protocol.

    Uses SQLAlchemy for connection pooling with automatic stale connection
    detection (pool_pre_ping) and proactive connection recycling.
    """

    # JSONB columns that need JSON string serialization
    # Other columns (like TEXT[] arrays) pass lists directly
    JSONB_COLUMNS = frozenset([
        "risks",  # milestones.risks - JSONB (dict or list of dicts)
    ])

    def __init__(self, database_url: str):
        """Initialize PostgreSQL adapter with SQLAlchemy engine.

        Args:
            database_url: PostgreSQL connection URL in the format:
                postgresql://user:password@host:port/database

        Example:
            adapter = PostgresAdapter("postgresql://mc_admin:pass@localhost:5432/mission_control")
        """
        self._engine: Engine = create_mc_engine(database_url)

    def select(
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
            conditions = []
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

        with self._engine.connect() as conn:
            result = conn.execute(query, params)
            # Get column names from result
            col_names = list(result.keys())
            rows = result.fetchall()
            return [self._serialize_row(dict(zip(col_names, row))) for row in rows]

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

    def insert(self, table: str, data: dict) -> dict:
        """Insert row and return created row with all fields.

        Filters out metadata fields (starting with _) before insertion.
        Handles JSONB fields by serializing to JSON strings with CAST().
        Handles TEXT[] arrays by passing Python lists directly.
        Uses engine.begin() for automatic commit on success, rollback on error.
        """
        # Remove metadata fields (e.g., _project_slug for multi-DB FK resolution)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        columns = list(clean_data.keys())

        # Build parameter placeholders with CAST for JSONB columns
        placeholders = []
        for col in columns:
            if col in self.JSONB_COLUMNS:
                # JSONB columns need explicit cast from JSON string
                placeholders.append(f"CAST(:{col} AS jsonb)")
            else:
                placeholders.append(f":{col}")

        query = text(f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({", ".join(placeholders)})
            RETURNING *
        """)

        # Prepare values
        params = {}
        for col, val in clean_data.items():
            if isinstance(val, dict):
                # Dicts always serialized to JSON string (likely JSONB column)
                params[col] = json.dumps(val)
            elif isinstance(val, list) and col in self.JSONB_COLUMNS:
                # JSONB list columns -> JSON string
                params[col] = json.dumps(val)
            else:
                # TEXT[] arrays and other values pass through directly
                params[col] = val

        with self._engine.begin() as conn:
            result = conn.execute(query, params)
            row = result.fetchone()
            col_names = list(result.keys())
            return self._serialize_row(dict(zip(col_names, row)))

    def update(self, table: str, data: dict, filters: dict[str, Any]) -> dict:
        """Update rows and return first updated row.

        Handles JSONB fields by serializing to JSON strings with CAST().
        Handles TEXT[] arrays by passing Python lists directly.
        Uses engine.begin() for automatic commit on success, rollback on error.
        """
        # Build SET clause with named parameters
        set_parts = []
        params: dict[str, Any] = {}

        for i, (k, v) in enumerate(data.items()):
            param_name = f"set_{i}"
            # Use CAST for JSONB columns
            if k in self.JSONB_COLUMNS:
                set_parts.append(f"{k} = CAST(:{param_name} AS jsonb)")
            else:
                set_parts.append(f"{k} = :{param_name}")

            # Serialize dicts and JSONB lists
            if isinstance(v, dict):
                params[param_name] = json.dumps(v)
            elif isinstance(v, list) and k in self.JSONB_COLUMNS:
                # JSONB list columns -> JSON string
                params[param_name] = json.dumps(v)
            else:
                # TEXT[] arrays and other values pass through directly
                params[param_name] = v

        set_clause = ", ".join(set_parts)

        # Build WHERE clause with named parameters
        where_parts = []
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

        with self._engine.begin() as conn:
            result = conn.execute(query, params)
            row = result.fetchone()
            if row is None:
                raise ValueError(f"No rows matched filters: {filters}")
            col_names = list(result.keys())
            return self._serialize_row(dict(zip(col_names, row)))

    def delete(self, table: str, filters: dict[str, Any]) -> None:
        """Delete rows from table.

        Uses engine.begin() for automatic commit on success, rollback on error.
        """
        # Build WHERE clause with named parameters
        params: dict[str, Any] = {}
        where_parts = []

        for i, (k, v) in enumerate(filters.items()):
            param_name = f"p_{i}"
            where_parts.append(f"{k} = :{param_name}")
            params[param_name] = v

        where_clause = " AND ".join(where_parts)
        query = text(f"DELETE FROM {table} WHERE {where_clause}")

        with self._engine.begin() as conn:
            conn.execute(query, params)

    def close(self) -> None:
        """Close PostgreSQL connection pool."""
        if self._engine:
            self._engine.dispose()

    def test_connection(self) -> bool:
        """Test database connection health.

        Uses pool_pre_ping implicitly through normal connection checkout.

        Returns:
            True if database connection succeeds.

        Raises:
            Exception: If database connection fails.
        """
        with self._engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            return result.scalar() == 1

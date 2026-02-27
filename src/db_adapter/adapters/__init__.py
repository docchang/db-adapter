"""Database adapters for Mission Control.

This package provides a Protocol-based abstraction over PostgreSQL.
"""

from adapters.base import DatabaseClient
from adapters.postgres_adapter import PostgresAdapter

__all__ = [
    "DatabaseClient",
    "PostgresAdapter",
]

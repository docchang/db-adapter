"""Database adapters package.

Provides the ``DatabaseClient`` Protocol and concrete async adapter
implementations for PostgreSQL and (optionally) Supabase.

``AsyncSupabaseAdapter`` is only available when the ``supabase`` extra
is installed.  A missing ``supabase`` dependency does not prevent
importing the rest of the package.

Usage:
    from db_adapter.adapters import DatabaseClient, AsyncPostgresAdapter

    # With supabase extra installed:
    from db_adapter.adapters import AsyncSupabaseAdapter
"""

from db_adapter.adapters.base import DatabaseClient
from db_adapter.adapters.postgres import AsyncPostgresAdapter

__all__ = [
    "DatabaseClient",
    "AsyncPostgresAdapter",
]

try:
    from db_adapter.adapters.supabase import AsyncSupabaseAdapter

    __all__.append("AsyncSupabaseAdapter")
except ImportError:
    # supabase extra not installed -- AsyncSupabaseAdapter unavailable
    pass

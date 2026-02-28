"""db-adapter: Async dict-based database adapter with Protocol typing.

Provides a clean async CRUD interface over PostgreSQL (and optionally Supabase),
multi-profile configuration, schema management CLI, and backup/restore.

Usage:
    from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter
    from db_adapter import BackupSchema, TableDef, ForeignKey
    from db_adapter import validate_schema, load_db_config
    from db_adapter import DatabaseProfile, DatabaseConfig
"""

__version__ = "0.1.0"

# Adapters
from db_adapter.adapters.base import DatabaseClient
from db_adapter.adapters.postgres import AsyncPostgresAdapter

# Config
from db_adapter.config.loader import load_db_config
from db_adapter.config.models import DatabaseConfig, DatabaseProfile

# Factory
from db_adapter.factory import (
    ProfileNotFoundError,
    connect_and_validate,
    get_adapter,
    resolve_url,
)

# Schema (comparator)
from db_adapter.schema.comparator import validate_schema

# Backup models
from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef

__all__ = [
    # Adapters
    "DatabaseClient",
    "AsyncPostgresAdapter",
    # Config
    "load_db_config",
    "DatabaseProfile",
    "DatabaseConfig",
    # Factory
    "get_adapter",
    "connect_and_validate",
    "ProfileNotFoundError",
    "resolve_url",
    # Schema
    "validate_schema",
    # Backup models
    "BackupSchema",
    "TableDef",
    "ForeignKey",
]

# Optional: AsyncSupabaseAdapter (only available with supabase extra)
try:
    from db_adapter.adapters.supabase import AsyncSupabaseAdapter

    __all__.append("AsyncSupabaseAdapter")
except ImportError:
    # supabase extra not installed -- AsyncSupabaseAdapter unavailable
    pass

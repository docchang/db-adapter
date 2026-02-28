"""Backup and restore with declarative table hierarchy.

Provides ``BackupSchema``-driven backup, restore, and validation.
The table structure and FK relationships are declared by the caller --
no hardcoded table names.

Usage:
    from db_adapter.backup import BackupSchema, TableDef, ForeignKey
    from db_adapter.backup import backup_database, restore_database, validate_backup
"""

from db_adapter.backup.backup_restore import (
    backup_database,
    restore_database,
    validate_backup,
)
from db_adapter.backup.models import BackupSchema, ForeignKey, TableDef

__all__ = [
    "BackupSchema",
    "TableDef",
    "ForeignKey",
    "backup_database",
    "restore_database",
    "validate_backup",
]

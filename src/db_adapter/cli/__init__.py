"""CLI module for database schema management and adapter toolkit.

Provides 8 subcommands for database profile management, schema validation,
schema fix, cross-profile data sync, and backup/restore operations.
Supports config-driven defaults via db.toml so common flags can be omitted.

Usage:
    DB_PROFILE=rds db-adapter connect
    db-adapter status
    db-adapter profiles
    db-adapter validate
    db-adapter fix --confirm                                          # uses column_defs and schema.file from db.toml
    db-adapter fix --schema-file schema.sql --column-defs defs.json   # explicit overrides
    db-adapter sync --from rds --dry-run                              # uses tables and user_id from db.toml
    db-adapter sync --from rds --confirm
    db-adapter backup                                                 # uses backup_schema and user_id from db.toml
    db-adapter backup --validate backup.json                          # validate backup file (no DB connection)
    db-adapter restore backup.json --dry-run                          # preview restore
    db-adapter restore backup.json --yes                              # restore without confirmation prompt

Commands:
    connect   - Connect to database and validate schema
    status    - Show current connection status and table row counts
    profiles  - List available profiles
    validate  - Re-validate current profile schema
    fix       - Fix schema drift (auto-backup before destructive changes when configured)
    sync      - Sync data from another profile to current profile
    backup    - Create backup or validate existing backup file
    restore   - Restore data from a backup file with FK ID remapping

This module serves as a facade: ``main()`` and argparse setup live here,
while command implementations are split across internal sub-modules:
- ``_helpers.py``: Shared constants, console, utility functions
- ``_connection.py``: connect, status, profiles, validate commands
- ``_schema_fix.py``: fix command
- ``_data_sync.py``: sync command
- ``_backup.py``: backup, restore commands
"""

import argparse
import sys

# Re-export helpers (8 symbols)
from db_adapter.cli._helpers import (  # noqa: F401
    console,
    _EXCLUDED_TABLES,
    _get_table_row_counts,
    _print_table_counts,
    _parse_expected_columns,
    _resolve_user_id,
    _load_backup_schema,
    _resolve_backup_schema_path,
)

# Re-export connection commands (7 symbols)
from db_adapter.cli._connection import (  # noqa: F401
    _async_connect,
    _async_validate,
    _async_status,
    cmd_connect,
    cmd_status,
    cmd_profiles,
    cmd_validate,
)

# Re-export schema fix commands (2 symbols)
from db_adapter.cli._schema_fix import (  # noqa: F401
    _async_fix,
    cmd_fix,
)

# Re-export data sync commands (2 symbols)
from db_adapter.cli._data_sync import (  # noqa: F401
    _async_sync,
    cmd_sync,
)

# Re-export backup commands (5 symbols)
from db_adapter.cli._backup import (  # noqa: F401
    _async_backup,
    _async_restore,
    _validate_backup,
    cmd_backup,
    cmd_restore,
)


# ============================================================================
# Main entry point
# ============================================================================


def main() -> int:
    """Main CLI entry point.

    Parses command line arguments and dispatches to appropriate handler.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    parser = argparse.ArgumentParser(
        prog="db-adapter",
        description="Database schema management and adapter toolkit",
    )

    # Global option: --env-prefix
    parser.add_argument(
        "--env-prefix",
        default="",
        help=(
            "Prefix for environment variable lookup "
            "(e.g., --env-prefix APP_ reads APP_DB_PROFILE)"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # connect command
    p_connect = subparsers.add_parser(
        "connect",
        help="Connect to database and validate schema",
    )
    p_connect.set_defaults(func=cmd_connect)

    # status command
    p_status = subparsers.add_parser(
        "status",
        help="Show current connection status and table row counts",
    )
    p_status.set_defaults(func=cmd_status)

    # profiles command
    p_profiles = subparsers.add_parser(
        "profiles",
        help="List available profiles",
    )
    p_profiles.set_defaults(func=cmd_profiles)

    # validate command
    p_validate = subparsers.add_parser(
        "validate",
        help="Re-validate current profile schema",
    )
    p_validate.add_argument(
        "--schema-file",
        required=False,
        default=None,
        help=(
            "Path to SQL file containing CREATE TABLE statements "
            "(overrides schema.file in db.toml)"
        ),
    )
    p_validate.set_defaults(func=cmd_validate)

    # sync command
    p_sync = subparsers.add_parser(
        "sync",
        help="Sync data from another profile to current profile",
    )
    p_sync.add_argument(
        "--from",
        "-f",
        dest="source",
        required=True,
        help="Source profile to sync from",
    )
    p_sync.add_argument(
        "--tables",
        required=False,
        default=None,
        help="Comma-separated list of tables to sync (defaults to sync.tables in db.toml)",
    )
    p_sync.add_argument(
        "--user-id",
        required=False,
        default=None,
        help="User ID to filter records by (defaults to env var from defaults.user_id_env in db.toml)",
    )
    p_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without making changes",
    )
    p_sync.add_argument(
        "--confirm",
        action="store_true",
        help="Actually perform the sync (required for non-dry-run)",
    )
    p_sync.set_defaults(func=cmd_sync)

    # fix command
    p_fix = subparsers.add_parser(
        "fix",
        help="Fix schema drift by adding missing tables and columns",
    )
    p_fix.add_argument(
        "--schema-file",
        required=False,
        default=None,
        help=(
            "Path to SQL file containing CREATE TABLE statements "
            "(defaults to schema.file in db.toml)"
        ),
    )
    p_fix.add_argument(
        "--column-defs",
        required=False,
        default=None,
        help='Path to JSON file mapping "table.column" to SQL type definition',
    )
    p_fix.add_argument(
        "--confirm",
        action="store_true",
        help="Apply fixes",
    )
    p_fix.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip automatic backup before applying fixes",
    )
    p_fix.set_defaults(func=cmd_fix)

    # backup command
    p_backup = subparsers.add_parser(
        "backup",
        help="Create a database backup or validate an existing backup",
    )
    p_backup.add_argument(
        "--backup-schema",
        required=False,
        default=None,
        help="Path to backup schema JSON file (defaults to schema.backup_schema in db.toml)",
    )
    p_backup.add_argument(
        "--user-id",
        required=False,
        default=None,
        help="User ID to filter backup records (defaults to env var from defaults.user_id_env in db.toml)",
    )
    p_backup.add_argument(
        "--output",
        "-o",
        required=False,
        default=None,
        help="Output file path for backup JSON",
    )
    p_backup.add_argument(
        "--tables",
        required=False,
        default=None,
        help="Comma-separated list of tables to back up (subset of backup schema)",
    )
    p_backup.add_argument(
        "--validate",
        type=str,
        default=None,
        help="Path to backup file to validate (read-only, no DB connection)",
    )
    p_backup.set_defaults(func=cmd_backup)

    # restore command
    p_restore = subparsers.add_parser(
        "restore",
        help="Restore data from a backup file",
    )
    p_restore.add_argument(
        "backup_path",
        help="Path to backup JSON file to restore",
    )
    p_restore.add_argument(
        "--backup-schema",
        required=False,
        default=None,
        help="Path to backup schema JSON file (defaults to schema.backup_schema in db.toml)",
    )
    p_restore.add_argument(
        "--user-id",
        required=False,
        default=None,
        help="User ID to filter restore records (defaults to env var from defaults.user_id_env in db.toml)",
    )
    p_restore.add_argument(
        "--mode",
        "-m",
        choices=["skip", "overwrite", "fail"],
        default="skip",
        help="Conflict resolution mode (default: skip)",
    )
    p_restore.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be restored without making changes",
    )
    p_restore.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    p_restore.set_defaults(func=cmd_restore)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Shared CLI helpers: console, constants, and utility functions.

This module provides shared resources used across all CLI sub-modules:
- ``console``: Rich Console instance for terminal output
- ``_EXCLUDED_TABLES``: System tables excluded from row count queries
- ``_get_table_row_counts()``: Query database for table row counts
- ``_print_table_counts()``: Render row counts as Rich table
- ``_parse_expected_columns()``: Parse CREATE TABLE statements from SQL files
- ``_resolve_user_id()``: Resolve user ID from CLI flag or env var
- ``_load_backup_schema()``: Load BackupSchema from JSON file
- ``_resolve_backup_schema_path()``: Resolve backup schema path from CLI or config

Import graph:
    This module imports only from db_adapter.* and stdlib/third-party.
    No imports from other cli sub-modules.
"""

import argparse
import json
import os
from pathlib import Path

import sqlparse
from psycopg import AsyncConnection
from psycopg.sql import SQL, Identifier
from rich.console import Console
from rich.table import Table
from sqlparse.sql import Identifier as SqlIdentifier
from sqlparse.sql import Parenthesis
from sqlparse.tokens import Keyword

from db_adapter.backup.models import BackupSchema
from db_adapter.config.models import DatabaseConfig

console = Console()

# System tables excluded from row count queries (mirrors SchemaIntrospector.EXCLUDED_TABLES_DEFAULT)
_EXCLUDED_TABLES: set[str] = {
    "schema_migrations",
    "pg_stat_statements",
    "spatial_ref_sys",
}


# ============================================================================
# Row count helpers (CLI-internal)
# ============================================================================


async def _get_table_row_counts(database_url: str) -> dict[str, int]:
    """Query all public base tables and return their row counts.

    Opens a direct psycopg async connection to the database, discovers all
    public base tables (excluding system tables), and runs ``SELECT COUNT(*)``
    on each. Returns a dict mapping table names to row counts, sorted
    alphabetically by table name.

    On any failure (connection refused, permission denied, etc.), returns
    an empty dict -- row counts are best-effort and never crash the CLI.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        Dict mapping table name to row count, sorted alphabetically.
        Empty dict on any error.

    Example:
        >>> counts = await _get_table_row_counts("postgresql://localhost/mydb")
        >>> counts
        {'items': 42, 'orders': 15, 'users': 3}
    """
    try:
        async with await AsyncConnection.connect(database_url) as conn:
            # Discover public base tables
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
                rows = await cur.fetchall()

            table_names = [
                row[0] for row in rows if row[0] not in _EXCLUDED_TABLES
            ]

            # Count rows in each table
            counts: dict[str, int] = {}
            for table_name in table_names:
                async with conn.cursor() as cur:
                    await cur.execute(
                        SQL("SELECT COUNT(*) FROM {}").format(
                            Identifier(table_name)
                        )
                    )
                    result = await cur.fetchone()
                    if result is not None:
                        counts[table_name] = result[0]

            return dict(sorted(counts.items()))
    except Exception:
        return {}


def _print_table_counts(counts: dict[str, int]) -> None:
    """Render a Rich table showing row counts for each database table.

    Displays a "Table Data" table with two columns: table name (left-aligned)
    and row count (right-aligned with comma formatting). Tables are sorted
    alphabetically by name.

    If ``counts`` is empty, no output is produced.

    Args:
        counts: Dict mapping table name to row count. Typically the return
            value of :func:`_get_table_row_counts`.

    Example:
        >>> _print_table_counts({"users": 3, "orders": 1500})
        # Prints a Rich table:
        #   Table Data
        #   +--------+-------+
        #   | Table  |  Rows |
        #   +--------+-------+
        #   | orders | 1,500 |
        #   | users  |     3 |
        #   +--------+-------+
    """
    if not counts:
        return

    table = Table(title="Table Data")
    table.add_column("Table")
    table.add_column("Rows", justify="right")

    for name, count in sorted(counts.items()):
        table.add_row(name, f"{count:,}")

    console.print(table)


# ============================================================================
# Schema file parsing (CLI-internal helper)
# ============================================================================


def _parse_expected_columns(schema_file: str | Path) -> dict[str, set[str]]:
    """Parse CREATE TABLE statements from a SQL file into expected columns.

    Uses ``sqlparse`` to tokenize the SQL, correctly handling:
    - Schema-qualified names (``CREATE TABLE public.users (...)``)
    - Quoted identifiers (``CREATE TABLE "Items" (...)``)
    - SQL comments (line ``--`` and block ``/* */``) -- ignored correctly
    - ``IF NOT EXISTS`` variant

    Args:
        schema_file: Path to a SQL file containing CREATE TABLE statements.

    Returns:
        Dict mapping table name to set of column names.
        Example: ``{"users": {"id", "email", "name"}, "orders": {"id", "total"}}``

    Raises:
        FileNotFoundError: If the schema file does not exist.
        ValueError: If no CREATE TABLE statements found in the file.

    Example:
        >>> expected = _parse_expected_columns("schema.sql")
        >>> expected["users"]
        {'id', 'email', 'name', 'created_at'}
    """
    schema_path = Path(schema_file)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    content = schema_path.read_text()
    statements = sqlparse.parse(content)

    result: dict[str, set[str]] = {}

    for stmt in statements:
        if stmt.get_type() != "CREATE":
            continue

        # Verify this is CREATE TABLE (not CREATE INDEX, CREATE VIEW, etc.)
        has_table_keyword = False
        for token in stmt.tokens:
            if token.ttype is Keyword and token.normalized == "TABLE":
                has_table_keyword = True
                break
        if not has_table_keyword:
            continue

        # Extract table name from Identifier token
        table_name = None
        parenthesis = None
        for token in stmt.tokens:
            if isinstance(token, SqlIdentifier) and table_name is None:
                raw_name = token.get_real_name()
                if raw_name:
                    # Strip quotes from quoted identifiers (e.g., "Items" -> Items)
                    table_name = raw_name.strip('"').strip("'").strip("`")
            if isinstance(token, Parenthesis) and parenthesis is None:
                parenthesis = token

        if table_name is None or parenthesis is None:
            continue

        # Strip comments from the parenthesis body before extracting columns
        body = sqlparse.format(str(parenthesis), strip_comments=True)
        # Remove outer parentheses
        body = body.strip()
        if body.startswith("("):
            body = body[1:]
        if body.endswith(")"):
            body = body[:-1]

        columns: set[str] = set()
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            # Skip constraints (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, CONSTRAINT)
            first_word = line.split()[0].upper() if line.split() else ""
            if first_word in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"):
                continue
            # First word of the line is the column name
            col_name = line.split()[0]
            # Skip if it looks like a SQL keyword (all-caps, known keywords)
            if col_name.upper() in ("CREATE", "TABLE", "IF", "NOT", "EXISTS"):
                continue
            # Strip quotes from column names
            col_name = col_name.strip('"').strip("'").strip("`")
            columns.add(col_name.lower())

        if columns:
            result[table_name.lower()] = columns

    if not result:
        raise ValueError(
            f"No CREATE TABLE statements found in {schema_path.name}"
        )

    return result


# ============================================================================
# Shared helpers
# ============================================================================


def _resolve_user_id(
    args: argparse.Namespace, config: DatabaseConfig | None
) -> str | None:
    """Resolve user ID from CLI flag or environment variable.

    Resolution order:
    1. ``--user-id`` CLI flag (via ``args.user_id``)
    2. Environment variable named in ``config.user_id_env``
    3. ``None`` if neither is available

    Uses ``getattr`` for safe access on subparsers that may not define
    ``--user-id``.  Empty-string env var values are treated as
    "not provided".

    Args:
        args: Parsed CLI arguments.
        config: Loaded database config, or ``None`` if unavailable.

    Returns:
        The resolved user ID string, or ``None`` if not available.

    Example:
        >>> uid = _resolve_user_id(args, config)
        >>> if uid is None:
        ...     print("Error: user_id required")
    """
    # 1. CLI flag
    cli_user_id = getattr(args, "user_id", None)
    if cli_user_id:
        return cli_user_id

    # 2. Env var from config.user_id_env
    if config is not None and config.user_id_env:
        env_value = os.environ.get(config.user_id_env)
        if env_value:  # truthy check: empty string treated as not provided
            return env_value

    # 3. Neither available
    return None


def _load_backup_schema(path: str) -> BackupSchema:
    """Load and validate a BackupSchema from a JSON file.

    Reads the JSON file at the given path, parses it, and validates the
    contents against the ``BackupSchema`` Pydantic model.

    Args:
        path: Path to a JSON file containing a BackupSchema definition.

    Returns:
        A validated ``BackupSchema`` instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        pydantic.ValidationError: If the JSON structure does not match
            the ``BackupSchema`` model.

    Example:
        >>> schema = _load_backup_schema("backup-schema.json")
        >>> len(schema.tables)
        3
    """
    schema_path = Path(path)
    with schema_path.open() as f:
        data = json.load(f)
    return BackupSchema(**data)


def _resolve_backup_schema_path(
    args: argparse.Namespace, config: DatabaseConfig | None
) -> str | None:
    """Resolve backup schema file path from CLI flag or config.

    Resolution order:
    1. ``--backup-schema`` CLI flag (via ``args.backup_schema``)
    2. ``config.backup_schema`` from ``db.toml``
    3. ``None`` if neither is available

    Uses ``getattr`` for safe access on subparsers that may not define
    ``--backup-schema``.

    Args:
        args: Parsed CLI arguments.
        config: Loaded database config, or ``None`` if unavailable.

    Returns:
        The resolved path string, or ``None`` if not available.

    Example:
        >>> path = _resolve_backup_schema_path(args, config)
        >>> if path is None:
        ...     print("No backup schema configured")
    """
    # 1. CLI flag
    cli_path = getattr(args, "backup_schema", None)
    if cli_path is not None:
        return cli_path

    # 2. Config fallback
    if config is not None and config.backup_schema:
        return config.backup_schema

    # 3. Neither available
    return None

"""CLI module for database schema management and adapter toolkit.

Provides commands for database profile management, schema validation,
schema fix, and cross-profile data sync.

Usage:
    DB_PROFILE=rds db-adapter connect
    db-adapter status
    db-adapter profiles
    db-adapter validate
    db-adapter fix --schema-file schema.sql --column-defs defs.json --confirm
    db-adapter sync --from rds --tables projects,milestones --user-id abc123 --dry-run
    db-adapter sync --from rds --tables projects,milestones --user-id abc123 --confirm

Commands:
    connect   - Connect to database and validate schema
    status    - Show current connection status
    profiles  - List available profiles
    validate  - Re-validate current profile schema
    fix       - Fix schema drift by adding missing tables and columns
    sync      - Sync data from another profile to current profile
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from db_adapter.config.loader import load_db_config
from db_adapter.factory import (
    connect_and_validate,
    read_profile_lock,
    get_active_profile_name,
    ProfileNotFoundError,
)
from db_adapter.schema.sync import compare_profiles, sync_data

console = Console()


# ============================================================================
# Schema file parsing (CLI-internal helper)
# ============================================================================


def _parse_expected_columns(schema_file: str | Path) -> dict[str, set[str]]:
    """Parse CREATE TABLE statements from a SQL file into expected columns.

    Reads the schema file, finds all CREATE TABLE blocks, and extracts
    table names and column names from each.

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

    # Find all CREATE TABLE blocks
    table_pattern = re.compile(
        r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(([^;]+)\);",
        re.IGNORECASE | re.DOTALL,
    )

    result: dict[str, set[str]] = {}

    for match in table_pattern.finditer(content):
        table_name = match.group(1)
        body = match.group(2)

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
            columns.add(col_name)

        if columns:
            result[table_name] = columns

    if not result:
        raise ValueError(
            f"No CREATE TABLE statements found in {schema_path.name}"
        )

    return result


# ============================================================================
# Async command implementations
# ============================================================================


async def _async_connect(args: argparse.Namespace) -> int:
    """Async implementation for connect command.

    Args:
        args: Parsed arguments with env_prefix.

    Returns:
        0 on success, 1 on failure.
    """
    env_prefix = getattr(args, "env_prefix", "")

    previous_profile = read_profile_lock()

    console.print("Connecting to database...", style="dim")

    result = await connect_and_validate(env_prefix=env_prefix)

    if result.success:
        console.print()
        console.print(
            f"[bold green]v[/bold green] Connected to profile: "
            f"[bold cyan]{result.profile_name}[/bold cyan]"
        )
        console.print("  Schema validation: [green]PASSED[/green]")
        if result.schema_report and result.schema_report.extra_tables:
            console.print(
                f"  Extra tables: [yellow]"
                f"{', '.join(result.schema_report.extra_tables)}[/yellow]"
            )

        # Show profile switch notice
        if previous_profile and previous_profile != result.profile_name:
            console.print(
                f"\n[dim]Switched from[/dim] [bold]{previous_profile}[/bold] "
                f"[dim]to[/dim] [bold cyan]{result.profile_name}[/bold cyan]"
            )

        return 0
    else:
        console.print()
        console.print(f"[bold red]x[/bold red] {result.error}")

        if result.schema_report:
            console.print("\n[bold]Schema validation report:[/bold]")
            console.print(result.schema_report.format_report())

        return 1


async def _async_validate(args: argparse.Namespace) -> int:
    """Async implementation for validate command.

    Args:
        args: Parsed arguments with env_prefix.

    Returns:
        0 on valid schema, 1 on invalid or no profile.
    """
    env_prefix = getattr(args, "env_prefix", "")

    profile = read_profile_lock()

    if not profile:
        console.print("[yellow]No validated profile.[/yellow]")
        console.print(
            "[dim]Run[/dim] [cyan]db-adapter connect[/cyan] [dim]first.[/dim]"
        )
        return 1

    console.print(
        f"Validating schema for profile: [bold cyan]{profile}[/bold cyan]"
    )

    result = await connect_and_validate(
        profile_name=profile, env_prefix=env_prefix
    )

    if result.schema_valid:
        console.print()
        console.print("[bold green]v[/bold green] Schema is valid")
        if result.schema_report and result.schema_report.extra_tables:
            console.print(
                f"  Extra tables: [yellow]"
                f"{', '.join(result.schema_report.extra_tables)}[/yellow]"
            )
        return 0
    else:
        console.print()
        console.print("[bold red]x[/bold red] Schema has drifted")
        if result.schema_report:
            console.print(result.schema_report.format_report())
        return 1


async def _async_fix(args: argparse.Namespace) -> int:
    """Async implementation for fix command.

    Uses ``--schema-file`` to parse expected columns and CREATE TABLE SQL,
    and ``--column-defs`` for ALTER TABLE column type definitions.
    Delegates FK ordering to ``FixPlan.drop_order``/``create_order``.

    Args:
        args: Parsed arguments with schema_file, column_defs, confirm,
            no_backup, and env_prefix.

    Returns:
        0 on success, 1 on failure.
    """
    from db_adapter.schema.fix import generate_fix_plan, apply_fixes

    env_prefix = getattr(args, "env_prefix", "")

    # Resolve profile
    try:
        profile = get_active_profile_name(env_prefix=env_prefix)
    except ProfileNotFoundError:
        console.print("[yellow]No profile configured.[/yellow]")
        console.print(
            "[dim]Run[/dim] [cyan]DB_PROFILE=<name> db-adapter fix "
            "--schema-file schema.sql --column-defs defs.json[/cyan]"
        )
        return 1

    console.print(
        f"Analyzing schema for profile: [bold cyan]{profile}[/bold cyan]"
    )

    # Parse expected columns from schema file
    try:
        expected_columns = _parse_expected_columns(args.schema_file)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"\n[red]Error: {e}[/red]")
        return 1

    # Load column definitions from JSON
    try:
        col_defs_path = Path(args.column_defs)
        column_definitions: dict[str, str] = json.loads(
            col_defs_path.read_text()
        )
    except (FileNotFoundError, json.JSONDecodeError) as e:
        console.print(f"\n[red]Error reading column definitions: {e}[/red]")
        return 1

    # Connect and validate to get schema report
    result = await connect_and_validate(
        profile_name=profile,
        expected_columns=expected_columns,
        env_prefix=env_prefix,
        validate_only=True,
    )

    if result.schema_valid:
        console.print()
        console.print(
            "[bold green]v[/bold green] Schema is valid - no fixes needed"
        )
        return 0

    if not result.schema_report:
        console.print(f"\n[red]Error: {result.error}[/red]")
        return 1

    # Generate fix plan using the new signature
    plan = generate_fix_plan(
        result.schema_report, column_definitions, args.schema_file
    )

    if plan.error:
        console.print(f"\n[red]Error: {plan.error}[/red]")
        return 1

    if not plan.has_fixes:
        console.print()
        console.print(
            "[bold green]v[/bold green] Schema is valid - no fixes needed"
        )
        return 0

    # Show schema differences
    console.print()
    diff_table = Table(
        title="Schema Differences", show_header=True, header_style="bold"
    )
    diff_table.add_column("Table", style="dim")
    diff_table.add_column("Column")
    diff_table.add_column("Type")

    for table_fix in plan.missing_tables:
        diff_table.add_row(
            table_fix.table,
            "[bold green]NEW TABLE[/bold green]",
            "",
        )

    for table_fix in plan.tables_to_recreate:
        diff_table.add_row(
            table_fix.table,
            "[bold yellow]RECREATE[/bold yellow]",
            "",
        )

    for col_fix in plan.missing_columns:
        type_display = col_fix.definition.split()[0]
        if "REFERENCES" in col_fix.definition:
            type_display += " (FK)"
        diff_table.add_row(col_fix.table, col_fix.column, type_display)

    console.print(diff_table)

    # Show execution plan using FixPlan's topological ordering
    console.print()
    console.print("[bold]Execution Plan:[/bold]")
    step = 1

    if not args.no_backup:
        console.print(f"  {step}. Backup [cyan]{profile}[/cyan] database")
        step += 1

    if plan.missing_tables:
        for t_name in plan.create_order:
            if any(tf.table == t_name for tf in plan.missing_tables):
                console.print(
                    f"  {step}. CREATE TABLE [cyan]{t_name}[/cyan]"
                )
                step += 1
        # Tables not in create_order
        for tf in plan.missing_tables:
            if tf.table not in plan.create_order:
                console.print(
                    f"  {step}. CREATE TABLE [cyan]{tf.table}[/cyan]"
                )
                step += 1

    if plan.tables_to_recreate:
        drop_names = [
            t for t in plan.drop_order
            if any(tf.table == t for tf in plan.tables_to_recreate)
        ]
        # Tables not in drop_order
        for tf in plan.tables_to_recreate:
            if tf.table not in drop_names:
                drop_names.append(tf.table)

        console.print(
            f"  {step}. DROP TABLES [cyan]{', '.join(drop_names)}[/cyan]"
        )
        step += 1

        create_names = [
            t for t in plan.create_order
            if any(tf.table == t for tf in plan.tables_to_recreate)
        ]
        for tf in plan.tables_to_recreate:
            if tf.table not in create_names:
                create_names.append(tf.table)

        for t_name in create_names:
            console.print(
                f"  {step}. CREATE TABLE [cyan]{t_name}[/cyan]"
            )
            step += 1

    if plan.missing_columns:
        for c in plan.missing_columns:
            console.print(
                f"  {step}. ALTER TABLE [cyan]{c.table}[/cyan] "
                f"ADD COLUMN {c.column}"
            )
            step += 1

    if not args.confirm:
        console.print()
        console.print(
            "[dim]To apply fixes, add[/dim] [cyan]--confirm[/cyan] "
            "[dim]flag.[/dim]"
        )
        return 0

    # Apply fixes via the async apply_fixes() function
    console.print()
    console.print("[bold]Applying fixes...[/bold]")

    from db_adapter.factory import get_adapter

    try:
        adapter = await get_adapter(
            profile_name=profile, env_prefix=env_prefix
        )
    except Exception as e:
        console.print(
            f"\n[bold red]Error:[/bold red] Connection failed: {e}"
        )
        return 1

    fix_result = await apply_fixes(
        adapter,
        plan,
        dry_run=False,
        confirm=True,
    )

    if fix_result.success:
        console.print()
        console.print("[bold green]v Schema fix complete![/bold green]")
        if fix_result.tables_created:
            console.print(
                f"  Tables created: {fix_result.tables_created}"
            )
        if fix_result.tables_recreated:
            console.print(
                f"  Tables recreated: {fix_result.tables_recreated}"
            )
        if fix_result.columns_added:
            console.print(
                f"  Columns added: {fix_result.columns_added}"
            )
        return 0
    else:
        console.print(
            f"\n[bold red]x[/bold red] Fix failed: {fix_result.error}"
        )
        return 1


async def _async_sync(args: argparse.Namespace) -> int:
    """Async implementation for sync command.

    Accepts ``--tables`` (comma-separated) and ``--user-id`` arguments,
    forwarded to ``compare_profiles()`` and ``sync_data()``.

    Args:
        args: Parsed arguments with source, tables, user_id, dry_run,
            confirm, and env_prefix.

    Returns:
        0 on success, 1 on failure.
    """
    env_prefix = getattr(args, "env_prefix", "")
    source = args.source
    tables = [t.strip() for t in args.tables.split(",")]
    user_id = args.user_id

    # Get destination (current profile)
    dest = read_profile_lock()
    if not dest:
        try:
            dest = get_active_profile_name(env_prefix=env_prefix)
        except ProfileNotFoundError:
            console.print(
                "[red]Error: No destination profile configured.[/red]"
            )
            console.print(
                "[dim]Run:[/dim] [cyan]DB_PROFILE=<name> db-adapter "
                "connect[/cyan]"
            )
            return 1

    if source == dest:
        console.print(
            f"[red]Error: Source and destination are the same profile: "
            f"{source}[/red]"
        )
        return 1

    console.print("Comparing profiles...", style="dim")
    console.print(f"  Source: [bold]{source}[/bold]")
    console.print(f"  Destination: [bold cyan]{dest}[/bold cyan]")
    console.print(f"  Tables: [dim]{', '.join(tables)}[/dim]")

    # Compare profiles
    result = await compare_profiles(
        source, dest, tables=tables, user_id=user_id, env_prefix=env_prefix
    )

    if not result.success:
        console.print(f"\n[red]Error: {result.error}[/red]")
        return 1

    # Show comparison table
    console.print()
    comp_table = Table(
        title="Data Comparison", show_header=True, header_style="bold"
    )
    comp_table.add_column("", style="dim")
    comp_table.add_column(f"{source} (source)", justify="right")
    comp_table.add_column(f"{dest} (dest)", justify="right")

    for tbl in tables:
        comp_table.add_row(
            tbl,
            str(result.source_counts.get(tbl, 0)),
            str(result.dest_counts.get(tbl, 0)),
        )

    console.print(comp_table)

    # Show sync plan
    if result.sync_plan:
        console.print()
        plan_table = Table(
            title="Sync Plan", show_header=True, header_style="bold"
        )
        plan_table.add_column("Table", style="dim")
        plan_table.add_column("New", justify="right", style="green")
        plan_table.add_column("Update", justify="right", style="yellow")

        for table_name, plan in result.sync_plan.items():
            plan_table.add_row(
                table_name,
                str(plan["new"]) if plan["new"] > 0 else "-",
                str(plan["update"]) if plan["update"] > 0 else "-",
            )

        console.print(plan_table)
        console.print("[dim]Source overwrites on collision.[/dim]")

    if args.dry_run:
        console.print()
        console.print("[bold yellow]DRY RUN[/bold yellow] - No changes made.")
        return 0

    if not args.confirm:
        console.print()
        console.print(
            "[dim]To actually sync, add[/dim] [cyan]--confirm[/cyan] "
            "[dim]flag.[/dim]"
        )
        return 0

    console.print()
    console.print("Syncing data...", style="dim")
    sync_result = await sync_data(
        source,
        dest,
        tables=tables,
        user_id=user_id,
        env_prefix=env_prefix,
        dry_run=False,
        confirm=True,
    )

    if sync_result.success:
        console.print("[bold green]v[/bold green] Sync complete.")
        return 0
    else:
        console.print(f"[bold red]x[/bold red] {sync_result.error}")
        return 1


# ============================================================================
# Sync command wrappers (cmd_status, cmd_profiles read local files only)
# ============================================================================


def cmd_connect(args: argparse.Namespace) -> int:
    """Connect to database and validate schema.

    Wraps the async implementation with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on failure.
    """
    return asyncio.run(_async_connect(args))


def cmd_status(args: argparse.Namespace) -> int:
    """Show current connection status.

    Reads only local files (lock file and TOML config) -- no database calls.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 always (informational command).
    """
    profile = read_profile_lock()

    if profile:
        table = Table(title="Connection Status", show_header=False)
        table.add_column("Key", style="dim")
        table.add_column("Value")

        table.add_row(
            "Current profile", f"[bold cyan]{profile}[/bold cyan]"
        )
        table.add_row("Profile source", ".db-profile (validated)")

        try:
            config = load_db_config()
            if profile in config.profiles:
                p = config.profiles[profile]
                table.add_row("Provider", p.provider)
                if p.description:
                    table.add_row("Description", p.description)
        except FileNotFoundError:
            table.add_row("Warning", "[yellow]db.toml not found[/yellow]")

        console.print(table)
    else:
        console.print("[yellow]No validated profile.[/yellow]")
        console.print(
            "[dim]Run:[/dim] [cyan]DB_PROFILE=<name> db-adapter connect[/cyan]"
        )

    return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    """List available profiles from db.toml.

    Reads only local TOML config -- no database calls.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 if db.toml not found.
    """
    try:
        config = load_db_config()
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1

    current = read_profile_lock()

    table = Table(
        title="Database Profiles", show_header=True, header_style="bold"
    )
    table.add_column("", width=2)
    table.add_column("Profile")
    table.add_column("Provider")
    table.add_column("Description")

    for name, profile in config.profiles.items():
        marker = "[bold green]*[/bold green]" if name == current else " "
        name_style = "bold cyan" if name == current else ""
        table.add_row(
            marker,
            f"[{name_style}]{name}[/{name_style}]" if name_style else name,
            profile.provider,
            profile.description or "",
        )

    console.print(table)

    if current:
        console.print(f"\n[bold green]*[/bold green] = current profile")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Re-validate current profile schema.

    Wraps the async implementation with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on valid schema, 1 on invalid or no profile.
    """
    return asyncio.run(_async_validate(args))


def cmd_fix(args: argparse.Namespace) -> int:
    """Fix schema drift by adding missing tables and columns.

    Wraps the async implementation with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on failure.
    """
    return asyncio.run(_async_fix(args))


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync data from source profile to current profile.

    Wraps the async implementation with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on failure.
    """
    return asyncio.run(_async_sync(args))


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
        help="Show current connection status",
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
        required=True,
        help="Comma-separated list of tables to sync (e.g., projects,milestones,tasks)",
    )
    p_sync.add_argument(
        "--user-id",
        required=True,
        help="User ID to filter records by",
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
        required=True,
        help="Path to SQL file containing CREATE TABLE statements",
    )
    p_fix.add_argument(
        "--column-defs",
        required=True,
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
        help="Skip backup step (for testing only)",
    )
    p_fix.set_defaults(func=cmd_fix)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

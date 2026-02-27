"""CLI module for schema management.

Provides commands for database profile management and schema validation.

Usage:
    MC_DB_PROFILE=rds python -m schema connect
    python -m schema status
    python -m schema profiles
    python -m schema validate
    python -m schema sync --from rds --dry-run
    python -m schema sync --from rds --confirm

Commands:
    connect   - Connect to database and validate schema
    status    - Show current connection status
    profiles  - List available profiles
    validate  - Re-validate current profile schema
    sync      - Sync data from another profile to current profile
"""

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import load_db_config
from db import (
    connect_and_validate,
    read_profile_lock,
    get_active_profile_name,
    get_dev_user_id,
    _resolve_url,
    ProfileNotFoundError,
)
from schema.sync import compare_profiles, sync_data

console = Console()


def cmd_connect(args: argparse.Namespace) -> int:
    """Connect to database and validate schema.

    Uses MC_DB_PROFILE env var or existing .db-profile lock file
    to determine which profile to connect to.

    When switching profiles, shows a data comparison report.

    Returns:
        0 on success, 1 on failure
    """
    # Get current profile before switching (for comparison)
    previous_profile = read_profile_lock()

    console.print("Connecting to database...", style="dim")

    result = connect_and_validate()

    if result.success:
        console.print()
        console.print(f"[bold green]✓[/bold green] Connected to profile: [bold cyan]{result.profile_name}[/bold cyan]")
        console.print(f"  Schema validation: [green]PASSED[/green]")
        if result.schema_report and result.schema_report.extra_tables:
            console.print(f"  Extra tables: [yellow]{', '.join(result.schema_report.extra_tables)}[/yellow]")

        # Show data comparison if switching profiles
        if previous_profile and previous_profile != result.profile_name:
            _show_profile_comparison(previous_profile, result.profile_name)
        elif not previous_profile:
            # First connection - show current profile data
            _show_profile_data(result.profile_name)

        return 0
    else:
        console.print()
        console.print(f"[bold red]✗[/bold red] {result.error}")

        if result.schema_report:
            console.print("\n[bold]Schema validation report:[/bold]")
            console.print(result.schema_report.format_report())

        return 1


def _show_profile_comparison(previous_profile: str, current_profile: str) -> None:
    """Show data comparison between two profiles.

    Args:
        previous_profile: Profile we switched from
        current_profile: Profile we switched to
    """
    console.print()
    console.print(
        Panel(
            f"[bold]{previous_profile}[/bold] → [bold cyan]{current_profile}[/bold cyan]",
            title="Profile Switch",
            border_style="cyan",
        )
    )

    comparison = compare_profiles(previous_profile, current_profile)
    if comparison.success:
        # Create comparison table
        table = Table(show_header=True, header_style="bold")
        table.add_column("", style="dim")
        table.add_column(previous_profile, justify="right")
        table.add_column(current_profile, justify="right")
        table.add_column("Δ", justify="right")

        for entity in ["projects", "milestones", "tasks"]:
            prev_count = comparison.source_counts[entity]
            curr_count = comparison.dest_counts[entity]
            diff = curr_count - prev_count

            if diff > 0:
                diff_str = f"[green]+{diff}[/green]"
            elif diff < 0:
                diff_str = f"[red]{diff}[/red]"
            else:
                diff_str = "[dim]=[/dim]"

            table.add_row(
                entity.capitalize(),
                str(prev_count),
                str(curr_count),
                diff_str,
            )

        console.print(table)

        # Show sync hint if data differs
        total_prev = sum(comparison.source_counts.values())
        total_curr = sum(comparison.dest_counts.values())
        if total_prev != total_curr:
            console.print()
            console.print(
                f"[dim]Hint: Use[/dim] [cyan]python -m schema sync --from {previous_profile} --dry-run[/cyan] [dim]to preview sync.[/dim]"
            )
    else:
        console.print(f"[yellow]Could not compare profiles: {comparison.error}[/yellow]")


def _show_profile_data(profile_name: str) -> None:
    """Show data counts for a single profile.

    Args:
        profile_name: Profile to show data for
    """
    from adapters import PostgresAdapter

    try:
        config = load_db_config()
        if profile_name not in config.profiles:
            return

        url = _resolve_url(config.profiles[profile_name])
        adapter = PostgresAdapter(database_url=url)
        user_id = get_dev_user_id()

        counts = {}
        for table in ["projects", "milestones", "tasks"]:
            result = adapter.select(table, "count(*) as cnt", filters={"user_id": user_id})
            counts[table] = result[0]["cnt"] if result else 0

        adapter.close()

        console.print()
        table = Table(title="Database Data", show_header=True, header_style="bold")
        table.add_column("Entity", style="dim")
        table.add_column("Count", justify="right")

        for entity in ["projects", "milestones", "tasks"]:
            table.add_row(entity.capitalize(), str(counts[entity]))

        console.print(table)

    except Exception:
        # Silently ignore errors showing data - connection is already validated
        pass


def cmd_status(args: argparse.Namespace) -> int:
    """Show current connection status.

    Displays the currently validated profile from .db-profile lock file,
    or indicates no profile is configured.

    Returns:
        0 always (informational command)
    """
    profile = read_profile_lock()

    if profile:
        # Profile info table
        table = Table(title="Connection Status", show_header=False)
        table.add_column("Key", style="dim")
        table.add_column("Value")

        table.add_row("Current profile", f"[bold cyan]{profile}[/bold cyan]")
        table.add_row("Profile source", ".db-profile (validated)")

        # Show profile details
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

        # Show data counts
        _show_profile_data(profile)
    else:
        console.print("[yellow]No validated profile.[/yellow]")
        console.print("[dim]Run:[/dim] [cyan]MC_DB_PROFILE=<name> python -m schema connect[/cyan]")

    return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    """List available profiles from db.toml.

    Shows all configured profiles with their details.
    Marks the current profile with an asterisk (*).

    Returns:
        0 on success, 1 if db.toml not found
    """
    try:
        config = load_db_config()
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1

    current = read_profile_lock()

    table = Table(title="Database Profiles", show_header=True, header_style="bold")
    table.add_column("", width=2)
    table.add_column("Profile")
    table.add_column("Provider")
    table.add_column("Description")

    for name, profile in config.profiles.items():
        marker = "[bold green]●[/bold green]" if name == current else " "
        name_style = "bold cyan" if name == current else ""
        table.add_row(
            marker,
            f"[{name_style}]{name}[/{name_style}]" if name_style else name,
            profile.provider,
            profile.description or "",
        )

    console.print(table)

    if current:
        console.print(f"\n[bold green]●[/bold green] = current profile")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Re-validate current profile schema.

    Validates the schema of the currently locked profile without
    changing the lock file.

    Returns:
        0 on valid schema, 1 on invalid or no profile
    """
    profile = read_profile_lock()

    if not profile:
        console.print("[yellow]No validated profile.[/yellow]")
        console.print("[dim]Run[/dim] [cyan]python -m schema connect[/cyan] [dim]first.[/dim]")
        return 1

    console.print(f"Validating schema for profile: [bold cyan]{profile}[/bold cyan]")

    result = connect_and_validate(profile_name=profile)

    if result.schema_valid:
        console.print()
        console.print("[bold green]✓[/bold green] Schema is valid")
        if result.schema_report and result.schema_report.extra_tables:
            console.print(f"  Extra tables: [yellow]{', '.join(result.schema_report.extra_tables)}[/yellow]")
        return 0
    else:
        console.print()
        console.print("[bold red]✗[/bold red] Schema has drifted")
        if result.schema_report:
            console.print(result.schema_report.format_report())
        return 1


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync data from source profile to current profile.

    Uses backup/restore infrastructure to copy data from source to destination.
    Records are matched by slug; source data takes precedence on collision.

    Args:
        args: Parsed arguments with source, dry_run, and confirm flags

    Returns:
        0 on success, 1 on failure
    """
    source = args.source

    # Get destination (current profile)
    dest = read_profile_lock()
    if not dest:
        try:
            dest = get_active_profile_name()
        except ProfileNotFoundError:
            console.print("[red]Error: No destination profile configured.[/red]")
            console.print("[dim]Run:[/dim] [cyan]MC_DB_PROFILE=<name> python -m schema connect[/cyan]")
            return 1

    if source == dest:
        console.print(f"[red]Error: Source and destination are the same profile: {source}[/red]")
        return 1

    console.print("Comparing profiles...", style="dim")
    console.print(f"  Source: [bold]{source}[/bold]")
    console.print(f"  Destination: [bold cyan]{dest}[/bold cyan]")

    # Compare profiles
    result = compare_profiles(source, dest)

    if not result.success:
        console.print(f"\n[red]Error: {result.error}[/red]")
        return 1

    # Show comparison table
    console.print()
    table = Table(title="Data Comparison", show_header=True, header_style="bold")
    table.add_column("", style="dim")
    table.add_column(f"{source} (source)", justify="right")
    table.add_column(f"{dest} (dest)", justify="right")

    for entity in ["projects", "milestones", "tasks"]:
        table.add_row(
            entity.capitalize(),
            str(result.source_counts[entity]),
            str(result.dest_counts[entity]),
        )

    console.print(table)

    # Show sync plan
    console.print()
    plan_table = Table(title="Sync Plan", show_header=True, header_style="bold")
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
        console.print("[dim]To actually sync, add[/dim] [cyan]--confirm[/cyan] [dim]flag.[/dim]")
        return 0

    console.print()
    console.print("Syncing data...", style="dim")
    sync_result = sync_data(source, dest, dry_run=False, confirm=True)

    if sync_result.success:
        console.print("[bold green]✓[/bold green] Sync complete.")
        return 0
    else:
        console.print(f"[bold red]✗[/bold red] {sync_result.error}")
        return 1


def cmd_fix(args: argparse.Namespace) -> int:
    """Fix schema drift by adding missing tables and columns.

    Backs up the database first, then applies ALTER TABLE statements.

    Args:
        args: Parsed arguments with dry_run and confirm flags

    Returns:
        0 on success, 1 on failure
    """
    from schema.fix import generate_fix_plan, apply_fixes

    # Use MC_DB_PROFILE if set, otherwise fall back to lock file
    try:
        profile = get_active_profile_name()
    except ProfileNotFoundError:
        console.print("[yellow]No profile configured.[/yellow]")
        console.print("[dim]Run[/dim] [cyan]MC_DB_PROFILE=<name> python -m schema fix --dry-run[/cyan]")
        return 1

    console.print(f"Analyzing schema for profile: [bold cyan]{profile}[/bold cyan]")

    # Generate fix plan
    plan = generate_fix_plan(profile)

    if plan.error:
        console.print(f"\n[red]Error: {plan.error}[/red]")
        return 1

    if not plan.has_fixes:
        console.print()
        console.print("[bold green]✓[/bold green] Schema is valid - no fixes needed")
        return 0

    # Show detailed column diff table
    console.print()
    table = Table(title="Schema Differences", show_header=True, header_style="bold")
    table.add_column("Table", style="dim")
    table.add_column("Column")
    table.add_column("Type")

    # Get all missing columns (including from tables to recreate)
    from schema.fix import COLUMN_DEFINITIONS

    for table_fix in plan.missing_tables:
        table.add_row(
            table_fix.table,
            "[bold green]NEW TABLE[/bold green]",
            "",
        )

    # For tables to recreate, show their missing columns
    for table_fix in plan.tables_to_recreate:
        result_check = connect_and_validate(profile_name=profile)
        if result_check.schema_report:
            for diff in result_check.schema_report.missing_columns:
                if diff.table == table_fix.table:
                    key = f"{diff.table}.{diff.column}"
                    if key in COLUMN_DEFINITIONS:
                        type_display = COLUMN_DEFINITIONS[key].split()[0]
                        if "REFERENCES" in COLUMN_DEFINITIONS[key]:
                            type_display += " (FK)"
                        table.add_row(diff.table, diff.column, type_display)

    # Single-column fixes
    for col_fix in plan.missing_columns:
        type_display = col_fix.definition.split()[0]
        if "REFERENCES" in col_fix.definition:
            type_display += " (FK)"
        table.add_row(col_fix.table, col_fix.column, type_display)

    console.print(table)

    # Show execution plan (must match actual execution order)
    console.print()
    console.print("[bold]Execution Plan:[/bold]")
    step = 1

    # FK order for display
    fk_drop_order = {"tasks": 0, "milestones": 1, "projects": 2}
    fk_create_order = {"projects": 0, "milestones": 1, "tasks": 2}

    console.print(f"  {step}. Backup [cyan]{profile}[/cyan] database")
    step += 1

    if plan.missing_tables:
        for t in plan.missing_tables:
            console.print(f"  {step}. CREATE TABLE [cyan]{t.table}[/cyan]")
            step += 1

    if plan.tables_to_recreate:
        # Show DROP all at once
        sorted_drop = sorted(plan.tables_to_recreate, key=lambda t: fk_drop_order.get(t.table, 99))
        drop_names = [t.table for t in sorted_drop]
        console.print(f"  {step}. DROP TABLES [cyan]{', '.join(drop_names)}[/cyan]")
        step += 1

        # Show CREATE in correct order (projects first)
        sorted_create = sorted(plan.tables_to_recreate, key=lambda t: fk_create_order.get(t.table, 99))
        for t in sorted_create:
            console.print(f"  {step}. CREATE TABLE [cyan]{t.table}[/cyan]")
            step += 1


    if plan.missing_columns:
        for c in plan.missing_columns:
            console.print(f"  {step}. ALTER TABLE [cyan]{c.table}[/cyan] ADD COLUMN {c.column}")
            step += 1

    if not args.confirm:
        console.print()
        console.print("[dim]To apply fixes, add[/dim] [cyan]--confirm[/cyan] [dim]flag.[/dim]")
        return 0

    # Apply fixes step by step with progress
    console.print()
    console.print("[bold]Applying fixes...[/bold]")

    from datetime import datetime
    from pathlib import Path
    import subprocess
    import io
    import sys

    from adapters import PostgresAdapter
    from config import load_db_config
    from db import _resolve_url

    step = 1
    backup_path = None

    # Step 1: Backup (unless --no-backup)
    if not args.no_backup:
        try:
            backup_dir = Path(__file__).parent.parent / "backup" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
            backup_path = backup_dir / f"pre-fix-{profile}-{timestamp}.json"

            # Use subprocess to avoid connection conflicts
            env = dict(os.environ)
            env["MC_DB_PROFILE"] = profile
            result = subprocess.run(
                ["uv", "run", "python", "backup/backup_cli.py", "backup", "--output", str(backup_path)],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode != 0:
                raise Exception(result.stderr or "Backup failed")

            console.print(f"  {step}. Backup [cyan]{profile}[/cyan] database [green]✓[/green]")
            console.print(f"     [dim]{backup_path}[/dim]")
        except Exception as e:
            console.print(f"  {step}. Backup [cyan]{profile}[/cyan] database [red]✗[/red]")
            console.print(f"     [bold red]Error:[/bold red] {e}")
            return 1
        step += 1
    elif plan.tables_to_recreate:
        console.print("[bold yellow]Warning:[/bold yellow] --no-backup with table recreation - data may be lost!")
        console.print("[dim]Proceeding without backup...[/dim]")

    # Get database connection
    try:
        config = load_db_config()
        url = _resolve_url(config.profiles[profile])
        adapter = PostgresAdapter(database_url=url)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] Connection failed: {e}")
        return 1

    # Step 2+: Create new tables
    for table_fix in plan.missing_tables:
        try:
            with adapter._conn.cursor() as cur:
                cur.execute(table_fix.to_sql())
            adapter._conn.commit()
            console.print(f"  {step}. CREATE TABLE [cyan]{table_fix.table}[/cyan] [green]✓[/green]")
        except Exception as e:
            console.print(f"  {step}. CREATE TABLE [cyan]{table_fix.table}[/cyan] [red]✗[/red]")
            console.print(f"     [bold red]Error:[/bold red] {e}")
            adapter.close()
            return 1
        step += 1

    # Step 3+: Recreate tables - DROP all first, then CREATE all
    # FK order for DROP: tasks → milestones → projects (reverse)
    # FK order for CREATE: projects → milestones → tasks (forward)
    fk_drop_order = {"tasks": 0, "milestones": 1, "projects": 2}
    fk_create_order = {"projects": 0, "milestones": 1, "tasks": 2}

    if plan.tables_to_recreate:
        # DROP all tables at once (faster, avoids FK issues)
        sorted_for_drop = sorted(plan.tables_to_recreate, key=lambda t: fk_drop_order.get(t.table, 99))
        drop_tables = [t.table for t in sorted_for_drop]
        drop_sql = "; ".join([f"DROP TABLE IF EXISTS {t} CASCADE" for t in drop_tables])

        try:
            with adapter._conn.cursor() as cur:
                cur.execute(drop_sql)
            adapter._conn.commit()
            console.print(f"  {step}. DROP TABLES [cyan]{', '.join(drop_tables)}[/cyan] [green]✓[/green]")
        except Exception as e:
            console.print(f"  {step}. DROP TABLES [cyan]{', '.join(drop_tables)}[/cyan] [red]✗[/red]")
            console.print(f"     [bold red]Error:[/bold red] {e}")
            adapter.close()
            return 1
        step += 1

        # CREATE all tables in correct FK order
        sorted_for_create = sorted(plan.tables_to_recreate, key=lambda t: fk_create_order.get(t.table, 99))
        for table_fix in sorted_for_create:
            try:
                with adapter._conn.cursor() as cur:
                    cur.execute(table_fix.to_sql())
                adapter._conn.commit()
                console.print(f"  {step}. CREATE TABLE [cyan]{table_fix.table}[/cyan] [green]✓[/green]")
            except Exception as e:
                console.print(f"  {step}. CREATE TABLE [cyan]{table_fix.table}[/cyan] [red]✗[/red]")
                console.print(f"     [bold red]Error:[/bold red] {e}")
                adapter.close()
                return 1
            step += 1

    # Step 4+: Add single columns
    for col_fix in plan.missing_columns:
        try:
            with adapter._conn.cursor() as cur:
                cur.execute(col_fix.to_sql())
            adapter._conn.commit()
            console.print(f"  {step}. ALTER TABLE [cyan]{col_fix.table}[/cyan] ADD {col_fix.column} [green]✓[/green]")
        except Exception as e:
            console.print(f"  {step}. ALTER TABLE [cyan]{col_fix.table}[/cyan] ADD {col_fix.column} [red]✗[/red]")
            console.print(f"     [bold red]Error:[/bold red] {e}")
            adapter.close()
            return 1
        step += 1

    adapter.close()

    # Verify (validate_only=True to not write lock file)
    verify_result = connect_and_validate(profile_name=profile, validate_only=True)
    if verify_result.success:
        console.print(f"  {step}. Verify schema [green]✓[/green]")
    else:
        console.print(f"  {step}. Verify schema [yellow]![/yellow]")
        console.print(f"     [yellow]Warning: {verify_result.error}[/yellow]")

    console.print()
    console.print("[bold green]✓ Schema fix complete![/bold green]")

    return 0


def main() -> int:
    """Main CLI entry point.

    Parses command line arguments and dispatches to appropriate handler.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = argparse.ArgumentParser(
        prog="python -m schema",
        description="Database schema management for Mission Control",
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

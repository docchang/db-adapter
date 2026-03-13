"""CLI data sync command.

Provides the sync subcommand for cross-profile data synchronization:
- ``_async_sync()``: Async implementation of data sync with FK pre-flight warning
- ``cmd_sync()``: Sync wrapper

Import graph:
    Imports from _helpers and db_adapter.* only.
    No imports from other cli sub-modules.
"""

import argparse
import asyncio
import logging

from rich.table import Table

from db_adapter.cli._helpers import (
    console,
    _resolve_user_id,
)
from db_adapter.config.loader import load_db_config
from db_adapter.factory import (
    get_active_profile_name,
    read_profile_lock,
    resolve_url,
    ProfileNotFoundError,
)
from db_adapter.schema.introspector import SchemaIntrospector
from db_adapter.schema.sync import compare_profiles, sync_data

logger = logging.getLogger(__name__)


# ============================================================================
# Async command implementation
# ============================================================================


async def _async_sync(args: argparse.Namespace) -> int:
    """Async implementation for sync command.

    Resolves ``tables`` from ``--tables`` CLI flag or
    ``config.sync_tables`` from ``db.toml``.  Resolves ``user_id`` via
    ``_resolve_user_id()`` (CLI flag -> env var -> error).

    Args:
        args: Parsed arguments with source, optional tables, optional
            user_id, dry_run, confirm, and env_prefix.

    Returns:
        0 on success, 1 on failure.
    """
    env_prefix = getattr(args, "env_prefix", "")
    source = args.source

    # Load config for fallback values
    try:
        config = load_db_config()
    except Exception:
        config = None

    # Resolve tables: CLI --tables -> config.sync_tables -> error
    cli_tables: str | None = getattr(args, "tables", None)

    if cli_tables is not None:
        tables = [t.strip() for t in cli_tables.split(",")]
    elif config is not None and config.sync_tables:
        tables = config.sync_tables
    else:
        console.print(
            "\n[red]Error: No tables specified. "
            "Provide --tables or configure sync.tables in db.toml[/red]"
        )
        return 1

    # Resolve user_id: CLI --user-id -> env var -> error
    user_id = _resolve_user_id(args, config)

    if not user_id:
        env_hint = (
            f"Set {config.user_id_env} or pass --user-id"
            if config and config.user_id_env
            else "Provide --user-id or configure defaults.user_id_env "
            "in db.toml"
        )
        console.print(f"\n[red]Error: No user ID available. {env_hint}[/red]")
        return 1

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

    # FK pre-flight warning: detect FK constraints on target tables
    # when backup_schema is not configured (heuristic for direct-insert path)
    if config is not None and not config.backup_schema:
        try:
            dest_profile = config.profiles[dest]
            dest_url = resolve_url(dest_profile)
            async with SchemaIntrospector(dest_url) as introspector:
                db_schema = await introspector.introspect()
                fk_tables: list[str] = []
                for table_name in tables:
                    table_schema = db_schema.tables.get(table_name)
                    if table_schema is None:
                        continue
                    for constraint in table_schema.constraints.values():
                        if constraint.constraint_type == "FOREIGN KEY":
                            fk_tables.append(table_name)
                            break
                if fk_tables:
                    table_names = ", ".join(fk_tables)
                    console.print(
                        f"[yellow]Warning:[/yellow] Tables {table_names} "
                        f"have foreign key constraints.\n"
                        f"Direct sync does not handle FK remapping. Consider "
                        f"configuring\nbackup_schema in db.toml for FK-aware sync."
                    )
        except Exception as e:
            logger.debug("FK detection skipped: %s", e)

    console.print("Comparing profiles...", style="dim")
    console.print(f"  Source: [bold]{source}[/bold]")
    console.print(f"  Destination: [bold cyan]{dest}[/bold cyan]")
    console.print(f"  Tables: [dim]{', '.join(tables)}[/dim]")

    # Compare profiles
    result = await compare_profiles(
        source, dest, tables=tables, user_id=user_id, env_prefix=env_prefix
    )

    if not result.success:
        error_msg = "; ".join(result.errors) if result.errors else "Unknown error"
        console.print(f"\n[red]Error: {error_msg}[/red]")
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
        error_msg = (
            "; ".join(sync_result.errors)
            if sync_result.errors
            else "Unknown error"
        )
        console.print(f"[bold red]x[/bold red] {error_msg}")
        return 1


# ============================================================================
# Sync command wrapper
# ============================================================================


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync data from source profile to current profile.

    Wraps the async implementation with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on failure.
    """
    return asyncio.run(_async_sync(args))

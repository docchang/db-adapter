"""CLI schema fix command.

Provides the fix subcommand for repairing schema drift:
- ``_async_fix()``: Async implementation of schema fix
- ``cmd_fix()``: Sync wrapper

Import graph:
    Imports from _helpers and db_adapter.* only.
    No imports from other cli sub-modules.
"""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from rich.table import Table

from db_adapter.cli._helpers import (
    console,
    _load_backup_schema,
    _parse_expected_columns,
    _resolve_backup_schema_path,
    _resolve_user_id,
)
from db_adapter.backup.backup_restore import backup_database
from db_adapter.config.loader import load_db_config
from db_adapter.factory import (
    connect_and_validate,
    get_active_profile_name,
    get_adapter,
    ProfileNotFoundError,
)


# ============================================================================
# Async command implementation
# ============================================================================


async def _async_fix(args: argparse.Namespace) -> int:
    """Async implementation for fix command.

    Resolves the schema file from ``--schema-file`` CLI argument or falls
    back to ``config.schema_file`` from ``db.toml``.  Uses the resolved
    schema file to parse expected columns and CREATE TABLE SQL, and
    ``--column-defs`` for ALTER TABLE column type definitions.
    Delegates FK ordering to ``FixPlan.drop_order``/``create_order``.

    Args:
        args: Parsed arguments with optional schema_file, column_defs,
            confirm, and env_prefix.

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

    # Always attempt to load config for fallback values
    try:
        config = load_db_config()
    except Exception:
        config = None

    # Resolve schema file: CLI --schema-file -> config.schema_file -> error
    schema_file: str | None = getattr(args, "schema_file", None)

    if schema_file is None and config is not None:
        schema_file = config.schema_file

    if schema_file is None:
        console.print(
            "\n[red]Error: No schema file available. "
            "Provide --schema-file or configure schema.file in db.toml[/red]"
        )
        return 1

    # Parse expected columns from schema file
    try:
        expected_columns = _parse_expected_columns(schema_file)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"\n[red]Error: {e}[/red]")
        return 1

    # Resolve column_defs: CLI --column-defs -> config.column_defs -> error
    column_defs: str | None = getattr(args, "column_defs", None)

    if column_defs is None and config is not None:
        column_defs = config.column_defs

    if column_defs is None:
        console.print(
            "\n[red]Error: No column definitions available. "
            "Provide --column-defs or configure schema.column_defs "
            "in db.toml[/red]"
        )
        return 1

    # Load column definitions from JSON
    try:
        col_defs_path = Path(column_defs)
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
        result.schema_report, column_definitions, schema_file
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

    try:
        adapter = await get_adapter(
            profile_name=profile, env_prefix=env_prefix
        )
    except Exception as e:
        console.print(
            f"\n[bold red]Error:[/bold red] Connection failed: {e}"
        )
        return 1

    try:
        # Auto-backup before applying destructive DDL
        if plan.has_fixes and not args.no_backup:
            backup_schema_path = _resolve_backup_schema_path(args, config)
            if backup_schema_path is None:
                console.print(
                    "[yellow]Warning: No backup_schema configured "
                    "-- skipping auto-backup[/yellow]"
                )
            else:
                try:
                    backup_schema = _load_backup_schema(backup_schema_path)
                except Exception as e:
                    console.print(
                        f"[yellow]Warning: Failed to load backup schema: "
                        f"{e} -- skipping auto-backup[/yellow]"
                    )
                    backup_schema = None

                if backup_schema is not None:
                    backup_user_id = _resolve_user_id(args, config)
                    if not backup_user_id:
                        console.print(
                            "[yellow]Warning: No user_id available "
                            "-- skipping auto-backup[/yellow]"
                        )
                    else:
                        try:
                            Path("backups").mkdir(exist_ok=True)
                            timestamp = datetime.now().strftime(
                                "%Y%m%d-%H%M%S"
                            )
                            backup_output = (
                                f"backups/pre-fix-{profile}-{timestamp}.json"
                            )
                            console.print(
                                "Creating pre-fix backup...", style="dim"
                            )
                            await backup_database(
                                adapter,
                                backup_schema,
                                backup_user_id,
                                output_path=backup_output,
                            )
                            console.print(
                                f"[green]Backup saved to: "
                                f"{backup_output}[/green]"
                            )
                        except Exception as e:
                            console.print(
                                f"\n[bold red]Error:[/bold red] "
                                f"Auto-backup failed: {e}"
                            )
                            console.print(
                                "[red]Aborting fix -- backup must "
                                "succeed before applying changes[/red]"
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
    finally:
        await adapter.close()


# ============================================================================
# Sync command wrapper
# ============================================================================


def cmd_fix(args: argparse.Namespace) -> int:
    """Fix schema drift by adding missing tables and columns.

    Wraps the async implementation with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on failure.
    """
    return asyncio.run(_async_fix(args))

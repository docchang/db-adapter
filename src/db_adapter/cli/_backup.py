"""CLI backup and restore commands.

Provides the backup and restore subcommands:
- ``_async_backup()``: Async implementation of backup
- ``_async_restore()``: Async implementation of restore
- ``_validate_backup()``: Sync validation of backup file
- ``cmd_backup()``: Sync wrapper for backup (dispatches to validate or backup)
- ``cmd_restore()``: Sync wrapper for restore

Import graph:
    Imports from _helpers and db_adapter.* only.
    No imports from other cli sub-modules.
"""

import argparse
import asyncio
import json
from pathlib import Path

from rich.table import Table

from db_adapter.cli._helpers import (
    console,
    _load_backup_schema,
    _resolve_backup_schema_path,
    _resolve_user_id,
)
from db_adapter.backup.backup_restore import (
    backup_database,
    restore_database,
    validate_backup as validate_backup_file,
)
from db_adapter.backup.models import BackupSchema
from db_adapter.config.loader import load_db_config
from db_adapter.factory import get_adapter


# ============================================================================
# Async command implementations
# ============================================================================


async def _async_backup(args: argparse.Namespace) -> int:
    """Async implementation for backup command.

    Creates a database backup using the backup library. Resolves
    backup schema, user ID, and optional table filter from CLI flags
    and config fallbacks. Connects to the database via ``get_adapter()``
    and calls ``backup_database()``.

    The adapter is always closed in a ``finally`` block to prevent
    connection leaks.

    Args:
        args: Parsed arguments with optional backup_schema, user_id,
            output, tables, and env_prefix.

    Returns:
        0 on success, 1 on failure.
    """
    env_prefix = getattr(args, "env_prefix", "")

    # 1. Load config (graceful degradation)
    try:
        config = load_db_config()
    except Exception:
        config = None

    # 2. Resolve backup_schema path
    backup_schema_path = _resolve_backup_schema_path(args, config)
    if backup_schema_path is None:
        console.print(
            "\n[red]Error: No backup schema available. "
            "Provide --backup-schema or configure schema.backup_schema "
            "in db.toml[/red]"
        )
        return 1

    # 3. Load BackupSchema
    try:
        schema = _load_backup_schema(backup_schema_path)
    except FileNotFoundError:
        console.print(
            f"\n[red]Error: Backup schema file not found: "
            f"{backup_schema_path}[/red]"
        )
        return 1
    except (json.JSONDecodeError, Exception) as e:
        console.print(
            f"\n[red]Error: Failed to load backup schema: {e}[/red]"
        )
        return 1

    # 4. Resolve user_id
    user_id = _resolve_user_id(args, config)
    if not user_id:
        env_hint = (
            f"Set {config.user_id_env} or pass --user-id"
            if config and config.user_id_env
            else "Provide --user-id or configure defaults.user_id_env "
            "in db.toml"
        )
        console.print(
            f"\n[red]Error: No user ID available. {env_hint}[/red]"
        )
        return 1

    # 5. Filter schema by --tables if provided
    cli_tables: str | None = getattr(args, "tables", None)
    if cli_tables is not None:
        requested_tables = [t.strip() for t in cli_tables.split(",")]
        requested_set = set(requested_tables)

        # Warn if child table included without parent
        for table_def in schema.tables:
            if table_def.name in requested_set and table_def.parent is not None:
                if table_def.parent.table not in requested_set:
                    console.print(
                        f"[yellow]Warning: Table '{table_def.name}' has "
                        f"parent '{table_def.parent.table}' which is not "
                        f"in --tables list[/yellow]"
                    )

        filtered_tables = [
            t for t in schema.tables if t.name in requested_set
        ]
        schema = BackupSchema(tables=filtered_tables)

    # 6. Resolve profile + create adapter
    try:
        adapter = await get_adapter(env_prefix=env_prefix)
    except Exception as e:
        console.print(
            f"\n[red]Error: Failed to connect: {e}[/red]"
        )
        return 1

    # 7. Call backup_database with try/finally for adapter cleanup
    try:
        output_path = getattr(args, "output", None)
        console.print("Creating backup...", style="dim")
        result_path = await backup_database(
            adapter, schema, user_id, output_path=output_path
        )

        # 8. Print result
        console.print()
        console.print(
            f"[bold green]v[/bold green] Backup saved to: "
            f"[cyan]{result_path}[/cyan]"
        )
        for table_def in schema.tables:
            console.print(
                f"  {table_def.name}: backed up"
            )
        return 0
    except Exception as e:
        console.print(
            f"\n[red]Error: Backup failed: {e}[/red]"
        )
        return 1
    finally:
        await adapter.close()


async def _async_restore(args: argparse.Namespace) -> int:
    """Async implementation for restore command.

    Restores data from a backup JSON file. Resolves backup schema,
    user ID from CLI flags and config fallbacks. Verifies the backup
    file exists, prompts for confirmation (unless ``--yes`` or
    ``--dry-run``), and calls ``restore_database()``.

    The adapter is always closed in a ``finally`` block.

    Args:
        args: Parsed arguments with backup_path, optional backup_schema,
            user_id, mode, dry_run, yes, and env_prefix.

    Returns:
        0 on success, 1 on failure.
    """
    env_prefix = getattr(args, "env_prefix", "")

    # 1. Load config, resolve backup_schema, load BackupSchema, resolve user_id
    try:
        config = load_db_config()
    except Exception:
        config = None

    backup_schema_path = _resolve_backup_schema_path(args, config)
    if backup_schema_path is None:
        console.print(
            "\n[red]Error: No backup schema available. "
            "Provide --backup-schema or configure schema.backup_schema "
            "in db.toml[/red]"
        )
        return 1

    try:
        schema = _load_backup_schema(backup_schema_path)
    except FileNotFoundError:
        console.print(
            f"\n[red]Error: Backup schema file not found: "
            f"{backup_schema_path}[/red]"
        )
        return 1
    except (json.JSONDecodeError, Exception) as e:
        console.print(
            f"\n[red]Error: Failed to load backup schema: {e}[/red]"
        )
        return 1

    user_id = _resolve_user_id(args, config)
    if not user_id:
        env_hint = (
            f"Set {config.user_id_env} or pass --user-id"
            if config and config.user_id_env
            else "Provide --user-id or configure defaults.user_id_env "
            "in db.toml"
        )
        console.print(
            f"\n[red]Error: No user ID available. {env_hint}[/red]"
        )
        return 1

    # 2. Verify backup file exists
    backup_path = args.backup_path
    if not Path(backup_path).exists():
        console.print(
            f"\n[red]Error: Backup file not found: {backup_path}[/red]"
        )
        return 1

    # 3. Confirmation prompt (unless --yes or --dry-run)
    if not args.yes and not args.dry_run:
        console.print(
            f"Restore from [cyan]{backup_path}[/cyan] "
            f"with mode=[bold]{args.mode}[/bold]?"
        )
        try:
            answer = input("Type 'yes' to confirm: ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Aborted.[/yellow]")
            return 1
        if answer.strip().lower() != "yes":
            console.print("[yellow]Aborted.[/yellow]")
            return 1

    # 4. Resolve profile + create adapter
    try:
        adapter = await get_adapter(env_prefix=env_prefix)
    except Exception as e:
        console.print(
            f"\n[red]Error: Failed to connect: {e}[/red]"
        )
        return 1

    # 5. Call restore_database with try/finally for adapter cleanup
    try:
        if args.dry_run:
            console.print("Previewing restore (dry run)...", style="dim")
        else:
            console.print("Restoring data...", style="dim")

        result = await restore_database(
            adapter,
            schema,
            backup_path,
            user_id,
            mode=args.mode,
            dry_run=args.dry_run,
        )

        # 6. Print result
        console.print()
        if args.dry_run:
            console.print(
                "[bold yellow]DRY RUN[/bold yellow] - No changes made."
            )
        else:
            console.print(
                "[bold green]v[/bold green] Restore complete."
            )

        console.print(f"  Mode: [bold]{args.mode}[/bold]")
        console.print()

        results_table = Table(
            title="Restore Results", show_header=True, header_style="bold"
        )
        results_table.add_column("Table", style="dim")
        results_table.add_column("Inserted", justify="right", style="green")
        results_table.add_column("Updated", justify="right", style="yellow")
        results_table.add_column("Skipped", justify="right")
        results_table.add_column("Failed", justify="right", style="red")

        for table_def in schema.tables:
            table_name = table_def.name
            if table_name in result:
                counts = result[table_name]
                results_table.add_row(
                    table_name,
                    str(counts.get("inserted", 0)),
                    str(counts.get("updated", 0)),
                    str(counts.get("skipped", 0)),
                    str(counts.get("failed", 0)),
                )

        console.print(results_table)

        # Display per-row failure details if any
        for table_def in schema.tables:
            details = result.get(table_def.name, {}).get("failure_details", [])
            if details:
                console.print(f"\n  [red]Failed rows in {table_def.name}:[/red]")
                for d in details:
                    console.print(
                        f"    row {d['row_index']} (pk={d['old_pk']}): {d['error']}"
                    )

        return 0
    except Exception as e:
        console.print(
            f"\n[red]Error: Restore failed: {e}[/red]"
        )
        return 1
    finally:
        await adapter.close()


def _validate_backup(args: argparse.Namespace) -> int:
    """Validate a backup file against a BackupSchema.

    This is a synchronous operation -- no database connection needed.
    Loads the backup schema from CLI flag or config, then calls
    ``validate_backup()`` to check the backup file's structure and
    data integrity.

    Args:
        args: Parsed arguments with validate (path to backup file)
            and optional backup_schema.

    Returns:
        0 on valid backup, 1 on invalid or error.
    """
    # 1. Load config, resolve backup_schema path, load BackupSchema
    try:
        config = load_db_config()
    except Exception:
        config = None

    backup_schema_path = _resolve_backup_schema_path(args, config)
    if backup_schema_path is None:
        console.print(
            "\n[red]Error: No backup schema available. "
            "Provide --backup-schema or configure schema.backup_schema "
            "in db.toml[/red]"
        )
        return 1

    try:
        schema = _load_backup_schema(backup_schema_path)
    except FileNotFoundError:
        console.print(
            f"\n[red]Error: Backup schema file not found: "
            f"{backup_schema_path}[/red]"
        )
        return 1
    except (json.JSONDecodeError, Exception) as e:
        console.print(
            f"\n[red]Error: Failed to load backup schema: {e}[/red]"
        )
        return 1

    # 2. Call validate_backup (sync -- no DB connection)
    backup_file_path = args.validate
    result = validate_backup_file(backup_file_path, schema)

    # 3. Print result
    console.print()
    if result["valid"]:
        console.print(
            f"[bold green]v[/bold green] Backup is valid: "
            f"[cyan]{backup_file_path}[/cyan]"
        )
    else:
        console.print(
            f"[bold red]x[/bold red] Backup is invalid: "
            f"[cyan]{backup_file_path}[/cyan]"
        )

    if result["errors"]:
        console.print("\n[bold]Errors:[/bold]")
        for error in result["errors"]:
            console.print(f"  [red]- {error}[/red]")

    if result["warnings"]:
        console.print("\n[bold]Warnings:[/bold]")
        for warning in result["warnings"]:
            console.print(f"  [yellow]- {warning}[/yellow]")

    return 0 if result["valid"] else 1


# ============================================================================
# Sync command wrappers
# ============================================================================


def cmd_backup(args: argparse.Namespace) -> int:
    """Create a database backup or validate an existing backup file.

    When ``--validate`` is provided, delegates to the synchronous
    ``_validate_backup()`` function (no DB connection needed).
    Otherwise, wraps the async ``_async_backup()`` with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on failure.
    """
    if getattr(args, "validate", None) is not None:
        return _validate_backup(args)
    return asyncio.run(_async_backup(args))


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore data from a backup file.

    Wraps the async implementation with ``asyncio.run()``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on failure.
    """
    return asyncio.run(_async_restore(args))

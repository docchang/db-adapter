"""CLI connection and validation commands.

Provides the connect, status, profiles, and validate subcommands:
- ``_async_connect()``: Async connect + schema validation
- ``_async_validate()``: Async re-validate current profile
- ``_async_status()``: Async show connection status + row counts
- ``cmd_connect()``: Sync wrapper for connect
- ``cmd_status()``: Sync wrapper for status
- ``cmd_profiles()``: List available profiles (sync, no DB call)
- ``cmd_validate()``: Sync wrapper for validate

Import graph:
    Imports from _helpers and db_adapter.* only.
    No imports from other cli sub-modules.
"""

import argparse
import asyncio

from rich.table import Table

from db_adapter.cli._helpers import (
    console,
    _get_table_row_counts,
    _parse_expected_columns,
    _print_table_counts,
)
from db_adapter.config.loader import load_db_config
from db_adapter.factory import (
    connect_and_validate,
    read_profile_lock,
    resolve_url,
)


# ============================================================================
# Async command implementations
# ============================================================================


async def _async_connect(args: argparse.Namespace) -> int:
    """Async implementation for connect command.

    Loads config from ``db.toml`` to determine whether schema validation
    should be performed.  When ``validate_on_connect`` is ``True`` and a
    schema file is available, expected columns are parsed and passed to
    ``connect_and_validate()``.  Gracefully degrades to connect-only mode
    when config or schema file is unavailable.

    Args:
        args: Parsed arguments with env_prefix.

    Returns:
        0 on success, 1 on failure.
    """
    env_prefix = getattr(args, "env_prefix", "")

    previous_profile = read_profile_lock()

    console.print("Connecting to database...", style="dim")

    # Determine expected_columns based on config
    expected_columns: dict[str, set[str]] | None = None
    validation_skip_reason: str | None = None

    try:
        config = load_db_config()
    except Exception:
        # db.toml missing or malformed -- fall back to connect-only
        config = None
        validation_skip_reason = "no config found"

    if config is not None:
        if config.validate_on_connect is True:
            try:
                expected_columns = _parse_expected_columns(config.schema_file)
            except (FileNotFoundError, ValueError):
                # Schema file missing or unparseable -- connect-only
                validation_skip_reason = "schema file not found"
        else:
            validation_skip_reason = "schema validation disabled in config"

    result = await connect_and_validate(
        env_prefix=env_prefix,
        expected_columns=expected_columns,
    )

    if not result.success:
        console.print()
        if result.schema_report:
            console.print(
                f"[bold red]x[/bold red] Connected to profile: "
                f"[bold cyan]{result.profile_name}[/bold cyan]"
            )
            console.print("\n[bold]Schema validation report:[/bold]")
            console.print(result.schema_report.format_report())
        else:
            console.print(f"[bold red]x[/bold red] {result.error}")
        return 1

    # Success path
    console.print()
    console.print(
        f"[bold green]v[/bold green] Connected to profile: "
        f"[bold cyan]{result.profile_name}[/bold cyan]"
    )

    if result.schema_valid is True:
        console.print("  Schema validation: [green]PASSED[/green]")
        if result.schema_report and result.schema_report.extra_tables:
            console.print(
                f"  Extra tables: [yellow]"
                f"{', '.join(result.schema_report.extra_tables)}[/yellow]"
            )
    elif result.schema_valid is None:
        console.print(
            f"  Connected ({validation_skip_reason} "
            f"-- schema validation skipped)"
        )

    # Show table row counts (best-effort)
    if (
        config is not None
        and result.profile_name is not None
        and result.profile_name in config.profiles
    ):
        url = resolve_url(config.profiles[result.profile_name])
        counts = await _get_table_row_counts(url)
        if counts:
            console.print()
            _print_table_counts(counts)

    # Show profile switch notice
    if previous_profile and previous_profile != result.profile_name:
        console.print(
            f"\n[dim]Switched from[/dim] [bold]{previous_profile}[/bold] "
            f"[dim]to[/dim] [bold cyan]{result.profile_name}[/bold cyan]"
        )

    return 0


async def _async_validate(args: argparse.Namespace) -> int:
    """Async implementation for validate command.

    Loads expected columns from config (``schema_file`` field) or from
    the ``--schema-file`` CLI override.  Passes them to
    ``connect_and_validate()`` with ``validate_only=True`` so the
    ``.db-profile`` lock file is not overwritten.

    Args:
        args: Parsed arguments with env_prefix and optional schema_file.

    Returns:
        0 on valid schema, 1 on invalid or no profile.
    """
    env_prefix = getattr(args, "env_prefix", "")
    cli_schema_file: str | None = getattr(args, "schema_file", None)

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

    # Determine schema file source: CLI override takes precedence over config
    schema_file_path: str | None = None

    if cli_schema_file is not None:
        # CLI --schema-file provided: skip config loading
        schema_file_path = cli_schema_file
    else:
        # Attempt to load schema file from config
        try:
            config = load_db_config()
            schema_file_path = config.schema_file
        except Exception:
            # db.toml missing or malformed -- no schema source
            pass

    # If no schema source available, report and exit
    if schema_file_path is None:
        console.print(
            "\n[red]Error: No schema file available. "
            "Provide --schema-file or configure schema.file in db.toml[/red]"
        )
        return 1

    # Parse expected columns from the resolved schema file
    try:
        expected_columns = _parse_expected_columns(schema_file_path)
    except FileNotFoundError:
        console.print(
            f"\n[red]Error: Schema file not found: {schema_file_path}[/red]"
        )
        return 1
    except ValueError as e:
        console.print(f"\n[red]Error: {e}[/red]")
        return 1

    # Validate with expected_columns; validate_only=True prevents
    # overwriting the .db-profile lock file
    result = await connect_and_validate(
        profile_name=profile,
        expected_columns=expected_columns,
        env_prefix=env_prefix,
        validate_only=True,
    )

    # Check connection success first
    if not result.success:
        console.print()
        if result.schema_report:
            console.print(
                f"[bold red]x[/bold red] Connected to profile: "
                f"[bold cyan]{profile}[/bold cyan]"
            )
            console.print("\n[bold]Schema validation report:[/bold]")
            console.print(result.schema_report.format_report())
        else:
            console.print(f"[bold red]x[/bold red] {result.error}")
        return 1

    # Three-state schema_valid check
    if result.schema_valid is True:
        console.print()
        console.print("[bold green]v[/bold green] Schema is valid")
        if result.schema_report and result.schema_report.extra_tables:
            console.print(
                f"  Extra tables: [yellow]"
                f"{', '.join(result.schema_report.extra_tables)}[/yellow]"
            )
        return 0
    elif result.schema_valid is False:
        console.print()
        console.print("[bold red]x[/bold red] Schema has drifted")
        if result.schema_report:
            console.print(result.schema_report.format_report())
        return 1
    elif result.schema_valid is None:
        # Defensive handler: should not occur when expected_columns is
        # always passed, but handle gracefully
        console.print()
        console.print(
            "[yellow]Validation could not be performed[/yellow]"
        )
        return 1


async def _async_status(args: argparse.Namespace) -> int:
    """Async implementation of status command.

    Shows connection status from local files and queries the database
    for table row counts when the profile is available and reachable.

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

        config = None
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

        # Row counts (graceful degradation -- returns {} on failure)
        if (
            config is not None
            and profile in config.profiles
        ):
            url = resolve_url(config.profiles[profile])
            counts = await _get_table_row_counts(url)
            if counts:
                console.print()
                _print_table_counts(counts)
    else:
        console.print("[yellow]No validated profile.[/yellow]")
        console.print(
            "[dim]Run:[/dim] [cyan]DB_PROFILE=<name> db-adapter connect[/cyan]"
        )

    return 0


# ============================================================================
# Sync command wrappers
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
    """Show current connection status and table row counts.

    Reads local files (lock file and TOML config) for profile info, then
    queries the database for table row counts with graceful degradation.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 always (informational command).
    """
    return asyncio.run(_async_status(args))


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

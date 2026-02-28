"""Data sync between database profiles (async).

Provides functionality to compare and sync data between different database
profiles (e.g., RDS to local, Supabase to RDS).  All operations are async.

Sync is slug-based: records are matched by slug, not by ID.  Supports two
sync paths:

1. **Direct insert** (``schema=None``): Simple per-table select/insert with
   slug-based matching.  No FK remapping.  Best for flat tables.
2. **Backup/restore** (``schema`` provided): FK-aware sync via
   ``backup_database()``/``restore_database()`` with ID remapping.  Required
   when tables have parent-child FK relationships.

Usage:
    from db_adapter.schema.sync import compare_profiles, sync_data, SyncResult

    # Compare what would be synced
    result = await compare_profiles(
        "rds", "local",
        tables=["authors", "books"],
        user_id="user-1",
    )

    # Perform direct sync (dry run first)
    result = await sync_data(
        "rds", "local",
        tables=["authors", "books"],
        user_id="user-1",
        dry_run=True,
    )

    # FK-aware sync with BackupSchema
    from db_adapter.backup.models import BackupSchema, TableDef, ForeignKey
    schema = BackupSchema(tables=[
        TableDef(name="authors", pk="id"),
        TableDef(name="books", pk="id",
                 parent=ForeignKey(table="authors", field="author_id")),
    ])
    result = await sync_data(
        "rds", "local",
        tables=["authors", "books"],
        user_id="user-1",
        schema=schema,
        dry_run=False,
        confirm=True,
    )
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from db_adapter.adapters.base import DatabaseClient
from db_adapter.backup.models import BackupSchema


class SyncResult(BaseModel):
    """Result of sync comparison or operation.

    All dict fields use dynamic table names provided by the caller -- no
    hardcoded defaults.

    Attributes:
        success: Whether the operation completed successfully.
        source_profile: Name of source profile.
        dest_profile: Name of destination profile.
        source_counts: Record counts per table in source database.
        dest_counts: Record counts per table in destination database.
        sync_plan: Per-table plan with ``new`` and ``update`` counts.
        synced_count: Total records synced (inserted or updated).
        skipped_count: Total records skipped (already existed in dest).
        errors: List of error messages encountered during sync.
    """

    success: bool = False
    source_profile: str = ""
    dest_profile: str = ""
    source_counts: dict[str, int] = Field(default_factory=dict)
    dest_counts: dict[str, int] = Field(default_factory=dict)
    sync_plan: dict[str, dict[str, int]] = Field(default_factory=dict)
    synced_count: int = 0
    skipped_count: int = 0
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_data_counts(
    adapter: DatabaseClient,
    user_id: str,
    tables: list[str],
    user_field: str,
) -> dict[str, int]:
    """Get record counts from database for given tables.

    Args:
        adapter: Database adapter.
        user_id: User ID to filter by.
        tables: List of table names to count.
        user_field: Column name for user ownership filtering.

    Returns:
        Dict mapping table name to record count.
    """
    counts: dict[str, int] = {}
    for table in tables:
        rows = await adapter.select(
            table, "count(*) as cnt", filters={user_field: user_id}
        )
        counts[table] = rows[0]["cnt"] if rows else 0
    return counts


async def _get_slugs(
    adapter: DatabaseClient,
    user_id: str,
    tables: list[str],
    slug_field: str,
    user_field: str,
) -> dict[str, set[str]]:
    """Get all slugs from database using flat slug per table.

    Each table uses the same ``slug_field`` column name for matching.
    No hierarchical project_slug/slug composition -- just flat slugs.

    Args:
        adapter: Database adapter.
        user_id: User ID to filter by.
        tables: List of table names to query.
        slug_field: Column name for slug lookup.
        user_field: Column name for user ownership filtering.

    Returns:
        Dict mapping table name to set of slug values.

    Note:
        All tables passed must use the same ``slug_field`` column name.
        If different slug column names are needed, callers should invoke
        sync per-table group.
    """
    slugs: dict[str, set[str]] = {}
    for table in tables:
        rows = await adapter.select(
            table, slug_field, filters={user_field: user_id}
        )
        slugs[table] = {r[slug_field] for r in rows}
    return slugs


async def _create_adapter_for_profile(
    profile_name: str,
    env_prefix: str = "",
) -> DatabaseClient:
    """Create an ``AsyncPostgresAdapter`` for the given profile.

    Uses ``load_db_config()`` and ``resolve_url()`` to resolve the profile
    URL, then constructs an adapter.

    Args:
        profile_name: Profile name from db.toml.
        env_prefix: Prefix for environment variable lookup.

    Returns:
        An ``AsyncPostgresAdapter`` instance.

    Raises:
        KeyError: If the profile is not found in db.toml.
    """
    from db_adapter.adapters.postgres import AsyncPostgresAdapter
    from db_adapter.config.loader import load_db_config
    from db_adapter.factory import resolve_url

    config = load_db_config()
    if profile_name not in config.profiles:
        available = ", ".join(config.profiles.keys())
        raise KeyError(
            f"Profile '{profile_name}' not found in db.toml. "
            f"Available: {available}"
        )
    profile = config.profiles[profile_name]
    url = resolve_url(profile)
    return AsyncPostgresAdapter(database_url=url)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compare_profiles(
    source_profile: str,
    dest_profile: str,
    tables: list[str],
    user_id: str,
    user_field: str = "user_id",
    slug_field: str = "slug",
    env_prefix: str = "",
) -> SyncResult:
    """Compare data between two profiles.

    Compares by slug (not ID) to determine what would be synced.
    Records with same slug will be updated, new slugs will be inserted.

    ``env_prefix`` is forwarded to ``get_active_profile_name()`` when
    resolving the default profile for adapter creation (e.g.,
    ``env_prefix="MC_"`` reads ``MC_DB_PROFILE``).

    Args:
        source_profile: Source profile name from db.toml.
        dest_profile: Destination profile name from db.toml.
        tables: List of table names to compare.
        user_id: User ID to filter by.
        user_field: Column name for user ownership filtering.
            Defaults to ``"user_id"``.
        slug_field: Column name for slug-based matching.
            Defaults to ``"slug"``.
        env_prefix: Prefix for environment variable lookup.
            Defaults to ``""`` (reads ``DB_PROFILE``).

    Returns:
        ``SyncResult`` with counts and sync plan.

    Example:
        >>> result = await compare_profiles(
        ...     "rds", "local",
        ...     tables=["authors", "books"],
        ...     user_id="user-1",
        ... )
        >>> print(result.source_counts)
        {'authors': 5, 'books': 12}
    """
    result = SyncResult(
        source_profile=source_profile,
        dest_profile=dest_profile,
    )

    # Create adapters
    source_adapter: DatabaseClient | None = None
    dest_adapter: DatabaseClient | None = None

    try:
        source_adapter = await _create_adapter_for_profile(
            source_profile, env_prefix
        )
    except Exception as e:
        result.errors.append(
            f"Failed to connect to source profile '{source_profile}': {e}"
        )
        return result

    try:
        dest_adapter = await _create_adapter_for_profile(
            dest_profile, env_prefix
        )
    except Exception as e:
        await source_adapter.close()
        result.errors.append(
            f"Failed to connect to destination profile '{dest_profile}': {e}"
        )
        return result

    try:
        # Get counts
        result.source_counts = await _get_data_counts(
            source_adapter, user_id, tables, user_field
        )
        result.dest_counts = await _get_data_counts(
            dest_adapter, user_id, tables, user_field
        )

        # Get slugs for comparison
        source_slugs = await _get_slugs(
            source_adapter, user_id, tables, slug_field, user_field
        )
        dest_slugs = await _get_slugs(
            dest_adapter, user_id, tables, slug_field, user_field
        )

        # Calculate sync plan
        for table in tables:
            src = source_slugs.get(table, set())
            dst = dest_slugs.get(table, set())
            result.sync_plan[table] = {
                "new": len(src - dst),
                "update": len(src & dst),
            }

        result.success = True

    except Exception as e:
        result.errors.append(f"Failed to compare profiles: {e}")

    finally:
        await source_adapter.close()
        await dest_adapter.close()

    return result


async def sync_data(
    source_profile: str,
    dest_profile: str,
    tables: list[str],
    user_id: str,
    user_field: str = "user_id",
    slug_field: str = "slug",
    env_prefix: str = "",
    schema: BackupSchema | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> SyncResult:
    """Sync data from source profile to destination profile.

    **Dual-path sync**:

    - When ``schema`` is ``None`` (direct insert path): performs per-table
      ``select()``/``insert()`` with slug-based matching.  Rows whose slug
      already exists in the destination are skipped.  No FK remapping.

    - When ``schema`` is provided (backup/restore path): uses
      ``await backup_database()``/``await restore_database()`` via a temp
      file for FK-aware restore with ID remapping.

    Args:
        source_profile: Source profile name from db.toml.
        dest_profile: Destination profile name from db.toml.
        tables: List of table names to sync.
        user_id: User ID to filter by.
        user_field: Column name for user ownership filtering.
            Defaults to ``"user_id"``.
        slug_field: Column name for slug-based matching.
            Defaults to ``"slug"``.
        env_prefix: Prefix for environment variable lookup.
            Defaults to ``""`` (reads ``DB_PROFILE``).
        schema: Optional ``BackupSchema`` for FK-aware sync via
            backup/restore.  When ``None``, uses direct insert path.
        dry_run: If ``True``, only show what would be synced.
        confirm: Must be ``True`` to actually perform sync (safety check).

    Returns:
        ``SyncResult`` with sync outcome.

    Raises:
        ValueError: When a FK constraint violation occurs during direct
            insert (suggests providing a ``BackupSchema``).

    Example:
        >>> result = await sync_data(
        ...     "rds", "local",
        ...     tables=["authors", "books"],
        ...     user_id="user-1",
        ...     dry_run=False,
        ...     confirm=True,
        ... )
    """
    # First compare profiles
    result = await compare_profiles(
        source_profile,
        dest_profile,
        tables=tables,
        user_id=user_id,
        user_field=user_field,
        slug_field=slug_field,
        env_prefix=env_prefix,
    )
    if not result.success:
        return result

    # Dry run just returns comparison
    if dry_run:
        return result

    # Safety check
    if not confirm:
        result.errors.append(
            "Sync requires confirm=True to actually perform changes"
        )
        result.success = False
        return result

    if schema is not None:
        # Backup/restore path (FK-aware)
        await _sync_via_backup(result, source_profile, dest_profile,
                               user_id, schema, env_prefix)
    else:
        # Direct insert path (no FK remapping)
        await _sync_direct(result, source_profile, dest_profile, tables,
                           user_id, user_field, slug_field, env_prefix)

    return result


async def _sync_via_backup(
    result: SyncResult,
    source_profile: str,
    dest_profile: str,
    user_id: str,
    schema: BackupSchema,
    env_prefix: str,
) -> None:
    """Sync using backup/restore for FK-aware data transfer.

    Creates a temp backup from source, then restores to destination
    with ``mode="overwrite"`` for ID remapping.

    Args:
        result: ``SyncResult`` to update (mutated in place).
        source_profile: Source profile name.
        dest_profile: Destination profile name.
        user_id: User ID to filter by.
        schema: ``BackupSchema`` driving backup/restore.
        env_prefix: Prefix for environment variable lookup.
    """
    from db_adapter.backup.backup_restore import backup_database, restore_database

    source_adapter: DatabaseClient | None = None
    dest_adapter: DatabaseClient | None = None
    backup_path: str | None = None

    try:
        source_adapter = await _create_adapter_for_profile(
            source_profile, env_prefix
        )
        dest_adapter = await _create_adapter_for_profile(
            dest_profile, env_prefix
        )

        # Create temp backup file
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            backup_path = f.name

        # Backup from source
        await backup_database(
            source_adapter, schema, user_id=user_id,
            output_path=backup_path,
        )

        # Restore to destination
        summary: dict[str, Any] = await restore_database(
            dest_adapter, schema, backup_path, user_id=user_id,
            mode="overwrite",
        )

        # Count synced/skipped from summary
        for table_def in schema.tables:
            table_summary = summary.get(table_def.name, {})
            result.synced_count += table_summary.get("inserted", 0)
            result.synced_count += table_summary.get("updated", 0)
            result.skipped_count += table_summary.get("skipped", 0)

        result.success = True

    except Exception as e:
        result.success = False
        result.errors.append(f"Sync via backup/restore failed: {e}")

    finally:
        if source_adapter is not None:
            await source_adapter.close()
        if dest_adapter is not None:
            await dest_adapter.close()
        # Cleanup temp file
        if backup_path is not None:
            Path(backup_path).unlink(missing_ok=True)


async def _sync_direct(
    result: SyncResult,
    source_profile: str,
    dest_profile: str,
    tables: list[str],
    user_id: str,
    user_field: str,
    slug_field: str,
    env_prefix: str,
) -> None:
    """Sync using direct select/insert per table.

    For each table, selects all rows from source matching ``user_id``,
    checks which slugs exist in destination, and inserts rows whose slug
    does not exist.  Existing slugs are skipped (not updated).

    No FK remapping is performed.  If a FK constraint violation occurs,
    raises ``ValueError`` suggesting the caller provide a ``BackupSchema``.

    Args:
        result: ``SyncResult`` to update (mutated in place).
        source_profile: Source profile name.
        dest_profile: Destination profile name.
        tables: List of table names to sync.
        user_id: User ID to filter by.
        user_field: Column name for user ownership filtering.
        slug_field: Column name for slug-based matching.
        env_prefix: Prefix for environment variable lookup.
    """
    source_adapter: DatabaseClient | None = None
    dest_adapter: DatabaseClient | None = None

    try:
        source_adapter = await _create_adapter_for_profile(
            source_profile, env_prefix
        )
        dest_adapter = await _create_adapter_for_profile(
            dest_profile, env_prefix
        )

        for table in tables:
            # Get all rows from source
            source_rows = await source_adapter.select(
                table, "*", filters={user_field: user_id}
            )

            # Get existing slugs in destination
            dest_slug_rows = await dest_adapter.select(
                table, slug_field, filters={user_field: user_id}
            )
            dest_slugs = {r[slug_field] for r in dest_slug_rows}

            # Insert rows whose slug does not exist in dest
            for row in source_rows:
                row_slug = row.get(slug_field)
                if row_slug in dest_slugs:
                    result.skipped_count += 1
                    continue

                try:
                    await dest_adapter.insert(table, data=row)
                    result.synced_count += 1
                except Exception as e:
                    err_type = type(e).__name__
                    if "ForeignKey" in err_type:
                        raise ValueError(
                            f"FK constraint violation inserting into "
                            f"'{table}': {e}. Consider providing a "
                            f"BackupSchema for FK-aware sync."
                        ) from e
                    raise

        result.success = True

    except ValueError:
        # Re-raise ValueError (FK suggestion) without wrapping
        result.success = False
        raise
    except Exception as e:
        result.success = False
        result.errors.append(f"Direct sync failed: {e}")

    finally:
        if source_adapter is not None:
            await source_adapter.close()
        if dest_adapter is not None:
            await dest_adapter.close()

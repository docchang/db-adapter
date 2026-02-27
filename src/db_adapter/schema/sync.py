"""Data sync between database profiles.

Provides functionality to compare and sync data between different database
profiles (e.g., RDS to local, Supabase to RDS).

Uses existing backup/restore infrastructure for cross-profile data migration.
Sync is slug-based: records are matched by slug, not by ID.

Usage:
    from schema.sync import compare_profiles, sync_data, SyncResult

    # Compare what would be synced
    result = compare_profiles("rds", "local")
    print(f"Source projects: {result.source_counts['projects']}")

    # Perform sync (dry run first)
    result = sync_data("rds", "local", dry_run=True)

    # Actually sync
    result = sync_data("rds", "local", dry_run=False, confirm=True)
"""

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

# Avoid circular imports - these are imported at runtime in functions
if TYPE_CHECKING:
    from adapters import PostgresAdapter
    from schema.models import DatabaseProfile


class SyncResult(BaseModel):
    """Result of sync comparison or operation.

    Attributes:
        success: Whether the operation completed successfully
        source_profile: Name of source profile
        dest_profile: Name of destination profile
        source_counts: Record counts in source database
        dest_counts: Record counts in destination database
        sync_plan: What would be synced (new vs update)
        error: Error message if operation failed
    """

    success: bool = False
    source_profile: str = ""
    dest_profile: str = ""
    source_counts: dict[str, int] = Field(
        default_factory=lambda: {"projects": 0, "milestones": 0, "tasks": 0}
    )
    dest_counts: dict[str, int] = Field(
        default_factory=lambda: {"projects": 0, "milestones": 0, "tasks": 0}
    )
    sync_plan: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {
            "projects": {"new": 0, "update": 0},
            "milestones": {"new": 0, "update": 0},
            "tasks": {"new": 0, "update": 0},
        }
    )
    error: str | None = None


def _get_data_counts(adapter: "PostgresAdapter", user_id: str) -> dict[str, int]:
    """Get record counts from database.

    Args:
        adapter: Database adapter
        user_id: User ID to filter by

    Returns:
        Dict mapping table name to record count
    """
    counts = {}
    for table in ["projects", "milestones", "tasks"]:
        result = adapter.select(table, "count(*) as cnt", filters={"user_id": user_id})
        counts[table] = result[0]["cnt"] if result else 0

    return counts


def _get_slugs(adapter: "PostgresAdapter", user_id: str) -> dict[str, set[str]]:
    """Get all slugs from database.

    For milestones and tasks, returns "project_slug/slug" format for uniqueness.

    Args:
        adapter: Database adapter
        user_id: User ID to filter by

    Returns:
        Dict mapping table name to set of slugs
    """
    slugs: dict[str, set[str]] = {}

    # Projects - simple slugs
    projects = adapter.select("projects", "slug", filters={"user_id": user_id})
    slugs["projects"] = {p["slug"] for p in projects}

    # Build project_id -> slug mapping for milestones/tasks
    all_projects = adapter.select("projects", "id, slug", filters={"user_id": user_id})
    project_id_to_slug = {p["id"]: p["slug"] for p in all_projects}

    # Milestones - need to include project slug for uniqueness
    milestones = adapter.select(
        "milestones", "project_id, slug", filters={"user_id": user_id}
    )
    slugs["milestones"] = set()
    for m in milestones:
        project_slug = project_id_to_slug.get(m["project_id"], "unknown")
        slugs["milestones"].add(f"{project_slug}/{m['slug']}")

    # Tasks - need to include project slug for uniqueness
    tasks = adapter.select("tasks", "project_id, slug", filters={"user_id": user_id})
    slugs["tasks"] = set()
    for t in tasks:
        project_slug = project_id_to_slug.get(t["project_id"], "unknown")
        slugs["tasks"].add(f"{project_slug}/{t['slug']}")

    return slugs


def compare_profiles(source_profile: str, dest_profile: str) -> SyncResult:
    """Compare data between two profiles.

    Compares by slug (not ID) to determine what would be synced.
    Records with same slug will be updated, new slugs will be inserted.

    Args:
        source_profile: Source profile name from db.toml
        dest_profile: Destination profile name from db.toml

    Returns:
        SyncResult with counts and sync plan
    """
    # Import at runtime to avoid circular imports
    from adapters import PostgresAdapter
    from config import load_db_config
    from db import _resolve_url, get_dev_user_id

    result = SyncResult(source_profile=source_profile, dest_profile=dest_profile)

    # Load config
    try:
        config = load_db_config()
    except FileNotFoundError as e:
        result.error = str(e)
        return result

    # Validate profiles exist
    if source_profile not in config.profiles:
        result.error = f"Source profile '{source_profile}' not found. Available: {', '.join(config.profiles.keys())}"
        return result
    if dest_profile not in config.profiles:
        result.error = f"Destination profile '{dest_profile}' not found. Available: {', '.join(config.profiles.keys())}"
        return result

    user_id = get_dev_user_id()

    # Connect to source
    try:
        source_url = _resolve_url(config.profiles[source_profile])
        source_adapter = PostgresAdapter(database_url=source_url)
    except Exception as e:
        result.error = f"Failed to connect to source profile '{source_profile}': {e}"
        return result

    # Connect to destination
    try:
        dest_url = _resolve_url(config.profiles[dest_profile])
        dest_adapter = PostgresAdapter(database_url=dest_url)
    except Exception as e:
        source_adapter.close()
        result.error = f"Failed to connect to destination profile '{dest_profile}': {e}"
        return result

    try:
        # Get counts
        result.source_counts = _get_data_counts(source_adapter, user_id)
        result.dest_counts = _get_data_counts(dest_adapter, user_id)

        # Get slugs for comparison
        source_slugs = _get_slugs(source_adapter, user_id)
        dest_slugs = _get_slugs(dest_adapter, user_id)

        # Calculate sync plan (what would be transferred)
        for table in ["projects", "milestones", "tasks"]:
            src = source_slugs[table]
            dst = dest_slugs[table]
            result.sync_plan[table] = {
                "new": len(src - dst),  # In source but not in dest
                "update": len(src & dst),  # In both (would be updated)
            }

        result.success = True

    except Exception as e:
        result.error = f"Failed to compare profiles: {e}"

    finally:
        source_adapter.close()
        dest_adapter.close()

    return result


def sync_data(
    source_profile: str,
    dest_profile: str,
    dry_run: bool = True,
    confirm: bool = False,
) -> SyncResult:
    """Sync data from source profile to destination profile.

    Uses backup/restore infrastructure via subprocess:
    1. Backup from source profile
    2. Restore to destination profile with mode="overwrite"

    Records are matched by slug. Source data takes precedence on collision.

    Args:
        source_profile: Source profile name from db.toml
        dest_profile: Destination profile name from db.toml
        dry_run: If True, only show what would be synced without making changes
        confirm: Must be True to actually perform sync (safety check)

    Returns:
        SyncResult with sync outcome
    """
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    # First compare profiles
    result = compare_profiles(source_profile, dest_profile)
    if not result.success:
        return result

    # Dry run just returns comparison
    if dry_run:
        return result

    # Safety check - require explicit confirmation for actual sync
    if not confirm:
        result.error = "Sync requires --confirm flag to actually perform changes"
        result.success = False
        return result

    # Get core directory for subprocess cwd
    core_dir = Path(__file__).parent.parent

    try:
        # Create temp backup file
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            backup_path = f.name

        # Step 1: Backup from source profile using subprocess
        env = dict(os.environ)
        env["MC_DB_PROFILE"] = source_profile
        backup_result = subprocess.run(
            ["uv", "run", "python", "backup/backup_cli.py", "backup", "--output", backup_path],
            cwd=core_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        if backup_result.returncode != 0:
            result.success = False
            result.error = f"Backup from {source_profile} failed: {backup_result.stderr}"
            return result

        # Step 2: Restore to destination profile using subprocess
        env["MC_DB_PROFILE"] = dest_profile
        restore_result = subprocess.run(
            ["uv", "run", "python", "backup/backup_cli.py", "restore", backup_path, "--mode", "overwrite", "--yes"],
            cwd=core_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        if restore_result.returncode != 0:
            result.success = False
            result.error = f"Restore to {dest_profile} failed: {restore_result.stderr}"
            return result

        # Cleanup temp file
        Path(backup_path).unlink(missing_ok=True)

        result.success = True

    except Exception as e:
        result.success = False
        result.error = f"Sync failed: {e}"

    return result

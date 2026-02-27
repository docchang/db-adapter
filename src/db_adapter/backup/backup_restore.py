"""Backup and restore Mission Control data to/from JSON.

This module provides database-agnostic backup and restore functionality
for Mission Control. Backups are stored as JSON files that can be easily
migrated between Supabase and PostgreSQL databases.

Usage:
    from backup_restore import backup_database, restore_database

    # Backup entire database
    backup_path = backup_database()

    # Restore from backup
    summary = restore_database(backup_path)
"""

from datetime import datetime
from pathlib import Path
import json
from typing import Optional, Literal

from adapters import DatabaseClient
from db import get_db_adapter, get_dev_user_id
from config import get_settings


def backup_database(
    output_path: Optional[str] = None,
    project_slugs: Optional[list[str]] = None,
) -> str:
    """
    Export database to JSON backup file.

    Args:
        output_path: Path to save backup (default: backup/backups/backup-{timestamp}.json)
        project_slugs: Only backup specific projects (default: all projects)

    Returns:
        Path to created backup file

    Example:
        # Backup everything
        path = backup_database()

        # Backup specific project
        path = backup_database(project_slugs=["mission-control"])
    """
    adapter: DatabaseClient = get_db_adapter()
    user_id = get_dev_user_id()
    settings = get_settings()

    # Generate output path if not provided
    if output_path is None:
        # Use path relative to backup module, not current working directory
        backups_dir = Path(__file__).parent / "backups"
        backups_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        output_path = str(backups_dir / f"backup-{timestamp}.json")

    # Prepare backup data structure
    backup_data = {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "db_provider": settings.db_provider,
            "user_id": user_id,
            "backup_type": "selective" if project_slugs else "full",
            "version": "1.1",
            "project_count": 0,
            "milestone_count": 0,
            "task_count": 0,
        },
        "projects": [],
        "milestones": [],
        "tasks": [],
    }

    # Export projects
    if project_slugs:
        # Selective backup - only specified projects
        for slug in project_slugs:
            result = adapter.select(
                "projects",
                columns="*",
                filters={"user_id": user_id, "slug": slug}
            )
            if result:
                backup_data["projects"].append(result[0])
    else:
        # Full backup - all projects for this user
        result = adapter.select(
            "projects",
            columns="*",
            filters={"user_id": user_id}
        )
        backup_data["projects"] = result

    backup_data["metadata"]["project_count"] = len(backup_data["projects"])

    # Collect project IDs for milestone and task filtering
    project_ids = [p["id"] for p in backup_data["projects"]]

    if project_ids:
        # Export milestones for these projects
        all_milestones = adapter.select(
            "milestones",
            columns="*",
            filters={"user_id": user_id}
        )
        backup_data["milestones"] = [
            m for m in all_milestones if m["project_id"] in project_ids
        ]
        backup_data["metadata"]["milestone_count"] = len(backup_data["milestones"])

        # Export tasks for these projects
        # Note: Can't use IN filter directly with adapter, so fetch all and filter
        all_tasks = adapter.select(
            "tasks",
            columns="*",
            filters={"user_id": user_id}
        )
        backup_data["tasks"] = [
            t for t in all_tasks if t["project_id"] in project_ids
        ]
        backup_data["metadata"]["task_count"] = len(backup_data["tasks"])

    # Write to JSON file
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(backup_data, f, indent=2, default=str)  # default=str handles datetime

    print(f"✅ Backup created: {output_path}")
    print(f"   Projects: {backup_data['metadata']['project_count']}")
    print(f"   Milestones: {backup_data['metadata']['milestone_count']}")
    print(f"   Tasks: {backup_data['metadata']['task_count']}")

    return output_path


def restore_database(
    backup_path: str,
    mode: Literal["skip", "overwrite", "fail"] = "skip",
    dry_run: bool = False,
) -> dict:
    """
    Restore database from JSON backup file.

    Args:
        backup_path: Path to backup JSON file
        mode: How to handle existing records:
              - "skip": Skip existing records (default, safest)
              - "overwrite": Update existing records with backup data
              - "fail": Abort if any record exists
        dry_run: Preview changes without applying them

    Returns:
        Summary dict with counts of inserted/skipped/updated records

    Example:
        # Restore with skip mode (safe)
        summary = restore_database("backup/backups/backup-2025-12-30.json")

        # Preview what would be restored
        summary = restore_database("backup/backups/backup.json", dry_run=True)

        # Restore with overwrite (replaces existing)
        summary = restore_database("backup/backups/backup.json", mode="overwrite")
    """
    adapter: DatabaseClient = get_db_adapter()
    user_id = get_dev_user_id()
    settings = get_settings()

    # Load backup file
    with open(backup_path, 'r') as f:
        backup_data = json.load(f)

    # Validate backup format
    validation = validate_backup(backup_path)
    if validation["errors"]:
        print("❌ Backup validation failed:")
        for error in validation["errors"]:
            print(f"   - {error}")
        raise ValueError("Invalid backup file")

    if validation["warnings"]:
        print("⚠️  Backup validation warnings:")
        for warning in validation["warnings"]:
            print(f"   - {warning}")

    # Check user_id compatibility
    backup_user_id = backup_data["metadata"]["user_id"]
    if backup_user_id != user_id:
        print(f"⚠️  Warning: Backup user_id ({backup_user_id}) differs from current user_id ({user_id})")
        print(f"   Records will be restored with current user_id: {user_id}")

    # Initialize summary
    summary = {
        "projects": {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0},
        "milestones": {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0},
        "tasks": {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0},
        "dry_run": dry_run,
    }

    if dry_run:
        print(f"🔍 DRY RUN - No changes will be made")
    else:
        print(f"📦 Restoring from: {backup_path}")
        print(f"   Mode: {mode}")
        print(f"   Provider: {backup_data['metadata']['db_provider']} → {settings.db_provider}")

    # Track ID mappings for foreign key updates
    project_id_map = {}  # old_id -> new_id
    milestone_id_map = {}  # old_id -> new_id

    # Restore projects first (dependencies)
    for project in backup_data["projects"]:
        try:
            # Save original ID for mapping
            old_project_id = project["id"]

            # Override user_id with current user
            project["user_id"] = user_id

            # Check if project exists
            existing = adapter.select(
                "projects",
                columns="id",
                filters={"user_id": user_id, "slug": project["slug"]}
            )

            if existing:
                # Map old ID to existing ID
                project_id_map[old_project_id] = existing[0]["id"]

                if mode == "fail":
                    raise ValueError(f"Project {project['slug']} already exists (mode=fail)")
                elif mode == "skip":
                    summary["projects"]["skipped"] += 1
                    if dry_run:
                        print(f"   [SKIP] Project: {project['slug']}")
                    continue
                elif mode == "overwrite":
                    if not dry_run:
                        # Update existing project
                        project_id = existing[0]["id"]
                        update_data = {k: v for k, v in project.items() if k != "id"}
                        adapter.update("projects", data=update_data, filters={"id": project_id})
                    summary["projects"]["updated"] += 1
                    if dry_run:
                        print(f"   [UPDATE] Project: {project['slug']}")
            else:
                if not dry_run:
                    # Insert new project
                    result = adapter.insert("projects", data=project)
                    # Map old ID to new ID
                    new_project_id = result["id"]
                    project_id_map[old_project_id] = new_project_id
                else:
                    # In dry run, map to old ID (won't be used)
                    project_id_map[old_project_id] = old_project_id

                summary["projects"]["inserted"] += 1
                if dry_run:
                    print(f"   [INSERT] Project: {project['slug']}")

        except Exception as e:
            summary["projects"]["failed"] += 1
            print(f"   ❌ Failed to restore project {project.get('slug', 'unknown')}: {e}")

    # Restore milestones (depend on projects, tasks depend on milestones)
    for milestone in backup_data.get("milestones", []):
        try:
            # Save original ID for mapping
            old_milestone_id = milestone["id"]

            # Override user_id with current user
            milestone["user_id"] = user_id

            # Remap project_id using the mapping from restored projects
            old_project_id = milestone["project_id"]
            if old_project_id in project_id_map:
                milestone["project_id"] = project_id_map[old_project_id]
            else:
                # Project wasn't in backup or failed to restore
                print(f"   ⚠️  Skipping milestone {milestone['slug']}: parent project not in backup or failed to restore")
                summary["milestones"]["skipped"] += 1
                continue

            # Check if milestone exists
            existing = adapter.select(
                "milestones",
                columns="id",
                filters={
                    "project_id": milestone["project_id"],
                    "slug": milestone["slug"]
                }
            )

            if existing:
                # Map old ID to existing ID
                milestone_id_map[old_milestone_id] = existing[0]["id"]

                if mode == "fail":
                    raise ValueError(f"Milestone {milestone['slug']} already exists (mode=fail)")
                elif mode == "skip":
                    summary["milestones"]["skipped"] += 1
                    if dry_run:
                        print(f"   [SKIP] Milestone: {milestone['slug']}")
                    continue
                elif mode == "overwrite":
                    if not dry_run:
                        milestone_id = existing[0]["id"]
                        update_data = {k: v for k, v in milestone.items() if k != "id"}
                        adapter.update("milestones", data=update_data, filters={"id": milestone_id})
                    summary["milestones"]["updated"] += 1
                    if dry_run:
                        print(f"   [UPDATE] Milestone: {milestone['slug']}")
            else:
                if not dry_run:
                    # Insert new milestone
                    result = adapter.insert("milestones", data=milestone)
                    # Map old ID to new ID
                    new_milestone_id = result["id"]
                    milestone_id_map[old_milestone_id] = new_milestone_id
                else:
                    # In dry run, map to old ID (won't be used)
                    milestone_id_map[old_milestone_id] = old_milestone_id

                summary["milestones"]["inserted"] += 1
                if dry_run:
                    print(f"   [INSERT] Milestone: {milestone['slug']}")

        except Exception as e:
            summary["milestones"]["failed"] += 1
            print(f"   ❌ Failed to restore milestone {milestone.get('slug', 'unknown')}: {e}")

    # Restore tasks (depend on projects and milestones)
    for task in backup_data.get("tasks", []):
        try:
            # Override user_id with current user
            task["user_id"] = user_id

            # Remap project_id using the mapping from restored projects
            old_project_id = task["project_id"]
            if old_project_id in project_id_map:
                task["project_id"] = project_id_map[old_project_id]
            else:
                # Project wasn't in backup or failed to restore
                print(f"   ⚠️  Skipping task {task['slug']}: parent project not in backup or failed to restore")
                summary["tasks"]["skipped"] += 1
                continue

            # Remap milestone_id if present
            if task.get("milestone_id"):
                old_milestone_id = task["milestone_id"]
                if old_milestone_id in milestone_id_map:
                    task["milestone_id"] = milestone_id_map[old_milestone_id]
                else:
                    # Milestone wasn't in backup or failed to restore - set to null
                    task["milestone_id"] = None

            # Verify parent project exists (should exist if mapping worked)
            if not dry_run:
                project_exists = adapter.select(
                    "projects",
                    columns="id",
                    filters={"id": task["project_id"]}
                )
                if not project_exists:
                    print(f"   ⚠️  Skipping task {task['slug']}: parent project not found")
                    summary["tasks"]["skipped"] += 1
                    continue

            # Check if task exists
            existing = adapter.select(
                "tasks",
                columns="id",
                filters={
                    "user_id": user_id,
                    "project_id": task["project_id"],
                    "slug": task["slug"]
                }
            )

            if existing:
                if mode == "fail":
                    raise ValueError(f"Task {task['slug']} already exists (mode=fail)")
                elif mode == "skip":
                    summary["tasks"]["skipped"] += 1
                    if dry_run:
                        print(f"   [SKIP] Task: {task['slug']}")
                    continue
                elif mode == "overwrite":
                    if not dry_run:
                        task_id = existing[0]["id"]
                        update_data = {k: v for k, v in task.items() if k != "id"}
                        adapter.update("tasks", data=update_data, filters={"id": task_id})
                    summary["tasks"]["updated"] += 1
                    if dry_run:
                        print(f"   [UPDATE] Task: {task['slug']}")
            else:
                if not dry_run:
                    adapter.insert("tasks", data=task)
                summary["tasks"]["inserted"] += 1
                if dry_run:
                    print(f"   [INSERT] Task: {task['slug']}")

        except Exception as e:
            summary["tasks"]["failed"] += 1
            print(f"   ❌ Failed to restore task {task.get('slug', 'unknown')}: {e}")

    # Print summary
    if dry_run:
        print(f"\n🔍 DRY RUN SUMMARY:")
    else:
        print(f"\n✅ RESTORE COMPLETE:")

    for table, counts in summary.items():
        if table == "dry_run":
            continue
        print(f"   {table}:")
        if counts["inserted"]:
            print(f"      Inserted: {counts['inserted']}")
        if counts["updated"]:
            print(f"      Updated: {counts['updated']}")
        if counts["skipped"]:
            print(f"      Skipped: {counts['skipped']}")
        if counts["failed"]:
            print(f"      Failed: {counts['failed']}")

    return summary


def validate_backup(backup_path: str) -> dict:
    """
    Validate backup file format and data integrity.

    Args:
        backup_path: Path to backup JSON file

    Returns:
        Validation report with warnings/errors

    Example:
        validation = validate_backup("backup/backups/backup.json")
        if validation["errors"]:
            print("Backup is invalid")
        if validation["warnings"]:
            print("Backup has warnings but is usable")
    """
    errors = []
    warnings = []

    try:
        with open(backup_path, 'r') as f:
            backup_data = json.load(f)
    except FileNotFoundError:
        errors.append(f"Backup file not found: {backup_path}")
        return {"valid": False, "errors": errors, "warnings": warnings}
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Check required top-level keys
    required_keys = ["metadata", "projects", "tasks"]
    for key in required_keys:
        if key not in backup_data:
            errors.append(f"Missing required key: {key}")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Check metadata
    metadata = backup_data["metadata"]
    required_metadata = ["created_at", "db_provider", "user_id", "backup_type", "version"]
    for key in required_metadata:
        if key not in metadata:
            warnings.append(f"Missing metadata field: {key}")

    # Validate version
    if metadata.get("version") != "1.0":
        warnings.append(f"Backup version {metadata.get('version')} may not be compatible (expected 1.0)")

    # Check project UUIDs
    project_ids = set()
    for project in backup_data["projects"]:
        if "id" not in project:
            errors.append(f"Project missing 'id' field: {project.get('slug', 'unknown')}")
        elif not project["id"]:
            errors.append(f"Project has empty 'id': {project.get('slug', 'unknown')}")
        else:
            project_ids.add(project["id"])

        if "slug" not in project:
            errors.append(f"Project missing 'slug' field")

    # Check task references
    for task in backup_data["tasks"]:
        if "project_id" not in task:
            errors.append(f"Task missing 'project_id': {task.get('slug', 'unknown')}")
        elif task["project_id"] not in project_ids:
            warnings.append(f"Orphaned task {task.get('slug')}: project_id not in backup")

    valid = len(errors) == 0
    return {"valid": valid, "errors": errors, "warnings": warnings}

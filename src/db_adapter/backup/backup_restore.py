"""Generic backup and restore driven by BackupSchema.

This module provides database-agnostic backup and restore functionality.
Backups are stored as JSON files. The table structure, FK relationships,
and ID remapping are all driven by a caller-provided ``BackupSchema``
model -- no hardcoded table names.

Usage:
    from db_adapter.backup.backup_restore import (
        backup_database,
        restore_database,
        validate_backup,
    )
    from db_adapter.backup.models import BackupSchema, TableDef, ForeignKey

    schema = BackupSchema(tables=[
        TableDef(name="authors", pk="id", slug_field="slug", user_field="user_id"),
        TableDef(
            name="books",
            pk="id",
            slug_field="slug",
            user_field="user_id",
            parent=ForeignKey(table="authors", field="author_id"),
        ),
    ])

    # Backup
    path = await backup_database(adapter, schema, user_id="u1")

    # Restore
    summary = await restore_database(adapter, schema, path, user_id="u1")

    # Validate (sync -- local file read only)
    report = validate_backup(path, schema)
"""

from datetime import datetime
from pathlib import Path
import json
from typing import Any, Literal

from db_adapter.adapters.base import DatabaseClient
from db_adapter.backup.models import BackupSchema, TableDef


async def backup_database(
    adapter: DatabaseClient,
    schema: BackupSchema,
    user_id: str,
    output_path: str | None = None,
    table_filters: dict[str, dict] | None = None,
    metadata: dict | None = None,
) -> str:
    """Export database rows to a JSON backup file.

    Iterates ``schema.tables`` in order (parents before children).
    For each table, selects all rows matching the ``user_id`` and any
    additional per-table filters from ``table_filters``.  Child tables
    are filtered by their parent's PK values collected during backup.

    Args:
        adapter: Database adapter implementing ``DatabaseClient`` Protocol.
        schema: Declarative backup schema describing tables and FK relationships.
        user_id: User ID to filter rows by (uses each table's ``user_field``).
        output_path: Path to save backup file.  When ``None``, generates a
            timestamped path under ``./backups/``.
        table_filters: Optional per-table extra WHERE filters.  Keys are
            table names, values are dicts of ``{column: value}`` pairs.
            Example: ``{"orders": {"status": "active"}}``.
        metadata: Optional extra metadata merged into the backup's
            ``metadata`` section.

    Returns:
        Absolute path to the created backup file.

    Example:
        path = await backup_database(
            adapter,
            schema,
            user_id="user-1",
            table_filters={"orders": {"status": "active"}},
            metadata={"environment": "staging"},
        )
    """
    table_filters = table_filters or {}

    # Generate output path if not provided
    if output_path is None:
        backups_dir = Path.cwd() / "backups"
        backups_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        output_path = str(backups_dir / f"backup-{timestamp}.json")

    # Prepare backup data structure
    backup_data: dict[str, Any] = {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "user_id": user_id,
            "backup_type": "full",
            "version": "1.1",
        },
    }

    # Merge caller-provided metadata
    if metadata:
        backup_data["metadata"].update(metadata)

    # Track PK values per table for child-table filtering
    pk_values: dict[str, set] = {}

    # Iterate tables in schema order (parents first)
    for table_def in schema.tables:
        filters: dict[str, Any] = {table_def.user_field: user_id}

        # Merge per-table filters from caller
        if table_def.name in table_filters:
            filters.update(table_filters[table_def.name])

        rows = await adapter.select(table_def.name, columns="*", filters=filters)

        # If this table has a parent FK, filter rows by parent PKs
        if table_def.parent is not None:
            parent_table = table_def.parent.table
            parent_field = table_def.parent.field
            parent_pks = pk_values.get(parent_table, set())
            rows = [
                r for r in rows
                if r.get(parent_field) in parent_pks
            ]

        # Collect PK values for this table (children will use them)
        pk_values[table_def.name] = {r[table_def.pk] for r in rows}

        # Store rows and count in backup
        backup_data[table_def.name] = rows
        backup_data["metadata"][f"{table_def.name}_count"] = len(rows)

    # Write to JSON file
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(backup_data, f, indent=2, default=str)

    return output_path


async def restore_database(
    adapter: DatabaseClient,
    schema: BackupSchema,
    backup_path: str,
    user_id: str,
    mode: Literal["skip", "overwrite", "fail"] = "skip",
    dry_run: bool = False,
) -> dict:
    """Restore database rows from a JSON backup file.

    Iterates ``schema.tables`` in order (parents before children).
    For each table, restores rows with FK remapping: parent PKs are
    mapped from old (backup) IDs to new (database) IDs using ``id_maps``.
    Optional refs are nulled out if the referenced row is not found.

    Args:
        adapter: Database adapter implementing ``DatabaseClient`` Protocol.
        schema: Declarative backup schema describing tables and FK relationships.
        backup_path: Path to backup JSON file.
        user_id: User ID to assign to restored rows (overrides backup user_id).
        mode: How to handle existing records:
            - ``"skip"``: Skip existing records (default, safest).
            - ``"overwrite"``: Update existing records with backup data.
            - ``"fail"``: Raise ``ValueError`` if any record already exists.
        dry_run: When ``True``, preview changes without writing to the database.

    Returns:
        Summary dict with per-table counts of inserted/updated/skipped/failed
        records, plus a ``dry_run`` flag.

    Raises:
        ValueError: If the backup file fails validation.

    Example:
        summary = await restore_database(
            adapter,
            schema,
            "backups/backup-2026-01-15.json",
            user_id="user-1",
            mode="skip",
        )
    """
    # Load backup file
    with open(backup_path, "r") as f:
        backup_data = json.load(f)

    # Validate backup format
    validation = validate_backup(backup_path, schema)
    if validation["errors"]:
        raise ValueError(
            f"Invalid backup file: {'; '.join(validation['errors'])}"
        )

    # Initialize summary with dynamic table names
    summary: dict[str, Any] = {"dry_run": dry_run}
    for table_def in schema.tables:
        summary[table_def.name] = {
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
        }

    # Generic ID maps: table_name -> {old_pk: new_pk}
    id_maps: dict[str, dict] = {}
    for table_def in schema.tables:
        id_maps[table_def.name] = {}

    # Restore tables in schema order (parents first)
    for table_def in schema.tables:
        rows = backup_data.get(table_def.name, [])
        await _restore_table(
            adapter=adapter,
            table_def=table_def,
            rows=rows,
            user_id=user_id,
            mode=mode,
            dry_run=dry_run,
            id_maps=id_maps,
            summary=summary,
        )

    return summary


async def _restore_table(
    adapter: DatabaseClient,
    table_def: TableDef,
    rows: list[dict],
    user_id: str,
    mode: Literal["skip", "overwrite", "fail"],
    dry_run: bool,
    id_maps: dict[str, dict],
    summary: dict[str, Any],
) -> None:
    """Restore rows for a single table with FK remapping.

    Args:
        adapter: Database adapter.
        table_def: Table definition from BackupSchema.
        rows: List of row dicts from the backup file.
        user_id: User ID to assign to restored rows.
        mode: Conflict handling mode.
        dry_run: Whether to skip actual database writes.
        id_maps: Shared ID maps for FK remapping (mutated in place).
        summary: Shared summary dict (mutated in place).
    """
    table_name = table_def.name
    table_summary = summary[table_name]

    for row in rows:
        try:
            # Save original PK for mapping
            old_pk = row[table_def.pk]

            # Override user_id with current user
            if table_def.user_field:
                row[table_def.user_field] = user_id

            # Remap parent FK (required -- skip row if parent missing)
            if table_def.parent is not None:
                parent_table = table_def.parent.table
                parent_field = table_def.parent.field
                old_parent_id = row.get(parent_field)
                if old_parent_id is not None and old_parent_id in id_maps.get(parent_table, {}):
                    row[parent_field] = id_maps[parent_table][old_parent_id]
                elif old_parent_id is not None:
                    # Parent not found in id_maps -- skip this row
                    table_summary["skipped"] += 1
                    continue

            # Remap optional refs (null out if ref not found)
            for ref in table_def.optional_refs:
                ref_field = ref.field
                ref_table = ref.table
                old_ref_id = row.get(ref_field)
                if old_ref_id is not None:
                    if old_ref_id in id_maps.get(ref_table, {}):
                        row[ref_field] = id_maps[ref_table][old_ref_id]
                    else:
                        row[ref_field] = None

            # Build existence-check filters using slug + user or slug + parent
            existence_filters: dict[str, Any] = {}
            if table_def.slug_field and table_def.slug_field in row:
                existence_filters[table_def.slug_field] = row[table_def.slug_field]
            if table_def.user_field and table_def.user_field in row:
                existence_filters[table_def.user_field] = row[table_def.user_field]
            # If there is a parent FK, include it in the existence check
            if table_def.parent is not None:
                parent_field = table_def.parent.field
                if parent_field in row and row[parent_field] is not None:
                    existence_filters[parent_field] = row[parent_field]

            # Check if record exists
            existing = await adapter.select(
                table_name,
                columns=table_def.pk,
                filters=existence_filters,
            )

            if existing:
                # Map old PK to existing PK
                id_maps[table_name][old_pk] = existing[0][table_def.pk]

                if mode == "fail":
                    slug_val = row.get(table_def.slug_field, "unknown")
                    raise ValueError(
                        f"{table_name} '{slug_val}' already exists (mode=fail)"
                    )
                elif mode == "skip":
                    table_summary["skipped"] += 1
                    continue
                elif mode == "overwrite":
                    if not dry_run:
                        existing_pk = existing[0][table_def.pk]
                        update_data = {
                            k: v for k, v in row.items() if k != table_def.pk
                        }
                        await adapter.update(
                            table_name,
                            data=update_data,
                            filters={table_def.pk: existing_pk},
                        )
                    table_summary["updated"] += 1
            else:
                if not dry_run:
                    result = await adapter.insert(table_name, data=row)
                    new_pk = result[table_def.pk]
                    id_maps[table_name][old_pk] = new_pk
                else:
                    # In dry run, map to old PK (won't be used for DB ops)
                    id_maps[table_name][old_pk] = old_pk

                table_summary["inserted"] += 1

        except ValueError:
            # Re-raise ValueError (mode=fail) without catching
            raise
        except Exception:
            table_summary["failed"] += 1


def validate_backup(backup_path: str, schema: BackupSchema) -> dict:
    """Validate backup file format and data integrity.

    Checks that the backup JSON file is well-formed, has the required
    metadata fields, uses version ``"1.1"``, and contains data keys
    matching the table names in the provided ``schema``.

    This function is **sync** -- it only reads a local JSON file with
    no database I/O.

    Args:
        backup_path: Path to backup JSON file.
        schema: Declarative backup schema to validate against.

    Returns:
        Dict with ``valid`` (bool), ``errors`` (list[str]),
        and ``warnings`` (list[str]).

    Example:
        report = validate_backup("backups/backup.json", schema)
        if report["errors"]:
            raise ValueError("Backup is invalid")
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        with open(backup_path, "r") as f:
            backup_data = json.load(f)
    except FileNotFoundError:
        errors.append(f"Backup file not found: {backup_path}")
        return {"valid": False, "errors": errors, "warnings": warnings}
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Check required top-level keys: metadata + all schema table names
    schema_table_names = [t.name for t in schema.tables]
    required_keys = ["metadata"] + schema_table_names
    for key in required_keys:
        if key not in backup_data:
            errors.append(f"Missing required key: {key}")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Check metadata
    metadata = backup_data["metadata"]
    required_metadata = ["created_at", "user_id", "backup_type", "version"]
    for key in required_metadata:
        if key not in metadata:
            warnings.append(f"Missing metadata field: {key}")

    # Validate version -- require "1.1" (reject "1.0" old format)
    version = metadata.get("version")
    if version != "1.1":
        errors.append(
            f"Unsupported backup version '{version}' (expected '1.1')"
        )

    # Validate each table's rows against schema
    for table_def in schema.tables:
        table_rows = backup_data.get(table_def.name, [])
        pk_values: set = set()

        for row in table_rows:
            # Check PK field exists and is non-empty
            if table_def.pk not in row:
                errors.append(
                    f"{table_def.name} row missing '{table_def.pk}' field: "
                    f"{row.get(table_def.slug_field, 'unknown')}"
                )
            elif not row[table_def.pk]:
                errors.append(
                    f"{table_def.name} row has empty '{table_def.pk}': "
                    f"{row.get(table_def.slug_field, 'unknown')}"
                )
            else:
                pk_values.add(row[table_def.pk])

            # Check slug field exists
            if table_def.slug_field and table_def.slug_field not in row:
                errors.append(
                    f"{table_def.name} row missing '{table_def.slug_field}' field"
                )

        # Check parent FK references for child tables
        if table_def.parent is not None:
            parent_table = table_def.parent.table
            parent_field = table_def.parent.field
            # Collect parent PKs from the backup data
            parent_rows = backup_data.get(parent_table, [])
            parent_pk_def = _find_table_def(schema, parent_table)
            if parent_pk_def:
                parent_pks = {
                    r[parent_pk_def.pk] for r in parent_rows
                    if parent_pk_def.pk in r
                }
                for row in table_rows:
                    ref_val = row.get(parent_field)
                    if ref_val is not None and ref_val not in parent_pks:
                        warnings.append(
                            f"Orphaned {table_def.name} "
                            f"'{row.get(table_def.slug_field, 'unknown')}': "
                            f"{parent_field} not in backup"
                        )

    valid = len(errors) == 0
    return {"valid": valid, "errors": errors, "warnings": warnings}


def _find_table_def(schema: BackupSchema, table_name: str) -> TableDef | None:
    """Find a TableDef by name in the schema."""
    for t in schema.tables:
        if t.name == table_name:
            return t
    return None

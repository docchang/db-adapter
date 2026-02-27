"""Schema fix module - automatically repair schema drift.

Detects missing tables and columns, backs up the database, and applies fixes.

Usage:
    from schema.fix import generate_fix_plan, apply_fixes, FixPlan

    # Generate plan
    plan = generate_fix_plan(profile_name)

    # Apply fixes (backs up first)
    result = apply_fixes(profile_name, dry_run=False)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from adapters import PostgresAdapter


# Column definitions extracted from schema.sql
# Maps table.column -> SQL column definition
COLUMN_DEFINITIONS: dict[str, str] = {
    # projects table
    "projects.id": "SERIAL PRIMARY KEY",
    "projects.user_id": "UUID NOT NULL",
    "projects.name": "VARCHAR(100) NOT NULL",
    "projects.slug": "VARCHAR(100) NOT NULL",
    "projects.status": "VARCHAR(20) DEFAULT 'active'",
    "projects.phase": "VARCHAR(100)",
    "projects.objective": "TEXT",
    "projects.business_value": "TEXT",
    "projects.next_action": "TEXT",
    "projects.blocker": "TEXT",
    "projects.backburner_reason": "TEXT",
    "projects.reactivation_trigger": "TEXT",
    "projects.notes": "TEXT",
    "projects.target_market": "TEXT",
    "projects.monthly_cost": "TEXT",
    "projects.projected_mrr": "TEXT",
    "projects.revenue_model": "TEXT",
    "projects.architecture_summary": "TEXT",
    "projects.artifacts_path": "TEXT",
    "projects.created_at": "TIMESTAMPTZ DEFAULT NOW()",
    "projects.updated_at": "TIMESTAMPTZ DEFAULT NOW()",
    # milestones table
    "milestones.id": "SERIAL PRIMARY KEY",
    "milestones.user_id": "UUID NOT NULL",
    "milestones.project_id": "INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "milestones.slug": "VARCHAR(100) NOT NULL",
    "milestones.name": "VARCHAR(100) NOT NULL",
    "milestones.description": "TEXT",
    "milestones.status": "VARCHAR(20) DEFAULT 'active'",
    "milestones.goal": "TEXT",
    "milestones.not_included": "TEXT",
    "milestones.strategic_rationale": "TEXT",
    "milestones.risks": "JSONB",
    "milestones.design_decisions": "TEXT",
    "milestones.tech_components": "TEXT[]",
    "milestones.open_questions": "TEXT",
    "milestones.created_at": "TIMESTAMPTZ DEFAULT NOW()",
    "milestones.updated_at": "TIMESTAMPTZ DEFAULT NOW()",
    "milestones.completed_at": "TIMESTAMPTZ",
    # tasks table
    "tasks.id": "SERIAL PRIMARY KEY",
    "tasks.user_id": "UUID NOT NULL",
    "tasks.project_id": "INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "tasks.milestone_id": "INT REFERENCES milestones(id) ON DELETE SET NULL",
    "tasks.slug": "VARCHAR(100) NOT NULL",
    "tasks.name": "VARCHAR(100) NOT NULL",
    "tasks.type": "VARCHAR(20) NOT NULL",
    "tasks.status": "VARCHAR(20) DEFAULT 'planned'",
    "tasks.is_optional": "BOOLEAN DEFAULT FALSE",
    "tasks.objective": "TEXT",
    "tasks.unlocks": "TEXT",
    "tasks.depends_on": "TEXT[]",
    "tasks.lessons_learned": "TEXT",
    "tasks.diagram": "TEXT",
    "tasks.started_at": "TIMESTAMPTZ",
    "tasks.created_at": "TIMESTAMPTZ DEFAULT NOW()",
    "tasks.updated_at": "TIMESTAMPTZ DEFAULT NOW()",
    "tasks.completed_at": "TIMESTAMPTZ",
}


@dataclass
class ColumnFix:
    """A column to be added."""

    table: str
    column: str
    definition: str

    def to_sql(self) -> str:
        """Generate ALTER TABLE statement."""
        # Strip PRIMARY KEY, NOT NULL, and REFERENCES for ALTER ADD COLUMN
        # (these can't be added via simple ALTER for existing tables with data)
        definition = self.definition

        # For foreign keys, keep the REFERENCES part
        if "REFERENCES" in definition:
            # Keep it as-is for FK columns
            pass
        else:
            # Remove NOT NULL for safety (can't add NOT NULL to existing table with data)
            definition = definition.replace(" NOT NULL", "")

        # PRIMARY KEY columns can't be added via ALTER
        if "PRIMARY KEY" in definition:
            definition = definition.replace(" PRIMARY KEY", "")

        return f"ALTER TABLE {self.table} ADD COLUMN {self.column} {definition};"


@dataclass
class TableFix:
    """A table to be created (new table or recreated)."""

    table: str
    create_sql: str
    is_recreate: bool = False  # True if DROP+CREATE instead of just CREATE

    def to_sql(self) -> str:
        """Return the CREATE TABLE statement."""
        return self.create_sql


@dataclass
class FixPlan:
    """Plan for fixing schema drift."""

    profile_name: str
    missing_tables: list[TableFix] = field(default_factory=list)
    missing_columns: list[ColumnFix] = field(default_factory=list)
    tables_to_recreate: list[TableFix] = field(default_factory=list)  # Tables with 2+ missing cols
    error: str | None = None

    @property
    def has_fixes(self) -> bool:
        """True if there are any fixes to apply."""
        return bool(self.missing_tables or self.missing_columns or self.tables_to_recreate)

    @property
    def fix_count(self) -> int:
        """Total number of fixes."""
        return len(self.missing_tables) + len(self.missing_columns) + len(self.tables_to_recreate)


class FixResult(BaseModel):
    """Result of applying fixes."""

    success: bool = False
    profile_name: str = ""
    backup_path: str | None = None
    tables_created: int = 0
    tables_recreated: int = 0
    columns_added: int = 0
    error: str | None = None


def _get_table_create_sql(table_name: str, schema_file: str | None = None) -> str:
    """Get CREATE TABLE SQL for a table from schema file.

    Args:
        table_name: Name of the table to get CREATE SQL for
        schema_file: Path to schema file (defaults to schema.sql, use local-schema.sql for local)

    Returns:
        CREATE TABLE SQL statement
    """
    if schema_file:
        schema_path = Path(schema_file)
    else:
        schema_path = Path(__file__).parent.parent / "schema.sql"

    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    content = schema_path.read_text()

    # Extract CREATE TABLE statement for this table
    # Handle both "CREATE TABLE" and "CREATE TABLE IF NOT EXISTS"
    pattern = rf"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+{table_name}\s*\([^;]+\);"
    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

    if match:
        return match.group(0)

    raise ValueError(f"CREATE TABLE for {table_name} not found in {schema_path.name}")


def generate_fix_plan(profile_name: str | None = None, schema_file: str | None = None) -> FixPlan:
    """Generate a plan to fix schema drift.

    If a table has 2+ missing columns, it will be scheduled for DROP+CREATE.
    If a table has 1 missing column, it will use ALTER ADD COLUMN.

    Args:
        profile_name: Profile to check (uses current if None)
        schema_file: Path to schema file (auto-selects based on profile if None)

    Returns:
        FixPlan with missing tables, columns, and tables to recreate
    """
    from collections import defaultdict

    from db import connect_and_validate, read_profile_lock

    # Determine profile
    if not profile_name:
        profile_name = read_profile_lock()
        if not profile_name:
            return FixPlan(profile_name="", error="No profile configured")

    # Always use schema.sql (canonical schema) for creating tables
    # local-schema.sql is just for documentation of the legacy state

    plan = FixPlan(profile_name=profile_name)

    # Validate schema to get differences (validate_only=True to not write lock file)
    result = connect_and_validate(profile_name=profile_name, validate_only=True)

    if result.success:
        # No fixes needed
        return plan

    if not result.schema_report:
        plan.error = result.error or "Unknown error"
        return plan

    report = result.schema_report

    # Process missing tables (completely new tables)
    for table in report.missing_tables:
        try:
            create_sql = _get_table_create_sql(table, schema_file)
            plan.missing_tables.append(TableFix(table=table, create_sql=create_sql))
        except (FileNotFoundError, ValueError) as e:
            plan.error = str(e)
            return plan

    # Group missing columns by table
    columns_by_table: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for col_diff in report.missing_columns:
        key = f"{col_diff.table}.{col_diff.column}"
        if key in COLUMN_DEFINITIONS:
            columns_by_table[col_diff.table].append(
                (col_diff.column, COLUMN_DEFINITIONS[key])
            )
        else:
            plan.error = f"Unknown column definition for {key}"
            return plan

    # Decide: recreate (2+ cols) vs alter (1 col)
    for table, columns in columns_by_table.items():
        if len(columns) >= 2:
            # Multiple missing columns -> DROP and CREATE
            try:
                create_sql = _get_table_create_sql(table, schema_file)
                plan.tables_to_recreate.append(
                    TableFix(table=table, create_sql=create_sql, is_recreate=True)
                )
            except (FileNotFoundError, ValueError) as e:
                plan.error = str(e)
                return plan
        else:
            # Single column -> ALTER
            col_name, col_def = columns[0]
            plan.missing_columns.append(
                ColumnFix(table=table, column=col_name, definition=col_def)
            )

    return plan


def apply_fixes(
    profile_name: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> FixResult:
    """Apply schema fixes to a database.

    Args:
        profile_name: Profile to fix (uses current if None)
        dry_run: If True, only show what would be done
        confirm: Must be True to actually apply fixes

    Returns:
        FixResult with outcome
    """
    from adapters import PostgresAdapter
    from backup.backup_restore import backup_database
    from config import load_db_config
    from db import _resolve_url, connect_and_validate, read_profile_lock

    # Determine profile
    if not profile_name:
        profile_name = read_profile_lock()
        if not profile_name:
            return FixResult(error="No profile configured")

    result = FixResult(profile_name=profile_name)

    # Generate plan
    plan = generate_fix_plan(profile_name)

    if plan.error:
        result.error = plan.error
        return result

    if not plan.has_fixes:
        result.success = True
        return result

    # Dry run just returns the plan info
    if dry_run:
        result.success = True
        result.tables_created = len(plan.missing_tables)
        result.columns_added = len(plan.missing_columns)
        return result

    # Safety check
    if not confirm:
        result.error = "Fix requires --confirm flag"
        return result

    # Load config and get connection
    try:
        config = load_db_config()
        if profile_name not in config.profiles:
            result.error = f"Profile '{profile_name}' not found"
            return result

        url = _resolve_url(config.profiles[profile_name])
    except Exception as e:
        result.error = f"Failed to load config: {e}"
        return result

    # Backup first
    try:
        from datetime import datetime

        backup_dir = Path(__file__).parent.parent / "backup" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        backup_path = backup_dir / f"pre-fix-{profile_name}-{timestamp}.json"

        # Use existing backup infrastructure
        backup_database(output_path=str(backup_path))
        result.backup_path = str(backup_path)
    except Exception as e:
        result.error = f"Backup failed: {e}"
        return result

    # Apply fixes
    try:
        adapter = PostgresAdapter(database_url=url)

        # 1. Create missing tables first (order matters for FKs)
        for table_fix in plan.missing_tables:
            with adapter._conn.cursor() as cur:
                cur.execute(table_fix.to_sql())
            adapter._conn.commit()
            result.tables_created += 1

        # 2. Recreate tables with multiple missing columns (DROP + CREATE + restore)
        for table_fix in plan.tables_to_recreate:
            # DROP the table (CASCADE to handle FKs)
            with adapter._conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {table_fix.table} CASCADE;")
            adapter._conn.commit()

            # CREATE the table fresh
            with adapter._conn.cursor() as cur:
                cur.execute(table_fix.to_sql())
            adapter._conn.commit()

            result.tables_recreated += 1

        # 3. Add single missing columns via ALTER
        for col_fix in plan.missing_columns:
            with adapter._conn.cursor() as cur:
                cur.execute(col_fix.to_sql())
            adapter._conn.commit()
            result.columns_added += 1

        adapter.close()

        # 4. Restore data from backup (if we recreated any tables)
        if plan.tables_to_recreate and result.backup_path:
            from backup.backup_restore import restore_database

            restore_database(result.backup_path, mode="skip", dry_run=False)

        # Verify the fix worked (validate_only=True to not write lock file)
        verify_result = connect_and_validate(profile_name=profile_name, validate_only=True)
        if not verify_result.success:
            result.error = f"Fix applied but verification failed: {verify_result.error}"
            return result

        result.success = True

    except Exception as e:
        result.error = f"Failed to apply fixes: {e}"
        return result

    return result

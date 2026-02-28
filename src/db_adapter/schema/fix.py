"""Schema fix module -- automatically repair schema drift.

Detects missing tables and columns, optionally backs up affected data,
and applies DDL fixes via the ``DatabaseClient.execute()`` Protocol method.

All functions accept caller-provided parameters -- no hardcoded table names,
column definitions, or MC-specific logic.

Usage:
    from db_adapter.schema.fix import generate_fix_plan, apply_fixes
    from db_adapter.schema.comparator import validate_schema
    from db_adapter.schema.introspector import SchemaIntrospector

    # 1. Introspect and compare
    async with SchemaIntrospector(url) as introspector:
        actual = await introspector.get_column_names()
    result = validate_schema(actual, expected_columns)

    # 2. Generate plan
    plan = generate_fix_plan(result, column_definitions, "schema.sql")

    # 3. Apply fixes
    fix_result = await apply_fixes(adapter, plan, confirm=True)
"""

import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from db_adapter.schema.models import SchemaValidationResult

if TYPE_CHECKING:
    from db_adapter.adapters.base import DatabaseClient


# ------------------------------------------------------------------
# Fix data classes
# ------------------------------------------------------------------


@dataclass
class ColumnFix:
    """A column to be added via ALTER TABLE.

    Example:
        fix = ColumnFix(table="users", column="email", definition="TEXT NOT NULL")
        fix.to_sql()
        # 'ALTER TABLE users ADD COLUMN email TEXT;'
    """

    table: str
    column: str
    definition: str

    def to_sql(self) -> str:
        """Generate ALTER TABLE ADD COLUMN statement.

        Strips PRIMARY KEY and NOT NULL from the definition for safety
        (can't add NOT NULL to existing table with data, can't add PK
        via simple ALTER).  Keeps REFERENCES clauses for foreign keys.
        """
        definition = self.definition

        # For foreign keys, keep the REFERENCES part
        if "REFERENCES" in definition:
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
    """A table to be created (new table or recreated via DROP+CREATE).

    Example:
        fix = TableFix(table="users", create_sql="CREATE TABLE users (...);")
        fix.to_sql()
        # 'CREATE TABLE users (...);'
    """

    table: str
    create_sql: str
    is_recreate: bool = False  # True if DROP+CREATE instead of just CREATE

    def to_sql(self) -> str:
        """Return the CREATE TABLE statement."""
        return self.create_sql


@dataclass
class FixPlan:
    """Plan for fixing schema drift.

    Attributes:
        missing_tables: Tables that need to be created from scratch.
        missing_columns: Single columns to add via ALTER TABLE.
        tables_to_recreate: Tables with 2+ missing columns (DROP+CREATE).
        drop_order: Reverse topological order for safe table drops
            (child tables before parent tables).
        create_order: Forward topological order for safe table creates
            (parent tables before child tables).
        error: Error message if plan generation failed.
    """

    missing_tables: list[TableFix] = field(default_factory=list)
    missing_columns: list[ColumnFix] = field(default_factory=list)
    tables_to_recreate: list[TableFix] = field(default_factory=list)
    drop_order: list[str] = field(default_factory=list)
    create_order: list[str] = field(default_factory=list)
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
    """Result of applying schema fixes.

    Attributes:
        success: True if all fixes were applied successfully.
        backup_path: Path to pre-fix backup (if backup_fn was provided).
        tables_created: Number of new tables created.
        tables_recreated: Number of tables dropped and recreated.
        columns_added: Number of columns added via ALTER TABLE.
        error: Error message if fix failed.
    """

    success: bool = False
    backup_path: str | None = None
    tables_created: int = 0
    tables_recreated: int = 0
    columns_added: int = 0
    error: str | None = None


# ------------------------------------------------------------------
# Schema file parsing
# ------------------------------------------------------------------


def _get_table_create_sql(table_name: str, schema_file: str | Path) -> str:
    """Get CREATE TABLE SQL for a table from a schema file.

    Args:
        table_name: Name of the table to get CREATE SQL for.
        schema_file: Path to the SQL schema file.  Required -- there is
            no default or fallback path.

    Returns:
        The CREATE TABLE SQL statement for the given table.

    Raises:
        FileNotFoundError: If the schema file does not exist.
        ValueError: If the table is not found in the schema file.

    Example:
        sql = _get_table_create_sql("users", "/app/schema.sql")
    """
    schema_path = Path(schema_file)

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


def _parse_fk_dependencies(schema_file: str | Path) -> dict[str, set[str]]:
    """Parse REFERENCES clauses from a schema file to build an FK dependency graph.

    Returns a dict mapping table_name -> set of tables it depends on (references).

    Args:
        schema_file: Path to the SQL schema file.

    Returns:
        Dict mapping each table to the set of tables it references via FK.

    Example:
        deps = _parse_fk_dependencies("schema.sql")
        # {"chapters": {"books"}, "reviews": {"books", "chapters"}}
    """
    schema_path = Path(schema_file)
    if not schema_path.exists():
        return {}

    content = schema_path.read_text()
    dependencies: dict[str, set[str]] = {}

    # Find all CREATE TABLE blocks
    table_pattern = re.compile(
        r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(([^;]+)\);",
        re.IGNORECASE | re.DOTALL,
    )

    for match in table_pattern.finditer(content):
        table_name = match.group(1)
        table_body = match.group(2)
        dependencies[table_name] = set()

        # Find all REFERENCES clauses within this table's body
        ref_pattern = re.compile(r"REFERENCES\s+(\w+)\s*\(", re.IGNORECASE)
        for ref_match in ref_pattern.finditer(table_body):
            referenced_table = ref_match.group(1)
            if referenced_table != table_name:  # Skip self-references
                dependencies[table_name].add(referenced_table)

    return dependencies


def _topological_sort(dependencies: dict[str, set[str]], tables: list[str]) -> list[str]:
    """Topological sort of tables based on FK dependencies.

    Returns tables in forward order: parent tables first, child tables last.
    Tables not in the dependency graph are appended at the end.

    Args:
        dependencies: FK dependency graph (table -> set of referenced tables).
        tables: List of table names to sort.

    Returns:
        Tables sorted so that parent tables come before child tables.
    """
    # Filter dependencies to only include relevant tables
    relevant = {t: dependencies.get(t, set()) & set(tables) for t in tables}

    sorted_tables: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()  # For cycle detection

    def visit(table: str) -> None:
        if table in visited:
            return
        if table in visiting:
            # Cycle detected -- break it by just adding the table
            return
        visiting.add(table)
        for dep in relevant.get(table, set()):
            visit(dep)
        visiting.discard(table)
        visited.add(table)
        sorted_tables.append(table)

    for table in tables:
        visit(table)

    return sorted_tables


# ------------------------------------------------------------------
# Plan generation
# ------------------------------------------------------------------


def generate_fix_plan(
    validation_result: SchemaValidationResult,
    column_definitions: dict[str, str],
    schema_file: str | Path,
) -> FixPlan:
    """Generate a plan to fix schema drift.

    Pure sync logic -- reads schema file for CREATE TABLE SQL and builds
    a fix plan based on the validation result.

    If a table has 2+ missing columns, it will be scheduled for DROP+CREATE.
    If a table has 1 missing column, it will use ALTER ADD COLUMN.

    Args:
        validation_result: Result from ``validate_schema(actual, expected)``.
            Contains ``missing_tables``, ``missing_columns``, and ``error_count``.
        column_definitions: Mapping of ``"table.column"`` to SQL type definition
            strings.  Used for ALTER TABLE ADD COLUMN statements.
            Example: ``{"users.email": "TEXT NOT NULL", "users.status": "VARCHAR(20) DEFAULT 'active'"}``.
        schema_file: Path to the SQL schema file containing CREATE TABLE
            statements.  Used for table creation/recreation.

    Returns:
        ``FixPlan`` with missing tables, columns, tables to recreate, and
        topological ordering for safe DDL execution.

    Example:
        plan = generate_fix_plan(validation_result, column_defs, "schema.sql")
        if plan.has_fixes:
            result = await apply_fixes(adapter, plan, confirm=True)
    """
    plan = FixPlan()

    if validation_result.error_count == 0:
        return plan

    # Parse FK dependencies for topological ordering
    fk_deps = _parse_fk_dependencies(schema_file)

    # Process missing tables (completely new tables)
    for table in validation_result.missing_tables:
        try:
            create_sql = _get_table_create_sql(table, schema_file)
            plan.missing_tables.append(TableFix(table=table, create_sql=create_sql))
        except (FileNotFoundError, ValueError) as e:
            plan.error = str(e)
            return plan

    # Group missing columns by table
    columns_by_table: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for col_diff in validation_result.missing_columns:
        key = f"{col_diff.table}.{col_diff.column}"
        if key in column_definitions:
            columns_by_table[col_diff.table].append(
                (col_diff.column, column_definitions[key])
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

    # Compute topological ordering for all tables that need DDL
    all_affected_tables = (
        [tf.table for tf in plan.missing_tables]
        + [tf.table for tf in plan.tables_to_recreate]
    )
    if all_affected_tables:
        forward_order = _topological_sort(fk_deps, all_affected_tables)
        plan.create_order = forward_order
        plan.drop_order = list(reversed(forward_order))

    return plan


# ------------------------------------------------------------------
# Fix application
# ------------------------------------------------------------------


async def apply_fixes(
    adapter: "DatabaseClient",
    plan: FixPlan,
    backup_fn: Callable[["DatabaseClient", str], Awaitable[str]] | None = None,
    restore_fn: Callable[["DatabaseClient", str], Awaitable[None]] | None = None,
    verify_fn: Callable[["DatabaseClient"], Awaitable[bool]] | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> FixResult:
    """Apply schema fixes to a database.

    Executes DDL statements via the ``adapter.execute()`` Protocol method.
    Optionally backs up tables before destructive operations and verifies
    post-fix state.

    Args:
        adapter: Database adapter implementing ``DatabaseClient`` Protocol.
            Must support ``execute()`` for DDL -- adapters that don't
            (e.g., Supabase) will raise ``RuntimeError``.
        plan: Fix plan from ``generate_fix_plan()``.
        backup_fn: Optional async callback to back up a single table
            before DROP+CREATE.  Signature: ``backup_fn(adapter, table_name) -> backup_path``.
        restore_fn: Optional async callback to restore a single table
            from backup if fix fails.  Signature: ``restore_fn(adapter, backup_path) -> None``.
        verify_fn: Optional async callback to verify post-fix state.
            Signature: ``verify_fn(adapter) -> bool``.
        dry_run: If True, only report what would be done without executing.
        confirm: Must be True to actually apply fixes (safety guard).

    Returns:
        ``FixResult`` with outcome.

    Raises:
        RuntimeError: If the adapter does not support DDL operations
            (raises ``NotImplementedError`` on ``execute()``).

    Example:
        result = await apply_fixes(adapter, plan, confirm=True)
        if result.success:
            print(f"Fixed: {result.tables_created} created, {result.columns_added} added")
    """
    result = FixResult()

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
        result.tables_recreated = len(plan.tables_to_recreate)
        result.columns_added = len(plan.missing_columns)
        return result

    # Safety check
    if not confirm:
        result.error = "Fix requires confirm=True"
        return result

    try:
        # Build lookup for ordered operations
        missing_table_map = {tf.table: tf for tf in plan.missing_tables}
        recreate_table_map = {tf.table: tf for tf in plan.tables_to_recreate}

        # 1. Create missing tables in topological order (parents first)
        tables_to_create = [t for t in plan.create_order if t in missing_table_map]
        # Also include tables not in create_order (no FK deps)
        for tf in plan.missing_tables:
            if tf.table not in tables_to_create:
                tables_to_create.append(tf.table)

        for table_name in tables_to_create:
            table_fix = missing_table_map[table_name]
            try:
                await adapter.execute(table_fix.to_sql())
            except NotImplementedError:
                raise RuntimeError("DDL operations not supported for this adapter type")
            result.tables_created += 1

        # 2. Recreate tables with multiple missing columns
        # Drop in reverse topological order (children first)
        tables_to_drop = [t for t in plan.drop_order if t in recreate_table_map]
        for tf in plan.tables_to_recreate:
            if tf.table not in tables_to_drop:
                tables_to_drop.append(tf.table)

        backup_paths: dict[str, str] = {}

        for table_name in tables_to_drop:
            # Backup before drop if callback provided
            if backup_fn is not None:
                backup_path = await backup_fn(adapter, table_name)
                backup_paths[table_name] = backup_path
                if result.backup_path is None:
                    result.backup_path = backup_path

            try:
                await adapter.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
            except NotImplementedError:
                raise RuntimeError("DDL operations not supported for this adapter type")

        # Create in forward topological order (parents first)
        tables_to_create_after_drop = [t for t in plan.create_order if t in recreate_table_map]
        for tf in plan.tables_to_recreate:
            if tf.table not in tables_to_create_after_drop:
                tables_to_create_after_drop.append(tf.table)

        for table_name in tables_to_create_after_drop:
            table_fix = recreate_table_map[table_name]
            try:
                await adapter.execute(table_fix.to_sql())
            except NotImplementedError:
                raise RuntimeError("DDL operations not supported for this adapter type")
            result.tables_recreated += 1

        # Restore data if callback provided
        if restore_fn is not None:
            for table_name in tables_to_create_after_drop:
                if table_name in backup_paths:
                    await restore_fn(adapter, backup_paths[table_name])

        # 3. Add single missing columns via ALTER
        for col_fix in plan.missing_columns:
            try:
                await adapter.execute(col_fix.to_sql())
            except NotImplementedError:
                raise RuntimeError("DDL operations not supported for this adapter type")
            result.columns_added += 1

        # 4. Verify if callback provided
        if verify_fn is not None:
            verified = await verify_fn(adapter)
            if not verified:
                result.error = "Fix applied but verification failed"
                return result

        result.success = True

    except RuntimeError:
        # Re-raise RuntimeError (DDL not supported) without wrapping
        raise
    except Exception as e:
        result.error = f"Failed to apply fixes: {e}"
        return result

    return result

"""Simple schema comparison using set operations.

Compares expected columns (from DB Models) against actual columns (from introspector).
No ALTER SQL generation - just reports what's missing.

Usage:
    from schema.comparator import validate_schema
    from schema.introspector import SchemaIntrospector

    with SchemaIntrospector(database_url) as introspector:
        actual_columns = introspector.get_column_names()

    result = validate_schema(actual_columns)
    if result.valid:
        print("Schema is valid")
    else:
        print(result.format_report())
"""

from schema.db_models import get_all_expected_columns
from schema.models import ColumnDiff, SchemaValidationResult


def validate_schema(actual_columns: dict[str, set[str]]) -> SchemaValidationResult:
    """Validate actual database schema against expected (from DB Models).

    Performs simple set operations to find:
    - Missing tables: Tables defined in DB Models but not in actual database
    - Missing columns: Columns defined in DB Models but not in actual table
    - Extra tables: Tables in actual database but not in DB Models (warning only)

    Args:
        actual_columns: Dict mapping table name to set of column names
                       (from introspector.get_column_names())

    Returns:
        SchemaValidationResult with:
        - valid: True if no missing tables or columns
        - missing_tables: List of table names missing from database
        - missing_columns: List of ColumnDiff for missing columns
        - extra_tables: List of extra tables in database (warning only)
    """
    expected_columns = get_all_expected_columns()

    missing_tables: list[str] = []
    missing_columns: list[ColumnDiff] = []
    extra_tables: list[str] = []

    # Check for missing tables and columns
    for table_name in expected_columns:
        if table_name not in actual_columns:
            missing_tables.append(table_name)
            continue

        # Check for missing columns in this table
        expected = expected_columns[table_name]
        actual = actual_columns[table_name]
        missing = expected - actual

        for col_name in sorted(missing):
            missing_columns.append(
                ColumnDiff(
                    table=table_name,
                    column=col_name,
                    message=f"Column '{table_name}.{col_name}' is missing",
                )
            )

    # Check for extra tables (warning only, doesn't invalidate)
    for table_name in actual_columns:
        if table_name not in expected_columns:
            extra_tables.append(table_name)

    # Valid if no missing tables or columns
    valid = len(missing_tables) == 0 and len(missing_columns) == 0

    return SchemaValidationResult(
        valid=valid,
        missing_tables=sorted(missing_tables),
        missing_columns=missing_columns,
        extra_tables=sorted(extra_tables),
    )

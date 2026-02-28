"""Schema comparison using set operations.

Compares expected columns against actual columns from the database.
Pure logic -- no I/O, no database connections, no external dependencies.

Usage:
    from db_adapter.schema.comparator import validate_schema
    from db_adapter.schema.introspector import SchemaIntrospector

    async with SchemaIntrospector(database_url) as introspector:
        actual_columns = await introspector.get_column_names()

    expected_columns = {
        "users": {"id", "name", "email"},
        "orders": {"id", "user_id", "total"},
    }

    result = validate_schema(actual_columns, expected_columns)
    if result.valid:
        print("Schema is valid")
    else:
        print(result.format_report())
"""

from db_adapter.schema.models import ColumnDiff, SchemaValidationResult


def validate_schema(
    actual_columns: dict[str, set[str]],
    expected_columns: dict[str, set[str]],
) -> SchemaValidationResult:
    """Validate actual database schema against expected columns.

    Performs pure set operations to find:
    - Missing tables: Tables in *expected_columns* but not in *actual_columns*
    - Missing columns: Columns in *expected_columns* but not in the actual table
    - Extra tables: Tables in *actual_columns* but not in *expected_columns*
      (warning only -- does not affect ``valid`` status)

    Args:
        actual_columns: Dict mapping table name to set of column names,
            as returned by ``introspector.get_column_names()``.
        expected_columns: Dict mapping table name to set of expected column
            names, provided by the consuming project.

    Returns:
        ``SchemaValidationResult`` with:

        - ``valid``: ``True`` if no missing tables or columns
        - ``missing_tables``: List of table names missing from database
        - ``missing_columns``: List of ``ColumnDiff`` for missing columns
        - ``extra_tables``: List of extra tables in database (warning only)

    Examples:
        >>> # All tables and columns present
        >>> result = validate_schema(
        ...     {"users": {"id", "name"}},
        ...     {"users": {"id", "name"}},
        ... )
        >>> result.valid
        True

        >>> # Missing column detected
        >>> result = validate_schema(
        ...     {"users": {"id"}},
        ...     {"users": {"id", "name"}},
        ... )
        >>> result.valid
        False
        >>> result.missing_columns[0].column
        'name'

        >>> # Empty expected means everything is valid (extra tables only)
        >>> result = validate_schema({"users": {"id"}}, {})
        >>> result.valid
        True
    """
    actual_tables: set[str] = set(actual_columns.keys())
    expected_tables: set[str] = set(expected_columns.keys())

    # Tables in expected but not in actual
    missing_tables: list[str] = sorted(expected_tables - actual_tables)

    # Tables in actual but not in expected (warning only)
    extra_tables: list[str] = sorted(actual_tables - expected_tables)

    # Columns missing from tables that exist in both actual and expected
    missing_columns: list[ColumnDiff] = []
    common_tables: set[str] = expected_tables & actual_tables

    for table_name in sorted(common_tables):
        expected_cols: set[str] = expected_columns[table_name]
        actual_cols: set[str] = actual_columns[table_name]
        missing_cols: set[str] = expected_cols - actual_cols

        for col_name in sorted(missing_cols):
            missing_columns.append(
                ColumnDiff(
                    table=table_name,
                    column=col_name,
                    message=f"Column '{col_name}' missing from table '{table_name}'",
                )
            )

    is_valid: bool = len(missing_tables) == 0 and len(missing_columns) == 0

    return SchemaValidationResult(
        valid=is_valid,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        extra_tables=extra_tables,
    )

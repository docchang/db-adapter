"""Schema introspection, validation, and drift repair.

Provides schema comparison (``validate_schema``), live database
introspection (``SchemaIntrospector``), drift repair (``generate_fix_plan``,
``apply_fixes``), and cross-profile data sync (``compare_profiles``,
``sync_data``).

Usage:
    from db_adapter.schema import validate_schema, SchemaIntrospector
    from db_adapter.schema import generate_fix_plan, apply_fixes
    from db_adapter.schema import compare_profiles, sync_data
"""

from db_adapter.schema.comparator import validate_schema
from db_adapter.schema.fix import (
    ColumnFix,
    FixPlan,
    FixResult,
    TableFix,
    apply_fixes,
    generate_fix_plan,
)
from db_adapter.schema.introspector import SchemaIntrospector
from db_adapter.schema.models import (
    ColumnDiff,
    ColumnSchema,
    ConnectionResult,
    ConstraintSchema,
    DatabaseSchema,
    FunctionSchema,
    IndexSchema,
    SchemaValidationResult,
    TableSchema,
    TriggerSchema,
)
from db_adapter.schema.sync import SyncResult, compare_profiles, sync_data

__all__ = [
    "validate_schema",
    "SchemaIntrospector",
    "SchemaValidationResult",
    "ColumnDiff",
    "ConnectionResult",
    "ColumnSchema",
    "ConstraintSchema",
    "IndexSchema",
    "TriggerSchema",
    "FunctionSchema",
    "TableSchema",
    "DatabaseSchema",
    "compare_profiles",
    "sync_data",
    "SyncResult",
    "generate_fix_plan",
    "apply_fixes",
    "FixPlan",
    "FixResult",
    "ColumnFix",
    "TableFix",
]

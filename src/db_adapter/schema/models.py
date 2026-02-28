"""Pydantic models for schema introspection and validation.

This module contains schema-domain models:
- Introspection models: ColumnSchema, ConstraintSchema, IndexSchema,
  TriggerSchema, FunctionSchema, TableSchema, DatabaseSchema
- Validation models: ColumnDiff, SchemaValidationResult
- Connection result: ConnectionResult

Configuration models (DatabaseProfile, DatabaseConfig) live in
db_adapter.config.models.
"""

from pydantic import BaseModel, Field


# ============================================================================
# Validation Result Models
# ============================================================================


class ColumnDiff(BaseModel):
    """A missing column detected during validation."""

    table: str
    column: str
    message: str = ""


class SchemaValidationResult(BaseModel):
    """Result of schema validation.

    Example:
        >>> result = SchemaValidationResult(valid=True)
        >>> result.error_count
        0
        >>> result.format_report()
        'Schema valid'
    """

    valid: bool
    missing_tables: list[str] = Field(default_factory=list)
    missing_columns: list[ColumnDiff] = Field(default_factory=list)
    extra_tables: list[str] = Field(default_factory=list)  # Warning only

    @property
    def error_count(self) -> int:
        """Count of critical errors (missing tables + missing columns)."""
        return len(self.missing_tables) + len(self.missing_columns)

    def format_report(self) -> str:
        """Format validation result as human-readable report."""
        if self.valid:
            return "Schema valid"

        lines = ["Schema validation failed:"]

        if self.missing_tables:
            lines.append(f"\n  Missing tables ({len(self.missing_tables)}):")
            for table in self.missing_tables:
                lines.append(f"    - {table}")

        if self.missing_columns:
            lines.append(f"\n  Missing columns ({len(self.missing_columns)}):")
            for diff in self.missing_columns:
                lines.append(f"    - {diff.table}.{diff.column}")

        if self.extra_tables:
            lines.append(f"\n  Extra tables (warning): {', '.join(self.extra_tables)}")

        return "\n".join(lines)


# ============================================================================
# Connection Result
# ============================================================================


class ConnectionResult(BaseModel):
    """Result of connect_and_validate().

    Example:
        >>> result = ConnectionResult(success=True, profile_name="dev", schema_valid=True)
        >>> result.success
        True
    """

    success: bool
    profile_name: str | None = None
    schema_valid: bool | None = None
    schema_report: SchemaValidationResult | None = None
    error: str | None = None


# ============================================================================
# Schema Introspection Models
# ============================================================================


class ColumnSchema(BaseModel):
    """Schema for a database column.

    Example:
        >>> col = ColumnSchema(name="id", data_type="uuid")
        >>> col.is_nullable
        True
    """

    name: str
    data_type: str
    is_nullable: bool = True
    default: str | None = None


class ConstraintSchema(BaseModel):
    """Schema for a database constraint."""

    name: str
    constraint_type: str  # PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK
    columns: list[str] = Field(default_factory=list)
    references_table: str | None = None
    references_columns: list[str] | None = None
    on_delete: str | None = None


class IndexSchema(BaseModel):
    """Schema for a database index."""

    name: str
    columns: list[str] = Field(default_factory=list)
    is_unique: bool = False
    index_type: str = "btree"


class TriggerSchema(BaseModel):
    """Schema for a database trigger."""

    name: str
    event: str  # INSERT, UPDATE, DELETE
    timing: str  # BEFORE, AFTER
    function_name: str = ""


class FunctionSchema(BaseModel):
    """Schema for a database function."""

    name: str
    return_type: str = ""
    definition: str = ""


class TableSchema(BaseModel):
    """Schema for a database table."""

    name: str
    columns: dict[str, ColumnSchema] = Field(default_factory=dict)
    constraints: dict[str, ConstraintSchema] = Field(default_factory=dict)
    indexes: dict[str, IndexSchema] = Field(default_factory=dict)
    triggers: dict[str, TriggerSchema] = Field(default_factory=dict)


class DatabaseSchema(BaseModel):
    """Complete database schema."""

    tables: dict[str, TableSchema] = Field(default_factory=dict)
    functions: dict[str, FunctionSchema] = Field(default_factory=dict)

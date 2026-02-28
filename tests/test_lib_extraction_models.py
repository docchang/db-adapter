"""Tests for Step 1: Consolidate Duplicate Models.

Verifies that config models (DatabaseProfile, DatabaseConfig) live exclusively
in db_adapter.config.models, and schema/introspection models live exclusively
in db_adapter.schema.models, with no duplication between the two files.
"""

import ast
import pathlib
import subprocess

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "db_adapter"
CONFIG_MODELS_PATH = SRC_ROOT / "config" / "models.py"
SCHEMA_MODELS_PATH = SRC_ROOT / "schema" / "models.py"


def _get_class_names(filepath: pathlib.Path) -> set[str]:
    """Parse a Python file and return the set of top-level class names."""
    tree = ast.parse(filepath.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


# ============================================================================
# Test: File-level class placement (AST inspection)
# ============================================================================


class TestModelPlacement:
    """Verify each model class lives in exactly one canonical file."""

    def test_config_models_contains_only_profile_and_config(self) -> None:
        """config/models.py must contain exactly DatabaseProfile and DatabaseConfig."""
        classes = _get_class_names(CONFIG_MODELS_PATH)
        assert classes == {"DatabaseProfile", "DatabaseConfig"}, (
            f"Expected exactly DatabaseProfile and DatabaseConfig, got: {classes}"
        )

    def test_schema_models_contains_ten_classes(self) -> None:
        """schema/models.py must contain exactly 10 classes (no config models)."""
        classes = _get_class_names(SCHEMA_MODELS_PATH)
        expected = {
            "ColumnDiff",
            "SchemaValidationResult",
            "ConnectionResult",
            "ColumnSchema",
            "ConstraintSchema",
            "IndexSchema",
            "TriggerSchema",
            "FunctionSchema",
            "TableSchema",
            "DatabaseSchema",
        }
        assert classes == expected, (
            f"Expected {expected}, got: {classes}"
        )

    def test_no_overlap_between_config_and_schema(self) -> None:
        """No class should appear in both config/models.py and schema/models.py."""
        config_classes = _get_class_names(CONFIG_MODELS_PATH)
        schema_classes = _get_class_names(SCHEMA_MODELS_PATH)
        overlap = config_classes & schema_classes
        assert overlap == set(), f"Duplicate classes found: {overlap}"

    def test_database_profile_only_in_config(self) -> None:
        """DatabaseProfile must exist in config/models.py and nowhere else in models files."""
        config_classes = _get_class_names(CONFIG_MODELS_PATH)
        schema_classes = _get_class_names(SCHEMA_MODELS_PATH)
        assert "DatabaseProfile" in config_classes
        assert "DatabaseProfile" not in schema_classes

    def test_schema_validation_result_only_in_schema(self) -> None:
        """SchemaValidationResult must exist in schema/models.py and nowhere else."""
        config_classes = _get_class_names(CONFIG_MODELS_PATH)
        schema_classes = _get_class_names(SCHEMA_MODELS_PATH)
        assert "SchemaValidationResult" in schema_classes
        assert "SchemaValidationResult" not in config_classes


# ============================================================================
# Test: grep-based uniqueness across entire src/ tree
# ============================================================================


class TestGrepUniqueness:
    """Use grep to verify class definitions appear exactly once in src/."""

    def test_database_profile_unique(self) -> None:
        """'class DatabaseProfile' appears exactly once in src/."""
        result = subprocess.run(
            ["grep", "-r", "class DatabaseProfile", str(SRC_ROOT)],
            capture_output=True,
            text=True,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l]
        assert len(lines) == 1, f"Expected 1 occurrence, got {len(lines)}: {lines}"
        assert "config/models.py" in lines[0]

    def test_schema_validation_result_unique(self) -> None:
        """'class SchemaValidationResult' appears exactly once in src/."""
        result = subprocess.run(
            ["grep", "-r", "class SchemaValidationResult", str(SRC_ROOT)],
            capture_output=True,
            text=True,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l]
        assert len(lines) == 1, f"Expected 1 occurrence, got {len(lines)}: {lines}"
        assert "schema/models.py" in lines[0]

    def test_connection_result_unique(self) -> None:
        """'class ConnectionResult' appears exactly once in src/."""
        result = subprocess.run(
            ["grep", "-r", "class ConnectionResult", str(SRC_ROOT)],
            capture_output=True,
            text=True,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l]
        assert len(lines) == 1, f"Expected 1 occurrence, got {len(lines)}: {lines}"
        assert "schema/models.py" in lines[0]


# ============================================================================
# Test: Model instantiation and field validation (config models)
# ============================================================================


class TestConfigModels:
    """Verify DatabaseProfile and DatabaseConfig instantiate and validate correctly."""

    def test_database_profile_required_fields(self) -> None:
        """DatabaseProfile requires url."""
        from db_adapter.config.models import DatabaseProfile

        profile = DatabaseProfile(url="postgresql://localhost:5432/mydb")
        assert profile.url == "postgresql://localhost:5432/mydb"
        assert profile.description == ""
        assert profile.db_password is None
        assert profile.provider == "postgres"

    def test_database_profile_all_fields(self) -> None:
        """DatabaseProfile accepts all optional fields."""
        from db_adapter.config.models import DatabaseProfile

        profile = DatabaseProfile(
            url="postgresql://localhost:5432/mydb",
            description="Development database",
            db_password="secret",
            provider="supabase",
        )
        assert profile.description == "Development database"
        assert profile.db_password == "secret"
        assert profile.provider == "supabase"

    def test_database_profile_missing_url_raises(self) -> None:
        """DatabaseProfile raises ValidationError when url is missing."""
        from pydantic import ValidationError

        from db_adapter.config.models import DatabaseProfile

        with pytest.raises(ValidationError):
            DatabaseProfile()  # type: ignore[call-arg]

    def test_database_config_with_profiles(self) -> None:
        """DatabaseConfig holds a dict of profiles."""
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        config = DatabaseConfig(
            profiles={
                "dev": DatabaseProfile(url="postgresql://localhost/dev"),
                "prod": DatabaseProfile(url="postgresql://prod-host/prod"),
            }
        )
        assert len(config.profiles) == 2
        assert config.profiles["dev"].url == "postgresql://localhost/dev"
        assert config.schema_file == "schema.sql"
        assert config.validate_on_connect is True

    def test_database_config_missing_profiles_raises(self) -> None:
        """DatabaseConfig requires profiles dict."""
        from pydantic import ValidationError

        from db_adapter.config.models import DatabaseConfig

        with pytest.raises(ValidationError):
            DatabaseConfig()  # type: ignore[call-arg]


# ============================================================================
# Test: Model instantiation and field validation (schema models)
# ============================================================================


class TestSchemaModels:
    """Verify schema/introspection models instantiate and validate correctly."""

    def test_column_diff(self) -> None:
        """ColumnDiff stores table, column, and optional message."""
        from db_adapter.schema.models import ColumnDiff

        diff = ColumnDiff(table="users", column="email")
        assert diff.table == "users"
        assert diff.column == "email"
        assert diff.message == ""

    def test_schema_validation_result_valid(self) -> None:
        """SchemaValidationResult with valid=True reports no errors."""
        from db_adapter.schema.models import SchemaValidationResult

        result = SchemaValidationResult(valid=True)
        assert result.error_count == 0
        assert result.format_report() == "Schema valid"

    def test_schema_validation_result_with_errors(self) -> None:
        """SchemaValidationResult counts missing tables and columns."""
        from db_adapter.schema.models import ColumnDiff, SchemaValidationResult

        result = SchemaValidationResult(
            valid=False,
            missing_tables=["users"],
            missing_columns=[ColumnDiff(table="projects", column="name")],
        )
        assert result.error_count == 2
        report = result.format_report()
        assert "Missing tables (1)" in report
        assert "Missing columns (1)" in report
        assert "users" in report
        assert "projects.name" in report

    def test_schema_validation_result_with_extras(self) -> None:
        """SchemaValidationResult format_report includes extra tables warning."""
        from db_adapter.schema.models import SchemaValidationResult

        result = SchemaValidationResult(
            valid=False,
            missing_tables=["users"],
            extra_tables=["temp_data"],
        )
        report = result.format_report()
        assert "Extra tables (warning): temp_data" in report

    def test_connection_result(self) -> None:
        """ConnectionResult holds connection outcome."""
        from db_adapter.schema.models import ConnectionResult

        result = ConnectionResult(success=True, profile_name="dev", schema_valid=True)
        assert result.success is True
        assert result.profile_name == "dev"
        assert result.error is None

    def test_connection_result_with_error(self) -> None:
        """ConnectionResult can hold an error string."""
        from db_adapter.schema.models import ConnectionResult

        result = ConnectionResult(success=False, error="Connection refused")
        assert result.success is False
        assert result.error == "Connection refused"

    def test_column_schema(self) -> None:
        """ColumnSchema represents a database column."""
        from db_adapter.schema.models import ColumnSchema

        col = ColumnSchema(name="id", data_type="uuid", is_nullable=False)
        assert col.name == "id"
        assert col.data_type == "uuid"
        assert col.is_nullable is False
        assert col.default is None

    def test_constraint_schema(self) -> None:
        """ConstraintSchema represents a database constraint."""
        from db_adapter.schema.models import ConstraintSchema

        constraint = ConstraintSchema(
            name="pk_users",
            constraint_type="PRIMARY KEY",
            columns=["id"],
        )
        assert constraint.name == "pk_users"
        assert constraint.constraint_type == "PRIMARY KEY"
        assert constraint.columns == ["id"]

    def test_index_schema(self) -> None:
        """IndexSchema represents a database index."""
        from db_adapter.schema.models import IndexSchema

        idx = IndexSchema(name="idx_email", columns=["email"], is_unique=True)
        assert idx.is_unique is True
        assert idx.index_type == "btree"

    def test_trigger_schema(self) -> None:
        """TriggerSchema represents a database trigger."""
        from db_adapter.schema.models import TriggerSchema

        trigger = TriggerSchema(
            name="trg_updated_at",
            event="UPDATE",
            timing="BEFORE",
            function_name="set_updated_at",
        )
        assert trigger.event == "UPDATE"
        assert trigger.timing == "BEFORE"

    def test_function_schema(self) -> None:
        """FunctionSchema represents a database function."""
        from db_adapter.schema.models import FunctionSchema

        func = FunctionSchema(name="set_updated_at", return_type="trigger")
        assert func.name == "set_updated_at"
        assert func.return_type == "trigger"

    def test_table_schema(self) -> None:
        """TableSchema holds columns, constraints, indexes, triggers."""
        from db_adapter.schema.models import ColumnSchema, TableSchema

        table = TableSchema(
            name="users",
            columns={
                "id": ColumnSchema(name="id", data_type="uuid"),
                "email": ColumnSchema(name="email", data_type="text"),
            },
        )
        assert table.name == "users"
        assert len(table.columns) == 2
        assert "id" in table.columns

    def test_database_schema(self) -> None:
        """DatabaseSchema holds tables and functions."""
        from db_adapter.schema.models import DatabaseSchema, FunctionSchema, TableSchema

        schema = DatabaseSchema(
            tables={"users": TableSchema(name="users")},
            functions={"set_updated_at": FunctionSchema(name="set_updated_at")},
        )
        assert "users" in schema.tables
        assert "set_updated_at" in schema.functions

    def test_connection_result_references_schema_validation_result(self) -> None:
        """ConnectionResult.schema_report correctly nests SchemaValidationResult."""
        from db_adapter.schema.models import ConnectionResult, SchemaValidationResult

        report = SchemaValidationResult(valid=True)
        result = ConnectionResult(
            success=True,
            profile_name="dev",
            schema_valid=True,
            schema_report=report,
        )
        assert result.schema_report is not None
        assert result.schema_report.valid is True
        assert result.schema_report.error_count == 0

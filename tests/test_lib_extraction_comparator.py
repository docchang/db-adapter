"""Tests for Step 5: Decouple Schema Comparator.

Verifies that validate_schema() accepts two parameters (actual_columns and
expected_columns) and performs pure set-based comparison with no MC-specific
dependencies.
"""

import ast
import inspect
from pathlib import Path

from db_adapter.schema.comparator import validate_schema
from db_adapter.schema.models import ColumnDiff, SchemaValidationResult


# Path to comparator source
COMPARATOR_PATH = Path(__file__).parent.parent / "src" / "db_adapter" / "schema" / "comparator.py"


class TestMCCodeRemoved:
    """Verify that all MC-specific code is removed from comparator.py."""

    def test_no_db_models_import(self) -> None:
        """comparator.py must not import from db_models in any form."""
        source: str = COMPARATOR_PATH.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert "db_models" not in node.module, (
                    f"Found db_models import: from {node.module} import ..."
                )

    def test_no_removed_comments(self) -> None:
        """No leftover # REMOVED: comments from Step 2."""
        source: str = COMPARATOR_PATH.read_text()
        assert "# REMOVED:" not in source, (
            "Found leftover '# REMOVED:' comment in comparator.py"
        )

    def test_no_get_all_expected_columns_reference(self) -> None:
        """No reference to get_all_expected_columns function."""
        source: str = COMPARATOR_PATH.read_text()
        assert "get_all_expected_columns" not in source, (
            "Found reference to get_all_expected_columns in comparator.py"
        )


class TestFunctionSignature:
    """Verify validate_schema() has the correct 2-param signature."""

    def test_accepts_two_positional_params(self) -> None:
        """validate_schema() must accept exactly 2 positional parameters."""
        sig = inspect.signature(validate_schema)
        params = list(sig.parameters.values())
        assert len(params) == 2, (
            f"Expected 2 parameters, got {len(params)}: "
            f"{[p.name for p in params]}"
        )

    def test_first_param_is_actual_columns(self) -> None:
        """First parameter must be named actual_columns."""
        sig = inspect.signature(validate_schema)
        params = list(sig.parameters.keys())
        assert params[0] == "actual_columns"

    def test_second_param_is_expected_columns(self) -> None:
        """Second parameter must be named expected_columns."""
        sig = inspect.signature(validate_schema)
        params = list(sig.parameters.keys())
        assert params[1] == "expected_columns"

    def test_return_type_is_schema_validation_result(self) -> None:
        """Return type annotation must be SchemaValidationResult."""
        sig = inspect.signature(validate_schema)
        assert sig.return_annotation is SchemaValidationResult

    def test_both_params_are_positional(self) -> None:
        """Both parameters must be positional-or-keyword (no defaults)."""
        sig = inspect.signature(validate_schema)
        for name, param in sig.parameters.items():
            assert param.default is inspect.Parameter.empty, (
                f"Parameter '{name}' has a default value; should be required"
            )


class TestValidSchemas:
    """Test cases where the schema is valid."""

    def test_exact_match(self) -> None:
        """Exact match between actual and expected returns valid=True."""
        actual = {"users": {"id", "name", "email"}}
        expected = {"users": {"id", "name", "email"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is True
        assert result.missing_tables == []
        assert result.missing_columns == []
        assert result.extra_tables == []

    def test_actual_has_extra_columns(self) -> None:
        """Extra columns in actual (not in expected) are ignored -- still valid."""
        actual = {"users": {"id", "name", "email", "created_at"}}
        expected = {"users": {"id", "name", "email"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is True
        assert result.missing_columns == []

    def test_empty_expected_returns_valid(self) -> None:
        """Empty expected_columns means nothing is required -- always valid."""
        actual = {"users": {"id", "name"}, "orders": {"id", "total"}}
        expected: dict[str, set[str]] = {}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is True
        assert result.missing_tables == []
        assert result.missing_columns == []
        assert sorted(result.extra_tables) == ["orders", "users"]

    def test_both_empty(self) -> None:
        """Both empty dicts means valid with no findings."""
        result: SchemaValidationResult = validate_schema({}, {})

        assert result.valid is True
        assert result.missing_tables == []
        assert result.missing_columns == []
        assert result.extra_tables == []

    def test_multiple_tables_all_present(self) -> None:
        """Multiple tables all matching returns valid."""
        actual = {
            "users": {"id", "name"},
            "orders": {"id", "user_id", "total"},
            "items": {"id", "order_id", "product_id"},
        }
        expected = {
            "users": {"id", "name"},
            "orders": {"id", "user_id", "total"},
            "items": {"id", "order_id", "product_id"},
        }

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is True


class TestMissingTables:
    """Test detection of missing tables."""

    def test_missing_table_detected(self) -> None:
        """Table in expected but not in actual is missing."""
        actual = {"users": {"id", "name"}}
        expected = {"users": {"id", "name"}, "orders": {"id", "total"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is False
        assert "orders" in result.missing_tables

    def test_all_tables_missing(self) -> None:
        """All expected tables missing from empty actual."""
        actual: dict[str, set[str]] = {}
        expected = {"users": {"id"}, "orders": {"id"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is False
        assert sorted(result.missing_tables) == ["orders", "users"]
        assert result.missing_columns == []

    def test_missing_table_and_extra_table(self) -> None:
        """Both missing and extra tables detected simultaneously."""
        actual = {"t1": {"a"}}
        expected = {"t2": {"a"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is False
        assert result.missing_tables == ["t2"]
        assert result.extra_tables == ["t1"]


class TestMissingColumns:
    """Test detection of missing columns."""

    def test_missing_column_detected(self) -> None:
        """Column in expected but not in actual is missing."""
        actual = {"users": {"id", "name"}}
        expected = {"users": {"id", "name", "email"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is False
        assert len(result.missing_columns) == 1
        assert result.missing_columns[0].table == "users"
        assert result.missing_columns[0].column == "email"

    def test_multiple_missing_columns(self) -> None:
        """Multiple missing columns in one table."""
        actual = {"users": {"id"}}
        expected = {"users": {"id", "name", "email", "phone"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is False
        assert len(result.missing_columns) == 3
        missing_col_names: list[str] = [c.column for c in result.missing_columns]
        assert sorted(missing_col_names) == ["email", "name", "phone"]

    def test_missing_columns_across_tables(self) -> None:
        """Missing columns across multiple tables."""
        actual = {
            "users": {"id"},
            "orders": {"id"},
        }
        expected = {
            "users": {"id", "name"},
            "orders": {"id", "total"},
        }

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is False
        assert len(result.missing_columns) == 2
        tables: list[str] = [c.table for c in result.missing_columns]
        assert "users" in tables
        assert "orders" in tables

    def test_column_diff_has_message(self) -> None:
        """Each ColumnDiff includes a descriptive message."""
        actual = {"users": {"id"}}
        expected = {"users": {"id", "email"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        diff: ColumnDiff = result.missing_columns[0]
        assert "email" in diff.message
        assert "users" in diff.message


class TestExtraTables:
    """Test detection of extra tables (warning only, does not affect validity)."""

    def test_extra_table_detected(self) -> None:
        """Table in actual but not in expected is extra."""
        actual = {"users": {"id"}, "logs": {"id", "message"}}
        expected = {"users": {"id"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is True
        assert result.extra_tables == ["logs"]

    def test_extra_tables_do_not_invalidate(self) -> None:
        """Extra tables are warnings -- they do not cause valid=False."""
        actual = {"users": {"id"}, "logs": {"id"}, "metrics": {"id"}}
        expected = {"users": {"id"}}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is True
        assert sorted(result.extra_tables) == ["logs", "metrics"]

    def test_all_extra_tables(self) -> None:
        """All actual tables are extra when expected is empty."""
        actual = {"t1": {"a"}, "t2": {"b"}}
        expected: dict[str, set[str]] = {}

        result: SchemaValidationResult = validate_schema(actual, expected)

        assert result.valid is True
        assert sorted(result.extra_tables) == ["t1", "t2"]


class TestErrorCount:
    """Test the error_count property on SchemaValidationResult."""

    def test_error_count_zero_when_valid(self) -> None:
        """error_count is 0 when schema is valid."""
        result = validate_schema({"t": {"a"}}, {"t": {"a"}})
        assert result.error_count == 0

    def test_error_count_includes_missing_tables(self) -> None:
        """error_count includes missing tables."""
        result = validate_schema({}, {"t1": {"a"}, "t2": {"b"}})
        assert result.error_count == 2  # 2 missing tables

    def test_error_count_includes_missing_columns(self) -> None:
        """error_count includes missing columns."""
        result = validate_schema({"t": {"a"}}, {"t": {"a", "b", "c"}})
        assert result.error_count == 2  # 2 missing columns

    def test_error_count_combined(self) -> None:
        """error_count sums missing tables and missing columns."""
        result = validate_schema(
            {"t1": {"a"}},
            {"t1": {"a", "b"}, "t2": {"x"}},
        )
        # 1 missing table (t2) + 1 missing column (t1.b)
        assert result.error_count == 2


class TestFormatReport:
    """Test the format_report() method on SchemaValidationResult."""

    def test_valid_report(self) -> None:
        """Valid schema returns 'Schema valid'."""
        result = validate_schema({"t": {"a"}}, {"t": {"a"}})
        assert result.format_report() == "Schema valid"

    def test_invalid_report_contains_missing_table(self) -> None:
        """Report includes missing table name."""
        result = validate_schema({}, {"orders": {"id"}})
        report: str = result.format_report()
        assert "orders" in report
        assert "Missing tables" in report

    def test_invalid_report_contains_missing_column(self) -> None:
        """Report includes missing column info."""
        result = validate_schema({"users": {"id"}}, {"users": {"id", "email"}})
        report: str = result.format_report()
        assert "users.email" in report
        assert "Missing columns" in report


class TestFactoryCallSite:
    """Verify factory.py passes expected_columns to validate_schema()."""

    def test_factory_passes_expected_columns(self) -> None:
        """factory.py's validate_schema call uses 2 args."""
        factory_path = Path(__file__).parent.parent / "src" / "db_adapter" / "factory.py"
        source: str = factory_path.read_text()
        tree = ast.parse(source)

        calls_to_validate: list[ast.Call] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Match validate_schema(...) calls
                if isinstance(node.func, ast.Name) and node.func.id == "validate_schema":
                    calls_to_validate.append(node)

        assert len(calls_to_validate) >= 1, (
            "No validate_schema() call found in factory.py"
        )

        for call in calls_to_validate:
            arg_count: int = len(call.args) + len(call.keywords)
            assert arg_count == 2, (
                f"validate_schema() called with {arg_count} args in factory.py; "
                f"expected 2 (actual_columns, expected_columns)"
            )

    def test_factory_skips_validation_when_none(self) -> None:
        """factory.py returns early when expected_columns is None."""
        factory_path = Path(__file__).parent.parent / "src" / "db_adapter" / "factory.py"
        source: str = factory_path.read_text()

        # The None-check must appear before the validate_schema call
        none_check_pos: int = source.index("expected_columns is None")
        validate_call_pos: int = source.index("validate_schema(actual_columns")

        assert none_check_pos < validate_call_pos, (
            "expected_columns is None check must appear before validate_schema() call"
        )

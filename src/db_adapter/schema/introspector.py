"""PostgreSQL schema introspection via information_schema.

This module queries the live database to extract schema information:
- Tables, columns, data types, nullability, defaults
- Constraints (primary key, foreign key, unique, check)
- Indexes (name, columns, uniqueness, type)
- Triggers (name, event, timing, function)
- Functions (name, return type, definition)

Uses psycopg (v3) for PostgreSQL connections.
"""

import psycopg
from psycopg import Connection

from schema.models import (
    ColumnSchema,
    ConstraintSchema,
    IndexSchema,
    TriggerSchema,
    FunctionSchema,
    TableSchema,
    DatabaseSchema,
)


class SchemaIntrospector:
    """Introspects PostgreSQL database schema.

    Uses information_schema and pg_catalog for comprehensive schema extraction.
    Works with any PostgreSQL database (RDS, Supabase, local).

    Usage:
        with SchemaIntrospector(database_url) as introspector:
            # Get full schema (tables, columns, constraints, indexes, triggers)
            schema = introspector.introspect()

            # Or just get column names for validation
            columns = introspector.get_column_names()
    """

    # Tables to exclude from introspection (system tables)
    EXCLUDED_TABLES = {
        "schema_migrations",
        "pg_stat_statements",
        "spatial_ref_sys",
    }

    def __init__(self, database_url: str):
        """Initialize with database connection URL.

        Args:
            database_url: PostgreSQL connection URL
        """
        self._database_url = database_url
        self._conn: Connection | None = None

    def __enter__(self) -> "SchemaIntrospector":
        """Context manager entry - opens connection."""
        # Append connect_timeout if not already in URL
        url = self._database_url
        if "connect_timeout" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}connect_timeout=10"

        self._conn = psycopg.connect(url)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - closes connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def introspect(self, schema_name: str = "public") -> DatabaseSchema:
        """Introspect full database schema.

        Args:
            schema_name: PostgreSQL schema to introspect (default: public)

        Returns:
            DatabaseSchema with all tables, columns, constraints, etc.
        """
        if not self._conn:
            raise RuntimeError("Introspector not connected. Use with statement.")

        db_schema = DatabaseSchema()

        # Get tables
        tables = self._get_tables(schema_name)

        for table_name in tables:
            if table_name in self.EXCLUDED_TABLES:
                continue

            table = TableSchema(name=table_name)

            # Get columns
            table.columns = self._get_columns(schema_name, table_name)

            # Get constraints
            table.constraints = self._get_constraints(schema_name, table_name)

            # Get indexes
            table.indexes = self._get_indexes(schema_name, table_name)

            # Get triggers
            table.triggers = self._get_triggers(schema_name, table_name)

            db_schema.tables[table_name] = table

        # Get functions
        db_schema.functions = self._get_functions(schema_name)

        return db_schema

    def get_column_names(self, schema_name: str = "public") -> dict[str, set[str]]:
        """Get column names for all tables (simplified for comparator).

        This is a lightweight alternative to full introspection when you only
        need to check if expected columns exist.

        Args:
            schema_name: PostgreSQL schema to query (default: public)

        Returns:
            Dict mapping table name to set of column names
        """
        if not self._conn:
            raise RuntimeError("Introspector not connected. Use with statement.")

        result: dict[str, set[str]] = {}

        # Get all tables
        tables = self._get_tables(schema_name)

        for table_name in tables:
            if table_name in self.EXCLUDED_TABLES:
                continue

            # Query just column names (no types, defaults, etc.)
            query = """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
            """
            with self._conn.cursor() as cur:
                cur.execute(query, (schema_name, table_name))
                result[table_name] = {row[0] for row in cur.fetchall()}

        return result

    def _get_tables(self, schema_name: str) -> list[str]:
        """Get all table names in schema."""
        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        with self._conn.cursor() as cur:
            cur.execute(query, (schema_name,))
            return [row[0] for row in cur.fetchall()]

    def _get_columns(self, schema_name: str, table_name: str) -> dict[str, ColumnSchema]:
        """Get columns for a table."""
        query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
        """
        with self._conn.cursor() as cur:
            cur.execute(query, (schema_name, table_name))
            columns = {}
            for row in cur.fetchall():
                col_name, data_type, is_nullable, default = row
                columns[col_name] = ColumnSchema(
                    name=col_name,
                    data_type=self._normalize_data_type(data_type),
                    is_nullable=(is_nullable == "YES"),
                    default=default,
                )
            return columns

    def _normalize_data_type(self, data_type: str) -> str:
        """Normalize PostgreSQL data type names.

        Maps verbose information_schema types to standard names.
        """
        type_map = {
            "character varying": "varchar",
            "character": "char",
            "timestamp with time zone": "timestamptz",
            "timestamp without time zone": "timestamp",
            "integer": "int",
            "boolean": "bool",
        }
        return type_map.get(data_type.lower(), data_type.lower())

    def _get_constraints(
        self, schema_name: str, table_name: str
    ) -> dict[str, ConstraintSchema]:
        """Get constraints for a table."""
        query = """
            SELECT
                tc.constraint_name,
                tc.constraint_type,
                kcu.column_name,
                ccu.table_name AS references_table,
                ccu.column_name AS references_column,
                rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            LEFT JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.constraint_type = 'FOREIGN KEY'
            LEFT JOIN information_schema.referential_constraints rc
                ON tc.constraint_name = rc.constraint_name
            WHERE tc.table_schema = %s
              AND tc.table_name = %s
            ORDER BY tc.constraint_name, kcu.ordinal_position
        """
        with self._conn.cursor() as cur:
            cur.execute(query, (schema_name, table_name))

            constraints: dict[str, ConstraintSchema] = {}
            constraint_columns: dict[str, list[str]] = {}

            for row in cur.fetchall():
                (
                    name,
                    ctype,
                    col_name,
                    ref_table,
                    ref_col,
                    delete_rule,
                ) = row

                if name not in constraints:
                    constraints[name] = ConstraintSchema(
                        name=name,
                        constraint_type=ctype,
                        columns=[],
                        references_table=ref_table if ctype == "FOREIGN KEY" else None,
                        references_columns=[ref_col] if ref_col else None,
                        on_delete=delete_rule,
                    )
                    constraint_columns[name] = []

                if col_name not in constraint_columns[name]:
                    constraint_columns[name].append(col_name)

            # Update column lists
            for name, cols in constraint_columns.items():
                constraints[name].columns = cols

            return constraints

    def _get_indexes(self, schema_name: str, table_name: str) -> dict[str, IndexSchema]:
        """Get indexes for a table (excluding primary key)."""
        query = """
            SELECT
                i.relname AS index_name,
                array_agg(a.attname ORDER BY x.ordinality) AS columns,
                ix.indisunique AS is_unique,
                am.amname AS index_type
            FROM pg_index ix
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_am am ON am.oid = i.relam
            JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS x(attnum, ordinality) ON TRUE
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.attnum
            WHERE n.nspname = %s
              AND t.relname = %s
              AND NOT ix.indisprimary
            GROUP BY i.relname, ix.indisunique, am.amname
            ORDER BY i.relname
        """
        with self._conn.cursor() as cur:
            cur.execute(query, (schema_name, table_name))
            indexes = {}
            for row in cur.fetchall():
                name, columns, is_unique, idx_type = row
                indexes[name] = IndexSchema(
                    name=name,
                    columns=list(columns),
                    is_unique=is_unique,
                    index_type=idx_type,
                )
            return indexes

    def _get_triggers(self, schema_name: str, table_name: str) -> dict[str, TriggerSchema]:
        """Get triggers for a table."""
        query = """
            SELECT
                trigger_name,
                event_manipulation,
                action_timing,
                action_statement
            FROM information_schema.triggers
            WHERE trigger_schema = %s
              AND event_object_table = %s
        """
        with self._conn.cursor() as cur:
            cur.execute(query, (schema_name, table_name))
            triggers = {}
            for row in cur.fetchall():
                name, event, timing, statement = row
                # Extract function name from statement like "EXECUTE FUNCTION func_name()"
                func_name = ""
                if "EXECUTE FUNCTION" in statement:
                    func_name = (
                        statement.split("EXECUTE FUNCTION")[1].strip().rstrip("()")
                    )
                elif "EXECUTE PROCEDURE" in statement:
                    func_name = (
                        statement.split("EXECUTE PROCEDURE")[1].strip().rstrip("()")
                    )

                triggers[name] = TriggerSchema(
                    name=name,
                    event=event,
                    timing=timing,
                    function_name=func_name,
                )
            return triggers

    def _get_functions(self, schema_name: str) -> dict[str, FunctionSchema]:
        """Get user-defined functions in schema.

        Note: Uses prokind = 'f' to filter for regular functions (PostgreSQL 11+).
        This excludes aggregate functions (prokind = 'a'), procedures (prokind = 'p'),
        and window functions (prokind = 'w').
        """
        query = """
            SELECT
                p.proname AS function_name,
                pg_get_function_result(p.oid) AS return_type,
                pg_get_functiondef(p.oid) AS definition
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = %s
              AND p.prokind = 'f'
              AND NOT EXISTS (
                  SELECT 1 FROM pg_depend d
                  WHERE d.objid = p.oid AND d.deptype = 'e'
              )
            ORDER BY p.proname
        """
        with self._conn.cursor() as cur:
            cur.execute(query, (schema_name,))
            functions = {}
            for row in cur.fetchall():
                name, return_type, definition = row
                functions[name] = FunctionSchema(
                    name=name,
                    return_type=return_type,
                    definition=definition,
                )
            return functions

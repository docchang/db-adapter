# DB Adapter Architecture

## Overview

DB Adapter is an async-first Python library providing a Protocol-typed CRUD interface over PostgreSQL (and optionally Supabase). It returns plain dicts, supports multi-profile TOML configuration, live schema introspection/validation/fix, cross-profile data sync, and FK-aware backup/restore. Designed as a standalone library — no ORM, no framework coupling — installable via `uv add` by any Python 3.12+ project.

## Architecture

### System Diagram

```
                        ┌─────────────────────────────────────────────┐
                        │              Consumer Application            │
                        │  (Mission Control, Video Professor, etc.)    │
                        └───────────┬─────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────────┐
                    │         db_adapter package         │
                    │                                    │
                    │  ┌──────────────────────────────┐  │
                    │  │        CLI (Layer 5)          │  │
                    │  │  asyncio.run() wrapper        │  │
                    │  │  connect│status│fix│sync│...  │  │
                    │  └────────────┬──────────────────┘  │
                    │               │                     │
                    │  ┌────────────┴──────────────────┐  │
                    │  │     Factory (Layer 3)          │  │
                    │  │  Profile resolution            │  │
                    │  │  connect_and_validate()        │  │
                    │  │  get_adapter()                 │  │
                    │  └──┬─────────┬──────────────┬───┘  │
                    │     │         │              │       │
                    │     ▼         ▼              ▼       │
                    │  ┌──────┐ ┌──────────┐ ┌─────────┐  │
                    │  │Config│ │  Schema  │ │ Backup  │  │
                    │  │(L 2) │ │  (L 4)   │ │ (L 5)   │  │
                    │  │      │ │          │ │         │  │
                    │  │TOML  │ │Introspec.│ │JSON     │  │
                    │  │loader│ │Comparator│ │backup/  │  │
                    │  │models│ │Fix       │ │restore  │  │
                    │  │      │ │Sync      │ │FK remap │  │
                    │  └──────┘ └────┬─────┘ └────┬────┘  │
                    │                │            │        │
                    │  ┌─────────────┴────────────┴────┐  │
                    │  │      Adapters (Layer 1)        │  │
                    │  │  DatabaseClient Protocol       │  │
                    │  │  ┌──────────┐ ┌────────────┐  │  │
                    │  │  │AsyncPG   │ │AsyncSupabase│  │  │
                    │  │  │Adapter   │ │Adapter      │  │  │
                    │  │  └────┬─────┘ └──────┬─────┘  │  │
                    │  └───────┼──────────────┼────────┘  │
                    └──────────┼──────────────┼───────────┘
                               │              │
                    ┌──────────┴──┐    ┌──────┴───────┐
                    │ PostgreSQL  │    │   Supabase   │
                    │ (asyncpg +  │    │  (async REST │
                    │  psycopg)   │    │   client)    │
                    └─────────────┘    └──────────────┘
```

### Components

#### Adapters (Layer 1)

- **Purpose**: Async CRUD operations over PostgreSQL or Supabase. All methods return plain dicts.
- **Inputs**: Table name, column strings, filter dicts, data dicts
- **Outputs**: `list[dict]` for select, `dict` for insert/update, `None` for delete
- **Dependencies**: `asyncpg` (via SQLAlchemy async engine) for Postgres; `supabase` async client for Supabase

The `DatabaseClient` Protocol defines the contract:
- `async select(table, columns, filters?, order_by?) -> list[dict]`
- `async insert(table, data) -> dict`
- `async update(table, data, filters) -> dict`
- `async delete(table, filters) -> None`
- `async close() -> None`

`AsyncPostgresAdapter` and `AsyncSupabaseAdapter` implement this structurally (no inheritance). JSONB column handling is a constructor parameter, not a class constant.

#### Config (Layer 2)

- **Purpose**: Multi-profile database configuration via TOML
- **Inputs**: `db.toml` file path
- **Outputs**: `DatabaseConfig` with named `DatabaseProfile` entries
- **Dependencies**: `pydantic` for model validation, `tomllib` for TOML parsing

Each profile specifies a connection URL, optional password, description, and provider type (`postgres` or `supabase`). The consumer creates a `db.toml` in their project root:

```toml
[schema]
schema_file = "schema.sql"
validate_on_connect = true

[profiles.local]
url = "postgresql://user:pass@localhost:5432/mydb"
description = "Local development"

[profiles.production]
url = "postgresql://user:[YOUR-PASSWORD]@host:5432/mydb"
db_password = "DB_PASSWORD"  # env var name
description = "Production RDS"
provider = "postgres"
```

#### Factory (Layer 3)

- **Purpose**: Profile resolution, adapter creation, and schema validation orchestration
- **Inputs**: Profile name (from env var, lock file, or explicit argument), optional `database_url` for direct mode
- **Outputs**: Validated `DatabaseClient` adapter instance
- **Dependencies**: Config (profile lookup), Schema (validation), Adapters (instantiation)

Profile resolution priority:
1. Explicit `profile_name` argument
2. `{PREFIX}_DB_PROFILE` env var (prefix configurable, default: `DB_PROFILE`)
3. `.db-profile` lock file (written after successful validation)
4. `{PREFIX}_DATABASE_URL` env var (direct mode, skips profile system)

`connect_and_validate()` introspects the live database, validates schema against caller-provided expected columns, writes the lock file on success, and returns a `ConnectionResult`. `get_adapter()` returns the cached adapter.

#### Schema (Layer 4)

- **Purpose**: Live schema introspection, validation, drift repair, and cross-profile data sync
- **Inputs**: Database connection URL, caller-provided expected schema, caller-provided column definitions
- **Outputs**: `DatabaseSchema` (full introspection), `SchemaValidationResult` (drift report), `FixPlan` / `SyncResult`
- **Dependencies**: `psycopg` (async connection for introspection), Adapters (for sync operations)

Four subcomponents:

- **Introspector**: Async context manager using `psycopg.AsyncConnection`. Queries `information_schema` and `pg_catalog` to extract tables, columns, constraints, indexes, triggers, and functions. Returns structured `DatabaseSchema` or lightweight column-name sets for validation.
- **Comparator**: Pure function (no I/O, stays sync). Takes `actual_columns` and `expected_columns` as `dict[str, set[str]]`, performs set operations to report missing/extra tables and columns.
- **Fix**: Generates repair plans from validation results. Single missing column uses safe `ALTER TABLE ADD COLUMN`. Multiple missing columns trigger `DROP + CREATE` (with backup first). Column definitions provided by caller (not hardcoded).
- **Sync**: Compares data between two profiles and optionally syncs records. Consumer declares which tables to sync and how to resolve identity (slug fields).

#### Backup (Layer 5)

- **Purpose**: JSON-based backup/restore with declarative table hierarchy and FK ID remapping
- **Inputs**: `BackupSchema` (table definitions with FK relationships), adapter instance, backup file path
- **Outputs**: JSON backup file (backup), restore summary with insert/skip/fail counts (restore)
- **Dependencies**: Adapters (data access)

The consumer declares their table hierarchy via `BackupSchema`:

```
BackupSchema
  └── TableDef("projects", pk="id", slug_field="slug", user_field="user_id")
  └── TableDef("milestones", parent=FK("projects","project_id"), ...)
  └── TableDef("tasks", parent=FK("projects","project_id"),
               optional_refs=[FK("milestones","milestone_id")])
```

Tables are ordered by dependency (parents first). During restore, FK IDs from the source database are remapped to destination IDs by matching on slug fields. Required FKs (`parent`) cause record skip if unresolvable; optional FKs (`optional_refs`) are set to NULL.

Restore modes: `skip` (ignore duplicates), `overwrite` (replace existing), `fail` (error on duplicate).

#### CLI (Layer 5)

- **Purpose**: Command-line interface for database operations
- **Inputs**: Shell commands and flags
- **Outputs**: Rich-formatted terminal output (tables, panels, status)
- **Dependencies**: All other layers, `rich` for formatting

Commands are sync from the user's perspective; internally they wrap async calls with `asyncio.run()`. Entry point: `db-adapter <command>`.

## Data Model

### Core Entities

| Entity | Purpose | Key Fields |
|--------|---------|------------|
| `DatabaseProfile` | Single database connection configuration | url, description, db_password, provider |
| `DatabaseConfig` | Multi-profile configuration container | profiles (dict), schema_file, validate_on_connect |
| `DatabaseSchema` | Full introspection result of a live database | tables (dict of TableSchema), functions |
| `TableSchema` | Single table's full schema | name, columns, constraints, indexes, triggers |
| `SchemaValidationResult` | Drift report between expected and actual | valid, missing_tables, missing_columns, extra_tables |
| `ConnectionResult` | Outcome of connect-and-validate | success, profile_name, schema_valid, schema_report, error |
| `FixPlan` | Planned schema repairs | profile_name, missing_tables, missing_columns, tables_to_recreate |
| `BackupSchema` | Declarative table hierarchy for backup/restore | tables (list of TableDef, ordered by dependency) |
| `TableDef` | Single table's backup metadata | name, pk, slug_field, user_field, parent FK, optional_refs |

### Relationships

- `DatabaseConfig` contains many `DatabaseProfile` entries (keyed by profile name)
- `DatabaseSchema` contains many `TableSchema` entries (keyed by table name)
- `TableSchema` contains many `ColumnSchema`, `ConstraintSchema`, `IndexSchema`, `TriggerSchema`
- `BackupSchema` contains ordered `TableDef` entries; each `TableDef` references parent/optional `ForeignKey` pointing to other table names
- `SchemaValidationResult` contains `ColumnDiff` entries for each mismatch

**Note**: These are library models, not database tables. The library operates on the consumer's database tables — it has no tables of its own.

## Data Flow

### Flow 1: CRUD Operation (Primary Path)

```
1. Consumer calls: await adapter.select("users", "id, name", filters={"active": True})
2. AsyncPostgresAdapter builds parameterized SQL: SELECT id, name FROM users WHERE active = :active
3. SQLAlchemy async engine acquires connection from pool
4. asyncpg executes query against PostgreSQL
5. Result rows mapped to list of dicts (JSONB columns auto-deserialized)
6. Connection returned to pool
7. list[dict] returned to consumer
```

### Flow 2: Connect and Validate

```
1. Consumer calls: result = await connect_and_validate(profile_name="production")
2. Factory resolves profile from db.toml via Config loader
3. Password placeholder resolved from env var (if [YOUR-PASSWORD] pattern)
4. SchemaIntrospector opens async psycopg connection to database
5. Introspector queries information_schema for actual column names
6. Comparator compares actual vs caller-provided expected columns (set operations)
7. If valid: .db-profile lock file written, adapter created and cached
8. ConnectionResult returned with schema report
9. Subsequent get_adapter() calls return cached adapter
```

### Flow 3: Backup and Restore with FK Remapping

```
Backup:
1. Consumer provides BackupSchema and adapter
2. For each TableDef (in dependency order): SELECT * WHERE user_field = user_id
3. Records serialized to JSON with metadata (timestamp, version, provider)
4. Written to output file

Restore:
1. Load JSON backup, iterate tables in dependency order
2. For each record in parent table (e.g., projects):
   - Check if slug exists in destination → skip/overwrite/fail per mode
   - Insert record, capture new ID
   - Store ID mapping: source_id → dest_id
3. For each record in child table (e.g., milestones):
   - Remap parent FK: source project_id → dest project_id (via mapping)
   - Remap optional refs: source milestone_id → dest milestone_id (or NULL)
   - Insert record with remapped FKs
4. Return summary with counts per table
```

### Flow 4: Schema Fix

```
1. connect_and_validate() reports missing columns/tables
2. generate_fix_plan() categorizes drift:
   - 1 missing column → ALTER TABLE ADD COLUMN (safe)
   - 2+ missing columns → DROP + CREATE table (destructive, backup first)
   - Missing table → CREATE TABLE from schema.sql
3. apply_fixes(confirm=True):
   a. Backup affected tables via backup layer
   b. Execute CREATE for missing tables
   c. Execute DROP + CREATE for tables with 2+ missing columns
   d. Execute ALTER for single missing columns
   e. Restore data into recreated tables (FK remapping handles ID changes)
   f. Re-validate to confirm fix
```

## Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Async PostgreSQL driver | `asyncpg` | Fastest Python async PG driver; SQLAlchemy's recommended async backend |
| SQL execution + pooling | `sqlalchemy[asyncio]` | Mature connection pooling, parameterized queries, async engine support. Using Core only (no ORM). |
| Schema introspection | `psycopg[binary]` | Direct access to `information_schema` and `pg_catalog` via async cursor. Needed because SQLAlchemy doesn't expose raw catalog queries cleanly. |
| Models + validation | `pydantic` v2 | Already used for config/schema models; fast validation, serialization |
| Config format | TOML (`tomllib`) | Human-readable, stdlib in Python 3.11+. Natural fit for profile-based config. |
| CLI output | `rich` | Formatted tables, panels, progress bars with zero boilerplate |
| Supabase (optional) | `supabase` | Supabase is Postgres under the hood. Optional extra for projects using Supabase hosting. |
| Testing | `pytest` + `pytest-asyncio` | Standard async test framework |
| Package manager | `uv` | Fast Python package management. Library distributed via git-based install. |

**Why two PostgreSQL drivers?** `asyncpg` (via SQLAlchemy) handles CRUD operations with connection pooling. `psycopg` handles schema introspection because it provides direct cursor access to `information_schema` and `pg_catalog` system tables, which SQLAlchemy Core abstracts away. Both support async. They connect to the same database but serve different purposes.

## Integration Points

### PostgreSQL Database

- **Type**: Network protocol (libpq/asyncpg wire protocol)
- **Purpose**: Primary data store for all CRUD operations and schema introspection
- **Contract**: Standard PostgreSQL 14+ with `information_schema` and `pg_catalog` access. JSONB column support required for JSONB features.
- **Fallback**: Connection pool retries via `pool_pre_ping=True`. Connect timeout of 5s. No automatic failover (consumer manages replicas if needed).

### Supabase (Optional)

- **Type**: REST API (supabase-py async client)
- **Purpose**: Alternative adapter for projects hosted on Supabase
- **Contract**: Supabase project URL + service key. PostgREST API for CRUD.
- **Fallback**: Isolated behind Protocol interface. If Supabase is unavailable, consumer switches to direct PostgreSQL adapter with same code.

### Consumer Application (Mission Control, etc.)

- **Type**: Python import (`from db_adapter import ...`)
- **Purpose**: Consumer provides expected schema, table hierarchy, and column definitions. Library provides CRUD, validation, and backup/restore.
- **Contract**: Consumer installs via `uv add`, provides `db.toml` for multi-profile setup or passes `database_url` directly. All methods are async — consumer must run in async context or wrap with `asyncio.run()`.
- **Fallback**: N/A — library is a dependency, not a service.

### Filesystem

- **Type**: Local filesystem I/O
- **Purpose**: `db.toml` config files, `.db-profile` lock file, `schema.sql` reference files, JSON backup files
- **Contract**: Read/write access to project directory. Lock file written to configurable path (defaults to project root).
- **Fallback**: Missing config files raise clear errors with guidance. Lock file absence triggers profile resolution from env vars.

## Security Considerations

**Philosophy**: Production-grade from day one, but sized for a library (not a service). The library doesn't manage authentication or authorization — it's a database access layer that connects with credentials the consumer provides.

### Authentication & Authorization

- Database credentials come from the consumer (connection URL or env var). Library never stores or generates credentials.
- Password placeholder pattern (`[YOUR-PASSWORD]`) resolved from env var at runtime — passwords never appear in config files.
- No user authentication layer — that's the consumer's responsibility. The library passes through whatever `user_id` the consumer provides for multi-tenant operations.

### Data Protection

- **Sensitive data**: Database connection URLs (contain credentials). Stored only in `db.toml` (consumer manages file permissions) and process memory.
- **In transit**: SSL/TLS to PostgreSQL delegated to connection URL params (`?sslmode=require`). Library doesn't override consumer's SSL settings.
- **At rest**: JSON backup files contain raw database records. Consumer is responsible for encrypting or securing backup files.
- **JSONB serialization**: Input dicts are serialized via `json.dumps()` and parameterized with `CAST(:param AS jsonb)` — no SQL injection risk from JSONB values.

### Known Risks (Acceptable for Library)

- Schema fix `DROP + CREATE` is destructive — mitigated by mandatory `--confirm` flag and automatic backup before fix
- Backup JSON files contain plaintext data — acceptable because consumer controls file storage; document the risk in README
- `.db-profile` lock file could be tampered with — low risk; only affects which profile is used, not credentials

## Observability

**Philosophy**: Library provides structured feedback to the consumer. It does not implement logging infrastructure — the consumer configures Python logging.

### Logging

- Standard Python `logging` module with named loggers per component (`db_adapter.adapters`, `db_adapter.schema`, etc.)
- Consumer configures log level and handlers. Library logs at DEBUG (queries), INFO (connections, validations), WARNING (schema drift), ERROR (connection failures).
- No log output by default (NullHandler) — consumer opts in.

### Monitoring

- Connection pool metrics available via SQLAlchemy engine (`pool.status()`, `pool.size()`, `pool.checkedout()`)
- `test_connection()` method on adapters for health checks
- `SchemaValidationResult.error_count` for schema drift monitoring

### Analytics

- Not applicable — library is a dependency, not a service. Consumer tracks their own usage metrics.

## Key Design Decisions

### Decision 1: Protocol Typing over Base Class Inheritance

- **Context**: Adapters need a shared interface but different implementations (Postgres vs Supabase)
- **Options Considered**: ABC base class, Protocol, duck typing
- **Decision**: `typing.Protocol` — structural subtyping
- **Rationale**: No inheritance coupling. Any class with matching method signatures satisfies the type checker. Consumers can create custom adapters (e.g., mock, in-memory) without importing the library's base class.

### Decision 2: Async-Only (No Sync Wrappers)

- **Context**: Python ecosystem split between sync and async. Providing both doubles the API surface.
- **Options Considered**: Async-only, sync-only, dual API with sync wrappers
- **Decision**: Async-only. CLI wraps with `asyncio.run()` for script usage.
- **Rationale**: Modern Python (3.12+) has mature async. All target consumers (FastMCP, web frameworks) are async. Sync wrappers add maintenance burden and introduce subtle bugs (event loop conflicts). Simple scripts use `asyncio.run()`.

### Decision 3: Dict-Based API (No Model Classes)

- **Context**: ORMs return model instances. Raw drivers return tuples. What should CRUD methods return?
- **Options Considered**: Pydantic models, dataclasses, TypedDicts, plain dicts
- **Decision**: Plain `dict` for all CRUD inputs and outputs
- **Rationale**: Zero ceremony — no model definitions required to start using the library. Consumers can wrap dicts in their own models if they want type safety. Dict-based API means any JSON-like data works out of the box.

### Decision 4: Two PostgreSQL Drivers (asyncpg + psycopg)

- **Context**: Need both CRUD connection pooling and low-level catalog introspection
- **Options Considered**: asyncpg only, psycopg only, both
- **Decision**: `asyncpg` (via SQLAlchemy async engine) for CRUD, `psycopg` for schema introspection
- **Rationale**: SQLAlchemy async engine with asyncpg gives best-in-class connection pooling and parameterized query execution. Schema introspection needs raw cursor access to `pg_catalog` system tables, which psycopg provides cleanly. Both are async-capable. The dependency cost is acceptable — both are standard PostgreSQL drivers.

### Decision 5: Caller-Provided Expected Schema

- **Context**: Schema validation needs to compare actual DB state against expected state. Where does "expected" come from?
- **Options Considered**: Schema.sql parsing, hardcoded in library, caller provides dict, auto-detect from models
- **Decision**: Caller provides `expected_columns: dict[str, set[str]]` to `validate_schema()`
- **Rationale**: Library cannot know what tables/columns the consumer expects. Each project defines its own expected schema (via db_models, constants, or whatever). The comparator is a pure function — expected vs actual set comparison — with no I/O or library-specific assumptions.

### Decision 6: Configurable Env Var Prefix

- **Context**: Multiple projects may use db-adapter on the same machine. Env vars like `DB_PROFILE` would collide.
- **Options Considered**: Fixed prefix (`DB_`), no prefix, configurable prefix
- **Decision**: Configurable prefix via `env_prefix` parameter. Default: no prefix (`DB_PROFILE`, `DATABASE_URL`).
- **Rationale**: Projects set `env_prefix="MC"` to read `MC_DB_PROFILE`, or `env_prefix="VP"` to read `VP_DB_PROFILE`. Default with no prefix matches Heroku/Railway/Render convention (`DATABASE_URL`). Zero config for simple projects, flexible for multi-project environments.

## Constraints & Assumptions

- **Python 3.12+**: Required for `tomllib` stdlib, mature `asyncio`, and `typing.Protocol` features
- **PostgreSQL 14+**: Required for `information_schema` views and `pg_catalog` system tables used by introspection
- **No ORM**: Library operates at the SQL Core level. Consumers wanting model mapping use their own layer on top.
- **Single-process pooling**: Connection pool is per-process. Multi-process deployments each maintain their own pool. Cross-process pooling requires PgBouncer or similar.
- **Lock file is local**: `.db-profile` is a local file, not shared. Each deployment/machine maintains its own validated profile state.
- **Backup format is JSON**: Not streaming — entire backup loaded into memory. Suitable for datasets up to ~100K records per table. Larger datasets should use `pg_dump`.
- **TOML config is file-based**: No remote config server support. Environment-specific configuration via env var overrides on top of TOML profiles.

## Future Considerations

- **PyPI publication**: Start with git-based install for early consumers. Publish to PyPI when API stabilizes and first external consumer (Mission Control) is integrated.
- **DATABASE_URL convention**: Support bare `DATABASE_URL` env var (Heroku/Railway/Render pattern) as a zero-config fallback when no `db.toml` or profile env var is set.
- **Connection pool observability**: Expose pool metrics (size, checked-out, overflow) via a structured API for consumers to integrate with their monitoring.
- **Schema.sql parsing**: Optionally parse a `schema.sql` file to derive expected columns, as an alternative to caller-provided dicts. Useful for projects that maintain a canonical schema file.
- **Batch operations**: `insert_many()` and `update_many()` methods for bulk operations using `executemany()` or `COPY`.
- **Transaction support**: Explicit transaction context manager (`async with adapter.transaction():`) for multi-statement atomicity beyond single CRUD calls.

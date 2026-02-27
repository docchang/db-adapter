# Core

**Status**: Planning
**Parent Document**: [Roadmap](./db-adapter-roadmap.md)
**Architecture Reference**: [Architecture Doc](./db-adapter-architecture.md)

---

## Executive Summary

This milestone transforms db-adapter from a raw copy of Mission Control sync code into a standalone, async-first Python library with zero external coupling. The codebase currently has broken imports (bare `from adapters import ...` instead of `from db_adapter.adapters import ...`), duplicate model files (identical `config/models.py` and `schema/models.py`), MC-specific hardcoded constants (`JSONB_COLUMNS`, `COLUMN_DEFINITIONS`, table names), MC-coupled imports (`fastmcp`, `creational.common`, `mcp.server`), and sync-only implementations throughout all 5 layers.

Core systematically addresses every coupling point across 4 phases: fix imports, remove MC-specific code, convert all layers to async, and build a test suite. The result is a library that any Python 3.12+ project can install and import — `from db_adapter import AsyncPostgresAdapter` — without pulling in any Mission Control dependencies.

**Key Principle**: Ship the right API from day one — decouple and convert to async in one milestone so the public interface is correct before any consumer depends on it.

---

## Goal

Extract db-adapter into a fully standalone, async-first library with zero Mission Control coupling. This comes first because nothing else matters if the library can't be installed and imported independently. The current codebase is a direct sync copy of MC code with broken imports, duplicate models, hardcoded constants, and MC-specific logic throughout — Core transforms it into a clean, tested, async library.

**What This Milestone Proves**:
- Library is installable via `uv add` in a clean virtual environment with no MC dependencies
- All CRUD, schema, and backup operations work asynchronously
- Protocol typing enables structural adapter implementation (no inheritance needed)
- Configurable constructors replace all hardcoded MC constants
- Caller-provided schemas replace all MC-specific imports

**What This Milestone Does NOT Include**:
- First consumer adoption (Mission Control integration comes in a later milestone)
- CLI unification (backup commands remain separate entry point; unified in later milestone)
- PyPI publication (git-based install only)
- Advanced features: batch operations (`insert_many`), transaction context manager, `DATABASE_URL` zero-config fallback
- Integration tests against a live PostgreSQL database (unit tests with mocks only; live DB testing comes with consumer adoption)

---

## Architecture Overview

### High-Level System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                      CORE MILESTONE SCOPE                             │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Current State (Broken)              Target State (Working)           │
│  ═══════════════════════             ═══════════════════════          │
│                                                                       │
│  from adapters import ...     →      from db_adapter.adapters ...     │
│  config/models.py  ═══╗      →      config/models.py (config only)   │
│  schema/models.py  ═══╝ dup  →      schema/models.py (schema only)   │
│  def select()             →      async def select()              │
│  JSONB_COLUMNS = {"risks"}    →      __init__(jsonb_columns=[...])    │
│  from schema.db_models import →      validate_schema(actual, expected)│
│  from db import get_settings  →      (removed — no Settings class)    │
│  MC_DB_PROFILE env var        →      {prefix}_DB_PROFILE configurable │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │            Target Package Structure                          │     │
│  │                                                              │     │
│  │  db_adapter/                                                 │     │
│  │  ├── __init__.py          # Exports: AsyncPostgresAdapter,  │     │
│  │  │                        #   DatabaseClient, get_adapter,   │     │
│  │  │                        #   connect_and_validate           │     │
│  │  ├── adapters/                                               │     │
│  │  │   ├── base.py          # DatabaseClient Protocol (async)  │     │
│  │  │   ├── postgres.py      # AsyncPostgresAdapter             │     │
│  │  │   └── supabase.py      # AsyncSupabaseAdapter             │     │
│  │  ├── config/                                                 │     │
│  │  │   ├── models.py        # DatabaseProfile, DatabaseConfig  │     │
│  │  │   └── loader.py        # load_db_config() TOML parser    │     │
│  │  ├── factory.py           # get_adapter(), connect_and_...() │     │
│  │  ├── schema/                                                 │     │
│  │  │   ├── models.py        # Introspection + validation models│     │
│  │  │   ├── introspector.py  # Async SchemaIntrospector         │     │
│  │  │   ├── comparator.py    # validate_schema(actual, expected)│     │
│  │  │   ├── fix.py           # Caller-provided column defs      │     │
│  │  │   └── sync.py          # Caller-declared table list       │     │
│  │  ├── backup/                                                 │     │
│  │  │   ├── models.py        # BackupSchema, TableDef, FK       │     │
│  │  │   └── backup_restore.py# BackupSchema-driven async ops   │     │
│  │  └── cli/                                                    │     │
│  │      ├── __init__.py      # Main CLI (asyncio.run wrappers)  │     │
│  │      └── backup.py        # Backup CLI (separate for now)    │     │
│  │                                                              │     │
│  │  Zero imports from: fastmcp, creational.common, mcp.*        │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

**Runtime**:
- Python 3.12+: `tomllib` stdlib, mature `asyncio`, `typing.Protocol`

**Database Drivers**:
- `sqlalchemy[asyncio]` >= 2.0: Async engine, connection pooling, parameterized SQL execution (Core only, no ORM)
- `asyncpg` >= 0.30: Async PostgreSQL wire protocol driver (SQLAlchemy's async backend)
- `psycopg[binary]` >= 3.0: Async cursor access to `information_schema` / `pg_catalog` for schema introspection

**Libraries**:
- `pydantic` >= 2.0: Model validation and serialization for config, schema, backup models
- `rich` >= 13.0: CLI output formatting (tables, panels, status indicators)

**Optional**:
- `supabase` >= 2.0: AsyncSupabaseAdapter (optional install extra)

**Dev**:
- `pytest` >= 8.0: Test framework
- `pytest-asyncio` >= 0.24: Async test support

**Cost Structure**:
- Infrastructure cost: $0 — this is a library, not a service
- Dependencies: All open source, no paid APIs
- Distribution: Git-based install (no PyPI costs until later milestone)

---

## Core Components Design

### 1. Async Adapter Layer

**Purpose**: Provide the fundamental async CRUD interface that every other layer depends on. The `DatabaseClient` Protocol defines the contract; `AsyncPostgresAdapter` and `AsyncSupabaseAdapter` implement it structurally.

**Features**:
- All 5 Protocol methods are `async def` (`select`, `insert`, `update`, `delete`, `close`)
- `AsyncPostgresAdapter` uses SQLAlchemy `create_async_engine` with `asyncpg` backend
- Configurable JSONB column handling via constructor parameter (not class constant)
- Configurable connection pool parameters (pool_size, max_overflow, pool_recycle, connect_timeout)
- Value serialization: UUID → string, datetime → ISO format, consistent with Pydantic expectations
- `AsyncSupabaseAdapter` uses `acreate_client()` with lazy initialization
- `test_connection()` async health check method

**System Flow**:
```
Consumer calls await adapter.select("users", "id, name", filters={"active": True})
  ↓
AsyncPostgresAdapter builds parameterized SQL text
  ↓
Check JSONB columns → serialize matching values via json.dumps() + CAST AS jsonb
  ↓
async with engine.connect() → acquires connection from pool
  ↓
await conn.execute(text(sql), params) → asyncpg executes against PostgreSQL
  ↓
Map CursorResult rows to list[dict] (JSONB auto-deserialized by driver)
  ↓
Connection returned to pool
  ↓
list[dict] returned to consumer
```

**Technical Design**:
- URL conversion: `postgresql://` → `postgresql+asyncpg://` for SQLAlchemy async engine
- Engine factory function `create_async_engine_pooled()` with configurable pool params and defaults: `pool_size=5`, `max_overflow=10`, `pool_pre_ping=True`, `pool_recycle=300`, `connect_timeout=5`
- JSONB serialization: On insert/update, values for columns in `_jsonb_columns` frozenset are `json.dumps()`'d and use `CAST(:param AS jsonb)` placeholder. On select, PostgreSQL returns JSONB as native Python objects (no deserialization needed).
- Metadata field filtering: Insert/update strip keys prefixed with `_` (internal metadata, not DB columns)
- `AsyncSupabaseAdapter` lazy client: `_get_client()` calls `acreate_client()` on first use, caches for reuse

**Integration Points**:
- **SQLAlchemy async engine**: Connection pooling, `text()` for parameterized SQL, `CursorResult` for row mapping
- **asyncpg**: Wire protocol driver — SQLAlchemy delegates actual PG communication to asyncpg
- **supabase-py async client**: PostgREST query builder for CRUD (optional extra)

### 2. Configuration & Factory

**Purpose**: Load multi-profile database configuration from TOML, resolve which profile to use, create and cache the appropriate adapter instance, and orchestrate schema validation during connection.

**Features**:
- TOML config parsing (`db.toml`) with profile and schema sections
- Password placeholder resolution: `[YOUR-PASSWORD]` in URL replaced with value from env var named in `db_password` field
- Configurable env var prefix (default: no prefix → `DB_PROFILE`, `DATABASE_URL`)
- Profile lock file (`.db-profile`) written after successful validation, read on subsequent `get_adapter()` calls
- Direct mode: skip profile system entirely with explicit `database_url` parameter
- Profile resolution priority: explicit arg → env var → lock file → direct URL env var

**System Flow**:
```
Consumer calls await connect_and_validate(profile_name="production")
  ↓
Factory loads db.toml via Config loader → DatabaseConfig
  ↓
Resolve profile: explicit arg > {prefix}_DB_PROFILE env > .db-profile lock file
  ↓
Password placeholder substitution from env var
  ↓
Introspect live DB schema (via SchemaIntrospector)
  ↓
Compare actual vs caller-provided expected columns (via comparator)
  ↓
If valid: write .db-profile lock, create adapter, cache it
  ↓
Return ConnectionResult with schema report

Consumer calls await get_adapter()
  ↓
Return cached adapter (or raise ProfileNotFoundError)
```

**Technical Design**:
- Config models in `config/models.py`: `DatabaseProfile` (url, description, db_password, provider) and `DatabaseConfig` (profiles dict, schema_file, validate_on_connect)
- `load_db_config(config_path)` uses `tomllib` to parse TOML; default path is caller's project root (not inside package)
- Factory maintains module-level `_adapter` cache; `get_adapter()` returns it or raises
- `connect_and_validate()` accepts optional `expected_columns` parameter — if provided, validates; if None, skips validation
- Lock file path configurable (default: `.db-profile` in current working directory)
- `ProfileNotFoundError` raised when no profile can be resolved from any source

**Integration Points**:
- **Config loader**: Reads `db.toml`, returns `DatabaseConfig`
- **SchemaIntrospector**: Introspects live DB to get actual columns
- **Comparator**: Validates actual vs expected columns
- **Adapters**: Creates `AsyncPostgresAdapter` or `AsyncSupabaseAdapter` based on profile's `provider` field

### 3. Schema Management

**Purpose**: Introspect live database schema, validate it against expected state, generate repair plans for drift, and sync data between profiles. All operations are async except the comparator (pure function, no I/O).

**Features**:
- **Introspector**: Async context manager (`async with SchemaIntrospector(url) as i:`) using `psycopg.AsyncConnection`. Queries `information_schema.columns`, `information_schema.table_constraints`, `pg_indexes`, `information_schema.triggers`, and `pg_proc` for functions. Returns full `DatabaseSchema` or lightweight `dict[str, set[str]]` column-name sets.
- **Comparator**: Pure sync function `validate_schema(actual, expected)`. Both args are `dict[str, set[str]]`. Set operations find missing tables, missing columns, extra tables. Returns `SchemaValidationResult`.
- **Fix**: Generates `FixPlan` from validation results. Single missing column → `ALTER TABLE ADD COLUMN`. 2+ missing columns → `DROP + CREATE` (with automatic backup). Column definitions provided by caller via dict or schema.sql path.
- **Sync**: Compares data between two profiles and optionally syncs. Consumer declares syncable tables and slug fields. Async operations for data comparison and transfer.

**System Flow (Validation)**:
```
SchemaIntrospector opened with database URL
  ↓
async with psycopg.AsyncConnection.connect(url):
  ↓
Query information_schema.columns (excluding EXCLUDED_TABLES set)
  ↓
Build actual_columns: dict[str, set[str]]  (table_name → column_names)
  ↓
validate_schema(actual_columns, expected_columns)  [pure sync function]
  ↓
Set operations: missing_tables = expected_tables - actual_tables
                missing_cols per table = expected_cols - actual_cols
                extra_tables = actual_tables - expected_tables
  ↓
Return SchemaValidationResult(valid=bool, missing_tables, missing_columns, extra_tables)
```

**System Flow (Fix)**:
```
generate_fix_plan(validation_result, column_definitions, schema_sql_path)
  ↓
For each missing table: extract CREATE TABLE from schema.sql
For each table with 1 missing column: schedule ALTER TABLE ADD COLUMN (from column_definitions)
For each table with 2+ missing columns: schedule DROP + CREATE (backup first)
  ↓
Return FixPlan(missing_tables, missing_columns, tables_to_recreate)
  ↓
apply_fixes(plan, adapter, confirm=True):
  ↓
Backup affected tables → CREATE missing → DROP+CREATE recreated → ALTER single columns → Re-validate
```

**Technical Design**:
- Introspector `EXCLUDED_TABLES` configurable via constructor (default: `{"schema_migrations", "pg_stat_statements", "spatial_ref_sys"}`)
- Introspector normalizes data types: `character varying` → `varchar`, `timestamp with time zone` → `timestamptz`
- Comparator has zero imports beyond stdlib — it's a pure function operating on sets
- Fix strips `NOT NULL` and `PRIMARY KEY` from ALTER ADD COLUMN statements (can't add these to existing tables with data)
- Sync identity resolution: consumer declares `slug_field` per table to match records across profiles

**Integration Points**:
- **psycopg.AsyncConnection**: Raw cursor access to PostgreSQL system catalogs
- **Comparator → Factory**: Called by `connect_and_validate()` during profile connection
- **Fix → Backup**: Backs up affected tables before destructive `DROP + CREATE`
- **Fix → Adapters**: Executes SQL via adapter's engine for ALTER/CREATE/DROP

### 4. Backup/Restore Engine

**Purpose**: Provide JSON-based backup and restore driven entirely by a declarative `BackupSchema`. The consumer defines their table hierarchy, FK relationships, and identity fields. The engine handles serialization, dependency ordering, and FK ID remapping during restore.

**Features**:
- `BackupSchema` with ordered `TableDef` entries (parents before children)
- Each `TableDef` specifies: table name, primary key column, slug field (for identity matching), user field (for multi-tenant filtering), parent FK (required), optional FK refs
- Backup: SELECT records per table, serialize to JSON with metadata (timestamp, version, provider)
- Restore with FK remapping: when inserting child records, remap source FK IDs to destination IDs by matching parent records on slug
- Three restore modes: `skip` (ignore duplicates), `overwrite` (replace existing), `fail` (error on duplicate)
- Backup validation: verify JSON structure matches expected BackupSchema

**System Flow (Restore with FK Remapping)**:
```
Load JSON backup file
  ↓
For each TableDef in BackupSchema (dependency order, parents first):
  ↓
  For each record in backup[table_name]:
    ↓
    Check if record exists in destination (by slug_field match)
    → skip / overwrite / fail based on mode
    ↓
    Remap parent FK:
      source record has project_id=5
      lookup id_mapping["projects"][5] → destination project_id=12
      set record["project_id"] = 12
    ↓
    Remap optional refs:
      source record has milestone_id=8
      if id_mapping["milestones"][8] exists → remap
      else → set to NULL (optional ref)
    ↓
    await adapter.insert(table, record)
    ↓
    Capture new ID → store in id_mapping[table][source_id] = new_id
  ↓
Return RestoreSummary per table: {inserted, skipped, failed, errors}
```

**Technical Design**:
- `BackupSchema.tables` order IS the dependency order — consumer declares parents before children
- ID mapping is per-restore-session: `dict[str, dict[int, int]]` mapping `{table_name: {source_id: dest_id}}`
- Slug matching for identity: on restore, if a record with the same slug exists in destination, its ID is used for remapping child records (even in `skip` mode, the existing ID is captured)
- Backup metadata includes: `created_at`, `version` (format version), `tables` (list of table names), `record_counts`
- JSON backup loaded entirely into memory — suitable for datasets up to ~100K records per table

**Integration Points**:
- **Adapters**: All data access via `DatabaseClient` Protocol (select for backup, insert/update for restore)
- **Schema Fix**: Fix calls backup before destructive operations, then restore afterward
- **BackupSchema models**: `backup/models.py` — already properly designed (generic, no MC coupling)

---

## Implementation Phases

### Phase 1: Foundation Cleanup

**Objective**: Fix all broken imports and eliminate duplicate code so the package can be imported without errors.

**Deliverables**:
- Fix all bare imports across every `.py` file to use `db_adapter.*` package paths:
  - `from adapters import ...` → `from db_adapter.adapters import ...`
  - `from config import ...` → `from db_adapter.config import ...`
  - `from schema.models import ...` → `from db_adapter.schema.models import ...`
  - `from db import ...` → `from db_adapter.factory import ...`
  - `from backup.backup_restore import ...` → `from db_adapter.backup.backup_restore import ...`
- Fix `adapters/__init__.py` import bug: references `postgres_adapter` (old filename) instead of `postgres`
- Consolidate duplicate models:
  - `config/models.py` keeps: `DatabaseProfile`, `DatabaseConfig`
  - `schema/models.py` keeps: All introspection models (`ColumnSchema`, `TableSchema`, `DatabaseSchema`, etc.) + validation models (`ColumnDiff`, `SchemaValidationResult`, `ConnectionResult`)
  - Remove duplicates from whichever file they don't belong in
- Remove MC-specific `Settings` class and `SharedSettings` import from `config/loader.py`
- Remove MC-specific factory functions: `get_dev_user_id()`, `get_user_id_from_ctx()`, `AuthenticationError`, `cleanup_project_all_dbs()`, `cleanup_projects_pattern()`, `reset_client()`
- Remove MC-specific imports: `fastmcp.Context`, `creational.common.config.SharedSettings`, `mcp.server.auth.middleware.auth_context`
- Update `__init__.py` exports to reflect new module paths

**Success Criteria**:
- `python -c "import db_adapter"` succeeds without errors
- `grep -r "from adapters import\|from config import\|from db import\|from schema.models import\|from backup" src/` returns only proper `db_adapter.*` imports
- `grep -r "fastmcp\|creational\.common\|mcp\.server" src/` returns zero matches
- No duplicate model definitions (each model defined in exactly one file)

### Phase 2: Generalization

**Objective**: Replace all MC-specific hardcoded constants and imports with configurable parameters and caller-provided values.

**Deliverables**:
- `AsyncPostgresAdapter.__init__()` accepts `jsonb_columns: list[str] | None = None` parameter; remove class-level `JSONB_COLUMNS = frozenset(["risks"])` constant
- `AsyncPostgresAdapter.__init__()` accepts `**engine_kwargs` for pool configuration overrides
- Rename `create_mc_engine()` to `create_async_engine_pooled()` with configurable params
- `comparator.validate_schema()` signature changes: `validate_schema(actual_columns, expected_columns)` — both args are `dict[str, set[str]]`; remove `from schema.db_models import get_all_expected_columns`
- `fix.py`: Remove `COLUMN_DEFINITIONS` dict (40+ MC-specific entries). `generate_fix_plan()` accepts `column_definitions: dict[str, str]` parameter from caller
- `fix.py`: `generate_fix_plan()` accepts optional `schema_sql_path: Path` for extracting CREATE TABLE statements
- `sync.py`: Replace hardcoded `projects/milestones/tasks` with caller-declared `sync_tables: list[SyncTableDef]` where each entry specifies table name, slug field, and user field
- `backup_restore.py`: `backup_database()` and `restore_database()` accept `BackupSchema` parameter and drive all logic from it (no hardcoded table names)
- `introspector.py`: Constructor accepts `excluded_tables: set[str] | None = None` (default: current hardcoded set)
- `factory.py`: `get_adapter()` and `connect_and_validate()` accept `env_prefix: str | None = None` parameter; reads `{prefix}_DB_PROFILE` / `{prefix}_DATABASE_URL`; default with no prefix reads `DB_PROFILE` / `DATABASE_URL`
- `factory.py`: Remove hardcoded `MC_DB_PROFILE` and `MC_DATABASE_URL` env var names
- `config/loader.py`: `load_db_config()` default path uses caller's working directory, not package directory

**Success Criteria**:
- `grep -r "JSONB_COLUMNS\|COLUMN_DEFINITIONS\|MC_DB_PROFILE\|MC_DATABASE_URL\|get_all_expected_columns\|get_settings\|db_models" src/` returns zero matches (except in comments/docs)
- All hardcoded constants replaced with constructor/function parameters
- Library imports cleanly with no MC-specific dependencies

### Phase 3: Async Conversion

**Objective**: Convert all sync implementations to async, fulfilling the "async-first" architecture.

**Deliverables**:
- `DatabaseClient` Protocol: All 5 method signatures become `async def`
- `AsyncPostgresAdapter`:
  - `create_async_engine_pooled()` returns `AsyncEngine` from `sqlalchemy.ext.asyncio`
  - URL auto-conversion: `postgresql://` → `postgresql+asyncpg://`
  - All CRUD methods use `async with self._engine.connect() as conn:` + `await conn.execute()`
  - `close()` calls `await self._engine.dispose()`
- `AsyncSupabaseAdapter`:
  - Lazy init via `_get_client()` → `await acreate_client(url, key)`
  - All CRUD methods `await` supabase async client calls
  - `close()` no-op (Supabase manages connections)
- `SchemaIntrospector`:
  - `async def __aenter__()` → `await psycopg.AsyncConnection.connect(url)`
  - `async def __aexit__()` → `await self._conn.close()`
  - All query methods (`_get_tables`, `_get_columns`, `_get_constraints`, etc.) become async with `await cursor.execute()` + `await cursor.fetchall()`
  - `introspect()` and `get_column_names()` become `async def`
- `factory.py`:
  - `connect_and_validate()` → `async def`
  - `get_adapter()` → `async def`
  - Lock file I/O remains sync (trivial file reads, not worth async overhead)
- `fix.py`:
  - `generate_fix_plan()` → `async def` (calls async introspector)
  - `apply_fixes()` → `async def` (calls async adapter for SQL execution, async backup/restore)
- `sync.py`:
  - `compare_profiles()` → `async def` (connects to two profiles async)
  - `sync_data()` → `async def` (async data transfer)
- `backup_restore.py`:
  - `backup_database()` → `async def` (async adapter.select for each table)
  - `restore_database()` → `async def` (async adapter.insert for each record)
  - `validate_backup()` stays sync (JSON file parsing, no DB access)
- `cli/__init__.py`:
  - Each command wraps async with `asyncio.run()`: `def cmd_connect(args): return asyncio.run(_async_connect(args))`
  - `cli/backup.py`: Same pattern for backup/restore commands

**Configuration**:
- `pyproject.toml` already lists `sqlalchemy[asyncio]` and `asyncpg` — no dependency changes needed
- `psycopg[binary]` already supports async — no new dependency needed

**Success Criteria**:
- All `DatabaseClient` Protocol methods are `async def`
- `AsyncPostgresAdapter` uses `create_async_engine` (not sync `create_engine`)
- `SchemaIntrospector` uses `psycopg.AsyncConnection` (not sync `psycopg.connect`)
- `factory.connect_and_validate()` and `factory.get_adapter()` are `async def`
- CLI commands successfully wrap async operations with `asyncio.run()`
- `grep -r "create_engine\b" src/ | grep -v "create_async_engine"` returns zero matches
- `grep -r "psycopg\.connect\b" src/` returns zero matches (all converted to async)

### Phase 4: Test Suite

**Objective**: Build comprehensive unit tests that validate every layer without requiring a live database.

**Deliverables**:
- **Adapter tests**: Mock SQLAlchemy async engine; verify SQL text generation for select/insert/update/delete; verify JSONB serialization (dict → `json.dumps` + `CAST AS jsonb`); verify `_` prefix field stripping; verify value serialization (UUID → str, datetime → ISO)
- **Config tests**: TOML parsing with multiple profiles; password placeholder resolution from env var; missing config file error handling; malformed TOML error handling; provider field defaults
- **Factory tests**: Profile resolution priority (explicit > env var > lock file); lock file write/read/clear; configurable env prefix; `ProfileNotFoundError` for missing profile; adapter caching (second `get_adapter()` returns same instance)
- **Comparator tests**: Perfect match (valid=True); missing table; missing column; extra table (warning only); multiple missing columns on same table; empty expected and actual
- **Introspector tests**: Mock `psycopg.AsyncConnection`; verify query structure for tables, columns, constraints; data type normalization (`character varying` → `varchar`); excluded tables filtering
- **Backup model tests**: `BackupSchema` construction; `TableDef` with parent FK; `TableDef` with optional refs; dependency ordering validation
- **Backup/restore tests**: Mock adapter; backup serialization to JSON; restore with FK remapping (verify ID mapping); restore skip/overwrite/fail modes; restore with missing parent FK (skip record)
- **Import test**: Verify `from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter, connect_and_validate` in clean environment
- **Coupling test**: `grep -r` for MC-specific imports returns zero matches (automated in CI)

**Testing**:
- All tests use `pytest-asyncio` for async test functions
- Mock database connections (no live PostgreSQL required)
- Factory tests use tmp directories for lock files and TOML configs
- Comparator tests are pure logic — no mocks needed

**Success Criteria**:
- All tests pass with `uv run pytest`
- Every public API function has at least one test
- Zero MC-coupling verification automated as a test

**Production Launch**:
- Tag version `0.2.0` (current is `0.1.0` — scaffold)
- Update README with async API examples
- Verify `uv add git+ssh://...` installs and imports cleanly from another project

---

## Success Metrics

### Library Independence

**Installable in Clean Environment**:
- Target: `uv add git+ssh://git@github-creational:creational-ai/db-adapter.git` succeeds in empty venv
- Measured: CI job that creates fresh venv, installs, and runs import test
- Why: If the library can't be installed independently, everything else is moot

**Zero MC Coupling**:
- Target: `grep -r "fastmcp\|creational\.common\|mcp\.server\|SharedSettings\|get_settings\|db_models" src/` returns zero matches
- Measured: Automated test in CI
- Why: Any remaining MC import means the library isn't standalone — consumers would need MC installed

**No Duplicate Definitions**:
- Target: Each model class defined in exactly one file
- Measured: Code review; `grep -rn "class DatabaseProfile\|class SchemaValidationResult" src/` returns one match per class
- Why: Duplicate models cause import confusion and divergence risk

### Async Coverage

**Protocol Methods**:
- Target: All 5 `DatabaseClient` methods (`select`, `insert`, `update`, `delete`, `close`) are `async def`
- Measured: Automated test that inspects Protocol method signatures with `inspect.iscoroutinefunction()`
- Why: Protocol is the contract — if it's sync, the entire async architecture is undermined

**Adapter Implementations**:
- Target: Both `AsyncPostgresAdapter` and `AsyncSupabaseAdapter` use async engines/clients
- Measured: `grep -r "create_engine\b" src/ | grep -v "create_async_engine"` returns zero; `AsyncSupabaseAdapter` uses `acreate_client`
- Why: Sync adapters behind an async Protocol would block the event loop

**Schema Introspector**:
- Target: Uses `psycopg.AsyncConnection`, `__aenter__`/`__aexit__`, all query methods are `async def`
- Measured: Automated test inspecting method signatures
- Why: Sync introspection blocks during database queries — unacceptable in async applications

### Code Quality

**Test Coverage**:
- Target: All public API functions have at least one unit test
- Measured: `uv run pytest` passes with all tests green
- Why: Tests catch regressions before any consumer depends on the library

**Configurable Constants**:
- Target: Zero hardcoded MC-specific constants (`JSONB_COLUMNS`, `COLUMN_DEFINITIONS`, `MC_DB_PROFILE`, table names)
- Measured: grep for known hardcoded values returns zero matches
- Why: Hardcoded constants make the library unusable for anyone except MC

---

## Testing Strategy

**Philosophy**: Production-grade unit tests from day one. All tests run without a live database — pure logic and mock-based verification.

### Test Coverage Approach

- **Unit Tests**: Every public function and class method. Adapter SQL generation, JSONB handling, value serialization. Config TOML parsing, password resolution. Factory profile resolution, lock file management. Comparator set logic. Introspector query structure. Backup FK remapping logic.
- **Mock-Based Integration**: Mock `AsyncEngine`, `psycopg.AsyncConnection`, and supabase client to test flows without network I/O. Factory → Config → Introspector → Comparator chain tested with mocks.

### Quality Gates

- All tests pass before any code is merged
- Zero MC coupling grep test passes (automated, not manual)
- Import test passes in clean environment

### What We're NOT Testing (Yet)

- Live database integration tests (requires PostgreSQL instance — deferred to consumer adoption milestone)
- Connection pool behavior under load
- Supabase adapter against real Supabase instance
- CLI end-to-end tests (command execution with real DB)
- Performance benchmarks

---

## Key Outcomes

- **Library installable and importable** without Mission Control or any MC-specific dependencies
  - `from db_adapter import AsyncPostgresAdapter` works in any Python 3.12+ project

- **All layers async** — Protocol, adapters, factory, introspector, fix, sync, backup/restore
  - No sync implementations remain (except comparator, which is pure logic)

- **Configurable constructors** replace all hardcoded MC constants
  - JSONB columns, env prefix, excluded tables, pool params — all configurable

- **Caller-provided schemas** replace all MC-specific imports
  - Expected columns, column definitions, table hierarchy — all provided by consumer

- **Test suite** validates every layer
  - Regressions caught before any consumer depends on the library

- **Ready for first consumer** integration in subsequent milestone

---

## Why Extract-and-Async Together?

**Ship the Right API from Day One**:
- Publishing a sync API that gets replaced by async would break every consumer's code. Doing both in one milestone means the first public API is the correct one.
- Consumers write `await adapter.select(...)` from their first line of code — no migration needed later.

**Incremental Verification Within the Milestone**:
- Phase 1 (imports) and Phase 2 (generalization) produce code that runs and can be manually tested (still sync). Phase 3 (async) converts verified-correct logic. Phase 4 (tests) locks it all down.
- Each phase is independently verifiable, even though they ship together as one milestone.

**Avoid Double-Touch**:
- Separating "decouple" and "async" into two milestones means touching every file twice. Once for decoupling, again for async conversion. Doing it in one pass is more efficient and less error-prone.

---

## Design Decisions & Rationale

### Why Consolidate Models Before Async?

- **Foundation integrity**: If models are duplicated when async conversion starts, it's unclear which file to import from. Fixing this first means every async import path is unambiguous.
- **Diff clarity**: Model consolidation changes are easy to review (move code between files). Mixing them with async conversion would make diffs much harder to read.

**Alternative Considered**: Convert to async first, fix models later (rejected — would create ambiguous imports during the most complex phase).

### Why Constructor Parameters over Config File Settings?

- **Composability**: Constructor params (`jsonb_columns=["risks"]`) are explicit and testable. Config file settings create hidden state that's harder to debug.
- **No file dependency**: A consumer can use `AsyncPostgresAdapter(url, jsonb_columns=["data"])` without any config file. Config files are for multi-profile setups, not required for basic usage.

**Alternative Considered**: JSONB columns in `db.toml` (rejected — mixes connection config with adapter behavior; constructor params keep concerns separate).

### Why Mock-Based Tests Instead of Live DB?

- **Speed**: Mock tests run in milliseconds. Live DB tests need PostgreSQL running, take seconds per test, and flake on CI.
- **Isolation**: Mock tests verify the library's logic (SQL generation, JSONB serialization, set comparisons), not PostgreSQL's behavior. The library trusts PostgreSQL to execute SQL correctly.
- **Scope**: Live DB integration tests prove the library works with a real database — that's the consumer adoption milestone's job, not Core's.

**Alternative Considered**: Docker-based PostgreSQL in CI (rejected for Core — adds CI complexity; appropriate for later milestone when testing real consumer integration).

### Why Keep Comparator Sync?

- **No I/O**: `validate_schema(actual, expected)` takes two dicts and does set operations. There's nothing to `await`. Making it async would add overhead for no benefit.
- **Composability**: Sync functions can be called from async code trivially (`result = validate_schema(actual, expected)` — no `await` needed). The reverse is not true.

**Alternative Considered**: Make everything async for consistency (rejected — unnecessary complexity for a pure function).

---

## Risks & Mitigation

### Risk: Async Conversion Breaks Subtle SQL Logic

**Impact**: HIGH — Incorrect SQL generation would corrupt data
**Probability**: LOW — SQL text generation is string manipulation, not affected by sync/async
**Mitigation**:
- Phase 2 (generalization) verifies SQL logic still works while code is still sync
- Phase 4 (tests) includes SQL generation tests that verify exact query text
- JSONB serialization tested independently of async plumbing
- Fallback: If async conversion introduces SQL bugs, revert Phase 3 and investigate before retrying

### Risk: SQLAlchemy Async Engine Behavioral Differences

**Impact**: MED — Connection pooling or transaction semantics could differ from sync engine
**Probability**: MED — SQLAlchemy async is mature but has known differences (e.g., `greenlet` requirement, connection checkout behavior)
**Mitigation**:
- Use SQLAlchemy's documented async patterns (`async with engine.connect()`, `await conn.execute()`)
- Pin `sqlalchemy[asyncio] >= 2.0` to ensure stable async API
- Mock-based tests verify the library's calls, not SQLAlchemy's behavior
- Fallback: If pool behavior differs, adjust pool configuration (pool_pre_ping, pool_recycle) or switch to explicit connection management

### Risk: psycopg Async API Differences from Sync

**Impact**: MED — Introspection queries could fail or return different result structures
**Probability**: LOW — psycopg3 async API mirrors sync API closely; same cursor interface
**Mitigation**:
- psycopg3's `AsyncConnection` uses identical SQL and cursor methods as sync `Connection`
- Mock tests verify query structure and result mapping
- Fallback: If async psycopg behaves differently, introspector tests will catch it before merge

### Risk: Import Cleanup Misses a Coupling Point

**Impact**: LOW — Library fails to import, caught immediately
**Probability**: MED — Many files with bare imports; easy to miss one
**Mitigation**:
- Automated grep test for known MC-specific patterns runs in CI
- Import test (`python -c "import db_adapter"`) catches any broken import path
- Phase 1 deliverables are independently verifiable before proceeding to Phase 2

---

## Open Questions

### Technical

- **Should `get_adapter()` use a module-level cache or instance-based pattern?**: Current factory uses module-level `_adapter` global. Module-level state is simpler but harder to test and doesn't support multiple adapter instances.
  - Decision: Keep module-level for now (matches existing pattern). Refactor to instance-based if testing or multi-adapter needs arise during implementation.

- **Should `validate_backup()` check BackupSchema compatibility?**: Currently validates JSON structure only. Could also verify that backup tables match the provided BackupSchema.
  - Decision: Add BackupSchema compatibility check. Low effort, high value — catches mismatched backup/schema before restore attempt.

### API Design

- **Should factory expose `create_adapter()` as a separate non-caching function?**: `get_adapter()` caches. Some consumers may want multiple adapter instances (e.g., one per profile for sync operations).
  - Decision: Add `create_adapter(profile_name_or_url)` that creates without caching. `get_adapter()` remains the primary cached path.

- **Should `connect_and_validate()` return the adapter directly instead of `ConnectionResult`?**: Current API requires two calls: `connect_and_validate()` then `get_adapter()`.
  - Decision: Keep `ConnectionResult` return (it carries schema report, error details). Add convenience: `ConnectionResult.adapter` property that returns the cached adapter if connection succeeded.

### Scope

- **How much CLI work belongs in Core vs. later milestone?**: CLI currently works (sync) but needs asyncio.run() wrappers. Backup CLI is separate.
  - Decision: Core converts existing CLI commands to async wrappers. CLI unification (merging backup commands) is explicitly deferred to consumer adoption milestone.

---

## Next Steps

**Immediate** (Start Here):
1. Create task spec breaking Core into atomic implementation tasks
2. Begin Phase 1: Fix all bare imports to `db_adapter.*` paths
3. Fix `adapters/__init__.py` import bug

**After Foundation Cleanup**:
1. Consolidate duplicate models (config vs schema)
2. Remove all MC-specific code (Settings, auth functions, cleanup helpers)
3. Begin Phase 2: Generalize all hardcoded constants to parameters

**Before Milestone Complete**:
1. Run full test suite — all tests passing
2. Verify import in clean environment (`uv add` from another project)
3. Verify zero MC coupling (automated grep)
4. Tag version `0.2.0`

---

## Related Documents

- [Roadmap](./db-adapter-roadmap.md) - Full milestone roadmap (Core → Integration → Distribution)
- [Architecture Doc](./db-adapter-architecture.md) - Complete technical architecture
- [Vision](./reference/db-adapter-vision.md) - Product vision and success metrics
- [Extraction Design](./core-lib-extraction-design.md) - Detailed analysis of every coupling point and async migration plan

---

*Document Status*: Design Complete - Ready for Task Spec
*Last Updated*: February 2026

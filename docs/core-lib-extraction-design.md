# Core-Lib-Extraction Design

> **Purpose**: Analyze and design solutions before implementation planning
>
> **Important**: This task must be self-contained (works independently; doesn't break existing functionality and existing tests)

## Executive Summary

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-02-27T00:00:00-0800 |
| **Task** | Extract and generalize MC-coupled sync code into a standalone async-first db-adapter library |
| **Type** | Refactor |
| **Scope** | All 5 layers: adapters, config, factory, schema, backup/CLI |
| **Code** | NO - This is a design document |
| **Risk Profile** | Standard |
| **Risk Justification** | Greenfield library extraction into a new repo with no consumers yet; all changes are additive and reversible before any downstream adoption. |

**Challenge**: The db-adapter repo contains raw copies of Mission Control sync code with MC-specific imports (`from adapters import ...`, `from db import ...`, `from config import ...`), MC-coupled logic (hardcoded table names, `JSONB_COLUMNS`, `COLUMN_DEFINITIONS`, `get_settings()`, `get_user_id_from_ctx()`), and sync-only implementations that need to become async-first.

**Solution**: Systematically decouple, generalize, and convert all 5 layers to produce a self-contained async-first library with proper `db_adapter.*` package imports, configurable constructor parameters replacing hardcoded constants, caller-provided expected schemas replacing MC-specific `db_models`, and async adapters using `create_async_engine`/`asyncpg`/`psycopg.AsyncConnection`.

---

## Context

### Current State

The db-adapter repo has the target package structure scaffolded (`src/db_adapter/` with all subpackages), but every `.py` file is a direct copy from Mission Control with the following issues:

- **Broken imports**: All modules use bare imports (`from adapters import ...`, `from config import ...`, `from db import ...`, `from schema.models import ...`) that rely on `sys.path` manipulation or MC's source root. None will resolve under the `db_adapter` package.
- **MC-specific coupling in factory.py**: Imports `fastmcp.Context`, `creational.common.config.SharedSettings`, `mcp.server.auth.middleware`; contains `get_user_id_from_ctx()`, `get_dev_user_id()`, `cleanup_project_all_dbs()`, `cleanup_projects_pattern()` -- all MC-specific.
- **MC-specific coupling in config/loader.py**: Imports `creational.common.config.SharedSettings`; contains `Settings(SharedSettings)` class with `service_slug`, `dev_user_id`, `supabase_key`, `base_url` -- all MC-specific.
- **Hardcoded constants in adapters/postgres.py**: `JSONB_COLUMNS = frozenset(["risks"])` is MC-specific. `create_mc_engine()` function name references MC.
- **Sync-only implementations**: All adapters, introspector, factory, backup/restore, and sync use synchronous APIs (`create_engine`, `psycopg.connect`, `engine.connect()`).
- **MC-specific schema coupling**: `comparator.py` imports `from schema.db_models import get_all_expected_columns` (MC module). `fix.py` has hardcoded `COLUMN_DEFINITIONS` dict with MC table/column definitions.
- **MC-specific backup/restore**: `backup_restore.py` hardcodes `projects`, `milestones`, `tasks` table names and their FK relationships. Imports `get_settings()` for `db_provider`.
- **MC-specific sync**: `sync.py` hardcodes `projects`, `milestones`, `tasks` table names and slug resolution logic.
- **MC-specific CLI**: References `python -m schema`, uses `MC_DB_PROFILE` env var, calls MC-coupled functions.
- **Duplicate models**: `config/models.py` and `schema/models.py` contain identical content (both have `DatabaseProfile`, `DatabaseConfig`, validation models, and introspection models).

### Target State

A self-contained, installable async-first Python library where:

- All imports use proper `db_adapter.*` package paths
- Adapters expose async CRUD methods via `AsyncPostgresAdapter` and `AsyncSupabaseAdapter`
- `DatabaseClient` Protocol defines async method signatures
- `JSONB_COLUMNS` is a configurable constructor parameter, not a class constant
- `create_async_engine_pooled()` replaces `create_mc_engine()`
- `SchemaIntrospector` uses `psycopg.AsyncConnection` with `async with` context manager
- `validate_schema(actual, expected)` accepts caller-provided expected columns (no MC import)
- `fix.py` accepts caller-provided column definitions or schema.sql path (no `COLUMN_DEFINITIONS` dict)
- `sync.py` accepts caller-declared table lists (no hardcoded `projects/milestones/tasks`)
- `backup_restore.py` uses `BackupSchema` declarative model for table hierarchy and FK remapping
- Factory supports configurable `env_prefix` for env var names (`DB_PROFILE`, `DATABASE_URL` by default)
- CLI uses `db-adapter` as program name, wraps async with `asyncio.run()`
- No MC-specific code remains (`fastmcp`, `creational.common`, `get_settings`, auth functions, test helpers)
- Models consolidated into appropriate locations (no duplicates)
- `pyproject.toml` entry point works: `uv run db-adapter connect`

```
db-adapter/src/db_adapter/
    __init__.py              # Main exports (AsyncPostgresAdapter, DatabaseClient, get_adapter, etc.)
    factory.py               # get_adapter(), connect_and_validate() -- async, configurable env_prefix
    adapters/
        __init__.py          # Exports
        base.py              # DatabaseClient Protocol (async)
        postgres.py          # AsyncPostgresAdapter (async engine, configurable JSONB)
        supabase.py          # AsyncSupabaseAdapter (async client)
    config/
        __init__.py
        models.py            # DatabaseProfile, DatabaseConfig (config only)
        loader.py            # load_db_config() -- TOML parser, no Settings class
    schema/
        __init__.py
        models.py            # Introspection models + validation result models
        introspector.py      # SchemaIntrospector (async)
        comparator.py        # validate_schema(actual, expected) -- pure logic, sync
        fix.py               # generate_fix_plan(), apply_fixes() -- generic, async
        sync.py              # compare_profiles(), sync_data() -- generic, async
    backup/
        __init__.py
        models.py            # BackupSchema, TableDef, ForeignKey (already done)
        backup_restore.py    # backup_database(), restore_database() -- generic, async
    cli/
        __init__.py          # main() entry point, all commands
        backup.py            # backup/restore/validate-backup subcommands
```

---

## Constraints

- **Scope boundaries**: This design covers converting the existing copied code to a working library. It does NOT cover MC-side migration (updating MC imports to use db-adapter). That is a separate downstream task.
- **Must NOT happen**: No MC-specific imports (`fastmcp`, `creational.common`, `mcp.server.auth`) or MC-specific logic (`get_user_id_from_ctx`, `cleanup_project_all_dbs`, `PROTECTED_PROJECTS`, hardcoded `projects/milestones/tasks`) may remain in the library.
- **Compatibility**: The `DatabaseClient` Protocol's method signatures (parameter names, return types) must be preserved so that consuming projects can structurally type-match. The backup JSON format (version 1.1 structure) must remain compatible.
- **Must NOT happen**: `config/models.py` and `schema/models.py` must not contain duplicate classes. Each model lives in exactly one place.

---

## Analysis

> Each item analyzed independently. No implied order - read in any sequence.

### 1. Fix Package Imports

**What**: Convert all bare module imports (`from adapters import ...`, `from config import ...`, `from db import ...`, `from schema.models import ...`) to proper `db_adapter.*` package imports throughout all source files.

**Why**: The current imports are broken -- they reference MC's source root layout and will fail with `ModuleNotFoundError` when the package is installed via pip/uv. This is the most fundamental issue: nothing works until imports resolve correctly.

**Approach**:

Systematically replace every import statement across all files. The mapping is:

| Current Import | New Import |
|---|---|
| `from adapters import ...` | `from db_adapter.adapters import ...` |
| `from adapters.base import ...` | `from db_adapter.adapters.base import ...` |
| `from adapters.postgres_adapter import ...` | `from db_adapter.adapters.postgres import ...` |
| `from config import ...` | `from db_adapter.config.loader import ...` |
| `from schema.models import ...` | `from db_adapter.schema.models import ...` or `from db_adapter.config.models import ...` |
| `from schema.comparator import ...` | `from db_adapter.schema.comparator import ...` |
| `from schema.introspector import ...` | `from db_adapter.schema.introspector import ...` |
| `from schema.db_models import ...` | REMOVE (MC-specific) |
| `from db import ...` | `from db_adapter.factory import ...` |
| `from backup.backup_restore import ...` | `from db_adapter.backup.backup_restore import ...` |

Files to modify: every `.py` file under `src/db_adapter/`.

Also fix the `adapters/__init__.py` which currently references `adapters.postgres_adapter` (old MC filename) instead of `adapters.postgres` (new filename).

Validation: `python -c "import db_adapter"` succeeds. All internal imports resolve.

---

### 2. Remove MC-Specific Code from Factory

**What**: Strip all Mission Control-specific functions and imports from `factory.py`, leaving only generic profile resolution and adapter creation logic.

**Why**: `factory.py` currently contains `get_user_id_from_ctx()` (FastMCP auth), `get_dev_user_id()` (MC settings), `cleanup_project_all_dbs()`, `cleanup_projects_pattern()` (MC test helpers), and `AuthenticationError` -- none of which belong in a generic database adapter library.

**Approach**:

Remove entirely:
- `from fastmcp import Context` import
- `from config import get_settings, load_db_config` (replace with `from db_adapter.config.loader import load_db_config`)
- `AuthenticationError` class
- `get_dev_user_id()` function
- `get_user_id_from_ctx()` function
- `cleanup_project_all_dbs()` function
- `cleanup_projects_pattern()` function
- `reset_client()` function (test helper; will be replaced by proper async close)

Keep and modify:
- `ProfileNotFoundError` class
- `read_profile_lock()`, `write_profile_lock()`, `clear_profile_lock()` -- update lock file path to be configurable or use CWD
- `get_active_profile_name()` -- make `env_prefix` configurable (default: no prefix, reads `DB_PROFILE`)
- `get_active_profile()` -- keep, update imports
- `_resolve_url()` -- keep
- `connect_and_validate()` -- convert to async, update to accept `expected_columns` parameter
- `get_db_adapter()` -- rename to `get_adapter()`, convert to async

Add:
- `env_prefix` parameter support: `get_adapter(env_prefix="MC")` reads `MC_DB_PROFILE`, `MC_DATABASE_URL`
- `database_url` parameter for direct mode: `get_adapter(database_url="postgresql://...")`
- Profile lock file path relative to CWD (not `Path(__file__).parent`)

Pattern for configurable env prefix:
```python
async def get_adapter(
    env_prefix: str = "",
    database_url: str | None = None,
    jsonb_columns: list[str] | None = None,
) -> DatabaseClient:
    ...
```

Validation: `factory.py` has zero imports from `fastmcp`, `mcp`, or `creational`.

---

### 3. Remove MC-Specific Code from Config Loader

**What**: Strip the `Settings` class (inherits `SharedSettings`), `get_settings()`, and the `creational.common.config` import from `config/loader.py`. Keep only the generic TOML-based `load_db_config()` function.

**Why**: The `Settings` class is MC-specific (contains `service_slug`, `dev_user_id`, `supabase_key`, `base_url`, inherits from a creational-specific base). The library's config layer should only handle database profile configuration via TOML, not application settings.

**Approach**:

Remove from `config/loader.py`:
- `from pydantic import AliasChoices, Field`
- `from creational.common.config import SharedSettings`
- `Settings(SharedSettings)` class entirely
- `get_settings()` function entirely

Keep and modify:
- `load_db_config()` function -- update imports to use `db_adapter.config.models`
- Make `config_path` default to `Path.cwd() / "db.toml"` instead of `Path(__file__).parent / "db.toml"` (library should look in project root, not inside the installed package)

Pattern:
```python
def load_db_config(config_path: Path | None = None) -> DatabaseConfig:
    if config_path is None:
        config_path = Path.cwd() / "db.toml"
    ...
```

Validation: `config/loader.py` has zero imports from `creational` or `pydantic` field aliases.

---

### 4. Consolidate Duplicate Models

**What**: Resolve the duplication between `config/models.py` and `schema/models.py` which currently contain identical classes (`DatabaseProfile`, `DatabaseConfig`, `ColumnDiff`, `SchemaValidationResult`, `ConnectionResult`, and all introspection models).

**Why**: Duplicate model definitions create confusion about which to import and risk divergence. Each model must live in exactly one canonical location.

**Approach**:

Split models by domain:

**`config/models.py`** -- configuration and connection models:
- `DatabaseProfile`
- `DatabaseConfig`

**`schema/models.py`** -- schema introspection, validation, and connection result models:
- `ColumnSchema`, `ConstraintSchema`, `IndexSchema`, `TriggerSchema`, `FunctionSchema`
- `TableSchema`, `DatabaseSchema`
- `ColumnDiff`, `SchemaValidationResult`
- `ConnectionResult`

Update all imports across the codebase to point to the canonical location. The `__init__.py` files for each subpackage should re-export their public models.

Validation: No class is defined in more than one file. `grep -r "class DatabaseProfile" src/` returns exactly one result.

---

### 5. Convert Adapters to Async

**What**: Convert `DatabaseClient` Protocol, `PostgresAdapter`, and `SupabaseAdapter` from sync to async implementations.

**Why**: The extraction plan specifies async-first architecture. All consumers (MC with FastMCP 2.0, future projects) will use async. This is the core value proposition of the library.

**Approach**:

**`adapters/base.py` -- `DatabaseClient` Protocol**:
All methods become `async def`:
```python
class DatabaseClient(Protocol):
    async def select(self, table, columns, filters, order_by) -> list[dict]: ...
    async def insert(self, table, data) -> dict: ...
    async def update(self, table, data, filters) -> dict: ...
    async def delete(self, table, filters) -> None: ...
    async def close(self) -> None: ...
```

**`adapters/postgres.py` -- `AsyncPostgresAdapter`**:
- Rename class from `PostgresAdapter` to `AsyncPostgresAdapter`
- Rename `create_mc_engine()` to `create_async_engine_pooled()`
- Replace `sqlalchemy.create_engine` with `sqlalchemy.ext.asyncio.create_async_engine`
- URL rewrite: `postgresql://` to `postgresql+asyncpg://`
- Replace `engine.connect()` with `async_engine.connect()` (async context manager)
- Replace `engine.begin()` with `async_engine.begin()` (async context manager)
- `JSONB_COLUMNS` becomes constructor parameter: `__init__(self, database_url, jsonb_columns=None, **engine_kwargs)`
- `engine.dispose()` becomes `await engine.dispose()`
- Add `test_connection()` as async

Pattern:
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

class AsyncPostgresAdapter:
    def __init__(self, database_url: str, jsonb_columns: list[str] | None = None, **engine_kwargs):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        self._engine: AsyncEngine = create_async_engine_pooled(async_url, **engine_kwargs)
        self._jsonb_columns = frozenset(jsonb_columns or [])

    async def select(self, table, columns, filters=None, order_by=None) -> list[dict]:
        async with self._engine.connect() as conn:
            result = await conn.execute(query, params)
            ...
```

**`adapters/supabase.py` -- `AsyncSupabaseAdapter`**:
- Rename class from `SupabaseAdapter` to `AsyncSupabaseAdapter`
- Replace `supabase.Client` / `create_client` with `supabase._async.client.AsyncClient` / `create_async_client`
- Use lazy initialization pattern since `create_async_client` is async (cannot call in `__init__`)
- All methods become `async def`

Pattern:
```python
from supabase._async.client import AsyncClient, create_async_client

class AsyncSupabaseAdapter:
    def __init__(self, url: str, key: str):
        self._url = url
        self._key = key
        self._client: AsyncClient | None = None

    async def _get_client(self) -> AsyncClient:
        if self._client is None:
            self._client = await create_async_client(self._url, self._key)
        return self._client
```

**`adapters/__init__.py`** -- update exports:
```python
from db_adapter.adapters.base import DatabaseClient
from db_adapter.adapters.postgres import AsyncPostgresAdapter
```

Validation: All adapter methods are `async def`. `create_engine` does not appear anywhere. `asyncpg` is used as the SQLAlchemy driver.

---

### 6. Convert Schema Introspector to Async

**What**: Convert `SchemaIntrospector` from sync `psycopg.connect()` with `__enter__`/`__exit__` to async `psycopg.AsyncConnection.connect()` with `__aenter__`/`__aexit__`.

**Why**: The introspector is called during `connect_and_validate()` which will become async. Using sync psycopg in an async context would block the event loop.

**Approach**:

- Replace `psycopg.connect()` with `await psycopg.AsyncConnection.connect()`
- Replace `__enter__`/`__exit__` with `__aenter__`/`__aexit__`
- Replace `self._conn.cursor()` context managers with async cursor usage
- All query methods (`introspect`, `get_column_names`, `_get_tables`, `_get_columns`, etc.) become `async def`
- `EXCLUDED_TABLES` becomes a configurable constructor parameter with sensible defaults

Pattern:
```python
import psycopg

class SchemaIntrospector:
    EXCLUDED_TABLES_DEFAULT = {"schema_migrations", "pg_stat_statements", "spatial_ref_sys"}

    def __init__(self, database_url: str, excluded_tables: set[str] | None = None):
        self._database_url = database_url
        self._excluded_tables = excluded_tables if excluded_tables is not None else self.EXCLUDED_TABLES_DEFAULT
        self._conn: psycopg.AsyncConnection | None = None

    async def __aenter__(self) -> "SchemaIntrospector":
        url = self._database_url
        if "connect_timeout" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}connect_timeout=10"
        self._conn = await psycopg.AsyncConnection.connect(url)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def introspect(self, schema_name: str = "public") -> DatabaseSchema: ...
    async def get_column_names(self, schema_name: str = "public") -> dict[str, set[str]]: ...
```

Validation: No sync `psycopg.connect()` calls remain. `__enter__`/`__exit__` replaced with async equivalents.

---

### 7. Decouple Schema Comparator

**What**: Remove the `from schema.db_models import get_all_expected_columns` import from `comparator.py` and change `validate_schema()` to accept both `actual_columns` and `expected_columns` as parameters.

**Why**: `schema.db_models` is an MC-specific module defining MC's table/column expectations. The library's comparator must be generic -- the caller provides what they expect. This is pure logic (set operations) with no IO, so it stays sync.

**Approach**:

Change signature from:
```python
def validate_schema(actual_columns: dict[str, set[str]]) -> SchemaValidationResult:
    expected_columns = get_all_expected_columns()  # MC import
```

To:
```python
def validate_schema(
    actual_columns: dict[str, set[str]],
    expected_columns: dict[str, set[str]],
) -> SchemaValidationResult:
```

The function body remains identical -- it already operates on the two dicts. Only the source of `expected_columns` changes (parameter instead of import).

This function stays **sync** because it is pure set comparison logic with no IO.

Validation: `comparator.py` has zero imports from `schema.db_models`. Function accepts two parameters.

---

### 8. Generalize Schema Fix Module

**What**: Remove the hardcoded `COLUMN_DEFINITIONS` dict (MC's projects/milestones/tasks column types) from `fix.py`. Make `generate_fix_plan()` and `apply_fixes()` accept caller-provided column definitions or a schema.sql path.

**Why**: `COLUMN_DEFINITIONS` contains 40+ entries specific to MC's three tables. A generic library cannot hardcode any project's schema.

**Approach**:

Remove:
- `COLUMN_DEFINITIONS` dict entirely
- `from db import connect_and_validate, read_profile_lock` (MC-coupled factory imports)

Modify:
- `generate_fix_plan()` signature to accept `column_definitions: dict[str, str]` parameter and `schema_file: str | Path`
- `apply_fixes()` to accept same parameters, convert to async
- `_get_table_create_sql()` uses caller-provided `schema_file` path (no default path)
- `ColumnFix`, `TableFix`, `FixPlan`, `FixResult` dataclasses remain as-is (they are generic)

Pattern:
```python
async def generate_fix_plan(
    validation_result: SchemaValidationResult,
    column_definitions: dict[str, str],
    schema_file: str | Path,
) -> FixPlan:
    ...
```

The function no longer calls `connect_and_validate()` internally -- the caller passes in the `SchemaValidationResult` they already obtained.

Validation: No `COLUMN_DEFINITIONS` dict in source. No `from db import ...` in fix.py.

---

### 9. Generalize Sync Module

**What**: Remove hardcoded `projects`, `milestones`, `tasks` table references from `sync.py`. Make sync operations work with caller-declared table lists.

**Why**: The sync module currently hardcodes MC's three tables and their slug-resolution logic. A generic library must accept any set of tables the caller wants to sync.

**Approach**:

Redesign `SyncResult` to use dynamic table names instead of hardcoded defaults:
```python
class SyncResult(BaseModel):
    success: bool = False
    source_profile: str = ""
    dest_profile: str = ""
    source_counts: dict[str, int] = Field(default_factory=dict)
    dest_counts: dict[str, int] = Field(default_factory=dict)
    sync_plan: dict[str, dict[str, int]] = Field(default_factory=dict)
    error: str | None = None
```

Functions accept a `tables` parameter:
```python
async def compare_profiles(
    source_profile: str,
    dest_profile: str,
    tables: list[str],
    user_field: str = "user_id",
    slug_field: str = "slug",
    env_prefix: str = "",
) -> SyncResult:
```

Remove:
- `from db import _resolve_url, get_dev_user_id` -- user_id becomes a parameter
- `_get_data_counts()` hardcoded table list -- iterate `tables` parameter
- `_get_slugs()` hardcoded project/milestone/task logic -- use generic slug resolution
- `sync_data()` subprocess calls referencing `backup/backup_cli.py` path

Validation: No hardcoded `"projects"`, `"milestones"`, or `"tasks"` string literals in sync.py.

---

### 10. Generalize Backup/Restore

**What**: Convert `backup_restore.py` from hardcoded MC table logic to use the `BackupSchema` declarative model that already exists in `backup/models.py`.

**Why**: The current implementation hardcodes `projects`, `milestones`, `tasks` table names, their FK relationships (`project_id`, `milestone_id`), and MC-specific imports (`get_db_adapter`, `get_dev_user_id`, `get_settings`). The `BackupSchema`/`TableDef`/`ForeignKey` models are already defined but not yet used.

**Approach**:

Rewrite `backup_database()` and `restore_database()` to accept `BackupSchema` and `DatabaseClient`:

```python
async def backup_database(
    adapter: DatabaseClient,
    schema: BackupSchema,
    user_id: str,
    output_path: str | None = None,
    table_filters: dict[str, dict] | None = None,
) -> str:
    ...

async def restore_database(
    adapter: DatabaseClient,
    schema: BackupSchema,
    backup_path: str,
    user_id: str,
    mode: Literal["skip", "overwrite", "fail"] = "skip",
    dry_run: bool = False,
) -> dict:
    ...
```

Key changes:
- Iterate `schema.tables` instead of hardcoded table names
- Use `TableDef.pk`, `TableDef.slug_field`, `TableDef.user_field` for column references
- Use `TableDef.parent` and `TableDef.optional_refs` for FK remapping instead of hardcoded `project_id_map`, `milestone_id_map`
- Build generic `id_maps: dict[str, dict]` keyed by table name
- Remove `from db import get_db_adapter, get_dev_user_id` and `from config import get_settings`
- `validate_backup()` becomes schema-aware (checks for table keys matching `BackupSchema.tables`)

The `BackupSchema` ordering (parents first) ensures restore processes tables in dependency order.

Validation: No hardcoded table names. `backup_restore.py` has zero MC-specific imports.

---

### 11. Modernize CLI

**What**: Update CLI to use `db-adapter` as program name, remove MC-specific references, integrate backup commands, and wrap all async calls with `asyncio.run()`.

**Why**: The CLI currently references `python -m schema`, uses `MC_DB_PROFILE` hardcoded, imports MC-coupled functions, and the backup CLI is a separate entry point.

**Approach**:

**`cli/__init__.py`** -- main entry point:
- Change `prog` from `"python -m schema"` to `"db-adapter"`
- Change description from "Mission Control" to generic
- Update all `cmd_*` functions to call async functions via `asyncio.run()`
- Remove MC-specific imports and functions
- Add `backup`, `restore`, `validate-backup` subcommands (merge from `cli/backup.py`)
- Accept `--env-prefix` global option

**`cli/backup.py`** -- will be merged into `cli/__init__.py` or kept as a submodule but using the generic `backup_restore` functions with a caller-provided schema.

Since the CLI cannot know the caller's `BackupSchema` at runtime, the CLI will need a way to load schema definitions. Two options:

**Option A**: CLI reads a `db-backup.toml` or section in `db.toml` that declares the table hierarchy.
**Option B**: CLI provides basic operations and consumers wrap it.

For initial release, Option B is simpler -- the CLI handles connect/status/profiles/validate/fix/sync. Backup commands require the consuming project to provide a thin wrapper script that passes in `BackupSchema`. The CLI can still include `backup` and `restore` commands that accept a `--schema` flag pointing to a TOML/JSON schema definition file.

Pattern for async CLI wrapping:
```python
def cmd_connect(args: argparse.Namespace) -> int:
    return asyncio.run(_async_connect(args))

async def _async_connect(args: argparse.Namespace) -> int:
    result = await connect_and_validate()
    ...
```

Validation: `"Mission Control"` does not appear in CLI code. `db-adapter` is the program name.

---

### 12. Update Package Exports and Init

**What**: Update `src/db_adapter/__init__.py` to export the library's primary public API, and update all subpackage `__init__.py` files.

**Why**: Currently `__init__.py` only exports `__version__`. Users need to import from the top level: `from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter`.

**Approach**:

```python
# src/db_adapter/__init__.py
"""db-adapter: Async dict-based database adapter with Protocol typing."""

__version__ = "0.1.0"

from db_adapter.adapters.base import DatabaseClient
from db_adapter.adapters.postgres import AsyncPostgresAdapter
from db_adapter.factory import get_adapter, connect_and_validate, ProfileNotFoundError
from db_adapter.config.loader import load_db_config
from db_adapter.config.models import DatabaseProfile, DatabaseConfig
from db_adapter.schema.comparator import validate_schema
from db_adapter.backup.models import BackupSchema, TableDef, ForeignKey

__all__ = [
    "DatabaseClient",
    "AsyncPostgresAdapter",
    "get_adapter",
    "connect_and_validate",
    "ProfileNotFoundError",
    "load_db_config",
    "DatabaseProfile",
    "DatabaseConfig",
    "validate_schema",
    "BackupSchema",
    "TableDef",
    "ForeignKey",
]
```

Subpackage `__init__.py` files should also export their public APIs.

Validation: `from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter` works.

---

## Proposed Sequence

> Shows dependencies and recommended order. Planning stage will create actual implementation steps.

**Order**: #4 -> #1 -> #3 -> #2 -> #7 -> #5 -> #6 -> #8 -> #9 -> #10 -> #11 -> #12

### #4: Consolidate Duplicate Models

**Depends On**: None

**Rationale**: Models are referenced by every other module. Resolving the duplication between `config/models.py` and `schema/models.py` first establishes a single source of truth that all subsequent import fixes will reference. Without this, import fixes would point to ambiguous locations.

---

### #1: Fix Package Imports

**Depends On**: #4

**Rationale**: After models are in their canonical locations, all `from adapters import ...` / `from schema.models import ...` bare imports can be converted to proper `db_adapter.*` paths. This unblocks everything else because no module can be tested or imported until its import statements resolve.

---

### #3: Remove MC-Specific Code from Config Loader

**Depends On**: #1

**Rationale**: Config loader is imported by factory and CLI. Removing `Settings`, `SharedSettings`, and `get_settings()` before converting factory code avoids having to temporarily fix broken MC-specific imports. Straightforward removal with no async conversion needed.

---

### #2: Remove MC-Specific Code from Factory

**Depends On**: #1, #3

**Rationale**: Factory imports from config loader (cleaned in #3). Removing MC functions (`get_user_id_from_ctx`, test helpers) and restructuring `get_db_adapter()`/`connect_and_validate()` signatures establishes the factory API shape. This is done before async conversion to isolate concerns.

---

### #7: Decouple Schema Comparator

**Depends On**: #1

**Rationale**: Simple signature change (add `expected_columns` parameter, remove MC import). Pure logic, no async. Should be done before factory async conversion because `connect_and_validate()` calls `validate_schema()`.

---

### #5: Convert Adapters to Async

**Depends On**: #1, #2

**Rationale**: The core async conversion. Depends on factory cleanup (#2) because factory creates adapters. All downstream async work (introspector, fix, sync, backup) depends on adapters being async first.

---

### #6: Convert Schema Introspector to Async

**Depends On**: #1, #5

**Rationale**: Introspector is called during `connect_and_validate()` which will use async adapters. Converting introspector to async (`psycopg.AsyncConnection`) is needed before the factory's `connect_and_validate()` can become fully async.

**Notes**: After this item, `connect_and_validate()` in factory can be converted to async since both adapters and introspector are now async.

---

### #8: Generalize Schema Fix Module

**Depends On**: #1, #5, #6, #7

**Rationale**: Fix module calls `connect_and_validate()` (now async), creates `PostgresAdapter` (now `AsyncPostgresAdapter`), and uses `validate_schema()` (now 2-param). All three dependencies must be in place.

---

### #9: Generalize Sync Module

**Depends On**: #1, #2, #5

**Rationale**: Sync module creates adapters (now async), uses factory's `_resolve_url()` (cleaned in #2), and queries tables. Must be done after adapter async conversion.

---

### #10: Generalize Backup/Restore

**Depends On**: #1, #5

**Rationale**: Backup/restore uses adapters for all DB operations. With async adapters in place and the `BackupSchema` model already defined (no work needed there), this is a rewrite of the backup functions to use the declarative schema model instead of hardcoded tables.

---

### #11: Modernize CLI

**Depends On**: #2, #3, #5, #6, #7, #8, #9, #10

**Rationale**: CLI is the integration layer that calls factory, comparator, fix, sync, and backup. All underlying modules must be converted before the CLI can wrap them with `asyncio.run()`.

---

### #12: Update Package Exports and Init

**Depends On**: #5, #10, #11

**Rationale**: Final item -- after all modules have their final names and signatures, update `__init__.py` files to export the public API. This is the finishing touch that makes the library usable from the outside.

---

## Success Criteria

- [ ] `uv sync` installs without errors (all dependencies resolve)
- [ ] `python -c "from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter"` succeeds
- [ ] Zero imports from `fastmcp`, `creational.common`, `mcp.server.auth`, or `schema.db_models`
- [ ] Zero hardcoded MC-specific table names (`"projects"`, `"milestones"`, `"tasks"`) in library code
- [ ] `DatabaseClient` Protocol has all `async def` methods
- [ ] `AsyncPostgresAdapter` uses `create_async_engine` with `asyncpg` driver
- [ ] `SchemaIntrospector` uses `psycopg.AsyncConnection` with `__aenter__`/`__aexit__`
- [ ] `validate_schema()` accepts `(actual_columns, expected_columns)` -- two parameters
- [ ] `JSONB_COLUMNS` is a constructor parameter, not a class constant
- [ ] `BackupSchema` model drives backup/restore instead of hardcoded table logic
- [ ] No duplicate model classes across `config/models.py` and `schema/models.py`
- [ ] CLI uses `db-adapter` as program name
- [ ] All existing model schemas (`BackupSchema`, `TableDef`, `ForeignKey`, `DatabaseProfile`, etc.) are preserved

---

## Implementation Options

### Option A: Async-First with No Sync Wrappers (Recommended)

The entire library is async-first. CLI wraps with `asyncio.run()`. Consuming projects must use `await` for all adapter/factory/schema calls.

**Pros**:
- Clean, consistent API surface
- No dual sync/async maintenance burden
- Matches the extraction plan specification
- FastMCP 2.0 and modern Python frameworks all support async

**Cons**:
- Consumers must adapt call sites to use `await`
- Simple scripts need `asyncio.run()` boilerplate

### Option B: Dual Sync/Async API

Provide both `select()` and `select_async()` (or `PostgresAdapter` and `AsyncPostgresAdapter` as separate classes).

**Pros**:
- Easier migration for sync consumers
- Simple scripts work without `asyncio.run()`

**Cons**:
- Double the maintenance surface
- Confusing API (which one to use?)
- Contradicts the extraction plan decision: "Entire lib is async"

### Recommendation

Option A because: The extraction plan explicitly states "Async-first. Entire lib is async. CLI wraps with `asyncio.run()`." There are no current consumers of this library yet, so there is no migration burden. Starting async-only avoids technical debt.

---

## Files to Modify

> Include this section to give clear scope of changes.

| File | Change | Complexity |
|------|--------|------------|
| `src/db_adapter/__init__.py` | Modify - add public API exports | Low |
| `src/db_adapter/factory.py` | Modify - remove MC code, add env_prefix, convert to async | High |
| `src/db_adapter/adapters/__init__.py` | Modify - fix imports, update exports | Low |
| `src/db_adapter/adapters/base.py` | Modify - all methods become async def | Low |
| `src/db_adapter/adapters/postgres.py` | Modify - async engine, configurable JSONB, rename class | High |
| `src/db_adapter/adapters/supabase.py` | Modify - async client, lazy init, rename class | Med |
| `src/db_adapter/config/__init__.py` | Modify - add exports | Low |
| `src/db_adapter/config/models.py` | Modify - keep only config models (remove duplicates) | Low |
| `src/db_adapter/config/loader.py` | Modify - remove Settings/SharedSettings, fix imports | Med |
| `src/db_adapter/schema/__init__.py` | Modify - add exports | Low |
| `src/db_adapter/schema/models.py` | Modify - keep introspection + validation models only | Low |
| `src/db_adapter/schema/introspector.py` | Modify - async psycopg, configurable excluded_tables | Med |
| `src/db_adapter/schema/comparator.py` | Modify - add expected_columns param, remove MC import | Low |
| `src/db_adapter/schema/fix.py` | Modify - remove COLUMN_DEFINITIONS, parameterize, async | High |
| `src/db_adapter/schema/sync.py` | Modify - remove hardcoded tables, parameterize, async | High |
| `src/db_adapter/backup/__init__.py` | Modify - add exports | Low |
| `src/db_adapter/backup/models.py` | No change - already generic | None |
| `src/db_adapter/backup/backup_restore.py` | Modify - use BackupSchema, remove MC imports, async | High |
| `src/db_adapter/cli/__init__.py` | Modify - rename to db-adapter, remove MC refs, asyncio.run | High |
| `src/db_adapter/cli/backup.py` | Modify - integrate into main CLI or use generic backup API | Med |

---

## Testing Strategy

**Unit Tests**:
- Protocol compliance: `AsyncPostgresAdapter` structurally matches `DatabaseClient`
- `validate_schema()` with mock actual/expected columns
- `BackupSchema` model validation
- `load_db_config()` with sample TOML
- Import resolution: `from db_adapter import ...` works for all public exports
- `_resolve_url()` password substitution

**Integration Tests** (require database):
- `AsyncPostgresAdapter` CRUD against a test PostgreSQL instance
- `SchemaIntrospector` async context manager against test DB
- `connect_and_validate()` end-to-end flow
- `backup_database()` / `restore_database()` round-trip with `BackupSchema`

**Manual Validation**:
- `uv sync` succeeds
- `uv run db-adapter --help` shows correct program name and commands
- `uv run python -c "from db_adapter import AsyncPostgresAdapter"` succeeds
- `grep -r "from fastmcp\|from creational\|from mcp.server" src/` returns nothing
- `grep -r "JSONB_COLUMNS = frozenset" src/` returns nothing

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| asyncpg driver incompatibilities with SQLAlchemy async | LOW | HIGH | asyncpg is SQLAlchemy's recommended async PostgreSQL driver; well-tested combination |
| psycopg async API differences from sync API | LOW | MED | psycopg v3 has first-class async support; API is nearly identical to sync |
| supabase-py async client import path changes between versions | MED | MED | Pin supabase dependency version; use try/except for import |
| CLI backup commands need BackupSchema but CLI cannot know it at runtime | MED | MED | CLI reads schema from a TOML/JSON config file, or delegates to consuming project wrapper |
| Large refactor scope increases risk of subtle bugs | MED | MED | Item-by-item execution with validation at each step; no dependencies on external systems until integration tests |

---

## Open Questions

1. **Profile lock file location**: Should `.db-profile` be created in CWD (project root) or in a configurable location? CWD seems right for a library (each project gets its own lock file), but needs confirmation.
2. **CLI backup schema source**: How should the CLI's backup/restore commands discover the `BackupSchema`? Options: TOML section in `db.toml`, separate `db-backup.toml`, JSON file passed via `--schema` flag, or defer backup CLI to consuming projects.
3. **Env var default prefix**: The extraction plan shows no prefix as default (`DB_PROFILE`, `DATABASE_URL`). Should we confirm this, or use a different convention?

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Async strategy | Async-first, no sync wrappers | Extraction plan explicitly specifies "Entire lib is async"; no current consumers to migrate |
| Model consolidation | Config models in `config/models.py`, schema/validation models in `schema/models.py` | Domain separation; config models describe connection profiles, schema models describe database structure |
| JSONB handling | Constructor parameter `jsonb_columns` | Extraction plan specifies this; avoids hardcoding any project's column names |
| Comparator signature | `validate_schema(actual, expected)` | Extraction plan specifies this; caller provides expected columns instead of MC-internal import |
| CLI program name | `db-adapter` | Matches package name; registered in pyproject.toml `[project.scripts]` |
| Lock file location | CWD-relative `.db-profile` | Library should not write inside its own package directory; each project gets its own lock |
| Engine factory name | `create_async_engine_pooled()` | Replaces `create_mc_engine()`; descriptive of what it does, no MC reference |

---

## Next Steps

1. Review this design and confirm approach
2. Run `/review-doc` to check for issues
3. Create implementation plan (`/dev-plan`)
4. Execute implementation (`/dev-execute`)

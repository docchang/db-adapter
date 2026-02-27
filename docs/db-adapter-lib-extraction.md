# db-adapter Library Extraction Plan

What to extract from Mission Control into a standalone open-source Python library.

## Decisions

| Question | Answer |
|---|---|
| **Package name** | `db-adapter` |
| **Repo** | `creational-ai` org (GitHub account issue pending) |
| **Distribution** | Git-based install (`uv add git+ssh://...`) |
| **Backup/restore** | Included in initial release |
| **Async** | Async-first. Entire lib is async. CLI wraps with `asyncio.run()`. |

---

## Concept

An async, dict-based database adapter with Protocol typing, multi-profile config, schema management CLI, and backup/restore. Like SQLAlchemy gives you the engine, this gives you a clean async CRUD interface + tooling on top of it.

```python
from db_adapter import AsyncPostgresAdapter

adapter = AsyncPostgresAdapter("postgresql://user:pass@host/db", jsonb_columns=["metadata"])
rows = await adapter.select("users", "id, name", filters={"active": True})
await adapter.insert("users", {"name": "Alice", "email": "alice@example.com"})
await adapter.close()
```

---

## Async Architecture

The entire library is async-first. MC and other consumers will need to adapt their call sites.

### Protocol

```python
# Before (sync)
class DatabaseClient(Protocol):
    def select(self, table, columns, filters, order_by) -> list[dict]: ...
    def insert(self, table, data) -> dict: ...
    def update(self, table, data, filters) -> dict: ...
    def delete(self, table, filters) -> None: ...
    def close(self) -> None: ...

# After (async)
class DatabaseClient(Protocol):
    async def select(self, table, columns, filters, order_by) -> list[dict]: ...
    async def insert(self, table, data) -> dict: ...
    async def update(self, table, data, filters) -> dict: ...
    async def delete(self, table, filters) -> None: ...
    async def close(self) -> None: ...
```

### PostgresAdapter

```python
# Before: sqlalchemy sync engine + engine.connect()
# After: sqlalchemy async engine + async_engine.connect()

from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

class AsyncPostgresAdapter:
    def __init__(self, database_url: str, jsonb_columns: list[str] | None = None, **engine_kwargs):
        # postgresql:// -> postgresql+asyncpg://
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        self._engine: AsyncEngine = create_async_engine(async_url, **engine_kwargs)
        self._jsonb_columns = frozenset(jsonb_columns or [])

    async def select(self, table, columns, filters=None, order_by=None) -> list[dict]:
        async with self._engine.connect() as conn:
            result = await conn.execute(query, params)
            ...

    async def close(self):
        await self._engine.dispose()
```

### SupabaseAdapter

```python
# Before: supabase-py sync client
# After: supabase-py async client (supabase already supports async)

from supabase._async.client import AsyncClient, create_async_client

class AsyncSupabaseAdapter:
    def __init__(self, url: str, key: str):
        self._client: AsyncClient | None = None
        self._url = url
        self._key = key

    async def _get_client(self) -> AsyncClient:
        if self._client is None:
            self._client = await create_async_client(self._url, self._key)
        return self._client
```

### SchemaIntrospector

```python
# Before: psycopg sync (psycopg.connect)
# After: psycopg async (psycopg.AsyncConnection)

import psycopg

class SchemaIntrospector:
    async def __aenter__(self):
        self._conn = await psycopg.AsyncConnection.connect(self._database_url)
        return self

    async def __aexit__(self, *args):
        await self._conn.close()

    async def introspect(self, schema_name="public") -> DatabaseSchema: ...
    async def get_column_names(self, schema_name="public") -> dict[str, set[str]]: ...
```

### CLI

CLI commands stay sync from the user's perspective. Internally they use `asyncio.run()`:

```python
def cmd_connect(args):
    return asyncio.run(_async_connect(args))

async def _async_connect(args):
    result = await connect_and_validate()
    ...
```

### Dependencies Change

| Before (sync) | After (async) |
|---|---|
| `sqlalchemy` | `sqlalchemy[asyncio]` |
| `psycopg[binary]` | `psycopg[binary]` (already supports async) |
| `supabase` | `supabase` (already supports async) |
| - | `asyncpg` (async PostgreSQL driver for SQLAlchemy) |

---

## What to Copy

### Layer 1: Core Adapter

| Source File | Lib Path | Changes Needed |
|---|---|---|
| `adapters/base.py` | `db_adapter/adapters/base.py` | All methods become `async def` |
| `adapters/postgres_adapter.py` | `db_adapter/adapters/postgres.py` | Async SQLAlchemy engine. `JSONB_COLUMNS` becomes constructor param. Rename `create_mc_engine` to `create_async_engine_pooled`. |
| `adapters/supabase_adapter.py` | `db_adapter/adapters/supabase.py` | Use `supabase` async client |
| `adapters/__init__.py` | `db_adapter/adapters/__init__.py` | Export all three |

**Key change in PostgresAdapter:**
```python
# Before (MC-specific, sync)
JSONB_COLUMNS = frozenset(["risks"])

# After (configurable, async)
def __init__(self, database_url: str, jsonb_columns: list[str] | None = None, **engine_kwargs):
    self._jsonb_columns = frozenset(jsonb_columns or [])
    self._engine = create_async_engine_pooled(database_url, **engine_kwargs)
```

**Engine factory becomes configurable + async:**
```python
def create_async_engine_pooled(
    database_url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_recycle: int = 300,
    connect_timeout: int = 5,
) -> AsyncEngine:
```

### Layer 2: Configuration

| Source File | Lib Path | Changes Needed |
|---|---|---|
| `schema/models.py` (DatabaseProfile, DatabaseConfig only) | `db_adapter/config/models.py` | Extract just profile/config models |
| `config.py` (`load_db_config` only) | `db_adapter/config/loader.py` | Remove `Settings` class (MC-specific). Keep TOML loading. |
| `db.py` (profile resolution + factory) | `db_adapter/factory.py` | Extract profile lock, `get_active_profile`, `get_adapter`. Remove auth, user_id, test helpers. |

**Factory API:**
```python
from db_adapter import get_adapter, connect_and_validate

# Profile mode (db.toml + lock file)
adapter = await get_adapter()  # uses .db-profile lock or DB_PROFILE env var

# Direct mode
adapter = await get_adapter(database_url="postgresql://...")

# With validation
result = await connect_and_validate(profile_name="production")
if result.success:
    adapter = await get_adapter()
```

### Layer 3: Schema Management

| Source File | Lib Path | Changes Needed |
|---|---|---|
| `schema/models.py` (introspection models) | `db_adapter/schema/models.py` | Already generic (ColumnSchema, TableSchema, etc.) |
| `schema/introspector.py` | `db_adapter/schema/introspector.py` | Async psycopg. Make `EXCLUDED_TABLES` configurable via constructor. |
| `schema/comparator.py` | `db_adapter/schema/comparator.py` | Change `validate_schema(actual)` to `validate_schema(actual, expected)` - caller passes expected columns instead of importing from db_models. Pure logic, no async needed. |
| `schema/fix.py` | `db_adapter/schema/fix.py` | Remove `COLUMN_DEFINITIONS` dict. Caller provides column defs or a schema.sql path. Async for DB operations. |
| `schema/sync.py` | `db_adapter/schema/sync.py` | Generalize table list (not hardcoded to projects/milestones/tasks). Caller declares syncable tables. Async. |

**Key change in comparator:**
```python
# Before (MC-coupled)
def validate_schema(actual_columns):
    expected_columns = get_all_expected_columns()  # imports MC's db_models

# After (generic, stays sync - pure logic)
def validate_schema(actual_columns: dict[str, set[str]], expected_columns: dict[str, set[str]]):
    # Pure set comparison, no imports, no IO
```

### Layer 4: CLI

| Source File | Lib Path | Changes Needed |
|---|---|---|
| `schema/__main__.py` | `db_adapter/cli/__init__.py` | Decouple from MC imports. Wrap async with `asyncio.run()`. |

**CLI commands:**
```bash
db-adapter connect
db-adapter status
db-adapter profiles
db-adapter validate
db-adapter fix --confirm
db-adapter sync --from production --dry-run
db-adapter backup                          # NEW
db-adapter backup --tables users,posts     # NEW
db-adapter restore backup.json             # NEW
db-adapter restore backup.json --mode overwrite  # NEW
```

### Layer 5: Backup/Restore

| Source File | Lib Path | Changes Needed |
|---|---|---|
| `backup/backup_restore.py` | `db_adapter/backup/backup_restore.py` | Generalize: remove hardcoded table names (projects/milestones/tasks). Caller declares table hierarchy and FK relationships. Async. |
| `backup/backup_cli.py` | `db_adapter/cli/backup.py` | Integrate into main CLI as `db-adapter backup` / `db-adapter restore` / `db-adapter validate-backup` subcommands. |

**Key change - generic table hierarchy:**
```python
# Before (MC-specific: hardcoded projects -> milestones -> tasks)
backup_data = {"projects": [], "milestones": [], "tasks": []}
for project in backup_data["projects"]:
    ...

# After (caller declares hierarchy)
schema = BackupSchema(
    tables=[
        TableDef("projects", pk="id", slug_field="slug", user_field="user_id"),
        TableDef("milestones", pk="id", slug_field="slug", user_field="user_id",
                 parent=ForeignKey(table="projects", field="project_id")),
        TableDef("tasks", pk="id", slug_field="slug", user_field="user_id",
                 parent=ForeignKey(table="projects", field="project_id"),
                 optional_refs=[ForeignKey(table="milestones", field="milestone_id")]),
    ]
)

# Backup
backup_data = await backup_database(adapter, schema, user_id="...")

# Restore (handles FK remapping automatically based on schema)
summary = await restore_database(adapter, schema, backup_path, user_id="...", mode="skip")
```

**BackupSchema model:**
```python
class ForeignKey(BaseModel):
    table: str          # parent table name
    field: str          # FK column in this table

class TableDef(BaseModel):
    name: str           # table name
    pk: str = "id"      # primary key column
    slug_field: str = "slug"
    user_field: str = "user_id"
    parent: ForeignKey | None = None       # required FK (skip record if parent missing)
    optional_refs: list[ForeignKey] = []   # optional FKs (set to null if ref missing)

class BackupSchema(BaseModel):
    tables: list[TableDef]  # ordered by dependency (parents first)
```

---

## What NOT to Copy

| File | Why |
|---|---|
| `schema/db_models.py` | MC-specific (DBProject, DBMilestone, DBTask). Each project defines its own expected schema. |
| `schema/fix.py` COLUMN_DEFINITIONS | MC-specific column types. Projects provide their own schema.sql or column defs. |
| `db.py` auth functions | `get_user_id_from_ctx`, `AuthenticationError` - FastMCP-specific |
| `db.py` test helpers | `cleanup_project_all_dbs`, `cleanup_projects_pattern` - MC-specific |
| `config.py` Settings class | MC-specific (inherits SharedSettings, has dev_user_id, supabase_key) |

---

## How Projects Use It

### Mission Control (after extraction)

```python
# config.py - slim, no more load_db_config
from db_adapter import get_adapter, load_db_config  # from lib now

# tools/crud.py
from db_adapter import DatabaseClient
adapter: DatabaseClient = await get_adapter()
rows = await adapter.select("projects", "*", filters={"user_id": uid})

# backup - declare MC's table hierarchy
from db_adapter.backup import BackupSchema, TableDef, ForeignKey

MC_SCHEMA = BackupSchema(tables=[
    TableDef("projects", pk="id", slug_field="slug", user_field="user_id"),
    TableDef("milestones", pk="id", slug_field="slug", user_field="user_id",
             parent=ForeignKey(table="projects", field="project_id")),
    TableDef("tasks", pk="id", slug_field="slug", user_field="user_id",
             parent=ForeignKey(table="projects", field="project_id"),
             optional_refs=[ForeignKey(table="milestones", field="milestone_id")]),
])

# schema/db_models.py stays in MC (defines expected schema)
# comparator calls become:
from db_adapter.schema import validate_schema
result = validate_schema(actual_columns, get_all_expected_columns())
```

### New Project (e.g., Video Professor)

```python
from db_adapter import AsyncPostgresAdapter

adapter = AsyncPostgresAdapter(
    "postgresql://user:pass@host/db",
    jsonb_columns=["transcript_data"],
)

# Simple CRUD
videos = await adapter.select("videos", "id, title", filters={"status": "published"})
await adapter.insert("videos", {"title": "New Video", "url": "https://..."})

# Or with profiles
# 1. Create db.toml with profiles
# 2. DB_PROFILE=production db-adapter connect
# 3. adapter = await get_adapter()
```

---

## Package Structure

```
db-adapter/
├── pyproject.toml
├── README.md
├── src/
│   └── db_adapter/
│       ├── __init__.py              # Main exports
│       ├── factory.py               # get_adapter(), connect_and_validate()
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py              # DatabaseClient Protocol (async)
│       │   ├── postgres.py          # AsyncPostgresAdapter
│       │   └── supabase.py          # AsyncSupabaseAdapter
│       ├── config/
│       │   ├── __init__.py
│       │   ├── models.py            # DatabaseProfile, DatabaseConfig
│       │   └── loader.py            # load_db_config() TOML parser
│       ├── schema/
│       │   ├── __init__.py
│       │   ├── models.py            # ColumnSchema, TableSchema, etc.
│       │   ├── introspector.py      # SchemaIntrospector (async)
│       │   ├── comparator.py        # validate_schema() (sync - pure logic)
│       │   ├── fix.py               # generate_fix_plan(), apply_fixes()
│       │   └── sync.py              # compare_profiles(), sync_data()
│       ├── backup/
│       │   ├── __init__.py
│       │   ├── models.py            # BackupSchema, TableDef, ForeignKey
│       │   └── backup_restore.py    # backup_database(), restore_database(), validate_backup()
│       └── cli/
│           ├── __init__.py          # CLI entry point + schema commands
│           └── backup.py            # backup/restore/validate-backup commands
└── tests/
```

**Dependencies:**

Core:
- `sqlalchemy[asyncio]` - Async connection pooling + SQL execution
- `asyncpg` - Async PostgreSQL driver
- `psycopg[binary]` - PostgreSQL introspection (schema tools)
- `pydantic` - Models and validation
- `rich` - CLI output formatting

Optional:
- `supabase` - AsyncSupabaseAdapter (optional extra)

**Install:**
```bash
uv add git+ssh://git@github-creational:creational-ai/db-adapter.git

# With Supabase support
uv add "db-adapter[supabase] @ git+ssh://..."
```

---

## Env Var Prefix

MC uses `MC_DB_PROFILE` and `MC_DATABASE_URL`. The lib uses a generic prefix that projects can override:

```python
# Default (no prefix)
DB_PROFILE=rds db-adapter connect
DATABASE_URL=postgresql://...

# Per-project override via env or config
adapter = await get_adapter(env_prefix="MC")  # reads MC_DB_PROFILE, MC_DATABASE_URL
adapter = await get_adapter(env_prefix="VP")  # reads VP_DB_PROFILE, VP_DATABASE_URL
```

---

## Migration Path for MC

1. Publish lib (`uv add git+ssh://git@github-creational:creational-ai/db-adapter.git`)
2. Convert MC tools to async (FastMCP 2.0 supports async tools)
3. Replace `from adapters import ...` with `from db_adapter import ...`
4. Move `load_db_config` from `config.py` to lib import
5. Define `MC_SCHEMA` BackupSchema for backup/restore
6. Keep `schema/db_models.py` in MC (project-specific schema definitions)
7. Update `comparator.py` calls to pass expected columns explicitly
8. Remove copied code from `core/adapters/`, `core/schema/`, `core/backup/` (except db_models.py)
9. Update CLI to wrap lib's CLI or use `db-adapter` directly

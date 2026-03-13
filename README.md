# db-adapter

Async-first database adapter toolkit for Python. Multi-profile config, schema validation and auto-fix, cross-profile data sync, and backup/restore with FK remapping.

* Protocol-typed `DatabaseClient` with PostgreSQL and Supabase implementations — all CRUD returns plain dicts
* `transaction()` async context manager for atomic batches — auto-commits on success, rolls back on exception
* TOML-based multi-profile config with profile lock files and config-driven CLI defaults
* Schema introspection via `pg_catalog`, set-based validation, and atomic auto-fix (ALTER/DROP+CREATE)
* Cross-profile data sync with FK pre-flight warnings and per-table transactions
* JSON backup/restore with declarative table hierarchy (`BackupSchema`) and automatic FK ID remapping
* `sqlparse`-based SQL file parsing — handles quoted identifiers, schema-qualified names, and comments
* 8 CLI subcommands with Rich table output and graceful degradation on errors

## Table of Contents

- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Connecting and Profiles](#connecting-and-profiles)
- [Schema Validation](#schema-validation)
- [Schema Fix](#schema-fix)
- [Data Sync](#data-sync)
- [Backup and Restore](#backup-and-restore)
- [Adapter API](#adapter-api)
- [Transactions](#transactions)
- [Development](#development)
- [License](#license)

## Getting started

Requires Python 3.12+.

```bash
uv add git+ssh://git@github.com/docchang/db-adapter.git

# With Supabase support
uv add "db-adapter[supabase] @ git+ssh://git@github.com/docchang/db-adapter.git"
```

Create a `db.toml` in your project root:

```toml
[profiles.local]
url = "postgresql://user:pass@localhost:5432/mydb"
description = "Local development"
provider = "postgres"

[schema]
file = "schema.sql"
validate_on_connect = true
```

Connect and validate:

```bash
$ DB_PROFILE=local db-adapter connect

v Connected to profile: local
  Schema validation: PASSED

     Table Data
┏━━━━━━━━━━━━┳━━━━━━┓
┃ Table      ┃ Rows ┃
┡━━━━━━━━━━━━╇━━━━━━┩
│ categories │    3 │
│ items      │    5 │
│ products   │    5 │
└────────────┴──────┘
```

This writes a `.db-profile` lock file. All subsequent commands use it automatically — no need to pass the profile name again.

## Configuration

All CLI commands read defaults from `db.toml`. With full configuration, most flags can be omitted.

```toml
[profiles.local]
url = "postgresql://user:pass@localhost:5432/mydb"
description = "Local development"
provider = "postgres"

[profiles.rds]
url = "postgresql://user:pass@rds-host:5432/mydb"
description = "AWS RDS production"
db_password = "secret"         # overrides password in URL
provider = "postgres"

[schema]
file = "schema.sql"              # SQL file with CREATE TABLE statements
validate_on_connect = true       # validate schema on `db-adapter connect`
column_defs = "column-defs.json" # column type definitions for schema fix
backup_schema = "backup-schema.json"  # table hierarchy for backup/restore

[sync]
tables = ["users", "orders", "items"]  # default tables for sync command

[defaults]
user_id_env = "DEV_USER_ID"      # env var name for user_id resolution
```

**Flag resolution order**: CLI flag → `db.toml` config → error. For example, `--schema-file schema.sql` overrides `schema.file` in config.

**User ID resolution**: `--user-id` flag → env var named in `defaults.user_id_env` → error.

### Backup Schema JSON

The `backup_schema` file declares your table hierarchy for backup, restore, and FK-aware sync:

```json
{
    "tables": [
        {
            "name": "categories",
            "pk": "id",
            "slug_field": "slug",
            "user_field": "user_id"
        },
        {
            "name": "products",
            "pk": "id",
            "slug_field": "slug",
            "user_field": "user_id",
            "parent": {
                "table": "categories",
                "field": "category_id"
            }
        }
    ]
}
```

Parent tables are backed up and restored first. The `parent.field` tells the restore engine which column in the child table references the parent's PK, enabling automatic FK ID remapping.

### Column Definitions JSON

The `column_defs` file maps `"table.column"` to SQL type definitions for `ALTER TABLE` when fixing schema drift:

```json
{
    "items.b": "VARCHAR(100) NOT NULL",
    "items.e": "BOOLEAN DEFAULT FALSE",
    "products.price": "INTEGER DEFAULT 0"
}
```

### Env Prefix

For projects that namespace their env vars:

```bash
# Default: reads DB_PROFILE env var
$ DB_PROFILE=local db-adapter connect

# With prefix: reads MC_DB_PROFILE env var
$ MC_DB_PROFILE=local db-adapter --env-prefix MC_ connect
```

The `--env-prefix` flag works with all commands and also affects the library's `get_adapter(env_prefix="MC_")`.

## Connecting and Profiles

### `db-adapter connect`

Connect to a profile, validate schema (if configured), and display table row counts:

```bash
$ DB_PROFILE=local db-adapter connect

v Connected to profile: local
  Schema validation: PASSED

     Table Data
┏━━━━━━━━━━━━┳━━━━━━┓
┃ Table      ┃ Rows ┃
┡━━━━━━━━━━━━╇━━━━━━┩
│ categories │    3 │
│ items      │    5 │
│ products   │    5 │
└────────────┴──────┘
```

When the schema has drifted, connect reports what's missing and exits with code 1:

```bash
$ DB_PROFILE=drift db-adapter connect

x Connected to profile: drift

Schema validation report:
Schema validation failed:

  Missing columns (5):
    - items.b
    - items.e
    - items.f
    - products.active
    - products.price
```

> The `.db-profile` lock file is only written on successful validation. A failed connect does not change the current profile.

### `db-adapter status`

Show the current profile and live table row counts without re-validating:

```bash
$ db-adapter status

               Connection Status
┌─────────────────┬───────────────────────────┐
│ Current profile │ local                     │
│ Profile source  │ .db-profile (validated)   │
│ Provider        │ postgres                  │
│ Description     │ Local development         │
└─────────────────┴───────────────────────────┘

     Table Data
┏━━━━━━━━━━━━┳━━━━━━┓
┃ Table      ┃ Rows ┃
┡━━━━━━━━━━━━╇━━━━━━┩
│ categories │    3 │
│ items      │    5 │
│ products   │    5 │
└────────────┴──────┘
```

Row counts are best-effort — if the database is unreachable, status still shows the profile info from the lock file and config.

### `db-adapter profiles`

List all profiles from `db.toml` with the current profile marked:

```bash
$ db-adapter profiles

                      Database Profiles
┏━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Profile ┃ Provider ┃ Description            ┃
┡━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ *  │ local   │ postgres │ Local development      │
│    │ rds     │ postgres │ AWS RDS production     │
└────┴─────────┴──────────┴────────────────────────┘

* = current profile
```

## Schema Validation

### `db-adapter validate`

Check if the current database matches your `schema.sql`:

```bash
$ db-adapter validate

Validating schema for profile: local
v Schema is valid
```

Use `--schema-file` to override the config:

```bash
$ db-adapter validate --schema-file other-schema.sql
```

When the schema has drifted, the report lists every missing column:

```bash
$ db-adapter validate

x Connected to profile: drift

Schema validation report:
Schema validation failed:

  Missing columns (5):
    - items.b
    - items.e
    - items.f
    - products.active
    - products.price
```

> Validate does not overwrite the `.db-profile` lock file — it's a read-only check.

### Programmatic validation

```python
from db_adapter import validate_schema
from db_adapter.schema import SchemaIntrospector

async with SchemaIntrospector(url) as introspector:
    actual = await introspector.get_column_names()

result = validate_schema(actual, {"users": {"id", "name", "email"}})
# result.valid, result.missing_columns, result.extra_tables
```

## Schema Fix

### `db-adapter fix`

Detect and repair schema drift. Preview by default, apply with `--confirm`:

```bash
$ db-adapter fix

Analyzing schema for profile: drift

      Schema Differences
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┓
┃ Table    ┃ Column   ┃ Type ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━┩
│ items    │ RECREATE │      │
│ products │ RECREATE │      │
└──────────┴──────────┴──────┘

Execution Plan:
  1. DROP TABLES products, items
  2. CREATE TABLE items
  3. CREATE TABLE products

To apply fixes, add --confirm flag.
```

```bash
$ db-adapter fix --confirm

Applying fixes...
v Schema fix complete!
  Tables recreated: 2
```

Fix operations are wrapped in a database transaction — if any step fails, all DDL rolls back atomically (PostgreSQL's transactional DDL). When `backup_schema` is configured, a pre-fix backup is created automatically before any destructive changes.

**Fix strategy**: 1 missing column triggers `ALTER TABLE ADD COLUMN`. 2+ missing columns triggers `DROP TABLE` + `CREATE TABLE` (with auto-backup first). Tables are ordered by FK dependencies — parents created before children, children dropped before parents.

| Flag | Purpose |
|------|---------|
| `--schema-file` | SQL file with CREATE TABLE statements (default: `schema.file`) |
| `--column-defs` | JSON mapping `"table.column"` to SQL type (default: `schema.column_defs`) |
| `--confirm` | Apply fixes (without this, only previews) |
| `--no-backup` | Skip automatic pre-fix backup |

## Data Sync

### `db-adapter sync`

Compare and sync data from one profile to the current profile:

```bash
$ db-adapter sync --from rds --dry-run

Warning: Tables products have foreign key constraints.
Direct sync does not handle FK remapping. Consider configuring
backup_schema in db.toml for FK-aware sync.

Comparing profiles...
  Source: rds
  Destination: local
  Tables: categories, products

               Data Comparison
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃            ┃ rds (source) ┃ local (dest)  ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ categories │            2 │             3 │
│ products   │            0 │             5 │
└────────────┴──────────────┴───────────────┘

DRY RUN - No changes made.
```

The FK pre-flight warning appears when target tables have foreign key constraints and no `backup_schema` is configured. It's advisory only — sync proceeds after the warning.

```bash
$ db-adapter sync --from rds --confirm

Syncing data...
v Sync complete.
```

Each table's inserts are wrapped in a per-table transaction. If a table's sync fails (e.g., FK violation), that table rolls back while previously synced tables remain committed.

| Flag | Purpose |
|------|---------|
| `--from` / `-f` | Source profile name (required) |
| `--tables` | Comma-separated table list (default: `sync.tables`) |
| `--user-id` | User ID for filtering (default: env var from `defaults.user_id_env`) |
| `--dry-run` | Preview without changes |
| `--confirm` | Execute the sync |

### Programmatic sync

```python
from db_adapter.schema import compare_profiles, sync_data

# Compare what would be synced
result = await compare_profiles("rds", "local", tables=["users"], user_id="user-123")
# result.source_counts, result.dest_counts, result.sync_plan

# Execute sync
result = await sync_data("rds", "local", tables=["users"], user_id="user-123", confirm=True)

# FK-aware sync via backup/restore path
result = await sync_data("rds", "local", tables=["users"], user_id="user-123",
                         schema=backup_schema, confirm=True)
```

## Backup and Restore

### `db-adapter backup`

Create a JSON backup of user-scoped data:

```bash
$ db-adapter backup

v Backup saved to: backups/local-20260313-121500.json
  categories: backed up
  products: backed up
```

Backup a subset of tables:

```bash
$ db-adapter backup --tables categories -o backups/cats-only.json
```

Validate an existing backup file (no database connection needed):

```bash
$ db-adapter backup --validate backup.json

v Backup is valid: backup.json
```

When validation fails:

```bash
$ db-adapter backup --validate bad-backup.json

x Backup is invalid: bad-backup.json

Errors:
  - Missing required key: metadata
  - Missing required key: categories
  - Missing required key: products
```

| Flag | Purpose |
|------|---------|
| `--backup-schema` | BackupSchema JSON (default: `schema.backup_schema`) |
| `--user-id` | User ID for filtering (default: env var from `defaults.user_id_env`) |
| `--output` / `-o` | Output file path |
| `--tables` | Comma-separated table subset |
| `--validate` | Validate existing backup instead of creating one |

### `db-adapter restore`

Restore from a backup file with FK ID remapping:

```bash
$ db-adapter restore backup.json --dry-run

DRY RUN - No changes made.
  Mode: skip

                   Restore Results
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┓
┃ Table      ┃ Inserted ┃ Updated ┃ Skipped ┃ Failed ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━┩
│ categories │        0 │       0 │       3 │      0 │
│ products   │        0 │       0 │       5 │      0 │
└────────────┴──────────┴─────────┴─────────┴────────┘
```

```bash
$ db-adapter restore backup.json --mode overwrite --yes

v Restore complete.
  Mode: overwrite

                   Restore Results
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┓
┃ Table      ┃ Inserted ┃ Updated ┃ Skipped ┃ Failed ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━┩
│ categories │        0 │       3 │       0 │      0 │
│ products   │        0 │       5 │       0 │      0 │
└────────────┴──────────┴─────────┴─────────┴────────┘
```

When rows fail, per-row error details are shown below the table:

```
  Failed rows in products:
    row 2 (pk=c3d4): IntegrityError: duplicate key value violates unique constraint
```

**Conflict modes**:

| Mode | Behavior |
|------|----------|
| `skip` (default) | Skip existing rows, insert new ones |
| `overwrite` | Update existing rows with backup data |
| `fail` | Abort on any duplicate — rolls back the entire restore |

Restore is wrapped in a transaction. FK IDs are remapped automatically — child records point to the newly created parent IDs, not the original ones from the backup.

| Flag | Purpose |
|------|---------|
| `--backup-schema` | BackupSchema JSON (default: `schema.backup_schema`) |
| `--user-id` | User ID for filtering |
| `--mode` / `-m` | Conflict resolution: `skip`, `overwrite`, or `fail` |
| `--dry-run` | Preview without changes |
| `--yes` / `-y` | Skip confirmation prompt |

### Programmatic backup/restore

```python
from db_adapter import AsyncPostgresAdapter, BackupSchema, TableDef, ForeignKey
from db_adapter.backup import backup_database, restore_database, validate_backup

schema = BackupSchema(tables=[
    TableDef(name="categories", pk="id", slug_field="slug", user_field="user_id"),
    TableDef(name="products", pk="id", slug_field="slug", user_field="user_id",
             parent=ForeignKey(table="categories", field="category_id")),
])

adapter = AsyncPostgresAdapter("postgresql://user:pass@localhost/mydb")

# Backup
path = await backup_database(adapter, schema, user_id="user-123")

# Validate (sync, no DB connection)
report = validate_backup(path, schema)
# report["valid"], report["errors"], report["warnings"]

# Restore with FK ID remapping
result = await restore_database(adapter, schema, path, user_id="user-123", mode="skip")
# result["categories"] = {"inserted": 3, "updated": 0, "skipped": 0, "failed": 0}
# result["categories"]["failure_details"] = [{"row_index": 0, "old_pk": "abc", "error": "..."}]

await adapter.close()
```

## Adapter API

For programmatic database access without the CLI.

```python
import asyncio
from db_adapter import AsyncPostgresAdapter

async def main():
    adapter = AsyncPostgresAdapter(
        "postgresql://user:pass@localhost:5432/mydb",
        jsonb_columns=["metadata"],  # columns needing JSONB serialization
    )

    # Select
    rows = await adapter.select("users", "id, name, email",
                                filters={"active": True}, order_by="name")

    # Insert — returns the created row as a dict
    user = await adapter.insert("users", {"name": "Alice", "email": "alice@example.com"})

    # Update — returns the updated row as a dict
    updated = await adapter.update("users", {"name": "Bob"}, filters={"id": user["id"]})

    # Delete
    await adapter.delete("users", filters={"id": user["id"]})

    # Raw SQL (DDL)
    await adapter.execute("CREATE INDEX idx_email ON users (email)")

    await adapter.close()

asyncio.run(main())
```

### Factory (profile-based)

```python
from db_adapter import get_adapter, connect_and_validate

# Direct URL (no db.toml needed)
adapter = await get_adapter(database_url="postgresql://user:pass@localhost/mydb")

# Profile from db.toml
adapter = await get_adapter(profile_name="local")

# Env var resolution (reads DB_PROFILE, then .db-profile lock file)
adapter = await get_adapter()

# With env prefix (reads MC_DB_PROFILE)
adapter = await get_adapter(env_prefix="MC_")
```

### DatabaseClient Protocol

`DatabaseClient` is a `typing.Protocol` — adapters implement it structurally, no inheritance needed:

```python
class DatabaseClient(Protocol):
    async def select(self, table, columns, filters=None, order_by=None) -> list[dict]: ...
    async def insert(self, table, data) -> dict: ...
    async def update(self, table, data, filters) -> dict: ...
    async def delete(self, table, filters) -> None: ...
    async def execute(self, sql, params=None) -> None: ...
    def transaction(self) -> AbstractAsyncContextManager[None]: ...
    async def close(self) -> None: ...
```

## Transactions

`transaction()` returns an async context manager that wraps all CRUD operations in a single database transaction:

```python
async with adapter.transaction():
    await adapter.insert("orders", {"user_id": "u1", "total": 99.99})
    await adapter.update("users", {"order_count": 1}, filters={"id": "u1"})
    # Both committed atomically on success
    # If either raises, both roll back
```

Transactions are used internally by `restore_database()` (wraps entire multi-table restore), `apply_fixes()` (wraps all DDL — DROP, CREATE, ALTER), and `_sync_direct()` (wraps each table's inserts).

The implementation uses `contextvars` — each adapter instance gets its own `ContextVar`, so multiple adapters in the same asyncio task don't interfere with each other. Nested transactions raise `RuntimeError`.

`AsyncSupabaseAdapter.transaction()` raises `NotImplementedError` — Supabase's REST API has no transaction semantics.

> When an adapter doesn't support transactions (Supabase, custom adapters), the library falls back to non-transactional behavior automatically — same as before, just without atomicity guarantees.

## Development

```bash
git clone git@github.com:docchang/db-adapter.git
cd db-adapter
uv sync --extra dev

# Run all tests (828 tests)
uv run pytest

# Run a single test file
uv run pytest tests/test_lib_extraction_adapters.py

# Run with verbose output
uv run pytest -v
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`.

| Dependency | Purpose |
|------------|---------|
| `sqlalchemy[asyncio]` | Async engine + connection pooling |
| `asyncpg` | PostgreSQL driver for SQLAlchemy |
| `psycopg[binary]` | PostgreSQL introspection + row counts |
| `pydantic` | Config and schema models |
| `rich` | CLI table formatting |
| `sqlparse` | SQL file parsing |
| `supabase` *(optional)* | Supabase async adapter |

## License

MIT

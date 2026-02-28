# db-adapter

An async-first, dict-based database adapter library for Python with Protocol typing, multi-profile configuration, schema management, and backup/restore.

Like SQLAlchemy gives you the engine, db-adapter gives you a clean async CRUD interface + tooling on top of it.

## Features

- **Async-first** — All database operations are `async def`. CLI wraps with `asyncio.run()`.
- **Protocol-typed adapters** — `DatabaseClient` protocol with PostgreSQL and Supabase implementations. All CRUD methods return plain dicts.
- **Multi-profile config** — TOML-based profiles (`local`, `rds`, `docker`, etc.) with profile lock files for validated connections.
- **Schema introspection** — Full database schema extraction via `information_schema` and `pg_catalog` (tables, columns, constraints, indexes, triggers, functions).
- **Schema validation & fix** — Set-based comparison of expected vs actual schema. Auto-fix with ALTER/DROP+CREATE and FK-aware topological ordering.
- **Cross-profile data sync** — Compare and sync data between database profiles with direct insert or FK-aware backup/restore paths.
- **Backup/restore** — JSON-based backup with declarative table hierarchy (`BackupSchema`) and FK ID remapping on restore.
- **CLI** — `db-adapter connect|status|profiles|validate|fix|sync`

## Installation

Requires Python 3.12+.

```bash
# From source
uv add git+ssh://git@github.com/docchang/db-adapter.git

# With Supabase support
uv add "db-adapter[supabase] @ git+ssh://git@github.com/docchang/db-adapter.git"
```

## Quick Start

### Direct adapter usage

```python
import asyncio
from db_adapter import AsyncPostgresAdapter

async def main():
    adapter = AsyncPostgresAdapter(
        "postgresql://user:pass@localhost:5432/mydb",
        jsonb_columns=["metadata"],  # columns needing JSONB serialization
    )

    # Select
    rows = await adapter.select("users", "id, name, email", filters={"active": True}, order_by="name")

    # Insert
    user = await adapter.insert("users", {"name": "Alice", "email": "alice@example.com"})

    # Update
    updated = await adapter.update("users", {"name": "Bob"}, filters={"id": user["id"]})

    # Delete
    await adapter.delete("users", filters={"id": user["id"]})

    # Raw SQL (DDL)
    await adapter.execute("CREATE INDEX idx_email ON users (email)")

    await adapter.close()

asyncio.run(main())
```

### Factory with profiles

Create a `db.toml` in your project root:

```toml
[profiles.local]
url = "postgresql://user:pass@localhost:5432/mydb"
description = "Local development"
provider = "postgres"

[profiles.rds]
url = "postgresql://user:[YOUR-PASSWORD]@rds-host:5432/mydb"
description = "AWS RDS production"
db_password = "secret"
provider = "postgres"
```

Use the factory to create adapters:

```python
import asyncio
from db_adapter import get_adapter, connect_and_validate

async def main():
    # Option 1: Direct URL (no db.toml needed)
    adapter = await get_adapter(database_url="postgresql://user:pass@localhost/mydb")

    # Option 2: Profile-based (reads db.toml)
    adapter = await get_adapter(profile_name="local")

    # Option 3: Env var resolution (reads DB_PROFILE env var, then .db-profile lock file)
    adapter = await get_adapter()

    # Option 4: Connect with schema validation first
    expected = {"users": {"id", "name", "email"}, "orders": {"id", "total", "user_id"}}
    result = await connect_and_validate("local", expected_columns=expected)
    if result.success:
        adapter = await get_adapter(profile_name="local")

    rows = await adapter.select("users", "*")
    await adapter.close()

asyncio.run(main())
```

Connect and validate via CLI:

```bash
DB_PROFILE=local db-adapter connect
```

### Schema validation

```python
from db_adapter import validate_schema
from db_adapter.schema import SchemaIntrospector

async def check_schema(url: str):
    expected = {
        "users": {"id", "name", "email", "created_at"},
        "orders": {"id", "user_id", "total", "status"},
    }

    async with SchemaIntrospector(url) as introspector:
        actual = await introspector.get_column_names()

    result = validate_schema(actual, expected)
    if result.valid:
        print("Schema OK")
    else:
        for diff in result.missing_columns:
            print(f"Missing: {diff.table}.{diff.column}")
```

### Backup & restore

Declare your table hierarchy with `BackupSchema`:

```python
import asyncio
from db_adapter import AsyncPostgresAdapter, BackupSchema, TableDef, ForeignKey
from db_adapter.backup import backup_database, restore_database, validate_backup

schema = BackupSchema(tables=[
    TableDef(name="authors", pk="id", slug_field="slug", user_field="user_id"),
    TableDef(name="books", pk="id", slug_field="slug", user_field="user_id",
             parent=ForeignKey(table="authors", field="author_id")),
    TableDef(name="chapters", pk="id", slug_field="slug", user_field="user_id",
             parent=ForeignKey(table="books", field="book_id")),
])

async def main():
    adapter = AsyncPostgresAdapter("postgresql://user:pass@localhost/mydb")

    # Backup
    path = await backup_database(adapter, schema, user_id="user-123")

    # Validate backup file (sync -- local file read only)
    report = validate_backup(path, schema)

    # Restore with FK ID remapping
    summary = await restore_database(adapter, schema, path, user_id="user-123")

    await adapter.close()

asyncio.run(main())
```

FK IDs are remapped automatically during restore — child records point to newly created parent IDs.

### Cross-profile data sync

```python
import asyncio
from db_adapter.schema import compare_profiles, sync_data

async def main():
    # Compare what would be synced
    result = await compare_profiles(
        "rds", "local",
        tables=["authors", "books"],
        user_id="user-123",
    )
    print(f"Source: {result.source_counts}, Dest: {result.dest_counts}")

    # Direct sync (flat tables, no FK remapping)
    result = await sync_data(
        "rds", "local",
        tables=["authors", "books"],
        user_id="user-123",
        dry_run=False,
        confirm=True,
    )

    # FK-aware sync with BackupSchema
    result = await sync_data(
        "rds", "local",
        tables=["authors", "books"],
        user_id="user-123",
        schema=schema,  # enables backup/restore path with ID remapping
        dry_run=False,
        confirm=True,
    )

asyncio.run(main())
```

### Configurable env prefix

For projects that namespace their env vars:

```python
# Default: reads DB_PROFILE env var
adapter = await get_adapter()

# With prefix: reads MC_DB_PROFILE env var
adapter = await get_adapter(env_prefix="MC_")
```

```bash
# CLI equivalent
db-adapter --env-prefix MC_ connect
```

## Architecture

```
db-adapter/
├── src/db_adapter/
│   ├── __init__.py           # Public API exports
│   ├── factory.py            # get_adapter(), connect_and_validate() (async)
│   ├── adapters/
│   │   ├── base.py           # DatabaseClient Protocol (async)
│   │   ├── postgres.py       # AsyncPostgresAdapter (SQLAlchemy + asyncpg)
│   │   └── supabase.py       # AsyncSupabaseAdapter (supabase-py async client)
│   ├── config/
│   │   ├── models.py         # DatabaseProfile, DatabaseConfig
│   │   └── loader.py         # TOML parser for db.toml
│   ├── schema/
│   │   ├── models.py         # ColumnSchema, SchemaValidationResult, ConnectionResult, etc.
│   │   ├── introspector.py   # SchemaIntrospector (async psycopg)
│   │   ├── comparator.py     # validate_schema(actual, expected) — pure sync logic
│   │   ├── fix.py            # generate_fix_plan(), apply_fixes() (async)
│   │   └── sync.py           # compare_profiles(), sync_data() (async)
│   ├── backup/
│   │   ├── models.py         # BackupSchema, TableDef, ForeignKey
│   │   └── backup_restore.py # backup_database(), restore_database() (async)
│   └── cli/
│       ├── __init__.py       # Main CLI (connect, status, profiles, validate, fix, sync)
│       └── backup.py         # Standalone backup CLI
└── tests/                    # 553 tests
```

### Key design decisions

- **Protocol, not inheritance** — `DatabaseClient` is a `typing.Protocol`. Adapters implement it structurally without inheriting from a base class.
- **Dicts, not ORMs** — All CRUD methods accept and return plain dicts. No model classes required.
- **Async-first** — All I/O operations are `async def`. CLI wraps with `asyncio.run()`. Schema comparator stays sync (pure set logic, no I/O).
- **JSONB handling** — `AsyncPostgresAdapter` serializes dict/list values to JSON strings with `CAST(:param AS jsonb)` for JSONB columns. Configurable via constructor parameter.
- **Profile lock file** — `.db-profile` stores the validated profile name. Written only after successful schema validation. Prevents connecting to unvalidated databases.
- **Set-based validation** — Schema comparator uses pure set operations (expected columns vs actual columns). No SQL generation — just reports diffs.
- **FK-aware operations** — Backup/restore and sync use `BackupSchema` for declarative FK relationships with automatic ID remapping.

## CLI Reference

```bash
db-adapter connect                                                    # Connect + validate schema
db-adapter status                                                     # Show current profile
db-adapter profiles                                                   # List available profiles
db-adapter validate                                                   # Re-validate current profile
db-adapter fix --schema-file schema.sql --column-defs defs.json       # Preview schema fix (dry run)
db-adapter fix --schema-file schema.sql --column-defs defs.json --confirm  # Apply schema fix
db-adapter sync --from rds --tables users,orders --user-id abc --dry-run   # Preview sync
db-adapter sync --from rds --tables users,orders --user-id abc --confirm   # Execute sync
db-adapter --env-prefix MC_ connect                                   # Use MC_DB_PROFILE env var
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Install with Supabase support
uv sync --extra supabase

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_name
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `sqlalchemy[asyncio]` | Async engine + connection pooling |
| `asyncpg` | Async PostgreSQL driver |
| `psycopg[binary]` | Async PostgreSQL introspection |
| `pydantic` | Models and validation |
| `rich` | CLI output formatting |
| `supabase` *(optional)* | Supabase async adapter |

## License

MIT

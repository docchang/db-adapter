# db-adapter

A dict-based database adapter library for Python with Protocol typing, multi-profile configuration, schema management, and backup/restore.

Like SQLAlchemy gives you the engine, db-adapter gives you a clean CRUD interface + tooling on top of it.

## Features

- **Protocol-typed adapters** — `DatabaseClient` protocol with PostgreSQL and Supabase implementations. All CRUD methods return plain dicts.
- **Multi-profile config** — TOML-based profiles (`local`, `rds`, `docker`, etc.) with profile lock files for validated connections.
- **Schema introspection** — Full database schema extraction via `information_schema` and `pg_catalog` (tables, columns, constraints, indexes, triggers, functions).
- **Schema validation & fix** — Set-based comparison of expected vs actual schema. Auto-fix with ALTER/DROP+CREATE.
- **Cross-profile data sync** — Compare and sync data between database profiles.
- **Backup/restore** — JSON-based backup with declarative table hierarchy and FK ID remapping on restore.
- **CLI** — `db-adapter connect|status|profiles|validate|fix|sync|backup|restore`

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
from db_adapter.adapters.postgres import PostgresAdapter

adapter = PostgresAdapter("postgresql://user:pass@localhost:5432/mydb")

# Select
rows = adapter.select("users", "id, name, email", filters={"active": True}, order_by="name")

# Insert
user = adapter.insert("users", {"name": "Alice", "email": "alice@example.com"})

# Update
updated = adapter.update("users", {"name": "Bob"}, filters={"id": user["id"]})

# Delete
adapter.delete("users", filters={"id": user["id"]})

adapter.close()
```

### Profile-based configuration

Create a `db.toml` in your project:

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

[schema]
file = "schema.sql"
validate_on_connect = true
```

Connect and validate:

```bash
DB_PROFILE=local db-adapter connect
```

Then use the factory:

```python
from db_adapter.factory import get_db_adapter

adapter = get_db_adapter()  # uses validated profile from .db-profile lock
rows = adapter.select("projects", "*")
```

### Backup & restore

Declare your table hierarchy:

```python
from db_adapter.backup.models import BackupSchema, TableDef, ForeignKey

schema = BackupSchema(tables=[
    TableDef("projects", pk="id", slug_field="slug", user_field="user_id"),
    TableDef("milestones", pk="id", slug_field="slug", user_field="user_id",
             parent=ForeignKey(table="projects", field="project_id")),
    TableDef("tasks", pk="id", slug_field="slug", user_field="user_id",
             parent=ForeignKey(table="projects", field="project_id"),
             optional_refs=[ForeignKey(table="milestones", field="milestone_id")]),
])
```

FK IDs are remapped automatically during restore.

## Architecture

```
db-adapter/
├── src/db_adapter/
│   ├── adapters/          # Layer 1: DatabaseClient Protocol + implementations
│   │   ├── base.py        #   Protocol definition (select/insert/update/delete/close)
│   │   ├── postgres.py    #   PostgreSQL via SQLAlchemy (connection pooling, JSONB handling)
│   │   └── supabase.py    #   Supabase via supabase-py client
│   ├── config/            # Layer 2: Multi-profile configuration
│   │   ├── models.py      #   DatabaseProfile, DatabaseConfig, schema models
│   │   └── loader.py      #   TOML parser for db.toml
│   ├── factory.py         # Layer 3: Profile resolution + adapter creation
│   ├── schema/            # Layer 4: Schema management
│   │   ├── models.py      #   ColumnSchema, TableSchema, DatabaseSchema
│   │   ├── introspector.py#   Live DB introspection via psycopg
│   │   ├── comparator.py  #   Set-based expected vs actual validation
│   │   ├── fix.py         #   ALTER/DROP+CREATE drift repair
│   │   └── sync.py        #   Cross-profile data sync
│   ├── backup/            # Layer 5: Backup & restore
│   │   ├── models.py      #   BackupSchema, TableDef, ForeignKey
│   │   └── backup_restore.py  # JSON backup/restore with FK remapping
│   └── cli/               # CLI entry point
│       ├── __init__.py    #   Main CLI (connect, status, profiles, validate, fix, sync)
│       └── backup.py      #   Backup/restore commands
└── tests/
```

### Key design decisions

- **Protocol, not inheritance** — `DatabaseClient` is a `typing.Protocol`. Adapters implement it structurally without inheriting from a base class.
- **Dicts, not ORMs** — All CRUD methods accept and return plain dicts. No model classes required.
- **JSONB handling** — PostgresAdapter serializes dict/list values to JSON strings with `CAST(:param AS jsonb)` for JSONB columns. Configurable via `JSONB_COLUMNS`.
- **Profile lock file** — `.db-profile` stores the validated profile name. Written only after successful schema validation. Prevents connecting to unvalidated databases.
- **Set-based validation** — Schema comparator uses pure set operations (expected columns vs actual columns). No SQL generation — just reports missing tables/columns.

## CLI Reference

```bash
db-adapter connect                        # Connect + validate schema
db-adapter status                         # Show current profile
db-adapter profiles                       # List available profiles
db-adapter validate                       # Re-validate current profile
db-adapter fix --confirm                  # Fix schema drift (backs up first)
db-adapter sync --from <profile> --dry-run  # Preview cross-profile sync
db-adapter sync --from <profile> --confirm  # Execute sync
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_name
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `sqlalchemy[asyncio]` | Connection pooling + SQL execution |
| `asyncpg` | Async PostgreSQL driver |
| `psycopg[binary]` | PostgreSQL introspection (schema tools) |
| `pydantic` | Models and validation |
| `rich` | CLI output formatting |
| `supabase` *(optional)* | Supabase adapter |

## Status

Early extraction from an internal project. The codebase contains sync implementations being converted to async-first. See `docs/db-adapter-lib-extraction.md` for the full migration plan.

## License

MIT

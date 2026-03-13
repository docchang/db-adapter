# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This workspace uses session agents. See `agents.md` for role definitions.

## Project Overview

`db-adapter` is an async-first, dict-based database adapter library for Python. It provides a Protocol-typed CRUD interface over PostgreSQL (and optionally Supabase), with multi-profile config (TOML), schema introspection/validation/fix, data sync between profiles, and backup/restore with FK remapping.

**Version:** 0.1.1 | **Python:** >=3.12 | **License:** MIT

## Build & Development

```bash
# Install dependencies
uv sync

# Install with Supabase support
uv sync --extra supabase

# Install with dev dependencies
uv sync --extra dev

# Run all tests (704 tests)
uv run pytest

# Run a single test file
uv run pytest tests/test_lib_extraction_adapters.py

# Run a single test
uv run pytest tests/test_lib_extraction_adapters.py::test_name

# CLI entry point
uv run db-adapter <command>
```

### Test Files

| File | Covers |
|------|--------|
| `test_lib_extraction_adapters.py` | DatabaseClient Protocol, AsyncPostgresAdapter, AsyncSupabaseAdapter |
| `test_lib_extraction_backup.py` | BackupSchema, backup/restore round-trips, FK remapping |
| `test_lib_extraction_cli.py` | CLI command parsing and execution |
| `test_lib_extraction_comparator.py` | Schema validation logic (set operations) |
| `test_lib_extraction_config.py` | TOML parsing, Pydantic models |
| `test_lib_extraction_exports.py` | Public API `__all__` lists, optional Supabase |
| `test_lib_extraction_factory.py` | `get_adapter()`, `connect_and_validate()`, profile lock |
| `test_lib_extraction_final.py` | Cross-module validation, no MC-specific code |
| `test_lib_extraction_fix.py` | `generate_fix_plan()`, `apply_fixes()`, DDL generation |
| `test_lib_extraction_imports.py` | Absolute import patterns |
| `test_lib_extraction_introspector.py` | SchemaIntrospector async context manager |
| `test_lib_extraction_models.py` | Pydantic model validation |
| `test_lib_extraction_sync.py` | `compare_profiles()`, `sync_data()` |
| `test_live_integration.py` | End-to-end tests against real PostgreSQL databases (requires `full` and `drift` profiles) |

pytest config: `asyncio_mode = "auto"` in pyproject.toml.

## Architecture

### Layered Design (5 layers, bottom-up)

1. **Adapters** (`adapters/`) — `DatabaseClient` Protocol + `AsyncPostgresAdapter` (SQLAlchemy async engine + asyncpg) + `AsyncSupabaseAdapter` (optional, supabase-py async). All CRUD methods return plain dicts.

2. **Config** (`config/`) — TOML-based multi-profile configuration. `DatabaseProfile` and `DatabaseConfig` Pydantic models in `config/models.py`. `loader.py` parses `db.toml` from the consuming project's working directory. Config supports `[schema]` (file, validate_on_connect, column_defs, backup_schema), `[sync]` (tables), and `[defaults]` (user_id_env) sections for CLI defaults.

3. **Factory** (`factory.py`) — Async profile resolution and adapter creation. `get_adapter()` creates adapters (no caching — callers can cache). `connect_and_validate()` introspects the live DB, validates schema, writes `.db-profile` lock file. Reads `{env_prefix}DB_PROFILE` env var or `.db-profile` lock file.

4. **Schema** (`schema/`) — Async introspection via `pg_catalog` (psycopg `AsyncConnection`), sync validation via pure set operations (`comparator.py`), async drift repair via ALTER/DROP+CREATE (`fix.py`), and async cross-profile data sync (`sync.py`).

5. **Backup** (`backup/`) — Async JSON-based backup/restore with declarative table hierarchy (`BackupSchema`, `TableDef`, `ForeignKey`). Handles FK ID remapping during restore.

### Key Patterns

- **Protocol typing:** `DatabaseClient` in `adapters/base.py` is a `typing.Protocol` — adapters implement it structurally (no inheritance required).
- **Async-first:** All I/O operations are `async def`. CLI wraps with `asyncio.run()`. Only pure-logic functions (comparator, models, config parsing) are sync.
- **JSONB handling:** `AsyncPostgresAdapter` accepts a `jsonb_columns` constructor parameter. Dicts/lists for these columns are serialized to JSON strings with `CAST(:param AS jsonb)`.
- **Profile lock file:** `.db-profile` stores the validated profile name. Written only after successful schema validation. Read by `get_adapter()` for profile resolution.
- **Schema validation is set-based:** `comparator.py` does pure set operations (expected columns vs actual columns). No SQL generation — just reports missing tables/columns.
- **Schema fix strategy:** 1 missing column -> ALTER ADD COLUMN. 2+ missing columns -> DROP+CREATE table (with backup first).
- **Config from CWD:** `load_db_config()` reads `db.toml` from `Path.cwd()`, not from the installed package.

### Import Style

All code uses **absolute package imports**: `from db_adapter.adapters.base import DatabaseClient`, `from db_adapter.schema.models import ...`, etc.

### CLI Commands

All 8 subcommands support config-driven defaults from `db.toml`. When `[schema]`, `[sync]`, and `[defaults]` sections are configured, common flags can be omitted.

```bash
# Profile management
db-adapter connect                                                    # Connect + validate schema + show table row counts
db-adapter status                                                     # Show current profile and table row counts (queries DB with graceful degradation)
db-adapter profiles                                                   # List profiles from db.toml
db-adapter validate                                                   # Re-validate current profile (uses schema.file from db.toml)
db-adapter validate --schema-file schema.sql                          # Re-validate with explicit schema file (overrides config)

# Schema fix (auto-backup before destructive changes when backup_schema configured)
db-adapter fix                                                        # Preview schema fix (uses schema.file and column_defs from db.toml)
db-adapter fix --schema-file schema.sql --column-defs defs.json       # Preview with explicit overrides
db-adapter fix --confirm                                              # Apply schema fix (auto-backup if backup_schema configured)
db-adapter fix --confirm --no-backup                                  # Apply without auto-backup

# Cross-profile data sync
db-adapter sync --from rds --dry-run                                  # Preview sync (uses tables and user_id from db.toml)
db-adapter sync --from rds --confirm                                  # Execute sync
db-adapter sync --from rds --tables users,orders --user-id abc --confirm   # Explicit overrides

# Backup and restore
db-adapter backup                                                     # Create backup (uses backup_schema and user_id from db.toml)
db-adapter backup --tables items                                      # Backup specific tables only
db-adapter backup --validate backup.json                              # Validate backup file (no DB connection)
db-adapter restore backup.json --dry-run                              # Preview restore
db-adapter restore backup.json --yes                                  # Restore without confirmation prompt
db-adapter restore backup.json --mode overwrite --yes                 # Restore with overwrite mode

# Env prefix
db-adapter --env-prefix MC_ connect                                   # Use MC_DB_PROFILE env var
```

### db.toml Configuration

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
file = "schema.sql"              # Path to SQL file with CREATE TABLE statements
validate_on_connect = true       # Validate schema on `db-adapter connect`
column_defs = "column-defs.json" # Column definitions for schema fix (default for --column-defs)
backup_schema = "backup-schema.json"  # BackupSchema JSON for backup/restore/auto-backup

[sync]
tables = ["users", "orders", "items"]  # Default tables for sync command

[defaults]
user_id_env = "DEV_USER_ID"      # Env var name for user_id resolution
```

### Public API (`db_adapter/__init__.py`)

```python
# Adapters
DatabaseClient, AsyncPostgresAdapter
AsyncSupabaseAdapter  # only with supabase extra

# Config
load_db_config, DatabaseProfile, DatabaseConfig

# Factory
get_adapter, connect_and_validate, ProfileNotFoundError, resolve_url

# Schema
validate_schema

# Backup models
BackupSchema, TableDef, ForeignKey
```

### Key Source Files

| File | Purpose |
|------|---------|
| `adapters/base.py` | `DatabaseClient` Protocol (6 async methods: select, insert, update, delete, execute, close) |
| `adapters/postgres.py` | `AsyncPostgresAdapter` — SQLAlchemy async engine + asyncpg, connection pooling, JSONB, URL normalization |
| `adapters/supabase.py` | `AsyncSupabaseAdapter` — supabase-py async client with lazy init + asyncio.Lock |
| `config/models.py` | `DatabaseProfile` (url, description, db_password, provider), `DatabaseConfig` (profiles, schema_file, column_defs, backup_schema, sync_tables, user_id_env) |
| `config/loader.py` | `load_db_config()` — parses `db.toml` from CWD |
| `factory.py` | `get_adapter()`, `connect_and_validate()`, profile lock file ops, URL resolution |
| `schema/models.py` | `SchemaValidationResult`, `ConnectionResult`, `ColumnSchema`, `TableSchema`, `DatabaseSchema`, etc. |
| `schema/introspector.py` | `SchemaIntrospector` — async context manager, `introspect()`, `get_column_names()` |
| `schema/comparator.py` | `validate_schema()` — pure sync set-based comparison |
| `schema/fix.py` | `generate_fix_plan()`, `apply_fixes()` — DDL generation with FK topological ordering |
| `schema/sync.py` | `compare_profiles()`, `sync_data()` — dual-path: direct insert or backup/restore |
| `backup/models.py` | `BackupSchema`, `TableDef`, `ForeignKey` — declarative table hierarchy |
| `backup/backup_restore.py` | `backup_database()`, `restore_database()`, `validate_backup()` |
| `cli/__init__.py` | Main CLI entry point with argparse (connect, status, profiles, validate, fix, sync, backup, restore) |

---

## Agent Roles

Roles are **assigned per session** — do not assume any role unless the user explicitly activates it (e.g., "You are the examiner", "You are the git agent"). See `agents.md` for full role definitions.

---

## Mission Control Integration

**This project is tracked in Mission Control portfolio system.**

When using Mission Control MCP tools (`mcp__mission-control__*`) to manage tasks, milestones, or project status, you are acting as the **PM (Project Manager) role**. Read these docs to understand the workflow, timestamp conventions, and scope:

- **Slug:** `db-adapter`
- **Role:** PM (Project Manager)
- **Read 1st:** `get_guide(name="PM_GUIDE")` - Project-level tactical execution
- **Read 2nd:** `get_guide(name="MCP_TOOLS_REFERENCE")` - Complete tool parameters

---

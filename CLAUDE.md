# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`db-adapter` is an async, dict-based database adapter library extracted from Mission Control. It provides a Protocol-typed CRUD interface over PostgreSQL (and optionally Supabase), with multi-profile config (TOML), schema introspection/validation/fix, data sync between profiles, and backup/restore with FK remapping.

**Status:** Early extraction — the codebase currently contains sync implementations being converted to async-first. See `docs/db-adapter-lib-extraction.md` for the full extraction plan and async migration design.

## Build & Development

```bash
# Install dependencies
uv sync

# Install with Supabase support
uv sync --extra supabase

# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_name

# CLI entry point
uv run db-adapter <command>
```

## Architecture

### Layered Design (5 layers, bottom-up)

1. **Adapters** (`adapters/`) — `DatabaseClient` Protocol + concrete implementations (`PostgresAdapter`, `SupabaseAdapter`). All CRUD methods return plain dicts. PostgresAdapter uses SQLAlchemy engine with connection pooling; Supabase wraps the supabase-py client.

2. **Config** (`config/`) — TOML-based multi-profile configuration. `DatabaseProfile` and `DatabaseConfig` models in `config/models.py`. `loader.py` parses `db.toml` files. Depends on `creational.common.config.SharedSettings` (will be decoupled).

3. **Factory** (`factory.py`) — Profile resolution and adapter creation. Reads `.db-profile` lock file or `MC_DB_PROFILE`/`MC_DATABASE_URL` env vars. `connect_and_validate()` introspects the live DB, validates schema, writes lock file, and caches the adapter. `get_db_adapter()` returns the cached adapter.

4. **Schema** (`schema/`) — Introspection via `information_schema` and `pg_catalog` (psycopg), validation by comparing expected columns (from consuming project's db_models) against actual, drift repair via ALTER/DROP+CREATE, and cross-profile data sync.

5. **Backup** (`backup/`) — JSON-based backup/restore with declarative table hierarchy (`BackupSchema`, `TableDef`, `ForeignKey`). Handles FK ID remapping during restore. Supports skip/overwrite/fail modes.

### Key Patterns

- **Protocol typing:** `DatabaseClient` in `adapters/base.py` is a `typing.Protocol` — adapters implement it structurally (no inheritance required).
- **JSONB handling:** PostgresAdapter has a `JSONB_COLUMNS` frozenset (will become a constructor param). Dicts/lists for these columns are serialized to JSON strings with `CAST(:param AS jsonb)`.
- **Profile lock file:** `.db-profile` stores the validated profile name. Written only after successful schema validation. Read by `get_db_adapter()` to determine which profile to connect to.
- **Schema validation is set-based:** `comparator.py` does pure set operations (expected columns vs actual columns). No SQL generation — just reports missing tables/columns.
- **Schema fix strategy:** 1 missing column → ALTER ADD COLUMN. 2+ missing columns → DROP+CREATE table (with backup first).

### CLI Commands

```bash
db-adapter connect           # Connect to DB and validate schema
db-adapter status            # Show current connection status
db-adapter profiles          # List available profiles from db.toml
db-adapter validate          # Re-validate current profile schema
db-adapter fix --confirm     # Fix schema drift (backs up first)
db-adapter sync --from <profile> --dry-run   # Compare data between profiles
db-adapter sync --from <profile> --confirm   # Sync data from another profile
```

Backup CLI is currently a separate entry point: `uv run python src/db_adapter/cli/backup.py backup|restore|validate`

### Import Style

The codebase currently uses **relative-style bare module imports** (e.g., `from adapters import ...`, `from schema.models import ...`). These are not standard relative imports — they rely on `sys.path` manipulation or the source root being in the path.

## Async Migration (Planned)

The extraction plan calls for converting all adapters and schema tools to async:
- `DatabaseClient` Protocol → all methods become `async def`
- `PostgresAdapter` → `AsyncPostgresAdapter` using `create_async_engine` + `asyncpg`
- `SchemaIntrospector` → async context manager with `psycopg.AsyncConnection`
- CLI commands wrap async with `asyncio.run()`
- `JSONB_COLUMNS` becomes a constructor parameter instead of class-level constant

---

## Mission Control Integration

**This project is tracked in Mission Control portfolio system.**

When using Mission Control MCP tools (`mcp__mission-control__*`) to manage tasks, milestones, or project status, you are acting as the **PM (Project Manager) role**. Read these docs to understand the workflow, timestamp conventions, and scope:

- **Slug:** `db-adapter`
- **Role:** PM (Project Manager)
- **Read 1st:** `get_guide(name="PM_GUIDE")` - Project-level tactical execution
- **Read 2nd:** `get_guide(name="MCP_TOOLS_REFERENCE")` - Complete tool parameters

---

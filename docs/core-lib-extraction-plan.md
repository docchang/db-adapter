# Core-Lib-Extraction Plan

> **Design**: See `docs/core-lib-extraction-design.md` for analysis and approach.
>
> **Track Progress**: See `docs/core-lib-extraction-results.md` for implementation status, test results, and issues.

## Overview

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-02-27T02:11:25-0800 |
| **Name** | Core Library Extraction |
| **Type** | Refactor |
| **Environment** | Python -- see `references/python-guide.md` |
| **Proves** | That db-adapter can be extracted into a standalone async-first library with zero MC-specific code |
| **Production-Grade Because** | Uses real async SQLAlchemy/asyncpg/psycopg drivers, validated Pydantic models, Protocol typing, and proper Python package structure -- no mocks or stubs |
| **Risk Profile** | Standard |
| **Risk Justification** | Greenfield library extraction with no consumers yet; all changes are additive and reversible before any downstream adoption. |

---

## Deliverables

Concrete capabilities this task delivers:

- All imports use proper `db_adapter.*` package paths (zero bare imports)
- `DatabaseClient` Protocol with all `async def` methods
- `AsyncPostgresAdapter` using `create_async_engine` with `asyncpg` driver
- `AsyncSupabaseAdapter` using `acreate_client` with lazy async init
- `SchemaIntrospector` using `psycopg.AsyncConnection` with `__aenter__`/`__aexit__`
- `validate_schema(actual, expected)` accepts caller-provided expected columns
- `JSONB_COLUMNS` as constructor parameter, not class constant
- Generic `backup_database()`/`restore_database()` driven by `BackupSchema` model
- Generic `compare_profiles()`/`sync_data()` with caller-declared table lists
- CLI using `db-adapter` as program name with `asyncio.run()` wrapping
- No `config/models.py` and `schema/models.py` duplication
- Zero imports from `fastmcp`, `creational.common`, `mcp.server.auth`, or `schema.db_models`
- Zero hardcoded MC-specific table names in library code
- Top-level `__init__.py` exports full public API

---

## Prerequisites

Complete these BEFORE starting implementation steps.

### 1. Identify Affected Tests

**Why Needed**: Run only affected tests during implementation (not full suite)

**Affected test files**:
- No test files exist yet (`tests/` directory is empty). All tests will be created during implementation steps.

**New test files to create**:
- `tests/test_lib_extraction_models.py` -- Config/schema model consolidation and validation
- `tests/test_lib_extraction_imports.py` -- Package import resolution
- `tests/test_lib_extraction_config.py` -- Config loader (MC code removed)
- `tests/test_lib_extraction_factory.py` -- Factory module (MC code removed, async)
- `tests/test_lib_extraction_comparator.py` -- Schema comparator (decoupled)
- `tests/test_lib_extraction_adapters.py` -- Async adapter structure and protocol compliance
- `tests/test_lib_extraction_introspector.py` -- Async introspector structure
- `tests/test_lib_extraction_fix.py` -- Schema fix module (generalized)
- `tests/test_lib_extraction_backup.py` -- Backup/restore (generic BackupSchema)
- `tests/test_lib_extraction_sync.py` -- Sync module (generalized)
- `tests/test_lib_extraction_cli.py` -- CLI (modernized)
- `tests/test_lib_extraction_exports.py` -- Package exports and public API

**Baseline verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short
# Expected: 0 tests collected (no test files exist yet)
```

### 2. Install Dependencies

**Why Needed**: The project dependencies are already declared in `pyproject.toml` but need to be installed.

**Commands**:
```bash
cd /Users/docchang/Development/db-adapter && uv sync --extra dev
```

**Verification** (inline OK for prerequisites):
```bash
cd /Users/docchang/Development/db-adapter && uv run python -c "import sqlalchemy; import pydantic; import asyncpg; print('Dependencies OK')"
# Expected: "Dependencies OK"
```

### 3. Confirm `config/models.py` and `schema/models.py` Duplication

**Why Needed**: Design states these files are identical. Verify before consolidating.

**Verification** (inline OK for prerequisites):
```bash
cd /Users/docchang/Development/db-adapter && diff src/db_adapter/config/models.py src/db_adapter/schema/models.py
# Expected: No diff (files are identical)
```

---

## Success Criteria

From Design doc (refined with verification commands):

- [ ] `uv sync` installs without errors
- [ ] `uv run python -c "from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter"` succeeds
- [ ] Zero imports from `fastmcp`, `creational.common`, `mcp.server.auth`, or `schema.db_models` in `src/`
- [ ] Zero hardcoded MC-specific table names (`"projects"`, `"milestones"`, `"tasks"`) in library code
- [ ] `DatabaseClient` Protocol has all `async def` methods
- [ ] `AsyncPostgresAdapter` uses `create_async_engine` with `asyncpg` driver
- [ ] `SchemaIntrospector` uses `psycopg.AsyncConnection` with `__aenter__`/`__aexit__`
- [ ] `validate_schema()` accepts `(actual_columns, expected_columns)` -- two parameters
- [ ] `JSONB_COLUMNS` is a constructor parameter, not a class constant
- [ ] `BackupSchema` model drives backup/restore instead of hardcoded table logic
- [ ] No duplicate model classes across `config/models.py` and `schema/models.py`
- [ ] CLI uses `db-adapter` as program name
- [ ] All existing model schemas (`BackupSchema`, `TableDef`, `ForeignKey`, `DatabaseProfile`, etc.) preserved

---

## Architecture

### File Structure
```
src/db_adapter/
├── __init__.py              # Public API exports
├── factory.py               # get_adapter(), connect_and_validate() -- async, configurable
├── adapters/
│   ├── __init__.py          # Exports
│   ├── base.py              # DatabaseClient Protocol (async)
│   ├── postgres.py          # AsyncPostgresAdapter (async engine, configurable JSONB)
│   └── supabase.py          # AsyncSupabaseAdapter (async client)
├── config/
│   ├── __init__.py          # Exports
│   ├── models.py            # DatabaseProfile, DatabaseConfig (config only)
│   └── loader.py            # load_db_config() -- TOML parser, no Settings class
├── schema/
│   ├── __init__.py          # Exports
│   ├── models.py            # Introspection + validation models (ColumnSchema, SchemaValidationResult, ConnectionResult, etc.)
│   ├── introspector.py      # SchemaIntrospector (async)
│   ├── comparator.py        # validate_schema(actual, expected) -- pure logic, sync
│   ├── fix.py               # generate_fix_plan(), apply_fixes() -- generic, async
│   └── sync.py              # compare_profiles(), sync_data() -- generic, async
├── backup/
│   ├── __init__.py          # Exports
│   ├── models.py            # BackupSchema, TableDef, ForeignKey (no change needed)
│   └── backup_restore.py    # backup_database(), restore_database() -- generic, async
├── cli/
│   ├── __init__.py          # main() entry point, all commands
│   └── backup.py            # Backup CLI (kept but not wired into main CLI)
tests/
├── test_lib_extraction_*.py # All tests
pyproject.toml               # Dependencies
```

### Design Principles
1. **OOP Design**: Use classes with single responsibility and clear interfaces (Protocol, adapters, introspector)
2. **Validated Data Models**: All data structures use Pydantic BaseModel (DatabaseProfile, BackupSchema, SyncResult, etc.)
3. **Strong Typing**: Type annotations on all functions, methods, and class attributes
4. **Async-First**: All I/O operations are async; CLI wraps with `asyncio.run()`

---

## Implementation Steps

**Approach**: Follow the design's proposed sequence, breaking each into bite-sized steps. Build bottom-up: models first, then imports, then remove MC coupling, then async conversion, then generalization, then CLI, then exports.

**Step-to-Design Mapping**:

| Plan Step | Design Analysis # | Topic |
|-----------|-------------------|-------|
| Step 0 | — | Environment setup |
| Step 1 | #4 | Model consolidation |
| Step 2 | #1 | Import fixes |
| Step 3 | #3 | Config MC removal |
| Step 4 | #2 | Factory MC removal |
| Step 5 | #7 | Comparator decoupling |
| Step 6 | #5 | Adapter async |
| Step 7 | #6 | Introspector async |
| Step 8 | #2 (async) | Factory async |
| Step 9 | #8 | Fix module generalization |
| Step 10 | #10 | Backup generalization |
| Step 11 | #9 | Sync generalization |
| Step 12 | #11 | CLI modernization |
| Step 13 | #12 | Package exports |
| Step 14 | — | Final validation |

> This plan is a contract between the executor (builder) and reviewer (validator). Steps specify **what** to build and **how** to verify -- the executor writes the implementation.

### Step 0: Verify Environment and Baseline

**Goal**: Confirm the development environment is ready and establish a clean starting point.

- [ ] Install all dependencies including dev extras
- [ ] Verify that `config/models.py` and `schema/models.py` are identical
- [ ] Create `tests/` directory marker if needed

**Code**:
```bash
cd /Users/docchang/Development/db-adapter && uv sync --extra dev --extra supabase
cd /Users/docchang/Development/db-adapter && diff src/db_adapter/config/models.py src/db_adapter/schema/models.py
cd /Users/docchang/Development/db-adapter && mkdir -p tests && touch tests/__init__.py && ls tests/
```

**Verification** (inline OK for Step 0):
```bash
cd /Users/docchang/Development/db-adapter && uv run python -c "import sqlalchemy; import pydantic; import asyncpg; import psycopg; print('OK')"
# Expected: OK
```

**Output**: Environment ready, duplication confirmed

---

### Step 1: Consolidate Duplicate Models

**Goal**: Resolve the duplication between `config/models.py` and `schema/models.py` by splitting models by domain. Each model lives in exactly one canonical location.

- [ ] Reduce `config/models.py` to contain only `DatabaseProfile` and `DatabaseConfig`
- [ ] Remove `DatabaseProfile` and `DatabaseConfig` from `schema/models.py` (they move to `config/models.py`)
- [ ] Keep `schema/models.py` with introspection models, validation models, and `ConnectionResult`
- [ ] Write tests verifying model placement and no duplication

**Specification**:
- `config/models.py` keeps: `DatabaseProfile`, `DatabaseConfig`
- `schema/models.py` currently has 12 classes; after removing `DatabaseProfile` and `DatabaseConfig`, it keeps 10 classes: `ColumnSchema`, `ConstraintSchema`, `IndexSchema`, `TriggerSchema`, `FunctionSchema`, `TableSchema`, `DatabaseSchema`, `ColumnDiff`, `SchemaValidationResult`, `ConnectionResult`
- Remove all classes from `config/models.py` that are not `DatabaseProfile` or `DatabaseConfig` (i.e., remove `ColumnDiff`, `SchemaValidationResult`, `ConnectionResult`, `ColumnSchema`, `ConstraintSchema`, `IndexSchema`, `TriggerSchema`, `FunctionSchema`, `TableSchema`, `DatabaseSchema`)
- Remove `DatabaseProfile` and `DatabaseConfig` from `schema/models.py` so they exist only in `config/models.py`
- Tests must verify: each class exists in exactly one file; `DatabaseProfile` and `DatabaseConfig` importable from `config/models`; `SchemaValidationResult`, `ConnectionResult`, and introspection models importable from `schema/models`

**Acceptance Criteria**:
- `config/models.py` contains exactly 2 model classes: `DatabaseProfile`, `DatabaseConfig`
- `schema/models.py` contains exactly 10 model classes (introspection + validation — `DatabaseProfile`/`DatabaseConfig` removed)
- `grep -r "class DatabaseProfile" src/` returns exactly 1 result (in `config/models.py`)
- `grep -r "class SchemaValidationResult" src/` returns exactly 1 result (in `schema/models.py`)
- Tests pass verifying model instantiation and field validation for both config and schema models

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_models.py -v
```

**Output**: Tests passing

---

### Step 2: Fix Package Imports

**Goal**: Convert all bare module imports to proper `db_adapter.*` package imports so the package can be imported when installed.

- [ ] Replace every bare import in all `.py` files under `src/db_adapter/`
- [ ] Fix `adapters/__init__.py` reference from `adapters.postgres_adapter` to `adapters.postgres`
- [ ] Update imports that reference models to point to canonical locations (per Step 1)
- [ ] Remove MC-specific imports that will break (`from schema.db_models import ...`, `from creational.common.config import ...`, `from fastmcp import ...`, `from mcp.server.auth ...`). Replace with placeholder comments or `pass` where needed to keep files syntactically valid -- actual functional replacements happen in later steps
- [ ] Write tests verifying all subpackages import cleanly

**Specification**:
- Apply the import mapping from the design document (see Analysis #1 table)
- Key mappings:
  - `from adapters import ...` -> `from db_adapter.adapters import ...`
  - `from adapters.base import ...` -> `from db_adapter.adapters.base import ...`
  - `from adapters.postgres_adapter import ...` -> `from db_adapter.adapters.postgres import ...`
  - `from config import load_db_config` -> `from db_adapter.config.loader import load_db_config`
  - `from config import get_settings` -> REMOVE (MC-specific)
  - `from schema.models import DatabaseProfile, DatabaseConfig` -> `from db_adapter.config.models import DatabaseProfile, DatabaseConfig`
  - `from schema.models import ConnectionResult, ColumnDiff, SchemaValidationResult` -> `from db_adapter.schema.models import ...`
  - `from schema.models import ColumnSchema, ...` -> `from db_adapter.schema.models import ...`
  - `from schema.comparator import ...` -> `from db_adapter.schema.comparator import ...`
  - `from schema.introspector import ...` -> `from db_adapter.schema.introspector import ...`
  - `from schema.fix import ...` -> `from db_adapter.schema.fix import ...`
  - `from schema.sync import ...` -> `from db_adapter.schema.sync import ...`
  - `from schema.db_models import ...` -> REMOVE
  - `from db import ...` -> `from db_adapter.factory import ...`
  - `from backup.backup_restore import ...` -> `from db_adapter.backup.backup_restore import ...`
  - `from backup.backup_cli import ...` -> `from db_adapter.cli.backup import ...` (included for completeness; this import pattern may not exist in current codebase)
- For MC-specific imports that are removed (`fastmcp`, `creational.common`, `mcp.server.auth`, `schema.db_models`, `config.get_settings`): comment them out or remove the lines. The functions that depend on them will be cleaned up in later steps (Steps 3-4 for factory/config, Step 5 for comparator, etc.)
- `adapters/__init__.py` must import from `db_adapter.adapters.base` and `db_adapter.adapters.postgres` (not `adapters.postgres_adapter`)
- Tests must verify: `import db_adapter`, `from db_adapter.config.models import DatabaseProfile`, `from db_adapter.schema.models import SchemaValidationResult`, `from db_adapter.backup.models import BackupSchema` all succeed without `ModuleNotFoundError`

**Acceptance Criteria**:
- `grep -rPn "^\s*from (adapters|config|schema\.|db\b(?!_adapter)|backup\.)" src/db_adapter/ --include="*.py"` returns zero results for bare imports (anchored to line start; `db\b(?!_adapter)` avoids false positives on `from db_adapter.*` imports)
- `uv run python -c "import db_adapter"` succeeds without `ModuleNotFoundError`
- `uv run python -c "from db_adapter.config.models import DatabaseProfile; from db_adapter.schema.models import SchemaValidationResult; from db_adapter.backup.models import BackupSchema; print('OK')"` succeeds
- Tests pass verifying subpackage imports

**Trade-offs**:
- **Handling MC-specific imports**: Comment out rather than delete because later steps need to see what was there and replace functionally. Alternative: delete now and re-check in later steps from design doc.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_imports.py -v
```

**Output**: Tests passing

---

### Step 3: Remove MC-Specific Code from Config Loader

**Goal**: Strip `Settings` class, `get_settings()`, and `SharedSettings` import from `config/loader.py`. Keep only the generic TOML-based `load_db_config()`.

- [ ] Remove `Settings(SharedSettings)` class entirely
- [ ] Remove `get_settings()` function
- [ ] Remove `from creational.common.config import SharedSettings`
- [ ] Remove `from functools import lru_cache`
- [ ] Remove `from pydantic import AliasChoices, Field`
- [ ] Update `load_db_config()` import to `from db_adapter.config.models import DatabaseConfig, DatabaseProfile` (Step 2 converted bare `from schema.models` imports to `db_adapter.*` paths; this step ensures loader.py uses the canonical location after Step 1's consolidation)
- [ ] Change default `config_path` from `Path(__file__).parent / "db.toml"` to `Path.cwd() / "db.toml"` (library reads config from consuming project's working directory, not from inside the installed package)
- [ ] Update `config/__init__.py` to export `load_db_config`, `DatabaseProfile`, `DatabaseConfig`
- [ ] Write tests

**Specification**:
- `config/loader.py` after this step should contain only: `import tomllib`, `from pathlib import Path`, `from db_adapter.config.models import DatabaseConfig, DatabaseProfile`, and the `load_db_config()` function
- `load_db_config(config_path: Path | None = None) -> DatabaseConfig` signature unchanged except default path changes to `Path.cwd() / "db.toml"`
- Tests must verify: `load_db_config()` with a sample TOML file parses profiles correctly; `load_db_config()` raises `FileNotFoundError` when file is missing; no `Settings` or `get_settings` importable from the module

**Acceptance Criteria**:
- `config/loader.py` has zero imports from `creational`, `pydantic`, or `functools`
- `grep -En "class Settings|def get_settings|SharedSettings" src/db_adapter/config/loader.py` returns nothing
- `load_db_config()` loads a TOML file with profiles and returns a `DatabaseConfig` with correct `DatabaseProfile` entries
- Default config path is `Path.cwd() / "db.toml"` (not `Path(__file__).parent`)
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_config.py -v
```

**Output**: Tests passing

---

### Step 4: Remove MC-Specific Code from Factory

**Goal**: Strip all Mission Control-specific functions and imports from `factory.py`, restructure `get_db_adapter()` to `get_adapter()`, and make `connect_and_validate()` accept caller-provided `expected_columns`.

- [ ] Remove `AuthenticationError` class
- [ ] Remove `get_dev_user_id()` function
- [ ] Remove `get_user_id_from_ctx()` function
- [ ] Remove `cleanup_project_all_dbs()` function
- [ ] Remove `cleanup_projects_pattern()` function
- [ ] Remove `reset_client()` function
- [ ] Remove module-level `_adapter` global cache
- [ ] Remove `from fastmcp import Context` import
- [ ] Add `env_prefix` parameter to `get_active_profile_name()`
- [ ] Add `expected_columns` parameter to `connect_and_validate()`
- [ ] Rename `get_db_adapter()` to `get_adapter()` with `env_prefix`, `database_url`, `jsonb_columns` parameters
- [ ] Change `_PROFILE_LOCK_FILE` to use `Path.cwd()` instead of `Path(__file__).parent`
- [ ] Update `get_active_profile_name()` to use configurable env var prefix (`{prefix}DB_PROFILE`)
- [ ] Update error messages that reference "Mission Control", `python -m schema`, or `MC_DB_PROFILE` to use generic `db-adapter` references
- [ ] Keep functions sync for now -- async conversion happens in later steps (after adapters become async)
- [ ] Write tests

**Specification**:
- `factory.py` keeps: `ProfileNotFoundError`, `read_profile_lock()`, `write_profile_lock()`, `clear_profile_lock()`, `get_active_profile_name()`, `get_active_profile()`, `_resolve_url()`, `connect_and_validate()`, `get_adapter()`
- `get_active_profile_name(env_prefix: str = "") -> str`: reads `{env_prefix}DB_PROFILE` env var (e.g., `MC_DB_PROFILE` when `env_prefix="MC_"`)
- `connect_and_validate(profile_name, expected_columns, env_prefix, validate_only) -> ConnectionResult`: when `expected_columns` is `None`, skip schema validation (connection-only mode). Note: accept `expected_columns` param but only use for the None-skip logic in Step 4; the actual pass-through to `validate_schema(actual, expected)` happens in Step 8 after the comparator signature changes in Step 5.
- `get_adapter(profile_name: str | None = None, env_prefix: str = "", database_url: str | None = None, jsonb_columns: list[str] | None = None) -> DatabaseClient`: factory function, no caching. Creates a new adapter each time. If `profile_name` is None, resolves from lock file or env var (with prefix). If `database_url` is provided, uses it directly (ignores profile).
- `_PROFILE_LOCK_FILE` = `Path.cwd() / ".db-profile"` (not inside package)
- All MC-specific error messages referencing `python -m schema` or `MC_DB_PROFILE` must be updated to use generic `db-adapter` references
- Tests must verify: `ProfileNotFoundError` raised when no profile; `_resolve_url()` password substitution works; `get_active_profile_name()` reads env var with prefix; `get_adapter()` returns adapter for given URL; `connect_and_validate()` skips validation when `expected_columns` is `None`
- **Test scope note**: Step 4 tests cover the sync factory API (MC removal, new parameters, sync function signatures). Step 8 rewrites these tests for the async factory API (`async def`, `AsyncPostgresAdapter` creation, `async with SchemaIntrospector`).

**Acceptance Criteria**:
- `factory.py` has zero imports from `fastmcp`, `mcp`, or `creational`
- `grep -En "get_user_id_from_ctx|get_dev_user_id|cleanup_project|reset_client|AuthenticationError|_adapter" src/db_adapter/factory.py` returns nothing (except possibly `get_adapter` function name)
- No module-level mutable state (`global _adapter`)
- `get_active_profile_name(env_prefix="MC_")` reads `MC_DB_PROFILE` env var
- `connect_and_validate(expected_columns=None)` returns `ConnectionResult` without calling `validate_schema`
- `_resolve_url()` correctly substitutes `[YOUR-PASSWORD]` placeholder
- Tests pass

**Trade-offs**:
- **Sync vs async factory functions**: Keep sync for now because the underlying adapters are still sync. Converting to async is done after Step 6 (adapter async conversion). Alternative: convert to async now but use `asyncio.run()` internally -- adds complexity.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_factory.py -v
```

**Output**: Tests passing

---

### Step 5: Decouple Schema Comparator

**Goal**: Decouple `validate_schema()` from MC's `db_models` module by changing its signature to accept both `actual_columns` and `expected_columns` as parameters. Remove the MC-specific `from schema.db_models import get_all_expected_columns` import.

- [ ] Remove `from schema.db_models import get_all_expected_columns` import (already converted to `from db_adapter...` or commented out in Step 2)
- [ ] Change `validate_schema()` signature to `validate_schema(actual_columns, expected_columns)`
- [ ] Remove internal call to `get_all_expected_columns()` -- use `expected_columns` parameter instead
- [ ] Update module docstring to reflect new API
- [ ] Update the `validate_schema()` call site in `factory.py` to pass `expected_columns` from `connect_and_validate()`'s own parameter. If `expected_columns` is None, skip the `validate_schema()` call entirely (connection-only mode per Step 4) — this prevents a broken call site between Steps 5 and 8
- [ ] Write tests

**Specification**:
- `validate_schema(actual_columns: dict[str, set[str]], expected_columns: dict[str, set[str]]) -> SchemaValidationResult`
- Function body remains identical (pure set operations) -- only the source of `expected_columns` changes
- This function stays **sync** because it is pure set comparison logic with no IO
- Update the factory call site (`factory.py`) in this step to avoid intermediate breakage: pass `expected_columns` from `connect_and_validate()`'s own parameter. If `expected_columns` is None, skip the `validate_schema()` call entirely (connection-only mode per Step 4). Step 8 will make the factory async but the call site will already have the correct parameter count.
- Tests must verify: missing tables detected, missing columns detected, extra tables detected (warning only), valid schema returns `valid=True`, empty expected returns valid

**Acceptance Criteria**:
- `comparator.py` has zero imports from `schema.db_models`
- `validate_schema()` accepts exactly 2 positional parameters: `actual_columns` and `expected_columns`
- `validate_schema({"t1": {"a", "b"}}, {"t1": {"a", "b", "c"}})` returns `SchemaValidationResult(valid=False, missing_columns=[ColumnDiff(table="t1", column="c", ...)])`
- `validate_schema({"t1": {"a"}}, {"t1": {"a"}})` returns `SchemaValidationResult(valid=True)`
- `validate_schema({"t1": {"a"}}, {"t2": {"a"}})` returns missing table `t2` and extra table `t1`
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_comparator.py -v
```

**Output**: Tests passing

---

### Step 6: Convert Adapters to Async

**Goal**: Convert `DatabaseClient` Protocol, `PostgresAdapter`, and `SupabaseAdapter` from sync to async implementations.

- [ ] `DatabaseClient` Protocol: all methods become `async def`
- [ ] Rename `PostgresAdapter` to `AsyncPostgresAdapter`
- [ ] Rename `create_mc_engine()` to `create_async_engine_pooled()`
- [ ] Replace `sqlalchemy.create_engine` with `sqlalchemy.ext.asyncio.create_async_engine`
- [ ] URL rewrite: `postgresql://` to `postgresql+asyncpg://`
- [ ] Replace `engine.connect()` with `async_engine.connect()` (async context manager)
- [ ] Replace `engine.begin()` with `async_engine.begin()` (async context manager)
- [ ] `JSONB_COLUMNS` becomes constructor parameter (not class constant)
- [ ] `engine.dispose()` becomes `await engine.dispose()`
- [ ] Convert existing `test_connection()` method to `async def` on `AsyncPostgresAdapter`
- [ ] Rename `SupabaseAdapter` to `AsyncSupabaseAdapter`
- [ ] Replace `supabase.Client` / `create_client` with `supabase.acreate_client`
- [ ] Implement lazy async init with `asyncio.Lock`
- [ ] Update `adapters/__init__.py` exports
- [ ] Write tests

**Specification**:
- `DatabaseClient` Protocol methods: `async def select(...)`, `async def insert(...)`, `async def update(...)`, `async def delete(...)`, `async def close(...)`. Note: `async def execute(...)` is added in Step 9. `test_connection()` is converted from the existing sync method in this step (see checklist) — it exists on adapter classes but is NOT a Protocol method.
- `AsyncPostgresAdapter.__init__(self, database_url: str, jsonb_columns: list[str] | None = None, **engine_kwargs)`:
  - Converts `postgresql://` to `postgresql+asyncpg://` (prefix match, not global replace)
  - Stores `frozenset(jsonb_columns or [])` as `self._jsonb_columns`
  - Creates engine via `create_async_engine_pooled(async_url, **engine_kwargs)`
- `create_async_engine_pooled(database_url: str, **kwargs) -> AsyncEngine`: replaces `create_mc_engine()`, uses `create_async_engine` with same pool settings
- `AsyncSupabaseAdapter.__init__(self, url: str, key: str)`: stores URL/key, `self._client = None`, `self._lock = asyncio.Lock()`
- `AsyncSupabaseAdapter._get_client(self) -> AsyncClient`: lazy init with lock
- `AsyncSupabaseAdapter.close(self)`: if `self._client` is not None, close it; if client was never initialized, no-op
- `adapters/__init__.py`: export `DatabaseClient`, `AsyncPostgresAdapter`; conditional `AsyncSupabaseAdapter` export with `try/except ImportError`
- Tests must verify: `AsyncPostgresAdapter` has all `async def` CRUD methods; `JSONB_COLUMNS` is NOT a class constant (constructor param); URL rewrite from `postgresql://` to `postgresql+asyncpg://`; `DatabaseClient` Protocol defines async methods; `AsyncSupabaseAdapter` uses lazy client init pattern

**Acceptance Criteria**:
- `PostgresAdapter` class no longer exists; only `AsyncPostgresAdapter`
- `create_mc_engine` function no longer exists; only `create_async_engine_pooled`
- `JSONB_COLUMNS` does not appear as a class constant (`grep "JSONB_COLUMNS = frozenset" src/` returns nothing)
- All 5 Protocol methods are `async def` in `base.py`
- `AsyncPostgresAdapter` uses `from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine`
- `AsyncSupabaseAdapter` uses `from supabase import acreate_client, AsyncClient`
- All `engine.connect()` and `engine.begin()` calls use `async with` (not sync `with`)
- Tests pass

**Trade-offs**:
- **Supabase async import path**: `acreate_client` may vary between supabase-py versions. Use `try/except ImportError` for robustness. Alternative: pin exact supabase version.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_adapters.py -v
```

**Output**: Tests passing

---

### Step 7: Convert Schema Introspector to Async

**Goal**: Convert `SchemaIntrospector` from sync `psycopg.connect()` to async `psycopg.AsyncConnection.connect()`.

- [ ] Replace `psycopg.connect()` with `await psycopg.AsyncConnection.connect()`
- [ ] Replace `__enter__`/`__exit__` with `__aenter__`/`__aexit__`
- [ ] All query methods become `async def` (except `_normalize_data_type` which is pure logic)
- [ ] Add `async def test_connection()` method (plan refinement: not in design Analysis #6; runs `SELECT 1` to verify the psycopg connection is alive)
- [ ] Replace sync cursor usage with async cursor
- [ ] `EXCLUDED_TABLES` becomes a configurable constructor parameter with sensible defaults
- [ ] Write tests

**Specification**:
- `SchemaIntrospector.__init__(self, database_url: str, excluded_tables: set[str] | None = None, connect_timeout: int = 10)`: `excluded_tables` defaults to `EXCLUDED_TABLES_DEFAULT` class constant (`{"schema_migrations", "pg_stat_statements", "spatial_ref_sys"}`). Preserve the existing `connect_timeout` parameter from the sync implementation.
- `async def __aenter__(self) -> "SchemaIntrospector"`: opens `psycopg.AsyncConnection`
- `async def __aexit__(...)`: closes connection
- `async def test_connection(...)`: tests the database connection (I/O operation, must be async)
- `async def introspect(...)`, `async def get_column_names(...)`, `async def _get_tables(...)`, `async def _get_columns(...)`, `async def _get_constraints(...)`, `async def _get_indexes(...)`, `async def _get_triggers(...)`, `async def _get_functions(...)`
- `def _normalize_data_type(...)` stays sync (pure logic)
- Cursor usage: `async with self._conn.cursor() as cur: await cur.execute(...); rows = await cur.fetchall()`
- Tests must verify: class has `__aenter__`/`__aexit__` (not `__enter__`/`__exit__`); query methods are coroutines; `_normalize_data_type` remains sync; `excluded_tables` is configurable

**Acceptance Criteria**:
- `grep -En "psycopg.connect|def __enter__|def __exit__" src/db_adapter/schema/introspector.py` returns nothing
- `SchemaIntrospector` has `__aenter__` and `__aexit__` methods
- All query methods (`test_connection`, `introspect`, `get_column_names`, `_get_tables`, `_get_columns`, `_get_constraints`, `_get_indexes`, `_get_triggers`, `_get_functions`) are `async def`
- `_normalize_data_type` is a regular `def` (not async)
- `EXCLUDED_TABLES` is a constructor parameter with default
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_introspector.py -v
```

**Output**: Tests passing

---

### Step 8: Convert Factory to Async

**Goal**: Now that adapters and introspector are async, convert `connect_and_validate()` and `get_adapter()` to async functions.

- [ ] `connect_and_validate()` becomes `async def`
- [ ] `get_adapter()` becomes `async def`
- [ ] Update introspector usage to `async with SchemaIntrospector(...) as introspector`
- [ ] Update adapter creation to use `AsyncPostgresAdapter`
- [ ] Update `validate_schema()` call to pass `expected_columns` parameter
- [ ] Write tests

**Specification**:
- `async def connect_and_validate(profile_name, expected_columns, env_prefix, validate_only) -> ConnectionResult`
- `async def get_adapter(profile_name, env_prefix, database_url, jsonb_columns) -> DatabaseClient`
- Inside `connect_and_validate()`: `async with SchemaIntrospector(url) as introspector: actual = await introspector.get_column_names()`
- When `expected_columns` is `None`: skip both introspection and validation entirely (connection-only mode — do not open `SchemaIntrospector`). When `expected_columns` is provided: `validation = validate_schema(actual, expected_columns)` (sync call, comparator stays sync).
- `get_adapter()` creates `AsyncPostgresAdapter(database_url=url, jsonb_columns=jsonb_columns)`. Note: `get_adapter()` is async for API consistency with `connect_and_validate()` and to allow future async initialization steps, even though current implementation performs no I/O requiring await.
- Tests must verify: both functions are coroutines; `connect_and_validate` returns `ConnectionResult`; `get_adapter` returns an `AsyncPostgresAdapter` instance (tested via mock/patch of adapter creation)

**Acceptance Criteria**:
- `connect_and_validate` and `get_adapter` are `async def` in `factory.py`
- No sync `SchemaIntrospector` usage (no `with` -- only `async with`)
- `connect_and_validate` passes `expected_columns` to `validate_schema()` when provided (verifiable via test mock/assert)
- `get_adapter` creates `AsyncPostgresAdapter` (not `PostgresAdapter`)
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_factory.py -v
```

**Output**: Tests passing

---

### Step 9: Generalize Schema Fix Module

**Goal**: Remove hardcoded `COLUMN_DEFINITIONS` and MC-specific imports from `fix.py`. Make functions accept caller-provided parameters.

- [ ] Remove `COLUMN_DEFINITIONS` dict entirely
- [ ] Remove MC-coupled imports (`from db import ...`, `from adapters import PostgresAdapter`, `from backup.backup_restore import ...`, `from config import ...`)
- [ ] Modify `generate_fix_plan()` to accept `validation_result`, `column_definitions`, `schema_file` parameters
- [ ] Modify `apply_fixes()` to accept adapter, plan, callback parameters; convert to async
- [ ] Remove `profile_name` from `FixPlan` and `FixResult`
- [ ] Add `drop_order: list[str]` and `create_order: list[str]` to `FixPlan`
- [ ] Add `execute` method to `DatabaseClient` Protocol for DDL operations
- [ ] Implement `execute(sql, params)` on `AsyncPostgresAdapter` (via async engine connection) and `AsyncSupabaseAdapter` (raise `NotImplementedError`)
- [ ] Modify `_get_table_create_sql()` to require `schema_file` (no default path)
- [ ] Write tests

**Specification**:
- `generate_fix_plan(validation_result: SchemaValidationResult, column_definitions: dict[str, str], schema_file: str | Path) -> FixPlan` -- pure sync logic, no I/O. Callers must first obtain `validation_result` by running introspection and comparison: `async with SchemaIntrospector(url) as i: actual = await i.get_column_names()` then `result = validate_schema(actual, expected)`.
- `async def apply_fixes(adapter: DatabaseClient, plan: FixPlan, backup_fn: Callable[[DatabaseClient, str], Awaitable[str]] | None = None, restore_fn: Callable[[DatabaseClient, str], Awaitable[None]] | None = None, verify_fn: Callable[[DatabaseClient], Awaitable[bool]] | None = None, dry_run: bool = True, confirm: bool = False) -> FixResult` -- callbacks are async; `backup_fn(adapter, table_name)` returns backup path, `restore_fn(adapter, backup_path)` restores, `verify_fn(adapter)` verifies post-fix state
- `FixPlan` dataclass: remove `profile_name`, add `drop_order: list[str]`, `create_order: list[str]`. `generate_fix_plan()` computes these from FK relationships in `schema_file` (reverse topological sort for drops, forward topological sort for creates).
- `FixResult` Pydantic model: remove `profile_name`
- `DatabaseClient` Protocol: add `async def execute(self, sql: str, params: dict | None = None) -> None: ...` for DDL. Implement on `AsyncPostgresAdapter` via `async with self._engine.begin() as conn: await conn.execute(text(sql), params)`. `AsyncSupabaseAdapter` raises `NotImplementedError` (DDL not supported via Supabase client).
- `_get_table_create_sql(table_name: str, schema_file: str | Path) -> str` -- `schema_file` is required (no None default, no fallback path)
- Tests must verify: `generate_fix_plan()` creates correct plan from validation result and column definitions; `FixPlan` has no `profile_name`; `_get_table_create_sql` requires `schema_file`; `ColumnFix.to_sql()` generates correct ALTER TABLE; `TableFix.to_sql()` returns CREATE TABLE SQL

**Acceptance Criteria**:
- `COLUMN_DEFINITIONS` dict does not exist in `fix.py`
- `grep -En "from db import|from adapters import|from backup\.|from config import" src/db_adapter/schema/fix.py` returns nothing
- `generate_fix_plan()` accepts 3 parameters (no `profile_name`)
- `apply_fixes()` is `async def` and accepts adapter + callbacks
- `FixPlan` and `FixResult` have no `profile_name` field
- `DatabaseClient` Protocol has `execute` method
- Tests pass

**Trade-offs**:
- **Adding `execute` to Protocol vs separate engine parameter**: Adding to Protocol keeps the interface clean and avoids exposing SQLAlchemy internals. Alternative: accept a separate engine/connection parameter for DDL. Preferred: add to Protocol since DDL execution is a legitimate database operation.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_fix.py -v
```

**Output**: Tests passing

---

### Step 10: Generalize Backup/Restore

**Goal**: Rewrite `backup_database()` and `restore_database()` to use the `BackupSchema` declarative model instead of hardcoded MC table logic.

- [ ] Rewrite `backup_database()` to accept `adapter`, `schema`, `user_id`, `output_path`, `table_filters`, `metadata` parameters
- [ ] Rewrite `restore_database()` to accept `adapter`, `schema`, `backup_path`, `user_id`, `mode`, `dry_run` parameters
- [ ] Iterate `schema.tables` instead of hardcoded table names
- [ ] Use `TableDef.pk`, `TableDef.slug_field`, `TableDef.user_field` for column references
- [ ] Use `TableDef.parent` and `TableDef.optional_refs` for generic FK remapping
- [ ] Build generic `id_maps: dict[str, dict]` keyed by table name
- [ ] Remove `from db import get_db_adapter, get_dev_user_id` and `from config import get_settings`
- [ ] Update `validate_backup()` to accept `schema: BackupSchema` parameter; fix version check logic to accept `"1.1"` as expected version
- [ ] Convert `backup_database()` and `restore_database()` to async (`validate_backup()` stays sync — local file read only)
- [ ] Remove print statements (callers handle output)
- [ ] Write tests

**Specification**:
- `async def backup_database(adapter: DatabaseClient, schema: BackupSchema, user_id: str, output_path: str | None = None, table_filters: dict[str, dict] | None = None, metadata: dict | None = None) -> str` — `table_filters` allows callers to add per-table WHERE clause filters (e.g., `{"projects": {"status": "active"}}`) to limit which rows are backed up
- `async def restore_database(adapter: DatabaseClient, schema: BackupSchema, backup_path: str, user_id: str, mode: Literal["skip", "overwrite", "fail"] = "skip", dry_run: bool = False) -> dict`
- `def validate_backup(backup_path: str, schema: BackupSchema) -> dict` (stays **sync** -- reads a local JSON file, no database I/O)
- **Async/sync summary**: `backup_database()` and `restore_database()` become `async def` (database I/O). `validate_backup()` stays sync (local file read only).
- FK remapping: `id_maps = {}` -> for each `table_def` in `schema.tables`, build `id_maps[table_def.name] = {}` mapping old PK to new PK. When restoring a child table, look up `parent.field` value in `id_maps[parent.table]`. For `optional_refs`, null out the field if ref not found.
- Backup metadata: no `db_provider` field written. Optional `metadata` dict merged into metadata section.
- `validate_backup()` checks table keys against `schema.tables` names instead of hardcoded list
- Tests must verify: `backup_database` iterates `BackupSchema.tables`; `restore_database` performs FK remapping via `id_maps`; `validate_backup` checks against schema table names; backup JSON format has `version: "1.1"`; round-trip backup/restore preserves data

**Acceptance Criteria**:
- Zero hardcoded table names (`"projects"`, `"milestones"`, `"tasks"`) in `backup_restore.py`
- `backup_restore.py` has zero imports from `db`, `config`, or `adapters` (receives adapter as parameter)
- `backup_database()` and `restore_database()` are `async def`
- `BackupSchema` drives table iteration order and FK remapping
- `validate_backup()` accepts `schema` parameter
- No print statements in module (callers handle output)
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_backup.py -v
```

**Output**: Tests passing

---

### Step 11: Generalize Sync Module

**Goal**: Remove hardcoded `projects/milestones/tasks` references from `sync.py`. Make sync operations work with caller-declared table lists.

- [ ] Redesign `SyncResult` to use dynamic table names (no hardcoded defaults)
- [ ] `compare_profiles()` accepts `tables`, `user_id`, `user_field`, `slug_field`, `env_prefix` parameters (`env_prefix` allows consuming projects to namespace their env vars, e.g., `env_prefix="MC_"` reads `MC_DB_PROFILE`; default `""` reads `DB_PROFILE`)
- [ ] `sync_data()` accepts same parameters plus `dry_run`, `confirm`
- [ ] Replace subprocess-based sync with direct async calls to `backup_database()`/`restore_database()`
- [ ] Remove `from db import _resolve_url, get_dev_user_id` imports
- [ ] Generic flat slug resolution (no hierarchical project_slug/slug composition)
- [ ] Internal adapter creation via `load_db_config` and `_resolve_url` from `db_adapter`
- [ ] Convert to async
- [ ] Write tests

**Specification**:
- `SyncResult(BaseModel)`: `source_counts: dict[str, int] = Field(default_factory=dict)`, `dest_counts: dict[str, int] = Field(default_factory=dict)`, `sync_plan: dict[str, dict[str, int]] = Field(default_factory=dict)` -- no hardcoded defaults
- `async def compare_profiles(source_profile: str, dest_profile: str, tables: list[str], user_id: str, user_field: str = "user_id", slug_field: str = "slug", env_prefix: str = "") -> SyncResult`
- `async def sync_data(source_profile: str, dest_profile: str, tables: list[str], user_id: str, user_field: str = "user_id", slug_field: str = "slug", env_prefix: str = "", schema: BackupSchema | None = None, dry_run: bool = True, confirm: bool = False) -> SyncResult` — when `schema` is provided, sync uses `backup_database()`/`restore_database()` via temp file; when `None`, sync uses direct `adapter.select()`/`adapter.insert()` per-table operations
- `async def _get_data_counts(adapter, user_id, tables, user_field)` iterates `tables` parameter (async — calls `adapter.select()`)
- `async def _get_slugs(adapter, user_id, tables, slug_field, user_field)` uses flat slug per table, no project_slug/slug composition (async — calls `adapter.select()`). Note: all tables passed to sync functions must use the same `slug_field` column name. If different slug column names are needed, callers should invoke sync per-table group.
- Internal adapter creation: `from db_adapter.config.loader import load_db_config` and `from db_adapter.factory import _resolve_url` then `AsyncPostgresAdapter(database_url=url)`
- Backup integration: `from db_adapter.backup.backup_restore import backup_database, restore_database` for sync-via-backup operations
- Tests must verify: `SyncResult` has no hardcoded table name defaults; `compare_profiles` accepts `tables` parameter; `_get_data_counts` iterates dynamic table list; flat slug resolution

**Acceptance Criteria**:
- Zero hardcoded `"projects"`, `"milestones"`, `"tasks"` string literals in `sync.py`
- `grep -En "get_dev_user_id|from db import" src/db_adapter/schema/sync.py` returns nothing
- `SyncResult` field defaults are empty dicts (not pre-populated with table names)
- `compare_profiles` and `sync_data` are `async def` and accept `tables` parameter
- No subprocess usage (`subprocess.run` removed)
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_sync.py -v
```

**Output**: Tests passing

---

### Step 12: Modernize CLI

**Goal**: Update CLI to use `db-adapter` as program name, remove MC-specific references, wrap async calls with `asyncio.run()`, and update all commands to use the new generic APIs.

- [ ] Change `prog` from `"python -m schema"` to `"db-adapter"`
- [ ] Change description from "Mission Control" to generic
- [ ] Update all `cmd_*` functions to call async functions via `asyncio.run()`
- [ ] Remove MC-specific imports and functions (`get_dev_user_id`, `_show_profile_data` with hardcoded tables)
- [ ] Remove `get_dev_user_id()` references from CLI (already removed from `factory.py` in Step 4, but CLI may still import/call it)
- [ ] Remove `from schema.fix import COLUMN_DEFINITIONS` import
- [ ] Remove hardcoded `fk_drop_order`/`fk_create_order` dicts with MC table names
- [ ] Update all MC_DB_PROFILE references in help text to use generic env prefix
- [ ] Generalize `_show_profile_comparison()` and `_show_profile_data()` to not use hardcoded table names (or remove data display)
- [ ] Update `cmd_fix()` to work with the new `generate_fix_plan()` signature; add `--schema-file` and `--column-defs` arguments to the fix subparser
- [ ] Update `cmd_sync()` to accept `--tables` argument instead of hardcoding tables
- [ ] Add `--env-prefix` global option
- [ ] Convert any remaining bare imports in CLI files to `db_adapter.*` package imports (complements Step 2's conversion)
- [ ] Update `cli/backup.py` imports to use `db_adapter.backup.backup_restore`
- [ ] Keep `cli/backup.py` as separate unregistered submodule; update its imports to `db_adapter.*` paths only — do NOT register backup commands from `cli/__init__.py` (deferred to consuming projects per design analysis #11, since CLI cannot know caller's BackupSchema at runtime)
- [ ] Write tests

**Specification**:
- `main()`: `argparse.ArgumentParser(prog="db-adapter", description="Database schema management and adapter toolkit")`
- Each `cmd_*` function wraps async with pattern: `def cmd_connect(args): return asyncio.run(_async_connect(args))`
- `cmd_fix()`: accepts `--schema-file` (path to SQL schema file) and `--column-defs` (path to JSON file mapping `table.column` to SQL type definition) arguments; delegates FK ordering to `FixPlan.drop_order`/`create_order` (no hardcoded `fk_drop_order`/`fk_create_order` dicts). Call pattern: `result = await connect_and_validate(..., expected_columns=expected); plan = generate_fix_plan(result.validation, column_defs, schema_file); await apply_fixes(adapter, plan, ...)`
- `cmd_sync()`: accepts `--tables` argument (required, comma-separated list e.g. `--tables projects,milestones,tasks`); passes to `compare_profiles()`/`sync_data()`
- All help text: `DB_PROFILE=<name> db-adapter connect` (no `MC_` prefix in help; actual prefix configurable via `--env-prefix`). Rename all internal `MC_DB_PROFILE` references to generic `DB_PROFILE` — consuming projects use `--env-prefix MC_` to get `MC_DB_PROFILE` behavior.
- `_show_profile_data()` and `_show_profile_comparison()`: removed or refactored to not hardcode table names (accept tables as parameter or omit data count display)
- `cli/backup.py` imports updated to `from db_adapter.backup.backup_restore import ...`
- Tests must verify: parser prog is `"db-adapter"`; no `"Mission Control"` string in CLI code; `--env-prefix` option exists; `cmd_connect` wraps async

**Acceptance Criteria**:
- `"Mission Control"` does not appear in any CLI file
- `"python -m schema"` does not appear in any CLI file
- `grep -rn "MC_DB_PROFILE" src/db_adapter/cli/` returns nothing (replaced with generic prefix)
- CLI uses `db-adapter` as program name
- All `cmd_*` functions wrap async calls via `asyncio.run()`
- `grep -E "COLUMN_DEFINITIONS|fk_drop_order|fk_create_order" src/db_adapter/cli/__init__.py` returns nothing
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v
```

**Output**: Tests passing

---

### Step 13: Update Package Exports

**Goal**: Update `src/db_adapter/__init__.py` and all subpackage `__init__.py` files to export the library's public API.

- [ ] Update `src/db_adapter/__init__.py` with all public exports
- [ ] Update `adapters/__init__.py` with new class names
- [ ] Update `config/__init__.py` with exports
- [ ] Update `schema/__init__.py` with exports
- [ ] Update `backup/__init__.py` with exports
- [ ] Define `__all__` in each `__init__.py`
- [ ] Write tests

**Specification**:
- `src/db_adapter/__init__.py` exports:
  - `DatabaseClient` from `adapters.base`
  - `AsyncPostgresAdapter` from `adapters.postgres`
  - `get_adapter`, `connect_and_validate`, `ProfileNotFoundError` from `factory`
  - `load_db_config` from `config.loader`
  - `DatabaseProfile`, `DatabaseConfig` from `config.models`
  - `validate_schema` from `schema.comparator`
  - `BackupSchema`, `TableDef`, `ForeignKey` from `backup.models`
  - Optional: `AsyncSupabaseAdapter` via `try/except ImportError`
  - `__all__` list with all exported names
- Subpackage `__all__` exports:
  - `adapters/__init__.py`: `["DatabaseClient", "AsyncPostgresAdapter"]` (+ conditional `"AsyncSupabaseAdapter"`)
  - `config/__init__.py`: `["load_db_config", "DatabaseProfile", "DatabaseConfig"]`
  - `schema/__init__.py`: `["validate_schema", "SchemaIntrospector", "SchemaValidationResult", "ColumnDiff", "ConnectionResult", "ColumnSchema", "ConstraintSchema", "IndexSchema", "TriggerSchema", "FunctionSchema", "TableSchema", "DatabaseSchema"]`
  - `backup/__init__.py`: `["BackupSchema", "TableDef", "ForeignKey", "backup_database", "restore_database", "validate_backup"]`
- Tests must verify: `from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter` works; `from db_adapter import BackupSchema, TableDef, ForeignKey` works; `from db_adapter import validate_schema, load_db_config` works; optional `AsyncSupabaseAdapter` does not error when supabase not installed

**Acceptance Criteria**:
- `uv run python -c "from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter, connect_and_validate"` succeeds
- `uv run python -c "from db_adapter import BackupSchema, TableDef, ForeignKey, load_db_config"` succeeds
- `uv run python -c "from db_adapter import DatabaseProfile, DatabaseConfig, validate_schema, ProfileNotFoundError"` succeeds
- Each `__init__.py` has an `__all__` list
- `from db_adapter import X` works for every name in the top-level `__all__` list
- Tests pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_exports.py -v
```

**Output**: Tests passing

---

### Step 14: Final Validation

**Goal**: Run full test suite and verify all success criteria are met.

- [ ] Run full test suite
- [ ] Verify zero MC-specific imports remain
- [ ] Verify zero hardcoded MC table names remain
- [ ] Verify `uv run db-adapter --help` works
- [ ] Verify top-level imports work

**Specification**:
- Run all test files created across steps 1-13
- Run grep checks for forbidden patterns: `fastmcp`, `creational.common`, `mcp.server.auth`, `schema.db_models`
- Grep for hardcoded MC table names: `"projects"`, `"milestones"`, `"tasks"` as string literals in library code (not test code) — these should be parameterized via `BackupSchema`/`tables` arguments
- Verify `uv sync` succeeds cleanly
- Verify CLI entry point works
- Tests must verify: full suite passes; import smoke tests pass; no forbidden patterns found

**Acceptance Criteria**:
- All tests from steps 1-13 pass (full suite)
- `grep -rEn "from fastmcp|from creational|from mcp.server|from schema.db_models|import fastmcp|import creational|import mcp\.server" src/db_adapter/` returns nothing (catches both `from X import Y` and bare `import X` forms)
- `grep -rEn '"projects"|"milestones"|"tasks"' src/db_adapter/ --include="*.py"` returns nothing (no hardcoded MC table names)
- `uv run python -c "from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter"` succeeds
- `uv run db-adapter --help` shows program name as `db-adapter`
- `uv sync --extra supabase --extra dev` succeeds with clean install (all extras resolve)

**Verification**:
```bash
# Run full test suite
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short

# Verify no MC-specific imports (both 'from X import Y' and 'import X' forms)
grep -rEn "from fastmcp|from creational|from mcp.server|from schema.db_models|import fastmcp|import creational|import mcp\.server" src/db_adapter/

# Verify no hardcoded MC table names
grep -rEn '"projects"|"milestones"|"tasks"' src/db_adapter/ --include="*.py"

# Verify uv sync with all extras
cd /Users/docchang/Development/db-adapter && uv sync --extra supabase --extra dev

# Verify CLI
cd /Users/docchang/Development/db-adapter && uv run db-adapter --help

# Verify imports (includes circular import check via importing all subpackages)
cd /Users/docchang/Development/db-adapter && uv run python -c "
from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter, connect_and_validate, BackupSchema
from db_adapter.adapters import DatabaseClient, AsyncPostgresAdapter
from db_adapter.config import load_db_config, DatabaseProfile, DatabaseConfig
from db_adapter.schema import validate_schema, SchemaIntrospector
from db_adapter.backup import BackupSchema, TableDef, ForeignKey
print('All imports OK — no circular import issues')
"
```

**Output**: All tests passing, all success criteria met

---

## Test Summary

### Affected Tests (Run These)

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `tests/test_lib_extraction_models.py` | ~6 | Model consolidation, no duplication |
| `tests/test_lib_extraction_imports.py` | ~8 | Package import resolution |
| `tests/test_lib_extraction_config.py` | ~5 | Config loader, TOML parsing |
| `tests/test_lib_extraction_factory.py` | ~10 | Factory functions, profile resolution, async |
| `tests/test_lib_extraction_comparator.py` | ~6 | Schema comparator, set operations |
| `tests/test_lib_extraction_adapters.py` | ~10 | Async adapter structure, protocol compliance |
| `tests/test_lib_extraction_introspector.py` | ~6 | Async introspector structure |
| `tests/test_lib_extraction_fix.py` | ~8 | Schema fix, generalized |
| `tests/test_lib_extraction_backup.py` | ~10 | Backup/restore with BackupSchema |
| `tests/test_lib_extraction_sync.py` | ~8 | Sync module, dynamic tables |
| `tests/test_lib_extraction_cli.py` | ~8 | CLI modernization |
| `tests/test_lib_extraction_exports.py` | ~6 | Package exports, public API |

**Affected tests: ~91 tests**

**Full suite**: ~91 tests (same as affected -- all tests are new)

**Test naming convention**: Use `test_{module}_{behavior}` pattern consistently (e.g., `test_factory_get_adapter_returns_async_postgres`, `test_comparator_missing_table_detected`).

---

## What "Done" Looks Like

```bash
# 1. Full test suite passes
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short
# Expected: All pass

# 2. No MC-specific imports remain
grep -rEn "from fastmcp|from creational|from mcp.server|from schema.db_models" src/db_adapter/
# Expected: No output (zero matches)

# 3. Top-level imports work
cd /Users/docchang/Development/db-adapter && uv run python -c "from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter, connect_and_validate, BackupSchema, validate_schema, load_db_config, ProfileNotFoundError; print('All imports OK')"
# Expected: "All imports OK"

# 4. CLI works
cd /Users/docchang/Development/db-adapter && uv run db-adapter --help
# Expected: Shows "db-adapter" as program name with connect/status/profiles/validate/fix/sync commands
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/db_adapter/__init__.py` | Modify | Add public API exports |
| `src/db_adapter/factory.py` | Modify | Remove MC code, async, env_prefix, expected_columns |
| `src/db_adapter/adapters/__init__.py` | Modify | Fix imports, update exports |
| `src/db_adapter/adapters/base.py` | Modify | All methods become async def, add execute method |
| `src/db_adapter/adapters/postgres.py` | Modify | Async engine, configurable JSONB, rename class |
| `src/db_adapter/adapters/supabase.py` | Modify | Async client, lazy init, rename class |
| `src/db_adapter/config/__init__.py` | Modify | Add exports |
| `src/db_adapter/config/models.py` | Modify | Keep only DatabaseProfile, DatabaseConfig |
| `src/db_adapter/config/loader.py` | Modify | Remove Settings/SharedSettings, fix imports/default path |
| `src/db_adapter/schema/__init__.py` | Modify | Add exports |
| `src/db_adapter/schema/models.py` | Modify | Remove duplicated config model classes (DatabaseProfile, DatabaseConfig) |
| `src/db_adapter/schema/introspector.py` | Modify | Async psycopg, configurable excluded_tables |
| `src/db_adapter/schema/comparator.py` | Modify | Add expected_columns param, remove MC import |
| `src/db_adapter/schema/fix.py` | Modify | Remove COLUMN_DEFINITIONS, parameterize, async |
| `src/db_adapter/schema/sync.py` | Modify | Remove hardcoded tables, parameterize, async |
| `src/db_adapter/backup/__init__.py` | Modify | Add exports |
| `src/db_adapter/backup/models.py` | No change | Already generic |
| `src/db_adapter/backup/backup_restore.py` | Modify | Use BackupSchema, remove MC imports, async |
| `src/db_adapter/cli/__init__.py` | Modify | Rename to db-adapter, remove MC refs, asyncio.run |
| `src/db_adapter/cli/backup.py` | Modify | Update imports to db_adapter paths |
| `tests/test_lib_extraction_models.py` | Create | Model consolidation tests |
| `tests/test_lib_extraction_imports.py` | Create | Import resolution tests |
| `tests/test_lib_extraction_config.py` | Create | Config loader tests |
| `tests/test_lib_extraction_factory.py` | Create | Factory module tests |
| `tests/test_lib_extraction_comparator.py` | Create | Comparator tests |
| `tests/test_lib_extraction_adapters.py` | Create | Async adapter tests |
| `tests/test_lib_extraction_introspector.py` | Create | Async introspector tests |
| `tests/test_lib_extraction_fix.py` | Create | Schema fix tests |
| `tests/test_lib_extraction_backup.py` | Create | Backup/restore tests |
| `tests/test_lib_extraction_sync.py` | Create | Sync module tests |
| `tests/test_lib_extraction_cli.py` | Create | CLI tests |
| `tests/test_lib_extraction_exports.py` | Create | Package export tests |

---

## Dependencies

_(No new dependencies needed -- all are already in `pyproject.toml`)_

Current `pyproject.toml` already includes:
```toml
dependencies = [
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "psycopg[binary]>=3.0",
    "pydantic>=2.0",
    "rich>=13.0",
]

[project.optional-dependencies]
supabase = ["supabase>=2.0"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]
```

Install:
```bash
cd /Users/docchang/Development/db-adapter && uv sync --extra dev
```

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| asyncpg driver incompatibilities with SQLAlchemy async | LOW | asyncpg is SQLAlchemy's recommended async PostgreSQL driver; well-tested combination |
| psycopg async API differences from sync API | LOW | psycopg v3 has first-class async support; API is nearly identical to sync |
| supabase-py async client import path changes | MED | Use `try/except ImportError` for conditional import; pin supabase version |
| Large refactor scope increases risk of subtle bugs | MED | Step-by-step execution with tests at each step; no dependencies on external DB systems for unit tests |
| Step 2 (import fixes) may break intermediate state | LOW | MC-specific imports are commented out, not deleted -- later steps clean up properly |

---

## Next Steps After Completion

1. Verify full test suite passes (~91 tests)
2. Verify all success criteria from design doc
3. Proceed to next task: MC-side migration (updating MC imports to use db-adapter as a dependency)

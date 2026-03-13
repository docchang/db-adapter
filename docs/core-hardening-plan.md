# Core-Hardening Plan

> **Design**: See `docs/core-hardening-design.md` for analysis and approach.
>
> **Track Progress**: See `docs/core-hardening-results.md` for implementation status, test results, and issues.

## Overview

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-12T01:05:11-0700 |
| **Name** | Core Hardening |
| **Type** | Refactor |
| **Environment** | Python -- see `references/python-guide.md` |
| **Proves** | Library-grade reliability: atomicity, error visibility, modularity, and robust SQL parsing |
| **Production-Grade Because** | Transactions prevent partial state on failure; failure details are preserved, not silently swallowed; SQL parsing handles real-world edge cases (comments, quoted identifiers, schema-qualified names) |
| **Risk Profile** | Standard |
| **Risk Justification** | Internal library refactoring with full test coverage; all changes are additive; no external API breaking changes at runtime (soft type-checking change for custom Protocol implementors adding `transaction()`) |

---

## Deliverables

Concrete capabilities this task delivers:

- CLI split into 6 focused modules (176-415 lines each) with facade re-exports and updated mock patch targets
- Restore `failure_details` list in result dict with per-row error context (row index, old PK, error message)
- `transaction()` async context manager on `DatabaseClient` Protocol, implemented in `AsyncPostgresAdapter` via contextvars
- `restore_database()`, `apply_fixes()`, and `_sync_direct()` wrapped in transactions for atomic operations
- FK pre-flight warning in CLI sync when direct-insert targets tables with FK constraints
- `sqlparse`-based SQL parsing replacing regex for CREATE TABLE extraction, FK dependency parsing, and table SQL lookup

---

## Prerequisites

Complete these BEFORE starting implementation steps.

### 1. Identify Affected Tests

**Why Needed**: Run only affected tests during implementation (not full suite)

**Affected test files**:
- `tests/test_lib_extraction_cli.py` (177 tests) - CLI commands, mock patching, parsing
- `tests/test_lib_extraction_backup.py` (48 tests) - Backup/restore round-trips, FK remapping
- `tests/test_lib_extraction_fix.py` (62 tests) - Fix plan generation, DDL generation, SQL parsing
- `tests/test_lib_extraction_adapters.py` (54 tests) - Protocol, adapter implementations
- `tests/test_lib_extraction_exports.py` - Public API `__all__` lists
- `tests/test_lib_extraction_imports.py` - Absolute import patterns

**Baseline verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_backup.py tests/test_lib_extraction_fix.py tests/test_lib_extraction_adapters.py tests/test_lib_extraction_exports.py tests/test_lib_extraction_imports.py -v --tb=short
# Expected: All pass (establishes baseline)
```

## Success Criteria

From Design doc (refined with verification commands):

- [ ] CLI split into 6 modules with all 177 CLI tests passing after patch target migration and unchanged entry point `db_adapter.cli:main`
- [ ] Restore `failure_details` present in result dict when `failed > 0`, containing `row_index`, `old_pk`, `error` per failure
- [ ] CLI displays per-row failure details below Rich Table on restore
- [ ] `transaction()` method on `DatabaseClient` Protocol, implemented in both adapters (contextvars for postgres, NotImplementedError for supabase)
- [ ] `restore_database()` rolls back all inserts on unrecoverable error; per-row failures in mode=skip/overwrite collected in `failure_details`
- [ ] `apply_fixes()` rolls back all DDL on any exception (transaction wraps inside try/except)
- [ ] `_sync_direct()` rolls back per-table on FK violation
- [ ] FK pre-flight warning emitted in CLI when direct sync targets tables with FK constraints
- [ ] `_parse_expected_columns()`, `_parse_fk_dependencies()`, `_get_table_create_sql()` handle quoted identifiers, schema-qualified names, and SQL comments
- [ ] `sqlparse` added as core dependency
- [ ] All existing 824 tests pass

---

## Architecture

### File Structure
```
src/db_adapter/
├── cli/
│   ├── __init__.py            # Facade: main(), argparse, re-exports of 24 symbols (plus main defined locally)
│   ├── _helpers.py            # Shared helpers, constants, console (~311 lines)
│   ├── _connection.py         # connect, validate, status, profiles (~415 lines)
│   ├── _schema_fix.py         # fix command (~335 lines)
│   ├── _data_sync.py          # sync command + FK pre-flight (~176 lines)
│   └── _backup.py             # backup, restore, validate-backup (~380 lines)
├── adapters/
│   ├── base.py                # Updated: transaction() on Protocol
│   ├── postgres.py            # Updated: transaction() with contextvars
│   └── supabase.py            # Updated: transaction() as NotImplementedError
├── backup/
│   └── backup_restore.py      # Updated: failure_details + logging + transaction wrap
├── schema/
│   ├── fix.py                 # Updated: transaction wrap + sqlparse refactor
│   └── sync.py                # Updated: transaction wrap in _sync_direct()
└── pyproject.toml             # Updated: sqlparse dependency
```

### Design Principles
1. **OOP Design**: Protocol-based adapter pattern with structural typing
2. **Validated Data Models**: Pydantic models for configs, fix results, sync results; dataclasses for fix plan components
3. **Strong Typing**: Type annotations on all functions, methods, and class attributes
4. **Add alongside, don't replace**: Transaction support is backward compatible via `hasattr()` guards; new dict keys are additive

---

## Implementation Steps

**Approach**: Build bottom-up, following the design sequence: CLI split first (enables cleaner subsequent changes), then restore failure details, then transaction support (Protocol, consumers, FK pre-flight), then SQL parser upgrade. Each step is independently verifiable.

> This plan is a contract between the executor (builder) and reviewer (validator). Steps specify **what** to build and **how** to verify -- the executor writes the implementation.

> **Sub-steps**: When a step is split during review, it becomes sub-steps (e.g., Step 8 -> Steps 8a, 8b, 8c).
> Sub-steps are full steps with letter suffixes. Each has the same sections as a regular step.
> Sub-steps execute in order (8a -> 8b -> 8c) before proceeding to the next whole number.
> Sub-steps are limited to one level -- no 8a-i, 8a-ii.

### Step 0: Add sqlparse Dependency

**Goal**: Add the `sqlparse` dependency to `pyproject.toml` and verify it installs.

- [ ] Add `"sqlparse>=0.5"` to `dependencies` list in `pyproject.toml` (after `"rich>=13.0"`)
- [ ] Run `uv sync` to install

**Code**:
```bash
# After editing pyproject.toml:
cd /Users/docchang/Development/db-adapter && uv sync
```

**Verification** (inline OK for Step 0):
```bash
cd /Users/docchang/Development/db-adapter && uv run python -c "import sqlparse; print(f'sqlparse {sqlparse.__version__}')"
# Expected: sqlparse version printed without error

cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short -q 2>&1 | tail -3
# Expected: 824 tests pass (no regressions from adding dependency)
```

**Output**: `sqlparse` installed, all 824 existing tests pass

---

### Step 1: CLI File Split -- Extract Functions into Sub-Modules

**Goal**: Split `src/db_adapter/cli/__init__.py` (1842 lines) into 5 internal modules (22 functions extracted) + a facade `__init__.py` that retains `main()` and re-exports 24 symbols.

- [ ] Create `src/db_adapter/cli/_helpers.py` with shared helpers
- [ ] Create `src/db_adapter/cli/_connection.py` with connection/validation commands
- [ ] Create `src/db_adapter/cli/_schema_fix.py` with fix command
- [ ] Create `src/db_adapter/cli/_data_sync.py` with sync command
- [ ] Create `src/db_adapter/cli/_backup.py` with backup/restore commands
- [ ] Reduce `__init__.py` to facade (main, argparse, re-exports)
- [ ] Write tests verifying the split

**Specification**:

Create 5 underscore-prefixed internal modules. Each module imports what it needs from the library directly (e.g., `from db_adapter.config.loader import load_db_config`). The import graph must be acyclic:

```
__init__.py <- imports from all modules
  _helpers.py       (no cli imports; imports from db_adapter.*)
  _connection.py  <- _helpers.py
  _schema_fix.py  <- _helpers.py
  _data_sync.py   <- _helpers.py
  _backup.py      <- _helpers.py
```

Module assignments (functions move from `__init__.py` to target module):

- **`_helpers.py`**: `console = Console()`, `_EXCLUDED_TABLES`, `_get_table_row_counts`, `_print_table_counts`, `_parse_expected_columns`, `_resolve_user_id`, `_load_backup_schema`, `_resolve_backup_schema_path`. Shared stdlib/third-party imports (`argparse`, `json`, `os`, `re`, `Path`, `Console`, `Table`, etc.) as needed by these functions.

- **`_connection.py`**: `_async_connect`, `_async_validate`, `_async_status`, `cmd_connect`, `cmd_status`, `cmd_profiles`, `cmd_validate`. Imports `console`, `_print_table_counts`, `_get_table_row_counts`, `_parse_expected_columns` from `_helpers`. Imports `load_db_config`, `read_profile_lock`, `connect_and_validate`, `get_adapter`, `resolve_url`, `ProfileNotFoundError` directly from their library modules.

- **`_schema_fix.py`**: `_async_fix`, `cmd_fix`. Imports from `_helpers` and library modules as needed. The `_async_fix` function uses `console`, `_parse_expected_columns`, `_resolve_backup_schema_path`, `_load_backup_schema`, `_resolve_user_id` from `_helpers`. Also imports `get_active_profile_name` from `db_adapter.factory`.

- **`_data_sync.py`**: `_async_sync`, `cmd_sync`. Imports from `_helpers` and library modules as needed.

- **`_backup.py`**: `_async_backup`, `_async_restore`, `_validate_backup`, `cmd_backup`, `cmd_restore`. Imports from `_helpers` and library modules as needed.

- **`__init__.py`** (facade): Retains `main()` and the `argparse` setup. Imports and re-exports all 24 symbols from the sub-modules so that `from db_adapter.cli import X` continues to work. `main` is defined here, not re-exported from a sub-module. Entry point `db_adapter.cli:main` is unchanged.

Each sub-module must have its own imports for the names it uses from library modules (e.g., `_connection.py` imports `load_db_config` from `db_adapter.config.loader`, not from `db_adapter.cli`).

Tests must verify:
- All 24 re-exported symbols importable from `db_adapter.cli`
- `main()` callable with `--help` (no import errors)
- No circular imports between sub-modules
- Each sub-module file exists and is non-empty

**Acceptance Criteria**:
- All 24 re-exported symbols (`_get_table_row_counts`, `_print_table_counts`, `_parse_expected_columns`, `_resolve_user_id`, `_load_backup_schema`, `_resolve_backup_schema_path`, `_EXCLUDED_TABLES`, `console`, `_async_connect`, `_async_validate`, `_async_status`, `cmd_connect`, `cmd_status`, `cmd_profiles`, `cmd_validate`, `_async_fix`, `cmd_fix`, `_async_sync`, `cmd_sync`, `_async_backup`, `_async_restore`, `_validate_backup`, `cmd_backup`, `cmd_restore`) are importable from `db_adapter.cli` (`main` is defined in `__init__.py` directly, not re-exported)
- `__init__.py` is reduced to approximately 245 lines (facade + main + argparse)
- 5 new files exist: `_helpers.py`, `_connection.py`, `_schema_fix.py`, `_data_sync.py`, `_backup.py`
- No file in the cli package has circular imports
- `uv run db-adapter --help` succeeds without error

**Trade-offs**:
- **Where to put `_parse_expected_columns`**: Place in `_helpers.py` for now (it will be refactored to use sqlparse in Step 7). Alternative: create a separate `_parsing.py` module, but that adds unnecessary complexity before the sqlparse migration.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_exports.py tests/test_lib_extraction_imports.py -v --tb=short
# These tests validate public API exports and import patterns
```

**Output**: Export and import tests passing

> **Note**: After Step 1, the 177 CLI tests in `test_lib_extraction_cli.py` will intentionally fail — their `patch()` targets still point to the old `db_adapter.cli` namespace. This is expected. Step 2 resolves this. Do not attempt to fix the CLI test failures before completing Step 2.

---

### Step 2: Migrate Mock Patch Targets in Test Files

**Goal**: Update all 178 `patch("db_adapter.cli.<name>", ...)` occurrences in `tests/test_lib_extraction_cli.py` to reference the sub-module where each name is actually used.

- [ ] Map each patched name to its new sub-module location
- [ ] Update all patch targets in `test_lib_extraction_cli.py`
- [ ] Verify all 177 CLI tests pass

**Specification**:

After the CLI split (Step 1), sub-modules import names directly from their origin modules. Patching `db_adapter.cli.<name>` only patches the re-exported binding in the facade -- not the binding that the sub-module code actually uses. Every `patch()` call must be updated to target the sub-module where the name is looked up at runtime.

Patch target mapping (based on the 178 occurrences found in the test file):

| Current Target | New Target | Count |
|---------------|------------|-------|
| `db_adapter.cli.load_db_config` | `db_adapter.cli._connection.load_db_config` (for connect/validate/status/profiles tests), `db_adapter.cli._schema_fix.load_db_config` (for fix tests), `db_adapter.cli._data_sync.load_db_config` (for sync tests), `db_adapter.cli._backup.load_db_config` (for backup/restore tests) | 59 |
| `db_adapter.cli.console` | `db_adapter.cli._helpers.console` (for tests targeting `_print_table_counts` directly) / `db_adapter.cli._connection.console` / `db_adapter.cli._schema_fix.console` / `db_adapter.cli._data_sync.console` / `db_adapter.cli._backup.console` (depending on which command is under test) | 56 |
| `db_adapter.cli.read_profile_lock` | `db_adapter.cli._connection.read_profile_lock` / `db_adapter.cli._data_sync.read_profile_lock` (depending on which command is under test — `read_profile_lock` is not called from `_async_fix` or backup functions) | 38 |
| `db_adapter.cli.cmd_*` | `db_adapter.cli.cmd_*` (NOT migrated — these remain in `__init__.py` for `main()` dispatch, kept as-is) | 15 |
| `db_adapter.cli.asyncio` | `db_adapter.cli._backup.asyncio` (all 3 asyncio patches test `cmd_backup`/`cmd_restore`) | 3 |
| `db_adapter.cli._validate_backup` | `db_adapter.cli._backup._validate_backup` | 2 |
| `db_adapter.cli._print_table_counts` | `db_adapter.cli._connection._print_table_counts` or `db_adapter.cli._helpers._print_table_counts` (depending on where it is called) | 5 |

The executor must determine the exact new target for each patch by examining which sub-module's code path is being tested. The key rule: **patch where the name is looked up**, which is the sub-module that imports it, not the facade that re-exports it.

Important: Some tests patch `cmd_*` functions when testing `main()` dispatch. These targets remain as `db_adapter.cli.cmd_*` since `main()` stays in `__init__.py` and looks up `cmd_*` from its own namespace (via re-imports or direct definition).

Tests must verify:
- All 177 CLI tests pass with updated patch targets
- No test uses `patch("db_adapter.cli.<name>")` for names that now live in sub-modules (except `cmd_*` and `main`)
- `test_lib_extraction_exports.py` and `test_lib_extraction_imports.py` still pass (verify they don't need patch target updates due to the new sub-module structure)

**Acceptance Criteria**:
- All 177 tests in `test_lib_extraction_cli.py` pass
- No `patch("db_adapter.cli.load_db_config"` / `patch("db_adapter.cli.console"` / `patch("db_adapter.cli.read_profile_lock"` remaining (these must reference sub-modules)
- `patch("db_adapter.cli.cmd_*"` targets for `main()` dispatch tests remain valid
- Full affected test suite passes (CLI + exports + imports)

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
# Expected: All 177 tests pass

cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_exports.py tests/test_lib_extraction_imports.py -v --tb=short
# Expected: All pass
```

**Output**: All CLI, export, and import tests passing

---

### Step 3: Restore Failure Details

**Goal**: Capture per-row error details in `_restore_table()` and display them in the CLI restore output.

- [ ] Add `import logging` and logger to `backup_restore.py`
- [ ] Update `_restore_table()` exception handling to capture failure details
- [ ] Add CLI display of failure details in `_backup.py`
- [ ] Write tests for failure details behavior

**Specification**:

**Library changes (`src/db_adapter/backup/backup_restore.py`)**:

Add at the top of the file:
```python
import logging
logger = logging.getLogger(__name__)
```

In `_restore_table()`:
1. Change `for row in rows:` to `for i, row in enumerate(rows):`
2. Move `old_pk = row[table_def.pk]` (line 261, currently inside `try`) to before the `try` block (but inside the loop), and change to safe access: `old_pk = row.get(table_def.pk, "<unknown>")`. Rationale: the old line accessed `row[table_def.pk]` directly inside the try, which could KeyError before `old_pk` was bound, making it unavailable in the except handler.
3. In the `except Exception:` block (line 347-348), replace the bare `table_summary["failed"] += 1` with:
   - `table_summary["failed"] += 1`
   - `table_summary.setdefault("failure_details", []).append({"row_index": i, "old_pk": old_pk, "error": f"{type(e).__name__}: {e}"})`
   - `logger.warning("Restore failed for %s row %d (pk=%s): %s", table_name, i, old_pk, e)`
4. The `except Exception:` must become `except Exception as e:` to capture the exception variable

**CLI changes (`src/db_adapter/cli/_backup.py`)**:

After the Rich Table is printed in `_async_restore()`, iterate over `schema.tables` and check each table's result for `failure_details`. If present and non-empty, print them:
```python
# Signature pattern:
for table_def in schema.tables:
    details = result.get(table_def.name, {}).get("failure_details", [])
    if details:
        console.print(f"\n  [red]Failed rows in {table_def.name}:[/red]")
        for d in details:
            console.print(f"    row {d['row_index']} (pk={d['old_pk']}): {d['error']}")
```

**Return dict evolution** (backward compatible -- new key only present when `failed > 0`):
```python
# Before: {"inserted": 5, "updated": 0, "skipped": 2, "failed": 3}
# After:  {"inserted": 5, "updated": 0, "skipped": 2, "failed": 3,
#           "failure_details": [{"row_index": 0, "old_pk": "a1b2", "error": "IntegrityError: ..."}]}
```

Tests must verify:
- Mock adapter that raises on a specific insert produces `failure_details` in result dict
- `failure_details` list contains correct `row_index`, `old_pk`, and `error` fields
- `failure_details` is absent from result when no failures occur
- `logger.warning` is called with correct arguments on failure
- Existing restore tests pass unchanged (they don't assert on failure_details)

**Acceptance Criteria**:
- `_restore_table()` captures exception details in `failure_details` list when `failed > 0`
- Each failure detail dict has keys: `row_index` (int), `old_pk` (str), `error` (str with exception class name)
- `logger.warning()` called once per failed row with table name, row index, pk, and error message
- `failure_details` key is absent from table summary when `failed == 0`
- `old_pk` extraction uses `.get()` with `"<unknown>"` default (safe access before try block)
- Existing 48 backup tests pass unchanged
- New tests cover: single failure, multiple failures, no failures, failure with missing PK field

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_backup.py -v --tb=short
# Expected: All existing + new tests pass
```

**Output**: Backup tests passing with new failure_details tests

---

### Step 4: Transaction Support -- Protocol and Adapter Implementation

**Goal**: Add `transaction()` async context manager to `DatabaseClient` Protocol and implement in both adapters.

- [ ] Add `transaction()` to `DatabaseClient` Protocol in `base.py`
- [ ] Implement in `AsyncPostgresAdapter` using contextvars
- [ ] Implement in `AsyncSupabaseAdapter` as NotImplementedError
- [ ] Modify all 5 CRUD methods in postgres adapter to check `_transaction_conn`
- [ ] Write tests for transaction behavior

**Specification**:

**Protocol (`src/db_adapter/adapters/base.py`)**:

Add import for `AbstractAsyncContextManager` from `contextlib`. Add method to `DatabaseClient`:
```python
def transaction(self) -> AbstractAsyncContextManager[None]:
    """Enter a transaction. Auto-commits on clean exit, auto-rolls back on exception."""
    ...
```

**PostgreSQL adapter (`src/db_adapter/adapters/postgres.py`)**:

1. Add `import contextvars` and `from contextlib import asynccontextmanager`
2. Add `AsyncConnection` to the `sqlalchemy.ext.asyncio` import (already imported as `AsyncEngine`).
3. In `AsyncPostgresAdapter.__init__()`, initialize an instance-level ContextVar:
   ```python
   self._transaction_conn: contextvars.ContextVar[AsyncConnection | None] = contextvars.ContextVar(
       f"_transaction_conn_{id(self)}", default=None
   )
   ```
   Each adapter instance gets its own ContextVar (with a unique name), so when two `AsyncPostgresAdapter` instances exist in the same asyncio task (as in `_sync_direct()` which creates both source and dest adapters), cross-instance contamination cannot occur. ContextVars still provide async task isolation within each instance.

4. Implement `transaction()` method on `AsyncPostgresAdapter`:
   - Check if `self._transaction_conn.get(None)` is already set -- if so, raise `RuntimeError("Nested transactions are not supported")` (no savepoint support in v1)
   - Call `self._engine.begin()` to get an `AsyncConnection`
   - Set the ContextVar via `token = self._transaction_conn.set(conn)`
   - Yield (caller executes within transaction)
   - On clean exit: connection auto-commits (SQLAlchemy `engine.begin()` behavior)
   - On exception: connection auto-rolls back (SQLAlchemy `engine.begin()` behavior)
   - In finally: reset ContextVar via `self._transaction_conn.reset(token)`

5. Modify all 5 CRUD methods (`select`, `insert`, `update`, `delete`, `execute`) to check `self._transaction_conn.get(None)` first:
   - If a transaction connection exists, use it directly (no `async with self._engine.begin()` or `self._engine.connect()`)
   - If no transaction connection, use the current behavior (backward compatible)
   - Key distinction: `select()` currently uses `engine.connect()` (read-only, no auto-commit), while `insert`/`update`/`delete`/`execute` use `engine.begin()` (auto-commit). When a transaction is active, all methods share the same connection from the ContextVar.

**Supabase adapter (`src/db_adapter/adapters/supabase.py`)**:

Add `transaction()` method:
```python
def transaction(self) -> AbstractAsyncContextManager[None]:
    raise NotImplementedError("Transactions not supported for Supabase adapter.")
```

Tests must verify:
- `transaction()` exists on Protocol (structural check)
- Existing `test_protocol_has_exactly_six_methods` is updated to check for 6 async methods + 1 sync method (`transaction()`), since `transaction()` is `def` (not `async def`) and the test only counts `ast.AsyncFunctionDef` nodes
- Postgres adapter: CRUD operations within `transaction()` share a connection
- Postgres adapter: clean exit commits, exception triggers rollback
- Postgres adapter: nested `transaction()` raises `RuntimeError`
- Postgres adapter: CRUD operations without `transaction()` behave identically to before (backward compatible)
- Supabase adapter: `transaction()` raises `NotImplementedError`
- `select()` inside a transaction uses the shared connection (not `engine.connect()`)

**Acceptance Criteria**:
- `DatabaseClient` Protocol has `transaction()` method returning `AbstractAsyncContextManager[None]`
- `AsyncPostgresAdapter.transaction()` uses `engine.begin()` + instance-level `contextvars.ContextVar` for connection sharing (per-instance isolation prevents cross-adapter contamination)
- All 5 CRUD methods check `self._transaction_conn` ContextVar before creating their own connection
- Nested `transaction()` calls raise `RuntimeError("Nested transactions are not supported")`
- `AsyncSupabaseAdapter.transaction()` raises `NotImplementedError`
- Existing 54 adapter tests pass unchanged (backward compatibility), with `test_protocol_has_exactly_six_methods` updated for the new method
- New tests cover: commit on success, rollback on exception, nested rejection, no-transaction backward compatibility
- Note: Adding `transaction()` to the Protocol is a soft breaking change for type checking. Document in CLAUDE.md's Protocol section that Protocol now has 7 methods (6 async + 1 sync).

**Trade-offs**:
- **ContextVar type**: Use `sqlalchemy.ext.asyncio.AsyncConnection` (not raw asyncpg connection) because all CRUD methods use SQLAlchemy's `text()` API. Alternative: use raw asyncpg, but that would require rewriting all CRUD methods.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_adapters.py -v --tb=short
# Expected: All existing + new tests pass
```

**Output**: Adapter tests passing with new transaction tests

---

### Step 5: Transaction Wrapping for Consumers

**Goal**: Wrap `restore_database()`, `apply_fixes()`, and `_sync_direct()` in adapter transactions with correct exception handler restructuring.

- [ ] Wrap `restore_database()` table loop in transaction
- [ ] Restructure `apply_fixes()` exception handling for transaction
- [ ] Wrap `_sync_direct()` per-table insert loop in transaction
- [ ] Write tests for transaction-wrapped consumer behavior

**Specification**:

All three consumers use `hasattr(adapter, 'transaction')` guard so custom adapters without the method still work (degraded -- no atomicity, same as today). The pattern:

```python
if hasattr(adapter, 'transaction'):
    async with adapter.transaction():
        # ... operation ...
else:
    # ... operation (same code, no transaction) ...
```

**`restore_database()` in `backup/backup_restore.py`**:

Wrap the `for table_def in schema.tables:` loop (the one calling `_restore_table`) inside `adapter.transaction()`. The `_restore_table` function's `except Exception` handler catches per-row errors and continues (mode=skip/overwrite), so the transaction commits with the successful subset. The `except ValueError: raise` path (mode=fail) propagates out of the `async with` block and triggers rollback. Unrecoverable errors (connection lost) also propagate and trigger rollback.

Important: The transaction wraps the entire multi-table loop (all tables in one transaction), not per-table. This is correct because FK remapping across tables requires atomicity -- a child table's inserts depend on parent table's id_maps.

**`apply_fixes()` in `schema/fix.py`**:

Restructure the exception handling so the transaction block is **inside** the try/except. Because the fix sequence is ~80 lines, avoid duplicating it with a `hasattr()` if/else branch. Instead, use a no-op context manager fallback so the fix sequence is written once:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def _noop_transaction():
    yield

# At call site inside apply_fixes():
ctx = adapter.transaction() if hasattr(adapter, 'transaction') else _noop_transaction()

try:
    async with ctx:
        # ... full fix sequence (CREATE, backup, DROP, CREATE, restore, ALTER) ...
        # If any step raises, exception propagates out of `async with` → rollback (or no-op)
except RuntimeError:
    raise
except Exception as e:
    # Transaction already rolled back before we get here
    result.error = f"Failed to apply fixes: {e}"
    return result
```

This ensures that if any step raises, the exception propagates out of `async with`, triggering rollback when a real transaction is active. When no transaction support exists (`_noop_transaction`), the `except Exception` handler still captures the error — same behavior as today, just without rollback.

The `NotImplementedError` -> `RuntimeError` conversion for DDL-unsupported adapters must remain inside the transaction block (it raises `RuntimeError` which propagates through `except RuntimeError: raise`).

All operations within the fix sequence share the same connection via contextvars: backup callback's `adapter.select()`, DROP/CREATE DDL via `adapter.execute()`, restore callback's `adapter.insert()`, and ALTER via `adapter.execute()`. PostgreSQL's transactional DDL ensures all or nothing.

**`_sync_direct()` in `schema/sync.py`**:

Wrap each table's insert loop (not the entire multi-table loop) in a transaction. Per-table granularity: if table A syncs successfully and table B fails, A's inserts are committed and B's are rolled back. This is correct because direct sync has no cross-table FK remapping.

```python
for table in tables:
    # ... get source_rows, dest_slugs ...
    if hasattr(dest_adapter, 'transaction'):
        async with dest_adapter.transaction():
            for row in source_rows:
                # ... insert logic ...
    else:
        for row in source_rows:
            # ... insert logic (same code) ...
```

To avoid code duplication, extract the per-table insert loop into a local async helper. The helper must also receive the `result` object (to update `synced_count` and `skipped_count`) and `slug_field`. `ValueError` from FK violations should propagate out of the helper (and thus out of the transaction, triggering rollback):
```python
async def _insert_rows(adapter, table, source_rows, dest_slugs, slug_field, result):
    for row in source_rows:
        # ... insert logic (updates result.synced_count, result.skipped_count) ...
        # ValueError from FK violations propagates out → transaction rollback

for table in tables:
    # ... get source_rows, dest_slugs ...
    if hasattr(dest_adapter, 'transaction'):
        async with dest_adapter.transaction():
            await _insert_rows(dest_adapter, table, source_rows, dest_slugs, slug_field, result)
    else:
        await _insert_rows(dest_adapter, table, source_rows, dest_slugs, slug_field, result)
```

Tests must verify:
- `restore_database()`: rollback on unrecoverable error (mock adapter raises on insert, verify no rows persisted)
- `restore_database()`: commit with failure_details on per-row failure in skip/overwrite mode
- `apply_fixes()`: rollback on exception during DDL (verify transaction context manager's `__aexit__` receives exception)
- `apply_fixes()`: successful fix commits all DDL atomically
- `_sync_direct()`: per-table rollback on FK violation
- All three consumers work without transaction support (hasattr guard, backward compatible)

**Acceptance Criteria**:
- `restore_database()` wraps multi-table loop in `adapter.transaction()` when available
- `apply_fixes()` has transaction inside try/except (not outside) -- exception triggers rollback then error capture
- `_sync_direct()` wraps each table's insert loop independently in `adapter.transaction()` when available
- All three use `hasattr(adapter, 'transaction')` guard for backward compatibility
- Existing backup (48), fix (62), and sync tests pass unchanged
- New tests verify rollback on failure and commit on success for each consumer

**Trade-offs**:
- **Sync duplication**: Extract the insert loop body into a helper to avoid duplicating the insert logic for transaction vs. no-transaction paths. Alternative: duplicate the loop body, but that creates maintenance burden.
- **Restore transaction granularity**: Wrap entire multi-table loop (not per-table) because FK remapping across tables requires atomicity. Alternative: per-table transactions, but that risks orphaned child rows if parent table's transaction committed but child's rolls back.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_backup.py tests/test_lib_extraction_fix.py tests/test_lib_extraction_sync.py -v --tb=short
# Expected: All existing + new tests pass
```

**Output**: Backup, fix, and sync tests passing with new transaction tests

---

### Step 6: FK Pre-Flight Warning in CLI Sync

**Goal**: Add FK constraint detection in the CLI sync handler that warns users when direct-insert sync targets tables with FK constraints.

- [ ] Add FK detection logic in `_async_sync()` in `_data_sync.py`
- [ ] Emit console warning when FKs found and no `backup_schema` configured
- [ ] Write tests for FK pre-flight warning

**Specification**:

In `_async_sync()` (located in `src/db_adapter/cli/_data_sync.py` after the Step 1 split), after resolving config but before calling `sync_data()`, add FK detection:

1. When `config.backup_schema` is not configured (used as a heuristic — if the user has not declared a BackupSchema with FK relationships, they likely lack FK-aware sync setup, making direct inserts the default path), resolve the destination profile URL via `config.profiles[dest]` + `resolve_url(profile)` and create a `SchemaIntrospector`. Skip FK detection entirely if `config` is `None`. Note: `config.backup_schema` does not directly control the sync path (current `_async_sync` always calls `sync_data()` without a schema parameter), but its presence indicates the user has declared FK relationships and is aware of FK handling.
2. Call `introspector.introspect()` to get the database schema
3. Check constraints for the target tables: filter for `constraint_type == "FOREIGN KEY"` on the sync target tables
4. If any FKs are found, emit a warning via `console.print()`:
   ```
   [yellow]Warning:[/yellow] Tables {table_names} have foreign key constraints.
   Direct sync does not handle FK remapping. Consider configuring
   backup_schema in db.toml for FK-aware sync.
   ```
5. Continue with the sync (warning only, not blocking)

The CLI handler has config access and can resolve the destination profile URL to create a `SchemaIntrospector`. URL resolution pattern: `profile = config.profiles[dest_name]` then `url = resolve_url(profile)`. This check uses `SchemaIntrospector.introspect()` to get constraints, then filters for FK constraints on the target tables.

Import `SchemaIntrospector` from `db_adapter.schema.introspector` and `resolve_url` from `db_adapter.factory`.

Tests must verify:
- Warning is printed when direct sync targets tables with FK constraints
- No warning when `backup_schema` is provided (backup/restore path)
- No warning when target tables have no FK constraints
- Warning includes the names of tables that have FK constraints
- Sync proceeds after warning (not blocked)

**Acceptance Criteria**:
- FK detection runs only on direct-insert path (when `config.backup_schema` is not configured)
- Warning message includes table names with FK constraints
- Warning is printed via `console.print()` with `[yellow]Warning:[/yellow]` prefix
- No FK detection or warning when `config.backup_schema` is configured (backup/restore path handles FK remapping)
- FK detection skipped entirely when `config` is `None`
- `SchemaIntrospector` connection failure is caught gracefully — catch `Exception` broadly, skip warning silently or with `logger.debug()` (warning is best-effort, not critical)
- Existing CLI sync tests pass unchanged
- New tests mock `SchemaIntrospector` and verify warning output

**Trade-offs**:
- **Where to add FK detection**: CLI handler `_async_sync()` (recommended) because it has config access and console output. Alternative: inside `_sync_direct()` itself, but that function doesn't have config access or console.
- **Graceful degradation on introspection failure**: Catch `Exception` broadly from `SchemaIntrospector` and skip the warning silently (or log at `logger.debug()` level). Pattern: `try: ... except Exception: logger.debug("FK detection skipped: %s", e)`. Alternative: propagate the error, but FK detection is advisory-only and should never block sync.
- **Extra database connection**: FK detection creates an additional `SchemaIntrospector` connection to the destination database, used for one introspection query and then closed. This is acceptable because FK detection is best-effort and the connection is short-lived. If the destination has connection limits or credential issues, the broad `except Exception` catch ensures graceful degradation.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short -k "sync"
# Expected: All sync-related tests pass including new FK pre-flight tests
```

**Output**: Sync tests passing with new FK pre-flight warning tests

---

### Step 7: SQL Parser Upgrade with sqlparse

**Goal**: Replace 3 regex-based SQL parsing functions with `sqlparse`-based tokenization to handle comments, quoted identifiers, and schema-qualified names.

- [ ] Refactor `_parse_expected_columns()` in `_helpers.py` to use sqlparse
- [ ] Refactor `_parse_fk_dependencies()` in `fix.py` to use sqlparse
- [ ] Refactor `_get_table_create_sql()` in `fix.py` to use sqlparse
- [ ] Write edge-case tests for all 3 functions

**Specification**:

**`_parse_expected_columns()` in `src/db_adapter/cli/_helpers.py`**:

Replace regex with `sqlparse.parse()`. For each parsed statement:
1. Check `statement.get_type() == 'CREATE'` (note: this matches all CREATE statements — CREATE INDEX, CREATE VIEW, etc.)
2. Verify the statement contains the TABLE keyword to distinguish CREATE TABLE from other CREATE types (CREATE INDEX, CREATE VIEW, CREATE FUNCTION, etc.)
3. Extract table name from the `Identifier` token after CREATE TABLE keywords. Use `get_real_name()` (not `get_name()`) to strip schema prefixes (e.g., `public.users` -> `users`). Strip quotes from quoted identifiers (e.g., `"Items"` -> `Items`).
3. Extract column names from the `Parenthesis` token body. Strip comments from the body first (e.g., via `sqlparse.format(str(parenthesis), strip_comments=True)`) since Parenthesis tokens still contain comment tokens within them — comments are tokenized but not removed. Column extraction can then use line-splitting within the comment-free body (splitting on commas).
4. Ignore `CONSTRAINT`, `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, and `CHECK` keywords when extracting column names (these are table-level constraints, not column definitions).

**`_parse_fk_dependencies()` in `src/db_adapter/schema/fix.py`**:

Use `sqlparse.parse()` to find CREATE TABLE blocks and extract table names. The table name extraction follows the same pattern as `_parse_expected_columns()` (using `get_real_name()`, stripping quotes). REFERENCES extraction can remain regex-based within the tokenized body (comments already stripped by the tokenizer), but must handle schema-qualified references (`REFERENCES public.users(id)` -> `users`).

**`_get_table_create_sql()` in `src/db_adapter/schema/fix.py`**:

Use `sqlparse.parse()` to find the CREATE statement matching the requested table name. Return the raw SQL string of the matched statement (preserving original formatting including comments). Name matching: compare the sqlparse-extracted table name (after `get_real_name()`, quote stripping, lowercase) against the provided `table_name` (also lowercase).

**Edge cases all 3 functions must handle**:

| Input | Before (regex) | After (sqlparse) |
|-------|----------------|------------------|
| `CREATE TABLE public.users (...)` | Not found | Parsed correctly |
| `CREATE TABLE "Items" (...)` | Not found | Parsed correctly |
| `-- CREATE TABLE fake (...)` | Parsed as real table | Ignored (comment) |
| `/* block */ email TEXT` inside body | Fake columns extracted | Comment stripped |
| `REFERENCES public.users(id)` | Not found | Parsed correctly |
| `CREATE TABLE IF NOT EXISTS users (...)` | Handled | Still handled |

Tests must verify:
- All existing parsing tests pass unchanged (backward compatible for normal SQL)
- New tests for: SQL line comments (`--`), block comments (`/* */`), quoted identifiers, schema-qualified table names, schema-qualified REFERENCES, `IF NOT EXISTS` variant
- `_parse_expected_columns()` returns correct column sets for edge cases
- `_parse_fk_dependencies()` returns correct dependency graph for edge cases
- `_get_table_create_sql()` finds correct CREATE statement for edge cases

**Acceptance Criteria**:
- `_parse_expected_columns()` correctly parses tables named with schema prefix (`public.users`), quoted identifiers (`"Items"`), and ignores commented-out CREATE TABLE lines
- `_parse_fk_dependencies()` handles `REFERENCES public.users(id)` and returns `users` (not `public.users`) in the dependency set
- `_get_table_create_sql()` finds `CREATE TABLE public.users (...)` when called with `table_name="users"`
- All 3 functions ignore SQL comments (line and block) that would previously create false positives
- `sqlparse` is used via `sqlparse.parse()` for all 3 functions (no regex for CREATE TABLE detection)
- Existing 62 fix tests pass unchanged
- Existing parsing tests in CLI tests pass unchanged
- 8-10 new edge-case tests added across fix and CLI test files

**Trade-offs**:
- **Column extraction granularity**: Keep line-splitting within the tokenized parenthesis body (simpler) rather than full token-level column scanning (more complex, marginal benefit). Alternative: deep token-level parsing, but sqlparse's tokenization of column definitions is inconsistent across PostgreSQL-specific syntax.
- **REFERENCES extraction**: Keep regex within the tokenized body for REFERENCES (simpler, already comment-free). Alternative: pure token-level scanning, but the regex is simple and reliable on clean input.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_fix.py tests/test_lib_extraction_cli.py -v --tb=short
# Expected: All existing + new edge-case tests pass
```

**Output**: Fix and CLI tests passing with new sqlparse edge-case tests

---

### Step 8: Full Suite Validation

**Goal**: Run the complete test suite to verify no regressions across all steps.

- [ ] Run full 824+ test suite
- [ ] Verify `uv run db-adapter --help` works
- [ ] Verify CLI entry point is unchanged

**Specification**:

Run the full test suite and verify all tests pass. Check that:
- All 824+ tests pass (original 824 + new tests added in Steps 1-7)
- `uv run db-adapter --help` displays help text without errors
- The entry point `db_adapter.cli:main` is unchanged in `pyproject.toml`
- No import errors from any module

**Acceptance Criteria**:
- Full test suite passes with zero failures
- `uv run db-adapter --help` returns exit code 0
- CLI entry point in `pyproject.toml` remains `db_adapter.cli:main`
- All new test files and modules follow absolute import patterns

**Verification**:
```bash
# Full test suite
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short

# CLI entry point check
cd /Users/docchang/Development/db-adapter && uv run db-adapter --help

# Verify entry point in pyproject.toml
grep 'db_adapter.cli:main' /Users/docchang/Development/db-adapter/pyproject.toml
# Expected: db-adapter = "db_adapter.cli:main"
```

**Output**: Full suite passing, CLI operational

---

## Test Summary

### Affected Tests (Run These)

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `tests/test_lib_extraction_cli.py` | ~177 | CLI commands, mock patching, parsing |
| `tests/test_lib_extraction_backup.py` | ~48 | Backup/restore round-trips, FK remapping |
| `tests/test_lib_extraction_fix.py` | ~62 | Fix plan generation, DDL, SQL parsing |
| `tests/test_lib_extraction_adapters.py` | ~54 | Protocol, adapter implementations |
| `tests/test_lib_extraction_exports.py` | varies | Public API `__all__` lists |
| `tests/test_lib_extraction_imports.py` | varies | Absolute import patterns |

**Affected tests: ~341+ tests**

**Full suite**: 824+ tests (run at Step 8 and optionally after Steps 2, 5, 7)

---

## What "Done" Looks Like

```bash
# 1. Full test suite passes
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short
# Expected: 824+ tests pass (original + new tests from Steps 1-7)

# 2. CLI works after split
cd /Users/docchang/Development/db-adapter && uv run db-adapter --help
# Expected: Help text displays, exit code 0

# 3. CLI entry point unchanged
grep 'db-adapter' /Users/docchang/Development/db-adapter/pyproject.toml
# Expected: db-adapter = "db_adapter.cli:main"
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/db_adapter/cli/_helpers.py` | Create | Shared helpers, constants, console |
| `src/db_adapter/cli/_connection.py` | Create | connect, validate, status, profiles |
| `src/db_adapter/cli/_schema_fix.py` | Create | fix command |
| `src/db_adapter/cli/_data_sync.py` | Create | sync command + FK pre-flight |
| `src/db_adapter/cli/_backup.py` | Create | backup, restore, validate-backup |
| `src/db_adapter/cli/__init__.py` | Modify | Reduce to facade (main, argparse, re-exports) |
| `src/db_adapter/backup/backup_restore.py` | Modify | Add failure_details, logging, transaction wrap |
| `src/db_adapter/adapters/base.py` | Modify | Add transaction() to Protocol |
| `src/db_adapter/adapters/postgres.py` | Modify | Implement transaction() with contextvars |
| `src/db_adapter/adapters/supabase.py` | Modify | Implement transaction() as NotImplementedError |
| `src/db_adapter/schema/fix.py` | Modify | Transaction wrap + sqlparse refactor |
| `src/db_adapter/schema/sync.py` | Modify | Transaction wrap in _sync_direct() |
| `pyproject.toml` | Modify | Add sqlparse dependency |
| `tests/test_lib_extraction_cli.py` | Modify | Update ~178 mock patch targets + new tests |
| `tests/test_lib_extraction_backup.py` | Modify | Add failure_details + transaction tests |
| `tests/test_lib_extraction_fix.py` | Modify | Add sqlparse edge-case tests + transaction tests |
| `tests/test_lib_extraction_adapters.py` | Modify | Add transaction tests |

---

## Dependencies

Update `pyproject.toml`:

```toml
dependencies = [
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "psycopg[binary]>=3.0",
    "pydantic>=2.0",
    "rich>=13.0",
    "sqlparse>=0.5",
]
```

Then run:
```bash
cd /Users/docchang/Development/db-adapter && uv sync
```

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `sqlparse` doesn't handle all PostgreSQL edge cases | LOW | sqlparse handles standard SQL; PostgreSQL-specific syntax is in column definitions, not table/column names |
| `contextvars` transaction tracking has edge cases with nested transactions | LOW | Raise RuntimeError on nested calls; no savepoint support in v1 |
| CLI split introduces subtle import ordering issues | LOW | All 824 tests validate imports; run full suite after split |
| `hasattr()` guard pattern is fragile | LOW | Only 3 call sites; well-documented; upgrade to Protocol check at 1.0 |
| Long-running transactions on large restores | LOW | Restore: acceptable for developer-scoped data (small datasets). Sync: per-table transaction granularity limits transaction size. |
| Mock patch target migration misses some targets | MED | Run full CLI test suite (177 tests) after migration; grep for old targets |

---

## Next Steps After Completion

1. Verify full test suite passes (824+ tests)
2. Verify `uv run db-adapter --help` works
3. Verify CLI entry point unchanged in pyproject.toml
4. Proceed to next task in the milestone

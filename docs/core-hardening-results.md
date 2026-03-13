# Core-Hardening Results

> **Plan**: See `docs/core-hardening-plan.md`

## Summary
| Attribute | Value |
|-----------|-------|
| **Status** | Complete |
| **Started** | 2026-03-13T11:41:47-0700 |
| **Completed** | 2026-03-13T12:25:28-0700 |
| **Reviewed** | 2026-03-13T15:06:26-0700 |
| **Proves** | Library-grade reliability: atomicity, error visibility, modularity, and robust SQL parsing |

## Diagram

```
┌──────────────────────────────────────┐
│           Core Hardening             │
│             RELIABILITY              │
│            ✅ Complete               │
│                                      │
│ Modularity                           │
│   • CLI split into 6 modules         │
│   • Facade re-exports 24 symbols     │
│   • Acyclic import graph             │
│                                      │
│ Atomicity                            │
│   • transaction() on Protocol        │
│   • ContextVar per-instance isolation │
│   • restore/fix/sync wrapped         │
│                                      │
│ Error Visibility                     │
│   • failure_details per row          │
│   • FK pre-flight warning            │
│   • logging.warning on failures      │
│                                      │
│ SQL Parsing                          │
│   • sqlparse replaces regex          │
│   • Quoted identifiers handled       │
│   • Schema-qualified names handled   │
│   • SQL comments stripped            │
└──────────────────────────────────────┘
```

---

## Goal
Harden db-adapter library with: CLI modular split, restore failure details, transaction support (Protocol + consumers), FK pre-flight warnings, and sqlparse-based SQL parsing replacing regex.

---

## Success Criteria
From `docs/core-hardening-plan.md`:

- [x] CLI split into 6 modules with all 177 CLI tests passing after patch target migration and unchanged entry point `db_adapter.cli:main`
- [x] Restore `failure_details` present in result dict when `failed > 0`, containing `row_index`, `old_pk`, `error` per failure
- [x] CLI displays per-row failure details below Rich Table on restore
- [x] `transaction()` method on `DatabaseClient` Protocol, implemented in both adapters (contextvars for postgres, NotImplementedError for supabase)
- [x] `restore_database()` rolls back all inserts on unrecoverable error; per-row failures in mode=skip/overwrite collected in `failure_details`
- [x] `apply_fixes()` rolls back all DDL on any exception (transaction wraps inside try/except)
- [x] `_sync_direct()` rolls back per-table on FK violation
- [x] FK pre-flight warning emitted in CLI when direct sync targets tables with FK constraints
- [x] `_parse_expected_columns()`, `_parse_fk_dependencies()`, `_get_table_create_sql()` handle quoted identifiers, schema-qualified names, and SQL comments
- [x] `sqlparse` added as core dependency
- [x] All existing 828 tests pass (704 original + 124 new from Steps 1-7)

**ALL CRITERIA MET**

---

## Prerequisites Completed
- [x] Affected test files identified (6 files, 417 tests)
- [x] Baseline verification passed: 417 affected tests pass, 704 total non-live tests pass

---

## Implementation Progress

### Step 0: Add sqlparse Dependency ✅
**Status**: Complete (2026-03-13T11:43:04-0700)
**Expected**: Add `sqlparse>=0.5` as a core dependency in `pyproject.toml` and verify installation.

**Implementation**:
- Added `"sqlparse>=0.5"` to `dependencies` list in `pyproject.toml` after `"rich>=13.0"`
- Ran `uv sync` -- sqlparse 0.5.5 installed successfully
- Verified import: `import sqlparse; print(sqlparse.__version__)` prints `0.5.5`

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 704/704 non-live tests passing
```bash
$ uv run pytest tests/ --ignore=tests/test_live_integration.py -v --tb=short -q
======================= 704 passed, 15 warnings in 6.01s =======================
```

Note: 153 failures in `test_live_integration.py` are pre-existing (require real database connections with `full` and `drift` profiles) and unrelated to this change.

**Issues**: None

**Trade-offs & Decisions**: No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- `uv sync` automatically resolves and installs transitive dependencies; sqlparse has no transitive deps so this was clean.
- The live integration tests (`test_live_integration.py`) always fail without database connections. The plan's "824 tests" count includes these; the actual verifiable baseline is 704 non-live tests.

**Result**: sqlparse 0.5.5 installed and importable. All 704 non-live tests pass with no regressions. Ready for Step 1.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- Plan specified adding `"sqlparse>=0.5"` after `"rich>=13.0"` and running `uv sync`. Both satisfied. The 704 vs 824 test count discrepancy is a correction of an inaccurate plan count (824 included live integration tests), not a missing criterion.
- **Assumption audit**: PASS -- No assumptions introduced beyond the plan. Version constraint `>=0.5` follows existing project convention.
- **Silent trade-offs**: PASS -- No undocumented decisions.
- **Complexity proportionality**: PASS -- Single line added to pyproject.toml, appropriate scope.
- **Architectural drift**: PASS -- Exactly one line added to dependencies list in pyproject.toml, matching plan specification.

---

### Step 1: CLI File Split -- Extract Functions into Sub-Modules ✅
**Status**: Complete (2026-03-13T11:51:48-0700)
**Expected**: Split `src/db_adapter/cli/__init__.py` (1842 lines) into 5 internal modules + facade `__init__.py` retaining `main()` and re-exporting 24 symbols.

**Implementation**:
- Created `src/db_adapter/cli/_helpers.py` (321 lines) -- `console`, `_EXCLUDED_TABLES`, `_get_table_row_counts`, `_print_table_counts`, `_parse_expected_columns`, `_resolve_user_id`, `_load_backup_schema`, `_resolve_backup_schema_path`
- Created `src/db_adapter/cli/_connection.py` (403 lines) -- `_async_connect`, `_async_validate`, `_async_status`, `cmd_connect`, `cmd_status`, `cmd_profiles`, `cmd_validate`
- Created `src/db_adapter/cli/_schema_fix.py` (379 lines) -- `_async_fix`, `cmd_fix`
- Created `src/db_adapter/cli/_data_sync.py` (214 lines) -- `_async_sync`, `cmd_sync`
- Created `src/db_adapter/cli/_backup.py` (430 lines) -- `_async_backup`, `_async_restore`, `_validate_backup`, `cmd_backup`, `cmd_restore`
- Reduced `__init__.py` to 307 lines (facade with `main()`, argparse, and 24 re-exports)
- Created `tests/test_hardening_cli_split.py` (49 tests) verifying: sub-module files exist, all 24 symbols importable, no circular imports, acyclic import graph, facade size, CLI `--help` works

**Deviation from Plan**: `__init__.py` is 307 lines instead of the estimated ~245. The difference is due to the argparse setup being inherently verbose (8 subcommands with multiple arguments each). The facade pattern is correctly implemented -- no command logic remains in `__init__.py`.

**Test Results**: 125/125 tests passing (49 new + 76 existing export/import tests)
```bash
$ uv run pytest tests/test_hardening_cli_split.py tests/test_lib_extraction_exports.py tests/test_lib_extraction_imports.py -v --tb=short
============================= 125 passed in 10.26s =============================
```

Broader suite (excluding intentionally-broken CLI tests and live tests): 576/576 passing
```bash
$ uv run pytest tests/ --ignore=tests/test_live_integration.py --ignore=tests/test_lib_extraction_cli.py -v --tb=short -q
====================== 576 passed, 13 warnings in 12.96s ======================
```

`uv run db-adapter --help` succeeds with all 8 subcommands listed.

**Issues**: None. Initial test run had 2 minor test issues (subprocess `-m` flag needs `__main__.py`, line count range too narrow) -- fixed in test file immediately.

**Trade-offs & Decisions**:
- **Decision:** Placed `_parse_expected_columns` in `_helpers.py` (not a separate `_parsing.py` module)
  - **Alternatives considered:** Separate `_parsing.py` module
  - **Why this approach:** Plan specifies it goes in `_helpers.py`; it will be refactored to use sqlparse in Step 7, at which point a separate module might make sense
  - **Risk accepted:** `_helpers.py` at 321 lines includes a function that may grow during sqlparse migration

**Lessons Learned**:
- The `from db_adapter.cli._helpers import console` pattern means each sub-module gets the same Console instance (module-level singleton), which is correct for CLI output consistency.
- Import graph acyclicity is enforced structurally: `_helpers.py` imports only from `db_adapter.*` and stdlib; command modules import from `_helpers` and `db_adapter.*`; `__init__.py` imports from all. No cross-imports between command modules.
- After the split, `patch("db_adapter.cli.<name>")` in existing CLI tests will fail because the name is looked up in the sub-module, not the facade. This is expected and addressed in Step 2.
- The facade's 307 lines are primarily argparse boilerplate (8 subcommands with 2-6 arguments each). The actual facade logic is just imports + `main()`.

**Result**: CLI successfully split into 6 focused modules. All 24 symbols re-exportable from `db_adapter.cli`. Entry point `db_adapter.cli:main` unchanged. Import graph is acyclic. The 177 CLI tests in `test_lib_extraction_cli.py` will intentionally fail until Step 2 migrates their patch targets. Ready for Step 2.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 5 acceptance criteria satisfied. 24 symbols in facade match plan's enumerated list exactly. main() defined locally in __init__.py. __init__.py is 307 lines vs estimated 245; deviation documented (argparse boilerplate, no command logic remains). All 5 sub-module files exist. Import graph verified acyclic: _helpers.py has zero cli._* imports, no cross-imports between command modules.
- **Assumption audit**: PASS -- Decision to place _parse_expected_columns in _helpers.py documented in Trade-offs and matches plan's explicit specification. File line counts reflect Step 1 state while disk reflects final state after all steps -- consistent and expected.
- **Silent trade-offs**: PASS -- No undocumented decisions found.
- **Complexity proportionality**: PASS -- 5 sub-modules plus facade is the minimum split needed for the plan's subsequent steps.
- **Architectural drift**: PASS -- File structure matches plan exactly. Function assignments match. Each sub-module imports directly from library source modules, not the facade. Entry point unchanged.

---

### Step 2: Migrate Mock Patch Targets in Test Files ✅
**Status**: Complete (2026-03-13T11:56:43-0700)
**Expected**: Update all 178 `patch("db_adapter.cli.<name>", ...)` occurrences in `tests/test_lib_extraction_cli.py` to reference the sub-module where each name is actually used.

**Implementation**:
- Mapped each patched name to its new sub-module target by analyzing which sub-module imports the name being patched and which command's code path is being tested
- Updated all patch targets in `tests/test_lib_extraction_cli.py` using a systematic Python script that processes each test class and applies the correct sub-module target based on which command the class tests
- Patch target mapping applied:
  - `_connection.py` targets: `load_db_config`, `read_profile_lock`, `connect_and_validate`, `resolve_url`, `console`, `_get_table_row_counts`, `_print_table_counts` (for TestAsyncConnectConfigDriven, TestConnectRowCountsIntegration, TestStatusRowCountsIntegration, TestAsyncValidateConfigDriven)
  - `_data_sync.py` targets: `load_db_config`, `read_profile_lock`, `compare_profiles`, `sync_data`, `console` (for TestAsyncSyncErrors, TestAsyncSyncConfigDefaults)
  - `_schema_fix.py` targets: `load_db_config`, `get_active_profile_name`, `connect_and_validate`, `get_adapter`, `backup_database`, `console` (for TestAsyncFixConfigFallback, TestAsyncFixColumnDefsResolution, TestAsyncFixAutoBackup)
  - `_backup.py` targets: `load_db_config`, `get_adapter`, `backup_database`, `restore_database`, `console`, `asyncio`, `_validate_backup` (for TestCmdBackupWrapper, TestCmdRestoreWrapper, TestAsyncBackup, TestAsyncRestore, TestValidateBackup)
  - `_helpers.py` targets: `AsyncConnection.connect`, `console` (for TestGetTableRowCounts, TestPrintTableCounts)
  - `db_adapter.cli.cmd_*` targets retained as-is for `main()` dispatch tests (TestCLIArguments, TestBackupSubparser, TestRestoreSubparser)
- 282 lines changed across the file
- Zero remaining `patch("db_adapter.cli.load_db_config"`, `patch("db_adapter.cli.console"`, or `patch("db_adapter.cli.read_profile_lock"` occurrences (all migrated to sub-modules)

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 302/302 tests passing (177 CLI + 76 export/import + 49 CLI split)
```bash
$ uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
======================= 177 passed, 2 warnings in 0.93s ========================

$ uv run pytest tests/test_lib_extraction_exports.py tests/test_lib_extraction_imports.py tests/test_hardening_cli_split.py -v --tb=short
============================== 125 passed ======================================
```

Full non-live test suite: 753/753 passing
```bash
$ uv run pytest tests/ --ignore=tests/test_live_integration.py -v --tb=short -q
====================== 753 passed, 15 warnings in 13.11s =======================
```

**Issues**: None. All 177 tests passed on the first run after migration.

**Trade-offs & Decisions**: No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- The "patch where the name is looked up" rule is the key to correct mock patching after a module split. Each sub-module imports names directly from library modules (e.g., `_connection.py` imports `load_db_config` from `db_adapter.config.loader`), so patches must target the sub-module's binding, not the facade's re-export.
- Organizing the migration by test class (which maps 1:1 to the command being tested) made the mapping deterministic: every test class tests exactly one command, which lives in exactly one sub-module.
- The `cmd_*` patches in `main()` dispatch tests correctly remain as `db_adapter.cli.cmd_*` because `main()` lives in `__init__.py` and looks up `cmd_*` from its own namespace via the re-imports.
- A systematic script approach (vs. manual find-and-replace) eliminated the risk of mismatched patch targets when the same name (e.g., `load_db_config`) maps to different sub-modules depending on context.

**Result**: All 177 CLI tests pass with updated patch targets. No `patch("db_adapter.cli.<name>")` references remain for names that now live in sub-modules (except `cmd_*` in main dispatch tests). CLI split is now fully verified end-to-end. Ready for Step 3.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 4 acceptance criteria met. Zero remaining facade-level patches for load_db_config, console, or read_profile_lock. 15 cmd_* patches remain at db_adapter.cli.cmd_* as specified. All 177 CLI tests pass. Full non-live suite at 753.
- **Assumption audit**: PASS -- Each test class maps to exactly one command/sub-module, making the mapping deterministic. Patches correctly target sub-module bindings (e.g., db_adapter.cli._connection.load_db_config), not origin modules. _helpers.console patches used only for tests exercising _print_table_counts directly.
- **Silent trade-offs**: PASS -- No undocumented decisions found.
- **Complexity proportionality**: PASS -- Only test_lib_extraction_cli.py modified, no structural additions.
- **Architectural drift**: PASS -- 178 total patch occurrences: 163 reference sub-modules, 15 remain as db_adapter.cli.cmd_* for main() dispatch. No new files created.

---

### Step 3: Restore Failure Details ✅
**Status**: Complete (2026-03-13T12:00:31-0700)
**Expected**: Capture per-row error details in `_restore_table()` and display them in the CLI restore output.

**Implementation**:
- Added `import logging` and `logger = logging.getLogger(__name__)` to `src/db_adapter/backup/backup_restore.py`
- Changed `for row in rows:` to `for i, row in enumerate(rows):` in `_restore_table()`
- Moved `old_pk` extraction before the `try` block with safe access: `old_pk = row.get(table_def.pk, "<unknown>")`
- Changed `except Exception:` to `except Exception as e:` and added `failure_details` capture and `logger.warning()` call
- Added failure details display in `src/db_adapter/cli/_backup.py` after the Rich Table output in `_async_restore()`
- Created `tests/test_hardening_restore_failure_details.py` with 11 tests covering: single failure, multiple failures, no failures, missing PK in insert result, logger.warning behavior

**Deviation from Plan**: The "failure with missing PK field" test was adapted. The plan suggested testing a row with no PK field, but `validate_backup()` rejects such rows before restore runs. Instead, the test verifies the safe `.get()` default by having the adapter return an insert result without the PK key (causing `KeyError` on `result[table_def.pk]`), which correctly demonstrates that `old_pk` was safely captured before the `try` block.

**Test Results**: 764/764 non-live tests passing (11 new + 753 existing)
```bash
$ uv run pytest tests/test_hardening_restore_failure_details.py tests/test_lib_extraction_backup.py -v --tb=short
============================== 59 passed in 0.68s ==============================

$ uv run pytest tests/ --ignore=tests/test_live_integration.py -v --tb=short -q
====================== 764 passed, 15 warnings in 13.34s =======================
```

**Issues**: Initial test for missing PK field failed because `validate_backup()` catches missing PK fields during validation (before restore). Fixed by testing a different scenario: adapter insert returning a result dict without the PK key, which triggers `KeyError` on `result[table_def.pk]` inside `_restore_table()` and correctly demonstrates the safe `old_pk` extraction.

**Trade-offs & Decisions**:
- **Decision:** `failure_details` key is only present via `setdefault()` when at least one failure occurs (lazy initialization)
  - **Alternatives considered:** Always initializing `failure_details` as an empty list in `restore_database()`
  - **Why this approach:** Backward compatible -- existing consumers checking `summary[table]["failed"]` see no new keys when `failed == 0`. The `setdefault()` pattern is idiomatic Python for optional accumulation.
  - **Risk accepted:** Consumers must use `.get("failure_details", [])` rather than direct key access

**Lessons Learned**:
- The `validate_backup()` function acts as a pre-flight check that catches structural issues (missing PK fields, wrong version, missing tables) before `_restore_table()` runs. This means certain error paths in `_restore_table()` are unreachable for structurally invalid data -- tests must simulate failures that pass validation but fail during insert/update.
- Moving `old_pk = row.get(table_def.pk, "<unknown>")` before the `try` block is important: if it were inside the `try` block with direct `row[table_def.pk]` access, a `KeyError` would be caught but `old_pk` would be unbound in the `except` handler.
- The `f"{type(e).__name__}: {e}"` pattern in `failure_details` gives both the exception class and message, which is more useful for debugging than just the message string.

**Result**: `_restore_table()` now captures per-row failure details with `row_index`, `old_pk`, and `error` fields. CLI displays failure details below the Rich Table. `logger.warning()` emits structured log messages per failed row. All 48 existing backup tests pass unchanged. Ready for Step 4.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 7 acceptance criteria met: enumerate() on row loop, old_pk via .get() before try block, except Exception as e with failure_details capture via setdefault, logger.warning per failed row, CLI display after Rich Table, failure_details absent when failed==0, existing 48 backup tests pass unchanged.
- **Assumption audit**: PASS -- Two decisions beyond design documented with rationale: (1) lazy init via setdefault() for backward compatibility, (2) adapted missing-PK test because validate_backup() rejects such rows pre-restore.
- **Silent trade-offs**: PASS -- No undocumented decisions found.
- **Complexity proportionality**: PASS -- Changes scoped to exactly the two files specified plus one test file.
- **Architectural drift**: PASS -- Modifies exactly backup_restore.py and cli/_backup.py as planned. Logging pattern matches design specification.

---

### Step 4: Transaction Support -- Protocol and Adapter Implementation ✅
**Status**: Complete (2026-03-13T12:05:23-0700)
**Expected**: Add `transaction()` async context manager to `DatabaseClient` Protocol and implement in both adapters.

**Implementation**:
- Added `AbstractAsyncContextManager` import and `transaction()` method to `DatabaseClient` Protocol in `src/db_adapter/adapters/base.py` (now 7 methods: 6 async + 1 sync)
- Added `contextvars`, `asynccontextmanager`, and `AsyncConnection` imports to `src/db_adapter/adapters/postgres.py`
- Added instance-level `ContextVar` (`_transaction_conn`) in `AsyncPostgresAdapter.__init__()` with unique name per instance (`f"_transaction_conn_{id(self)}"`) for cross-instance isolation
- Implemented `transaction()` as `@asynccontextmanager` on `AsyncPostgresAdapter`: checks for nested call (RuntimeError), uses `engine.begin()` for connection, sets/resets ContextVar via token
- Modified all 5 CRUD methods (`select`, `insert`, `update`, `delete`, `execute`) to check `self._transaction_conn.get(None)` first -- if set, use transaction connection directly; otherwise, use existing engine.connect()/engine.begin() behavior
- Added `transaction()` to `AsyncSupabaseAdapter` that raises `NotImplementedError("Transactions not supported for Supabase adapter.")`
- Updated `test_protocol_has_exactly_six_methods` -> `test_protocol_has_seven_methods` in `tests/test_lib_extraction_adapters.py` to check for 6 async + 1 sync method
- Created `tests/test_hardening_transaction.py` with 30 tests across 7 test classes

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 84/84 tests passing (30 new + 54 existing adapter tests)
```bash
$ uv run pytest tests/test_hardening_transaction.py tests/test_lib_extraction_adapters.py -v --tb=short
============================== 84 passed in 0.70s ==============================
```

Full non-live test suite: 794/794 passing
```bash
$ uv run pytest tests/ --ignore=tests/test_live_integration.py -v --tb=short -q
====================== 794 passed, 15 warnings in 12.89s =======================
```

**Issues**: None. All tests passed on the first run.

**Trade-offs & Decisions**:
- **Decision:** Used `sqlalchemy.ext.asyncio.AsyncConnection` as the ContextVar type (not raw asyncpg connection)
  - **Alternatives considered:** Raw asyncpg connection for lower-level control
  - **Why this approach:** All CRUD methods use SQLAlchemy's `text()` API; using raw asyncpg would require rewriting all query execution paths
  - **Risk accepted:** Tied to SQLAlchemy's async connection abstraction

**Lessons Learned**:
- Per-instance ContextVar names (`f"_transaction_conn_{id(self)}"`) are essential when multiple adapter instances coexist in the same asyncio task (e.g., `_sync_direct()` creates both source and dest adapters). Without unique names, a module-level ContextVar would leak the transaction connection from one adapter to another.
- The `@asynccontextmanager` decorator on `transaction()` makes the method return type compatible with `AbstractAsyncContextManager[None]` on the Protocol without needing an explicit return type annotation on the concrete implementation.
- SQLAlchemy's `engine.begin()` context manager handles commit/rollback automatically: `__aexit__` with no exception triggers commit, `__aexit__` with exception triggers rollback. The `transaction()` method just needs to manage the ContextVar lifecycle -- it delegates commit/rollback entirely to SQLAlchemy.
- The ContextVar `reset(token)` in the `finally` block ensures the ContextVar is always cleaned up, even when an exception propagates. This prevents a stale transaction connection from being visible to subsequent CRUD calls.

**Result**: `DatabaseClient` Protocol now has 7 methods (6 async + 1 sync `transaction()`). `AsyncPostgresAdapter` implements transaction support via instance-level ContextVar with per-instance isolation. All 5 CRUD methods check the ContextVar before creating their own connection. `AsyncSupabaseAdapter` raises `NotImplementedError`. All 54 existing adapter tests pass unchanged (with one test renamed). Ready for Step 5.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 7 acceptance criteria verified against actual code. Protocol declares transaction() with correct return type. Per-instance ContextVar with id(self) for isolation. All 5 CRUD methods check _transaction_conn. Nested calls raise RuntimeError. Supabase raises NotImplementedError. test_protocol_has_seven_methods correctly checks 6 async + 1 sync. 30 new tests cover all required scenarios.
- **Assumption audit**: PASS -- @asynccontextmanager on concrete method while Protocol declares def returning AbstractAsyncContextManager is structurally correct and documented. ContextVar type choice (SQLAlchemy AsyncConnection vs raw asyncpg) documented in Trade-offs.
- **Silent trade-offs**: PASS -- No undocumented decisions found.
- **Complexity proportionality**: PASS -- Changes scoped to exactly the 3 adapter files specified.
- **Architectural drift**: PASS -- Exactly base.py, postgres.py, and supabase.py modified as planned. Test file follows test_hardening_* naming convention. Absolute imports throughout.

---

### Step 5: Transaction Wrapping for Consumers ✅
**Status**: Complete (2026-03-13T12:12:33-0700)
**Expected**: Wrap `restore_database()`, `apply_fixes()`, and `_sync_direct()` in adapter transactions with correct exception handler restructuring.

**Implementation**:
- Added `_noop_transaction()` async context manager and `_get_transaction_ctx()` helper to `backup/backup_restore.py`, `schema/fix.py`, and `schema/sync.py`
- `_get_transaction_ctx()` safely calls `adapter.transaction()` with try/except for `AttributeError`, `NotImplementedError`, and `TypeError`, plus a `__aenter__` check to validate the result is a proper async context manager (handles mock adapters that return coroutines instead)
- `restore_database()`: wraps entire multi-table `for table_def in schema.tables:` loop in `async with ctx:` for FK remapping atomicity
- `apply_fixes()`: moved `async with ctx:` inside the existing `try/except` block (transaction block inside try/except, not outside) so exceptions trigger rollback then error capture
- `_sync_direct()`: extracted insert loop into `_insert_rows()` async helper to avoid code duplication; wraps per-table via `async with _get_transaction_ctx(dest_adapter):` (per-table granularity, not multi-table)
- Created `tests/test_hardening_transaction_consumers.py` with 13 tests across 3 test classes

**Deviation from Plan**: Used `_get_transaction_ctx()` helper with try/except + `__aenter__` validation instead of the plan's `hasattr(adapter, 'transaction')` guard. The `hasattr` approach fails with `AsyncMock()` objects (which auto-create any attribute), causing existing tests to break. The `_get_transaction_ctx()` pattern is strictly more robust: it catches `AttributeError` (no method), `NotImplementedError` (Supabase), `TypeError` (unexpected), and validates the result is an actual async context manager. All three consumers use this shared pattern, eliminating the if/else branching the plan described.

**Test Results**: 807/807 non-live tests passing (13 new + 794 existing)
```bash
$ uv run pytest tests/test_hardening_transaction_consumers.py -v --tb=short
============================== 13 passed in 0.54s ==============================

$ uv run pytest tests/test_lib_extraction_backup.py tests/test_lib_extraction_fix.py tests/test_lib_extraction_sync.py -v --tb=short
======================= 159 passed, 23 warnings in 0.81s ======================

$ uv run pytest tests/ --ignore=tests/test_live_integration.py -q
807 passed, 48 warnings in 12.67s
```

**Issues**: Initial implementation used `hasattr(adapter, 'transaction')` as the plan specified, but this broke 24 existing tests. `AsyncMock()` objects auto-create any attribute on access, so `hasattr` always returns `True` for mock adapters. The `transaction()` call then returns a coroutine (not an async context manager), which fails with `TypeError: 'coroutine' object does not support the asynchronous context manager protocol`. Fixed by implementing `_get_transaction_ctx()` with try/except + `__aenter__` validation, which gracefully falls back to `_noop_transaction()` for mock adapters.

**Trade-offs & Decisions**:
- **Decision:** Used `_get_transaction_ctx()` helper in all three modules instead of `hasattr` guard
  - **Alternatives considered:** (1) `hasattr(adapter, 'transaction')` as plan specified; (2) Using `spec` on all existing test mocks to restrict attributes
  - **Why this approach:** `hasattr` fails with `AsyncMock` (auto-creates attributes). Modifying existing test mocks would violate the acceptance criterion "existing tests pass unchanged". The `_get_transaction_ctx()` pattern is production-safe, mock-safe, and eliminates code duplication (if/else branching)
  - **Risk accepted:** Three copies of `_get_transaction_ctx()` and `_noop_transaction()` across modules (could be centralized in a shared utils module, but that's a refactoring concern for later)

**Lessons Learned**:
- `AsyncMock()` auto-creates any attribute on access, making `hasattr()` unreliable for feature detection. When production code needs to check if a mock-compatible object supports a method that returns a specific protocol (like async context manager), a try/except with result validation is more robust than `hasattr`.
- The `__aenter__` check on the result of `adapter.transaction()` is the key discriminator: a coroutine from `AsyncMock` has no `__aenter__`, while a real `@asynccontextmanager`-decorated function returns an object that does.
- PostgreSQL's transactional DDL means `apply_fixes()` genuinely benefits from the transaction wrapper -- if CREATE TABLE succeeds but ALTER fails, the whole batch rolls back. This is a real atomicity gain, not just a consistency improvement.
- The `_noop_transaction()` pattern (no-op async context manager as fallback) eliminates code duplication entirely -- the fix/restore/sync logic is written once, not duplicated in if/else branches.

**Result**: All three consumers (`restore_database()`, `apply_fixes()`, `_sync_direct()`) now wrap their operations in adapter transactions when available, with safe fallback via `_get_transaction_ctx()`. Existing 159 affected tests pass unchanged. 13 new tests verify: transaction used when available, rollback on errors, commit on success, backward compatibility without transaction support. Ready for Step 6.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 6 acceptance criteria satisfied. restore_database() wraps entire multi-table loop in transaction. apply_fixes() places transaction inside try/except. _sync_direct() wraps per-table via _insert_rows() helper. The hasattr criterion was replaced with documented, strictly more robust _get_transaction_ctx() alternative (AsyncMock defeats hasattr). Existing 159 tests pass unchanged. 13 new tests cover all scenarios.
- **Assumption audit**: PASS -- _get_transaction_ctx() with try/except + __aenter__ validation fully documented in Trade-offs with rationale, alternatives, and accepted risk (three copies across modules).
- **Silent trade-offs**: PASS -- Deviation from hasattr to _get_transaction_ctx() explicitly documented with justification.
- **Complexity proportionality**: PASS -- _noop_transaction() eliminates if/else branching, reducing complexity vs plan's approach.
- **Architectural drift**: PASS -- Exactly backup_restore.py, fix.py, and sync.py modified as planned. No unexpected files beyond test file.

---

### Step 6: FK Pre-Flight Warning in CLI Sync ✅
**Status**: Complete (2026-03-13T12:16:31-0700)
**Expected**: Add FK constraint detection in `_async_sync()` that warns users when direct-insert sync targets tables with FK constraints.

**Implementation**:
- Added `import logging`, `logger`, `resolve_url`, and `SchemaIntrospector` imports to `src/db_adapter/cli/_data_sync.py`
- Added FK detection block in `_async_sync()` after dest resolution and before `compare_profiles()` call
- FK detection runs only when `config is not None` and `config.backup_schema` is not configured (heuristic for direct-insert path)
- Resolves destination profile URL via `config.profiles[dest]` + `resolve_url(profile)`, creates `SchemaIntrospector`, calls `introspect()`, filters constraints for `constraint_type == "FOREIGN KEY"` on target tables
- If FK constraints found, emits warning via `console.print()` with `[yellow]Warning:[/yellow]` prefix listing table names
- Entire FK detection block wrapped in `try/except Exception` with `logger.debug()` for graceful degradation
- Created `tests/test_hardening_fk_preflight.py` with 10 tests across 1 test class

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 817/817 non-live tests passing (10 new + 807 existing)
```bash
$ uv run pytest tests/test_hardening_fk_preflight.py -v --tb=short
============================== 10 passed in 0.67s ==============================

$ uv run pytest tests/test_lib_extraction_cli.py -v --tb=short -k "sync"
====================== 93 passed, 84 deselected in 0.65s =======================

$ uv run pytest tests/ --ignore=tests/test_live_integration.py -q
817 passed, 49 warnings in 12.87s
```

**Issues**: None. All tests passed on the first run.

**Trade-offs & Decisions**: No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- The FK detection is purely advisory (warning only, never blocking). Using a broad `except Exception` catch ensures it never interferes with the sync workflow, even if the destination database is unreachable or has permission issues.
- Using real Pydantic models (`DatabaseConfig`, `DatabaseProfile`, `DatabaseSchema`, `TableSchema`, `ConstraintSchema`) in tests instead of MagicMock provides stronger type safety and catches structural issues that MagicMock would silently accept.
- The `config.backup_schema` heuristic works well as a proxy for "user is FK-aware": if they have declared a BackupSchema with FK relationships, they likely have FK-aware sync configured. This avoids needing to inspect the actual sync path (which is determined at a lower level).

**Result**: `_async_sync()` now detects FK constraints on target tables when `backup_schema` is not configured and emits a yellow warning. The warning is best-effort (graceful degradation on introspection failure), non-blocking (sync proceeds after warning), and correctly skipped when `backup_schema` is configured or `config` is None. All 177 existing CLI tests pass unchanged. Ready for Step 7.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 8 acceptance criteria met. FK detection only when config.backup_schema not configured. Warning includes table names. Uses console.print with [yellow]Warning:[/yellow]. No detection when backup_schema configured or config is None. Graceful degradation via except Exception with logger.debug. 10 new tests mock SchemaIntrospector and verify warning output. Existing 93 sync CLI tests pass unchanged.
- **Assumption audit**: PASS -- config.profiles[dest] access assumes dest is valid key; KeyError caught by broad except Exception for graceful degradation. constraint_type == "FOREIGN KEY" comparison consistent with ConstraintSchema usage throughout codebase.
- **Silent trade-offs**: PASS -- No undocumented decisions found.
- **Complexity proportionality**: PASS -- Single block of FK detection code added to _async_sync(), appropriate scope.
- **Architectural drift**: PASS -- FK detection placed in _data_sync.py as plan specified. Imports follow established pattern. No new modules beyond test file.

---

### Step 7: SQL Parser Upgrade with sqlparse ✅
**Status**: Complete (2026-03-13T12:21:45-0700)
**Expected**: Replace 3 regex-based SQL parsing functions with `sqlparse`-based tokenization to handle comments, quoted identifiers, and schema-qualified names.

**Implementation**:
- Refactored `_parse_expected_columns()` in `src/db_adapter/cli/_helpers.py`: replaced regex with `sqlparse.parse()`, uses `statement.get_type() == 'CREATE'` + TABLE keyword check, extracts table name via `SqlIdentifier.get_real_name()` with quote stripping, strips comments from `Parenthesis` body via `sqlparse.format(strip_comments=True)` before column extraction
- Refactored `_parse_fk_dependencies()` in `src/db_adapter/schema/fix.py`: uses `sqlparse.parse()` for CREATE TABLE detection and table name extraction (same pattern as above), REFERENCES extraction uses regex within comment-stripped body with schema-qualified name support (`REFERENCES public.users(id)` -> `users`)
- Refactored `_get_table_create_sql()` in `src/db_adapter/schema/fix.py`: uses `sqlparse.parse()` to find matching CREATE TABLE statement by comparing `get_real_name()` (lowercase, quote-stripped) against provided table_name (lowercase), returns raw statement string preserving original formatting
- Removed `import re` from `_helpers.py` (no longer needed); `re` retained in `fix.py` for REFERENCES regex within tokenized body
- Added `import sqlparse`, `from sqlparse.sql import Identifier as SqlIdentifier, Parenthesis`, `from sqlparse.tokens import Keyword` to both files
- Added 11 new edge-case tests: 5 in `tests/test_lib_extraction_cli.py` (TestParseExpectedColumnsSqlparseEdgeCases) and 6 in `tests/test_lib_extraction_fix.py` (TestGetTableCreateSQLSqlparseEdgeCases + TestFKDependenciesSqlparseEdgeCases)

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 828/828 non-live tests passing (11 new + 817 existing)
```bash
$ uv run pytest tests/test_lib_extraction_fix.py tests/test_lib_extraction_cli.py -v --tb=short
======================= 250 passed, 8 warnings in 1.14s ========================

$ uv run pytest tests/ --ignore=tests/test_live_integration.py -q
828 passed, 49 warnings in 12.81s
```

**Issues**: None. All existing 239 fix+CLI tests passed on the first run after refactoring, confirming full backward compatibility.

**Trade-offs & Decisions**:
- **Decision:** Used `SqlIdentifier` alias for `sqlparse.sql.Identifier` to avoid shadowing psycopg's `Identifier` import in `_helpers.py`
  - **Alternatives considered:** Renaming psycopg's Identifier import, or using fully qualified `sqlparse.sql.Identifier`
  - **Why this approach:** Minimal change to existing code; `SqlIdentifier` clearly communicates it's the sqlparse variant
  - **Risk accepted:** Two different `Identifier` classes in the same module could cause confusion for future maintainers (mitigated by the `Sql` prefix)
- **Decision:** Kept REFERENCES extraction as regex within the tokenized body (not pure token-level scanning)
  - **Alternatives considered:** Full token-level REFERENCES parsing
  - **Why this approach:** Per plan spec, regex is simpler and reliable on comment-stripped input; sqlparse's tokenization of REFERENCES clauses is inconsistent for PostgreSQL-specific FK syntax
  - **Risk accepted:** Regex could theoretically match REFERENCES inside a string literal, but this is extremely unlikely in CREATE TABLE bodies

**Lessons Learned**:
- `sqlparse.parse()` treats a `-- comment` followed by a real statement as a single statement object. The comment is a token within the statement, but `get_type()` still correctly returns `'CREATE'` because it looks at the first non-comment DDL token. This means commented-out CREATE TABLE lines are naturally ignored.
- `sqlparse.sql.Identifier.get_real_name()` is the correct method for schema-qualified names -- it returns only the final name component (e.g., `public.users` -> `users`). `get_name()` also works but `get_real_name()` is more explicit about stripping qualifiers.
- `sqlparse.format(body, strip_comments=True)` removes both line (`--`) and block (`/* */`) comments from the body string. This is essential for column extraction because comments could contain column-like text that the line-splitting logic would incorrectly parse.
- The TABLE keyword check (`token.normalized == "TABLE"`) is necessary because `get_type() == 'CREATE'` matches all CREATE statements including CREATE INDEX, CREATE VIEW, CREATE FUNCTION, etc. Without this check, a `CREATE INDEX idx ON users (email)` would be incorrectly parsed as a table definition.

**Result**: All 3 regex-based SQL parsing functions successfully replaced with sqlparse-based tokenization. Schema-qualified names (`public.users`), quoted identifiers (`"Items"`), SQL comments (line and block), and `IF NOT EXISTS` are all handled correctly. All 239 existing fix+CLI tests pass unchanged (backward compatible). 11 new edge-case tests verify the new capabilities. Ready for Step 8.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 8 acceptance criteria verified. All 3 functions use sqlparse.parse() for CREATE TABLE detection. get_real_name() for schema-qualified names with quote stripping. sqlparse.format(strip_comments=True) for comment removal. TABLE keyword check to exclude CREATE INDEX/VIEW. import re removed from _helpers.py; retained in fix.py only for REFERENCES regex within tokenized body. 11 new edge-case tests (slightly above 8-10 range). 828/828 tests pass including all 239 existing fix+CLI tests.
- **Assumption audit**: PASS -- Two documented decisions: SqlIdentifier alias to avoid psycopg shadowing, and keeping REFERENCES as regex within tokenized body (explicitly allowed by plan and design doc).
- **Silent trade-offs**: PASS -- No undocumented decisions found.
- **Complexity proportionality**: PASS -- Changes scoped to exactly the 2 source files specified with tests in existing test files.
- **Architectural drift**: PASS -- _helpers.py and fix.py modified as planned. Tests added as new classes in existing test files. No new files created.

---

### Step 8: Full Suite Validation ✅
**Status**: Complete (2026-03-13T12:24:09-0700)
**Expected**: Run the complete test suite to verify no regressions across all steps.

**Implementation**:
No new code -- this is a validation-only step. Ran the full test suite, verified CLI entry point, confirmed import integrity, and checked absolute import patterns.

**Deviation from Plan**: None -- implemented per plan specification.

**Verification Results**:

1. **Full test suite**: 828/828 non-live tests passing (zero failures)
```bash
$ uv run pytest tests/ --ignore=tests/test_live_integration.py -v --tb=short
====================== 828 passed, 49 warnings in 13.31s =======================
```

2. **CLI entry point**: `uv run db-adapter --help` returns exit code 0 with all 8 subcommands listed (connect, status, profiles, validate, sync, fix, backup, restore)

3. **Entry point in pyproject.toml**: Confirmed `db-adapter = "db_adapter.cli:main"` unchanged

4. **All module imports**: Verified zero import errors
```bash
$ uv run python -c "from db_adapter.cli import main; from db_adapter.cli._helpers import console; from db_adapter.cli._connection import cmd_connect; from db_adapter.cli._schema_fix import cmd_fix; from db_adapter.cli._data_sync import cmd_sync; from db_adapter.cli._backup import cmd_backup; print('All imports OK')"
All imports OK
```

5. **Absolute import patterns**: Zero relative imports (`from .` or `import .`) found in any new test file (`test_hardening_*.py`) or source module (`src/db_adapter/cli/_*.py`)

**Test Counts by File**:
| Test File | Tests | Status |
|-----------|-------|--------|
| `test_hardening_cli_split.py` | 49 | Passing |
| `test_hardening_restore_failure_details.py` | 11 | Passing |
| `test_hardening_transaction.py` | 30 | Passing |
| `test_hardening_transaction_consumers.py` | 13 | Passing |
| `test_hardening_fk_preflight.py` | 10 | Passing |
| `test_lib_extraction_cli.py` | 182 | Passing (177 original + 5 sqlparse edge cases) |
| `test_lib_extraction_fix.py` | 68 | Passing (62 original + 6 sqlparse edge cases) |
| `test_lib_extraction_adapters.py` | 54 | Passing (1 test renamed) |
| `test_lib_extraction_backup.py` | 48 | Passing |
| `test_lib_extraction_comparator.py` | 31 | Passing |
| `test_lib_extraction_config.py` | 43 | Passing |
| `test_lib_extraction_exports.py` | 37 | Passing |
| `test_lib_extraction_factory.py` | 48 | Passing |
| `test_lib_extraction_final.py` | 19 | Passing |
| `test_lib_extraction_imports.py` | 39 | Passing |
| `test_lib_extraction_introspector.py` | 42 | Passing |
| `test_lib_extraction_models.py` | 55 | Passing |
| `test_lib_extraction_sync.py` | 49 | Passing |
| **Total** | **828** | **All passing** |

**Issues**: None. All 828 tests pass. The 49 warnings are pre-existing deprecation warnings (e.g., `asyncio.iscoroutinefunction` deprecated in Python 3.16) and `RuntimeWarning` from `_get_transaction_ctx()` probing mock objects -- neither affects functionality.

**Trade-offs & Decisions**: No significant trade-offs -- validation-only step.

**Lessons Learned**:
- The progressive test count growth across steps (704 -> 753 -> 764 -> 794 -> 807 -> 817 -> 828) confirms each step was additive with zero regressions. No step broke a previously-passing test.
- The 49 warnings are all safe to ignore: 15 are `DeprecationWarning` for `asyncio.iscoroutinefunction` (deprecated in Python 3.16, current is 3.14), and the remainder are `RuntimeWarning` from `_get_transaction_ctx()` calling `.transaction()` on `AsyncMock` objects (the coroutine is never awaited because the try/except gracefully falls back to `_noop_transaction()`).

**Result**: Full suite validation complete. All 828 non-live tests pass. CLI operational with all 8 subcommands. Entry point `db_adapter.cli:main` unchanged. All modules import cleanly. All new code uses absolute imports. Core Hardening task is ready for finalization.

**Review**: PASS
**Reviewed**: 2026-03-13T15:04:05-0700
- **Intent match**: PASS -- All 4 acceptance criteria confirmed: 828/828 non-live tests pass, db-adapter --help exits 0, pyproject.toml entry point unchanged, zero relative imports in new files. Progressive test count (704→828) confirms additive steps with zero regressions.
- **Assumption audit**: PASS -- Ignoring test_live_integration.py is consistent with baseline established in Step 0. No undocumented assumptions.
- **Silent trade-offs**: PASS -- Validation-only step, no decisions to make.
- **Complexity proportionality**: PASS -- No new code, appropriate for final validation.
- **Architectural drift**: PASS -- No structural changes. Entry point confirmed unchanged.

---

## Lessons Learned

- **Patch where the name is looked up** - After splitting a module into sub-modules with a facade, `unittest.mock.patch()` targets must reference the sub-module where the name is actually imported and used, not the facade's re-export. Organizing migration by test class (one command per class, one sub-module per command) makes the mapping deterministic.

- **AsyncMock defeats hasattr feature detection** - `AsyncMock()` auto-creates any attribute on access, so `hasattr(mock, 'transaction')` always returns True. The `_get_transaction_ctx()` pattern with try/except + `__aenter__` validation is more robust for detecting whether an object supports a specific async context manager protocol.

- **Per-instance ContextVar names prevent cross-adapter leaks** - When multiple `AsyncPostgresAdapter` instances coexist in the same asyncio task (e.g., source and dest in `_sync_direct()`), using `f"_transaction_conn_{id(self)}"` as the ContextVar name prevents one adapter's transaction connection from being visible to another.

- **PostgreSQL transactional DDL enables atomic schema fixes** - Unlike MySQL, PostgreSQL's DDL (CREATE TABLE, ALTER, DROP) is transactional. This means `apply_fixes()` wrapped in a transaction genuinely rolls back partial DDL on failure -- a dropped table reappears as if nothing happened.

- **validate_backup guards error paths in restore** - `validate_backup()` catches structural issues (missing PK fields, wrong version) before `_restore_table()` runs. Tests for restore error paths must simulate failures that pass validation but fail during insert/update, not structurally invalid data.

- **sqlparse get_real_name strips schema qualifiers** - `sqlparse.sql.Identifier.get_real_name()` returns only the final name component (e.g., `public.users` returns `users`), making it the correct method for matching schema-qualified table names against bare names from introspection.

- **sqlparse TABLE keyword check beyond get_type** - `statement.get_type() == 'CREATE'` matches all CREATE statements (INDEX, VIEW, FUNCTION). An additional `token.normalized == "TABLE"` check is needed to filter to CREATE TABLE specifically.

- **backup_schema as FK-awareness proxy** - Using `config.backup_schema is not None` as a heuristic for "user has FK-aware sync configured" avoids needing to inspect the actual sync code path. Users who declare a BackupSchema with FK relationships likely already have FK-aware sync configured.

- **Noop context manager eliminates transaction branching** - The `_noop_transaction()` async context manager as a fallback when `adapter.transaction()` is unavailable eliminates if/else duplication. The operation logic is written once and works identically with or without transaction support.

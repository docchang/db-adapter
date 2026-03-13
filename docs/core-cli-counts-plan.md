# core-cli-counts Plan

> **Design**: See `docs/core-cli-counts-design.md` for analysis and approach.
>
> **Track Progress**: See `docs/core-cli-counts-results.md` for implementation status, test results, and issues.

## Overview

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-11T11:45:25-0700 |
| **Name** | Add Table Row Counts to CLI |
| **Type** | Feature |
| **Environment** | Python -- see `references/python-guide.md` |
| **Proves** | CLI provides immediate data visibility after connect and status commands |
| **Production-Grade Because** | Uses real DB queries, graceful degradation on failure, proper SQL identifier quoting, alphabetical sorting |
| **Risk Profile** | Standard |
| **Risk Justification** | Additive display-only feature; no changes to data flow, adapters, or schema logic |

---

## Deliverables

Concrete capabilities this task delivers:

- `_get_table_row_counts()` async helper that queries all public base tables and returns `dict[str, int]`
- `_print_table_counts()` Rich table renderer for row counts display
- `db-adapter connect` shows "Table Data" table with row counts after successful connection
- `db-adapter status` shows "Table Data" table with row counts (async conversion with graceful degradation)
- Updated documentation (CLAUDE.md, README.md, CLI docstrings/help text)

---

## Prerequisites

Complete these BEFORE starting implementation steps.

### 1. Identify Affected Tests

**Why Needed**: Run only affected tests during implementation (not full suite)

**Affected test files**:
- `tests/test_lib_extraction_cli.py` -- CLI command parsing, `_async_connect()`, `cmd_status()` tests
- `tests/test_live_integration.py` -- Live integration tests for `connect` and `status` commands

**Baseline verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
# Expected: All pass (establishes baseline)
```

### 2. Verify psycopg Import Availability

**Why Needed**: The row count helper uses `psycopg.AsyncConnection` and `psycopg.sql.Identifier` directly. These must be importable.

**Verification** (inline OK for prerequisites):
```bash
cd /Users/docchang/Development/db-adapter && uv run python -c "from psycopg import AsyncConnection; from psycopg.sql import SQL, Identifier; print('psycopg imports OK')"
# Expected: "psycopg imports OK"
```

### 3. Verify resolve_url Import Path

**Why Needed**: `resolve_url` from `db_adapter.factory` is needed to get the database URL from a profile but is not currently imported in `cli/__init__.py`.

**Verification** (inline OK for prerequisites):
```bash
cd /Users/docchang/Development/db-adapter && uv run python -c "from db_adapter.factory import resolve_url; print('resolve_url importable')"
# Expected: "resolve_url importable"
```

---

## Success Criteria

From Design doc (refined with verification commands):

- [ ] `db-adapter connect` shows a "Table Data" table with row counts for all tables after successful connection
- [ ] `db-adapter connect` does NOT show counts when connection or validation fails
- [ ] `db-adapter status` shows a "Table Data" table with row counts when DB is reachable
- [ ] `db-adapter status` shows just the connection status table (no error) when DB is unreachable
- [ ] `db-adapter status` still returns 0 in all cases (informational command)
- [ ] Row counts table is sorted alphabetically by table name
- [ ] All existing tests pass (no regressions)
- [ ] New tests added for row count helper, display helper, connect integration, and status integration

---

## Architecture

### File Structure
```
src/db_adapter/
├── cli/
│   └── __init__.py              # Modified: add helpers, update connect/status
├── factory.py                   # Unchanged (resolve_url already exists)
└── schema/
    └── introspector.py          # Unchanged (reference for EXCLUDED_TABLES_DEFAULT)
tests/
├── test_lib_extraction_cli.py   # Modified: new tests for counts
└── test_live_integration.py     # Modified: new live tests for counts
CLAUDE.md                        # Modified: update CLI docs
README.md                        # Modified: update CLI reference
```

### Design Principles
1. **Graceful Degradation**: Row counts are best-effort; failure never crashes the command
2. **SQL Safety**: Table names quoted with `psycopg.sql.Identifier` (not f-strings)
3. **Shared Helpers**: Both commands reuse the same query and display functions
4. **Strong Typing**: All functions fully typed with return types and parameter types

---

## Implementation Steps

**Approach**: Build helpers first (query + display), then integrate into `connect`, then convert `status` to async and integrate, then update docs. Each step builds on the previous.

> This plan is a contract between the executor (builder) and reviewer (validator). Steps specify **what** to build and **how** to verify -- the executor writes the implementation.

> **Sub-steps**: When a step is split during review, it becomes sub-steps (e.g., Step 8 -> Steps 8a, 8b, 8c).
> Sub-steps are full steps with letter suffixes. Each has the same sections as a regular step.
> Sub-steps execute in order (8a -> 8b -> 8c) before proceeding to the next whole number.
> Sub-steps are limited to one level -- no 8a-i, 8a-ii.

### Step 0: Add resolve_url Import

**Goal**: Add the `resolve_url` import to `cli/__init__.py` so it is available for subsequent steps.

- [ ] Add `resolve_url` to the `from db_adapter.factory import (...)` block in `cli/__init__.py`

**Code**:
```bash
# Add resolve_url to the existing factory import block in cli/__init__.py
# The import block at line 52-58 currently imports:
#   connect_and_validate, get_adapter, read_profile_lock, get_active_profile_name, ProfileNotFoundError
# Add resolve_url to this block
```

**Verification** (inline OK for Step 0):
```bash
cd /Users/docchang/Development/db-adapter && uv run python -c "from db_adapter.cli import console; print('CLI module loads OK')"
# Expected: "CLI module loads OK"
```

**Output**: `resolve_url` available for use in CLI helpers

---

### Step 1: Row Count Query Helper

**Goal**: Implement `_get_table_row_counts()` async helper that queries all public base tables and returns row counts.

- [ ] Add `_get_table_row_counts()` to `cli/__init__.py`
- [ ] Add psycopg imports (`AsyncConnection`, `sql.SQL`, `sql.Identifier`) to `cli/__init__.py`
- [ ] Write tests for the helper

**Specification**:
- File to modify: `src/db_adapter/cli/__init__.py`
- Add imports at top: `from psycopg import AsyncConnection` and `from psycopg.sql import SQL, Identifier`
- Function signature: `async def _get_table_row_counts(database_url: str) -> dict[str, int]`
- Opens a raw `psycopg.AsyncConnection` using `await AsyncConnection.connect(database_url)`
- Queries `information_schema.tables` for table names where `table_schema = 'public'` and `table_type = 'BASE TABLE'`
- Excludes system tables: `schema_migrations`, `pg_stat_statements`, `spatial_ref_sys` (same as `SchemaIntrospector.EXCLUDED_TABLES_DEFAULT`)
- Define the excluded set as a module-level constant `_EXCLUDED_TABLES` (mirrors introspector but keeps CLI independent)
- For each table, runs `SELECT COUNT(*) FROM <table>` using `sql.SQL("SELECT COUNT(*) FROM {}").format(Identifier(table_name))` for safe quoting
- Returns dict mapping table names to counts, sorted alphabetically by key
- Wraps entire function body in try/except: on any exception, returns empty dict `{}`
- Connection is closed in a `finally` block or via `async with`
- Tests must verify: successful count retrieval (mock connection), connection failure returns `{}`, system tables excluded from results

**Acceptance Criteria**:
- `_get_table_row_counts()` returns `dict[str, int]` with alphabetically sorted keys on success
- Returns empty `{}` on connection failure (no exception raised)
- Excludes `schema_migrations`, `pg_stat_statements`, `spatial_ref_sys` from results
- Uses `psycopg.sql.Identifier` for table name quoting (not f-strings)
- Tests mock the psycopg connection to verify query logic and error handling

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short -k "row_count"
```

**Output**: New tests passing for `_get_table_row_counts()`

---

### Step 2: Display Helper for Row Counts Table

**Goal**: Implement `_print_table_counts()` that renders a Rich table from the row counts dict.

- [ ] Add `_print_table_counts()` to `cli/__init__.py`
- [ ] Write tests for the display helper

**Specification**:
- File to modify: `src/db_adapter/cli/__init__.py`
- Function signature: `def _print_table_counts(counts: dict[str, int]) -> None`
- If `counts` is empty, return immediately (no output)
- Create a `rich.table.Table` with title `"Table Data"`
- Two columns: `"Table"` (left-aligned) and `"Rows"` (right-aligned via `justify="right"`)
- Add rows sorted alphabetically by table name (use `sorted(counts.items())`)
- Row count values formatted with `f"{count:,}"` for thousand separators
- Print the table using the module-level `console` object
- Tests must verify: populated dict renders a table (capture console output), empty dict produces no output, rows are sorted alphabetically, "Rows" column is right-justified

**Acceptance Criteria**:
- `_print_table_counts({})` produces no console output
- `_print_table_counts({"b": 10, "a": 5})` prints a Rich table with "a" row before "b" row
- Table title is "Table Data"
- Rows column uses right justification
- Row counts include comma formatting for large numbers

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short -k "table_counts"
```

**Output**: New tests passing for `_print_table_counts()`

---

### Step 3: Integrate Row Counts into Connect Command

**Goal**: After successful `connect`, query and display table row counts.

- [ ] Update `_async_connect()` in `cli/__init__.py` to call helpers after success
- [ ] Write tests for connect integration

**Specification**:
- File to modify: `src/db_adapter/cli/__init__.py`
- In `_async_connect()`, after the schema validation output (around line 322-332) and before the profile switch notice (line 335):
  - Guard: only attempt if `config is not None` and `result.profile_name is not None` and `result.profile_name in config.profiles`
  - Resolve URL: `url = resolve_url(config.profiles[result.profile_name])`
  - Get counts: `counts = await _get_table_row_counts(url)`
  - Display: if `counts` is non-empty, print a blank line then call `_print_table_counts(counts)`
- No counts on failure path (when `result.success is False`, the function already returns 1 before reaching this code)
- Tests must verify: successful connect calls `_get_table_row_counts` and `_print_table_counts`, failed connect does not call row counts, connect with `config=None` skips row counts gracefully

**Acceptance Criteria**:
- Successful connect (result.success=True) with config available calls `_get_table_row_counts()` with the resolved URL
- Successful connect displays row counts table when counts are non-empty
- Successful connect with empty counts (DB has no tables) does not print Table Data section
- Failed connect (result.success=False) does not attempt row counts
- Connect with missing config (config=None) does not attempt row counts (no crash)
- Existing connect tests continue to pass (may need mock for `_get_table_row_counts`)

**Trade-offs**:
- **Mocking strategy for existing tests**: Prefer patching `_get_table_row_counts` to return `{}` in existing connect tests rather than modifying their assertions, because this preserves the existing test intent while preventing test failures from the new code path. Alternative: update all existing connect tests to expect new output.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short -k "connect"
```

**Output**: All connect tests passing (existing + new)

---

### Step 4: Convert Status to Async and Add Row Counts

**Goal**: Make `cmd_status` async-capable and display table row counts when DB is reachable.

- [ ] Create `_async_status()` async handler
- [ ] Modify `cmd_status()` to call `asyncio.run(_async_status(args))`
- [ ] Add row counts query and display to `_async_status()`
- [ ] Write tests for status integration

**Specification**:
- File to modify: `src/db_adapter/cli/__init__.py`
- Create `async def _async_status(args: argparse.Namespace) -> int` containing the existing `cmd_status` logic
- Change `cmd_status` to: `return asyncio.run(_async_status(args))`
- In `_async_status`, after printing the status table (after the `console.print(table)` call):
  - Guard: only attempt if `profile is not None` and `config` was loaded successfully and `profile in config.profiles`
  - Resolve URL: `url = resolve_url(config.profiles[profile])`
  - Get counts: `counts = await _get_table_row_counts(url)`
  - Display: if `counts` is non-empty, print a blank line then call `_print_table_counts(counts)`
- Graceful degradation: if DB is unreachable, `_get_table_row_counts()` returns `{}` and status shows just the local info (no error message)
- `_async_status` must still return `0` in all cases
- Update `cmd_status` docstring: remove "Reads only local files" and "no database calls" language; note it queries the database for row counts with graceful degradation
- Update section comment at line 943: change from "cmd_status, cmd_profiles read local files only" to reflect that only `cmd_profiles` is local-only
- Initialize `config = None` before the try block so the guard condition `config is not None` works when `load_db_config()` raises `FileNotFoundError`
- Update `test_cmd_status_is_sync` in `test_lib_extraction_cli.py`: invert the assertion to `"asyncio.run" in source` and rename to `test_cmd_status_delegates_to_async` (or similar). Add a corresponding test that `_async_status` is an async coroutine function.
- Tests must verify: status with reachable DB shows row counts, status with unreachable DB returns 0 without error, status with no profile still returns 0, existing status tests continue to pass

**Acceptance Criteria**:
- `cmd_status` delegates to `asyncio.run(_async_status(args))`
- `_async_status` returns `0` in all cases (reachable DB, unreachable DB, no profile)
- When DB is reachable and profile exists, row counts table appears after the Connection Status table
- When DB is unreachable, only the Connection Status table appears (no error output)
- When no profile exists (no `.db-profile`), output unchanged from current behavior
- `cmd_status` docstring updated to reflect async DB query behavior
- Section comment updated to reflect `cmd_status` is no longer local-only
- `test_cmd_status_is_sync` replaced with `test_cmd_status_delegates_to_async` asserting `asyncio.run` is present
- Existing status tests pass (may need mock updates for async wrapper)

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short -k "status"
```

**Output**: All status tests passing (existing + new)

---

### Step 5: Update Documentation

**Goal**: Update CLAUDE.md, README.md, and CLI help text to reflect the new row counts feature.

- [ ] Update CLAUDE.md CLI command descriptions
- [ ] Update README.md CLI Reference section
- [ ] Update `status` subparser help text in `build_parser()`
- [ ] Update module docstring in `cli/__init__.py`

**Specification**:
- Files to modify: `CLAUDE.md`, `README.md`, `src/db_adapter/cli/__init__.py`
- `CLAUDE.md`: In the CLI Commands section, update `status` description from "Show current profile (local files only)" to note it now queries DB for row counts. Add note to `connect` that it shows table row counts after successful connection.
- `README.md`: Update the CLI Reference section similarly. Update `status` comment from "Show current profile" to reflect row counts. Add note about `connect` showing row counts.
- `cli/__init__.py` module docstring: Update the `status` line from "Show current connection status" to reflect it now queries the database for row counts
- `cli/__init__.py` `build_parser()`: Update the `status` subparser `help` kwarg to mention row counts (current text is "Show current connection status" -- update to reflect new behavior)
- No new tests needed for documentation changes; run full affected test suite to confirm no regressions

**Acceptance Criteria**:
- CLAUDE.md reflects that `connect` shows row counts and `status` queries DB with graceful degradation
- README.md reflects the same
- Module docstring in `cli/__init__.py` updated for `status` command description
- `status` subparser help text does not claim "local files only"
- All existing tests still pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_imports.py -v --tb=short
```

**Output**: All affected tests passing

---

### Step 6: Full Test Suite Validation

**Goal**: Run the full test suite and verify no regressions across all modules.

- [ ] Run full test suite
- [ ] Verify all tests pass

**Specification**:
- Run the complete test suite to confirm no regressions from the new feature
- If any failures, diagnose and fix before marking complete
- Tests must verify: all 700+ existing tests pass, all new tests pass

**Acceptance Criteria**:
- Full test suite passes with zero failures
- New tests are included in the count
- No warnings related to the new code

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest -v --tb=short
```

**Output**: Full suite passing

---

## Test Summary

### Affected Tests (Run These)

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `tests/test_lib_extraction_cli.py` | ~50+ | CLI command parsing, connect, status |
| `tests/test_lib_extraction_imports.py` | ~10 | Import patterns (may be affected by new imports) |
| `tests/test_live_integration.py` | ~30+ | Live CLI tests against real databases |

**Affected tests: ~90+ tests**

**Full suite**: ~704 tests (run at Step 6 as final validation)

---

## What "Done" Looks Like

```bash
# 1. Affected tests pass
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_imports.py -v --tb=short
# Expected: All pass

# 2. Full suite passes
cd /Users/docchang/Development/db-adapter && uv run pytest -v --tb=short
# Expected: All pass

# 3. Connect shows row counts (live test)
cd /Users/docchang/Development/db-adapter && DB_PROFILE=full uv run db-adapter connect
# Expected: Shows "Table Data" table with row counts after "Schema validation: PASSED"

# 4. Status shows row counts (live test)
cd /Users/docchang/Development/db-adapter && uv run db-adapter status
# Expected: Shows "Table Data" table after "Connection Status" table
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/db_adapter/cli/__init__.py` | Modify | Add helpers, update connect/status, update docstrings |
| `tests/test_lib_extraction_cli.py` | Modify | Add tests for row count helper, display helper, connect + status integration |
| `tests/test_live_integration.py` | Modify | Add live tests for connect and status row counts |
| `CLAUDE.md` | Modify | Update CLI command descriptions |
| `README.md` | Modify | Update CLI Reference section |

---

## Dependencies

No new dependencies required. `psycopg` is already a dependency (used by `schema/introspector.py`). `rich` is already a dependency (used by `cli/__init__.py`).

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `SELECT COUNT(*)` slow on large tables | LOW | Acceptable for dev tooling; typical databases have < 20 tables |
| Status command now requires DB access | MED | Graceful degradation -- shows local status without counts if DB unreachable |
| Existing `cmd_status` tests assume sync | MED | Update tests to handle `asyncio.run()` wrapper; mock `_get_table_row_counts` |
| New psycopg imports in CLI module | LOW | psycopg already a project dependency; import only at module level |

---

## Next Steps After Completion

1. Verify affected tests pass (~90+ tests)
2. Verify live CLI commands show row counts (`connect` and `status`)
3. Run full suite (~704+ tests)
4. Proceed to next task as determined by project priorities

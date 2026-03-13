# core-cli-counts Results

## Summary
| Attribute | Value |
|-----------|-------|
| **Status** | ✅ Complete |
| **Started** | 2026-03-11T17:01:34-0700 |
| **Completed** | 2026-03-11T17:17:32-0700 |
| **Reviewed** | 2026-03-11T17:26:45-0700 |
| **Proves** | CLI provides immediate data visibility after connect and status commands |

## Diagram

```
┌──────────────────────────────────┐
│          Cli Counts              │
│            COUNTS                │
│          ✅ Complete             │
│                                  │
│ Capabilities                     │
│   • Row counts on connect        │
│   • Row counts on status         │
│   • Graceful degradation         │
│                                  │
│ Architecture                     │
│   • Raw psycopg connection       │
│   • SQL Identifier quoting       │
│   • Shared query + display       │
│   • Status async conversion      │
│                                  │
│ Display                          │
│   • Rich "Table Data" table      │
│   • Alphabetical sorting         │
│   • Comma-formatted counts       │
└──────────────────────────────────┘
```

---

## Goal
Add table row counts to `db-adapter connect` and `db-adapter status` CLI commands, providing immediate data visibility after connection. Uses real DB queries with graceful degradation on failure.

---

## Success Criteria
From `docs/core-cli-counts-plan.md`:

- [x] `db-adapter connect` shows a "Table Data" table with row counts for all tables after successful connection
- [x] `db-adapter connect` does NOT show counts when connection or validation fails
- [x] `db-adapter status` shows a "Table Data" table with row counts when DB is reachable
- [x] `db-adapter status` shows just the connection status table (no error) when DB is unreachable
- [x] `db-adapter status` still returns 0 in all cases (informational command)
- [x] Row counts table is sorted alphabetically by table name
- [x] All existing tests pass (no regressions)
- [x] New tests added for row count helper, display helper, connect integration, and status integration

**ALL SUCCESS CRITERIA MET** ✅

---

## Prerequisites Completed
- [x] Affected tests identified: `test_lib_extraction_cli.py` (150 tests), `test_lib_extraction_imports.py` (32 tests), `test_live_integration.py`
- [x] Baseline tests passing: 150 CLI tests, 32 import tests
- [x] psycopg imports verified: `AsyncConnection`, `sql.SQL`, `sql.Identifier` all importable
- [x] `resolve_url` import path verified: importable from `db_adapter.factory`

---

## Implementation Progress

### Step 0: Add resolve_url Import ✅
**Status**: Complete (2026-03-11T17:01:34-0700)
**Expected**: Add `resolve_url` to the factory import block in `cli/__init__.py`

**Implementation**:
- ✅ Added `resolve_url` to `from db_adapter.factory import (...)` block in `cli/__init__.py`

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: ✅ 182/182 tests passing (150 CLI + 32 imports)
```bash
# CLI tests
tests/test_lib_extraction_cli.py: 150 passed in 0.73s

# Import tests
tests/test_lib_extraction_imports.py: 32 passed in 0.68s
```

**Inline Verification**:
```bash
$ uv run python -c "from db_adapter.cli import console; print('CLI module loads OK')"
CLI module loads OK
```

**Issues**: None

**Trade-offs & Decisions**: No significant trade-offs -- straightforward import addition per plan.

**Lessons Learned**:
- The factory import block already had 5 imports; adding `resolve_url` was a clean one-line addition
- Alphabetical ordering maintained within the import block (resolve_url after read_profile_lock)

**Result**: `resolve_url` is now available in `cli/__init__.py` for use in subsequent steps (row count query helper).

**Review**: PASS
**Reviewed**: 2026-03-11T17:25:09-0700
- **Intent match**: PASS -- Plan specifies adding `resolve_url` to the factory import block. Working tree confirms it's present. 182/182 tests pass.
- **Assumption audit**: PASS -- Exactly one import added. No assumptions beyond plan specification.
- **Architectural drift**: PASS -- Modifies only `cli/__init__.py` as specified. Follows established absolute import pattern.

---

### Step 1: Row Count Query Helper ✅
**Status**: Complete (2026-03-11T17:03:17-0700)
**Expected**: Implement `_get_table_row_counts()` async helper that queries all public base tables and returns row counts

**Implementation**:
- ✅ Added psycopg imports (`AsyncConnection`, `sql.SQL`, `sql.Identifier`) to `cli/__init__.py`
- ✅ Added `_EXCLUDED_TABLES` module-level constant mirroring `SchemaIntrospector.EXCLUDED_TABLES_DEFAULT`
- ✅ Implemented `async def _get_table_row_counts(database_url: str) -> dict[str, int]` with full docstring
- ✅ Uses `async with await AsyncConnection.connect(database_url)` for connection management
- ✅ Queries `information_schema.tables` for public base tables
- ✅ Excludes system tables via `_EXCLUDED_TABLES` set
- ✅ Uses `SQL("SELECT COUNT(*) FROM {}").format(Identifier(table_name))` for safe quoting
- ✅ Returns alphabetically sorted dict on success, empty `{}` on any exception
- ✅ 8 new tests covering success, sorting, connection failure, query error, system table exclusion, empty DB, async verification, and SQL identifier usage

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: ✅ 190/190 tests passing (158 CLI + 32 imports)
```bash
# New tests (8/8 passing)
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_successful_row_count_retrieval PASSED
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_result_sorted_alphabetically PASSED
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_connection_failure_returns_empty_dict PASSED
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_query_error_returns_empty_dict PASSED
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_excludes_system_tables PASSED
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_empty_database_returns_empty_dict PASSED
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_get_table_row_counts_is_async PASSED
tests/test_lib_extraction_cli.py::TestGetTableRowCounts::test_uses_sql_identifier_not_fstrings PASSED

# Full affected suite
tests/test_lib_extraction_cli.py: 158 passed
tests/test_lib_extraction_imports.py: 32 passed
```

**Issues**: None

**Trade-offs & Decisions**: No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- Mocking psycopg's `AsyncConnection.connect` with nested `async with` context managers requires careful layering of `AsyncMock` with `__aenter__`/`__aexit__` methods
- The `_EXCLUDED_TABLES` constant deliberately duplicates the introspector's set rather than importing it, keeping the CLI module independent of schema internals
- Using `dict(sorted(counts.items()))` provides the alphabetical ordering guarantee at the return point

**Result**: `_get_table_row_counts()` is implemented, tested, and ready for integration into `connect` and `status` commands in subsequent steps.

**Review**: PASS
**Reviewed**: 2026-03-11T17:25:09-0700
- **Intent match**: PASS -- All 5 acceptance criteria verified. Sorted keys via `dict(sorted(...))`, empty `{}` on exception, excludes all 3 system tables, uses `SQL/Identifier` quoting, 8 tests mock psycopg connection.
- **Assumption audit**: PASS -- `_EXCLUDED_TABLES` duplication is intentional (documented). `async with` connection management satisfies plan's "finally block or via async with" spec.
- **Architectural drift**: PASS -- Only `cli/__init__.py` and test file modified. Helper is underscore-prefixed, placed at module level. No structural deviations.

---

### Step 2: Display Helper for Row Counts Table ✅
**Status**: Complete (2026-03-11T17:06:39-0700)
**Expected**: Implement `_print_table_counts()` that renders a Rich table from the row counts dict

**Implementation**:
- ✅ Added `_print_table_counts(counts: dict[str, int]) -> None` to `cli/__init__.py` with full docstring
- ✅ Returns immediately with no output when `counts` is empty
- ✅ Creates Rich table with title "Table Data", columns "Table" (left-aligned) and "Rows" (right-justified)
- ✅ Rows sorted alphabetically by table name via `sorted(counts.items())`
- ✅ Row counts formatted with comma separators via `f"{count:,}"`
- ✅ Uses the module-level `console` object for output
- ✅ 6 new tests covering empty dict, populated dict, alphabetical sorting, right justification, comma formatting, and table title

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: ✅ 196/196 tests passing (164 CLI + 32 imports)
```bash
# New tests (6/6 passing)
tests/test_lib_extraction_cli.py::TestPrintTableCounts::test_empty_dict_produces_no_output PASSED
tests/test_lib_extraction_cli.py::TestPrintTableCounts::test_populated_dict_renders_table PASSED
tests/test_lib_extraction_cli.py::TestPrintTableCounts::test_rows_sorted_alphabetically PASSED
tests/test_lib_extraction_cli.py::TestPrintTableCounts::test_rows_column_right_justified PASSED
tests/test_lib_extraction_cli.py::TestPrintTableCounts::test_comma_formatting_for_large_numbers PASSED
tests/test_lib_extraction_cli.py::TestPrintTableCounts::test_table_title_is_table_data PASSED

# Full affected suite
tests/test_lib_extraction_cli.py: 164 passed
tests/test_lib_extraction_imports.py: 32 passed
```

**Issues**: None

**Trade-offs & Decisions**: No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- Rich's `Console` can be redirected to a `StringIO` buffer for test output capture, making it straightforward to verify rendered table content without needing snapshot testing
- Source inspection (`inspect.getsource`) is a clean way to verify structural properties like `justify="right"` without needing to parse Rich's rendered output for alignment
- The `sorted(counts.items())` in the display function is technically redundant with `_get_table_row_counts()` already returning sorted keys, but it makes the function independently correct regardless of input ordering

**Result**: `_print_table_counts()` is implemented, tested, and ready for integration into `connect` and `status` commands in subsequent steps.

**Review**: PASS
**Reviewed**: 2026-03-11T17:25:09-0700
- **Intent match**: PASS -- All 5 acceptance criteria satisfied: empty dict returns immediately, sorted output, title "Table Data", right-justified Rows column, comma formatting. 6 tests cover all criteria.
- **Assumption audit**: PASS -- No assumptions beyond plan. Defensive `sorted()` in display function documented as intentional.
- **Architectural drift**: PASS -- Helper placed alongside `_get_table_row_counts` in CLI module. Uses existing `console` object and `Table` import. No structural deviations.

---

### Step 3: Integrate Row Counts into Connect Command ✅
**Status**: Complete (2026-03-11T17:09:29-0700)
**Expected**: After successful `connect`, query and display table row counts

**Implementation**:
- ✅ Added row counts integration to `_async_connect()` in `cli/__init__.py` after schema validation output and before profile switch notice
- ✅ Guard condition: only attempts row counts when `config is not None`, `result.profile_name is not None`, and `result.profile_name in config.profiles`
- ✅ Resolves URL via `resolve_url(config.profiles[result.profile_name])`
- ✅ Calls `await _get_table_row_counts(url)` and displays via `_print_table_counts(counts)` only when counts are non-empty
- ✅ Prints blank line before table for visual separation
- ✅ No row counts on failure path (function returns 1 before reaching this code)
- ✅ 6 new integration tests covering: successful connect calls helpers, displays table, empty counts skips display, failed connect skips counts, no config skips counts, profile not in config skips counts

**Deviation from Plan**: None -- implemented per plan specification. The plan noted that existing tests may need mocking of `_get_table_row_counts` to return `{}`, but this turned out to be unnecessary. Existing tests either have `config=None` (via `FileNotFoundError`/`Exception`) or have `MagicMock` config objects where `MagicMock.__contains__` returns `False` by default, so the guard condition `result.profile_name in config.profiles` naturally prevents the row counts code from executing.

**Test Results**: ✅ 202/202 tests passing (170 CLI + 32 imports)
```bash
# New tests (6/6 passing)
tests/test_lib_extraction_cli.py::TestConnectRowCountsIntegration::test_successful_connect_calls_get_table_row_counts PASSED
tests/test_lib_extraction_cli.py::TestConnectRowCountsIntegration::test_successful_connect_displays_row_counts PASSED
tests/test_lib_extraction_cli.py::TestConnectRowCountsIntegration::test_successful_connect_empty_counts_skips_display PASSED
tests/test_lib_extraction_cli.py::TestConnectRowCountsIntegration::test_failed_connect_does_not_attempt_row_counts PASSED
tests/test_lib_extraction_cli.py::TestConnectRowCountsIntegration::test_connect_with_no_config_skips_row_counts PASSED
tests/test_lib_extraction_cli.py::TestConnectRowCountsIntegration::test_connect_with_profile_not_in_config_skips_row_counts PASSED

# Full affected suite
tests/test_lib_extraction_cli.py: 170 passed
tests/test_lib_extraction_imports.py: 32 passed
```

**Issues**: None

**Trade-offs & Decisions**:
- **Decision:** Did not add explicit `_get_table_row_counts` mocking to existing connect tests
  - **Alternatives considered:** Patching `_get_table_row_counts` to return `{}` in all existing connect tests as suggested by the plan
  - **Why this approach:** Existing tests naturally bypass the row counts code via the guard condition (`MagicMock.__contains__` returns `False` for `"dev" in mock_config.profiles`). Adding unnecessary mocking would be defensive overhead without value.
  - **Risk accepted:** If future tests create configs with real `profiles` dicts, they will need to mock `_get_table_row_counts` -- but the new `TestConnectRowCountsIntegration` class demonstrates the pattern.

**Lessons Learned**:
- `MagicMock.__contains__` returns `False` by default, so `"key" in mock_obj` is `False` -- this makes guard conditions that use `in` naturally safe with mock configs that don't explicitly set up `profiles` as a real dict
- The guard condition `config is not None and result.profile_name is not None and result.profile_name in config.profiles` provides three layers of protection: no config, no profile name, profile not in config
- Integration tests should mock at the boundary (`_get_table_row_counts`, `resolve_url`) rather than deep internals, making tests robust against implementation changes in the helpers

**Review**: PASS
**Reviewed**: 2026-03-11T17:25:09-0700
- **Intent match**: PASS -- All 6 acceptance criteria satisfied. Guard condition uses three-layer check. Row counts placed after validation output, before profile switch notice. Failed connect returns 1 before reaching row counts. 6 new integration tests verify each criterion.
- **Assumption audit**: PASS -- Deviation from plan's mocking strategy documented with reasoning. Relies on `MagicMock.__contains__` returning `False` — sound reasoning with minimal risk.
- **Architectural drift**: PASS -- Only `cli/__init__.py` and test file modified. Code placed in `_async_connect()` success path as specified. No structural changes.

**Result**: Row counts integration in `_async_connect()` is complete and tested. Successful connects with config and matching profile will display table row counts. All guard conditions protect against edge cases.

---

### Step 4: Convert Status to Async and Add Row Counts ✅
**Status**: Complete (2026-03-11T17:11:27-0700)
**Expected**: Make `cmd_status` async-capable and display table row counts when DB is reachable

**Implementation**:
- ✅ Created `async def _async_status(args: argparse.Namespace) -> int` containing the existing `cmd_status` logic
- ✅ Changed `cmd_status` to delegate via `return asyncio.run(_async_status(args))`
- ✅ Initialized `config = None` before the try block so guard condition works when `load_db_config()` raises `FileNotFoundError`
- ✅ Added row counts after the Connection Status table with guard: `config is not None and profile in config.profiles`
- ✅ Resolves URL via `resolve_url(config.profiles[profile])`, gets counts via `await _get_table_row_counts(url)`, displays via `_print_table_counts(counts)` only when non-empty
- ✅ Updated `cmd_status` docstring: removed "Reads only local files" and "no database calls" language; now describes async DB query with graceful degradation
- ✅ Updated section comment at line 1062: changed from "cmd_status, cmd_profiles read local files only" to "cmd_profiles reads local files only"
- ✅ Replaced `test_cmd_status_is_sync` with `test_cmd_status_delegates_to_async` asserting `asyncio.run` is present
- ✅ Added `test_async_status_is_async` test verifying `_async_status` is an async coroutine function
- ✅ Added 6 new status row counts integration tests in `TestStatusRowCountsIntegration` class

**Deviation from Plan**: None -- implemented per plan specification. The mock config helper needed `mock_profile.provider = "postgres"` and `mock_profile.description = "Test database"` because Rich's `Table.add_row()` cannot render `MagicMock` objects as strings. This is different from the connect integration tests where existing tests use `MagicMock` configs that bypass the status table rendering code path entirely.

**Test Results**: ✅ 209/209 tests passing (177 CLI + 32 imports)
```bash
# Status-specific tests (8/8 passing)
tests/test_lib_extraction_cli.py::TestAsyncWrapping::test_cmd_status_delegates_to_async PASSED
tests/test_lib_extraction_cli.py::TestAsyncWrapping::test_async_status_is_async PASSED
tests/test_lib_extraction_cli.py::TestStatusRowCountsIntegration::test_status_with_reachable_db_shows_row_counts PASSED
tests/test_lib_extraction_cli.py::TestStatusRowCountsIntegration::test_status_with_unreachable_db_returns_zero PASSED
tests/test_lib_extraction_cli.py::TestStatusRowCountsIntegration::test_status_with_no_profile_returns_zero PASSED
tests/test_lib_extraction_cli.py::TestStatusRowCountsIntegration::test_status_with_no_config_returns_zero PASSED
tests/test_lib_extraction_cli.py::TestStatusRowCountsIntegration::test_status_with_profile_not_in_config_skips_row_counts PASSED
tests/test_lib_extraction_cli.py::TestStatusRowCountsIntegration::test_status_empty_counts_skips_print PASSED

# Full affected suite
tests/test_lib_extraction_cli.py: 177 passed
tests/test_lib_extraction_imports.py: 32 passed
```

**Issues**:
- Initial test failure: `MagicMock` attributes on mock profiles are not renderable by Rich's `Table.add_row()`. Fixed by setting `mock_profile.provider = "postgres"` and `mock_profile.description = "Test database"` in the test helper.

**Trade-offs & Decisions**:
- **Decision:** Set string values on mock profile attributes (`provider`, `description`) in status test helper
  - **Alternatives considered:** Mocking `console.print` to prevent Rich rendering, or using a `spec=DatabaseProfile` mock
  - **Why this approach:** Setting explicit string values is the simplest fix and makes the test data explicit. The status command actually renders these values in the Connection Status table, so the mock must provide renderable values.
  - **Risk accepted:** If new profile attributes are added that `_async_status` renders, the mock will need updating.

**Lessons Learned**:
- Status command tests require mock profiles with real string values for `provider` and `description` because Rich's `Table.add_row()` cannot render `MagicMock` objects -- unlike connect tests where the guard conditions prevent reaching the rendering code
- The `config = None` initialization before the try block is essential: without it, a `FileNotFoundError` from `load_db_config()` would leave `config` unbound, causing a `NameError` in the guard condition
- The graceful degradation pattern (try/except returning empty dict in `_get_table_row_counts` + guard conditions in callers) provides two layers of protection: the helper swallows DB errors, and the caller checks for empty results

**Result**: `cmd_status` now delegates to `_async_status()` via `asyncio.run()`. When a profile is validated and config is available, it queries the database for table row counts and displays them. Graceful degradation ensures status always returns 0 regardless of DB reachability.

**Review**: PASS
**Reviewed**: 2026-03-11T17:25:09-0700
- **Intent match**: PASS -- All 8 acceptance criteria satisfied. `cmd_status` delegates to `asyncio.run(_async_status(args))`. Returns 0 in all cases. Row counts after Connection Status table with guard. Graceful degradation on unreachable DB. Docstring and section comment updated. Test replaced. 6 new integration tests.
- **Assumption audit**: PASS -- `config = None` initialization before try block is plan-specified. Two-layer guard (vs three-layer) is correct since row counts block is inside `if profile:` branch. Mock attributes documented.
- **Architectural drift**: PASS -- Async delegation pattern matches existing `cmd_connect` → `_async_connect` pattern. `_async_status` placed after `cmd_status`, consistent with codebase conventions.

---

### Step 5: Update Documentation ✅
**Status**: Complete (2026-03-11T17:15:01-0700)
**Expected**: Update CLAUDE.md, README.md, and CLI help text to reflect the new row counts feature

**Implementation**:
- ✅ Updated CLAUDE.md CLI Commands section: `connect` comment changed to "Connect + validate schema + show table row counts", `status` comment changed to "Show current profile and table row counts (queries DB with graceful degradation)"
- ✅ Updated README.md CLI Reference section: `connect` comment changed to "Connect + validate schema + show table row counts", `status` comment changed to "Show current profile and table row counts"
- ✅ Updated `cli/__init__.py` module docstring: `status` line changed from "Show current connection status" to "Show current connection status and table row counts"
- ✅ Updated `build_parser()` status subparser help text from "Show current connection status" to "Show current connection status and table row counts"

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: ✅ 209/209 tests passing (177 CLI + 32 imports)
```bash
tests/test_lib_extraction_cli.py: 177 passed
tests/test_lib_extraction_imports.py: 32 passed
```

**Issues**: None

**Trade-offs & Decisions**: No significant trade-offs -- straightforward documentation updates per plan.

**Lessons Learned**:
- Documentation updates are a good opportunity to verify consistency across all places that describe the same feature: CLAUDE.md (developer reference), README.md (user-facing), module docstring (code-level), and argparse help text (CLI help output)
- The `cmd_status` docstring and section comment were already updated in Step 4 when the async conversion was done, so this step only needed to update the module-level docstring, the `build_parser()` help text, and the two markdown files

**Review**: PASS
**Reviewed**: 2026-03-11T17:25:09-0700
- **Intent match**: PASS -- All 5 acceptance criteria satisfied. CLAUDE.md and README.md updated for connect/status. Module docstring and `build_parser()` help text updated. No "local files only" for status. 209/209 tests pass.
- **Assumption audit**: PASS -- No new assumptions. Step 4 already handled docstring and section comment; Step 5 covered remaining 4 locations.
- **Architectural drift**: PASS -- Text-only updates across 4 files. No structural changes. Documentation consistent across all locations.

---

### Step 6: Full Test Suite Validation ✅
**Status**: Complete (2026-03-11T17:16:11-0700)
**Expected**: Run the full test suite and verify no regressions across all modules

**Implementation**:
- ✅ Ran full test suite: `uv run pytest -v --tb=short`
- ✅ All 824 tests pass with zero failures
- ✅ 15 warnings are all pre-existing `DeprecationWarning` for `asyncio.iscoroutinefunction` in introspector tests (unrelated to new code)
- ✅ No new warnings introduced by the row counts feature

**Deviation from Plan**: None -- implemented per plan specification. The plan estimated 700+ tests; the actual count is 824 tests (growth from the 27 new tests added in Steps 1-4 plus other recent additions).

**Test Results**: ✅ 824/824 tests passing
```bash
824 passed, 15 warnings in 29.89s
```

**Issues**: None

**Trade-offs & Decisions**: No significant trade-offs -- straightforward full suite validation.

**Lessons Learned**:
- The full suite grew from the estimated 700+ to 824 tests, reflecting both the 27 new row counts tests and other recent feature additions
- The 15 warnings are all `DeprecationWarning` for `asyncio.iscoroutinefunction` (deprecated in Python 3.14, slated for removal in 3.16) in `test_lib_extraction_introspector.py` -- these should be migrated to `inspect.iscoroutinefunction()` in a future cleanup task
- Zero test failures confirm the row counts feature is fully additive with no regressions across adapters, backup, comparator, config, exports, factory, fix, imports, introspector, models, sync, and CLI modules

**Result**: Full test suite passes with zero failures. The row counts feature is fully validated with no regressions.

**Review**: PASS
**Reviewed**: 2026-03-11T17:26:45-0700
- **Intent match**: PASS -- All 3 acceptance criteria met. 824/824 tests pass. New tests included. No warnings from row counts code (15 warnings are pre-existing introspector deprecations).
- **Assumption audit**: PASS -- No code changes in this step. Validation-only.
- **Architectural drift**: PASS -- No structural changes. File modifications match plan's Architecture section exactly.

---

## Final Validation

```bash
824 passed, 15 warnings in 29.89s
```

**Total**: 824 tests passing (797 existing + 27 new row counts tests)

---

## Key Decisions Made
| Decision | Rationale |
|----------|-----------|
| Independent `_EXCLUDED_TABLES` constant in CLI | Keeps CLI module independent of schema internals; mirrors `SchemaIntrospector.EXCLUDED_TABLES_DEFAULT` |
| Guard condition with three layers (config, profile_name, in profiles) | Prevents crashes across all edge cases: no config, no profile, profile not in config |
| No explicit mocking of `_get_table_row_counts` in existing connect tests | MagicMock's `__contains__` naturally returns False, preventing existing tests from reaching new code paths |
| Mock profiles with explicit string attributes for status tests | Rich's `Table.add_row()` cannot render MagicMock objects; explicit values make test data clear |

---

## What This Unlocks
Row counts in CLI output provide immediate data visibility after connecting or checking status, reducing the need to manually query the database.

---

## Next Steps
1. Run `/dev-finalize` to record completion timestamp, consolidate lessons, and update PROJECT_STATE.md
2. Verify live CLI commands show row counts (`db-adapter connect` and `db-adapter status`)
3. Proceed to next task as determined by project priorities

---

## Lessons Learned

- **MagicMock __contains__ returns False** - `"key" in MagicMock()` evaluates to `False` by default, so guard conditions using `in` naturally bypass new code paths in existing tests without needing explicit mocking. This can be relied upon but should be documented for future test maintainers.

- **Rich tables reject MagicMock values** - Rich's `Table.add_row()` cannot render `MagicMock` objects as strings, so mock profiles used in tests that reach Rich rendering code must have explicit string values for attributes like `provider` and `description`. Connect tests avoided this because guard conditions prevented reaching the render path.

- **Initialize variables before try blocks** - When a variable (like `config`) is assigned inside a try block and referenced in later guard conditions, it must be initialized to `None` before the try block. Otherwise, exceptions in the try block leave the variable unbound, causing `NameError` downstream.

- **Two-layer graceful degradation** - The helper swallows DB errors (returning empty dict) and the caller checks for empty results before rendering. This double protection ensures display-only features never crash the host command, even when failure modes combine unexpectedly.

- **Duplicate constants for module independence** - `_EXCLUDED_TABLES` in the CLI deliberately mirrors `SchemaIntrospector.EXCLUDED_TABLES_DEFAULT` rather than importing it. This keeps the CLI module independent of schema internals, avoiding a coupling that would make the CLI harder to test and maintain separately.

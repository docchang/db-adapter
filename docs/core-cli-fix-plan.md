# core-cli-fix Plan

> **Design**: See `docs/core-cli-fix-design.md` for analysis and approach.
>
> **Track Progress**: See `docs/core-cli-fix-results.md` for implementation status, test results, and issues.

## Overview

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-10T18:23:16-0700 |
| **Name** | Fix post-extraction CLI bugs, adapter compatibility, and test infrastructure |
| **Type** | Issue |
| **Environment** | Python -- see `references/python-guide.md` |
| **Proves** | All CLI commands produce correct, honest output against real databases |
| **Production-Grade Because** | Fixes bugs confirmed via 120 live integration tests against real PostgreSQL databases; no mock data or stubs |
| **Risk Profile** | Standard |
| **Risk Justification** | Internal CLI tooling with full test coverage; no production data paths affected |

---

## Deliverables

Concrete capabilities this task delivers:

- `AsyncPostgresAdapter` connects without `connect_timeout` error (asyncpg-compatible)
- `_parse_expected_columns()` returns lowercase column and table names (PostgreSQL-compatible)
- `connect` command performs real schema validation using config-driven `schema_file` and `validate_on_connect`
- `validate` command correctly reports schema validity using config or `--schema-file` override
- `fix` command falls back to `config.schema_file` when `--schema-file` not provided
- `sync` command error path uses `.errors` list (no AttributeError)
- `TestNoCircularImports` uses subprocess isolation instead of `importlib.reload()`
- All 553 existing unit tests pass; live integration xfails reduced from 16 to 0

---

## Prerequisites

Complete these BEFORE starting implementation steps.

### 1. Identify Affected Tests

**Why Needed**: Run only affected tests during implementation (not full suite)

**Affected test files**:
- `tests/test_lib_extraction_adapters.py` -- AsyncPostgresAdapter, `create_async_engine_pooled`, `test_appends_connect_timeout`
- `tests/test_lib_extraction_cli.py` -- CLI argument parsing, `_parse_expected_columns`, command structure
- `tests/test_lib_extraction_exports.py` -- `TestNoCircularImports` reload tests
- `tests/test_live_integration.py` -- Live integration tests (120 tests, 16 xfailed)

**Baseline verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_adapters.py tests/test_lib_extraction_cli.py tests/test_lib_extraction_exports.py -v --tb=short
# Expected: All pass (establishes baseline)
```

### 2. Verify Test Databases Available

**Why Needed**: Live integration tests require local PostgreSQL databases

**Steps**:
1. Confirm `db_adapter_full` and `db_adapter_drift` databases are reachable
2. Confirm `db.toml` exists in CWD with both profiles configured
3. Confirm `schema.sql` and `column-defs.json` exist in CWD

**Verification** (inline OK for prerequisites):
```bash
cd /Users/docchang/Development/db-adapter && uv run python -c "
from db_adapter.config.loader import load_db_config
config = load_db_config()
print('Profiles:', list(config.profiles.keys()))
print('Schema file:', config.schema_file)
print('Validate on connect:', config.validate_on_connect)
"
# Expected: Profiles listed, schema_file and validate_on_connect shown
```

---

## Success Criteria

From Design doc (refined with verification commands):

- [ ] `AsyncPostgresAdapter` connects without `connect_timeout` error (unblocks 14 xfailed tests)
- [ ] `_parse_expected_columns("schema.sql")` returns lowercase column names
- [ ] `connect` against full DB shows "Schema validation: PASSED" (real validation)
- [ ] `connect` against drift DB reports missing columns
- [ ] `connect` without schema file shows honest "skipped" message
- [ ] `validate` against full DB shows "Schema is valid"
- [ ] `validate` against drift DB reports specific drift
- [ ] `sync` error path shows proper error message (no AttributeError)
- [ ] `fix` without `--schema-file` uses config default
- [ ] `TestNoCircularImports` no longer uses `importlib.reload()`
- [ ] All 553 existing unit tests pass
- [ ] Live integration tests: xfails reduced from 16 to 0

---

## Architecture

### File Structure
```
src/db_adapter/
├── adapters/
│   └── postgres.py               # Fix connect_timeout
├── cli/
│   └── __init__.py                # Fix connect/validate/fix/sync commands + case sensitivity
├── config/
│   └── models.py                  # No changes (schema_file, validate_on_connect already exist)
└── schema/
    └── sync.py                    # No changes (.errors already correct in model)

tests/
├── test_lib_extraction_adapters.py  # Update connect_timeout test
├── test_lib_extraction_cli.py       # Add tests for config-driven commands, case sensitivity
├── test_lib_extraction_exports.py   # Replace importlib.reload() with subprocess
└── test_live_integration.py         # Update xfail markers after fixes
```

### Design Principles
1. **OOP Design**: Existing class patterns maintained; changes are surgical bug fixes within existing functions
2. **Validated Data Models**: `SyncResult.errors` (Pydantic list), `DatabaseConfig.schema_file`/`validate_on_connect` already validated
3. **Strong Typing**: All modified function signatures retain type annotations
4. **Config-Driven with CLI Override**: CLI commands read `DatabaseConfig` fields; CLI flags override config defaults

---

## Implementation Steps

**Approach**: Fix bugs in dependency order -- adapter first (foundation), then parser (shared utility), then CLI commands that consume both, then test infrastructure. Each step is independently verifiable.

> This plan is a contract between the executor (builder) and reviewer (validator). Steps specify **what** to build and **how** to verify -- the executor writes the implementation.

### Step 0: Verify Baseline

**Goal**: Confirm affected test files pass before making changes

- [ ] Run existing unit tests to establish green baseline

**Code**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_adapters.py tests/test_lib_extraction_cli.py tests/test_lib_extraction_exports.py -v --tb=short
```

**Verification** (inline OK for Step 0):
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_adapters.py tests/test_lib_extraction_cli.py tests/test_lib_extraction_exports.py --tb=short -q
# Expected: All pass
```

**Output**: Confirmed baseline -- all existing unit tests pass

---

### Step 1: Fix `connect_timeout` in AsyncPostgresAdapter

**Goal**: Remove the buggy URL-based `connect_timeout` parameter from `create_async_engine_pooled()` so asyncpg connections succeed (Design Bug #4)

- [ ] Modify `create_async_engine_pooled()` in `src/db_adapter/adapters/postgres.py`
- [ ] Update `test_appends_connect_timeout` in `tests/test_lib_extraction_adapters.py`

**Specification**:
- Remove the URL manipulation block (lines 52-55 of `postgres.py`) that appends `connect_timeout=5` as a query parameter
- Instead, pass `connect_args={"timeout": 5}` to `create_async_engine()` by adding it to the `defaults` dict (alongside `pool_size`, `pool_pre_ping`, etc. at lines 57-63 of `postgres.py`). This uses asyncpg's native `timeout` parameter for connection establishment
- The `connect_args` key should be overridable by caller kwargs, same as other defaults. Note: override is full replacement (not merge), consistent with `{**defaults, **kwargs}` behavior for all keys -- a caller passing `connect_args={"command_timeout": 10}` would replace the entire dict including `timeout: 5`. Document this in a code comment
- Update the existing `test_appends_connect_timeout` test in `tests/test_lib_extraction_adapters.py` to verify:
  - `connect_args={"timeout": 5}` is passed to `create_async_engine` — assert via `mock_create.call_args[1].get("connect_args") == {"timeout": 5}` (keyword args dict)
  - No `connect_timeout` parameter appears in the URL — assert via `"connect_timeout" not in mock_create.call_args[0][0]`
- The function signature `create_async_engine_pooled(database_url: str, **kwargs: Any) -> AsyncEngine` must not change

**Acceptance Criteria**:
- `create_async_engine_pooled("postgresql+asyncpg://user:pass@host/db")` does NOT append `connect_timeout` to the URL
- `create_async_engine` is called with `connect_args={"timeout": 5}` in kwargs
- Caller can override `connect_args` via `**kwargs`
- All tests in `test_lib_extraction_adapters.py` pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_adapters.py -v --tb=short
```

**Output**: All adapter tests passing

---

### Step 2: Fix Case Sensitivity in `_parse_expected_columns`

**Goal**: Make `_parse_expected_columns()` return lowercase table and column names to match PostgreSQL's identifier folding behavior (Design Bug #3, resolves Bug #9)

- [ ] Modify `_parse_expected_columns()` in `src/db_adapter/cli/__init__.py`
- [ ] Write tests verifying lowercase output

**Specification**:
- In `_parse_expected_columns()`, apply `.lower()` to both `table_name` and `col_name` before adding them to the result dict:
  - Line 108: `result[table_name.lower()] = columns`
  - Line 105: `columns.add(col_name.lower())`
- Existing tests in `TestParseExpectedColumns` use lowercase column names in their SQL fixtures, so they should continue passing (`.lower()` is a no-op on already-lowercase names)
- Add a new test in `TestParseExpectedColumns` that uses uppercase column names in the SQL fixture and verifies the result contains lowercase names
- Add a second test with mixed-case names (e.g., `CREATE TABLE Items (Id TEXT, NAME TEXT)`) and verify the result contains all lowercase

**Acceptance Criteria**:
- `_parse_expected_columns()` on a SQL file with `CREATE TABLE Items (A TEXT, B TEXT)` returns `{"items": {"a", "b"}}`
- All existing `TestParseExpectedColumns` tests still pass
- New test for uppercase SQL identifiers passes
- Mixed case (some uppercase, some lowercase) returns all lowercase

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py::TestParseExpectedColumns -v --tb=short
```

**Output**: All parse tests passing

---

### Step 3: Fix `connect` Command to Wire Config

**Goal**: Make `_async_connect()` read `config.schema_file` and `config.validate_on_connect` so it performs real schema validation when configured (Design Bug #1, resolves Bug #8 partially)

- [ ] Modify `_async_connect()` in `src/db_adapter/cli/__init__.py`
- [ ] Write tests for config-driven validation behavior

**Specification**:
- Modify `_async_connect()` to:
  1. Load config via `load_db_config()`. Catch `Exception` (including `FileNotFoundError` and Pydantic `ValidationError` for malformed config) -- if config unavailable, fall back to connect-only and print "Connected (no config found -- schema validation skipped)"
  2. If `config.validate_on_connect` is `True`:
     - Try to parse expected columns via `_parse_expected_columns(config.schema_file)`
     - If successful, pass `expected_columns` to `connect_and_validate()`
     - If `FileNotFoundError` or `ValueError` (schema file missing or unparseable): connect-only, print warning like "Connected (schema file not found -- validation skipped)"
  3. If `config.validate_on_connect` is `False`: connect-only, print "Connected (schema validation disabled in config)"
  4. Check `result.success` first. If `False`, check if `result.schema_report` is available -- if so, display the schema report (missing tables/columns) before returning 1. If no schema report, print the connection error (`result.error`). Return 1 in both cases. Only proceed to steps 5-7 when `result.success is True`
  5. Only print "Schema validation: PASSED" when `expected_columns` was actually passed and `result.schema_valid is True`
  6. When validation was performed but `result.success is False` due to schema drift (i.e., `result.schema_valid is False`), this is handled in step 4 above via `result.schema_report`
  7. When validation was skipped (`result.schema_valid is None`), show the connect-only message appropriate to the reason
- The `connect_and_validate()` function signature must NOT change
- Use explicit `is True` / `is False` / `is None` checks on `result.schema_valid` to handle the three-state correctly
- Tests should mock `load_db_config()` and `connect_and_validate()` to verify:
  - Config with `validate_on_connect=True` and valid schema file calls `connect_and_validate` with `expected_columns`
  - Config with `validate_on_connect=False` calls `connect_and_validate` without `expected_columns`
  - Missing `db.toml` (`FileNotFoundError` from `load_db_config`) still connects successfully
  - Missing schema file (`FileNotFoundError` from `_parse_expected_columns`) still connects, shows warning

**Acceptance Criteria**:
- `_async_connect()` calls `connect_and_validate(expected_columns=...)` when `validate_on_connect=True` and schema file exists
- `_async_connect()` calls `connect_and_validate()` without `expected_columns` when `validate_on_connect=False`
- Missing `db.toml` does not crash -- connects with informational message
- Missing schema file does not crash -- connects with warning message
- "Schema validation: PASSED" only prints when validation actually occurred and passed
- All tests in `test_lib_extraction_cli.py` pass

**Trade-offs**:
- **Config loading in `_async_connect`**: Load config at the start of the function rather than at module level, because CLI commands should not crash at import time if `db.toml` is missing. This follows the same location pattern as `cmd_profiles` and `cmd_status` (load inside function body). Note: the exception handling is broader (`Exception`) than those commands (`FileNotFoundError` only) to also handle Pydantic `ValidationError` for malformed config.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 4: Fix `validate` Command

**Goal**: Make `_async_validate()` load expected columns from config (or `--schema-file` override) and correctly handle the three-state `schema_valid` result (Design Bug #2, resolves Bug #8 partially)

- [ ] Modify `_async_validate()` in `src/db_adapter/cli/__init__.py`
- [ ] Add `--schema-file` optional argument to the `validate` subparser
- [ ] Write tests for config-driven validation and `--schema-file` override

**Specification**:
- Add optional `--schema-file` argument to the `validate` subparser (`required=False, default=None`)
- Modify `_async_validate()` to:
  1. Determine schema file source: if `args.schema_file` is provided, use it directly (skip config loading). Otherwise, attempt `load_db_config()` -- catch `Exception` (including `FileNotFoundError` and Pydantic `ValidationError`) and if it fails, fall through to bullet 3's "no schema source" error. If config loads successfully, use `config.schema_file`
  2. Parse expected columns via `_parse_expected_columns(schema_file_path)`. Catch `FileNotFoundError`/`ValueError` from `_parse_expected_columns()`
  3. If no schema source available (no `--schema-file` flag AND `load_db_config()` fails): print error "No schema file available. Provide --schema-file or configure schema.file in db.toml" and return 1. If config loads but `_parse_expected_columns(config.schema_file)` raises `FileNotFoundError`: print error referencing the missing file and return 1
  4. Pass `expected_columns` to `connect_and_validate(profile_name=profile, expected_columns=expected, env_prefix=env_prefix, validate_only=True)` (`validate_only=True` prevents overwriting the `.db-profile` lock file during a validate-only operation)
  5. Check `result.success` first. If `False`, check if `result.schema_report` is available -- if so, display the schema report before returning 1. If no schema report (pure connection failure), print `result.error` and return 1. Only proceed to the three-state `schema_valid` check when `result.success is True`. This mirrors Step 3's bullet 4 pattern
  6. Fix the three-state check: `result.schema_valid is True` for pass, `result.schema_valid is False` for fail. Add defensive `elif result.schema_valid is None:` handler (print "Validation could not be performed" and return 1) even though it should not occur when `expected_columns` is always passed
- Tests should verify:
  - `validate` with config schema file calls `connect_and_validate` with `expected_columns`
  - `validate --schema-file override.sql` uses the CLI-provided file
  - `validate` with no schema source returns 1 with informative error

**Acceptance Criteria**:
- `_async_validate()` passes `expected_columns` to `connect_and_validate()` when schema file is available
- `--schema-file` override takes precedence over config
- Explicit `is True` check on `result.schema_valid` replaces truthy check
- No schema source produces clear error message and returns 1
- Existing test `test_fix_parser_requires_schema_file` still passes (it tests `fix`, not `validate`)
- All existing CLI tests still pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 5: Fix Sync `.error` to `.errors` and Make `fix --schema-file` Optional

**Goal**: Fix the `sync` command's attribute access bug and make `fix --schema-file` fall back to config default (Design Bugs #5 and #7)

- [ ] Fix `.error` to `.errors` in `_async_sync()` (two locations)
- [ ] Change `fix --schema-file` from `required=True` to `required=False, default=None`
- [ ] Add config fallback logic to `_async_fix()`
- [ ] Write tests for both fixes

**Specification**:
- In `_async_sync()`:
  - Line 495: Change `result.error` to `"; ".join(result.errors) if result.errors else "Unknown error"` (show all errors since multiple sync errors can occur across tables)
  - Line 565: Change `sync_result.error` to `"; ".join(sync_result.errors) if sync_result.errors else "Unknown error"` (same pattern)
- In argparse setup for `fix`:
  - Change `--schema-file` from `required=True` to `required=False, default=None`
  - Keep `--column-defs` as `required=True` (no config equivalent per constraints)
- In `_async_fix()`:
  - If `args.schema_file` is provided: use it directly (existing behavior)
  - If `args.schema_file` is `None`: load config via `load_db_config()`, set `schema_file = config.schema_file`. If `load_db_config()` raises `Exception` (no `db.toml` or malformed): print error "No schema file available. Provide --schema-file or configure schema.file in db.toml" and return 1
  - Once `schema_file` is resolved (from either source), update both `_parse_expected_columns(args.schema_file)` (line 252) and `generate_fix_plan(..., args.schema_file)` (line 288) to use the resolved `schema_file` variable instead of `args.schema_file`. Let the existing `_parse_expected_columns()` try/except handle `FileNotFoundError` naturally if the file doesn't exist
- Tests should verify:
  - `_async_sync()` accesses `result.errors` not `result.error`
  - `fix` without `--schema-file` falls back to config
  - `fix --schema-file explicit.sql` uses the provided file
  - `fix` with no schema source returns 1 with clear error
  - Existing test `test_fix_parser_requires_schema_file` must be updated since `--schema-file` is no longer required
  - Existing test `test_fix_parser_requires_column_defs` still passes

**Acceptance Criteria**:
- `_async_sync()` has no reference to `.error` attribute -- only `.errors` list
- `fix` command works without `--schema-file` when `db.toml` has `schema_file` configured
- `fix --schema-file explicit.sql` overrides config (existing behavior preserved)
- `fix` with no schema source at all (no flag, no config) returns 1 with error message
- `--column-defs` remains required
- All existing CLI tests pass (with `test_fix_parser_requires_schema_file` updated)

**Trade-offs**:
- **Error formatting for `.errors`**: Use `"; ".join(result.errors)` to show all errors rather than just the first, because multiple sync errors can occur across different tables. Alternative: show only first error for brevity.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### ~~Step 6~~: Moved

> Backup CLI (Design Bug #6) moved to separate task: [core-backup-cli-design.md](core-backup-cli-design.md)

---

### Step 7: Fix `importlib.reload()` Test Interaction

**Goal**: Replace `importlib.reload()` calls in `TestNoCircularImports` with subprocess isolation to prevent exception class identity breakage (Design Bug #10)

- [ ] Modify `TestNoCircularImports` in `tests/test_lib_extraction_exports.py`
- [ ] Remove `importlib.reload()` usage from circular import tests
- [ ] Write subprocess-based tests that verify import ordering in a fresh process

**Specification**:
- Replace all `importlib.reload()` calls in `TestNoCircularImports` with subprocess-based import checks:
  ```python
  # Pattern: subprocess.run([sys.executable, "-c", "import db_adapter.config; import db_adapter.factory"])
  ```
- Each test should:
  - Use `subprocess.run()` with `sys.executable` and `-c` flag
  - Import the modules in the specific order being tested
  - Check `returncode == 0` to verify no circular import errors
  - Optionally capture stderr to show import errors in test failure messages
- `test_import_all_subpackages` can remain as-is (it does not use reload)
- Add `import subprocess` and `import sys` to the test file imports
- The `import importlib` at the top of the file can be removed if no other test uses it (check first)

**Acceptance Criteria**:
- `TestNoCircularImports` tests pass without using `importlib.reload()`
- Each test verifies import ordering in a clean Python subprocess
- No side effects on other test modules (the class identity problem is eliminated)
- `importlib.reload()` does not appear anywhere in `test_lib_extraction_exports.py`
- All tests in `test_lib_extraction_exports.py` pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_exports.py -v --tb=short
```

**Output**: All export tests passing

---

### Step 8: Update Live Integration Test Markers

**Goal**: Update xfail markers and expected assertions in `tests/test_live_integration.py` to reflect fixed behavior

- [ ] Remove xfail markers from all 16 tests unblocked by Bug #4 fix
- [ ] Update assertions for tests affected by Bug #1, #2, #3, #5 fixes
- [ ] Remove workarounds for Bug #10 (`importlib.reload()` class identity issue)
- [ ] Verify all live integration tests pass (if test databases are available)

**Specification**:
- Remove all 16 `@pytest.mark.xfail` markers from tests unblocked by fixes in Steps 1-5:
  - `TestAdapterLive` (5 xfail tests) -- adapter CRUD operations should now work (Bug #4)
  - `TestGetAdapterLive` (3 xfail tests) -- `get_adapter()` should now succeed (Bug #4)
  - `TestSyncLive` (5 xfail tests) -- sync operations should now work (Bug #4)
  - `TestAdapterEngineBug` (1 xfail test) -- engine bug should be fixed (Bug #4)
  - `TestAsyncSyncDirect::test_sync_dry_run_direct` (1 xfail test, line 1408) -- sync direct call should work (Bug #4)
  - `TestAsyncSyncDirect::test_sync_error_attribute` (1 xfail test, line 1422) -- sync error attribute should work (Bug #5, depends on Step 5 `.errors` fix)
- Update non-xfail test affected by Step 1:
  - `TestAdapterEngineBug::test_connect_timeout_appended_to_url` (line 794) -- currently asserts `assert "connect_timeout" in source`. After Step 1 removes `connect_timeout`, this assertion will fail. Either invert to verify `connect_timeout` is absent from the source (confirming the fix) or replace with a test verifying `connect_args` usage
- Update assertions in tests that demonstrated bugs:
  - `TestParseExpectedColumnsLive` -- change `assert any(c != c.lower() ...)` to `assert all(c == c.lower() ...)` (expect lowercase after case fix)
  - `TestCLIConnectLive` -- connect against drift DB should show drift report (not "PASSED"). `test_connect_drift_succeeds` should change from `assert r.returncode == 0` to `assert r.returncode == 1`. `test_connect_profile_switch_notice` (line 494) should also change from `assert r.returncode == 0` to `assert r.returncode == 1` (connecting to drift profile now fails schema validation with `validate_on_connect=True`); update the "Switched from" assertion accordingly since the profile switch message only prints in the success path
  - `TestCLIValidateLive` -- validate against full DB should show "valid" (not "drifted")
  - `TestSyncResultBug` -- should test `.errors` list attribute works correctly (no AttributeError)
  - `TestAsyncConnectDirect` -- should verify config-driven validation passes with expected_columns. `test_connect_drift_direct` (line 1217) should change from `assert rc == 0` to `assert rc == 1` (drift now detected after Step 3's config-driven validation). `test_connect_full_direct` (line 1207) should remain `assert rc == 0` (valid DB passes validation)
  - `TestAsyncValidateDirect` -- should verify real validation produces correct result. All `Namespace(env_prefix="")` objects must include `schema_file=None` to match the new argument added in Step 4 (otherwise `AttributeError` on `args.schema_file`). `test_validate_full_db` should change from `assert rc == 1` to `assert rc == 0`
  - `TestAsyncFixDirect` -- should verify fix plan works after case fix (no "Unknown column definition" error). `test_fix_preview_full_db_direct` should change from `assert rc == 1` to `assert rc == 0` (no fixes needed on a valid DB). `test_fix_preview_drift_db_direct` should change from `assert rc == 1` to `assert rc == 0` (fix plan generated successfully in preview mode after case fix enables correct plan generation)
  - `TestCaseMismatchSeverity` (2 tests at lines 1449, 1483) -- both tests assert uppercase column names and false drift from `_parse_expected_columns`. After Step 2's case fix: `test_fix_plan_errors_from_case_mismatch` should verify the fix plan succeeds with lowercase columns (not `assert "A" in parsed["items"]`); `test_case_mismatch_items_columns_only` should verify `result.valid is True` (not `assert not result.valid`). Alternatively, these bug-demonstration tests can be removed since the bug is now fixed
  - `TestParseExpectedColumnsLive::test_case_mismatch_causes_false_drift` (line 657) -- the test's `actual` dict only has 1 table (items) while `_parse_expected_columns` returns 3 tables, so `result.valid` remains `False` due to missing tables even after the case fix. Update to assert that `result.missing_columns` is empty (no false column drift from case mismatch) while acknowledging `result.valid is False` due to incomplete `actual` dict, or remove as a now-irrelevant bug demonstration
- Remove workarounds for the `importlib.reload()` class identity issue:
  - `test_fix_no_profile` (line 1288) and `test_sync_no_dest_profile` (line 1374): remove try/except workaround blocks, use `assert rc == 1` directly (after Step 7's fix, `ProfileNotFoundError` will be caught correctly without the workaround)
- This step requires test databases to be available. If databases are not reachable, tests will auto-skip (per existing skip guard)

**Acceptance Criteria**:
- No `@pytest.mark.xfail` markers remain for bugs that have been fixed
- Tests that previously demonstrated bugs now assert the corrected behavior
- No workaround comments for `importlib.reload()` class identity issue
- Live integration tests: 120 tests, 0 failures, 0 xfails (when databases available)
- Tests still auto-skip when databases are not available

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_live_integration.py -v --tb=short
# Expected: 120 tests, 0 failures, 0 xfails (when DBs available)
# If DBs not available: all tests skipped
```

**Output**: All live integration tests passing (or skipped if no DBs)

---

### Step 9: Final Integration and Documentation

**Goal**: Run full test suite, update README and CLAUDE.md to reflect fixed CLI behavior

- [ ] Run full test suite (553 unit + live integration)
- [ ] Update README.md CLI Reference section
- [ ] Update CLAUDE.md CLI Commands section
- [ ] Verify combined test run with no failures

**Prerequisite**: Steps 1-8 completed successfully. All previous bug fixes must be in place for this step to verify correctly.

**Specification**:
- Run full test suite to verify no regressions
- Update README.md:
  - CLI `connect` section: note that it reads `schema_file` and `validate_on_connect` from config; e.g., `db-adapter connect  # Validates schema when validate_on_connect=true in db.toml`
  - CLI `validate` section: add `--schema-file` optional argument; e.g., `db-adapter validate [--schema-file schema.sql]`
  - CLI `fix` section: note `--schema-file` defaults to config value; e.g., `db-adapter fix --column-defs defs.json  # Uses schema_file from db.toml`
  - Extend the config example section (README line ~66-79) to include a `[schema]` section showing `file` and `validate_on_connect` fields (the TOML keys, not the Pydantic field names -- `load_db_config()` reads `schema_settings.get("file", ...)`)
- Update CLAUDE.md:
  - CLI Commands section (line ~84-96): reflect actual behavior post-fix
  - Note `validate` accepts `--schema-file`
  - Note `fix --schema-file` is optional when config provides default
- No changes to `pyproject.toml` or dependencies -- this is a bug fix task

**Acceptance Criteria**:
- All 553 unit tests pass
- Live integration tests pass (when databases available)
- README.md CLI Reference accurately describes current behavior
- CLAUDE.md CLI Commands section is accurate
- No new dependencies introduced

**Verification**:
```bash
# Run all unit tests
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short --ignore=tests/test_live_integration.py

# Run live integration tests (if DBs available)
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_live_integration.py -v --tb=short

# Expected: All pass
```

**Output**: Full suite passing

---

## Test Summary

### Affected Tests (Run These)

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `tests/test_lib_extraction_adapters.py` | ~60 | AsyncPostgresAdapter, connect_timeout fix |
| `tests/test_lib_extraction_cli.py` | ~30 | CLI arguments, _parse_expected_columns, command wiring |
| `tests/test_lib_extraction_exports.py` | ~30 | Package exports, circular import checks |
| `tests/test_live_integration.py` | ~120 | Live database integration tests |

**Affected tests: ~240 tests**

**Full suite**: ~553 unit tests + ~120 live integration (run at final step)

---

## What "Done" Looks Like

```bash
# 1. All unit tests pass
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ --ignore=tests/test_live_integration.py --tb=short -q
# Expected: 553 passed

# 2. Live integration tests pass (when DBs available)
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_live_integration.py --tb=short -q
# Expected: 120 passed, 0 xfailed

# 3. CLI commands produce correct output
DB_PROFILE=full uv run db-adapter connect
# Expected: "Schema validation: PASSED" (real validation)

DB_PROFILE=drift uv run db-adapter connect
# Expected: Reports missing columns (items: b,e,f + products: price,active)

uv run db-adapter validate
# Expected: "Schema is valid" or drift report depending on current profile
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/db_adapter/adapters/postgres.py` | Modify | Fix `connect_timeout` -- remove URL param, use `connect_args` |
| `src/db_adapter/cli/__init__.py` | Modify | Wire config into connect/validate/fix; fix .error to .errors; fix case sensitivity; make --schema-file optional for fix; add --schema-file to validate |
| `tests/test_lib_extraction_adapters.py` | Modify | Update `test_appends_connect_timeout` |
| `tests/test_lib_extraction_cli.py` | Modify | Add tests for config-driven commands, case sensitivity, update fix arg test |
| `tests/test_lib_extraction_exports.py` | Modify | Replace `importlib.reload()` with subprocess isolation |
| `tests/test_live_integration.py` | Modify | Remove xfail markers, update bug-demonstration assertions |
| `README.md` | Modify | Update CLI Reference section |
| `CLAUDE.md` | Modify | Update CLI Commands section |

---

## Dependencies

No new dependencies required. All fixes use existing packages:
- `sqlalchemy` (connect_args parameter)
- `subprocess` (stdlib, for test isolation)
- `argparse` (stdlib, already imported)

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Case sensitivity fix breaks existing tests | LOW | Only affects `_parse_expected_columns` (CLI-internal); existing tests use lowercase SQL |
| `connect_timeout` removal affects connection reliability | LOW | SQLAlchemy `pool_pre_ping=True` handles stale connections; asyncpg has 60s default timeout |
| Config loading failure breaks connection-only mode | MED | Catch `FileNotFoundError` gracefully -- fall back to connect-only |
| Live integration test updates fail on CI without databases | LOW | Tests auto-skip when databases not reachable |

---

## Next Steps After Completion

1. Verify all 553 unit tests pass
2. Verify live integration tests: 0 xfails, 0 failures
3. Verify CLI commands produce correct output against test databases

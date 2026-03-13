# core-cli-fix Design

> **Purpose**: Analyze and design solutions before implementation planning
>
> **Important**: This task must be self-contained (works independently; doesn't break existing functionality and existing tests)

## Executive Summary

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-10T16:45:29-0700 |
| **Updated** | 2026-03-10T19:43:19-0700 |
| **Task** | Fix post-extraction CLI bugs, adapter compatibility, and test infrastructure |
| **Type** | Issue |
| **Scope** | CLI, factory, adapter — 5 files + docs |
| **Code** | NO - This is a design document |
| **Risk Profile** | Standard |
| **Risk Justification** | Internal CLI tooling with full test coverage; no production data paths affected |

**Challenge**: Post-extraction audit and live integration testing revealed 9 bugs across CLI commands, adapter connection, schema parsing, and test infrastructure — ranging from false validation output to completely broken commands.

**Solution**: Fix all bugs in priority order — starting with the adapter connection issue, then CLI validation wiring, case-sensitivity fix, sync error handling, and test infrastructure repair.

---

## Context

### Current State

During the library extraction from Mission Control, the hardcoded schema definitions were correctly removed. However, several CLI commands weren't updated to work without them, and the audit revealed additional issues beyond the original scope.

**Verified via live testing** against two local PostgreSQL databases (3 tables each, with FK relationships):
- `db_adapter_full`: items (a–g), categories (3 rows), products (5 rows, FK → categories)
- `db_adapter_drift`: items (a,c,d,g — missing b,e,f), categories (2 rows), products (missing price,active — 2 rows)

**Bug inventory (9 issues confirmed):**

```
SEVERITY: CRITICAL (blocks basic usage)
├── #1  connect prints "PASSED" without validating     [cli/__init__.py:138-144]
├── #2  validate always reports drift                   [cli/__init__.py:196-214]
├── #3  _parse_expected_columns case mismatch           [cli/__init__.py:51-115]
├── #4  AsyncPostgresAdapter connect_timeout rejected   [adapters/postgres.py:52-55]
├── #9  Case mismatch cascades into fix plan failure   [cli/__init__.py + schema/fix.py]

SEVERITY: HIGH (broken error paths)
├── #5  sync CLI uses .error but model has .errors      [cli/__init__.py:495,565]

SEVERITY: MEDIUM (design gaps, not blocking)
├── #7  fix --schema-file always required               [cli/__init__.py:815-819]
├── #8  Dead config: schema_file, validate_on_connect   [config/models.py:38-39]

SEVERITY: MEDIUM (test infrastructure)
├── #10 importlib.reload() breaks exception class identity [test_lib_extraction_exports.py + cli/__init__.py]
```

> **Note**: Bug #6 (Backup CLI non-functional) moved to separate design: [core-cli-unify-design.md](core-cli-unify-design.md)

**What works correctly (verified by 120 live integration tests — 104 passed, 16 xfailed):**
- `SchemaIntrospector` — correctly introspects both databases, all 3 tables, FK constraints, column types (uses psycopg, not asyncpg)
- `validate_schema()` comparator — correctly detects 5 missing columns across 2 tables (items: b,e,f + products: price,active)
- `connect_and_validate()` — works correctly when `expected_columns` is provided
- `get_adapter()` — resolves profiles and creates adapters (but see #4 for connection issue)
- `status`, `profiles` CLI commands — read-only, work fine
- Lock file mechanics — read/write/clear works correctly
- FK-aware fix plan generation — respects topological ordering (categories before products)
- Config loading — parses `db.toml` including `[schema]` section
- Backup models — `BackupSchema`, `TableDef`, `ForeignKey` all work correctly
- All 553 existing unit tests pass

### Target State

```
CLI Commands (target state)
├── connect    → loads config.schema_file + config.validate_on_connect
│                → validates when configured; honest messaging when not
├── validate   → loads config.schema_file (or --schema-file override)
│                → actually validates; errors clearly if no schema source
├── fix        → --schema-file defaults to config.schema_file
│                → case-insensitive column matching works
├── sync       → .errors list handled correctly on failure
├── status     → unchanged (works)
└── profiles   → unchanged (works)

Adapter
├── AsyncPostgresAdapter → connect_timeout fixed for asyncpg compat

Config
├── schema_file       ← READ by connect, validate, fix
└── validate_on_connect ← READ by connect
```

---

## Constraints

- **Must NOT happen**: Existing 553 tests must not break.
- **Compatibility**: `connect_and_validate()` function signature must not change.
- **Scope boundaries**: `sync --tables` and `--user-id` being required is correct (not a bug). `get_adapter()` ignoring `provider` field is a separate enhancement (not this task).
- **Other guardrails**: `--column-defs` for `fix` remains required (no config equivalent). `_parse_expected_columns()` stays CLI-internal.

---

## Analysis

> Each item analyzed independently. No implied order - read in any sequence.

### 1. `connect` Prints "PASSED" Without Validating

**What**: `_async_connect()` calls `connect_and_validate(env_prefix=env_prefix)` without `expected_columns`. The factory skips validation and writes the lock file. CLI unconditionally prints "Schema validation: PASSED".

**Why**: Users get false confidence. Lock file contract ("validated profile") is undermined.

**Approach**:
Wire `config.schema_file` and `config.validate_on_connect` into `_async_connect()`:
1. Load config via `load_db_config()`. If `FileNotFoundError` (no `db.toml`), fall back to connect-only with message: "Connected (no config found — schema validation skipped)"
2. If `validate_on_connect=True` and schema file exists and parses successfully: pass to `connect_and_validate(expected_columns=expected)`
3. If `validate_on_connect=True` but schema file missing or unparseable (`FileNotFoundError`, `ValueError`): connect-only, print warning
4. If `validate_on_connect=False`: connect-only, print "Connected (schema validation skipped)"
5. Only print "Schema validation: PASSED" when validation actually occurred

> **Behavioral note**: `DatabaseConfig` defaults to `validate_on_connect=True` and `schema_file="schema.sql"`. Users who never configured a `[schema]` section in `db.toml` will get validation on `connect` if `schema.sql` happens to exist in CWD. This is the desired behavior — if a schema file is present, validation should run. If users want to skip validation, they set `validate_on_connect = false` in `db.toml`. If the schema file exists but is unreadable or contains invalid SQL, `_parse_expected_columns()` will raise `ValueError` or `FileNotFoundError` — these should be caught and treated as "schema file missing" (connect-only + warning), not as fatal errors.

**Live test evidence:**
```
$ DB_PROFILE=drift uv run db-adapter connect
v Connected to profile: drift
  Schema validation: PASSED           ← LIE: drift DB is missing 5 columns
                                         (items: b,e,f + products: price,active)
```

Files: `src/db_adapter/cli/__init__.py` — `_async_connect()`

---

### 2. `validate` Always Reports Drift

**What**: `_async_validate()` calls `connect_and_validate()` without `expected_columns`. Returns `schema_valid=None`. Since `None` is falsy, `if result.schema_valid:` falls through to "Schema has drifted".

**Why**: The `validate` command is completely non-functional. It always fails, even on a valid database.

**Approach**:
1. Load config, resolve schema file (config default or `--schema-file` override)
2. Parse expected columns, pass to `connect_and_validate(expected_columns=expected, validate_only=True)`
3. Fix falsy-None: explicitly check `result.schema_valid is True` / `is False` / `is None`
4. Add optional `--schema-file` to validate subparser

**Live test evidence:**
```
$ DB_PROFILE=full uv run db-adapter connect    ← connects to VALID database
$ uv run db-adapter validate
x Schema has drifted                            ← LIE: schema is valid
```

Files: `src/db_adapter/cli/__init__.py` — `_async_validate()` + argparse

---

### 3. `_parse_expected_columns` Case Mismatch

**What**: The SQL parser preserves column name case from the CREATE TABLE statement (e.g., uppercase `A, B, C`). PostgreSQL folds unquoted identifiers to lowercase. The introspector returns lowercase `a, b, c`. Set comparison fails because `{"A"} != {"a"}`.

**Why**: Schema validation will report ALL columns as missing even when the schema matches perfectly. This blocks `connect`, `validate`, and `fix` from working correctly even after bugs #1 and #2 are fixed.

**Approach**:
Lowercase all parsed column names in `_parse_expected_columns()`:
```python
columns.add(col_name.lower())  # instead of columns.add(col_name)
```

Also lowercase the table name for consistency:
```python
result[table_name.lower()] = columns
```

> **Note**: Double-quoted SQL identifiers (e.g., `"MyColumn"`) where PostgreSQL preserves case are out of scope. The parser already does not handle quoted identifiers, and this function stays CLI-internal per constraints.

**Live test evidence:**
```python
# Parsed from schema.sql (preserves case from SQL file — items has uppercase A-G;
# categories and products have lowercase in current schema.sql)
{'items': {'F', 'G', 'A', 'D', 'B', 'E', 'C'},
 'categories': {'id', 'slug', 'name', 'user_id'},
 'products': {'id', 'slug', 'name', 'category_id', 'price', 'active', 'user_id'}}

# Introspected from DB (PostgreSQL folds to lowercase)
{'items': {'d', 'f', 'c', 'e', 'a', 'g', 'b'},
 'categories': {'id', 'slug', 'name', 'user_id'},
 'products': {'id', 'slug', 'name', 'category_id', 'price', 'active', 'user_id'}}

# Set comparison: items table has 7 "missing" columns due to case mismatch (A≠a, B≠b, etc.)
# categories and products match correctly (both lowercase)
```

Files: `src/db_adapter/cli/__init__.py` — `_parse_expected_columns()`

---

### 4. AsyncPostgresAdapter `connect_timeout` Rejected by asyncpg

**What**: `create_async_engine_pooled()` appends `connect_timeout=5` as a URL query parameter. asyncpg does not recognize `connect_timeout` — it expects `command_timeout` or `timeout`.

**Why**: Any direct use of `AsyncPostgresAdapter` fails at connection time. The CLI `connect` command works because it uses `SchemaIntrospector` (psycopg), not the adapter. But any CRUD operation via the adapter fails.

**Approach**:
Remove URL-based `connect_timeout` parameter. Use SQLAlchemy's `connect_args` instead:
```python
create_async_engine(
    database_url,
    connect_args={"timeout": 5},  # asyncpg's connection timeout parameter
    ...
)
```

> **Note**: asyncpg has two timeout parameters: `timeout` (connection establishment, default 60s) and `command_timeout` (query execution). The error message suggests `command_timeout` but `timeout` is the correct replacement for `connect_timeout`. The existing unit test `test_appends_connect_timeout` in `test_lib_extraction_adapters.py` asserts the current buggy behavior and must be updated.

Or simply remove the timeout parameter entirely — SQLAlchemy's `pool_pre_ping=True` already handles stale connections.

**Live test evidence:**
```
TypeError: connect() got an unexpected keyword argument 'connect_timeout'.
Did you mean 'command_timeout'?
```

Files: `src/db_adapter/adapters/postgres.py` — `create_async_engine_pooled()`

---

### 5. Sync CLI Uses `.error` but Model Has `.errors`

**What**: `_async_sync()` accesses `result.error` (line 495) and `sync_result.error` (line 565), but `SyncResult` has an `.errors` list, not a singular `.error` property.

**Why**: AttributeError when sync fails. The error path is broken — users won't see a helpful error message, they'll see a crash.

**Approach**:
Change `result.error` to `result.errors[0] if result.errors else "Unknown error"` (or join all errors). Two locations:
- Line 495: `result.error` → format `result.errors`
- Line 565: `sync_result.error` → format `sync_result.errors`

Files: `src/db_adapter/cli/__init__.py` — `_async_sync()`

---

### 6. ~~Backup CLI~~ — Moved

> Moved to separate design: [core-cli-unify-design.md](core-cli-unify-design.md)
> Backup commands will be integrated as subcommands of the main `db-adapter` CLI.

---

### 7. Make `fix --schema-file` Optional with Config Default

**What**: `fix` requires `--schema-file` even though `config.schema_file` could serve as default.

**Why**: Redundant when db.toml already specifies the schema file. Inconsistent with the config-driven approach for `connect` and `validate`.

**Approach**:
1. Change `--schema-file` from `required=True` to `required=False, default=None`
2. In `_async_fix()`: if `--schema-file` provided, use it directly; otherwise, load config via `load_db_config()` (same pattern as #1/#2) and use `config.schema_file`
3. If neither available (no `--schema-file` flag AND `load_db_config()` raises `FileNotFoundError` or `config.schema_file` not set): produce a clear error like "No schema file: provide --schema-file or configure schema.file in db.toml"

Files: `src/db_adapter/cli/__init__.py` — `_async_fix()` + argparse

---

### 8. Dead Config: `schema_file` and `validate_on_connect`

**What**: `DatabaseConfig` has `schema_file` and `validate_on_connect` fields parsed from `db.toml`, but no CLI command reads them.

**Why**: These fields exist for exactly the purpose of items #1, #2, and #7. Wiring them in resolves the dead config issue automatically.

**Approach**:
Resolved by items #1, #2, and #7 — no separate work needed. Once `connect`, `validate`, and `fix` read these config fields, they're no longer dead.

Files: No additional changes needed.

---

### 9. Case Mismatch Cascades Into Fix Plan Failure

**What**: Bug #3's case mismatch cascades beyond validation into `generate_fix_plan()`. When `_parse_expected_columns` returns uppercase column names (e.g., `items.A`), the fix plan generation tries to look up `"items.A"` in the `column-defs.json` keys (which are lowercase: `"items.b"`). This fails with `"Unknown column definition for items.A"`, causing `_async_fix` to return exit code 1 on ALL databases — including a perfectly valid full DB.

**Why**: The `fix` command is completely broken. On a valid DB, it should report "no fixes needed" but instead errors out. On a drifted DB, it should generate ALTER/DROP plans but instead fails before generating any fixes.

**Approach**:
Resolved by Bug #3 fix — once `_parse_expected_columns` returns lowercase column names, the downstream lookup in `column-defs.json` will match correctly. No additional fix needed beyond #3.

**Live test evidence:**
```python
# _async_fix on VALID full DB:
# Expected: rc=0, "No fixes needed"
# Actual: rc=1, plan.error = "Unknown column definition for items.A"

# _async_fix on DRIFT DB:
# Expected: rc=0, fix plan with 5 ALTER/DROP operations
# Actual: rc=1, plan.error = "Unknown column definition for items.A"
```

Files: `src/db_adapter/cli/__init__.py` — `_async_fix()`, `src/db_adapter/schema/fix.py` — `generate_fix_plan()`

---

### 10. `importlib.reload()` Breaks Exception Class Identity in Tests

**What**: `test_lib_extraction_exports.py::TestNoCircularImports::test_import_order_config_then_factory` calls `importlib.reload()` on `db_adapter.factory`, which recreates `ProfileNotFoundError` as a new class object. `cli/__init__.py` still holds a stale module-level reference to the original class. After reload, `except ProfileNotFoundError:` in `_async_fix()` and `_async_sync()` silently fails to catch the new class — the exception propagates uncaught.

**Why**: 2 live integration tests (`test_fix_no_profile`, `test_sync_no_dest_profile`) fail only in the combined suite (553 unit + 120 live = 673 tests), pass in isolation. Without a fix, these tests require a workaround that obscures what they're actually testing.

**Approach**:
Replace `importlib.reload()` with non-destructive import checks in `TestNoCircularImports`. The reload tests intend to verify no circular imports exist — this can be done via subprocess isolation or by simply importing without reloading:

```python
# Before (breaks class identity across modules)
importlib.reload(importlib.import_module("db_adapter.factory"))

# After — Option A: import without reload (weaker — only verifies module names are valid;
# for already-loaded modules, returns cached module from sys.modules without re-executing)
importlib.import_module("db_adapter.config")
importlib.import_module("db_adapter.factory")

# After — Option B (Recommended): subprocess isolation (strongest guarantee, no side effects,
# actually tests import ordering in a fresh Python process)
subprocess.run([sys.executable, "-c", "import db_adapter.config; import db_adapter.factory"])
```

**Minimal reproduction:**
```bash
uv run pytest \
  tests/test_lib_extraction_exports.py::TestCliSubpackageImportable \
  tests/test_lib_extraction_exports.py::TestNoCircularImports::test_import_order_config_then_factory \
  tests/test_live_integration.py::TestAsyncFixDirect::test_fix_no_profile \
  --tb=short -v
# FAILS — remove any one of the three and it passes
```

**Detailed analysis**: [importlib-reload-class-identity.md](importlib-reload-class-identity.md)

Files: `tests/test_lib_extraction_exports.py` — `TestNoCircularImports`

---

## Proposed Sequence

> Shows dependencies and recommended order. Planning stage will create actual implementation steps.

**Order**: #4 → #3 → #1 → #2 → #5 → #7 → #10 → docs → tests

> Note: #6 moved to [core-cli-unify-design.md](core-cli-unify-design.md). #8 resolved by #1/#2/#7, #9 resolved by #3 — no separate sequence items needed.

### #4: Fix `connect_timeout` in AsyncPostgresAdapter

**Depends On**: None

**Rationale**: Foundation — the adapter must connect successfully before any other fix can be verified end-to-end. Without this, live integration tests for CRUD operations fail.

---

### #3: Fix Case Sensitivity in `_parse_expected_columns`

**Depends On**: None (can parallelize with #4)

**Rationale**: Small, surgical fix (add `.lower()` calls). Must be done before #1 and #2, because both use `_parse_expected_columns()` — without this fix, validation would report false drift.

---

### #1: Fix `connect` Command

**Depends On**: #3, #4

**Rationale**: `connect` is the entry point. Once case sensitivity and adapter connection work, `connect` can be wired to actually validate. Establishes the pattern for #2.

---

### #2: Fix `validate` Command

**Depends On**: #1, #3

**Rationale**: Same pattern as #1. Uses the lock file written by `connect`.

---

### #5: Fix Sync `.error` → `.errors`

**Depends On**: None (can parallelize with #1/#2)

**Rationale**: Small, surgical fix. Independent of the validation chain.

---

### #7: Make `fix --schema-file` Optional

**Depends On**: #1, #2, #3

**Rationale**: Same config-loading pattern. Lower priority since `fix` works with explicit `--schema-file`.

---

### #10: Fix `importlib.reload()` Test Interaction

**Depends On**: None (independent of production fixes)

**Rationale**: Can be done anytime, but best after all production fixes so the live test workarounds can be removed and replaced with clean assertions.

---

### Docs & Tests

**Depends On**: All above

**Rationale**: Documentation and test updates must reflect the final state of all fixes.

---

## Success Criteria

- [ ] `AsyncPostgresAdapter` connects without `connect_timeout` error (unblocks 14 xfailed tests)
- [ ] `_parse_expected_columns("schema.sql")` returns lowercase column names
- [ ] `connect` against full DB → "Schema validation: PASSED" (real validation)
- [ ] `connect` against drift DB → reports 5 missing columns (items: b,e,f + products: price,active)
- [ ] `connect` without schema file → honest "skipped" message
- [ ] `validate` against full DB → "Schema is valid"
- [ ] `validate` against drift DB → reports specific drift across multiple tables
- [ ] `sync` error path shows proper error message (no AttributeError)
- [ ] `fix` without `--schema-file` → uses config default
- [ ] `fix` against drift DB → shows correct fix plan (ALTER or DROP+CREATE)
- [ ] `TestNoCircularImports` no longer uses `importlib.reload()` — live test workarounds removed
- [ ] All 553 existing unit tests pass
- [ ] Live integration tests: 120 tests, 0 failures, xfails reduced from 16 to 0
- [ ] Combined coverage ≥ 78% (currently 75%, blocked by bugs; conservative target accounting for new config-loading code paths)
- [ ] README and CLAUDE.md match actual CLI behavior

---

## Implementation Options

### Option A: Config-Driven with CLI Override (Recommended)

`connect` and `validate` read `schema_file` from `DatabaseConfig`. CLI `--schema-file` flag overrides config.

**Pros**:
- Uses existing config infrastructure
- Zero-config for projects that follow convention (`schema.sql` in CWD)
- CLI override available when needed
- No changes to the library API — only CLI wrappers change

**Cons**:
- `connect` becomes slightly more complex (load config + check flags)

### Option B: Always Require `--schema-file` on CLI

**Pros**:
- Explicit

**Cons**:
- Ignores existing config infrastructure
- Verbose
- Inconsistent with how profiles/passwords work via db.toml

### Recommendation

Option A because: the config infrastructure already exists and is parsed. Using it is the natural design.

---

## Files to Modify

| File | Change | Complexity |
|------|--------|------------|
| `src/db_adapter/adapters/postgres.py` | Fix `connect_timeout` → asyncpg-compatible | Low |
| `src/db_adapter/cli/__init__.py` | Wire config into connect/validate/fix; fix .error→.errors; fix case sensitivity | High |
| `tests/test_lib_extraction_cli.py` | Add tests for config-driven validation, case sensitivity | Med |
| `tests/test_lib_extraction_exports.py` | Remove `importlib.reload()` from `TestNoCircularImports` | Low |
| `tests/test_live_integration.py` | Update xfail markers and expected results after fixes (120 tests already written) | Low |
| `README.md` | Update CLI Reference, add `[schema]` config docs | Low |
| `CLAUDE.md` | Update CLI Commands section | Low |

---

## Testing Strategy

### Current Coverage Baseline (combined: 553 unit + 120 live integration = 673 tests, 75% overall)

| Module | Coverage | Blocked By | Post-Fix Target |
|--------|----------|------------|-----------------|
| `adapters/postgres.py` | 50% | Bug #4 (connect_timeout) | 85%+ |
| `adapters/supabase.py` | 37% | No Supabase instance | N/A (optional extra) |
| `backup/backup_restore.py` | 97% | — | 97% |
| `cli/__init__.py` | 56% | Bugs #1-3, #5, #7, #9 | 70%+ |
| `config/loader.py` | 100% | — | 100% |
| `factory.py` | 95% | — | 95% |
| `schema/comparator.py` | 100% | — | 100% |
| `schema/fix.py` | 93% | — | 93% |
| `schema/introspector.py` | 91% | — | 91% |
| `schema/sync.py` | 91% | — | 91% |

> **Coverage target note**: The 78% overall target is driven primarily by unblocking `adapters/postgres.py` (50%→85%+) and `cli/__init__.py` (56%→70%+), which are the two largest coverage gaps blocked by bugs. New config-loading code paths in CLI commands will need corresponding unit tests to avoid dragging down the CLI coverage improvement.

### Live Integration Test Structure (120 tests across 32 test classes)

```
tests/test_live_integration.py
├── TestIntrospectorLive (8)         — SchemaIntrospector against real DBs
├── TestSchemaValidationLive (4)     — validate_schema with real introspected data
├── TestFactoryLive (8)              — connect_and_validate, resolve_url, profiles
├── TestAdapterLive (6)              — CRUD operations (5 xfail: Bug #4)
├── TestGetAdapterLive (3)           — get_adapter (3 xfail: Bug #4)
├── TestCLIConnectLive (5)           — CLI connect via subprocess
├── TestCLIValidateLive (3)          — CLI validate via subprocess
├── TestCLIStatusLive (2)            — CLI status
├── TestCLIProfilesLive (2)          — CLI profiles
├── TestCLIFixLive (3)               — CLI fix with schema.sql + column-defs.json
├── TestCLISyncLive (4)              — CLI sync argument validation
├── TestParseExpectedColumnsLive (5) — Case sensitivity bug demonstration
├── TestConfigLive (3)               — Config loading with real db.toml
├── TestSyncResultBug (2)            — .error vs .errors demonstration
├── TestBackupCLIBugs (4)            — Backup CLI signature mismatches (fix in core-cli-unify)
├── TestAdapterEngineBug (2)         — connect_timeout bug (1 xfail)
├── TestLockFileLive (3)             — Lock file operations
├── TestFixPlanLive (2)              — Fix plan generation with real schema
├── TestFKIntrospectionLive (5)      — FK relationship introspection
├── TestSyncLive (5)                 — Sync between profiles (5 xfail: Bug #4)
├── TestBackupModelsLive (2)         — BackupSchema model
├── TestFullSchemaDiffLive (2)       — Full vs drift comparison
├── TestCLIDirectCalls (4)           — Direct cmd_status, cmd_profiles calls
├── TestAsyncConnectDirect (4)       — Direct _async_connect calls
├── TestAsyncValidateDirect (3)      — Direct _async_validate calls
├── TestAsyncFixDirect (5)           — Direct _async_fix calls (Bug #9 demo)
├── TestAsyncSyncDirect (4)          — Direct _async_sync calls
├── TestCaseMismatchSeverity (2)     — Bug #3→#9 cascade demonstration
├── TestIntrospectorErrorPaths (6)   — RuntimeError paths, detailed introspection
├── TestBackupCLIDeeper (3)          — Backup CLI signature analysis (fix in core-cli-unify)
├── TestSchemaModelEdgeCases (3)     — format_report branches, ConnectionResult
└── TestFactoryEdgeCases (3)         — get_active_profile, ProfileNotFoundError
```

### Post-Fix Testing Plan

**Unit Tests** (mock-based, update existing + add new):
- `_parse_expected_columns` returns lowercase columns
- `connect` with mocked config → calls `connect_and_validate` with `expected_columns`
- `validate` with mocked config → performs real validation
- `fix` falls back to `config.schema_file`
- Sync error formatting works with `.errors` list

**Live Integration Tests** (update xfail markers after fixes):
- Bug #4 fixed → 14 xfail tests should start passing (adapter CRUD, sync, get_adapter)
- Bug #1 fixed → `test_connect_drift_succeeds` updated to expect drift report
- Bug #2 fixed → `test_validate_after_connect_full` updated to expect "valid"
- Bug #3 fixed → `test_case_mismatch_bug` updated to expect lowercase

**Manual Validation**:
- Run each CLI command against both test databases
- Verify output matches expected behavior

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Case sensitivity fix breaks existing tests | LOW | LOW | Only affects `_parse_expected_columns` which is CLI-internal; no existing tests pass uppercase column names |
| `connect_timeout` removal affects connection reliability | LOW | MED | SQLAlchemy's `pool_pre_ping=True` already handles stale connections; asyncpg has its own defaults |
| Config loading failure breaks connection-only mode | MED | HIGH | Catch `FileNotFoundError` gracefully — fall back to connect-only |
| `importlib.reload()` breaks exception class identity | CONFIRMED | MED | See [importlib-reload-class-identity.md](importlib-reload-class-identity.md). Workaround applied to live tests; permanent fix options documented |

---

## Open Questions

None — all questions resolved. Backup CLI moved to [core-cli-unify-design.md](core-cli-unify-design.md).

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Config-driven vs always-explicit | Config-driven with CLI override | Config infrastructure already exists; using it is natural |
| `sync --user-id` required | Keep as-is (not a bug) | Underlying API requires user_id for filtering |
| `connect_timeout` fix | Remove URL param, use connect_args or remove entirely | asyncpg doesn't recognize `connect_timeout` |
| Case sensitivity | Lowercase in parser | PostgreSQL folds unquoted identifiers to lowercase; parser must match |
| Backup CLI approach | Separate design doc | Moved to [core-cli-unify-design.md](core-cli-unify-design.md) — integrating as main CLI subcommands |
| `get_adapter()` ignoring `provider` | Out of scope | Separate enhancement, not a post-extraction bug |
| `importlib.reload()` test interaction | Workaround in live tests | Reload in export tests recreates `ProfileNotFoundError` class, breaking `except` in CLI. Detailed in [importlib-reload-class-identity.md](importlib-reload-class-identity.md) |

---

## Test Infrastructure (created during design)

**Test databases** (local PostgreSQL, `db.toml` gitignored):
- `db_adapter_full` — 3 tables: items (a-g, 5 rows), categories (3 rows), products (5 rows, FK→categories)
- `db_adapter_drift` — 3 tables: items (a,c,d,g, 5 rows), categories (2 rows), products (no price/active, 2 rows)

**Test support files** (checked in):
- `schema.sql` — expected schema with all 3 tables and FK constraint
- `column-defs.json` — column definitions for 5 drifted columns across items and products

**Live integration tests** (`tests/test_live_integration.py`):
- 120 tests across 32 test classes
- 104 passing, 16 xfailed (all blocked by Bug #4)
- Skip-if-no-DB guard: tests auto-skip if local databases aren't reachable
- Tests document all 9 bugs with explicit assertions proving each bug exists (plus backup CLI bugs tracked in core-cli-unify)
- Direct CLI function calls (not subprocess) for coverage measurement

**Known test interaction** — `importlib.reload()` class identity issue:
- `test_lib_extraction_exports.py::TestNoCircularImports::test_import_order_config_then_factory` reloads `db_adapter.factory`, recreating `ProfileNotFoundError` as a new class
- `cli/__init__.py` still holds its module-level reference to the old class
- `except ProfileNotFoundError:` in `_async_fix()` / `_async_sync()` fails to catch the new class
- Workaround: `test_fix_no_profile` and `test_sync_no_dest_profile` accept either `rc==1` or the uncaught exception
- Full analysis: [importlib-reload-class-identity.md](importlib-reload-class-identity.md)

## Next Steps

1. Review this design and confirm approach
2. Run `/review-doc` to check for issues
3. Create implementation plan (`/dev-plan`)
4. Execute implementation (`/dev-execute`)

# Review: Core-Hardening Plan

| Field | Value |
|-------|-------|
| **Document** | docs/core-hardening-plan.md |
| **Type** | Plan |
| **Created** | 2026-03-12T01:12:33-0700 |

---

## Step Summary

| # | Step | R1 | R2 |
|---|------|----|----|
| 0 | Add sqlparse Dependency | 1 HIGH | ✅ |
| 1 | CLI File Split -- Extract Functions into Sub-Modules | 2 LOW | 2 LOW |
| 2 | Migrate Mock Patch Targets in Test Files | 1 MED 2 LOW | ✅ |
| 3 | Restore Failure Details | ✅ | 1 LOW |
| 4 | Transaction Support -- Protocol and Adapter Implementation | 1 MED | 1 HIGH 1 LOW |
| 5 | Transaction Wrapping for Consumers | 1 HIGH 2 LOW | 1 LOW |
| 6 | FK Pre-Flight Warning in CLI Sync | 1 MED 1 LOW | 1 MED |
| 7 | SQL Parser Upgrade with sqlparse | ✅ | 2 LOW |
| 8 | Full Suite Validation | ✅ | 1 LOW |

> `...` = In Progress

---

## Step Details

### Step 0: Add sqlparse Dependency
**R1** (2026-03-12T01:12:33-0700, review-doc-run):
- [HIGH] (elevated from MED — also found by holistic reviewer) Step 0 duplicates Prerequisite #2 ("Install sqlparse Dependency") almost verbatim. Prerequisites section says "Complete these BEFORE starting implementation steps," so sqlparse install would already be done before Step 0 executes, making Step 0 redundant. -> Remove Prerequisite #2 and keep Step 0 as the canonical step, or convert Prerequisite #2 into a reference to Step 0.

**R2** (2026-03-13T10:15:35-0700, review-doc-run): Sound

### Step 1: CLI File Split -- Extract Functions into Sub-Modules
**R1** (2026-03-12T01:12:33-0700, review-doc-run):
- [LOW] `_schema_fix.py` specification says `_async_fix` uses `_EXCLUDED_TABLES`, `_print_table_counts`, `_get_table_row_counts` but none of these are used in `_async_fix`. They're only used in `_async_connect`/`_async_status`. -> Remove these from `_schema_fix.py` dependency list. Correct deps are: `console`, `_parse_expected_columns`, `_resolve_backup_schema_path`, `_load_backup_schema`, `_resolve_user_id`.
- [LOW] `_connection.py` specification lists `get_active_profile_name` as an import but none of the 7 functions assigned to `_connection.py` use it. It's used in `_async_fix` and `_async_sync`. -> Remove from `_connection.py` imports; belongs in `_schema_fix.py` and `_data_sync.py`.

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- [LOW] `_connection.py` specification lists `_EXCLUDED_TABLES` as an import from `_helpers`, but no function assigned to `_connection.py` references `_EXCLUDED_TABLES` directly — it is only used inside `_get_table_row_counts` which stays in `_helpers.py`. -> Remove `_EXCLUDED_TABLES` from `_connection.py` imports list in the specification.
- [LOW] Goal line says "23 functions" but `main` stays in `__init__.py` and is not extracted. Could be clearer about what moves vs stays. -> Minor — the specification body already clarifies `main` treatment. Consider rephrasing to "22 functions extracted + `main` retained" for precision.

### Step 2: Migrate Mock Patch Targets in Test Files
**R1** (2026-03-12T01:12:33-0700, review-doc-run):
- [MED] Patch mapping table lists `_schema_fix.read_profile_lock` and `_backup.read_profile_lock` as targets, but `read_profile_lock` is never called from `_async_fix` (uses `get_active_profile_name`) or backup functions. Correct sub-modules are `_connection` and `_data_sync` only. -> Replace with `db_adapter.cli._connection.read_profile_lock` and `db_adapter.cli._data_sync.read_profile_lock`. Remove `_schema_fix` and `_backup`.
- [LOW] Console mapping omits `_helpers.console`. `TestPrintTableCounts` (4 patches) tests `_print_table_counts` directly in `_helpers.py`, so target should be `db_adapter.cli._helpers.console`. -> Add `db_adapter.cli._helpers.console` to console mapping row.
- [LOW] Asyncio mapping lists `_connection.asyncio` first but all 3 asyncio patches test `cmd_backup`/`cmd_restore` in `_backup.py`. -> Change to `db_adapter.cli._backup.asyncio` as primary target.

**R2** (2026-03-13T10:15:35-0700, review-doc-run): Sound

### Step 3: Restore Failure Details
**R1** (2026-03-12T01:12:33-0700, review-doc-run): Sound

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- [LOW] Specification items 2 and 5 are duplicate instructions — both describe moving `old_pk` extraction before the `try` block and changing to `.get()` with `"<unknown>"` default. Item 5 adds rationale but an executor may be confused about whether these are two separate changes. -> Merge items 2 and 5 into a single specification item, or mark item 5 as a clarification note for item 2.

### Step 4: Transaction Support -- Protocol and Adapter Implementation
**R1** (2026-03-12T01:12:33-0700, review-doc-run):
- [MED] Existing test `test_protocol_has_exactly_six_methods` only counts `ast.AsyncFunctionDef` nodes and asserts exactly 6 async methods. Since `transaction()` is `def` (not `async def`), it technically passes unchanged, but the test's intent (verifying Protocol method count) becomes stale — Protocol now has 7 methods but test says 6. -> Either acknowledge this semantic drift in the specification or include updating this test to check for 6 async methods + 1 sync method.

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- [HIGH] Module-level `ContextVar` for `_transaction_conn` provides per-asyncio-task isolation but NOT per-adapter-instance isolation. When two `AsyncPostgresAdapter` instances exist in the same task (as in `_sync_direct()` at `sync.py:506-515`, which creates both source and dest adapters), one adapter's transaction connection would be visible to the other's CRUD methods, executing queries against the wrong database. -> Change `_transaction_conn` from module-level ContextVar to an instance attribute initialized in `__init__()`: `self._transaction_conn = contextvars.ContextVar(f"_transaction_conn_{id(self)}", default=None)`. Update all references to use `self._transaction_conn`.
- [LOW] Specification says "Add import for `AsyncContextManager` from `contextlib` (or `collections.abc`)" but neither module exports `AsyncContextManager`. The correct import is `from contextlib import AbstractAsyncContextManager`. -> Update import instruction to use `AbstractAsyncContextManager` from `contextlib`.

### Step 5: Transaction Wrapping for Consumers
**R1** (2026-03-12T01:12:33-0700, review-doc-run):
- [HIGH] (elevated from MED — also found by holistic reviewer) Verification command omits `tests/test_lib_extraction_sync.py` despite step modifying `_sync_direct()` in `sync.py`. -> Add `tests/test_lib_extraction_sync.py` to the Verification command.
- [LOW] Output line says "Backup and fix tests" but does not mention sync tests. -> Update to "Backup, fix, and sync tests passing with new transaction tests."
- [LOW] Specification for `_sync_direct()` hasattr() code duplication suggests "extract helper or flag-based approach" but doesn't specify which, unlike the detailed patterns for apply_fixes(). -> Add concrete pattern for sync helper extraction.

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- [LOW] [Recurring from R1 -- prior fix: added concrete `_insert_rows` helper extraction pattern; root cause: the helper's parameter list and return value handling remain underspecified] The `_insert_rows` helper signature shows `(adapter, table, source_rows, dest_slugs, ...)` but the current insert loop also reads/writes `result.skipped_count`, `result.synced_count`, and raises `ValueError` for FK violations. -> Add note that `_insert_rows` should also receive the `result` object to update counters, and that `ValueError` from FK violations should propagate out to trigger rollback.

### Step 6: FK Pre-Flight Warning in CLI Sync
**R1** (2026-03-12T01:12:33-0700, review-doc-run):
- [MED] Specification condition "when `schema` is `None`" references a variable that doesn't exist in current `_async_sync()`. Function never loads a BackupSchema. Executor must infer what `schema` means. Acceptance Criteria uses clearer language ("when backup_schema configured") but contradicts the spec's variable-based condition. -> Rewrite to: "When config.backup_schema is not configured, proceed with FK detection. Load BackupSchema via _load_backup_schema() if configured."
- [LOW] Specification doesn't explain how to resolve destination profile URL from profile name. Executor needs: config.profiles[dest] → DatabaseProfile → resolve_url(profile). Skip FK detection if config is None. -> Add note: "Use config.profiles[dest] + resolve_url() for URL. Skip if config is None."

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- [MED] Specification states "no BackupSchema means sync uses direct inserts, not backup/restore" implying `config.backup_schema` controls the sync path. This is factually incorrect: current `_async_sync()` (line 1038) calls `sync_data()` without a `schema` parameter, so direct inserts are always used regardless of `config.backup_schema`. The condition is reasonable as a heuristic (user has declared FK relationships) but the rationale is wrong. -> Either (a) add clarification that `config.backup_schema` is a proxy/heuristic for FK-aware setup, not a sync path determinant; or (b) add wiring to pass `backup_schema` to `sync_data()` so the condition is accurate.

### Step 7: SQL Parser Upgrade with sqlparse
**R1** (2026-03-12T01:12:33-0700, review-doc-run): Sound

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- [LOW] Specification says Parenthesis token body is "comment-free tokenized text" but sqlparse Parenthesis tokens still contain comment tokens within them — comments are tokenized, not stripped. Executor must actively skip comment tokens. -> Add note: "Strip comments from Parenthesis body via `sqlparse.format(str(parenthesis), strip_comments=True)` before line-splitting."
- [LOW] `statement.get_type() == 'CREATE'` matches all CREATE statements (INDEX, VIEW, FUNCTION, etc.), not just CREATE TABLE. The spec mentions "CREATE TABLE keywords" in point 2 but doesn't list TABLE keyword check as a distinct filtering step. -> Add explicit sub-step: "After confirming `get_type() == 'CREATE'`, verify the statement contains the TABLE keyword before attempting table name extraction."

### Step 8: Full Suite Validation
**R1** (2026-03-12T01:12:33-0700, review-doc-run): Sound

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- [LOW] Verification `grep 'db-adapter' pyproject.toml` matches multiple lines (project name and entry point). -> Use more specific pattern like `grep 'db_adapter.cli:main' pyproject.toml` to target only the entry point line.

---

## Holistic Summary

| Concern | R1 | R2 |
|---------|----|----|
| Template Alignment | ✅ | ✅ |
| Soundness | ✅ | ✅ |
| Flow & Dependencies | ✅ | ✅ |
| Contradictions | 2 MED 1 LOW | 1 MED 1 LOW |
| Clarity & Terminology | ✅ | 1 LOW |
| Surprises | 2 MED 2 LOW | 1 MED |
| Cross-References | ✅ | ✅ |

---

## Holistic Details

**R1** (2026-03-12T01:12:33-0700, review-doc-run):
- **[Contradictions]** [MED] Prerequisites #2 and Step 0 are duplicate work — both describe installing sqlparse with identical commands. If prerequisites are followed first, Step 0 is redundant. -> Remove Prerequisites #2 and keep Step 0, or vice versa.
- **[Contradictions]** [MED] Step 5 verification omits `test_lib_extraction_sync.py` despite wrapping `_sync_direct()` in transactions. -> Add sync test file to Step 5 verification command.
- **[Contradictions]** [LOW] Step 2 mapping table lists `cmd_*` targets with count "~15" but acceptance criteria says these don't need migration. Table entry could mislead executor. -> Clarify in the mapping table that cmd_* targets are NOT migrated (kept as-is).
- **[Surprises]** [MED] Step 5 wraps entire restore multi-table loop in single transaction. Long-running transaction concern from design review R1 is noted in Risks table but mitigation conflates restore and sync. -> Split mitigation: "Restore: acceptable for developer-scoped data. Sync: per-table granularity limits transaction size."
- **[Surprises]** [MED] Step 1 creates 5 new modules but Step 2 only updates `test_lib_extraction_cli.py`. Other test files (exports, imports) may need updates if they test CLI module structure. -> Verify whether exports/imports tests need patch target updates in Step 2.
- **[Surprises]** [LOW] Step 4 adds transaction() to Protocol (soft breaking change for type checking) but no mention of documentation or changelog update. -> Note in Step 4 that the Protocol change should be documented.
- **[Surprises]** [LOW] Step 6 FK pre-flight says "graceful degradation" but doesn't specify catch pattern or behavior. -> Specify: catch Exception broadly, skip warning silently or with debug-level log.

**R2** (2026-03-13T10:15:35-0700, review-doc-run):
- **[Contradictions]** [MED] Overview table says "no external API breaking changes" but Step 4 acknowledges adding `transaction()` to the Protocol is a "soft breaking change for type checking." -> Qualify the Overview statement: "No external API breaking changes at runtime; soft type-checking change for custom Protocol implementors."
- **[Contradictions]** [LOW] Step 1 re-export count of "24 symbols" differs from design's "25 symbols" (after R2 fix). The plan counts 24 re-exports excluding locally-defined `main`, which is functionally correct but numerically inconsistent with the design. -> Align wording: "24 re-exported symbols (plus `main` defined locally)."
- **[Clarity & Terminology]** [LOW] Step 2 individual patch counts use "~" prefix (~59, ~56, etc.) but the Goal states exact "178" total. Minor inconsistency. -> Either use "~178" in the Goal or remove "~" from component counts.
- **[Surprises]** [MED] Step 6 FK pre-flight warning creates an additional `SchemaIntrospector` database connection to the destination just for FK detection. This extra connection is not documented as a potential surprise — could fail with connection limits or credential issues. -> Add note in Step 6 Trade-offs that the extra connection is acceptable because FK detection is best-effort and the connection is short-lived.

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-12T01:12:33-0700 | review-doc-run | Parallel (9 item + 1 holistic) --auto | 2 HIGH 5 MED 12 LOW | Applied (19 of 19) |
| R2 | 2026-03-13T10:15:35-0700 | review-doc-run | Parallel (9 item + 1 holistic) --auto | 1 HIGH 3 MED 10 LOW | Applied (14 of 14) |

---

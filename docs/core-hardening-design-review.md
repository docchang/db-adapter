# Review: Core-Hardening Design

| Field | Value |
|-------|-------|
| **Document** | docs/core-hardening-design.md |
| **Type** | Task Design |
| **Created** | 2026-03-12T00:34:13-0700 |

---

## Item Summary

| # | Item | R1 | R2 |
|---|------|----|----|
| 1 | CLI File Split | 1 HIGH | 1 MED |
| 2 | Restore Failure Details | 1 MED | 1 LOW |
| 3 | Transaction Support | 1 HIGH 1 LOW | ✅ |
| 4 | SQL Parser Upgrade | 1 LOW | 1 LOW |

> `...` = In Progress

---

## Item Details

### Item 1: CLI File Split
**R1** (2026-03-12T00:34:13-0700, review-doc-run):
- [HIGH] "Zero test changes" claim is incorrect. Tests use `patch("db_adapter.cli.console", ...)` (~55 occurrences), `patch("db_adapter.cli.load_db_config", ...)` (~40 occurrences), `patch("db_adapter.cli.read_profile_lock", ...)` (~30 occurrences), etc. After the split, sub-modules import these names directly, so patching the `db_adapter.cli` binding in `__init__.py` won't affect the code under test. This is a fundamental Python mock constraint: `patch()` must target where the name is looked up, not where it's defined. -> Add a section addressing mock `patch()` targets. The correct approach is to update ~130+ test patch paths to target sub-modules (e.g., `db_adapter.cli._connection.load_db_config`). Acknowledge the test changes are required and estimate the scope. Update the "zero test changes" claim accordingly.

**R2** (2026-03-12T00:51:28-0700, review-doc-run):
- [MED] (elevated from LOW — also found by holistic reviewer) Mock `patch()` target migration section states "~130+ occurrences" but actual count is 178 occurrences in `tests/test_lib_extraction_cli.py`. While "~130+" is technically not wrong, it understates the migration volume by ~37%. -> Update to "~180 occurrences" or "~178 occurrences" for a more accurate implementation estimate.

### Item 2: Restore Failure Details
**R1** (2026-03-12T00:34:13-0700, review-doc-run):
- [MED] `old_pk` reference in except block may be undefined or stale. If the exception occurs at `old_pk = row[table_def.pk]` (first statement in try), `old_pk` is either unset (first iteration → `NameError`) or holds previous row's value (subsequent iterations → incorrect data). -> Initialize `old_pk` before the try block: `old_pk = row.get(table_def.pk, "<unknown>")` as the first line before `try:`, so it is always defined.

**R2** (2026-03-12T00:51:28-0700, review-doc-run):
- [LOW] "This is the only silent exception handler in the codebase" is inaccurate. `cli/__init__.py` has 8+ `except Exception:` handlers (lines 130, 388, 504, 615, 918, 1293, 1415, 1567) that silently discard exceptions. These are graceful-degradation handlers for config loading (different category), but the literal claim is false. -> Qualify: "This is the only silent exception handler for data operations in the codebase" or "the only handler that discards actionable error details."

### Item 3: Transaction Support
**R1** (2026-03-12T00:34:13-0700, review-doc-run):
- [HIGH] Phase 1 says only `insert`, `update`, `delete`, `execute` check `_transaction_conn`, excluding `select`. Phase 2 claims backup callback SELECTs and restore existence-check SELECTs share the transaction connection in `apply_fixes()`. Since `backup_database()` calls `adapter.select()` (line 119) and `_restore_table()` calls `adapter.select()` (line 303), these reads will NOT use the transaction connection unless `select` is also made ContextVar-aware. This breaks the atomicity guarantee for `apply_fixes()`. -> Add `select` to the list of methods that check `_transaction_conn` in Phase 1. The sentence should read: "CRUD methods (`select`, `insert`, `update`, `delete`, `execute`) check `_transaction_conn.get(None)`".
- [LOW] The ContextVar type annotation `AsyncConnection` is ambiguous — the codebase uses both `psycopg.AsyncConnection` (in CLI and introspector) and SQLAlchemy's `AsyncConnection` (implicit in `postgres.py` via `engine.begin()`). -> Qualify the type: `contextvars.ContextVar[sqlalchemy.ext.asyncio.AsyncConnection | None]` to avoid confusion during implementation.

**R2** (2026-03-12T00:51:28-0700, review-doc-run): Sound

### Item 4: SQL Parser Upgrade
**R1** (2026-03-12T00:34:13-0700, review-doc-run):
- [LOW] `_get_table_create_sql` description does not address how the `table_name` parameter will be matched against the sqlparse-extracted name. The current regex interpolates `table_name` directly into the pattern, and the caller may pass a bare name like `"users"` while the SQL has `public.users` or `"Users"`. -> Add a brief note on the matching strategy: compare the sqlparse-extracted table name (after stripping schema prefix and quotes, lowercased) against the provided `table_name` (also lowercased).

**R2** (2026-03-12T00:51:28-0700, review-doc-run):
- [LOW] Design says "stripping schema prefix via `get_name()`" but the correct sqlparse method for extracting the unqualified table name from a schema-qualified identifier is `get_real_name()`. `get_name()` returns the alias if present, otherwise delegates to `get_real_name()`. In CREATE TABLE context (no alias) the result is the same, but referencing the wrong method could mislead the implementor. -> Change "stripping schema prefix via `get_name()`" to "stripping schema prefix via `get_real_name()`".

---

## Holistic Summary

| Concern | R1 | R2 |
|---------|----|----|
| Template Alignment | ✅ | ✅ |
| Soundness | ✅ | 1 LOW |
| Flow & Dependencies | ✅ | ✅ |
| Contradictions | 1 HIGH | 2 MED |
| Clarity & Terminology | ✅ | ✅ |
| Surprises | 1 MED 1 LOW | ✅ |
| Cross-References | 1 LOW | ✅ |

---

## Holistic Details

**R1** (2026-03-12T00:34:13-0700, review-doc-run):
- **[Contradictions]** [HIGH] (elevated from MED — also found by Item 3 reviewer) Analysis #3 lists "CRUD methods (`insert`, `update`, `delete`, `execute`) check `_transaction_conn.get(None)`" but omits `select()`. The `apply_fixes()` transaction wrapper calls backup callbacks that use `select()` to read table data before DROP. If `select()` does not participate in the transaction, it may use a separate connection and could fail or see stale data. -> Add `select()` to the explicit list of methods that check `_transaction_conn`. All 5 async methods on the Protocol should honor the transaction connection when active.
- **[Surprises]** [MED] The design wraps the entire `restore_database()` multi-table loop in a single transaction. For large restores (many tables, many rows), this creates a long-running transaction holding locks and accumulating WAL. No discussion of transaction size limits or batching. -> Add a note in Analysis #3 or Risks & Mitigations discussing the long-transaction trade-off. Consider whether per-table transactions might be more practical for large datasets. At minimum, document the dataset size expectation.
- **[Surprises]** [LOW] `_EXCLUDED_TABLES` is re-exported as a public symbol from the CLI package (prefixed with underscore, suggesting internal use). Unusual pattern to publicly re-export an underscore-prefixed symbol. -> Minor, no fix required. Document that this is preserved for test compatibility. [Skipped: no fix required per suggestion]
- **[Cross-References]** [LOW] No parent task-spec or milestone-spec found for this design. The examiner audit serves as the upstream source but formal scope definition is missing. -> Document that the examiner audit serves as the upstream specification, or create a task-spec if the project uses that workflow.

**R2** (2026-03-12T00:51:28-0700, review-doc-run):
- **[Contradictions]** [MED] Re-export count of "24 symbols (23 functions + `_EXCLUDED_TABLES`)" may be incomplete. `console = Console()` is extensively patched in tests via `db_adapter.cli.console` (part of 178 occurrences) but is not counted among the 24 re-exported symbols. If `console` is not re-exported from `__init__.py`, tests patching `db_adapter.cli.console` will break. -> Verify whether `console` needs to be in the re-export list. If yes, update count to 25 symbols. If no (because all `console` patches will be migrated to sub-module targets), state this explicitly.
- **[Contradictions]** [MED] (elevated from LOW — also found by Item 1 reviewer) Mock patch target count stated as "~130+" but actual count is 178 occurrences. The 35% underestimate could affect planning effort estimates. -> Update to "~180" or "~175+" to reflect actual count.
- **[Soundness]** [LOW] `select()` currently uses `engine.connect()` (read-only, no begin/commit) while all other CRUD methods use `engine.begin()`. The design correctly includes `select` in the `_transaction_conn` check list but does not call out this asymmetry. The implementation will need to handle it: shared connection inside transaction, `connect()` outside. -> Add a brief note in Phase 1 that `select()` currently uses `engine.connect()` (not `engine.begin()`) and the `_transaction_conn` check preserves this distinction.

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-12T00:40:00-0700 | review-doc-run | Parallel (4 item + 1 holistic) --auto | 2 HIGH 2 MED 4 LOW | Applied (7 of 8) |
| R2 | 2026-03-12T00:51:28-0700 | review-doc-run | Parallel (4 item + 1 holistic) --auto | 3 MED 3 LOW | Applied (6 of 6) |

---

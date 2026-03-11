# Review: core-cli-fix Design

| Field | Value |
|-------|-------|
| **Document** | docs/core-cli-fix-design.md |
| **Type** | Task Design |
| **Created** | 2026-03-10T17:53:31-0700 |

---

## Item Summary

| # | Item | R1 | R2 | R3 |
|---|------|----|----|-----|
| 1 | `connect` Prints "PASSED" Without Validating | ✅ | ✅ | 1 MED 1 LOW |
| 2 | `validate` Always Reports Drift | ✅ | ✅ | ✅ |
| 3 | `_parse_expected_columns` Case Mismatch | 1 LOW | 1 LOW | ✅ |
| 4 | AsyncPostgresAdapter `connect_timeout` Rejected | ✅ | 2 LOW | ✅ |
| 5 | Sync CLI Uses `.error` but Model Has `.errors` | ✅ | ✅ | ✅ |
| 6 | Backup CLI Is Completely Non-Functional | ✅ | ✅ | ✅ |
| 7 | Make `fix --schema-file` Optional with Config Default | ✅ | 1 MED 1 LOW | 1 MED |
| 8 | Dead Config: `schema_file` and `validate_on_connect` | ✅ | ✅ | ✅ |
| 9 | Case Mismatch Cascades Into Fix Plan Failure | ✅ | ✅ | ✅ |
| 10 | `importlib.reload()` Breaks Exception Class Identity | — | 1 MED | ✅ |

> `...` = In Progress

---

## Item Details

### Item 1: `connect` Prints "PASSED" Without Validating
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run): Sound
**R3** (2026-03-10T18:18:00-0700, review-doc-run):
- [MED] Approach step 1 says "Load config via `load_db_config()`" but does not specify what happens when `db.toml` itself is missing (`FileNotFoundError`). The Risks table mentions this scenario generically but the item's approach doesn't handle it. Item #7 explicitly catches `FileNotFoundError` but item #1 does not. -> Add to approach: "If `load_db_config()` raises `FileNotFoundError` (no db.toml), fall back to connect-only mode with message: 'Connected (no config found — schema validation skipped)'"
- [LOW] Behavioral note says "if a schema file is present, validation should run" but doesn't clarify handling for unreadable or unparseable schema files (e.g., invalid SQL). -> Add note that `_parse_expected_columns()` errors (ValueError, FileNotFoundError) should be caught and treated as "schema file missing" with a warning.

### Item 2: `validate` Always Reports Drift
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run): Sound
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

### Item 3: `_parse_expected_columns` Case Mismatch
**R1** (2026-03-10T17:53:31-0700, review-doc-run):
- [LOW] Approach does not mention the edge case of double-quoted SQL identifiers (e.g., `"MyColumn"`) where PostgreSQL preserves case; adding `.lower()` unconditionally would be wrong for quoted identifiers -> Add a brief note that quoted identifiers are out of scope, or strip double quotes before lowercasing. LOW severity because the parser already does not handle quoted identifiers and the constraint says `_parse_expected_columns()` stays CLI-internal.
**R2** (2026-03-10T18:02:56-0700, review-doc-run):
- [LOW] Live test evidence shows `categories: {'Id', 'Slug', 'Name', 'User_id'}` and `products: {'Id', ...}` with title-case, but current `schema.sql` has all-lowercase columns for `categories` and `products` (only `items` uses uppercase `A-G`). Evidence appears from a prior schema version. -> Update the evidence to reflect current `schema.sql`, or note the evidence was captured from a different schema version. The bug itself remains valid for the `items` table.
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

### Item 4: AsyncPostgresAdapter `connect_timeout` Rejected
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run):
- [LOW] Approach uses `connect_args={"timeout": 5}` but the error message suggests `command_timeout`. These are different asyncpg parameters (`timeout` = connection, `command_timeout` = query). The design uses the correct one but the juxtaposition could confuse implementers. -> Add a clarifying note that `timeout` is correct, not `command_timeout`, despite the error message suggestion.
- [LOW] Existing unit test `test_appends_connect_timeout` in `test_lib_extraction_adapters.py` asserts the current buggy behavior. This test must be updated but the design doesn't mention it. -> Note that `test_appends_connect_timeout` must be updated to verify new behavior.
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

### Item 5: Sync CLI Uses `.error` but Model Has `.errors`
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run): Sound
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

### Item 6: Backup CLI Is Completely Non-Functional
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run): Sound
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

### Item 7: Make `fix --schema-file` Optional with Config Default
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run):
- [MED] Approach references `config.schema_file` but `_async_fix()` currently has no `load_db_config()` call. The approach does not mention adding this call, which is a prerequisite for the fallback to work. While items #1/#2 establish this pattern, reading this item alone would produce an incomplete implementation. -> Add an explicit step: "Load config via `load_db_config()` (same pattern as #1/#2)" before the fallback logic, or note that the config-loading code from #1/#2 is a prerequisite.
- [LOW] "If neither available: clear error message" does not specify handling `FileNotFoundError` from `load_db_config()` itself. If `--schema-file` is omitted and `db.toml` is absent, the fallback path will fail. -> Clarify that step 3 should also catch `FileNotFoundError` from `load_db_config()` and produce a clear error like "No schema file: provide --schema-file or configure schema.file in db.toml".
**R3** (2026-03-10T18:18:00-0700, review-doc-run):
- [MED] Execution order is ambiguous: should `load_db_config()` be called unconditionally (then fall back to `--schema-file`), or conditionally (only if `--schema-file` not provided)? The approach says "If `--schema-file` not provided, fall back to `config.schema_file`" but doesn't specify whether config is loaded first or on demand. -> Clarify execution order: "If `--schema-file` provided, use it directly; otherwise, load config via `load_db_config()` and use `config.schema_file`" (conditional loading is more efficient and clearer).

### Item 8: Dead Config: `schema_file` and `validate_on_connect`
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run): Sound
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

### Item 9: Case Mismatch Cascades Into Fix Plan Failure
**R1** (2026-03-10T17:53:31-0700, review-doc-run): Sound
**R2** (2026-03-10T18:02:56-0700, review-doc-run): Sound
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

### Item 10: `importlib.reload()` Breaks Exception Class Identity
**R2** (2026-03-10T18:02:56-0700, review-doc-run):
- [MED] Option A (`importlib.import_module` without reload) is described as "sufficient for circular import check" but for already-loaded modules it returns the cached module from `sys.modules` without re-executing any code — effectively a no-op. -> Revise Option A description to note this limitation. Recommend Option B (subprocess isolation) as the primary approach that maintains the original test's intent, or acknowledge Option A is a weaker test that only verifies module names are valid.
**R3** (2026-03-10T18:18:00-0700, review-doc-run): Sound

---

## Holistic Summary

| Concern | R1 | R2 | R3 |
|---------|----|----|-----|
| Template Alignment | ✅ | ✅ | ✅ |
| Soundness | ✅ | ✅ | ✅ |
| Flow & Dependencies | ✅ | ✅ | 1 LOW |
| Contradictions | ✅ | 2 LOW | ✅ |
| Clarity & Terminology | ✅ | ✅ | 1 LOW |
| Surprises | 1 MED 2 LOW | ✅ | ✅ |
| Cross-References | ✅ | 1 LOW | ✅ |

---

## Holistic Details

**R1** (2026-03-10T17:57:55-0700, review-doc-run):
- **[Surprises]** [MED] Default `validate_on_connect=True` and `schema_file="schema.sql"` in `DatabaseConfig` means users who never configured these fields will suddenly experience validation on `connect` if `schema.sql` happens to exist in CWD. The design mentions catching `FileNotFoundError` but does not address the case where `schema.sql` exists incidentally and validation runs unexpectedly. -> Add explicit handling: if `schema_file` was never set in `db.toml` (i.e., using the default), consider checking whether the file actually defines tables relevant to the connected database, or document this behavior change clearly. At minimum, note this as a behavioral change in the design.
- **[Surprises]** [LOW] The Files to Modify table row for `cli/backup.py` says "Fix async calls, parameter mismatches, or document as reference" — the "or" is ambiguous. Decisions Log says "Document as reference (Option A)." -> Update the Files to Modify table to match the decision: "Document as reference; add header/docstring noting it is a template, not a runnable CLI"
- **[Surprises]** [LOW] "Combined coverage >= 80% (currently 75%, blocked by bugs)" — this criterion may be difficult to achieve solely from bug fixes. New config-loading logic adds new code paths that need corresponding tests. -> Clarify whether the 80% target accounts for new code paths, or revise to a more conservative target.

**R2** (2026-03-10T18:02:56-0700, review-doc-run):
- **[Contradictions]** [LOW] Testing Strategy says "553 unit + 120 live = 673 tests" (line 499) but Item #10 says "combined suite (657 tests)" (line 320). Numbers do not reconcile. -> Verify actual combined count and use a single consistent number, or clarify that 657 refers to a different subset.
- **[Contradictions]** [LOW] Document states "27 test classes" (lines 517, 617) but the tree structure enumerates 32 classes. -> Update both occurrences from "27 test classes" to "32 test classes".
- **[Cross-References]** [LOW] Item #10 modifies `tests/test_lib_extraction_exports.py` (per line 349) but this file is absent from the Files to Modify summary table. -> Add a row for this file.

**R3** (2026-03-10T18:18:00-0700, review-doc-run):
- **[Flow & Dependencies]** [LOW] Bug #9 is listed in bug inventory as CRITICAL (line 44) but missing from Proposed Sequence order text (line 363: "#4 → #3 → #1 → #2 → #5 → #7 → #6 → #10 → docs → tests"). Analysis #9 correctly says it's resolved by #3, but the sequence text should note this explicitly. -> Add clarifying text after the order line: "Note: #8 resolved by #1/#2/#7, #9 resolved by #3 — no separate sequence items needed."
- **[Clarity & Terminology]** [LOW] Success Criteria targets "Combined coverage >= 78%" but the per-module coverage improvements in Testing Strategy (postgres.py 50%→85%, cli/__init__.py 56%→70%, cli/backup.py 11%→50%) are not correlated to the overall target. -> Add brief note explaining which module improvements drive the 78% target.

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-10T17:57:55-0700 | review-doc-run | Parallel (9 item + 1 holistic) | 1 MED 3 LOW | Applied (4 of 4) |
| R2 | 2026-03-10T18:02:56-0700 | review-doc-run | Parallel (10 item + 1 holistic) --auto | 2 MED 8 LOW | Applied (10 of 10) |
| R3 | 2026-03-10T18:18:00-0700 | review-doc-run | Parallel (10 item + 1 holistic) --auto | 2 MED 3 LOW | Applied (5 of 5) |

---

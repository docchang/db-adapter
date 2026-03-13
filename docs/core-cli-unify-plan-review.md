# Review: core-cli-unify Plan

| Field | Value |
|-------|-------|
| **Document** | docs/core-cli-unify-plan.md |
| **Type** | Plan |
| **Created** | 2026-03-10T22:08:38-0700 |

---

## Step Summary

| # | Step | R1 | R2 |
|---|------|----|----|
| 0 | Baseline Verification | 1 MED | ✅ |
| 1 | Config Model -- Add New Fields to DatabaseConfig | ✅ | ✅ |
| 2 | Config Loader -- Parse New Sections from db.toml | ✅ | ✅ |
| 3 | CLI Config Defaults for Fix Command | ✅ | ✅ |
| 4 | CLI Config Defaults for Sync Command and Shared user_id Resolution | 1 HIGH 1 LOW | ✅ |
| 5 | BackupSchema Loading and Resolution Helpers | ✅ | 1 LOW |
| 6 | Add backup/restore Subcommand Parsers and Sync Wrappers | ✅ | ✅ |
| 7 | Async Wiring for Backup Commands | 1 MED 1 LOW | ✅ |
| 8 | Auto-Backup Before Fix | 1 HIGH | ✅ |
| 9 | Retire Standalone cli/backup.py and Update Tests | ✅ | ✅ |
| 10 | Update Documentation | 1 MED 2 LOW | ✅ |
| 11 | Final Integration Validation | 1 MED 1 LOW | ✅ |

> `...` = In Progress

---

## Step Details

### Step 0: Baseline Verification
**R1** (2026-03-10T22:08:38-0700, review-doc-run):
- [MED] Checklist item 2 says "Run full suite to establish baseline" but neither Code nor Verification sections include a full suite command (`uv run pytest tests/`). Only 4 specific test files are run. -> Either add `uv run pytest tests/ -v --tb=short` to the Code/Verification sections, or remove the "Run full suite" checklist item.

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound. R1 MED issue resolved -- checklist now reads "Run affected test files and confirm all pass" which matches the commands.

### Step 1: Config Model -- Add New Fields to DatabaseConfig
**R1** (2026-03-10T22:08:38-0700, review-doc-run): Sound

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound

### Step 2: Config Loader -- Parse New Sections from db.toml
**R1** (2026-03-10T22:08:38-0700, review-doc-run): Sound

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound

### Step 3: CLI Config Defaults for Fix Command
**R1** (2026-03-10T22:08:38-0700, review-doc-run): Sound

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound

### Step 4: CLI Config Defaults for Sync Command and Shared user_id Resolution
**R1** (2026-03-10T22:08:38-0700, review-doc-run):
- [HIGH] (elevated from MED -- also in holistic Cross-References) `_resolve_user_id()` spec says "checks `args.user_id` first" using direct attribute access, but design doc (Analysis #5) specifies `getattr(args, "user_id", None)` for safe access. Direct `args.user_id` will raise `AttributeError` when called from fix auto-backup (Step 8), where fix subparser has no `--user-id` argument. -> Change to `getattr(args, "user_id", None)` in the specification, matching the design doc.
- [LOW] Step does not clarify the type difference between `args.tables` (comma-separated string needing `.split(",")`) and `config.sync_tables` (`list[str]`). Executor may not handle both sources correctly. -> Add note: "When tables come from CLI, split comma-separated string; when from config.sync_tables, use list directly."

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound. Both R1 issues resolved -- spec now uses `getattr(args, "user_id", None)` and documents the type difference between CLI string and config list sources.

### Step 5: BackupSchema Loading and Resolution Helpers
**R1** (2026-03-10T22:08:38-0700, review-doc-run): Sound

**R2** (2026-03-10T22:20:55-0700, review-doc-run):
- [LOW] Step specifies adding `from db_adapter.backup.models import BackupSchema` but does not mention that `DatabaseConfig` must also be imported for the `_resolve_backup_schema_path` type annotation (`config: DatabaseConfig | None`). Step 4 also omits this import. -> Add note that `DatabaseConfig` import is expected from Step 4, or add `from db_adapter.config.models import DatabaseConfig` to this step's import list.

### Step 6: Add backup/restore Subcommand Parsers and Sync Wrappers
**R1** (2026-03-10T22:08:38-0700, review-doc-run): Sound

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound

### Step 7: Async Wiring for Backup Commands
**R1** (2026-03-10T22:08:38-0700, review-doc-run):
- [MED] (elevated from LOW -- also in holistic Surprises) Specification says "following the existing pattern (e.g., `_async_fix`)" for try/finally adapter close, but `_async_fix` does not close the adapter at all (no try/finally). The step introduces a new, better pattern rather than following the existing one. -> Rephrase to "improving on the existing pattern" or note that `_async_fix` lacks adapter cleanup.
- [LOW] Test items (8) and (9) cover valid/invalid backup file for `_validate_backup` but do not cover the error path where backup_schema is not available (neither CLI nor config). `_async_backup` has this test but `_validate_backup` does not. -> Add test case: `_validate_backup` with missing backup_schema returns 1.

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound. Both R1 issues resolved -- phrasing now says "improving on `_async_fix`" and test case (11) covers `_validate_backup` with missing backup_schema.

### Step 8: Auto-Backup Before Fix
**R1** (2026-03-10T22:08:38-0700, review-doc-run):
- [HIGH] (elevated from MED -- also in holistic Cross-References) Step assumes `_resolve_user_id` uses `getattr(args, "user_id", None)` for safe access on the fix namespace (which lacks `--user-id`), but Step 4 specifies direct `args.user_id` access. If Step 4 implements direct access, calling from `_async_fix()` will raise `AttributeError`. -> Fix in Step 4: specify `getattr(args, "user_id", None)` instead of direct `args.user_id` (shared helper must be safe across all subparsers). [Skipped: root cause fixed in Step 4]

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound. R1 HIGH resolved -- Step 4 now uses `getattr`. Also confirmed: `backups/` dir creation and adapter try/finally notes were added per R1 holistic fixes.

### Step 9: Retire Standalone cli/backup.py and Update Tests
**R1** (2026-03-10T22:08:38-0700, review-doc-run): Sound

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound

### Step 10: Update Documentation
**R1** (2026-03-10T22:08:38-0700, review-doc-run):
- [MED] README.md specification does not mention updating the Architecture file structure tree (line 257) which lists `backup.py -- Standalone backup CLI` and `cli/__init__.py` with only 6 subcommands. After Step 9 deletes backup.py, this tree would be stale. -> Add: "Update Architecture file structure tree to remove `backup.py` entry and update `cli/__init__.py` description to list all 8 subcommands."
- [LOW] README.md specification does not mention updating the feature list at line 16 (`**CLI** -- db-adapter connect|status|profiles|validate|fix|sync`) to include `backup` and `restore`. -> Add to README.md spec: "Update the features list to show all 8 subcommands." [Skipped: combined with MED fix above]
- [LOW] Tests note "module docstring is checked by some AST tests" is misleading -- the AST docstring test inspects `cli/backup.py`'s docstring, not `cli/__init__.py`'s. Tests that read `cli/__init__.py` are negative string checks. -> Clarify: "Tests check for absence of MC-specific strings; docstring update must not introduce prohibited strings." [Skipped: combined with MED fix above]

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound. All R1 issues resolved -- README spec now includes architecture tree update, features list update, and test note clarified.

### Step 11: Final Integration Validation
**R1** (2026-03-10T22:08:38-0700, review-doc-run):
- [MED] Specification says "Verify CLI help output shows all 8 subcommands" but does not list them explicitly. Executor would need to look elsewhere to know the expected set. -> Add explicit list: "Verify CLI help output shows all 8 subcommands: connect, status, profiles, validate, fix, sync, backup, restore."
- [LOW] Acceptance Criteria list only 3 checks but do not reference the plan's 16 overall Success Criteria. -> Add a fourth criterion: "All plan-level Success Criteria verified (by passing tests or manual spot-check)."

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound. Both R1 issues resolved -- subcommands listed explicitly and acceptance criteria now references plan-level success criteria.

---

## Holistic Summary

| Concern | R1 | R2 |
|---------|----|----|
| Template Alignment | ✅ | ✅ |
| Soundness | ✅ | ✅ |
| Flow & Dependencies | ✅ | ✅ |
| Contradictions | ✅ | ✅ |
| Clarity & Terminology | ✅ | ✅ |
| Surprises | 2 MED | ✅ |
| Cross-References | 1 MED | ✅ |

---

## Holistic Details

**R1** (2026-03-10T22:08:38-0700, review-doc-run):
- **[Surprises]** [MED] Step 8 auto-backup output path `backups/pre-fix-{profile}-{timestamp}.json` uses relative path but does not mention ensuring the `backups/` directory exists. If `backup_database()` does not create intermediate directories, this raises `FileNotFoundError`. -> Add note to Step 8: "Ensure `backups/` directory exists before calling `backup_database()` (e.g., `Path('backups').mkdir(exist_ok=True)`)." Or verify `backup_database()` creates the directory.
- **[Surprises]** [MED] (elevated from LOW -- also in Step 7 item) Step 8 adapter in `_async_fix()` is not wrapped in try/finally for cleanup, which contradicts the Design's constraint "Use try/finally pattern consistently" and Step 7's acceptance criteria. -> Add note to Step 8 that adapter should be wrapped in try/finally, or note this as existing limitation out of scope.
- **[Cross-References]** [MED] (elevated from LOW -- also in Steps 4, 8 items) Step 4 `_resolve_user_id` specification uses `args.user_id` (direct access) but Design Analysis #5 pseudocode uses `getattr(args, "user_id", None)`. Step 5's `_resolve_backup_schema_path` correctly uses `getattr`. Inconsistency in Step 4 may cause `AttributeError` when called from Step 8's fix auto-backup. -> Align Step 4 with Design by using `getattr(args, "user_id", None)`. [Skipped: root cause fixed in Step 4]

**R2** (2026-03-10T22:20:55-0700, review-doc-run): Sound. All R1 holistic issues resolved: `backups/` dir creation note added to Step 8, try/finally note added to Step 8, `getattr` fix applied in Step 4. Full cross-reference alignment with design doc and source code confirmed.

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-10T22:16:48-0700 | review-doc-run | Parallel (12 item + 1 holistic) --auto | 2 HIGH 6 MED 5 LOW | Applied (10 of 13) |
| R2 | 2026-03-10T22:27:21-0700 | review-doc-run | Parallel (12 item + 1 holistic) --auto | 1 LOW | Applied (1 of 1) |

---

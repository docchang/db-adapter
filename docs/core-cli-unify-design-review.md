# Review: core-cli-unify Design

| Field | Value |
|-------|-------|
| **Document** | docs/core-cli-unify-design.md |
| **Type** | Task Design |
| **Created** | 2026-03-10T21:29:22-0700 |

---

## Item Summary

| # | Item | R1 | R2 | R3 |
|---|------|----|----|-----|
| 1 | Config Defaults for Fix Command (`column_defs`) | ✅ | 1 HIGH | ✅ |
| 2 | Config Defaults for Sync Command (`tables`) and Shared `user_id_env` | 1 MED | ✅ | ✅ |
| 3 | BackupSchema Sourcing via JSON File | ✅ | ✅ | ✅ |
| 4 | Add backup/restore Subcommands | 1 MED | ✅ | 3 LOW |
| 5 | Async Wiring for Backup Commands | 1 HIGH 1 MED | 1 MED | 1 LOW |
| 6 | Auto-Backup Before Fix | 1 HIGH 1 MED 1 LOW | 1 MED | 1 MED |
| 7 | Retire Standalone cli/backup.py | 1 HIGH | 3 HIGH | 1 LOW |
| 8 | Update Public Exports and Documentation | ✅ | ✅ | 1 MED 1 LOW |

> `...` = In Progress

---

## Item Details

### Item 1: Config Defaults for Fix Command (`column_defs`)
**R1** (2026-03-10T21:29:22-0700, review-doc-run): Sound
**R2** (2026-03-10T21:37:21-0700, review-doc-run):
- [MED->HIGH] The item claims the `column_defs` fallback "follows exact pattern of `schema_file` fallback" but does not note that `_async_fix()` currently loads `config` only conditionally (inside `if schema_file is None:`). If `--schema-file` is provided but `--column-defs` is omitted, `config` is never loaded and the `column_defs` fallback will fail. -> Add a note to the Approach stating that `_async_fix()` config loading must be restructured to load config whenever either `schema_file` or `column_defs` needs a fallback (not just when `schema_file is None`). [Elevated: also flagged in holistic review]
**R3** (2026-03-10T21:54:37-0700, review-doc-run): Sound
- [MED->HIGH] The item claims the `column_defs` fallback "follows exact pattern of `schema_file` fallback" but does not note that `_async_fix()` currently loads `config` only conditionally (inside `if schema_file is None:`). If `--schema-file` is provided but `--column-defs` is omitted, `config` is never loaded and the `column_defs` fallback will fail. -> Add a note to the Approach stating that `_async_fix()` config loading must be restructured to load config whenever either `schema_file` or `column_defs` needs a fallback (not just when `schema_file is None`). [Elevated: also flagged in holistic review]

### Item 2: Config Defaults for Sync Command (`tables`) and Shared `user_id_env`
**R1** (2026-03-10T21:29:22-0700, review-doc-run):
- [MED] The item says "Resolution in `_async_sync()`" for user_id but also says user_id_env is "shared across sync, backup, and restore commands." Analysis #5 defines a `_resolve_user_id()` helper. This wording could mislead an implementer into building sync-specific resolution instead of using the shared helper. -> Clarify that `_async_sync()` will use a shared `_resolve_user_id()` helper (defined in Analysis #5) rather than implementing its own resolution inline. Or note that the inline resolution shown here will later be refactored into the shared helper.
**R2** (2026-03-10T21:37:21-0700, review-doc-run): Sound
**R3** (2026-03-10T21:54:37-0700, review-doc-run): Sound

### Item 3: BackupSchema Sourcing via JSON File
**R1** (2026-03-10T21:29:22-0700, review-doc-run): Sound
**R2** (2026-03-10T21:37:21-0700, review-doc-run): Sound
**R3** (2026-03-10T21:54:37-0700, review-doc-run): Sound

### Item 4: Add backup/restore Subcommands
**R1** (2026-03-10T21:29:22-0700, review-doc-run):
- [LOW->MED] The `--tables` filtering snippet filters `BackupSchema.tables` by name but does not implement the claimed "preserving FK relationships for included parents" behavior. If a child table is requested without its parent, the filtered schema would contain a dangling `parent` FK reference. The Risks table flags this but no cross-reference here. -> Add a note or expand the snippet to show how missing parents are handled -- either auto-include parents, warn the user, or cross-reference the Risks table entry. [Elevated: also flagged in holistic review]
**R2** (2026-03-10T21:37:21-0700, review-doc-run): Sound
**R3** (2026-03-10T21:54:37-0700, review-doc-run):
- [LOW] The `--tables` filter code snippet is approximately 10 lines of executable Python that borders on implementation-level detail for a design document, though it clarifies semantics that would otherwise be ambiguous.
- [LOW] The `--validate` flag takes a path argument but the design does not specify the argparse `type` or `nargs`. It must be defined as `type=str, default=None` (not `store_true`). Clear from context but could be made explicit.
- [LOW] The `--yes`/`-y` flag for restore defines the flag but does not describe default prompt behavior. Behavior is deferred to Analysis #5, which is acceptable separation of concerns.

### Item 5: Async Wiring for Backup Commands
**R1** (2026-03-10T21:29:22-0700, review-doc-run):
- [MED] `_resolve_user_id` returns `str | None`, but `backup_database` and `restore_database` both require `user_id: str` (not optional). The pseudocode for `_async_backup` and `_async_restore` does not show error handling for the `None` case, risking a runtime TypeError. -> Add a note that `_async_backup` and `_async_restore` must check for `None` user_id and return error code 1 with a message like "No user_id available. Set {env_var} or pass --user-id" before calling the library function.
- [MED->HIGH] Files to modify lists 6 functions but omits `_resolve_backup_schema_path`, which the Proposed Sequence section (#6) explicitly states is provided by item #5. -> Add `_resolve_backup_schema_path` to the function list in "Files to modify", and add a brief description in the Approach section. [Elevated: also flagged in holistic review]
**R2** (2026-03-10T21:37:21-0700, review-doc-run):
- [MED] `_async_restore` is described only as "Same pattern for `_async_restore`" with no pseudocode or parameter outline. Restore has additional complexity (positional `backup_path`, `--mode`, `--dry-run`, `--yes` confirmation prompt) not illustrated. An implementer must cross-reference Analysis #4's flag definitions. -> Add a skeleton pseudocode block for `_async_restore` showing how `backup_path`, `mode`, `dry_run`, and `yes` args are resolved and passed to `restore_database()`.
**R3** (2026-03-10T21:54:37-0700, review-doc-run):
- [LOW] The `_resolve_user_id` and `_resolve_backup_schema_path` helper functions are complete, copy-paste-ready implementations (~6-7 lines each). Combined with other code blocks, the total approaches the boundary of what a design item should contain. Acceptable given they illustrate a shared pattern.

### Item 6: Auto-Backup Before Fix
**R1** (2026-03-10T21:29:22-0700, review-doc-run):
- [HIGH] `_resolve_backup_schema_path()` is called in the code snippet but never defined in any analysis item. Analysis #5 defines `_resolve_user_id()` and the Proposed Sequence claims #5 provides `_resolve_backup_schema_path`, but Analysis #5 does not define it. The implementer has no specification for this helper. -> Define `_resolve_backup_schema_path()` either in this item or in Analysis #3 or #5. It should follow the resolution pattern: CLI `--backup-schema` flag > `config.backup_schema` > `None`.
- [MED] The snippet references `adapter` and `config` variables, but in current `_async_fix()`, `adapter` is created at line 535 (after `args.confirm` check at line 520), and `config` is only loaded conditionally inside the `if schema_file is None:` block at line 367. At the stated insertion point, neither variable reliably exists. -> Add a note that the implementation must restructure `_async_fix()` to (a) always load config and (b) place auto-backup logic after adapter creation.
- [LOW] The code snippet does not show error handling for `backup_database()` failure, yet Risks and Testing Strategy both state "abort fix if backup fails." -> Add a try/except around the `backup_database()` call in the snippet, or add a note about error handling.
**R2** (2026-03-10T21:37:21-0700, review-doc-run):
- [MED] The design does not mention or acknowledge the existing `backup_fn` parameter on `apply_fixes()` (line 383 of `schema/fix.py`), which already supports per-table backup callbacks before DROP+CREATE operations. The implementer may wonder why auto-backup is placed before `apply_fixes()` instead of using the built-in mechanism. -> Add a note explaining that the full-database backup approach is preferred over `backup_fn` because it captures a complete snapshot before any changes, whereas `backup_fn` only backs up individual tables being recreated.
**R3** (2026-03-10T21:54:37-0700, review-doc-run):
- [MED] The main code block (~21 lines of executable Python) exceeds design document guidelines for implementation detail. It includes complete conditional branching, error handling, and output formatting that approaches copy-paste-ready implementation. -> Reduce to pseudocode or a shorter structural sketch showing key decision points (check backup_schema -> check user_id -> backup or warn -> apply fixes). Move detailed implementation to the plan step.

### Item 7: Retire Standalone cli/backup.py
**R1** (2026-03-10T21:29:22-0700, review-doc-run):
- [HIGH] Files to modify lists only `cli/backup.py -- delete` but does not mention existing tests that directly reference this file. At least 6 tests across `test_lib_extraction_cli.py` (TestNoMCReferences, TestAbsoluteImportsInCLI, TestBackupCLI) and `test_lib_extraction_imports.py` (TestCLIImports, TestSysPathRemoved) use `CLI_BACKUP_PY` or import `db_adapter.cli.backup`. Deleting the file without removing these tests will cause test failures. -> Add `tests/test_lib_extraction_cli.py` and `tests/test_lib_extraction_imports.py` to "Files to modify" with a note to remove or update tests that reference `cli/backup.py`.
**R2** (2026-03-10T21:37:21-0700, review-doc-run):
- [HIGH] References `TestNoMCReferences` in test_lib_extraction_cli.py -- this class does not exist. The actual class is `TestMCCodeRemoved` (line 55), which contains `test_no_mission_control_in_cli_backup`. -> Replace `TestNoMCReferences` with `TestMCCodeRemoved`.
- [HIGH] References `TestAbsoluteImportsInCLI` in test_lib_extraction_cli.py -- this class does not exist. The actual class is `TestImportStyle` (line 1434), which contains `test_no_bare_imports_in_cli_backup` and `test_backup_py_imports_from_db_adapter`. -> Replace `TestAbsoluteImportsInCLI` with `TestImportStyle`.
- [HIGH] References `TestCLIImports` in test_lib_extraction_imports.py -- this class does not exist. The relevant class is `TestSubpackageImports` (line 162), which contains `test_import_cli_backup` (line 291). -> Replace `TestCLIImports` with `TestSubpackageImports`.
**R3** (2026-03-10T21:54:37-0700, review-doc-run):
- [LOW] `CLAUDE.md` references `cli/backup.py` in two places (line 101 and Key Source Files table at line 141) but this item does not list `CLAUDE.md` as a file to modify. Item #8 covers CLAUDE.md updates, so coverage exists overall, but this item's file list is incomplete for deletion impact.

### Item 8: Update Public Exports and Documentation
**R1** (2026-03-10T21:29:22-0700, review-doc-run): Sound
**R2** (2026-03-10T21:37:21-0700, review-doc-run): Sound
**R3** (2026-03-10T21:54:37-0700, review-doc-run):
- [MED] Title says "Update Public Exports and Documentation" but the approach contains no instructions about updating public exports (`db_adapter/__init__.py`). The title implies export changes that are not described. -> Either rename to "Update Documentation" or add explicit instructions about any public export changes needed.
- [LOW] README.md entry says "update CLI Reference section" but README.md also contains a db.toml configuration example (lines 68-83) that needs `[sync]` and `[defaults]` sections. -> Update the Files to modify entry for README.md to: "update CLI Reference section and db.toml configuration example".

---

## Holistic Summary

| Concern | R1 | R2 | R3 |
|---------|----|----|-----|
| Template Alignment | ✅ | ✅ | ✅ |
| Soundness | 1 MED | ✅ | ✅ |
| Flow & Dependencies | ✅ | ✅ | ✅ |
| Contradictions | 1 MED | 1 MED | ✅ |
| Clarity & Terminology | ✅ | ✅ | ✅ |
| Surprises | 1 MED 3 LOW | 1 HIGH 1 LOW | 1 MED 2 LOW |
| Cross-References | ✅ | ✅ | ✅ |

---

## Holistic Details

**R1** (2026-03-10T21:29:22-0700, review-doc-run):
- **[Contradictions]** [MED] `_resolve_backup_schema_path(args, config)` is called in Analysis #6's code sample but never defined in any analysis item. Analysis #5 defines `_resolve_user_id()` but the backup-schema-path helper is missing. -> Add `_resolve_backup_schema_path()` specification to Analysis #3 or #5, or note it follows the same pattern as `_resolve_user_id()`.
- **[Soundness]** [LOW->MED] The `backup-schema.json` example in Analysis #3 does not show the `optional_refs` field from `TableDef`, which may leave users unsure how to specify optional FK references. -> Add an example table with `"optional_refs": [{"table": "authors", "field": "editor_id"}]` to the JSON sample. [Elevated: also flagged by item #3 area]
- **[Surprises]** [LOW] The `--tables` flag for backup has different semantics than `--tables` for sync (structural filter vs table name list). Documented in Analysis #4 but CLI users may be confused. -> Consider a note in the documentation update (#8) about this distinction.
- **[Surprises]** [LOW] Auto-backup failure aborts fix. Users in CI/CD may be surprised if `fix --confirm` fails because `backups/` is read-only or disk is full. Design states this is intentional. -> No fix needed, but consider noting this in documentation.
- **[Surprises]** [LOW] The `--tables` filter for backup does not validate FK parent tables are included. Risks table mentions this but code sample does not implement the warning. -> Note for planner to include FK parent validation.
**R2** (2026-03-10T21:37:21-0700, review-doc-run):
- **[Contradictions]** [MED] Inconsistent `user_id` null-check strategy: Analysis #5 says "check for `None` return" but Analysis #6 uses `if user_id:` (truthy check). `os.environ.get()` can return empty string which passes a `None` check but fails a truthy check. Both paths should behave the same way. -> Standardize on truthy check in both descriptions. Add a note that empty-string env var values are treated as "not provided."
- **[Surprises]** [MED->HIGH] The `_async_fix()` restructuring to "always load config" could break CLI-flag-only usage when `db.toml` is missing. Currently, if `db.toml` is absent but `--schema-file` and `--column-defs` are provided via CLI flags, `_async_fix()` works because config loading is skipped. After restructuring, config loading failure must be handled gracefully. -> Add explicit constraint: "Config loading must remain wrapped in `try/except` with `config = None` fallback. All auto-backup logic must handle `config is None` gracefully." [Elevated: also flagged by item #1]
- **[Surprises]** [LOW] The example output shows `pre-fix-local-2026-03-10-2130.json` as the auto-backup filename, but the design does not specify passing a custom `output_path` to `backup_database()`. The library default would produce `backup-{timestamp}.json`. -> Specify `output_path` parameter in the `backup_database()` call within the auto-backup code snippet.
**R3** (2026-03-10T21:54:37-0700, review-doc-run):
- **[Surprises]** [MED] The auto-backup code example in Analysis #6 references `profile_name` and `timestamp` variables (`output_path=f"backups/pre-fix-{profile_name}-{timestamp}.json"`) which are not defined in the snippet. `profile_name` maps to `profile` in the actual `_async_fix()` code, and `timestamp` needs to be generated. -> Clarify that `profile_name` maps to the existing `profile` variable and show `timestamp` generation (e.g., `datetime.now().strftime("%Y%m%d-%H%M%S")`), or note this as pseudocode.
- **[Surprises]** [LOW] `_load_backup_schema()` callers (`_async_backup`, `_async_restore`, `_validate_backup`, auto-backup in `_async_fix`) will all need to catch `ValidationError`, `FileNotFoundError`, and `json.JSONDecodeError`. This error handling is not described in the design but is appropriate for the Plan stage.
- **[Surprises]** [LOW] Files to Modify table lists `test_lib_extraction_cli.py` for removal of `cli/backup.py` references but does not mention new test additions for backup/restore commands that will also go in this file.

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-10T21:34:34-0700 | review-doc-run | Parallel (8 item + 1 holistic) --auto | 3 HIGH 4 MED 2 LOW | Applied (9 of 9) |
| R2 | 2026-03-10T21:44:50-0700 | review-doc-run | Parallel (8 item + 1 holistic) --auto | 4 HIGH 3 MED 1 LOW | Applied (8 of 8) |
| R3 | 2026-03-10T22:00:31-0700 | review-doc-run | Parallel (8 item + 1 holistic) --auto | 3 MED 8 LOW | Applied (3 of 11) |

---

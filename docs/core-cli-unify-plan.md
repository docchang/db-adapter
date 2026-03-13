# core-cli-unify Plan

> **Design**: See `docs/core-cli-unify-design.md` for analysis and approach.
>
> **Track Progress**: See `docs/core-cli-unify-results.md` for implementation status, test results, and issues.

## Overview

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-10T22:03:16-0700 |
| **Name** | Unify CLI: integrate backup subcommands + config-driven defaults + auto-backup safety net |
| **Type** | Feature |
| **Environment** | Python -- see `references/python-guide.md` |
| **Proves** | A unified CLI with config-driven defaults, backup/restore subcommands, and auto-backup safety reduces friction and prevents data loss |
| **Production-Grade Because** | Real config parsing (TOML + Pydantic), real async backup library, real argparse subcommands, real error handling with graceful degradation |
| **Risk Profile** | Standard |
| **Risk Justification** | Internal CLI tooling; backup library functions are already tested; config changes are additive with `None` defaults |

---

## Deliverables

Concrete capabilities this task delivers:

- `column_defs` config default in `db.toml` -- `fix` command works without `--column-defs` flag when configured
- `sync_tables` and `user_id_env` config defaults in `db.toml` -- `sync` command works without `--tables`/`--user-id` when configured
- `backup_schema` config default in `db.toml` -- backup/restore commands use config path for BackupSchema JSON
- `backup` subcommand with create mode and `--validate` mode
- `restore` subcommand with `--mode`, `--dry-run`, `--yes` flags
- Auto-backup before `fix --confirm` when backup_schema is configured (with `--no-backup` escape hatch)
- Standalone `cli/backup.py` retired (dead code removed)
- Updated documentation (CLAUDE.md, README.md, module docstrings)

---

## Prerequisites

Complete these BEFORE starting implementation steps.

### 1. Identify Affected Tests

**Why Needed**: Run only affected tests during implementation (not full suite)

**Affected test files**:
- `tests/test_lib_extraction_cli.py` - CLI command parsing, async wrappers, config-driven validation, MC code removal, import style, backup CLI tests (~90 tests)
- `tests/test_lib_extraction_config.py` - TOML parsing, Pydantic models, config loader (~20 tests)
- `tests/test_lib_extraction_imports.py` - Import style, subpackage imports, sys.path workaround tests (~21 tests)

**Baseline verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_config.py tests/test_lib_extraction_imports.py -v --tb=short
# Expected: All pass (establishes baseline)
```

### 2. Verify Backup Library Functions Are Working

**Why Needed**: The new CLI commands wire to existing backup library functions. They must be verified as working before building CLI wrappers.

**Verification** (inline OK for prerequisites):
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_backup.py -v --tb=short
# Expected: All pass
```

---

## Success Criteria

From Design doc (refined with verification commands):

- [ ] `db-adapter fix --confirm` works without `--column-defs` when configured in db.toml
- [ ] `db-adapter fix --confirm` auto-backs-up before applying destructive DDL (when `backup_schema` configured)
- [ ] `db-adapter fix --confirm --no-backup` skips auto-backup
- [ ] `db-adapter fix --confirm` warns and continues when no `backup_schema` configured
- [ ] `db-adapter sync --from rds --dry-run` works without `--tables` or `--user-id` when configured in db.toml
- [ ] `db-adapter backup` creates a valid backup JSON file (all params from config)
- [ ] `db-adapter backup --tables items` backs up only the specified tables from BackupSchema
- [ ] `db-adapter backup --validate backup.json` validates backup file integrity (read-only, no DB connection)
- [ ] `db-adapter restore backup.json` restores data from backup (all params from config)
- [ ] CLI flags override config values when explicitly provided
- [ ] All commands resolve `user_id` via: CLI flag -> env var from `[defaults].user_id_env` -> error
- [ ] `--backup-schema` flag falls back to `config.backup_schema` from db.toml
- [ ] `cli/backup.py` is deleted
- [ ] All existing tests pass (no regressions)
- [ ] New CLI command tests added for config defaults, backup subcommands, and auto-backup

---

## Architecture

### File Structure
```
src/db_adapter/
├── config/
│   ├── models.py              # Updated: add column_defs, backup_schema, sync_tables, user_id_env
│   └── loader.py              # Updated: parse [sync] and [defaults] sections
├── cli/
│   ├── __init__.py            # Updated: config fallbacks, backup/restore subcommands, auto-backup, helpers
│   └── backup.py              # DELETED: retired standalone CLI
├── backup/
│   ├── models.py              # Unchanged: BackupSchema, TableDef, ForeignKey
│   └── backup_restore.py     # Unchanged: backup_database, restore_database, validate_backup
├── __init__.py                # Unchanged
tests/
├── test_lib_extraction_cli.py     # Updated: remove backup.py refs, add new command tests
├── test_lib_extraction_config.py  # Updated: add tests for new config fields
└── test_lib_extraction_imports.py # Updated: remove cli/backup.py import test
```

### Design Principles
1. **OOP Design**: Use classes with single responsibility and clear interfaces (Pydantic models for config)
2. **Validated Data Models**: All new config fields use Pydantic models with typed defaults
3. **Strong Typing**: Type annotations on all functions, methods, and class attributes
4. **Graceful Degradation**: Config loading wrapped in `try/except`; CLI flags always work without `db.toml`

---

## Implementation Steps

**Approach**: Build bottom-up -- config model changes first, then CLI integration in order of increasing complexity (fix defaults -> sync defaults -> backup schema loading -> backup/restore subcommands -> auto-backup -> cleanup -> docs).

> This plan is a contract between the executor (builder) and reviewer (validator). Steps specify **what** to build and **how** to verify -- the executor writes the implementation.

### Step 0: Baseline Verification

**Goal**: Verify all affected tests pass before making any changes

- [ ] Run affected test files and confirm all pass

**Code**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_config.py tests/test_lib_extraction_imports.py tests/test_lib_extraction_backup.py -v --tb=short
```

**Verification** (inline OK for Step 0):
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_config.py tests/test_lib_extraction_imports.py tests/test_lib_extraction_backup.py -v --tb=short
# Expected: All pass
```

**Output**: Baseline test counts confirmed

---

### Step 1: Config Model -- Add New Fields to DatabaseConfig

**Goal**: Add `column_defs`, `backup_schema`, `sync_tables`, and `user_id_env` fields to `DatabaseConfig` Pydantic model, all with `None` defaults for backward compatibility.

- [ ] Add `column_defs: str | None = None` field to `DatabaseConfig`
- [ ] Add `backup_schema: str | None = None` field to `DatabaseConfig`
- [ ] Add `sync_tables: list[str] | None = None` field to `DatabaseConfig`
- [ ] Add `user_id_env: str | None = None` field to `DatabaseConfig`
- [ ] Write tests verifying backward compatibility and new field parsing

**Specification**:
- Modify `src/db_adapter/config/models.py`: Add four new optional fields to `DatabaseConfig` class, all defaulting to `None`
- All existing `DatabaseConfig` instantiations must continue working without changes (backward compatible via `None` defaults)
- Tests must verify: (1) `DatabaseConfig` with no new fields still works, (2) `DatabaseConfig` with all new fields populated parses correctly, (3) each new field defaults to `None` when not provided

**Acceptance Criteria**:
- `DatabaseConfig(profiles={...})` continues to work without providing new fields
- `DatabaseConfig(profiles={...}, column_defs="defs.json", backup_schema="bs.json", sync_tables=["t1", "t2"], user_id_env="DEV_USER_ID")` parses all fields correctly
- Each new field is typed as `str | None` (or `list[str] | None` for `sync_tables`) and defaults to `None`
- Existing config model tests still pass

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_config.py -v --tb=short
```

**Output**: All config tests passing

---

### Step 2: Config Loader -- Parse New Sections from db.toml

**Goal**: Update `load_db_config()` to parse `column_defs` and `backup_schema` from `[schema]` section, `sync_tables` from `[sync]` section, and `user_id_env` from `[defaults]` section.

- [ ] Update `load_db_config()` to extract `column_defs` from `schema_settings`
- [ ] Update `load_db_config()` to extract `backup_schema` from `schema_settings`
- [ ] Update `load_db_config()` to parse `[sync]` section and extract `tables` as `sync_tables`
- [ ] Update `load_db_config()` to parse `[defaults]` section and extract `user_id_env`
- [ ] Write tests verifying new section parsing

**Specification**:
- Modify `src/db_adapter/config/loader.py`: In `load_db_config()`, after parsing `schema_settings`, also extract `column_defs` and `backup_schema`. Parse new `data.get("sync", {})` for `tables` and `data.get("defaults", {})` for `user_id_env`. Pass all new values to `DatabaseConfig()` constructor.
- TOML structure for new sections:
  ```toml
  [schema]
  column_defs = "column-defs.json"
  backup_schema = "backup-schema.json"

  [sync]
  tables = ["projects", "milestones", "tasks"]

  [defaults]
  user_id_env = "DEV_USER_ID"
  ```
- When sections or keys are missing, the corresponding `DatabaseConfig` field remains `None` (its default)
- Tests must verify: (1) TOML with all new sections parses correctly, (2) TOML without new sections still works (backward compatible), (3) partial sections (e.g., `[sync]` without `[defaults]`) work, (4) existing `TestLoadDbConfig` tests still pass
- Note: The existing test `test_only_expected_imports` in `TestMCCodeRemoved` class of `test_lib_extraction_config.py` will fail if the loader's import set changes. Verify the loader still uses only `tomllib`, `pathlib`, and `db_adapter.config.models` imports.

**Acceptance Criteria**:
- `load_db_config()` with a TOML file containing `[schema]`, `[sync]`, and `[defaults]` sections returns a `DatabaseConfig` with all new fields populated
- `load_db_config()` with a minimal TOML file (only `[profiles]`) returns `DatabaseConfig` with all new fields as `None`
- The `sync_tables` field is `list[str]` when provided, `None` when not
- Existing loader tests continue passing without modification

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_config.py -v --tb=short
```

**Output**: All config tests passing

---

### Step 3: CLI Config Defaults for Fix Command

**Goal**: Make `--column-defs` optional by reading the default path from `config.column_defs` in db.toml. Restructure `_async_fix()` config loading.

- [ ] Change argparse: `--column-defs` from `required=True` to `required=False, default=None`
- [ ] Restructure `_async_fix()` to always load config (not just when `schema_file is None`)
- [ ] Add column_defs resolution: CLI flag -> config -> error
- [ ] Write tests verifying column_defs resolution and backward compatibility

**Specification**:
- Modify `src/db_adapter/cli/__init__.py`:
  - In `main()`, change the `--column-defs` argument from `required=True` to `required=False, default=None`
  - In `_async_fix()`, restructure config loading: always attempt to load config at the top (wrapped in `try/except` with `config = None` fallback), then use config for both `schema_file` and `column_defs` fallbacks
  - Resolution order for `column_defs`: (1) `args.column_defs` if provided, (2) `config.column_defs` if config loaded, (3) return 1 with error message
  - Config loading must remain wrapped in `try/except` so CLI-flag-only usage (no `db.toml`) continues to work
- Tests must verify: (1) `_async_fix()` with `column_defs` from config (no CLI flag) resolves correctly, (2) CLI `--column-defs` overrides config value, (3) neither provided returns 1 with error message, (4) `--schema-file` provided but `--column-defs` omitted still loads config for `column_defs` fallback, (5) existing fix tests still pass
- Note: The existing test `test_fix_parser_requires_column_defs` expects `SystemExit(2)` when `--column-defs` is omitted. This test must be updated or removed since `--column-defs` is now optional.

**Acceptance Criteria**:
- `db-adapter fix` without `--column-defs` does not exit with argparse error (previously required)
- `_async_fix()` resolves `column_defs` from config when CLI flag not provided
- `_async_fix()` uses CLI `--column-defs` value when provided (overrides config)
- `_async_fix()` returns 1 with clear error message when neither CLI flag nor config provides `column_defs`
- `_async_fix()` works correctly when `--schema-file` is provided but `--column-defs` is not (config loaded for `column_defs` fallback)

**Trade-offs**:
- **Config loading restructure**: Always load config at top of `_async_fix()` because both `schema_file` and `column_defs` may need fallbacks. Alternative: load conditionally for each, but this duplicates the try/except pattern.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 4: CLI Config Defaults for Sync Command and Shared user_id Resolution

**Goal**: Make `--tables` and `--user-id` optional on sync by reading defaults from config. Introduce `_resolve_user_id()` shared helper.

- [ ] Change argparse: `--tables` from `required=True` to `required=False, default=None`
- [ ] Change argparse: `--user-id` from `required=True` to `required=False, default=None`
- [ ] Add `_resolve_user_id(args, config)` shared helper function
- [ ] Update `_async_sync()` to use config fallbacks for tables and user_id
- [ ] Write tests verifying sync defaults resolution and `_resolve_user_id()` behavior

**Specification**:
- Modify `src/db_adapter/cli/__init__.py`:
  - In `main()`, change `--tables` and `--user-id` arguments on sync subparser from `required=True` to `required=False, default=None`
  - Add `_resolve_user_id(args: argparse.Namespace, config: DatabaseConfig | None) -> str | None` helper: checks `getattr(args, "user_id", None)` first (safe for subparsers without `--user-id`), then reads env var named in `config.user_id_env` via `os.environ.get()`, returns `None` if neither available. Empty-string env var values are treated as "not provided" (use truthy check).
  - In `_async_sync()`, load config (try/except with `config = None` fallback), then resolve `tables` from `args.tables` or `config.sync_tables`, and `user_id` via `_resolve_user_id()`. Return 1 with clear error if either is missing. Note: `args.tables` is a comma-separated string (split with `.split(",")`) while `config.sync_tables` is already `list[str]` -- handle both sources appropriately.
  - Add `import os` at module level if not already present
- Tests must verify: (1) `_resolve_user_id()` returns CLI flag value when provided, (2) reads correct env var when CLI flag absent, (3) returns `None` when neither available, (4) empty env var treated as not provided, (5) `_async_sync()` resolves tables from config, (6) CLI `--tables` overrides config, (7) missing tables returns 1, (8) existing sync tests still pass
- Note: Existing tests `test_sync_parser_requires_tables` and `test_sync_parser_requires_user_id` expect `SystemExit(2)`. These must be updated since the args are now optional.

**Acceptance Criteria**:
- `_resolve_user_id()` returns CLI flag when provided, env var from `config.user_id_env` when not, `None` when neither
- Empty-string env var (`""`) is treated as "not provided" by `_resolve_user_id()`
- `_async_sync()` resolves `tables` from `config.sync_tables` when `--tables` not provided
- `_async_sync()` returns 1 with error when tables cannot be resolved
- `_async_sync()` returns 1 with error when user_id cannot be resolved
- CLI flags override config for both `--tables` and `--user-id`

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 5: BackupSchema Loading and Resolution Helpers

**Goal**: Add `_load_backup_schema()` and `_resolve_backup_schema_path()` helpers for loading BackupSchema from JSON files with config fallback.

- [ ] Add `_load_backup_schema(path: str) -> BackupSchema` helper
- [ ] Add `_resolve_backup_schema_path(args, config)` helper
- [ ] Add required imports for backup models
- [ ] Write tests verifying JSON loading and path resolution

**Specification**:
- Modify `src/db_adapter/cli/__init__.py`:
  - Add import: `from db_adapter.backup.models import BackupSchema`
  - Note: `DatabaseConfig` import (`from db_adapter.config.models import DatabaseConfig`) should already be present from Step 4's `_resolve_user_id()` type annotation. If not, add it here for `_resolve_backup_schema_path()`'s type annotation.
  - Add `_load_backup_schema(path: str) -> BackupSchema`: reads JSON file, validates with `BackupSchema(**data)`, returns model. Raises `FileNotFoundError` if file missing, `json.JSONDecodeError` if invalid JSON, `pydantic.ValidationError` if schema invalid.
  - Add `_resolve_backup_schema_path(args: argparse.Namespace, config: DatabaseConfig | None) -> str | None`: checks `getattr(args, "backup_schema", None)` first, then `config.backup_schema`, returns `None` if neither.
- Tests must verify: (1) `_load_backup_schema()` with valid JSON returns `BackupSchema`, (2) with invalid JSON raises error, (3) with missing file raises `FileNotFoundError`, (4) with valid JSON but invalid schema raises `ValidationError`, (5) `_resolve_backup_schema_path()` returns CLI flag when provided, (6) returns config path when flag absent, (7) returns `None` when neither

**Acceptance Criteria**:
- `_load_backup_schema("valid.json")` returns a `BackupSchema` with correct tables
- `_load_backup_schema("invalid.json")` raises appropriate error
- `_load_backup_schema("missing.json")` raises `FileNotFoundError`
- `_resolve_backup_schema_path()` follows resolution order: CLI flag -> config -> `None`
- Both helpers are importable from `db_adapter.cli`

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 6: Add backup/restore Subcommand Parsers and Sync Wrappers

**Goal**: Add argparse subparser definitions for `backup` and `restore` subcommands, with their respective flags and sync wrappers. Wire to async handler functions (stubs returning 1 initially -- full implementation in Step 7).

- [ ] Add `backup` subparser with `--backup-schema`, `--user-id`, `--output`, `--tables`, `--validate` flags
- [ ] Add `restore` subparser with positional `backup_path`, `--backup-schema`, `--user-id`, `--mode`, `--dry-run`, `--yes` flags
- [ ] Add `cmd_backup(args)` and `cmd_restore(args)` sync wrappers
- [ ] Write tests verifying argparse structure and parser behavior

**Specification**:
- Modify `src/db_adapter/cli/__init__.py` `main()` function:
  - Add `backup` subparser with:
    - `--backup-schema`: path to backup schema JSON (optional)
    - `--user-id`: user ID (optional, shared with sync)
    - `--output` / `-o`: output file path (optional)
    - `--tables`: comma-separated table filter (optional)
    - `--validate`: path to backup file to validate (optional, `type=str, default=None`)
  - Add `restore` subparser with:
    - `backup_path`: positional argument (path to backup JSON)
    - `--backup-schema`: path to backup schema JSON (optional)
    - `--user-id`: user ID (optional)
    - `--mode` / `-m`: choices `["skip", "overwrite", "fail"]`, default `"skip"`
    - `--dry-run`: `action="store_true"`
    - `--yes` / `-y`: `action="store_true"`
  - Add `cmd_backup(args) -> int` sync wrapper that calls `asyncio.run(_async_backup(args))`; when `args.validate` is provided, calls `_validate_backup(args)` instead (sync path)
  - Add `cmd_restore(args) -> int` sync wrapper that calls `asyncio.run(_async_restore(args))`
  - Add stub `_async_backup`, `_async_restore`, `_validate_backup` functions that return 1 with "Not yet implemented" message (full implementation in Step 7)
- Tests must verify: (1) `backup` subparser accepts all defined flags, (2) `restore` subparser accepts positional `backup_path` and all flags, (3) `cmd_backup` calls `asyncio.run` for create mode, (4) `cmd_backup` calls `_validate_backup` for validate mode, (5) `cmd_restore` calls `asyncio.run`, (6) argparse correctly dispatches to handlers

**Acceptance Criteria**:
- `db-adapter backup --backup-schema bs.json --user-id uid1 --output out.json --tables t1,t2` parses without error
- `db-adapter backup --validate backup.json` parses without error
- `db-adapter restore backup.json --backup-schema bs.json --user-id uid1 --mode overwrite --dry-run --yes` parses without error
- `cmd_backup` dispatches to sync `_validate_backup` when `--validate` provided, async `_async_backup` otherwise
- `cmd_restore` dispatches to async `_async_restore`
- Both sync wrappers follow the existing `asyncio.run()` pattern

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 7: Async Wiring for Backup Commands

**Goal**: Implement the full async handler functions `_async_backup`, `_async_restore`, and `_validate_backup` that connect CLI subcommands to the backup library functions.

- [ ] Implement `_async_backup(args)` -- config loading, schema resolution, user_id resolution, table filtering, adapter creation, `backup_database()` call
- [ ] Implement `_async_restore(args)` -- config loading, schema resolution, user_id resolution, confirmation prompt, adapter creation, `restore_database()` call
- [ ] Implement `_validate_backup(args)` -- config loading, schema resolution, `validate_backup()` call (sync, no DB)
- [ ] Write tests verifying all three handler functions

**Specification**:
- Modify `src/db_adapter/cli/__init__.py`:
  - Replace stub `_async_backup` with full implementation (improving on `_async_fix` by adding try/finally adapter cleanup):
    1. Load config (try/except, `config = None` fallback)
    2. Resolve backup_schema path via `_resolve_backup_schema_path(args, config)` -- return 1 if None
    3. Load BackupSchema via `_load_backup_schema(path)` -- return 1 on error
    4. Resolve user_id via `_resolve_user_id(args, config)` -- return 1 if not truthy
    5. Filter schema by `--tables` if provided (construct filtered `BackupSchema` with only matching tables; warn if child table included without parent)
    6. Resolve profile + create adapter via `get_adapter()`
    7. Call `backup_database(adapter, schema, user_id, output_path=args.output)` in try/finally (close adapter)
    8. Print result (path, per-table counts)
  - Replace stub `_async_restore` with full implementation:
    1. Load config, resolve backup_schema, load BackupSchema, resolve user_id (same as backup)
    2. Verify backup file exists (return 1 if not)
    3. If not `args.yes` and not `args.dry_run`: print confirmation prompt, use `input()`, abort if not confirmed
    4. Resolve profile + create adapter
    5. Call `restore_database(adapter, schema, args.backup_path, user_id, mode=args.mode, dry_run=args.dry_run)` in try/finally
    6. Print result (per-table counts, mode used)
  - Replace stub `_validate_backup` with full implementation:
    1. Load config, resolve backup_schema path, load BackupSchema
    2. Call `validate_backup(args.validate, schema)` (sync -- no DB connection)
    3. Print result (valid/invalid + errors/warnings)
  - Add import: `from db_adapter.backup.backup_restore import backup_database, restore_database, validate_backup`
  - Add import: `from db_adapter.factory import get_adapter` (may already be imported in local scope)
- Tests must verify: (1) `_async_backup` with valid schema + mock adapter returns 0 and calls `backup_database`, (2) missing backup-schema returns 1, (3) missing user_id returns 1, (4) `--tables` flag filters BackupSchema, (5) `_async_restore` with valid inputs returns 0 and calls `restore_database`, (6) `--dry-run` passes `dry_run=True`, (7) `--mode overwrite` passes `mode="overwrite"`, (8) `_validate_backup` with valid backup returns 0, (9) invalid backup returns 1, (10) adapter is always closed (try/finally), (11) `_validate_backup` with missing backup_schema returns 1

**Acceptance Criteria**:
- `_async_backup` calls `backup_database()` with correct args and returns 0 on success
- `_async_backup` returns 1 with error message when backup_schema path not available
- `_async_backup` returns 1 with error message when user_id not available
- `_async_backup` with `--tables` passes a filtered `BackupSchema` containing only requested tables
- `_async_restore` calls `restore_database()` with correct args and returns 0 on success
- `_async_restore` respects `--dry-run`, `--mode`, and `--yes` flags
- `_validate_backup` calls `validate_backup()` (sync) and prints results
- Adapter is closed in `finally` block for both backup and restore

**Trade-offs**:
- **Confirmation prompt in restore**: Use `input()` for confirmation prompt because the existing CLI does not use a confirmation library. Alternative: use `rich.prompt.Confirm`, but `input()` is simpler and matches the standalone backup CLI pattern.
- **Table filtering approach**: Filter BackupSchema tables by name with parent-missing warning because auto-including parents would be surprising behavior. Alternative: auto-include parent tables, but users should explicitly request what they want.

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 8: Auto-Backup Before Fix

**Goal**: When `fix --confirm` applies changes and a `backup_schema` is configured, automatically create a backup before applying destructive DDL. Add `--no-backup` flag to skip.

- [ ] Add `--no-backup` flag to fix subparser
- [ ] Add auto-backup logic to `_async_fix()` between adapter creation and `apply_fixes()` call
- [ ] Handle backup failure (abort fix)
- [ ] Handle missing backup_schema or user_id (warn and continue)
- [ ] Write tests verifying auto-backup behavior

**Specification**:
- Modify `src/db_adapter/cli/__init__.py`:
  - Add `--no-backup` flag to fix subparser: `action="store_true"`, help text indicates it skips automatic backup
  - In `_async_fix()`, after adapter creation and before `apply_fixes()`, add auto-backup logic:
    1. Only when `args.confirm` and `plan.has_fixes` and not `args.no_backup`
    2. Resolve backup_schema_path via `_resolve_backup_schema_path(args, config)` -- if None, print warning and continue without backup
    3. Load BackupSchema via `_load_backup_schema(path)` -- if error, print warning and continue
    4. Resolve user_id via `_resolve_user_id(args, config)` -- if not truthy, print warning and continue
    5. Ensure `backups/` directory exists (`Path("backups").mkdir(exist_ok=True)`) then call `backup_database(adapter, schema, user_id, output_path=f"backups/pre-fix-{profile}-{timestamp}.json")` with `timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")`
    6. On success: print saved path
    7. On failure: abort fix (return 1) -- safety net must work
  - Add import: `from datetime import datetime` at module level
  - Note: `config` is already loaded at the top of `_async_fix()` (restructured in Step 3). The `adapter` variable is created after the `args.confirm` check. Auto-backup logic goes between adapter creation and `apply_fixes()` call. Note: the existing `_async_fix()` does not wrap adapter in try/finally -- consider adding `await adapter.close()` in a finally block (consistent with the try/finally pattern in Step 7's backup/restore handlers).
  - Note: The `args` Namespace for `fix` does not have `backup_schema` or `user_id` attributes by default (those are on `backup`/`restore` subparsers). `_resolve_backup_schema_path` and `_resolve_user_id` use `getattr(args, ..., None)` which safely returns `None`, falling back to config.
- Tests must verify: (1) `fix --confirm` with `backup_schema` configured calls `backup_database()` before `apply_fixes()`, (2) `fix --confirm --no-backup` does not call `backup_database()`, (3) `fix --confirm` without `backup_schema` warns and continues, (4) `fix --confirm` without `user_id` warns and continues, (5) backup failure aborts fix (returns 1), (6) `fix` without `--confirm` (preview only) does not trigger backup

**Acceptance Criteria**:
- `fix --confirm` with configured `backup_schema` and `user_id` creates a backup file before applying fixes
- `fix --confirm --no-backup` skips backup entirely
- `fix --confirm` without `backup_schema` configured prints warning and applies fixes without backup
- `fix --confirm` without `user_id` available prints warning and applies fixes without backup
- Backup failure causes fix to abort (return 1) -- safety net integrity
- `fix` without `--confirm` (preview mode) never triggers backup logic
- Backup output path follows pattern `backups/pre-fix-{profile}-{timestamp}.json`

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py -v --tb=short
```

**Output**: All CLI tests passing

---

### Step 9: Retire Standalone cli/backup.py and Update Tests

**Goal**: Delete the broken standalone `cli/backup.py` and update all test files that reference it.

- [ ] Delete `src/db_adapter/cli/backup.py`
- [ ] Update `tests/test_lib_extraction_cli.py`: remove `CLI_BACKUP_PY` constant, remove tests referencing it
- [ ] Update `tests/test_lib_extraction_imports.py`: remove `test_import_cli_backup` and `TestSysPathRemoved` class
- [ ] Verify no other files reference `cli/backup.py`

**Specification**:
- Delete `src/db_adapter/cli/backup.py`
- Modify `tests/test_lib_extraction_cli.py`:
  - Remove the `CLI_BACKUP_PY` constant (line 45-47)
  - Remove `test_no_mission_control_in_cli_backup` from `TestMCCodeRemoved` (reads `CLI_BACKUP_PY`)
  - Remove `test_no_bare_imports_in_cli_backup` from `TestImportStyle` (reads `CLI_BACKUP_PY`)
  - Remove `test_backup_py_imports_from_db_adapter` from `TestImportStyle` (reads `CLI_BACKUP_PY`)
  - Remove entire `TestBackupCLI` class (both tests read `CLI_BACKUP_PY`)
  - Update module docstring to remove `cli/backup.py` reference
- Modify `tests/test_lib_extraction_imports.py`:
  - Remove `test_import_cli_backup` from `TestSubpackageImports` (imports `db_adapter.cli.backup`)
  - Remove entire `TestSysPathRemoved` class (reads `cli/backup.py`)
- Verify: no remaining references to `cli/backup.py` or `cli.backup` in source or tests (excluding this plan and design docs)

**Acceptance Criteria**:
- `src/db_adapter/cli/backup.py` no longer exists
- No test file references `CLI_BACKUP_PY`, `cli/backup.py`, or `db_adapter.cli.backup`
- All remaining tests pass without errors
- No import of `db_adapter.cli.backup` exists in any source file

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_imports.py -v --tb=short
```

**Output**: All tests passing (fewer tests due to removed dead-code tests)

---

### Step 10: Update Documentation

**Goal**: Update module docstring, CLAUDE.md, and README.md to reflect the unified CLI with config-driven defaults, new subcommands, and updated db.toml configuration.

- [ ] Update `cli/__init__.py` module docstring
- [ ] Update CLAUDE.md CLI Commands section and db.toml documentation
- [ ] Update README.md CLI Reference section and db.toml configuration
- [ ] Remove references to standalone `cli/backup.py` from CLAUDE.md

**Specification**:
- Modify `src/db_adapter/cli/__init__.py`: Update module docstring to list all 8 subcommands (connect, status, profiles, validate, fix, sync, backup, restore) with brief descriptions including new capabilities (auto-backup, config defaults)
- Modify `CLAUDE.md`:
  - Update CLI Commands section to show clean usage (without verbose flags when config provides defaults)
  - Add `backup` and `restore` commands to the command list
  - Update db.toml configuration example to include `[sync]` and `[defaults]` sections and new `[schema]` fields
  - Remove references to `cli/backup.py` from Key Source Files table and elsewhere
  - Update Backup CLI description to note it's now integrated into main CLI
- Modify `README.md`:
  - Update CLI Reference section with new subcommands and clean usage examples
  - Update db.toml configuration example to include new sections
  - Update Architecture file structure tree to remove `backup.py` entry and update `cli/__init__.py` description to list all 8 subcommands
  - Update the features list to show all 8 subcommands
- Tests must verify: documentation changes don't break any existing tests (tests that read `cli/__init__.py` check for absence of MC-specific strings; docstring update must not introduce prohibited strings like "Mission Control" or "MC_DB_PROFILE")

**Acceptance Criteria**:
- `cli/__init__.py` module docstring lists all 8 subcommands
- CLAUDE.md shows updated CLI commands including `backup` and `restore`
- CLAUDE.md db.toml example includes `[schema]` (with `column_defs`, `backup_schema`), `[sync]`, and `[defaults]` sections
- No reference to standalone `cli/backup.py` remains in CLAUDE.md
- README.md CLI reference includes new subcommands
- All tests pass after documentation updates

**Verification**:
```bash
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_config.py tests/test_lib_extraction_imports.py -v --tb=short
```

**Output**: All affected tests passing

---

### Step 11: Final Integration Validation

**Goal**: Run the full test suite and verify all success criteria are met.

- [ ] Run full test suite
- [ ] Verify all affected tests pass
- [ ] Verify no regressions in unrelated tests

**Specification**:
- Run all affected test files to verify no regressions
- Run full test suite to verify no unrelated breakage
- Verify CLI help output shows all 8 subcommands: connect, status, profiles, validate, fix, sync, backup, restore

**Acceptance Criteria**:
- All affected tests pass (test_lib_extraction_cli, test_lib_extraction_config, test_lib_extraction_imports)
- All plan-level Success Criteria verified (covered by test suite or manual spot-check)
- Full test suite passes with no regressions
- `db-adapter --help` shows all 8 subcommands

**Verification**:
```bash
# Run affected tests
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_config.py tests/test_lib_extraction_imports.py -v --tb=short
# Expected: All pass

# Full suite
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short
# Expected: All pass

# CLI help
cd /Users/docchang/Development/db-adapter && uv run db-adapter --help
# Expected: Shows all 8 subcommands
```

**Output**: Affected tests passing, full suite passing

---

## Test Summary

### Affected Tests (Run These)

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `tests/test_lib_extraction_cli.py` | ~90 | CLI command parsing, async wrappers, config-driven validation, backup CLI |
| `tests/test_lib_extraction_config.py` | ~20 | TOML parsing, Pydantic models, config loader |
| `tests/test_lib_extraction_imports.py` | ~21 | Import style, subpackage imports |

**Affected tests: ~131 tests** (some will be removed in Step 9, new ones added in Steps 1-8)

**Full suite**: ~704 tests (run at final validation step)

---

## What "Done" Looks Like

```bash
# 1. Affected tests pass
cd /Users/docchang/Development/db-adapter && uv run pytest tests/test_lib_extraction_cli.py tests/test_lib_extraction_config.py tests/test_lib_extraction_imports.py -v --tb=short
# Expected: All pass

# 2. Full suite
cd /Users/docchang/Development/db-adapter && uv run pytest tests/ -v --tb=short
# Expected: All pass

# 3. CLI shows all 8 subcommands
cd /Users/docchang/Development/db-adapter && uv run db-adapter --help
# Expected: connect, status, profiles, validate, fix, sync, backup, restore
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/db_adapter/config/models.py` | Modify | Add `column_defs`, `backup_schema`, `sync_tables`, `user_id_env` fields |
| `src/db_adapter/config/loader.py` | Modify | Parse `[sync]` and `[defaults]` sections, new `[schema]` fields |
| `src/db_adapter/cli/__init__.py` | Modify | Config fallbacks, backup/restore subcommands, auto-backup, helpers |
| `src/db_adapter/cli/backup.py` | Delete | Retire broken standalone CLI |
| `tests/test_lib_extraction_cli.py` | Modify | Remove backup.py refs, add new command tests |
| `tests/test_lib_extraction_config.py` | Modify | Add tests for new config fields and loader sections |
| `tests/test_lib_extraction_imports.py` | Modify | Remove cli/backup.py import test and sys.path test |
| `CLAUDE.md` | Modify | Update CLI commands, config example, remove backup.py references |
| `README.md` | Modify | Update CLI reference, config example |

---

## Dependencies

No new dependencies required. All functionality uses existing packages:
- `pydantic` (already installed) -- config models
- `rich` (already installed) -- CLI output
- `argparse` (stdlib) -- CLI parsing
- `asyncio` (stdlib) -- async wrappers
- `json` (stdlib) -- BackupSchema JSON loading
- `os` (stdlib) -- env var resolution
- `datetime` (stdlib) -- timestamp generation

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| New config fields break existing db.toml parsing | LOW | All fields optional with `None` default -- existing configs unaffected |
| `user_id_env` env var not set | MED | Clear error message: "Set {env_var} or pass --user-id" |
| Adapter not closed on error | MED | Use `try/finally` pattern consistently in all async handlers |
| Auto-backup fails (disk full, permissions) | LOW | Abort fix if backup fails -- safety net must work |
| Existing tests reference deleted `cli/backup.py` | HIGH | Step 9 explicitly removes all references before deleting file |
| `--tables` filter removes FK parents | MED | Warn if child tables included without their parents |

---

## Next Steps After Completion

1. Verify affected tests pass (~131 tests)
2. Verify full suite passes (~704 tests)
3. Verify `db-adapter --help` shows all 8 subcommands
4. Proceed to next task

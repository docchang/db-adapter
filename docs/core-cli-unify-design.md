# core-cli-unify Design

> **Purpose**: Analyze and design solutions before implementation planning
>
> **Important**: This task must be self-contained (works independently; doesn't break existing functionality and existing tests)

## Executive Summary

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-10T19:35:53-0700 |
| **Task** | Unify CLI: integrate backup subcommands + config-driven defaults + auto-backup safety net |
| **Type** | Feature |
| **Scope** | CLI, config, backup — 6 files modified, 1 file retired |
| **Code** | NO - This is a design document |
| **Risk Profile** | Standard |
| **Risk Justification** | Internal CLI tooling; backup library functions are already tested; config changes are additive with `None` defaults |

**Challenge**: The CLI requires verbose flags on every invocation because it doesn't read defaults from config, the backup CLI is a broken standalone script, and `fix --confirm` applies destructive DDL without a safety net.

**Solution**: Add config sections to `db.toml` for command defaults, integrate backup/restore as main CLI subcommands, wire auto-backup into `fix --confirm`, and retire the broken standalone backup CLI.

---

## Context

### Current State

**Verbose CLI usage**: Three commands require flags that rarely change between invocations:

| Command | Required Flag | Typical Value | Changes Often? |
|---------|--------------|---------------|----------------|
| `fix` | `--column-defs` | `column-defs.json` | No |
| `sync` | `--tables` | `projects,milestones,tasks` | No |
| `sync` | `--user-id` | from env var | No |

The old Mission Control CLI didn't have this problem because these values were hardcoded or read from Python models. The extracted db-adapter CLI correctly made them explicit flags (it shouldn't hardcode MC-specific values), but didn't provide a config-based default mechanism.

**No safety net for fix**: The old MC CLI auto-backed-up the database before applying `fix --confirm`. The current db-adapter `fix` applies DROP+CREATE directly with no backup. Since the backup library is now internal, the fix command can and should use it.

**Broken backup CLI**: The backup CLI (`cli/backup.py`) was extracted from Mission Control but is completely broken:

```
cli/backup.py problems:
+-- backup_database() called without adapter, schema, user_id args
+-- restore_database() called without adapter, schema, user_id args
+-- validate_backup() called without schema arg
+-- All 3 library functions are async but called synchronously
+-- No profile resolution (get_adapter, get_active_profile_name)
+-- No config loading (load_db_config)
+-- Hardcoded paths (Path(__file__).parent / "backups")
+-- Separate entry point: python -m db_adapter.cli.backup
```

The library functions themselves are correct and well-tested:

| Function | Signature | Status |
|----------|-----------|--------|
| `backup_database(adapter, schema, user_id, ...)` | async | Working |
| `restore_database(adapter, schema, backup_path, user_id, ...)` | async | Working |
| `validate_backup(backup_path, schema)` | sync | Working |

**Current verbose usage:**
```bash
db-adapter fix --column-defs defs.json --confirm
db-adapter sync --from rds --tables projects,milestones,tasks --user-id abc123 --dry-run
db-adapter backup --backup-schema schema.json --user-id abc123
db-adapter backup --validate backup.json --backup-schema schema.json
```

**Dependency**: This design extends the config-driven CLI pattern established in Steps 3-5 of `core-cli-fix` and replaces Bug #6 ("Backup CLI Is Completely Non-Functional") from that task. core-cli-fix is complete.

### Target State

One unified CLI with 8 subcommands, config-driven defaults, and auto-backup safety:

```
db-adapter CLI (unified)
+-- connect              # existing
+-- status               # existing
+-- profiles             # existing
+-- validate             # existing
+-- fix                  # existing -- column_defs from config, auto-backup before apply
+-- sync                 # existing -- tables + user_id from config
+-- backup               # NEW -- export database to JSON (+ --validate for file validation)
+-- restore              # NEW -- restore from backup JSON
```

**db.toml configuration:**
```toml
[profiles.local]
url = "postgresql://localhost/mydb"
provider = "postgres"

[schema]
file = "schema.sql"
validate_on_connect = true
column_defs = "column-defs.json"
backup_schema = "backup-schema.json"

[sync]
tables = ["projects", "milestones", "tasks"]

[defaults]
user_id_env = "DEV_USER_ID"
```

**Clean CLI usage (with db.toml configured):**
```bash
DB_PROFILE=local db-adapter connect           # validates schema via config
db-adapter status                             # shows current profile
db-adapter validate                           # uses schema.file from config
db-adapter fix --confirm                      # auto-backup, then apply fixes
db-adapter fix --confirm --no-backup          # skip auto-backup (testing only)
db-adapter sync --from rds --dry-run          # uses tables + user_id from config
db-adapter backup                             # uses backup_schema + user_id from config
db-adapter backup --tables items              # backup only specific tables
db-adapter backup --validate backup.json      # validate backup file integrity (read-only)
db-adapter restore backup.json --dry-run      # uses backup_schema + user_id from config
```

All flags still work as overrides for one-off operations.

---

## Constraints

- **Scope boundaries**: No auto-generation of BackupSchema from introspection — that's a separate feature. Users provide a JSON file.
- **Must NOT happen**: Breaking existing 6 subcommands or their tests. Breaking the backup library functions (`backup/backup_restore.py`, `backup/models.py`).
- **Compatibility**: All new config fields have `None` defaults — existing db.toml files work without changes. CLI flags continue to work as before.
- **Other guardrails**: Follow the existing CLI pattern (sync wrapper -> `asyncio.run(_async_impl)` -> library call). No new dependencies.

---

## Analysis

> Each item analyzed independently. No implied order - read in any sequence.

### 1. Config Defaults for Fix Command (`column_defs`)

**What**: Make `--column-defs` optional by reading a default path from `db.toml` config.

**Why**: The column-defs file rarely changes. Requiring it on every `fix` invocation is unnecessary when it can be configured once.

**Approach**:

Add `column_defs` field to `[schema]` section in db.toml:

```toml
[schema]
file = "schema.sql"
validate_on_connect = true
column_defs = "column-defs.json"
```

Add to `DatabaseConfig` model:

```python
class DatabaseConfig(BaseModel):
    profiles: dict[str, DatabaseProfile]
    schema_file: str = "schema.sql"
    validate_on_connect: bool = True
    column_defs: str | None = None  # NEW
```

Resolution in `_async_fix()` — same pattern already used for `schema_file`:
1. CLI `--column-defs defs.json` -> use it
2. Not provided -> load from `config.column_defs`
3. Neither -> error

Note: The current `_async_fix()` loads `config` only conditionally (inside `if schema_file is None:`). The implementation must restructure config loading to occur whenever either `schema_file` or `column_defs` needs a fallback. Config loading must remain wrapped in `try/except` with `config = None` fallback so that CLI-flag-only usage (no `db.toml`) continues to work.

Change argparse: `--column-defs` from `required=True` to `required=False, default=None`.

Files to modify:
- `config/models.py` — add `column_defs` field
- `config/loader.py` — parse from `[schema]` section
- `cli/__init__.py` — config fallback in `_async_fix()`, argparse change

Validate: Follows exact pattern of `schema_file` fallback (already working in Steps 4-5 of core-cli-fix).

---

### 2. Config Defaults for Sync Command (`tables`) and Shared `user_id_env`

**What**: Make `--tables` and `--user-id` optional by reading defaults from `db.toml` config.

**Why**: Sync tables and user ID rarely change between invocations. The old MC CLI hardcoded tables and read user_id from `DEV_USER_ID` env var.

**Approach**:

Add `[sync]` and `[defaults]` sections to db.toml:

```toml
[sync]
tables = ["projects", "milestones", "tasks"]

[defaults]
user_id_env = "DEV_USER_ID"
```

`user_id_env` lives under `[defaults]` (not `[sync]`) because it's shared across sync, backup, and restore commands. All three resolve user_id the same way.

Add fields to `DatabaseConfig`:

```python
class DatabaseConfig(BaseModel):
    # ... existing fields ...
    sync_tables: list[str] | None = None    # NEW — from [sync]
    user_id_env: str | None = None          # NEW — from [defaults], shared across commands
```

Resolution in `_async_sync()` (uses shared `_resolve_user_id()` helper defined in Analysis #5):

For `--tables`:
1. CLI `--tables users,orders` -> use it
2. Not provided -> load from `config.sync_tables`
3. Neither -> error

For `--user-id` (shared resolution via `_resolve_user_id()` — used by sync, backup, restore):
1. CLI `--user-id abc123` -> use it
2. Not provided -> read env var named in `config.user_id_env` (e.g., `os.environ["DEV_USER_ID"]`)
3. Neither -> error

Change argparse: `--tables` and `--user-id` from `required=True` to `required=False, default=None`.

Files to modify:
- `config/models.py` — add `sync_tables`, `user_id_env` fields
- `config/loader.py` — parse `[sync]` and `[defaults]` sections
- `cli/__init__.py` — config fallback in `_async_sync()`, argparse changes

Validate: Same resolution pattern as `schema_file` and `column_defs`.

---

### 3. BackupSchema Sourcing via JSON File

**What**: Define how the CLI obtains a `BackupSchema` for backup/restore/validate-backup commands. The user provides a `backup-schema.json` file via `--backup-schema` flag, with an optional fallback to `db.toml` config.

**Why**: The library functions require a `BackupSchema` with application-specific fields (`slug_field`, `user_field`, FK relationships) that cannot be fully auto-discovered from introspection. A JSON file is the simplest approach consistent with how `fix` uses `--schema-file`.

**Approach**:

The JSON file maps directly to the existing Pydantic models:

```json
{
  "tables": [
    {"name": "categories", "pk": "id", "slug_field": "slug", "user_field": "user_id"},
    {
      "name": "products",
      "pk": "id",
      "slug_field": "slug",
      "user_field": "user_id",
      "parent": {"table": "categories", "field": "category_id"},
      "optional_refs": [{"table": "brands", "field": "brand_id"}]
    }
  ]
}
```

Loading pattern:

```python
def _load_backup_schema(path: str) -> BackupSchema:
    """Load and validate a BackupSchema from a JSON file."""
    # Read JSON, validate with BackupSchema(**data), return
```

Config fallback — add `backup_schema` field to `DatabaseConfig`:

```python
class DatabaseConfig(BaseModel):
    # ... existing fields ...
    backup_schema: str | None = None  # NEW: path to backup-schema.json
```

Resolution order: `--backup-schema` flag > `config.backup_schema` from db.toml > error.

Note: Backup/restore commands also need `--user-id`, which follows the shared `user_id_env` resolution from Analysis #2.

Files to modify:
- `cli/__init__.py` — add `_load_backup_schema()` helper
- `config/models.py` — add `backup_schema` field to `DatabaseConfig`
- `config/loader.py` — parse `backup_schema` from `[schema]` section

Validate: `BackupSchema(**json.load(f))` succeeds with valid JSON, raises `ValidationError` with invalid.

---

### 4. Add backup/restore Subcommands

**What**: Add two new subcommands to the main CLI argparse structure. Backup validation is a `--validate` flag on the backup subcommand rather than a separate subcommand.

**Why**: Unifies the CLI surface — one tool, one entry point. Users don't need to know about a separate `cli/backup.py`. Validation is logically part of the backup workflow, not a standalone operation.

**Approach**:

Add to `main()` argparse setup:

**`backup` subcommand** (two modes: create and validate):

Create mode (default):
```
db-adapter backup
db-adapter backup --output backups/my-backup.json
db-adapter backup --tables items,products
db-adapter backup --backup-schema schema.json --user-id abc123    # explicit overrides
```

Validate mode:
```
db-adapter backup --validate backups/backup-2026-03-10.json
db-adapter backup --validate backups/backup.json --backup-schema schema.json  # explicit
```

When `--validate` is provided, backup runs in read-only validate mode. Write-related flags (`--output`, `--tables`, `--user-id`) are ignored — it loads the file and calls `validate_backup()`.

Flags:
- `--backup-schema` — path to backup schema JSON (optional if configured in db.toml). Used in both modes.
- `--user-id` — user ID to filter rows by (optional if `user_id_env` configured in `[defaults]`). Create mode only.
- `--output` / `-o` — optional output path (default: library generates `./backups/backup-{timestamp}.json`). Create mode only.
- `--tables` — optional, comma-separated subset of tables to include from the BackupSchema. Create mode only.
- `--validate` — path to a backup JSON file to validate. Switches to read-only validate mode (no DB connection needed).

**`--tables` semantics for backup**: When provided, the CLI constructs a filtered `BackupSchema` containing only the specified tables (preserving FK relationships for included parents). This is different from `table_filters` in the library API which adds extra WHERE clauses — `--tables` controls *which* tables are backed up, not *which rows*.

```python
# CLI constructs filtered schema before calling library
if args.tables:
    requested = set(args.tables.split(","))
    filtered_tables = [t for t in schema.tables if t.name in requested]
    # Warn if child tables included without their parents (see Risks table)
    for t in filtered_tables:
        if t.parent and t.parent.table not in requested:
            console.print(f"[yellow]Warning: {t.name} references parent {t.parent.table} which is not included[/yellow]")
    schema = BackupSchema(tables=filtered_tables)
```

**`restore` subcommand**:
```
db-adapter restore backups/backup-2026-03-10.json
db-adapter restore backups/backup.json --mode overwrite --yes
db-adapter restore backups/backup.json --dry-run
db-adapter restore backups/backup.json --backup-schema schema.json --user-id abc123  # explicit
```

Flags:
- `backup_path` — positional, path to backup JSON file
- `--backup-schema` — path to backup schema JSON (optional if configured)
- `--user-id` — user ID for restored rows (optional if `user_id_env` configured in `[defaults]`)
- `--mode` / `-m` — skip | overwrite | fail (default: skip)
- `--dry-run` — preview without applying
- `--yes` / `-y` — skip confirmation prompt

Files to modify:
- `cli/__init__.py` — add subparser definitions in `main()`

---

### 5. Async Wiring for Backup Commands

**What**: Implement the async handler functions and sync wrappers that connect the CLI subcommands to the library functions.

**Why**: The library's backup/restore functions are async and require an `adapter` and `schema`. The CLI must create these from config/profile resolution, call the library functions, then clean up.

**Approach**:

Follow the existing pattern (e.g., `cmd_fix` -> `_async_fix`):

```python
def cmd_backup(args: argparse.Namespace) -> int:
    return asyncio.run(_async_backup(args))

async def _async_backup(args: argparse.Namespace) -> int:
    # 1. Load config
    # 2. Resolve backup_schema (--backup-schema or config)
    # 3. Resolve user_id (--user-id or env var from config.user_id_env)
    # 4. Filter schema by --tables if provided
    # 5. Resolve profile + create adapter
    # 6. Call backup_database(adapter, schema, user_id, ...)
    # 7. Close adapter (try/finally)
    # 8. Print result (path, per-table counts)
```

Restore follows the same pattern with additional parameters:

```python
def cmd_restore(args: argparse.Namespace) -> int:
    return asyncio.run(_async_restore(args))

async def _async_restore(args: argparse.Namespace) -> int:
    # 1. Load config
    # 2. Resolve backup_schema (--backup-schema or config)
    # 3. Resolve user_id (--user-id or env var from config.user_id_env)
    # 4. Resolve profile + create adapter
    # 5. If not args.yes: prompt user for confirmation (show backup file path + mode)
    # 6. Call restore_database(adapter, schema, args.backup_path, user_id, mode=args.mode, dry_run=args.dry_run)
    # 7. Close adapter (try/finally)
    # 8. Print result (per-table counts, mode used)
```

When `--validate` is provided, `cmd_backup` short-circuits to the sync `validate_backup()` path — no adapter or async needed (just schema + file path):

```python
def cmd_backup(args: argparse.Namespace) -> int:
    if args.validate:
        return _validate_backup(args)  # sync path -- no DB connection
    return asyncio.run(_async_backup(args))

def _validate_backup(args: argparse.Namespace) -> int:
    # 1. Load config
    # 2. Resolve backup_schema (--backup-schema or config)
    # 3. Call validate_backup(args.validate, schema)
    # 4. Print result (valid/invalid + details)
```

Helper for shared user_id resolution (used by sync, backup, restore):

```python
def _resolve_user_id(args: argparse.Namespace, config: DatabaseConfig | None) -> str | None:
    """Resolve user_id from CLI flag, then env var from config."""
    cli_user_id = getattr(args, "user_id", None)
    if cli_user_id is not None:
        return cli_user_id
    if config and config.user_id_env:
        return os.environ.get(config.user_id_env)
    return None
```

Helper for shared backup_schema path resolution (used by backup, restore, validate, auto-backup in fix):

```python
def _resolve_backup_schema_path(args: argparse.Namespace, config: DatabaseConfig | None) -> str | None:
    """Resolve backup_schema path from CLI flag, then config."""
    cli_path = getattr(args, "backup_schema", None)
    if cli_path is not None:
        return cli_path
    if config and config.backup_schema:
        return config.backup_schema
    return None
```

Note: `_async_backup` and `_async_restore` must use a truthy check (not just `is None`) on the return from `_resolve_user_id()` and return error code 1 with a message like "No user_id available. Set {env_var} or pass --user-id" before calling the library function, since `backup_database()` and `restore_database()` require `user_id: str` (not optional). Empty-string env var values should be treated as "not provided" — `os.environ.get()` can return `""` for set-but-empty env vars.

Files to modify:
- `cli/__init__.py` — add `cmd_backup`, `cmd_restore`, `_async_backup`, `_async_restore`, `_validate_backup`, `_resolve_user_id`, `_resolve_backup_schema_path`

---

### 6. Auto-Backup Before Fix

**What**: When `fix --confirm` applies destructive DDL (DROP+CREATE), automatically create a backup first — same as the old MC CLI did.

**Why**: The old MC CLI always backed up before applying fixes. This was a critical safety net: `fix` can DROP+CREATE tables (when 2+ columns are missing), which is destructive and irreversible. Since the backup library is now internal to db-adapter, the fix command can use it directly.

**Approach**:

Note: `apply_fixes()` already has a `backup_fn` parameter that supports per-table backup callbacks before DROP+CREATE operations. The full-database backup approach here is preferred because it captures a complete snapshot of all tables before any changes are applied, whereas `backup_fn` only backs up individual tables as they are being recreated. The full-database approach provides a single restore point that covers cross-table data consistency.

When `fix --confirm` is about to apply changes:

1. Check if `backup_schema` is configured (config or flag)
2. If configured: load BackupSchema, resolve user_id, create backup before applying fixes
3. If not configured: warn "No backup_schema configured — skipping pre-fix backup" and continue
4. `--no-backup` flag explicitly skips auto-backup (for testing or when data loss is acceptable)

Integration into `_async_fix()`:

Note: The current `_async_fix()` loads `config` only conditionally (inside `if schema_file is None:`) and creates `adapter` after the `args.confirm` check. The implementation must restructure `_async_fix()` to (a) always load config (not just when schema_file is None) and (b) place the auto-backup logic after adapter creation, between adapter creation and the `apply_fixes()` call. Config loading must remain wrapped in `try/except` with `config = None` fallback so that CLI-flag-only usage (no `db.toml`) continues to work. All auto-backup logic must handle `config is None` gracefully.

Note: In the pseudocode below, `profile` is the existing profile name variable in `_async_fix()`, and `timestamp` is generated via `datetime.now().strftime("%Y%m%d-%H%M%S")`.

```
# After adapter creation, before applying fixes:
if confirm and plan.has_fixes and not no_backup:
    1. Resolve backup_schema_path (--backup-schema or config)
    2. If path exists: load BackupSchema, resolve user_id
    3. If user_id exists: call backup_database() with output_path="backups/pre-fix-{profile}-{timestamp}.json"
       - On success: print saved path
       - On failure: abort fix (return 1) -- safety net must work
    4. If user_id missing: warn and continue without backup
    5. If backup_schema_path missing: warn and continue without backup
# Then apply fixes...
```

Add argparse flag:
- `--no-backup` — skip automatic backup before fixing (testing only)

**Output with auto-backup:**
```
Applying fixes...
  1. Backing up database...
     Saved: backups/pre-fix-local-2026-03-10-2130.json
  2. DROP TABLES products, items
  3. CREATE TABLE items
  4. CREATE TABLE products

v Schema fix complete!
```

Files to modify:
- `cli/__init__.py` — add auto-backup logic to `_async_fix()`, add `--no-backup` flag

Validate: Follows the same pattern as the old MC CLI. Gracefully degrades when backup_schema or user_id is not configured.

---

### 7. Retire Standalone cli/backup.py

**What**: Remove the standalone backup CLI file.

**Why**: With backup commands integrated into the main CLI, the standalone file is dead code. Keeping it creates confusion (two entry points, one broken).

**Approach**: Delete `cli/backup.py` entirely. The file was never functional post-extraction — nobody is depending on it.

Files to modify:
- `cli/backup.py` — delete
- `tests/test_lib_extraction_cli.py` — remove or update tests that reference `cli/backup.py` (TestMCCodeRemoved, TestImportStyle, TestBackupCLI use `CLI_BACKUP_PY` or import `db_adapter.cli.backup`)
- `tests/test_lib_extraction_imports.py` — remove or update tests that reference `cli/backup.py` (TestSubpackageImports, TestSysPathRemoved)

---

### 8. Update Documentation

**What**: Update module docstring, CLAUDE.md, README.md to reflect the unified CLI with config-driven defaults.

**Why**: Documentation must reflect the new subcommands and clean usage patterns.

**Approach**:

Update `cli/__init__.py` module docstring:

```python
"""CLI module for database schema management and adapter toolkit.

Commands:
    connect          - Connect to database and validate schema
    status           - Show current connection status
    profiles         - List available profiles
    validate         - Re-validate current profile schema
    fix              - Fix schema drift (auto-backup when configured)
    sync             - Sync data from another profile
    backup           - Backup database to JSON file (+ --validate for file validation)
    restore          - Restore from backup JSON file
"""
```

Update CLAUDE.md CLI Commands section to show clean usage.
Update README.md CLI Reference section to show clean usage.
Update db.toml configuration documentation to include `[sync]` and `[defaults]` sections.

Files to modify:
- `cli/__init__.py` — update module docstring
- `CLAUDE.md` — update CLI Commands section and db.toml example
- `README.md` — update CLI Reference section and db.toml configuration example

---

## Proposed Sequence

> Shows dependencies and recommended order. Planning stage will create actual implementation steps.

**Order**: #1 -> #2 -> #3 -> #4 -> #5 -> #6 -> #7 -> #8

### #1: Config Defaults for Fix Command

**Depends On**: None

**Rationale**: Smallest change, establishes the config fallback pattern for `column_defs`. Same pattern already exists for `schema_file`.

---

### #2: Config Defaults for Sync Command + Shared `user_id_env`

**Depends On**: #1 (shared config model changes)

**Rationale**: Adds `[sync]` and `[defaults]` section parsing. The `user_id_env` mechanism is reused by backup commands (#3-#5) and auto-backup (#6).

---

### #3: BackupSchema Sourcing via JSON File

**Depends On**: #1 (config model pattern)

**Rationale**: Foundation — all three backup subcommands need to load a BackupSchema. The helper function and config field must exist before commands can be wired.

---

### #4: Add backup/restore Subcommands

**Depends On**: #3

**Rationale**: Argparse structure must be defined before async handlers can be connected.

---

### #5: Async Wiring for Backup Commands

**Depends On**: #2 (user_id_env resolution), #3 (backup schema loader), #4 (subparser definitions)

**Rationale**: The handler functions wire the argparse namespace to the library functions. Requires schema loader (#3), user_id resolution (#2), and subparser definitions (#4).

---

### #6: Auto-Backup Before Fix

**Depends On**: #3 (backup schema loader), #5 (backup wiring provides `_resolve_backup_schema_path`, `_resolve_user_id`)

**Rationale**: Depends on the backup infrastructure being in place. Modifies the existing `_async_fix()` to call `backup_database()` before applying destructive DDL.

---

### #7: Retire Standalone cli/backup.py

**Depends On**: #5, #6

**Rationale**: Only safe to remove after both the replacement backup commands and the auto-backup integration are fully wired and tested.

---

### #8: Update Documentation

**Depends On**: #7

**Rationale**: Documentation should reflect the final state after all changes are complete.

---

## Success Criteria

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

## Implementation Options

### Option A: JSON File + db.toml Config (Recommended)

User provides config defaults in `db.toml` and JSON files (`backup-schema.json`, `column-defs.json`). CLI flags override config for one-off use.

**Pros**:
- Consistent with existing `schema_file` pattern
- Simple, no new infrastructure
- JSON maps directly to existing Pydantic models
- User has full control
- Non-breaking — all new fields default to `None`

**Cons**:
- User must create config once (one-time setup)

### Option B: Auto-Generate from Introspection

Use `SchemaIntrospector` to discover tables, PKs, FKs, and auto-generate BackupSchema and column defs.

**Pros**:
- Zero-config for standard schemas

**Cons**:
- Convention-based inference is fragile
- Scope expansion — new feature
- Requires database connection for offline operations

### Recommendation

Option A because: consistent with existing patterns, non-breaking, and the one-time config setup is a small cost for clean ongoing CLI usage.

---

## Files to Modify

> Include this section to give clear scope of changes.

| File | Change | Complexity |
|------|--------|------------|
| `config/models.py` | Modify — add `column_defs`, `backup_schema`, `sync_tables`, `user_id_env` fields | Low |
| `config/loader.py` | Modify — parse `[sync]` and `[defaults]` sections, add new fields from `[schema]` | Low |
| `cli/__init__.py` | Modify — config fallbacks for fix/sync + auto-backup in fix + 2 new subcommands + handlers + helpers | Med |
| `cli/backup.py` | Delete — retire standalone CLI | Low |
| `tests/test_lib_extraction_cli.py` | Modify — remove/update tests referencing `cli/backup.py` | Low |
| `tests/test_lib_extraction_imports.py` | Modify — remove/update tests referencing `cli/backup.py` | Low |
| `CLAUDE.md` | Modify — update CLI Commands, config example | Low |
| `README.md` | Modify — update CLI Reference, config example | Low |

---

## Testing Strategy

> Include this section to outline how changes will be verified.

**Unit Tests** (in `test_lib_extraction_cli.py`):

Config defaults:
- `_async_fix()` with `column_defs` from config (no CLI flag) -> resolves correctly
- `_async_fix()` with CLI `--column-defs` overriding config -> uses CLI value
- `_async_fix()` with neither -> returns 1 with error
- `_async_sync()` with `tables` and `user_id_env` from config -> resolves correctly
- `_async_sync()` with CLI `--tables` and `--user-id` overriding config -> uses CLI values
- `_async_sync()` with neither -> returns 1 with error
- `_resolve_user_id()` reads correct env var, CLI flag takes precedence, missing env var returns None

Auto-backup before fix:
- `_async_fix()` with `--confirm` and `backup_schema` configured -> calls `backup_database()` before `apply_fixes()`
- `_async_fix()` with `--confirm --no-backup` -> does not call `backup_database()`
- `_async_fix()` with `--confirm` but no `backup_schema` -> warns and continues without backup
- `_async_fix()` with `--confirm` but no `user_id` -> warns and continues without backup
- Auto-backup failure aborts fix (safety net must work or fix shouldn't proceed)

Backup commands:
- `cmd_backup` (create mode) with valid schema, valid adapter mock -> returns 0
- `cmd_backup` (create mode) with missing backup-schema -> returns 1 with error
- `cmd_backup` (create mode) with `--tables` flag -> passes filtered BackupSchema to library
- `cmd_backup` with `--validate` flag -> calls `validate_backup()` (sync, no DB connection)
- `cmd_backup` with `--validate` + valid backup -> returns 0, prints valid
- `cmd_backup` with `--validate` + invalid backup -> returns 1, prints errors
- `cmd_restore` with valid backup file -> returns 0
- `cmd_restore` with `--dry-run` -> no writes
- `cmd_restore` with `--mode overwrite` -> calls update
- `_load_backup_schema` with valid JSON -> returns BackupSchema
- `_load_backup_schema` with invalid JSON -> raises error
- `--backup-schema` flag resolution: explicit flag > config > error
- Argparse: both subcommands parse correctly

Config model tests:
- `DatabaseConfig` with new fields defaults to `None` (backward compatible)
- `DatabaseConfig` with all fields populated parses correctly
- Loader parses `[sync]` and `[defaults]` sections

**Live Integration Tests** (in `test_live_integration.py`):
- Backup -> `backup --validate` -> restore round-trip against test database
- Config-driven fix and sync (no explicit flags)
- Fix with auto-backup creates backup file before applying

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| New config fields break existing db.toml parsing | LOW | MED | All fields optional with `None` default — existing configs unaffected |
| `user_id_env` env var not set | MED | LOW | Clear error message: "Set {env_var} or pass --user-id" |
| Adapter not closed on error | MED | MED | Use `try/finally` pattern consistently |
| Auto-backup fails (disk full, permissions) | LOW | HIGH | Abort fix if backup fails — the whole point is safety |
| Large backups exhaust memory | LOW | MED | Out of scope — existing library limitation |
| `--tables` filter removes FK parents | MED | LOW | Warn if child tables included without their parents |

---

## Open Questions

None — all resolved during design (see Decisions Log).

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Config-driven defaults | `db.toml` sections: `[schema]`, `[sync]`, `[defaults]` | Same pattern as existing `schema_file`; non-breaking |
| `user_id_env` location | Under `[defaults]` section (shared) | Used by sync, backup, restore — not sync-specific |
| BackupSchema sourcing | JSON file via `--backup-schema` or config | Consistent with `fix --schema-file` pattern |
| Standalone backup CLI | Delete entirely | File was non-functional; no users depending on it |
| Subcommand naming | `backup` (+ `--validate` flag), `restore` | Validation consolidated into backup subcommand — fewer subcommands, logical grouping |
| Auto-backup before fix | Yes, when `backup_schema` + `user_id` available | Matches old MC CLI safety behavior; graceful degradation when not configured |
| Auto-backup failure | Abort fix | Safety net must work or fix shouldn't proceed |
| Backup `--tables` semantics | Filter BackupSchema tables (not `table_filters`) | `table_filters` adds WHERE clauses; `--tables` controls which tables are included |
| `validate-backup` placement | `backup --validate` flag, not separate subcommand | Validation is part of backup workflow; keeps subcommand count at 8 |
| `--user-id` default | `user_id_env` config reads from env var | Shared by sync, backup, restore; matches old MC CLI pattern |

---

## Next Steps

1. Review this design and confirm approach
2. Run `/review-doc` to check for issues
3. Create implementation plan (`/dev-plan`)
4. Execute implementation (`/dev-execute`)

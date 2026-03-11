# core-backup-cli Design

> **Purpose**: Analyze and design solutions before implementation planning
>
> **Important**: This task must be self-contained (works independently; doesn't break existing functionality and existing tests)

## Executive Summary

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-10T19:35:53-0700 |
| **Task** | Integrate backup/restore/validate-backup as subcommands of the main `db-adapter` CLI |
| **Type** | Feature |
| **Scope** | CLI, config, backup — 3 files modified, 1 file retired |
| **Code** | NO - This is a design document |
| **Risk Profile** | Standard |
| **Risk Justification** | Internal CLI tooling; backup library functions are already tested; adding subcommands alongside existing ones |

**Challenge**: The backup CLI (`cli/backup.py`) is a standalone script with wrong function signatures, no async wrapping, no profile resolution, and no adapter creation — completely non-functional as shipped. It also ships as a separate entry point, fragmenting the CLI surface.

**Solution**: Retire the standalone backup CLI and integrate backup/restore/validate-backup as subcommands of the main `db-adapter` CLI, wired to existing infrastructure (profile resolution, adapter creation, config loading) with a user-provided `backup-schema.json` file.

---

## Context

### Current State

The backup CLI (`cli/backup.py`) was extracted from Mission Control but is completely broken:

```
cli/backup.py problems:
├── backup_database() called without adapter, schema, user_id args
├── restore_database() called without adapter, schema, user_id args
├── validate_backup() called without schema arg
├── All 3 library functions are async but called synchronously
├── No profile resolution (get_adapter, get_active_profile_name)
├── No config loading (load_db_config)
├── Hardcoded paths (Path(__file__).parent / "backups")
└── Separate entry point: python -m db_adapter.cli.backup
```

The library functions themselves are correct and well-tested:

| Function | Signature | Status |
|----------|-----------|--------|
| `backup_database(adapter, schema, user_id, ...)` | async | Working |
| `restore_database(adapter, schema, backup_path, user_id, ...)` | async | Working |
| `validate_backup(backup_path, schema)` | sync | Working |

The main CLI already has 6 working subcommands (connect, status, profiles, validate, fix, sync) with a consistent pattern: sync wrapper calls `asyncio.run(_async_impl(args))`.

### Target State

One unified CLI with 9 subcommands:

```
db-adapter CLI (unified)
├── connect              # existing
├── status               # existing
├── profiles             # existing
├── validate             # existing
├── fix                  # existing
├── sync                 # existing
├── backup               # NEW — export database to JSON
├── restore              # NEW — restore from backup JSON
└── validate-backup      # NEW — validate backup file integrity
```

Backup commands use the same infrastructure as all other commands:

```
User runs: db-adapter backup --backup-schema schema.json --user-id abc123

CLI does:
1. load_db_config() → get profile + DB URL
2. get_adapter() → create AsyncPostgresAdapter
3. Load backup-schema.json → parse into BackupSchema
4. await backup_database(adapter, schema, user_id) → backup file
5. adapter.close()
```

`cli/backup.py` is retired (deleted or converted to a deprecation stub).

---

## Constraints

- **Scope boundaries**: No auto-generation of BackupSchema from introspection — that's a separate feature. Users provide a JSON file.
- **Must NOT happen**: Breaking existing 6 subcommands or their tests. Breaking the backup library functions (`backup/backup_restore.py`, `backup/models.py`).
- **Compatibility**: `BackupSchema`, `TableDef`, `ForeignKey` Pydantic models remain unchanged. The JSON file maps directly to these models.
- **Other guardrails**: Follow the existing CLI pattern (sync wrapper → `asyncio.run(_async_impl)` → library call). No new dependencies.

---

## Analysis

> Each item analyzed independently. No implied order - read in any sequence.

### 1. BackupSchema Sourcing via JSON File

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
      "parent": {"table": "categories", "field": "category_id"}
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
    schema_file: str = "schema.sql"
    validate_on_connect: bool = True
    backup_schema: str | None = None  # NEW: path to backup-schema.json
```

Resolution order: `--backup-schema` flag > `config.backup_schema` from db.toml > error.

Files to modify:
- `cli/__init__.py` — add `_load_backup_schema()` helper
- `config/models.py` — add `backup_schema` field to `DatabaseConfig`

Validate: `BackupSchema(**json.load(f))` succeeds with valid JSON, raises `ValidationError` with invalid.

---

### 2. Add backup/restore/validate-backup Subcommands

**What**: Add three new subcommands to the main CLI argparse structure with appropriate flags.

**Why**: Unifies the CLI surface — one tool, one entry point. Users don't need to know about a separate `cli/backup.py`.

**Approach**:

Add to `main()` argparse setup:

**`backup` subcommand**:
```
db-adapter backup --backup-schema schema.json --user-id abc123
db-adapter backup --backup-schema schema.json --user-id abc123 --output backups/my-backup.json
db-adapter backup --backup-schema schema.json --user-id abc123 --tables orders,items
```

Flags:
- `--backup-schema` — path to backup schema JSON (optional if configured in db.toml)
- `--user-id` — required, user ID to filter rows by
- `--output` / `-o` — optional output path (default: `./backups/backup-{timestamp}.json`)
- `--tables` — optional, comma-separated table filter (maps to `table_filters`)

**`restore` subcommand**:
```
db-adapter restore backups/backup-2026-03-10.json --backup-schema schema.json --user-id abc123
db-adapter restore backups/backup.json --backup-schema schema.json --user-id abc123 --mode overwrite --yes
db-adapter restore backups/backup.json --backup-schema schema.json --user-id abc123 --dry-run
```

Flags:
- `backup_path` — positional, path to backup JSON file
- `--backup-schema` — path to backup schema JSON
- `--user-id` — required, user ID for restored rows
- `--mode` / `-m` — skip | overwrite | fail (default: skip)
- `--dry-run` — preview without applying
- `--yes` / `-y` — skip confirmation prompt

**`validate-backup` subcommand**:
```
db-adapter validate-backup backups/backup-2026-03-10.json --backup-schema schema.json
```

Flags:
- `backup_path` — positional, path to backup JSON file
- `--backup-schema` — path to backup schema JSON

Files to modify:
- `cli/__init__.py` — add subparser definitions in `main()`

---

### 3. Async Wiring for Backup Commands

**What**: Implement the async handler functions and sync wrappers that connect the CLI subcommands to the library functions.

**Why**: The library's backup/restore functions are async and require an `adapter` and `schema`. The CLI must create these from config/profile resolution, call the library functions, then clean up.

**Approach**:

Follow the existing pattern (e.g., `cmd_fix` → `_async_fix`):

```python
def cmd_backup(args: argparse.Namespace) -> int:
    return asyncio.run(_async_backup(args))

async def _async_backup(args: argparse.Namespace) -> int:
    # 1. Load backup schema (from --backup-schema or config)
    # 2. Resolve profile + create adapter
    # 3. Call backup_database(adapter, schema, user_id, ...)
    # 4. Close adapter
    # 5. Print result
```

Adapter lifecycle:

```python
async def _async_backup(args: argparse.Namespace) -> int:
    env_prefix = getattr(args, "env_prefix", "")
    try:
        schema = _load_backup_schema(_resolve_backup_schema_path(args))
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as e:
        console.print(f"[red]Error loading backup schema: {e}[/red]")
        return 1

    try:
        profile_name = get_active_profile_name(env_prefix=env_prefix)
    except ProfileNotFoundError:
        console.print("[red]No active profile. Run: db-adapter connect[/red]")
        return 1

    config = load_db_config()
    adapter = get_adapter(config.profiles[profile_name])
    try:
        path = await backup_database(adapter, schema, user_id=args.user_id, ...)
        console.print(f"[green]Backup saved: {path}[/green]")
        return 0
    except Exception as e:
        console.print(f"[red]Backup failed: {e}[/red]")
        return 1
    finally:
        await adapter.close()
```

Same pattern for `_async_restore` and `cmd_validate_backup` (validate-backup is sync — no adapter needed, just schema + file path).

Files to modify:
- `cli/__init__.py` — add `cmd_backup`, `cmd_restore`, `cmd_validate_backup`, `_async_backup`, `_async_restore`

---

### 4. Retire Standalone cli/backup.py

**What**: Remove or replace the standalone backup CLI file.

**Why**: With backup commands integrated into the main CLI, the standalone file is dead code. Keeping it creates confusion (two entry points, one broken).

**Approach**:

**Option A: Delete** (Recommended)

Remove `cli/backup.py` entirely. The main CLI is the only entry point.

**Pros**: Clean, no dead code, no confusion.
**Cons**: Breaking change if anyone is using `python -m db_adapter.cli.backup` (unlikely — it was broken).

**Option B: Deprecation stub**

Replace contents with a message redirecting to the main CLI:

```python
"""Deprecated. Use: db-adapter backup|restore|validate-backup"""
import sys
print("This entry point is deprecated. Use: db-adapter backup|restore|validate-backup")
sys.exit(1)
```

**Pros**: Gentle migration path.
**Cons**: Unnecessary — the file was never functional post-extraction.

**Recommendation**: Option A (delete). The file was broken — nobody is depending on it.

Files to modify:
- `cli/backup.py` — delete

---

### 5. Update Public Exports and Documentation

**What**: Update module docstring, CLAUDE.md CLI Commands section, and pyproject.toml if needed.

**Why**: The CLI surface has changed — documentation must reflect the new subcommands.

**Approach**:

Update `cli/__init__.py` module docstring to include new commands:

```python
"""CLI module for database schema management and adapter toolkit.

Commands:
    connect          - Connect to database and validate schema
    status           - Show current connection status
    profiles         - List available profiles
    validate         - Re-validate current profile schema
    fix              - Fix schema drift
    sync             - Sync data from another profile
    backup           - Backup database to JSON file
    restore          - Restore from backup JSON file
    validate-backup  - Validate backup file integrity
"""
```

Update CLAUDE.md CLI Commands section to include:
```
db-adapter backup --backup-schema schema.json --user-id abc123
db-adapter restore backup.json --backup-schema schema.json --user-id abc123 --mode skip
db-adapter validate-backup backup.json --backup-schema schema.json
```

Check if pyproject.toml needs any entry point changes (the `db-adapter` entry point already points to `cli:main` — no change needed).

Files to modify:
- `cli/__init__.py` — update module docstring
- `CLAUDE.md` — update CLI Commands section

---

## Proposed Sequence

**Order**: #1 → #2 → #3 → #4 → #5

### #1: BackupSchema Sourcing via JSON File

**Depends On**: None

**Rationale**: Foundation — all three subcommands need to load a BackupSchema. The helper function and config model change must exist before commands can be wired.

---

### #2: Add backup/restore/validate-backup Subcommands

**Depends On**: #1

**Rationale**: Argparse structure must be defined before async handlers can be connected. Depends on #1 because the `--backup-schema` flag resolution uses the helper.

---

### #3: Async Wiring for Backup Commands

**Depends On**: #1, #2

**Rationale**: The handler functions (`_async_backup`, `_async_restore`, `cmd_validate_backup`) wire the argparse namespace to the library functions. Requires both the schema loader (#1) and the subparser definitions (#2).

---

### #4: Retire Standalone cli/backup.py

**Depends On**: #3

**Rationale**: Only safe to remove after the replacement is fully wired and tested.

---

### #5: Update Public Exports and Documentation

**Depends On**: #4

**Rationale**: Documentation should reflect the final state after all changes are complete.

---

## Success Criteria

- [ ] `db-adapter backup --backup-schema schema.json --user-id abc123` creates a valid backup JSON file
- [ ] `db-adapter restore backup.json --backup-schema schema.json --user-id abc123` restores data from backup
- [ ] `db-adapter validate-backup backup.json --backup-schema schema.json` validates backup file integrity
- [ ] All three commands resolve profile via `get_active_profile_name()` and create adapter via `get_adapter()`
- [ ] `--backup-schema` flag falls back to `config.backup_schema` from db.toml when not provided
- [ ] `cli/backup.py` is deleted
- [ ] All existing tests pass (553 unit + 120 live = no regressions)
- [ ] New CLI command tests added for backup/restore/validate-backup

---

## Implementation Options

### Option A: JSON File + db.toml Config (Recommended)

User provides a `backup-schema.json` file via `--backup-schema` flag. Optional fallback to `backup_schema` path in `db.toml`.

**Pros**:
- Consistent with `fix --schema-file` pattern
- Simple, no new infrastructure
- JSON maps directly to existing Pydantic models
- User has full control over table definitions

**Cons**:
- User must create and maintain the JSON file manually

### Option B: Auto-Generate BackupSchema from Introspection

Use `SchemaIntrospector` to discover tables, PKs, and FKs. Infer `slug_field` and `user_field` by convention (`slug`, `user_id`).

**Pros**:
- Zero-config for standard schemas
- Always in sync with live database

**Cons**:
- Convention-based inference is fragile (`slug_field` could be `name`, `title`, etc.)
- Requires database connection just to validate a backup file
- Scope expansion — new feature, not a bug fix
- `SchemaIntrospector` uses psycopg, but backup library uses `DatabaseClient` Protocol — two different connections

### Recommendation

Option A because: consistent with existing CLI patterns, no scope expansion, JSON-to-Pydantic mapping is trivial, and the user already knows their table structure. Option B can be built as a future enhancement.

---

## Files to Modify

| File | Change | Complexity |
|------|--------|------------|
| `cli/__init__.py` | Modify — add 3 subcommands, handlers, schema loader | Med |
| `config/models.py` | Modify — add `backup_schema` field to `DatabaseConfig` | Low |
| `cli/backup.py` | Delete — retire standalone CLI | Low |
| `CLAUDE.md` | Modify — update CLI Commands section | Low |

---

## Testing Strategy

**Unit Tests** (in `test_lib_extraction_cli.py`):
- `cmd_backup` with valid schema, valid adapter mock → returns 0
- `cmd_backup` with missing backup-schema → returns 1 with error
- `cmd_restore` with valid backup file → returns 0
- `cmd_restore` with --dry-run → no writes
- `cmd_restore` with --mode overwrite → calls update
- `cmd_validate_backup` with valid backup → returns 0, prints valid
- `cmd_validate_backup` with invalid backup → returns 1, prints errors
- `_load_backup_schema` with valid JSON → returns BackupSchema
- `_load_backup_schema` with invalid JSON → raises error
- `--backup-schema` flag resolution: explicit flag > config > error
- Argparse: all three subcommands parse correctly

**Live Integration Tests** (in `test_live_integration.py`):
- Backup → validate-backup → restore round-trip against test database
- Backup with `--user-id` filters correctly

**Manual Validation**:
- `db-adapter backup --backup-schema test-backup-schema.json --user-id test-user`
- `db-adapter validate-backup backups/backup-*.json --backup-schema test-backup-schema.json`
- `db-adapter restore backups/backup-*.json --backup-schema test-backup-schema.json --user-id test-user --dry-run`

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Adapter not closed on error | MED | MED | Use `try/finally` pattern consistently (same as existing commands) |
| `backup_schema` config field breaks existing db.toml parsing | LOW | MED | Field is optional with `None` default — existing configs unaffected |
| Confirmation prompt on restore blocks CI/automated use | LOW | LOW | `--yes` flag skips prompt; `--dry-run` has no prompt |
| Large backups exhaust memory | LOW | MED | Out of scope — existing library limitation, not introduced by CLI |

---

## Open Questions

1. **Should `validate-backup` be a hyphenated subcommand or underscore?** Argparse supports both. Hyphenated (`validate-backup`) is conventional for CLI tools. The `dest` attribute handles the Python side.
2. **Should `--user-id` be required for `backup` or default to some value?** The library function requires it. Making it required is clearest. Could potentially read from config in a future enhancement.

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| BackupSchema sourcing | JSON file via `--backup-schema` | Consistent with `fix --schema-file` pattern; no scope expansion |
| Standalone backup CLI fate | Delete entirely | File was non-functional; no users depending on it |
| Subcommand naming | `backup`, `restore`, `validate-backup` | Standard CLI verbs; hyphenated subcommand for consistency |
| Config fallback for backup_schema | Optional `backup_schema` field in DatabaseConfig | Reduces repetitive `--backup-schema` flag for frequent users |

---

## Relationship to core-cli-fix

This design replaces Bug #6 ("Backup CLI Is Completely Non-Functional") from the `core-cli-fix` design. The `core-cli-fix` design should update Bug #6 to reference this document:

> Bug #6 resolution: Moved to separate design doc `docs/core-backup-cli-design.md`. Backup commands integrated as main CLI subcommands instead of fixing the standalone script.

This task can be sequenced after the core-cli-fix bugs are resolved, or in parallel — it has no dependencies on the other bug fixes.

---

## Next Steps

1. Review this design and confirm approach
2. Run `/review-doc` to check for issues
3. Create implementation plan (`/dev-plan`)
4. Execute implementation (`/dev-execute`)

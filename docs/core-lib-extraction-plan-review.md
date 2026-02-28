# Review: Core-Lib-Extraction Plan

| Field | Value |
|-------|-------|
| **Document** | docs/core-lib-extraction-plan.md |
| **Type** | Plan |
| **Created** | 2026-02-27T18:42:32-0800 |

---

## Step Summary

| # | Step | R1 | R2 | R3 |
|---|------|----|-----|-----|
| 0 | Verify Environment and Baseline | 1 LOW | -- | 1 LOW |
| 1 | Consolidate Duplicate Models | 1 MED 1 LOW | -- | -- |
| 2 | Fix Package Imports | 1 MED 1 LOW | 2 MED 2 LOW | -- |
| 3 | Remove MC-Specific Code from Config Loader | 1 LOW | -- | 2 LOW |
| 4 | Remove MC-Specific Code from Factory | 1 MED 1 LOW | 2 MED 1 LOW | 1 MED 1 LOW |
| 5 | Decouple Schema Comparator | -- | 2 LOW | 1 LOW |
| 6 | Convert Adapters to Async | 1 MED 1 LOW | 2 LOW | 1 LOW |
| 7 | Convert Schema Introspector to Async | 1 MED | 2 LOW | 1 LOW |
| 8 | Convert Factory to Async | -- | -- | -- |
| 9 | Generalize Schema Fix Module | -- | 2 LOW | 2 MED 1 LOW |
| 10 | Generalize Backup/Restore | 1 LOW | -- | -- |
| 11 | Generalize Sync Module | 1 MED | 2 MED | 2 MED 1 LOW |
| 12 | Modernize CLI | 3 MED 2 LOW | 1 MED | 1 HIGH 1 MED 2 LOW |
| 13 | Update Package Exports | -- | 2 HIGH 1 MED | 1 LOW |
| 14 | Final Validation | 2 LOW | 1 MED 1 LOW | 2 LOW |

> `--` = Sound

---

## Step Details

### Step 0: Verify Environment and Baseline
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [LOW] Verification command does not verify `supabase` import despite Code section installing `--extra supabase` -> Add `import supabase` to verification command

**R2** (2026-02-27T19:32:22-0800, review-doc-run): Sound

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [LOW] Prerequisites section installs `uv sync --extra dev` (line 80) but Step 0 installs `uv sync --extra dev --extra supabase` (line 200). Prerequisites verification (line 85) does not check `import supabase` -> Update Prerequisites install command to `uv sync --extra dev --extra supabase` and add `import supabase` to verification

### Step 1: Consolidate Duplicate Models
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [MED] Step does not mention that removing `DatabaseProfile`/`DatabaseConfig` from `schema/models.py` will break existing imports in `config/loader.py` (line 11), `factory.py` (line 18), and `schema/sync.py` (line 30). While Step 2 handles import migration, Step 1 should acknowledge this creates a temporarily broken state -> Add a note: "Note: Removing classes from `schema/models.py` will break existing bare imports in `config/loader.py`, `factory.py`, and `schema/sync.py`. These are fixed in Step 2."
- [LOW] Test import paths use bare module refs (`config/models`, `schema/models`) instead of `db_adapter.config.models` and `db_adapter.schema.models` -> Clarify test imports use `db_adapter.*` package paths

**R2** (2026-02-27T19:32:22-0800, review-doc-run): Sound

**R3** (2026-02-27T20:24:03-0800, review-doc-run): Sound

### Step 2: Fix Package Imports
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [MED] Mapping table does not enumerate deferred/runtime bare imports inside function bodies (e.g., `schema/fix.py` lines 212, 296-299; `schema/sync.py` lines 138-140; `cli/__init__.py` lines 152, 407, 439, 521-523) -> Add note: "This mapping also applies to deferred imports inside function bodies and TYPE_CHECKING blocks. Files with function-level bare imports include: `schema/fix.py`, `schema/sync.py`, `cli/__init__.py`, `cli/backup.py`, `backup/backup_restore.py`."
- [LOW] `sys.path.insert` hack in `cli/backup.py` (line 19) not mentioned for removal -> Add sub-bullet to remove `sys.path.insert` workaround

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [MED] Acceptance criteria grep pattern only checks bare module imports but does not verify removal of MC-specific external imports (`from fastmcp ...`, `from creational.common ...`, `from mcp.server.auth ...`). Since `__init__.py` doesn't import those modules, the runtime `import db_adapter` test won't catch them either -> Add acceptance criterion: `grep -rPn "from (fastmcp|creational\.common|mcp\.server\.auth|schema\.db_models) " src/db_adapter/ --include="*.py"` returns zero results (excluding `# REMOVED:` lines)
- [MED] Runtime import test only verifies `config.models`, `schema.models`, and `backup.models` -- not all subpackages. Bare imports remaining in `factory`, `cli`, `adapters`, `schema.comparator/fix/sync`, `backup.backup_restore` would not be caught -> Add import test covering all subpackages: `from db_adapter import factory; from db_adapter import cli; from db_adapter.schema import comparator, fix, sync; from db_adapter.backup import backup_restore`
- [LOW] Note says `cli/backup.py` and `backup/backup_restore.py` have "function-level bare imports" but both have top-level imports (line 21 and lines 22-24 respectively), not function-level -> Revise to separate "top-level bare imports" from "function-level bare imports"
- [LOW] Mapping entry `from backup.backup_cli import ...` -> `from db_adapter.cli.backup import ...` references a pattern that does not exist in the codebase -- no file has `from backup.backup_cli import ...` -> Remove this mapping entry or note it is speculative/unused

**R3** (2026-02-27T20:24:03-0800, review-doc-run): Sound

### Step 3: Remove MC-Specific Code from Config Loader
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [LOW] Sub-task "Update `load_db_config()` import" is redundant with Step 2 which already maps this import -> Reword to "Verify `load_db_config()` import is `from db_adapter.config.models import DatabaseConfig, DatabaseProfile` (already set by Step 2)"

**R2** (2026-02-27T19:32:22-0800, review-doc-run): Sound

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [LOW] Checklist says "Remove `from creational.common.config import SharedSettings`" but Step 2 already converted this to a `# REMOVED:` comment. Step 3 removes the comment, not the original import -> Reword to "Remove the `# REMOVED: from creational.common.config import SharedSettings` comment (left by Step 2)"
- [LOW] Checklist item "Remove `from functools import lru_cache`" and "Remove `from pydantic import AliasChoices, Field`" are standard library/dependency imports used only by the `Settings` class being removed. These are implicit side-effects of removing `Settings`, not separate checklist items -> Consolidate under "Remove `Settings(SharedSettings)` class and all its supporting imports (`functools.lru_cache`, `pydantic.AliasChoices`, `pydantic.Field`)"

### Step 4: Remove MC-Specific Code from Factory
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [MED] When `expected_columns` IS provided, the step must handle the `validate_schema()` call which still has its old 1-param signature (changed in Step 5). The step does not state the interim behavior: keep the 1-arg call for now -> Add note: "When `expected_columns` is provided, the `validate_schema()` call retains its current 1-arg signature -- passing `expected_columns` through happens in Step 5."
- [LOW] `get_active_profile()` is listed as kept but spec does not state whether it should accept `env_prefix` and forward to `get_active_profile_name()` -> Clarify `get_active_profile()` signature with `env_prefix` forwarding

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [MED] Checklist does not mention removing the `# REMOVED: from config import get_settings` comment left by Step 2 in `factory.py`. This orphaned comment violates acceptance criteria ("zero imports from `fastmcp`, `mcp`, or `creational`") -> Add checklist item: "Remove all `# REMOVED:` comments in `factory.py` left by Step 2's import cleanup"
- [MED] Current `get_db_adapter()` has two resolution paths not addressed: `db.toml` existence check (lines 272-274) and `MC_DATABASE_URL` env var fallback (line 286). New `get_adapter()` parameter precedence implicitly replaces both, but neither checklist nor spec explicitly states removal -> Add explicit mention that `get_adapter()` replaces the old `db.toml` existence check and `MC_DATABASE_URL` env var fallback; add checklist item for removal
- [LOW] When `expected_columns` is not None in Step 4, `validate_schema(actual_columns)` still calls `get_all_expected_columns()` from `schema.db_models` which is removed/commented in Step 2. Non-None path will fail at runtime until Step 5 -> Add note that tests should only exercise `expected_columns=None` path until Step 5

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [MED] Checklist adds `env_prefix` parameter to `get_active_profile_name()` but specification also lists `env_prefix` on `connect_and_validate()` and `get_active_profile()` without corresponding checklist items -> Add checklist items: "Add `env_prefix` parameter to `connect_and_validate()`" and "Forward `env_prefix` in `get_active_profile()` to `get_active_profile_name()`"
- [LOW] Test scope note (line 371) says the non-None `expected_columns` path "will raise `ImportError`" but since Step 2 comments out imports with `# REMOVED:` prefix (not removes them), the runtime error would be `NameError` (undefined `get_all_expected_columns`) not `ImportError` -> Change "will raise `ImportError`" to "will raise `NameError`"

### Step 5: Decouple Schema Comparator
**R1** (2026-02-27T18:42:32-0800, review-doc-run): Sound

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [LOW] Acceptance criteria check for zero `schema.db_models` imports may be imprecise -- after Step 2 the import could be in `db_adapter.schema.db_models` form -> Broaden criterion to check for zero imports referencing `db_models` in any form (bare or package-qualified)
- [LOW] Test list says "empty expected returns valid" but no matching acceptance criteria example provided -> Add example: `validate_schema({"t1": {"a"}}, {})` returns `SchemaValidationResult(valid=True, extra_tables=["t1"])`

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [LOW] Checklist item "Remove `from schema.db_models import get_all_expected_columns` import (already converted to `from db_adapter...` or commented out in Step 2)" — the parenthetical is misleading: Step 2 comments out `schema.db_models` imports with `# REMOVED:` prefix, it does not convert them to `from db_adapter...` form (since `db_models` is being eliminated entirely) -> Change parenthetical to "(already commented out with `# REMOVED:` prefix in Step 2)"

### Step 6: Convert Adapters to Async
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [MED] URL rewrite only handles `postgresql://` prefix but not the `postgres://` alias (without "ql") commonly used by Heroku, Railway, and Supabase connection strings. A `postgres://` URL would silently bypass the asyncpg driver -> Add explicit handling: normalize `postgres://` to `postgresql://` first, then apply asyncpg rewrite
- [LOW] `test_connection()` async method mentioned in checklist but no explicit signature provided in Specification (unlike all other methods) -> Add `AsyncPostgresAdapter.test_connection(self) -> bool` signature to Specification

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [LOW] Specification details async conversion for `PostgresAdapter` CRUD methods extensively but does not specify how `AsyncSupabaseAdapter` CRUD methods should be converted -- supabase-py `AsyncClient` requires `.execute()` calls to be awaited -> Add note that `AsyncSupabaseAdapter` CRUD methods must `await` the `.execute()` call on the query builder chain
- [LOW] `adapters/__init__.py` line 7 imports from `adapters.postgres_adapter` but actual file is `adapters/postgres.py` -- a pre-existing broken import. Step says "Update exports" but does not mention this mismatch -> Confirm Step 2 resolves this broken import path or add explicit fix here

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [LOW] Specification says `test_connection()` is "NOT a Protocol method" and converted from "existing sync method" but only specifies it on `AsyncPostgresAdapter` (line 459). `AsyncSupabaseAdapter` has no `test_connection()` mentioned — unclear if it should have one -> Clarify: either add `test_connection()` to `AsyncSupabaseAdapter` spec or note it is intentionally omitted (Supabase client handles connection internally)

### Step 7: Convert Schema Introspector to Async
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [MED] `connect_timeout` kwarg (`psycopg.AsyncConnection.connect(url, connect_timeout=...)`) is described in the `test_connection` bullet but belongs in the `__aenter__` bullet where the connection is actually opened. `test_connection` only runs `SELECT 1` on an already-open connection -> Move `connect_timeout` specification from `test_connection` to `__aenter__`

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [LOW] Specification says "Preserve the existing `connect_timeout` parameter" but current `__init__` has no such parameter -- `connect_timeout=10` is hardcoded as URL appendage in `__enter__` (lines 60-64). The plan is promoting, not preserving -> Reword to: "Promote the existing hardcoded `connect_timeout=10` URL appendage to an explicit constructor parameter"
- [LOW] `__aenter__` snippet uses bare `url` variable (`psycopg.AsyncConnection.connect(url, ...)`) without defining it. After refactor, no URL manipulation needed -> Change to `psycopg.AsyncConnection.connect(self._database_url, connect_timeout=self._connect_timeout)`

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [LOW] `__aenter__` specification (line 501) shows `psycopg.AsyncConnection.connect(self._database_url, connect_timeout=self._connect_timeout)` but this is an awaitable call inside an `async def __aenter__` — needs `await` keyword -> Add `await`: `self._conn = await psycopg.AsyncConnection.connect(self._database_url, connect_timeout=self._connect_timeout)`

### Step 8: Convert Factory to Async
**R1** (2026-02-27T18:42:32-0800, review-doc-run): Sound

**R2** (2026-02-27T19:32:22-0800, review-doc-run): Sound

**R3** (2026-02-27T20:24:03-0800, review-doc-run): Sound

### Step 9: Generalize Schema Fix Module
**R1** (2026-02-27T18:42:32-0800, review-doc-run): Sound

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [LOW] `generate_fix_plan()` described as "pure sync logic, no I/O" but it parses `schema_file` to build FK dependency graph -- reading a file from disk is I/O -> Change to "pure sync logic (file reads only, no network I/O)"
- [LOW] Test requirements do not mention verifying `drop_order`/`create_order` topological sort computation, despite being a non-trivial new feature -> Add explicit test requirement for verifying topological sort correctness

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [MED] `column_definitions` parameter type is `dict[str, str]` but key format is never specified in Step 9. Step 12's `--column-defs` JSON example (line 727-734) uses `"table.column"` format but this convention is not documented in Step 9's spec where the parameter is defined -> Add to Step 9 spec: "`column_definitions` keys use `"table.column"` format (e.g., `{"users.email": "TEXT NOT NULL"}`)"
- [MED] Spec says `AsyncPostgresAdapter.execute()` uses `async with self._engine.begin() as conn` (line 584) but existing `fix.py` code may reference `adapter._conn` to access the database connection directly. Step 9 should call `adapter.execute()` (Protocol method) not access adapter internals -> Add note: "All DDL execution in `apply_fixes()` must use `adapter.execute(sql)` Protocol method, not `adapter._conn` or `adapter._engine` internals"
- [LOW] `apply_fixes()` wraps each `execute()` call individually to catch `NotImplementedError`, meaning the `RuntimeError` is raised on the first DDL statement rather than failing eagerly at function entry -> Clarify this is intentional: per-call wrapping allows partial DDL execution reporting before failure

### Step 10: Generalize Backup/Restore
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [LOW] Acceptance criterion "Zero imports from `db`, `config`, or `adapters`" is ambiguous since `DatabaseClient` must be imported from `db_adapter.adapters.base` -> Reword to: "Zero bare MC-style imports (`from db import ...`, `from config import ...`, `from adapters import ...`); all imports use `db_adapter.*` package paths"

**R2** (2026-02-27T19:32:22-0800, review-doc-run): Sound

**R3** (2026-02-27T20:24:03-0800, review-doc-run): Sound

### Step 11: Generalize Sync Module
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [MED] `sync_data` adds `schema: BackupSchema | None = None` parameter with dual-path behavior not present in Design Analysis #9. This is a meaningful enhancement but not acknowledged as a design divergence -> Add note acknowledging this extends the design's original approach

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [MED] Task checklist bullet says "Internal adapter creation via `_resolve_url`" using old private name, while Specification and Acceptance Criteria correctly reference renamed public `resolve_url`. Also flagged holistically: the rename is split across Steps 4 and 11, breaking Step 4 tests [Elevated from LOW -- overlaps with holistic Contradictions] -> Update task bullet to use `resolve_url`; consider moving rename to Step 4
- [MED] Dual-path sync behavior (direct select/insert vs backup/restore) is a significant design decision but lacks an explicit Trade-offs section. Also flagged holistically: no error handling spec for slug conflicts or FK violations on direct insert path [Elevated from LOW -- overlaps with holistic Surprises] -> Add Trade-offs subsection and error handling specification for direct insert path

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [MED] `compare_profiles()` accepts `env_prefix` parameter (line 671) but the function creates adapters internally from profile names via `load_db_config` and `resolve_url` — `env_prefix` is not used in the function body since profile names are provided explicitly -> Either remove `env_prefix` from `compare_profiles()` or document how it is used (e.g., forwarded to `get_active_profile_name()` for default profile resolution)
- [MED] `SyncResult` spec (line 670) lists only `source_counts`, `dest_counts`, `sync_plan` but `sync_data()` needs to report what was actually synced — missing `synced_count: int`, `skipped_count: int`, `errors: list[str]` fields -> Add `synced_count: int = 0`, `skipped_count: int = 0`, `errors: list[str] = Field(default_factory=list)` to `SyncResult`
- [LOW] Internal adapter creation says `AsyncPostgresAdapter(database_url=url)` but doesn't specify the import path needed -> Add: `from db_adapter.adapters.postgres import AsyncPostgresAdapter`

### Step 12: Modernize CLI
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [MED] `get_dev_user_id` is imported at line 35 and used at line 161 of CLI but has no explicit checklist item for removal. Step 4 removes it from factory.py, breaking the CLI import -> Add explicit checklist item: "Remove `get_dev_user_id` import (line 35) and all usages"
- [MED] `cmd_fix()` call pattern shows `expected_columns=expected` but does not specify how `expected_columns` dict is derived from `--schema-file` input. Parsing CREATE TABLE to extract column sets should be called out -> Add specification for how CLI parses `--schema-file` to extract `expected_columns`
- [MED] `cmd_sync()` does not address the `user_id` parameter that Step 11's `compare_profiles()`/`sync_data()` require -> Add `--user-id` CLI argument to `cmd_sync()` specification
- [LOW] `cmd_fix()` call pattern uses `result.validation` but `ConnectionResult` model has `schema_report` field, not `validation` -> Fix to `result.schema_report`
- [LOW] `cmd_fix()` subprocess backup call (lines 536-547) invoking `backup/backup_cli.py` not mentioned for removal -> Add checklist item to remove/replace subprocess-based backup call

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [MED] `cli/backup.py` contains "Mission Control" text at line 2 (docstring) and line 120 (argparse description). Acceptance criteria requires no "Mission Control" in any CLI file, but checklist only addresses import updates for `cli/backup.py` -> Add checklist item: "Remove 'Mission Control' from `cli/backup.py` docstring and argparse description; replace with generic text"

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [HIGH] `_parse_expected_columns()` is called in `cmd_fix()` specification (line 735: `expected = _parse_expected_columns(schema_file)`) but this function is never specified — no signature, no description of how it parses CREATE TABLE SQL to extract `dict[str, set[str]]`, no error handling for malformed SQL. This is a non-trivial function that is critical to the `cmd_fix` flow [Elevated from MED -- also flagged holistically] -> Add specification: `def _parse_expected_columns(schema_file: str | Path) -> dict[str, set[str]]`: parses CREATE TABLE statements from the SQL file, extracts table names and column names, returns `{table_name: {col1, col2, ...}}`. Add to checklist and acceptance criteria.
- [MED] Specification says all `cmd_*` functions wrap async via `asyncio.run()` (line 726) but `cmd_status` and `cmd_profiles` in the current codebase only read local files (lock file, TOML config) — they make no database calls. Wrapping them in `asyncio.run()` is unnecessary overhead -> Clarify: `cmd_status` and `cmd_profiles` remain sync (no DB calls); only `cmd_connect`, `cmd_validate`, `cmd_fix`, `cmd_sync` need async wrapping
- [LOW] `_show_profile_comparison()` is listed for "removal/refactoring" (line 738) but the directive is ambiguous — should it be removed entirely or refactored to accept a `tables` parameter? -> Specify: remove `_show_profile_comparison()` (data count display requires DB queries that belong in `cmd_status`, not in a helper that assumes table names)
- [LOW] Step 12 has no Trade-offs section despite being one of the most complex steps (CLI modernization with async wrapping, argument changes, multiple command updates) -> Add Trade-offs section discussing: keeping `cli/backup.py` as separate unregistered module vs integrating; `asyncio.run()` per-command vs shared event loop

### Step 13: Update Package Exports
**R1** (2026-02-27T18:42:32-0800, review-doc-run): Sound

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [HIGH] Missing `compare_profiles`, `sync_data`, `SyncResult` from `schema/__init__.py` exports. These are listed in plan Deliverables (line 34) and directory structure (line 143) as public API -> Add `"compare_profiles"`, `"sync_data"`, `"SyncResult"` to `schema/__init__.py` `__all__`
- [HIGH] Missing `generate_fix_plan`, `apply_fixes`, `FixPlan` from `schema/__init__.py` exports. These are listed in directory structure (line 142) as public functions created in Step 9 -> Add `"generate_fix_plan"`, `"apply_fixes"`, `"FixPlan"` to `schema/__init__.py` `__all__`
- [MED] Missing `resolve_url` from factory exports. Step 11 (line 667) explicitly states `_resolve_url` must be renamed to `resolve_url` (public) and "added to factory `__all__` in Step 13" -> Add `resolve_url` to factory exports and consider top-level exports

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [LOW] Acceptance criteria import verification lines (791-793) do not include `resolve_url` despite it being listed in Step 13's specification exports (line 776) -> Add `resolve_url` to acceptance criteria: `uv run python -c "from db_adapter import resolve_url"` succeeds

### Step 14: Final Validation
**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- [LOW] Grep pattern for forbidden imports omits bare `import schema.db_models` form -> Add `|import schema\.db_models` to the grep pattern
- [LOW] Verification import block does not import `ProfileNotFoundError` from `db_adapter`, though it is a required top-level export per Step 13 and "What Done Looks Like" -> Add `ProfileNotFoundError` to verification import line

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- [MED] Grep for hardcoded MC table names (`"projects"|"milestones"|"tasks"`) will match docstring example in `backup/models.py` (lines 10-14). File is marked "No change" but grep check would fail -> Either add task to Step 10 to update docstring example with generic table names, or mark `backup/models.py` as needing docstring modification
- [LOW] Import smoke test omits several Step 13 exports: `backup_database`, `restore_database`, `validate_backup` from `db_adapter.backup` -> Add these to the verification import script

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- [LOW] Specification text (line 819) says "forbidden patterns: `fastmcp`, `creational.common`, `mcp.server.auth`, `schema.db_models`" listing `mcp.server.auth` specifically, but acceptance criteria grep (line 827) uses broader `from mcp.server` pattern. Spec text should match the grep pattern -> Align spec text with grep: change "mcp.server.auth" to "mcp.server" in the specification description
- [LOW] Verification import script (lines 855-863) does not include `resolve_url` from `db_adapter` despite it being a required top-level export per Step 13 -> Add `from db_adapter import resolve_url` to the verification import script

---

## Holistic Summary

| Concern | R1 | R2 | R3 |
|---------|----|-----|-----|
| Template Alignment | -- | -- | -- |
| Soundness | -- | -- | -- |
| Flow & Dependencies | -- | -- | -- |
| Contradictions | -- | 1 MED | -- |
| Clarity & Terminology | -- | -- | -- |
| Surprises | 2 MED 2 LOW | 2 MED 3 LOW | 1 MED |
| Cross-References | 1 MED | -- | 1 MED 1 LOW |

---

## Holistic Details

**R1** (2026-02-27T18:42:32-0800, review-doc-run):
- **[Cross-References]** [MED] Plan adds Step 8 (factory async conversion) as a separate step not present in the design's proposed sequence or analysis items. The design's #2 covers MC removal only; factory async is implied but not explicitly analyzed -> Add note in Step-to-Design Mapping acknowledging Step 8 is a plan refinement not present as a separate design analysis item
- **[Surprises]** [MED] The `# REMOVED:` comment strategy (Step 2) distributes cleanup across Steps 3-12 without tracking. Step 14 grep only checks `fastmcp`, `creational`, `mcp.server` -- not ALL `# REMOVED:` patterns -> Broaden Step 14 grep: `grep -rn "# REMOVED:" src/db_adapter/`
- **[Surprises]** [MED] `_resolve_url` used cross-module (from `factory.py` in `sync.py`) as private function. Plan suggests renaming but no acceptance criterion commits to resolution -> Add acceptance criterion to Step 11 or Step 13 requiring public API (`resolve_url` or `get_database_url()`)
- **[Surprises]** [LOW] `apply_fixes()` wraps `execute()` with error for `NotImplementedError`, but no acceptance criterion verifies this error path -> Add criterion to Step 9: calling `apply_fixes()` with adapter that raises `NotImplementedError` on `execute()` raises `RuntimeError`
- **[Surprises]** [LOW] Supabase `try/except ImportError` conditional import not verified. No criterion checks that adapter imports succeed when supabase is not installed -> Add criterion to Step 6 or Step 13: `from db_adapter.adapters import AsyncPostgresAdapter` succeeds without supabase extra installed

**R2** (2026-02-27T19:32:22-0800, review-doc-run):
- **[Contradictions]** [MED] Step 4 keeps `_resolve_url()` as private and tests it by that name, but Step 11 renames it to `resolve_url()` (public) in a sync module step. This splits a factory.py change across an unrelated step and means Step 4 tests break in Step 11 -> Move rename from `_resolve_url` to `resolve_url` to Step 4 (factory MC removal) where the function is already being modified
- **[Surprises]** [MED] Step 6 acceptance criteria says "All 5 Protocol methods are `async def`" but Step 9 adds a 6th method (`execute`). Step 6 criteria becomes retroactively incomplete -> Change Step 6 to "All 5 CRUD+lifecycle Protocol methods" and add note that Step 9 extends Protocol with `execute`
- **[Surprises]** [MED] Step 4 creates sync factory tests that Step 8 rewrites for async, but plan does not specify whether same file is modified or new tests added. Could lead to orphaned sync tests -> Add instruction to Step 8: "Modify `test_lib_extraction_factory.py` to replace sync factory tests with async factory tests"
- **[Surprises]** [LOW] `sync_data()` dual-path (direct insert when `schema=None`, backup/restore when provided) has no error handling spec for slug conflicts, partial failures, or FK constraint violations on the direct insert path -> Add error handling specification for direct insert path
- **[Surprises]** [LOW] "What Done Looks Like" grep pattern is less thorough than Step 14's pattern (missing `import X` forms) -> Update to match Step 14's pattern
- **[Surprises]** [LOW] `--column-defs` CLI argument (Step 12) introduces a JSON format for the first time without formal schema or multi-entry example -> Add specification or example file reference for the JSON format

**R3** (2026-02-27T20:24:03-0800, review-doc-run):
- **[Cross-References]** [MED] `FixResult` is created in Step 9 and used by `apply_fixes()` return type but not included in `schema/__init__.py` `__all__` exports (Step 13, line 786). Callers importing `from db_adapter.schema import ...` cannot access `FixResult` -> Add `"FixResult"` to `schema/__init__.py` `__all__` list in Step 13 spec
- **[Cross-References]** [LOW] `ColumnFix` and `TableFix` are created in Step 9 as part of `FixPlan` structure but not exported from `schema/__init__.py`. While less commonly needed by callers, they are part of the public API surface for type checking -> Add `"ColumnFix"`, `"TableFix"` to `schema/__init__.py` `__all__` list
- **[Surprises]** [MED] `_parse_expected_columns()` is called in Step 12's `cmd_fix()` flow (line 735) but never specified in any step — no signature, no parsing logic, no error handling. This is a gap between Steps 9 (which defines `column_definitions`) and Step 12 (which calls it) [Elevated from LOW -- overlaps with Step 12 item review] -> Add `_parse_expected_columns()` specification to Step 12

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-02-27T18:42:32-0800 | review-doc-run | Parallel (15 item + 1 holistic) | 12 MED 13 LOW | Applied (25 of 25) |
| R2 | 2026-02-27T19:32:22-0800 | review-doc-run | Parallel (15 item + 1 holistic) | 2 HIGH 12 MED 15 LOW | Applied (29 of 29) |
| R3 | 2026-02-27T20:24:03-0800 | review-doc-run | Parallel (15 item + 1 holistic) --auto | 1 HIGH 8 MED 15 LOW | Applied (24 of 24) |

---

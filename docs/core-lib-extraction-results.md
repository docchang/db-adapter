# Core-Lib-Extraction Results

## Summary
| Attribute | Value |
|-----------|-------|
| **Status** | Complete |
| **Started** | 2026-02-27T20:45:26-0800 |
| **Completed** | 2026-02-27T21:59:09-0800 |
| **Reviewed** | 2026-02-28T00:15:17-0800 |
| **Proves** | That db-adapter can be extracted into a standalone async-first library with zero MC-specific code |

## Diagram

```
┌──────────────────────────────────────────┐
│           Core Lib Extraction            │
│              EXTRACTION                  │
│             ✅ Complete                   │
│                                          │
│ Architecture                             │
│   • 5-layer async-first library          │
│   • Protocol-typed DatabaseClient        │
│   • Zero MC-specific code                │
│                                          │
│ Adapters                                 │
│   • AsyncPostgresAdapter (asyncpg)       │
│   • AsyncSupabaseAdapter (optional)      │
│   • JSONB as constructor param           │
│                                          │
│ Schema                                   │
│   • Async SchemaIntrospector (psycopg)   │
│   • Decoupled validate_schema()          │
│   • Topological sort for DDL order       │
│                                          │
│ Capabilities                             │
│   • BackupSchema-driven backup/restore   │
│   • Dual-path sync (direct + FK-aware)   │
│   • CLI with asyncio.run() wrappers      │
│   • Configurable env prefix              │
│                                          │
│ Quality                                  │
│   • 553 tests, 100% pass rate            │
│   • 13/13 success criteria met           │
└──────────────────────────────────────────┘
```

---

## Goal
Extract db-adapter into a standalone async-first Python library with zero Mission Control-specific code. All adapters, schema tools, config, backup/restore, and CLI converted to async-first with proper `db_adapter.*` package imports, Protocol typing, Pydantic models, and configurable parameters instead of hardcoded constants.

---

## Success Criteria
From `docs/core-lib-extraction-plan.md`:

- [x] `uv sync` installs without errors
- [x] `uv run python -c "from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter"` succeeds
- [x] Zero imports from `fastmcp`, `creational.common`, `mcp.server.auth`, or `schema.db_models` in `src/`
- [x] Zero hardcoded MC-specific table names (`"projects"`, `"milestones"`, `"tasks"`) in library code
- [x] `DatabaseClient` Protocol has all `async def` methods
- [x] `AsyncPostgresAdapter` uses `create_async_engine` with `asyncpg` driver
- [x] `SchemaIntrospector` uses `psycopg.AsyncConnection` with `__aenter__`/`__aexit__`
- [x] `validate_schema()` accepts `(actual_columns, expected_columns)` -- two parameters
- [x] `JSONB_COLUMNS` is a constructor parameter, not a class constant
- [x] `BackupSchema` model drives backup/restore instead of hardcoded table logic
- [x] No duplicate model classes across `config/models.py` and `schema/models.py`
- [x] CLI uses `db-adapter` as program name
- [x] All existing model schemas (`BackupSchema`, `TableDef`, `ForeignKey`, `DatabaseProfile`, etc.) preserved

**ALL SUCCESS CRITERIA MET**

---

## Prerequisites Completed
- [x] Identified affected tests -- no existing test files; all tests will be created during implementation steps
- [x] Installed dependencies -- `uv sync --extra dev --extra supabase` succeeded; all imports verified
- [x] Confirmed `config/models.py` and `schema/models.py` are identical -- `diff` returned no output

---

## Implementation Progress

### Step 0: Verify Environment and Baseline -- Complete
**Status**: Complete (2026-02-27T20:45:26-0800)
**Expected**: Confirm the development environment is ready and establish a clean starting point.

**Implementation**:
- Installed all dependencies including dev and supabase extras via `uv sync --extra dev --extra supabase`
- Verified `config/models.py` and `schema/models.py` are byte-identical (diff returned empty)
- Created `tests/__init__.py` marker file
- Verified all key dependencies import successfully: sqlalchemy, pydantic, asyncpg, psycopg, supabase

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: N/A (Step 0 uses inline verification, not pytest)
```bash
$ uv run python -c "import sqlalchemy; import pydantic; import asyncpg; import psycopg; import supabase; print('OK')"
OK

$ diff src/db_adapter/config/models.py src/db_adapter/schema/models.py
(no output -- files are identical)

$ uv run pytest tests/ -v --tb=short
collected 0 items -- no tests ran (expected baseline)
```

**Issues**:
- None

**Trade-offs & Decisions**:
- No significant trade-offs -- straightforward environment verification per plan.

**Lessons Learned**:
- The `config/models.py` and `schema/models.py` files are byte-identical (12 Pydantic model classes each). Step 1 will consolidate them by domain: config models stay in `config/models.py`, introspection/validation models stay in `schema/models.py`.
- `tests/` directory existed but was empty (no `__init__.py`). Created the marker file for proper test package structure.

**Result**: Environment ready. Dependencies installed and verified. Model duplication confirmed. Ready for Step 1 (Consolidate Duplicate Models).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:39-0800
- **Intent match**: PASS -- The plan specifies three actions: install dependencies, verify model file duplication, and create the tests directory marker. The results doc confirms all three were completed with matching verification output (`uv sync --extra dev --extra supabase` succeeded, `diff` returned no output confirming identical files, `tests/__init__.py` was created). The design doc's intent for this step is purely environmental readiness, and the implementation satisfies that exactly.
- **Assumption audit**: PASS -- No assumptions were introduced beyond what the plan specified. The executor ran the exact commands listed in the plan (dependency install, diff verification, marker file creation) and the inline verification command (`import sqlalchemy; import pydantic; ...`). The conclusion that files are byte-identical matches the plan's prerequisite 3 expectation.
- **Architectural drift**: PASS -- Step 0 made no architectural changes. The only filesystem change was creating `tests/__init__.py` (an empty marker file), which matches the plan's specification. No source code was modified or added. The project structure remains unchanged from the initial scaffold.

---

### Step 1: Consolidate Duplicate Models -- Complete
**Status**: Complete (2026-02-27T20:50:14-0800)
**Expected**: Split config/models.py and schema/models.py by domain so each model lives in exactly one canonical location.

**Implementation**:
- Reduced `config/models.py` to contain only `DatabaseProfile` and `DatabaseConfig` (2 classes)
- Removed `DatabaseProfile` and `DatabaseConfig` from `schema/models.py`, leaving 10 classes: `ColumnDiff`, `SchemaValidationResult`, `ConnectionResult`, `ColumnSchema`, `ConstraintSchema`, `IndexSchema`, `TriggerSchema`, `FunctionSchema`, `TableSchema`, `DatabaseSchema`
- Added docstrings with usage examples to both module files
- Updated module-level docstrings to document which models belong where

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 27/27 tests passing
```bash
tests/test_lib_extraction_models.py::TestModelPlacement (5 tests) - PASSED
tests/test_lib_extraction_models.py::TestGrepUniqueness (3 tests) - PASSED
tests/test_lib_extraction_models.py::TestConfigModels (5 tests) - PASSED
tests/test_lib_extraction_models.py::TestSchemaModels (14 tests) - PASSED
```

**Issues**:
- None encountered.

**Trade-offs & Decisions**:
- No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- The two files were byte-for-byte identical, making the split clean with no merge conflicts.
- AST-based inspection in tests is more reliable than grep for verifying class placement since it avoids false positives from comments or string literals.
- Using both AST inspection and subprocess grep provides defense-in-depth: AST for structural correctness, grep for codebase-wide uniqueness.

**Result**: Step 1 complete. Both model files now contain only their domain-specific classes with zero overlap. Ready for Step 2 (Fix Package Imports).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:30-0800
- **Intent match**: PASS -- The plan specifies splitting models by domain: config models (DatabaseProfile, DatabaseConfig) stay in config/models.py, schema models stay in schema/models.py. The results confirm both files contain only their domain-specific classes with zero overlap, matching the design doc's target layout.
- **Assumption audit**: PASS -- No assumptions beyond plan specification. AST-based and grep-based dual verification provides defense-in-depth. The byte-identical starting state made the split straightforward with no merge conflict decisions.
- **Architectural drift**: PASS -- File locations match the plan's architecture: config models in config/models.py, schema models in schema/models.py. Test file follows the project naming convention. No new files created beyond what was specified.

---

### Step 2: Fix Package Imports -- Complete
**Status**: Complete (2026-02-27T20:50:05-0800)
**Expected**: Convert all bare module imports to proper db_adapter.* package imports so the package can be imported when installed.

**Implementation**:
- Converted all bare imports across 10 source files to proper `db_adapter.*` package paths
- Fixed `adapters/__init__.py` to import from `db_adapter.adapters.base` and `db_adapter.adapters.postgres` (not `postgres_adapter`)
- Updated model imports to point to canonical locations per Step 1 (e.g., `DatabaseProfile` from `db_adapter.config.models`, `ConnectionResult` from `db_adapter.schema.models`)
- Commented out MC-specific imports with `# REMOVED:` prefix: `fastmcp`, `creational.common.config`, `mcp.server.auth`, `schema.db_models`, `config.get_settings`
- Stubbed function bodies that depend on removed imports (`get_dev_user_id()`, `get_user_id_from_ctx()`, `validate_schema()`) with `pass` and explanatory notes
- Replaced `settings.db_provider` references in `backup_restore.py` with hardcoded `"postgres"` placeholder
- Removed `sys.path.insert` workaround from `cli/backup.py`

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 34/34 tests passing (61/61 full suite)
```bash
tests/test_lib_extraction_imports.py::TestNoBareImports (5 tests) - PASSED
tests/test_lib_extraction_imports.py::TestMCImportsRemoved (4 tests) - PASSED
tests/test_lib_extraction_imports.py::TestSubpackageImports (17 tests) - PASSED
tests/test_lib_extraction_imports.py::TestAdaptersInitCorrectness (2 tests) - PASSED
tests/test_lib_extraction_imports.py::TestSysPathRemoved (1 test) - PASSED
tests/test_lib_extraction_imports.py::TestModelImportLocations (5 tests) - PASSED
```

**Issues**:
- Initial grep-based bare import tests produced false positives from docstrings, comments, and string literals (e.g., `from schema.fix import ...` in module docstrings). Switched to AST-based import inspection which only checks actual import statements.

**Trade-offs & Decisions**:
- **Decision:** Used AST inspection instead of grep for bare import detection in tests.
  - **Alternatives considered:** grep with complex regex to exclude comments/docstrings.
  - **Why this approach:** AST parsing is structurally correct -- it only examines actual Python import nodes, avoiding false positives from strings, comments, and docstrings. More reliable than regex.
  - **Risk accepted:** AST-only detection won't catch dynamic imports constructed via `__import__()` or `importlib`, but no such patterns exist in this codebase.

**Lessons Learned**:
- Grep-based import checks on Python files are unreliable because module path strings appear in docstrings (Usage examples), comments (REMOVED markers), and string literals. AST inspection is the correct approach for detecting actual import statements.
- The `adapters/__init__.py` file was importing from `adapters.postgres_adapter` which doesn't match the actual filename `postgres.py` -- this was a pre-existing mismatch that Step 2 corrected.
- Functions whose bodies depend on removed MC imports need to be stubbed with `pass` (not deleted) so that other modules importing those functions continue to load without `ImportError`. The stubs serve as markers for later steps that will remove or rewrite them.

**Result**: Step 2 complete. All bare module imports converted to proper `db_adapter.*` package paths. MC-specific external imports removed/commented. All subpackages import cleanly. Ready for Step 3 (Remove MC-Specific Code from Config).

**Review**: PASS
**Reviewed**: 2026-02-28T00:12:06-0800
- **Intent match**: PASS -- Design Analysis #1 requires converting all bare imports to proper db_adapter.* paths. All six acceptance criteria are satisfied: zero bare imports via grep, zero active MC-specific imports, import db_adapter succeeds, model imports from canonical locations succeed, all subpackages import cleanly, 34 tests pass. The adapters/__init__.py correctly imports from db_adapter.adapters.base and db_adapter.adapters.postgres.
- **Assumption audit**: PASS -- AST-based inspection for bare import detection is documented in Trade-offs & Decisions with rationale. The # REMOVED: comment approach for MC-specific imports was specified by the plan. The settings.db_provider replacement with hardcoded "postgres" placeholder is a reasonable stub for later steps. No undocumented assumptions introduced.
- **Architectural drift**: PASS -- All imports follow the absolute db_adapter.* pattern. Model imports point to canonical locations per Step 1's consolidation. The optional Supabase import pattern in adapters/__init__.py uses try/except, consistent with the design's intent. No structural deviations.

---

### Step 3: Remove MC-Specific Code from Config Loader -- Complete
**Status**: Complete (2026-02-27T20:57:51-0800)
**Expected**: Strip Settings class, get_settings(), and SharedSettings import from config/loader.py. Keep only the generic TOML-based load_db_config(). Update config/__init__.py exports.

**Implementation**:
- Rewrote `config/loader.py` to contain only `load_db_config()` with three imports: `tomllib`, `pathlib.Path`, `db_adapter.config.models`
- Removed all `# REMOVED:` comments left by Step 2 (Settings class, get_settings, SharedSettings, functools, pydantic)
- Changed default `config_path` from `Path(__file__).parent / "db.toml"` to `Path.cwd() / "db.toml"` so the library reads config from the consuming project's working directory
- Updated `config/__init__.py` to export `load_db_config`, `DatabaseProfile`, `DatabaseConfig` with `__all__`
- Added module-level docstring with usage examples to `config/loader.py`
- Added type annotations to local variables (`profiles: dict[str, DatabaseProfile]`, `schema_settings: dict`)

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 23/23 tests passing (84/84 full suite)
```bash
tests/test_lib_extraction_config.py::TestMCCodeRemoved (8 tests) - PASSED
tests/test_lib_extraction_config.py::TestLoadDbConfig (8 tests) - PASSED
tests/test_lib_extraction_config.py::TestConfigInitExports (5 tests) - PASSED
tests/test_lib_extraction_config.py::TestLoaderModuleAttributes (2 tests) - PASSED
```

**Issues**:
- None encountered.

**Trade-offs & Decisions**:
- No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- The `# REMOVED:` comment approach from Step 2 worked well as breadcrumbs -- it was clear exactly what needed to be deleted in this step. Clean removal is simpler than incremental commenting.
- Changing the default path from `Path(__file__).parent` to `Path.cwd()` is essential for library semantics: a library should read config from the consumer's working directory, not from inside its own installed package.
- The `config/__init__.py` re-export pattern (`from .loader import load_db_config`) provides a clean public API (`from db_adapter.config import load_db_config`) while keeping implementation in `loader.py`.

**Result**: Step 3 complete. Config loader is now a clean, generic TOML loader with zero MC-specific code. Ready for Step 4 (Remove MC-Specific Code from Factory).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:33-0800
- **Intent match**: PASS -- Design doc specifies stripping Settings class, get_settings(), and SharedSettings import from config/loader.py, keeping only generic TOML-based load_db_config() with Path.cwd() default. All six acceptance criteria are met: loader.py contains exactly three imports (tomllib, pathlib.Path, db_adapter.config.models), the default path uses Path.cwd(), and config/__init__.py exports exactly {load_db_config, DatabaseConfig, DatabaseProfile} via __all__.
- **Assumption audit**: PASS -- No hidden assumptions introduced. The error message wording and type annotations on local variables are minor details neither the design nor plan constrained. The schema_settings parsing logic faithfully preserves existing DatabaseConfig model defaults.
- **Architectural drift**: PASS -- File locations match the plan's architecture: config models in config/models.py, loader in config/loader.py, re-exports in config/__init__.py. Import pattern uses absolute db_adapter.config.models as required. The loader depends only on config.models (downward in the config layer), consistent with the 5-layer architecture.

---

### Step 4: Remove MC-Specific Code from Factory -- Complete
**Status**: Complete (2026-02-27T21:04:00-0800)
**Expected**: Strip all Mission Control-specific functions and imports from factory.py, restructure get_db_adapter() to get_adapter(), and make connect_and_validate() accept caller-provided expected_columns.

**Implementation**:
- Removed 6 MC-specific functions/classes: `AuthenticationError`, `get_dev_user_id()`, `get_user_id_from_ctx()`, `cleanup_project_all_dbs()`, `cleanup_projects_pattern()`, `reset_client()`
- Removed module-level `_adapter` global cache and all `global _adapter` statements
- Removed all `# REMOVED:` comments left by Step 2
- Renamed `get_db_adapter()` to `get_adapter()` with `profile_name`, `env_prefix`, `database_url`, `jsonb_columns` parameters; no caching (new instance each call)
- Renamed `_resolve_url()` to public `resolve_url()` for cross-module use
- Added `env_prefix` parameter to `get_active_profile_name()`, `get_active_profile()`, `connect_and_validate()`
- Added `expected_columns` parameter to `connect_and_validate()` -- when `None`, skips schema validation (connection-only mode)
- Changed `_PROFILE_LOCK_FILE` from `Path(__file__).parent` to `Path.cwd()`
- Updated error messages from MC-specific (`MC_DB_PROFILE`, `python -m schema`) to generic (`DB_PROFILE`, `db-adapter connect`)
- Updated `ConnectionResult.schema_valid` field type from `bool` to `bool | None` to support connection-only mode (validation not performed)
- Updated downstream imports in `cli/__init__.py`, `schema/fix.py`, `schema/sync.py` from `_resolve_url` to `resolve_url`; removed `get_dev_user_id` import from `cli/__init__.py`; commented out removed imports in `backup/backup_restore.py`
- Updated Step 2 test to reference `get_adapter` instead of `get_db_adapter`

**Deviation from Plan**: Minor -- updated `ConnectionResult.schema_valid` type from `bool` to `bool | None` in `schema/models.py`. The plan did not explicitly call for this change, but it was necessary to support the `expected_columns=None` connection-only mode where validation is skipped (schema_valid should be `None`, not `False`, to distinguish "not validated" from "validation failed"). Also updated downstream module imports (`cli/__init__.py`, `schema/fix.py`, `schema/sync.py`, `backup/backup_restore.py`) to use the renamed `resolve_url` and remove references to deleted functions -- necessary to keep all modules importable for the full test suite.

**Test Results**: 53/53 tests passing (137/137 full suite)
```bash
tests/test_lib_extraction_factory.py::TestMCCodeRemoved (12 tests) - PASSED
tests/test_lib_extraction_factory.py::TestKeptFunctions (9 tests) - PASSED
tests/test_lib_extraction_factory.py::TestProfileLockPath (2 tests) - PASSED
tests/test_lib_extraction_factory.py::TestResolveUrl (3 tests) - PASSED
tests/test_lib_extraction_factory.py::TestGetActiveProfileName (6 tests) - PASSED
tests/test_lib_extraction_factory.py::TestGetAdapter (5 tests) - PASSED
tests/test_lib_extraction_factory.py::TestConnectAndValidate (6 tests) - PASSED
tests/test_lib_extraction_factory.py::TestFunctionSignatures (10 tests) - PASSED
```

**Issues**:
- `PostgresAdapter.__init__` calls `create_engine()` which tries to import `psycopg2` (not installed -- the project uses `asyncpg`/`psycopg` v3). Tests that create adapters via `get_adapter()` must mock `PostgresAdapter.__init__` to avoid the driver import error. This is expected -- the sync adapter is legacy code that Step 6 replaces with `AsyncPostgresAdapter`.
- `ConnectionResult.schema_valid` was typed as `bool` but connection-only mode needs `None`. Changed to `bool | None` in `schema/models.py`.

**Trade-offs & Decisions**:
- **Decision:** Keep factory functions sync for now.
  - **Alternatives considered:** Convert to async immediately with `asyncio.run()` wrapping.
  - **Why this approach:** The underlying adapters (`PostgresAdapter`, `SchemaIntrospector`) are still sync. Converting factory to async before adapters would add unnecessary complexity. Step 8 handles async conversion after Step 6 (adapters) and Step 7 (introspector).
  - **Risk accepted:** Temporary API churn -- consumers call sync `get_adapter()` now, will switch to async after Step 8.

**Lessons Learned**:
- Renaming a function (`get_db_adapter` to `get_adapter`) requires updating all downstream consumers and tests. The `# REMOVED:` breadcrumbs from Step 2 made it easy to find factory.py's own dead code, but downstream files (`cli/__init__.py`, `schema/fix.py`, `schema/sync.py`, `backup/backup_restore.py`) also had references to renamed/removed functions that needed updating to keep modules importable.
- Changing a Pydantic model field type (`schema_valid: bool` to `bool | None`) is safe because `None` was not a valid value before, so no existing code was passing `None`. The change is additive.
- Mocking `PostgresAdapter.__init__` is the correct approach for unit testing factory logic without a database driver. The factory's job is to resolve profiles and create adapters -- testing the adapter itself is a separate concern.

**Result**: Step 4 complete. Factory is now a clean, generic module with zero MC-specific code, configurable env prefix, and connection-only mode. Ready for Step 5 (Decouple Schema Comparator).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:22-0800
- **Intent match**: PASS -- All 7 acceptance criteria met: zero MC imports in factory.py; MC-specific functions removed (AuthenticationError, get_dev_user_id, get_user_id_from_ctx, cleanup_project_all_dbs, cleanup_projects_pattern, reset_client); no module-level _adapter global; get_active_profile_name(env_prefix="MC_") reads MC_DB_PROFILE via f"{env_prefix}DB_PROFILE"; connect_and_validate(expected_columns=None) skips validation and returns ConnectionResult with schema_valid=None; resolve_url() substitutes [YOUR-PASSWORD]; 53/53 tests pass.
- **Assumption audit**: PASS -- ConnectionResult.schema_valid type changed from bool to bool | None, documented in Deviation section with clear rationale (distinguishing "not validated" from "validation failed"). No other hidden assumptions found.
- **Architectural drift**: PASS -- Factory module structure unchanged at factory.py. Functions retained match plan specification exactly. resolve_url renamed from _resolve_url per plan. Downstream import updates in cli/__init__.py, schema/fix.py, schema/sync.py, backup/backup_restore.py are cascading changes documented in results.

---

### Step 5: Decouple Schema Comparator -- Complete
**Status**: Complete (2026-02-27T21:05:34-0800)
**Expected**: Decouple validate_schema() from MC's db_models module by changing its signature to accept both actual_columns and expected_columns as parameters.

**Implementation**:
- Rewrote `comparator.py` with 2-param `validate_schema(actual_columns, expected_columns)` signature
- Removed the `# REMOVED: from schema.db_models import get_all_expected_columns` comment left by Step 2
- Implemented pure set comparison logic: missing tables (expected - actual), missing columns per common table (expected - actual), extra tables (actual - expected, warning only)
- Results are deterministic: all lists are sorted alphabetically for consistent output
- Each `ColumnDiff` includes a descriptive message (e.g., "Column 'email' missing from table 'users'")
- Updated module docstring with new 2-param API usage examples showing async introspector pattern
- Updated `factory.py` call site: `validate_schema(actual_columns, expected_columns)` -- now passes the `expected_columns` parameter from `connect_and_validate()`

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 32/32 tests passing (169/169 full suite)
```bash
tests/test_lib_extraction_comparator.py::TestMCCodeRemoved (3 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestFunctionSignature (5 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestValidSchemas (5 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestMissingTables (3 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestMissingColumns (4 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestExtraTables (3 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestErrorCount (4 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestFormatReport (3 tests) - PASSED
tests/test_lib_extraction_comparator.py::TestFactoryCallSite (2 tests) - PASSED
```

**Issues**:
- None encountered.

**Trade-offs & Decisions**:
- No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- The function body was trivially implementable because the original code was already pure set logic -- only the source of `expected_columns` changed (from internal `get_all_expected_columns()` call to caller-provided parameter). This validates the design principle of separating "where data comes from" from "how data is processed."
- Sorting all output lists (missing_tables, extra_tables, missing columns per table) makes tests deterministic and makes the `format_report()` output consistent regardless of Python set iteration order.
- Testing the factory call site with AST inspection (checking argument count on `validate_schema()` calls) is more robust than string matching since it catches the actual call structure, not just text patterns.

**Result**: Step 5 complete. Schema comparator is now fully decoupled from MC -- accepts caller-provided expected_columns with zero external dependencies. Ready for Step 6 (Convert Adapters to Async).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:45-0800
- **Intent match**: PASS -- Design Analysis #7 specifies removing from schema.db_models import get_all_expected_columns and changing validate_schema() to 2-param while keeping it sync with identical set-operation logic. All 7 acceptance criteria satisfied: zero db_models imports, 2-param signature, correct behavior for matching/missing/extra tables and columns, factory call site updated. 32/32 tests pass.
- **Assumption audit**: PASS -- Sorted output for deterministic results is a reasonable defensive choice. ColumnDiff.message field provides descriptive error strings consistent with existing SchemaValidationResult.format_report() pattern. No tenancy, concurrency, or storage assumptions introduced.
- **Architectural drift**: PASS -- comparator.py uses correct absolute import (from db_adapter.schema.models). File remains in schema/comparator.py as specified. Module docstring shows intended usage pattern maintaining the design's layered architecture where the comparator is pure logic with no I/O dependencies.

---

### Step 6: Convert Adapters to Async -- Complete
**Status**: Complete (2026-02-27T21:08:53-0800)
**Expected**: Convert DatabaseClient Protocol, PostgresAdapter, and SupabaseAdapter from sync to async implementations.

**Implementation**:
- Converted `DatabaseClient` Protocol in `base.py` -- all 5 methods (`select`, `insert`, `update`, `delete`, `close`) are now `async def`
- Renamed `PostgresAdapter` to `AsyncPostgresAdapter` in `postgres.py` with full async implementation
- Renamed `create_mc_engine()` to `create_async_engine_pooled()` using `sqlalchemy.ext.asyncio.create_async_engine`
- URL normalization: `postgres://` -> `postgresql://` -> `postgresql+asyncpg://` (prefix match, not global replace)
- All `engine.connect()` and `engine.begin()` calls use `async with` context managers with `await`
- `JSONB_COLUMNS` removed as class constant; now a constructor parameter (`jsonb_columns: list[str] | None = None`) stored as `frozenset`
- `engine.dispose()` now uses `await engine.dispose()`
- Converted `test_connection()` to `async def` on `AsyncPostgresAdapter`
- Renamed `SupabaseAdapter` to `AsyncSupabaseAdapter` in `supabase.py`
- Replaced `supabase.Client`/`create_client` with `supabase.AsyncClient`/`acreate_client`
- Implemented lazy async init with `asyncio.Lock` (double-check pattern after lock acquisition)
- All `AsyncSupabaseAdapter` CRUD methods `await` the `.execute()` call
- `AsyncSupabaseAdapter.close()` properly handles `aclose()` on client; no-op when client is `None`
- Updated `adapters/__init__.py` exports: `DatabaseClient`, `AsyncPostgresAdapter`, conditional `AsyncSupabaseAdapter` via `try/except ImportError`
- Updated `factory.py` to import and create `AsyncPostgresAdapter` instead of `PostgresAdapter`
- Updated downstream modules (`schema/fix.py`, `schema/sync.py`, `cli/__init__.py`) to reference `AsyncPostgresAdapter`
- Updated previous step tests (`test_lib_extraction_factory.py`, `test_lib_extraction_imports.py`) to reference new class names

**Deviation from Plan**: Updated downstream modules (`schema/fix.py`, `schema/sync.py`, `cli/__init__.py`) and previous step tests (`test_lib_extraction_factory.py`, `test_lib_extraction_imports.py`) to reference `AsyncPostgresAdapter` instead of `PostgresAdapter`. The plan did not explicitly list these as files to update, but it was necessary to keep all modules importable and the full test suite passing.

**Test Results**: 53/53 tests passing (222/222 full suite)
```bash
tests/test_lib_extraction_adapters.py::TestOldNamesRemoved (7 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestDatabaseClientProtocol (6 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestAsyncPostgresAdapterMethods (6 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestAsyncPostgresAdapterURLRewrite (3 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestJSONBColumnsConstructorParam (4 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestAsyncSQLAlchemyImports (5 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestAsyncSupabaseAdapter (8 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestAdaptersInitExports (6 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestFactoryUpdatedReferences (3 tests) - PASSED
tests/test_lib_extraction_adapters.py::TestCreateAsyncEnginePooled (5 tests) - PASSED
```

**Issues**:
- Initial test used `asyncio.get_event_loop().run_until_complete()` for the async close no-op test, which fails on Python 3.14 (no default event loop in thread). Fixed by switching to `asyncio.run()`.

**Trade-offs & Decisions**:
- **Decision:** Update all downstream references to `AsyncPostgresAdapter` in this step rather than leaving `PostgresAdapter` aliases.
  - **Alternatives considered:** Adding a backward-compatible alias (`PostgresAdapter = AsyncPostgresAdapter`) to avoid updating downstream files.
  - **Why this approach:** Clean break is simpler. Aliases create confusion about which name is canonical. Downstream modules (`fix.py`, `sync.py`, `cli/`) are still sync and will be converted in later steps anyway.
  - **Risk accepted:** If any external consumer references `PostgresAdapter` by name, it will break. Since there are no external consumers yet (greenfield extraction), this is acceptable.
**Lessons Learned**:
- URL normalization requires two-step conversion: first handle the `postgres://` alias (used by Heroku, Railway, Supabase), then convert `postgresql://` to `postgresql+asyncpg://`. Using prefix matching (not global replace) prevents double-prefixing when the URL already has the async driver prefix.
- Python 3.14 removed the implicit event loop creation in `asyncio.get_event_loop()` -- use `asyncio.run()` for one-shot async calls in tests.
- The `try/except ImportError` pattern in `__init__.py` for conditional `AsyncSupabaseAdapter` export ensures the package remains importable even when the `supabase` extra is not installed.
- Renaming a class propagates through more files than expected: not just the defining module and `__init__.py`, but also `factory.py`, downstream modules with `TYPE_CHECKING` imports, runtime imports in function bodies, and all test files from previous steps.

**Result**: Step 6 complete. All adapters are async-first. DatabaseClient Protocol has async methods, AsyncPostgresAdapter uses SQLAlchemy async engine with asyncpg driver, AsyncSupabaseAdapter uses lazy async client init. JSONB_COLUMNS is a constructor parameter. All 222 tests pass. Ready for Step 7 (Convert Introspector to Async).

**Review**: PASS
**Reviewed**: 2026-02-28T00:12:12-0800
- **Intent match**: PASS -- All 8 acceptance criteria satisfied: PostgresAdapter and create_mc_engine removed; AsyncPostgresAdapter and AsyncSupabaseAdapter created; JSONB_COLUMNS is constructor parameter stored as frozenset; all 5 Protocol methods are async def; AsyncPostgresAdapter imports create_async_engine from sqlalchemy.ext.asyncio; AsyncSupabaseAdapter imports acreate_client from supabase; all engine calls use async with; 53/53 step tests and 222/222 full suite pass.
- **Assumption audit**: PASS -- Two-step URL normalization matches plan specification and improves on design doc's simpler single-step approach to handle the postgres:// alias. Deviation of updating downstream modules and previous step tests is documented. No undocumented assumptions found.
- **Architectural drift**: PASS -- File structure matches the design: Protocol in base.py, Postgres adapter in postgres.py, Supabase adapter in supabase.py, conditional exports in __init__.py. All imports use db_adapter.* absolute paths. Lazy async init pattern with asyncio.Lock for AsyncSupabaseAdapter follows the design's specified pattern.

---

### Step 7: Convert Introspector to Async -- Complete
**Status**: Complete (2026-02-27T21:16:17-0800)
**Expected**: Convert SchemaIntrospector from sync psycopg.connect() to async psycopg.AsyncConnection.connect().

**Implementation**:
- Replaced `psycopg.connect()` with `await psycopg.AsyncConnection.connect()` in `__aenter__`
- Replaced `__enter__`/`__exit__` with `__aenter__`/`__aexit__` (async context manager)
- Removed `from psycopg import Connection` import (sync Connection type no longer used)
- All 9 query methods converted to `async def`: `test_connection`, `introspect`, `get_column_names`, `_get_tables`, `_get_columns`, `_get_constraints`, `_get_indexes`, `_get_triggers`, `_get_functions`
- `_normalize_data_type` remains sync `def` (pure logic, no I/O)
- Added `async def test_connection()` method -- runs `SELECT 1` via async cursor, returns `True` on success, raises `ConnectionError` on failure
- `EXCLUDED_TABLES` replaced with `_excluded_tables` instance attribute set from constructor parameter `excluded_tables: set[str] | None = None` (defaults to `EXCLUDED_TABLES_DEFAULT` class constant)
- `connect_timeout` promoted from URL appendage hack to explicit constructor parameter `connect_timeout: int = 10`, passed as kwarg to `AsyncConnection.connect()`
- All cursor usage converted to `async with self._conn.cursor() as cur: await cur.execute(...); rows = await cur.fetchall()`
- Connection type annotation updated from `Connection | None` to `psycopg.AsyncConnection | None`
- Error messages updated from "Use with statement" to "Use 'async with' statement"

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: 43/43 tests passing (265/265 full suite)
```bash
tests/test_lib_extraction_introspector.py::TestSyncPatternsRemoved (5 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestAsyncPatternsPresent (6 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestQueryMethodsAsync (9 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestNormalizeDataTypeSync (3 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestConstructorParameters (8 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestConnectionNotEstablished (3 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestTestConnection (3 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestAsyncContextManager (3 tests) - PASSED
tests/test_lib_extraction_introspector.py::TestSourceStructure (3 tests) - PASSED
```

**Issues**:
- Initial mock setup for async cursor context manager failed because `AsyncMock()` for `cursor()` does not automatically produce a valid `async with` target. Fixed by using `MagicMock` for the context manager wrapper with explicit `__aenter__`/`__aexit__` `AsyncMock` methods, while the cursor itself remains `AsyncMock`.
- Test for `self.EXCLUDED_TABLES` absence initially matched `self.EXCLUDED_TABLES_DEFAULT` in the constructor (substring match). Fixed by switching to AST inspection that checks for exact attribute name `EXCLUDED_TABLES` in method bodies only (skipping `__init__`).

**Trade-offs & Decisions**:
- No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- When mocking psycopg's async cursor pattern (`async with conn.cursor() as cur`), `cursor()` is a regular method that returns an async context manager. The mock must be `MagicMock` for `cursor()` return value with `__aenter__`/`__aexit__` as `AsyncMock` methods. Using `AsyncMock` for the cursor return directly causes `cursor()` itself to become a coroutine, which breaks the `async with` pattern.
- Promoting `connect_timeout` from a URL string appendage to an explicit constructor parameter is cleaner -- `psycopg.AsyncConnection.connect()` accepts `connect_timeout` as a kwarg natively, eliminating URL parsing edge cases (e.g., whether `?` or `&` separator is needed).
- String-based assertions on source code (e.g., `"self.EXCLUDED_TABLES" not in source`) are fragile when similar names exist (`EXCLUDED_TABLES_DEFAULT`). AST inspection with exact attribute matching is more robust.

**Result**: Step 7 complete. SchemaIntrospector is fully async: uses `psycopg.AsyncConnection`, `__aenter__`/`__aexit__`, all query methods are `async def`, `_normalize_data_type` stays sync. `excluded_tables` and `connect_timeout` are configurable constructor parameters. `test_connection()` async method added. All 265 tests pass. Ready for Step 8 (Convert Factory to Async).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:36-0800
- **Intent match**: PASS -- Design Analysis #6 specifies converting SchemaIntrospector from sync psycopg.connect() to async psycopg.AsyncConnection.connect(), replacing __enter__/__exit__ with __aenter__/__aexit__, making all query methods async def (except _normalize_data_type), and making EXCLUDED_TABLES a configurable constructor parameter. All acceptance criteria are satisfied: async context manager at lines 88-100, all 9 query methods are async def, _normalize_data_type remains regular def, excluded_tables/connect_timeout are constructor parameters with defaults, and test_connection() is async.
- **Assumption audit**: PASS -- The connect_timeout promotion from URL appendage to explicit constructor parameter was explicitly specified in the plan. The test_connection() method was explicitly specified as a plan refinement. The EXCLUDED_TABLES_DEFAULT.copy() defensive pattern is reasonable. No undocumented assumptions found.
- **Architectural drift**: PASS -- The file remains at schema/introspector.py, consistent with the 5-layer architecture. Import uses absolute db_adapter.schema.models path. The class structure (single SchemaIntrospector with async context manager pattern) matches the design doc's pattern exactly. No new files created.

---

### Step 8: Convert Factory to Async -- Complete
**Status**: Complete (2026-02-27T21:21:11-0800)
**Expected**: Convert connect_and_validate() and get_adapter() to async functions now that adapters and introspector are async.

**Implementation**:
- Converted `connect_and_validate()` to `async def` with `async with SchemaIntrospector(...)` and `await introspector.get_column_names()`
- Converted `get_adapter()` to `async def` for API consistency with `connect_and_validate()` and to allow future async initialization steps
- Updated introspector usage from sync `with` to `async with` in `connect_and_validate()`
- Added `await` on `introspector.get_column_names()` call
- Updated `get_adapter()` to forward `jsonb_columns` parameter to `AsyncPostgresAdapter` constructor (previously not forwarded)
- Updated module docstring with `await` usage examples
- Profile lock file operations (`read_profile_lock`, `write_profile_lock`, `clear_profile_lock`), `get_active_profile_name`, `get_active_profile`, and `resolve_url` remain sync (pure file/env I/O, no database operations)
- Updated Step 6 test (`test_lib_extraction_adapters.py`) to use `async def` + `await` for `test_get_adapter_creates_async_adapter`
- Rewrote `test_lib_extraction_factory.py` from sync to async tests (replaced Step 4 sync tests with Step 8 async equivalents)

**Deviation from Plan**: Minor -- (1) Fixed `get_adapter()` to forward `jsonb_columns` to `AsyncPostgresAdapter` constructor. The Step 4 implementation was not forwarding this parameter (it was listed as "reserved for future use"). Since Step 8 makes the adapter creation explicit with `jsonb_columns` as a constructor param, this was the right time to wire it through. (2) Updated `test_lib_extraction_adapters.py::TestFactoryUpdatedReferences::test_get_adapter_creates_async_adapter` from sync to async -- necessary because `get_adapter()` is now a coroutine.

**Test Results**: 68/68 factory tests passing (280/280 full suite)
```bash
tests/test_lib_extraction_factory.py::TestMCCodeRemoved (12 tests) - PASSED
tests/test_lib_extraction_factory.py::TestKeptFunctions (9 tests) - PASSED
tests/test_lib_extraction_factory.py::TestProfileLockPath (2 tests) - PASSED
tests/test_lib_extraction_factory.py::TestResolveUrl (3 tests) - PASSED
tests/test_lib_extraction_factory.py::TestGetActiveProfileName (6 tests) - PASSED
tests/test_lib_extraction_factory.py::TestAsyncFunctions (8 tests) - PASSED
tests/test_lib_extraction_factory.py::TestGetAdapterAsync (8 tests) - PASSED
tests/test_lib_extraction_factory.py::TestConnectAndValidateAsync (10 tests) - PASSED
tests/test_lib_extraction_factory.py::TestFunctionSignatures (10 tests) - PASSED
```

**Issues**:
- Step 6 test `test_get_adapter_creates_async_adapter` called `get_adapter()` synchronously (returned a coroutine object instead of an adapter). Fixed by converting the test method to `async def` with `await`.

**Trade-offs & Decisions**:
- **Decision:** Make `get_adapter()` async even though its current implementation performs no I/O requiring `await`.
  - **Alternatives considered:** Keep `get_adapter()` sync since it only creates an adapter object without connecting.
  - **Why this approach:** API consistency -- both factory functions (`connect_and_validate` and `get_adapter`) are async, providing a uniform `await`-based API. This also future-proofs for potential async initialization steps (e.g., async connection pooling warmup).
  - **Risk accepted:** Callers must use `await` even for simple URL-based adapter creation. This is a minor inconvenience but consistent with async-first design.

**Lessons Learned**:
- Converting a function from sync to async is a cascading change: all callers and tests that call the function directly must be updated to use `await`. The Step 6 adapter test that called `get_adapter()` sync was broken by this change and needed updating.
- `jsonb_columns` was declared as a parameter on `get_adapter()` in Step 4 but was not actually forwarded to `AsyncPostgresAdapter`. Step 8 was the right time to fix this since the adapter constructor already accepts `jsonb_columns` (from Step 6).
- Mocking `SchemaIntrospector` as an async context manager requires `MagicMock` with `__aenter__`/`__aexit__` as `AsyncMock` methods, and `get_column_names` as `AsyncMock`. The pattern is consistent with Step 7's introspector test approach.
- With `asyncio_mode = "auto"` in pytest config, `@pytest.mark.asyncio` decorators are optional but harmless -- they serve as documentation that the test is async.

**Result**: Step 8 complete. Both `connect_and_validate()` and `get_adapter()` are now `async def`. Introspector usage is `async with`. `validate_schema()` (comparator) remains sync (pure logic). All 280 tests pass. Ready for Step 9 (Generalize Schema Fix Module).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:38-0800
- **Intent match**: PASS -- All acceptance criteria satisfied. connect_and_validate() is async def at factory.py line 182, get_adapter() is async def at line 299. SchemaIntrospector usage is async with at line 260 with await introspector.get_column_names() at line 261. jsonb_columns is forwarded through get_adapter() to the adapter constructor. 68/68 factory tests pass.
- **Assumption audit**: PASS -- The decision to make get_adapter() async despite no current I/O is explicitly stated in the plan specification and documented in Trade-offs & Decisions with rationale (API consistency, future-proofing). Minor deviations (forwarding jsonb_columns, updating Step 6 test) are documented. No undocumented assumptions found.
- **Architectural drift**: PASS -- Factory module uses correct absolute db_adapter.* imports. The factory sits at layer 3 of the 5-layer architecture, importing only from layers below it. Profile lock file operations and resolve_url remain sync as specified. Test file was updated in-place per plan instruction.

---

### Step 9: Generalize Schema Fix Module -- Complete
**Status**: Complete (2026-02-27T21:32:13-0800)
**Expected**: Remove hardcoded COLUMN_DEFINITIONS and MC-specific imports from fix.py. Make functions accept caller-provided parameters. Add execute method to DatabaseClient Protocol.

**Implementation**:
- Removed `COLUMN_DEFINITIONS` dict (58 hardcoded MC column definitions) entirely from `fix.py`
- Removed all MC-coupled imports: `from db_adapter.factory import connect_and_validate, read_profile_lock`, `from db_adapter.adapters import AsyncPostgresAdapter`, `from db_adapter.backup.backup_restore import backup_database`, `from db_adapter.config.loader import load_db_config`
- Rewrote `generate_fix_plan(validation_result, column_definitions, schema_file)` -- pure sync logic accepting caller-provided parameters; no `profile_name`
- Rewrote `apply_fixes(adapter, plan, backup_fn, restore_fn, verify_fn, dry_run, confirm)` as `async def` -- uses `adapter.execute()` Protocol method for all DDL; wraps `NotImplementedError` as `RuntimeError("DDL operations not supported for this adapter type")`
- Removed `profile_name` from `FixPlan` dataclass and `FixResult` Pydantic model
- Added `drop_order: list[str]` and `create_order: list[str]` to `FixPlan` -- computed via FK dependency parsing and topological sort of CREATE TABLE REFERENCES clauses
- Added `async def execute(sql, params)` to `DatabaseClient` Protocol in `base.py`
- Implemented `execute()` on `AsyncPostgresAdapter` via `async with self._engine.begin() as conn: await conn.execute(text(sql), params or {})`
- Implemented `execute()` on `AsyncSupabaseAdapter` as `raise NotImplementedError("DDL operations not supported for this adapter type")`
- Changed `_get_table_create_sql(table_name, schema_file)` to require `schema_file` (no default path, no fallback)
- Added `_parse_fk_dependencies()` for parsing REFERENCES clauses from schema files
- Added `_topological_sort()` for computing safe DDL execution order
- Updated Step 6 test `test_protocol_has_exactly_five_methods` to `test_protocol_has_exactly_six_methods` (now includes `execute`)

**Deviation from Plan**: Updated Step 6 test (`test_lib_extraction_adapters.py::TestDatabaseClientProtocol::test_protocol_has_exactly_five_methods` -> `test_protocol_has_exactly_six_methods`). This test verified the Protocol had exactly 5 methods; adding `execute` broke it. The plan noted Step 9 adds a 6th method but did not explicitly list this test file as needing an update.

**Test Results**: 62/62 tests passing (342/342 full suite)
```bash
tests/test_lib_extraction_fix.py::TestMCCodeRemoved (6 tests) - PASSED
tests/test_lib_extraction_fix.py::TestFunctionSignatures (7 tests) - PASSED
tests/test_lib_extraction_fix.py::TestDatabaseClientExecute (6 tests) - PASSED
tests/test_lib_extraction_fix.py::TestColumnFix (5 tests) - PASSED
tests/test_lib_extraction_fix.py::TestTableFix (2 tests) - PASSED
tests/test_lib_extraction_fix.py::TestFixPlan (4 tests) - PASSED
tests/test_lib_extraction_fix.py::TestFixResult (2 tests) - PASSED
tests/test_lib_extraction_fix.py::TestGetTableCreateSQL (4 tests) - PASSED
tests/test_lib_extraction_fix.py::TestFKDependencies (3 tests) - PASSED
tests/test_lib_extraction_fix.py::TestTopologicalSort (5 tests) - PASSED
tests/test_lib_extraction_fix.py::TestGenerateFixPlan (6 tests) - PASSED
tests/test_lib_extraction_fix.py::TestApplyFixes (12 tests) - PASSED
```

**Issues**:
- `SchemaValidationResult` requires a `valid` field in its constructor. Initial tests omitted it and passed `error_count` (a computed property) as a constructor arg. Fixed by adding `valid=True/False` and removing `error_count`.
- Step 6 test `test_protocol_has_exactly_five_methods` failed because `DatabaseClient` now has 6 methods. Updated test name and expected set to include `execute`.

**Trade-offs & Decisions**:
- **Decision:** Add `execute` to `DatabaseClient` Protocol rather than accepting a separate engine/connection parameter.
  - **Alternatives considered:** Accept a raw SQLAlchemy engine or connection for DDL. This would leak implementation details and break the Protocol abstraction.
  - **Why this approach:** DDL execution is a legitimate database operation. Keeping it in the Protocol provides a uniform interface and allows `apply_fixes()` to work with any adapter without knowing its internals.
  - **Risk accepted:** Adapters that don't support DDL (Supabase) must implement `execute()` as `raise NotImplementedError`. Callers must handle this.

**Lessons Learned**:
- Adding a method to a Protocol class is a cascading change: the method must be implemented on all concrete adapters, and tests that assert the Protocol's method count must be updated. Planning for this upfront (as the plan did by noting "Step 9 adds a 6th method") helps but the test file reference is easy to miss.
- `SchemaValidationResult.error_count` is a computed property, not a field -- passing it as a constructor arg silently fails (Pydantic ignores extra fields by default). Tests must use the actual required fields (`valid`, `missing_tables`, `missing_columns`).
- Topological sort with cycle detection is important even for schema files -- circular FK references (e.g., self-referencing tables or mutual references) should not cause infinite loops. The visiting-set approach breaks cycles gracefully.

**Result**: Step 9 complete. Fix module is fully generalized: no hardcoded column definitions, no MC-specific imports, all functions accept caller-provided parameters. DatabaseClient Protocol has `execute` method for DDL. Topological sort ensures safe DDL execution order. All 342 tests pass. Ready for Step 10 (Generalize Backup/Restore).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:51-0800
- **Intent match**: PASS -- All 9 acceptance criteria satisfied. COLUMN_DEFINITIONS is gone from fix.py. generate_fix_plan() accepts 3 parameters (validation_result, column_definitions, schema_file) with no profile_name. apply_fixes() is async def and accepts adapter + callbacks. DatabaseClient Protocol has execute method at adapters/base.py:112. Calling apply_fixes() with NotImplementedError-raising adapter raises RuntimeError("DDL operations not supported for this adapter type"). 62/62 tests pass.
- **Assumption audit**: PASS -- The decision to add execute to the Protocol was explicitly called out in both the design doc and plan's Trade-offs section. Topological sort cycle-detection behavior and _parse_fk_dependencies returning empty dict for missing files are reasonable safe defaults. No undocumented assumptions found.
- **Architectural drift**: PASS -- fix.py lives at schema/fix.py as specified. execute() is added to DatabaseClient Protocol in adapters/base.py, implemented on AsyncPostgresAdapter, and raises NotImplementedError on AsyncSupabaseAdapter. All imports use absolute db_adapter.* package paths. Dependency direction is correct: schema layer depends on adapter types only for typing.

---

### Step 10: Generalize Backup/Restore -- Complete
**Status**: Complete (2026-02-27T21:38:59-0800)
**Expected**: Rewrite backup_database() and restore_database() to use the BackupSchema declarative model instead of hardcoded MC table logic.

**Implementation**:
- Rewrote `backup_database()` as `async def` accepting `adapter`, `schema`, `user_id`, `output_path`, `table_filters`, `metadata` parameters
- Rewrote `restore_database()` as `async def` accepting `adapter`, `schema`, `backup_path`, `user_id`, `mode`, `dry_run` parameters
- Extracted `_restore_table()` as async helper for per-table restore with FK remapping
- Iterates `schema.tables` instead of hardcoded table names -- parents before children
- Uses `TableDef.pk`, `TableDef.slug_field`, `TableDef.user_field` for column references
- Uses `TableDef.parent` for required FK remapping (skips row if parent missing from `id_maps`)
- Uses `TableDef.optional_refs` for optional FK remapping (nulls out field if ref missing)
- Builds generic `id_maps: dict[str, dict]` keyed by table name for old-to-new PK mapping
- Removed all MC-specific imports: `get_db_adapter`, `get_dev_user_id`, `get_settings` -- all gone
- Removed all `# REMOVED:` comments left by Step 2
- Removed all print statements (callers handle output)
- Removed `db_provider` from backup metadata
- Updated `validate_backup()` to accept `schema: BackupSchema` parameter; checks table keys against `schema.tables` names
- Fixed version check: requires `"1.1"` (rejects `"1.0"` old format as error, not warning)
- `validate_backup()` stays sync (local file read only)
- `backup_database()` filters child rows by parent PKs collected during backup
- `backup_database()` supports `table_filters` for per-table extra WHERE clause filters
- `backup_database()` supports `metadata` dict merged into backup metadata section
- Default output path uses `Path.cwd() / "backups"` (not `Path(__file__).parent`)
- Updated `backup/models.py` docstring to use generic table names (authors/books/chapters) instead of MC-specific projects/milestones/tasks
- Added `_find_table_def()` helper for looking up TableDef by name in schema

**Deviation from Plan**: Minor -- Updated `backup/models.py` docstring wording from "Consuming projects" to "Consuming applications" because "projects" triggered the MC-table-name check (it's a reserved MC table name). The word "projects" in English prose was a false positive for the grep check, so using "applications" avoids ambiguity.

**Test Results**: 48/48 tests passing (390/390 full suite)
```bash
tests/test_lib_extraction_backup.py::TestMCCodeRemoved (7 tests) - PASSED
tests/test_lib_extraction_backup.py::TestFunctionSignatures (8 tests) - PASSED
tests/test_lib_extraction_backup.py::TestBackupDatabase (8 tests) - PASSED
tests/test_lib_extraction_backup.py::TestRestoreDatabase (11 tests) - PASSED
tests/test_lib_extraction_backup.py::TestValidateBackup (10 tests) - PASSED
tests/test_lib_extraction_backup.py::TestRoundTrip (1 test) - PASSED
tests/test_lib_extraction_backup.py::TestFindTableDef (2 tests) - PASSED
tests/test_lib_extraction_backup.py::TestIdMaps (1 test) - PASSED
```

**Issues**:
- Initial `models.py` docstring used "Consuming projects" which triggered the MC-table-name check for `"projects"`. Fixed by rewording to "Consuming applications".

**Trade-offs & Decisions**:
- **Decision:** Extract `_restore_table()` as a separate async helper instead of inlining restore logic for each table.
  - **Alternatives considered:** Inline all restore logic in `restore_database()` with a for-loop per table (matching the original code's structure).
  - **Why this approach:** Separating per-table restore logic into `_restore_table()` reduces nesting depth (the original had 4+ levels of if/elif/try nesting) and makes the generic iteration pattern clearer. The helper is private (underscore prefix) so it's not part of the public API.
  - **Risk accepted:** The helper mutates `id_maps` and `summary` dicts in place. This is intentional for simplicity but means the function has side effects beyond its return value.

**Lessons Learned**:
- Generic FK remapping via `id_maps: dict[str, dict]` keyed by table name is cleaner than the original approach of separate `project_id_map` and `milestone_id_map` variables. Adding a new table level requires zero code changes -- just add a `TableDef` to the schema.
- The `BackupSchema.tables` ordering (parents first) is critical: `restore_database()` iterates in schema order, so parent IDs must be in `id_maps` before child rows try to look them up. This is a contract the caller must uphold when constructing the schema.
- Version checking should be an error (not a warning) when the format is incompatible. The old code warned about version mismatch but continued anyway, which could silently corrupt data if the format changed.
- AST-based string literal checks (for MC table names) catch string constants everywhere in the module, including dict keys, function arguments, and variable assignments. This is more thorough than grep but also catches false positives in English prose (e.g., "projects" in a docstring). The fix is to use different wording in prose.

**Result**: Step 10 complete. Backup/restore is fully generalized: BackupSchema drives table iteration and FK remapping, no hardcoded table names, async backup/restore with sync validate, version 1.1 required. All 390 tests pass. Ready for Step 11 (Generalize Sync Module).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:37-0800
- **Intent match**: PASS -- Design doc specifies converting backup_restore.py from hardcoded MC table logic to use BackupSchema declarative model. All seven acceptance criteria are satisfied: zero hardcoded table names, zero bare MC-style imports, async backup/restore, BackupSchema driving table iteration and FK remapping, validate_backup() accepting schema parameter, no print statements, and tests passing. The implementation iterates schema.tables, uses TableDef fields throughout _restore_table(), and builds generic id_maps: dict[str, dict].
- **Assumption audit**: PASS -- No assumptions beyond design and plan. BackupSchema.tables ordering contract (parents first) is documented in both design and results docs. Default output path using Path.cwd() / "backups" is reasonable. Mutation-in-place pattern for id_maps and summary in _restore_table() is explicitly documented in Trade-offs. The _find_table_def() helper is a trivial addition not requiring design specification.
- **Architectural drift**: PASS -- File structure matches design doc's target layout: backup/models.py contains BackupSchema, TableDef, ForeignKey; backup/backup_restore.py contains the three functions. All imports use absolute db_adapter.* package paths. Public API in __init__.py correctly exports the backup models. No new files created beyond specification.

---

### Step 11: Generalize Sync Module ✅
**Status**: Complete (2026-02-27T21:45:25-0800)
**Expected**: Remove hardcoded projects/milestones/tasks references from sync.py. Make sync operations work with caller-declared table lists.

**Implementation**:
- ✅ Redesigned `SyncResult` with `default_factory=dict` for all dict fields (no hardcoded table name defaults) and added `synced_count`, `skipped_count`, `errors` fields
- ✅ `compare_profiles()` is now `async def` accepting `tables`, `user_id`, `user_field`, `slug_field`, `env_prefix` parameters
- ✅ `sync_data()` is now `async def` accepting same parameters plus `schema`, `dry_run`, `confirm` -- dual-path sync
- ✅ `_get_data_counts()` iterates caller-provided `tables` list with `user_field` parameter (async)
- ✅ `_get_slugs()` uses flat slug per table -- no hierarchical project_slug/slug composition (async)
- ✅ `_create_adapter_for_profile()` helper uses `load_db_config`, `resolve_url`, `AsyncPostgresAdapter` from `db_adapter.*` imports
- ✅ `_sync_via_backup()` uses `await backup_database()`/`await restore_database()` via temp file for FK-aware sync
- ✅ `_sync_direct()` uses per-table `select()`/`insert()` with slug-based matching for simple sync
- ✅ FK constraint violation in direct insert raises `ValueError` suggesting `BackupSchema`
- ✅ Removed all subprocess usage, `get_dev_user_id`, `from db import` references
- ✅ Zero hardcoded `"projects"`, `"milestones"`, `"tasks"` string literals in sync.py

**Deviation from Plan**: None -- implemented per plan specification. The dual-path sync (direct insert when `schema=None`, backup/restore when `schema` provided) matches the plan's specification exactly.

**Test Results**: ✅ 49/49 tests passing (439/439 full suite)
```bash
tests/test_lib_extraction_sync.py - 49 passed in 0.63s
Full suite: 439 passed, 13 warnings in 1.08s
```

**Issues**:
- None encountered.

**Trade-offs & Decisions**:
- **Decision:** Runtime imports in `_create_adapter_for_profile()` and `_sync_via_backup()` instead of top-level imports
  - **Alternatives considered:** Top-level imports for all dependencies
  - **Why this approach:** Avoids circular imports (sync -> factory -> config -> loader), which is the same pattern used by the original code. Runtime imports inside helper functions keep the import scope narrow.
  - **Risk accepted:** Slightly slower first-call performance due to deferred import resolution (negligible in practice since these are async I/O operations).
- **Decision:** `_sync_direct()` commits inserts per-row (no transaction rollback across tables)
  - **Alternatives considered:** Wrapping all inserts in a single transaction
  - **Why this approach:** Matches the plan's specification ("Partial failures on direct insert: committed rows stay committed -- no transaction rollback across tables") and the original behavior
  - **Risk accepted:** Partial sync state if an error occurs mid-way through multiple tables

**Lessons Learned**:
- The dual-path sync design (direct vs backup/restore) cleanly separates concerns: flat tables with no FK relationships can use the simpler direct path, while hierarchical data with FK constraints should use the BackupSchema-driven path. The caller decides which path based on their data model.
- Flat slug resolution (one `slug_field` per table) is simpler and sufficient when all tables in a sync group use the same slug column name. The plan correctly notes that callers needing different slug columns should invoke sync per-table group.
- Patching runtime imports in tests requires patching the source module (`db_adapter.backup.backup_restore.backup_database`) not the importing module, since the name is not yet bound in the importing module's namespace.

**Result**: Step 11 complete. Sync module is fully generalized: no hardcoded MC table names, caller-declared table lists, async compare/sync with dual-path (direct insert vs backup/restore), flat slug resolution, proper db_adapter imports, no subprocess usage. All 439 tests pass. Ready for Step 12 (Modernize CLI).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:42-0800
- **Intent match**: PASS -- Design Analysis #9 requires removing hardcoded projects/milestones/tasks references, accepting caller-declared table lists, replacing subprocess with direct async backup/restore calls, and using flat slug resolution. All criteria are met: SyncResult uses Field(default_factory=dict), both public functions are async def accepting tables: list[str], _sync_via_backup calls await backup_database()/await restore_database(), and dual-path sync (direct vs backup/restore) matches the plan specification exactly.
- **Assumption audit**: PASS -- The env_prefix parameter is accepted on public signatures but not functionally used in _create_adapter_for_profile. This is not a flag because compare_profiles/sync_data always receive explicit profile names. The parameter exists for API consistency and future use. Runtime imports pattern is documented in Trade-offs with circular import rationale. No undocumented assumptions found.
- **Architectural drift**: PASS -- Code lives in schema/sync.py as specified. Uses absolute package imports (from db_adapter.factory import resolve_url, from db_adapter.config.loader import load_db_config). Async-first pattern maintained. Module properly exported via schema/__init__.py. DatabaseClient Protocol used for adapter type hints. All patterns match the established architecture.

---

### Step 12: Modernize CLI ✅
**Status**: Complete (2026-02-27T21:51:13-0800)
**Expected**: Update CLI to use db-adapter as program name, remove MC-specific references, wrap async calls with asyncio.run(), and update all commands to use the new generic APIs.

**Implementation**:
- ✅ Changed `prog` from `"python -m schema"` to `"db-adapter"` and description to generic text
- ✅ Removed `_show_profile_data()` and `_show_profile_comparison()` helpers (used hardcoded MC tables)
- ✅ Removed `get_dev_user_id` import and all usages
- ✅ Removed `COLUMN_DEFINITIONS` import from `schema.fix`
- ✅ Removed hardcoded `fk_drop_order`/`fk_create_order` dicts (now uses `FixPlan.drop_order`/`create_order`)
- ✅ Removed subprocess-based backup call in `cmd_fix()` (replaced with `apply_fixes()` async API)
- ✅ All `MC_DB_PROFILE` references replaced with generic `DB_PROFILE` (configurable via `--env-prefix`)
- ✅ Added `--env-prefix` global option to main parser
- ✅ All database-calling commands (`cmd_connect`, `cmd_validate`, `cmd_fix`, `cmd_sync`) wrap async via `asyncio.run()`
- ✅ `cmd_status` and `cmd_profiles` remain sync (read local files only)
- ✅ Each async command has `async def _async_<name>(args)` + `def cmd_<name>(args): return asyncio.run(_async_<name>(args))`
- ✅ `cmd_fix()` accepts `--schema-file` and `--column-defs` required arguments; uses `_parse_expected_columns()` + `generate_fix_plan()` + `apply_fixes()` async chain
- ✅ `cmd_sync()` accepts `--tables` (comma-separated) and `--user-id` required arguments; forwards to async `compare_profiles()`/`sync_data()`
- ✅ Implemented `_parse_expected_columns(schema_file)` helper to parse CREATE TABLE SQL into `dict[str, set[str]]`
- ✅ `cli/backup.py` docstring and argparse description updated from "Mission Control" to generic text
- ✅ `cli/backup.py` imports use `db_adapter.backup.backup_restore` paths
- ✅ All bare imports converted to `db_adapter.*` package imports
- ✅ [Fix 2026-02-28] Removed misleading "Backup database" display from `_async_fix()` execution plan UI -- the CLI was showing a backup step that was never executed since no `backup_fn` callback was passed to `apply_fixes()`. Also removed the `--no-backup` flag since there is no CLI-level backup to skip. The `backup_fn` callback in `apply_fixes()` remains available for consuming projects that provide their own backup logic.

**Deviation from Plan**: The plan says "replace with `backup_fn` callback to `apply_fixes()`" but the CLI cannot know the caller's `BackupSchema` at runtime (same reasoning as why `cli/backup.py` is kept as a separate unregistered module). Instead of wiring up an unusable backup callback, removed the misleading backup display and `--no-backup` flag. The `backup_fn` parameter on `apply_fixes()` is already available for consuming projects to use directly.

**Test Results**: ✅ 553/553 tests passing
```bash
uv run pytest tests/test_lib_extraction_cli.py -v
# 44 passed in 0.74s

uv run pytest
# 553 passed, 13 warnings in 3.47s
```

**Issues**:
- Help text for `--env-prefix` initially contained `MC_DB_PROFILE` as an example; updated to generic `APP_DB_PROFILE` to satisfy the no-MC-references acceptance criterion.
- [Fix 2026-02-28] Execution plan UI displayed "Backup database" as step 1 but no backup was actually performed; removed the misleading display and `--no-backup` flag.

**Trade-offs & Decisions**:
- **Decision:** Used `inspect.iscoroutinefunction()` instead of `asyncio.iscoroutinefunction()` in tests
  - **Alternatives considered:** Using `asyncio.iscoroutinefunction()` (simpler import)
  - **Why this approach:** Python 3.14+ deprecated `asyncio.iscoroutinefunction()` in favor of `inspect.iscoroutinefunction()` -- avoids DeprecationWarning
  - **Risk accepted:** None -- `inspect.iscoroutinefunction()` is the standard going forward
- **Decision:** Removed `_show_profile_data()` and `_show_profile_comparison()` entirely rather than making them generic
  - **Alternatives considered:** Generalizing them to accept table lists as parameters
  - **Why this approach:** Per plan spec: "removed. Data count display requires DB queries that belong in cmd_status or cmd_sync, not in helpers that assume table names"
  - **Risk accepted:** `cmd_status` no longer shows data counts; `cmd_connect` no longer shows comparison on profile switch. These are informational features that belonged to MC-specific logic.
- **Decision:** Removed misleading "Backup database" display and `--no-backup` flag instead of wiring up a `backup_fn` callback
  - **Alternatives considered:** Implementing a generic backup callback in the CLI that calls `backup_database()` from the backup module
  - **Why this approach:** The CLI cannot know the caller's `BackupSchema` at runtime -- backup requires a declarative table hierarchy that only consuming projects can define. This is the same reasoning behind keeping `cli/backup.py` as a separate unregistered module.
  - **Risk accepted:** `cmd_fix --confirm` applies DDL without pre-fix backup. Consuming projects that need backup should call `apply_fixes()` directly with their own `backup_fn` callback.

**Lessons Learned**:
- Help text examples can inadvertently contain MC-specific references (like `MC_DB_PROFILE`) even when the functional code is clean. Need to check help strings and examples, not just code logic.
- The `asyncio.iscoroutinefunction()` deprecation in Python 3.14+ means tests should use `inspect.iscoroutinefunction()` to avoid warnings.
- The async wrapping pattern `def cmd_x(args): return asyncio.run(_async_x(args))` is clean and testable -- the sync wrapper can be source-inspected for `asyncio.run` presence without needing to mock the event loop.
- UI displays should only advertise operations that actually execute. Showing "Backup database" while not actually performing one is misleading and erodes user trust in the tool's output.

**Result**: Step 12 complete. CLI is fully modernized: program name is `db-adapter`, all MC-specific references removed, async calls wrapped with `asyncio.run()`, generic `--env-prefix` option added, `cmd_sync` accepts `--tables`/`--user-id`, `cmd_fix` accepts `--schema-file`/`--column-defs`, `_parse_expected_columns()` helper implemented, `cli/backup.py` updated. Misleading backup display fixed. All 553 tests pass.

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:52-0800
- **Intent match**: PASS -- All 7 acceptance criteria satisfied: "Mission Control" absent from both CLI files, "python -m schema" absent, MC_DB_PROFILE absent, prog is "db-adapter", cmd_connect/cmd_validate/cmd_fix/cmd_sync wrap async via asyncio.run() while cmd_status/cmd_profiles remain sync, COLUMN_DEFINITIONS/fk_drop_order/fk_create_order absent, and 553 tests pass. The design doc's intent of a generic CLI with configurable env-prefix and asyncio.run() wrapping is fully realized.
- **Assumption audit**: PASS -- The deviation from "replace with backup_fn callback" is documented in Trade-offs & Decisions with clear reasoning: CLI cannot know the caller's BackupSchema at runtime. The removal of the misleading backup display and --no-backup flag is a documented post-step integrity fix. No other silent assumptions found.
- **Architectural drift**: PASS -- All imports use absolute db_adapter.* paths. The async wrapping pattern (def cmd_x(args): return asyncio.run(_async_x(args))) matches the design doc's prescribed pattern exactly. cli/backup.py remains a separate unregistered module per design. No unexpected files or modules added.

---

### Step 13: Package Exports ✅
**Status**: Complete (2026-02-27T21:53:23-0800)
**Expected**: Update src/db_adapter/__init__.py and all subpackage __init__.py files to export the library's public API with __all__ lists.

**Implementation**:
- ✅ Updated `src/db_adapter/__init__.py` with all public exports: `DatabaseClient`, `AsyncPostgresAdapter`, `load_db_config`, `DatabaseProfile`, `DatabaseConfig`, `get_adapter`, `connect_and_validate`, `ProfileNotFoundError`, `resolve_url`, `validate_schema`, `BackupSchema`, `TableDef`, `ForeignKey`; plus conditional `AsyncSupabaseAdapter` via `try/except ImportError`
- ✅ `adapters/__init__.py` already had correct exports (from Step 6) -- no changes needed
- ✅ `config/__init__.py` already had correct exports (from Step 3) -- no changes needed
- ✅ Updated `schema/__init__.py` with full exports: `validate_schema`, `SchemaIntrospector`, `SchemaValidationResult`, `ColumnDiff`, `ConnectionResult`, `ColumnSchema`, `ConstraintSchema`, `IndexSchema`, `TriggerSchema`, `FunctionSchema`, `TableSchema`, `DatabaseSchema`, `compare_profiles`, `sync_data`, `SyncResult`, `generate_fix_plan`, `apply_fixes`, `FixPlan`, `FixResult`, `ColumnFix`, `TableFix`
- ✅ Updated `backup/__init__.py` with full exports: `BackupSchema`, `TableDef`, `ForeignKey`, `backup_database`, `restore_database`, `validate_backup`
- ✅ All five `__init__.py` files have `__all__` lists defined
- ✅ `from db_adapter import X` works for every name in the top-level `__all__` list

**Deviation from Plan**: None -- implemented per plan specification.

**Test Results**: ✅ 527/527 tests passing (483 existing + 44 new)
```bash
uv run pytest tests/test_lib_extraction_exports.py -v
# 44 passed in 0.55s

uv run pytest tests/ -v --tb=short
# 527 passed, 13 warnings in 1.13s
```

**Issues**:
- None. The `adapters/__init__.py` and `config/__init__.py` files already had complete exports with `__all__` from earlier steps (Step 6 and Step 3 respectively), so only `schema/__init__.py`, `backup/__init__.py`, and the top-level `__init__.py` needed updates.

**Trade-offs & Decisions**:
- No significant trade-offs -- straightforward implementation per plan.

**Lessons Learned**:
- The `adapters/__init__.py` and `config/__init__.py` had already been set up with proper exports in earlier steps (Step 6 for adapters with conditional Supabase, Step 3 for config). This is the expected outcome of a well-sequenced plan -- later steps can reuse earlier work.
- Cross-package consistency tests (verifying `from db_adapter import X` is the same object as `from db_adapter.subpkg import X`) are valuable for catching re-export issues where a name might inadvertently create a separate copy.
- The `importlib.reload()` approach for circular import tests works but requires care -- it re-executes module-level code. In this case it was safe because the modules have no side effects at import time.

**Result**: Step 13 complete. All `__init__.py` files updated with full public API exports and `__all__` lists. Top-level `from db_adapter import ...` convenience imports work for all public names. Conditional `AsyncSupabaseAdapter` export handles optional dependency correctly. All 527 tests pass. Ready for Step 14 (Final Validation).

**Review**: PASS
**Reviewed**: 2026-02-28T00:11:30-0800
- **Intent match**: PASS -- All 6 acceptance criteria satisfied: three import-statement checks succeed, every __init__.py defines __all__, from db_adapter import X works for every name in top-level __all__, and 44 tests pass. The design doc's intent (top-level convenience imports with conditional Supabase export) is fully realized. __all__ lists contain exactly the names enumerated in the plan.
- **Assumption audit**: PASS -- No assumptions introduced beyond plan specification. The conditional try/except ImportError pattern for Supabase follows the design doc's exact code example. No extra names added, no names removed.
- **Architectural drift**: PASS -- All __init__.py files use absolute db_adapter.* imports matching the project's import convention. Cross-package consistency tests verify objects imported from top-level, subpackage, and module paths are identical (is checks), confirming no accidental re-definition or shadowing. File structure matches the design doc's target tree.

---

### Step 14: Final Validation ✅
**Status**: Complete (2026-02-27T21:59:09-0800)
**Expected**: Run full test suite and verify all success criteria are met.

**Implementation**:
- Ran full test suite: 553 tests passing (527 existing from steps 1-13 + 26 new final validation tests)
- Fixed 3 residual issues found during validation:
  - Removed orphaned `# REMOVED:` comment from `cli/backup.py` line 21
  - Renamed argparse `dest="projects"` to `dest="items"` in `cli/backup.py` (triggered MC table name grep check)
  - Replaced MC example table names in `schema/fix.py` docstring (`"milestones"`, `"projects"`) with generic names (`"chapters"`, `"books"`)
- Verified all 13 success criteria are met (grep checks, import checks, CLI checks, async checks)
- Created comprehensive test file `tests/test_lib_extraction_final.py` with 26 tests across 8 test classes

**Deviation from Plan**: Minor -- found and fixed 3 residual issues that were not caught by earlier steps' grep checks (orphaned REMOVED comment, argparse dest name, docstring example table names). These are cosmetic fixes that do not change any functional behavior.

**Test Results**: 26/26 final validation tests passing (553/553 full suite)
```bash
tests/test_lib_extraction_final.py::TestNoMCImports (2 tests) - PASSED
tests/test_lib_extraction_final.py::TestNoHardcodedMCTableNames (2 tests) - PASSED
tests/test_lib_extraction_final.py::TestNoOrphanedRemovedComments (1 test) - PASSED
tests/test_lib_extraction_final.py::TestPublicAPIImports (6 tests) - PASSED
tests/test_lib_extraction_final.py::TestAsyncSignatures (4 tests) - PASSED
tests/test_lib_extraction_final.py::TestCLIEntryPoint (3 tests) - PASSED
tests/test_lib_extraction_final.py::TestConstructorParameters (3 tests) - PASSED
tests/test_lib_extraction_final.py::TestSuccessCriteria (5 tests) - PASSED
```

**Issues**:
- `cli/backup.py` had an orphaned `# REMOVED:` comment from Step 2 and used `dest="projects"` as an argparse destination name. The grep check for MC table names flagged `"projects"` as a string literal. Fixed by renaming to `dest="items"`.
- `schema/fix.py` docstring used `"milestones"` and `"projects"` as example FK dependency table names. Fixed by using `"chapters"` and `"books"`.

**Trade-offs & Decisions**:
- **Decision:** Created a comprehensive final validation test file rather than relying only on manual grep/CLI checks.
  - **Alternatives considered:** Manual verification only (run grep commands and visually inspect output).
  - **Why this approach:** Automated tests are repeatable and serve as regression guards. If future changes reintroduce MC-specific code, the tests will catch it.
  - **Risk accepted:** Some tests (e.g., `test_uv_sync_succeeds`, `test_cli_help_shows_db_adapter_program_name`) shell out to subprocess which is slower than in-process tests, but acceptable for a final validation suite run infrequently.

**Lessons Learned**:
- Final validation catches issues that slip through per-step testing. The orphaned `# REMOVED:` comment and argparse `dest="projects"` were not caught by any earlier step's tests because those tests focused on functional behavior, not on full-source grep scanning.
- Grep checks for MC table names as string literals can produce false positives in surprising places: argparse `dest=` values and docstring examples. Using generic example names (books/chapters/reviews) in docstrings avoids this class of false positives.
- A final validation step is valuable as the "integration test" of the entire extraction -- it verifies invariants across all modules simultaneously, catching cross-step regressions.

**Result**: All 13 success criteria verified and met. Full test suite (553 tests) passes. The db-adapter library is fully extracted as a standalone async-first package with zero MC-specific code.

**Review**: PASS
**Reviewed**: 2026-02-28T00:12:25-0800
- **Intent match**: PASS -- All 13 success criteria verified. Grep checks return empty for MC imports and hardcoded table names. uv run db-adapter --help shows correct program name with all 6 subcommands. Top-level imports succeed. 26-test final validation suite codifies checks as repeatable regression guards. The 3 residual fixes (orphaned REMOVED comment, argparse dest rename, docstring example names) are cosmetic corrections bringing the codebase fully in line with criteria.
- **Assumption audit**: PASS -- The dual-verification strategy (AST + grep) is explicitly documented in the results' Trade-offs section and Key Decisions table. The choice to use subprocess for CLI tests is noted as a trade-off (slower but thorough). No undocumented assumptions found.
- **Architectural drift**: PASS -- Test file follows the project's test naming convention, uses the same SRC_DIR path resolution pattern, and is placed in tests/ consistent with all other test files. The 3 source fixes are minimal edits that do not alter any module's structure, dependency graph, or public API. No new files created beyond the single planned test file.

---

## Final Validation

**All Tests**:
```bash
$ uv run pytest tests/ -v --tb=short
553 passed, 13 warnings in 3.62s
```

**Total**: 553 tests passing (all new -- zero pre-existing tests at project start)

---

## Key Decisions Made
| Decision | Rationale |
|----------|-----------|
| AST + grep dual verification in tests | AST catches structural issues; grep catches codebase-wide duplication |
| AST-only import detection (Step 2 tests) | Grep produces false positives from docstrings/comments; AST inspection is structurally correct |
| Stub removed-import functions with `pass` | Keeps files syntactically valid so other modules can still import them; later steps remove/rewrite |
| Default config path `Path.cwd()` not `Path(__file__).parent` | Library reads config from consumer's working directory, not from inside installed package |
| Keep factory sync until Step 8 | Underlying adapters are still sync; async conversion is done after adapter async (Step 6) |
| `ConnectionResult.schema_valid: bool \| None` | Distinguishes "not validated" (None) from "validation failed" (False) for connection-only mode |
| No adapter caching in `get_adapter()` | Caching adds global mutable state; callers can cache the adapter themselves if needed |
| Sorted output lists in `validate_schema()` | Deterministic test assertions and consistent `format_report()` output regardless of set iteration order |
| Clean break: rename `PostgresAdapter` to `AsyncPostgresAdapter` everywhere | No backward-compatible alias; clean names prevent confusion about which is canonical |
| Two-step URL normalization (`postgres://` -> `postgresql://` -> `postgresql+asyncpg://`) | Handles all provider URL variants without double-prefixing |
| `JSONB_COLUMNS` as constructor `frozenset` (not class constant) | Callers declare their own JSONB columns; library has no hardcoded schema knowledge |
| `get_adapter()` async despite no current I/O | API consistency -- both factory functions are async, future-proofs for async init steps |
| Forward `jsonb_columns` from `get_adapter()` to `AsyncPostgresAdapter` | Parameter was accepted but not forwarded in Step 4; Step 8 wires it through |
| Add `execute` to `DatabaseClient` Protocol for DDL | Keeps interface clean; avoids exposing SQLAlchemy engine internals; `NotImplementedError` for non-DDL adapters |
| Topological sort for DDL execution order | FK dependencies parsed from schema file REFERENCES clauses; reverse for drops (children first), forward for creates (parents first) |
| Dual-path sync: direct insert vs backup/restore | Direct insert (schema=None) is simpler for flat tables; backup/restore (schema provided) handles FK remapping. Caller decides based on data model |
| Remove `_show_profile_data`/`_show_profile_comparison` instead of generalizing | Data count display requires DB queries that assume table names; belongs in consuming project's CLI, not in the library |
| `asyncio.run()` per-command wrapper pattern | Simple, isolates each command's async lifecycle; each `cmd_*` is a thin sync wrapper over `_async_*` |
| Automated final validation test file | Repeatable regression guards for MC-specific code leaks; catches cross-step issues that per-step tests miss |
| Generic example names in docstrings (books/chapters/reviews) | Avoids false positives in MC table name grep checks while keeping documentation clear |

---

## What This Unlocks
The db-adapter library is now a standalone, async-first Python package ready for downstream adoption:
- Mission Control can depend on `db-adapter` as a pip-installable library instead of embedding database code
- Any new project can use `from db_adapter import AsyncPostgresAdapter, get_adapter` for async database operations
- The library can be published to PyPI or a private registry for cross-project reuse

---

## Next Steps
1. Publish initial release (tag v0.1.0)
2. Migrate Mission Control to depend on db-adapter as an external package
3. Add integration tests against a real PostgreSQL database

---

## Lessons Learned

- **AST inspection over grep for Python analysis** - Grep-based checks on Python files produce false positives from docstrings, comments, and string literals. AST inspection examines actual import nodes and class definitions, making it structurally correct for detecting bare imports, class placement, and method signatures.

- **Stub removed-import functions with pass** - When removing external dependencies from a codebase, stub the function bodies with `pass` instead of deleting them. This keeps modules importable so downstream code does not break with ImportError, while serving as markers for later steps that will rewrite or remove the stubs.

- **Library config reads from cwd not package dir** - Changing default config path from `Path(__file__).parent` to `Path.cwd()` is essential for library semantics. A library should read configuration from the consuming project's working directory, not from inside its own installed package tree.

- **Two-step URL normalization for async drivers** - PostgreSQL URL conversion requires handling the `postgres://` alias first (used by Heroku, Railway, Supabase), then converting `postgresql://` to `postgresql+asyncpg://`. Using prefix matching prevents double-prefixing when the URL already contains the async driver prefix.

- **Async mock cursor requires mixed mock types** - When mocking psycopg's `async with conn.cursor() as cur` pattern, `cursor()` returns a sync context manager wrapping an async cursor. The mock must use `MagicMock` for the context manager with `__aenter__`/`__aexit__` as `AsyncMock` methods. Using `AsyncMock` for the cursor return directly makes `cursor()` itself a coroutine, which breaks the `async with` pattern.

- **Rename cascades through more files than expected** - Renaming a class or function propagates beyond the defining module and `__init__.py` into factory code, downstream modules with TYPE_CHECKING imports, runtime imports in function bodies, and all test files from previous steps. Plan for downstream file updates during renames.

- **Generic id_maps eliminates per-table variables** - Using `id_maps: dict[str, dict]` keyed by table name for FK remapping during restore is cleaner than separate `project_id_map` and `milestone_id_map` variables. Adding a new table level requires zero code changes -- just add a TableDef to the BackupSchema.

- **Final validation catches cross-step residue** - Per-step tests focus on functional behavior of that step. A final sweep catches residual issues (orphaned REMOVED comments, MC-specific argparse dest names, example table names in docstrings) that slip through because no individual step's tests scan the entire codebase for those patterns.

- **Sync-to-async is a cascading change** - Converting a function from sync to async requires updating all callers and tests to use `await`. This cascades through factory functions, CLI wrappers, and test files from earlier steps that call the function directly.

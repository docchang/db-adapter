# Core-Hardening Design

> **Purpose**: Analyze and design solutions before implementation planning
>
> **Important**: This task must be self-contained (works independently; doesn't break existing functionality and existing tests)

## Executive Summary

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-12T00:18:49-0700 |
| **Task** | Address 6 technical risks identified in examiner audit (examiner-audit-mc-comparison.md) — serves as upstream specification |
| **Type** | Refactor |
| **Scope** | CLI structure, backup/restore error handling, adapter Protocol, SQL schema parsing |
| **Code** | NO - This is a design document |
| **Risk Profile** | Standard |
| **Risk Justification** | Internal library refactoring with full test coverage; all changes are additive (add alongside, don't replace); no external API breaking changes |

**Challenge**: db-adapter inherited 5 technical risks from the MC extraction and introduced 1 new risk from the architecture change. These affect error visibility, data integrity on failure, and SQL parsing robustness.

**Solution**: Four grouped work items — CLI file split, restore failure details, transaction support (unified solution for 3 risks), and SQL parser upgrade — each self-contained and independently shippable.

---

## Context

### Current State

db-adapter is a working async-first library with 8 CLI subcommands, 824 passing tests, and config-driven defaults. It was extracted from Mission Control's sync database CLI. The extraction was successful — no functionality was lost — but the examiner audit (`docs/examiner-audit-mc-comparison.md`) identified 6 technical risks:

- **CLI**: 1842 lines in a single `__init__.py` (23 functions + 1 constant)
- **Restore errors**: `_restore_table()` silently swallows exceptions — `failed` count increments but no error details preserved
- **No transaction boundaries**: Each adapter CRUD call auto-commits independently via `engine.begin()`. Multi-table restore, fix, and sync operations can leave partial state on failure.
- **Direct sync foot-gun**: `_sync_direct()` does naive row-by-row inserts without FK awareness. FK violations leave already-inserted rows behind.
- **Subprocess isolation lost**: MC used `subprocess.run()` for sync and fix auto-backup. db-adapter moved to in-process async — cleaner but lost implicit atomicity boundaries.
- **Regex SQL parsing**: 3 functions use regex to parse `.sql` schema files. Fails on SQL comments, quoted identifiers, and schema-qualified names.

### Target State

- **CLI**: Split into 6 focused modules (176–415 lines each) with re-exports + mock patch target migration (~130+ test path updates)
- **Restore errors**: `failure_details` list in result dict + `logging.warning()` per failure + CLI display when failures > 0
- **Transaction support**: `transaction()` async context manager on the adapter Protocol, wrapping restore, fix, and sync in atomic operations
- **FK pre-flight**: Introspector-based FK detection warning before `_sync_direct()`
- **SQL parsing**: `sqlparse`-based tokenization replacing regex for CREATE TABLE extraction, FK dependency parsing, and table SQL lookup

```
DatabaseClient Protocol (base.py)
    ├── select, insert, update, delete, execute, close  (existing)
    └── transaction()  (NEW — async context manager)

AsyncPostgresAdapter (postgres.py)
    └── transaction() → contextvars + engine.begin()
        ├── CRUD methods check _transaction_conn ContextVar
        └── Auto-commit if no active transaction (backward compatible)

AsyncSupabaseAdapter (supabase.py)
    └── transaction() → raise NotImplementedError

CLI Package (cli/)
    ├── __init__.py      → main(), argparse, re-exports
    ├── _helpers.py      → shared helpers, constants
    ├── _connection.py   → connect, validate, status, profiles
    ├── _schema_fix.py   → fix command
    ├── _data_sync.py    → sync command
    └── _backup.py       → backup, restore, validate-backup
```

---

## Constraints

- **Scope boundaries**: No new CLI commands. No changes to `db.toml` config format. No changes to `BackupSchema` JSON format. No ORM/model changes.
- **Must NOT happen**: Existing 824 tests must not break. Public API exports (`__init__.py`) must not change. Return dict keys in `restore_database()` must not be removed or renamed (new keys are safe). Entry point `db_adapter.cli:main` must not change.
- **Compatibility**: `DatabaseClient` Protocol changes must not break existing structural implementors at runtime — only at type-checking time. Adapters that don't implement `transaction()` must continue to work for non-transactional code paths.
- **Dependencies**: `sqlparse` is a new core dependency (pure Python, zero transitive deps). No other new dependencies.

---

## Analysis

> Each item analyzed independently. No implied order — read in any sequence.

### 1. CLI File Split

**What**: Split `src/db_adapter/cli/__init__.py` (1842 lines, 23 functions) into a package of 6 focused modules.

**Why**: Every subsequent hardening change touches CLI code. A 1842-line file makes diffs hard to review and increases merge conflict risk. The file has 3 distinct domains (connection/schema, fix, data ops) that map naturally to separate modules.

**Approach**:

Split by domain into underscore-prefixed internal modules. The `__init__.py` becomes a thin facade that re-exports all public symbols.

Proposed module boundaries:

| Module | Contents | Lines |
|--------|----------|-------|
| `__init__.py` | `main()` (defined locally), argparse setup, re-exports of 24 symbols | ~245 |
| `_helpers.py` | `_get_table_row_counts`, `_print_table_counts`, `_parse_expected_columns`, `_resolve_user_id`, `_load_backup_schema`, `_resolve_backup_schema_path`, `_EXCLUDED_TABLES`, `console`, shared imports | ~311 |
| `_connection.py` | `_async_connect`, `_async_validate`, `_async_status`, `cmd_connect`, `cmd_status`, `cmd_profiles`, `cmd_validate` | ~415 |
| `_schema_fix.py` | `_async_fix`, `cmd_fix` | ~335 |
| `_data_sync.py` | `_async_sync`, `cmd_sync` | ~176 |
| `_backup.py` | `_async_backup`, `_async_restore`, `_validate_backup`, `cmd_backup`, `cmd_restore` | ~380 |

Import graph (acyclic — no circular dependencies):

```
__init__.py ← imports from all modules
  _helpers.py       (no cli imports; imports from db_adapter.*)
  _connection.py  ← _helpers.py
  _schema_fix.py  ← _helpers.py
  _data_sync.py   ← _helpers.py
  _backup.py      ← _helpers.py
```

Key design decisions:
- `console = Console()` lives in `_helpers.py` — imported by all command modules
- `__init__.py` re-exports 24 symbols (22 functions that move to sub-modules + `_EXCLUDED_TABLES` + `console`). `main` stays in `__init__.py` and is not a re-export. Direct imports from `db_adapter.cli` continue to resolve.
- Argparse setup stays in `__init__.py` — it's the natural home for the CLI entry point
- `_parse_expected_columns` stays in `_helpers.py` for now (moves to a parsing module in item 4 if sqlparse is adopted)

**Mock `patch()` target migration**: Re-exports preserve import resolution but do NOT preserve `unittest.mock.patch()` targets. Tests extensively use `patch("db_adapter.cli.console", ...)`, `patch("db_adapter.cli.load_db_config", ...)`, `patch("db_adapter.cli.read_profile_lock", ...)`, etc. (~180 occurrences). After the split, sub-modules import these names directly (e.g., `_connection.py` does `from db_adapter.config.loader import load_db_config`), so patching the `db_adapter.cli` namespace only patches the re-exported binding — not the binding the sub-module code actually looks up. All `patch()` targets must be updated to reference the sub-module where the name is used (e.g., `db_adapter.cli._connection.load_db_config`). This is a mechanical but high-volume change.

Validate: All existing tests pass after patch target migration. `uv run db-adapter --help` works. No import errors.

---

### 2. Restore Failure Details

**What**: Capture and surface per-row error details when `_restore_table()` catches exceptions during restore operations.

**Why**: Currently the `except Exception` block at `backup_restore.py:347-348` increments `failed` and discards the exception. Users see "Failed: 3" in the Rich Table but can't diagnose what went wrong. This is the only silent exception handler for data operations in the codebase — `sync.py` and `fix.py` both capture error details.

**Approach**:

Two changes — one in the library, one in the CLI:

**Library (`backup/backup_restore.py`):**

Add a `failure_details` list to each table's result dict. Initialize empty, append on each caught exception:

The existing loop `for row in rows:` must change to `for i, row in enumerate(rows):` to track the row index.

```python
# In _restore_table(), change loop to enumerate and update except block:
for i, row in enumerate(rows):  # was: for row in rows:
    old_pk = row.get(table_def.pk, "<unknown>")  # safe access before try block
    try:
        ...
    except Exception as e:
        table_summary["failed"] += 1
        table_summary.setdefault("failure_details", []).append({
            "row_index": i,
            "old_pk": old_pk,
            "error": f"{type(e).__name__}: {e}",
        })
        logger.warning("Restore failed for %s row %d (pk=%s): %s", table_name, i, old_pk, e)
```

Add `import logging` and `logger = logging.getLogger(__name__)` at the top. This is the first `logging` usage in the codebase — appropriate for a library (callers configure handlers).

**Return dict evolution** (backward compatible):

```python
# Before:
{"inserted": 5, "updated": 0, "skipped": 2, "failed": 3}

# After (failure_details only present when failed > 0):
{"inserted": 5, "updated": 0, "skipped": 2, "failed": 3,
 "failure_details": [
     {"row_index": 0, "old_pk": "a1b2", "error": "IntegrityError: duplicate key..."},
     {"row_index": 2, "old_pk": "c3d4", "error": "KeyError: 'required_column'"},
 ]}
```

**CLI (`cli/_backup.py` post-split):**

After printing the Rich Table, check for failure details and print them:

```python
# After console.print(results_table):
for table_def in schema.tables:
    details = result.get(table_def.name, {}).get("failure_details", [])
    if details:
        console.print(f"\n  [red]Failed rows in {table_def.name}:[/red]")
        for d in details:
            console.print(f"    row {d['row_index']} (pk={d['old_pk']}): {d['error']}")
```

Validate: Existing restore tests pass (they don't assert on output text). New test: mock adapter to raise on specific insert, verify `failure_details` structure in result dict.

---

### 3. Transaction Support

**What**: Add a `transaction()` async context manager to the `DatabaseClient` Protocol and implement it in both adapters. Then wrap `restore_database()`, `apply_fixes()`, and `_sync_direct()` in transactions.

**Why**: This is the unified solution for 3 risks:
- **Risk 2**: `restore_database()` inserts row-by-row with auto-commit. Failure mid-restore leaves partial state.
- **Risk 3**: `_sync_direct()` does naive inserts. FK violations leave already-inserted rows behind.
- **Risk 6**: MC used subprocess isolation for atomicity. db-adapter moved to in-process async and lost that boundary.

Transaction support directly replaces the safety that subprocess isolation provided, but at the correct abstraction level (database transactions rather than OS process boundaries).

**Approach**:

Three phases, each independently shippable:

**Phase 1 — Protocol + Adapter Implementation:**

Add to `DatabaseClient` Protocol in `adapters/base.py`:

```python
def transaction(self) -> AbstractAsyncContextManager[None]:
    """Enter a transaction. Auto-commits on clean exit, auto-rolls back on exception."""
    ...
```

PostgreSQL implementation in `adapters/postgres.py` using `contextvars`:

```python
from sqlalchemy.ext.asyncio import AsyncConnection

# Instance-level ContextVar (in __init__):
self._transaction_conn: contextvars.ContextVar[AsyncConnection | None] = contextvars.ContextVar(
    f"_transaction_conn_{id(self)}", default=None
)
```

Each adapter instance gets its own ContextVar (with a unique name via `id(self)`), so when two `AsyncPostgresAdapter` instances exist in the same asyncio task (as in `_sync_direct()` which creates both source and dest adapters), cross-instance contamination cannot occur.

The `transaction()` context manager acquires a connection via `engine.begin()`, stores it in the ContextVar, and yields. All async methods (`select`, `insert`, `update`, `delete`, `execute`) check `self._transaction_conn.get(None)` — if set, use that connection; otherwise create a new micro-transaction (current behavior, backward compatible). Note: `select()` currently uses `engine.connect()` (read-only, no begin/commit) while the other CRUD methods use `engine.begin()`. The `_transaction_conn` check preserves this distinction: shared connection inside a transaction, `connect()` outside. Including `select` is essential because `apply_fixes()` calls backup callbacks that use `adapter.select()` to read table data within the transaction scope (e.g., before DROP), and `_restore_table()` uses `adapter.select()` for existence checks.

Supabase implementation: `raise NotImplementedError("Transactions not supported for Supabase adapter.")`.

**Phase 2 — Wrap Consumers:**

`restore_database()` in `backup/backup_restore.py`: Wrap the main table loop in `async with adapter.transaction():`. Use `hasattr(adapter, 'transaction')` guard so custom adapters without the method still work (degraded — no atomicity, same as today).

**Exception handler restructuring required.** The existing `_restore_table()` has `except Exception: table_summary["failed"] += 1` which catches per-row errors and continues. This catch-and-continue pattern means the exception never propagates out of the `async with` block, so the transaction commits with partial data (successful rows minus failed ones) rather than rolling back. To fix: move the transaction boundary to wrap the `_restore_table()` calls but restructure the outer error handling so that unrecoverable errors (connection failures, constraint violations in mode=fail) propagate out and trigger rollback, while per-row failures in mode=skip/overwrite are still collected. Concretely: the `except ValueError: raise` path (mode=fail) already propagates correctly. For mode=skip/overwrite, per-row failures are caught intentionally — the transaction commits with the successful subset, and `failure_details` (from item #2) tells the user what was skipped. This is the correct behavior for skip/overwrite modes. Full rollback only occurs on unrecoverable errors (connection lost, mode=fail ValueError).

`apply_fixes()` in `schema/fix.py`: Wrap the full fix sequence (CREATE missing tables → backup → DROP → CREATE recreated tables → restore data → ALTER columns). This path is more complex than restore or sync because it includes backup/restore callbacks (`backup_fn`, `restore_fn`) that themselves use the adapter. Within a transaction, all of these share the same connection via contextvars: the backup callback's SELECT reads, the DROP/CREATE DDL, the restore callback's INSERTs, and the ALTER statements. PostgreSQL's transactional DDL means if any step fails, everything rolls back — including the DROP. The table reappears as if nothing happened.

**Exception handler restructuring required.** The existing `except Exception as e: result.error = ...; return result` at the end of `apply_fixes()` catches errors and returns normally. A normal return exits the `async with` block cleanly, causing the transaction to **commit** with partial DDL state — the opposite of the intended rollback. To fix: restructure so the transaction block is inside the try/except, and use a no-op context manager fallback to avoid duplicating the ~80-line fix sequence:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def _noop_transaction():
    yield

ctx = adapter.transaction() if hasattr(adapter, 'transaction') else _noop_transaction()

try:
    async with ctx:
        # ... full fix sequence ...
        # If any step raises, exception propagates out of `async with` → rollback (or no-op)
except RuntimeError:
    raise
except Exception as e:
    # Transaction already rolled back before we get here
    result.error = f"Failed to apply fixes: {e}"
    return result
```

This ensures the `except Exception` handler runs *after* the transaction has rolled back, preserving the error-in-result pattern while guaranteeing atomicity. When no transaction support exists (`_noop_transaction`), the behavior is identical to today.

`_sync_direct()` in `schema/sync.py`: Wrap the insert loop in `async with dest_adapter.transaction():`. Sync transactions are **per-table, not all-or-nothing across the full table list**. If you sync tables A, B, C: A's transaction commits, then if B gets an FK violation, B rolls back while A's inserts are permanent, and C never runs. This is the correct granularity — each table's sync is independent in the direct path (no cross-table FK remapping). If any FK violation occurs within a table, all rows for that table roll back.

**Phase 3 — FK Pre-flight Warning:**

Add FK detection in the CLI handler `_async_sync()` (not inside `_sync_direct()` itself). The CLI handler has config access and can resolve the destination profile URL to create a `SchemaIntrospector`. The check uses `SchemaIntrospector.introspect()` to get constraints, then filters for `constraint_type == "FOREIGN KEY"` on the target tables. If FKs are found and no `backup_schema` is configured, emit a warning via `console.print()` suggesting BackupSchema for FK-aware sync. This turns a runtime FK error into a pre-flight advisory.

Note: `_sync_direct()` receives profile names and creates its own adapters internally — it doesn't have access to introspection. The CLI handler is the correct location because it already resolves config, URLs, and has the console for output.

Files to modify:
- `adapters/base.py` — add `transaction()` to Protocol
- `adapters/postgres.py` — implement with contextvars
- `adapters/supabase.py` — implement as NotImplementedError
- `backup/backup_restore.py` — wrap restore loop
- `schema/fix.py` — wrap full fix sequence
- `schema/sync.py` — wrap per-table insert loop in `_sync_direct()`
- `cli/_data_sync.py` — FK pre-flight warning in `_async_sync()`

Validate: New tests for transaction commit/rollback semantics (mock adapter). Existing 824 tests pass. Transaction-wrapped operations produce identical results on success.

---

### 4. SQL Parser Upgrade

**What**: Replace 3 regex-based SQL parsing functions with `sqlparse`-based tokenization.

**Why**: The regex pattern `(\w+)` for table names fails on schema-qualified names (`public.users`), quoted identifiers (`"Items"`), and SQL comments (`-- CREATE TABLE fake`). MC controlled its own schema files. As a library, db-adapter will encounter arbitrary SQL from other projects.

**Approach**:

Add `sqlparse` as a core dependency in `pyproject.toml`. It's pure Python with zero transitive dependencies.

Refactor 3 functions:

**`_parse_expected_columns()` (cli/_helpers.py post-split, currently cli/__init__.py):**

Replace regex with `sqlparse.parse()`. For each statement where `get_type() == 'CREATE'`:
1. Extract table name from `Identifier` token (handles quotes, schema prefixes)
2. Extract column names from `Parenthesis` token body (with comments already tokenized separately)

Column extraction still uses line-splitting on the parenthesized body, but on comment-free tokenized text rather than raw SQL.

**`_parse_fk_dependencies()` (schema/fix.py):**

Use `sqlparse.parse()` to find CREATE TABLE blocks and extract table names. REFERENCES extraction can remain regex-based within the tokenized body (comments already stripped by the tokenizer), or switch to token-level scanning.

**`_get_table_create_sql()` (schema/fix.py):**

Use `sqlparse.parse()` to find the CREATE statement matching the requested table name. Return the raw SQL string of the matched statement. Name matching strategy: compare the sqlparse-extracted table name (after stripping schema prefix via `get_real_name()` and removing quotes, lowercased) against the provided `table_name` (also lowercased). This ensures callers using bare names can find schema-qualified or quoted tables in the SQL file.

Failure cases resolved:

| Input | Before (regex) | After (sqlparse) |
|-------|----------------|------------------|
| `CREATE TABLE public.users (...)` | Not found | Parsed correctly |
| `CREATE TABLE "Items" (...)` | Not found | Parsed correctly |
| `-- CREATE TABLE fake (...)` | Parsed as real table | Ignored (comment token) |
| `/* block */ email TEXT` inside body | Fake columns extracted | Comment stripped |
| `REFERENCES public.users(id)` | Not found | Parsed correctly |

Validate: Existing parsing tests pass. New edge-case tests for comments, quoted identifiers, schema-qualified names (~8-10 new test cases).

---

## Proposed Sequence

> Shows dependencies and recommended order. Planning stage will create actual implementation steps.

**Order**: #1 → #2 → #3 → #4

### #1: CLI File Split

**Depends On**: None

**Rationale**: Every subsequent item modifies CLI code. Splitting first means items #2, #3, and #4 land in focused, smaller files (~176–415 lines) rather than a monolithic 1842-line file. This reduces merge conflict risk and makes code review cleaner.

**Notes**: Pure refactor — no behavioral changes. Requires updating ~130+ mock `patch()` targets in test files to reference sub-module paths (e.g., `db_adapter.cli._connection.load_db_config` instead of `db_adapter.cli.load_db_config`). This is mechanical but high-volume.

---

### #2: Restore Failure Details

**Depends On**: #1

**Rationale**: Small, self-contained change with high user-facing impact. Depends on #1 only because the CLI display code will be in `_backup.py` rather than `__init__.py`. Could technically be done before #1 but lands cleaner after the split.

**Notes**: First introduction of `logging` in the codebase. Sets the pattern for future library-level logging.

---

### #3: Transaction Support

**Depends On**: #1

**Rationale**: Largest item — touches the Protocol, both adapters, and 3 consumer modules (restore, fix, sync). Depends on #1 because the CLI wrappers for fix and sync live in split modules. The 3 internal phases (Protocol → consumers → FK pre-flight) can be implemented as separate plan steps.

**Notes**: The `hasattr()` guard pattern ensures custom adapters without `transaction()` continue working. Transaction wrapping changes no behavior on success — only on failure (rollback instead of partial state).

---

### #4: SQL Parser Upgrade

**Depends On**: #1

**Rationale**: Independent of #2 and #3 (different code paths). Depends on #1 because `_parse_expected_columns` moves to `_helpers.py` in the split. New dependency (`sqlparse`) added to `pyproject.toml`. Largest test surface area change (new edge-case tests).

**Notes**: `sqlparse` limitation — it tokenizes but doesn't deeply parse column definitions. Column extraction still uses line-splitting within the tokenized body. This is a significant improvement (comment-free, properly tokenized) but not a full AST parse.

---

## Success Criteria

- [ ] CLI split into 6 modules with all tests passing (after patch target migration) and unchanged entry point
- [ ] Restore `failure_details` present in result dict when failures > 0
- [ ] CLI displays per-row failure details below Rich Table
- [ ] `transaction()` method on Protocol, implemented in both adapters
- [ ] `restore_database()` rolls back all inserts on unrecoverable error (connection loss, mode=fail ValueError). Per-row failures in mode=skip/overwrite are collected in `failure_details`, not rolled back.
- [ ] `apply_fixes()` rolls back all DDL on any exception (transaction wraps inside try/except, not outside)
- [ ] `_sync_direct()` rolls back per-table on FK violation (per-table granularity — earlier tables' commits are not rolled back)
- [ ] FK pre-flight warning emitted when `_sync_direct()` targets tables with FK constraints
- [ ] `_parse_expected_columns()` handles quoted identifiers, schema-qualified names, and SQL comments
- [ ] `_parse_fk_dependencies()` handles same edge cases
- [ ] `_get_table_create_sql()` handles same edge cases
- [ ] All existing 824 tests pass
- [ ] `sqlparse` added as core dependency

---

## Implementation Options

Implementation options are addressed per-item in the Analysis section. The key cross-cutting decision is documented here.

### Option A: `transaction()` on Protocol (Recommended)

Add `transaction()` directly to `DatabaseClient` Protocol. Use `hasattr()` guard in consumers for backward compatibility with custom adapters.

**Pros**:
- Type checkers flag adapters missing the method
- Single Protocol (no hierarchy)
- Consumers degrade gracefully via `hasattr()` guard

**Cons**:
- Soft breaking change for type checking (not runtime)

### Option B: Separate `TransactionalClient` Protocol

Create `TransactionalClient(Protocol)` extending `DatabaseClient` with `transaction()`. Consumers accept `TransactionalClient | DatabaseClient`.

**Pros**:
- Clean type separation
- No breaking change to `DatabaseClient`

**Cons**:
- Two Protocol types to manage
- Consumer signatures get verbose
- Over-engineered for current scope (2 adapters)

### Option C: Duck-typed without Protocol

Implement `transaction()` on both adapters without adding to Protocol. Consumers use `hasattr()`.

**Pros**:
- Zero breaking changes
- Simplest implementation

**Cons**:
- No type-checking benefit
- Method not discoverable via Protocol docs

### Recommendation

Option A — adding to the Protocol is the right level of formality for a library. The `hasattr()` guard in consumers handles backward compatibility. The soft breaking change for type checking is acceptable given the library is pre-1.0.

Note: `hasattr()` + Protocol is a transitional pattern. The whole point of a Protocol is static type checking — runtime `hasattr()` guards work around adapters that haven't caught up. At 1.0, the `hasattr()` guards should be removed and `transaction()` becomes a hard requirement on the Protocol contract.

---

## Files to Modify

| File | Change | Complexity |
|------|--------|------------|
| `src/db_adapter/cli/__init__.py` | Modify — extract to 5 internal modules, keep as facade | Med |
| `src/db_adapter/cli/_helpers.py` | Create — shared helpers, constants, console | Low |
| `src/db_adapter/cli/_connection.py` | Create — connect, validate, status, profiles | Low |
| `src/db_adapter/cli/_schema_fix.py` | Create — fix command | Low |
| `src/db_adapter/cli/_data_sync.py` | Create — sync command | Low |
| `src/db_adapter/cli/_backup.py` | Create — backup, restore, validate-backup | Low |
| `src/db_adapter/backup/backup_restore.py` | Modify — add failure_details + logging + transaction wrap | Med |
| `src/db_adapter/adapters/base.py` | Modify — add transaction() to Protocol | Low |
| `src/db_adapter/adapters/postgres.py` | Modify — implement transaction() with contextvars | Med |
| `src/db_adapter/adapters/supabase.py` | Modify — implement transaction() as NotImplementedError | Low |
| `src/db_adapter/schema/fix.py` | Modify — transaction wrap + sqlparse refactor | Med |
| `src/db_adapter/schema/sync.py` | Modify — transaction wrap in `_sync_direct()` | Med |
| `src/db_adapter/cli/_data_sync.py` | Modify — FK pre-flight warning in `_async_sync()` | Low |
| `pyproject.toml` | Modify — add sqlparse dependency | Low |
| `tests/test_lib_extraction_cli.py` | Modify — update ~130+ mock `patch()` targets to sub-module paths | Med |
| `tests/test_lib_extraction_backup.py` | Modify — add failure_details test | Low |
| `tests/test_lib_extraction_fix.py` | Modify — add sqlparse edge-case tests | Low |

---

## Testing Strategy

**Unit Tests**:
- CLI split: existing tests pass after mock `patch()` target migration (~130+ path updates from `db_adapter.cli.*` to `db_adapter.cli._submodule.*`)
- Failure details: mock adapter raises on insert, verify `failure_details` structure
- Transaction: mock adapter verifies commit on success, rollback on exception
- SQL parsing: edge-case tests for comments, quoted identifiers, schema-qualified names

**Integration Tests**:
- Transaction rollback: insert rows, raise mid-restore, verify DB is clean (requires live DB)
- FK pre-flight: create tables with FKs, run sync without BackupSchema, verify warning

**Manual Validation**:
- `uv run db-adapter restore backup.json --dry-run` — verify Rich Table + failure details display
- `uv run db-adapter --help` — verify CLI still works after split

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `sqlparse` doesn't handle all PostgreSQL edge cases | LOW | MED | sqlparse handles standard SQL; PostgreSQL-specific syntax (e.g., `GENERATED ALWAYS AS`) is in column definitions, not table/column names which is all we parse |
| `contextvars` transaction tracking has edge cases with nested transactions | LOW | MED | Don't support nesting in v1 — raise if `_transaction_conn` is already set |
| CLI split introduces subtle import ordering issues | LOW | LOW | All existing 824 tests validate imports. Run full suite after split. |
| `hasattr()` guard pattern is fragile | LOW | LOW | Only 3 call sites. Well-documented in code. Can upgrade to Protocol check later. |
| Long-running transactions on large restores | LOW | MED | `restore_database()` wraps the entire multi-table loop in one transaction, holding locks and accumulating WAL until commit. For db-adapter's expected dataset size (developer-scoped data, not bulk ETL), this is acceptable. If large-dataset support is needed later, consider per-table transactions with an opt-in full-atomicity flag. |

---

## Open Questions

1. **Nested transactions**: Should `transaction()` support nesting (via savepoints)? Current design says no — raise if already in a transaction. Revisit if a real use case emerges.
2. **`sqlparse` version pinning**: Pin to specific version or use `>=` constraint? Follow project convention (check existing deps in `pyproject.toml`).
3. **Logging configuration**: Should the CLI configure a root logger handler, or leave it to the caller? Current recommendation: CLI adds no handler (library convention). Users see warnings only if they configure logging.

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| CLI split granularity | 6 modules by domain | Natural boundaries (connection, fix, sync, backup), acyclic imports, 176–415 lines each |
| Transaction API | Context manager only (no begin/commit/rollback) | Matches SQLAlchemy's engine.begin() pattern, eliminates forgotten commit/rollback bugs |
| Transaction storage | contextvars | Async-safe, per-task isolation, no shared mutable state |
| Supabase transaction | NotImplementedError | Honest about limitations — REST API has no transaction semantics |
| Protocol evolution | Add to Protocol + hasattr() guard | Type checking benefit + runtime backward compatibility |
| SQL parser | sqlparse (new dependency) | Pure Python, zero transitive deps, handles all failure cases. Comment stripping alone doesn't fix quoted identifiers or schema-qualified names. |
| Failure details storage | In result dict (not separate return) | Backward compatible — adding new keys to existing dict |

---

## Next Steps

1. Review this design and confirm approach
2. Run `/review-doc` to check for issues
3. Create implementation plan (`/dev-plan`)
4. Execute implementation (`/dev-execute`)

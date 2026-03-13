# Examiner Audit: db-adapter vs Mission Control db CLI

## Summary
| Attribute | Value |
|-----------|-------|
| **Date** | 2026-03-11 (risks), 2026-03-12 (research) |
| **Role** | Examiner (independent analysis) |
| **Scope** | Full codebase comparison — db-adapter library vs MC `core/schema/` + `core/backup/` predecessor |
| **Verdict** | Extraction successful. 6 technical risks identified (5 inherited, 1 new from architecture change), ranked by priority. Solutions researched for all 6. |

---

## 1. Extraction Comparison

### What db-adapter got right

| Area | MC (before) | db-adapter (after) | Verdict |
|------|-------------|-------------------|---------|
| Async | Fully sync adapters, sync introspector | Async-first (asyncpg, psycopg async) | Major upgrade |
| Table knowledge | Hardcoded `projects/milestones/tasks` | Generic via `db.toml` + `BackupSchema` JSON | Correct for a library |
| CLI entry points | Two (`schema/__main__.py` + `backup/backup_cli.py`) | One unified `db-adapter` command | Cleaner UX |
| Config defaults | All flags required on every invocation | `[schema]`, `[sync]`, `[defaults]` sections in db.toml | Reduces repetition |
| Row counts | Not available | `connect` and `status` show table row counts | Operational visibility |
| Adapter caching | Global mutable state in `get_db_adapter()` | No caching — callers own lifecycle | Safer for library |
| Backup schema | Hardcoded table hierarchy in Python | External `BackupSchema` JSON file | Configurable per-project |
| Sync path | Subprocess isolation (backup_cli as child process) | In-process async (cleaner but less isolated) | Tradeoff — see Risk 2 |

**No MC functionality was lost.** All 8 commands map 1:1. The extraction added features (config defaults, row counts, table filters on backup, `--validate` flag) without removing any.

### Command mapping

| MC Command | db-adapter Command | Changes |
|------------|-------------------|---------|
| `python -m schema connect` | `db-adapter connect` | Added row counts, config-driven schema file |
| `python -m schema status` | `db-adapter status` | Converted to async, added row counts |
| `python -m schema profiles` | `db-adapter profiles` | Added active profile marker |
| `python -m schema validate` | `db-adapter validate` | Added `--schema-file` override |
| `python -m schema fix` | `db-adapter fix` | Added auto-backup, `--no-backup`, config-driven column-defs |
| `python -m schema sync` | `db-adapter sync` | Added config-driven tables/user-id, BackupSchema path |
| `python backup_cli.py backup` | `db-adapter backup` | Added `--tables` filter, `--validate` flag, config fallbacks |
| `python backup_cli.py restore` | `db-adapter restore` | Added config-driven defaults, Rich Table output |

### MC subprocess isolation vs db-adapter in-process

MC used subprocess isolation in two places:
- **Sync** (`core/schema/sync.py`): called `backup_cli.py backup` then `backup_cli.py restore` as separate `subprocess.run()` calls
- **Fix auto-backup** (`core/schema/__main__.py`): called `backup_cli.py backup` via subprocess before executing destructive DDL

Each subprocess got its own connection pool, and a crash in one didn't corrupt the other's state. If restore failed, the backup subprocess had already completed cleanly — no shared adapter state to worry about.

db-adapter does everything in-process with async. This is cleaner and faster, but means a failure mid-restore shares state with the caller. The `finally` blocks handle adapter cleanup, so connections don't leak, but partial data state is possible (see Risk 2 and Risk 6).

Not a bug — a conscious tradeoff of isolation for simplicity.

---

## 2. Technical Risks

Five risks inherited from MC that matter more now that db-adapter is a library, plus one new risk introduced by the architecture change from subprocess to in-process execution.

### Risk 1: Regex SQL Parsing — HIGH

**Where:**
- `cli/__init__.py` → `_parse_expected_columns()` — parses CREATE TABLE from SQL files
- `schema/fix.py` → `_parse_fk_dependencies()` — parses REFERENCES clauses
- `schema/fix.py` → `_get_table_create_sql()` — extracts CREATE TABLE blocks

**Problem:** All three use regex on raw SQL files. Known failure cases:
- SQL comments containing `CREATE TABLE` or `REFERENCES` keywords
- Quoted identifiers (e.g., `"order"`, `"group"` — reserved words as table names)
- Multi-line column defaults containing parentheses (confuses block detection)
- `CREATE TABLE IF NOT EXISTS` with schema prefix (e.g., `public.tablename`)

**Why it matters more now:** MC controlled its own schema files and could ensure they followed the expected patterns. As a library, db-adapter will encounter arbitrary SQL files from other projects. This is the most likely source of first bug reports.

**Mitigation options:**
- Use a lightweight SQL parser (e.g., `sqlparse` or `sqlglot`) for CREATE TABLE extraction
- Or: document the supported SQL subset explicitly (no comments in CREATE blocks, no quoted identifiers, etc.)
- Short-term: add comment stripping as a preprocessing step before regex

### Risk 2: No Transaction Boundaries on Multi-Table Operations — MEDIUM

**Where:**
- `backup/backup_restore.py` → `restore_database()` — restores tables sequentially, no transaction
- `schema/fix.py` → `apply_fixes()` — executes DDL sequentially, no transaction

**Problem:** If restore inserts rows into 3 of 5 tables then fails on the 4th, you get partial state with no rollback. Same for fix — if DROP succeeds but CREATE fails, the table is gone.

**Current behavior:** The `failed` counter increments and processing continues to the next row. For fix, exceptions propagate and abort (but prior DDL already committed).

**Why it matters more now:** MC operators understood the system and could clean up manually. Library consumers won't know what partial state looks like or how to recover.

**Mitigation options:**
- Wrap `restore_database()` in a single transaction (requires adapter-level `begin()`/`commit()` support)
- For fix: DDL in PostgreSQL is transactional — wrap the entire fix sequence in a transaction
- At minimum: document the partial-state risk and provide recovery guidance

### Risk 3: Direct Sync Without BackupSchema is a Foot-Gun — MEDIUM

**Where:** `schema/sync.py` → `_sync_direct()`

**Problem:** If tables have foreign keys and user runs `sync --from X --confirm` without configuring `backup_schema` in db.toml, it falls through to `_sync_direct()`. This path does naive row-by-row inserts with no FK awareness. FK violations happen *after* some rows are already inserted — leaving the destination in a partial state.

The error message helpfully suggests using BackupSchema, but the damage is done.

**Current behavior:** `_sync_direct()` catches the FK error and raises `ValueError` with guidance. But rows inserted before the error remain.

**Mitigation options:**
- Detect FK constraints via introspector before attempting direct sync; warn or require BackupSchema when FKs exist
- Or: wrap direct sync in a transaction so FK violations roll back all inserts
- Short-term: add a pre-flight check that warns "tables have FK constraints, consider configuring backup_schema"

### Risk 4: `failed` Count Silently Swallows Exceptions — MEDIUM

**Where:** `backup/backup_restore.py:344-348` (`_restore_table()`)

```python
except ValueError:
    raise  # mode=fail
except Exception:
    table_summary["failed"] += 1  # ← silent
```

**Problem:** Any non-ValueError exception increments `failed` and continues. The user sees "Failed: 3" in the Rich Table output but has no idea *which* rows failed or *why*. No logging, no error details preserved in the return value.

**Why it matters:** This generates "it didn't work and I don't know why" debugging sessions. The caller (CLI or programmatic) has no way to diagnose failures without adding their own try/except around the library call.

**Mitigation options:**
- Collect `(row_index, table_name, str(exception))` tuples in the result dict under a `"failure_details"` key
- Surface in CLI output: show summary table normally, print failure details below (or behind `--verbose`)
- At minimum: log the exception with `logging.warning()` so it appears in debug output

### Risk 5: CLI is 1842 Lines in One `__init__.py` — LOW

**Where:** `src/db_adapter/cli/__init__.py`

**Problem:** MC split CLI across `schema/__main__.py` (~600 lines) and `backup/backup_cli.py` (~300 lines). db-adapter unified into one file for a single entry point. Each new feature adds weight — Rich Table for restore, row counts, config fallbacks, etc.

**Current state:** Still manageable. The file is well-organized with clear section headers and helper functions. But the next major command addition should prompt a split.

**Mitigation options:**
- Split into `cli/` package: `cli/__init__.py` (argparse + main), `cli/commands.py` (handlers), `cli/helpers.py` (shared utilities)
- Or: `cli/schema_commands.py`, `cli/backup_commands.py` — mirrors MC's original split
- Not urgent — address opportunistically with next significant CLI work

### Risk 6: Loss of Subprocess Isolation for Sync and Fix — LOW

**Where:**
- `schema/sync.py` → `_sync_via_backup()` — backup + restore in same process
- `cli/__init__.py` → `_async_fix()` → `apply_fixes()` — auto-backup + DDL + restore in same process

**What MC did:** MC used `subprocess.run()` to call `backup_cli.py backup` and `backup_cli.py restore` as separate child processes for both sync and fix operations. Each subprocess got its own Python interpreter, connection pool, and crash boundary. A restore failure couldn't corrupt the source adapter's connection state, and the backup file was always written cleanly before restore began.

**What db-adapter does:** Everything runs in-process with async. The sync path calls `backup_database()` then `restore_database()` using the same event loop. The fix path calls the backup callback, executes DDL, then calls restore — all sharing adapter state.

**Concrete risk scenarios:**
- If `restore_database()` raises mid-way during sync, the source adapter's connection pool may be in an unclear state (though `finally` blocks close adapters)
- If auto-backup succeeds but DDL fails during fix, the adapter used for DDL may have a half-committed transaction (PostgreSQL DDL is transactional, so this should roll back — but the adapter doesn't expose transaction control)
- If an asyncio cancellation occurs mid-restore, cleanup may not run (unlike subprocess kill, which leaves the backup file intact)

**Why it's LOW priority:** The `finally` blocks handle adapter cleanup in practice. The risk is theoretical — no reported failures from this pattern. And the in-process approach is significantly simpler, faster, and more testable.

**Mitigation options (if needed later):**
- Add explicit transaction support to the adapter Protocol (`begin()`/`commit()`/`rollback()`) — this also addresses Risk 2
- Or: use separate adapter instances for source and destination in sync (already done) and ensure fix uses a fresh adapter for DDL vs. backup

---

## 3. Non-Issues (Investigated and Cleared)

| Item | Why it's fine |
|------|---------------|
| Lock file has no expiry | `connect` rewrites it; `status` degrades gracefully if stale |
| Backup minute-precision timestamp | Acceptable for CLI tool; not a continuous backup system |
| No column type validation in comparator | Presence-only is the right scope — type drift is a different problem |
| No adapter caching in factory | Deliberate design for library safety; callers own lifecycle |
| ColumnFix strips NOT NULL on ALTER | Necessary — can't add NOT NULL column to table with existing data without a default |
| No backup file encryption | Backups are local dev tool artifacts, not production secrets transport |
| Lock file is plaintext | Same as above — local dev tool, not a security boundary |

---

## 4. Implementation Order (Research-Informed)

Pre-research ranking was by impact. Post-research ranking accounts for dependencies and the fact that Risks 2, 3, and 6 share a unified solution (transaction support).

| Order | Risk(s) | Effort | Rationale |
|-------|---------|--------|-----------|
| **1** | Risk 5: CLI file split | Small | Refactor while file is stable. Every subsequent change touches CLI — split first avoids merge pain. |
| **2** | Risk 4: Silent failures | Small | Self-contained, high user impact. Add `failure_details` to result dict + show in CLI. |
| **3** | Risks 2+3+6: Transaction support | Medium | Unified solution: `transaction()` context manager on Protocol. Wraps restore, fix, and sync. Includes FK pre-flight for Risk 3. |
| **4** | Risk 1: Regex SQL parsing | Medium | Largest scope. Replace 3 regex functions with `sqlparse` (new dep, pure Python). Independent of other risks. |

See Section 6 for detailed research findings and recommended solutions per risk.

---

## 5. Architectural Observations

### What survived extraction well
- **Protocol typing** (`DatabaseClient`) — structural typing means no inheritance coupling
- **Layered architecture** — adapters → config → factory → schema → backup → CLI layers are clean
- **Set-based schema validation** — pure sync logic with no side effects, easy to test
- **Config model** — Pydantic validation catches bad config early

### What could improve with maturity
- **Error detail propagation** — too many places silently swallow or summarize errors (Risk 4 is the worst case, but `_get_table_row_counts()` returning `{}` on any error is the same pattern)
- **SQL parsing** — the regex approach worked for MC's controlled environment but needs hardening for library use
- **Transaction support** — the adapter Protocol has no `begin()`/`commit()`/`rollback()` — adding these would enable Risks 2, 3, and 6 fixes

### What should NOT change
- The async-first design
- The no-caching factory pattern
- The config-driven CLI defaults
- The Protocol-based adapter interface (structural typing over inheritance)

---

## 6. Research Findings (2026-03-12)

Parallel research conducted across all 6 risks. Risks 2, 3, and 6 grouped into a unified transaction solution.

### 6.1 Risk 5: CLI File Split

**Recommendation:** Split now, by domain.

**Current state:** 1842 lines, 23 functions, 3 distinct domains (connection/schema, fix, data ops). Organization is good (8/10 — clear section headers, logical flow), but past the "beneficial to split" threshold (~1200 lines).

**Proposed structure:**
```
cli/
  __init__.py      → main(), argparse, re-exports (facade)     ~245 lines
  _helpers.py      → shared helpers, constants, imports         ~311 lines
  _connection.py   → connect, validate, status, profiles        ~415 lines
  _schema_fix.py   → fix command + wrapper                      ~335 lines
  _data_sync.py    → sync command + wrapper                     ~176 lines
  _backup.py       → backup, restore, validate-backup           ~380 lines
```

**Import graph (acyclic):**
```
__init__.py ← imports all modules
  _helpers.py       (no cli imports)
  _connection.py  ← _helpers.py
  _schema_fix.py  ← _helpers.py
  _data_sync.py   ← _helpers.py
  _backup.py      ← _helpers.py
```

**Key decisions:**
- Re-export all 24 symbols from `__init__.py` (23 functions + `_EXCLUDED_TABLES` constant) — **zero test changes needed** (tests import from `db_adapter.cli`)
- Entry point `db_adapter.cli:main` unchanged
- Underscore-prefixed module names (`_helpers.py`) signal internal implementation
- Each module 176–415 lines (manageable)

**Why split first:** Every subsequent risk fix touches CLI code. Splitting first avoids merge conflicts and makes each subsequent change land in a focused, smaller file.

### 6.2 Risk 4: Silent Failures in Restore

**Recommendation:** Add `failure_details` list to result dict + `logging.warning()` per failure.

**Current return structure:**
```python
{"dry_run": False, "items": {"inserted": 5, "updated": 0, "skipped": 2, "failed": 3}}
```

**Proposed return structure:**
```python
{"dry_run": False, "items": {"inserted": 5, "updated": 0, "skipped": 2, "failed": 3,
                              "failure_details": [
                                  {"row_index": 0, "old_pk": "a1", "error": "IntegrityError: duplicate key..."},
                                  {"row_index": 2, "old_pk": "a3", "error": "KeyError: 'required_column'"},
                              ]}}
```

**Changes needed:**

| File | Change | Lines |
|------|--------|-------|
| `backup/backup_restore.py` | Add `logging` import, initialize `failure_details` list per table, capture exception type+message in except block, emit `logger.warning()` | ~20 lines |
| `cli/_backup.py` (post-split) | After Rich Table, check for `failure_details` in any table, print details if failures > 0 | ~15 lines |
| Tests | Verify `failure_details` structure on simulated failure | ~30 lines |

**Key findings:**
- **Backward compatible** — adding new keys to existing dict. Old callers using `.get("failed", 0)` are unaffected.
- **Only silent handler in codebase** — `sync.py` and `fix.py` both capture error details in their result objects. Restore is the sole outlier.
- **No `--verbose` flag needed** — show failure details unconditionally when failures > 0. The restore operation is explicit enough that users expect full output.
- **Codebase has zero `logging` imports today** — this would be the first. Appropriate for a library.

**CLI display (when failures > 0):**
```
       Restore Results
┌──────────┬──────────┬─────────┬─────────┬────────┐
│ Table    │ Inserted │ Updated │ Skipped │ Failed │
├──────────┼──────────┼─────────┼─────────┼────────┤
│ items    │        5 │       0 │       0 │      2 │
└──────────┴──────────┴─────────┴─────────┴────────┘

  Failed row details:
    items row 3 (pk=a1b2): IntegrityError: duplicate key value
    items row 7 (pk=c3d4): KeyError: 'required_column'
```

### 6.3 Risks 2+3+6: Transaction Support (Unified Solution)

**Recommendation:** Add `transaction()` async context manager to the adapter Protocol, implemented via `contextvars` in the PostgreSQL adapter.

**Why these three risks are one solution:** MC used subprocess isolation to get atomicity for free — each subprocess was its own transaction boundary. When db-adapter moved to in-process async, it lost that implicit boundary. Transaction support is the direct replacement: it restores the all-or-nothing guarantee that subprocess isolation provided, but at the right abstraction level (database transactions rather than OS process boundaries).

| Risk | MC's safety mechanism | db-adapter replacement |
|------|----------------------|----------------------|
| Risk 2 (restore partial state) | Subprocess crash → no partial commits | `async with adapter.transaction():` around restore loop |
| Risk 3 (sync FK violations) | Subprocess crash → no partial inserts | Per-table transaction in `_sync_direct()` + FK pre-flight warning |
| Risk 6 (fix DDL atomicity) | Subprocess backup completed before DDL started | `async with adapter.transaction():` around DDL sequence (PostgreSQL DDL is transactional) |

#### Root Cause

Each CRUD method in `AsyncPostgresAdapter` wraps itself in `async with self._engine.begin() as conn:` — a micro-transaction that auto-commits. Callers cannot group multiple operations into a single atomic unit. This is the root cause of partial state in restore, fix, and sync.

#### Protocol Change

Add one method to `DatabaseClient`:

```python
@asynccontextmanager
async def transaction(self) -> AsyncIterator[None]:
    """Enter a transaction. Auto-commits on clean exit, auto-rolls back on exception."""
    ...
```

**Why context manager only** (not `begin()`/`commit()`/`rollback()`):
- Matches SQLAlchemy's `engine.begin()` pattern exactly
- Eliminates forgotten `commit()` or `rollback()` bugs
- Standard Python async context manager pattern
- Supabase can raise `NotImplementedError` cleanly

#### PostgreSQL Implementation

Use `contextvars` to track the active transaction connection:

```python
_transaction_conn: contextvars.ContextVar[AsyncConnection | None] = contextvars.ContextVar(
    "_transaction_conn", default=None
)

@asynccontextmanager
async def transaction(self):
    async with self._engine.begin() as conn:
        token = _transaction_conn.set(conn)
        try:
            yield
        finally:
            _transaction_conn.reset(token)
```

CRUD methods check for an active transaction connection:

```python
async def insert(self, table, data):
    conn = _transaction_conn.get(None)
    if conn is not None:
        # Use existing transaction connection
        result = await conn.execute(...)
    else:
        # Create new micro-transaction (current behavior)
        async with self._engine.begin() as conn:
            result = await conn.execute(...)
```

**Key finding:** SQLAlchemy already supports this — the infrastructure exists, it just needs to be exposed.

#### Supabase Implementation

```python
async def transaction(self):
    raise NotImplementedError(
        "Transactions not supported for Supabase adapter. "
        "Use PostgreSQL adapter for transactional operations."
    )
```

Honest about limitations. Supabase REST API has no transaction semantics.

#### Impact on Restore (Risk 2)

Wrap the main loop in `restore_database()`:

```python
async with adapter.transaction():
    for table_def in schema.tables:
        await _restore_table(adapter, table_def, ...)
    # All-or-nothing: commit on success, rollback on any exception
```

If any row in any table fails, the entire restore rolls back. No partial state.

#### Impact on Sync (Risk 3)

Two changes:

1. **Per-table transaction in `_sync_direct()`:**
```python
for table in tables:
    async with dest_adapter.transaction():
        for row in source_rows:
            await dest_adapter.insert(table, data=row)
        # If FK violation, all rows for this table roll back
```

2. **Pre-flight FK detection** (bonus): Introspector already extracts FK constraints via `_get_constraints()`. Before `_sync_direct()`, check if any target tables have FKs and warn:
```python
for table_name in tables:
    fks = [c for c in schema.tables[table_name].constraints.values()
           if c.constraint_type == "FOREIGN KEY"]
    if fks:
        warn(f"{table_name} has FK constraints — consider configuring backup_schema")
```

#### Impact on Fix (Risk 6)

Wrap DDL in `apply_fixes()`:

```python
async with adapter.transaction():
    for table_name in plan.create_order:
        await adapter.execute(create_sql)
    for column_fix in plan.missing_columns:
        await adapter.execute(alter_sql)
    # PostgreSQL DDL is transactional — all rolls back on failure
```

**Key finding confirmed:** PostgreSQL supports transactional DDL (CREATE/ALTER/DROP all roll back). SQLAlchemy's async engine honors this.

#### Phased Rollout

| Phase | Scope | Description |
|-------|-------|-------------|
| Phase 1 | Protocol + adapters | Add `transaction()` to Protocol, implement in PostgreSQL (contextvars), Supabase (NotImplementedError). Tests for commit/rollback semantics. |
| Phase 2 | Consumers | Wrap `restore_database()`, `apply_fixes()`, and `_sync_direct()` in transactions. |
| Phase 3 | FK pre-flight | Add introspector-based FK detection warning before `_sync_direct()`. |

#### Protocol Evolution

Adding `transaction()` to `DatabaseClient` is a **soft breaking change**. The adapters use structural typing (neither `AsyncPostgresAdapter` nor `AsyncSupabaseAdapter` inherits from `DatabaseClient`), so:
- Existing adapters that don't implement `transaction()` still work at runtime for non-transaction code paths
- Type checkers will flag them as incompatible with `DatabaseClient` until they add the method
- Callers that use `adapter.transaction()` will get `AttributeError` on adapters without it

Mitigation options:
- **Option A (recommended):** Add `transaction()` to both built-in adapters. Use `hasattr(adapter, 'transaction')` check in callers (`restore_database`, `apply_fixes`, `_sync_direct`) so they degrade gracefully for custom adapters that haven't added it yet.
- **Option B:** Create a separate `TransactionalClient(Protocol)` that extends `DatabaseClient`. Callers accept either type. Cleaner typing but more complex.
- **Option C:** Don't add to Protocol at all — just implement on both adapters as a duck-typed method. Callers use `hasattr()`. No type-checking benefit but zero breaking changes.

### 6.4 Risk 1: Regex SQL Parsing

**Recommendation:** Replace 3 regex-based parsing functions with `sqlparse` (pure Python, minimal footprint — would be a new dependency).

#### Current Failure Cases (Verified)

| Input | Expected | Actual (regex) | Status |
|-------|----------|-----------------|--------|
| `CREATE TABLE users (id TEXT, name TEXT);` | `{"users": {"id", "name"}}` | Correct | OK |
| `CREATE TABLE IF NOT EXISTS users (...)` | Parsed | Correct | OK |
| `CREATE TABLE public.users (...)` | `{"users": {"id", ...}}` | Not found | **FAIL** |
| `CREATE TABLE "Items" (...)` | `{"Items": {...}}` | Not found | **FAIL** |
| `-- CREATE TABLE fake (...)` in comment | Ignored | Parsed as real table | **FAIL** |
| `/* block */ email TEXT` inside body | `{"email"}` | `{"/*", "block", "email"}` | **FAIL** |
| `REFERENCES public.users(id)` | `users` | Not found | **FAIL** |

#### Why sqlparse

| Library | In environment | Size | Handles all cases | PostgreSQL-specific |
|---------|---------------|------|-------------------|---------------------|
| `sqlparse` | No (new dep) | Minimal (pure Python) | Yes (with post-processing) | No (generic SQL) |
| `sqlglot` | No | ~15MB | Yes (deep AST) | Multi-dialect |
| `pglast` | No | Heavy (C extension) | Yes (bulletproof) | Yes |

`sqlparse` is the right choice: pure Python with zero transitive dependencies, handles quotes/comments/schema-qualified names, and db-adapter's parsing needs are narrow (table names, column names, REFERENCES targets — no expression evaluation). Would be added as a core dependency in `pyproject.toml`.

#### Scope of Change

3 functions to refactor:

| Function | File | Current lines | Approach |
|----------|------|---------------|----------|
| `_parse_expected_columns()` | `cli/__init__.py` | 72 lines | Use `sqlparse.parse()` to find CREATE statements, extract table name from `Identifier` token, extract column names from `Parenthesis` token body |
| `_parse_fk_dependencies()` | `schema/fix.py` | 40 lines | Use `sqlparse.parse()` for CREATE blocks, regex for REFERENCES within tokenized body (comments already stripped by tokenizer) |
| `_get_table_create_sql()` | `schema/fix.py` | 36 lines | Use `sqlparse.parse()` to find matching CREATE statement by table name, return raw SQL |

#### Test Gap

Current tests cover basic cases (multiple tables, IF NOT EXISTS, constraints, mixed case). Missing edge cases:
- Schema-qualified table names (`public.users`)
- Quoted identifiers (`"Items"`, `"User Name"`)
- SQL comments (`--` inline, `/* block */`)
- REFERENCES with quoted/schema-qualified tables

New tests needed: ~8-10 test cases for the edge cases above.

#### Comment-Stripping Alternative (Rejected)

Preprocessing to strip comments before regex would fix the comment problem but **not** schema-qualified names or quoted identifiers. The `\w+` regex pattern fundamentally cannot match `public.users` or `"Items"`. A real tokenizer is needed.

#### sqlparse Limitation

`sqlparse` tokenizes but doesn't deeply parse column definitions. Column name extraction still requires line-splitting of the parenthesized body — but on **comment-free, properly tokenized** text rather than raw SQL. This is a significant improvement over the current approach.

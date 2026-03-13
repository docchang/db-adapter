# core-cli-counts Design

> **Purpose**: Analyze and design solutions before implementation planning
>
> **Important**: This task must be self-contained (works independently; doesn't break existing functionality and existing tests)

## Executive Summary

| Attribute | Value |
|-----------|-------|
| **Created** | 2026-03-10T22:33:03-0700 |
| **Task** | Add table row counts to CLI connect and status commands |
| **Type** | Feature |
| **Scope** | CLI, factory -- 2-3 files modified |
| **Code** | NO - This is a design document |
| **Risk Profile** | Standard |
| **Risk Justification** | Additive display-only feature; no changes to data flow, adapters, or schema logic |

**Challenge**: After connecting or checking status, users have no visibility into whether the database is populated, empty, or missing data -- they must run separate queries to see table row counts.

**Solution**: Add a "Table Data" summary (table name + row count) to the `connect` output, and optionally to `status` (which becomes async to support a DB query).

---

## Context

### Current State

**`connect` output** (after successful connection):
```
v Connected to profile: local
  Schema validation: PASSED

  Switched from rds to local
```

No data visibility. User doesn't know if the DB has 0 rows or 10,000 rows in any table. The old Mission Control CLI showed a "Database Data" table with per-entity counts on both `connect` and `status`.

**`status` output** (local-only, no DB calls):
```
┌───────────────────────────────────┐
│        Connection Status          │
├─────────────────┬─────────────────┤
│ Current profile │ local           │
│ Profile source  │ .db-profile     │
│ Provider        │ postgres        │
│ Description     │ Local dev       │
└─────────────────┴─────────────────┘
```

Status is currently a local-only command (reads `.db-profile` + `db.toml`, no DB connection). Adding counts requires a DB query.

**What we already have**:
- `SchemaIntrospector._get_tables()` -- returns all table names from `information_schema`
- `connect_and_validate()` already opens an introspector connection during `connect`
- `get_adapter()` / `get_active_profile()` can resolve a profile to a DB URL
- The adapter's `execute()` runs raw SQL but doesn't return results (DDL-only)
- The adapter's `select()` can query any table

**Key gap**: `connect_and_validate()` uses `SchemaIntrospector` (psycopg) which closes after validation. Row counts need either a second connection or a way to piggyback on the existing one.

### Target State

**`connect` output** (with row counts):
```
v Connected to profile: local
  Schema validation: PASSED

         Table Data
┌────────────┬───────┐
│ Table      │ Rows  │
├────────────┼───────┤
│ categories │    12 │
│ items      │    85 │
│ users      │     3 │
└────────────┴───────┘

  Switched from rds to local
```

**`status` output** (with row counts -- now async):
```
┌───────────────────────────────────┐
│        Connection Status          │
├─────────────────┬─────────────────┤
│ Current profile │ local           │
│ Profile source  │ .db-profile     │
│ Provider        │ postgres        │
│ Description     │ Local dev       │
└─────────────────┴─────────────────┘

         Table Data
┌────────────┬───────┐
│ Table      │ Rows  │
├────────────┼───────┤
│ categories │    12 │
│ items      │    85 │
│ users      │     3 │
└────────────┴───────┘
```

Row counts shown on both commands. All tables in the database are counted (no config needed). Tables sorted alphabetically.

---

## Constraints

- **Scope boundaries**: No config-driven table filtering (count all tables). No cross-profile comparison table (requires connecting to two DBs simultaneously, fragile). These are separate features if ever needed.
- **Must NOT happen**: Changing `connect_and_validate()` return type or signature. Modifying `SchemaIntrospector` public API. Breaking existing CLI tests.
- **Compatibility**: `status` currently returns `0` always and makes no DB calls. After this change it will make a DB call but must still return `0` on success and degrade gracefully if DB is unreachable (show status without counts).
- **Performance**: Row counts use `SELECT COUNT(*)` per table. For databases with many large tables this could be slow. Acceptable for dev tooling; not a concern for typical use (< 20 tables).

---

## Analysis

> Each item analyzed independently. No implied order - read in any sequence.

### 1. Row Count Query Helper

**What**: A shared async helper function that connects to the database and returns row counts for all tables.

**Why**: Both `connect` and `status` need the same data. Extracting a helper avoids duplication and keeps the CLI handlers clean.

**Approach**:

Add a helper to `cli/__init__.py` that opens a raw `psycopg.AsyncConnection` to discover tables and run `SELECT COUNT(*)` for each:

```python
async def _get_table_row_counts(database_url: str) -> dict[str, int]:
    """Get row counts for all tables in the database."""
    # 1. Open raw psycopg.AsyncConnection (not SchemaIntrospector)
    # 2. Query information_schema.tables for table names
    #    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    #    (excludes views; same filters as SchemaIntrospector._get_tables())
    # 3. Exclude system tables matching EXCLUDED_TABLES_DEFAULT
    #    (schema_migrations, pg_stat_statements, spatial_ref_sys)
    # 4. For each table: SELECT COUNT(*) FROM "table_name" (quoted identifier)
    # 5. Return dict mapping table_name -> count, sorted alphabetically
```

**Why a raw psycopg connection instead of SchemaIntrospector**: `SchemaIntrospector` has no public method to execute arbitrary SQL like `SELECT COUNT(*)`. Its public API (`test_connection()`, `introspect()`, `get_column_names()`) does not expose raw query execution, and its internal `_get_tables()` method is private. Rather than coupling to private internals, the helper opens its own `psycopg.AsyncConnection` directly -- this is the same driver the introspector uses, so it's lightweight and consistent. The table discovery query (from `information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'`) is replicated directly in the helper, with the same `EXCLUDED_TABLES_DEFAULT` filtering (`schema_migrations`, `pg_stat_statements`, `spatial_ref_sys`) to maintain parity with the introspector's table set.

**Why not the adapter**: The adapter's `select()` method returns `list[dict]` -- overhead for a simple count. It also requires constructing a full SQLAlchemy-based adapter just for counts.

**SQL safety**: Table names come from `information_schema.tables` (trusted source), not user input. Table names are quoted using `sql.Identifier` from psycopg to handle reserved words and special characters safely.

**New imports required**: `psycopg` (for `AsyncConnection`) and `psycopg.sql` (for `sql.Identifier`) will need to be imported in `cli/__init__.py`. `resolve_url` must be added to the `from db_adapter.factory import (...)` block.

**Error handling**: Wrap in try/except. On failure, return an empty dict (caller shows no counts table rather than crashing).

Files to modify:
- `cli/__init__.py` -- add `_get_table_row_counts()` helper

Validate: Helper returns `{"categories": 12, "items": 85}` for a populated database, `{}` for an empty or unreachable database.

---

### 2. Display Helper for Row Counts Table

**What**: A function that renders a Rich table from the row counts dict.

**Why**: Both `connect` and `status` display the same table format. Extracting display logic keeps handlers clean.

**Approach**:

Add a display helper to `cli/__init__.py`:

```python
def _print_table_counts(counts: dict[str, int]) -> None:
    """Print a Rich table showing row counts per table."""
    # Skip entirely if counts is empty (no tables or error)
    # Create Rich Table with "Table" and "Rows" columns
    # Add rows sorted alphabetically by table name
    # Right-align the Rows column for readability
```

Output format:
```
         Table Data
┌────────────┬───────┐
│ Table      │  Rows │
├────────────┼───────┤
│ categories │    12 │
│ items      │    85 │
│ users      │     3 │
└────────────┴───────┘
```

Files to modify:
- `cli/__init__.py` -- add `_print_table_counts()` helper

Validate: Renders correctly with 0, 1, and many tables. Skips rendering when dict is empty.

---

### 3. Add Row Counts to `connect` Command

**What**: After a successful `connect`, query and display table row counts.

**Why**: Gives immediate visibility into whether the database is populated. The old MC CLI showed this and it was useful for spotting empty databases or confirming sync results.

**Approach**:

In `_async_connect()`, after the success path (schema validation passed), resolve the database URL and call the row counts helper:

```python
# After success output (schema validation line)...
# Get and display table row counts (guard for None config/profile)
if config and result.profile_name and result.profile_name in config.profiles:
    url = resolve_url(config.profiles[result.profile_name])
    counts = await _get_table_row_counts(url)
    if counts:
        console.print()
        _print_table_counts(counts)
```

**URL resolution**: `connect_and_validate()` already resolves the profile internally but doesn't expose the URL. The CLI handler must resolve it independently using `config.profiles[profile_name]` + `resolve_url()`. The config is already loaded at the top of `_async_connect()` but can be `None` (when `db.toml` is missing or malformed). Row counts should only be attempted when `config is not None` and `result.profile_name is not None`.

**Import**: `resolve_url` is not currently imported in `cli/__init__.py`; add it to the `from db_adapter.factory import (...)` block.

**Graceful degradation**: If `_get_table_row_counts()` fails (returns empty dict), the connect output is unchanged -- counts are simply not shown. No error printed (the connection itself succeeded).

**Placement in output**: Row counts appear after schema validation line and before the profile switch notice:

```
v Connected to profile: local
  Schema validation: PASSED

         Table Data
┌────────────┬───────┐
│ ...        │       │
└────────────┴───────┘

  Switched from rds to local
```

Files to modify:
- `cli/__init__.py` -- update `_async_connect()` to call helpers after success

Validate: `DB_PROFILE=full db-adapter connect` shows table counts. `DB_PROFILE=drift db-adapter connect` (failed validation) does NOT show counts.

---

### 4. Add Row Counts to `status` Command

**What**: Make `status` async and add table row counts to its output.

**Why**: `status` is the "what's my current state" command. Showing row counts completes the picture without needing to run a separate query.

**Approach**:

Currently `cmd_status` is sync (local-only). To add DB queries:

1. Create `_async_status(args)` async handler
2. Change `cmd_status` to call `asyncio.run(_async_status(args))`
3. In `_async_status`, after the existing status table, resolve profile URL and call `_get_table_row_counts()`

```python
def cmd_status(args: argparse.Namespace) -> int:
    return asyncio.run(_async_status(args))

async def _async_status(args: argparse.Namespace) -> int:
    # ... existing local-only logic (profile, config, status table) ...

    # Add row counts if profile is available
    if profile and config and profile in config.profiles:
        url = resolve_url(config.profiles[profile])
        counts = await _get_table_row_counts(url)
        if counts:
            console.print()
            _print_table_counts(counts)

    return 0
```

**Graceful degradation**: If the DB is unreachable (e.g., VPN down, Docker stopped), `_get_table_row_counts()` returns an empty dict and the status output is the same as today -- just the local connection status table without counts. No error, no crash. This preserves the "status always returns 0" contract.

**Import of `resolve_url`**: `resolve_url` is not currently imported in `cli/__init__.py`; add it to the `from db_adapter.factory import (...)` block.

Files to modify:
- `cli/__init__.py` -- refactor `cmd_status` to async, add row counts

Validate: `db-adapter status` shows counts when DB is reachable. Shows just the status table (no error) when DB is unreachable.

---

### 5. Update Documentation

**What**: Update CLAUDE.md, README.md to reflect the new output format for `connect` and `status`.

**Why**: Documentation must match actual behavior. The CLI Reference sections show example outputs that will change.

**Approach**:

- Update CLAUDE.md CLI Commands section: note that `connect` and `status` now show table row counts
- Update README.md: update `status` comment from "Show current profile" to reflect that it now queries for counts (with graceful degradation)
- Note: `status` is no longer "reads only local files" -- update help text in argparse too
- Update `cmd_status` function docstring ("Reads only local files... no database calls") to reflect async DB query behavior
- Update section comment ("cmd_status, cmd_profiles read local files only") to reflect that `cmd_status` now makes DB calls
- Update module docstring (`status - Show current connection status`) to reflect that status now queries the database for row counts

Files to modify:
- `CLAUDE.md` -- update CLI command descriptions
- `README.md` -- update CLI Reference section
- `cli/__init__.py` -- update `status` subparser help text, module docstring, `cmd_status` function docstring, and section comment

---

## Proposed Sequence

> Shows dependencies and recommended order. Planning stage will create actual implementation steps.

**Order**: #1 → #2 → #3 → #4 → #5

### #1: Row Count Query Helper

**Depends On**: None

**Rationale**: Foundation -- both `connect` and `status` use this helper. Must exist before either command can be updated.

---

### #2: Display Helper for Row Counts Table

**Depends On**: None

**Rationale**: Rendering logic shared by both commands. Takes a standard `dict[str, int]` input with no code dependency on the query helper. Must exist before integrating into either command.

---

### #3: Add Row Counts to `connect` Command

**Depends On**: #1, #2

**Rationale**: `connect` is the primary entry point and already async. Simpler integration than `status` (no sync-to-async refactor needed).

---

### #4: Add Row Counts to `status` Command

**Depends On**: #1, #2

**Rationale**: Requires making `status` async (currently sync/local-only). More involved change than `connect`. Can be done in parallel with #3 but sequentially is safer.

---

### #5: Update Documentation

**Depends On**: #3, #4

**Rationale**: Documentation should reflect the final state after both commands are updated.

---

## Success Criteria

- [ ] `db-adapter connect` shows a "Table Data" table with row counts for all tables after successful connection
- [ ] `db-adapter connect` does NOT show counts when connection or validation fails
- [ ] `db-adapter status` shows a "Table Data" table with row counts when DB is reachable
- [ ] `db-adapter status` shows just the connection status table (no error) when DB is unreachable
- [ ] `db-adapter status` still returns 0 in all cases (informational command)
- [ ] Row counts table is sorted alphabetically by table name
- [ ] All existing tests pass (no regressions)
- [ ] New tests added for row count helper and display integration

---

## Implementation Options

### Option A: Raw psycopg AsyncConnection (Recommended)

Open a raw `psycopg.AsyncConnection` to query `information_schema.tables` for table names, then run `SELECT COUNT(*)` on each table using the same connection. Uses `sql.Identifier` for safe table name quoting.

**Pros**:
- Lightweight -- single connection for both discovery and counting
- No dependency on SchemaIntrospector private methods (`_get_tables()`, `_conn`)
- psycopg cursor supports `fetchone()` for SELECT queries
- Same driver the introspector uses internally

**Cons**:
- Opens a separate connection from the adapter (psycopg vs SQLAlchemy/asyncpg)
- Replicates the table discovery query from SchemaIntrospector (minor duplication)

### Option B: Adapter-Based Counts

Use `get_adapter()` to create an `AsyncPostgresAdapter`, then call `adapter.select(table, "COUNT(*)")` for each table.

**Pros**:
- Uses the same adapter the user would use for CRUD
- Consistent connection pooling

**Cons**:
- `select()` returns `list[dict]` -- overhead for a simple count
- Need to create and close a full adapter just for counts
- Table discovery still needs introspector or a raw query

### Recommendation

Option A because: lighter-weight, single connection for both discovery and counting, avoids coupling to SchemaIntrospector private methods. The raw psycopg connection is perfect for this read-only diagnostic query.

---

## Files to Modify

| File | Change | Complexity |
|------|--------|------------|
| `cli/__init__.py` | Modify -- add `_get_table_row_counts()`, `_print_table_counts()`, update `_async_connect()`, refactor `cmd_status` to async | Med |
| `CLAUDE.md` | Modify -- update CLI command descriptions | Low |
| `README.md` | Modify -- update CLI Reference section | Low |

---

## Testing Strategy

**Unit Tests** (in `test_lib_extraction_cli.py`):
- `_get_table_row_counts()` with mock connection returning table list and counts
- `_get_table_row_counts()` with connection failure returning empty dict
- `_print_table_counts()` with populated dict renders table
- `_print_table_counts()` with empty dict renders nothing
- `_async_connect()` success path includes row counts call
- `_async_connect()` failure path does not call row counts
- `_async_status()` with reachable DB includes row counts
- `_async_status()` with unreachable DB returns 0 without error

**Live Integration Tests** (in `test_live_integration.py`):
- `db-adapter connect` against test DB shows row counts table
- `db-adapter status` against test DB shows row counts table

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `SELECT COUNT(*)` slow on large tables | LOW | LOW | Acceptable for dev tooling; typical databases have < 20 tables with < 1M rows |
| Status command now requires DB access | MED | LOW | Graceful degradation -- shows local status without counts if DB unreachable |
| Second connection to DB during connect | LOW | LOW | psycopg connection is lightweight; connects and disconnects quickly |
| Existing `cmd_status` tests assume sync | MED | LOW | Update tests to handle async wrapper |

---

## Open Questions

None -- all resolved during design:

1. **Which tables to count**: All base tables from `information_schema` where `table_schema = 'public' AND table_type = 'BASE TABLE'`, excluding `EXCLUDED_TABLES_DEFAULT` (`schema_migrations`, `pg_stat_statements`, `spatial_ref_sys`) -- same set the introspector uses. No config needed.
2. **Cross-profile comparison**: Out of scope. Just show current profile's counts.
3. **Status becoming async**: Acceptable trade-off for data visibility. Graceful degradation preserves the "always returns 0" contract.

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Table discovery method | Raw psycopg query on `information_schema.tables` | Avoids coupling to SchemaIntrospector private methods; same query, independent connection |
| Count query method | `SELECT COUNT(*) FROM "table"` per table (quoted identifier) | Simple, standard, fast for typical databases; safe with reserved words |
| Which tables to count | All tables (minus system exclusions) | Zero config, universally useful |
| Cross-profile comparison | Out of scope | Requires dual-DB connection, fragile, MC-specific feature |
| Status async conversion | Yes -- make status async | Necessary for DB query; graceful degradation when offline |
| Count display placement | After schema validation, before profile switch | Natural reading order: connect -> validate -> data overview -> switch notice |

---

## Next Steps

1. Review this design and confirm approach
2. Run `/review-doc` to check for issues
3. Create implementation plan (`/dev-plan`)
4. Execute implementation (`/dev-execute`)

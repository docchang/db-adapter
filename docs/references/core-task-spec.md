# Core Task Spec

## Milestone Overview
Prove that db-adapter is a fully standalone, async-first Python library with zero Mission Control coupling — installable and importable by any Python 3.12+ project. Core transforms a raw copy of MC sync code into a clean, tested, async library ready for its first consumer.

## Project
db-adapter — [Vision](./db-adapter-vision.md)

## Task Dependency Diagram

```
+-----------------------------+
|  Task: lib-extraction       |
|  ✅ Complete                 |
|  Extract standalone async   |
|  library from MC code       |
+-------------+---------------+
              |
              v
+-----------------------------+
|  Task: release-prep         |
|  Version bump, tag, and     |
|  clean install verification |
+-----------------------------+
```

**Parallel tracks**: None — release-prep depends on lib-extraction being complete.

## Tasks

### Task: lib-extraction
- **Type**: Refactor
- **Validates**: That db-adapter can be extracted into a standalone async-first library with zero MC-specific code, proper package imports, configurable constructors, and a comprehensive test suite
- **Unlocks**: release-prep
- **Status**: Complete (553 tests, 13/13 success criteria met)
- **Success Criteria**:
  - `uv sync` installs without errors
  - `from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter` succeeds
  - Zero imports from `fastmcp`, `creational.common`, `mcp.server.auth`, or `schema.db_models` in `src/`
  - Zero hardcoded MC-specific table names in library code
  - All `DatabaseClient` Protocol methods are `async def`
  - `AsyncPostgresAdapter` uses `create_async_engine` with `asyncpg`
  - `SchemaIntrospector` uses `psycopg.AsyncConnection`
  - `factory.get_adapter()` and `factory.connect_and_validate()` are `async def`
  - JSONB columns configurable via constructor (no class-level constant)
  - Env prefix configurable (no hardcoded `MC_` prefix)
  - `BackupSchema`-driven backup/restore (no hardcoded table names)
  - CLI commands wrap async operations with `asyncio.run()`
  - All tests pass with `uv run pytest`
- **Results**: [core-lib-extraction-results.md](../core-lib-extraction-results.md)

### Task: release-prep
- **Type**: Feature
- **Validates**: That the library is installable from git in a clean environment and tagged for consumption
- **Unlocks**: Integration milestone (MC adoption depends on a tagged, installable release)
- **Success Criteria**:
  - Version bumped to `0.1.1` in both `pyproject.toml` and `src/db_adapter/__init__.py`
  - Git tag `v0.1.1` exists on main branch
  - `uv add git+ssh://git@github.com/docchang/db-adapter.git` succeeds in a clean virtual environment (separate project)
  - `python -c "from db_adapter import AsyncPostgresAdapter, DatabaseClient, get_adapter, connect_and_validate; print('OK')"` succeeds in that clean environment
  - `python -c "from db_adapter import BackupSchema, TableDef, ForeignKey, validate_schema; print('OK')"` succeeds in that clean environment
  - Optional supabase extra installs: `uv add "db-adapter[supabase] @ git+ssh://git@github.com/docchang/db-adapter.git"` succeeds
  - All 553+ tests still pass after version bump

## Execution Order
1. Task: lib-extraction (complete)
2. Task: release-prep (requires lib-extraction)

## Integration Points
- **release-prep → Integration milestone**: The tagged v0.1.1 release is what MC will add as a dependency (`uv add git+ssh://...@v0.1.1`). Without a tag, MC would pin to a commit hash, which is fragile.
- **release-prep → README**: README install URLs already point to `git+ssh://git@github.com/docchang/db-adapter.git` — no changes needed.

## Risk Assessment
| Task | Risk Level | Mitigation |
|------|------------|------------|
| lib-extraction | LOW | Complete — all risks resolved |
| release-prep | LOW | Standard version bump and tag; clean install test catches any packaging issues (missing files in wheel, broken `[project.scripts]` entry) |

## Feedback Loops

### If a Task Fails

**A failed task is valuable information, not wasted effort.**

When a task doesn't meet success criteria:

1. **Document what we learned** — What specifically failed? Why?
2. **Assess impact** — Does this invalidate the milestone approach? Or just this task?
3. **Decide next action**:
   - **Retry with different approach** — Update task design and re-attempt
   - **Pivot the milestone** — Revisit milestone spec with new constraints
   - **Revisit architecture** — If fundamental assumption was wrong
   - **Kill the milestone** — If the capability isn't achievable/valuable

### Checkpoint Questions

After each task, ask:
- Did we learn something that changes our assumptions?
- Should we update subsequent task designs based on this learning?
- Is the milestone still viable and valuable?

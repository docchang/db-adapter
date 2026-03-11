# Project State: db-adapter

> **Last Updated**: 2026-03-10T20:40:55-0700

**db-adapter** is an async, dict-based database adapter library extracted from Mission Control, providing a Protocol-typed CRUD interface over PostgreSQL (and optionally Supabase), with multi-profile config (TOML), schema introspection/validation/fix, data sync between profiles, and backup/restore with FK remapping.

**Current Status**: Core library extraction complete with all post-extraction CLI bugs fixed. 584 unit tests + 120 live integration tests passing (704 total). All CLI commands produce correct, honest output against real databases.

---

## Progress

### Milestone: Core

| ID | Name | Type | Status | Docs |
|-----|------|------|--------|------|
| core-lib-extraction | Library Extraction | refactor | ✅ Complete | `core-lib-extraction-*.md` |
| core-cli-fix | CLI Bug Fixes | issue | ✅ Complete | `core-cli-fix-*.md` |

---

## Key Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-27 | AST + grep dual verification in tests | AST catches structural issues; grep catches codebase-wide duplication |
| 2026-02-27 | Default config path `Path.cwd()` not `Path(__file__).parent` | Library reads config from consumer's working directory |
| 2026-02-27 | `ConnectionResult.schema_valid: bool \| None` | Distinguishes "not validated" from "validation failed" for connection-only mode |
| 2026-02-27 | No adapter caching in `get_adapter()` | Caching adds global mutable state; callers can cache themselves |
| 2026-02-27 | Rename to `AsyncPostgresAdapter` (clean break) | No backward-compatible alias; clean names prevent confusion |
| 2026-02-27 | Add `execute` to `DatabaseClient` Protocol for DDL | Keeps interface clean; avoids exposing SQLAlchemy engine internals |
| 2026-02-27 | Dual-path sync: direct insert vs backup/restore | Direct insert for flat tables; backup/restore handles FK remapping |
| 2026-03-10 | Use `connect_args` instead of URL param for timeout | asyncpg does not recognize `connect_timeout` as a DSN query parameter |
| 2026-03-10 | Config-driven CLI with CLI override pattern | CLI commands read `DatabaseConfig` fields; `--schema-file` flag overrides config |
| 2026-03-10 | Subprocess isolation for import ordering tests | `importlib.reload()` breaks exception class identity across modules |

---

## What's Next

**Recommended Next Steps**:
1. Proceed to backup CLI task (see `docs/core-backup-cli-design.md`)
2. Migrate Mission Control to depend on db-adapter as an external package
3. Implement connection pooling configuration via constructor parameters

**System Status**: ✅ **CLI Bugs Fixed**
- 584 unit tests + 120 live integration tests passing (704 total)
- All 9 post-extraction bugs fixed
- All CLI commands config-driven with correct output
- Zero xfail markers remaining

---

## Latest Health Check

### 2026-03-10 - Core-Cli-Fix Finalization
**Status**: ✅ On Track

**Context**:
Task finalization after fixing all 9 post-extraction CLI bugs. Adapter connect_timeout, case sensitivity in schema parser, config-driven connect/validate/fix commands, sync .errors attribute, and importlib.reload() subprocess isolation all resolved.

**Findings**:
- ✅ Alignment: All fixes directly address bugs discovered during live integration testing. CLI commands now produce correct, honest output matching the library's intended behavior.
- ✅ Production readiness: All fixes verified against real PostgreSQL databases (not mocks). 120 live integration tests confirm end-to-end correctness with 0 xfails.
- ✅ Scope: No drift from design doc. All 9 bugs fixed per plan specification. Backup CLI correctly deferred to separate task.
- ✅ Complexity: Fixes are surgical -- minimal changes to existing functions, no new abstractions. 31 new unit tests proportionate to 9 bug fixes.
- ✅ Test coverage: 584 unit tests + 120 live integration tests = 704 total, all passing.

**Challenges**:
- xfail-marked tests contained latent bugs (e.g., dict treated as list) that were only exposed when xfail markers were removed
- Source-level string assertions failed when comments mentioned the same terms as the bug; resolved by targeting specific code patterns
- Connecting to drift DB now correctly fails validation, requiring live integration tests to bypass connect and use lock file or env var directly

**Results**:
- ✅ 9 post-extraction bugs fixed across adapter, CLI, schema parser, and test infrastructure
- ✅ 584 unit tests passing (up from 553, +31 new bug fix tests)
- ✅ 120 live integration tests passing, 0 xfails (down from 16)
- ✅ All CLI commands config-driven with honest output

**Lessons Learned**:
- asyncpg requires `connect_args` for timeout, not URL query parameters
- Three-state fields need explicit `is` checks, not truthiness
- importlib.reload() in tests breaks class identity across modules

**Next**: Proceed to backup CLI task (see `docs/core-backup-cli-design.md`)

# Project State: db-adapter

> **Last Updated**: 2026-03-13T12:25:28-0700

**db-adapter** is an async, dict-based database adapter library extracted from Mission Control, providing a Protocol-typed CRUD interface over PostgreSQL (and optionally Supabase), with multi-profile config (TOML), schema introspection/validation/fix, data sync between profiles, and backup/restore with FK remapping.

**Current Status**: Hardened library with CLI modular split (6 modules), transaction support (Protocol + 3 consumers), restore failure details, FK pre-flight warnings, and sqlparse-based SQL parsing. 828 unit tests passing + 120 live integration tests.

---

## Progress

### Milestone: Core

| ID | Name | Type | Status | Docs |
|-----|------|------|--------|------|
| core-lib-extraction | Library Extraction | refactor | ✅ Complete | `core-lib-extraction-*.md` |
| core-cli-fix | CLI Bug Fixes | issue | ✅ Complete | `core-cli-fix-*.md` |
| core-cli-unify | Unified CLI + Config Defaults | feature | ✅ Complete | `core-cli-unify-*.md` |
| core-cli-counts | Table Row Counts in CLI | feature | ✅ Complete | `core-cli-counts-*.md` |
| core-hardening | Library Hardening | refactor | ✅ Complete | `core-hardening-*.md` |

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
| 2026-03-10 | Always load config at top of async handlers | Both schema_file and column_defs may need fallbacks from the same config object |
| 2026-03-10 | Shared `_resolve_user_id()` helper | Reused by sync, backup, restore, and auto-backup; module-level for testability |
| 2026-03-10 | Backup failure aborts fix | Safety net integrity must be maintained; destructive DDL should not proceed without backup |
| 2026-03-10 | `--validate` as flag on backup, not separate subcommand | Validation is part of backup workflow; keeps subcommand count at 8 |
| 2026-03-13 | `transaction()` on Protocol + `hasattr()` guard | Type checking benefit + runtime backward compatibility; `hasattr()` is transitional until 1.0 |
| 2026-03-13 | Per-instance ContextVar for transaction tracking | Unique `f"_transaction_conn_{id(self)}"` prevents cross-adapter contamination in same asyncio task |
| 2026-03-13 | `_get_transaction_ctx()` over `hasattr()` guard | `AsyncMock` auto-creates attributes, making `hasattr` unreliable; try/except + `__aenter__` check is robust |
| 2026-03-13 | `sqlparse` as core dependency for SQL parsing | Pure Python, zero transitive deps; handles comments, quoted identifiers, schema-qualified names that regex missed |

---

## What's Next

**Recommended Next Steps**:
1. Migrate Mission Control to depend on db-adapter as an external package
2. Implement connection pooling configuration via constructor parameters
3. Add auto-generation of BackupSchema from introspection

**System Status**: ✅ **Library Hardened**
- 828 unit tests passing + 120 live integration tests
- 8 CLI subcommands split across 6 focused modules
- Transaction support on Protocol with 3 consumer wrappers
- Restore failure details with per-row error context
- sqlparse-based SQL parsing replacing regex

---

## Latest Health Check

### 2026-03-13 - Core-Hardening Finalization
**Status**: ✅ On Track

**Context**:
Task finalization after completing Core Hardening -- addressing all 6 technical risks from the examiner audit. 9 implementation steps (Step 0 through Step 8), all 11 success criteria met.

**Findings**:
- ✅ Alignment: All 6 risks from the examiner audit addressed. CLI modularity, transaction support, error visibility, and SQL parsing robustness are library-grade hardening aligned with the goal of making db-adapter a standalone, production-quality library.
- ✅ Production readiness: Transaction support uses real SQLAlchemy `engine.begin()` + contextvars (not mocks). sqlparse is a production SQL tokenizer. FK pre-flight uses real `SchemaIntrospector`. All changes are additive -- existing behavior preserved on success paths.
- ✅ Gap analysis: All 11 success criteria met. No missing edge cases identified. The `hasattr()` guard pattern is documented as transitional (remove at 1.0). Three copies of `_get_transaction_ctx()` could be centralized later but is acceptable for current scope.
- ✅ Scope: No drift from plan. One deviation in Step 5 (`_get_transaction_ctx()` instead of `hasattr()`) was a necessary fix for AsyncMock compatibility, not scope creep.
- ✅ Complexity: Proportionate. 5 new CLI modules are natural domain boundaries (connection, fix, sync, backup, helpers). Transaction support adds one ContextVar per adapter instance. No unnecessary abstractions or over-engineering.
- ✅ Test coverage: 828 unit tests passing (704 original + 124 new). Zero failures. 100% pass rate.

**Challenges**:
- `AsyncMock` auto-creates attributes, breaking `hasattr()` feature detection; resolved with `_get_transaction_ctx()` try/except + `__aenter__` validation pattern
- `validate_backup()` pre-flight check makes certain restore error paths unreachable for structurally invalid data; tests adapted to simulate failures that pass validation but fail during insert

**Results**:
- ✅ CLI split into 6 focused modules with facade re-exports
- ✅ Transaction support on Protocol, implemented in AsyncPostgresAdapter, wrapping restore/fix/sync
- ✅ Restore failure_details with per-row error context and CLI display
- ✅ FK pre-flight warning in CLI sync
- ✅ sqlparse-based SQL parsing replacing regex for 3 functions
- ✅ 828 unit tests passing (124 net new)

**Lessons Learned**:
- Per-instance ContextVar names are essential when multiple adapter instances coexist in the same asyncio task
- PostgreSQL transactional DDL means schema fix rollback genuinely restores dropped tables
- The noop context manager pattern eliminates code duplication for optional transaction support

**Next**: Migrate Mission Control to depend on db-adapter as an external package

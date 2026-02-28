# DB Adapter - Vision

## Vision

A standalone, async-first Python library that provides a clean dict-based CRUD interface over PostgreSQL (and optionally Supabase) with Protocol typing, multi-profile configuration, schema management, and backup/restore. Extracted from Mission Control and designed for wide adoption — any Python project that needs structured database access without ORM ceremony can install it, point it at a database, and start working in minutes.

## Problem Statement

Python projects that want structured database access face a false choice: heavyweight ORMs (SQLAlchemy ORM, Django ORM) that impose model classes, migration frameworks, and steep learning curves — or raw SQL/psycopg that gives no structure at all.

**For whom:** Python developers building applications that need reliable CRUD operations, schema validation, multi-environment database configuration, and backup/restore — without adopting a full ORM.

Specific pain points:
- **No lightweight async CRUD layer exists** that returns plain dicts and works with PostgreSQL out of the box. Most async database libraries are either raw drivers (asyncpg) or full ORMs (SQLAlchemy ORM, Tortoise).
- **Multi-profile database config is DIY** — developers hand-roll environment switching between local, staging, and production databases with env vars and ad-hoc config.
- **Schema validation requires migration frameworks** — checking that a live database matches expectations means adopting Alembic or writing custom introspection scripts.
- **Backup/restore with FK remapping is tedious** — exporting data from one database and importing into another while preserving relational integrity (ID remapping) is custom work every time.

## Core Value Proposition

**Dict in, dict out, async everywhere.** DB Adapter gives you a typed async CRUD interface that works with plain Python dicts — no model classes, no migrations framework, no ORM sessions. Protocol typing means any adapter structurally matches the interface without inheritance.

What sets it apart:
1. **Protocol-typed, not class-based** — `DatabaseClient` is a `typing.Protocol`. Adapters implement it structurally. Your code type-checks without inheriting from anything.
2. **Async-first** — Built on `asyncpg` + SQLAlchemy async engine. No sync/async duality to manage. CLI wraps with `asyncio.run()`.
3. **Batteries included, not required** — Multi-profile TOML config, live schema introspection/validation/fix, cross-profile data sync, and FK-aware backup/restore are all optional layers you adopt when ready.
4. **No lock-in** — Returns plain dicts. No special model classes. Switch adapters (Postgres ↔ Supabase) by changing one line.

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| Installable and importable | `uv add` + `from db_adapter import AsyncPostgresAdapter` works | CI: import test in clean venv |
| Zero MC coupling | No `fastmcp`, `creational.common`, or MC-specific imports remain | `grep -r` across source |
| Async coverage | All adapter, factory, introspector, and backup methods are async | Code review; Protocol signature check |
| First external consumer | Mission Control successfully imports and uses db-adapter as a dependency | MC integration test passes |
| Public usability | A new project can go from install to first query in <5 minutes | README walkthrough test |

## Non-Goals

- **Not an ORM** — No model classes, no automatic migration generation, no relationship mapping. If you want Django ORM or SQLAlchemy ORM, use those.
- **Not a migration framework** — Schema fix repairs drift (missing columns/tables) but does not generate versioned migration files. Use Alembic for that.
- **Not multi-database** — PostgreSQL is the primary target. Supabase support exists because it's Postgres under the hood. No plans for MySQL, SQLite, MongoDB, etc.
- **Not a query builder** — CRUD methods accept table names, column strings, and filter dicts. Complex queries (joins, subqueries, CTEs) should use SQLAlchemy Core or raw SQL directly.
- **Not a connection manager service** — The library manages connection pools within a single process. It does not provide connection pooling as a service (use PgBouncer for that).
- **Sync API** — No sync wrappers. The library is async-only. Scripts use `asyncio.run()`.

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Async-only narrows adoption | MED | MED | Modern Python (3.12+) has mature async; CLI wraps with `asyncio.run()` for scripts; document the pattern clearly |
| Dict-based API lacks type safety for column names | MED | LOW | Tradeoff is intentional (simplicity > safety); consumers can add their own typed wrappers if needed |
| Schema fix (DROP+CREATE) is destructive | LOW | HIGH | Always backup before fix; fix requires explicit `--confirm` flag; single-column drift uses safe ALTER |
| Competing with established libraries (SQLAlchemy, databases, etc.) | MED | MED | Not competing — complementary. DB Adapter sits between raw drivers and full ORMs, a layer most projects DIY anyway |
| Supabase async client API instability | MED | LOW | Supabase adapter is an optional extra; pin dependency version; isolated behind Protocol |
| Extraction leaves subtle MC-coupled assumptions in logic | MED | MED | Systematic design doc identifies every coupling point; validation checks at each extraction step |

## Open Questions

- [ ] Should the library provide a thin sync wrapper (e.g., `SyncPostgresAdapter`) for simple scripts, or stay pure async-only?
- [ ] How should the CLI discover `BackupSchema` at runtime? Options: TOML section in `db.toml`, separate config file, or `--schema` flag pointing to a JSON/TOML definition.
- [ ] Should `validate_schema` support schema.sql file parsing for expected columns, or always require the caller to provide `expected_columns` as a dict?
- [ ] PyPI publication timeline — start with git-based install, but when to publish to PyPI for wider adoption?
- [ ] Should the library support `DATABASE_URL` as default env var (matching Heroku/Railway/Render convention), or require explicit config?

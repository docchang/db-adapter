# DB Adapter - Roadmap

**Vision**: A standalone, async-first Python library providing dict-based CRUD over PostgreSQL with Protocol typing, multi-profile config, schema management, and backup/restore — installable by any Python 3.12+ project.

**Related Documents**:
- [Vision](./reference/db-adapter-vision.md)
- [Architecture](./db-adapter-architecture.md)

**Strategic Approach**: Extract and decouple from MC → Async conversion + testing → First consumer validates API → PyPI publication for wider adoption

---

## Milestone Progression

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         MILESTONE PROGRESSION                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Core                     Integration              Distribution              │
│  ═════                    ═══════════              ════════════              │
│                                                                              │
│  Standalone Async  ──────▶ First Consumer   ──────▶ Public Adoption         │
│  Library                   Validates API            Ready                    │
│                                                                              │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│  │ Fix imports       │     │ MC installs lib  │     │ PyPI publication │    │
│  │       ↓           │     │       ↓          │     │       ↓          │    │
│  │ Remove MC coupling│     │ MC removes copied│     │ DATABASE_URL     │    │
│  │       ↓           │     │ code             │     │ convention       │    │
│  │ Consolidate models│     │       ↓          │     │       ↓          │    │
│  │       ↓           │     │ CLI unified      │     │ Batch operations │    │
│  │ Convert to async  │     │       ↓          │     │       ↓          │    │
│  │       ↓           │     │ End-to-end tests │     │ Transaction ctx  │    │
│  │ Test suite        │     │                  │     │                  │    │
│  └──────────────────┘     └──────────────────┘     └──────────────────┘    │
│                                                                              │
│  OUTCOME:                  OUTCOME:                 OUTCOME:                 │
│  • Library installable     • API validated by       • Any project installs   │
│  • Zero MC coupling          real consumer            via pip/uv             │
│  • All layers async        • MC runs on lib         • <5 min to first query │
│  • Test suite passing      • Unified CLI            • Advanced features      │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Core

**[Detailed Plan](./core-milestone-spec.md)**

**Status**: Planning

### Goal

Extract db-adapter into a fully standalone, async-first library with zero Mission Control coupling. This comes first because nothing else matters if the library can't be installed and imported independently. The current codebase is a direct sync copy of MC code with broken imports, duplicate models, hardcoded constants, and MC-specific logic throughout — Core transforms it into a clean, tested, async library that any Python project can depend on.

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                      CORE MILESTONE                                   │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  What Changes (Current → Target):                                     │
│                                                                       │
│  Imports:  from adapters import ...  →  from db_adapter.adapters ...  │
│  Models:   config/models.py DUPLICATE →  consolidated (config + schema)│
│  Adapters: sync Engine + connect()   →  async AsyncEngine + connect() │
│  Protocol: def select()              →  async def select()            │
│  Factory:  MC_DB_PROFILE, Settings   →  configurable env_prefix       │
│  Schema:   MC db_models import       →  caller-provided expected cols │
│  Fix:      COLUMN_DEFINITIONS dict   →  caller-provided col defs      │
│  Sync:     hardcoded 3 tables        →  caller-declared table list    │
│  Backup:   hardcoded table names     →  BackupSchema-driven           │
│  Introspect: psycopg.connect()      →  psycopg.AsyncConnection       │
│  CLI:      sync commands             →  asyncio.run() wrappers        │
│  Tests:    0% coverage               →  all layers tested             │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │            Target: Standalone Async Library                   │     │
│  │                                                               │     │
│  │  db_adapter/                                                  │     │
│  │  ├── adapters/  AsyncPostgresAdapter, AsyncSupabaseAdapter   │     │
│  │  ├── config/    TOML loader, DatabaseProfile, DatabaseConfig  │     │
│  │  ├── factory.py async get_adapter(), connect_and_validate()  │     │
│  │  ├── schema/    async introspector, comparator, fix, sync    │     │
│  │  ├── backup/    BackupSchema-driven backup/restore           │     │
│  │  └── cli/       asyncio.run() wrappers for all commands      │     │
│  │                                                               │     │
│  │  Zero imports from: fastmcp, creational.common, mcp.*        │     │
│  │  Zero hardcoded: table names, column defs, JSONB columns     │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### What Gets Built

**Phase 1: Foundation Cleanup**
- Fix all bare imports to `db_adapter.*` package imports throughout codebase
- Fix `adapters/__init__.py` import bug (references `postgres_adapter` instead of `postgres`)
- Consolidate duplicate models: config models → `config/models.py`, schema/introspection models → `schema/models.py`
- Remove MC-specific `Settings` class and `SharedSettings` import from `config/loader.py`
- Remove MC-specific functions from factory: `get_dev_user_id()`, `get_user_id_from_ctx()`, `AuthenticationError`, `cleanup_*` helpers
- Make env var prefix configurable (default `DB_PROFILE` / `DATABASE_URL`)

**Phase 2: Generalization**
- `AsyncPostgresAdapter`: JSONB columns as constructor parameter, rename engine factory
- `comparator.py`: Accept `expected_columns` as parameter (remove MC `db_models` import)
- `fix.py`: Remove hardcoded `COLUMN_DEFINITIONS`; accept column definitions from caller or schema.sql path
- `sync.py`: Replace hardcoded table names with caller-declared table list and slug fields
- `backup_restore.py`: Drive all backup/restore logic from `BackupSchema` (remove hardcoded `projects/milestones/tasks`)
- `introspector.py`: Make `EXCLUDED_TABLES` configurable via constructor
- `factory.py`: Remove `MC_DATABASE_URL` hardcoding; configurable env prefix

**Phase 3: Async Conversion**
- `DatabaseClient` Protocol: all methods become `async def`
- `AsyncPostgresAdapter`: `create_async_engine` with `postgresql+asyncpg://` URLs, `async with engine.connect()`
- `AsyncSupabaseAdapter`: `acreate_client()`, async CRUD methods
- `SchemaIntrospector`: `psycopg.AsyncConnection`, `async with` context manager (`__aenter__`/`__aexit__`)
- `factory.py`: `async connect_and_validate()`, `async get_adapter()`
- `fix.py`: Async plan generation and apply
- `sync.py`: Async compare and sync operations
- `backup_restore.py`: `async backup_database()`, `async restore_database()`
- `cli/__init__.py`: Wrap all commands with `asyncio.run()`

**Phase 4: Test Suite**
- Adapter unit tests (mock database, verify SQL generation and JSONB handling)
- Config loader tests (TOML parsing, profile resolution, password placeholder substitution)
- Factory tests (profile lock file, env var resolution, adapter caching)
- Schema comparator tests (pure logic — missing tables, missing columns, extra tables)
- Introspector tests (mock psycopg connection, verify query structure)
- Backup model tests (BackupSchema, TableDef, FK definitions)
- Import test (verify `from db_adapter import AsyncPostgresAdapter` works in clean environment)
- Zero MC coupling test (`grep -r` for `fastmcp`, `creational.common`, `mcp.server`)

### Success Metrics

**Library Independence**:
- **Installable**: `uv add git+ssh://...` succeeds in a clean venv
- **Importable**: `from db_adapter import AsyncPostgresAdapter` works
- **Zero MC coupling**: `grep -r "fastmcp\|creational\.common\|mcp\.server" src/` returns no matches

**Async Coverage**:
- **Protocol**: All 5 `DatabaseClient` methods are `async def`
- **Adapters**: Both adapters use async engines/clients
- **Schema tools**: Introspector uses `psycopg.AsyncConnection`
- **Factory**: `get_adapter()` and `connect_and_validate()` are async

**Code Quality**:
- **No duplicate models**: Each model defined in exactly one location
- **No hardcoded constants**: JSONB columns, table names, column definitions, env prefix all configurable
- **Tests passing**: All unit tests pass in CI

### Key Outcomes

- Library installable and importable without Mission Control
- All adapters, factory, schema tools, and backup/restore are async
- Configurable constructors replace all hardcoded MC-specific constants
- Caller-provided schemas replace all MC-specific imports
- Test suite validates all layers
- Ready for first consumer integration

### Why Extract-First, Then Async?

- **Clean foundation before complexity**: Fixing imports and removing MC coupling first means the async conversion operates on clean, understandable code — not code tangled with external dependencies
- **Testable at each phase**: After Phase 1-2, the library can be tested (still sync but standalone). After Phase 3, async tests confirm the conversion. Incremental verification reduces risk.
- **Async is the identity**: The vision says "async-first" — shipping a sync version would create an API that immediately breaks when async lands. Better to do it all in Core and ship the right API from day one.

---

## Integration

**[Detailed Plan](./integration-milestone-spec.md)**

**Status**: Planning

### Goal

Validate the db-adapter API with its first real consumer: Mission Control. Core proves the library works in isolation — Integration proves it works when a real application depends on it. This milestone catches API design issues, missing edge cases, and ergonomic problems that only surface during real adoption. It also unifies the CLI (merging backup commands) and establishes the pattern for how any project adopts db-adapter.

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                    INTEGRATION MILESTONE                              │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────────────────────────┐                            │
│  │          Mission Control              │                            │
│  │                                       │                            │
│  │  schema/db_models.py (stays in MC)    │                            │
│  │  ├── get_all_expected_columns()       │                            │
│  │  └── MC_BACKUP_SCHEMA (BackupSchema)  │                            │
│  │                                       │                            │
│  │  tools/crud.py                        │                            │
│  │  ├── from db_adapter import get_adapter│                           │
│  │  └── adapter = await get_adapter()    │                            │
│  │                                       │                            │
│  │  Removed:                             │                            │
│  │  ├── core/adapters/ (deleted)         │                            │
│  │  ├── core/schema/ (except db_models)  │                            │
│  │  └── core/backup/ (deleted)           │                            │
│  └──────────────────┬───────────────────┘                            │
│                     │ uv add db-adapter                               │
│                     ▼                                                 │
│  ┌──────────────────────────────────────┐                            │
│  │          db-adapter (library)         │                            │
│  │                                       │                            │
│  │  from db_adapter import               │                            │
│  │    AsyncPostgresAdapter,              │                            │
│  │    get_adapter,                       │                            │
│  │    connect_and_validate,              │                            │
│  │    validate_schema,                   │                            │
│  │    SchemaIntrospector,                │                            │
│  │    BackupSchema, backup_database,     │                            │
│  │    restore_database                   │                            │
│  └──────────────────────────────────────┘                            │
│                                                                       │
│  CLI Unified:                                                         │
│  db-adapter connect|status|profiles|validate|fix|sync|backup|restore │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### What Gets Built

**Phase 1: MC Adoption**
- MC adds db-adapter as a dependency (`uv add git+ssh://...`)
- MC converts import statements: `from adapters import ...` → `from db_adapter import ...`
- MC defines `MC_BACKUP_SCHEMA` using `BackupSchema` / `TableDef` / `ForeignKey`
- MC passes `expected_columns` to `validate_schema()` instead of library importing `db_models`
- MC sets `env_prefix="MC"` for `MC_DB_PROFILE` / `MC_DATABASE_URL` resolution

**Phase 2: MC Code Removal**
- Remove copied adapter code from MC (`core/adapters/`)
- Remove copied schema tools from MC (`core/schema/` except `db_models.py`)
- Remove copied backup code from MC (`core/backup/`)
- Remove copied config loading from MC (use lib's `load_db_config`)
- Verify MC test suite passes entirely on db-adapter

**Phase 3: CLI Unification**
- Merge backup CLI commands into main `db-adapter` CLI entry point
- `db-adapter backup` / `db-adapter restore` / `db-adapter validate-backup`
- Remove separate `backup.py` CLI entry point
- CLI discovers `BackupSchema` via `db.toml` section or `--schema` flag

**Phase 4: API Refinement**
- Address any API friction discovered during MC adoption
- Improve error messages based on real integration scenarios
- Add integration tests that exercise the full library through MC's usage patterns
- Document adoption pattern as a reference for future consumers

### Success Metrics

**Consumer Adoption**:
- **MC dependency**: `uv add db-adapter` in MC's pyproject.toml
- **MC tests pass**: Full MC test suite runs on db-adapter (no copied code)
- **Code reduction**: MC removes 1000+ lines of copied adapter/schema/backup code

**API Validation**:
- **No breaking changes needed**: MC adoption doesn't require API changes to Core (or if it does, changes are minor and documented)
- **Ergonomic**: MC migration requires changing imports + providing schemas — no deep refactoring

**CLI**:
- **Unified**: Single `db-adapter` entry point for all commands (schema + backup)
- **Backup integration**: `db-adapter backup` / `db-adapter restore` work end-to-end

### Key Outcomes

- Mission Control running on db-adapter as a dependency
- Copied adapter/schema/backup code removed from MC
- API validated by real-world consumer with production data
- Unified CLI with all commands under one entry point
- Adoption pattern documented for future consumers

### Why Integration Before Distribution?

- **API validation**: Real consumer surfaces design issues that isolated testing misses. Better to fix API before publishing to PyPI.
- **Prove the value**: If MC can adopt db-adapter cleanly and remove 1000+ lines of copied code, the library delivers real value — not just theoretical benefit.
- **Adoption pattern**: MC integration establishes the reference pattern (how to provide schemas, declare BackupSchema, set env prefix) that documentation will describe for new users.

---

## Distribution

**[Detailed Plan](./distribution-milestone-spec.md)**

**Status**: Planning

### Goal

Make db-adapter publicly available and easy to adopt by any Python project. Core built the library, Integration validated it with a real consumer — Distribution makes it accessible beyond internal projects. This includes PyPI publication, zero-config `DATABASE_URL` support for platform convention, and feature additions (batch operations, transaction support) that emerged from Integration learnings.

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                    DISTRIBUTION MILESTONE                             │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │Mission Control│  │Video Professor│  │ New Project  │              │
│  │(existing)     │  │(new consumer) │  │(any Python)  │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                  │                  │                       │
│         │ uv add           │ pip install      │ pip install           │
│         │ db-adapter       │ db-adapter       │ db-adapter            │
│         │                  │                  │                       │
│         ▼                  ▼                  ▼                       │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                db-adapter (on PyPI)                        │       │
│  │                                                            │       │
│  │  pip install db-adapter                                    │       │
│  │  pip install db-adapter[supabase]                          │       │
│  │                                                            │       │
│  │  New features:                                             │       │
│  │  ├── DATABASE_URL zero-config fallback                    │       │
│  │  ├── insert_many() / update_many() batch operations       │       │
│  │  └── async with adapter.transaction(): context manager    │       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### What Gets Built

**Phase 1: PyPI Publication**
- Configure `pyproject.toml` for PyPI (classifiers, license, project URLs)
- Set up CI pipeline for automated testing and publishing
- Publish initial release to PyPI
- Update install docs: `pip install db-adapter` / `uv add db-adapter`

**Phase 2: Zero-Config Improvements**
- Support bare `DATABASE_URL` env var (Heroku/Railway/Render convention) as default fallback
- Direct mode: `AsyncPostgresAdapter(database_url)` with no config file needed
- Quickstart documentation: install → first query in <5 minutes

**Phase 3: Feature Additions**
- `insert_many(table, records) -> list[dict]` — Bulk inserts via `executemany()`
- `update_many(table, records, key_columns) -> list[dict]` — Bulk updates by key
- `async with adapter.transaction():` — Explicit transaction context manager for multi-statement atomicity
- Pool observability: `adapter.pool_status()` returning structured pool metrics

### Success Metrics

**Public Availability**:
- **PyPI**: `pip install db-adapter` succeeds
- **Quickstart**: New project goes from install to first query in <5 minutes (timed README walkthrough test)

**Adoption**:
- **Second consumer**: At least one project beyond MC uses db-adapter
- **API stability**: No breaking changes needed after PyPI publication

### Key Outcomes

- db-adapter available on PyPI for any Python project
- Zero-config path for simple projects (just `DATABASE_URL`)
- Batch and transaction features for production workloads
- Comprehensive quickstart documentation

### Why Distribution Last?

- **API must be stable**: Publishing to PyPI means the API is public. Breaking changes after publication are costly. Core + Integration ensure the API is right before publishing.
- **Real validation first**: PyPI publication without a real consumer is vanity. MC integration proves the library works before asking others to adopt it.
- **Features informed by usage**: Batch operations and transaction support are features that real consumers will need — but their exact API should be informed by Integration learnings, not guessed upfront.

---

## Strategic Decisions

### Why This Milestone Order?

**Core First**:
- Nothing else matters if the library can't be installed independently. Every subsequent milestone depends on a working, standalone, async library.
- Doing decoupling + async in one milestone avoids shipping a sync API that immediately gets replaced. The public API should be right from the start.
- Test suite in Core catches regressions before any consumer depends on the library.

**Integration Second**:
- Real-world validation is the highest-value activity after the library works. A library that only passes unit tests but fails during actual adoption is incomplete.
- MC is the ideal first consumer — it's the source of the extracted code, so adoption should be the smoothest possible case. If MC can't adopt cleanly, no one can.
- Integration feedback may require API adjustments. Better to discover this before PyPI publication locks the public API.

**Distribution Third**:
- PyPI publication is a one-way door for API stability. Rushing to publish before real validation would lock in mistakes.
- Feature additions (batch, transactions) are informed by Integration learnings — what consumers actually need, not what we guess they'll need.
- Documentation quality matters more for public release — Integration gives us real examples to write from.

---

## Success Criteria

### Core
- [ ] `uv add git+ssh://...` succeeds in clean venv
- [ ] `from db_adapter import AsyncPostgresAdapter` works
- [ ] `grep -r "fastmcp\|creational\.common\|mcp\.server" src/` returns zero matches
- [ ] All `DatabaseClient` Protocol methods are `async def`
- [ ] Both adapters use async engines/clients
- [ ] All unit tests pass
- [ ] No duplicate model definitions

### Integration
- [ ] MC's `pyproject.toml` lists db-adapter as dependency
- [ ] MC test suite passes entirely on db-adapter (no copied code)
- [ ] Copied adapter/schema/backup code removed from MC
- [ ] Unified CLI: `db-adapter backup` / `db-adapter restore` work end-to-end
- [ ] Adoption pattern documented

### Distribution
- [ ] `pip install db-adapter` succeeds from PyPI
- [ ] New project: install to first query in <5 minutes
- [ ] At least one consumer beyond MC
- [ ] Batch operations and transaction support available

### Long-Term
- [ ] Stable public API with semantic versioning
- [ ] Multiple production consumers
- [ ] Community contributions or feature requests from external users
- [ ] Library recognized as a lightweight alternative to full ORMs

---

## Next Steps

**Current Status**: Vision and Architecture complete, ready to start Core milestone.

**Next Action**: Create detailed Core milestone spec, then break into atomic tasks for implementation.

**Detailed Plans** (to be created):
- [Core Milestone Spec](./core-milestone-spec.md)
- [Integration Milestone Spec](./integration-milestone-spec.md)
- [Distribution Milestone Spec](./distribution-milestone-spec.md)

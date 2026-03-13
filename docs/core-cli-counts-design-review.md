# Review: core-cli-counts Design

| Field | Value |
|-------|-------|
| **Document** | docs/core-cli-counts-design.md |
| **Type** | Task Design |
| **Created** | 2026-03-10T23:16:13-0700 |

---

## Item Summary

| # | Item | R1 | R2 | R3 |
|---|------|----|-----|----|
| 1 | Row Count Query Helper | 1 HIGH 2 LOW | 1 HIGH | ✅ |
| 2 | Display Helper for Row Counts Table | ✅ | ✅ | ✅ |
| 3 | Add Row Counts to `connect` Command | 1 HIGH 1 MED | ✅ | ✅ |
| 4 | Add Row Counts to `status` Command | 1 LOW | ✅ | ✅ |
| 5 | Update Documentation | 1 MED | 1 LOW | 1 LOW |

> `...` = In Progress

---

## Item Details

### Item 1: Row Count Query Helper
**R1** (2026-03-10T23:16:13-0700, review-doc-run):
- [HIGH] `SchemaIntrospector` has no public method to execute arbitrary SQL. COUNT queries would require accessing private `_conn` or opening a separate raw `psycopg.AsyncConnection`. Design does not address this gap. (Elevated from MED -- corroborated by holistic Soundness + Contradictions) -> Clarify the approach: either (a) open a raw `psycopg.AsyncConnection` directly in the helper (bypassing SchemaIntrospector for counts), (b) use `get_column_names().keys()` for table discovery and a raw connection for counts, or (c) explicitly note that `_conn` will be accessed as an internal implementation detail.
- [LOW] `_get_tables()` is a private method but referenced as if part of public API. Constraints forbid modifying SchemaIntrospector public API, implying awareness of public/private boundary. -> Acknowledge that `_get_tables()` is private and clarify whether the helper will call it directly, use `get_column_names().keys()`, or replicate the query.
- [LOW] Helper will need `SchemaIntrospector` and `resolve_url` imported into `cli/__init__.py` (neither currently imported). Design does not mention these new imports. -> Add a note that new imports for `SchemaIntrospector` and `resolve_url` will be needed in `cli/__init__.py`.
**R2** (2026-03-11T11:28:56-0700, review-doc-run):
- [HIGH] Pseudocode says "same query as introspector" but omits two filters the introspector applies: (a) `table_type = 'BASE TABLE'` (excludes views), and (b) `EXCLUDED_TABLES_DEFAULT` filtering (`schema_migrations`, `pg_stat_statements`, `spatial_ref_sys`). Without these, the helper would count views and system tables. Decisions Log says "minus system exclusions" but the Approach section does not specify this. (Elevated from MED -- corroborated by holistic Contradictions) -> Add to the Approach section that the helper must: (1) include `AND table_type = 'BASE TABLE'` in the query, and (2) exclude the same system tables as `SchemaIntrospector.EXCLUDED_TABLES_DEFAULT`.
**R3** (2026-03-11T11:36:00-0700, review-doc-run): Sound

### Item 2: Display Helper for Row Counts Table
**R1** (2026-03-10T23:16:13-0700, review-doc-run): Sound
**R2** (2026-03-11T11:28:56-0700, review-doc-run): Sound
**R3** (2026-03-11T11:36:00-0700, review-doc-run): Sound

### Item 3: Add Row Counts to `connect` Command
**R1** (2026-03-10T23:16:13-0700, review-doc-run):
- [HIGH] `resolve_url` is not currently imported in `cli/__init__.py`. Design lists only "update `_async_connect()`" under Files to modify but does not mention the required new import. (Elevated from MED -- corroborated by holistic Soundness + Items 1, 4) -> Add a note that `resolve_url` must be added to the `from db_adapter.factory import (...)` block in `cli/__init__.py`.
- [MED] `config` can be `None` in `_async_connect()` (line 283, when `db.toml` is missing). Connection can still succeed in connect-only mode, so the success path is reachable with `config = None`. The snippet `config.profiles[result.profile_name]` would raise `AttributeError`. -> Add a null guard: row counts should only be attempted when `config is not None` and `result.profile_name is not None`. Note this edge case explicitly.
**R2** (2026-03-11T11:28:56-0700, review-doc-run): Sound
**R3** (2026-03-11T11:36:00-0700, review-doc-run): Sound

### Item 4: Add Row Counts to `status` Command
**R1** (2026-03-10T23:16:13-0700, review-doc-run):
- [LOW] Design notes "`resolve_url` -- Already imported? Need to verify. If not, add import." Verification confirms it is not imported. Should be a definitive statement, not an open question. -> Change to: "`resolve_url` is not currently imported in `cli/__init__.py`; add it to the factory import block."
**R2** (2026-03-11T11:28:56-0700, review-doc-run): Sound
**R3** (2026-03-11T11:36:00-0700, review-doc-run): Sound

### Item 5: Update Documentation
**R1** (2026-03-10T23:16:13-0700, review-doc-run):
- [MED] Item lists updating `cli/__init__.py` "status subparser help text and module docstring" but does not mention the `cmd_status` function docstring (line 962-964: "Reads only local files... no database calls") nor the section comment (line 943: "cmd_status, cmd_profiles read local files only"). Both directly contradict post-change behavior. -> Add `cmd_status` function docstring (line 962-964) and section comment (line 943) to the list of documentation locations to update within `cli/__init__.py`.
**R2** (2026-03-11T11:28:56-0700, review-doc-run):
- [LOW] Approach states "Update README.md: update `status` description from 'no database calls'" but README.md line 285 says `# Show current profile` -- it does not contain "no database calls". That phrase only appears in `cli/__init__.py` line 964. -> Change the README bullet to reference the actual current text: update `status` comment from "Show current profile" to reflect that it now queries for counts with graceful degradation.
**R3** (2026-03-11T11:36:00-0700, review-doc-run):
- [LOW] Module docstring in `cli/__init__.py` (line 23) describes `status` as "Show current connection status" with no mention of DB access or row counts. This is an additional documentation update point not explicitly called out in the approach bullets. -> Add an explicit bullet: "Update module docstring (line 23: `status - Show current connection status`) to reflect that status now queries the database for row counts"

---

## Holistic Summary

| Concern | R1 | R2 | R3 |
|---------|----|-----|----|
| Template Alignment | ✅ | ✅ | ✅ |
| Soundness | 1 MED | ✅ | ✅ |
| Flow & Dependencies | ✅ | ✅ | 1 LOW |
| Contradictions | 1 MED | 1 MED | ✅ |
| Clarity & Terminology | ✅ | ✅ | ✅ |
| Surprises | 1 LOW | ✅ | 1 MED |
| Cross-References | ✅ | ✅ | ✅ |

---

## Holistic Details

**R1** (2026-03-10T23:16:13-0700, review-doc-run):
- **[Soundness]** [MED] Design relies on `SchemaIntrospector._get_tables()` which is a private method, but Constraints prohibit modifying the public API. The design does not specify how to resolve this tension. -> Clarify in Analysis #1 which approach: call `_get_tables()` directly (acceptable for internal CLI code), duplicate the SQL, or use `get_column_names()`.
- **[Contradictions]** [MED] Constraints say "Modifying `SchemaIntrospector` public API" must NOT happen, but Analysis #1 relies on `_get_tables()` (private). Design does not clarify whether it will call the private method or use an alternative. -> Explicitly state the approach for table discovery without modifying the public API.
- **[Surprises]** [LOW] SQL interpolation `SELECT COUNT(*) FROM {table_name}` does not use identifier quoting. Table names with reserved words or special characters would cause SQL errors. -> Note that table names should be quoted with `sql.Identifier` from psycopg or double-quoted.

**R2** (2026-03-11T11:28:56-0700, review-doc-run):
- **[Contradictions]** [MED] Analysis #1 describes querying `information_schema.tables WHERE table_schema = 'public'` with no exclusions, but Open Questions #1 says "minus excluded system tables." The introspector excludes `schema_migrations`, `pg_stat_statements`, `spatial_ref_sys`. (Elevated from LOW -- corroborated by Item 1) -> Add a note in Analysis #1 specifying whether the helper excludes the same tables as `SchemaIntrospector.EXCLUDED_TABLES_DEFAULT` or intentionally shows all tables, and update Open Questions #1 to match.

**R3** (2026-03-11T11:36:00-0700, review-doc-run):
- **[Surprises]** [MED] Analysis #5 references specific source line numbers (line 962-964, line 943) for code that needs updating. These line numbers are brittle and could shift if other changes are made before implementation. -> Remove line number references or replace with content-based descriptions (e.g., "the `cmd_status` docstring that says 'Reads only local files'" and "the section comment containing 'cmd_status, cmd_profiles read local files only'").
- **[Flow & Dependencies]** [LOW] Proposed Sequence #2 lists "Depends On: #1" but `_print_table_counts(counts: dict[str, int])` has no code dependency on `_get_table_row_counts()`. It only depends on a standard `dict[str, int]` input shape. -> Consider changing to "Depends On: None" since the display helper can be built and tested independently. Alternatively, keep as-is if the intent is to signal logical design flow.

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-10T23:22:30-0700 | review-doc-run | Parallel (5 item + 1 holistic) | 2 HIGH 4 MED 4 LOW | Applied (10 of 10) |
| R2 | 2026-03-11T11:28:56-0700 | review-doc-run | Parallel (5 item + 1 holistic) --auto | 1 HIGH 1 MED 1 LOW | Applied (3 of 3) |
| R3 | 2026-03-11T11:36:00-0700 | review-doc-run | Parallel (5 item + 1 holistic) --auto | 1 MED 2 LOW | Applied (3 of 3) |

---

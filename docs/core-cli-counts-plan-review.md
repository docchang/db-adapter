# Review: core-cli-counts Plan

| Field | Value |
|-------|-------|
| **Document** | docs/core-cli-counts-plan.md |
| **Type** | Plan |
| **Created** | 2026-03-11T11:50:22-0700 |

---

## Step Summary

| # | Step | R1 | R2 |
|---|------|----|----|
| 0 | Add resolve_url Import | ✅ | ✅ |
| 1 | Row Count Query Helper | ✅ | ✅ |
| 2 | Display Helper for Row Counts Table | ✅ | ✅ |
| 3 | Integrate Row Counts into Connect Command | ✅ | ✅ |
| 4 | Convert Status to Async and Add Row Counts | 1 MED 1 LOW | ✅ |
| 5 | Update Documentation | 1 LOW | ✅ |
| 6 | Full Test Suite Validation | ✅ | ✅ |

> `...` = In Progress

---

## Step Details

### Step 0: Add resolve_url Import
**R1** (2026-03-11T11:50:22-0700, review-doc-run): Sound
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

### Step 1: Row Count Query Helper
**R1** (2026-03-11T11:50:22-0700, review-doc-run): Sound
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

### Step 2: Display Helper for Row Counts Table
**R1** (2026-03-11T11:50:22-0700, review-doc-run): Sound
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

### Step 3: Integrate Row Counts into Connect Command
**R1** (2026-03-11T11:50:22-0700, review-doc-run): Sound
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

### Step 4: Convert Status to Async and Add Row Counts
**R1** (2026-03-11T11:50:22-0700, review-doc-run):
- [MED] Existing test `test_cmd_status_is_sync` (line 237-241 of `test_lib_extraction_cli.py`) explicitly asserts `"asyncio.run" not in source` for `cmd_status`. This step converts `cmd_status` to use `asyncio.run()`, which will directly break this test. The acceptance criteria says "may need mock updates for async wrapper" which understates the issue -- this test must be inverted or replaced. -> Add an explicit specification bullet: "Update `test_cmd_status_is_sync` in `test_lib_extraction_cli.py` to assert `'asyncio.run' in source` (inverting the current assertion) and rename it to `test_cmd_status_delegates_to_async` or similar."
- [LOW] In the current `cmd_status` code, `config` is assigned inside a `try` block (line 985) with a `FileNotFoundError` except handler. When moving this logic to `_async_status`, the executor needs to ensure `config` is initialized to `None` before the try block so the guard condition works. -> Add a note: "Initialize `config = None` before the try block so the guard condition `config is not None` works when `load_db_config()` raises `FileNotFoundError`."
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

### Step 5: Update Documentation
**R1** (2026-03-11T11:50:22-0700, review-doc-run):
- [LOW] The checklist unconditionally says "Update `status` subparser help text in `build_parser()`" but the specification says to update only "if it says 'local files only' or similar." The actual help text is `"Show current connection status"` which does not match the conditional. -> Align the checklist and specification: make both unconditional -- update help text to mention row counts since behavior is changing.
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

### Step 6: Full Test Suite Validation
**R1** (2026-03-11T11:50:22-0700, review-doc-run): Sound
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

---

## Holistic Summary

| Concern | R1 | R2 |
|---------|----|----|
| Template Alignment | ✅ | ✅ |
| Soundness | ✅ | ✅ |
| Flow & Dependencies | ✅ | ✅ |
| Contradictions | ✅ | ✅ |
| Clarity & Terminology | ✅ | ✅ |
| Surprises | ✅ | ✅ |
| Cross-References | ✅ | ✅ |

---

## Holistic Details

**R1** (2026-03-11T11:50:22-0700, review-doc-run): Sound
**R2** (2026-03-11T16:51:59-0700, review-doc-run): Sound

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-11T11:50:22-0700 | review-doc-run | Parallel (7 item + 1 holistic) --auto | 1 MED 2 LOW | Applied (3 of 3) |
| R2 | 2026-03-11T16:51:59-0700 | review-doc-run | Parallel (7 item + 1 holistic) --auto | 0 | Clean |

---

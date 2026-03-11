# Review: core-cli-fix Plan

| Field | Value |
|-------|-------|
| **Document** | docs/core-cli-fix-plan.md |
| **Type** | Plan |
| **Created** | 2026-03-10T18:28:17-0700 |

---

## Step Summary

| # | Step | R1 | R2 | R3 | R4 | R5 |
|---|------|----|----|-----|----|----|
| 0 | Verify Baseline | 1 MED 1 LOW | 1 LOW | ✅ | ✅ | ✅ |
| 1 | Fix `connect_timeout` in AsyncPostgresAdapter | 1 HIGH 1 MED 1 LOW | 1 MED | 1 LOW | ✅ | ✅ |
| 2 | Fix Case Sensitivity in `_parse_expected_columns` | 2 MED 2 LOW | ✅ | ✅ | ✅ | ✅ |
| 3 | Fix `connect` Command to Wire Config | 2 MED | 1 MED 1 LOW | 1 HIGH | 2 LOW | ✅ |
| 4 | Fix `validate` Command | 1 MED 1 LOW | 1 LOW | 1 MED | 1 MED 1 LOW | 1 MED |
| 5 | Fix Sync `.error` to `.errors` and Make `fix --schema-file` Optional | 2 MED 1 LOW | 1 LOW | 1 MED | 2 LOW | 1 MED |
| 6 | ~~Fix Backup CLI~~ (Moved) | 3 MED | 1 MED 2 LOW | 1 HIGH 1 MED | 1 MED 1 LOW | ✅ |
| 7 | Fix `importlib.reload()` Test Interaction | ✅ | ✅ | ✅ | ✅ | ✅ |
| 8 | Update Live Integration Test Markers | 2 HIGH 3 MED 1 LOW | 1 HIGH 2 MED | 2 HIGH 1 MED | 1 HIGH 1 MED | 1 MED 1 LOW |
| 9 | Final Integration and Documentation | 3 MED 2 LOW | 1 MED | ✅ | 1 MED | 1 LOW |

> `...` = In Progress

---

## Step Details

### Step 0: Verify Baseline
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [MED] Checklist says "Note current xfail count in live integration tests" but Code/Verification commands don't run `test_live_integration.py` -> Remove second checklist item or add live integration test command
- [LOW] Step 0 duplicates Prerequisites baseline verification -> Acceptable; keep as explicit confirmation

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [LOW] Goal says "Confirm all existing tests pass" but command runs only 3 of 13+ test files (affected subset). Intent is clear from context but wording is slightly misleading -> Change Goal to "Confirm affected test files pass before making changes"

**R3** (2026-03-10T18:59:51-0700, review-doc-run): Sound

**R4** (2026-03-10T19:12:48-0700, review-doc-run): Sound

**R5** (2026-03-10T20:01:22-0700, review-doc-run): Sound

### Step 1: Fix `connect_timeout` in AsyncPostgresAdapter
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [HIGH] Test update specification incomplete: says "Update test" but doesn't show how to access `connect_args` from mock call args. Executor needs explicit assertion pattern (e.g., `mock_create.call_args[1].get("connect_args")`) -> Add example assertion structure to Specification
- [MED] Specification says "pass `connect_args` as a default in the `defaults` dict" but doesn't show placement. Code has `defaults` dict at line 57-63 -> Clarify: "`connect_args` should be added to the `defaults` dict alongside `pool_size`, `pool_pre_ping`, etc."
- [LOW] Acceptance criterion "All tests in test_lib_extraction_adapters.py pass" doesn't specify which test classes -> Acceptable; full file scope is clear enough

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [MED] `connect_args` override via `**kwargs` is full replacement (not merge). A caller passing `connect_args={"command_timeout": 10}` would lose `timeout: 5`. The acceptance criterion says "Caller can override `connect_args`" but doesn't clarify full replacement vs merge semantics -> Add clarifying note that `connect_args` override is full replacement (consistent with `{**defaults, **kwargs}`), and document in a code comment

**R3** (2026-03-10T18:59:51-0700, review-doc-run):
- [LOW] Checklist item 3 "Write tests verifying the fix" is ambiguous -- overlaps with item 2 "Update `test_appends_connect_timeout`". Specification only describes updating the existing test, not writing additional new tests. Executor may wonder if additional tests are expected -> Either remove item 3 as redundant with item 2, or specify what additional tests beyond updating `test_appends_connect_timeout` are expected (e.g., a test for `connect_args` override behavior)

**R4** (2026-03-10T19:12:48-0700, review-doc-run): Sound

**R5** (2026-03-10T20:01:22-0700, review-doc-run): Sound

### Step 2: Fix Case Sensitivity in `_parse_expected_columns`
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [MED] Line references say "line where table is stored" and "line where column is added" without specifying actual line numbers (105 and 108) -> Add explicit line numbers: "Line 105: `columns.add(col_name.lower())` and Line 108: `result[table_name.lower()] = columns`"
- [MED] Acceptance criteria require "Mixed case returns all lowercase" but test specification only mentions "uppercase column names" test, not a mixed-case test -> Add mixed-case test to specification
- [LOW] No explicit note that `.lower()` is a no-op on already-lowercase names -> Acceptable; logically obvious
- [LOW] Verification doesn't specify expected test count -> Acceptable; count precision not needed

**R2** (2026-03-10T18:45:15-0700, review-doc-run): Sound

**R3** (2026-03-10T18:59:51-0700, review-doc-run): Sound

**R4** (2026-03-10T19:12:48-0700, review-doc-run): Sound

**R5** (2026-03-10T20:01:22-0700, review-doc-run): Sound

### Step 3: Fix `connect` Command to Wire Config
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [MED] Acceptance criteria says "All existing CLI tests still pass" without specifying which tests -> Clarify: "All tests in `test_lib_extraction_cli.py`"
- [MED] Specification only catches `FileNotFoundError` from `load_db_config()` but doesn't handle `ValidationError` if db.toml is malformed. Could crash instead of degrading gracefully [Elevated from LOW -- holistic overlap: exception handling gap] -> Add: "Catch `Exception` from `load_db_config()` (including `FileNotFoundError` and Pydantic `ValidationError`). Fall back to connect-only in all error cases."

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [MED] Specification describes three-state `schema_valid` handling but does not describe the connection-failure path (`result.success is False`). Current `_async_connect()` gates output on `result.success` first. Executor could omit this branch -> Add explicit item: "Check `result.success` first. If `False`, print connection error and return 1. Only proceed to `schema_valid` checks when `result.success is True`."
- [LOW] Catching bare `Exception` from `load_db_config()` is broader than existing pattern in same file (`cmd_status` catches `FileNotFoundError` specifically). Pragmatically correct but deviates from codebase convention -> Consider catching specific exceptions or adding comment explaining why broad catch is needed [Skipped: style note, spec already covers intent]

**R3** (2026-03-10T18:59:51-0700, review-doc-run):
- [HIGH] Specification points 4 and 6 are internally inconsistent. Point 4 says "Check `result.success` first. If `False`, return 1." Point 6 says "When `schema_valid is False`, show schema report with missing tables/columns." But `connect_and_validate()` returns `success=False` AND `schema_valid=False` when validation fails (factory.py lines 285-291). Point 4 catches `success=False` first and returns 1 before `schema_valid` is ever checked -- making point 6 unreachable. The detailed schema report would be lost on validation failure, a regression from current behavior (lines 165-167 display `result.schema_report.format_report()`). -> Either (a) modify point 4 to also check `result.schema_report` and display it when present before returning 1, or (b) restructure so `schema_valid` checks happen independently of the `success` gate (e.g., check `success` for pure connection failures where `schema_valid is None`, but let `schema_valid is False` be handled by its own branch)

**R4** (2026-03-10T19:12:48-0700, review-doc-run):
- [LOW] Specification item 6 uses ambiguous wording: "When validation passed but `result.success is False`" conflates "validation was performed" with "validation passed." The parenthetical clarifies intent but the sentence initially reads as a contradiction -> Reword to: "When validation was performed but `result.success is False` due to schema drift" [Applied]
- [LOW] Trade-offs section states this follows "the pattern used by `cmd_profiles` and `cmd_status`" but those commands catch only `FileNotFoundError`, whereas this step catches `Exception`. The pattern similarity is in config loading location (inside function body), not exception handling scope -> Clarify that the pattern reference is about loading config inside the function, not about exception handling breadth [Applied]

**R5** (2026-03-10T20:01:22-0700, review-doc-run): Sound

### Step 4: Fix `validate` Command
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [MED] Error handling pattern not explicit for `load_db_config()` and `_parse_expected_columns()`. Unlike Step 3, Step 4 doesn't specify try/except pattern -> Add: "Follow Step 3's error handling pattern: catch exceptions from `load_db_config()` and `_parse_expected_columns()`"
- [LOW] Error message presentation timing unclear relative to config loading -> Acceptable; implementation detail

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [LOW] Specification says `schema_valid is None` "should not occur since we always pass `expected_columns`" but dismisses it rather than adding a defensive handler. Design doc recommends explicit three-state checks -> Add brief `elif result.schema_valid is None:` handler (e.g., print "Validation could not be performed" and return 1)

**R3** (2026-03-10T18:59:51-0700, review-doc-run):
- [MED] Step says "Follow Step 3's error handling pattern" without restating the logic. Step 4 should be self-contained: when `args.schema_file` is provided, use it directly (skip config loading); otherwise, attempt `load_db_config()` and if it fails, fall through to the "no schema source" error. The cross-step reference makes execution depend on reading Step 3 [Recurring from R1 -- prior fix: added "Follow Step 3's error handling pattern" reference; root cause: cross-step reference doesn't make Step 4 self-contained, the actual logic should be restated inline] -> Restate the logic explicitly: "If `args.schema_file` is provided, use it directly (skip config loading). Otherwise, attempt `load_db_config()` -- if it fails or `config.schema_file` is not set, fall through to bullet 3's error."

**R4** (2026-03-10T19:12:48-0700, review-doc-run):
- [MED] Specification bullet 3 condition "config has no `schema_file`" is unreachable. `DatabaseConfig.schema_file` is typed as `str` with default `"schema.sql"` (not `Optional[str]`), so it always has a value after successful `load_db_config()`. The actual "no schema source" scenario is: no `--schema-file` flag AND `load_db_config()` raises an exception. If config loads successfully, `config.schema_file` always exists -> Simplify bullet 3 to: "If no `--schema-file` flag AND `load_db_config()` fails: print error and return 1. If config loads but `_parse_expected_columns(config.schema_file)` raises `FileNotFoundError`: print error referencing the missing file and return 1." [Applied]
- [LOW] Specification bullet 4 uses `validate_only=True` without explaining why. Since this is a contract for the executor, a brief rationale (e.g., "to avoid overwriting the lock file") would prevent misunderstanding -> Add one-line rationale for `validate_only=True` [Applied]

**R5** (2026-03-10T20:01:22-0700, review-doc-run):
- [MED] Missing `result.success` check before the three-state `schema_valid` check. When `connect_and_validate` fails due to a connection error (DB unreachable), it returns `ConnectionResult(success=False, error="...", schema_valid=None)`. The `schema_valid is None` handler would print "Validation could not be performed" instead of the actual connection error from `result.error`. Step 3's specification explicitly handles `result.success` first (bullet 4) -- Step 4 should follow the same pattern -> Add a `result.success` check before the three-state check: if `result.success is False` and `result.schema_report` is available, display schema report; if `result.success is False` with no schema report, print `result.error` and return 1. Then proceed to `schema_valid` three-state check only when `success is True`

### Step 5: Fix Sync `.error` to `.errors` and Make `fix --schema-file` Optional
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [MED] Ambiguous error formatting decision: Trade-offs section describes both `"; ".join()` and `errors[0]` without clear recommendation -> Clarify: recommend `"; ".join(result.errors)` as the default approach
- [MED] Error message format "No schema file: provide --schema-file..." doesn't match message style in Steps 3/4 -> Align message style with Steps 3/4 for consistency
- [LOW] `default=None` for argparse is implicit when `required=False` -> Acceptable; explicit is fine

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [LOW] Spec says "config has no schema_file" as error condition, but `DatabaseConfig.schema_file` always defaults to `"schema.sql"` (str, cannot be None). Condition is unreachable -- the natural path is `_parse_expected_columns("schema.sql")` raising `FileNotFoundError` if file missing -> Clarify to "config's schema_file points to a nonexistent file" or rely on `_parse_expected_columns` raising `FileNotFoundError`

**R3** (2026-03-10T18:59:51-0700, review-doc-run):
- [MED] Config fallback logic in `_async_fix()` conflates two separate error layers: (1) config loading failure (`load_db_config()` raises) and (2) schema file not found (`_parse_expected_columns()` raises `FileNotFoundError`). The existing code at line 251-255 already has a try/except for `_parse_expected_columns`. The cleaner pattern: if `args.schema_file is None`, load config and set `schema_file = config.schema_file`, then let the existing `_parse_expected_columns()` call handle `FileNotFoundError`. The "No schema file available" error should only trigger when `load_db_config()` itself fails, not when the file is missing [Recurring from R2 -- prior fix: clarified "config's schema_file points to a nonexistent file"; root cause: the fallback logic still conflates config loading failure with schema file parsing failure as a single error condition] -> Restructure: fallback only resolves `schema_file` from config. Let existing `_parse_expected_columns()` try/except handle file-not-found naturally. "No schema file available" error only when `load_db_config()` fails AND no `--schema-file` flag.

**R4** (2026-03-10T19:12:48-0700, review-doc-run):
- [LOW] Line numbers 495 and 565 for `.error` references are fragile -- they reference pre-modification state and will shift after Steps 1-4 modify the same file -> Add note that line numbers reference pre-modification baseline, or supplement with surrounding code context (e.g., "the `compare_profiles` failure block" and "the `sync_data` failure block") [Skipped: inherent to plan format; context already provided alongside line numbers]
- [LOW] Catching bare `Exception` from `load_db_config()` is broader than the established `FileNotFoundError`-only pattern used by `cmd_status` and `cmd_profiles` in the same file. The broader catch is pragmatically correct but diverges from codebase convention without explicit rationale -> Add brief comment explaining why `Exception` (rather than `FileNotFoundError`) is needed (e.g., to handle Pydantic `ValidationError` for malformed TOML) [Skipped: already documented in Step 3's trade-offs clarification which establishes the pattern]

**R5** (2026-03-10T20:01:22-0700, review-doc-run):
- [MED] Specification describes resolving `schema_file` from config for `_async_fix()` but only mentions passing it to `_parse_expected_columns()`. The `generate_fix_plan()` call at line 288 of `cli/__init__.py` also uses `args.schema_file` directly and would need updating to use the resolved `schema_file` variable. A builder following the spec literally could miss this second reference -> Add to the specification: "Update both `_parse_expected_columns(args.schema_file)` (line 252) and `generate_fix_plan(..., args.schema_file)` (line 288) to use the resolved `schema_file` variable instead of `args.schema_file`."

### Step 6: Fix Backup CLI as Reference/Template
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [MED] "Do NOT fix the broken function calls" needs explicit explanation that they are intentionally unfixed to demonstrate API shape -> Add clarification that broken calls are intentional documentation
- [MED] Test specification says verify import is present but doesn't specify verification method -> Add: verify via string assertion on module source
- [MED] `NOT_RUNNABLE` constant test criteria vague: should specify which keywords to assert [Elevated from LOW -- holistic overlap: documentation verification] -> Clarify: test should assert docstring contains "reference" AND "BackupSchema" AND "DatabaseClient"

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [MED] Design doc Target State (lines 87-89) says backup CLI target is "Async calls properly wrapped with asyncio.run()" and "Function signatures match actual API" -- contradicts plan's approach of intentionally leaving calls unfixed. Target State was never updated after Option A decision. Could confuse executor -> Update design doc Target State for Backup CLI to say "Documented as reference/template" (design doc issue, not plan issue -- plan correctly follows Analysis/Decisions) [Skipped: outside document scope -- design doc issue]
- [LOW] New tests (docstring assertions, `NOT_RUNNABLE` check) don't specify which test class they belong to. Verification targets `TestBackupCLI` which currently has only 2 tests -> Add: "Add new tests to existing `TestBackupCLI` class"
- [LOW] Specification groups all three functions under "(adapter, schema, user_id)" rationale but `validate_backup()` is sync and only requires `backup_path` + `schema`, not `adapter` or `user_id` -> Clarify that different functions require different parameter subsets [Skipped: minor accuracy, parenthetical is illustrative]

**R3** (2026-03-10T18:59:51-0700, review-doc-run):
- [HIGH] Rationale for leaving broken function calls unfixed is weak. The calls demonstrate *incorrect* parameters (e.g., `project_slugs` does not exist in the real API, missing `adapter`/`schema`/`user_id`). A reference template should show correct usage patterns. Broken code with wrong parameters doesn't serve as useful documentation of the required API [Recurring from R1 -- prior fix: added clarification that broken calls are intentional documentation; root cause: clarification doesn't address fundamental issue that broken code with incorrect parameters isn't a useful reference pattern] [Elevated from MED -- holistic overlap: contradictions concern about backup CLI design target state vs plan approach] -> Either (a) replace broken calls with commented pseudo-code showing correct signatures (e.g., `# result = await backup_database(adapter, schema, user_id=...)`), or (b) add inline comments to each broken call explaining the correct parameters
- [MED] `NOT_RUNNABLE` constant specified without a concrete value, type, or usage guidance. "Or similar marker" adds ambiguity [Elevated from LOW -- holistic overlap: surprises concern about same unspecified constant] -> Specify the exact constant definition, e.g., `NOT_RUNNABLE: bool = True` with a comment

**R4** (2026-03-10T19:12:48-0700, review-doc-run):
- [MED] After replacing broken function calls with commented pseudo-code, `cmd_backup()`, `cmd_restore()`, and `cmd_validate()` become effectively empty functions returning `None`. Since argparse's `set_defaults(func=...)` still wires them, someone invoking the CLI would get silent no-ops. The spec should clarify whether function bodies should include a `print()` explaining the template status plus `return 1`, or a `raise NotImplementedError` -> Add explicit guidance that each function body should include a print statement explaining it is a reference template, followed by `return 1` [Applied]
- [LOW] Test reference "similar to existing test at test_lib_extraction_cli.py:491" is off by one — the test `test_backup_py_imports_from_db_adapter` is at line 490 and belongs to `TestImportStyle`, not `TestBackupCLI` -> Correct to line 490 or reference the test by name only [Applied]

**R5** (2026-03-10T20:01:22-0700, review-doc-run): Sound

### Step 7: Fix `importlib.reload()` Test Interaction
**R1** (2026-03-10T18:34:22-0700, review-doc-run): Sound

**R2** (2026-03-10T18:45:15-0700, review-doc-run): Sound

**R3** (2026-03-10T18:59:51-0700, review-doc-run): Sound

**R4** (2026-03-10T19:12:48-0700, review-doc-run): Sound

**R5** (2026-03-10T20:01:22-0700, review-doc-run): Sound

### Step 8: Update Live Integration Test Markers
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [HIGH] Specification references "TestReloadBug (2 xfail tests, if present)" but this class does not exist in `test_live_integration.py`. The 2-test gap (16 total vs 14 enumerated) is unaccounted for -> Remove TestReloadBug reference. The missing 2 xfails are `test_sync_dry_run_direct` (line 1408) and `test_sync_error_attribute` (line 1422), both Bug #4
- [HIGH] Specification says "14 tests" blocked by Bug #4 but 16 xfails exist total. Enumeration is incomplete -> Revise to "Remove xfail markers from all 16 tests blocked by Bug #4" and list complete breakdown
- [MED] Assertion update guidance is vague: "case mismatch tests should expect lowercase" without specific assertion changes -> Add specific assertion examples per test class
- [MED] "Should use clean assertions" for workaround removal doesn't specify final form (pytest.raises? assert rc==1?) -> Specify: "Use `assert rc == 1` without try/except workaround"
- [MED] Verification command only checks pass/fail counts, not assertion content -> Add spot-check verification for specific test assertions
- [LOW] Not exhaustive listing of all 32 test classes -> Acceptable; only affected classes need listing

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [HIGH] `test_connect_timeout_appended_to_url` (line 794) is NOT xfailed and asserts `assert "connect_timeout" in source`. After Step 1 removes `connect_timeout` from `postgres.py`, this test will fail. Step 8 only mentions removing the xfail from `test_engine_connect_fails` but omits this non-xfail test entirely -> Add instruction to update or remove `test_connect_timeout_appended_to_url` -- either invert assertion to verify `connect_timeout` is absent (confirming fix), or replace with test verifying `connect_args` usage
- [MED] `TestAsyncValidateDirect` Namespace objects (lines 1257, 1268, 1279) use `Namespace(env_prefix="")` but after Step 4 adds `--schema-file`, `_async_validate()` will access `args.schema_file`. Missing attribute will cause `AttributeError` -> Explicitly state all `Namespace` objects for `_async_validate` direct calls must include `schema_file=None`
- [MED] Assertion update guidance still vague for several test classes (e.g., `TestAsyncFixDirect` "should verify fix plan works" without specifying `rc == 0` vs `rc == 1`, `TestAsyncValidateDirect` "should verify real validation") [Recurring from R1 -- prior fix: added some assertion examples; root cause: guidance was added for case-mismatch tests but not for TestAsyncFixDirect and TestAsyncValidateDirect] -> Add specific expected values: `test_fix_preview_full_db_direct` should change `assert rc == 1` to `assert rc == 0`; `test_validate_full_db` should change `assert rc == 1` to `assert rc == 0`

**R3** (2026-03-10T18:59:51-0700, review-doc-run):
- [HIGH] `TestCaseMismatchSeverity` (2 tests at lines 1449, 1483) is not mentioned in the specification. Both tests explicitly assert uppercase column names and false drift from `_parse_expected_columns`. After Step 2's case fix, `test_fix_plan_errors_from_case_mismatch` will fail at `assert "A" in parsed["items"]` (line 1466) and `test_case_mismatch_items_columns_only` will fail at `assert not result.valid` (line 1501). These are hard failures, not vacuously passing tests -> Add `TestCaseMismatchSeverity` to the specification. Both tests need assertion inversions: verify fix plan succeeds (no error, lowercase columns) and `result.valid is True`. Alternatively, remove these tests since they demonstrate a bug that is now fixed.
- [HIGH] `test_fix_preview_drift_db_direct` (line 1352) is not mentioned. Currently asserts `rc == 1` because case mismatch causes `plan.error`. After Step 2's case fix, the fix plan generates correctly and preview mode returns 0. This assertion will fail -> Add `test_fix_preview_drift_db_direct` to the specification, noting it should change from `assert rc == 1` to `assert rc == 0` (fix plan generated successfully in preview mode)
- [MED] `test_case_mismatch_causes_false_drift` (line 657 in `TestParseExpectedColumnsLive`) is not mentioned. After Step 2's case fix, `validate_schema(actual, parsed)` returns `result.valid == True`, making the `if not result.valid:` block at line 669 dead code. Test passes vacuously without testing anything meaningful -> Either update to assert `result.valid is True` (confirming fix works) or remove as a now-irrelevant bug-demonstration test

**R4** (2026-03-10T19:12:48-0700, review-doc-run):
- [HIGH] Assertion guidance for `TestParseExpectedColumnsLive::test_case_mismatch_causes_false_drift` (line 657) is incorrect. The step claims "after case fix, `validate_schema(actual, parsed)` returns `result.valid == True`" but the test's `actual` dict at line 664 only contains `{"items": {"a","b","c","d","e","f","g"}}` (1 table), while `_parse_expected_columns("schema.sql")` returns 3 tables (items, categories, products). `validate_schema` would report categories and products as missing tables, so `result.valid` remains `False`. Asserting `result.valid is True` would produce a failing test [Recurring from R3 -- prior fix: added guidance to assert `result.valid is True`; root cause: guidance assumed actual and parsed dicts have same tables, but actual only has items while parsed has 3 tables] -> Either: (a) update the test's `actual` dict to include all 3 tables, (b) assert `result.missing_columns` is empty (no false column drift) while acknowledging `result.valid is False` due to incomplete `actual`, or (c) remove this test as a now-irrelevant bug demonstration [Applied]
- [MED] `TestAsyncConnectDirect` guidance says "should verify config-driven validation passes with expected_columns" without specifying which assertions change. After Step 3 fixes `_async_connect`, `test_connect_drift_direct` (line 1217) currently asserts `rc == 0` but should assert `rc == 1` (drift now detected). `test_connect_full_direct` (line 1207) should remain `rc == 0`. Executor may miss the `test_connect_drift_direct` change -> Add explicit guidance: "`test_connect_drift_direct` should change from `assert rc == 0` to `assert rc == 1`; `test_connect_full_direct` remains `assert rc == 0`" [Applied]

**R5** (2026-03-10T20:01:22-0700, review-doc-run):
- [MED] `test_connect_profile_switch_notice` (line 494) is not mentioned in the specification. After Step 3's fix, connecting to the drift profile would return exit code 1 (schema validation fails with `validate_on_connect=True`), breaking the current `assert r.returncode == 0` and the `"Switched from" in r.stdout` assertion (profile switch message only prints in the success path). This test will fail but the plan does not instruct the implementer to update it -> Add `test_connect_profile_switch_notice` to the specification. Either update to expect `r.returncode == 1` and verify drift report output, or restructure to switch between two valid profiles
- [LOW] Specification says "connect against drift DB should show drift report" for `TestCLIConnectLive` but does not explicitly state that `test_connect_drift_succeeds` must change its return code from `assert r.returncode == 0` to `assert r.returncode == 1`. The direct-call equivalent (`test_connect_drift_direct`) does specify this change -> Add explicit note: "`test_connect_drift_succeeds` should change from `assert r.returncode == 0` to `assert r.returncode == 1`"

### Step 9: Final Integration and Documentation
**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- [MED] No explicit dependency note that Steps 1-8 must be complete -> Add: "Requires Steps 1-8 completed successfully"
- [MED] "Add `[schema]` section documentation to the config reference" is vague -- README has no explicit "config reference" section -> Clarify: extend the config example in README to include `[schema]` section
- [MED] Documentation update text not specified; executor must infer new descriptions from design -> Add example text for CLI command descriptions
- [LOW] Backup CLI documentation responsibility split between Steps 6 and 9 unclear -> Acceptable; Step 6 handles code, Step 9 handles README/CLAUDE.md
- [LOW] Checklist format purpose unclear -> Acceptable; standard plan format

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- [MED] Specification says "showing `schema_file` and `validate_on_connect` fields" for the TOML example, but the actual TOML key is `file` (not `schema_file`). The loader reads `schema_settings.get("file", ...)`. An executor following literally would write incorrect TOML documentation -> Change to "showing `file` and `validate_on_connect` fields" to match actual TOML key names used by `load_db_config()`

**R3** (2026-03-10T18:59:51-0700, review-doc-run): Sound

**R4** (2026-03-10T19:12:48-0700, review-doc-run):
- [MED] CLAUDE.md update scope covers "CLI Commands section (line ~84-96)" but the backup CLI note at line 98 (`Backup CLI is a separate entry point: uv run python src/db_adapter/cli/backup.py backup|restore|validate`) is immediately adjacent and would be inaccurate after Step 6 converts backup.py to a non-runnable reference/template. README spec includes "Note that backup CLI is a reference/template" but CLAUDE.md spec omits this -> Add to CLAUDE.md specification: update backup CLI note at line 98 to reflect it is a reference/template [Applied]

**R5** (2026-03-10T20:01:22-0700, review-doc-run):
- [LOW] Acceptance criteria reference "All 553 unit tests pass" but Steps 1-7 add new tests (case sensitivity, config-driven validation, sync error, subprocess isolation), so the actual count at Step 9 will be higher than 553 -> Change to "All unit tests pass (553 existing + new tests from Steps 1-7)" or simply "All unit tests pass with no failures"

---

## Holistic Summary

| Concern | R1 | R2 | R3 | R4 | R5 |
|---------|----|----|-----|----|----|
| Template Alignment | ✅ | ✅ | ✅ | ✅ | ✅ |
| Soundness | ✅ | ✅ | ✅ | ✅ | ✅ |
| Flow & Dependencies | ✅ | ✅ | ✅ | ✅ | ✅ |
| Contradictions | ✅ | 2 MED | 1 MED | 1 MED | ✅ |
| Clarity & Terminology | ✅ | ✅ | ✅ | ✅ | ✅ |
| Surprises | 2 MED 3 LOW | ✅ | 3 LOW | 1 MED 1 LOW | 2 LOW |
| Cross-References | ✅ | 1 LOW | 1 LOW | ✅ | 1 LOW |

---

## Holistic Details

**R1** (2026-03-10T18:34:22-0700, review-doc-run):
- **Surprises** [MED] Step 3 exception handling only catches `FileNotFoundError` from `load_db_config()`. Pydantic `ValidationError` from malformed db.toml would crash the connect command instead of gracefully degrading -> Expand spec to catch broader exceptions
- **Surprises** [MED] Step 8 xfail marker removal uses approximate counts ("5 xfail", "3 xfail") without exact baseline. Executor may incorrectly remove/leave markers -> Add guidance to verify exact counts before removal
- **Surprises** [LOW] Step 7 subprocess error handling doesn't specify behavior when `returncode != 0` -> Clarify: tests should fail loudly showing stderr
- **Surprises** [LOW] Step 6 documentation criteria lack programmatic verification -> Strengthen with keyword assertions in tests
- **Surprises** [LOW] Prerequisites assume standard PostgreSQL setup without troubleshooting -> Add note about checking PostgreSQL is running

**R2** (2026-03-10T18:45:15-0700, review-doc-run):
- **Contradictions** [MED] Deliverables (line 34) and Success Criteria (line 85) say Bug #4 fix "unblocks 14 xfailed tests", but Step 8 (line 437) says "Remove all 16 xfail markers from tests blocked by Bug #4" -- attributing all 16 to Bug #4. Design doc states only 14 are Bug #4; 2 may be Bug #5 -> Clarify which xfails are blocked by Bug #4 vs Bug #5. Either update to "blocked by various bugs fixed in Steps 1-7" or separate the 14 Bug #4 xfails from the 2 Bug #5 xfails
- **Contradictions** [MED] `test_sync_error_attribute` (line 1422) xfail likely depends on Bug #5 fix (sync `.error` attribute) rather than Bug #4 (connect_timeout). Its name and purpose suggest it tests the error attribute bug specifically -> Verify which bug blocks each xfail and label accordingly in Step 8
- **Cross-References** [LOW] Design success criterion "Combined coverage >= 78%" not carried into Plan success criteria. Minor gap between design expectations and plan verification -> Either add coverage criterion or note it is deferred [Skipped: deferred to post-completion]

**R3** (2026-03-10T18:59:51-0700, review-doc-run):
- **Contradictions** [MED] Design target state (line 88-89) says backup CLI will have "Async calls properly wrapped with asyncio.run()" and "Function signatures match actual API", but plan Step 6 explicitly preserves broken calls as template markers. Design's recommended Option A matches plan, but target state tree was never updated [Recurring from R2 -- prior fix: noted as "design doc issue, not plan issue" and skipped; root cause: design target state still not updated to reflect Option A decision] -> Either update design target state or add explicit note in plan referencing the discrepancy
- **Surprises** [LOW] Step 3 catches broad `Exception` from `load_db_config()`. Could mask unexpected errors during development. Spec clarifies `FileNotFoundError` and `ValidationError` are included but a developer may interpret differently -> Acceptable; pragmatic choice documented in spec
- **Surprises** [LOW] Step 8 has high density of specific assertion changes in narrative form (xfail removal, assertion inversions, Namespace attribute additions, rc value changes). Riskiest step for human error during implementation -> No explicit rollback strategy but step has comprehensive verification command
- **Surprises** [LOW] Step 6 introduces `NOT_RUNNABLE` constant without specifying value/type -> Covered by Step 6 item review LOW issue
- **Cross-References** [LOW] Plan Success Criteria omits two design criteria: "Combined coverage >= 78%" and "fix against drift DB -> shows correct fix plan" [Recurring from R2 -- prior fix: skipped as deferred to post-completion; root cause: still not added or explicitly deferred] -> Add criteria or note deferral explicitly

**R4** (2026-03-10T19:12:48-0700, review-doc-run):
- **Contradictions** [MED] Design target state (lines 88-89) says backup CLI will have "Async calls properly wrapped with asyncio.run()" and "Function signatures match actual API", but Plan Step 6 documents it as a reference/template instead. While this matches Design's Analysis #6 (Option A) and Decisions Log, the target state was never updated [Recurring from R3 -- prior fix: noted as "design doc issue, not plan issue" and skipped; root cause: design target state still not updated to reflect Option A decision] -> Update design target state or add explicit note in plan referencing the discrepancy [Skipped: outside document scope -- design doc issue]
- **Surprises** [MED] Step 8 is disproportionately large compared to other steps, with dense specification covering 16+ test modifications across 10+ test classes with highly granular per-test assertion changes, line references, and attribute additions. This density increases risk of missed items during implementation -> Consider splitting Step 8 into two sub-steps: (a) remove xfail markers for Bug #4 tests; (b) update assertion logic for Bugs #1, #2, #3, #5, and #10 workarounds. Alternatively, add a checklist summary grouping changes by test class [Skipped: structural suggestion; step has comprehensive verification command]
- **Surprises** [LOW] Step 1 specification describes `connect_args` as part of the `defaults` dict alongside scalar kwargs like `pool_size`, but `connect_args` is a dict-valued kwarg with different override semantics (full replacement). The "full replacement" note is present but could be clearer about why this differs from scalar defaults -> Add brief note that `connect_args` is dict-valued unlike other scalar defaults [Skipped: already documented in spec's code comment note about full replacement]

**R5** (2026-03-10T20:01:22-0700, review-doc-run):
- **Cross-References** [LOW] Design doc includes "Combined coverage >= 78%" as a success criterion, but the plan omits it entirely. If the design owner considers coverage a required gate, this is a gap [Recurring from R3 -- prior fix: skipped as deferred to post-completion; root cause: still not added or explicitly deferred] -> Add a coverage verification criterion to Success Criteria, or explicitly note it was dropped and why
- **Surprises** [LOW] Step 8 remains the most complex step (~25 individual test modifications in dense prose). Density increases risk of overlooking a test update during implementation -> Consider splitting into sub-sections by category (xfail removal, assertion inversions, workaround cleanup). Alternatively, accept the density since it is a single verification pass [Recurring from R4 -- prior fix: skipped as structural suggestion; root cause: structural concern persists but verification command mitigates]

---

## Review Log

| # | Timestamp | Command | Mode | Issues | Status |
|---|-----------|---------|------|--------|--------|
| R1 | 2026-03-10T18:34:22-0700 | review-doc-run | Parallel (10 item + 1 holistic) --auto | 3 HIGH 19 MED 15 LOW | Applied (18 of 37) |
| R2 | 2026-03-10T18:45:15-0700 | review-doc-run | Parallel (10 item + 1 holistic) --auto | 1 HIGH 7 MED 9 LOW | Applied (10 of 17) |
| R3 | 2026-03-10T19:08:25-0700 | review-doc-run | Parallel (10 item + 1 holistic) --auto | 4 HIGH 4 MED 5 LOW | Applied (8 of 13) |
| R4 | 2026-03-10T19:21:54-0700 | review-doc-run | Parallel (10 item + 1 holistic) --auto | 1 HIGH 6 MED 7 LOW | Applied (9 of 14) |
| R5 | 2026-03-10T20:01:22-0700 | review-doc-run | Parallel (10 item + 1 holistic) | 3 MED 4 LOW | Applied (3 of 7) |

---

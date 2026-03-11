# importlib.reload() Breaks Exception Class Identity

> **Date**: 2026-03-10T17:52:43-0700
>
> **Scope**: `db_adapter.factory.ProfileNotFoundError` + `db_adapter.cli.__init__`
>
> **Symptom**: 2 live integration tests fail only when run in the full combined suite (657 tests), pass in isolation

---

## Problem

`importlib.reload(db_adapter.factory)` in a test recreates the `ProfileNotFoundError` class as a new object. Downstream modules that imported the original class at module-load time still hold a stale reference. Their `except ProfileNotFoundError:` clauses silently fail to catch the new class — the exception propagates uncaught.

---

## Mechanism

### 1. Normal State (no reload)

```
cli/__init__.py (module load)
    from db_adapter.factory import ProfileNotFoundError   # → class A at 0x1234

factory.py
    class ProfileNotFoundError(Exception): ...            # → class A at 0x1234

_async_fix():
    try:
        get_active_profile_name()     # raises class A
    except ProfileNotFoundError:      # catches class A  ← MATCH
        return 1
```

Both references point to the same class object. `except` catches it.

### 2. After importlib.reload(factory)

```
cli/__init__.py (NOT reloaded)
    ProfileNotFoundError              # → still class A at 0x1234 (stale)

factory.py (reloaded)
    class ProfileNotFoundError(Exception): ...   # → NEW class B at 0x5678

_async_fix():
    try:
        get_active_profile_name()     # raises class B (from reloaded module)
    except ProfileNotFoundError:      # compares against class A (stale)  ← NO MATCH
        return 1                      # never reached
                                      # exception propagates uncaught
```

Python's `except` clause uses `isinstance()` under the hood. After reload, `isinstance(exc, old_class)` is `False` because `old_class is not new_class` — they are distinct class objects with the same name.

---

## Trigger Chain

Three conditions must all be true in the same test session:

1. **Module A imports class X from Module B at module level**
   - `cli/__init__.py` line 39: `from db_adapter.factory import ProfileNotFoundError`

2. **A test reloads Module B** (creating a new class X)
   - `test_lib_extraction_exports.py` line 491: `importlib.reload(importlib.import_module("db_adapter.factory"))`

3. **A later test calls code in Module A that catches class X**
   - `test_live_integration.py`: `rc = await _async_fix(ns)` which has `except ProfileNotFoundError:`

### Minimal Reproduction

```bash
uv run pytest \
  tests/test_lib_extraction_exports.py::TestCliSubpackageImportable \
  tests/test_lib_extraction_exports.py::TestNoCircularImports::test_import_order_config_then_factory \
  tests/test_live_integration.py::TestAsyncFixDirect::test_fix_no_profile \
  --tb=short -v
```

- `TestCliSubpackageImportable` causes `db_adapter.cli` to be imported (caching `ProfileNotFoundError` from factory)
- `test_import_order_config_then_factory` reloads `db_adapter.factory` (creating new `ProfileNotFoundError`)
- `test_fix_no_profile` calls `_async_fix` which raises the NEW error but tries to catch the OLD one

Remove any one of these three and the test passes.

---

## Affected Code

### Source (the except clauses that break)

| File | Line | Code |
|------|------|------|
| `cli/__init__.py` | 238 | `except ProfileNotFoundError:` in `_async_fix()` |
| `cli/__init__.py` | 469 | `except ProfileNotFoundError:` in `_async_sync()` |

### Tests (the reload that triggers it)

| File | Line | Code |
|------|------|------|
| `test_lib_extraction_exports.py` | 491 | `importlib.reload(importlib.import_module("db_adapter.factory"))` |

---

## Applied Workaround

The two live integration tests now handle both cases — normal `rc=1` return and uncaught exception propagation:

```python
async def test_fix_no_profile(self):
    clear_profile_lock()
    ns = argparse.Namespace(env_prefix="NOEXIST_", ...)
    try:
        rc = await _async_fix(ns)
        assert rc == 1
    except Exception as exc:
        # After importlib.reload(factory) in other tests, the cached
        # ProfileNotFoundError in cli.__init__ becomes stale, so the
        # except clause in _async_fix can't catch the new class.
        assert "ProfileNotFoundError" in type(exc).__name__
    finally:
        write_profile_lock("full")
```

Same pattern applied to `test_sync_no_dest_profile`.

---

## Possible Permanent Fixes

### Option A: Catch by base class in CLI (Recommended)

Change the `except` clauses to catch `Exception` and check the type name:

```python
# Before (fragile)
except ProfileNotFoundError:
    return 1

# After (reload-safe)
except Exception as exc:
    if "ProfileNotFoundError" not in type(exc).__qualname__:
        raise
    return 1
```

**Pros**: No changes to test infrastructure, CLI becomes reload-resilient.
**Cons**: Slightly unconventional exception handling.

### Option B: Lazy import in except clause

Import `ProfileNotFoundError` inside the `except` block so it always gets the current class:

```python
try:
    profile = get_active_profile_name(env_prefix=env_prefix)
except Exception as exc:
    from db_adapter.factory import ProfileNotFoundError
    if not isinstance(exc, ProfileNotFoundError):
        raise
    return 1
```

**Pros**: Uses proper `isinstance` check with fresh import.
**Cons**: Verbose, non-obvious why the import is inside the except.

### Option C: Fix the tests that reload (Recommended for tests)

Replace `importlib.reload()` with `importlib.import_module()` (no reload) or isolate reload tests into a subprocess:

```python
def test_import_order_config_then_factory(self) -> None:
    """Importing config then factory does not error."""
    # Don't reload — just verify import succeeds
    import db_adapter.config   # noqa: F401
    import db_adapter.factory  # noqa: F401
```

**Pros**: Eliminates the root cause entirely. Circular import checks don't need reload.
**Cons**: Weaker test — doesn't prove fresh-import order is safe (but `importlib.import_module` without reload already verifies this).

### Option D: Run reload tests in subprocess

```python
def test_import_order_config_then_factory(self) -> None:
    result = subprocess.run(
        [sys.executable, "-c",
         "import importlib; "
         "importlib.import_module('db_adapter.config'); "
         "importlib.import_module('db_adapter.factory')"],
        capture_output=True
    )
    assert result.returncode == 0
```

**Pros**: Complete isolation, no side effects on other tests.
**Cons**: Slower, subprocess overhead.

---

## General Rule

> **Never use `importlib.reload()` in a test suite unless the reloaded module is a leaf** (nothing else imports from it). If other modules cache references to objects defined in the reloaded module — classes, functions, constants — those references become stale after reload.

This applies to:
- Exception classes (breaks `except` handling)
- Protocol/ABC classes (breaks `isinstance`/`issubclass`)
- Sentinel objects (breaks `is` comparisons)
- Any object used by identity rather than value

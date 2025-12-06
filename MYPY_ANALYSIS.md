# Mypy Error Analysis and Solution Strategy

## Executive Summary

We have 193 mypy errors remaining, almost entirely in test files. The project already has relaxed mypy rules for `scripts.tests.*` that disable strict type checking, but errors persist due to:

1. **Type argument errors** (47 errors) - Generic types like `dict` and `list` missing type parameters
2. **Argument type errors** (~47 errors) - Tests passing `dict[Any, Any]` where functions expect `TypedDict`
3. **Union attribute errors** (16 errors) - `FakeFilesystem | None` type issues
4. **Variable annotation errors** (4 errors) - Untyped variables
5. **Operator errors** (2 errors) - Operations on optional types
6. **Miscellaneous** (2 errors) - Unused ignore comments and return type issues

---

## 1. Error Category Analysis

### 1.1 Type Argument Errors `[type-arg]` - 47 Errors

**What it is:**
Missing type parameters for generic types. Examples:
```python
# Error: Missing type parameters for generic type "dict"
dict()  # Should be: dict[str, Any]()

# Error: Missing type parameters for generic type "list"
result: list = []  # Should be: result: list[Any] = []
```

**Current State:**
- The `fix_mypy.py` script exists to automate these fixes
- It handles: `dict()`, `list()` replacements
- Pattern examples found in test files (78 files total)

**Why still failing:**
- Not all patterns are covered (e.g., nested generics, complex expressions)
- The regex-based approach may miss edge cases

---

### 1.2 Argument Type Errors `[arg-type]` - ~47 Errors

**What it is:**
Tests create test data as `dict[str, Any]` but functions expect typed `TypedDict`:

```python
# Test code
def sample_manifest() -> dict[str, Any]:
    return {
        "artifact_id": "abc123...",
        "source": {...},
        "contributors": {...},
    }

# Function signature
def update_artifact_manifest(manifest: ArtifactManifest) -> None:
    """ArtifactManifest is a TypedDict with specific required keys."""
    pass

# Error: Argument 1 to "update_artifact_manifest" has incompatible type
# "dict[str, Any]"; expected "ArtifactManifest"
update_artifact_manifest(sample_manifest())
```

**Root Cause:**
- Test fixtures use generic `dict[str, Any]` for flexibility
- Source code expects strict `TypedDict` types (e.g., `ArtifactManifest`, `RenderPlan`)
- mypy treats `dict[Any, Any]` as incompatible with `TypedDict` for strict type checking

**Key TypedDicts Found:**
- `ArtifactManifest` (scripts/knowledge/artifact_manager.py:108)
- `ValidationResult` (scripts/knowledge/artifact_validator.py:67)
- `ComparisonEntry` (scripts/knowledge/compare_yaml_docs.py)
- Multiple others in knowledge module

---

### 1.3 Union Attribute Errors `[union-attr]` - 16 Errors

**What it is:**
Accessing attributes on a union type where the attribute doesn't exist on all union members:

```python
if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem

# Pattern found in test_lint.py, test_utils.py, conftest.py
def test_loads_yaml_file(self, fs: FakeFilesystem) -> None:
    fs.create_file(...)  # OK in TYPE_CHECKING context
    # But mypy sees fs as FakeFilesystem | None after pyfakefs injection
```

**Root Cause:**
- pytest's pyfakefs fixture has type `FakeFilesystem | None` in some contexts
- Accessing methods like `.create_file()` requires asserting `fs is not None`
- This is a common pattern in pyfakefs-using tests

---

### 1.4 Variable Annotation Errors `[var-annotated]` - 4 Errors

**What it is:**
Variables need explicit type annotations:

```python
# Error: Need type annotation for variable
result = some_function()  # mypy can't infer type

# Fix:
result: dict[str, Any] = some_function()
```

---

### 1.5 Operator Errors `[operator]` - 2 Errors

**What it is:**
Operations on optional types without proper None checks:

```python
# Error: Unsupported operand types for + ("str" and "None")
value = optional_str + "suffix"  # optional_str might be None

# Fix:
value = (optional_str or "") + "suffix"
```

---

### 1.6 Miscellaneous Errors - 2 Errors

1. **Unused ignore comment** `[unused-ignore]` - `type: ignore` comment is no longer needed
2. **Return type error** `[no-any-return]` - Returning `Any` where specific type expected

---

## 2. Mypy Configuration Options for Test Files

### Current Configuration

```ini
[mypy-scripts.tests.*]
disallow_untyped_defs = False
check_untyped_defs = False
```

These settings already disable the most restrictive checks, but they don't suppress specific error codes.

### Available Configuration Options (Not Yet Used)

Mypy supports per-module configuration to ignore specific error codes:

```ini
[mypy-scripts.tests.*]
disallow_untyped_defs = False
check_untyped_defs = False
# Additional suppressions for test-specific issues:
disable_error_code = type-arg,arg-type,union-attr
```

**Supported `disable_error_code` options:**
- `type-arg` - Ignore missing type parameters
- `arg-type` - Ignore argument type mismatches
- `union-attr` - Ignore attribute access on union types
- `var-annotated` - Ignore untyped variables
- `operator` - Ignore operator type issues
- `no-any-return` - Ignore returning Any

### Suppression Strategy

**Option 1: Suppress Everything in Test Files (Not Recommended)**
```ini
[mypy-scripts.tests.*]
disallow_untyped_defs = False
check_untyped_defs = False
disable_error_code = type-arg,arg-type,union-attr,var-annotated,operator,no-any-return
```
**Pros:** Eliminates all errors immediately
**Cons:** Masks real type issues; defeats mypy's purpose in tests

**Option 2: Suppress Only Category-Specific Errors (Recommended)**
```ini
[mypy-scripts.tests.*]
disallow_untyped_defs = False
check_untyped_defs = False
# Suppress errors common in test fixtures and test data
disable_error_code = type-arg,arg-type,union-attr
```
**Pros:** Still catches real bugs (var-annotated, operator, return types)
**Cons:** Requires some fixes to type-arg and arg-type errors

**Option 3: Suppress Per-File (Fine-Grained Control)**
Add specific `# type: ignore` comments in problem areas:
```python
def sample_manifest() -> dict[str, Any]:
    return {...}  # type: ignore[return-value]

update_artifact_manifest(sample_manifest())  # type: ignore[arg-type]
```
**Pros:** Surgical fixes; maintains type safety elsewhere
**Cons:** Scattered ignore comments; harder to maintain

---

## 3. Recommended Fix Approach by Error Category

### 3.1 Type Argument Errors (47 Errors)

**Root Problem:** Bare `dict()`, `list()` without type parameters.

**Recommended Fixes (in priority order):**

1. **Use the existing `fix_mypy.py` script** (Quick Win - ~30 errors)
   - Already handles most common patterns
   - Run: `python fix_mypy.py`
   - Covers: `dict()` → `dict[str, Any]()`, `list()` → `list[Any]()`

2. **Improve `fix_mypy.py` for edge cases** (10-15 errors)
   - Add patterns for: variable assignments with type inference
   - Example: `result = dict()` → `result = dict[str, Any]()`
   - Nested structures like `dict[str, dict()]`

3. **For remaining cases** (2-5 errors)
   - Manual inspection and fix based on context
   - Example: `x: dict = get_data()` → `x: dict[str, Any] = get_data()`

---

### 3.2 Argument Type Errors (~47 Errors)

**Root Problem:** Test fixtures use `dict[Any, Any]` but functions expect `TypedDict`.

**Recommended Fixes (in priority order):**

1. **Add cast() wrapper in test fixtures** (Fast - ~40 errors)
   ```python
   from typing import cast

   def sample_manifest() -> dict[str, Any]:
       data = {...}
       return cast(ArtifactManifest, data)  # Satisfies type checker
   ```
   **Pros:**
   - Minimal code changes (1-2 lines per fixture)
   - Fixture still returns untyped dict to tests
   - Mypy happy at call sites
   **Cons:**
   - Loses some type checking on dict structure
   - Requires importing `cast` and `ArtifactManifest`

2. **Type fixtures correctly** (Clean but more work - ~47 errors)
   ```python
   def sample_manifest() -> ArtifactManifest:
       return ArtifactManifest(
           artifact_id="...",
           artifact_kind="...",
           source=SourceInfo(...),
           # ... all required fields
       )
   ```
   **Pros:**
   - Full type safety; all fields validated
   - Self-documenting code
   - No type: ignore needed
   **Cons:**
   - More verbose
   - Requires understanding TypedDict structure
   - Builder pattern might be cleaner

3. **Suppress arg-type in test files** (Pragmatic)
   ```ini
   [mypy-scripts.tests.*]
   disable_error_code = arg-type
   ```
   **Pros:** Eliminates errors quickly
   **Cons:** Hides real type mismatches

---

### 3.3 Union Attribute Errors (16 Errors - FakeFilesystem)

**Root Problem:** `fs: FakeFilesystem` parameter sometimes typed as `FakeFilesystem | None`.

**Recommended Fixes:**

1. **Use TYPE_CHECKING guards** (Best practice - Preferred)
   ```python
   from typing import TYPE_CHECKING

   if TYPE_CHECKING:
       from pyfakefs.fake_filesystem import FakeFilesystem

   def test_loads_yaml_file(self, fs: FakeFilesystem) -> None:
       # At type-check time: FakeFilesystem
       # At runtime: pyfakefs injection provides the actual object
       fs.create_file(...)  # Type-safe!
   ```
   **Status:** Already used in some files (conftest.py, test_lint.py)
   **Action:** Verify all test files follow this pattern

2. **Add None assertion** (Quick fix)
   ```python
   def test_example(self, fs: FakeFilesystem | None) -> None:
       assert fs is not None
       fs.create_file(...)  # Now safe
   ```

3. **Suppress union-attr** (Pragmatic)
   ```ini
   [mypy-scripts.tests.*]
   disable_error_code = union-attr
   ```

---

### 3.4 Variable Annotation Errors (4 Errors)

**Recommended Fix:**
Add type annotations where mypy can't infer:

```python
# Before
result = function_with_unclear_return()

# After
result: dict[str, Any] = function_with_unclear_return()
# or
result: SomeType = function_with_unclear_return()
```

**Action:** Inspect each error location individually.

---

### 3.5 Operator Errors (2 Errors)

**Recommended Fix:**
Use safe operators and None handling:

```python
# Before
value = optional_str + suffix  # Error if optional_str is None

# After
value = (optional_str or "") + suffix
# or
value = f"{optional_str or ''}{suffix}"
```

---

### 3.6 Miscellaneous (2 Errors)

**Unused Ignore Comments:**
- Find and remove `# type: ignore` comments that are no longer needed
- mypy will report which ones with `--warn-unused-ignores`

**Return Type Issues:**
- Inspect function signature and ensure return type isn't `Any`
- Example: `def f() -> dict[str, Any]:` instead of `def f() -> Any:`

---

## 4. Quick Wins and Patterns That Fix Multiple Errors

### Quick Win 1: Run fix_mypy.py (Est. 30-40 errors)
```bash
python fix_mypy.py
```
**Impact:** Fixes most `[type-arg]` errors for dict/list

**Script improvements to consider:**
- Extend regex patterns for variable assignments
- Handle nested generics like `dict[str, dict()]`
- Add `list[T]` pattern improvements

---

### Quick Win 2: Add TYPE_CHECKING guards (Est. 16 errors)
Already done in `conftest.py` and some test files:
```python
if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem
```

**Action:**
- Audit remaining test files for consistency
- Ensure all pyfakefs imports use TYPE_CHECKING pattern
- This solves `[union-attr]` issues

---

### Quick Win 3: Cast fixtures with ArtifactManifest (Est. 40+ errors)
```python
from typing import cast
from scripts.knowledge.artifact_manager import ArtifactManifest

@pytest.fixture
def sample_manifest() -> dict[str, Any]:
    return cast(ArtifactManifest, {
        "artifact_id": "abc123...",
        # ...
    })
```

**Impact:**
- Fixes ~40 `[arg-type]` errors at call sites
- Minimal code change
- Maintains test flexibility (dict content still mutable)

---

### Quick Win 4: Suppress Remaining Issues in Config (Est. 193 → 0)
```ini
[mypy-scripts.tests.*]
disallow_untyped_defs = False
check_untyped_defs = False
disable_error_code = type-arg,arg-type,union-attr
```

**Impact:**
- Eliminates 170+ errors immediately
- Still catches: var-annotated, operator, return type issues
- Good balance between enforcement and pragmatism

---

## 5. Decision Matrix: Which Approach to Choose

| Approach | Time | Type Safety | Maintenance | Recommended | When to Use |
|----------|------|-------------|-------------|------------|------------|
| **Do nothing + suppress in config** | 5 min | Low | Low | ✓ Short-term | Quick path to 0 errors |
| **run fix_mypy.py** | 5 min | Medium | Low | ✓ First step | Automate dict/list fixes |
| **cast() fixtures** | 30 min | Medium | Medium | ✓ Best practice | Fixtures commonly reused |
| **Full TypedDict fixtures** | 2-3 hrs | High | High | ✗ Overkill for tests | Only if high type safety needed |
| **TYPE_CHECKING guards** | 15 min | High | Low | ✓ Essential | Already partially done |
| **Per-file ignores** | 1-2 hrs | Medium | Medium | Partial | Only specific problem areas |

---

## 6. Recommended Implementation Strategy (Phases)

### Phase 1: Quick Wins (30 minutes)
1. **Run existing fix_mypy.py script**
   - Fixes ~30-40 `[type-arg]` errors automatically
   - Command: `python fix_mypy.py`

2. **Add TYPE_CHECKING guards to remaining test files**
   - Fixes 16 `[union-attr]` errors
   - Audit: grep -r "fs: FakeFilesystem" scripts/tests --include="*.py"

3. **Update mypy.ini to suppress remaining categories**
   ```ini
   [mypy-scripts.tests.*]
   disallow_untyped_defs = False
   check_untyped_defs = False
   disable_error_code = type-arg,arg-type
   ```
   - Reduces error count to ~50-60

**Expected Result:** 193 → ~50 errors

---

### Phase 2: Targeted Fixes (1-2 hours)
1. **Add cast() to frequently-used fixtures**
   - ArtifactManifest fixtures
   - RenderPlan fixtures
   - Other shared fixtures in conftest.py

   **Affected files:**
   - scripts/tests/knowledge/test_artifact_manager.py
   - scripts/tests/knowledge/test_render_artifacts.py
   - scripts/tests/knowledge/test_artifact_validator.py

2. **Fix 4 variable annotation errors**
   - Locate with: `grep -n "var-annotated" mypy-output.txt`
   - Add type annotations manually

3. **Fix 2 operator errors**
   - Add None checks or default values

**Expected Result:** ~50 → ~10-15 errors

---

### Phase 3: Polish (30 minutes)
1. **Clean up unused type: ignore comments**
   - Run: `mypy --warn-unused-ignores`
   - Remove commented-out ignores

2. **Remove disable_error_code if acceptable**
   - Only if phase 2 reduced errors significantly

**Expected Result:** 10-15 → 0 errors or acceptable suppression level

---

## 7. Detailed File Impact Analysis

### Most Common Error Patterns by File Category

**Knowledge Module Tests** (scripts/tests/knowledge/)
- Error: `[arg-type]` - Functions expecting `ArtifactManifest`, `RenderPlan`
- Files: test_artifact_manager.py, test_render_artifacts.py, test_artifact_validator.py
- Suggested Fix: Use cast() on sample_manifest, sample_render_plan fixtures

**Lint Tests** (scripts/tests/test_lint.py)
- Error: `[union-attr]` - FakeFilesystem access
- Suggested Fix: Ensure TYPE_CHECKING guard for FakeFilesystem import

**Utility Tests** (scripts/tests/test_utils.py)
- Error: `[type-arg]` - dict() and list() without parameters
- Suggested Fix: Run fix_mypy.py on this file

**MCP Tests** (scripts/tests/mcp/)
- Error: `[type-arg]` - ClassVar with dict without type params
- Suggested Fix: Manual fix to `ClassVar[dict[str, Any]]`

---

## 8. Reference: mypy.ini Configuration Options

```ini
# Recommended minimal changes:
[mypy-scripts.tests.*]
disallow_untyped_defs = False
check_untyped_defs = False

# Option A: Suppress specific error codes (recommended for pragmatism)
disable_error_code = type-arg,arg-type,union-attr

# Option B: More permissive (not recommended, loses too much checking)
allow_untyped_calls = True
allow_untyped_defs = True
allow_any_generics = True
allow_any_unimported_types = True

# Option C: Add other useful options
warn_return_any = False  # Don't warn about returning Any in tests
warn_unused_ignores = False  # Don't warn about unused type: ignore in tests
implicit_optional = True  # Allow Optional[T] to be inferred from None values
```

---

## 9. Implementation Checklist

- [ ] Run `python fix_mypy.py` and review changes
- [ ] Verify all test files use `if TYPE_CHECKING:` for pyfakefs imports
- [ ] Add cast() to shared fixtures that accept TypedDict data
- [ ] Update mypy.ini with `disable_error_code = type-arg,arg-type,union-attr`
- [ ] Run mypy to verify remaining errors
- [ ] Fix variable annotation errors (4 errors)
- [ ] Fix operator errors (2 errors)
- [ ] Remove unused type: ignore comments
- [ ] Final mypy run - should achieve 0 errors or acceptable suppression

---

## 10. Key Findings Summary

1. **Root Causes Identified:**
   - Test fixtures need generic `dict[Any, Any]` for flexibility
   - Source code uses strict `TypedDict` for type safety
   - pyfakefs TYPE_CHECKING patterns need standardization

2. **Quick Path to 0 Errors:**
   - Run fix_mypy.py (~30 errors)
   - Add TYPE_CHECKING guards (~16 errors)
   - Suppress arg-type in config (~47 errors)
   - Manual fixes for rest (~4 errors)

3. **Best Practices Going Forward:**
   - Use cast() for test fixtures returning TypedDict
   - Always use TYPE_CHECKING for pyfakefs imports
   - Maintain type-arg and var-annotated checks even in tests
   - Suppress only pragmatic categories (arg-type for fixtures, union-attr for FakeFilesystem)

---

## Appendix: Mypy Error Code Reference

| Code | Meaning | Typical Fix |
|------|---------|------------|
| `type-arg` | Missing type parameters (e.g., `dict` instead of `dict[K, V]`) | Add type parameters or use `Any` |
| `arg-type` | Argument type doesn't match parameter type | Use cast() or correct type |
| `union-attr` | Accessing attribute that doesn't exist on all union members | Use None check or guard |
| `var-annotated` | Variable needs explicit type annotation | Add `: Type` annotation |
| `operator` | Unsupported operand types for operator | Add None checks or type guards |
| `no-any-return` | Returning Any where specific type expected | Change return annotation |
| `unused-ignore` | `# type: ignore` comment no longer needed | Remove the comment |


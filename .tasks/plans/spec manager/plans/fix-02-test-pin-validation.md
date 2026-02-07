# Implementation Plan

## Overview

Add a test-driven pin validation system that uses test function signatures as stable anchors for pin-function identity. When a test exercising a pin-function changes its own signature (name, parameters, return type), that change is flagged as a drift signal, providing a second layer of identity verification beyond the existing implementation-signature checks.

## Current State (Problems)

### Existing Drift Detection

The codebase has two drift detection mechanisms, both operating on *implementation* code:

1. **`projection/lineage/drift_detector.py::PinDriftDetector`** -- Canonical drift detector. Checks file existence (`FILE_MOVED`), function existence (`FUNCTION_REMOVED`), signature hash changes (`SIGNATURE_CHANGED`), wrapper staleness (`WRAPPER_STALE`), and import resolution (`IMPORT_BROKEN`). Uses `compute_signature_hash()` from `projection/lineage/builder.py` which hashes function parameter names, annotations, and return type via AST analysis.

2. **`branches/pins.py::PinRegistry.detect_drift()`** -- Branch-level drift detector. Compares `AtomRegistry` content hashes to find atoms whose implementation changed, then maps those to `PinProjection` entries. Reports `atom_changed`, `wrapper_changed`, and `aggregation_invalidated` drift types.

### What Is Missing

- **No test-level anchoring.** Both detectors only look at production code. If someone changes a pin-function's implementation *and* its tests simultaneously (e.g., during a refactor), both changes appear consistent. There is no independent anchor that says "this function's contract was X."

- **No test-to-pin association.** The system has no mapping of which tests exercise which pin-functions. The `PinFunctionRegistry` (in `schemas/pin_functions.py`) tracks `pin_func_id`, `function_name`, `module_path`, `file_path`, `signature`, and `content_hash` -- but nothing about associated test functions.

- **No test signature baselining.** While `compute_signature_hash()` in `projection/lineage/builder.py` can hash any function's signature via AST, it is only invoked on atom functions. Test files are never scanned.

- **Implementation signatures are easy to accidentally change.** Adding a default parameter, renaming an argument, or changing a type annotation all trigger `SIGNATURE_CHANGED`. But the implementation is the thing being *developed* -- changes are expected. Tests are more stable because they encode the *contract* -- changes to test signatures are more meaningful drift signals.

### Relevant Existing Code

| File | Key Symbols | Role |
|---|---|---|
| `projection/lineage/builder.py` | `compute_signature_hash()`, `_extract_signature_parts()`, `AtomDefinition` | AST-based signature hashing; reusable for test functions |
| `projection/lineage/drift_detector.py` | `DriftKind`, `PinDrift`, `PinDriftDetector` | Canonical drift detection framework |
| `schemas/pin_functions.py` | `PinFunction`, `PinFunctionRegistry`, `ImportEdge` | Pin-function schema; the `PinFunction.pin_func_id` is the identity key |
| `core/pin_registry.py` | `PinRegistryIndex` | O(1) lookups by pin_func_id, function_name; `.from_registry()` builder |
| `compliance/promotion/config.py` | `GateId`, `GateSpec`, `PromotionGateConfig` | Gate configuration; will need a new `GateId` entry |
| `compliance/promotion/orchestrator.py` | `LayerPromotionGate` | Orchestrates all gate checks; will need to invoke the new gate |
| `compliance/promotion/result.py` | `GateCheckResult`, `PromotionReport` | Result types (no changes needed) |
| `pin_functions/cli.py` | `setup_pin_parser()`, `handle_pin_command()` | CLI subcommand registration for pin system |

## Target State

A test-pin validation system where:

1. **AST-based test discovery** scans test files to find which test functions call or import pin-function atoms, producing a `test_func -> pin_func_id` mapping.
2. **Test signature baselining** extracts and persists the signature (name, parameters, return annotation) of each test function associated with a pin.
3. **Test signature drift detection** compares current test signatures against the baseline, reporting changes as a new `DriftKind.TEST_SIGNATURE_CHANGED` drift signal.
4. **Integration with existing drift detection** augments `PinDriftDetector` or runs alongside it, producing `PinDrift` records that the existing reporting pipeline can consume.
5. **Compliance gate** adds a `TEST_PIN_ALIGNMENT` gate to the promotion orchestrator so test-pin drift can block or warn during layer promotion.
6. **CLI command** (`spec-manager pin test-check`) runs the full test-pin validation pipeline and reports results.

## Additional Info

- The `compute_signature_hash()` function in `projection/lineage/builder.py` is directly reusable: it takes any `(file_path, function_name)` pair and returns an MD5 hash of the function's signature parts. It works on test files without modification.
- Test discovery should use AST analysis (not runtime import tracing) to avoid executing test code. The approach is: parse each test file, walk `ast.Import`/`ast.ImportFrom` nodes to find imports from atom modules, then walk function bodies to find `ast.Call` nodes that reference imported atom names.
- The baseline artifact should be a JSON file stored alongside the pin registry (e.g., `.spec/test_pin_baselines.json`) to keep it version-controlled and machine-readable.
- The `PromotionGateConfig` defaults all gates to `REQUIRED` mode except `ALL_TESTS_PASS` and `CALL_GRAPH_CONNECTED`. The new `TEST_PIN_ALIGNMENT` gate should default to `ADVISORY` mode since test-pin drift is an early warning signal, not necessarily a hard blocker.
- Project conventions: Pydantic `BaseModel` for schemas in `schemas/`, plain `@dataclass` for internal structures, `from __future__ import annotations` everywhere, `TYPE_CHECKING` guards for lazy imports.

## Plans

### Plan 1: Test-Pin Association Discovery via AST

Build the AST-based scanner that discovers which test functions exercise which pin-functions. This is the foundational mapping that all subsequent plans depend on.

**New file**: `scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py`

**Data structures**:

```python
@dataclass
class TestPinAssociation:
    """A discovered association between a test function and a pin-function."""
    test_file: str            # Path to the test file
    test_function: str        # Fully qualified test function name (e.g., "TestClass.test_method")
    pin_func_id: str          # The pin-function ID being exercised
    pin_function_name: str    # The pin-function's Python name
    association_type: str     # "direct_import", "indirect_call", "fixture_usage"
    confidence: float         # 0.0-1.0 confidence in the association

@dataclass
class TestPinMap:
    """Complete mapping of test functions to pin-functions."""
    associations: list[TestPinAssociation]
    scan_timestamp: str       # ISO-8601
    test_roots_scanned: list[str]  # Directories that were scanned
```

**Discovery algorithm**:

1. Accept a list of test file paths and a `PinFunctionRegistry`.
2. Build a lookup: `{function_name: pin_func_id}` from the registry's `pin_functions`.
3. For each test file:
   a. Parse with `ast.parse()`.
   b. Walk `ast.Import` and `ast.ImportFrom` nodes. If any imported name matches a pin-function's `function_name`, record the mapping: `imported_name -> pin_func_id`.
   c. Walk all `ast.FunctionDef` / `ast.AsyncFunctionDef` nodes whose name starts with `test_` or whose parent is a class whose name starts with `Test`.
   d. For each test function, walk its body looking for `ast.Call` nodes where the called name matches a mapped import. Record a `TestPinAssociation` with `association_type="direct_import"`.
   e. For fixture-based associations: if the test function has a parameter whose name matches a pin-function name, record with `association_type="fixture_usage"` and lower confidence (0.7).

**Key function**: `discover_test_pin_associations(test_files: list[Path], registry: PinFunctionRegistry) -> TestPinMap`

**Tests**: `scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_discovery.py`

- Test with a file that imports and calls a pin-function directly.
- Test with a class-based test (`TestFoo.test_bar`) that imports and calls a pin-function.
- Test with a file that imports from an atom module but does not call any pin-function (should produce no associations).
- Test with a file that uses a fixture whose name matches a pin-function (fixture_usage association).
- Test with zero test files (empty map).
- Test with a file that has a syntax error (graceful skip).

**Files changed**:
- NEW: `scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py`
- NEW: `scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_discovery.py`
- EDIT: `scripts/spec_manager/spec_manager/projection/lineage/__init__.py` -- add to `__all__`

### Plan 2: Test Signature Baselining and Persistence

Build the baseline extraction and JSON persistence layer. This plan takes the `TestPinMap` from Plan 1 and extracts the current signature of each associated test function, then stores it as a baseline artifact.

**New file**: `scripts/spec_manager/spec_manager/projection/lineage/test_pin_baseline.py`

**Data structures**:

```python
@dataclass
class TestSignatureBaseline:
    """Baseline signature of a single test function."""
    test_file: str
    test_function: str
    pin_func_id: str
    signature_hash: str       # MD5 hash from compute_signature_hash()
    signature_text: str       # Human-readable signature string for diagnostics
    recorded_at: str          # ISO-8601

@dataclass
class TestPinBaselineStore:
    """Persistent store of all test-pin signature baselines."""
    schema_version: str = "1.0"
    baselines: list[TestSignatureBaseline] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
```

**Key functions**:

1. `build_baseline(test_pin_map: TestPinMap) -> TestPinBaselineStore` -- For each `TestPinAssociation` in the map, call `compute_signature_hash(test_file, test_function)` to extract the signature hash. Also extract the human-readable signature string using `_extract_signature_parts()`. Return a `TestPinBaselineStore`.

2. `save_baseline(store: TestPinBaselineStore, path: Path) -> None` -- Serialize to JSON and write to disk. Default path: `.spec/test_pin_baselines.json`.

3. `load_baseline(path: Path) -> TestPinBaselineStore` -- Load from JSON. Return empty store if file does not exist.

4. `update_baseline(existing: TestPinBaselineStore, new_map: TestPinMap, force: bool = False) -> tuple[TestPinBaselineStore, list[str]]` -- Merge new associations into existing baselines. If `force=True`, overwrite changed signatures. Return updated store and list of change descriptions.

**Tests**: `scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_baseline.py`

- Test building baseline from a TestPinMap with known test files.
- Test round-trip save/load preserves all fields.
- Test load from nonexistent path returns empty store.
- Test update adds new baselines without overwriting existing ones.
- Test update with `force=True` overwrites changed signatures.
- Test that `compute_signature_hash` is called correctly for test function names (including class-qualified names like `TestFoo.test_method` -- note: `compute_signature_hash` searches for the bare function name in the AST, so a helper may be needed to handle methods inside test classes).

**Files changed**:
- NEW: `scripts/spec_manager/spec_manager/projection/lineage/test_pin_baseline.py`
- NEW: `scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_baseline.py`

### Plan 3: Test Signature Drift Detection

Build the drift comparison logic that compares current test signatures against the persisted baseline. Produces `PinDrift` records compatible with the existing drift reporting pipeline.

**Edit file**: `scripts/spec_manager/spec_manager/projection/lineage/drift_detector.py`

**Changes**:

1. Add `TEST_SIGNATURE_CHANGED = "test_signature_changed"` to `DriftKind` enum.

2. Add `DriftKind.TEST_SIGNATURE_CHANGED: "warning"` to `_DRIFT_SEVERITY`.

3. Add new method to `PinDriftDetector`:

```python
def detect_test_signature_drift(
    self,
    baseline_store: TestPinBaselineStore,
    current_map: TestPinMap,
) -> list[PinDrift]:
    """Check if test function signatures have changed since baseline.

    For each baseline entry, recompute the test function's signature hash
    and compare against the stored hash. Changes indicate the test
    contract has shifted.

    Args:
        baseline_store: Previously recorded test signature baselines.
        current_map: Current test-pin association map (for locating test files).

    Returns:
        List of PinDrift for each test whose signature changed.
    """
```

4. Extend `detect_all_drift()` to optionally accept baseline_store and current_map parameters (with `None` defaults to preserve backward compatibility) and include test drift results when provided.

**New file**: `scripts/spec_manager/spec_manager/projection/lineage/test_pin_checker.py`

High-level orchestration function that ties Plan 1 + Plan 2 + Plan 3 together:

```python
def check_test_pin_alignment(
    registry: PinFunctionRegistry,
    test_roots: list[Path],
    baseline_path: Path,
    update_baseline: bool = False,
) -> TestPinCheckResult:
    """Run full test-pin validation pipeline.

    1. Discover test-pin associations (Plan 1).
    2. Load existing baseline (Plan 2).
    3. Detect test signature drift (Plan 3).
    4. Optionally update baseline.

    Returns:
        TestPinCheckResult with drift findings and coverage stats.
    """
```

**Data structure**:

```python
@dataclass
class TestPinCheckResult:
    """Result of test-pin alignment check."""
    drift_items: list[PinDrift]
    total_pin_functions: int
    pin_functions_with_tests: int
    pin_functions_without_tests: int
    test_coverage_ratio: float  # pin_functions_with_tests / total_pin_functions
    associations_found: int
    baseline_updated: bool
```

**Tests**: `scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_checker.py`

- Test detecting drift when a test function's parameter list changes.
- Test detecting drift when a test function's return annotation changes.
- Test detecting drift when a test function is renamed (baseline entry becomes orphaned).
- Test no drift when test signatures match baseline.
- Test with no baseline file (all signatures are new -- no drift, but baseline created if `update_baseline=True`).
- Test coverage statistics are computed correctly.

**Files changed**:
- EDIT: `scripts/spec_manager/spec_manager/projection/lineage/drift_detector.py` -- add `TEST_SIGNATURE_CHANGED` to `DriftKind`, add `detect_test_signature_drift()` method
- NEW: `scripts/spec_manager/spec_manager/projection/lineage/test_pin_checker.py`
- NEW: `scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_checker.py`
- EDIT: `scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py` -- add tests for the new `DriftKind` value and `detect_test_signature_drift` method

### Plan 4: Compliance Gate Integration

Wire the test-pin check into the promotion gate system so it can block or warn during layer promotion.

**Changes to `compliance/promotion/config.py`**:
- Add `TEST_PIN_ALIGNMENT = "test_pin_alignment"` to `GateId` enum.
- In `PromotionGateConfig.default()`, set the new gate to `GateMode.ADVISORY` (warning, not blocker).

**New file**: `scripts/spec_manager/spec_manager/compliance/promotion/test_pin_gate.py`

```python
def check_test_pin_alignment_gate(
    registry: PinFunctionRegistry,
    test_roots: list[Path],
    baseline_path: Path,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Test signatures anchoring pin-functions have not drifted.

    Runs the test-pin checker and evaluates against gate thresholds.

    gate_spec.threshold: Minimum test-pin coverage ratio (default 0.0 = no minimum).
    gate_spec.params:
        - test_roots (list[str]): Override test directories.
        - update_baseline (bool): Whether to update baseline after check.

    Returns:
        GateCheckResult with findings for each drifted test signature.
    """
```

**Changes to `compliance/promotion/orchestrator.py`**:
- Import the new gate function.
- Add a step between the pin coverage check and the introduced algorithm spec check (step 2.5):
  ```python
  # 2.5 Test-pin alignment check
  gate_spec = self._config.get_gate(GateId.TEST_PIN_ALIGNMENT)
  if gate_spec.enabled:
      ...
  ```
- Add `TEST_PIN_ALIGNMENT` to `run_single_check()` dispatch table.

**Tests**: `scripts/spec_manager/tests/compliance/promotion/test_test_pin_gate.py`

- Test gate passes when no drift is detected.
- Test gate fails (advisory warning) when test signatures have drifted.
- Test gate produces findings with test file paths and pin-function IDs.
- Test gate is skipped when no PinFunctionRegistry is provided.
- Test coverage threshold enforcement (if configured).

**Files changed**:
- EDIT: `scripts/spec_manager/spec_manager/compliance/promotion/config.py` -- add `TEST_PIN_ALIGNMENT` to `GateId`
- NEW: `scripts/spec_manager/spec_manager/compliance/promotion/test_pin_gate.py`
- EDIT: `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py` -- add new gate step
- NEW: `scripts/spec_manager/tests/compliance/promotion/test_test_pin_gate.py`

### Plan 5: CLI Command

Add a `spec-manager pin test-check` subcommand that runs the test-pin validation pipeline from the command line.

**Changes to `pin_functions/cli.py`**:

Add a new subcommand in `setup_pin_parser()`:

```python
# pin test-check
p_test_check = pin_sub.add_parser(
    "test-check",
    help="Check test-pin alignment (test signatures as stable anchors)",
)
p_test_check.add_argument("--project-root", default=".", help="Project root directory")
p_test_check.add_argument(
    "--test-root", action="append", default=None,
    help="Test directory to scan (repeatable, default: tests/)",
)
p_test_check.add_argument(
    "--update-baseline", action="store_true",
    help="Update the baseline after checking",
)
p_test_check.add_argument(
    "--format", choices=["json", "text"], default="text",
    help="Output format",
)
```

Add handler `_cmd_pin_test_check(args)` that:

1. Resolves project root and test roots (default: `tests/` under project root).
2. Loads or scans the `PinFunctionRegistry`.
3. Resolves baseline path (default: `.spec/test_pin_baselines.json`).
4. Calls `check_test_pin_alignment()` from Plan 3.
5. Prints results in text or JSON format.
6. Returns exit code 0 if no drift, 1 if drift detected.

Add `"test-check": _cmd_pin_test_check` to the handlers dict in `handle_pin_command()`.

**Tests**: Manual verification via CLI invocation (the underlying logic is tested in Plans 1-4).

**Files changed**:
- EDIT: `scripts/spec_manager/spec_manager/pin_functions/cli.py` -- add `test-check` subcommand and handler

## Execution Instructions

Execute plans sequentially (Plan 1, then 2, then 3, then 4, then 5). Each plan builds on the prior:

- Plan 1 produces the test-pin association map.
- Plan 2 uses the map to build and persist baselines.
- Plan 3 uses both to detect drift and produces the orchestration function.
- Plan 4 wires the orchestration into the compliance gate system.
- Plan 5 exposes everything via CLI.

Run tests after each plan:

```bash
cd scripts/spec_manager
uv run pytest spec_manager/projection/lineage/tests/ -x --tb=short -p no:randomly
uv run pytest tests/compliance/promotion/ -x --tb=short -p no:randomly
```

## Success Criteria

1. **Test-pin discovery** correctly identifies test functions that import and call pin-function atoms, with at least 90% precision on the existing test suite (no false positives on non-atom imports).

2. **Baseline persistence** round-trips through JSON without data loss: `load(save(baseline)) == baseline`.

3. **Drift detection** catches all three categories of test signature change:
   - Parameter list modification (added, removed, or retyped parameter).
   - Return annotation change.
   - Test function rename (orphaned baseline entry).

4. **No regression** in existing drift detection: all tests in `test_drift_detector.py` continue to pass unchanged.

5. **Compliance gate** correctly reports `TEST_PIN_ALIGNMENT` findings in `PromotionReport` when test signatures drift, and passes cleanly when they do not.

6. **CLI** `spec-manager pin test-check` exits 0 on clean baseline, exits 1 with human-readable output when drift is detected.

7. **Test coverage**: each new module has a corresponding test file with at least one test per public function.

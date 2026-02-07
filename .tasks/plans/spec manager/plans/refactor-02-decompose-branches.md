# Implementation Plan: Decompose branches/ to Delegate to Existing Modules

## Overview

The `branches/` package is a 13-module standalone system that reimplements functionality already present in `compliance/`, `analysis/`, `core/`, and `projection/`. This plan decomposes `branches/` so each module either delegates to the canonical implementation, is retained as genuinely unique, or is removed as pure duplication.

## Current State (Problems)

The `branches/` package (`scripts/spec_manager/spec_manager/branches/`) contains 13 modules:

| Module | Lines | Purpose |
|---|---|---|
| `types.py` | 208 | Enums (BranchKind, AtomKind, StoreType, ProjectionType, SliceOrientation) and dataclasses (AtomDescriptor, PinFunction, VerticalSlice) |
| `layout.py` | 102 | Directory structure creation/validation for branch directories |
| `atoms.py` | 128 | Atom registry with CRUD, hash-based change detection, JSON persistence |
| `pins.py` | 283 | Pin registry with forward/backward trace, drift detection, coverage analysis, JSON persistence |
| `analysis.py` | 377 | Analysis branch generator: lineage table, adjacency graph, drift report |
| `compliance.py` | 265 | Compliance gate checks: no comments, no stubs, tests pass, call graph connected, store monogamy |
| `promotion.py` | 209 | Promotion workflow: compliance gate -> identify changed atoms -> project -> create pins |
| `gap_detection.py` | 259 | Gap detection: comment scanning, stub detection, runtime error detection |
| `downward_flow.py` | 211 | Issue tracing from architectural locations back to atoms via pins |
| `collapse.py` | 392 | Codebase collapse to Layer 1: AST-based function classification |
| `slices.py` | 380 | Vertical/horizontal slice navigation, store monogamy validation |
| `manager.py` | 324 | Unified facade wiring all subsystems together |
| `__init__.py` | 64 | Re-exports |

**The core problem**: These modules reimplement (with less sophistication) functionality that exists in:

1. **`compliance/promotion/`** (8 modules, ~900 lines) -- Production-grade promotion gating with configurable gate modes (REQUIRED/ADVISORY), per-gate thresholds, timing metrics, and 10 distinct gate checks vs. `branches/compliance.py` and `branches/promotion.py` which have only 5 hardcoded gates and no configurability.

2. **`compliance/detection/`** (6 modules, ~850 lines) -- Full executable gap detection with comment scanner (handles 8+ excluded prefixes, enclosing function resolution), stub scanner (structured StubFunction output with qualified names), runtime detector (subprocess probing), call graph builder (proper CallGraph data structure with BFS components), and coverage analyzer vs. `branches/gap_detection.py` which has a simpler version of the same three scanners.

3. **`analysis/adjacency/`** (7+ modules) -- Weighted signal-typed graph (`AdjacencyGraph`) with 5 signal types, connected component analysis, isolation classification (3-tier), bridge candidate detection vs. `branches/analysis.py` which reimplements union-find and store-touch analysis with a flat list structure.

4. **`core/pin_registry.py`** -- O(1) indexed `PinRegistryIndex` with forward/reverse import graph traversal, MicroAddress resolution, and affected location queries vs. `branches/pins.py` which uses linear scans for all lookups.

5. **`analysis/ast_extractor.py`** -- Production `AtomFunctionExtractor` with convention/heuristic/annotation detection, shape detection, store reference detection, and body hashing vs. `branches/collapse.py` and `branches/atoms.py` which reimplement simpler versions of the same AST heuristics.

6. **`schemas/pin_functions.py`** -- Pydantic `PinFunction`, `ImportEdge`, `MicroAddress`, `PinFunctionRegistry` schemas vs. `branches/types.py` which defines parallel dataclass-based `PinFunction` and `AtomDescriptor` types.

7. **`projection/`** -- Full drift detection (`projection/drift.py`, `projection/lineage/drift_detector.py`) and change propagation (`projection/pin_propagation.py`) vs. `branches/pins.py` which reimplements simpler drift detection and `branches/downward_flow.py` which reimplements simpler issue tracing.

**Only one caller exists**: `refinement/workspace/manager.py` lazily imports `BranchManager` and exposes it via a `.branches` property.

**No tests exist** for any `branches/` module.

## Target State

- `branches/` retains only genuinely unique functionality (layout management, slice navigation, unified facade)
- All duplicated logic delegates to the canonical modules in `compliance/`, `analysis/`, `core/`, `projection/`
- Type system uses existing `schemas/pin_functions.py` Pydantic models where possible
- `branches/`-specific dataclasses remain only where they serve a distinct purpose (VerticalSlice, HorizontalLayer)
- The single caller (`workspace/manager.py`) continues to work unchanged

## Additional Info

### Data Structure Mapping

| branches/ type | Canonical type | Relationship |
|---|---|---|
| `branches.types.PinFunction` (dataclass) | `schemas.pin_functions.PinFunction` (Pydantic) | DUPLICATE -- different fields but same concept. branches version has `atom_id` + `architectural_location` + `wrapper_hash`; schema version has `module_path` + `line_start/end` + `content_hash` + `store_touches`. |
| `branches.types.AtomDescriptor` (dataclass) | `analysis.ast_extractor.AtomCandidate` | OVERLAP -- AtomDescriptor is a registry record; AtomCandidate is an extraction result. Different lifecycles. |
| `branches.types.ProjectionType` (enum) | `schemas.pin_functions.ProjectionType` (Literal) | DUPLICATE -- branches uses enum with 4 values (PASS_THROUGH, PROJECTION, AGGREGATION, INTRODUCTION); schema uses Literal with 4 values (PASS_THROUGH, WRAP, SMEAR, INTRODUCTION). Values differ. |
| `branches.pins.DriftReport` (dataclass) | `projection.lineage.drift_detector.PinDrift` | DUPLICATE -- same concept, different structure. |
| `branches.gap_detection.GapItem` | `compliance.detection.comment_scanner.CommentGap` / `stub_scanner.StubFunction` | DUPLICATE -- GapItem is a generic gap; canonical modules have typed gap structures. |
| `branches.compliance.ComplianceGateResult` | `compliance.promotion.result.PromotionReport` | DUPLICATE -- ComplianceGateResult has 5 booleans; PromotionReport has configurable gate results with scores. |
| `branches.types.VerticalSlice` | (no equivalent) | UNIQUE to branches |
| `branches.slices.HorizontalLayer` | (no equivalent) | UNIQUE to branches |
| `branches.types.BranchKind` | (no equivalent) | UNIQUE to branches |
| `branches.types.SliceOrientation` | (no equivalent) | UNIQUE to branches |

### Key Design Constraint

The `branches/` module serves the "design doc" concept of a branch organization system with algorithmic/architectural/analysis layers. The canonical modules were built independently for the same concepts. The adapter layer must bridge the `branches/` facade API (used by `BranchManager`) to the canonical implementations without breaking the facade contract.

## Module Classification

### DELEGATE (6 modules -- keep module, replace internals)

1. **`branches/compliance.py`** -- Delegate to `compliance/promotion/orchestrator.py`
2. **`branches/promotion.py`** -- Delegate to `compliance/promotion/orchestrator.py`
3. **`branches/gap_detection.py`** -- Delegate to `compliance/detection/`
4. **`branches/analysis.py`** -- Delegate to `analysis/adjacency/` and `projection/lineage/`
5. **`branches/pins.py`** -- Delegate to `core/pin_registry.py` and `projection/pin_propagation.py`
6. **`branches/collapse.py`** -- Delegate to `analysis/ast_extractor.py`

### UNIQUE (5 modules -- genuinely new, keep as-is)

7. **`branches/types.py`** -- Domain enums (BranchKind, AtomKind, StoreType, SliceOrientation) and VerticalSlice are unique to the branch organization concept. PinFunction and ProjectionType overlap but serve a different facade contract.
8. **`branches/layout.py`** -- Directory structure management is unique to branches.
9. **`branches/slices.py`** -- Vertical/horizontal slice navigation is unique.
10. **`branches/downward_flow.py`** -- Issue tracing concept is unique as a facade, though internals should delegate to pin registry.
11. **`branches/manager.py`** -- Unified facade, must remain.

### REMOVE (2 modules)

12. **`branches/atoms.py`** -- Pure duplication of a simple registry pattern. Callers should use the AtomFunctionExtractor from `analysis/ast_extractor.py` for extraction and a simplified internal registry within `manager.py` for runtime lookup. However, since `atoms.py` serves as the in-memory atom store for the facade (register, get, list, save/load), it has a distinct lifecycle role. **Reclassified to UNIQUE** -- keep for now, but mark for future consolidation.
13. **`branches/__init__.py`** -- Re-exports, will be updated to match whatever remains.

**Final classification**: 6 DELEGATE, 6 UNIQUE, 1 UPDATE-ONLY (`__init__.py`).

## Plans

### Plan 1: Delegate `branches/gap_detection.py` to `compliance/detection/`

**Rationale**: Lowest risk. `GapDetector` reimplements comment scanning, stub detection, and runtime error detection that already exist in more sophisticated form in `compliance/detection/comment_scanner.py`, `stub_scanner.py`, and `runtime_detector.py`.

**Changes**:

1. **`branches/gap_detection.py`** -- Replace method bodies with delegation:
   - `find_unimplemented_comments(filepath)` -> call `compliance.detection.comment_scanner.scan_comments(filepath)` and convert `CommentGap` results to `GapItem` format
   - `detect_stubs(filepath)` -> call `compliance.detection.stub_scanner.scan_stubs(filepath)` and convert `StubFunction` results to `GapItem` format
   - `detect_runtime_errors(filepath)` -> keep as-is (no exact equivalent in detection; `runtime_detector.py` probes at runtime via subprocess, which is a different approach)
   - `scan_branch(algorithmic_dir)` -> call `compliance.detection.orchestrator.scan_executable_gaps()` with appropriate config, convert `ExecutableGapReport` to list of `GapItem`
   - Keep `GapItem` dataclass unchanged (it is the facade's return type)

2. **Adapter code needed**:
   ```python
   def _comment_gap_to_gap_item(cg: CommentGap) -> GapItem:
       return GapItem(file=cg.file_path, line=cg.line, text=cg.text, gap_type="unimplemented_comment")
   
   def _stub_to_gap_item(sf: StubFunction) -> GapItem:
       return GapItem(file=sf.file_path, line=sf.line, text=f"Stub function: {sf.name} ({sf.stub_type})", gap_type="stub_function")
   ```

3. **Verification**: The `ComplianceChecker` in `branches/compliance.py` calls `self._gap_detector.find_unimplemented_comments()` and `self._gap_detector.detect_stubs()`. These must continue to return `list[GapItem]` with the same fields.

**Files modified**:
- `scripts/spec_manager/spec_manager/branches/gap_detection.py`

### Plan 2: Delegate `branches/compliance.py` to `compliance/promotion/`

**Rationale**: `ComplianceChecker.check_all()` reimplements the same 5 algorithmic gates that `compliance/promotion/algorithmic_gates.py` implements more robustly.

**Changes**:

1. **`branches/compliance.py`** -- Replace `ComplianceChecker` internals:
   - `check_no_comments()` -> call `compliance.promotion.algorithmic_gates.check_no_remaining_comments()`, adapting the file list from `BranchLayout.algorithmic_dir()`
   - `check_no_stubs()` -> call `check_no_stub_functions()`
   - `check_tests_pass()` -> call `check_all_tests_pass()` (with a configurable test command)
   - `check_call_graph_connected()` -> call `check_call_graph_connected()`
   - `check_store_monogamy()` -> keep current implementation (it operates on VerticalSlice objects which have no equivalent in the canonical module's file-based approach)
   - Keep `ComplianceGateResult` dataclass unchanged

2. **Adapter code needed**:
   - A helper to collect `.py` files from `BranchLayout.algorithmic_dir()` into `list[Path]` (the canonical functions expect file lists, not a directory)
   - A `GateSpec` factory that creates default gate specs for each check
   - Convert `GateCheckResult` to the `(passed, errors)` tuple format that the existing branches API returns

3. **Dependencies**: Plan 1 should complete first (gap_detection delegation), since `ComplianceChecker.__init__` creates a `GapDetector` instance.

**Files modified**:
- `scripts/spec_manager/spec_manager/branches/compliance.py`

### Plan 3: Delegate `branches/promotion.py` to `compliance/promotion/`

**Rationale**: `PromotionEngine.promote()` reimplements the promotion workflow. The canonical `LayerPromotionGate.run_all_checks()` is more comprehensive (10 gates vs 5).

**Changes**:

1. **`branches/promotion.py`** -- Replace `PromotionEngine` internals:
   - `_check_compliance()` -> instantiate `LayerPromotionGate` with `PromotionGateConfig.default()` and call `run_all_checks()`, then convert `PromotionReport` to `ComplianceGateResult`
   - `_identify_changed_atoms()` -> keep as-is (operates on branches-specific `AtomRegistry` and `PinRegistry`)
   - `_project_atom()` -> keep as-is (creates branches-specific `PinFunction` dataclass instances)
   - Keep `PromotionResult` dataclass unchanged

2. **Adapter code needed**:
   - Convert `PromotionReport` (canonical) to `ComplianceGateResult` (branches):
     ```python
     def _promotion_report_to_compliance_result(report: PromotionReport) -> ComplianceGateResult:
         gate_map = {gid.value: False for gid in GateId}
         for gr in report.gate_results:
             gate_map[gr.gate_id] = gr.passed
         return ComplianceGateResult(
             passed=report.passed,
             no_comments=gate_map.get("no_remaining_comments", True),
             no_stubs=gate_map.get("no_stub_functions", True),
             tests_pass=gate_map.get("all_tests_pass", True),
             call_graph_connected=gate_map.get("call_graph_connected", True),
             store_monogamy=gate_map.get("store_monogamy", True),
             errors=[b.summary for b in report.blockers],
             warnings=[w.summary for w in report.warnings],
         )
     ```

3. **Dependencies**: Plan 2 should complete first.

**Files modified**:
- `scripts/spec_manager/spec_manager/branches/promotion.py`

### Plan 4: Delegate `branches/pins.py` drift detection to `projection/`

**Rationale**: `PinRegistry.detect_drift()` reimplements drift detection that exists in `projection/lineage/drift_detector.py` and `projection/pin_propagation.py`. The forward/backward trace and coverage analysis in `branches/pins.py` overlap with `core/pin_registry.py`.

**Changes**:

1. **`branches/pins.py`** -- Replace `detect_drift()` internals:
   - `detect_drift()` currently compares content hashes and generates `DriftReport` objects. Delegate to `projection.pin_propagation.detect_pin_changes()` or keep the simple hash comparison (which is lightweight and self-contained).
   - **Decision**: Keep the simple hash comparison in `detect_drift()` since the branches version operates on its own `AtomRegistry` data model. The canonical drift detector operates on `ProjectionLineageTable` and `AtomDefinition` types, making adaptation heavier than the value gained.
   - However, add a `to_canonical()` method on `DriftReport` that can produce a `DriftItem` for interop.

2. **Forward/backward trace optimization**:
   - `get_architectural_locations(atom_id)` and `get_atom_for_location()` are O(n) linear scans. For small registries (typical in branches), this is fine. For future optimization, note that `core/pin_registry.py:PinRegistryIndex` provides O(1) lookups.
   - Add a comment indicating the canonical O(1) alternative exists in `core.pin_registry.PinRegistryIndex`.

3. **No API change** -- all methods keep their signatures.

**Files modified**:
- `scripts/spec_manager/spec_manager/branches/pins.py` (documentation + optional interop method)

### Plan 5: Delegate `branches/analysis.py` to `analysis/adjacency/` and `projection/lineage/`

**Rationale**: `AnalysisGenerator` reimplements union-find for disconnected subgraphs, store-touch edge building, and adjacency computation. The canonical `analysis/adjacency/graph.py:AdjacencyGraph` and `detector.py` do this with signal-typed weighted edges and three-tier isolation classification.

**Changes**:

1. **`branches/analysis.py`** -- Replace internal analysis with delegation:
   - `_find_disconnected_subgraphs()` -> build an `AdjacencyGraph`, populate with slice co-occurrence edges, call `graph.connected_components()`, convert back to `list[list[str]]`
   - `_build_store_touch_edges()` -> build store-touch edges via `AdjacencyGraph.add_edge()` with `SignalType.STORE_TOUCH` signals, then extract the edge list
   - `_analyze_atom()` -> keep mostly as-is since it operates on branches-specific types, but use `AdjacencyGraph` for adjacency computation
   - Keep `AnalysisArtifact`, `AnalysisReport` dataclasses unchanged
   - Keep `write_lineage_table()`, `write_adjacency_graph()`, `write_drift_report()` unchanged (they are serialization logic)

2. **Adapter code needed**:
   ```python
   from spec_manager.analysis.adjacency.graph import AdjacencyGraph, EdgeSignal, SignalType
   
   def _build_adjacency_graph(atoms, slices, store_atom_map) -> AdjacencyGraph:
       graph = AdjacencyGraph()
       # Add co-occurrence edges from slices
       for vs in slices:
           for i, aid_a in enumerate(vs.atom_ids):
               for aid_b in vs.atom_ids[i+1:]:
                   graph.add_edge(aid_a, aid_b, EdgeSignal(SignalType.CO_OCCURRENCE, 1.0))
       # Add store-touch edges
       for store_id, touching in store_atom_map.items():
           for aid in touching:
               graph.add_edge(aid, store_id, EdgeSignal(SignalType.STORE_TOUCH, 1.0))
       return graph
   ```

3. **Dependencies**: None (independent of Plans 1-4).

**Files modified**:
- `scripts/spec_manager/spec_manager/branches/analysis.py`

### Plan 6: Delegate `branches/collapse.py` to `analysis/ast_extractor.py`

**Rationale**: `CollapseEngine._classify_function()` reimplements shape detection, store detection, and function classification that `AtomFunctionExtractor` already provides with more sophistication (convention/heuristic/annotation detection modes, `_IO_FUNCTIONS` set, `_STORE_PATTERNS` set).

**Changes**:

1. **`branches/collapse.py`** -- Replace classification and extraction with delegation:
   - `_classify_function()` -> use `AtomFunctionExtractor.is_shape()` for shape detection, `AtomFunctionExtractor.detect_store_references()` for store detection, and the existing `_ARCH_INDICATORS` check for architectural filtering
   - `_extract_atom()` -> use `AtomFunctionExtractor.extract_signature()` and `AtomFunctionExtractor.compute_body_hash()` instead of reimplementing
   - `_has_side_effects()` and `_has_external_calls()` -> replace with `AtomFunctionExtractor.is_shape()` (which checks the same things plus yield/generator detection)
   - Keep `CollapseResult` and `CollapseEngine.collapse()` orchestration unchanged
   - Keep `_ARCH_INDICATORS` (unique to collapse context)

2. **Adapter code needed**:
   ```python
   from spec_manager.analysis.ast_extractor import AtomFunctionExtractor, ExtractionConfig
   
   # In CollapseEngine.__init__:
   self._extractor = AtomFunctionExtractor(ExtractionConfig(
       require_docstring=False,  # Collapse should not require docstrings
       max_function_lines=999,   # No line limit during collapse
   ))
   ```

3. **Dependencies**: None (independent of Plans 1-5).

**Files modified**:
- `scripts/spec_manager/spec_manager/branches/collapse.py`

### Plan 7: Update `__init__.py` and add delegation documentation

**Rationale**: After all delegations are in place, update the package-level exports and add documentation explaining the delegation pattern.

**Changes**:

1. **`branches/__init__.py`** -- No API changes needed (all public types are preserved). Add a module docstring explaining the delegation pattern.

2. **Add `branches/README.md`** -- Document which modules delegate and to where, for future maintainers.

3. **Verify workspace integration** -- Confirm that `refinement/workspace/manager.py` still works correctly by tracing the `BranchManager` usage.

**Files modified**:
- `scripts/spec_manager/spec_manager/branches/__init__.py`
- `scripts/spec_manager/spec_manager/branches/README.md` (new)

## Execution Instructions

Execute plans in order: Plan 1, Plan 2, Plan 3, Plan 4, Plan 5, Plan 6, Plan 7.

Plans 1-3 form a dependency chain (gap_detection -> compliance -> promotion).
Plans 4-6 are independent of each other and of Plans 1-3.
Plan 7 is a final cleanup that depends on all prior plans.

A safe parallel execution order is:
- Phase A: Plans 1, 4, 5, 6 (independent)
- Phase B: Plan 2 (depends on Plan 1)
- Phase C: Plan 3 (depends on Plan 2)
- Phase D: Plan 7 (depends on all)

For each plan:
1. Read the target module and the canonical module it will delegate to
2. Implement the adapter functions
3. Replace the method bodies with delegation calls
4. Run verification commands (below)
5. Confirm no import errors and the public API is unchanged

## Import Rewrites Needed

After delegation, `branches/` modules will gain these new imports:

| Module | New Imports |
|---|---|
| `gap_detection.py` | `from spec_manager.compliance.detection.comment_scanner import scan_comments, CommentGap` |
| | `from spec_manager.compliance.detection.stub_scanner import scan_stubs, StubFunction` |
| `compliance.py` | `from spec_manager.compliance.promotion.algorithmic_gates import check_no_remaining_comments, check_no_stub_functions, check_all_tests_pass, check_call_graph_connected` |
| | `from spec_manager.compliance.promotion.config import GateSpec, GateId` |
| | `from spec_manager.compliance.promotion.result import GateCheckResult` |
| `promotion.py` | `from spec_manager.compliance.promotion.orchestrator import LayerPromotionGate` |
| | `from spec_manager.compliance.promotion.config import PromotionGateConfig` |
| | `from spec_manager.compliance.promotion.result import PromotionReport` |
| `analysis.py` | `from spec_manager.analysis.adjacency.graph import AdjacencyGraph, EdgeSignal, SignalType` |
| `collapse.py` | `from spec_manager.analysis.ast_extractor import AtomFunctionExtractor, ExtractionConfig` |

No external callers import from `branches/` submodules directly (the only external import is `from spec_manager.branches.manager import BranchManager` in `workspace/manager.py`), so no import rewrites are needed outside the `branches/` package.

## Test Updates

**Current state**: No tests exist for `branches/`. This is a risk for the refactoring.

**Recommended approach**:
1. Before starting Plan 1, write characterization tests for each module's public API by instantiating `BranchManager` with a temp directory and exercising the full lifecycle (initialize -> register atoms -> register pins -> check compliance -> promote -> trace issue -> collapse codebase -> regenerate analysis -> save/load)
2. After each plan, re-run characterization tests to verify behavior is preserved
3. Test file location: `scripts/spec_manager/spec_manager/branches/tests/test_branch_manager.py`

## Verification Commands

```bash
# 1. Check no import errors in branches package
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager
uv run python -c "from spec_manager.branches import BranchManager; print('OK')"

# 2. Check no import errors in workspace integration
uv run python -c "from spec_manager.refinement.workspace.manager import WorkspaceManager; print('OK')"

# 3. Type check the branches package
uv run mypy spec_manager/branches/ --ignore-missing-imports

# 4. Run any existing tests that might exercise branches indirectly
uv run pytest -x --tb=short -p no:randomly

# 5. Verify canonical modules still import cleanly (no circular deps introduced)
uv run python -c "
from spec_manager.compliance.detection import scan_executable_gaps
from spec_manager.compliance.promotion import LayerPromotionGate
from spec_manager.analysis.adjacency.graph import AdjacencyGraph
from spec_manager.analysis.ast_extractor import AtomFunctionExtractor
from spec_manager.core.pin_registry import PinRegistryIndex
print('All canonical imports OK')
"
```

## Success Criteria

1. All 6 DELEGATE modules have their core logic replaced with calls to canonical modules
2. The `BranchManager` public API is unchanged -- all method signatures and return types are identical
3. `from spec_manager.branches import BranchManager` works without import errors
4. `refinement/workspace/manager.py` creates and uses `BranchManager` without errors
5. No circular import dependencies are introduced between `branches/` and the canonical modules
6. Each delegating module's adapter code is fewer than 30 lines (the goal is thin wrappers, not new complexity)
7. All characterization tests pass before and after each plan
8. The `branches/__init__.__all__` list remains unchanged

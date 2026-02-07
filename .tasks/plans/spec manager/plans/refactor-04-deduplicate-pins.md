# Implementation Plan

## Overview

Deduplicate the pin-related registries, schemas, and edge types scattered across five modules into canonical locations, eliminating redundant type definitions and inconsistent naming while preserving the distinct responsibilities of each subsystem.

## Current State (Problems)

There are **three independent "PinFunction" types**, **two independent "ProjectionType" enums**, **three independent import-edge types**, and **two independent registry classes** -- all representing overlapping concepts with incompatible field names and serialization:

### Type Inventory

| Type | Location | Base | Fields | Consumers |
|---|---|---|---|---|
| `PinFunction` | `schemas/pin_functions.py` | Pydantic `BaseModel` | `pin_func_id`, `function_name`, `module_path`, `file_path`, `line_start`, `line_end`, `signature`, `docstring`, `content_hash`, `is_shape`, `store_touches`, `evidence_atom_ids` | `core/pin_registry.py`, `pin_functions/orchestrator.py`, `analysis/import_graph.py`, `projection/pin_propagation.py`, `compliance/promotion/{pin_coverage,provenance,architectural_quality,orchestrator}.py`, all labyrinth tests, compliance promotion tests |
| `PinFunction` | `branches/types.py` | `@dataclass` | `pin_id`, `atom_id`, `architectural_location`, `projection_type`, `confidence`, `wrapper_hash` | `branches/pins.py`, `branches/promotion.py`, `branches/analysis.py`, `branches/downward_flow.py`, `branches/manager.py`, `branches/__init__.py` |
| `PinFunctionSchema` | `schemas/pin_function.py` (singular) | Pydantic `BaseModel` | `pin_id`, `atom_id`, `architectural_location`, `projection_type`, `confidence`, `wrapper_hash` | **Zero imports found** -- completely unused |

| Enum/Type | Location | Values | Consumers |
|---|---|---|---|
| `ProjectionType` (Literal) | `schemas/pin_functions.py` | `PASS_THROUGH`, `WRAP`, `SMEAR`, `INTRODUCTION` | Same as `schemas/pin_functions.PinFunction` consumers |
| `ProjectionType` (Enum) | `branches/types.py` | `pass_through`, `projection`, `aggregation`, `introduction` | Same as `branches/types.PinFunction` consumers |
| `TransformationType` (Enum) | `projection/lineage/edges.py` | `pass_through`, `event_bridge`, `middleware_wrap`, `retry_decorate`, `slice`, `smear`, `introduction` | `projection/lineage/{table,builder,drift_detector,data_flow,persistence}.py`, lineage tests |

| Registry | Location | Type | Responsibility |
|---|---|---|---|
| `PinRegistryIndex` | `core/pin_registry.py` | `@dataclass` | In-memory O(1) lookup index for `schemas/pin_functions.PinFunctionRegistry`; forward/reverse import graph traversal; micro-address resolution |
| `PinRegistry` | `branches/pins.py` | Class | Branch-aware pin registry with persistence; forward/backward atom trace; drift detection; coverage analysis; PIN-#### ID allocation; JSON save/load |

| Import Edge | Location | Base | Fields |
|---|---|---|---|
| `ImportEdge` | `schemas/pin_functions.py` | Pydantic `BaseModel` | `edge_id`, `pin_func_id`, `arch_location`, `arch_file_path`, `arch_line`, `projection_type`, `confidence`, `is_direct_import` |
| `ImportEdge` | `projection/lineage/import_graph.py` | `@dataclass` | `importer_file`, `importer_location`, `imported_name`, `imported_from_module`, `imported_from_file`, `line_no`, `is_direct` |
| `ProjectionLineageEdge` | `projection/lineage/edges.py` | `@dataclass` | `from_unit`, `to_unit`, `transformation`, `confidence`, `timestamp`, `details`, `pin_id` |

### Key Problems

1. **`schemas/pin_function.py` (singular) is dead code**: `PinFunctionSchema` has zero imports anywhere in the codebase. It duplicates the fields of `branches/types.PinFunction` with Pydantic validation.

2. **Two `PinFunction` types with completely different schemas**: The `schemas/pin_functions.py` version (PFUNC-#### IDs, 12 fields, code-location-centric) and the `branches/types.py` version (PIN-#### IDs, 6 fields, atom-to-arch-mapping-centric) represent different conceptual levels but share the same name, causing confusion.

3. **Three `ProjectionType` definitions with inconsistent values**: `WRAP` vs `projection`, `SMEAR` vs `aggregation` -- these represent the same concepts with different names, making it impossible to pass values between subsystems.

4. **Three `ImportEdge` types**: `schemas/pin_functions.ImportEdge` (pin-function import graph edge), `projection/lineage/import_graph.ImportEdge` (raw Python import edge), and `ProjectionLineageEdge` (lineage transformation edge) all model "edge from A to B" but with different semantics and field names.

5. **Two registries that don't know about each other**: `PinRegistryIndex` indexes `PinFunctionRegistry` data. `PinRegistry` manages branch-level pins. Neither delegates to the other.

## Target State

1. **Single `PinFunction` schema** in `schemas/pin_functions.py` (the Pydantic version) -- this is the canonical definition for code-level pin-functions (PFUNC-####).
2. **Rename `branches/types.PinFunction` to `PinProjection`** to clarify it represents a pin-to-architecture projection mapping (PIN-####), not a pin-function itself. This is a semantically different concept.
3. **Delete `schemas/pin_function.py`** (singular) -- it is dead code.
4. **Unify ProjectionType values** into a single canonical enum, keeping `TransformationType` as a finer-grained superset for lineage tracking.
5. **Keep both registries** but clarify their roles: `PinRegistryIndex` for read-only querying, `PinRegistry` for mutable branch-level operations with persistence.
6. **Keep all three ImportEdge types** as they model genuinely different concepts (pin-function import edges, raw Python import edges, lineage transformation edges), but add clear documentation distinguishing them.

## Additional Info

- The `branches/` subsystem is a self-contained module with its own `types.py`. Its `PinFunction` is consumed only within `branches/` and re-exported via `branches/__init__.py`. The rename to `PinProjection` is local to that module.
- `TransformationType` in lineage is intentionally finer-grained than `ProjectionType` (e.g., `event_bridge`, `middleware_wrap`, `retry_decorate` are all "WRAP" at the schema level). This is complementary, not duplicative.
- `schemas/pin_function.py` (singular) has Pydantic field validators (`validate_pin_id`, `validate_confidence`) that could be migrated to `branches/types.PinFunction` (renamed to `PinProjection`) if validation is desired there.
- The `projection/lineage/import_graph.ImportEdge` is a raw AST import analysis result; `schemas/pin_functions.ImportEdge` is a higher-level pin-function-to-architecture mapping. These are different abstraction levels.

## Plans

### Plan 1: Delete Dead Code (`schemas/pin_function.py`)

**Rationale**: `PinFunctionSchema` in `schemas/pin_function.py` has zero imports. Remove it.

**Steps**:

1. Verify zero imports with: `grep -r "from spec_manager.schemas.pin_function import" scripts/spec_manager/` and `grep -r "from spec_manager.schemas import pin_function" scripts/spec_manager/`
2. Delete `scripts/spec_manager/spec_manager/schemas/pin_function.py`
3. If `schemas/__init__.py` re-exports it, remove the re-export
4. Run full test suite to confirm no breakage

**Files changed**:
- DELETE: `scripts/spec_manager/spec_manager/schemas/pin_function.py`
- MAYBE: `scripts/spec_manager/spec_manager/schemas/__init__.py` (if it re-exports)

### Plan 2: Rename `branches/types.PinFunction` to `PinProjection`

**Rationale**: Having two types named `PinFunction` with different schemas is the core confusion. The `branches/types.py` version represents a projection (atom -> arch location mapping), not a pin-function itself. Renaming it to `PinProjection` clarifies the distinction.

**Steps**:

1. In `scripts/spec_manager/spec_manager/branches/types.py`:
   - Rename class `PinFunction` to `PinProjection`
   - Update `to_dict()` and `from_dict()` class references

2. Update all consumers within `branches/`:
   - `branches/pins.py`: `PinFunction` -> `PinProjection` (import and all references in `PinRegistry`)
   - `branches/promotion.py`: `PinFunction` -> `PinProjection` (import and `PromotionEngine._project_atom` return type, `PromotionResult` type annotations)
   - `branches/analysis.py`: `PinFunction` -> `PinProjection` (import and `AnalysisArtifact.architectural_imports` type, `AnalysisGenerator._analyze_atom`)
   - `branches/downward_flow.py`: `PinFunction` -> `PinProjection` (import and all references)
   - `branches/manager.py`: `PinFunction` -> `PinProjection` (import and all references)
   - `branches/__init__.py`: Update re-export from `PinFunction` to `PinProjection`

3. Search for any external consumers of `branches.PinFunction` (none found, but verify):
   - `grep -r "from spec_manager.branches import.*PinFunction" scripts/spec_manager/tests/`
   - `grep -r "from spec_manager.branches.types import.*PinFunction" scripts/spec_manager/tests/`

4. Run full test suite

**Files changed**:
- `scripts/spec_manager/spec_manager/branches/types.py` (rename class)
- `scripts/spec_manager/spec_manager/branches/pins.py` (update imports and references)
- `scripts/spec_manager/spec_manager/branches/promotion.py` (update imports and references)
- `scripts/spec_manager/spec_manager/branches/analysis.py` (update imports and references)
- `scripts/spec_manager/spec_manager/branches/downward_flow.py` (update imports and references)
- `scripts/spec_manager/spec_manager/branches/manager.py` (update imports and references)
- `scripts/spec_manager/spec_manager/branches/__init__.py` (update re-export)

### Plan 3: Unify ProjectionType Definitions

**Rationale**: Three separate definitions with inconsistent values (`WRAP` vs `projection`, `SMEAR` vs `aggregation`) make cross-subsystem communication impossible. Create a single canonical `ProjectionType` enum in `schemas/pin_functions.py` and make other modules reference it.

**Steps**:

1. In `scripts/spec_manager/spec_manager/schemas/pin_functions.py`:
   - Convert the current `Literal` type alias to a proper `str` Enum (or keep as `Literal` and update values for consistency)
   - Canonical values: `"PASS_THROUGH"`, `"WRAP"`, `"SMEAR"`, `"INTRODUCTION"` (the current values in `schemas/pin_functions.py`)

2. In `scripts/spec_manager/spec_manager/branches/types.py`:
   - Remove the local `ProjectionType` Enum class
   - Import `ProjectionType` from `schemas.pin_functions` OR define a mapping function
   - **Decision point**: The branches `ProjectionType` has `projection` and `aggregation` values that do not exist in the schemas version. These need either:
     - (a) Addition to the canonical set (add `PROJECTION`, `AGGREGATION` alongside `WRAP`, `SMEAR`), or
     - (b) A documented mapping (`projection` -> `WRAP`, `aggregation` -> `SMEAR`)
   - Recommended: Option (a) -- expand the canonical `ProjectionType` to include all values from both definitions: `PASS_THROUGH`, `WRAP`, `SMEAR`, `PROJECTION`, `AGGREGATION`, `INTRODUCTION`. This avoids lossy mappings.

3. Update `scripts/spec_manager/spec_manager/branches/types.py`:
   - Remove local `ProjectionType` Enum
   - Add: `from spec_manager.schemas.pin_functions import ProjectionType`
   - Update `PinProjection` (formerly `PinFunction`) to use string values from the canonical set

4. Leave `TransformationType` in `projection/lineage/edges.py` as-is -- it is intentionally a finer-grained superset for lineage tracking. Add a docstring cross-reference to `ProjectionType`.

5. Update all branch consumers that construct `ProjectionType` enum values to use the new canonical values.

6. Run full test suite

**Files changed**:
- `scripts/spec_manager/spec_manager/schemas/pin_functions.py` (expand `ProjectionType`)
- `scripts/spec_manager/spec_manager/branches/types.py` (remove local `ProjectionType`, import canonical)
- `scripts/spec_manager/spec_manager/branches/pins.py` (update import path for `ProjectionType`)
- `scripts/spec_manager/spec_manager/branches/promotion.py` (update `ProjectionType` references)
- `scripts/spec_manager/spec_manager/branches/analysis.py` (update `ProjectionType` references)
- `scripts/spec_manager/spec_manager/branches/__init__.py` (update re-export)
- `scripts/spec_manager/spec_manager/projection/lineage/edges.py` (add docstring cross-reference)

### Plan 4: Add Documentation Distinguishing Import Edge Types

**Rationale**: Three `ImportEdge`-like types exist but model genuinely different concepts. Rather than merging them (which would create a "god class"), add clear documentation.

**Steps**:

1. In `scripts/spec_manager/spec_manager/schemas/pin_functions.py`:
   - Update `ImportEdge` docstring to explicitly state: "This is a pin-function-to-architecture mapping edge (PFUNC -> arch location). Not to be confused with `projection.lineage.import_graph.ImportEdge` (raw Python AST import) or `projection.lineage.edges.ProjectionLineageEdge` (lineage transformation edge)."

2. In `scripts/spec_manager/spec_manager/projection/lineage/import_graph.py`:
   - Update `ImportEdge` docstring to explicitly state: "This is a raw Python import relationship from AST analysis. Not to be confused with `schemas.pin_functions.ImportEdge` (pin-function mapping) or `projection.lineage.edges.ProjectionLineageEdge` (lineage transformation edge)."

3. In `scripts/spec_manager/spec_manager/projection/lineage/edges.py`:
   - Update `ProjectionLineageEdge` docstring to cross-reference the other two edge types.
   - Update `TransformationType` docstring to cross-reference `schemas.pin_functions.ProjectionType` and note it is the finer-grained superset.

4. Consider renaming `projection/lineage/import_graph.ImportEdge` to `RawImportEdge` or `PythonImportEdge` to avoid name collision, but this is optional and lower priority.

**Files changed**:
- `scripts/spec_manager/spec_manager/schemas/pin_functions.py` (docstring update)
- `scripts/spec_manager/spec_manager/projection/lineage/import_graph.py` (docstring update)
- `scripts/spec_manager/spec_manager/projection/lineage/edges.py` (docstring update)

### Plan 5: Add Validation from Deleted Schema to PinProjection

**Rationale**: The deleted `PinFunctionSchema` had useful validators (`pin_id` format `PIN-####`, confidence bounds `[0.0, 1.0]`). Port these to the renamed `PinProjection` dataclass as `__post_init__` validation.

**Steps**:

1. In `scripts/spec_manager/spec_manager/branches/types.py`:
   - Add `__post_init__` to `PinProjection` (formerly `PinFunction`):
     ```python
     def __post_init__(self):
         if not re.fullmatch(r"PIN-\d{4}", self.pin_id):
             raise ValueError("pin_id must match PIN-#### format")
         if not 0.0 <= self.confidence <= 1.0:
             raise ValueError("confidence must be between 0.0 and 1.0")
     ```
   - Import `re` at module top

2. Add tests for the new validation in the branches test suite.

3. Run full test suite to verify existing code conforms to the format constraints.

**Files changed**:
- `scripts/spec_manager/spec_manager/branches/types.py` (add validation)
- New or existing test file for branches types validation

## Execution Instructions

Execute plans in order (1 through 5). Each plan is independently reviewable and testable:

- **Plan 1** is a pure deletion with no downstream effects (dead code).
- **Plan 2** is a rename scoped entirely within the `branches/` package.
- **Plan 3** depends on Plan 2 (the renamed class uses the unified `ProjectionType`).
- **Plan 4** is pure documentation, can be done at any point.
- **Plan 5** depends on Plan 1 (porting validators from deleted file) and Plan 2 (adding to renamed class).

Verification after each plan:
```bash
cd scripts/spec_manager
uv run python -m pytest -x -p no:randomly
```

For import verification after Plans 2-3:
```bash
cd scripts/spec_manager
uv run python -c "from spec_manager.branches import PinProjection, ProjectionType; print('OK')"
uv run python -c "from spec_manager.schemas.pin_functions import PinFunction, ProjectionType, ImportEdge; print('OK')"
uv run python -c "from spec_manager.core.pin_registry import PinRegistryIndex; print('OK')"
```

## Success Criteria

1. `schemas/pin_function.py` (singular) is deleted and no imports reference it
2. No two types share the name `PinFunction` -- the branches version is `PinProjection`
3. A single canonical `ProjectionType` exists in `schemas/pin_functions.py`, used by both subsystems
4. `TransformationType` in lineage remains as a documented finer-grained superset
5. All three import edge types have cross-reference docstrings
6. Full test suite passes: `uv run python -m pytest -x -p no:randomly` exits 0
7. No new `# type: ignore` or `noqa` comments introduced
8. `PinProjection` has `__post_init__` validation for `pin_id` format and `confidence` bounds

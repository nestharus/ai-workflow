# Implementation Plan

## Overview

Unify the three separate representations of projection/transformation types into a single canonical enum, eliminating vocabulary fragmentation between the lineage system, branches system, schemas, and analysis classifier.

## Current State (Problems)

There are **four** separate representations of projection types across the codebase:

1. **`projection/lineage/edges.py::TransformationType`** (Enum, 7 fine-grained values)
   - Values (lowercase snake_case): `pass_through`, `event_bridge`, `middleware_wrap`, `retry_decorate`, `slice`, `smear`, `introduction`
   - Used by: `ProjectionLineageEdge`, `ProjectionLineageTable`, `LineageBuilder`, `DataFlowHop`, and all lineage tests

2. **`schemas/pin_functions.py::ProjectionType`** (str Enum, 6 coarse values)
   - Values (UPPER_CASE): `PASS_THROUGH`, `WRAP`, `SMEAR`, `PROJECTION`, `AGGREGATION`, `INTRODUCTION`
   - Used by: `ImportEdge`, `PinProjection`, `DriftReport`, `PinRegistry`, `PromotionEngine`, `AnalysisGenerator`, and all branches tests

3. **`schemas/lineage.py::LineageEdge.transformation`** (Literal type, 4 values)
   - Values (lowercase): `"pass_through"`, `"wrap"`, `"smear"`, `"introduction"`
   - Used by: `projection_classifier.py::classify_import()`

4. **`analysis/projection_classifier.py::ProjectionType`** (Literal type alias, 4 values)
   - Values (lowercase): `"pass_through"`, `"wrap"`, `"smear"`, `"introduction"`
   - Shadows the enum name, used only within that module

### Problems

- **Semantic overlap**: `TransformationType.EVENT_BRIDGE`, `.MIDDLEWARE_WRAP`, `.RETRY_DECORATE` are all fine-grained variants of `ProjectionType.WRAP`. `TransformationType.SLICE` maps to `ProjectionType.PROJECTION`. But there is no formal mapping.
- **Value format mismatch**: `TransformationType` uses lowercase snake_case values (`"pass_through"`); `ProjectionType` uses UPPER_CASE values (`"PASS_THROUGH"`). Serialized data from the two systems is incompatible.
- **Name collision**: `analysis/projection_classifier.py` defines a local `ProjectionType` Literal that shadows `schemas.pin_functions.ProjectionType`.
- **Missing mapping**: No code converts between the two enum types, so the lineage system and branches system cannot interoperate on projection metadata.
- **Test inconsistency**: `test_types.py` asserts `ProjectionType.PASS_THROUGH.value == "pass_through"` (lowercase), but the enum source in `pin_functions.py` declares `PASS_THROUGH = "PASS_THROUGH"` (UPPER_CASE).

## Target State

- **One canonical enum** (`ProjectionType`) in `schemas/pin_functions.py` with the fine-grained values from `TransformationType`, using consistent lowercase snake_case values.
- `TransformationType` deleted from `projection/lineage/edges.py`.
- `analysis/projection_classifier.py` local `ProjectionType` Literal removed; uses the canonical enum.
- `schemas/lineage.py::LineageEdge.transformation` Literal updated to reference the canonical enum values.
- All consumers import from the single canonical location.
- A `ProjectionType.to_coarse()` helper or standalone mapping function exists for contexts that only need the 4-category coarse classification.

## Additional Info

### Canonical Enum Definition (Target)

```python
# schemas/pin_functions.py
class ProjectionType(str, Enum):
    """How an architectural location uses a pin-function.

    Fine-grained classification supporting both lineage tracking and
    branch organization. Coarse groupings:
    - Direct: PASS_THROUGH
    - Wrapping: EVENT_BRIDGE, MIDDLEWARE_WRAP, RETRY_DECORATE
    - Combining: SMEAR, AGGREGATION
    - Subsetting: SLICE (aka PROJECTION)
    - Novel: INTRODUCTION
    """
    PASS_THROUGH = "pass_through"
    EVENT_BRIDGE = "event_bridge"
    MIDDLEWARE_WRAP = "middleware_wrap"
    RETRY_DECORATE = "retry_decorate"
    SLICE = "slice"
    SMEAR = "smear"
    AGGREGATION = "aggregation"
    INTRODUCTION = "introduction"
```

### Mapping from Old to New

| Old `ProjectionType` | New `ProjectionType` | Notes |
|---|---|---|
| `PASS_THROUGH` ("PASS_THROUGH") | `PASS_THROUGH` ("pass_through") | Value changes to lowercase |
| `WRAP` ("WRAP") | `MIDDLEWARE_WRAP` ("middleware_wrap") | Default for generic wrapping; specific sites may use `EVENT_BRIDGE` or `RETRY_DECORATE` |
| `SMEAR` ("SMEAR") | `SMEAR` ("smear") | Value changes to lowercase |
| `PROJECTION` ("PROJECTION") | `SLICE` ("slice") | Renamed to match lineage vocabulary |
| `AGGREGATION` ("AGGREGATION") | `AGGREGATION` ("aggregation") | Value changes to lowercase |
| `INTRODUCTION` ("INTRODUCTION") | `INTRODUCTION` ("introduction") | Value changes to lowercase |

| Old `TransformationType` | New `ProjectionType` | Notes |
|---|---|---|
| `PASS_THROUGH` | `PASS_THROUGH` | No change |
| `EVENT_BRIDGE` | `EVENT_BRIDGE` | No change |
| `MIDDLEWARE_WRAP` | `MIDDLEWARE_WRAP` | No change |
| `RETRY_DECORATE` | `RETRY_DECORATE` | No change |
| `SLICE` | `SLICE` | No change |
| `SMEAR` | `SMEAR` | No change |
| `INTRODUCTION` | `INTRODUCTION` | No change |

### Coarse Group Helper

```python
COARSE_GROUP = {
    ProjectionType.PASS_THROUGH: "direct",
    ProjectionType.EVENT_BRIDGE: "wrap",
    ProjectionType.MIDDLEWARE_WRAP: "wrap",
    ProjectionType.RETRY_DECORATE: "wrap",
    ProjectionType.SLICE: "subset",
    ProjectionType.SMEAR: "combine",
    ProjectionType.AGGREGATION: "combine",
    ProjectionType.INTRODUCTION: "introduction",
}
```

### Files Affected (30 total)

**Source files requiring changes (12):**
- `scripts/spec_manager/spec_manager/schemas/pin_functions.py` -- expand enum, lowercase values
- `scripts/spec_manager/spec_manager/projection/lineage/edges.py` -- delete `TransformationType`, import from schemas
- `scripts/spec_manager/spec_manager/projection/lineage/table.py` -- update imports
- `scripts/spec_manager/spec_manager/projection/lineage/builder.py` -- update imports + enum references
- `scripts/spec_manager/spec_manager/projection/lineage/data_flow.py` -- update imports + enum references
- `scripts/spec_manager/spec_manager/projection/__init__.py` -- update lazy import mapping
- `scripts/spec_manager/spec_manager/projection/lineage/__init__.py` -- update exports
- `scripts/spec_manager/spec_manager/schemas/lineage.py` -- update Literal to use enum values
- `scripts/spec_manager/spec_manager/analysis/projection_classifier.py` -- remove local Literal, use enum
- `scripts/spec_manager/spec_manager/analysis/import_graph.py` -- no structural change (already imports from schemas)
- `scripts/spec_manager/spec_manager/branches/types.py` -- import unchanged (re-exports from schemas)
- `scripts/spec_manager/spec_manager/branches/pins.py` -- update `PROJECTION` -> `SLICE` references

**Test files requiring changes (18):**
- `scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py`
- `scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py`
- `scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py`
- `scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py`
- `scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py`
- `scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py`
- `scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py`
- `scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py`
- `scripts/tests/unit/spec_manager/branches/test_types.py`
- `scripts/tests/unit/spec_manager/branches/test_pins.py`
- `scripts/tests/unit/spec_manager/branches/test_manager.py`
- `scripts/tests/unit/spec_manager/branches/test_slices.py`
- `scripts/tests/unit/spec_manager/branches/test_promotion.py`
- `scripts/tests/unit/spec_manager/branches/test_analysis.py`
- `scripts/tests/unit/spec_manager/branches/test_downward_flow.py`

### Serialization Compatibility

This is a **breaking change** for serialized data. All persisted JSON artifacts that contain projection type values (e.g., `"PASS_THROUGH"` -> `"pass_through"`, `"WRAP"` -> `"middleware_wrap"`) will need migration. Since there is no production data at this stage, a clean break is acceptable.

## Plans

### Plan 1: Expand Canonical Enum and Add Coarse Mapping

**Goal**: Create the unified `ProjectionType` enum in `schemas/pin_functions.py` with all 8 values and a coarse-group mapping function.

**Files**:
- `scripts/spec_manager/spec_manager/schemas/pin_functions.py`
- `scripts/spec_manager/spec_manager/schemas/__init__.py`

**Steps**:

1. In `schemas/pin_functions.py`, replace the `ProjectionType` enum with the expanded version containing 8 members, all with lowercase snake_case values:
   - Keep: `PASS_THROUGH`, `SMEAR`, `INTRODUCTION` (change values to lowercase)
   - Add: `EVENT_BRIDGE`, `MIDDLEWARE_WRAP`, `RETRY_DECORATE`, `SLICE`
   - Rename: `WRAP` -> removed (consumers use specific wrap types); `PROJECTION` -> `SLICE`
   - Keep: `AGGREGATION` (change value to lowercase)

2. Add a module-level `COARSE_GROUP: dict[ProjectionType, str]` mapping and a `coarse_group(pt: ProjectionType) -> str` convenience function below the enum.

3. Ensure `schemas/__init__.py` still exports `ProjectionType` (no change needed, already re-exports).

4. Update `__all__` in `pin_functions.py` to include `coarse_group` and `COARSE_GROUP`.

### Plan 2: Delete TransformationType and Update Lineage System

**Goal**: Remove `TransformationType` from `projection/lineage/edges.py` and update all lineage modules to use the canonical `ProjectionType`.

**Files**:
- `scripts/spec_manager/spec_manager/projection/lineage/edges.py`
- `scripts/spec_manager/spec_manager/projection/lineage/table.py`
- `scripts/spec_manager/spec_manager/projection/lineage/builder.py`
- `scripts/spec_manager/spec_manager/projection/lineage/data_flow.py`
- `scripts/spec_manager/spec_manager/projection/__init__.py`
- `scripts/spec_manager/spec_manager/projection/lineage/__init__.py`

**Steps**:

1. In `edges.py`:
   - Delete the `TransformationType` class entirely.
   - Add `from spec_manager.schemas.pin_functions import ProjectionType`.
   - Change `ProjectionLineageEdge.transformation` type annotation from `TransformationType` to `ProjectionType`.
   - Update `from_dict` to use `ProjectionType(data["transformation"])`.
   - Remove `TransformationType` from `__all__`; optionally add a re-export of `ProjectionType` for backward compatibility.

2. In `table.py`:
   - Replace `from spec_manager.projection.lineage.edges import ... TransformationType` with `from spec_manager.schemas.pin_functions import ProjectionType`.
   - Update all type annotations and dict keys from `TransformationType` to `ProjectionType`.

3. In `builder.py`:
   - Replace `TransformationType` import with `ProjectionType` from schemas.
   - Update all `TransformationType.EVENT_BRIDGE` -> `ProjectionType.EVENT_BRIDGE`, etc.

4. In `data_flow.py`:
   - Replace `TransformationType` import and all usages with `ProjectionType`.

5. In `projection/__init__.py`:
   - Update lazy import block: remove `TransformationType` from `_lineage_edge_names` set.
   - Add `TransformationType` as a deprecated alias that resolves to `ProjectionType` (or remove entirely and let consumers update imports).
   - Keep `"TransformationType"` in `__all__` temporarily as alias, or remove.

6. In `projection/lineage/__init__.py`:
   - Update `__all__` and `__getattr__` to remove or alias `TransformationType`.

### Plan 3: Update Branches System for New Values

**Goal**: Update all branches modules that reference `ProjectionType` to handle the new lowercase values and the renamed member (`PROJECTION` -> `SLICE`, `WRAP` removed).

**Files**:
- `scripts/spec_manager/spec_manager/branches/types.py`
- `scripts/spec_manager/spec_manager/branches/pins.py`
- `scripts/spec_manager/spec_manager/branches/promotion.py`
- `scripts/spec_manager/spec_manager/branches/analysis.py`
- `scripts/spec_manager/spec_manager/branches/__init__.py`

**Steps**:

1. In `branches/types.py`:
   - Import remains `from spec_manager.schemas.pin_functions import ProjectionType` -- no change needed.
   - `PinProjection.from_dict` already uses `ProjectionType(data["projection_type"])` which will auto-work with lowercase values.

2. In `branches/pins.py`:
   - Update `ProjectionType.PROJECTION` -> `ProjectionType.SLICE` in `detect_drift()` (line 217).
   - Update `ProjectionType.AGGREGATION` reference (no member rename, just value change, handled by enum).

3. In `branches/promotion.py`:
   - `ProjectionType.PASS_THROUGH` reference unchanged (member name stays same).

4. In `branches/analysis.py`:
   - `ProjectionType(v)` deserialization calls will automatically work with lowercase values.

5. In `branches/__init__.py`:
   - No changes needed (already re-exports from types.py).

### Plan 4: Unify Analysis Classifier and Schema Lineage

**Goal**: Remove the shadow `ProjectionType` Literal in `analysis/projection_classifier.py` and update `schemas/lineage.py` to use the canonical enum.

**Files**:
- `scripts/spec_manager/spec_manager/analysis/projection_classifier.py`
- `scripts/spec_manager/spec_manager/schemas/lineage.py`

**Steps**:

1. In `analysis/projection_classifier.py`:
   - Delete line 14: `ProjectionType = Literal["pass_through", "wrap", "smear", "introduction"]`
   - Add import: `from spec_manager.schemas.pin_functions import ProjectionType`
   - Update string literal assignments (`transformation = "wrap"` etc.) to use enum members (`transformation = ProjectionType.MIDDLEWARE_WRAP` etc.)
   - Update `classify_import()` return type and all `LineageEdge` construction to use enum values.
   - Note: `LineageEdge` from `schemas/lineage.py` uses a `Literal` for `transformation`; after Plan 4 step 2, it will accept enum values.

2. In `schemas/lineage.py`:
   - Replace the `Literal["pass_through", "wrap", "smear", "introduction"]` type for `LineageEdge.transformation` with `ProjectionType`.
   - Add `from spec_manager.schemas.pin_functions import ProjectionType` import.
   - Remove the `Literal` import if no longer needed.

### Plan 5: Update All Tests

**Goal**: Update all test files to use the unified `ProjectionType` enum with correct member names and lowercase values.

**Files**: All 15+ test files listed in Additional Info.

**Steps**:

1. **Lineage tests** (6 files in `projection/lineage/tests/`):
   - Replace all `from spec_manager.projection.lineage.edges import TransformationType` with `from spec_manager.schemas.pin_functions import ProjectionType`.
   - Replace all `TransformationType.X` references with `ProjectionType.X`.
   - `test_edges.py`: Update `TestTransformationType` class -- rename to `TestProjectionType`, update value assertions to lowercase, update count assertion from 7 to 8 (adding `AGGREGATION`).

2. **Branches tests** (7 files in `scripts/tests/unit/spec_manager/branches/`):
   - `test_types.py`: Fix value assertions to use lowercase (e.g., `"pass_through"` not `"PASS_THROUGH"`). Update `ProjectionType.PROJECTION` -> `ProjectionType.SLICE`.
   - `test_pins.py`: Update `ProjectionType.AGGREGATION` usages (member name unchanged, values now lowercase).
   - `test_downward_flow.py`: Update `ProjectionType.PROJECTION` -> `ProjectionType.SLICE`.
   - Other test files: Mechanical `PROJECTION` -> `SLICE` rename where used.

3. **Labyrinth tests** (2 files):
   - `test_pin_registry.py`: Update string literals `"PASS_THROUGH"` -> `"pass_through"`, `"WRAP"` -> `"middleware_wrap"`, `"SMEAR"` -> `"smear"`, `"INTRODUCTION"` -> `"introduction"` in `_make_import_edge` calls and assertions.
   - `test_import_graph.py`: Update `== "PASS_THROUGH"` -> `== "pass_through"`, `== "WRAP"` -> enum comparisons.

4. Run full test suite: `cd scripts/spec_manager && uv run pytest -x -p no:randomly` to verify no regressions.

## Execution Instructions

Execute plans in order (1 through 5). Each plan is independently testable:

- **After Plan 1**: Run `uv run pytest scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py -x` -- existing tests may break due to value changes; this is expected until Plan 5 fixes them.
- **After Plan 2**: Run lineage tests (will fail until Plan 5).
- **After Plan 3**: Run branches tests (will fail until Plan 5).
- **After Plan 4**: Run classifier and lineage schema tests.
- **After Plan 5**: Run full suite to confirm green.

Alternatively, execute Plans 1-4 together, then Plan 5, and run tests only after Plan 5.

## Success Criteria

1. `grep -r "TransformationType" scripts/spec_manager/` returns zero hits in production code (test files may have renamed test classes).
2. `grep -r 'class TransformationType' scripts/spec_manager/` returns zero hits.
3. Only one `class ProjectionType` definition exists in `schemas/pin_functions.py`.
4. `grep -rn "ProjectionType = Literal" scripts/spec_manager/` returns zero hits.
5. All enum values across the codebase use lowercase snake_case format.
6. `uv run pytest scripts/spec_manager/ scripts/tests/unit/spec_manager/branches/ -x -p no:randomly` passes with zero failures.
7. The `COARSE_GROUP` mapping covers all 8 enum members.
8. No file imports `TransformationType` -- all imports reference `ProjectionType` from `spec_manager.schemas.pin_functions`.

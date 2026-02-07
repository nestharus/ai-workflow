# Implementation Plan

## Overview

Design and implement the branch organization system that maintains multiple parallel representations of code (algorithmic, architectural, analysis), manages promotion workflows between them via pin-functions, handles downward flow for issue resolution, collapses untracked systems to Layer 1, and structures horizontal/vertical slices within each branch.

## Current State (Problems)

1. **No branch concept exists.** The existing workspace managers (`scripts/spec_manager/spec_manager/workspace/manager.py` and `scripts/spec_manager/spec_manager/refinement/workspace/manager.py`) manage a single flat workspace per run. There is no mechanism to maintain parallel representations of the same codebase.

2. **Projection schema is minimal.** The existing `schemas/projection.py` defines `Pin`, `ProjectionArtifact`, and `ProjectionPolicy` but only supports offset-based pin mapping within a single document. There is no support for cross-branch pin tracking or function-level pin-functions.

3. **Lineage tracking is unit-level, not branch-level.** `core/provenance.py` tracks `TrackedUnit` and `LineageEdge` at the content unit level. There is no concept of a "branch" that maintains its own view of the codebase with different projection transformations applied.

4. **No promotion workflow.** Changes cannot flow from algorithmic to architectural representation. The architecture workflow in `docs/development/architecture-workflow.md` describes library-to-component mapping but not atom-level promotion with pin tracking.

5. **No collapse mechanism.** Existing codebases cannot be ingested and stripped down to Layer 1 (algorithmic intent without architectural concerns).

6. **No vertical/horizontal slice navigation.** The recursive `system/algorithms/stores/shapes/children/...` structure from the design document (Section 9) has no implementation.

## Target State

A `branches/` module within spec_manager that:
- Represents three branch types (algorithmic, architectural, analysis) as directory-backed virtual layers
- Shares `atoms/` as a single source of truth across branches
- Tracks pin-functions as real Python function references with import-based resolution
- Promotes changes upward (algorithmic -> architectural) with compliance gating
- Propagates architectural issues downward to algorithmic atoms via pin tracing
- Collapses an existing codebase to Layer 1 by extracting algorithmic intent
- Navigates vertical slices (components) and horizontal slices (layers within a component)
- Integrates with the existing `RunFolderStructure` and `WorkspaceManager`

## Additional Info

**Design document reference:** `.tasks/plans/spec manager/algorithmic-projection-patch.md`, Sections 5, 6, 9, 11, 12.

**Key constraints:**
- The atoms directory is physically shared between branches. Both the algorithmic and architectural branches import the same atom functions. When an atom changes, pass-through pins propagate automatically.
- The analysis branch is always a computed artifact -- never manually edited. It is regenerated from the pin-function import graph and lineage table.
- Promotion from algorithmic to architectural requires a compliance gate (Section 12): no remaining comments, no stubs, all tests pass, connected call graph, store monogamy enforced.
- The system must work with the existing `resolve_from_root()` pattern for path resolution.
- Pydantic models are used for schemas (existing convention in `schemas/`), while `dataclass` is used for state objects (existing convention in `workspace/state.py`).

**Existing integration points:**
- `RunFolderStructure` in `refinement/workspace/manager.py` (lines 44-164) defines the current run directory layout.
- `ProjectionArtifact` and `Pin` in `schemas/projection.py` define the current pin concept.
- `LineageEdge` and `LineageTable` in `core/provenance.py` define the current lineage tracking.
- `EdgeListSchema` in `schemas/edge_list.py` defines cross-library dependency edges.

## Plans

### Plan 1: Branch Data Model and Directory Layout

**Goal:** Define the core data structures for branches, atoms, pin-functions, and the physical directory layout within a run folder.

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/__init__.py`
2. `scripts/spec_manager/spec_manager/branches/types.py` -- Core enums and data structures
3. `scripts/spec_manager/spec_manager/branches/layout.py` -- Physical directory layout
4. `scripts/spec_manager/spec_manager/branches/atoms.py` -- Shared atom registry

**Files to modify:**

1. `scripts/spec_manager/spec_manager/refinement/workspace/manager.py` -- Add `branches_dir` property to `RunFolderStructure`

**Directory structure within a run:**

```
runs/{run_id}/
  branches/
    algorithmic/                    # Layer 1: The spec
      atoms/                        # Pin-functions (shared via symlink or registry)
        validate_payment.py
        apply_discount.py
      compositions/                 # How atoms compose into algorithms
        process_order.py
      stores/                       # Store definitions
        order_store.py
      shapes/                       # Pure logic shapes
        discount_calculator.py
    architectural/                  # Layer 2: Real architecture
      services/                     # Atoms recomposed into services
        payment_service.py
      events/                       # Event handlers wrapping atoms
        payment_events.py
      middleware/                    # Middleware wrapping atoms
        validation_middleware.py
      infrastructure/               # Introduced algorithms (retry, circuit breaking)
        retry_policy.py
    analysis/                       # Computed artifact
      lineage_table.json            # Pin map: atom -> architectural locations
      adjacency_graph.json          # Co-occurrence and store-touch edges
      drift_report.md               # Detected drift between branches
    atoms/                          # Single source of truth (actual files live here)
      validate_payment.py
      apply_discount.py
      __registry__.json             # Atom metadata: provenance, signatures, hashes
```

**Data structures in `types.py`:**

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class BranchKind(Enum):
    """Types of branches in the system."""
    ALGORITHMIC = "algorithmic"
    ARCHITECTURAL = "architectural"
    ANALYSIS = "analysis"


class AtomKind(Enum):
    """Classification of atom functions."""
    ALGORITHM = "algorithm"     # Business logic step
    STORE = "store"             # Persistent state definition
    SHAPE = "shape"             # Pure logic, no side effects


class StoreType(Enum):
    """Store persistence classification (from design doc Section 3)."""
    PERSISTED = "persisted"           # Type A: survives restart
    LONG_LIVED_EPHEMERAL = "ephemeral_long"  # Type B: in-memory across steps
    PURE_EPHEMERAL = "ephemeral_pure"        # Type C: local/temporary


class ProjectionType(Enum):
    """How an atom is projected into architecture (from design doc Section 11)."""
    PASS_THROUGH = "pass_through"     # Architecture imports atom directly
    PROJECTION = "projection"         # Architecture uses subset of atom output
    AGGREGATION = "aggregation"       # Architecture combines multiple atoms
    INTRODUCTION = "introduction"     # Architecture adds new algorithm (no source atom)


class SliceOrientation(Enum):
    """Navigation direction within the branch structure."""
    HORIZONTAL = "horizontal"   # Layers within a vertical (algorithms, stores, shapes, events, ...)
    VERTICAL = "vertical"       # Components with state/lifecycle (entities)


@dataclass
class AtomDescriptor:
    """Metadata for a registered atom function.

    Attributes:
        atom_id: Unique identifier (function name or qualified name).
        kind: Whether this is an algorithm, store, or shape.
        file_path: Relative path within the atoms/ directory.
        function_name: The Python function name.
        signature: Type signature string (for contract checking).
        content_hash: SHA-256 of the function source.
        introduced_by: Which plan/patch added this atom.
        modified_by: Chain of modifications.
        store_type: If kind is STORE, the persistence classification.
        vertical_slice: Which vertical slice this atom belongs to.
    """
    atom_id: str
    kind: AtomKind
    file_path: str
    function_name: str
    signature: str
    content_hash: str
    introduced_by: str
    modified_by: list[str] = field(default_factory=list)
    store_type: StoreType | None = None
    vertical_slice: str | None = None


@dataclass
class PinFunction:
    """A pin mapping an atom to an architectural location.

    This is an executable bridge (design doc Section 5). The pin is the
    atom function itself. This descriptor records WHERE the atom is used
    in the architectural branch and HOW it was projected.

    Attributes:
        pin_id: Unique pin identifier (PIN-####).
        atom_id: The atom being pinned.
        architectural_location: File:class.method in the architectural branch.
        projection_type: How the atom was projected.
        confidence: 1.0 for mechanical (import), <1.0 for inferred.
        wrapper_hash: Hash of wrapping code (for drift detection on non-pass-through).
    """
    pin_id: str
    atom_id: str
    architectural_location: str
    projection_type: ProjectionType
    confidence: float = 1.0
    wrapper_hash: str | None = None


@dataclass
class VerticalSlice:
    """A component vertical slice in the recursive structure.

    Attributes:
        slice_id: Unique identifier for this slice.
        name: Human-readable name.
        parent_slice_id: Parent in the recursive hierarchy (None for root).
        atom_ids: Atoms belonging to this vertical.
        store_ids: Stores owned by this vertical (store monogamy).
        children: Child vertical slices.
    """
    slice_id: str
    name: str
    parent_slice_id: str | None = None
    atom_ids: list[str] = field(default_factory=list)
    store_ids: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
```

**Data structures in `layout.py`:**

```python
@dataclass
class BranchLayout:
    """Physical directory layout for branches within a run.

    Attributes:
        run_root: Root of the run directory.
    """
    run_root: Path

    @property
    def branches_dir(self) -> Path:
        return self.run_root / "branches"

    @property
    def atoms_dir(self) -> Path:
        """Single source of truth for atom files."""
        return self.branches_dir / "atoms"

    @property
    def atom_registry_path(self) -> Path:
        return self.atoms_dir / "__registry__.json"

    def branch_dir(self, kind: BranchKind) -> Path:
        return self.branches_dir / kind.value

    def algorithmic_dir(self) -> Path:
        return self.branch_dir(BranchKind.ALGORITHMIC)

    def architectural_dir(self) -> Path:
        return self.branch_dir(BranchKind.ARCHITECTURAL)

    def analysis_dir(self) -> Path:
        return self.branch_dir(BranchKind.ANALYSIS)

    def initialize(self) -> None:
        """Create the full branch directory structure."""
        ...

    def validate(self) -> list[str]:
        """Validate the branch directory structure exists."""
        ...
```

**Data structures in `atoms.py`:**

```python
class AtomRegistry:
    """Registry of all atom functions (single source of truth).

    Manages atom descriptors, content hashes, and provides lookup by
    atom_id, kind, or vertical slice.
    """

    def __init__(self, layout: BranchLayout) -> None: ...

    def register(self, descriptor: AtomDescriptor) -> None: ...
    def unregister(self, atom_id: str) -> None: ...
    def get(self, atom_id: str) -> AtomDescriptor | None: ...
    def list_by_kind(self, kind: AtomKind) -> list[AtomDescriptor]: ...
    def list_by_slice(self, slice_id: str) -> list[AtomDescriptor]: ...
    def detect_changes(self) -> list[tuple[str, str, str]]:
        """Compare content hashes to detect modified atoms.
        Returns list of (atom_id, old_hash, new_hash).
        """
        ...

    def save(self) -> None: ...

    @classmethod
    def load(cls, layout: BranchLayout) -> AtomRegistry: ...
```

**Modification to `RunFolderStructure`:**

Add to `scripts/spec_manager/spec_manager/refinement/workspace/manager.py`:

```python
@property
def branches_dir(self) -> Path:
    """Path to the branches directory."""
    return self.root / "branches"
```

**Steps:**
1. Create the `branches/` package with `__init__.py`
2. Implement `types.py` with all dataclasses and enums (serialization via `to_dict`/`from_dict`)
3. Implement `layout.py` with `BranchLayout` including `initialize()` and `validate()`
4. Implement `atoms.py` with `AtomRegistry` using JSON persistence at `__registry__.json`
5. Add `branches_dir` property to `RunFolderStructure`
6. Write unit tests for all dataclasses (serialization roundtrip) and `BranchLayout` (directory creation/validation)

---

### Plan 2: Pin-Function Registry and Projection Tracking

**Goal:** Implement the pin-function registry that tracks how atoms are used in the architectural branch, supporting all four projection types and enabling change propagation queries.

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/pins.py` -- Pin registry and projection tracking
2. `scripts/spec_manager/spec_manager/schemas/pin_function.py` -- Pydantic schemas for pin-function validation

**Files to modify:**

1. `scripts/spec_manager/spec_manager/schemas/projection.py` -- Extend `Pin` to support function-level targets with `ATOM_FUNCTION` kind

**Data structures in `pins.py`:**

```python
@dataclass
class PinRegistry:
    """Registry of all pin-functions mapping atoms to architectural locations.

    Provides:
    - Forward trace: atom_id -> all architectural locations
    - Backward trace: architectural_location -> originating atom
    - Change propagation: given a changed atom, list affected pins
    - Drift detection: compare wrapper hashes for non-pass-through pins
    """

    def __init__(self, layout: BranchLayout) -> None: ...

    def register_pin(self, pin: PinFunction) -> None: ...
    def unregister_pin(self, pin_id: str) -> None: ...
    def get_pin(self, pin_id: str) -> PinFunction | None: ...

    # Forward trace (design doc Section 11)
    def get_architectural_locations(self, atom_id: str) -> list[PinFunction]:
        """All architectural locations importing this atom."""
        ...

    # Backward trace
    def get_atom_for_location(self, architectural_location: str) -> PinFunction | None:
        """Which atom does this architectural location use?"""
        ...

    # Change propagation (design doc Section 5)
    def get_affected_pins(self, changed_atom_ids: list[str]) -> dict[str, list[PinFunction]]:
        """For each changed atom, return affected pins grouped by projection type.

        Returns:
            Dict mapping atom_id -> list of PinFunction that reference it.
            Pass-through pins propagate automatically.
            Wrapping/aggregation pins need manual verification.
        """
        ...

    # Drift detection (design doc Section 11)
    def detect_drift(self, atom_registry: AtomRegistry) -> list[DriftReport]:
        """Compare wrapper hashes and atom content hashes to find drift.

        For pass-through: drift if atom changed but architectural code
            still imports old version (should be impossible with shared atoms).
        For wrapping: drift if wrapper_hash changed OR atom changed.
        For aggregation: drift if any aggregated atom changed.
        """
        ...

    # Coverage analysis
    def get_unpinned_atoms(self, atom_registry: AtomRegistry) -> list[str]:
        """Atoms with no architectural usage (not yet projected)."""
        ...

    def get_orphaned_architectural_code(self) -> list[str]:
        """Architectural locations with no pin (undocumented/orphaned)."""
        ...

    def allocate_pin_id(self) -> str:
        """Allocate the next PIN-#### identifier."""
        ...

    def save(self) -> None: ...

    @classmethod
    def load(cls, layout: BranchLayout) -> PinRegistry: ...


@dataclass
class DriftReport:
    """Report of detected drift between branches."""
    pin_id: str
    atom_id: str
    drift_type: str  # "atom_changed", "wrapper_changed", "aggregation_invalidated"
    architectural_location: str
    projection_type: ProjectionType
    details: str
```

**Schema in `pin_function.py`:**

```python
from pydantic import BaseModel, field_validator

class PinFunctionSchema(BaseModel):
    """Pydantic validation schema for pin-functions."""
    pin_id: str
    atom_id: str
    architectural_location: str
    projection_type: Literal["pass_through", "projection", "aggregation", "introduction"]
    confidence: float = 1.0
    wrapper_hash: str | None = None

    @field_validator("pin_id")
    @classmethod
    def validate_pin_id(cls, value: str) -> str:
        if not re.fullmatch(r"PIN-\d{4}", value):
            raise ValueError("pin_id must match PIN-#### format")
        return value
```

**Modification to `schemas/projection.py`:**

Extend the `target_kind` literal in `Pin` to include `"ATOM_FUNCTION"`:

```python
target_kind: Literal["LIBRARY", "ELEMENT", "ATOM_RANGE", "ATOM_FUNCTION"]
```

**Steps:**
1. Create `schemas/pin_function.py` with Pydantic validation
2. Extend `schemas/projection.py` to support `ATOM_FUNCTION` target kind
3. Implement `branches/pins.py` with `PinRegistry` and `DriftReport`
4. Implement forward/backward trace methods
5. Implement change propagation and drift detection
6. Write unit tests for all registry operations, trace queries, and drift detection

---

### Plan 3: Promotion Workflow (Algorithmic -> Architectural)

**Goal:** Implement the promotion workflow that moves changes from the algorithmic branch to the architectural branch, enforcing compliance gates before promotion.

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/promotion.py` -- Promotion workflow engine
2. `scripts/spec_manager/spec_manager/branches/compliance.py` -- Compliance gate checks (design doc Section 12)
3. `scripts/spec_manager/spec_manager/branches/gap_detection.py` -- Executable gap detection (design doc Section 7)

**Data structures in `compliance.py`:**

```python
@dataclass
class ComplianceGateResult:
    """Result of running compliance gate checks before promotion."""
    passed: bool
    no_comments: bool           # All pseudocode translated
    no_stubs: bool              # All atoms implemented
    tests_pass: bool            # Algorithmic tests pass
    call_graph_connected: bool  # No orphaned algorithms
    store_monogamy: bool        # Each store in one vertical
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ComplianceChecker:
    """Checks compliance gates before promotion (design doc Section 12)."""

    def __init__(self, layout: BranchLayout, atom_registry: AtomRegistry) -> None: ...

    def check_all(self) -> ComplianceGateResult: ...
    def check_no_comments(self) -> tuple[bool, list[str]]: ...
    def check_no_stubs(self) -> tuple[bool, list[str]]: ...
    def check_tests_pass(self) -> tuple[bool, list[str]]: ...
    def check_call_graph_connected(self) -> tuple[bool, list[str]]: ...
    def check_store_monogamy(self, slices: list[VerticalSlice]) -> tuple[bool, list[str]]: ...
```

**Data structures in `gap_detection.py`:**

```python
@dataclass
class GapItem:
    """A detected gap in algorithmic code (design doc Section 7)."""
    file: str
    line: int
    text: str
    gap_type: str  # "unimplemented_comment", "stub_function", "runtime_error"


class GapDetector:
    """Detects gaps in algorithmic code mechanically."""

    def find_unimplemented_comments(self, filepath: Path) -> list[GapItem]:
        """Every comment in algorithmic code is an unimplemented spec element."""
        ...

    def detect_stubs(self, filepath: Path) -> list[GapItem]:
        """Functions containing only pass, raise NotImplementedError, or Ellipsis."""
        ...

    def scan_branch(self, algorithmic_dir: Path) -> list[GapItem]:
        """Scan the entire algorithmic branch for gaps."""
        ...
```

**Data structures in `promotion.py`:**

```python
@dataclass
class PromotionResult:
    """Result of a promotion attempt."""
    success: bool
    promoted_atoms: list[str]      # Atom IDs that were promoted
    skipped_atoms: list[str]       # Atom IDs skipped (already projected)
    compliance_result: ComplianceGateResult | None
    pin_ids_created: list[str]     # New pins created during promotion
    errors: list[str] = field(default_factory=list)


class PromotionEngine:
    """Manages promotion of changes from algorithmic to architectural branch.

    Workflow (design doc Section 6):
    1. Run compliance gate
    2. Identify changed/new atoms
    3. For each atom, determine projection type needed
    4. Create/update pins in architectural branch
    5. Record promotion in analysis branch
    """

    def __init__(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> None: ...

    def promote(
        self,
        atom_ids: list[str] | None = None,
        skip_compliance: bool = False,
    ) -> PromotionResult:
        """Promote atoms from algorithmic to architectural branch.

        Args:
            atom_ids: Specific atoms to promote (None = all changed).
            skip_compliance: Skip compliance gate (for development only).
        """
        ...

    def _check_compliance(self) -> ComplianceGateResult: ...
    def _identify_changed_atoms(self) -> list[str]: ...
    def _project_atom(self, atom_id: str) -> PinFunction | None: ...
```

**Steps:**
1. Implement `gap_detection.py` with comment detection (tokenize) and stub detection (ast)
2. Implement `compliance.py` with all five gate checks
3. Implement `promotion.py` with the full promotion workflow
4. Write integration tests: promotion with passing compliance, promotion blocked by compliance, partial promotion

---

### Plan 4: Downward Flow (Architectural Issues -> Atom Fix -> Re-verify)

**Goal:** Implement the downward flow where architectural integration test failures trace back to algorithmic atoms via pins, enabling targeted fixes and re-verification.

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/downward_flow.py` -- Downward tracing and fix coordination

**Data structures:**

```python
@dataclass
class ArchitecturalIssue:
    """An issue detected in the architectural branch."""
    issue_id: str
    location: str               # file:class.method in architectural branch
    description: str
    test_name: str | None = None
    stack_trace: str | None = None


@dataclass
class DownwardTraceResult:
    """Result of tracing an architectural issue back to atoms."""
    issue: ArchitecturalIssue
    traced_pins: list[PinFunction]      # Pins at the issue location
    traced_atoms: list[AtomDescriptor]  # Atoms reached via pin trace
    confidence: float                   # How confident the trace is
    suggested_fix_location: str | None  # Where to look in algorithmic branch


class DownwardFlowEngine:
    """Handles downward flow from architectural issues to atom fixes.

    Workflow (design doc Section 6):
    1. Architectural integration test fails
    2. Trace pin back to algorithmic atom
    3. Fix atom function (shared, so algorithmic layer updates too)
    4. Re-verify both layers
    """

    def __init__(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> None: ...

    def trace_issue(self, issue: ArchitecturalIssue) -> DownwardTraceResult:
        """Trace an architectural issue back to its algorithmic origin."""
        ...

    def verify_fix(self, atom_id: str) -> dict[str, bool]:
        """After fixing an atom, verify both branches.

        Returns:
            Dict of {"algorithmic": bool, "architectural": bool}
        """
        ...
```

**Steps:**
1. Implement `DownwardFlowEngine` with pin-based backward tracing
2. Implement `verify_fix` that checks both branches after an atom change
3. Write tests for tracing through pass-through, wrapping, and aggregation pins

---

### Plan 5: Codebase Collapse to Layer 1

**Goal:** Implement the mechanism to ingest an existing codebase that has no layer separation and collapse it to Layer 1 (algorithmic representation).

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/collapse.py` -- Collapse engine

**Data structures:**

```python
@dataclass
class CollapseResult:
    """Result of collapsing a codebase to Layer 1."""
    extracted_atoms: list[AtomDescriptor]
    extracted_stores: list[AtomDescriptor]
    extracted_shapes: list[AtomDescriptor]
    architectural_remnants: list[str]    # Code identified as purely architectural
    ambiguous_code: list[str]            # Code that could be either layer
    warnings: list[str]


class CollapseEngine:
    """Collapses an existing codebase to Layer 1 (design doc Section 6).

    When ingesting an existing codebase with no layer separation:
    1. Parse all Python files for function definitions
    2. Classify each function: algorithm, store, shape, or architecture
    3. Extract algorithms/stores/shapes into atoms/
    4. Record architectural remnants for future projection
    5. Build initial atom registry
    """

    def __init__(self, layout: BranchLayout) -> None: ...

    def collapse(self, source_dir: Path) -> CollapseResult:
        """Collapse an existing codebase to Layer 1."""
        ...

    def _classify_function(self, func_node: ast.FunctionDef, module_path: Path) -> AtomKind | None:
        """Classify a function as algorithm, store, shape, or architectural.

        Heuristics:
        - Shape: no side effects, no I/O, no global state, no external calls
        - Store: touches database, files, queues, or caches
        - Algorithm: sequences of steps that transform data
        - None (architectural): routing, middleware, retry, event handling patterns
        """
        ...

    def _extract_atom(self, func_node: ast.FunctionDef, module_path: Path) -> AtomDescriptor:
        """Extract a function as an atom with metadata."""
        ...
```

**Steps:**
1. Implement AST-based function classification heuristics
2. Implement atom extraction (copy function to atoms/ directory)
3. Implement full collapse workflow with reporting
4. Write tests against the labyrinth test codebase (`scripts/spec_manager/spec_manager/labyrinth/`) as a realistic brownfield example

---

### Plan 6: Vertical and Horizontal Slice Navigation

**Goal:** Implement the recursive vertical/horizontal slice structure and navigation API described in the design document Section 9.

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/slices.py` -- Slice management and navigation

**Data structures:**

```python
@dataclass
class HorizontalLayer:
    """A horizontal layer within a vertical slice.

    The base horizontal layers are: algorithms, stores, shapes.
    Architecture adds: events, middleware, routing, infrastructure.
    """
    layer_id: str
    name: str
    branch_kind: BranchKind         # Which branch this layer belongs to
    item_ids: list[str] = field(default_factory=list)  # Atom IDs or file paths


class SliceNavigator:
    """Navigate the vertical/horizontal slice structure.

    Provides:
    - Down: strip architecture, see business logic
    - Up: see how business logic is deployed
    - Across: see component boundaries

    Pin-functions are the navigation mechanism.
    """

    def __init__(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> None: ...

    # Vertical slice management
    def create_slice(self, name: str, parent_slice_id: str | None = None) -> VerticalSlice: ...
    def get_slice(self, slice_id: str) -> VerticalSlice | None: ...
    def list_root_slices(self) -> list[VerticalSlice]: ...
    def list_children(self, slice_id: str) -> list[VerticalSlice]: ...

    # Horizontal layer access
    def get_horizontal_layers(self, slice_id: str) -> list[HorizontalLayer]:
        """Get all horizontal layers for a vertical slice."""
        ...

    # Navigation
    def navigate_down(self, atom_id: str) -> AtomDescriptor:
        """From any layer, navigate down to the algorithmic atom."""
        ...

    def navigate_up(self, atom_id: str) -> list[PinFunction]:
        """From an atom, navigate up to all architectural locations."""
        ...

    def navigate_across(self, slice_id: str) -> list[VerticalSlice]:
        """From a vertical slice, see sibling components."""
        ...

    # Store monogamy enforcement (design doc Section 9)
    def validate_store_monogamy(self) -> list[str]:
        """Ensure every store lives inside exactly one vertical slice."""
        ...

    def save(self) -> None: ...

    @classmethod
    def load(
        cls,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> SliceNavigator: ...
```

**Steps:**
1. Implement `VerticalSlice` tree management (create, nest, list)
2. Implement `HorizontalLayer` enumeration per slice
3. Implement navigation methods (down/up/across) using pin registry
4. Implement store monogamy validation
5. Write tests for recursive slice creation, navigation in all three directions, and monogamy violations

---

### Plan 7: Analysis Branch Generation

**Goal:** Implement the analysis branch as a computed artifact that is regenerated from the pin-function import graph and lineage table (design doc Section 13).

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/analysis.py` -- Analysis branch generator

**Data structures:**

```python
@dataclass
class AnalysisArtifact:
    """Generated analysis for an atom."""
    atom_id: str
    architectural_imports: list[PinFunction]   # Forward trace
    projection_types: dict[str, ProjectionType]  # pin_id -> projection type
    adjacencies: list[str]                     # Co-occurrence and store-touch edges
    data_flow_in: list[str]                    # Signals into this atom
    data_flow_out: list[str]                   # Signals out of this atom
    stores_touched: list[str]                  # Stores read/written
    unprojected: bool                          # No architectural usage


@dataclass
class AnalysisReport:
    """Full analysis branch content."""
    generated_at: str
    atoms: list[AnalysisArtifact]
    orphaned_architectural: list[str]  # Arch code with no atom
    disconnected_subgraphs: list[list[str]]  # Isolated atom groups
    store_touch_edges: list[tuple[str, str, str]]  # (atom1, store, atom2)


class AnalysisGenerator:
    """Generates the analysis branch from current state.

    The analysis branch is ALWAYS computed, never manually edited.
    It is regenerated on demand from the pin-function import graph.
    """

    def __init__(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        slice_navigator: SliceNavigator,
    ) -> None: ...

    def generate(self) -> AnalysisReport:
        """Generate the full analysis branch."""
        ...

    def write_lineage_table(self, report: AnalysisReport) -> Path:
        """Write lineage_table.json to analysis/ directory."""
        ...

    def write_adjacency_graph(self, report: AnalysisReport) -> Path:
        """Write adjacency_graph.json to analysis/ directory."""
        ...

    def write_drift_report(self, report: AnalysisReport) -> Path:
        """Write drift_report.md to analysis/ directory."""
        ...
```

**Steps:**
1. Implement per-atom analysis artifact generation
2. Implement disconnected subgraph detection (union-find on call graph + store-touch edges)
3. Implement full report generation and file output
4. Write tests ensuring analysis is purely computed from registry state

---

### Plan 8: BranchManager Facade and Integration

**Goal:** Create a unified facade that ties all branch subsystems together and integrates with the existing `WorkspaceManager`.

**Files to create:**

1. `scripts/spec_manager/spec_manager/branches/manager.py` -- Unified facade

**Files to modify:**

1. `scripts/spec_manager/spec_manager/refinement/workspace/manager.py` -- Add branch manager initialization
2. `scripts/spec_manager/spec_manager/branches/__init__.py` -- Export public API

**Data structures in `manager.py`:**

```python
class BranchManager:
    """Unified facade for the branch organization system.

    Integrates:
    - BranchLayout (directory structure)
    - AtomRegistry (shared atoms)
    - PinRegistry (atom-to-architecture mapping)
    - SliceNavigator (vertical/horizontal navigation)
    - PromotionEngine (upward flow)
    - DownwardFlowEngine (downward flow)
    - CollapseEngine (codebase ingestion)
    - AnalysisGenerator (computed analysis)
    """

    def __init__(self, run_root: Path) -> None: ...

    # Lifecycle
    def initialize(self, force: bool = False) -> list[str]: ...
    def is_initialized(self) -> bool: ...

    # Atom management
    def register_atom(self, descriptor: AtomDescriptor) -> None: ...
    def get_atom(self, atom_id: str) -> AtomDescriptor | None: ...
    def list_atoms(self, kind: AtomKind | None = None) -> list[AtomDescriptor]: ...

    # Pin management
    def register_pin(self, pin: PinFunction) -> None: ...
    def trace_forward(self, atom_id: str) -> list[PinFunction]: ...
    def trace_backward(self, location: str) -> PinFunction | None: ...

    # Promotion
    def promote(
        self,
        atom_ids: list[str] | None = None,
        skip_compliance: bool = False,
    ) -> PromotionResult: ...

    # Downward flow
    def trace_issue(self, issue: ArchitecturalIssue) -> DownwardTraceResult: ...

    # Collapse
    def collapse_codebase(self, source_dir: Path) -> CollapseResult: ...

    # Analysis
    def regenerate_analysis(self) -> AnalysisReport: ...

    # Navigation
    def navigate_down(self, atom_id: str) -> AtomDescriptor: ...
    def navigate_up(self, atom_id: str) -> list[PinFunction]: ...
    def navigate_across(self, slice_id: str) -> list[VerticalSlice]: ...

    # Slice management
    def create_slice(self, name: str, parent: str | None = None) -> VerticalSlice: ...
    def validate_store_monogamy(self) -> list[str]: ...
```

**Integration with existing WorkspaceManager:**

Add to `refinement/workspace/manager.py` `WorkspaceManager.__post_init__`:
```python
# Lazy initialization -- BranchManager is created on first access
self._branch_manager: BranchManager | None = None

@property
def branches(self) -> BranchManager:
    """Access the branch organization system."""
    if self._branch_manager is None:
        from spec_manager.branches.manager import BranchManager
        self._branch_manager = BranchManager(self.structure.root)
    return self._branch_manager
```

**Public API in `__init__.py`:**

```python
from .atoms import AtomRegistry
from .collapse import CollapseEngine, CollapseResult
from .compliance import ComplianceChecker, ComplianceGateResult
from .downward_flow import ArchitecturalIssue, DownwardFlowEngine, DownwardTraceResult
from .gap_detection import GapDetector, GapItem
from .layout import BranchLayout
from .manager import BranchManager
from .pins import DriftReport, PinRegistry
from .promotion import PromotionEngine, PromotionResult
from .slices import HorizontalLayer, SliceNavigator
from .analysis import AnalysisGenerator, AnalysisReport
from .types import (
    AtomDescriptor,
    AtomKind,
    BranchKind,
    PinFunction,
    ProjectionType,
    SliceOrientation,
    StoreType,
    VerticalSlice,
)
```

**Steps:**
1. Implement `BranchManager` as a facade delegating to subsystem classes
2. Add lazy `branches` property to `WorkspaceManager`
3. Add `branches_dir` to `RunFolderStructure.initialize()` subdirectory list
4. Update `branches/__init__.py` with all public exports
5. Write integration tests exercising the full lifecycle: initialize -> register atoms -> promote -> trace issue -> regenerate analysis

## Execution Instructions

Plans should be implemented in order (1 through 8). Each plan is independently reviewable but builds on the preceding plan's data structures.

- **Plan 1** establishes the foundation. All subsequent plans depend on `BranchLayout`, `AtomRegistry`, and the type definitions.
- **Plans 2-7** can be developed in parallel after Plan 1, but Plan 3 (promotion) depends on Plan 2 (pins). Plan 7 (analysis) depends on Plans 2 and 6.
- **Plan 8** must be implemented last as it integrates all subsystems.

Testing strategy:
- Each plan should include unit tests in `scripts/spec_manager/tests/branches/`
- Use `pytest -p no:randomly` for deterministic test ordering
- Plan 5 (collapse) should include integration tests against the labyrinth codebase at `scripts/spec_manager/spec_manager/labyrinth/`

## Success Criteria

1. `BranchLayout.initialize()` creates the full directory structure under `runs/{run_id}/branches/` matching the layout described in Plan 1.
2. `AtomRegistry` can register, list, and detect changes for atom descriptors with JSON roundtrip serialization.
3. `PinRegistry` supports forward trace (atom -> locations), backward trace (location -> atom), and drift detection with all four projection types.
4. `ComplianceChecker.check_all()` returns a `ComplianceGateResult` that correctly blocks promotion when any gate fails.
5. `GapDetector.scan_branch()` detects all comments and stub functions in a test algorithmic branch.
6. `PromotionEngine.promote()` creates pins and records promotion when compliance passes, and refuses promotion with errors when compliance fails.
7. `DownwardFlowEngine.trace_issue()` correctly traces an architectural issue back through pins to the originating atom.
8. `CollapseEngine.collapse()` can ingest the labyrinth test codebase and produce a classified set of atoms, stores, shapes, and architectural remnants.
9. `SliceNavigator` correctly enforces store monogamy and supports navigate_down/up/across.
10. `AnalysisGenerator.generate()` produces a complete `AnalysisReport` from the current registry state without manual editing.
11. `BranchManager` facade provides a single entry point that delegates to all subsystems.
12. `WorkspaceManager.branches` property provides lazy access to the branch system.
13. All dataclass types support `to_dict()`/`from_dict()` roundtrip serialization.
14. Test coverage for the `branches/` package exceeds 80%.
# Implementation Plan: Lineage Tracking and Import Graph

## Overview

Build a lineage tracking system that records how algorithmic atoms (pin-functions) map to architectural locations through destructive transformations, with an import graph for static analysis, forward/backward trace queries, data flow projection tracking, and drift detection.

## Current State (Problems)

1. **Existing `LineageEdge` is under-specified for projection tracking.** The current `LineageEdge` in `scripts/spec_manager/spec_manager/core/provenance.py` (line 440) tracks generic transformations (`split`, `merge`, `infer`, `transform`) between content units during spec processing. It has no notion of architectural projection types (pass_through, event_bridge, middleware_wrap, etc.), no confidence scoring, and no concept of atom-to-architecture mapping.

2. **Existing `LineageTable` is content-processing-oriented.** The `LineageTable` class in `provenance.py` (line 471) provides ancestor/descendant traversal and transformation path tracing, but only for spec content units. It lacks the query APIs needed for projection lineage: "show all arch locations for this atom" or "show what atom this middleware implements."

3. **No import graph infrastructure exists.** There is no static analysis of Python `import`/`from ... import` statements to build the atom-to-architectural-location graph. The design document (Section 11) specifies that pin-functions are importable and that `grep for imports of the changed function` reveals affected locations.

4. **No data flow projection tracking.** ALGORITHM.md Phase 5 defines signal tracing (pass-through, projection/slice, aggregation/smear), but there is no implementation tracking how data signals transform through architectural hops.

5. **No drift detection for pin targets.** The existing `AtomAwareDriftComparator` in `scripts/spec_manager/spec_manager/projection/drift.py` compares projections against spec indexes using atom fingerprints, but does not detect when a pin-function's signature changed, its file moved, or architectural wrappers became stale.

## Target State

A self-contained `lineage` subpackage under `projection/` that:
- Defines `ProjectionLineageEdge` with transformation types from the design document
- Provides a `ProjectionLineageTable` queryable by from/to/transformation/confidence
- Builds an import graph from Python source via `ast` analysis
- Supports forward trace ("atom -> all arch locations") and backward trace ("arch location -> source atom")
- Tracks data flow projections (signal in/out/stores per hop)
- Detects drift when pin targets no longer match (signature changes, file moves)
- Persists to JSON and integrates with the existing workspace indexes system

## Additional Info

- The existing `LineageEdge`/`LineageTable` in `provenance.py` must NOT be modified. They serve spec content tracking. The new system is specifically for algorithm-to-architecture projection tracking.
- The existing `DriftItem` types in `projection/drift.py` are `PLAN_ONLY`, `MISMATCH`, `MISSING_PIN`, `PIN_TARGET_MISSING`. The new drift detection adds `SIGNATURE_CHANGED`, `FILE_MOVED`, `WRAPPER_STALE`.
- Pydantic is used for schemas (see `schemas/projection.py`), dataclasses for internal data structures (see `projection/drift.py`).
- Workspace indexes are stored under `workspace/indexes/` as JSON files (see `WorkspaceManager.write_edge_list` pattern).
- Test structure: tests for the projection module do not yet exist. New tests should follow the pattern in `labyrinth/tests/`.

## Plans

### Plan 1: ProjectionLineageEdge and Transformation Types

Create the core data structures for projection-specific lineage edges.

**Files to create:**
- `scripts/spec_manager/spec_manager/projection/lineage/__init__.py`
- `scripts/spec_manager/spec_manager/projection/lineage/edges.py`

**Data structures in `edges.py`:**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TransformationType(Enum):
    """How an atom was projected into architecture.

    From algorithmic-projection-patch.md Section 11 and ALGORITHM.md Phase 5.
    """
    PASS_THROUGH = "pass_through"        # Architecture imports and calls atom directly
    EVENT_BRIDGE = "event_bridge"        # Atom wrapped in event handler
    MIDDLEWARE_WRAP = "middleware_wrap"   # Atom wrapped in middleware layer
    RETRY_DECORATE = "retry_decorate"    # Atom wrapped with retry/resilience
    SLICE = "slice"                      # Architecture uses subset of atom output
    SMEAR = "smear"                      # Architecture combines multiple atoms
    INTRODUCTION = "introduction"        # Architecture adds new algo (no source atom)


@dataclass
class ProjectionLineageEdge:
    """An edge mapping an algorithmic atom to an architectural location.

    Attributes:
        from_unit: Algorithmic atom ID (pin-function name or atom ID).
        to_unit: Architectural location (file:class.method or module path).
        transformation: How the atom was projected into architecture.
        confidence: 1.0 for mechanical (direct import), <1.0 for inferred.
        timestamp: When this edge was recorded.
        details: Additional metadata (e.g., wrapper function name, event topic).
        pin_id: Optional associated pin ID from projection artifacts.
    """
    from_unit: str
    to_unit: str
    transformation: TransformationType
    confidence: float = 1.0
    timestamp: datetime = field(default_factory=datetime.now)
    details: dict[str, Any] = field(default_factory=dict)
    pin_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "from_unit": self.from_unit,
            "to_unit": self.to_unit,
            "transformation": self.transformation.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "pin_id": self.pin_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionLineageEdge:
        """Deserialize from dictionary."""
        return cls(
            from_unit=data["from_unit"],
            to_unit=data["to_unit"],
            transformation=TransformationType(data["transformation"]),
            confidence=data.get("confidence", 1.0),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            details=data.get("details", {}),
            pin_id=data.get("pin_id"),
        )
```

**`__init__.py`** exposes `TransformationType`, `ProjectionLineageEdge`, and (from later plans) `ProjectionLineageTable`, `ImportGraph`, query functions.

**Steps:**
1. Create `scripts/spec_manager/spec_manager/projection/lineage/` directory
2. Implement `edges.py` with `TransformationType` enum and `ProjectionLineageEdge` dataclass
3. Implement `__init__.py` with lazy imports following the pattern in `projection/__init__.py`
4. Add unit tests in `scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py`

**Tests:**
- `test_transformation_type_values`: All enum values match design doc strings
- `test_edge_roundtrip_serialization`: `to_dict()` / `from_dict()` roundtrip preserves all fields
- `test_edge_default_confidence`: Default confidence is 1.0
- `test_edge_introduction_no_from_unit`: Introduction edges can have empty `from_unit`

---

### Plan 2: ProjectionLineageTable with Query API

Build the queryable collection of projection lineage edges.

**Files to create:**
- `scripts/spec_manager/spec_manager/projection/lineage/table.py`

**Data structure:**

```python
class ProjectionLineageTable:
    """Collection of projection lineage edges with query support.

    Provides forward trace (atom -> arch locations), backward trace
    (arch location -> atoms), and filtering by transformation type
    and confidence threshold.
    """

    def __init__(self) -> None:
        self.edges: list[ProjectionLineageEdge] = []
        self._by_from: dict[str, list[ProjectionLineageEdge]]   # index
        self._by_to: dict[str, list[ProjectionLineageEdge]]     # index
        self._by_transformation: dict[TransformationType, list[ProjectionLineageEdge]]

    # --- Mutation ---
    def add_edge(
        self,
        from_unit: str,
        to_unit: str,
        transformation: TransformationType,
        confidence: float = 1.0,
        details: dict[str, Any] | None = None,
        pin_id: str | None = None,
    ) -> ProjectionLineageEdge: ...

    def remove_edges_for(self, unit_id: str) -> int: ...

    # --- Forward trace: atom -> arch locations ---
    def trace_forward(
        self,
        from_unit: str,
        min_confidence: float = 0.0,
    ) -> list[ProjectionLineageEdge]: ...

    # --- Backward trace: arch location -> atoms ---
    def trace_backward(
        self,
        to_unit: str,
        min_confidence: float = 0.0,
    ) -> list[ProjectionLineageEdge]: ...

    # --- Filter by transformation ---
    def edges_by_transformation(
        self,
        transformation: TransformationType,
    ) -> list[ProjectionLineageEdge]: ...

    # --- Find orphans ---
    def find_orphan_atoms(self, known_atoms: set[str]) -> set[str]: ...
    def find_orphan_arch_locations(self, known_locations: set[str]) -> set[str]: ...

    # --- Find introductions (no source atom) ---
    def find_introductions(self) -> list[ProjectionLineageEdge]: ...

    # --- Serialization ---
    def to_dict(self) -> list[dict[str, Any]]: ...

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> ProjectionLineageTable: ...
```

**Steps:**
1. Implement `ProjectionLineageTable` in `table.py`
2. Implement three internal indexes: `_by_from`, `_by_to`, `_by_transformation` (all `defaultdict(list)`)
3. Implement `trace_forward` and `trace_backward` with optional `min_confidence` filter
4. Implement orphan detection: atoms with no forward edges, arch locations with no backward edges
5. Implement `find_introductions`: edges where `transformation == INTRODUCTION`
6. Implement JSON serialization/deserialization following the `LineageTable.to_dict` pattern from `provenance.py`
7. Add unit tests in `scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py`

**Tests:**
- `test_add_edge_indexes_correctly`: Adding an edge updates all three indexes
- `test_trace_forward_returns_all_arch_locations`: Given atom with 3 edges, returns all 3
- `test_trace_forward_respects_min_confidence`: Only returns edges above threshold
- `test_trace_backward_returns_source_atoms`: Given arch location, returns source atoms
- `test_find_orphan_atoms`: Atoms in `known_atoms` but not in any edge `from_unit`
- `test_find_introductions`: Only returns edges with `INTRODUCTION` transformation
- `test_table_roundtrip_serialization`: `to_dict()` / `from_dict()` preserves all edges and indexes
- `test_remove_edges_for`: Removes edges and updates indexes

---

### Plan 3: Import Graph Builder (Static Analysis)

Build Python import graph from source files using `ast` module analysis.

**Files to create:**
- `scripts/spec_manager/spec_manager/projection/lineage/import_graph.py`

**Data structures and API:**

```python
@dataclass
class ImportEdge:
    """A single import relationship."""
    importer_file: str          # File that contains the import statement
    importer_location: str      # file:class.method or file:module-level
    imported_name: str          # The name being imported (function/class)
    imported_from_module: str   # The module being imported from
    imported_from_file: str     # Resolved file path (if resolvable)
    line_no: int                # Line number of the import statement
    is_direct: bool = True      # Direct import vs re-export


class ImportGraph:
    """Graph of Python import relationships.

    Built from static analysis of ast.Import and ast.ImportFrom nodes.
    Enables "who imports function X?" queries for pin-function tracing.
    """

    def __init__(self) -> None:
        self.edges: list[ImportEdge] = []
        self._by_imported_name: dict[str, list[ImportEdge]]   # name -> importers
        self._by_importer_file: dict[str, list[ImportEdge]]   # file -> imports

    # --- Build ---
    @classmethod
    def build_from_directory(
        cls,
        root_dir: Path,
        exclude_patterns: list[str] | None = None,
    ) -> ImportGraph: ...

    @classmethod
    def build_from_files(
        cls,
        file_paths: list[Path],
    ) -> ImportGraph: ...

    def _analyze_file(self, file_path: Path) -> list[ImportEdge]: ...

    # --- Query ---
    def importers_of(self, function_name: str) -> list[ImportEdge]: ...

    def imports_in(self, file_path: str) -> list[ImportEdge]: ...

    def resolve_module_to_file(
        self,
        module_path: str,
        search_roots: list[Path],
    ) -> str | None: ...

    # --- Serialization ---
    def to_dict(self) -> list[dict[str, Any]]: ...

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> ImportGraph: ...
```

**Implementation approach for `_analyze_file`:**

```python
import ast

def _analyze_file(self, file_path: Path) -> list[ImportEdge]:
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    edges = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                edges.append(ImportEdge(
                    importer_file=str(file_path),
                    importer_location=f"{file_path}:module-level",
                    imported_name=alias.asname or alias.name,
                    imported_from_module=module,
                    imported_from_file="",  # resolved later
                    line_no=node.lineno,
                ))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                edges.append(ImportEdge(
                    importer_file=str(file_path),
                    importer_location=f"{file_path}:module-level",
                    imported_name=alias.asname or alias.name,
                    imported_from_module=alias.name,
                    imported_from_file="",
                    line_no=node.lineno,
                ))
    return edges
```

**Steps:**
1. Implement `ImportEdge` dataclass
2. Implement `ImportGraph` class with `_analyze_file` using `ast.parse` + `ast.walk`
3. Implement `build_from_directory` that walks `.py` files, skipping `__pycache__` and configurable exclude patterns
4. Implement `importers_of(function_name)` that queries `_by_imported_name` index
5. Implement `resolve_module_to_file` for dotted module paths to filesystem paths
6. Add unit tests in `scripts/spec_manager/spec_manager/projection/lineage/tests/test_import_graph.py`

**Tests:**
- `test_analyze_import_from`: Parses `from module import name` correctly
- `test_analyze_import`: Parses `import module` correctly
- `test_analyze_aliased_import`: Handles `import X as Y` and `from X import Y as Z`
- `test_importers_of`: Given files that import `validate_payment`, returns all importers
- `test_build_from_directory_excludes_pycache`: Skips `__pycache__` directories
- `test_resolve_module_to_file`: Resolves `spec_manager.core.provenance` to actual file
- `test_graph_roundtrip_serialization`: Serialization preserves all edges

---

### Plan 4: Lineage Builder (Import Graph to Lineage Edges)

Bridge the import graph with the lineage table: infer `ProjectionLineageEdge` entries from import relationships and classify transformation types.

**Files to create:**
- `scripts/spec_manager/spec_manager/projection/lineage/builder.py`

**API:**

```python
@dataclass
class AtomDefinition:
    """A registered atom (pin-function) for lineage tracking."""
    atom_id: str             # e.g., "validate_payment"
    function_name: str       # Python function name
    file_path: str           # File where atom is defined
    module_path: str         # Python module path
    signature_hash: str      # Hash of function signature for drift detection


class LineageBuilder:
    """Builds ProjectionLineageTable from ImportGraph and atom definitions."""

    def __init__(
        self,
        import_graph: ImportGraph,
        atoms: list[AtomDefinition],
    ) -> None: ...

    def build_lineage(self) -> ProjectionLineageTable:
        """Build lineage table by matching imports against known atoms."""
        ...

    def _classify_transformation(
        self,
        import_edge: ImportEdge,
        atom: AtomDefinition,
        importer_context: str,
    ) -> tuple[TransformationType, float]:
        """Classify the transformation type and assign confidence.

        Returns:
            (transformation_type, confidence)

        Classification rules:
        - Direct import + direct call: PASS_THROUGH, confidence=1.0
        - Import in event handler class: EVENT_BRIDGE, confidence=0.9
        - Import in middleware class: MIDDLEWARE_WRAP, confidence=0.9
        - Import in retry/resilience wrapper: RETRY_DECORATE, confidence=0.9
        - Import but only partial fields used: SLICE, confidence=0.8
        - Multiple atoms imported in same handler: SMEAR, confidence=0.8
        - No atom import (arch-only code): INTRODUCTION, confidence=1.0
        """
        ...

    def _detect_handler_pattern(self, file_path: str) -> str | None:
        """Detect if a file follows event handler, middleware, or retry patterns.

        Uses AST analysis to check class bases and decorator patterns.
        Returns pattern name or None.
        """
        ...
```

**Steps:**
1. Implement `AtomDefinition` dataclass
2. Implement `LineageBuilder.__init__` that indexes atoms by function name
3. Implement `build_lineage` that iterates import graph edges, matches against atoms, classifies transformations
4. Implement `_classify_transformation` with heuristic rules based on importer context
5. Implement `_detect_handler_pattern` using AST analysis of class decorators and base classes
6. Add tests in `scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py`

**Tests:**
- `test_direct_import_classified_as_pass_through`: Direct function call = PASS_THROUGH
- `test_event_handler_classified_as_event_bridge`: Import in handler class = EVENT_BRIDGE
- `test_no_matching_atom_skipped`: Imports not matching any atom are ignored
- `test_multiple_atoms_in_handler_classified_as_smear`: Multiple atoms = SMEAR
- `test_confidence_scoring`: Direct import = 1.0, handler patterns = 0.9, inferred = 0.8

---

### Plan 5: Data Flow Projection Tracking

Track how data signals transform through architectural hops.

**Files to create:**
- `scripts/spec_manager/spec_manager/projection/lineage/data_flow.py`

**Data structures:**

```python
@dataclass
class SignalSpec:
    """Data signal specification for a function/step."""
    signals_in: list[str]     # Input signal names (parameter names or types)
    signals_out: list[str]    # Output signal names (return type fields)
    stores_read: list[str]    # Stores read from
    stores_written: list[str] # Stores written to


@dataclass
class DataFlowHop:
    """A single hop in data flow through architecture."""
    source_unit: str          # Where signal comes from
    target_unit: str          # Where signal goes to
    signals_passed: list[str] # Which signals are passed through
    signals_dropped: list[str]# Which signals are dropped (slice)
    signals_added: list[str]  # Which signals are added (enrichment)
    hop_type: TransformationType


class DataFlowTracker:
    """Tracks data signal projections through architectural hops.

    For each lineage edge, tracks which signals pass through,
    which are dropped (slice), and which are added.
    """

    def __init__(self, lineage_table: ProjectionLineageTable) -> None: ...

    def register_signal_spec(
        self,
        unit_id: str,
        spec: SignalSpec,
    ) -> None: ...

    def compute_flow_projection(
        self,
        from_unit: str,
        to_unit: str,
    ) -> DataFlowHop | None: ...

    def find_signal_loss(self) -> list[DataFlowHop]: ...

    def get_store_touch_graph(self) -> dict[str, list[str]]: ...
```

**Steps:**
1. Implement `SignalSpec` and `DataFlowHop` dataclasses
2. Implement `DataFlowTracker` with signal spec registration
3. Implement `compute_flow_projection` that compares signal specs across a lineage edge
4. Implement `find_signal_loss` that identifies hops where signals are dropped
5. Implement `get_store_touch_graph` mapping stores to units that touch them
6. Add tests in `scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py`

**Tests:**
- `test_pass_through_preserves_all_signals`: No signal loss for PASS_THROUGH
- `test_slice_detects_dropped_signals`: Subset of signals = signals_dropped populated
- `test_store_touch_graph`: Correctly maps stores to reading/writing units
- `test_find_signal_loss_returns_only_lossy_hops`: Filters to hops with dropped signals

---

### Plan 6: Drift Detection for Pin Targets

Detect when pin targets no longer match their expected state.

**Files to create:**
- `scripts/spec_manager/spec_manager/projection/lineage/drift_detector.py`

**Data structures and API:**

```python
class DriftKind(Enum):
    """Types of drift between pin and target."""
    SIGNATURE_CHANGED = "signature_changed"   # Function signature changed
    FILE_MOVED = "file_moved"                 # File no longer at expected path
    FUNCTION_REMOVED = "function_removed"     # Function no longer exists
    WRAPPER_STALE = "wrapper_stale"           # Wrapper no longer matches atom
    IMPORT_BROKEN = "import_broken"           # Import no longer resolves


@dataclass
class PinDrift:
    """A detected drift for a pin target."""
    edge: ProjectionLineageEdge   # The affected lineage edge
    drift_kind: DriftKind
    expected: str                 # What was expected (old signature, old path)
    actual: str                   # What was found (new signature, new path, "missing")
    severity: str                 # "error" | "warning" | "info"


class PinDriftDetector:
    """Detects drift in pin targets.

    Checks that:
    1. Pin target files still exist at expected paths
    2. Pin target functions still have expected signatures
    3. Import relationships still resolve
    4. Wrappers still correctly wrap their atoms
    """

    def __init__(
        self,
        lineage_table: ProjectionLineageTable,
        atoms: list[AtomDefinition],
    ) -> None: ...

    def detect_all_drift(self) -> list[PinDrift]: ...

    def detect_file_drift(self, edge: ProjectionLineageEdge) -> PinDrift | None: ...

    def detect_signature_drift(
        self,
        edge: ProjectionLineageEdge,
        atom: AtomDefinition,
    ) -> PinDrift | None: ...

    def detect_import_drift(
        self,
        edge: ProjectionLineageEdge,
        import_graph: ImportGraph,
    ) -> PinDrift | None: ...

    def _compute_current_signature_hash(self, file_path: str, function_name: str) -> str | None:
        """Use ast to extract current function signature and hash it."""
        ...
```

**Steps:**
1. Implement `DriftKind` enum and `PinDrift` dataclass
2. Implement `PinDriftDetector` class
3. Implement `detect_file_drift`: checks `Path(edge.to_unit.split(':')[0]).exists()`
4. Implement `detect_signature_drift`: uses `ast.parse` to extract function signature, compares hash with `AtomDefinition.signature_hash`
5. Implement `detect_import_drift`: verifies import edge still resolves in current import graph
6. Implement `detect_all_drift`: runs all checks on all edges, returns combined list
7. Add tests in `scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py`

**Tests:**
- `test_detect_file_moved`: File path in edge no longer exists
- `test_detect_signature_changed`: Function signature hash mismatch
- `test_detect_function_removed`: Function no longer in file
- `test_no_drift_for_valid_edges`: All checks pass, returns empty list
- `test_severity_assignment`: FILE_MOVED = error, SIGNATURE_CHANGED = warning

---

### Plan 7: Workspace Persistence and Integration

Integrate lineage tracking with the existing workspace and projection systems.

**Files to modify:**
- `scripts/spec_manager/spec_manager/projection/__init__.py` -- add lineage exports
- `scripts/spec_manager/spec_manager/refinement/workspace/manager.py` -- add read/write methods

**Files to create:**
- `scripts/spec_manager/spec_manager/projection/lineage/persistence.py`

**Persistence API in `persistence.py`:**

```python
def save_lineage_table(table: ProjectionLineageTable, path: Path) -> None:
    """Save lineage table to JSON file."""
    ...

def load_lineage_table(path: Path) -> ProjectionLineageTable:
    """Load lineage table from JSON file."""
    ...

def save_import_graph(graph: ImportGraph, path: Path) -> None:
    """Save import graph to JSON file."""
    ...

def load_import_graph(path: Path) -> ImportGraph:
    """Load import graph from JSON file."""
    ...
```

**WorkspaceManager additions:**

```python
# In WorkspaceManager class
def write_lineage_table(self, table: ProjectionLineageTable) -> Path:
    """Write lineage table to workspace/indexes/lineage_table.json."""
    ...

def read_lineage_table(self) -> ProjectionLineageTable | None:
    """Read lineage table from workspace/indexes/lineage_table.json."""
    ...

def write_import_graph(self, graph: ImportGraph) -> Path:
    """Write import graph to workspace/indexes/import_graph.json."""
    ...

def read_import_graph(self) -> ImportGraph | None:
    """Read import graph from workspace/indexes/import_graph.json."""
    ...
```

**Steps:**
1. Implement `persistence.py` with JSON read/write for lineage table and import graph
2. Add `write_lineage_table` and `read_lineage_table` to `WorkspaceManager` following the `write_edge_list` pattern at line 1194 of `manager.py`
3. Add `write_import_graph` and `read_import_graph` to `WorkspaceManager`
4. Update `projection/__init__.py` to export lineage module symbols
5. Add lineage table and import graph to the trace index in `trace_indexes.py` (new index files: `lineage_table.json`, `import_graph.json`)
6. Add integration tests

**Tests:**
- `test_lineage_table_persistence_roundtrip`: Write and read back preserves all edges
- `test_import_graph_persistence_roundtrip`: Write and read back preserves all edges
- `test_workspace_manager_lineage_integration`: Manager can write/read lineage table

---

## Execution Instructions

Execute plans sequentially (Plan 1 through Plan 7). Each plan builds on the previous:

1. **Plan 1** establishes the data model (no dependencies)
2. **Plan 2** builds the queryable table (depends on Plan 1 edges)
3. **Plan 3** builds import graph analysis (independent of Plans 1-2, but logically next)
4. **Plan 4** bridges import graph to lineage table (depends on Plans 1-3)
5. **Plan 5** adds data flow tracking (depends on Plans 1-2)
6. **Plan 6** adds drift detection (depends on Plans 1-4)
7. **Plan 7** wires everything into the workspace system (depends on all)

Run tests after each plan: `uv run python -m pytest scripts/spec_manager/spec_manager/projection/lineage/tests/ -v -p no:randomly`

## Success Criteria

1. **Unit test coverage**: All public methods of `ProjectionLineageTable`, `ImportGraph`, `LineageBuilder`, `DataFlowTracker`, and `PinDriftDetector` have tests
2. **Serialization roundtrip**: All data structures survive JSON roundtrip without data loss
3. **Forward trace**: Given an atom ID, `trace_forward` returns all architectural locations with correct transformation types
4. **Backward trace**: Given an architectural location, `trace_backward` returns all source atoms
5. **Import graph accuracy**: Running `ImportGraph.build_from_directory` on the spec_manager source tree produces edges matching actual import statements
6. **Drift detection**: `PinDriftDetector.detect_all_drift` correctly identifies moved files, changed signatures, and broken imports when test fixtures are modified
7. **Workspace integration**: `WorkspaceManager.write_lineage_table` / `read_lineage_table` roundtrips correctly
8. **No regression**: Existing `projection/drift.py` and `core/provenance.py` are not modified
9. **Transformation coverage**: All 7 transformation types from the design document are represented in the `TransformationType` enum and handled in the builder
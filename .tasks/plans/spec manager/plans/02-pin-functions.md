# Implementation Plan: Pin-Functions System

## Overview

Build the pin-function system that identifies atom functions in algorithmic code, extracts them into shared addressable units, constructs an import graph tracking which architectural locations import which pin-functions, and supports incremental change propagation when a pin-function changes.

## Current State (Problems)

1. **Projection pins are offset-based, not function-based.** The existing `Pin` schema (`scripts/spec_manager/spec_manager/schemas/projection.py`) maps character offsets in projection content to L1 entity IDs (libraries, elements, atom ranges). These pins track *where content came from* in a document sense, but they cannot represent that two layers share the same executable function.

2. **No concept of "atom functions" as shared units.** The `LineAtom` schema (`scripts/spec_manager/spec_manager/schemas/atoms.py`) represents individual lines with fingerprints. There is no higher-level construct representing a complete function that can be imported by multiple architectural locations.

3. **LineageEdge is document-level, not function-level.** The existing `LineageEdge` in `scripts/spec_manager/spec_manager/core/provenance.py` (L440-L468) tracks transformations between tracked units (split, merge, infer, transform) but has no concept of projection types (pass-through, wrapping, smearing) or import relationships.

4. **No AST-based import analysis.** The system currently uses text-based pattern matching for references (`AnnotationParser` in `core/annotations.py`). There is no `ast.Import` / `ast.ImportFrom` analysis to discover which architectural files import which algorithmic functions.

5. **Drift detection does not trace function-level changes.** The `AtomAwareDriftComparator` in `scripts/spec_manager/spec_manager/projection/drift.py` compares projection content against spec indexes using atom fingerprints, but cannot answer "when `validate_payment` changes, which architectural handlers must be reviewed?"

## Target State

A pin-function system where:
- Functions in algorithmic code are identified and registered as "atoms" (pin-functions)
- An import graph tracks which architectural files import which pin-functions
- Micro-addressing is supported: `function_name`, `function_name:L3-L5`, `composition:call_site`
- Projection types (pass-through, wrap, smear, introduction) are classified per-import
- When a pin-function changes, all importers are enumerated for review
- The system integrates with the existing projection and drift detection modules

## Additional Info

- The design document (Section 5 of `algorithmic-projection-patch.md`) specifies that pins are *actual extracted functions*, not annotation labels. Both the algorithmic layer and architectural layer literally import the same function.
- Pin-functions must support the edit-in-place engine (Task #4): when an atom function body changes, the system must know which architectural locations need re-verification.
- The existing `projection/` module generates plan.md with offset-based pins. Pin-functions operate at a different level -- they track Python function-level relationships, not document character offsets. The two pin systems are complementary.
- The codebase uses Pydantic `BaseModel` for schemas (see `schemas/`) and plain `@dataclass` for internal data structures (see `core/`). New schemas should follow this convention.
- The project uses `from __future__ import annotations` and `TYPE_CHECKING` guards for lazy imports to avoid circular dependencies (see `projection/__init__.py`).

## Plans

### Plan 1: Pin-Function Data Structures and Registry Schema

Define the core data models for pin-functions, the pin registry, and the import graph. These are the foundational types that all subsequent plans depend on.

**Files to create:**

- `scripts/spec_manager/spec_manager/schemas/pin_functions.py` -- Pydantic schemas for serialization/persistence
- `scripts/spec_manager/spec_manager/core/pin_registry.py` -- Runtime registry with query methods

**Data structures in `schemas/pin_functions.py`:**

```python
from pydantic import BaseModel, Field
from typing import Literal

# Projection type: how an architectural location uses a pin-function
ProjectionType = Literal[
    "PASS_THROUGH",    # Architecture imports and calls atom directly
    "WRAP",            # Architecture wraps atom in decorator/middleware/handler
    "SMEAR",           # Architecture combines multiple atoms into one location
    "INTRODUCTION",    # Architectural algorithm with no algorithmic origin
]

class PinFunction(BaseModel):
    """A registered atom function that both layers can import.

    Represents a decomposed algorithm step extracted as a shared function.
    """
    pin_func_id: str           # e.g., "PFUNC-0001"
    function_name: str         # Python qualified name, e.g., "validate_payment"
    module_path: str           # Module where defined, e.g., "atoms.payment"
    file_path: str             # Relative file path, e.g., "atoms/payment.py"
    line_start: int            # First line of function def
    line_end: int              # Last line of function body
    signature: str             # Function signature string, e.g., "(payment_data: dict) -> ValidationResult"
    docstring: str             # First line of docstring (summary)
    content_hash: str          # SHA-256 of function body (for change detection)
    is_shape: bool = False     # True if pure function (no side effects, no state)
    store_touches: list[str] = Field(default_factory=list)  # Store IDs touched by this function
    evidence_atom_ids: list[str] = Field(default_factory=list)  # Atoms supporting this function


class MicroAddress(BaseModel):
    """Precise address within or referencing a pin-function.

    Supports three addressing modes:
    - Function-level: pin_func_id only (whole function)
    - Line-range: pin_func_id + line_start/line_end (lines within function)
    - Call-site: composition_func + callee_pin_func_id (call site in composition)
    """
    pin_func_id: str                        # Target function
    line_start: int | None = None           # Optional: line range start (relative to function)
    line_end: int | None = None             # Optional: line range end
    composition_func: str | None = None     # Optional: enclosing composition function name


class ImportEdge(BaseModel):
    """A directed edge from a pin-function to an architectural location that imports it.

    Represents one usage of a pin-function in the architectural layer.
    """
    edge_id: str                            # e.g., "IMEDGE-0001"
    pin_func_id: str                        # Source: the pin-function being imported
    arch_location: str                      # Target: "file:class.method" or "file:function"
    arch_file_path: str                     # Relative path to architectural file
    arch_line: int                          # Line number of the import/call site
    projection_type: ProjectionType         # How the architecture uses this pin-function
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # 1.0 for detected imports, <1.0 for inferred
    is_direct_import: bool = True           # True if literal import, False if inferred usage


class PinFunctionRegistry(BaseModel):
    """Complete registry of all pin-functions and their import graph.

    Serializable artifact that represents the full state of the pin system.
    """
    schema_version: str = "1.0"
    pin_functions: list[PinFunction] = Field(default_factory=list)
    import_edges: list[ImportEdge] = Field(default_factory=list)
    created_at: str  # ISO-8601
```

**Runtime registry in `core/pin_registry.py`:**

```python
@dataclass
class PinRegistryIndex:
    """In-memory index for efficient pin-function queries.

    Provides O(1) lookups by function name, file path, and pin_func_id.
    Provides forward/reverse import graph traversal.
    """
    # Forward: pin_func_id -> [ImportEdge]
    _by_pin: dict[str, list[ImportEdge]]
    # Reverse: arch_location -> [ImportEdge]
    _by_arch_location: dict[str, list[ImportEdge]]
    # Lookup: function_name -> PinFunction
    _by_name: dict[str, PinFunction]
    # Lookup: pin_func_id -> PinFunction
    _by_id: dict[str, PinFunction]

    def get_importers(self, pin_func_id: str) -> list[ImportEdge]: ...
    def get_pin_functions_for_arch(self, arch_location: str) -> list[ImportEdge]: ...
    def get_by_name(self, function_name: str) -> PinFunction | None: ...
    def get_by_id(self, pin_func_id: str) -> PinFunction | None: ...
    def resolve_micro_address(self, addr: MicroAddress) -> PinFunction | None: ...
    def get_affected_locations(self, changed_pin_func_ids: list[str]) -> list[ImportEdge]: ...

    @classmethod
    def from_registry(cls, registry: PinFunctionRegistry) -> PinRegistryIndex: ...
```

**Integration points:**
- `PinFunction.evidence_atom_ids` links to the existing `LineAtom` IDs from `schemas/atoms.py`
- `PinFunction.content_hash` uses SHA-256 consistent with `LineAtom.sha256`
- `PinFunctionRegistry` follows the same serialization pattern as `SpecIndexV2` in `schemas/spec_index_v2.py`
- `ImportEdge.projection_type` maps to the projection types enumerated in Section 11 of the design document

**Update `schemas/__init__.py`** to export `PinFunction`, `ImportEdge`, `MicroAddress`, `PinFunctionRegistry`, and `ProjectionType`.

**Update `core/__init__.py`** to export `PinRegistryIndex`.

**Tests:** `scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py`
- Test PinFunction creation and validation
- Test ImportEdge creation with all ProjectionType variants
- Test MicroAddress resolution (function-level, line-range, call-site)
- Test PinRegistryIndex forward/reverse lookups
- Test `get_affected_locations` returns correct edges for changed pin-functions
- Test serialization round-trip (PinFunctionRegistry -> JSON -> PinFunctionRegistry)

---

### Plan 2: AST-Based Atom Function Extractor

Build the static analysis engine that scans Python source files to identify atom functions and extract their metadata. This is the "identification" step that populates the pin-function registry.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/ast_extractor.py` -- AST-based function extraction

**Key design decisions for atom identification:**

The extractor uses a combination of heuristics and optional annotations:
1. **Convention-based**: Functions in designated directories (e.g., `atoms/`, `shapes/`) are automatically pinned
2. **Size heuristic**: Functions with body <= N lines (configurable, default 30) that have a docstring are candidates
3. **Annotation override**: A `# @pin` comment or type annotation `Pin[T]` can explicitly mark/unmark functions
4. **Shape detection**: Functions that touch no stores and have no side effects (no I/O, no mutations of external state) are classified as shapes using AST analysis (no `global`, no attribute assignment on non-local objects, no `open()`, no `print()`)

**Public API in `analysis/ast_extractor.py`:**

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class AtomCandidate:
    """A function identified as a potential pin-function atom."""
    function_name: str
    qualified_name: str          # module.class.function
    file_path: str
    module_path: str
    line_start: int
    line_end: int
    signature: str
    docstring: str
    body_source: str             # Raw source of function body
    is_shape: bool               # Pure function detection result
    detection_method: str        # "convention", "heuristic", "annotation"
    store_references: list[str]  # Detected store accesses
    called_functions: list[str]  # Functions called within body

@dataclass
class ExtractionConfig:
    """Configuration for atom extraction."""
    atom_directories: list[str] = field(default_factory=lambda: ["atoms", "shapes"])
    max_function_lines: int = 30
    require_docstring: bool = True
    annotation_marker: str = "# @pin"
    exclude_patterns: list[str] = field(default_factory=lambda: ["test_", "_test", "conftest"])

class AtomFunctionExtractor:
    """Extracts atom function candidates from Python source files using AST analysis."""

    def __init__(self, config: ExtractionConfig | None = None): ...

    def extract_from_file(self, file_path: Path) -> list[AtomCandidate]: ...
    def extract_from_directory(self, dir_path: Path, recursive: bool = True) -> list[AtomCandidate]: ...
    def is_shape(self, node: ast.FunctionDef, file_path: Path) -> bool: ...
    def detect_store_references(self, node: ast.FunctionDef) -> list[str]: ...
    def extract_signature(self, node: ast.FunctionDef) -> str: ...
    def compute_body_hash(self, node: ast.FunctionDef, source: str) -> str: ...
```

**Implementation details:**
- Uses `ast.parse()` and `ast.walk()` to traverse Python files
- Extracts `ast.FunctionDef` and `ast.AsyncFunctionDef` nodes
- Computes `content_hash` from function body source using SHA-256 (consistent with `LineAtom.sha256`)
- Shape detection: walks function body AST looking for `ast.Global`, `ast.Nonlocal`, attribute mutations on non-`self` objects, `ast.Call` nodes to known I/O functions
- Store reference detection: looks for database/file/queue access patterns (configurable)

**Integration points:**
- Output `AtomCandidate` objects are converted to `PinFunction` schemas (Plan 1) by the registration step (Plan 4)
- `AtomCandidate.called_functions` feeds into the import graph builder (Plan 3) for composition analysis
- Works alongside existing `analysis/operations.py` which handles library-level restructuring -- this module handles function-level extraction

**Update `analysis/__init__.py`** to export `AtomFunctionExtractor`, `AtomCandidate`, `ExtractionConfig`.

**Tests:** `scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py`
- Test extraction from a file with mixed functions (some atoms, some not)
- Test convention-based detection (files in `atoms/` directory)
- Test heuristic detection (small functions with docstrings)
- Test annotation-based detection (`# @pin` marker)
- Test shape detection (pure functions vs. functions with side effects)
- Test signature extraction for various function signatures (args, kwargs, defaults, type hints)
- Test body hash computation is deterministic
- Test exclusion patterns (test files skipped)

---

### Plan 3: Import Graph Builder

Build the import graph that maps which architectural files import which pin-functions. This is the "tracing" step that connects the algorithmic layer to the architectural layer.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/import_graph.py` -- Import graph construction from AST analysis

**Public API:**

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ImportReference:
    """A detected import of a pin-function in an architectural file."""
    pin_func_name: str            # Name of the imported function
    import_module: str            # Module it was imported from
    file_path: str                # File containing the import
    import_line: int              # Line number of import statement
    usage_sites: list[UsageSite] # Where the function is actually called
    alias: str | None = None      # Import alias if renamed

@dataclass
class UsageSite:
    """A location where an imported pin-function is called."""
    line: int                     # Line number of the call
    enclosing_function: str       # Function/method containing the call
    enclosing_class: str | None   # Class containing the method (if any)
    call_pattern: str             # "direct", "wrapped", "partial", "lambda"

@dataclass
class ImportGraphConfig:
    """Configuration for import graph construction."""
    algorithmic_roots: list[str]  # Module paths considered algorithmic (e.g., ["atoms", "shapes"])
    architectural_roots: list[str]  # Module paths considered architectural (e.g., ["services", "handlers"])
    follow_reexports: bool = True  # Follow re-exports through __init__.py

class ImportGraphBuilder:
    """Builds the import graph between algorithmic and architectural layers."""

    def __init__(self, config: ImportGraphConfig): ...

    def build_graph(
        self,
        pin_functions: list[PinFunction],
        arch_directory: Path,
    ) -> list[ImportEdge]: ...

    def scan_file_imports(self, file_path: Path) -> list[ImportReference]: ...

    def classify_projection_type(
        self,
        reference: ImportReference,
        usage: UsageSite,
    ) -> ProjectionType: ...

    def detect_smeared_functions(
        self,
        references: list[ImportReference],
    ) -> list[tuple[str, list[str]]]: ...
```

**Projection type classification logic (`classify_projection_type`):**

| Pattern | Projection Type | Detection |
|---------|----------------|-----------|
| `result = pin_func(args)` | `PASS_THROUGH` | Direct call, return value used |
| `async def handler(event): pin_func(event.payload)` | `PASS_THROUGH` | Direct call inside handler/middleware |
| `@retry(max=3) def wrapped(): return pin_func(...)` | `WRAP` | Pin-function called inside a decorator-wrapped function |
| `def handler(): a = func_a(...); b = func_b(...); combine(a, b)` | `SMEAR` | Multiple pin-functions called in same enclosing function |
| Function with no pin-function imports | `INTRODUCTION` | No edges from algorithmic layer |

**Implementation details:**
- Scans architectural files for `ast.Import` and `ast.ImportFrom` nodes
- Matches imported names against registered pin-function names
- For each import, walks the AST to find all `ast.Call` nodes that reference the imported name
- Classifies each call site's projection type based on surrounding context
- Smear detection: when a single enclosing function imports and calls 2+ pin-functions

**Integration points:**
- Input `PinFunction` objects come from Plan 1 schemas
- Output `ImportEdge` objects are stored in `PinFunctionRegistry.import_edges` (Plan 1)
- `ImportGraphBuilder` is called by the orchestration layer (Plan 4) during registry population
- The builder reads files that are NOT in the spec_manager package itself -- it analyzes the *target project* being managed

**Tests:** `scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py`
- Test detection of direct imports (`from atoms.payment import validate_payment`)
- Test detection of module imports (`import atoms.payment; atoms.payment.validate_payment()`)
- Test aliased imports (`from atoms.payment import validate_payment as vp`)
- Test classification of PASS_THROUGH calls
- Test classification of WRAP calls (inside decorated functions)
- Test classification of SMEAR calls (multiple pin-functions in one handler)
- Test INTRODUCTION detection (architectural function with no pin-function imports)
- Test re-export following through `__init__.py`

---

### Plan 4: Change Propagation Engine

Build the engine that detects when pin-functions change and traces all affected architectural locations. This is the "incremental update" capability that makes the system useful for ongoing development.

**Files to create:**

- `scripts/spec_manager/spec_manager/projection/pin_propagation.py` -- Change detection and propagation

**Public API:**

```python
from dataclasses import dataclass, field

@dataclass
class PinChange:
    """A detected change in a pin-function."""
    pin_func_id: str
    function_name: str
    change_type: str        # "modified", "added", "removed", "signature_changed"
    old_content_hash: str | None
    new_content_hash: str | None
    old_signature: str | None
    new_signature: str | None
    diff_summary: str       # Human-readable change summary

@dataclass
class PropagationItem:
    """An architectural location that needs review due to a pin-function change."""
    import_edge: ImportEdge
    pin_change: PinChange
    review_urgency: str     # "auto_propagated", "review_required", "breaking_change"
    reason: str             # Why this location is affected

@dataclass
class PropagationReport:
    """Report of change propagation from pin-function changes."""
    changes: list[PinChange]
    propagation_items: list[PropagationItem]
    auto_propagated_count: int   # PASS_THROUGH changes (automatic)
    review_required_count: int   # WRAP/SMEAR changes (manual review)
    breaking_change_count: int   # Signature changes

class PinChangePropagator:
    """Detects pin-function changes and propagates to affected architectural locations."""

    def __init__(self, registry_index: PinRegistryIndex): ...

    def detect_changes(
        self,
        old_registry: PinFunctionRegistry,
        new_registry: PinFunctionRegistry,
    ) -> list[PinChange]: ...

    def propagate(self, changes: list[PinChange]) -> PropagationReport: ...

    def classify_urgency(
        self,
        change: PinChange,
        edge: ImportEdge,
    ) -> str: ...
```

**Urgency classification logic:**

| Change Type | Projection Type | Urgency |
|-------------|----------------|---------|
| Body modified | PASS_THROUGH | `auto_propagated` (same import, behavior changes automatically) |
| Body modified | WRAP | `review_required` (wrapper may depend on old behavior) |
| Body modified | SMEAR | `review_required` (aggregation may not work with new behavior) |
| Signature changed | Any | `breaking_change` (callers will fail) |
| Function removed | Any | `breaking_change` (imports will fail) |
| Function added | N/A | No propagation needed (no existing importers) |

**Integration with drift detection:**
- `PropagationReport` can be converted to `DriftItem` objects from `projection/drift.py` (L28-L47) for integration with the existing drift pipeline
- A utility function `convert_propagation_to_drift(report: PropagationReport) -> list[DriftItem]` bridges the two systems

**Integration with edit-in-place engine (Task #4):**
- When the edit-in-place engine modifies an atom function body, it produces a `PinChange` with `change_type="modified"` and the new content hash
- The propagator traces all affected architectural locations
- For `auto_propagated` items, the edit-in-place engine can proceed without intervention
- For `review_required` and `breaking_change` items, the engine flags these as manual review tasks

**Files to modify:**

- `scripts/spec_manager/spec_manager/projection/__init__.py` -- Add exports for `PinChangePropagator`, `PinChange`, `PropagationItem`, `PropagationReport`

**Tests:** `scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py`
- Test change detection: body modification (hash change)
- Test change detection: signature change
- Test change detection: function added/removed
- Test propagation for PASS_THROUGH edges (auto_propagated)
- Test propagation for WRAP edges (review_required)
- Test propagation for SMEAR edges (review_required)
- Test breaking change detection (signature change + any edge)
- Test conversion to DriftItem objects
- Test empty propagation (no changes detected)

---

### Plan 5: CLI Integration and Orchestration

Wire the pin-function system into the spec_manager CLI and provide the orchestration layer that ties Plans 1-4 together into user-facing commands.

**Files to create:**

- `scripts/spec_manager/spec_manager/pin_functions/__init__.py` -- Package init
- `scripts/spec_manager/spec_manager/pin_functions/orchestrator.py` -- High-level orchestration
- `scripts/spec_manager/spec_manager/pin_functions/cli.py` -- CLI commands (if using Click/Typer, follow existing CLI patterns)

**Orchestrator API:**

```python
class PinFunctionOrchestrator:
    """Orchestrates pin-function extraction, registration, and change tracking."""

    def __init__(self, project_root: Path, config: PinFunctionConfig | None = None): ...

    def scan(self) -> PinFunctionRegistry:
        """Full scan: extract atoms, build import graph, produce registry."""
        ...

    def diff(self, old_registry_path: Path) -> PropagationReport:
        """Compare current state to previous registry and report changes."""
        ...

    def query_importers(self, function_name: str) -> list[ImportEdge]:
        """Query which architectural locations import a given function."""
        ...

    def query_pin_functions_for(self, arch_file: str) -> list[PinFunction]:
        """Query which pin-functions a given architectural file uses."""
        ...

    def generate_analysis_file(self) -> str:
        """Generate the computed analysis artifact (Section 13 of design doc)."""
        ...
```

**CLI commands (following existing CLI patterns in `spec_manager/cli.py`):**

```
spec-manager pin scan [--project-root PATH] [--config PATH]
    # Scans project, extracts pin-functions, builds import graph, saves registry

spec-manager pin diff [--old-registry PATH] [--format json|text]
    # Compares current scan against previous registry, reports changes

spec-manager pin query --function NAME
    # Shows all architectural locations importing a given pin-function

spec-manager pin query --arch-file PATH
    # Shows all pin-functions used by a given architectural file

spec-manager pin analysis
    # Generates the analysis file (Section 13 computed artifact)
```

**Files to modify:**

- `scripts/spec_manager/spec_manager/cli.py` -- Add `pin` subcommand group

**Persistence:**
- Registry is saved as JSON at `{project_root}/.spec/pin_registry.json`
- Previous registries are kept for diff comparison at `{project_root}/.spec/pin_registry.{timestamp}.json`

**Tests:** `scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py`
- Test full scan on a fixture project with known atoms and architectural files
- Test diff detection between two registries
- Test query commands return correct results
- Test analysis file generation contains expected sections

## Execution Instructions

Execute plans sequentially (Plan 1 through Plan 5). Each plan is independently implementable and testable, but depends on the schemas/types defined in prior plans.

1. **Plan 1** establishes all data structures. No external dependencies. Test with unit tests for model validation and serialization.
2. **Plan 2** requires only `ast` (stdlib) and Plan 1 schemas. Test with fixture Python files containing various function patterns.
3. **Plan 3** requires Plan 1 schemas and Plan 2's `AtomCandidate` for context. Test with fixture projects containing import relationships.
4. **Plan 4** requires Plan 1's `PinRegistryIndex` and `PinFunctionRegistry`. Test with before/after registry snapshots.
5. **Plan 5** requires all prior plans. Test with end-to-end fixture projects.

For each plan, run tests with: `uv run python -m pytest scripts/spec_manager/spec_manager/labyrinth/tests/test_<module>.py -v`

## Success Criteria

1. **Pin-function extraction**: Given a Python project with clearly defined atom functions, `AtomFunctionExtractor.extract_from_directory()` identifies all atoms with correct metadata (name, signature, line range, body hash).
2. **Import graph accuracy**: Given a project where architectural files import atom functions, `ImportGraphBuilder.build_graph()` produces edges with correct projection type classification for all four types (PASS_THROUGH, WRAP, SMEAR, INTRODUCTION).
3. **Change propagation correctness**: Given a registry diff where one pin-function body changes, `PinChangePropagator.propagate()` returns all and only the architectural locations that import that function, with correct urgency classification.
4. **Micro-addressing resolution**: `PinRegistryIndex.resolve_micro_address()` correctly resolves all three address modes (function-level, line-range, call-site).
5. **Serialization round-trip**: `PinFunctionRegistry` serializes to JSON and deserializes back with no data loss for all field types.
6. **Integration with drift pipeline**: `convert_propagation_to_drift()` produces valid `DriftItem` objects that are accepted by the existing `AtomAwareDriftComparator`.
7. **Test coverage**: Each plan has corresponding test files with >90% line coverage of the new modules.

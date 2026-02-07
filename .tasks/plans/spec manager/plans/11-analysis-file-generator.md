# Implementation Plan

## Overview

Build the analysis file generator -- a stateless, on-demand computed artifact that maps algorithmic atoms to their architectural projections via the pin-function import graph and lineage table. The generator produces a Markdown + JSON report covering forward traces, projection type annotations, adjacency edges, unimplemented atoms, orphaned architecture, and data flow summaries.

## Current State (Problems)

1. **No algorithmic-to-architectural mapping exists.** The existing `analysis/` module (`scripts/spec_manager/spec_manager/analysis/operations.py`) handles library-level restructuring (divergence/convergence/reference analysis) but has no concept of pin-functions, atom-level import graphs, or projection type tracking.

2. **Report generation is library-scoped.** The current report generators in `scripts/spec_manager/spec_manager/refinement/workflows/reports.py` (coverage, compliance, drift, run audit) operate on spec elements, sections, and tasks -- not on atom-to-architecture lineage.

3. **Projection schema is offset-based only.** The existing `schemas/projection.py` defines `Pin` with `from_projection_offset` targeting LIBRARY/ELEMENT/ATOM_RANGE entities. There is no lineage edge schema capturing transformation types (pass-through, wrap, smear, introduction).

4. **No adjacency graph.** Co-occurrence edges and store-touch edges (Section 10 of the design doc) are referenced conceptually but have no data structure or builder.

5. **No data flow summary per atom.** The design doc (Section 11, 13) calls for signals-in/signals-out/stores-touched per atom, which does not exist.

## Target State

A new `analysis/projection` submodule that:
- Accepts the algorithmic atom registry and architectural source tree as inputs
- Traverses the pin-function import graph to build forward traces
- Classifies each import as pass-through, wrap, smear, or introduction
- Builds adjacency edges (co-occurrence + store-touch)
- Flags unimplemented atoms and orphaned architecture
- Summarizes data flow per atom (signals in/out, stores touched)
- Outputs a regenerable Markdown report + structured JSON artifact
- Integrates with the existing CLI via a new `generate-analysis` command
- Integrates with the existing report pipeline for inclusion in run audits

## Additional Info

### Design Constraints (from Section 13 of the design doc)

- **Never manually maintained** -- always computed from current code state
- **No persistent state** -- regenerated on demand
- **Projection of the import graph** -- the analysis file is derived from `import` statements tracing atom functions across layers
- **Triggered on demand** -- not automatically after every edit; explicitly invoked via CLI or programmatic API

### Relationship to Existing Modules

- `analysis/operations.py` -- library restructuring; orthogonal to this work. The new module lives alongside it in `analysis/`.
- `schemas/projection.py` -- existing Pin/ProjectionArtifact schemas; the new LineageEdge schema extends the conceptual model but is a separate concern.
- `refinement/workflows/reports.py` -- existing report generators; the new analysis report follows the same pattern (`generate_X_report(manager) -> str`).
- `refinement/workflows/trace_indexes.py` -- existing trace index builders; the new module consumes atom-to-section indexes but builds its own forward-trace index.
- `utils/graph.py` -- existing graph utilities (Kahn's algorithm, cycle detection, Mermaid generation); reusable for adjacency graph operations.

### Output Format Decision

Both Markdown and JSON. The Markdown report is human-readable and suitable for review/audit. The JSON artifact is machine-readable and suitable for downstream tooling (drift detection, change propagation). This matches the existing dual-format pattern used by edge lists (`write_edge_list_json` + Markdown reports).

## Plans

### Plan 1: Lineage Edge Schema and Data Structures

Define the core data model for the analysis file generator. All subsequent plans depend on these types.

**Files to create:**

`scripts/spec_manager/spec_manager/schemas/lineage.py`

```python
"""Schemas for algorithmic-to-architectural lineage edges."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LineageEdge(BaseModel):
    """A directed edge from an algorithmic atom to an architectural location.

    Attributes:
        from_atom: Algorithmic atom ID (pin-function name or ATOM-* ID)
        to_location: Architectural location (file_path:class.method or file_path:function)
        transformation: How the atom was projected into architecture
        confidence: 1.0 for mechanical (import-based), <1.0 for inferred
        import_path: The Python import path if mechanically detected
        evidence: Optional textual evidence supporting this edge
    """

    from_atom: str
    to_location: str
    transformation: Literal[
        "pass_through",   # Architecture imports and calls atom directly
        "wrap",           # Architecture wraps atom with additional logic
        "smear",          # Architecture combines multiple atoms
        "introduction",   # Architecture introduces algorithm with no atom source
    ]
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    import_path: str | None = None
    evidence: str | None = None


class AtomAdjacency(BaseModel):
    """Adjacency edges for an algorithmic atom.

    Attributes:
        atom_id: The atom identifier
        co_occurrence_edges: Atoms that co-occur in the same evidence window / section
        store_touch_edges: Atoms that read/write the same stores
    """

    atom_id: str
    co_occurrence_edges: list[str] = Field(default_factory=list)
    store_touch_edges: list[str] = Field(default_factory=list)


class DataFlowSummary(BaseModel):
    """Data flow summary for an atom.

    Attributes:
        atom_id: The atom identifier
        signals_in: Parameter names / types consumed
        signals_out: Return values / types produced
        stores_touched: Store identifiers read or written
    """

    atom_id: str
    signals_in: list[str] = Field(default_factory=list)
    signals_out: list[str] = Field(default_factory=list)
    stores_touched: list[str] = Field(default_factory=list)


class AtomAnalysisEntry(BaseModel):
    """Complete analysis entry for a single atom.

    Attributes:
        atom_id: The atom identifier (function name or ATOM-* ID)
        atom_file: File where the atom is defined
        forward_traces: All architectural locations importing this atom
        adjacency: Co-occurrence and store-touch edges
        data_flow: Signals in/out/stores touched
        is_unimplemented: True if atom has no architectural imports
    """

    atom_id: str
    atom_file: str
    forward_traces: list[LineageEdge] = Field(default_factory=list)
    adjacency: AtomAdjacency | None = None
    data_flow: DataFlowSummary | None = None
    is_unimplemented: bool = False


class OrphanedArchEntry(BaseModel):
    """An architectural location with no atom imports.

    Attributes:
        location: File path and function/class
        description: What the orphaned code appears to do
        suggested_action: Recommended remediation
    """

    location: str
    description: str = ""
    suggested_action: Literal[
        "create_atom",        # Should be an atom but was never extracted
        "mark_introduction",  # Legitimate architectural introduction
        "investigate",        # Unclear, needs manual review
    ] = "investigate"


class AnalysisFileSchema(BaseModel):
    """Top-level schema for the analysis file artifact.

    Attributes:
        run_id: The run that generated this analysis
        generated_at: ISO-8601 timestamp
        atoms: Per-atom analysis entries
        orphaned_architecture: Architectural code with no atom imports
        summary: Aggregate statistics
    """

    run_id: str
    generated_at: str
    atoms: list[AtomAnalysisEntry] = Field(default_factory=list)
    orphaned_architecture: list[OrphanedArchEntry] = Field(default_factory=list)
    summary: dict[str, int | float] = Field(default_factory=dict)
```

**Files to create:**

`tests/spec_manager/schemas/test_lineage.py`

```python
"""Tests for lineage schema validation."""
# Tests for:
# - LineageEdge field validation (transformation enum, confidence range)
# - AtomAnalysisEntry serialization round-trip
# - AnalysisFileSchema with empty and populated atoms
# - OrphanedArchEntry suggested_action enum validation
```

**Estimated scope:** ~150 lines of production code, ~100 lines of tests.

---

### Plan 2: Import Graph Traversal Engine

Build the core engine that scans architectural source files for imports of algorithmic atom functions and constructs forward traces.

**Files to create:**

`scripts/spec_manager/spec_manager/analysis/import_scanner.py`

```python
"""Scan architectural source files for imports of algorithmic atom functions."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImportHit:
    """A detected import of an atom function in an architectural file."""

    atom_name: str
    arch_file: str
    arch_location: str       # file:class.method or file:function
    import_statement: str    # The raw import line
    usage_sites: list[str] = field(default_factory=list)  # line numbers where used


def scan_file_imports(
    file_path: Path,
    atom_names: set[str],
) -> list[ImportHit]:
    """Scan a single Python file for imports of known atom functions.

    Uses AST parsing to detect:
    - `from atoms.module import atom_func`
    - `import atoms.module` followed by `atoms.module.atom_func()` usage
    - Direct function calls matching atom names

    Args:
        file_path: Path to the architectural Python file.
        atom_names: Set of known atom function names.

    Returns:
        List of ImportHit records for detected atom imports.
    """
    ...


def scan_directory_imports(
    arch_dir: Path,
    atom_names: set[str],
    exclude_patterns: list[str] | None = None,
) -> list[ImportHit]:
    """Scan an entire directory tree for atom imports.

    Args:
        arch_dir: Root directory of architectural source files.
        atom_names: Set of known atom function names.
        exclude_patterns: Glob patterns to exclude (e.g., ["**/tests/**"]).

    Returns:
        Aggregated list of ImportHit records.
    """
    ...


def build_atom_registry(
    algorithmic_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Build a registry of atom functions from algorithmic source files.

    Parses all Python files in the algorithmic directory to extract:
    - Function names
    - File locations
    - Signatures (parameter names and types)
    - Return types

    Args:
        algorithmic_dir: Root directory of algorithmic source files.

    Returns:
        Dict mapping atom_name to metadata dict with keys:
        file, line, params, return_type.
    """
    ...
```

**Files to create:**

`tests/spec_manager/analysis/test_import_scanner.py`

```python
"""Tests for the import scanner engine."""
# Tests for:
# - scan_file_imports with simple from-import
# - scan_file_imports with module-level import + attribute access
# - scan_file_imports with no matches returns empty
# - scan_directory_imports aggregates across files
# - build_atom_registry extracts function signatures
# - Handles syntax errors in source files gracefully
```

**Estimated scope:** ~250 lines of production code, ~200 lines of tests.

---

### Plan 3: Projection Type Classifier

Classify each detected import as pass-through, wrap, smear, or introduction based on how the architectural code uses the imported atom.

**Files to create:**

`scripts/spec_manager/spec_manager/analysis/projection_classifier.py`

```python
"""Classify the projection type of each architectural import of an atom."""

from __future__ import annotations

import ast
import logging
from typing import Literal

from spec_manager.analysis.import_scanner import ImportHit
from spec_manager.schemas.lineage import LineageEdge

logger = logging.getLogger(__name__)

ProjectionType = Literal["pass_through", "wrap", "smear", "introduction"]


def classify_import(
    hit: ImportHit,
    arch_source: str,
    all_atom_names: set[str],
) -> LineageEdge:
    """Classify a single import hit into a projection type.

    Classification rules:
    1. pass_through: The atom function is called directly and its result
       returned or assigned without modification.
    2. wrap: The atom function is called but its result is transformed,
       decorated, or augmented before use.
    3. smear: The architectural location calls multiple atom functions
       and combines their results.
    4. introduction: The architectural function does not import any atoms
       (detected separately, not via import hits).

    Args:
        hit: The import hit to classify.
        arch_source: Full source text of the architectural file.
        all_atom_names: Set of all known atom names for smear detection.

    Returns:
        A LineageEdge with the determined transformation type.
    """
    ...


def classify_all_imports(
    hits: list[ImportHit],
    arch_sources: dict[str, str],
    all_atom_names: set[str],
) -> list[LineageEdge]:
    """Classify all import hits into lineage edges.

    Args:
        hits: List of import hits from the scanner.
        arch_sources: Map of file paths to source text.
        all_atom_names: Set of all known atom names.

    Returns:
        List of classified LineageEdge objects.
    """
    ...


def detect_introductions(
    arch_dir_files: list[str],
    lineage_edges: list[LineageEdge],
) -> list[str]:
    """Detect architectural files/functions with no atom imports.

    These are "introduced" algorithms -- architectural code that has
    no counterpart in the algorithmic layer.

    Args:
        arch_dir_files: All architectural file paths.
        lineage_edges: Already-classified lineage edges.

    Returns:
        List of architectural locations that are introductions.
    """
    ...
```

**Files to create:**

`tests/spec_manager/analysis/test_projection_classifier.py`

```python
"""Tests for projection type classification."""
# Tests for:
# - classify_import detects pass_through (direct call, result returned)
# - classify_import detects wrap (call + transform)
# - classify_import detects smear (multiple atom calls in one function)
# - classify_all_imports processes batch correctly
# - detect_introductions finds files with no atom imports
# - Edge cases: lambdas wrapping atoms, atoms used in comprehensions
```

**Estimated scope:** ~200 lines of production code, ~200 lines of tests.

---

### Plan 4: Adjacency Graph Builder

Build co-occurrence and store-touch adjacency edges between atoms, drawing on the section manifest and store definitions.

**Files to create:**

`scripts/spec_manager/spec_manager/analysis/adjacency_builder.py`

```python
"""Build adjacency edges between atoms (co-occurrence + store-touch)."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from spec_manager.schemas.lineage import AtomAdjacency

logger = logging.getLogger(__name__)


def build_co_occurrence_edges(
    atom_to_section: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """Build co-occurrence edges from section colocation.

    Two atoms co-occur if they share the same section_id. This indicates
    they were discussed in the same evidence window and are likely adjacent.

    Args:
        atom_to_section: Mapping of atom_id to {section_id, file_id, sha256}.

    Returns:
        Dict mapping atom_id to list of co-occurring atom_ids.
    """
    ...


def build_store_touch_edges(
    atom_registry: dict[str, dict[str, Any]],
    store_definitions: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Build store-touch edges from shared store access.

    Two atoms touch the same store if both read from or write to
    the same store identifier. This creates a coupling edge even
    if the atoms never directly call each other.

    Args:
        atom_registry: Map of atom_name to metadata (file, params, etc.).
        store_definitions: Map of store_id to list of atom_ids that access it.

    Returns:
        Dict mapping atom_id to list of store-coupled atom_ids.
    """
    ...


def build_adjacency_graph(
    atom_to_section: dict[str, dict[str, str]],
    atom_registry: dict[str, dict[str, Any]],
    store_definitions: dict[str, list[str]] | None = None,
) -> dict[str, AtomAdjacency]:
    """Build complete adjacency graph combining co-occurrence and store-touch.

    Args:
        atom_to_section: Mapping from trace indexes.
        atom_registry: Atom function metadata from the scanner.
        store_definitions: Optional store-to-atoms mapping.

    Returns:
        Dict mapping atom_id to AtomAdjacency with both edge types populated.
    """
    ...
```

**Files to create:**

`tests/spec_manager/analysis/test_adjacency_builder.py`

```python
"""Tests for adjacency graph building."""
# Tests for:
# - build_co_occurrence_edges groups atoms by section
# - build_co_occurrence_edges returns empty for single-atom sections
# - build_store_touch_edges detects shared store access
# - build_adjacency_graph combines both edge types
# - No duplicate edges in adjacency lists
```

**Estimated scope:** ~150 lines of production code, ~120 lines of tests.

---

### Plan 5: Data Flow Summary Extractor

Extract signals-in, signals-out, and stores-touched per atom by analyzing function signatures and bodies.

**Files to create:**

`scripts/spec_manager/spec_manager/analysis/data_flow.py`

```python
"""Extract data flow summaries (signals in/out, stores touched) per atom."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

from spec_manager.schemas.lineage import DataFlowSummary

logger = logging.getLogger(__name__)


def extract_data_flow(
    atom_name: str,
    file_path: Path,
    store_definitions: dict[str, list[str]] | None = None,
) -> DataFlowSummary:
    """Extract data flow summary for a single atom function.

    Analyzes:
    - Function parameters (signals_in)
    - Return type annotations or inferred returns (signals_out)
    - Calls to store-access functions (stores_touched)

    Args:
        atom_name: Name of the atom function.
        file_path: Path to the file containing the function.
        store_definitions: Optional map of store access patterns.

    Returns:
        DataFlowSummary for the atom.
    """
    ...


def extract_all_data_flows(
    atom_registry: dict[str, dict[str, Any]],
    store_definitions: dict[str, list[str]] | None = None,
) -> dict[str, DataFlowSummary]:
    """Extract data flow summaries for all atoms.

    Args:
        atom_registry: Map of atom_name to metadata.
        store_definitions: Optional store access patterns.

    Returns:
        Dict mapping atom_name to DataFlowSummary.
    """
    ...
```

**Files to create:**

`tests/spec_manager/analysis/test_data_flow.py`

```python
"""Tests for data flow summary extraction."""
# Tests for:
# - extract_data_flow captures parameter names from type annotations
# - extract_data_flow captures return type
# - extract_data_flow detects store access calls
# - extract_all_data_flows processes batch
# - Handles functions with no type annotations gracefully
```

**Estimated scope:** ~120 lines of production code, ~100 lines of tests.

---

### Plan 6: Analysis File Generator (Orchestrator)

Orchestrate all components into the analysis file generator that produces the complete analysis artifact.

**Files to create:**

`scripts/spec_manager/spec_manager/analysis/generator.py`

```python
"""Analysis file generator -- orchestrates all analysis components.

This is the main entry point. It composes the import scanner,
projection classifier, adjacency builder, and data flow extractor
into a single computed artifact.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.analysis.adjacency_builder import build_adjacency_graph
from spec_manager.analysis.data_flow import extract_all_data_flows
from spec_manager.analysis.import_scanner import (
    build_atom_registry,
    scan_directory_imports,
)
from spec_manager.analysis.projection_classifier import (
    classify_all_imports,
    detect_introductions,
)
from spec_manager.schemas.lineage import (
    AnalysisFileSchema,
    AtomAnalysisEntry,
    OrphanedArchEntry,
)

logger = logging.getLogger(__name__)


def generate_analysis_file(
    algorithmic_dir: Path,
    architectural_dir: Path,
    atom_to_section: dict[str, dict[str, str]] | None = None,
    store_definitions: dict[str, list[str]] | None = None,
    run_id: str = "",
) -> AnalysisFileSchema:
    """Generate the complete analysis file artifact.

    This is the core function. It:
    1. Builds the atom registry from algorithmic sources
    2. Scans architectural sources for atom imports
    3. Classifies each import as pass-through/wrap/smear
    4. Detects introductions (architectural code with no atom source)
    5. Builds adjacency graph (co-occurrence + store-touch)
    6. Extracts data flow summaries
    7. Flags unimplemented atoms (no architectural imports)
    8. Assembles everything into AnalysisFileSchema

    Args:
        algorithmic_dir: Root of algorithmic layer source files.
        architectural_dir: Root of architectural layer source files.
        atom_to_section: Optional pre-built atom-to-section index.
        store_definitions: Optional store-to-atoms mapping.
        run_id: Run identifier for the artifact.

    Returns:
        Complete AnalysisFileSchema artifact.
    """
    ...


def write_analysis_json(
    analysis: AnalysisFileSchema,
    output_path: Path,
) -> None:
    """Write analysis artifact as JSON.

    Args:
        analysis: The analysis schema to serialize.
        output_path: Destination file path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(analysis.model_dump(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_analysis_json(input_path: Path) -> AnalysisFileSchema:
    """Read and validate an analysis artifact.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated AnalysisFileSchema.
    """
    content = input_path.read_text(encoding="utf-8")
    return AnalysisFileSchema.model_validate(json.loads(content))
```

**Files to create:**

`tests/spec_manager/analysis/test_generator.py`

```python
"""Tests for the analysis file generator orchestrator."""
# Tests for:
# - generate_analysis_file with minimal fixture (one atom, one arch file)
# - Unimplemented atom detection (atom with no imports)
# - Orphaned architecture detection
# - Summary statistics calculation
# - JSON round-trip (write + read)
# - Empty inputs produce valid schema with zero counts
```

**Estimated scope:** ~200 lines of production code, ~200 lines of tests.

---

### Plan 7: Markdown Report Renderer

Render the analysis artifact as a human-readable Markdown report, following the existing report generation patterns in `reports.py`.

**Files to modify:**

`scripts/spec_manager/spec_manager/refinement/workflows/reports.py`

Add a new function:

```python
def generate_analysis_report(manager: WorkspaceManager) -> str:
    """Generate analysis file report from algorithmic/architectural layers.

    Reads the pre-generated analysis JSON artifact and renders it as
    a Markdown report with sections for:
    - Per-atom forward traces with projection types
    - Adjacency graph summary
    - Unimplemented atoms
    - Orphaned architecture
    - Data flow summaries
    - Aggregate statistics

    Args:
        manager: WorkspaceManager providing access to run artifacts.

    Returns:
        Markdown content string. Also writes to reports/analysis.md.
    """
    ...
```

**Files to create:**

`scripts/spec_manager/spec_manager/analysis/report_renderer.py`

```python
"""Render analysis artifacts as Markdown reports."""

from __future__ import annotations

from spec_manager.schemas.lineage import (
    AnalysisFileSchema,
    AtomAnalysisEntry,
    OrphanedArchEntry,
)


def render_analysis_markdown(analysis: AnalysisFileSchema) -> str:
    """Render a complete analysis artifact as Markdown.

    Output structure:
    # Analysis Report
    - run_id, generated_at

    ## Summary
    | Metric | Value |
    | Total atoms | N |
    | Implemented atoms | N |
    | Unimplemented atoms | N |
    | Orphaned architecture | N |
    | Pass-through imports | N |
    | Wrap imports | N |
    | Smear imports | N |
    | Introductions | N |

    ## Per-Atom Analysis
    ### atom_name (atom_file)
    **Forward Traces:**
    | Architectural Location | Projection Type | Confidence |
    **Adjacency:**
    - Co-occurrence: [atom_a, atom_b]
    - Store-touch: [atom_c]
    **Data Flow:**
    - Signals in: [param_a, param_b]
    - Signals out: [return_type]
    - Stores touched: [store_x]

    ## Unimplemented Atoms
    | Atom | File | Reason |

    ## Orphaned Architecture
    | Location | Description | Suggested Action |

    Args:
        analysis: Complete analysis artifact.

    Returns:
        Markdown string.
    """
    ...


def render_summary_table(analysis: AnalysisFileSchema) -> str:
    """Render just the summary statistics table.

    Useful for embedding in other reports (e.g., run audit).

    Args:
        analysis: Analysis artifact.

    Returns:
        Markdown table string.
    """
    ...
```

**Files to create:**

`tests/spec_manager/analysis/test_report_renderer.py`

```python
"""Tests for analysis Markdown report rendering."""
# Tests for:
# - render_analysis_markdown produces valid Markdown
# - Empty analysis renders gracefully (no atoms, no orphans)
# - Per-atom section includes forward traces table
# - Unimplemented atoms section populated correctly
# - Orphaned architecture section populated correctly
# - render_summary_table standalone usage
```

**Estimated scope:** ~200 lines of production code, ~150 lines of tests.

---

### Plan 8: CLI Integration and Workspace Wiring

Wire the analysis generator into the CLI and workspace infrastructure so it can be invoked on demand.

**Files to modify:**

`scripts/spec_manager/spec_manager/cli.py`

Add a new `generate-analysis` subcommand:

```python
def cmd_generate_analysis(args: argparse.Namespace) -> int:
    """Generate the analysis file (computed artifact)."""
    ...
```

Register in the parser:

```python
# generate-analysis
p_gen_analysis = subparsers.add_parser(
    "generate-analysis",
    help="Generate analysis file (algorithmic-to-architectural mapping)",
)
p_gen_analysis.add_argument("spec_folder", help="Path to spec folder")
p_gen_analysis.add_argument(
    "--format",
    choices=["markdown", "json", "both"],
    default="both",
    help="Output format (default: both)",
)
p_gen_analysis.add_argument("--json", action="store_true", help="Print JSON to stdout")
```

Add to the commands dict:

```python
"generate-analysis": cmd_generate_analysis,
```

**Files to modify:**

`scripts/spec_manager/spec_manager/analysis/__init__.py`

Add the new public API exports:

```python
from spec_manager.analysis.generator import (
    generate_analysis_file,
    read_analysis_json,
    write_analysis_json,
)
```

**Files to modify:**

`scripts/spec_manager/spec_manager/refinement/workspace/manager.py`

Add an `analysis_dir` property to `RunFolderStructure`:

```python
@property
def analysis_dir(self) -> Path:
    """Path to the analysis artifacts directory."""
    return self.root / "analysis"
```

**Files to modify:**

`scripts/spec_manager/spec_manager/refinement/workflows/reports.py`

Import and call the analysis report generator in `generate_run_audit()` to include a summary section, and add `generate_analysis_report` to `__all__`.

**Estimated scope:** ~100 lines of production code across 4 files, ~50 lines of tests for CLI integration.

## Execution Instructions

Execute plans in order (1 through 8). Each plan is independently testable:

1. **Plan 1** (Schema) -- no dependencies. Merge when tests pass.
2. **Plan 2** (Import Scanner) -- depends on Plan 1 for `LineageEdge` import. Merge after Plan 1.
3. **Plan 3** (Classifier) -- depends on Plan 2 for `ImportHit`. Merge after Plan 2.
4. **Plan 4** (Adjacency) -- depends on Plan 1 for `AtomAdjacency`. Can parallelize with Plans 2-3.
5. **Plan 5** (Data Flow) -- depends on Plan 1 for `DataFlowSummary`. Can parallelize with Plans 2-4.
6. **Plan 6** (Generator) -- depends on Plans 2-5. Merge after all predecessors.
7. **Plan 7** (Report Renderer) -- depends on Plan 1 for schemas and Plan 6 for generator. Merge after Plan 6.
8. **Plan 8** (CLI + Workspace) -- depends on Plans 6-7. Merge last.

Parallelization is possible: Plans 4 and 5 can be developed concurrently with Plans 2-3 since they share only the schema dependency (Plan 1).

## Success Criteria

1. **Schema validation**: `AnalysisFileSchema` validates with Pydantic, including nested `LineageEdge`, `AtomAdjacency`, `DataFlowSummary`, and `OrphanedArchEntry` models.
2. **Import detection**: Given a fixture with one algorithmic file defining `validate_payment` and one architectural file importing it, the scanner returns exactly one `ImportHit`.
3. **Projection classification**: Given fixtures for each projection type (pass-through, wrap, smear), the classifier assigns the correct transformation label.
4. **Adjacency edges**: Two atoms in the same section produce a co-occurrence edge. Two atoms touching the same store produce a store-touch edge.
5. **Unimplemented detection**: An atom with zero forward traces is flagged `is_unimplemented=True`.
6. **Orphaned detection**: An architectural function with no atom imports appears in `orphaned_architecture`.
7. **Markdown output**: The rendered report contains all expected sections (Summary, Per-Atom Analysis, Unimplemented Atoms, Orphaned Architecture).
8. **JSON round-trip**: `write_analysis_json` followed by `read_analysis_json` produces an identical `AnalysisFileSchema`.
9. **CLI invocation**: `uv run spec-manager generate-analysis <spec_folder>` produces both `analysis/analysis.json` and `reports/analysis.md`.
10. **No regressions**: All existing tests pass (`pytest -p no:randomly`).
11. **Idempotency**: Running the generator twice with unchanged inputs produces identical output.

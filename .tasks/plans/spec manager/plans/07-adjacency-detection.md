# Implementation Plan

## Overview

Build an adjacency detection system that identifies integrated and adjacent algorithms by constructing and unioning four graph types -- call graph, event graph, store touch graph, and entity co-occurrence graph -- then detecting disconnected components to reveal missed dependencies or confirm true isolation.

## Current State (Problems)

The existing `analysis/` module (`operations.py`, `resolver.py`) performs library-level restructuring analysis (divergence, convergence, reference patterns) but operates exclusively on spec annotations and library registry metadata. It has no understanding of:

1. **Function-level call relationships** -- which algorithms invoke which other algorithms
2. **Event-mediated coupling** -- publish/subscribe patterns that connect otherwise disconnected call graphs
3. **Shared store access** -- two algorithms that read/write the same database table or queue are coupled even without direct calls
4. **Spec-section co-occurrence** -- algorithms discussed together in spec text are likely adjacent

The design document (algorithmic-projection-patch.md, Sections 7 and 10) calls for a union of call graph + event graph + store touch graph to reveal the "complete dependency picture." ALGORITHM.md Phase 2 defines the coupling signals (entity co-occurrence 2.1, reference edges 2.2, store touch edges 2.3). Neither is currently implemented.

## Target State

A new `analysis/adjacency/` subpackage that:

- Extracts four graph signal types from algorithmic code and spec content
- Merges them into a single weighted adjacency graph
- Detects connected components and reports disconnected subgraphs
- Classifies disconnected subgraphs as "truly isolated" vs "potentially missed adjacency"
- Integrates with the existing `analysis/` module and can be invoked from CLI
- Produces a serializable adjacency report (JSON + markdown)

## Additional Info

### Graph Library Decision

Use **no external graph library**. The project currently has only `pyyaml` as a dependency (`pyproject.toml`). The graph operations needed (union, connected components, edge weighting) are straightforward adjacency-list algorithms that do not justify adding networkx (~30MB) or igraph. A lightweight custom graph class with ~100 lines covers all needs:

- `add_node(id)`, `add_edge(u, v, weight, signal_type)`
- `neighbors(u)` -> list of (v, weight, signal_type)
- `connected_components()` -> list of sets
- `subgraph(nodes)` -> new Graph
- `union(other_graph)` -> new Graph

If the graph grows beyond ~10k nodes in practice, networkx can be added later as an optional dependency.

### Edge Weighting Strategy

Per ALGORITHM.md Phase 2.4, edge weight = sum of signal weights. The default weights are:

| Signal Type | Default Weight | Rationale |
|---|---|---|
| `call` | 1.0 | Direct function invocation is the strongest coupling signal |
| `reference` | 0.7 | Explicit spec references (`@[+ID]`, `@[=ID]`) are intentional links |
| `store_touch` | 0.5 | Shared store implies data coupling even without direct calls |
| `co_occurrence` | 0.3 | Same-section discussion is a weak but useful proximity signal |
| `event` | 0.8 | Event publish/subscribe is a strong architectural coupling |

Weights are configurable. When multiple signals exist between the same pair, weights are summed (multi-edge collapse with additive weighting).

### Store Touch Detection Strategy

Stores are detected via naming conventions and AST patterns in algorithmic code, following ALGORITHM.md Phase 2.6 store classification:

1. **AST-based**: Function parameters with type hints containing `Store`, `Repository`, `Queue`, `DB`, `Session`, `Connection`
2. **Naming convention**: Functions containing `read_`, `write_`, `load_`, `save_`, `persist_`, `fetch_`, `query_`, `enqueue_`, `dequeue_`, `publish_`, `subscribe_`
3. **Spec annotation**: `(@pin path:symbol)` annotations that reference store-related files
4. **Store type classification**: Type A (persisted), Type B (long-lived ephemeral), Type C (pure ephemeral) per ALGORITHM.md 2.6

### Event Detection Strategy

Events are detected via:

1. **AST patterns**: Calls to methods named `publish`, `emit`, `dispatch`, `subscribe`, `on_event`, `handle`, `listen`
2. **String literal analysis**: First argument to publish/subscribe calls often contains the event topic string
3. **Decorator patterns**: `@event_handler("topic")`, `@subscribe("topic")`, `@on("topic")`
4. **Class inheritance**: Classes inheriting from `EventHandler`, `Subscriber`, `Handler` base classes

### Disconnected Component Classification

A disconnected subgraph in the union graph is classified as:

- **Truly isolated**: The subgraph has no store touches in common with other subgraphs AND no co-occurrence edges to other subgraphs. Confidence: high.
- **Potentially missed adjacency**: The subgraph is disconnected in the call+event graph but has store touch or co-occurrence edges to another subgraph. This suggests a missing explicit connection. Confidence: medium.
- **Suspiciously isolated**: A single-node subgraph (one algorithm with no connections at all). Either it is genuinely standalone or the extraction missed its connections. Confidence: low.

## Plans

### Plan 1: Core Graph Data Structure

Create the lightweight graph implementation that all extractors will populate.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/__init__.py`
- `scripts/spec_manager/spec_manager/analysis/adjacency/graph.py`

**Data structures:**

```python
# graph.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalType(Enum):
    """Types of adjacency signals between nodes."""
    CALL = "call"
    REFERENCE = "reference"
    STORE_TOUCH = "store_touch"
    CO_OCCURRENCE = "co_occurrence"
    EVENT = "event"


@dataclass(frozen=True)
class EdgeSignal:
    """A single signal contributing to an edge."""
    signal_type: SignalType
    weight: float
    details: dict[str, Any] = field(default_factory=dict)
    # details may include: store_name, event_topic, section_id, call_site, etc.


@dataclass
class Edge:
    """A weighted edge between two nodes, potentially with multiple signals."""
    source: str
    target: str
    signals: list[EdgeSignal] = field(default_factory=list)

    @property
    def total_weight(self) -> float:
        return sum(s.weight for s in self.signals)

    def add_signal(self, signal: EdgeSignal) -> None:
        self.signals.append(signal)

    def to_dict(self) -> dict[str, Any]:
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Edge:
        ...


@dataclass
class NodeInfo:
    """Metadata about a graph node."""
    node_id: str
    node_type: str  # "algorithm", "function", "handler", "store", etc.
    file_path: str | None = None
    line_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeInfo:
        ...


class AdjacencyGraph:
    """Lightweight weighted directed graph with signal-typed edges.

    Nodes are string IDs (algorithm names, function names, etc.).
    Edges carry one or more EdgeSignal instances.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, NodeInfo] = {}
        self._adj: dict[str, dict[str, Edge]] = {}  # source -> {target -> Edge}

    def add_node(self, node_id: str, info: NodeInfo | None = None) -> None:
        ...

    def add_edge(self, source: str, target: str, signal: EdgeSignal) -> None:
        """Add or augment an edge. If edge exists, appends signal."""
        ...

    def get_edge(self, source: str, target: str) -> Edge | None:
        ...

    def neighbors(self, node_id: str) -> list[tuple[str, Edge]]:
        """Outgoing neighbors with their edges."""
        ...

    def all_neighbors(self, node_id: str) -> list[tuple[str, Edge]]:
        """Both incoming and outgoing neighbors (undirected view)."""
        ...

    def nodes(self) -> list[str]:
        ...

    def edges(self) -> list[Edge]:
        ...

    def connected_components(self) -> list[set[str]]:
        """Undirected connected components via BFS."""
        ...

    def subgraph(self, node_ids: set[str]) -> AdjacencyGraph:
        """Extract induced subgraph."""
        ...

    def union(self, other: AdjacencyGraph) -> AdjacencyGraph:
        """Merge two graphs. Overlapping edges get signals combined."""
        ...

    def filter_by_signal_type(self, signal_types: set[SignalType]) -> AdjacencyGraph:
        """Return subgraph containing only edges with specified signal types."""
        ...

    def to_dict(self) -> dict[str, Any]:
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdjacencyGraph:
        ...
```

**Tests to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/__init__.py`
- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py`

Test cases:
- Add nodes and edges, verify adjacency
- Multiple signals on same edge (weight summing)
- Connected components on known graphs (single component, two components, isolated node)
- Subgraph extraction preserves correct edges
- Graph union merges overlapping edges correctly
- Filter by signal type
- Serialization round-trip (to_dict / from_dict)

---

### Plan 2: Call Graph Extractor

AST-based analysis of function calls in Python algorithmic code.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/extractors/__init__.py`
- `scripts/spec_manager/spec_manager/analysis/adjacency/extractors/call_graph.py`

**Function signatures:**

```python
# call_graph.py

from __future__ import annotations
import ast
from pathlib import Path
from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


@dataclass
class CallSite:
    """A detected function call site."""
    caller: str          # fully qualified caller name (module.class.method or module.function)
    callee: str          # name of the called function
    file_path: str
    line_number: int
    is_method_call: bool # obj.method() vs function()


def extract_call_graph(
    source_paths: list[Path],
    root_dir: Path | None = None,
) -> AdjacencyGraph:
    """Build a call graph from Python source files.

    Walks AST of each file, identifies function/method definitions,
    and records call relationships between them.

    Args:
        source_paths: Python files to analyze
        root_dir: Project root for computing module-qualified names

    Returns:
        AdjacencyGraph with SignalType.CALL edges
    """
    ...


def _extract_functions(tree: ast.Module, file_path: Path, root_dir: Path | None) -> list[NodeInfo]:
    """Extract all function/method definitions from an AST."""
    ...


def _extract_calls(tree: ast.Module, file_path: Path, root_dir: Path | None) -> list[CallSite]:
    """Extract all function call sites from an AST."""
    ...


def _resolve_callee(call_site: CallSite, known_functions: set[str]) -> str | None:
    """Attempt to resolve a callee name to a known function.

    Handles simple cases (direct calls) and common patterns
    (self.method, module.function). Does NOT resolve dynamic dispatch.
    """
    ...
```

**Key implementation details:**

- Use `ast.walk()` to find `ast.FunctionDef` and `ast.AsyncFunctionDef` for node extraction
- Use `ast.Call` nodes to find call sites
- For `ast.Attribute` calls (`self.validate()`, `bus.publish()`), record `obj.method` form
- Name resolution is best-effort: match unqualified callee names against known function names in the same file set
- Functions in `__init__.py`, test files, and non-algorithmic infrastructure are excluded by default

**Tests:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_call_graph.py`

Test cases:
- Simple function-to-function calls
- Method calls on self
- Calls across files (module.function pattern)
- Unresolvable calls (external libraries) are excluded
- Async function calls
- Nested function definitions

---

### Plan 3: Event Graph Extractor

Detect publish/subscribe patterns that create implicit coupling.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/extractors/event_graph.py`

**Function signatures:**

```python
# event_graph.py

from __future__ import annotations
import ast
from dataclasses import dataclass
from pathlib import Path
from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


@dataclass
class EventEndpoint:
    """A detected event publish or subscribe point."""
    function_name: str   # function/method containing the event interaction
    event_topic: str     # topic string if detectable, else "unknown"
    direction: str       # "publish" or "subscribe"
    file_path: str
    line_number: int


# Configurable patterns for event detection
DEFAULT_PUBLISH_PATTERNS: list[str] = [
    "publish", "emit", "dispatch", "send_event", "fire",
    "bus.publish", "bus.emit", "event_bus.publish",
]

DEFAULT_SUBSCRIBE_PATTERNS: list[str] = [
    "subscribe", "on_event", "handle", "listen",
    "bus.subscribe", "bus.on", "event_bus.subscribe",
]

DEFAULT_DECORATOR_PATTERNS: list[str] = [
    "event_handler", "subscribe", "on", "handles",
]


def extract_event_graph(
    source_paths: list[Path],
    root_dir: Path | None = None,
    publish_patterns: list[str] | None = None,
    subscribe_patterns: list[str] | None = None,
    decorator_patterns: list[str] | None = None,
) -> AdjacencyGraph:
    """Build an event graph from Python source files.

    Detects publish/subscribe patterns and creates edges between
    publishers and subscribers of the same topic.

    Args:
        source_paths: Python files to analyze
        root_dir: Project root for computing module-qualified names
        publish_patterns: Override default publish method name patterns
        subscribe_patterns: Override default subscribe method name patterns
        decorator_patterns: Override default decorator patterns

    Returns:
        AdjacencyGraph with SignalType.EVENT edges
    """
    ...


def _detect_event_endpoints(
    tree: ast.Module,
    file_path: Path,
    root_dir: Path | None,
    publish_patterns: list[str],
    subscribe_patterns: list[str],
    decorator_patterns: list[str],
) -> list[EventEndpoint]:
    """Detect publish/subscribe endpoints in an AST."""
    ...


def _extract_topic_from_call(call_node: ast.Call) -> str | None:
    """Extract topic string from the first argument of a publish/subscribe call.

    Handles string literals and simple string constants.
    Returns None if topic cannot be statically determined.
    """
    ...


def _match_publishers_to_subscribers(
    endpoints: list[EventEndpoint],
) -> list[tuple[EventEndpoint, EventEndpoint]]:
    """Match publisher endpoints to subscriber endpoints by topic.

    Returns pairs of (publisher, subscriber) that share the same topic.
    Endpoints with "unknown" topic are matched to ALL endpoints of the
    opposite direction as low-confidence edges.
    """
    ...
```

**Tests:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py`

Test cases:
- Detect `bus.publish("order.created")` and `@subscribe("order.created")` as connected
- Multiple subscribers to same topic
- Unknown topics produce low-confidence edges
- Decorator-based subscription detection
- No false positives on unrelated `publish` method names (e.g., `book.publish()`)

---

### Plan 4: Store Touch Graph Extractor

Identify which functions read/write which stores.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/extractors/store_graph.py`

**Function signatures:**

```python
# store_graph.py

from __future__ import annotations
import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


class StoreType(Enum):
    """Store lifecycle classification per ALGORITHM.md 2.6."""
    PERSISTED = "type_a"       # DB, files -- survives restart
    LONG_LIVED = "type_b"      # In-memory across steps -- HIGH RISK
    EPHEMERAL = "type_c"       # Local/temporary within single step


class AccessMode(Enum):
    """How a function accesses a store."""
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


@dataclass
class StoreTouch:
    """A detected store access by a function."""
    function_name: str
    store_name: str
    store_type: StoreType
    access_mode: AccessMode
    file_path: str
    line_number: int
    detection_method: str  # "type_hint", "naming_convention", "pin_annotation"


# Naming convention patterns for store access detection
READ_PATTERNS: list[str] = [
    "read_", "load_", "fetch_", "query_", "get_from_",
    "find_", "lookup_", "retrieve_", "dequeue_",
]

WRITE_PATTERNS: list[str] = [
    "write_", "save_", "persist_", "store_", "put_",
    "insert_", "update_", "delete_", "enqueue_", "push_",
]

STORE_TYPE_HINTS: list[str] = [
    "Store", "Repository", "Queue", "DB", "Session",
    "Connection", "Cache", "Registry", "Journal",
]


def extract_store_graph(
    source_paths: list[Path],
    root_dir: Path | None = None,
    pin_annotations: dict[str, str] | None = None,
) -> AdjacencyGraph:
    """Build a store touch graph from Python source files.

    Two functions that touch the same store get an edge between them.
    Store nodes are included in the graph as intermediate nodes.

    Args:
        source_paths: Python files to analyze
        root_dir: Project root for module-qualified names
        pin_annotations: Optional map of function_name -> store file path
            from (@pin path:symbol) annotations in spec content

    Returns:
        AdjacencyGraph with SignalType.STORE_TOUCH edges.
        Edges connect function pairs that share a store.
        Edge details include store_name, store_type, access_modes.
    """
    ...


def _detect_store_touches(
    tree: ast.Module,
    file_path: Path,
    root_dir: Path | None,
) -> list[StoreTouch]:
    """Detect store accesses in an AST via type hints and naming conventions."""
    ...


def _classify_store_type(store_name: str, context_hints: dict[str, Any] | None = None) -> StoreType:
    """Classify a store into Type A/B/C based on naming and context.

    Heuristic:
    - Names containing 'db', 'sql', 'file', 'disk', 'persist' -> PERSISTED
    - Names containing 'cache', 'session', 'state' -> LONG_LIVED
    - Names containing 'temp', 'local', 'buffer' -> EPHEMERAL
    - Default: PERSISTED (conservative -- assume worst case)
    """
    ...


def _build_store_adjacency(
    touches: list[StoreTouch],
) -> AdjacencyGraph:
    """Convert store touches into function-to-function edges.

    For each store S:
      For each pair (f1, f2) that both touch S:
        Add edge f1 <-> f2 with SignalType.STORE_TOUCH
        Edge details include store_name, store_type, access modes
    """
    ...
```

**Tests:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_store_graph.py`

Test cases:
- Two functions calling `read_orders()` and `write_orders()` share a store edge
- Type hint detection: `def process(db: DatabaseStore)` detects store access
- Store type classification (db -> persisted, cache -> long-lived, temp -> ephemeral)
- No false edges between functions touching different stores
- Pin annotation integration (spec `(@pin orders.py:OrderStore)` adds store touch)

---

### Plan 5: Entity Co-occurrence Extractor

Extract adjacency signals from spec content -- algorithms discussed in the same section.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/extractors/cooccurrence.py`

**Function signatures:**

```python
# cooccurrence.py

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


@dataclass
class CoOccurrence:
    """A detected co-occurrence of two entities in the same context."""
    entity_a: str
    entity_b: str
    section_id: str        # which spec section they co-occur in
    source_file: str
    proximity: float       # 0.0-1.0, closer = higher (same paragraph > same section)


def extract_cooccurrence_graph(
    spec_paths: list[Path],
    window_mode: str = "section",
) -> AdjacencyGraph:
    """Build co-occurrence graph from spec markdown files.

    Entities (algorithms, data structures, components) that appear in the
    same section/window form weighted edges.

    Uses the existing SectionExtractor and AnnotationParser from core/
    to identify declared entities and their references.

    Args:
        spec_paths: Markdown spec files to analyze
        window_mode: "section" (default) or "paragraph" granularity

    Returns:
        AdjacencyGraph with SignalType.CO_OCCURRENCE edges
    """
    ...


def _extract_entity_mentions(
    content: str,
    source_file: str,
) -> dict[str, list[str]]:
    """Extract entity IDs mentioned in each section.

    Uses AnnotationParser to find declarations ([=ID]) and
    references (@[+ID], @[=ID]) within each section boundary
    identified by SectionExtractor.

    Returns:
        Dict mapping section_id -> list of entity IDs mentioned
    """
    ...


def _build_cooccurrence_edges(
    section_entities: dict[str, list[str]],
    source_file: str,
) -> list[CoOccurrence]:
    """Build pairwise co-occurrences from section entity lists.

    For each section with entities [A, B, C]:
      Emit edges: (A,B), (A,C), (B,C)
      Proximity = 1.0 / len(entities) to down-weight sections with many entities
    """
    ...
```

**Integration with existing code:**

This extractor reuses:
- `spec_manager.core.sections.SectionExtractor` for section boundary detection
- `spec_manager.core.annotations.AnnotationParser` for entity mention extraction
- `spec_manager.core.ids.IdValidator` for validating extracted IDs

**Tests:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py`

Test cases:
- Two algorithms declared in same section produce co-occurrence edge
- References (`@[+Algorithm 1]`) count as mentions
- Sections with many entities have lower per-edge proximity weight
- No self-edges (entity does not co-occur with itself)
- Multi-file co-occurrence (same entity in different files, different sections)

---

### Plan 6: Graph Union and Disconnected Component Detection

Merge all four signal graphs and analyze connectivity.

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/detector.py`

**Function signatures:**

```python
# detector.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .graph import AdjacencyGraph, SignalType


class IsolationClassification(Enum):
    """How a disconnected component is classified."""
    TRULY_ISOLATED = "truly_isolated"
    POTENTIALLY_MISSED = "potentially_missed"
    SUSPICIOUSLY_ISOLATED = "suspiciously_isolated"


@dataclass
class ComponentReport:
    """Report for a single connected component."""
    component_id: int
    nodes: set[str]
    size: int
    signal_types_present: set[SignalType]
    total_internal_weight: float
    classification: IsolationClassification | None = None  # None for the main component
    classification_reason: str = ""
    bridge_candidates: list[dict[str, Any]] = field(default_factory=list)
    # bridge_candidates: edges in partial graphs that connect this to other components

    def to_dict(self) -> dict[str, Any]:
        ...


@dataclass
class AdjacencyReport:
    """Full adjacency analysis report."""
    total_nodes: int
    total_edges: int
    num_components: int
    components: list[ComponentReport]
    signal_type_counts: dict[str, int]   # edges per signal type
    signal_type_weights: dict[str, float]  # total weight per signal type
    disconnected_warnings: list[str]      # human-readable warnings

    def to_dict(self) -> dict[str, Any]:
        ...

    def to_markdown(self) -> str:
        """Render as markdown report."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdjacencyReport:
        ...


DEFAULT_SIGNAL_WEIGHTS: dict[SignalType, float] = {
    SignalType.CALL: 1.0,
    SignalType.REFERENCE: 0.7,
    SignalType.STORE_TOUCH: 0.5,
    SignalType.CO_OCCURRENCE: 0.3,
    SignalType.EVENT: 0.8,
}


def build_unified_graph(
    call_graph: AdjacencyGraph | None = None,
    event_graph: AdjacencyGraph | None = None,
    store_graph: AdjacencyGraph | None = None,
    cooccurrence_graph: AdjacencyGraph | None = None,
    weight_overrides: dict[SignalType, float] | None = None,
) -> AdjacencyGraph:
    """Merge all signal graphs into a unified adjacency graph.

    Applies weight scaling per signal type (overridable).
    Overlapping edges between same node pairs have their signals combined.

    Args:
        call_graph: Call graph (SignalType.CALL edges)
        event_graph: Event graph (SignalType.EVENT edges)
        store_graph: Store touch graph (SignalType.STORE_TOUCH edges)
        cooccurrence_graph: Co-occurrence graph (SignalType.CO_OCCURRENCE edges)
        weight_overrides: Optional weight multipliers per signal type

    Returns:
        Unified AdjacencyGraph containing all signals
    """
    ...


def detect_disconnected_components(
    unified_graph: AdjacencyGraph,
    partial_graphs: dict[str, AdjacencyGraph] | None = None,
) -> AdjacencyReport:
    """Analyze the unified graph for disconnected components.

    Classifies each component using the three-tier system:
    - truly_isolated: no store or co-occurrence links to other components
    - potentially_missed: disconnected in call+event but linked via store/co-occurrence
    - suspiciously_isolated: single-node component

    Args:
        unified_graph: The merged graph from build_unified_graph()
        partial_graphs: Optional individual signal graphs for cross-checking.
            Keys should be signal type names ("call", "event", "store", "cooccurrence").

    Returns:
        AdjacencyReport with component analysis
    """
    ...


def _classify_component(
    component: set[str],
    all_components: list[set[str]],
    unified_graph: AdjacencyGraph,
    partial_graphs: dict[str, AdjacencyGraph] | None,
) -> tuple[IsolationClassification, str, list[dict[str, Any]]]:
    """Classify a disconnected component.

    Returns (classification, reason, bridge_candidates).
    """
    ...
```

**Tests:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_detector.py`

Test cases:
- Fully connected graph produces one component with no warnings
- Two disconnected subgraphs with no shared stores -> truly_isolated
- Two disconnected subgraphs sharing a store -> potentially_missed with bridge candidates
- Single isolated node -> suspiciously_isolated
- Weight override changes total_weight correctly
- Empty graphs produce empty report
- Markdown report generation

---

### Plan 7: Integration with Existing Analysis Module and CLI

Wire the adjacency system into the existing `analysis/` module and expose it through CLI.

**Files to modify:**

- `scripts/spec_manager/spec_manager/analysis/__init__.py` -- add adjacency exports
- `scripts/spec_manager/spec_manager/analysis/operations.py` -- add `run_adjacency_analysis()` to `AnalysisResult`
- `scripts/spec_manager/spec_manager/cli.py` -- add `adjacency` subcommand

**Files to create:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/runner.py` -- orchestrates the full pipeline

**Runner function signatures:**

```python
# runner.py

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .detector import AdjacencyReport, build_unified_graph, detect_disconnected_components
from .graph import AdjacencyGraph


@dataclass
class AdjacencyAnalysisConfig:
    """Configuration for adjacency analysis."""
    source_dirs: list[Path]           # Python source directories to analyze
    spec_dirs: list[Path]             # Spec markdown directories
    include_call_graph: bool = True
    include_event_graph: bool = True
    include_store_graph: bool = True
    include_cooccurrence: bool = True
    weight_overrides: dict[str, float] | None = None
    output_format: str = "json"       # "json" or "markdown"
    output_path: Path | None = None


def run_adjacency_analysis(config: AdjacencyAnalysisConfig) -> AdjacencyReport:
    """Run the full adjacency detection pipeline.

    1. Collect source files from source_dirs
    2. Collect spec files from spec_dirs
    3. Run enabled extractors
    4. Build unified graph
    5. Detect disconnected components
    6. Produce report

    Args:
        config: Analysis configuration

    Returns:
        AdjacencyReport with full analysis
    """
    ...


def save_report(report: AdjacencyReport, config: AdjacencyAnalysisConfig) -> Path:
    """Save report to configured output path.

    Returns path where report was saved.
    """
    ...
```

**Modifications to existing files:**

`analysis/operations.py` -- extend `AnalysisResult`:
```python
@dataclass
class AnalysisResult:
    # ... existing fields ...
    adjacency_report: AdjacencyReport | None = None
```

`analysis/__init__.py` -- add exports:
```python
from spec_manager.analysis.adjacency.detector import AdjacencyReport
from spec_manager.analysis.adjacency.runner import run_adjacency_analysis
```

`cli.py` -- add subcommand:
```
spec-manager adjacency [--source-dir DIR] [--spec-dir DIR] [--format json|markdown] [--output PATH]
    [--no-call-graph] [--no-event-graph] [--no-store-graph] [--no-cooccurrence]
```

**Tests:**

- `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_runner.py`

Test cases:
- End-to-end: small fixture directory with known adjacency -> correct report
- Config with disabled extractors skips them
- JSON and markdown output formats both produce valid output
- Integration: report is attached to AnalysisResult correctly

## Execution Instructions

Implement plans sequentially (Plan 1 through Plan 7). Each plan depends on the previous:

1. **Plan 1** (graph.py) has no dependencies -- implement first
2. **Plans 2-5** (extractors) depend on Plan 1 but are independent of each other -- can be implemented in any order or in parallel
3. **Plan 6** (detector.py) depends on Plan 1 and conceptually on Plans 2-5 (but only needs the graph interface, not the extractors themselves)
4. **Plan 7** (integration) depends on all previous plans

For each plan:
1. Create the file(s) with the data structures and function signatures
2. Implement the functions
3. Write and run tests: `uv run python -m pytest scripts/spec_manager/spec_manager/analysis/adjacency/tests/ -v`
4. Verify no regressions: `uv run python -m pytest scripts/spec_manager/ -p no:randomly -x`

## Success Criteria

1. **Graph operations**: `AdjacencyGraph` supports add/query/union/components/filter with full serialization round-trip. All test cases in `test_graph.py` pass.

2. **Call graph extraction**: Given Python source files with known call relationships, `extract_call_graph()` produces a graph containing all direct function-to-function calls. Verified by fixture files with at least 5 functions and 8 call edges.

3. **Event graph extraction**: Given Python source files with `publish()`/`subscribe()` patterns, `extract_event_graph()` connects publishers to subscribers by topic. Verified by fixture with at least 3 event topics.

4. **Store touch graph extraction**: Given Python source files with store access patterns, `extract_store_graph()` connects functions sharing the same store. Verified by fixture with at least 2 stores and 4 functions.

5. **Co-occurrence extraction**: Given spec markdown files with entity declarations and references, `extract_cooccurrence_graph()` connects entities appearing in the same section. Verified using existing spec_manager core extractors (SectionExtractor, AnnotationParser).

6. **Unified graph and components**: `build_unified_graph()` merges all four signal types. `detect_disconnected_components()` correctly classifies components as truly_isolated, potentially_missed, or suspiciously_isolated. Verified by a test with a known graph topology containing each classification.

7. **Integration**: `run_adjacency_analysis()` completes end-to-end and produces a valid `AdjacencyReport`. The CLI subcommand `spec-manager adjacency` runs without error.

8. **No new dependencies**: The implementation uses only the Python standard library (ast, collections, dataclasses, enum, json, pathlib) plus existing spec_manager.core modules. No new entries in `pyproject.toml` dependencies.

9. **All existing tests pass**: `uv run python -m pytest scripts/spec_manager/ -p no:randomly` shows no regressions.

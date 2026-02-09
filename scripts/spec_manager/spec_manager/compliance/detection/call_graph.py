"""Call graph builder and adjacency detector for executable gap detection.

Builds a static function-level call graph from language-agnostic source
analysis. Detects disconnected subgraphs that may indicate missed adjacencies
per design doc Section 7.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.gap import GapEvidence


@dataclass
class FunctionNode:
    """A function in the call graph."""

    qualified_name: str
    file_path: str
    line: int
    is_stub: bool


@dataclass
class CallEdge:
    """A call relationship between two functions."""

    caller: str
    callee: str
    call_site_line: int
    file_path: str


@dataclass
class CallGraph:
    """Function-level call graph with adjacency detection."""

    nodes: dict[str, FunctionNode] = field(default_factory=dict)
    edges: dict[str, set[str]] = field(default_factory=dict)
    reverse_edges: dict[str, set[str]] = field(default_factory=dict)

    def add_node(self, node: FunctionNode) -> None:
        """Add a function node to the graph."""
        self.nodes[node.qualified_name] = node
        self.edges.setdefault(node.qualified_name, set())
        self.reverse_edges.setdefault(node.qualified_name, set())

    def add_edge(self, caller: str, callee: str) -> None:
        """Add a call edge between two functions."""
        self.edges.setdefault(caller, set()).add(callee)
        self.reverse_edges.setdefault(callee, set()).add(caller)

    def get_connected_components(self) -> list[set[str]]:
        """Find connected components via BFS on undirected view."""
        visited: set[str] = set()
        components: list[set[str]] = []

        all_nodes = set(self.nodes.keys())

        for node in all_nodes:
            if node in visited:
                continue

            component: set[str] = set()
            queue: deque[str] = deque([node])

            while queue:
                current = queue.popleft()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)

                # Forward edges
                for neighbor in self.edges.get(current, set()):
                    if neighbor in all_nodes and neighbor not in visited:
                        queue.append(neighbor)

                # Reverse edges (undirected view)
                for neighbor in self.reverse_edges.get(current, set()):
                    if neighbor in all_nodes and neighbor not in visited:
                        queue.append(neighbor)

            if component:
                components.append(component)

        return components

    def get_disconnected_subgraphs(self) -> list[set[str]]:
        """Return components that have no edges to other components.

        These are potential missed adjacencies per design doc Section 7.
        A component is "disconnected" if none of its members call or are
        called by functions in other components.
        """
        components = self.get_connected_components()
        # All components with more than one member are inherently connected
        # internally, but disconnected from other components by definition
        # of connected components. So all components are disconnected subgraphs.
        return components

    def get_callers(self, function_name: str) -> set[str]:
        """Get all functions that call the given function."""
        return set(self.reverse_edges.get(function_name, set()))

    def get_callees(self, function_name: str) -> set[str]:
        """Get all functions called by the given function."""
        return set(self.edges.get(function_name, set()))

    def get_reachable(self, function_name: str) -> set[str]:
        """Get all functions reachable from the given function (transitive)."""
        visited: set[str] = set()
        queue: deque[str] = deque([function_name])

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for callee in self.edges.get(current, set()):
                if callee not in visited:
                    queue.append(callee)

        visited.discard(function_name)
        return visited


def _extract_functions_and_calls(
    source: str,
    filepath: Path,
    module_prefix: str,
) -> tuple[list[FunctionNode], list[CallEdge]]:
    """Extract function definitions and call relationships from source code.

    Uses ``analyze_source`` for function discovery (language-agnostic) and
    regex for approximate call detection within function bodies.

    Args:
        source: Source code text.
        filepath: Path to the source file.
        module_prefix: Dotted module prefix for qualified names.

    Returns:
        Tuple of (function_nodes, call_edges).
    """
    analysis = analyze_source(source, filepath=str(filepath))

    if not analysis.functions:
        return [], []

    nodes: list[FunctionNode] = []
    edges: list[CallEdge] = []
    lines = source.splitlines()

    for func_info in analysis.functions:
        qualified = f"{module_prefix}{func_info.qualified_name}"
        fn_node = FunctionNode(
            qualified_name=qualified,
            file_path=str(filepath),
            line=func_info.start_line,
            is_stub=func_info.is_stub,
        )
        nodes.append(fn_node)

        # Extract the function body text from the source lines
        body_start = func_info.body_start_line
        body_end = func_info.end_line
        if body_start > 0 and body_end > 0 and body_end <= len(lines):
            body_lines = lines[body_start - 1 : body_end]
            body_text = "\n".join(body_lines)
        elif func_info.start_line > 0 and func_info.end_line > 0:
            body_lines = lines[func_info.start_line - 1 : func_info.end_line]
            body_text = "\n".join(body_lines)
        else:
            body_text = ""

        # Use regex to find call-like patterns in body text
        raw_calls = re.findall(r"\b(\w+)\s*\(", body_text)
        # Deduplicate while preserving first-seen order
        seen: set[str] = set()
        for callee_name in raw_calls:
            if callee_name not in seen:
                seen.add(callee_name)
                edges.append(
                    CallEdge(
                        caller=qualified,
                        callee=callee_name,
                        call_site_line=func_info.body_start_line,
                        file_path=str(filepath),
                    )
                )

    return nodes, edges


def build_call_graph(
    filepaths: list[Path],
    project_root: Path | None = None,
) -> CallGraph:
    """Build a function-level call graph from source files.

    For each file:
    1. Use ``analyze_source`` to find all function/method definitions
    2. Use regex on function bodies to find call-like patterns
    3. Resolve call targets to qualified names where possible
    4. Unresolved calls (dynamic dispatch, closures) are ignored

    Args:
        filepaths: Source files to analyze.
        project_root: Root for module path resolution.

    Returns:
        CallGraph with nodes and edges.
    """
    graph = CallGraph()
    all_nodes: list[FunctionNode] = []
    all_edges: list[CallEdge] = []

    for filepath in filepaths:
        try:
            source = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Compute module prefix
        module_prefix = ""
        if project_root is not None:
            try:
                rel = filepath.resolve().relative_to(project_root.resolve())
                parts = list(rel.parts)
                if parts and parts[-1].endswith(".py"):
                    parts[-1] = parts[-1][:-3]
                    if parts[-1] == "__init__":
                        parts = parts[:-1]
                    module_prefix = ".".join(parts) + "." if parts else ""
            except ValueError:
                pass

        nodes, edges = _extract_functions_and_calls(source, filepath, module_prefix)
        all_nodes.extend(nodes)
        all_edges.extend(edges)

    # Build name lookup for resolution
    name_lookup: dict[str, str] = {}
    for node in all_nodes:
        graph.add_node(node)
        # Index by short name and qualified name
        short_name = node.qualified_name.rsplit(".", 1)[-1]
        name_lookup[short_name] = node.qualified_name
        name_lookup[node.qualified_name] = node.qualified_name

    # Resolve edges
    for edge in all_edges:
        caller_qualified = name_lookup.get(edge.caller, edge.caller)
        callee_qualified = name_lookup.get(edge.callee)

        if callee_qualified is None:
            # Try partial matching: the callee might be "self.method" -> look up "method"
            parts = edge.callee.split(".")
            for part in reversed(parts):
                if part in name_lookup and part != "self":
                    callee_qualified = name_lookup[part]
                    break

        if (
            callee_qualified is not None
            and callee_qualified in graph.nodes
            and caller_qualified in graph.nodes
        ):
            graph.add_edge(caller_qualified, callee_qualified)

    return graph


def detect_adjacency_gaps(
    call_graph: CallGraph,
    min_component_size: int = 2,
) -> list[GapEvidence]:
    """Detect disconnected subgraphs that may indicate missed adjacencies.

    Per design doc Section 7: "Two subgraphs that are disconnected in the
    UNION of (call graph + event graph) are truly isolated."

    Since we only have the call graph (no event graph yet), disconnected
    components are flagged as POTENTIAL missed adjacencies with lower
    confidence.

    Args:
        call_graph: The CallGraph to analyze.
        min_component_size: Minimum size of a component to report (ignore singletons).

    Returns:
        List of GapEvidence with invariant_family = "executable_adjacency".
    """
    components = call_graph.get_disconnected_subgraphs()

    # Filter by minimum size
    significant_components = [c for c in components if len(c) >= min_component_size]

    # If there is only one significant component (or none), no adjacency gaps
    if len(significant_components) <= 1:
        return []

    evidence: list[GapEvidence] = []
    for i, component in enumerate(significant_components):
        sorted_members = sorted(component)
        representative = sorted_members[0]
        node = call_graph.nodes.get(representative)
        file_path = node.file_path if node else "unknown"

        details: dict[str, Any] = {
            "component_index": i,
            "component_size": len(component),
            "members": sorted_members[:10],
            "total_components": len(significant_components),
        }

        evidence.append(
            GapEvidence(
                invariant_family="executable_adjacency",
                description=(
                    f"Disconnected subgraph with {len(component)} functions: "
                    f"{', '.join(sorted_members[:3])}"
                    + (f" and {len(component) - 3} more" if len(component) > 3 else "")
                ),
                details=details,
                confidence=0.6,  # Lower confidence since we lack event graph
                location=file_path,
                detector="call_graph",
            )
        )

    return evidence

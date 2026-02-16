"""Dependency graph building for spec decomposition."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from spec_manager.decomposition.entity_index import load_entity_index
from spec_manager.decomposition.id_generator import (
    IDType,
    get_ids_by_type,
    load_id_map,
)


class EntityIndexEntry(TypedDict):
    """Projection contract for a single entity index record."""

    name: str
    keywords: list[str]
    sources: list[str]


RelationRecord = TypedDict(
    "RelationRecord",
    {
        "file": str,
        "line": int,
        "source": str,
        "target": str,
        "from": str,
        "to": str,
        "relation_type": str,
        "context": str,
        "snippet_id": str,
        "type": str,
    },
    total=False,
)


class GraphDiagnostic(TypedDict):
    """Structured diagnostic emitted while building a graph."""

    code: str
    message: str
    relation_id: str | None
    record_index: int | None
    record: Any


class GraphEdgeSource(TypedDict):
    """Structured provenance for one relation record supporting an edge."""

    relation_id: str
    relation_record_index: int
    file: str | None
    line: int | None
    record: RelationRecord


class GraphNode(TypedDict, total=False):
    """Serialized graph node."""

    id: str
    name: str
    keywords: list[str]
    sources: list[str]
    unresolved: bool


GraphEdge = TypedDict(
    "GraphEdge",
    {
        "id": str,
        "from": str,
        "to": str,
        "type": str,
        "relation_ids": list[str],
        "sources": list[GraphEdgeSource],
    },
)


class OutgoingAdjacencyEntry(TypedDict):
    """Outgoing adjacency entry."""

    target: str
    type: str
    relation_ids: list[str]


class IncomingAdjacencyEntry(TypedDict):
    """Incoming adjacency entry."""

    source: str
    type: str
    relation_ids: list[str]


class GraphAdjacency(TypedDict):
    """Incoming/outgoing adjacency lists for one node."""

    outgoing: list[OutgoingAdjacencyEntry]
    incoming: list[IncomingAdjacencyEntry]


class TopologicalOrderResult(TypedDict):
    """Topological sort output with explicit cycle metadata."""

    order: list[str]
    has_cycle: bool
    cycle_nodes: list[str]
    cycles: list[list[str]]


class TopologicalOrder(list[str]):
    """Topological order list enriched with cycle metadata."""

    has_cycle: bool
    cycle_nodes: list[str]
    cycles: list[list[str]]

    def __init__(
        self,
        order: list[str],
        *,
        has_cycle: bool,
        cycle_nodes: list[str],
        cycles: list[list[str]],
    ) -> None:
        super().__init__(order)
        self.has_cycle = has_cycle
        self.cycle_nodes = cycle_nodes
        self.cycles = cycles

    def as_dict(self) -> TopologicalOrderResult:
        """Return metadata in plain JSON-serializable form."""
        return {
            "order": list(self),
            "has_cycle": self.has_cycle,
            "cycle_nodes": self.cycle_nodes,
            "cycles": self.cycles,
        }


def _append_diagnostic(
    diagnostics: list[GraphDiagnostic],
    *,
    code: str,
    message: str,
    relation_id: str | None = None,
    record_index: int | None = None,
    record: Any = None,
) -> None:
    diagnostics.append(
        {
            "code": code,
            "message": message,
            "relation_id": relation_id,
            "record_index": record_index,
            "record": record,
        }
    )


def _normalize_entity_nodes(
    entity_index: dict[str, Any],
    diagnostics: list[GraphDiagnostic],
) -> dict[str, GraphNode]:
    """Normalize entity index records into node projection objects."""
    nodes: dict[str, GraphNode] = {}

    for entity_id, raw_entity_data in entity_index.items():
        if not isinstance(raw_entity_data, dict):
            _append_diagnostic(
                diagnostics,
                code="invalid_entity_record",
                message="Entity index entry is not an object.",
                record={"entity_id": entity_id, "value": raw_entity_data},
            )
            continue

        entity_data = cast("EntityIndexEntry", raw_entity_data)
        name = entity_data.get("name")
        raw_keywords = entity_data.get("keywords")
        raw_sources = entity_data.get("sources")

        if not isinstance(name, str) or not name:
            _append_diagnostic(
                diagnostics,
                code="entity_missing_name",
                message="Entity index entry is missing a valid name; using entity ID.",
                record={"entity_id": entity_id, "value": raw_entity_data},
            )
            name = entity_id

        keywords: list[str] = []
        if isinstance(raw_keywords, list):
            keywords = [kw for kw in raw_keywords if isinstance(kw, str)]
        else:
            _append_diagnostic(
                diagnostics,
                code="entity_invalid_keywords",
                message="Entity index entry has invalid keywords; expected a list of strings.",
                record={"entity_id": entity_id, "value": raw_entity_data},
            )

        sources: list[str] = []
        if isinstance(raw_sources, list):
            sources = [source for source in raw_sources if isinstance(source, str)]
        else:
            _append_diagnostic(
                diagnostics,
                code="entity_invalid_sources",
                message="Entity index entry has invalid sources; expected a list of strings.",
                record={"entity_id": entity_id, "value": raw_entity_data},
            )

        nodes[entity_id] = {
            "id": entity_id,
            "name": name,
            "keywords": keywords,
            "sources": sources,
            "unresolved": False,
        }

    return nodes


def _ensure_node(
    *,
    node_id: str,
    nodes: dict[str, GraphNode],
    unresolved_node_ids: set[str],
    diagnostics: list[GraphDiagnostic],
    relation_id: str,
    record_index: int,
    relation_record: RelationRecord,
) -> None:
    """Ensure a node exists and mark unresolved nodes explicitly."""
    if node_id in nodes:
        return

    nodes[node_id] = {
        "id": node_id,
        "name": node_id,
        "keywords": [],
        "sources": [],
        "unresolved": True,
    }

    if node_id in unresolved_node_ids:
        return
    unresolved_node_ids.add(node_id)

    _append_diagnostic(
        diagnostics,
        code="unresolved_entity",
        message="Relation references an entity absent from the entity index.",
        relation_id=relation_id,
        record_index=record_index,
        record={"node_id": node_id, "relation_record": relation_record},
    )


def _provenance_from_relation_record(
    *,
    relation_id: str,
    record_index: int,
    relation_record: RelationRecord,
    diagnostics: list[GraphDiagnostic],
) -> GraphEdgeSource:
    """Build structured provenance and surface missing provenance fields."""
    raw_file = relation_record.get("file")
    raw_line = relation_record.get("line")

    file_value = raw_file if isinstance(raw_file, str) and raw_file else None
    line_value = raw_line if isinstance(raw_line, int) and raw_line > 0 else None

    if file_value is None or line_value is None:
        _append_diagnostic(
            diagnostics,
            code="missing_relation_provenance",
            message="Relation record is missing authoritative file/line provenance.",
            relation_id=relation_id,
            record_index=record_index,
            record=relation_record,
        )

    return {
        "relation_id": relation_id,
        "relation_record_index": record_index,
        "file": file_value,
        "line": line_value,
        "record": relation_record,
    }


def _extract_relation_endpoints(
    *,
    relation_record: RelationRecord,
    diagnostics: list[GraphDiagnostic],
    relation_id: str,
    record_index: int,
) -> tuple[str | None, str | None]:
    """Normalize relation endpoints from boundary record variants."""
    source_value = relation_record.get("source")
    target_value = relation_record.get("target")
    from_value = relation_record.get("from")
    to_value = relation_record.get("to")

    from_id: str | None = None
    to_id: str | None = None

    if isinstance(source_value, str) and source_value:
        from_id = source_value
    elif isinstance(from_value, str) and from_value:
        from_id = from_value

    if isinstance(target_value, str) and target_value:
        to_id = target_value
    elif isinstance(to_value, str) and to_value:
        to_id = to_value

    source_conflict = (
        isinstance(source_value, str)
        and source_value
        and isinstance(from_value, str)
        and from_value
        and source_value != from_value
    )
    target_conflict = (
        isinstance(target_value, str)
        and target_value
        and isinstance(to_value, str)
        and to_value
        and target_value != to_value
    )
    if source_conflict or target_conflict:
        _append_diagnostic(
            diagnostics,
            code="conflicting_relation_endpoints",
            message="Relation record has conflicting endpoint fields.",
            relation_id=relation_id,
            record_index=record_index,
            record=relation_record,
        )
        return None, None

    if isinstance(from_value, str) and from_value and source_value is None:
        _append_diagnostic(
            diagnostics,
            code="relation_legacy_from_field",
            message="Relation record used 'from' instead of canonical 'source'.",
            relation_id=relation_id,
            record_index=record_index,
            record=relation_record,
        )
    if isinstance(to_value, str) and to_value and target_value is None:
        _append_diagnostic(
            diagnostics,
            code="relation_legacy_to_field",
            message="Relation record used 'to' instead of canonical 'target'.",
            relation_id=relation_id,
            record_index=record_index,
            record=relation_record,
        )

    return from_id, to_id


def _write_with_snapshot(path: Path, content: str) -> None:
    """Write file while preserving prior versions when content changes."""
    if path.exists():
        previous_content = path.read_text()
        if previous_content != content:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            digest = hashlib.sha256(previous_content.encode("utf-8")).hexdigest()[:12]
            snapshot_path = path.with_name(f"{path.stem}.{timestamp}.{digest}{path.suffix}")
            if not snapshot_path.exists():
                snapshot_path.write_text(previous_content)
    path.write_text(content)


def build_dependency_graph(workspace: Path) -> dict[str, Any]:
    """Build a dependency graph from relations.

    Returns a graph structure with:
    - nodes: All entities
    - edges: All relations between entities
    - adjacency: Adjacency lists for graph traversal
    - diagnostics: Explicit records for malformed or incomplete inputs
    """
    raw_id_map = load_id_map(workspace)
    raw_entity_index = load_entity_index(workspace)

    id_map = raw_id_map if isinstance(raw_id_map, dict) else {}
    entity_index = raw_entity_index if isinstance(raw_entity_index, dict) else {}

    diagnostics: list[GraphDiagnostic] = []
    if not isinstance(raw_id_map, dict):
        _append_diagnostic(
            diagnostics,
            code="invalid_id_map",
            message="ID map is not an object; graph will be empty.",
            record=raw_id_map,
        )
    if not isinstance(raw_entity_index, dict):
        _append_diagnostic(
            diagnostics,
            code="invalid_entity_index",
            message="Entity index is not an object; graph nodes will be unresolved from relations.",
            record=raw_entity_index,
        )

    nodes = _normalize_entity_nodes(entity_index, diagnostics)
    unresolved_node_ids: set[str] = set()

    # Deduplicate logical edges while preserving all source evidence.
    edge_index: dict[tuple[str, str, str], GraphEdge] = {}

    relation_ids = get_ids_by_type(id_map, IDType.RELATION)
    for rel_id in relation_ids:
        relation_sources = id_map.get(rel_id, [])
        if not isinstance(relation_sources, list):
            _append_diagnostic(
                diagnostics,
                code="invalid_relation_sources",
                message="Relation entry is not a list of source records.",
                relation_id=rel_id,
                record=relation_sources,
            )
            continue

        for record_index, raw_relation_record in enumerate(relation_sources):
            if not isinstance(raw_relation_record, dict):
                _append_diagnostic(
                    diagnostics,
                    code="invalid_relation_record",
                    message="Relation source record is not an object.",
                    relation_id=rel_id,
                    record_index=record_index,
                    record=raw_relation_record,
                )
                continue

            relation_record = cast("RelationRecord", raw_relation_record)
            from_id, to_id = _extract_relation_endpoints(
                relation_record=relation_record,
                diagnostics=diagnostics,
                relation_id=rel_id,
                record_index=record_index,
            )
            rel_type_raw = relation_record.get("relation_type")
            rel_type = (
                rel_type_raw if isinstance(rel_type_raw, str) and rel_type_raw else "relates_to"
            )

            if from_id is None:
                _append_diagnostic(
                    diagnostics,
                    code="missing_relation_source",
                    message="Relation record is missing a valid source entity ID.",
                    relation_id=rel_id,
                    record_index=record_index,
                    record=relation_record,
                )
                continue

            if to_id is None:
                _append_diagnostic(
                    diagnostics,
                    code="missing_relation_target",
                    message="Relation record is missing a valid target entity ID.",
                    relation_id=rel_id,
                    record_index=record_index,
                    record=relation_record,
                )
                continue

            _ensure_node(
                node_id=from_id,
                nodes=nodes,
                unresolved_node_ids=unresolved_node_ids,
                diagnostics=diagnostics,
                relation_id=rel_id,
                record_index=record_index,
                relation_record=relation_record,
            )
            _ensure_node(
                node_id=to_id,
                nodes=nodes,
                unresolved_node_ids=unresolved_node_ids,
                diagnostics=diagnostics,
                relation_id=rel_id,
                record_index=record_index,
                relation_record=relation_record,
            )

            edge_key = (from_id, to_id, rel_type)
            edge = edge_index.get(edge_key)
            if edge is None:
                edge = {
                    "id": rel_id,
                    "from": from_id,
                    "to": to_id,
                    "type": rel_type,
                    "relation_ids": [rel_id],
                    "sources": [],
                }
                edge_index[edge_key] = edge
            elif rel_id not in edge["relation_ids"]:
                edge["relation_ids"].append(rel_id)

            edge["sources"].append(
                _provenance_from_relation_record(
                    relation_id=rel_id,
                    record_index=record_index,
                    relation_record=relation_record,
                    diagnostics=diagnostics,
                )
            )

    edges = sorted(
        edge_index.values(),
        key=lambda edge: (
            edge["from"],
            edge["to"],
            edge["type"],
            edge["id"],
        ),
    )

    adjacency: dict[str, GraphAdjacency] = {
        entity_id: {"outgoing": [], "incoming": []} for entity_id in nodes
    }
    for edge in edges:
        adjacency[edge["from"]]["outgoing"].append(
            {
                "target": edge["to"],
                "type": edge["type"],
                "relation_ids": list(edge["relation_ids"]),
            }
        )
        adjacency[edge["to"]]["incoming"].append(
            {
                "source": edge["from"],
                "type": edge["type"],
                "relation_ids": list(edge["relation_ids"]),
            }
        )

    for entity_id in adjacency:
        outgoing = cast("list[OutgoingAdjacencyEntry]", adjacency[entity_id]["outgoing"])
        incoming = cast("list[IncomingAdjacencyEntry]", adjacency[entity_id]["incoming"])
        outgoing.sort(
            key=lambda item: (item["target"], item["type"], ",".join(item["relation_ids"]))
        )
        incoming.sort(
            key=lambda item: (item["source"], item["type"], ",".join(item["relation_ids"]))
        )

    graph = {
        "nodes": nodes,
        "edges": edges,
        "adjacency": adjacency,
        "diagnostics": diagnostics,
        "statistics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "diagnostic_count": len(diagnostics),
        },
    }

    return graph


def save_dependency_graph(workspace: Path, graph: dict[str, Any]) -> None:
    """Save dependency graph to workspace output."""
    output_dir = workspace / "output"
    output_dir.mkdir(exist_ok=True)

    # Save JSON
    json_file = output_dir / "dependency_graph.json"
    _write_with_snapshot(json_file, json.dumps(graph, indent=2))

    # Generate Mermaid diagram
    mermaid = generate_mermaid_diagram(graph)
    mermaid_file = output_dir / "dependency_graph.mermaid"
    _write_with_snapshot(mermaid_file, mermaid)


def generate_mermaid_diagram(graph: dict[str, Any]) -> str:
    """Generate a Mermaid diagram from the dependency graph."""
    lines = ["graph TD"]

    # Add nodes with labels
    for node_id, node_data in graph["nodes"].items():
        # Escape special characters in name
        name = node_data["name"].replace('"', "'")
        lines.append(f'    {node_id}["{name}"]')

    # Add edges
    arrow_styles = {
        "uses": "-->",
        "depends_on": "-.->",
        "composes": "===>",
        "triggers": "-..->",
        "extends": "-->|extends|",
        "produces": "-->|produces|",
        "consumes": "-->|consumes|",
    }

    for edge in graph["edges"]:
        from_id = edge.get("from")
        if not isinstance(from_id, str) or not from_id:
            continue
        arrow = arrow_styles.get(edge["type"], "-->")
        if "|" in arrow:
            lines.append(f"    {from_id} {arrow} {edge['to']}")
        else:
            lines.append(f"    {from_id} {arrow}|{edge['type']}| {edge['to']}")

    return "\n".join(lines)


def get_topological_order(graph: dict[str, Any]) -> TopologicalOrder:
    """Get entities in topological order (dependencies first).

    Useful for implementation ordering.
    """
    # Kahn's algorithm
    adjacency = graph.get("adjacency", {})
    in_degree = {node_id: len(adj["incoming"]) for node_id, adj in adjacency.items()}

    # Start with nodes that have no dependencies
    queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)

        for edge in adjacency.get(node, {}).get("outgoing", []):
            target = edge["target"]
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)

    cycle_nodes: list[str] = []
    cycles: list[list[str]] = []
    if len(result) != len(graph.get("nodes", {})):
        remaining = set(graph.get("nodes", {}).keys()) - set(result)
        cycle_nodes = sorted(remaining)
        result.extend(cycle_nodes)
        cycles = find_cycles(graph)

    return TopologicalOrder(
        result,
        has_cycle=bool(cycle_nodes),
        cycle_nodes=cycle_nodes,
        cycles=cycles,
    )


def find_cycles(graph: dict[str, Any]) -> list[list[str]]:
    """Find cycles in the dependency graph.

    Returns list of cycles, where each cycle is a list of entity IDs.
    """
    adjacency = graph["adjacency"]
    nodes = list(graph["nodes"].keys())

    visited = set()
    rec_stack = set()
    cycles = []

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)

        for edge in adjacency.get(node, {}).get("outgoing", []):
            target = edge["target"]
            if target not in visited:
                dfs(target, [*path, target])
            elif target in rec_stack:
                # Found a cycle
                cycle_start = path.index(target) if target in path else -1
                if cycle_start >= 0:
                    cycle = [*path[cycle_start:], target]
                    cycles.append(cycle)

        rec_stack.remove(node)

    for node in nodes:
        if node not in visited:
            dfs(node, [node])

    return cycles

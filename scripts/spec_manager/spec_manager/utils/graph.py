"""Dependency graph building for spec decomposition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spec_manager.decomposition.entity_index import load_entity_index
from spec_manager.decomposition.id_generator import (
    IDType,
    get_ids_by_type,
    load_id_map,
)


def build_dependency_graph(workspace: Path) -> dict[str, Any]:
    """Build a dependency graph from relations.

    Returns a graph structure with:
    - nodes: All entities
    - edges: All relations between entities
    - adjacency: Adjacency lists for graph traversal
    """
    id_map = load_id_map(workspace)
    entity_index = load_entity_index(workspace)

    # Build nodes from entity index
    nodes: dict[str, dict[str, Any]] = {}
    for entity_id, entity_data in entity_index.items():
        nodes[entity_id] = {
            "id": entity_id,
            "name": entity_data["name"],
            "keywords": entity_data["keywords"],
            "sources": entity_data["sources"],
        }

    def _relation_edges(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize relation sources into edge records."""
        out: list[dict[str, Any]] = []
        for src in sources:
            rel_type = src.get("relation_type") or src.get("relationship") or "relates_to"
            if src.get("from") and src.get("to"):
                out.append(
                    {"from": src.get("from"), "to": src.get("to"), "type": rel_type, "src": src}
                )
                continue
            if src.get("source") and src.get("target"):
                out.append(
                    {
                        "from": src.get("source"),
                        "to": src.get("target"),
                        "type": rel_type,
                        "src": src,
                    }
                )
                continue
            if src.get("source") and isinstance(src.get("targets"), list):
                for t in src.get("targets", []):
                    out.append({"from": src.get("source"), "to": t, "type": rel_type, "src": src})
        # Dedup
        seen = set()
        deduped = []
        for e in out:
            k = (e.get("from"), e.get("to"), e.get("type"))
            if k in seen:
                continue
            seen.add(k)
            deduped.append(e)
        return deduped

    # Build edges from relations
    edges: list[dict[str, Any]] = []
    adjacency: dict[str, dict[str, list[dict[str, Any]]]] = {
        entity_id: {"outgoing": [], "incoming": []} for entity_id in nodes
    }

    relation_ids = get_ids_by_type(id_map, IDType.RELATION)
    for rel_id in relation_ids:
        sources = id_map.get(rel_id, [])
        for edge_info in _relation_edges(sources):
            from_id = edge_info.get("from")
            to_id = edge_info.get("to")
            rel_type = edge_info.get("type", "relates_to")
            src = edge_info.get("src", {})

            if not from_id or not to_id:
                continue

            # Ensure nodes exist even if entity index missed them.
            for nid in (from_id, to_id):
                if nid not in nodes:
                    nodes[nid] = {"id": nid, "name": nid, "keywords": [], "sources": []}
                    adjacency[nid] = {"outgoing": [], "incoming": []}

            src_ref = None
            if src.get("file") is not None and src.get("line") is not None:
                src_ref = f"{src.get('file')}:{src.get('line')}"
            else:
                src_ref = "unknown"

            edge = {
                "id": rel_id,
                "from": from_id,
                "to": to_id,
                "type": rel_type,
                "source": src_ref,
            }
            edges.append(edge)

            # Update adjacency
            adjacency[from_id]["outgoing"].append(
                {
                    "target": to_id,
                    "type": rel_type,
                    "relation_id": rel_id,
                }
            )
            adjacency[to_id]["incoming"].append(
                {
                    "source": from_id,
                    "type": rel_type,
                    "relation_id": rel_id,
                }
            )

    graph = {
        "nodes": nodes,
        "edges": edges,
        "adjacency": adjacency,
        "statistics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }

    return graph


def save_dependency_graph(workspace: Path, graph: dict[str, Any]) -> None:
    """Save dependency graph to workspace output."""
    output_dir = workspace / "output"
    output_dir.mkdir(exist_ok=True)

    # Save JSON
    json_file = output_dir / "dependency_graph.json"
    json_file.write_text(json.dumps(graph, indent=2))

    # Generate Mermaid diagram
    mermaid = generate_mermaid_diagram(graph)
    mermaid_file = output_dir / "dependency_graph.mermaid"
    mermaid_file.write_text(mermaid)


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
        arrow = arrow_styles.get(edge["type"], "-->")
        if "|" in arrow:
            lines.append(f"    {edge['from']} {arrow} {edge['to']}")
        else:
            lines.append(f"    {edge['from']} {arrow}|{edge['type']}| {edge['to']}")

    return "\n".join(lines)


def get_topological_order(graph: dict[str, Any]) -> list[str]:
    """Get entities in topological order (dependencies first).

    Useful for implementation ordering.
    """
    # Kahn's algorithm
    adjacency = graph["adjacency"]
    in_degree = {node_id: len(adj["incoming"]) for node_id, adj in adjacency.items()}

    # Start with nodes that have no dependencies
    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    result = []

    while queue:
        node = queue.pop(0)
        result.append(node)

        for edge in adjacency.get(node, {}).get("outgoing", []):
            target = edge["target"]
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)

    # If result doesn't contain all nodes, there's a cycle
    if len(result) != len(graph["nodes"]):
        # Return partial order with cycle warning
        remaining = set(graph["nodes"].keys()) - set(result)
        result.extend(sorted(remaining))  # Add remaining in arbitrary order

    return result


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

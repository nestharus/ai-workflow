"""Adapter functions bridging legacy dict-based inputs to AdjacencyGraph.

These adapters accept the same pre-built dict inputs that the former
``adjacency_builder.py`` consumed and return ``AdjacencyGraph`` objects
with the appropriate ``SignalType`` edges.  A conversion helper turns
an ``AdjacencyGraph`` back into ``dict[str, AtomAdjacency]`` for
``AnalysisFileSchema`` compatibility.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from spec_manager.schemas.lineage import AtomAdjacency

from .graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


def cooccurrence_from_atom_sections(
    atom_to_section: dict[str, dict[str, str]],
) -> AdjacencyGraph:
    """Build a co-occurrence ``AdjacencyGraph`` from section colocation.

    Two atoms co-occur if they share the same ``section_id``.  This
    replicates the logic of the former ``build_co_occurrence_edges()``
    but outputs an ``AdjacencyGraph`` with ``SignalType.CO_OCCURRENCE``
    edges.

    Args:
        atom_to_section: Mapping of atom_id to
            ``{section_id, file_id, sha256}``.

    Returns:
        An ``AdjacencyGraph`` containing ``CO_OCCURRENCE`` edges.
    """
    graph = AdjacencyGraph()

    # Invert the mapping: section_id -> list of atom_ids.
    section_to_atoms: dict[str, list[str]] = defaultdict(list)
    for atom_id, section_info in atom_to_section.items():
        section_id = section_info.get("section_id", "")
        if section_id:
            section_to_atoms[section_id].append(atom_id)

    signal = EdgeSignal(signal_type=SignalType.CO_OCCURRENCE, weight=0.3)

    for _section_id, atoms in section_to_atoms.items():
        if len(atoms) < 2:
            continue
        for atom_id in atoms:
            graph.add_node(
                atom_id,
                NodeInfo(node_id=atom_id, node_type="algorithm"),
            )
        for i, atom_id in enumerate(atoms):
            for other_id in atoms[i + 1 :]:
                # Add bidirectional edges (undirected relationship).
                graph.add_edge(atom_id, other_id, signal)
                graph.add_edge(other_id, atom_id, signal)

    return graph


def store_touch_from_definitions(
    atom_registry: dict[str, dict[str, Any]],
    store_definitions: dict[str, list[str]],
) -> AdjacencyGraph:
    """Build a store-touch ``AdjacencyGraph`` from shared store access.

    Two atoms touch the same store if both appear in the atom list for
    a given store identifier.  This replicates the logic of the former
    ``build_store_touch_edges()`` but outputs an ``AdjacencyGraph`` with
    ``SignalType.STORE_TOUCH`` edges.

    Args:
        atom_registry: Map of atom_name to metadata (file, params, etc.).
        store_definitions: Map of store_id to list of atom_ids that
            access it.

    Returns:
        An ``AdjacencyGraph`` containing ``STORE_TOUCH`` edges.
    """
    graph = AdjacencyGraph()
    signal = EdgeSignal(signal_type=SignalType.STORE_TOUCH, weight=0.5)

    for _store_id, atom_ids in store_definitions.items():
        if len(atom_ids) < 2:
            continue
        # Filter to atoms that actually exist in the registry.
        valid_atoms = [a for a in atom_ids if a in atom_registry]
        if len(valid_atoms) < 2:
            continue

        for atom_id in valid_atoms:
            file_path = atom_registry[atom_id].get("file")
            graph.add_node(
                atom_id,
                NodeInfo(
                    node_id=atom_id,
                    node_type="algorithm",
                    file_path=file_path,
                ),
            )

        for i, atom_id in enumerate(valid_atoms):
            for other_id in valid_atoms[i + 1 :]:
                graph.add_edge(atom_id, other_id, signal)
                graph.add_edge(other_id, atom_id, signal)

    return graph


def graph_to_atom_adjacency(
    graph: AdjacencyGraph,
    all_atom_ids: set[str],
) -> dict[str, AtomAdjacency]:
    """Convert an ``AdjacencyGraph`` into ``dict[str, AtomAdjacency]``.

    For each atom_id, collects neighbors by signal type:
    ``CO_OCCURRENCE`` maps to ``co_occurrence_edges`` and
    ``STORE_TOUCH`` maps to ``store_touch_edges``.

    Args:
        graph: A unified ``AdjacencyGraph`` (may contain multiple
            signal types).
        all_atom_ids: Complete set of atom IDs to include in the
            output (atoms with no edges get empty lists).

    Returns:
        Dict mapping atom_id to ``AtomAdjacency`` with sorted edge
        lists, compatible with ``AnalysisFileSchema``.
    """
    co_occurrence: dict[str, set[str]] = defaultdict(set)
    store_touch: dict[str, set[str]] = defaultdict(set)

    for edge in graph.edges():
        for signal in edge.signals:
            if signal.signal_type == SignalType.CO_OCCURRENCE:
                co_occurrence[edge.source].add(edge.target)
            elif signal.signal_type == SignalType.STORE_TOUCH:
                store_touch[edge.source].add(edge.target)

    adjacency: dict[str, AtomAdjacency] = {}
    for atom_id in sorted(all_atom_ids):
        adjacency[atom_id] = AtomAdjacency(
            atom_id=atom_id,
            co_occurrence_edges=sorted(co_occurrence.get(atom_id, set())),
            store_touch_edges=sorted(store_touch.get(atom_id, set())),
        )

    return adjacency

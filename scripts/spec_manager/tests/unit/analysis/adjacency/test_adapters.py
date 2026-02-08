"""Tests for adjacency adapter functions.

Migrated from the former ``test_adjacency_builder.py``, adapted to verify
that the adapter functions produce correct ``AdjacencyGraph`` objects and
that ``graph_to_atom_adjacency`` converts them to ``AtomAdjacency`` dicts.
"""

from __future__ import annotations

from spec_manager.analysis.adjacency.adapters import (
    cooccurrence_from_atom_sections,
    graph_to_atom_adjacency,
    store_touch_from_definitions,
)
from spec_manager.analysis.adjacency.detector import build_unified_graph
from spec_manager.analysis.adjacency.graph import SignalType


class TestCooccurrenceFromAtomSections:
    """Test co-occurrence graph building from section colocation."""

    def test_groups_atoms_by_section(self) -> None:
        atom_to_section = {
            "atom_a": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
            "atom_b": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
            "atom_c": {"section_id": "SEC-002", "file_id": "f2", "sha256": "def"},
        }
        graph = cooccurrence_from_atom_sections(atom_to_section)

        # atom_a and atom_b share SEC-001, so they should be connected.
        edge_ab = graph.get_edge("atom_a", "atom_b")
        assert edge_ab is not None
        assert edge_ab.signals[0].signal_type == SignalType.CO_OCCURRENCE

        edge_ba = graph.get_edge("atom_b", "atom_a")
        assert edge_ba is not None

        # atom_c is alone in SEC-002 -- no edges from/to it.
        assert graph.get_edge("atom_a", "atom_c") is None
        assert graph.get_edge("atom_c", "atom_a") is None

    def test_single_atom_sections_produce_no_edges(self) -> None:
        atom_to_section = {
            "atom_x": {"section_id": "SEC-100", "file_id": "f1", "sha256": "abc"},
        }
        graph = cooccurrence_from_atom_sections(atom_to_section)
        assert graph.edges() == []

    def test_empty_input(self) -> None:
        graph = cooccurrence_from_atom_sections({})
        assert graph.edges() == []
        assert graph.nodes() == []

    def test_three_atoms_in_same_section(self) -> None:
        atom_to_section = {
            "a": {"section_id": "SEC-001", "file_id": "f1", "sha256": "x"},
            "b": {"section_id": "SEC-001", "file_id": "f1", "sha256": "x"},
            "c": {"section_id": "SEC-001", "file_id": "f1", "sha256": "x"},
        }
        graph = cooccurrence_from_atom_sections(atom_to_section)

        # All pairs should be connected (bidirectional).
        for src, tgt in [("a", "b"), ("a", "c"), ("b", "c")]:
            assert graph.get_edge(src, tgt) is not None
            assert graph.get_edge(tgt, src) is not None


class TestStoreTouchFromDefinitions:
    """Test store-touch graph building from shared store access."""

    def test_detects_shared_store_access(self) -> None:
        atom_registry = {
            "atom_a": {"file": "a.py", "params": [], "return_type": ""},
            "atom_b": {"file": "b.py", "params": [], "return_type": ""},
            "atom_c": {"file": "c.py", "params": [], "return_type": ""},
        }
        store_definitions = {
            "user_db": ["atom_a", "atom_b"],
            "cache": ["atom_c"],
        }
        graph = store_touch_from_definitions(atom_registry, store_definitions)

        edge_ab = graph.get_edge("atom_a", "atom_b")
        assert edge_ab is not None
        assert edge_ab.signals[0].signal_type == SignalType.STORE_TOUCH

        edge_ba = graph.get_edge("atom_b", "atom_a")
        assert edge_ba is not None

        # atom_c is alone in cache -- no edges.
        assert graph.get_edge("atom_a", "atom_c") is None

    def test_atoms_not_in_registry_ignored(self) -> None:
        atom_registry = {
            "atom_a": {"file": "a.py", "params": [], "return_type": ""},
        }
        store_definitions = {
            "user_db": ["atom_a", "atom_unknown"],
        }
        graph = store_touch_from_definitions(atom_registry, store_definitions)
        # atom_unknown is not in registry, so no valid pair exists.
        assert graph.edges() == []

    def test_empty_store_definitions(self) -> None:
        atom_registry = {"atom_a": {"file": "a.py", "params": [], "return_type": ""}}
        graph = store_touch_from_definitions(atom_registry, {})
        assert graph.edges() == []


class TestGraphToAtomAdjacency:
    """Test conversion from AdjacencyGraph to dict[str, AtomAdjacency]."""

    def test_combines_both_edge_types(self) -> None:
        atom_to_section = {
            "atom_a": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
            "atom_b": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
        }
        atom_registry = {
            "atom_a": {"file": "a.py", "params": [], "return_type": ""},
            "atom_b": {"file": "b.py", "params": [], "return_type": ""},
        }
        store_definitions = {
            "cache": ["atom_a", "atom_b"],
        }

        cooccurrence_graph = cooccurrence_from_atom_sections(atom_to_section)
        store_graph = store_touch_from_definitions(atom_registry, store_definitions)
        unified = build_unified_graph(
            cooccurrence_graph=cooccurrence_graph,
            store_graph=store_graph,
        )

        all_ids = set(atom_to_section.keys()) | set(atom_registry.keys())
        adjacency = graph_to_atom_adjacency(unified, all_ids)

        assert "atom_a" in adjacency
        assert "atom_b" in adjacency

        adj_a = adjacency["atom_a"]
        assert "atom_b" in adj_a.co_occurrence_edges
        assert "atom_b" in adj_a.store_touch_edges

    def test_no_duplicate_edges(self) -> None:
        atom_to_section = {
            "atom_a": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
            "atom_b": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
            "atom_c": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
        }
        atom_registry = {
            "atom_a": {"file": "a.py", "params": [], "return_type": ""},
            "atom_b": {"file": "b.py", "params": [], "return_type": ""},
            "atom_c": {"file": "c.py", "params": [], "return_type": ""},
        }

        cooccurrence_graph = cooccurrence_from_atom_sections(atom_to_section)
        unified = build_unified_graph(cooccurrence_graph=cooccurrence_graph)

        all_ids = set(atom_to_section.keys()) | set(atom_registry.keys())
        adjacency = graph_to_atom_adjacency(unified, all_ids)

        adj_a = adjacency["atom_a"]
        assert len(adj_a.co_occurrence_edges) == len(set(adj_a.co_occurrence_edges))

    def test_no_store_definitions(self) -> None:
        atom_to_section = {
            "atom_a": {"section_id": "SEC-001", "file_id": "f1", "sha256": "x"},
        }
        atom_registry = {
            "atom_a": {"file": "a.py", "params": [], "return_type": ""},
        }

        cooccurrence_graph = cooccurrence_from_atom_sections(atom_to_section)
        unified = build_unified_graph(cooccurrence_graph=cooccurrence_graph)

        all_ids = set(atom_to_section.keys()) | set(atom_registry.keys())
        adjacency = graph_to_atom_adjacency(unified, all_ids)

        assert adjacency["atom_a"].store_touch_edges == []

    def test_empty_graph(self) -> None:
        from spec_manager.analysis.adjacency.graph import AdjacencyGraph

        graph = AdjacencyGraph()
        adjacency = graph_to_atom_adjacency(graph, {"atom_x", "atom_y"})

        assert "atom_x" in adjacency
        assert "atom_y" in adjacency
        assert adjacency["atom_x"].co_occurrence_edges == []
        assert adjacency["atom_x"].store_touch_edges == []

    def test_atoms_without_edges_included(self) -> None:
        """Atoms in all_atom_ids but with no graph edges still appear."""
        atom_to_section = {
            "atom_a": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
            "atom_b": {"section_id": "SEC-001", "file_id": "f1", "sha256": "abc"},
        }

        cooccurrence_graph = cooccurrence_from_atom_sections(atom_to_section)
        unified = build_unified_graph(cooccurrence_graph=cooccurrence_graph)

        # Include atom_c which has no edges.
        all_ids = {"atom_a", "atom_b", "atom_c"}
        adjacency = graph_to_atom_adjacency(unified, all_ids)

        assert "atom_c" in adjacency
        assert adjacency["atom_c"].co_occurrence_edges == []
        assert adjacency["atom_c"].store_touch_edges == []

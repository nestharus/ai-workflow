"""Tests for entity co-occurrence extraction."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from spec_manager.analysis.adjacency.extractors.cooccurrence import (
    _build_cooccurrence_edges,
    _extract_entity_mentions,
    extract_cooccurrence_graph,
)


def _write_spec(directory: Path, filename: str, content: str) -> Path:
    """Write a spec markdown file and return its path."""
    path = directory / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


class TestExtractCooccurrenceGraph:
    def test_two_algorithms_same_section(self, tmp_path: Path) -> None:
        """Two algorithms declared in same section produce co-occurrence edge."""
        path = _write_spec(
            tmp_path,
            "spec.md",
            """\
            ## Sort Algorithms ([=Algorithm 1])

            This section covers sorting. See also (@[+Algorithm 2]) for comparison.

            ## Search ([=Algorithm 2])

            Binary search implementation.
            """,
        )
        graph = extract_cooccurrence_graph([path])

        # Algorithm 1 and Algorithm 2 co-occur in the first section
        # (Algorithm 1 is declared, Algorithm 2 is referenced)
        edge = graph.get_edge("Algorithm 1", "Algorithm 2")
        reverse = graph.get_edge("Algorithm 2", "Algorithm 1")
        assert edge is not None or reverse is not None

    def test_references_count_as_mentions(self, tmp_path: Path) -> None:
        """References (@[+Algorithm 1]) count as mentions."""
        path = _write_spec(
            tmp_path,
            "spec.md",
            """\
            ## Overview ([=Algorithm 3])

            Uses (@[+Algorithm 1]) and (@[+Algorithm 2]) together.
            """,
        )
        graph = extract_cooccurrence_graph([path])

        # All three algorithms co-occur in the same section
        nodes = set(graph.nodes())
        assert "Algorithm 1" in nodes
        assert "Algorithm 2" in nodes
        assert "Algorithm 3" in nodes

        # Each pair should have an edge
        edge_12 = graph.get_edge("Algorithm 1", "Algorithm 2")
        edge_13 = graph.get_edge("Algorithm 1", "Algorithm 3")
        edge_23 = graph.get_edge("Algorithm 2", "Algorithm 3")
        assert edge_12 is not None
        assert edge_13 is not None
        assert edge_23 is not None

    def test_many_entities_lower_proximity(self, tmp_path: Path) -> None:
        """Sections with many entities have lower per-edge proximity weight."""
        # Section with 2 entities
        path_small = _write_spec(
            tmp_path,
            "small.md",
            """\
            ## Section ([=Algorithm 1])

            Related to (@[+Algorithm 2]).
            """,
        )
        # Section with 5 entities
        path_large = _write_spec(
            tmp_path,
            "large.md",
            """\
            ## Overview ([=Algorithm 10])

            Uses (@[+Algorithm 11]), (@[+Algorithm 12]), (@[+Algorithm 13]), and (@[+Algorithm 14]).
            """,
        )

        graph_small = extract_cooccurrence_graph([path_small])
        graph_large = extract_cooccurrence_graph([path_large])

        # Small section (2 entities) has proximity = 0.5
        # Large section (5 entities) has proximity = 0.2
        small_edge = graph_small.get_edge("Algorithm 1", "Algorithm 2")
        large_edge = graph_large.get_edge("Algorithm 10", "Algorithm 11")

        assert small_edge is not None
        assert large_edge is not None

        small_weight = small_edge.total_weight
        large_weight = large_edge.total_weight
        assert small_weight > large_weight

    def test_no_self_edges(self, tmp_path: Path) -> None:
        """No self-edges (entity does not co-occur with itself)."""
        path = _write_spec(
            tmp_path,
            "spec.md",
            """\
            ## Algorithm ([=Algorithm 1])

            This section defines Algorithm 1. See also (@[+Algorithm 2]).
            """,
        )
        graph = extract_cooccurrence_graph([path])

        # No self-edge on Algorithm 1
        self_edge = graph.get_edge("Algorithm 1", "Algorithm 1")
        assert self_edge is None

    def test_multi_file_cooccurrence(self, tmp_path: Path) -> None:
        """Same entity in different files, different sections - no cross-file co-occurrence."""
        path_a = _write_spec(
            tmp_path,
            "file_a.md",
            """\
            ## Section A ([=Algorithm 1])

            Only Algorithm 1 here.
            """,
        )
        path_b = _write_spec(
            tmp_path,
            "file_b.md",
            """\
            ## Section B ([=Algorithm 2])

            References (@[+Algorithm 1]) from another file.
            """,
        )
        graph = extract_cooccurrence_graph([path_a, path_b])

        # file_b has Algorithm 2 and Algorithm 1 in same section
        edge = graph.get_edge("Algorithm 1", "Algorithm 2")
        reverse = graph.get_edge("Algorithm 2", "Algorithm 1")
        assert edge is not None or reverse is not None

    def test_empty_spec_list(self) -> None:
        graph = extract_cooccurrence_graph([])
        assert len(graph.nodes()) == 0
        assert len(graph.edges()) == 0

    def test_spec_without_annotations(self, tmp_path: Path) -> None:
        path = _write_spec(
            tmp_path,
            "plain.md",
            """\
            # Just a plain document

            No annotations here.
            """,
        )
        graph = extract_cooccurrence_graph([path])
        assert len(graph.nodes()) == 0
        assert len(graph.edges()) == 0

    def test_paragraph_mode(self, tmp_path: Path) -> None:
        """Paragraph mode uses blank-line-separated paragraphs as windows."""
        path = _write_spec(
            tmp_path,
            "para.md",
            """\
            ## Header ([=Algorithm 1])

            This paragraph references both (@[+Algorithm 2]) and (@[+Algorithm 3]).

            This paragraph only has (@[+Algorithm 4]).
            """,
        )
        graph = extract_cooccurrence_graph([path], window_mode="paragraph")

        # In paragraph mode, Algorithm 2 and Algorithm 3 co-occur in the same paragraph
        nodes = set(graph.nodes())
        assert "Algorithm 2" in nodes
        assert "Algorithm 3" in nodes
        # Algorithm 2 and Algorithm 3 should have an edge (same paragraph)
        edge = graph.get_edge("Algorithm 2", "Algorithm 3")
        reverse = graph.get_edge("Algorithm 3", "Algorithm 2")
        assert edge is not None or reverse is not None


class TestExtractEntityMentions:
    def test_basic_extraction(self, tmp_path: Path) -> None:
        content = textwrap.dedent("""\
            ## Feature ([=Algorithm 1])

            Uses (@[+Algorithm 2]) and (@[=Algorithm 3]) together.

            ## Other ([=Algorithm 4])

            Independent section.
        """)
        mentions = _extract_entity_mentions(content, "test.md")

        assert "Algorithm 1" in mentions
        algo1_section = mentions["Algorithm 1"]
        assert "Algorithm 1" in algo1_section
        assert "Algorithm 2" in algo1_section
        assert "Algorithm 3" in algo1_section

    def test_no_declarations(self) -> None:
        content = "Just plain text without annotations."
        mentions = _extract_entity_mentions(content, "test.md")
        assert len(mentions) == 0


class TestBuildCooccurrenceEdges:
    def test_pairwise_combinations(self) -> None:
        section_entities = {
            "section_1": ["A", "B", "C"],
        }
        edges = _build_cooccurrence_edges(section_entities, "test.md")
        # 3 entities -> 3 pairs: (A,B), (A,C), (B,C)
        assert len(edges) == 3

    def test_single_entity_no_edges(self) -> None:
        section_entities = {
            "section_1": ["A"],
        }
        edges = _build_cooccurrence_edges(section_entities, "test.md")
        assert len(edges) == 0

    def test_proximity_inversely_proportional(self) -> None:
        section_entities_2 = {"s1": ["A", "B"]}
        section_entities_5 = {"s1": ["A", "B", "C", "D", "E"]}

        edges_2 = _build_cooccurrence_edges(section_entities_2, "test.md")
        edges_5 = _build_cooccurrence_edges(section_entities_5, "test.md")

        # Proximity for 2 entities = 0.5, for 5 entities = 0.2
        assert edges_2[0].proximity == pytest.approx(0.5)
        assert edges_5[0].proximity == pytest.approx(0.2)

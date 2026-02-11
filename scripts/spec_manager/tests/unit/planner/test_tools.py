"""Tests for spec_manager.planner.tools — tool adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from spec_manager.planner.tools.constraints_tool import (
    ConstraintRecord,
    ConstraintsSnapshot,
    ConstraintsTool,
)
from spec_manager.planner.tools.evidence_tool import (
    EvidenceHit,
    EvidenceSearchResult,
    EvidenceTool,
)
from spec_manager.planner.tools.integration_tool import (
    IntegrationEdge,
    IntegrationGraph,
    IntegrationNode,
    IntegrationTool,
    RiskAssessment,
)
from spec_manager.planner.tools.research_tool import (
    ResearchFinding,
    ResearchQuery,
    ResearchResult,
    ResearchTool,
)

# ---------------------------------------------------------------------------
# ResearchTool
# ---------------------------------------------------------------------------


class TestResearchTool:
    def test_research_tool_no_deps(self) -> None:
        """With no dependencies, research returns an empty result."""
        tool = ResearchTool()
        query = ResearchQuery(question="What is netting?")
        result = tool.research(query)
        assert isinstance(result, ResearchResult)
        assert result.findings == []
        assert result.synthesis == ""
        assert result.confidence == 0.0
        assert result.has_answer is False

    def test_research_tool_steering_match(self) -> None:
        """With a steering script that matches, returns a finding."""
        steering = MagicMock()
        steering.match.return_value = "Netting is bilateral offset"

        tool = ResearchTool(steering_script=steering)
        query = ResearchQuery(question="What is netting?", dimension="local")
        result = tool.research(query)

        assert result.has_answer is True
        assert len(result.findings) == 1
        assert result.findings[0].source == "steering"
        assert result.findings[0].confidence == 0.9
        assert "Netting is bilateral offset" in result.synthesis

    def test_research_tool_steering_no_match(self) -> None:
        """Steering script that returns None has no findings."""
        steering = MagicMock()
        steering.match.return_value = None

        tool = ResearchTool(steering_script=steering)
        query = ResearchQuery(question="Unknown topic", dimension="local")
        result = tool.research(query)
        assert result.findings == []

    def test_research_tool_evidence_search(self) -> None:
        """With a mock evidence searcher, returns findings from the store."""
        hit = MagicMock()
        hit.text = "Treasury netting reduces settlement risk"
        hit.score = 0.8
        hit.lib_id = "lib-treasury"
        hit.section_path = "section/2"

        searcher = MagicMock()
        searcher.search.return_value = [hit]

        tool = ResearchTool(evidence_searcher=searcher)
        query = ResearchQuery(question="netting risk", max_results=3)
        result = tool.research(query)

        assert len(result.findings) == 1
        assert result.findings[0].source == "evidence_store"
        assert result.findings[0].confidence == 0.8
        searcher.search.assert_called_once_with("netting risk", max_results=3)


# ---------------------------------------------------------------------------
# IntegrationTool
# ---------------------------------------------------------------------------


class TestIntegrationTool:
    def test_integration_tool_empty_graph(self) -> None:
        """Without source_cache, build_graph returns an empty graph."""
        tool = IntegrationTool()
        graph = tool.build_graph(["foo.py", "bar.py"])
        assert isinstance(graph, IntegrationGraph)
        assert graph.nodes == []
        assert graph.edges == []

    def test_integration_tool_risk_assessment_no_edges(self) -> None:
        """assess_risk with no edges returns blast_radius equal to changed set."""
        tool = IntegrationTool()
        graph = IntegrationGraph(
            nodes=[
                IntegrationNode(node_id="a", node_type="function", name="fn_a", file="a.py"),
                IntegrationNode(node_id="b", node_type="function", name="fn_b", file="b.py"),
            ],
            edges=[],
        )
        risk = tool.assess_risk(graph, changed_nodes=["a"])
        assert isinstance(risk, RiskAssessment)
        assert risk.blast_radius == 1
        assert risk.risk_level == "low"
        assert risk.rationale != ""

    def test_integration_tool_risk_assessment_with_edges(self) -> None:
        """assess_risk with edges walks the BFS and finds impacted files."""
        tool = IntegrationTool()
        graph = IntegrationGraph(
            nodes=[
                IntegrationNode(node_id="a", node_type="function", name="fn_a", file="a.py"),
                IntegrationNode(node_id="b", node_type="function", name="fn_b", file="b.py"),
                IntegrationNode(node_id="c", node_type="function", name="fn_c", file="c.py"),
            ],
            edges=[
                IntegrationEdge(source="a", target="b", edge_type="calls"),
                IntegrationEdge(source="b", target="c", edge_type="calls"),
            ],
        )
        risk = tool.assess_risk(graph, changed_nodes=["a"])
        assert risk.blast_radius == 3
        assert risk.risk_level == "low"  # 3 <= 3 is low
        assert set(risk.impacted_files) == {"a.py", "b.py", "c.py"}

    def test_integration_graph_to_dict(self) -> None:
        """IntegrationGraph.to_dict serializes correctly."""
        graph = IntegrationGraph(
            nodes=[IntegrationNode(node_id="x", node_type="file", name="x.py")],
            edges=[IntegrationEdge(source="x", target="y", edge_type="imports")],
        )
        d = graph.to_dict()
        assert len(d["nodes"]) == 1
        assert d["nodes"][0]["id"] == "x"
        assert len(d["edges"]) == 1
        assert d["edges"][0]["type"] == "imports"


# ---------------------------------------------------------------------------
# ConstraintsTool
# ---------------------------------------------------------------------------


class TestConstraintsTool:
    def test_constraints_tool_load_empty(self) -> None:
        """No workspace returns an empty snapshot."""
        tool = ConstraintsTool(workspace_root=None)
        snapshot = tool.load_constraints("slice-1")
        assert isinstance(snapshot, ConstraintsSnapshot)
        assert snapshot.slice_id == "slice-1"
        assert snapshot.constraints == []

    def test_constraints_tool_load_no_file(self, tmp_path: Path) -> None:
        """No constraint file on disk returns empty snapshot."""
        tool = ConstraintsTool(workspace_root=tmp_path)
        snapshot = tool.load_constraints("slice-no-file")
        assert snapshot.constraints == []

    def test_constraints_tool_load_from_file(self, tmp_path: Path) -> None:
        """Reads constraints from a JSON file on disk."""
        constraints_dir = tmp_path / "analysis" / "constraints"
        constraints_dir.mkdir(parents=True)
        data = {
            "constraints": [
                {
                    "constraint_id": "c-1",
                    "question": "What is the netting scope?",
                    "answer": "Bilateral only",
                    "source": "user",
                    "confidence": 0.95,
                },
                {
                    "constraint_id": "c-2",
                    "question": "Settlement frequency?",
                    "answer": "T+1",
                    "source": "steering",
                    "confidence": 0.8,
                },
            ]
        }
        (constraints_dir / "my-slice.json").write_text(json.dumps(data), encoding="utf-8")

        tool = ConstraintsTool(workspace_root=tmp_path)
        snapshot = tool.load_constraints("my-slice")
        assert len(snapshot.constraints) == 2
        assert snapshot.constraints[0].question == "What is the netting scope?"
        assert snapshot.constraints[0].answer == "Bilateral only"
        assert snapshot.constraints[1].constraint_id == "c-2"

    def test_constraints_tool_check_coverage(self, tmp_path: Path) -> None:
        """check_coverage identifies which questions are already answered."""
        constraints_dir = tmp_path / "analysis" / "constraints"
        constraints_dir.mkdir(parents=True)
        data = {
            "constraints": [
                {
                    "constraint_id": "c-1",
                    "question": "What is the netting scope?",
                    "answer": "Bilateral only",
                    "source": "user",
                    "confidence": 0.95,
                },
            ]
        }
        (constraints_dir / "s1.json").write_text(json.dumps(data), encoding="utf-8")

        tool = ConstraintsTool(workspace_root=tmp_path)
        coverage = tool.check_coverage(
            "s1",
            ["What is the netting scope?", "What is the settlement currency?"],
        )
        assert coverage["What is the netting scope?"] is not None
        assert coverage["What is the netting scope?"].answer == "Bilateral only"
        assert coverage["What is the settlement currency?"] is None

    def test_constraints_snapshot_covers(self) -> None:
        """ConstraintsSnapshot.covers matches case-insensitively."""
        snapshot = ConstraintsSnapshot(
            slice_id="s1",
            constraints=[
                ConstraintRecord(
                    constraint_id="c-1",
                    question="What is X?",
                    answer="42",
                )
            ],
        )
        assert snapshot.covers("what is x?") is not None
        assert snapshot.covers("What is X?") is not None
        assert snapshot.covers("unrelated?") is None


# ---------------------------------------------------------------------------
# EvidenceTool
# ---------------------------------------------------------------------------


class TestEvidenceTool:
    def test_evidence_tool_no_searcher(self) -> None:
        """Without a searcher, search returns empty result."""
        tool = EvidenceTool()
        result = tool.search("netting")
        assert isinstance(result, EvidenceSearchResult)
        assert result.hits == []
        assert result.has_results is False
        assert result.best_hit is None

    def test_evidence_tool_with_mock_searcher(self) -> None:
        """With a mock searcher, delegates and wraps results."""
        raw_hit = MagicMock()
        raw_hit.paragraph = MagicMock()
        raw_hit.paragraph.text = "Treasury netting explanation"
        raw_hit.lib_id = "lib-treasury"
        raw_hit.score = 0.75
        raw_hit.section_path = "section/3"
        raw_hit.matched_keywords = ["netting"]

        searcher = MagicMock()
        searcher.search.return_value = [raw_hit]

        tool = EvidenceTool(evidence_searcher=searcher)
        result = tool.search("netting", max_results=3, min_score=0.1)

        assert result.has_results is True
        assert len(result.hits) == 1
        assert result.hits[0].text == "Treasury netting explanation"
        assert result.hits[0].lib_id == "lib-treasury"
        assert result.hits[0].score == 0.75
        assert result.best_hit is not None
        assert result.best_hit.score == 0.75
        searcher.search.assert_called_once_with("netting", max_results=3, min_score=0.1)

    def test_evidence_tool_search_for_ambiguity(self) -> None:
        """search_for_ambiguity falls back to regular search when no specialized method."""
        searcher = MagicMock()
        searcher.search.return_value = []
        # No search_for_ambiguity attr -> falls back
        del searcher.search_for_ambiguity

        tool = EvidenceTool(evidence_searcher=searcher)
        result = tool.search_for_ambiguity("ambiguity text", "question?")
        assert isinstance(result, EvidenceSearchResult)

    def test_evidence_hit_dataclass(self) -> None:
        """EvidenceHit can be constructed with all fields."""
        hit = EvidenceHit(
            lib_id="lib-1",
            text="some text",
            score=0.9,
            section_path="s/1",
            matched_keywords=["netting", "treasury"],
        )
        assert hit.lib_id == "lib-1"
        assert hit.score == 0.9
        assert len(hit.matched_keywords) == 2

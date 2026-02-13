"""Tests for spec_manager.planner.architecture.decision_detector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from spec_manager.planner.architecture.decision_detector import (
    DecisionPointDetector,
    _build_detection_prompt,
    _parse_detection_output,
)
from spec_manager.planner.constraints.types import ConstraintFact, ImpactClassification


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def sample_gaps() -> list[dict[str, Any]]:
    return [
        {"target": "module_a", "description": "Choose architecture pattern for module"},
        {"target": "module_b", "description": "Simple data format"},
        {"target": "module_c", "description": "Design coupling between components"},
    ]


@pytest.fixture()
def sample_discovery() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "kind": "function", "name": "process_data"},
            {"id": "n2", "kind": "class", "name": "DataProcessor"},
        ],
        "edges": [],
    }


# ---------------------------------------------------------------------------
# Heuristic detection (no LLM)
# ---------------------------------------------------------------------------


class TestHeuristicDetection:
    def test_detects_arch_keywords(self, workspace: Path, sample_gaps, sample_discovery):
        detector = DecisionPointDetector(workspace)
        results = detector.detect(
            slice_id="slice-1",
            gaps=sample_gaps,
            discovery=sample_discovery,
        )
        # "architecture pattern" and "coupling" should trigger
        assert len(results) >= 2
        for dp in results:
            assert dp.decision_id.startswith("DEC-")
            assert dp.owner_slice_id == "slice-1"
            assert dp.status == "OPEN"

    def test_no_arch_keywords_returns_empty(self, workspace: Path, sample_discovery):
        gaps = [
            {"target": "x", "description": "add logging"},
            {"target": "y", "description": "fix typo"},
        ]
        detector = DecisionPointDetector(workspace)
        results = detector.detect(
            slice_id="slice-1",
            gaps=gaps,
            discovery=sample_discovery,
        )
        assert results == []

    def test_empty_gaps(self, workspace: Path, sample_discovery):
        detector = DecisionPointDetector(workspace)
        results = detector.detect(
            slice_id="slice-1",
            gaps=[],
            discovery=sample_discovery,
        )
        assert results == []


# ---------------------------------------------------------------------------
# LLM-based detection (mocked)
# ---------------------------------------------------------------------------


class TestLLMDetection:
    def test_detect_via_llm(self, workspace: Path, sample_gaps, sample_discovery):
        llm_response = json.dumps(
            [
                {
                    "scope": "intra:LIB",
                    "description": "Choose event-driven vs request-response",
                    "trigger_evidence": ["ev-1"],
                    "impact": "HIGH",
                    "blast_radius": "CROSS_SLICE",
                },
                {
                    "scope": "inter:A->B",
                    "description": "Define API contract",
                    "trigger_evidence": ["ev-2"],
                    "impact": "MEDIUM",
                    "blast_radius": "SLICE",
                },
            ]
        )

        def mock_agent(prompt: str) -> str:
            return llm_response

        detector = DecisionPointDetector(workspace, run_agent=mock_agent)
        results = detector.detect(
            slice_id="slice-1",
            gaps=sample_gaps,
            discovery=sample_discovery,
        )
        assert len(results) == 2
        assert results[0].description == "Choose event-driven vs request-response"
        assert results[0].impact.impact == "HIGH"
        assert results[1].scope == "inter:A->B"

    def test_llm_returns_empty_array(self, workspace: Path, sample_gaps, sample_discovery):
        def mock_agent(prompt: str) -> str:
            return "[]"

        detector = DecisionPointDetector(workspace, run_agent=mock_agent)
        results = detector.detect(
            slice_id="s1",
            gaps=sample_gaps,
            discovery=sample_discovery,
        )
        assert results == []

    def test_llm_returns_garbage(self, workspace: Path, sample_gaps, sample_discovery):
        def mock_agent(prompt: str) -> str:
            return "not valid json at all"

        detector = DecisionPointDetector(workspace, run_agent=mock_agent)
        results = detector.detect(
            slice_id="s1",
            gaps=sample_gaps,
            discovery=sample_discovery,
        )
        assert results == []

    def test_llm_returns_json_with_wrapper(self, workspace: Path, sample_gaps, sample_discovery):
        llm_response = 'Here are the decisions:\n```json\n[{"scope":"system","description":"Global config","trigger_evidence":[],"impact":"LOW","blast_radius":"LOCAL"}]\n```'

        def mock_agent(prompt: str) -> str:
            return llm_response

        detector = DecisionPointDetector(workspace, run_agent=mock_agent)
        results = detector.detect(
            slice_id="s1",
            gaps=sample_gaps,
            discovery=sample_discovery,
        )
        assert len(results) == 1
        assert results[0].scope == "system"


# ---------------------------------------------------------------------------
# Filtering decided points
# ---------------------------------------------------------------------------


class TestFilterDecided:
    def test_filters_exact_match(self, workspace: Path, sample_gaps, sample_discovery):
        llm_response = json.dumps(
            [
                {
                    "scope": "intra:LIB",
                    "description": "Use caching",
                    "trigger_evidence": [],
                    "impact": "LOW",
                    "blast_radius": "LOCAL",
                },
                {
                    "scope": "inter:A->B",
                    "description": "Define API contract",
                    "trigger_evidence": [],
                    "impact": "MEDIUM",
                    "blast_radius": "SLICE",
                },
            ]
        )

        def mock_agent(prompt: str) -> str:
            return llm_response

        constraints = [
            ConstraintFact(
                constraint_id="CON-001",
                question="Use caching",
                answer="Yes, Redis",
                scope="intra:LIB",
                validated=True,
                status="ACTIVE",
            ),
        ]

        detector = DecisionPointDetector(workspace, run_agent=mock_agent)
        results = detector.detect(
            slice_id="s1",
            gaps=sample_gaps,
            discovery=sample_discovery,
            authoritative_constraints=constraints,
        )
        # "Use caching" should be filtered out (scope + description match)
        assert len(results) == 1
        assert results[0].description == "Define API contract"

    def test_no_filter_when_no_constraints(self, workspace: Path, sample_gaps, sample_discovery):
        llm_response = json.dumps(
            [
                {
                    "scope": "intra:LIB",
                    "description": "Pick DB",
                    "trigger_evidence": [],
                    "impact": "LOW",
                    "blast_radius": "LOCAL",
                },
            ]
        )

        def mock_agent(prompt: str) -> str:
            return llm_response

        detector = DecisionPointDetector(workspace, run_agent=mock_agent)
        results = detector.detect(
            slice_id="s1",
            gaps=sample_gaps,
            discovery=sample_discovery,
            authoritative_constraints=[],
        )
        assert len(results) == 1

    def test_superseded_constraint_does_not_filter(
        self, workspace: Path, sample_gaps, sample_discovery
    ):
        llm_response = json.dumps(
            [
                {
                    "scope": "intra:LIB",
                    "description": "Pick DB",
                    "trigger_evidence": [],
                    "impact": "LOW",
                    "blast_radius": "LOCAL",
                },
            ]
        )

        def mock_agent(prompt: str) -> str:
            return llm_response

        constraints = [
            ConstraintFact(
                constraint_id="CON-OLD",
                question="Pick DB",
                scope="intra:LIB",
                validated=True,
                status="SUPERSEDED",
            ),
        ]
        detector = DecisionPointDetector(workspace, run_agent=mock_agent)
        results = detector.detect(
            slice_id="s1",
            gaps=sample_gaps,
            discovery=sample_discovery,
            authoritative_constraints=constraints,
        )
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Prompt / parse helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_build_detection_prompt_format(self):
        prompt = _build_detection_prompt(
            slice_id="s1",
            gaps=[{"target": "t1", "description": "d1"}],
            discovery={"nodes": [{"kind": "function", "name": "f1"}]},
            evidence_refs=["ref-1"],
        )
        assert "s1" in prompt
        assert "t1" in prompt
        assert "ref-1" in prompt

    def test_parse_detection_output_valid(self):
        raw = json.dumps(
            [
                {
                    "scope": "system",
                    "description": "D1",
                    "trigger_evidence": ["e1"],
                    "impact": "HIGH",
                    "blast_radius": "SYSTEM",
                },
            ]
        )
        results = _parse_detection_output(raw, "slice-x")
        assert len(results) == 1
        assert results[0].owner_slice_id == "slice-x"
        assert results[0].impact.impact == "HIGH"

    def test_parse_detection_output_invalid(self):
        assert _parse_detection_output("garbage", "s1") == []

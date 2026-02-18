"""Tests for the evidence store researcher."""

from __future__ import annotations

import json
from pathlib import Path

from spec_manager.core.evidence_index import EvidenceIndex
from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.research.evidence_store_researcher import (
    EvidenceStoreResearcher,
)

SPEC_WITH_ANSWER = """\
# Payment Processing

## Gateway Timeout Handling

When the payment gateway times out, the system retries up to 3 times
with exponential backoff. After all retries are exhausted, the transaction
is marked as PENDING and a manual review notification is sent.

The timeout threshold is configurable via the gateway_timeout_ms setting,
defaulting to 5000 milliseconds. ENT-0001 payment config store holds
the current timeout values.

## Refund Processing

Refunds are processed within 5 business days. The refund amount cannot
exceed the original transaction amount.
"""


def _make_ambiguity(
    ambiguity_id: str = "AMB-001",
    source_text: str = "gateway timeout behavior",
    question: str = "How does the system handle gateway timeouts?",
) -> Ambiguity:
    return Ambiguity(
        ambiguity_id=ambiguity_id,
        source_text=source_text,
        source_location="spec.md::PaymentProcessing",
        ambiguity_type="missing_condition",
        confidence=0.8,
        suggested_question=question,
    )


def _build_researcher_with_spec(spec_content: str = SPEC_WITH_ANSWER) -> EvidenceStoreResearcher:
    index = EvidenceIndex()
    hollowed = hollow_out_spec("LIB-0001", spec_content)
    index.add_spec(hollowed)
    return EvidenceStoreResearcher(index)


def test_research_finds_answer_in_store(tmp_path: Path):
    """Mock index with matching content, verify SteeringResponse returned."""
    researcher = _build_researcher_with_spec()
    ambiguity = _make_ambiguity()

    response = researcher.research(ambiguity, tmp_path)

    assert response is not None
    assert response.ambiguity_id == "AMB-001"
    assert response.source == "evidence_store"
    assert len(response.response_text) > 0
    # Should contain gateway/timeout related content
    assert (
        "timeout" in response.response_text.lower() or "gateway" in response.response_text.lower()
    )


def test_research_no_answer_returns_none(tmp_path: Path):
    """Empty store, verify None returned."""
    index = EvidenceIndex()
    researcher = EvidenceStoreResearcher(index)
    ambiguity = _make_ambiguity()

    response = researcher.research(ambiguity, tmp_path)

    assert response is None


def test_flag_as_spec_gap_creates_gap(tmp_path: Path):
    """Verify Gap entry created with correct type and evidence."""
    index = EvidenceIndex()
    researcher = EvidenceStoreResearcher(index)
    ambiguity = _make_ambiguity()

    researcher.flag_as_spec_gap(ambiguity, tmp_path)

    gap_file = tmp_path / "evidence_store_gaps.json"
    assert gap_file.exists()

    data = json.loads(gap_file.read_text(encoding="utf-8"))
    assert len(data["gaps"]) == 1

    gap = data["gaps"][0]
    assert gap["gap_type"] == "ambiguity"
    assert gap["id"] == "GAP-ES-AMB-001"
    assert gap["status"] == "open"
    assert len(gap["evidence"]) == 1
    assert gap["evidence"][0]["detector"] == "evidence_store_researcher"


def test_response_source_is_evidence_store(tmp_path: Path):
    """Verify source field is set correctly."""
    researcher = _build_researcher_with_spec()
    ambiguity = _make_ambiguity()

    response = researcher.research(ambiguity, tmp_path)

    assert response is not None
    assert response.source == "evidence_store"


def test_flag_idempotent(tmp_path: Path):
    """Calling flag_as_spec_gap twice does not duplicate the gap."""
    index = EvidenceIndex()
    researcher = EvidenceStoreResearcher(index)
    ambiguity = _make_ambiguity()

    researcher.flag_as_spec_gap(ambiguity, tmp_path)
    researcher.flag_as_spec_gap(ambiguity, tmp_path)

    gap_file = tmp_path / "evidence_store_gaps.json"
    data = json.loads(gap_file.read_text(encoding="utf-8"))
    # Should still be 1 gap, not 2
    assert len(data["gaps"]) == 1


def test_low_score_returns_none(tmp_path: Path):
    """When query doesn't match well, return None."""
    # Use spec content that has nothing to do with the query
    researcher = _build_researcher_with_spec(
        "# Cooking\n\n## Recipes\n\nMake a cake with flour and eggs."
    )
    ambiguity = _make_ambiguity(
        source_text="quantum computing entanglement protocol",
        question="How do qubits maintain coherence during measurement?",
    )

    response = researcher.research(ambiguity, tmp_path)

    # Should be None because the spec has nothing about quantum computing
    assert response is None

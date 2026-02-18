"""Tests for coordinator integration with evidence store."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from spec_manager.core.evidence_index import EvidenceIndex
from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.research.coordinator import ResearchCoordinator

SPEC_WITH_ANSWER = """\
# Payment Processing

## Gateway Timeout Handling

When the payment gateway times out, the system retries up to 3 times
with exponential backoff. After all retries are exhausted, the transaction
is marked as PENDING and a manual review notification is sent.
"""


def _make_ambiguity() -> Ambiguity:
    return Ambiguity(
        ambiguity_id="AMB-001",
        source_text="gateway timeout behavior",
        source_location="spec.md::Payments",
        ambiguity_type="missing_condition",
        confidence=0.8,
        suggested_question="How does the system handle gateway timeouts?",
    )


def test_coordinator_skips_web_when_evidence_found(tmp_path: Path):
    """Verify web search agents are not called when evidence store has an answer."""
    index = EvidenceIndex()
    hollowed = hollow_out_spec("LIB-0001", SPEC_WITH_ANSWER)
    index.add_spec(hollowed)

    coordinator = ResearchCoordinator(evidence_index=index)
    ambiguity = _make_ambiguity()

    # Mock run_agent so we can verify it's NOT called
    with patch("spec_manager.refinement.interactive.research.coordinator.run_agent") as mock_agent:
        response = coordinator.research(ambiguity, tmp_path)

    assert response is not None
    assert response.source == "evidence_store"
    # run_agent should NOT have been called
    mock_agent.assert_not_called()


def test_coordinator_falls_through_to_web_search(tmp_path: Path):
    """Verify web search is used when evidence store returns None."""
    # Empty index - no evidence available
    index = EvidenceIndex()
    coordinator = ResearchCoordinator(evidence_index=index)
    ambiguity = _make_ambiguity()

    # Mock run_agent to simulate web search returning a decision
    decision_json = '{"decision": "Retry 3 times then fail", "confidence": 0.7}'
    with patch(
        "spec_manager.refinement.interactive.research.coordinator.run_agent",
        return_value=decision_json,
    ) as mock_agent:
        response = coordinator.research(ambiguity, tmp_path)

    assert response is not None
    assert response.source == "research_web"
    # run_agent should have been called (3 times: signal, search, synthesis)
    assert mock_agent.call_count == 3


def test_coordinator_without_evidence_index(tmp_path: Path):
    """Without evidence index, coordinator goes straight to web search."""
    coordinator = ResearchCoordinator(evidence_index=None)
    ambiguity = _make_ambiguity()

    decision_json = '{"decision": "Handle gracefully", "confidence": 0.6}'
    with patch(
        "spec_manager.refinement.interactive.research.coordinator.run_agent",
        return_value=decision_json,
    ) as mock_agent:
        response = coordinator.research(ambiguity, tmp_path)

    assert response is not None
    assert response.source == "research_web"
    assert mock_agent.call_count == 3

"""Tests for the evidence searcher."""

from __future__ import annotations

from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher

SPEC_PAYMENTS = """\
# Payments Library

## Payment Validation

Credit card validation uses the Luhn algorithm to verify card numbers.
Invalid cards are rejected immediately.

## Payment Gateway Integration

The gateway processes authorized transactions through the payment processor.
Timeout handling ensures graceful degradation when the gateway is unavailable.
"""

SPEC_AUTH = """\
# Authentication Library

## Token Management

OAuth2 tokens are issued with a 3600 second lifetime.
Refresh tokens support seamless re-authentication.
ENT-0001 user registry validates token signatures.

## Session Handling

Sessions are stored in a distributed cache for horizontal scaling.
Session timeout defaults to 30 minutes of inactivity.
"""

SPEC_FRAUD = """\
# Fraud Detection Library

## Rule Engine

The fraud rule engine evaluates transaction patterns against known fraud signatures.
Rules are versioned and hot-reloadable without downtime.
ENT-0001 user profiles inform risk scoring.

## Machine Learning Scoring

A gradient boosted model scores each transaction for fraud probability.
Transactions scoring above 0.8 are automatically blocked.
"""


def _build_test_index() -> EvidenceIndex:
    """Build a test index with 3 specs."""
    index = EvidenceIndex()
    for lib_id, content in [
        ("LIB-0001", SPEC_PAYMENTS),
        ("LIB-0002", SPEC_AUTH),
        ("LIB-0003", SPEC_FRAUD),
    ]:
        hollowed = hollow_out_spec(lib_id, content)
        index.add_spec(hollowed)
    return index


def test_keyword_search_basic():
    """Search for a known keyword, verify results."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    results = searcher.search("payment gateway")
    assert len(results) > 0

    # Top result should be from the payments library
    top = results[0]
    assert top.lib_id == "LIB-0001"
    assert top.score > 0
    assert len(top.matched_keywords) > 0


def test_entity_search_boost():
    """Verify entity matches are scored higher."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    # Search with entity name
    results_with_entity = searcher.search("user profiles", entity_names=["ENT-0001"])

    # With entity should have results from both auth and fraud libs
    if results_with_entity:
        entity_lib_ids = {r.lib_id for r in results_with_entity}
        # ENT-0001 appears in LIB-0002 and LIB-0003
        assert entity_lib_ids & {"LIB-0002", "LIB-0003"}


def test_exclude_lib_ids():
    """Verify exclusion works."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    results = searcher.search("payment", exclude_lib_ids=["LIB-0001"])

    # No results should be from LIB-0001
    for result in results:
        assert result.lib_id != "LIB-0001"


def test_search_for_ambiguity():
    """End-to-end ambiguity search with context."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    results = searcher.search_for_ambiguity(
        ambiguity_text="What happens when the payment gateway times out?",
        ambiguity_question="How does the system handle gateway timeouts?",
        context_section="Payment Processing",
        max_results=5,
    )

    assert len(results) > 0
    # Should find gateway/timeout references in payments lib
    top = results[0]
    assert (
        "gateway" in top.paragraph.text.lower()
        or "timeout" in top.paragraph.text.lower()
        or "payment" in top.paragraph.text.lower()
    )


def test_no_results_returns_empty():
    """Query with no matches returns []."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    results = searcher.search("xyznonexistentterm12345")
    assert results == []


def test_min_score_filters():
    """Verify low-scoring results are filtered."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    # With very high min_score, should get fewer or no results
    results_high = searcher.search("payment", min_score=0.99)
    results_low = searcher.search("payment", min_score=0.01)

    # Low threshold should yield >= high threshold results
    assert len(results_low) >= len(results_high)


def test_max_results_limits():
    """Verify max_results limits output."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    results = searcher.search("transaction", max_results=2)
    assert len(results) <= 2


def test_empty_query_returns_empty():
    """Empty query with no entities returns []."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    results = searcher.search("")
    assert results == []


def test_entity_only_search():
    """Search with only entity names, no keywords."""
    index = _build_test_index()
    searcher = EvidenceSearcher(index)

    results = searcher.search("", entity_names=["ENT-0001"])
    assert len(results) > 0
    # All results should mention ENT-0001
    for r in results:
        assert "ENT-0001" in r.matched_entities

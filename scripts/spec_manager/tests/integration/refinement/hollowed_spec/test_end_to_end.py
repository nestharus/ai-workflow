"""End-to-end integration tests for the hollowed-out spec evidence store."""

from __future__ import annotations

import json
from pathlib import Path

from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.research.evidence_store_researcher import (
    EvidenceStoreResearcher,
)

SPEC_A = """\
# Payment Processing Library

## Overview

This library handles all payment processing for the system.
It integrates with the payment gateway and manages transaction lifecycle.
The payment processor validates credit card numbers using the Luhn algorithm.

## Authentication

Users must authenticate via OAuth2 before initiating payments.
The authentication token is validated against ENT-0001 user registry.
Multi-factor authentication is required for amounts exceeding $1000.

## Transaction Flow

The transaction flow involves validation, authorization, and confirmation.
Each step logs to the audit trail referencing ENT-0002 audit store.

### Validation Rules

Credit card expiration dates must be in the future.
CVV codes must be exactly 3 or 4 digits.
Card numbers must pass the Luhn checksum algorithm.

### Gateway Integration

The payment gateway processes authorized transactions.
Timeout handling ensures graceful degradation when the gateway is unavailable.
Connection pooling limits concurrent gateway connections to 50.
"""

SPEC_B = """\
# Fraud Detection Library

## Rule Engine

The fraud rule engine evaluates transaction patterns against known fraud signatures.
Rules are versioned and hot-reloadable without service downtime.
ENT-0001 user profiles inform risk scoring decisions.

## Machine Learning Scoring

A gradient boosted model scores each transaction for fraud probability.
Transactions scoring above 0.8 are automatically blocked.
The model is retrained weekly using the latest transaction data.
"""

SPEC_C = """\
# Notification Library

## Email Notifications

Transaction completion emails are sent via the notification service.
Email templates support variable substitution using Mustache syntax.
ENT-0002 notification queue manages asynchronous delivery.

## SMS Alerts

Critical transaction alerts are sent via SMS gateway.
SMS rate limiting prevents exceeding carrier quotas.
"""


def test_full_pipeline_hollow_index_search():
    """Create a spec, hollow it, build index, search, verify results."""
    # Step 1: Hollow out specs
    hollowed_a = hollow_out_spec("LIB-0001", SPEC_A)
    hollowed_b = hollow_out_spec("LIB-0002", SPEC_B)
    hollowed_c = hollow_out_spec("LIB-0003", SPEC_C)

    assert len(hollowed_a.paragraphs) >= 5  # Multiple sections with paragraphs
    assert len(hollowed_a.keyword_index) >= 10  # Many keywords

    # Step 2: Build index
    index = EvidenceIndex()
    index.add_spec(hollowed_a)
    index.add_spec(hollowed_b)
    index.add_spec(hollowed_c)

    assert len(index.specs) == 3
    assert index.total_paragraphs > 0

    # Step 3: Search
    searcher = EvidenceSearcher(index)

    # Search for payment-related content
    results = searcher.search("payment gateway timeout")
    assert len(results) > 0
    # Top result should be from payments library
    assert results[0].lib_id == "LIB-0001"

    # Search for fraud-related content
    results = searcher.search("fraud detection machine learning")
    assert len(results) > 0
    assert results[0].lib_id == "LIB-0002"

    # Search with entity
    results = searcher.search("user registry", entity_names=["ENT-0001"])
    assert len(results) > 0
    # Should find results from both LIB-0001 and LIB-0002
    result_libs = {r.lib_id for r in results}
    assert "LIB-0001" in result_libs or "LIB-0002" in result_libs


def test_ambiguity_resolved_from_evidence_store(tmp_path: Path):
    """Full flow: detect ambiguity -> evidence store search -> SteeringResponse."""
    # Build index with payment spec
    index = EvidenceIndex()
    hollowed = hollow_out_spec("LIB-0001", SPEC_A)
    index.add_spec(hollowed)

    researcher = EvidenceStoreResearcher(index)

    ambiguity = Ambiguity(
        ambiguity_id="AMB-001",
        source_text="gateway timeout handling",
        source_location="spec.md::Payments",
        ambiguity_type="missing_condition",
        confidence=0.9,
        suggested_question="What happens when the payment gateway times out?",
    )

    response = researcher.research(ambiguity, tmp_path)

    assert response is not None
    assert response.source == "evidence_store"
    assert response.ambiguity_id == "AMB-001"
    # Response should contain gateway timeout information
    lower_text = response.response_text.lower()
    assert "gateway" in lower_text or "timeout" in lower_text or "payment" in lower_text


def test_ambiguity_not_resolved_creates_gap(tmp_path: Path):
    """Full flow: detect ambiguity -> evidence store returns None -> Gap created."""
    # Empty index - no answers available
    index = EvidenceIndex()
    researcher = EvidenceStoreResearcher(index)

    ambiguity = Ambiguity(
        ambiguity_id="AMB-002",
        source_text="database sharding strategy",
        source_location="spec.md::Infrastructure",
        ambiguity_type="missing_condition",
        confidence=0.85,
        suggested_question="How should the database be sharded for horizontal scaling?",
    )

    # Research should return None
    response = researcher.research(ambiguity, tmp_path)
    assert response is None

    # Flag as gap
    researcher.flag_as_spec_gap(ambiguity, tmp_path)

    # Verify gap was created
    gap_file = tmp_path / "evidence_store_gaps.json"
    assert gap_file.exists()

    data = json.loads(gap_file.read_text(encoding="utf-8"))
    assert len(data["gaps"]) == 1
    gap = data["gaps"][0]
    assert gap["gap_type"] == "ambiguity"
    assert (
        "sharding" in gap["description"].lower()
        or "scaling" in gap["description"].lower()
        or "database" in gap["description"].lower()
    )


def test_index_persistence_roundtrip(tmp_path: Path):
    """Verify index can be saved and loaded without data loss."""
    # Build index
    index = EvidenceIndex()
    for lib_id, content in [
        ("LIB-0001", SPEC_A),
        ("LIB-0002", SPEC_B),
        ("LIB-0003", SPEC_C),
    ]:
        hollowed = hollow_out_spec(lib_id, content)
        index.add_spec(hollowed)

    # Save
    index_path = tmp_path / "evidence_index.json"
    index.save(index_path)

    # Load
    loaded = EvidenceIndex.load(index_path)

    # Verify
    assert len(loaded.specs) == 3
    assert loaded.total_paragraphs == index.total_paragraphs
    assert loaded.total_keywords == index.total_keywords

    # Search on loaded index should work
    searcher = EvidenceSearcher(loaded)
    results = searcher.search("payment gateway")
    assert len(results) > 0
    assert results[0].lib_id == "LIB-0001"

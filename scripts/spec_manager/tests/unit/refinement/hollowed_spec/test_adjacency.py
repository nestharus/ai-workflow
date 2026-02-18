"""Tests for the proactive adjacency scanner."""

from __future__ import annotations

from spec_manager.core.evidence_index import EvidenceIndex
from spec_manager.refinement.hollowed_spec.adjacency import (
    AdjacencyScanner,
)
from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec

SPEC_PAYMENTS = """\
# Payments

## Payment Processing

The payment processor handles credit card transactions.
It calls validate_payment before authorizing amounts.
ENT-0001 payment config defines gateway settings.

The orders table stores transaction records.
Each transaction is linked to a user in the database.
"""

SPEC_FRAUD = """\
# Fraud Detection

## Risk Assessment

The fraud engine scores transactions using ENT-0001 user profiles.
It evaluates patterns against the orders table.
The validate_payment function is called by the fraud pre-check module.

## Anomaly Detection

Machine learning models detect anomalous transaction patterns.
Flagged transactions are stored in the review queue.
"""

SPEC_NOTIFICATIONS = """\
# Notifications

## Email Alerts

Transaction completion emails are sent via the notification service.
ENT-0002 notification config defines email templates.
"""


def _build_test_index() -> EvidenceIndex:
    """Build a test index with specs for adjacency testing."""
    index = EvidenceIndex()
    for lib_id, content in [
        ("LIB-0001", SPEC_PAYMENTS),
        ("LIB-0002", SPEC_FRAUD),
        ("LIB-0003", SPEC_NOTIFICATIONS),
    ]:
        hollowed = hollow_out_spec(lib_id, content)
        index.add_spec(hollowed)
    return index


def test_entity_co_occurrence_finds_related():
    """Two specs with shared entity refs, verify discovery."""
    index = _build_test_index()
    scanner = AdjacencyScanner(index)

    context = scanner.scan(
        lib_id="LIB-0001",
        section_heading="Payment Processing",
        section_content="Processing payments with ENT-0001 settings.",
    )

    # Should find LIB-0002 (fraud) which also references ENT-0001
    adjacent_libs = {r.lib_id for r in context.adjacent_evidence}
    assert "LIB-0002" in adjacent_libs
    # Should NOT include own library
    assert "LIB-0001" not in adjacent_libs


def test_store_touch_finds_shared_store():
    """Two sections describing same 'orders' table, verify match."""
    index = _build_test_index()
    scanner = AdjacencyScanner(index)

    context = scanner.scan(
        lib_id="LIB-0001",
        section_heading="Payment Processing",
        section_content="Writing records to the orders table in the database.",
    )

    # Should find LIB-0002 which also mentions orders table and database
    store_libs = {r.lib_id for r in context.store_touch_evidence}
    assert "LIB-0002" in store_libs


def test_call_graph_finds_function_reference():
    """Section mentions validate_payment, verify it finds another section defining that function."""
    index = _build_test_index()
    scanner = AdjacencyScanner(index)

    context = scanner.scan(
        lib_id="LIB-0001",
        section_heading="Payment Processing",
        section_content="The system calls validate_payment to check amounts.",
    )

    # Should find LIB-0002 which also mentions validate_payment
    call_libs = {r.lib_id for r in context.call_graph_evidence}
    assert "LIB-0002" in call_libs


def test_exclude_own_library():
    """Verify the scanner does not return results from the library being translated."""
    index = _build_test_index()
    scanner = AdjacencyScanner(index)

    context = scanner.scan(
        lib_id="LIB-0001",
        section_heading="Payment Processing",
        section_content="Payment processing with ENT-0001 and validate_payment and orders database.",
    )

    for result in context.all_evidence:
        assert result.lib_id != "LIB-0001"


def test_all_evidence_deduplicates():
    """Verify duplicate paragraphs across signals are deduplicated."""
    index = _build_test_index()
    scanner = AdjacencyScanner(index)

    context = scanner.scan(
        lib_id="LIB-0001",
        section_heading="Payment Processing",
        section_content="ENT-0001 validate_payment orders database",
    )

    all_evidence = context.all_evidence
    seen_keys = set()
    for result in all_evidence:
        key = f"{result.lib_id}:{result.paragraph.paragraph_id}"
        assert key not in seen_keys, f"Duplicate found: {key}"
        seen_keys.add(key)


def test_empty_index_returns_empty_context():
    """No indexed specs, verify empty AdjacencyContext."""
    index = EvidenceIndex()
    scanner = AdjacencyScanner(index)

    context = scanner.scan(
        lib_id="LIB-0001",
        section_heading="Test",
        section_content="Some content with ENT-0001.",
    )

    assert context.target_lib_id == "LIB-0001"
    assert context.target_section == "Test"
    assert len(context.adjacent_evidence) == 0
    assert len(context.store_touch_evidence) == 0
    assert len(context.call_graph_evidence) == 0
    assert len(context.all_evidence) == 0


def test_max_results_per_signal():
    """Verify max_results_per_signal limits each signal type."""
    index = _build_test_index()
    scanner = AdjacencyScanner(index)

    context = scanner.scan(
        lib_id="LIB-0001",
        section_heading="Payment Processing",
        section_content="ENT-0001 validate_payment orders database",
        max_results_per_signal=1,
    )

    assert len(context.adjacent_evidence) <= 1
    assert len(context.store_touch_evidence) <= 1
    assert len(context.call_graph_evidence) <= 1

"""Tests for the evidence index."""

from __future__ import annotations

from pathlib import Path

from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex

SPEC_A = """\
# Library A

## Authentication

Users authenticate via OAuth2 tokens with ENT-0001 user registry.
Tokens expire after 3600 seconds.

## Authorization

Role-based access control using permission matrix.
Administrators can manage all resources.
"""

SPEC_B = """\
# Library B

## Payment Processing

Payments are processed through the payment gateway.
Credit card validation uses Luhn algorithm.
References ENT-0001 for user identity verification.

## Fraud Detection

Fraud rules evaluate transaction patterns.
Machine learning model scores each transaction.
Suspicious transactions are flagged for review.
"""

SPEC_C = """\
# Library C

## Notifications

Email and SMS notifications for transaction events.
Notification templates use the Mustache rendering engine.
ENT-0002 notification queue manages delivery.
"""


def _build_index_with_specs(*specs: tuple[str, str]) -> EvidenceIndex:
    """Helper to build an index from (lib_id, content) pairs."""
    index = EvidenceIndex()
    for lib_id, content in specs:
        hollowed = hollow_out_spec(lib_id, content)
        index.add_spec(hollowed)
    return index


def test_build_index_from_single_spec():
    """Build index, verify keyword and entity entries."""
    index = _build_index_with_specs(("LIB-0001", SPEC_A))

    assert "LIB-0001" in index.specs
    assert index.total_paragraphs > 0
    assert index.total_keywords > 0

    # Keyword index should have authentication-related terms
    assert (
        "authenticate" in index.global_keyword_index
        or "authentication" in index.global_keyword_index
    )

    # Entity index should have ENT-0001
    assert "ENT-0001" in index.global_entity_index
    entries = index.global_entity_index["ENT-0001"]
    assert all(lib_id == "LIB-0001" for lib_id, _ in entries)


def test_build_index_from_multiple_specs():
    """Verify cross-library search works."""
    index = _build_index_with_specs(
        ("LIB-0001", SPEC_A),
        ("LIB-0002", SPEC_B),
        ("LIB-0003", SPEC_C),
    )

    assert len(index.specs) == 3
    assert index.total_paragraphs > 0

    # ENT-0001 should appear in both LIB-0001 and LIB-0002
    ent_entries = index.global_entity_index.get("ENT-0001", [])
    lib_ids = {lid for lid, _ in ent_entries}
    assert "LIB-0001" in lib_ids
    assert "LIB-0002" in lib_ids

    # ENT-0002 should only be in LIB-0003
    ent2_entries = index.global_entity_index.get("ENT-0002", [])
    lib_ids_2 = {lid for lid, _ in ent2_entries}
    assert "LIB-0003" in lib_ids_2


def test_remove_and_rebuild():
    """Remove a spec, verify its entries are gone."""
    index = _build_index_with_specs(
        ("LIB-0001", SPEC_A),
        ("LIB-0002", SPEC_B),
    )

    assert "LIB-0001" in index.specs
    assert "LIB-0002" in index.specs

    # Remove LIB-0001
    index.remove_spec("LIB-0001")

    assert "LIB-0001" not in index.specs
    assert "LIB-0002" in index.specs

    # ENT-0001 should still exist (from LIB-0002) but no LIB-0001 entries
    ent_entries = index.global_entity_index.get("ENT-0001", [])
    lib_ids = {lid for lid, _ in ent_entries}
    assert "LIB-0001" not in lib_ids
    assert "LIB-0002" in lib_ids

    # Keywords unique to LIB-0001 should be gone
    for _kw, entries in index.global_keyword_index.items():
        for lid, _ in entries:
            assert lid != "LIB-0001"


def test_index_persistence_roundtrip(tmp_path: Path):
    """Save and load, verify equality."""
    index = _build_index_with_specs(
        ("LIB-0001", SPEC_A),
        ("LIB-0002", SPEC_B),
    )

    index_path = tmp_path / "index.json"
    index.save(index_path)

    loaded = EvidenceIndex.load(index_path)

    assert set(loaded.specs.keys()) == set(index.specs.keys())
    assert loaded.total_paragraphs == index.total_paragraphs
    assert loaded.total_keywords == index.total_keywords
    assert loaded.total_entities == index.total_entities

    # Verify keyword index equality
    assert set(loaded.global_keyword_index.keys()) == set(index.global_keyword_index.keys())

    # Verify entity index equality
    assert set(loaded.global_entity_index.keys()) == set(index.global_entity_index.keys())


def test_load_nonexistent_path(tmp_path: Path):
    """Loading from a nonexistent path returns empty index."""
    index = EvidenceIndex.load(tmp_path / "nonexistent.json")
    assert len(index.specs) == 0
    assert index.total_paragraphs == 0


def test_add_spec_replaces_existing():
    """Adding a spec with same lib_id replaces existing."""
    index = EvidenceIndex()

    hollowed1 = hollow_out_spec("LIB-0001", SPEC_A)
    index.add_spec(hollowed1)

    hollowed2 = hollow_out_spec("LIB-0001", SPEC_B)
    index.add_spec(hollowed2)

    # Should have replaced, not accumulated
    assert len(index.specs) == 1
    assert index.specs["LIB-0001"].spec_hash == hollowed2.spec_hash

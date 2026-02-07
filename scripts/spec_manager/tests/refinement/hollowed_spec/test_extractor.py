"""Tests for the hollow-out extractor pipeline."""

from __future__ import annotations

from spec_manager.refinement.hollowed_spec.extractor import (
    _classify_paragraph,
    _extract_entity_refs,
    _extract_keywords,
    hollow_out_spec,
)
from spec_manager.schemas.hollowed_spec import ParagraphKind


SAMPLE_SPEC = """\
# Payment Processing Library

## Overview

This library handles all payment processing for the system.
It integrates with the payment gateway and manages transaction lifecycle.

The payment processor validates credit card numbers and applies
fraud detection rules before authorizing transactions.

## Details

### Authentication

Users must authenticate via OAuth2 before initiating payments.
The authentication token is validated against ENT-0001 user registry.

- Token lifetime: 3600 seconds
- Refresh tokens supported
- Multi-factor authentication required for amounts > $1000

### Transaction Flow

The transaction flow involves multiple steps:

1. Validate payment method
2. Check fraud rules
3. Authorize with gateway
4. Confirm transaction

Each step logs to the audit trail referencing ENT-0002 audit store.

```python
def process_payment(amount, method):
    validate(method)
    check_fraud(amount)
    return authorize(amount, method)
```

## Error Handling

When a transaction fails, the system retries up to 3 times.
Failed transactions are logged to ENT-0001 and ENT-0002 stores.
"""


def test_hollow_out_basic_spec():
    """Parse a simple spec with sections, verify hierarchy and paragraph extraction."""
    result = hollow_out_spec("LIB-0001", SAMPLE_SPEC)

    assert result.lib_id == "LIB-0001"
    assert result.spec_hash  # non-empty hash
    assert len(result.sections) >= 2  # At least Overview + Details or more
    assert len(result.paragraphs) > 0

    # Verify section hierarchy
    headings = [s.heading for s in result.sections]
    assert "Payment Processing Library" in headings
    assert "Overview" in headings
    assert "Details" in headings
    assert "Authentication" in headings
    assert "Transaction Flow" in headings
    assert "Error Handling" in headings

    # Verify child relationships
    details_section = next(s for s in result.sections if s.heading == "Details")
    assert len(details_section.child_section_ids) == 2  # Authentication, Transaction Flow


def test_paragraph_classification():
    """Verify prose, bullet list, code block, and table detection."""
    assert _classify_paragraph("This is a simple paragraph.") == ParagraphKind.PROSE

    assert (
        _classify_paragraph("- item 1\n- item 2\n- item 3")
        == ParagraphKind.BULLET_LIST
    )

    assert (
        _classify_paragraph("```python\ndef foo():\n    pass\n```")
        == ParagraphKind.CODE_BLOCK
    )

    assert (
        _classify_paragraph(
            "| Name | Value |\n| --- | --- |\n| foo | bar |"
        )
        == ParagraphKind.TABLE
    )

    assert (
        _classify_paragraph("1. First\n2. Second\n3. Third")
        == ParagraphKind.BULLET_LIST
    )


def test_keyword_extraction():
    """Verify stop-word filtering and meaningful keyword extraction."""
    text = "The payment processor validates credit card numbers and applies fraud detection"
    keywords = _extract_keywords(text)

    assert "payment" in keywords
    assert "processor" in keywords
    assert "validates" in keywords
    assert "credit" in keywords
    assert "fraud" in keywords
    assert "detection" in keywords

    # Stop words should be excluded
    assert "the" not in keywords
    assert "and" not in keywords

    # Short words (< 3 chars) excluded
    short_kw = _extract_keywords("it is a go to x y")
    assert len(short_kw) == 0


def test_entity_ref_extraction():
    """Verify ENT-#### pattern extraction from text."""
    text = "References ENT-0001 user registry and ENT-0002 audit store. Also ENT-0001 again."
    refs = _extract_entity_refs(text)

    assert refs == ["ENT-0001", "ENT-0002"]  # sorted, deduplicated

    # No entities
    assert _extract_entity_refs("No entity references here") == []


def test_spec_hash_changes_on_content_change():
    """Verify spec_hash differs for different content."""
    result1 = hollow_out_spec("LIB-0001", "# Spec A\nContent A")
    result2 = hollow_out_spec("LIB-0001", "# Spec B\nContent B")
    result3 = hollow_out_spec("LIB-0001", "# Spec A\nContent A")

    assert result1.spec_hash != result2.spec_hash
    assert result1.spec_hash == result3.spec_hash  # Same content = same hash


def test_empty_spec_produces_empty_hollowed_spec():
    """Edge case for empty input."""
    result = hollow_out_spec("LIB-0001", "")

    assert result.lib_id == "LIB-0001"
    assert result.spec_hash  # Still has a hash (of empty string)
    assert len(result.sections) == 0
    assert len(result.paragraphs) == 0
    assert len(result.keyword_index) == 0
    assert len(result.entity_index) == 0


def test_keyword_index_populated():
    """Verify keyword_index is populated as inverted map."""
    result = hollow_out_spec("LIB-0001", SAMPLE_SPEC)

    assert len(result.keyword_index) > 0
    # Payment should appear in multiple paragraphs
    assert "payment" in result.keyword_index
    payment_para_ids = result.keyword_index["payment"]
    assert len(payment_para_ids) >= 1

    # Each paragraph_id should exist in paragraphs dict
    for para_id in payment_para_ids:
        assert para_id in result.paragraphs


def test_entity_index_populated():
    """Verify entity_index captures all ENT-#### references."""
    result = hollow_out_spec("LIB-0001", SAMPLE_SPEC)

    assert "ENT-0001" in result.entity_index
    assert "ENT-0002" in result.entity_index

    # ENT-0001 appears in Authentication and Error Handling
    ent_0001_paras = result.entity_index["ENT-0001"]
    assert len(ent_0001_paras) >= 2


def test_paragraph_line_numbers():
    """Verify paragraph line numbers are set correctly."""
    result = hollow_out_spec("LIB-0001", SAMPLE_SPEC)

    for para_id, para in result.paragraphs.items():
        assert para.line_start >= 1
        assert para.line_end >= para.line_start


def test_section_ids_unique():
    """Verify all section IDs are unique."""
    result = hollow_out_spec("LIB-0001", SAMPLE_SPEC)

    section_ids = [s.section_id for s in result.sections]
    assert len(section_ids) == len(set(section_ids))


def test_paragraph_ids_unique():
    """Verify all paragraph IDs are unique."""
    result = hollow_out_spec("LIB-0001", SAMPLE_SPEC)

    para_ids = list(result.paragraphs.keys())
    assert len(para_ids) == len(set(para_ids))

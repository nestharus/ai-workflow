"""Tests for TagIndexDelta schema (CON-0019).

Tests:
- test_tag_item_validation: TagItem validation
- test_tag_relation_basic: TagRelation creation
- test_tag_index_delta_operations: Delta operations
"""

import pytest
from spec_manager.schemas.tag_delta import (
    TagIndexDelta,
    TagItem,
    TagRelation,
)


class TestTagItem:
    """Test TagItem model."""

    def test_new_item_requires_evidence(self) -> None:
        """Test new items require evidence_atom_ids."""
        with pytest.raises(ValueError, match="evidence_atom_ids"):
            TagItem(
                local_id="item_1",
                kind="REQ",
                lib_id="LIB-0001",
                title="Test",
                body="Test body",
                # No existing_elem_id and no evidence_atom_ids
            )

    def test_new_item_with_evidence(self) -> None:
        """Test new items work with evidence."""
        item = TagItem(
            local_id="item_1",
            kind="REQ",
            lib_id="LIB-0001",
            title="Test Requirement",
            body="This is a test requirement.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0001"],
        )
        assert item.local_id == "item_1"
        assert item.kind == "REQ"
        assert item.existing_elem_id is None

    def test_existing_item_no_evidence_required(self) -> None:
        """Test existing items don't require evidence."""
        item = TagItem(
            local_id="ref_1",
            existing_elem_id="REQ-LIB-0001-0001",
            kind="REQ",
            lib_id="LIB-0001",
            title="Existing Requirement",
            body="Reference to existing.",
            # No evidence_atom_ids needed for references
        )
        assert item.existing_elem_id == "REQ-LIB-0001-0001"

    def test_item_with_all_fields(self) -> None:
        """Test item with all fields populated."""
        item = TagItem(
            local_id="full_item",
            existing_elem_id=None,
            kind="ALG",
            lib_id="LIB-0002",
            evidence_atom_ids=["ATOM-1", "ATOM-2"],
            title="Algorithm Item",
            body="Algorithm description.",
        )
        assert len(item.evidence_atom_ids) == 2


class TestTagRelation:
    """Test TagRelation model."""

    def test_basic_relation(self) -> None:
        """Test basic relation creation."""
        relation = TagRelation(
            from_local_id="item_1",
            to_local_id="item_2",
            relation_type="DEPENDS_ON",
        )
        assert relation.from_local_id == "item_1"
        assert relation.to_local_id == "item_2"
        assert relation.relation_type == "DEPENDS_ON"
        assert relation.evidence_atom_ids == []

    def test_relation_with_evidence(self) -> None:
        """Test relation with evidence atoms."""
        relation = TagRelation(
            from_local_id="req_1",
            to_local_id="alg_1",
            relation_type="IMPLEMENTS",
            evidence_atom_ids=["ATOM-1", "ATOM-2"],
        )
        assert len(relation.evidence_atom_ids) == 2


class TestTagIndexDelta:
    """Test TagIndexDelta model."""

    def test_empty_delta(self) -> None:
        """Test creating empty delta."""
        delta = TagIndexDelta()
        assert delta.items == []
        assert delta.relations == []
        assert delta.lib_id == ""

    def test_delta_with_items(self) -> None:
        """Test delta with items."""
        item1 = TagItem(
            local_id="item_1",
            kind="REQ",
            lib_id="LIB-0001",
            title="First",
            body="First item",
            evidence_atom_ids=["ATOM-1"],
        )
        item2 = TagItem(
            local_id="item_2",
            kind="REQ",
            lib_id="LIB-0001",
            title="Second",
            body="Second item",
            evidence_atom_ids=["ATOM-2"],
        )

        delta = TagIndexDelta(
            items=[item1, item2],
            lib_id="LIB-0001",
        )

        assert len(delta.items) == 2

    def test_get_item_by_local_id(self) -> None:
        """Test get_item_by_local_id method."""
        item1 = TagItem(
            local_id="req_1",
            kind="REQ",
            lib_id="LIB-0001",
            title="Requirement",
            body="Body",
            evidence_atom_ids=["ATOM-1"],
        )
        delta = TagIndexDelta(items=[item1])

        found = delta.get_item_by_local_id("req_1")
        assert found is not None
        assert found.title == "Requirement"

        not_found = delta.get_item_by_local_id("unknown")
        assert not_found is None

    def test_get_local_ids(self) -> None:
        """Test get_local_ids method."""
        items = [
            TagItem(
                local_id=f"item_{i}",
                kind="REQ",
                lib_id="LIB-0001",
                title=f"Item {i}",
                body=f"Body {i}",
                evidence_atom_ids=["ATOM-1"],
            )
            for i in range(3)
        ]
        delta = TagIndexDelta(items=items)

        local_ids = delta.get_local_ids()
        assert local_ids == {"item_0", "item_1", "item_2"}

    def test_validate_relation_references_valid(self) -> None:
        """Test validate_relation_references with valid references."""
        items = [
            TagItem(
                local_id="item_1",
                kind="REQ",
                lib_id="LIB-0001",
                title="First",
                body="Body",
                evidence_atom_ids=["ATOM-1"],
            ),
            TagItem(
                local_id="item_2",
                kind="REQ",
                lib_id="LIB-0001",
                title="Second",
                body="Body",
                evidence_atom_ids=["ATOM-2"],
            ),
        ]
        relations = [
            TagRelation(
                from_local_id="item_1",
                to_local_id="item_2",
                relation_type="DEPENDS_ON",
            )
        ]
        delta = TagIndexDelta(items=items, relations=relations)

        errors = delta.validate_relation_references()
        assert errors == []

    def test_validate_relation_references_invalid(self) -> None:
        """Test validate_relation_references with invalid references."""
        items = [
            TagItem(
                local_id="item_1",
                kind="REQ",
                lib_id="LIB-0001",
                title="First",
                body="Body",
                evidence_atom_ids=["ATOM-1"],
            ),
        ]
        relations = [
            TagRelation(
                from_local_id="item_1",
                to_local_id="item_999",  # Does not exist
                relation_type="DEPENDS_ON",
            )
        ]
        delta = TagIndexDelta(items=items, relations=relations)

        errors = delta.validate_relation_references()
        assert len(errors) == 1
        assert "item_999" in errors[0]

    def test_serialization_roundtrip(self) -> None:
        """Test serialization and deserialization."""
        items = [
            TagItem(
                local_id="item_1",
                kind="REQ",
                lib_id="LIB-0001",
                title="Requirement",
                body="Body text",
                evidence_atom_ids=["ATOM-1"],
            )
        ]
        relations = [
            TagRelation(
                from_local_id="item_1",
                to_local_id="item_1",  # Self-reference
                relation_type="OVERLAPS",
            )
        ]
        delta = TagIndexDelta(items=items, relations=relations, lib_id="LIB-0001")

        data = delta.model_dump()
        restored = TagIndexDelta.model_validate(data)

        assert len(restored.items) == 1
        assert len(restored.relations) == 1
        assert restored.lib_id == "LIB-0001"

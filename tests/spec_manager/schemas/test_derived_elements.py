"""Tests for derived element schemas (DS-SPEC-0001, DS-SPEC-0004).

Tests:
- test_elem_id_format: Element ID format validation
- test_rejection_without_evidence: CON-0005 compliance
- test_relation_edge_validation: RelationEdge validation
- test_kind_matches_prefix: Kind must match elem_id prefix
"""

import pytest

from spec_manager.schemas.derived_elements import (
    DerivedElement,
    RelationEdge,
    allocate_element_id,
    validate_element_references,
)


class TestRelationEdge:
    """Test RelationEdge model."""

    def test_valid_relation_edge(self) -> None:
        """Test valid relation edge creation."""
        edge = RelationEdge(
            from_id="REQ-LIB-0001-0001",
            to_id="REQ-LIB-0001-0002",
            relation_type="DEPENDS_ON",
            evidence_atom_ids=["ATOM-F0001-R0001-L0010"],
            confidence=0.95,
        )
        assert edge.from_id == "REQ-LIB-0001-0001"
        assert edge.to_id == "REQ-LIB-0001-0002"
        assert edge.relation_type == "DEPENDS_ON"
        assert len(edge.evidence_atom_ids) == 1

    def test_all_relation_types(self) -> None:
        """Test all relation types are valid."""
        relation_types = ["DEPENDS_ON", "REFINES", "CONTRADICTS", "OVERLAPS", "IMPLEMENTS"]
        for rel_type in relation_types:
            edge = RelationEdge(
                from_id="REQ-LIB-0001-0001",
                to_id="REQ-LIB-0001-0002",
                relation_type=rel_type,  # type: ignore[arg-type]
            )
            assert edge.relation_type == rel_type

    def test_relation_edge_default_confidence(self) -> None:
        """Test default confidence is 1.0."""
        edge = RelationEdge(
            from_id="ALG-LIB-0001-0001",
            to_id="DS-LIB-0001-0001",
            relation_type="IMPLEMENTS",
        )
        assert edge.confidence == 1.0

    def test_relation_edge_invalid_from_id(self) -> None:
        """Test invalid from_id raises error."""
        with pytest.raises(ValueError, match="Element ID must match"):
            RelationEdge(
                from_id="INVALID-ID",
                to_id="REQ-LIB-0001-0001",
                relation_type="DEPENDS_ON",
            )

    def test_relation_edge_invalid_to_id(self) -> None:
        """Test invalid to_id raises error."""
        with pytest.raises(ValueError, match="Element ID must match"):
            RelationEdge(
                from_id="REQ-LIB-0001-0001",
                to_id="BADID",
                relation_type="DEPENDS_ON",
            )


class TestDerivedElement:
    """Test DerivedElement model."""

    def test_valid_requirement_element(self) -> None:
        """Test valid requirement element creation."""
        elem = DerivedElement(
            elem_id="REQ-LIB-0001-0001",
            kind="REQ",
            lib_id="LIB-0001",
            title="User Authentication",
            body="The system must authenticate users before granting access.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0010", "ATOM-F0001-R0001-L0011"],
            confidence=0.95,
            status="ACTIVE",
        )
        assert elem.elem_id == "REQ-LIB-0001-0001"
        assert elem.kind == "REQ"
        assert elem.lib_id == "LIB-0001"
        assert len(elem.evidence_atom_ids) == 2
        assert elem.status == "ACTIVE"

    def test_valid_flow_element(self) -> None:
        """Test valid flow element creation."""
        elem = DerivedElement(
            elem_id="FLOW-LIB-0002-01",
            kind="FLOW",
            lib_id="LIB-0002",
            title="Login Flow",
            body="User enters credentials, system validates, returns token.",
            evidence_atom_ids=["ATOM-F0002-R0001-L0020"],
        )
        assert elem.elem_id == "FLOW-LIB-0002-01"
        assert elem.kind == "FLOW"

    def test_valid_decision_element(self) -> None:
        """Test valid decision element creation."""
        elem = DerivedElement(
            elem_id="DEC-LIB-0001-0001",
            kind="DEC",
            lib_id="LIB-0001",
            title="Use JWT for authentication",
            body="JWT tokens provide stateless authentication.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0015"],
            status="DRAFT",
        )
        assert elem.kind == "DEC"
        assert elem.status == "DRAFT"

    def test_valid_algorithm_element(self) -> None:
        """Test valid algorithm element creation."""
        elem = DerivedElement(
            elem_id="ALG-LIB-0003-0001",
            kind="ALG",
            lib_id="LIB-0003",
            title="Token Validation",
            body="Validate JWT signature and expiration.",
            evidence_atom_ids=["ATOM-F0003-R0001-L0001"],
        )
        assert elem.kind == "ALG"

    def test_valid_data_structure_element(self) -> None:
        """Test valid data structure element creation."""
        elem = DerivedElement(
            elem_id="DS-LIB-0001-0001",
            kind="DS",
            lib_id="LIB-0001",
            title="UserCredentials",
            body="Structure containing username and hashed password.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0030"],
        )
        assert elem.kind == "DS"

    def test_rejection_without_evidence_atom_ids(self) -> None:
        """Test CON-0005: elements without evidence are rejected."""
        with pytest.raises(ValueError, match="must cite at least one evidence atom"):
            DerivedElement(
                elem_id="REQ-LIB-0001-0001",
                kind="REQ",
                lib_id="LIB-0001",
                title="Missing Evidence",
                body="This element has no evidence.",
                evidence_atom_ids=[],  # Empty - violates CON-0005
            )

    def test_rejection_empty_list_evidence(self) -> None:
        """Test rejection of empty evidence_atom_ids list."""
        with pytest.raises(ValueError, match="CON-0005"):
            DerivedElement(
                elem_id="INV-LIB-0001-0001",
                kind="INV",
                lib_id="LIB-0001",
                title="Test",
                body="Test body",
                evidence_atom_ids=[],
            )

    def test_invalid_elem_id_format(self) -> None:
        """Test invalid elem_id format raises error."""
        with pytest.raises(ValueError, match="elem_id must match"):
            DerivedElement(
                elem_id="INVALID-0001",
                kind="REQ",
                lib_id="LIB-0001",
                title="Test",
                body="Test",
                evidence_atom_ids=["ATOM-1"],
            )

    def test_invalid_lib_id_format(self) -> None:
        """Test invalid lib_id format raises error."""
        with pytest.raises(ValueError, match="lib_id must match"):
            DerivedElement(
                elem_id="REQ-LIB-0001-0001",
                kind="REQ",
                lib_id="LIBRARY-0001",  # Wrong format
                title="Test",
                body="Test",
                evidence_atom_ids=["ATOM-1"],
            )

    def test_kind_must_match_elem_id_prefix(self) -> None:
        """Test that kind must match the elem_id prefix."""
        with pytest.raises(ValueError, match="does not match kind"):
            DerivedElement(
                elem_id="REQ-LIB-0001-0001",  # REQ prefix
                kind="FLOW",  # But kind is FLOW
                lib_id="LIB-0001",
                title="Mismatch",
                body="Kind and prefix mismatch",
                evidence_atom_ids=["ATOM-1"],
            )

    def test_element_with_relations(self) -> None:
        """Test element with relation edges."""
        relation = RelationEdge(
            from_id="REQ-LIB-0001-0001",
            to_id="REQ-LIB-0001-0002",
            relation_type="REFINES",
        )
        elem = DerivedElement(
            elem_id="REQ-LIB-0001-0001",
            kind="REQ",
            lib_id="LIB-0001",
            title="Refined Requirement",
            body="This refines another requirement.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0001"],
            relations=[relation],
        )
        assert len(elem.relations) == 1
        assert elem.relations[0].relation_type == "REFINES"

    def test_element_with_derived_from(self) -> None:
        """Test element with derived_from_elem_ids."""
        elem = DerivedElement(
            elem_id="REQ-LIB-0001-0002",
            kind="REQ",
            lib_id="LIB-0001",
            title="Derived Requirement",
            body="Derived from parent.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0010"],
            derived_from_elem_ids=["REQ-LIB-0001-0001"],
        )
        assert "REQ-LIB-0001-0001" in elem.derived_from_elem_ids

    def test_all_status_values_valid(self) -> None:
        """Test all status values are accepted."""
        statuses = ["DRAFT", "ACTIVE", "NON_AUTHORITATIVE", "QUARANTINED", "DEPRECATED"]
        for status in statuses:
            elem = DerivedElement(
                elem_id="REQ-LIB-0001-0001",
                kind="REQ",
                lib_id="LIB-0001",
                title="Test",
                body="Test",
                evidence_atom_ids=["ATOM-1"],
                status=status,  # type: ignore[arg-type]
            )
            assert elem.status == status

    def test_serialization_roundtrip(self) -> None:
        """Test serialization and deserialization."""
        elem = DerivedElement(
            elem_id="ALG-LIB-0001-0001",
            kind="ALG",
            lib_id="LIB-0001",
            title="Sort Algorithm",
            body="Merge sort implementation",
            evidence_atom_ids=["ATOM-F0001-R0001-L0001"],
            confidence=0.9,
            status="ACTIVE",
            derived_from_elem_ids=["REQ-LIB-0001-0001"],
            relations=[
                RelationEdge(
                    from_id="ALG-LIB-0001-0001",
                    to_id="DS-LIB-0001-0001",
                    relation_type="IMPLEMENTS",
                )
            ],
        )

        data = elem.model_dump()
        restored = DerivedElement.model_validate(data)

        assert restored.elem_id == elem.elem_id
        assert restored.confidence == 0.9
        assert len(restored.relations) == 1
        assert restored.relations[0].relation_type == "IMPLEMENTS"


class TestAllocateElementId:
    """Test allocate_element_id function."""

    def test_allocate_first_requirement(self) -> None:
        """Test allocating first requirement ID."""
        eid = allocate_element_id("REQ", "LIB-0001", set())
        assert eid == "REQ-LIB-0001-0001"

    def test_allocate_next_requirement(self) -> None:
        """Test allocating next requirement ID after existing ones."""
        existing = {"REQ-LIB-0001-0001", "REQ-LIB-0001-0002"}
        eid = allocate_element_id("REQ", "LIB-0001", existing)
        assert eid == "REQ-LIB-0001-0003"

    def test_allocate_flow_uses_2_digits(self) -> None:
        """Test that FLOW uses 2-digit sequence."""
        eid = allocate_element_id("FLOW", "LIB-0002", set())
        assert eid == "FLOW-LIB-0002-01"

    def test_allocate_different_library(self) -> None:
        """Test allocation for different library."""
        existing = {"REQ-LIB-0001-0001", "REQ-LIB-0001-0002"}
        eid = allocate_element_id("REQ", "LIB-0002", existing)
        # Different library, so starts at 0001
        assert eid == "REQ-LIB-0002-0001"

    def test_allocate_different_kinds_independent(self) -> None:
        """Test different kinds have independent sequences."""
        existing = {"REQ-LIB-0001-0005", "ALG-LIB-0001-0003"}
        req_id = allocate_element_id("REQ", "LIB-0001", existing)
        alg_id = allocate_element_id("ALG", "LIB-0001", existing)
        ds_id = allocate_element_id("DS", "LIB-0001", existing)

        assert req_id == "REQ-LIB-0001-0006"
        assert alg_id == "ALG-LIB-0001-0004"
        assert ds_id == "DS-LIB-0001-0001"

    def test_allocate_invalid_lib_id(self) -> None:
        """Test allocation with invalid lib_id raises error."""
        with pytest.raises(ValueError, match="Invalid lib_id"):
            allocate_element_id("REQ", "INVALID", set())


class TestValidateElementReferences:
    """Test validate_element_references function."""

    def test_valid_references(self) -> None:
        """Test element with valid references."""
        elem = DerivedElement(
            elem_id="REQ-LIB-0001-0002",
            kind="REQ",
            lib_id="LIB-0001",
            title="Child Requirement",
            body="Derives from parent",
            evidence_atom_ids=["ATOM-1"],
            derived_from_elem_ids=["REQ-LIB-0001-0001"],
        )
        valid_ids = {"REQ-LIB-0001-0001", "REQ-LIB-0001-0002"}

        errors = validate_element_references(elem, valid_ids)
        assert errors == []

    def test_invalid_derived_from_reference(self) -> None:
        """Test element with invalid derived_from reference."""
        elem = DerivedElement(
            elem_id="REQ-LIB-0001-0002",
            kind="REQ",
            lib_id="LIB-0001",
            title="Child",
            body="Test",
            evidence_atom_ids=["ATOM-1"],
            derived_from_elem_ids=["REQ-LIB-0001-9999"],  # Does not exist
        )
        valid_ids = {"REQ-LIB-0001-0002"}

        errors = validate_element_references(elem, valid_ids)
        assert len(errors) == 1
        assert "unknown parent" in errors[0]

    def test_invalid_relation_references(self) -> None:
        """Test element with invalid relation references."""
        elem = DerivedElement(
            elem_id="REQ-LIB-0001-0001",
            kind="REQ",
            lib_id="LIB-0001",
            title="Test",
            body="Test",
            evidence_atom_ids=["ATOM-1"],
            relations=[
                RelationEdge(
                    from_id="REQ-LIB-0001-0001",
                    to_id="REQ-LIB-0001-9999",  # Does not exist
                    relation_type="DEPENDS_ON",
                )
            ],
        )
        valid_ids = {"REQ-LIB-0001-0001"}

        errors = validate_element_references(elem, valid_ids)
        assert len(errors) == 1
        assert "unknown to_id" in errors[0]

    def test_self_reference_allowed(self) -> None:
        """Test that self-references in relations are allowed."""
        elem = DerivedElement(
            elem_id="REQ-LIB-0001-0001",
            kind="REQ",
            lib_id="LIB-0001",
            title="Test",
            body="Test",
            evidence_atom_ids=["ATOM-1"],
            relations=[
                RelationEdge(
                    from_id="REQ-LIB-0001-0001",  # Self
                    to_id="REQ-LIB-0001-0001",  # Self
                    relation_type="OVERLAPS",
                )
            ],
        )
        valid_ids: set[str] = set()  # Even without being in valid_ids

        errors = validate_element_references(elem, valid_ids)
        assert errors == []

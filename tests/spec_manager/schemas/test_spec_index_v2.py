"""Tests for SpecIndexV2 schema (DS-SPEC-0003).

Tests:
- test_bidirectional_map_consistency: Maps are consistent
- test_serialization_roundtrip: JSON roundtrip
- test_backward_compatibility: Legacy format conversion
- test_query_methods: Lookup methods work correctly
"""

from pathlib import Path

import pytest

from spec_manager.schemas.derived_elements import DerivedElement, RelationEdge
from spec_manager.schemas.spec_index_v2 import (
    Library,
    SpecIndexV2,
    build_spec_index,
    convert_legacy_spec_index,
)


class TestLibrary:
    """Test Library model."""

    def test_valid_library(self) -> None:
        """Test valid library creation."""
        lib = Library(
            lib_id="LIB-0001",
            name="Authentication",
            description="User authentication system",
            stability_key="ENT:ENT-0001|ENT-0002",
            element_count=5,
        )
        assert lib.lib_id == "LIB-0001"
        assert lib.name == "Authentication"
        assert lib.element_count == 5

    def test_invalid_lib_id(self) -> None:
        """Test invalid lib_id raises error."""
        with pytest.raises(ValueError, match="LIB-####"):
            Library(lib_id="INVALID", name="Test")


class TestSpecIndexV2:
    """Test SpecIndexV2 model."""

    def test_empty_index(self) -> None:
        """Test creating empty index."""
        index = SpecIndexV2()
        assert index.schema_version == "2.0"
        assert index.libraries == []
        assert index.elements == {}
        assert index.atom_to_elements == {}
        assert index.element_to_atoms == {}

    def test_get_elements_for_atom(self) -> None:
        """Test get_elements_for_atom method."""
        index = SpecIndexV2(
            atom_to_elements={
                "ATOM-1": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002"],
                "ATOM-2": ["REQ-LIB-0001-0001"],
            }
        )

        elems = index.get_elements_for_atom("ATOM-1")
        assert len(elems) == 2
        assert "REQ-LIB-0001-0001" in elems

        elems = index.get_elements_for_atom("ATOM-UNKNOWN")
        assert elems == []

    def test_get_atoms_for_element(self) -> None:
        """Test get_atoms_for_element method."""
        index = SpecIndexV2(
            element_to_atoms={
                "REQ-LIB-0001-0001": ["ATOM-1", "ATOM-2", "ATOM-3"],
            }
        )

        atoms = index.get_atoms_for_element("REQ-LIB-0001-0001")
        assert len(atoms) == 3

        atoms = index.get_atoms_for_element("UNKNOWN")
        assert atoms == []

    def test_get_element(self) -> None:
        """Test get_element method."""
        index = SpecIndexV2(
            elements={
                "REQ-LIB-0001-0001": {
                    "elem_id": "REQ-LIB-0001-0001",
                    "kind": "REQ",
                    "title": "Test Requirement",
                }
            }
        )

        elem = index.get_element("REQ-LIB-0001-0001")
        assert elem is not None
        assert elem["title"] == "Test Requirement"

        elem = index.get_element("UNKNOWN")
        assert elem is None

    def test_get_library(self) -> None:
        """Test get_library method."""
        index = SpecIndexV2(
            libraries=[
                Library(lib_id="LIB-0001", name="Auth"),
                Library(lib_id="LIB-0002", name="Data"),
            ]
        )

        lib = index.get_library("LIB-0001")
        assert lib is not None
        assert lib.name == "Auth"

        lib = index.get_library("LIB-9999")
        assert lib is None

    def test_get_elements_by_library(self) -> None:
        """Test get_elements_by_library method."""
        index = SpecIndexV2(
            elements={
                "REQ-LIB-0001-0001": {"lib_id": "LIB-0001", "kind": "REQ"},
                "REQ-LIB-0001-0002": {"lib_id": "LIB-0001", "kind": "REQ"},
                "REQ-LIB-0002-0001": {"lib_id": "LIB-0002", "kind": "REQ"},
            }
        )

        lib1_elems = index.get_elements_by_library("LIB-0001")
        assert len(lib1_elems) == 2

        lib2_elems = index.get_elements_by_library("LIB-0002")
        assert len(lib2_elems) == 1

    def test_get_elements_by_kind(self) -> None:
        """Test get_elements_by_kind method."""
        index = SpecIndexV2(
            elements={
                "REQ-LIB-0001-0001": {"kind": "REQ"},
                "ALG-LIB-0001-0001": {"kind": "ALG"},
                "REQ-LIB-0001-0002": {"kind": "REQ"},
            }
        )

        reqs = index.get_elements_by_kind("REQ")
        assert len(reqs) == 2

        algs = index.get_elements_by_kind("ALG")
        assert len(algs) == 1

    def test_get_coverage_stats(self) -> None:
        """Test get_coverage_stats method."""
        index = SpecIndexV2(
            atom_to_elements={
                "ATOM-1": ["REQ-LIB-0001-0001"],
                "ATOM-2": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002"],
                "ATOM-3": [],  # Uncovered atom
            },
            element_to_atoms={
                "REQ-LIB-0001-0001": ["ATOM-1", "ATOM-2"],
                "REQ-LIB-0001-0002": ["ATOM-2"],
            },
            elements={
                "REQ-LIB-0001-0001": {},
                "REQ-LIB-0001-0002": {},
            },
        )

        stats = index.get_coverage_stats()
        assert stats["total_atoms"] == 3
        assert stats["total_elements"] == 2
        assert stats["covered_atoms"] == 2  # ATOM-3 has empty list

    def test_serialization_roundtrip(self) -> None:
        """Test JSON serialization roundtrip."""
        index = SpecIndexV2(
            libraries=[Library(lib_id="LIB-0001", name="Test")],
            elements={
                "REQ-LIB-0001-0001": {
                    "elem_id": "REQ-LIB-0001-0001",
                    "kind": "REQ",
                    "lib_id": "LIB-0001",
                    "title": "Test",
                    "body": "Body",
                    "evidence_atom_ids": ["ATOM-1"],
                }
            },
            atom_to_elements={"ATOM-1": ["REQ-LIB-0001-0001"]},
            element_to_atoms={"REQ-LIB-0001-0001": ["ATOM-1"]},
        )

        data = index.model_dump()
        restored = SpecIndexV2.model_validate(data)

        assert restored.schema_version == "2.0"
        assert len(restored.libraries) == 1
        assert "REQ-LIB-0001-0001" in restored.elements


class TestBuildSpecIndex:
    """Test build_spec_index function."""

    def test_build_from_elements(self) -> None:
        """Test building index from elements."""
        libraries = [Library(lib_id="LIB-0001", name="Test Library")]

        elements = [
            DerivedElement(
                elem_id="REQ-LIB-0001-0001",
                kind="REQ",
                lib_id="LIB-0001",
                title="First Requirement",
                body="Body 1",
                evidence_atom_ids=["ATOM-1", "ATOM-2"],
            ),
            DerivedElement(
                elem_id="REQ-LIB-0001-0002",
                kind="REQ",
                lib_id="LIB-0001",
                title="Second Requirement",
                body="Body 2",
                evidence_atom_ids=["ATOM-2", "ATOM-3"],
            ),
        ]

        index = build_spec_index(libraries, elements)

        # Check bidirectional maps
        assert "REQ-LIB-0001-0001" in index.atom_to_elements.get("ATOM-1", [])
        assert "REQ-LIB-0001-0001" in index.atom_to_elements.get("ATOM-2", [])
        assert "REQ-LIB-0001-0002" in index.atom_to_elements.get("ATOM-2", [])

        assert "ATOM-1" in index.element_to_atoms.get("REQ-LIB-0001-0001", [])
        assert "ATOM-2" in index.element_to_atoms.get("REQ-LIB-0001-0001", [])

        # Check element count updated
        lib = index.get_library("LIB-0001")
        assert lib is not None
        assert lib.element_count == 2

    def test_build_with_relations(self) -> None:
        """Test building index preserves relations."""
        libraries = [Library(lib_id="LIB-0001", name="Test")]

        elements = [
            DerivedElement(
                elem_id="REQ-LIB-0001-0001",
                kind="REQ",
                lib_id="LIB-0001",
                title="Requirement",
                body="Body",
                evidence_atom_ids=["ATOM-1"],
                relations=[
                    RelationEdge(
                        from_id="REQ-LIB-0001-0001",
                        to_id="REQ-LIB-0001-0002",
                        relation_type="DEPENDS_ON",
                    )
                ],
            ),
            DerivedElement(
                elem_id="REQ-LIB-0001-0002",
                kind="REQ",
                lib_id="LIB-0001",
                title="Another",
                body="Body 2",
                evidence_atom_ids=["ATOM-2"],
            ),
        ]

        index = build_spec_index(libraries, elements)

        assert len(index.relations) == 1
        assert index.relations[0]["relation_type"] == "DEPENDS_ON"

    def test_bidirectional_consistency(self) -> None:
        """Test bidirectional maps are consistent."""
        libraries = [Library(lib_id="LIB-0001", name="Test")]
        elements = [
            DerivedElement(
                elem_id="REQ-LIB-0001-0001",
                kind="REQ",
                lib_id="LIB-0001",
                title="Test",
                body="Body",
                evidence_atom_ids=["ATOM-1", "ATOM-2", "ATOM-3"],
            ),
        ]

        index = build_spec_index(libraries, elements)

        # Every atom in element_to_atoms should point back
        elem_id = "REQ-LIB-0001-0001"
        for atom_id in index.element_to_atoms[elem_id]:
            assert elem_id in index.atom_to_elements[atom_id]


class TestConvertLegacySpecIndex:
    """Test convert_legacy_spec_index function."""

    def test_convert_legacy_format(self) -> None:
        """Test converting legacy spec index format."""
        legacy_index = {
            "lib_id": "LIB-0001",
            "generated_at": "2024-01-15T10:30:00",
            "spec_path": "spec/requirements.md",
            "elements": [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "kind": "requirement",
                    "section": "Authentication",
                    "text": "Users must authenticate",
                    "citations": ["EVID-001", "EVID-002"],
                },
                {
                    "element_id": "REQ-LIB-0001-0002",
                    "kind": "requirement",
                    "section": "Authorization",
                    "text": "Users must be authorized",
                    "citations": ["EVID-002"],
                },
            ],
        }

        converted = convert_legacy_spec_index(legacy_index, "LIB-0001")

        assert converted.schema_version == "2.0"
        assert len(converted.libraries) == 1
        assert len(converted.elements) == 2

        # Check atom maps built from citations
        assert "REQ-LIB-0001-0001" in converted.atom_to_elements.get("EVID-001", [])
        assert "EVID-001" in converted.element_to_atoms.get("REQ-LIB-0001-0001", [])

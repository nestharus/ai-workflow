"""SpecIndexV2 schema compliant with DS-SPEC-0003.

This module defines the SpecIndexV2 schema with bidirectional atom-to-element
and element-to-atom maps for efficient traceability queries.

Design References:
- DS-SPEC-0003: SpecIndex with atom maps
- ALG-SPEC-0003: BuildSpecIndex
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from .validation_utils import LIB_ID_RE

if TYPE_CHECKING:
    from spec_manager.schemas.derived_elements import DerivedElement


class Library(BaseModel):
    """A library in the spec index (DS-DISC-0001).

    Attributes:
        lib_id: Unique library identifier (LIB-####)
        name: Display name for the library
        description: Description of the library's purpose
        stability_key: Key used for stable ID allocation
        element_count: Number of elements in this library
    """

    lib_id: str
    name: str
    description: str = ""
    stability_key: str = ""
    element_count: int = 0

    @field_validator("lib_id")
    @classmethod
    def validate_lib_id(cls, value: str) -> str:
        """Validate library ID format."""
        if not LIB_ID_RE.fullmatch(value):
            raise ValueError(f"lib_id must match LIB-#### format, got: {value}")
        return value


class SpecIndexV2(BaseModel):
    """Design-compliant spec index with bidirectional maps (DS-SPEC-0003).

    This schema provides efficient traceability between atoms and elements,
    supporting both "which elements cite this atom?" and "which atoms
    support this element?" queries.

    Attributes:
        schema_version: Schema version string
        libraries: List of libraries in the index
        elements: Dictionary mapping elem_id to DerivedElement data
        atom_to_elements: Mapping of atom_id to list of elem_ids
        element_to_atoms: Mapping of elem_id to list of atom_ids
        relations: List of relation edges (stored separately for queries)
        created_at: ISO8601 timestamp when index was created
    """

    schema_version: str = "2.0"
    libraries: list[Library] = Field(default_factory=list)
    elements: dict[str, dict] = Field(default_factory=dict)  # elem_id -> element data
    atom_to_elements: dict[str, list[str]] = Field(default_factory=dict)
    element_to_atoms: dict[str, list[str]] = Field(default_factory=dict)
    relations: list[dict] = Field(default_factory=list)  # RelationEdge dicts
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def get_elements_for_atom(self, atom_id: str) -> list[str]:
        """Get all element IDs that cite a specific atom.

        Args:
            atom_id: The atom ID to look up

        Returns:
            List of element IDs that cite this atom
        """
        return self.atom_to_elements.get(atom_id, [])

    def get_atoms_for_element(self, elem_id: str) -> list[str]:
        """Get all atom IDs that support a specific element.

        Args:
            elem_id: The element ID to look up

        Returns:
            List of atom IDs that support this element
        """
        return self.element_to_atoms.get(elem_id, [])

    def get_element(self, elem_id: str) -> dict | None:
        """Get element data by ID.

        Args:
            elem_id: The element ID to look up

        Returns:
            Element data dict if found, None otherwise
        """
        return self.elements.get(elem_id)

    def get_library(self, lib_id: str) -> Library | None:
        """Get a library by ID.

        Args:
            lib_id: The library ID to look up

        Returns:
            Library if found, None otherwise
        """
        for lib in self.libraries:
            if lib.lib_id == lib_id:
                return lib
        return None

    def get_elements_by_library(self, lib_id: str) -> list[dict]:
        """Get all elements belonging to a library.

        Args:
            lib_id: The library ID to filter by

        Returns:
            List of element data dicts for this library
        """
        return [elem for elem in self.elements.values() if elem.get("lib_id") == lib_id]

    def get_elements_by_kind(self, kind: str) -> list[dict]:
        """Get all elements of a specific kind.

        Args:
            kind: The element kind to filter by (REQ, FLOW, etc.)

        Returns:
            List of element data dicts of this kind
        """
        return [elem for elem in self.elements.values() if elem.get("kind") == kind]

    def get_coverage_stats(self) -> dict:
        """Get coverage statistics for the index.

        Returns:
            Dictionary with coverage statistics
        """
        total_atoms = len(self.atom_to_elements)
        total_elements = len(self.elements)
        covered_atoms = sum(1 for atoms in self.atom_to_elements.values() if atoms)

        return {
            "total_atoms": total_atoms,
            "total_elements": total_elements,
            "covered_atoms": covered_atoms,
            "coverage_ratio": covered_atoms / total_atoms if total_atoms > 0 else 0.0,
            "avg_elements_per_atom": (
                sum(len(elems) for elems in self.atom_to_elements.values()) / total_atoms
                if total_atoms > 0
                else 0.0
            ),
            "avg_atoms_per_element": (
                sum(len(atoms) for atoms in self.element_to_atoms.values()) / total_elements
                if total_elements > 0
                else 0.0
            ),
        }


def build_spec_index(
    libraries: list[Library],
    elements: list[DerivedElement],
) -> SpecIndexV2:
    """Build a SpecIndexV2 from libraries and elements (ALG-SPEC-0003).

    Constructs the bidirectional atom <-> element maps for efficient
    traceability queries.

    Args:
        libraries: List of Library objects
        elements: List of DerivedElement objects

    Returns:
        Populated SpecIndexV2 instance
    """
    # Build bidirectional maps
    atom_to_elements: dict[str, list[str]] = defaultdict(list)
    element_to_atoms: dict[str, list[str]] = {}
    elements_dict: dict[str, dict] = {}
    relations_list: list[dict] = []

    for elem in elements:
        # Store element data
        elem_data = elem.model_dump()
        elements_dict[elem.elem_id] = elem_data

        # Build element -> atoms map
        element_to_atoms[elem.elem_id] = list(elem.evidence_atom_ids)

        # Build atom -> elements map
        for atom_id in elem.evidence_atom_ids:
            atom_to_elements[atom_id].append(elem.elem_id)

        # Collect relations
        for relation in elem.relations:
            relations_list.append(relation.model_dump())

    # Update library element counts
    lib_counts: dict[str, int] = defaultdict(int)
    for elem_data in elements_dict.values():
        lib_id = elem_data.get("lib_id")
        if lib_id:
            lib_counts[lib_id] += 1

    updated_libraries = []
    for lib in libraries:
        updated_lib = Library(
            lib_id=lib.lib_id,
            name=lib.name,
            description=lib.description,
            stability_key=lib.stability_key,
            element_count=lib_counts.get(lib.lib_id, 0),
        )
        updated_libraries.append(updated_lib)

    return SpecIndexV2(
        libraries=updated_libraries,
        elements=elements_dict,
        atom_to_elements=dict(atom_to_elements),
        element_to_atoms=element_to_atoms,
        relations=relations_list,
    )


def convert_legacy_spec_index(
    legacy_index: dict,
    lib_id: str,
) -> SpecIndexV2:
    """Convert a legacy SpecIndex to SpecIndexV2 format.

    Args:
        legacy_index: Legacy spec index data
        lib_id: Library ID for the legacy index

    Returns:
        Converted SpecIndexV2 instance
    """
    # Extract legacy elements
    legacy_elements = legacy_index.get("elements", [])

    # Build minimal atom maps from legacy citations
    atom_to_elements: dict[str, list[str]] = defaultdict(list)
    element_to_atoms: dict[str, list[str]] = {}
    elements_dict: dict[str, dict] = {}

    for elem in legacy_elements:
        elem_id = elem.get("element_id")
        if not elem_id:
            continue

        # Convert legacy format to new format
        new_elem = {
            "elem_id": elem_id,
            "kind": elem.get("kind", "REQ").upper(),
            "lib_id": lib_id,
            "title": elem.get("section", ""),
            "body": elem.get("text", ""),
            "evidence_atom_ids": elem.get("citations", []),
            "confidence": 1.0,
            "status": "ACTIVE",
            "derived_from_elem_ids": [],
            "relations": [],
        }
        elements_dict[elem_id] = new_elem

        # Build maps from citations
        citations = elem.get("citations", [])
        element_to_atoms[elem_id] = citations
        for citation in citations:
            atom_to_elements[citation].append(elem_id)

    # Create library
    library = Library(
        lib_id=lib_id,
        name=legacy_index.get("spec_path", lib_id),
        description="Converted from legacy format",
        element_count=len(elements_dict),
    )

    return SpecIndexV2(
        libraries=[library],
        elements=elements_dict,
        atom_to_elements=dict(atom_to_elements),
        element_to_atoms=element_to_atoms,
        relations=[],
        created_at=legacy_index.get("generated_at", datetime.now(UTC).isoformat()),
    )

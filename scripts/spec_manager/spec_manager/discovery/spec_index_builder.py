"""Spec index builder (ALG-SPEC-0003).

This module builds SpecIndexV2 instances from libraries and elements,
coordinating the creation of bidirectional atom-element maps.

Design References:
- ALG-SPEC-0003: BuildSpecIndex
- DS-SPEC-0003: SpecIndex schema
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.core.library_registry import LibraryIdAllocator
    from spec_manager.schemas.derived_elements import DerivedElement

from spec_manager.schemas.spec_index_v2 import Library, SpecIndexV2, build_spec_index


class SpecIndexBuilder:
    """Builder for SpecIndexV2 instances (ALG-SPEC-0003).

    Coordinates the construction of spec indexes from various sources,
    including library discovery outputs and element extraction outputs.
    """

    def __init__(self) -> None:
        """Initialize the builder."""
        self._libraries: list[Library] = []
        self._elements: list["DerivedElement"] = []

    def add_library(
        self,
        lib_id: str,
        name: str,
        description: str = "",
        stability_key: str = "",
    ) -> "SpecIndexBuilder":
        """Add a library to the index.

        Args:
            lib_id: Library identifier
            name: Library display name
            description: Library description
            stability_key: Key for stable allocation

        Returns:
            Self for method chaining
        """
        library = Library(
            lib_id=lib_id,
            name=name,
            description=description,
            stability_key=stability_key,
        )
        self._libraries.append(library)
        return self

    def add_libraries_from_allocator(
        self, allocator: "LibraryIdAllocator"
    ) -> "SpecIndexBuilder":
        """Add all libraries from a LibraryIdAllocator.

        Args:
            allocator: The allocator containing library entries

        Returns:
            Self for method chaining
        """
        for entry in allocator.entries.values():
            self.add_library(
                lib_id=entry.lib_id,
                name=entry.name,
                stability_key=entry.stability_key,
            )
        return self

    def add_element(self, element: "DerivedElement") -> "SpecIndexBuilder":
        """Add an element to the index.

        Args:
            element: The element to add

        Returns:
            Self for method chaining
        """
        self._elements.append(element)
        return self

    def add_elements(self, elements: list["DerivedElement"]) -> "SpecIndexBuilder":
        """Add multiple elements to the index.

        Args:
            elements: List of elements to add

        Returns:
            Self for method chaining
        """
        self._elements.extend(elements)
        return self

    def build(self) -> SpecIndexV2:
        """Build the SpecIndexV2 from added components.

        Returns:
            Populated SpecIndexV2 instance
        """
        return build_spec_index(self._libraries, self._elements)

    def clear(self) -> "SpecIndexBuilder":
        """Clear all added components.

        Returns:
            Self for method chaining
        """
        self._libraries = []
        self._elements = []
        return self


def write_spec_index_json(index: SpecIndexV2, path: Path) -> None:
    """Write a SpecIndexV2 to a JSON file.

    Args:
        index: The index to write
        path: Output path
    """
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index.model_dump(), f, indent=2)


def read_spec_index_json(path: Path) -> SpecIndexV2:
    """Read a SpecIndexV2 from a JSON file.

    Args:
        path: Path to read from

    Returns:
        Loaded SpecIndexV2 instance
    """
    import json

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return SpecIndexV2.model_validate(data)

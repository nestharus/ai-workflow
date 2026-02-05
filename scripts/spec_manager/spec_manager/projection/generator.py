"""Plan projection generator implementing ALG-PROJ-0001.

Generates plan.md as a projection artifact with pins mapping
content back to authoritative L1 library sources.

Phase 7 Work Item 1: Projection Generation with Pins
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.schemas.projection import (
    Pin,
    ProjectionArtifact,
    ProjectionPolicy,
)

if TYPE_CHECKING:
    from spec_manager.schemas.derived_elements import DerivedElement
    from spec_manager.schemas.spec_index_v2 import Library


class ProjectionGenerator:
    """Generator for plan.md projection artifacts.

    Implements ALG-PROJ-0001: Build plan.md from libraries with embedded pins.
    """

    def __init__(self, policy: ProjectionPolicy | None = None) -> None:
        """Initialize the projection generator.

        Args:
            policy: Configuration for projection generation
        """
        self.policy = policy or ProjectionPolicy()
        self._pin_counter = 0

    def _next_pin_id(self) -> str:
        """Generate the next pin ID."""
        self._pin_counter += 1
        return f"PIN-{self._pin_counter:04d}"

    def reset_pin_counter(self) -> None:
        """Reset the pin counter for a new projection."""
        self._pin_counter = 0

    def generate_plan(
        self,
        libraries: list["Library"],
        elements: list["DerivedElement"],
        projection_id: str | None = None,
    ) -> ProjectionArtifact:
        """Generate a plan.md projection from libraries and elements.

        Args:
            libraries: List of Library objects
            elements: List of DerivedElement objects
            projection_id: Optional ID for the projection

        Returns:
            ProjectionArtifact with content and pins
        """
        self.reset_pin_counter()

        if projection_id is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            projection_id = f"PROJ-PLAN-{timestamp}"

        lines: list[str] = []
        pins: list[Pin] = []
        current_offset = 0

        # Header
        header = "# Plan\n\n"
        if self.policy.include_metadata:
            header += f"<!-- projection_id: {projection_id} -->\n"
            header += f"<!-- generated_at: {datetime.now(timezone.utc).isoformat()} -->\n"
            header += f"<!-- generated_from: LIBRARIES -->\n\n"

        lines.append(header)
        current_offset += len(header)

        # Group elements by library
        if self.policy.group_by_library:
            elements_by_lib = self._group_by_library(elements)

            for lib in sorted(libraries, key=lambda x: x.lib_id):
                lib_elements = elements_by_lib.get(lib.lib_id, [])
                if not lib_elements and not self.policy.include_metadata:
                    continue

                # Library section header with pin
                lib_header, lib_pins = self._generate_library_section(
                    lib, lib_elements, current_offset
                )
                lines.append(lib_header)
                pins.extend(lib_pins)
                current_offset += len(lib_header)
        else:
            # Flat list of elements
            for elem in sorted(elements, key=lambda x: x.elem_id):
                elem_content, elem_pins = self._generate_element_section(
                    elem, current_offset
                )
                lines.append(elem_content)
                pins.extend(elem_pins)
                current_offset += len(elem_content)

        content = "".join(lines)

        return ProjectionArtifact(
            projection_id=projection_id,
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content=content,
            pins=pins,
        )

    def _group_by_library(
        self, elements: list["DerivedElement"]
    ) -> dict[str, list["DerivedElement"]]:
        """Group elements by library ID."""
        groups: dict[str, list["DerivedElement"]] = {}
        for elem in elements:
            lib_id = elem.lib_id
            if lib_id not in groups:
                groups[lib_id] = []
            groups[lib_id].append(elem)
        return groups

    def _generate_library_section(
        self,
        library: "Library",
        elements: list["DerivedElement"],
        offset: int,
    ) -> tuple[str, list[Pin]]:
        """Generate content for a library section.

        Args:
            library: Library object
            elements: Elements belonging to this library
            offset: Current character offset in projection

        Returns:
            Tuple of (content string, list of pins)
        """
        pins: list[Pin] = []
        lines: list[str] = []

        # Library header
        header = f"\n## {library.name}"
        if self.policy.include_pins:
            pin = Pin(
                pin_id=self._next_pin_id(),
                from_projection_offset=offset + len(header) + 1,  # After newline
                target_id=library.lib_id,
                target_kind="LIBRARY",
            )
            pins.append(pin)
            pin_str = self.policy.format_pin(pin)
            header += f" {pin_str}"

        header += "\n\n"
        lines.append(header)

        if library.description:
            lines.append(f"{library.description}\n\n")

        current_offset = offset + len("".join(lines))

        # Elements in this library
        for elem in sorted(elements, key=lambda x: x.elem_id):
            elem_content, elem_pins = self._generate_element_section(
                elem, current_offset
            )
            lines.append(elem_content)
            pins.extend(elem_pins)
            current_offset += len(elem_content)

        return "".join(lines), pins

    def _generate_element_section(
        self,
        element: "DerivedElement",
        offset: int,
    ) -> tuple[str, list[Pin]]:
        """Generate content for an element.

        Args:
            element: DerivedElement object
            offset: Current character offset in projection

        Returns:
            Tuple of (content string, list of pins)
        """
        pins: list[Pin] = []
        lines: list[str] = []

        # Element header
        header = f"### {element.elem_id}: {element.title}"
        if self.policy.include_pins:
            pin = Pin(
                pin_id=self._next_pin_id(),
                from_projection_offset=offset + len(header) + 1,
                target_id=element.elem_id,
                target_kind="ELEMENT",
            )
            pins.append(pin)
            pin_str = self.policy.format_pin(pin)
            header += f" {pin_str}"

        header += "\n\n"
        lines.append(header)

        # Element body
        if element.body:
            lines.append(f"{element.body}\n\n")

        return "".join(lines), pins


def generate_plan_from_libraries(
    libraries: list["Library"],
    elements: list["DerivedElement"],
    policy: ProjectionPolicy | None = None,
) -> ProjectionArtifact:
    """Generate a plan.md projection from libraries (ALG-PROJ-0001).

    Convenience function that creates a ProjectionGenerator and
    generates a plan artifact.

    Args:
        libraries: List of Library objects
        elements: List of DerivedElement objects
        policy: Optional projection policy

    Returns:
        ProjectionArtifact with plan.md content and pins
    """
    generator = ProjectionGenerator(policy)
    return generator.generate_plan(libraries, elements)


def save_projection(
    artifact: ProjectionArtifact,
    content_path: Path,
    pins_path: Path | None = None,
) -> None:
    """Save a projection artifact to disk.

    Args:
        artifact: ProjectionArtifact to save
        content_path: Path to write content (e.g., plan.md)
        pins_path: Optional path to write pins JSON
    """
    # Write content
    content_path.parent.mkdir(parents=True, exist_ok=True)
    content_path.write_text(artifact.content, encoding="utf-8")

    # Write pins if path provided
    if pins_path is not None:
        pins_path.parent.mkdir(parents=True, exist_ok=True)
        pins_data = {
            "projection_id": artifact.projection_id,
            "kind": artifact.kind,
            "generated_from": artifact.generated_from,
            "created_at": artifact.created_at,
            "pins": [pin.model_dump() for pin in artifact.pins],
        }
        pins_path.write_text(
            json.dumps(pins_data, indent=2, default=str),
            encoding="utf-8",
        )


def load_projection_pins(pins_path: Path) -> list[Pin]:
    """Load pins from a projection pins JSON file.

    Args:
        pins_path: Path to pins JSON file

    Returns:
        List of Pin objects
    """
    data = json.loads(pins_path.read_text(encoding="utf-8"))
    return [Pin.model_validate(pin_data) for pin_data in data.get("pins", [])]


__all__ = [
    "ProjectionGenerator",
    "generate_plan_from_libraries",
    "save_projection",
    "load_projection_pins",
]

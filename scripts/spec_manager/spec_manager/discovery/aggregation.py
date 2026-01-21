"""Library shape aggregation.

This module aggregates labels to see the "shape" of each library -
what elements point to it, how strongly, and whether there's
convergence or divergence.

The shape tells us:
- What elements strongly belong to a library
- What elements weakly relate
- Whether the library is well-defined (convergence)
- Whether it overlaps with other libraries
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .labeling import ElementLabels


@dataclass
class LibraryShape:
    """Aggregated view of a library's shape.

    The shape tells us:
    - What elements strongly belong here
    - What elements weakly relate
    - Whether the library is well-defined (convergence)
    - Whether it overlaps with other libraries
    """

    name: str

    # Elements by confidence tier
    strong_matches: list[str] = field(default_factory=list)  # > 0.7
    medium_matches: list[str] = field(default_factory=list)  # 0.4 - 0.7
    weak_matches: list[str] = field(default_factory=list)  # 0.2 - 0.4

    # Metrics
    total_weight: float = 0.0  # Sum of all confidences
    element_count: int = 0  # Total elements
    convergence: float = 0.0  # How well-defined (0-1)

    # Overlap with other libraries
    overlaps: dict[str, float] = field(default_factory=dict)

    # Suggestions
    should_split: bool = False
    should_merge_with: str | None = None
    split_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "strong_matches": len(self.strong_matches),
            "medium_matches": len(self.medium_matches),
            "weak_matches": len(self.weak_matches),
            "total_weight": round(self.total_weight, 2),
            "element_count": self.element_count,
            "convergence": round(self.convergence, 2),
            "overlaps": {k: round(v, 2) for k, v in self.overlaps.items()},
            "should_split": self.should_split,
            "should_merge_with": self.should_merge_with,
            "split_reason": self.split_reason,
        }


class ShapeAggregator:
    """Aggregates labels to reveal library shapes.

    The aggregation process:
    1. Group elements by their labels
    2. Compute metrics for each library
    3. Identify overlaps between libraries
    4. Suggest refinements (split, merge, new)
    """

    def __init__(self, labels: dict[str, ElementLabels]):
        self.labels = labels
        self.shapes: dict[str, LibraryShape] = {}

    def aggregate(self) -> dict[str, LibraryShape]:
        """Compute shapes for all libraries."""
        # Collect elements per library
        library_elements: dict[str, list[tuple[str, float]]] = {}

        for element_id, element_labels in self.labels.items():
            for lib_name, confidence in element_labels.labels.items():
                if lib_name not in library_elements:
                    library_elements[lib_name] = []
                library_elements[lib_name].append((element_id, confidence))

        # Compute shape for each library
        for lib_name, elements in library_elements.items():
            shape = self._compute_shape(lib_name, elements)
            self.shapes[lib_name] = shape

        # Compute overlaps
        self._compute_overlaps()

        # Generate suggestions
        self._generate_suggestions()

        return self.shapes

    def _compute_shape(self, name: str, elements: list[tuple[str, float]]) -> LibraryShape:
        """Compute shape metrics for a library."""
        shape = LibraryShape(name=name)

        # Sort by confidence
        elements.sort(key=lambda x: x[1], reverse=True)

        # Categorize by confidence tier
        for element_id, confidence in elements:
            if confidence > 0.7:
                shape.strong_matches.append(element_id)
            elif confidence > 0.4:
                shape.medium_matches.append(element_id)
            else:
                shape.weak_matches.append(element_id)

            shape.total_weight += confidence

        shape.element_count = len(elements)

        # Compute convergence
        # High convergence = most elements are strong matches
        if shape.element_count > 0:
            strong_ratio = len(shape.strong_matches) / shape.element_count
            # Also consider confidence distribution
            avg_confidence = shape.total_weight / shape.element_count
            shape.convergence = (strong_ratio + avg_confidence) / 2

        return shape

    def _compute_overlaps(self) -> None:
        """Compute overlap between libraries."""
        library_names = list(self.shapes.keys())

        for i, lib1 in enumerate(library_names):
            shape1 = self.shapes[lib1]
            elements1 = set(shape1.strong_matches + shape1.medium_matches)

            for lib2 in library_names[i + 1 :]:
                shape2 = self.shapes[lib2]
                elements2 = set(shape2.strong_matches + shape2.medium_matches)

                # Compute Jaccard overlap
                intersection = len(elements1 & elements2)
                union = len(elements1 | elements2)

                if union > 0:
                    overlap = intersection / union
                    if overlap > 0.1:  # Significant overlap
                        shape1.overlaps[lib2] = overlap
                        shape2.overlaps[lib1] = overlap

    def _generate_suggestions(self) -> None:
        """Generate refinement suggestions based on shapes."""
        for name, shape in self.shapes.items():
            # Should split? (bimodal distribution)
            # Heuristic: many medium matches but few strong
            if (
                len(shape.medium_matches) > len(shape.strong_matches) * 2
                and shape.convergence < 0.5
            ):
                shape.should_split = True
                shape.split_reason = "Bimodal distribution suggests two distinct concepts"

            # Should merge? (high overlap with another)
            for other_name, overlap in shape.overlaps.items():
                if overlap > 0.6:  # Very high overlap
                    other_shape = self.shapes[other_name]
                    # Merge smaller into larger
                    if shape.element_count < other_shape.element_count:
                        shape.should_merge_with = other_name

    def get_new_library_candidates(self) -> list[list[str]]:
        """Find clusters that might be new libraries.

        These are elements that:
        - Have no strong match to any library
        - But strongly reference each other
        """
        # Find elements with only weak matches
        weak_elements: list[str] = []
        for element_id, labels in self.labels.items():
            max_confidence = max(labels.labels.values()) if labels.labels else 0
            if max_confidence < 0.4:
                weak_elements.append(element_id)

        if len(weak_elements) < 3:
            return []

        # These could form new libraries - return as candidates
        return [weak_elements]

    def summary(self) -> dict[str, Any]:
        """Generate a summary of all library shapes."""
        return {
            name: {
                "strong": len(shape.strong_matches),
                "medium": len(shape.medium_matches),
                "weak": len(shape.weak_matches),
                "convergence": round(shape.convergence, 2),
                "overlaps": {k: round(v, 2) for k, v in shape.overlaps.items()},
                "should_split": shape.should_split,
                "should_merge_with": shape.should_merge_with,
            }
            for name, shape in self.shapes.items()
        }

    def get_well_defined_libraries(self, min_convergence: float = 0.7) -> list[str]:
        """Get libraries with high convergence (well-defined)."""
        return [name for name, shape in self.shapes.items() if shape.convergence >= min_convergence]

    def get_problematic_libraries(self) -> list[tuple[str, str]]:
        """Get libraries with issues and their problems."""
        problems: list[tuple[str, str]] = []

        for name, shape in self.shapes.items():
            if shape.should_split:
                problems.append((name, f"Should split: {shape.split_reason}"))
            if shape.should_merge_with:
                problems.append((name, f"Should merge with {shape.should_merge_with}"))
            if shape.convergence < 0.3:
                problems.append((name, f"Very low convergence ({shape.convergence:.2f})"))

        return problems

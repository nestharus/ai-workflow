"""
Multi-label assignment for library discovery.

This module assigns elements to candidate libraries with confidence
scores. Elements can have multiple labels - this captures the
"smear" of cross-cutting concerns.

The labeling process:
1. For each element, check against each candidate library
2. Compute confidence based on keyword match, references, type
3. Store all labels above threshold
"""

from __future__ import annotations

from dataclasses import dataclass

from spec_manager.core.provenance import TrackedUnit
from .candidate import CandidateLibrary


@dataclass
class ElementLabels:
    """Labels assigned to an element."""

    element_id: str
    labels: dict[str, float]  # library_name -> confidence

    @property
    def primary(self) -> str | None:
        """Get the primary (highest confidence) label."""
        if not self.labels:
            return None
        return max(self.labels, key=lambda k: self.labels[k])

    @property
    def relations(self) -> list[str]:
        """Get non-primary labels as relations."""
        primary = self.primary
        return [
            lib for lib, conf in self.labels.items()
            if lib != primary and conf > 0.2  # Threshold for relation
        ]


class MultiLabeler:
    """
    Assigns multiple labels to elements with confidence scores.

    The labeling process:
    1. For each element, check against each candidate library
    2. Compute confidence based on keyword match, references, type
    3. Store all labels above threshold

    Known Limitation:
    The _compute_confidence() method currently weights signals as:
    - 40% - Keyword matches in content
    - 30% - References to exemplar elements
    - 20% - Is this element an exemplar?
    - 10% - Name/ID similarity (keyword-based)

    This means 50% of the signal is keyword-based (40% direct + 10% name).
    This is acceptable for now because:
    1. Keywords come from config or data-driven clustering (not hardcoded)
    2. CandidateIdentifier.discover_with_all_signals() compensates by using
       multi-signal discovery for candidate generation
    3. The labeling step happens AFTER candidates are identified
    """

    def __init__(self, candidates: list[CandidateLibrary]):
        self.candidates = {c.name: c for c in candidates}
        self.labels: dict[str, ElementLabels] = {}

    def label_element(self, unit: TrackedUnit) -> ElementLabels:
        """Assign labels to a single element."""
        scores: dict[str, float] = {}

        for lib_name, candidate in self.candidates.items():
            score = self._compute_confidence(unit, candidate)
            if score > 0.1:  # Minimum threshold
                scores[lib_name] = score

        labels = ElementLabels(
            element_id=unit.id,
            labels=scores
        )
        self.labels[unit.id] = labels
        return labels

    def label_all(self, units: list[TrackedUnit]) -> dict[str, ElementLabels]:
        """Label all elements."""
        for unit in units:
            self.label_element(unit)
        return self.labels

    def _compute_confidence(
        self,
        unit: TrackedUnit,
        candidate: CandidateLibrary
    ) -> float:
        """
        Compute confidence that element belongs to library.

        Factors:
        - Keyword matches in content (40% weight)
        - References to exemplar elements (30% weight)
        - Is this element an exemplar? (20% weight)
        - Name/ID similarity (10% weight)
        """
        score = 0.0
        content_lower = unit.content.lower()

        # Keyword matches (40% weight)
        if candidate.keywords:
            keyword_matches = sum(
                content_lower.count(kw) for kw in candidate.keywords
            )
            keyword_score = min(keyword_matches / 10, 1.0)  # Normalize
            score += keyword_score * 0.4

        # Reference to exemplars (30% weight)
        if candidate.exemplar_elements:
            ref_matches = sum(
                1 for ref in unit.references
                if ref in candidate.exemplar_elements
            )
            ref_score = min(ref_matches / 3, 1.0)
            score += ref_score * 0.3

        # Is this element an exemplar? (20% weight)
        if unit.id in candidate.exemplar_elements:
            score += 0.2

        # Name similarity (10% weight)
        if candidate.keywords:
            id_lower = unit.id.lower()
            name_match = any(kw in id_lower for kw in candidate.keywords)
            if name_match:
                score += 0.1

        return min(score, 1.0)

    def get_unlabeled(self) -> list[str]:
        """Get elements with no labels above threshold."""
        return [
            eid for eid, labels in self.labels.items()
            if not labels.labels
        ]

    def get_by_library(self, library_name: str) -> list[tuple[str, float]]:
        """Get all elements labeled with a library, sorted by confidence."""
        results: list[tuple[str, float]] = []
        for eid, labels in self.labels.items():
            if library_name in labels.labels:
                results.append((eid, labels.labels[library_name]))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def get_multi_labeled(self) -> list[tuple[str, dict[str, float]]]:
        """Get elements with multiple labels (cross-cutting concerns)."""
        return [
            (eid, labels.labels)
            for eid, labels in self.labels.items()
            if len(labels.labels) > 1
        ]

    def summary(self) -> dict[str, int]:
        """Generate a summary of labeling results."""
        total = len(self.labels)
        unlabeled = len(self.get_unlabeled())
        multi_labeled = len(self.get_multi_labeled())
        single_labeled = total - unlabeled - multi_labeled

        return {
            'total_elements': total,
            'unlabeled': unlabeled,
            'single_labeled': single_labeled,
            'multi_labeled': multi_labeled,
            'libraries_used': len(self.candidates)
        }

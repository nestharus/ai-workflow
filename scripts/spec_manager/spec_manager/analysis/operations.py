"""
Analysis operations for library restructuring.

These operations detect patterns that suggest libraries should be split or merged.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.annotations import AnnotationParser, AnnotationType
from spec_manager.core.ids import IdValidator, IdCategory
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.sections import SectionExtractor


@dataclass
class DivergenceCandidate:
    """A library that may benefit from being split."""

    library: str
    suggested_split: str  # Name for the new library
    ids_to_move: list[str]
    reason: str
    confidence: float  # 0.0 to 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "suggested_split": self.suggested_split,
            "ids_to_move": self.ids_to_move,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class ConvergenceCandidate:
    """Two libraries that may benefit from being merged."""

    library1: str
    library2: str
    shared_context_ids: list[str]
    reason: str
    confidence: float  # 0.0 to 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "library1": self.library1,
            "library2": self.library2,
            "shared_context_ids": self.shared_context_ids,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class ReferencePattern:
    """A pattern of cross-library references."""

    source_library: str
    target_library: str
    reference_count: int
    referenced_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_library": self.source_library,
            "target_library": self.target_library,
            "reference_count": self.reference_count,
            "referenced_ids": self.referenced_ids[:10],  # Limit output
        }


@dataclass
class RestructuringSuggestion:
    """A suggested restructuring action."""

    action: str  # "split", "merge", "move_ids"
    libraries: list[str]
    ids: list[str]
    description: str
    priority: int  # Lower = higher priority
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "libraries": self.libraries,
            "ids": self.ids,
            "description": self.description,
            "priority": self.priority,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class AnalysisResult:
    """Result of library analysis."""

    divergence_candidates: list[DivergenceCandidate] = field(default_factory=list)
    convergence_candidates: list[ConvergenceCandidate] = field(default_factory=list)
    reference_patterns: list[ReferencePattern] = field(default_factory=list)
    suggestions: list[RestructuringSuggestion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "divergence_candidates": [d.to_dict() for d in self.divergence_candidates],
            "convergence_candidates": [c.to_dict() for c in self.convergence_candidates],
            "reference_patterns": [r.to_dict() for r in self.reference_patterns],
            "suggestions": [s.to_dict() for s in self.suggestions],
        }


def detect_divergence(
    registry: LibsRegistry,
    libraries_dir: Path,
    min_cluster_size: int = 3,
) -> list[DivergenceCandidate]:
    """
    Detect libraries that should be split based on related patterns.

    A library is a divergence candidate when:
    - Many of its IDs share a common subset of related libraries
    - The IDs cluster by category (all algorithms, all data structures)
    - The library has grown beyond a reasonable size

    Args:
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        min_cluster_size: Minimum IDs to form a cluster

    Returns:
        List of DivergenceCandidate
    """
    candidates: list[DivergenceCandidate] = []
    validator = IdValidator()
    extractor = SectionExtractor()

    # Get library sizes
    library_results = extractor.extract_from_directory(libraries_dir)
    library_sizes = {name: len(result.sections) for name, result in library_results.items()}

    # Use registry's built-in divergence detection
    registry_candidates = registry.detect_divergence_candidates(min_cluster_size)

    for library, suggested_split, ids in registry_candidates:
        # Calculate confidence based on cluster cohesion
        confidence = min(len(ids) / 10, 0.9)  # More IDs = higher confidence

        candidates.append(
            DivergenceCandidate(
                library=library,
                suggested_split=suggested_split,
                ids_to_move=ids,
                reason=f"{len(ids)} IDs share strong relationship with {suggested_split}",
                confidence=confidence,
            )
        )

    # Also check for category-based clustering
    for lib_name, ids in [(e.primary, e.id_value) for e in registry.iter_entries()]:
        pass  # Category clustering could be added here

    # Check for large libraries
    for lib_name, size in library_sizes.items():
        if size > 30:  # Threshold for "large"
            # Group by category
            categories: dict[IdCategory, list[str]] = defaultdict(list)
            for entry in registry.iter_entries():
                if entry.primary == lib_name:
                    cat = validator.get_category(entry.id_value)
                    categories[cat].append(entry.id_value)

            # Suggest splitting by category if one dominates
            for cat, cat_ids in categories.items():
                if len(cat_ids) >= min_cluster_size and len(cat_ids) >= size * 0.3:
                    candidates.append(
                        DivergenceCandidate(
                            library=lib_name,
                            suggested_split=f"{lib_name}_{cat.value}",
                            ids_to_move=cat_ids,
                            reason=f"{len(cat_ids)} {cat.value} IDs could form separate library",
                            confidence=0.5,
                        )
                    )

    return candidates


def detect_convergence(
    registry: LibsRegistry,
    libraries_dir: Path,
    min_cross_reference: int = 3,
) -> list[ConvergenceCandidate]:
    """
    Detect libraries that should be merged based on cross-references.

    Two libraries are convergence candidates when:
    - Many IDs from one reference the other in related
    - They share common themes/categories
    - They are both small

    Args:
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        min_cross_reference: Minimum cross-references to suggest merge

    Returns:
        List of ConvergenceCandidate
    """
    candidates: list[ConvergenceCandidate] = []
    extractor = SectionExtractor()

    # Get library sizes
    library_results = extractor.extract_from_directory(libraries_dir)
    library_sizes = {name: len(result.sections) for name, result in library_results.items()}

    # Use registry's built-in convergence detection
    registry_candidates = registry.detect_convergence_candidates(min_cross_reference)

    for lib1, lib2, shared_ids in registry_candidates:
        # Higher confidence if both libraries are small
        size1 = library_sizes.get(lib1, 0)
        size2 = library_sizes.get(lib2, 0)
        combined_size = size1 + size2

        if combined_size <= 20:
            confidence = 0.8
        elif combined_size <= 40:
            confidence = 0.6
        else:
            confidence = 0.4

        # Adjust for cross-reference strength
        cross_ref_strength = len(shared_ids) / max(size1, size2, 1)
        confidence = min(confidence + cross_ref_strength * 0.2, 0.95)

        candidates.append(
            ConvergenceCandidate(
                library1=lib1,
                library2=lib2,
                shared_context_ids=shared_ids,
                reason=f"{len(shared_ids)} IDs create strong cross-references",
                confidence=confidence,
            )
        )

    return candidates


def analyze_references(
    libraries_dir: Path,
    registry: LibsRegistry,
) -> list[ReferencePattern]:
    """
    Analyze cross-library reference patterns.

    Examines (@[+ID]) and (@[=ID]) references to find patterns
    of inter-library dependencies.

    Args:
        libraries_dir: Path to libraries directory
        registry: The libs.md registry

    Returns:
        List of ReferencePattern showing cross-library references
    """
    patterns: list[ReferencePattern] = []
    parser = AnnotationParser()
    validator = IdValidator()

    # Track references: source_lib -> target_lib -> [ids]
    cross_refs: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for lib_file in sorted(libraries_dir.glob("*.md")):
        lib_name = lib_file.stem
        content = lib_file.read_text(encoding="utf-8")

        # Find all references
        for annotation in parser.parse_references(content):
            id_value = annotation.id_value
            if not validator.is_valid(id_value):
                continue

            # Find target library
            target_lib = registry.get_primary(id_value)
            if target_lib and target_lib != lib_name:
                cross_refs[lib_name][target_lib].append(id_value)

    # Convert to patterns
    for source_lib, targets in cross_refs.items():
        for target_lib, ids in targets.items():
            patterns.append(
                ReferencePattern(
                    source_library=source_lib,
                    target_library=target_lib,
                    reference_count=len(ids),
                    referenced_ids=list(set(ids)),  # Dedupe
                )
            )

    # Sort by reference count
    patterns.sort(key=lambda p: -p.reference_count)

    return patterns


def suggest_restructuring(
    divergence: list[DivergenceCandidate],
    convergence: list[ConvergenceCandidate],
    reference_patterns: list[ReferencePattern],
) -> list[RestructuringSuggestion]:
    """
    Generate prioritized restructuring suggestions.

    Combines divergence, convergence, and reference analysis
    to produce actionable recommendations.

    Args:
        divergence: Divergence candidates
        convergence: Convergence candidates
        reference_patterns: Reference patterns

    Returns:
        Prioritized list of RestructuringSuggestion
    """
    suggestions: list[RestructuringSuggestion] = []

    # High-confidence divergences first
    for d in divergence:
        if d.confidence >= 0.7:
            suggestions.append(
                RestructuringSuggestion(
                    action="split",
                    libraries=[d.library],
                    ids=d.ids_to_move,
                    description=f"Split {len(d.ids_to_move)} IDs from {d.library} into {d.suggested_split}",
                    priority=1,
                    confidence=d.confidence,
                )
            )

    # High-confidence convergences
    for c in convergence:
        if c.confidence >= 0.7:
            suggestions.append(
                RestructuringSuggestion(
                    action="merge",
                    libraries=[c.library1, c.library2],
                    ids=c.shared_context_ids,
                    description=f"Merge {c.library1} and {c.library2} ({len(c.shared_context_ids)} shared)",
                    priority=2,
                    confidence=c.confidence,
                )
            )

    # High-volume reference patterns might indicate ID moves
    for p in reference_patterns:
        if p.reference_count >= 5:
            suggestions.append(
                RestructuringSuggestion(
                    action="move_ids",
                    libraries=[p.source_library, p.target_library],
                    ids=p.referenced_ids[:5],
                    description=f"Consider moving frequently-referenced IDs from {p.target_library} to {p.source_library}",
                    priority=3,
                    confidence=min(p.reference_count / 10, 0.8),
                )
            )

    # Sort by priority then confidence
    suggestions.sort(key=lambda s: (s.priority, -s.confidence))

    return suggestions


def run_analysis(
    registry: LibsRegistry,
    libraries_dir: Path,
) -> AnalysisResult:
    """
    Run full library structure analysis.

    Args:
        registry: The libs.md registry
        libraries_dir: Path to libraries directory

    Returns:
        AnalysisResult with all findings
    """
    result = AnalysisResult()

    result.divergence_candidates = detect_divergence(registry, libraries_dir)
    result.convergence_candidates = detect_convergence(registry, libraries_dir)
    result.reference_patterns = analyze_references(libraries_dir, registry)
    result.suggestions = suggest_restructuring(
        result.divergence_candidates,
        result.convergence_candidates,
        result.reference_patterns,
    )

    return result

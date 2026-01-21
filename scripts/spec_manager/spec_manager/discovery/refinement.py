"""Iterative library refinement.

This module handles the iterative process of refining libraries
until each element has a single primary assignment.

The refinement loop:
1. Label elements with current libraries
2. Aggregate to see shapes
3. Apply suggestions (split, merge, new)
4. Repeat until stable
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.provenance import TrackedUnit

from .aggregation import LibraryShape, ShapeAggregator
from .candidate import CandidateIdentifier, CandidateLibrary
from .labeling import ElementLabels, MultiLabeler


@dataclass
class RefinementResult:
    """Result of a refinement iteration."""

    iteration: int
    libraries: list[CandidateLibrary]
    shapes: dict[str, LibraryShape]
    labels: dict[str, ElementLabels]

    # Changes made
    libraries_added: list[str] = field(default_factory=list)
    libraries_removed: list[str] = field(default_factory=list)
    libraries_merged: list[tuple[str, str]] = field(default_factory=list)  # (source, target)
    libraries_split: list[tuple[str, list[str]]] = field(
        default_factory=list
    )  # (source, new_names)

    # Metrics
    convergence_score: float = 0.0  # Overall convergence
    unassigned_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "iteration": self.iteration,
            "libraries": [c.name for c in self.libraries],
            "convergence_score": round(self.convergence_score, 2),
            "unassigned_count": self.unassigned_count,
            "libraries_added": self.libraries_added,
            "libraries_removed": self.libraries_removed,
            "libraries_merged": self.libraries_merged,
            "libraries_split": self.libraries_split,
        }


class LibraryRefiner:
    """Iteratively refines libraries until stable.

    The refinement loop:
    1. Label elements with current libraries
    2. Aggregate to see shapes
    3. Apply suggestions (split, merge, new)
    4. Repeat until stable
    """

    def __init__(self, units: list[TrackedUnit]):
        self.units = units
        self.iteration = 0
        self.history: list[RefinementResult] = []

    def refine(
        self, initial_candidates: list[CandidateLibrary], max_iterations: int = 10
    ) -> RefinementResult:
        """Run refinement until stable or max iterations.

        Returns the final refinement result.
        """
        candidates = list(initial_candidates)  # Make a copy

        for i in range(max_iterations):
            self.iteration = i + 1

            # Label with current candidates
            labeler = MultiLabeler(candidates)
            labels = labeler.label_all(self.units)

            # Aggregate to see shapes
            aggregator = ShapeAggregator(labels)
            shapes = aggregator.aggregate()

            # Check for suggested changes
            added, removed, merged, split = self._apply_suggestions(candidates, shapes, aggregator)

            # Compute metrics
            convergence = self._compute_overall_convergence(shapes)
            unassigned = len(labeler.get_unlabeled())

            result = RefinementResult(
                iteration=self.iteration,
                libraries=list(candidates),  # Copy current state
                shapes=shapes,
                labels=labels,
                libraries_added=added,
                libraries_removed=removed,
                libraries_merged=merged,
                libraries_split=split,
                convergence_score=convergence,
                unassigned_count=unassigned,
            )
            self.history.append(result)

            # Check for stability
            if not added and not removed and not merged and not split:
                break  # Stable!

            # Update candidates for next iteration
            # (mutations happened in _apply_suggestions)

        return self.history[-1]

    def _apply_suggestions(
        self,
        candidates: list[CandidateLibrary],
        shapes: dict[str, LibraryShape],
        aggregator: ShapeAggregator,
    ) -> tuple[list[str], list[str], list[tuple[str, str]], list[tuple[str, list[str]]]]:
        """Apply shape-based suggestions to candidates."""
        added: list[str] = []
        removed: list[str] = []
        merged: list[tuple[str, str]] = []
        split: list[tuple[str, list[str]]] = []

        # Handle merges
        for name, shape in shapes.items():
            if shape.should_merge_with:
                # Remove the smaller library
                candidates[:] = [c for c in candidates if c.name != name]
                removed.append(name)
                merged.append((name, shape.should_merge_with))

        # Handle splits - name using TF-IDF based on split content
        for name, shape in shapes.items():
            if shape.should_split and name not in removed:
                old_candidate = next((c for c in candidates if c.name == name), None)

                if old_candidate is None:
                    continue

                # Split elements between new libraries
                mid = len(shape.medium_matches) // 2
                elements_a = shape.strong_matches[:3] + shape.medium_matches[:mid]
                elements_b = shape.medium_matches[mid:] + shape.weak_matches[:3]

                # Name splits using TF-IDF based on their content
                name_a = self._name_split_by_tfidf(elements_a, set())
                name_b = self._name_split_by_tfidf(elements_b, {name_a})

                new_a = CandidateLibrary(
                    internal_id=f"{old_candidate.internal_id}_a",
                    name=name_a,
                    description=f"Split from {name}",
                    keywords=list(old_candidate.keywords),
                    exemplar_elements=elements_a,
                    confidence=0.5,
                    how_identified=f"Split from {name}",
                )

                new_b = CandidateLibrary(
                    internal_id=f"{old_candidate.internal_id}_b",
                    name=name_b,
                    description=f"Split from {name}",
                    keywords=list(old_candidate.keywords),
                    exemplar_elements=elements_b,
                    confidence=0.5,
                    how_identified=f"Split from {name}",
                )

                candidates[:] = [c for c in candidates if c.name != name]
                candidates.extend([new_a, new_b])

                removed.append(name)
                added.extend([name_a, name_b])
                split.append((name, [name_a, name_b]))

        # Handle new library candidates - name using TF-IDF
        new_clusters = aggregator.get_new_library_candidates()
        used_emerging_names: set[str] = set()
        for cluster in new_clusters:
            new_name = self._name_split_by_tfidf(cluster, used_emerging_names)
            used_emerging_names.add(new_name)
            new_lib = CandidateLibrary(
                internal_id=f"LIB_EMERGING_{self.iteration}",
                name=new_name,
                description="Emerged from weak-match cluster",
                keywords=[],
                exemplar_elements=cluster[:5],
                confidence=0.3,
                how_identified="Emerged from weak-match cluster",
            )
            candidates.append(new_lib)
            added.append(new_name)

        return added, removed, merged, split

    def _name_split_by_tfidf(self, element_ids: list[str], used_names: set[str]) -> str:
        """Name a split/emerging cluster using TF-IDF.

        Picks the most distinctive term from the cluster's content.
        """
        import math
        import re
        from collections import defaultdict

        # Get units for these element IDs
        unit_map = {u.id: u for u in self.units}
        cluster_units = [unit_map[eid] for eid in element_ids if eid in unit_map]

        if not cluster_units:
            return f"cluster_{self.iteration}"

        # Compute global doc frequency
        total_units = len(self.units)
        global_doc_freq: dict[str, int] = defaultdict(int)
        for unit in self.units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            for word in words:
                global_doc_freq[word] += 1

        english_stopwords = {
            "that",
            "this",
            "with",
            "from",
            "have",
            "will",
            "been",
            "each",
            "which",
            "their",
            "when",
            "where",
            "they",
            "them",
            "then",
            "than",
            "also",
            "only",
            "more",
            "some",
            "such",
            "other",
            "into",
            "over",
            "after",
            "before",
            "through",
            "what",
            "about",
            "would",
            "could",
            "should",
            "there",
        }

        # Compute TF-IDF for cluster
        cluster_tf: dict[str, int] = defaultdict(int)
        for unit in cluster_units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            words = words - english_stopwords
            for word in words:
                cluster_tf[word] += 1

        tfidf_scores: dict[str, float] = {}
        for word, tf in cluster_tf.items():
            df = global_doc_freq.get(word, 1)
            idf = math.log(total_units / df) if df > 0 else 0
            tfidf_scores[word] = tf * idf

        # Pick highest TF-IDF word not already used
        sorted_words = sorted(tfidf_scores.keys(), key=lambda w: tfidf_scores[w], reverse=True)
        for word in sorted_words:
            if word not in used_names:
                return word

        # Fallback
        base = sorted_words[0] if sorted_words else "cluster"
        counter = 1
        while f"{base}_{counter}" in used_names:
            counter += 1
        return f"{base}_{counter}"

    def _compute_overall_convergence(self, shapes: dict[str, LibraryShape]) -> float:
        """Compute overall convergence across all libraries."""
        if not shapes:
            return 0.0

        total_convergence = sum(s.convergence for s in shapes.values())
        return total_convergence / len(shapes)

    def finalize(self) -> dict[str, ElementLabels]:
        """Finalize labels by assigning primary and relations.

        After refinement, each element should have exactly one
        primary library and zero or more relation libraries.
        """
        if not self.history:
            raise ValueError("Must run refine() before finalize()")

        final_result = self.history[-1]
        final_labels: dict[str, ElementLabels] = {}

        for element_id, labels in final_result.labels.items():
            # Primary is highest confidence
            primary = labels.primary
            relations = labels.relations

            # Create new labels with primary normalized to 1.0
            new_labels: dict[str, float] = {}
            if primary:
                new_labels[primary] = 1.0
            # Store relations for annotation
            if relations:
                for r in relations:
                    new_labels[r] = labels.labels[r]

            final_labels[element_id] = ElementLabels(element_id=element_id, labels=new_labels)

        return final_labels

    def get_iteration_summary(self) -> list[dict[str, Any]]:
        """Get a summary of all iterations."""
        return [result.to_dict() for result in self.history]

    def get_final_library_assignments(self) -> dict[str, str]:
        """Get final library assignment for each element."""
        if not self.history:
            return {}

        final_labels = self.finalize()
        return {eid: labels.primary or "unassigned" for eid, labels in final_labels.items()}


async def discover_libraries(
    units: list[TrackedUnit], llm_client: Any = None, config_path: Path | None = None
) -> dict[str, ElementLabels]:
    """Run the full library discovery workflow.

    IMPORTANT: Uses discover_with_all_signals() for multi-signal discovery.
    This combines:
    1. Reference graph structure (highest weight)
    2. Unit type clustering
    3. Relation annotations from prior iterations
    4. Content clustering (word-based seed)
    5. LLM system summaries (optional, if llm_client provided)

    Args:
        units: List of TrackedUnits to process
        llm_client: Optional LLM client for semantic analysis
        config_path: Optional path to keyword config file

    Returns:
        Dictionary mapping element IDs to their labels
    """
    # Step 1: Identify candidates using ALL signals (not just keywords)
    identifier = CandidateIdentifier(config_path=config_path, llm_client=llm_client)
    candidates = identifier.discover_with_all_signals(units)  # Multi-signal discovery

    print(f"Identified {len(candidates)} candidate libraries via multi-signal discovery")
    for c in candidates:
        print(f"  - {c.name} ({c.internal_id}): {c.how_identified}")

    # Step 2-4: Refine iteratively
    refiner = LibraryRefiner(units)
    result = refiner.refine(candidates, max_iterations=10)

    print(f"Refinement completed in {result.iteration} iterations")
    print(f"Convergence: {result.convergence_score:.2f}")
    print(f"Unassigned: {result.unassigned_count}")

    # Step 5: Finalize assignments
    final_labels = refiner.finalize()

    return final_labels


def discover_libraries_sync(
    units: list[TrackedUnit], llm_client: Any = None, config_path: Path | None = None
) -> dict[str, ElementLabels]:
    """Synchronous version of discover_libraries.

    For use in non-async contexts.
    """
    import asyncio

    # Try to get existing event loop, create one if needed
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, need to use different approach
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run, discover_libraries(units, llm_client, config_path)
                )
                return future.result()
        return loop.run_until_complete(discover_libraries(units, llm_client, config_path))
    except RuntimeError:
        # No event loop, create one
        return asyncio.run(discover_libraries(units, llm_client, config_path))


# Legacy wrapper (deprecated - use discover_libraries with discover_with_all_signals)
async def discover_libraries_keyword_only(units: list[TrackedUnit]) -> dict[str, ElementLabels]:
    """DEPRECATED: Keyword-based discovery only.

    Use discover_libraries() instead, which uses discover_with_all_signals().
    This is kept for backward compatibility but should not be used in new code.
    """
    import warnings

    warnings.warn(
        "discover_libraries_keyword_only is deprecated. "
        "Use discover_libraries() which uses discover_with_all_signals().",
        DeprecationWarning,
        stacklevel=2,
    )

    identifier = CandidateIdentifier()
    candidates = identifier.identify_candidates(units)  # Old method
    candidates.extend(identifier.suggest_from_references(units))

    refiner = LibraryRefiner(units)
    refiner.refine(candidates, max_iterations=10)

    return refiner.finalize()

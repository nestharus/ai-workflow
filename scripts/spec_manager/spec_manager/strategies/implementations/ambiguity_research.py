"""Ambiguity research strategy for the translation paradigm.

Searches hollowed-out spec for details when a pseudocode comment
has insufficient context for translation. Uses needle-in-haystack
search against the complete spec to find relevant details.
"""

from __future__ import annotations

import re

from spec_manager.core.provenance import TrackedUnit, UnitType
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)


class AmbiguityResearchStrategy(Strategy):
    """Searches hollowed-out spec for details when comment is underspecified.

    Uses needle-in-haystack search against the complete spec to find
    relevant details for translation.
    """

    def __init__(
        self, definition: StrategyDefinition | None = None, tools: dict[str, Tool] | None = None
    ) -> None:
        """Initialize the strategy.

        Args:
            definition: Strategy definition from YAML.
            tools: Dictionary of available tools.
        """
        self.definition = definition
        self.tools = tools or {}
        self._spec_researcher = self.tools.get("spec_researcher")
        self._needle_searcher = self.tools.get("needle_searcher")

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "ambiguity_research"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Search hollowed-out spec for details when comment has insufficient context"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Translation failure from insufficient detail in pseudocode comment"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.TRANSLATION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if hollowed_spec_path is available and comment is underspecified.

        A comment is considered underspecified if it is short (fewer than 5 words)
        or contains vague terms without specific identifiers.
        """
        tc = context.translation_context
        if tc is None:
            return False

        if tc.hollowed_spec_path is None:
            return False

        # Heuristic: short comments or those with underspecified terms
        words = tc.comment_text.strip().split()
        if len(words) < 5:
            return True

        vague_terms = ["something", "somehow", "appropriate", "relevant", "necessary", "needed"]
        comment_lower = tc.comment_text.lower()
        return any(term in comment_lower for term in vague_terms)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Search spec, extract relevant details, augment translation context."""
        actions: list[str] = []
        issues: list[str] = []
        evidence_records: list[dict[str, object]] = []

        tc = context.translation_context
        if tc is None:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=["No translation context available"],
                metrics={"research_hits": 0},
            )

        # Extract key terms from comment for searching
        key_terms = self._extract_key_terms(tc.comment_text)
        research_hits: list[str] = []

        # Use needle_searcher tool if available
        if self._needle_searcher and tc.hollowed_spec_path:
            for term in key_terms:
                try:
                    results = self._needle_searcher(
                        needle=term, haystack_path=tc.hollowed_spec_path
                    )
                    if results:
                        research_hits.append(str(results))
                except Exception as exc:
                    issues.append(f"Needle search failed for term '{term}': {exc}")

        # Use spec_researcher tool if available
        if self._spec_researcher and tc.hollowed_spec_path:
            try:
                results = self._spec_researcher(
                    query=tc.comment_text, spec_path=tc.hollowed_spec_path
                )
                if results:
                    research_hits.append(str(results))
            except Exception as exc:
                issues.append(f"Spec research failed: {exc}")

        if research_hits:
            actions.append(f"Found {len(research_hits)} relevant spec sections for comment")
            evidence_records.append(
                {
                    "category": "research",
                    "type": "ambiguity_resolved",
                    "severity": "info",
                    "details": {
                        "comment": tc.comment_text,
                        "hits": len(research_hits),
                        "key_terms": key_terms,
                    },
                }
            )
        else:
            issues.append("No relevant spec sections found for underspecified comment")

        # Augment existing units with research context
        output_units: list[TrackedUnit] = []
        for unit in context.units:
            if research_hits and unit.unit_type in (UnitType.PROSE, UnitType.UNKNOWN):
                augmented_content = (
                    unit.content + "\n\n[Research context]: " + "; ".join(research_hits[:3])
                )
                new_unit = unit.derive(
                    augmented_content,
                    new_id=f"{unit.id}_researched",
                    modifier="ambiguity_research",
                )
                new_unit.add_parent(unit.id)
                unit.add_child(new_unit.id)

                lineage_table = getattr(context, "lineage_table", None)
                if lineage_table is not None:
                    lineage_table.add_edge(
                        from_unit=unit.id,
                        to_unit=new_unit.id,
                        transformation="transform",
                    )
                output_units.append(new_unit)
            else:
                output_units.append(unit)

        return StrategyResult(
            units=output_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "research_hits": len(research_hits),
                "key_terms_searched": len(key_terms),
            },
            evidence_records=evidence_records,
        )

    @staticmethod
    def _extract_key_terms(comment: str) -> list[str]:
        """Extract key terms from a comment for searching."""
        # Remove comment markers and stopwords
        stripped = re.sub(r"^#\s*", "", comment.strip())
        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "and",
            "or",
            "but",
            "if",
            "then",
            "else",
            "this",
            "that",
            "it",
            "its",
        }

        words = re.findall(r"\b[a-zA-Z_]\w+\b", stripped)
        key_terms = [w for w in words if w.lower() not in stopwords and len(w) > 2]

        # Return unique terms, preserving order
        seen: set[str] = set()
        unique_terms: list[str] = []
        for term in key_terms:
            lower = term.lower()
            if lower not in seen:
                seen.add(lower)
                unique_terms.append(term)

        return unique_terms[:10]

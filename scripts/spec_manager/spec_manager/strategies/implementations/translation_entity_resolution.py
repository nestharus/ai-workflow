"""Translation entity resolution strategy for the translation paradigm.

Resolves vague references in pseudocode comments during translation.
Differs from the existing EntityResolutionStrategy in that it operates
on pseudocode comments within code files rather than prose TrackedUnits,
and uses the call graph and function signatures for resolution context.
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

# Vague reference patterns commonly found in pseudocode comments
_VAGUE_PATTERNS = [
    r"\bthe algorithm\b",
    r"\bthe function\b",
    r"\bthe method\b",
    r"\bthe routine\b",
    r"\bthe handler\b",
    r"\bthe callback\b",
    r"\bit\b(?!\s+is\b)",  # "it" but not "it is" (to avoid false positives)
    r"\bthis\b(?!\s+function\b|\s+class\b|\s+method\b)",
    r"\bthat\b(?!\s+is\b|\s+are\b)",
]


class TranslationEntityResolutionStrategy(Strategy):
    """Resolves vague references in pseudocode comments during translation.

    Differs from the existing EntityResolutionStrategy in that it operates
    on pseudocode comments within code files rather than prose TrackedUnits,
    and uses the call graph and function signatures for resolution context.
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
        self._reference_resolver = self.tools.get("reference_resolver")
        self._call_graph_analyzer = self.tools.get("call_graph_analyzer")

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "translation_entity_resolution"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Resolve vague references in pseudocode comments to specific function names"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Translation failure from comments referencing 'the algorithm' without specifics"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.TRANSLATION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if comment contains vague references.

        Uses pattern matching to detect vague references that would
        benefit from resolution before translation.
        """
        tc = context.translation_context
        if tc is None:
            return False

        comment_lower = tc.comment_text.lower()
        return any(re.search(pattern, comment_lower) for pattern in _VAGUE_PATTERNS)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Resolve references using call graph, function signatures, and spec."""
        actions: list[str] = []
        issues: list[str] = []
        evidence_records: list[dict[str, object]] = []

        tc = context.translation_context
        if tc is None:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=["No translation context available"],
                metrics={"references_resolved": 0},
            )

        comment = tc.comment_text
        vague_refs = self._find_vague_references(comment)

        if not vague_refs:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=[],
                metrics={"references_resolved": 0},
            )

        resolved_comment = comment
        resolved_count = 0

        for ref_text in vague_refs:
            resolved_name = self._resolve_reference(ref_text, tc)
            if resolved_name:
                resolved_comment = resolved_comment.replace(ref_text, resolved_name)
                resolved_count += 1
                actions.append(f"Resolved '{ref_text}' -> '{resolved_name}'")
                evidence_records.append(
                    {
                        "category": "resolution",
                        "type": "vague_reference_resolved",
                        "severity": "info",
                        "details": {
                            "original": ref_text,
                            "resolved_to": resolved_name,
                            "method": "translation_entity_resolution",
                        },
                    }
                )
            else:
                issues.append(f"Could not resolve vague reference: '{ref_text}'")

        # Create output units with resolved content
        output_units: list[TrackedUnit] = []
        for unit in context.units:
            if resolved_count > 0 and unit.unit_type in (UnitType.PROSE, UnitType.UNKNOWN):
                new_unit = unit.derive(
                    resolved_comment,
                    new_id=f"{unit.id}_resolved",
                    modifier="translation_entity_resolution",
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
                "vague_references_found": len(vague_refs),
                "references_resolved": resolved_count,
            },
            evidence_records=evidence_records,
        )

    @staticmethod
    def _find_vague_references(comment: str) -> list[str]:
        """Find vague references in a comment."""
        found: list[str] = []
        comment_lower = comment.lower()
        if any(re.search(pattern, comment_lower) for pattern in _VAGUE_PATTERNS):
            # Vague references found, extract them with original casing
            for pattern in _VAGUE_PATTERNS:
                for match in re.finditer(pattern, comment_lower):
                    start, end = match.start(), match.end()
                    found.append(comment[start:end])
        return found

    def _resolve_reference(
        self,
        ref_text: str,
        tc: object,
    ) -> str | None:
        """Attempt to resolve a vague reference to a specific name.

        Uses call graph neighbors and function signatures for context.
        """
        from spec_manager.strategies.base import TranslationContext

        if not isinstance(tc, TranslationContext):
            return None

        # Use reference_resolver tool if available
        if self._reference_resolver:
            try:
                result = self._reference_resolver(
                    reference=ref_text,
                    function_signature=tc.function_signature,
                    neighbors=tc.call_graph_neighbors,
                )
                if result:
                    return str(result)
            except Exception:  # noqa: S110
                pass

        # Use call_graph_analyzer tool if available
        if self._call_graph_analyzer:
            try:
                result = self._call_graph_analyzer(
                    reference=ref_text,
                    neighbors=tc.call_graph_neighbors,
                    stores=tc.store_dependencies,
                )
                if result:
                    return str(result)
            except Exception:  # noqa: S110
                pass

        # Heuristic resolution: if we have call graph neighbors,
        # pick the most likely candidate based on the reference text
        if tc.call_graph_neighbors:
            ref_lower = ref_text.lower()
            for neighbor in tc.call_graph_neighbors:
                neighbor_lower = neighbor.lower()
                # Match "the algorithm" to a function with "algorithm" in its name
                for word in ref_lower.split():
                    if len(word) > 3 and word in neighbor_lower:
                        return neighbor

            # If no match found, return the first neighbor as a best guess
            if len(tc.call_graph_neighbors) == 1:
                return tc.call_graph_neighbors[0]

        return None

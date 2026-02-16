"""Translation entity resolution strategy for the translation paradigm.

Resolves vague references in pseudocode comments during translation.
Differs from the existing EntityResolutionStrategy in that it operates
on pseudocode comments within code files rather than prose TrackedUnits,
and uses the call graph and function signatures for resolution context.
"""

from __future__ import annotations

import hashlib
import logging
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

_CONFIDENCE_THRESHOLD = 0.7
logger = logging.getLogger(__name__)


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
        output_units: list[TrackedUnit] = []
        existing_ids = {unit.id for unit in context.units}
        lineage_table = getattr(context, "lineage_table", None)

        tc = context.translation_context
        if tc is None:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=["No translation context available"],
                metrics={"references_resolved": 0},
            )

        comment_vague_refs = self._find_vague_references(tc.comment_text)

        if not comment_vague_refs:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=[],
                metrics={"references_resolved": 0},
            )

        vague_refs_found = 0
        resolved_count = 0

        for unit in context.units:
            if unit.unit_type not in (UnitType.PROSE, UnitType.UNKNOWN):
                output_units.append(unit)
                continue

            unit_refs = self._find_vague_references(unit.content)
            vague_refs_found += len(unit_refs)
            if not unit_refs:
                output_units.append(unit)
                continue

            resolved_content = unit.content
            unit_resolved = 0
            for ref_text in unit_refs:
                resolved_name, confidence, method, rationale, resolver_errors = (
                    self._resolve_reference(ref_text, tc)
                )
                for resolver_error in resolver_errors:
                    logger.warning(
                        "Translation entity resolver error for '%s' in %s: %s",
                        ref_text,
                        unit.id,
                        resolver_error,
                    )
                    issues.append(
                        f"Resolver error while resolving '{ref_text}' in {unit.id}: "
                        f"{resolver_error}"
                    )
                    evidence_records.append(
                        {
                            "category": "resolution",
                            "type": "resolver_error",
                            "severity": "warning",
                            "details": {
                                "unit_id": unit.id,
                                "reference": ref_text,
                                "error": resolver_error,
                            },
                        }
                    )

                if not resolved_name:
                    issues.append(f"Could not resolve vague reference: '{ref_text}' in {unit.id}")
                    continue

                if confidence < _CONFIDENCE_THRESHOLD:
                    issues.append(
                        f"Low-confidence resolution for '{ref_text}' in {unit.id} "
                        f"({confidence:.2f} < {_CONFIDENCE_THRESHOLD:.2f})"
                    )
                    evidence_records.append(
                        {
                            "category": "resolution",
                            "type": "low_confidence_resolution",
                            "severity": "warning",
                            "details": {
                                "unit_id": unit.id,
                                "reference": ref_text,
                                "candidate": resolved_name,
                                "confidence": confidence,
                                "threshold": _CONFIDENCE_THRESHOLD,
                                "method": method,
                                "rationale": rationale,
                            },
                        }
                    )
                    continue

                resolved_content = resolved_content.replace(ref_text, resolved_name)
                unit_resolved += 1
                resolved_count += 1
                actions.append(
                    f"Resolved '{ref_text}' -> '{resolved_name}' in {unit.id} "
                    f"(confidence: {confidence:.2f})"
                )
                evidence_records.append(
                    {
                        "category": "resolution",
                        "type": "vague_reference_resolved",
                        "severity": "info",
                        "details": {
                            "unit_id": unit.id,
                            "original": ref_text,
                            "resolved_to": resolved_name,
                            "confidence": confidence,
                            "method": method,
                            "rationale": rationale,
                        },
                    }
                )

            if unit_resolved > 0:
                new_unit = unit.derive(
                    resolved_content,
                    new_id=self._build_resolved_unit_id(unit.id, resolved_content, existing_ids),
                    modifier="translation_entity_resolution",
                )
                new_unit.add_parent(unit.id)
                unit.add_child(new_unit.id)

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
                "vague_references_found": vague_refs_found,
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
    ) -> tuple[str | None, float, str, str, list[str]]:
        """Attempt to resolve a vague reference to a specific name.

        Uses call graph neighbors and function signatures for context.
        """
        from spec_manager.strategies.base import TranslationContext

        errors: list[str] = []
        if not isinstance(tc, TranslationContext):
            return None, 0.0, "invalid_context", "Invalid translation context", errors

        # Use reference_resolver tool if available
        if self._reference_resolver:
            try:
                result = self._reference_resolver(
                    reference=ref_text,
                    function_signature=tc.function_signature,
                    neighbors=tc.call_graph_neighbors,
                )
                parsed = self._parse_resolution_result(result, "reference_resolver")
                if parsed:
                    return parsed[0], parsed[1], parsed[2], parsed[3], errors
            except Exception as exc:
                errors.append(f"reference_resolver: {type(exc).__name__}: {exc}")

        # Use call_graph_analyzer tool if available
        if self._call_graph_analyzer:
            try:
                result = self._call_graph_analyzer(
                    reference=ref_text,
                    neighbors=tc.call_graph_neighbors,
                    stores=tc.store_dependencies,
                )
                parsed = self._parse_resolution_result(result, "call_graph_analyzer")
                if parsed:
                    return parsed[0], parsed[1], parsed[2], parsed[3], errors
            except Exception as exc:
                errors.append(f"call_graph_analyzer: {type(exc).__name__}: {exc}")

        # Heuristic resolution: if we have call graph neighbors,
        # pick the most likely candidate based on the reference text
        if tc.call_graph_neighbors:
            ref_lower = ref_text.lower()
            for neighbor in tc.call_graph_neighbors:
                neighbor_lower = neighbor.lower()
                # Match "the algorithm" to a function with "algorithm" in its name
                for word in ref_lower.split():
                    if len(word) > 3 and word in neighbor_lower:
                        return (
                            neighbor,
                            0.6,
                            "neighbor_name_overlap",
                            f"Matched reference token overlap with neighbor '{neighbor}'",
                            errors,
                        )

            # Single-candidate fallback is treated as ambiguous, not authoritative.
            if len(tc.call_graph_neighbors) == 1:
                return (
                    None,
                    0.0,
                    "single_candidate_ambiguous",
                    "Single candidate exists but confidence is unverified",
                    errors,
                )

        return None, 0.0, "unresolved", "No reliable resolution candidate found", errors

    @staticmethod
    def _parse_resolution_result(result: object, method: str) -> tuple[str, float, str, str] | None:
        """Parse resolver output into a normalized candidate tuple."""
        if isinstance(result, str) and result.strip():
            resolved = result.strip()
            return resolved, 0.8, method, f"{method} returned a direct resolution"

        if isinstance(result, dict):
            candidate = result.get("resolved") or result.get("target") or result.get("id")
            if isinstance(candidate, str) and candidate.strip():
                confidence = result.get("confidence", 0.8)
                try:
                    parsed_confidence = float(confidence)
                except (TypeError, ValueError):
                    parsed_confidence = 0.0
                rationale = str(result.get("rationale", f"{method} returned structured resolution"))
                return candidate.strip(), max(0.0, min(parsed_confidence, 1.0)), method, rationale
        return None

    def _build_resolved_unit_id(self, base_id: str, content: str, existing_ids: set[str]) -> str:
        """Build deterministic, collision-safe IDs for resolved units."""
        suffix = hashlib.sha256(content.encode()).hexdigest()[:8]
        candidate = f"{base_id}_resolved_{suffix}"
        counter = 1
        while candidate in existing_ids:
            candidate = f"{base_id}_resolved_{suffix}_{counter}"
            counter += 1
        existing_ids.add(candidate)
        return candidate

"""Entity resolution strategy.

Resolves vague references like "the algorithm" or "this" to specific IDs
using available context and optional LLM inference.
"""

from __future__ import annotations

import re
from typing import Any

from spec_manager.core.provenance import TrackedUnit, UnitType
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)
from spec_manager.strategies.implementations.llm_inference import VagueReferenceResolver

_VAGUE_REFERENCE_PATTERNS = (
    re.compile(r"\b(this|that|it|these|those)\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(algorithm|claim|invariant|proof)\b", re.IGNORECASE),
    re.compile(
        r"\b(patch|update|modify)\s+(this|that|it|these|those|the\s+\w+)\b",
        re.IGNORECASE,
    ),
)

_GENERIC_NOUN_TYPES = {
    "algorithm": UnitType.ALGORITHM,
    "claim": UnitType.CLAIM,
    "invariant": UnitType.INVARIANT,
    "proof": UnitType.PROOF,
}

_CONFIDENCE_THRESHOLD = 0.7


class EntityResolutionStrategy(Strategy):
    """Resolve vague references to specific IDs."""

    def __init__(
        self, definition: StrategyDefinition | None = None, tools: dict[str, Tool] | None = None
    ) -> None:
        """Initialize entity resolution strategy with optional definition and tools."""
        self.definition = definition
        self.tools = tools or {}
        self._llm = self.tools.get("llm_client")

    @property
    def name(self) -> str:
        """Return strategy identifier."""
        return "entity_resolution"

    @property
    def purpose(self) -> str:
        """Return strategy purpose description."""
        return "Resolve vague references like 'the algorithm' to specific IDs"

    @property
    def risk_addressed(self) -> str:
        """Return the risk this strategy addresses."""
        return "Vague references make it unclear what is being modified"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Return the processing phases where this strategy applies."""
        return [StrategyPhase.RESOLUTION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if any units contain vague references."""
        return any(self._find_vague_references(unit.content) for unit in context.units)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute entity resolution strategy."""
        actions: list[str] = []
        issues: list[str] = []
        output_units: list[TrackedUnit] = []

        resolver = VagueReferenceResolver(reference_store=None, llm_client=self._llm)

        total_references = 0
        resolved_count = 0
        unresolved_count = 0

        existing_ids = {unit.id for unit in context.units}

        for index, unit in enumerate(context.units):
            reference_texts = self._find_vague_references(unit.content)
            if not reference_texts:
                output_units.append(unit)
                continue

            total_references += len(reference_texts)
            resolution_context = self._build_resolution_context(context, index)

            resolved_content = unit.content
            resolutions: list[tuple[str, float, str, str, str]] = []
            used_heuristic = False

            for reference_text in reference_texts:
                if reference_text not in resolved_content:
                    continue
                if self._llm:
                    target_id, confidence, rationale = self._resolve_with_llm(
                        resolver, reference_text, resolution_context
                    )
                    if not target_id or confidence < _CONFIDENCE_THRESHOLD:
                        issues.append(f"Unresolved reference '{reference_text}' in {unit.id}")
                        unresolved_count += 1
                        continue
                    method = "llm_inference"
                else:
                    target_id, confidence, rationale = self._resolve_with_heuristic(
                        reference_text, context.units, index
                    )
                    if not target_id:
                        issues.append(f"Unresolved reference '{reference_text}' in {unit.id}")
                        unresolved_count += 1
                        continue
                    method = "heuristic"
                    used_heuristic = True

                resolved_count += 1
                resolved_content = self._replace_reference(
                    resolved_content, reference_text, target_id
                )
                resolutions.append((target_id, confidence, rationale, method, reference_text))

            if resolutions:
                new_id = f"{unit.id}_resolved"
                if new_id in existing_ids:
                    suffix = abs(hash(resolved_content)) % 10000
                    new_id = f"{unit.id}_resolved_{suffix:04d}"
                    counter = 1
                    while new_id in existing_ids:
                        new_id = f"{unit.id}_resolved_{suffix:04d}_{counter}"
                        counter += 1
                new_unit = unit.derive(
                    resolved_content, new_id=new_id, modifier="entity_resolution"
                )
                existing_ids.add(new_id)
                new_unit.add_parent(unit.id)
                unit.add_child(new_unit.id)
                lineage_table = getattr(context, "lineage_table", None)
                if lineage_table is not None:
                    lineage_table.add_edge(
                        from_unit=unit.id,
                        to_unit=new_unit.id,
                        transformation="transform",
                    )

                for target_id, confidence, rationale, method, reference_text in resolutions:
                    new_unit.add_membership(
                        target_id, rationale=rationale, confidence=confidence, method=method
                    )
                    actions.append(
                        f"Resolved '{reference_text}' -> '{target_id}' in {unit.id} "
                        f"(confidence: {confidence:.2f})"
                    )

                if used_heuristic:
                    issues.append(f"Heuristic resolution used for {unit.id}")

                output_units.append(new_unit)
            else:
                output_units.append(unit)

        resolution_rate = resolved_count / total_references if total_references > 0 else 0.0

        return StrategyResult(
            units=output_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "total_references": total_references,
                "resolved": resolved_count,
                "unresolved": unresolved_count,
                "resolution_rate": resolution_rate,
            },
        )

    def _find_vague_references(self, text: str) -> list[str]:
        """Extract vague reference phrases from text."""
        matches: list[str] = []
        for pattern in _VAGUE_REFERENCE_PATTERNS:
            for match in pattern.finditer(text):
                reference = match.group(0).strip()
                if reference and reference not in matches:
                    matches.append(reference)
        filtered: list[str] = []
        for reference in matches:
            has_longer_match = any(
                reference != other and reference in other and len(other) > len(reference)
                for other in matches
            )
            if not has_longer_match:
                filtered.append(reference)
        return filtered

    def _build_resolution_context(self, context: ProcessingContext, index: int) -> dict[str, Any]:
        """Build resolution context for LLM-based inference."""
        window = 2
        before = context.units[max(0, index - window) : index]
        after = context.units[index + 1 : index + 1 + window]
        nearby_units = [*before, *after]

        return {
            "patch_chain": context.previous_results.get("patch_chain", []),
            "nearby_elements": [unit.id for unit in nearby_units],
            "nearby_declarations": [decl for unit in nearby_units for decl in unit.declarations],
            "reference_files": context.reference_files,
            "previous_results": context.previous_results,
            "patch_id": context.patch_id or context.units[index].source.patch_id,
            "source_file": context.source_file,
        }

    def _resolve_with_llm(
        self,
        resolver: VagueReferenceResolver,
        reference_text: str,
        resolution_context: dict[str, Any],
    ) -> tuple[str | None, float, str]:
        """Resolve a reference using LLM inference."""
        candidates = resolver.resolve(reference_text, resolution_context)
        if not candidates:
            return None, 0.0, "No candidates found"

        best = candidates[0]
        return best.inferred_content, best.confidence, best.rationale

    def _resolve_with_heuristic(
        self, reference_text: str, units: list[TrackedUnit], index: int
    ) -> tuple[str | None, float, str]:
        """Fallback heuristic resolution when no LLM is available."""
        reference_lower = reference_text.lower()
        unit_type = None
        for noun, mapped_type in _GENERIC_NOUN_TYPES.items():
            if noun in reference_lower:
                unit_type = mapped_type
                break

        prior_units = units[:index]
        if unit_type:
            typed_candidates = [
                unit for unit in prior_units if unit.unit_type == unit_type and unit.declarations
            ]
            if typed_candidates:
                candidate = typed_candidates[-1]
                return (
                    candidate.id,
                    0.6,
                    f"Heuristic match to most recent {unit_type.value} declaration {candidate.id}",
                )

        declared_candidates = [unit for unit in prior_units if unit.declarations]
        if declared_candidates:
            candidate = declared_candidates[-1]
            return (
                candidate.id,
                0.55,
                f"Heuristic match to most recent declaration {candidate.id}",
            )

        return None, 0.0, "No heuristic match"

    def _replace_reference(self, text: str, reference_text: str, target_id: str) -> str:
        """Replace a reference phrase with the resolved target ID."""
        return re.sub(re.escape(reference_text), target_id, text)

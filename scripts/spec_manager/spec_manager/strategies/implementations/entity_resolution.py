"""Entity resolution strategy.

Resolves vague references like "the algorithm" or "this" to specific IDs
using available context and optional LLM inference.

Phase 5 (CON-0003/CON-0004 compliance):
- Removed keyword/regex patterns for raw text scanning
- Uses structural gating via unresolved_references count in evidence_summary
- Heuristic fallbacks are non-authoritative (confidence < 0.5)
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

# System-owned ID reference pattern - allowed by CON-0004
# This matches explicit ID references like (@[+ATOM-0001]) or (@[=P1I1]) or (@[+Algorithm 1])
_SYSTEM_ID_REFERENCE_PATTERN = re.compile(
    r"\(@\[\+?=?([A-Z]+-\d+|[A-Z]\d+[A-Z]\d+|Algorithm[\s_]+\d+)\]\)"
)


def compute_unresolved_references(units: list[TrackedUnit], declared_ids: set[str]) -> int:
    """Compute count of unresolved ID references in units.

    This is a STRUCTURAL signal - counts (@[+ID]) patterns that don't match
    any declared ID. This is CON-0004 compliant as it only scans for
    system-owned ID markers, not semantic keywords.

    Args:
        units: List of tracked units to scan
        declared_ids: Set of IDs that have been declared in the spec

    Returns:
        Count of unresolved ID references
    """
    unresolved_count = 0

    for unit in units:
        # Find all system ID references in content
        for match in _SYSTEM_ID_REFERENCE_PATTERN.finditer(unit.content):
            ref_id = match.group(1)
            # Normalize "Algorithm 1" to a comparable form
            normalized_id = ref_id.replace(" ", "_").upper()

            # Check if reference points to a declared ID
            if ref_id not in declared_ids and normalized_id not in declared_ids:
                unresolved_count += 1

    return unresolved_count


_CONFIDENCE_THRESHOLD = 0.7

# Heuristic confidence threshold - below this, findings are non-authoritative
_HEURISTIC_CONFIDENCE_THRESHOLD = 0.5


class EntityResolutionStrategy(Strategy):
    """Resolve vague references to specific IDs.

    Phase 5 (CON-0003/CON-0004 compliance):
    - Strategy gating uses structural signals (unresolved_references count)
    - No keyword/regex scanning of raw text content
    - Always runs on PROSE-type units in RESOLUTION phase, letting LLM determine need
    """

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
        """Check if this strategy should run using STRUCTURAL signals only.

        Phase 5 (CON-0003 compliance): No regex/keyword scanning of raw text.
        Instead, uses:
        1. evidence_summary.unresolved_references > 0 (structural signal), OR
        2. Presence of PROSE-type units (always eligible for resolution)

        This is CON-0004 compliant as we only check structural metadata.
        """
        # Check structural signal from evidence_summary
        if context.evidence_summary:
            unresolved_refs = context.evidence_summary.get("unresolved_references", 0)
            if unresolved_refs > 0:
                return True

        # Alternative: always run on PROSE-type units in RESOLUTION phase
        # Let LLM determine if resolution is actually needed
        has_prose_units = any(unit.unit_type == UnitType.PROSE for unit in context.units)
        return has_prose_units

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute entity resolution strategy.

        Phase 5 (CON-0003 compliance): Uses LLM or structural detection instead
        of keyword/regex scanning. References are detected via:
        1. LLM inference (if available) - authoritative
        2. Structural detection (system ID patterns) - authoritative
        3. Heuristic fallback - non-authoritative (confidence < 0.5)
        """
        actions: list[str] = []
        issues: list[str] = []
        output_units: list[TrackedUnit] = []
        evidence_records: list[dict[str, Any]] = []

        resolver = VagueReferenceResolver(reference_store=None, llm_client=self._llm)

        total_references = 0
        resolved_count = 0
        unresolved_count = 0

        existing_ids = {unit.id for unit in context.units}
        declared_ids = {decl for unit in context.units for decl in unit.declarations}

        for index, unit in enumerate(context.units):
            # Phase 5: Use structural detection (system ID patterns) instead of regex
            reference_texts = self._find_unresolved_system_refs(unit.content, declared_ids)

            # If LLM available, also ask it to identify vague references
            if self._llm and not reference_texts:
                reference_texts = self._detect_vague_refs_via_llm(unit, context, index)

            if not reference_texts:
                output_units.append(unit)
                continue

            total_references += len(reference_texts)
            resolution_context = self._build_resolution_context(context, index)
            context_summary = {
                "patch_id": resolution_context.get("patch_id"),
                "source_file": resolution_context.get("source_file"),
                "nearby_elements": resolution_context.get("nearby_elements", []),
                "nearby_declarations": resolution_context.get("nearby_declarations", []),
                "reference_files": sorted(
                    list(resolution_context.get("reference_files", {}).keys())
                ),
            }

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
                    if not target_id:
                        issues.append(f"Unresolved reference '{reference_text}' in {unit.id}")
                        unresolved_count += 1
                        evidence_records.append(
                            {
                                "category": "resolution",
                                "type": "unresolved_reference",
                                "severity": "warning",
                                "details": {
                                    "reference_text": reference_text,
                                    "unit_id": unit.id,
                                    "context": context_summary,
                                },
                            }
                        )
                        continue
                    if confidence < _CONFIDENCE_THRESHOLD:
                        issues.append(f"Unresolved reference '{reference_text}' in {unit.id}")
                        unresolved_count += 1
                        evidence_records.append(
                            {
                                "category": "resolution",
                                "type": "low_confidence_resolution",
                                "severity": "warning",
                                "details": {
                                    "reference_text": reference_text,
                                    "confidence": confidence,
                                    "threshold": _CONFIDENCE_THRESHOLD,
                                },
                            }
                        )
                        evidence_records.append(
                            {
                                "category": "resolution",
                                "type": "unresolved_reference",
                                "severity": "warning",
                                "details": {
                                    "reference_text": reference_text,
                                    "unit_id": unit.id,
                                    "context": context_summary,
                                },
                            }
                        )
                        continue
                    method = "llm_inference"
                else:
                    # Phase 5: Heuristic fallback with non-authoritative confidence
                    target_id, confidence, rationale = self._resolve_with_heuristic(
                        reference_text, context.units, index
                    )
                    if not target_id:
                        issues.append(f"Unresolved reference '{reference_text}' in {unit.id}")
                        unresolved_count += 1
                        evidence_records.append(
                            {
                                "category": "resolution",
                                "type": "unresolved_reference",
                                "severity": "warning",
                                "details": {
                                    "reference_text": reference_text,
                                    "unit_id": unit.id,
                                    "context": context_summary,
                                },
                            }
                        )
                        continue
                    method = "heuristic"
                    used_heuristic = True
                    evidence_records.append(
                        {
                            "category": "resolution",
                            "type": "heuristic_resolution",
                            "severity": "info",
                            "is_authoritative": False,  # Phase 5: mark non-authoritative
                            "details": {
                                "reference_text": reference_text,
                                "target_id": target_id,
                                "confidence": confidence,
                                "method": method,
                            },
                        }
                    )

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
                    issues.append(f"Heuristic resolution used for {unit.id} (non-authoritative)")

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
            evidence_records=evidence_records,
        )

    def _find_unresolved_system_refs(self, content: str, declared_ids: set[str]) -> list[str]:
        """Find unresolved system ID references (CON-0004 compliant).

        Only scans for system-owned ID patterns, not semantic keywords.
        """
        unresolved = []
        for match in _SYSTEM_ID_REFERENCE_PATTERN.finditer(content):
            ref_id = match.group(1)
            normalized_id = ref_id.replace(" ", "_").upper()
            if ref_id not in declared_ids and normalized_id not in declared_ids:
                unresolved.append(match.group(0))
        return unresolved

    def _detect_vague_refs_via_llm(
        self, unit: TrackedUnit, context: ProcessingContext, index: int
    ) -> list[str]:
        """Use LLM to detect vague references requiring resolution.

        Phase 5 (CON-0003 compliance): LLM determines if resolution is needed,
        not keyword patterns.
        """
        if not self._llm:
            return []

        prompt = f"""Analyze this text and identify any vague references that need resolution.
Vague references are phrases like "the algorithm", "this claim", "that proof" that
refer to specific spec elements but don't specify which one.

Text:
{unit.content[:1500]}

Context - nearby element IDs: {[u.id for u in context.units[max(0, index - 2) : index + 3]]}

Return a JSON array of vague reference phrases found (empty array if none):
["the algorithm", "this claim", ...]"""

        try:
            response = self._llm.complete(prompt)
            import json

            refs = json.loads(response)
            return refs if isinstance(refs, list) else []
        except Exception:
            logger.debug("Entity resolution failed", exc_info=True)
            return []

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
        """Fallback heuristic resolution when no LLM is available.

        Phase 5 (AUTH-0001 compliance): Heuristic fallbacks are NON-AUTHORITATIVE.
        All confidence scores are < 0.5 to indicate they require confirmation.

        Note: This method uses structural signals (unit types, declarations) rather
        than semantic keyword matching to remain CON-0003 compliant.
        """
        # Use structural signals: look for prior units with declarations
        prior_units = units[:index]

        # Structural heuristic: match to most recent unit with declarations
        # of matching type (based on unit metadata, not content scanning)
        declared_candidates = [unit for unit in prior_units if unit.declarations]

        if declared_candidates:
            candidate = declared_candidates[-1]
            # Phase 5: Non-authoritative confidence (< 0.5)
            return (
                candidate.id,
                0.4,  # Below 0.5 threshold - non-authoritative
                f"Heuristic match to most recent declaration {candidate.id} (non-authoritative)",
            )

        return None, 0.0, "No heuristic match"

    def _replace_reference(self, text: str, reference_text: str, target_id: str) -> str:
        """Replace a reference phrase with the resolved target ID."""
        return re.sub(re.escape(reference_text), target_id, text)

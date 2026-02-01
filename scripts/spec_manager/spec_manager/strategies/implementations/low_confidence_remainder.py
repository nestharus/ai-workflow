"""Low-confidence remainder routing strategy.

Routes units with low-confidence membership mappings to the remainder queue
instead of allowing them to overwrite authoritative content. Preserves the
"never drop details" guarantee by keeping both versions for review.
"""

from __future__ import annotations

from typing import Any

from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)
from spec_manager.workflow.config import TrackedUnit

# Default confidence threshold below which units are routed to remainder
_DEFAULT_CONFIDENCE_THRESHOLD = 0.7


class LowConfidenceRemainderStrategy(Strategy):
    """Routes low-confidence units to remainder queue."""

    def __init__(
        self, definition: StrategyDefinition | None = None, tools: dict[str, Tool] | None = None
    ) -> None:
        self.definition = definition
        self.tools = tools or {}

    @property
    def name(self) -> str:
        return "low_confidence_remainder"

    @property
    def purpose(self) -> str:
        return (
            "Route low-confidence integrations to remainder queue "
            "instead of overwriting authoritative content"
        )

    @property
    def risk_addressed(self) -> str:
        return "Low-confidence mappings silently overwrite high-quality content"

    @property
    def phases(self) -> list[StrategyPhase]:
        return [StrategyPhase.CLEANING]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Applies when there are units with low-confidence membership evidence."""
        threshold = context.config.get("confidence_threshold", _DEFAULT_CONFIDENCE_THRESHOLD)
        for unit in context.units:
            for evidence in unit.membership_evidence.values():
                if evidence.confidence < threshold:
                    return True
        return False

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Route low-confidence units to remainder.

        Scans all units for membership evidence below the confidence
        threshold. Units with any low-confidence mapping are removed from
        the active set and routed to remainder via the remainder_router tool.
        """
        threshold = context.config.get("confidence_threshold", _DEFAULT_CONFIDENCE_THRESHOLD)
        remainder_router = self.tools.get("remainder_router")
        confidence_scorer = self.tools.get("confidence_scorer")

        kept_units: list[TrackedUnit] = []
        actions: list[str] = []
        issues: list[str] = []
        routed_count = 0

        for unit in context.units:
            low_confidence_mappings = self._find_low_confidence_mappings(
                unit, threshold, confidence_scorer
            )

            if low_confidence_mappings:
                reason = (
                    f"confidence below {threshold} for mappings: "
                    + ", ".join(
                        f"{target}({conf:.2f})" for target, conf in low_confidence_mappings
                    )
                )
                if remainder_router:
                    remainder_router(unit, reason)
                actions.append(f"Routed {unit.id} to remainder: {reason}")
                routed_count += 1
            else:
                kept_units.append(unit)

        if routed_count:
            issues.append(f"{routed_count} units routed to remainder due to low confidence")

        return StrategyResult(
            units=kept_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "routed_to_remainder": routed_count,
                "kept": len(kept_units),
                "threshold": threshold,
            },
        )

    def _find_low_confidence_mappings(
        self,
        unit: TrackedUnit,
        threshold: float,
        confidence_scorer: Any,
    ) -> list[tuple[str, float]]:
        """Return (target_id, confidence) pairs below threshold."""
        low: list[tuple[str, float]] = []
        for target_id, evidence in unit.membership_evidence.items():
            confidence = evidence.confidence
            if confidence_scorer is not None:
                confidence = confidence_scorer(
                    {"method": evidence.method, "similarity": evidence.confidence}
                )
            if confidence < threshold:
                low.append((target_id, confidence))
        return low

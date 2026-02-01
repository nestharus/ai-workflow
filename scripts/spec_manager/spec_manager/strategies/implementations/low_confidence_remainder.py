"""Low-confidence remainder routing strategy.

Routes units with low-confidence membership mappings to the remainder queue
instead of allowing them to overwrite authoritative content.
"""

from __future__ import annotations

from spec_manager.core.provenance import UnitStatus
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)

_DEFAULT_CONFIDENCE_THRESHOLD = 0.7


class LowConfidenceRemainderStrategy(Strategy):
    """Routes low-confidence units to the remainder queue."""

    def __init__(
        self, definition: StrategyDefinition | None = None, tools: dict[str, Tool] | None = None
    ) -> None:
        """Initialize the strategy with definition and tools."""
        self.definition = definition
        self.tools = tools or {}
        if definition:
            self.threshold = definition.metadata.get(
                "confidence_threshold", _DEFAULT_CONFIDENCE_THRESHOLD
            )
        else:
            self.threshold = _DEFAULT_CONFIDENCE_THRESHOLD

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "low_confidence_remainder"

    @property
    def purpose(self) -> str:
        """Return strategy purpose."""
        return "Route low-confidence integrations to remainder queue instead of overwriting"

    @property
    def risk_addressed(self) -> str:
        """Return risk addressed by this strategy."""
        return "Low-confidence mappings silently overwrite high-quality content"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Return applicable strategy phases."""
        return [StrategyPhase.CLEANING, StrategyPhase.RESOLUTION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Applies when there are units with low-confidence membership evidence."""
        for unit in context.units:
            for evidence in unit.membership_evidence.values():
                if evidence.confidence < self.threshold:
                    return True
        return False

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Route low-confidence units to remainder."""
        actions: list[str] = []
        issues: list[str] = []

        high_confidence = 0
        remainder_count = 0

        for unit in context.units:
            confidences = [evidence.confidence for evidence in unit.membership_evidence.values()]
            target_ids = list(unit.membership_evidence.keys())

            if self._is_ambiguous(confidences):
                unit.status = UnitStatus.REMAINDER
                unit.drop_reason = "Ambiguous entity resolution"
                issues.append(f"Ambiguous mapping for {unit.id}: {target_ids}")
                remainder_count += 1
                continue

            if not confidences:
                unit.status = UnitStatus.REMAINDER
                unit.drop_reason = "Low confidence mapping (max: 0.00)"
                issues.append(f"Routed {unit.id} to remainder (confidence: 0.00)")
                remainder_count += 1
                continue

            min_confidence = min(confidences)
            if min_confidence < self.threshold:
                max_confidence = max(confidences)
                unit.status = UnitStatus.REMAINDER
                unit.drop_reason = f"Low confidence mapping (max: {max_confidence:.2f})"
                issues.append(f"Routed {unit.id} to remainder (confidence: {max_confidence:.2f})")
                remainder_count += 1
                continue

            high_confidence += 1
            actions.append(f"Accepted {unit.id} (confidence: {min_confidence:.2f})")

        total_units = len(context.units)
        remainder_ratio = remainder_count / total_units if total_units > 0 else 0.0

        return StrategyResult(
            units=context.units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "total_units": total_units,
                "high_confidence": high_confidence,
                "remainder": remainder_count,
                "remainder_ratio": remainder_ratio,
            },
            should_repeat=False,
        )

    def _is_ambiguous(self, confidences: list[float]) -> bool:
        """Check for ambiguous mappings with similar confidence scores."""
        if len(confidences) < 2:
            return False
        ordered = sorted(confidences, reverse=True)
        return abs(ordered[0] - ordered[1]) < 0.1

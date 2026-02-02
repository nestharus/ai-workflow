"""Truncation guard strategy.

Ensures unit content does not exceed the configured maximum length.
"""

from __future__ import annotations

from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)

_DEFAULT_MAX_LENGTH = 50_000


class TruncationGuardStrategy(Strategy):
    """Enforce max content length to prevent downstream truncation."""

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

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "truncation_guard"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Enforce max content length to prevent truncation in downstream processing"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Content truncation causing information loss"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.CLEANING]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if any unit exceeds the configured max length."""
        cap = self._get_cap(context)
        return any(len(unit.content) > cap for unit in context.units)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Truncate content that exceeds the configured cap."""
        actions: list[str] = []
        issues: list[str] = []
        evidence_records: list[dict[str, object]] = []
        truncation_count = 0
        total_chars_removed = 0
        cap = self._get_cap(context)

        for unit in context.units:
            original_length = len(unit.content)
            if original_length <= cap:
                continue

            unit.content = unit.content[:cap]
            truncation_count += 1
            removed = original_length - cap
            total_chars_removed += removed
            severity = "error" if original_length > cap * 2 else "warning"
            issues.append(
                f"{severity.upper()}: Truncation guard: truncated {unit.id} from "
                f"{original_length} to {cap} chars (removed {removed})"
            )
            actions.append(f"Truncated {unit.id} by {removed} chars")
            evidence_records.append(
                {
                    "category": "truncation",
                    "type": "content_truncated",
                    "severity": severity,
                    "details": {
                        "unit_id": unit.id,
                        "original_length": original_length,
                        "truncated_length": cap,
                        "chars_removed": removed,
                    },
                }
            )

        return StrategyResult(
            units=context.units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "truncation_count": truncation_count,
                "total_chars_removed": total_chars_removed,
                "max_unit_content_length": cap,
            },
            evidence_records=evidence_records,
        )

    def _get_cap(self, context: ProcessingContext) -> int:
        """Resolve max content length from config or defaults."""
        cap = context.config.get("max_unit_content_length")
        if isinstance(cap, int) and cap > 0:
            return cap
        return _DEFAULT_MAX_LENGTH

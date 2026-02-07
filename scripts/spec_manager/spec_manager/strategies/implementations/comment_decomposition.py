"""Comment decomposition strategy for the translation paradigm.

Decomposes multi-concern pseudocode comments into single-concern comments
so each can be translated independently. This is an adaptation of
SentenceDecompositionStrategy for code comments rather than prose TrackedUnits.

Example:
  Input: "# validate payment against fraud rules and send confirmation to customer"
  Output:
    - "# validate payment against fraud rules"
    - "# send confirmation to customer"
"""

from __future__ import annotations

import hashlib
import re

from spec_manager.core.provenance import GranularityLevel, TrackedUnit, UnitType
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)


class CommentDecompositionStrategy(Strategy):
    """Decomposes multi-concern pseudocode comments into single-concern comments.

    Adapted from SentenceDecompositionStrategy for the translation paradigm.
    Operates on pseudocode comments rather than prose TrackedUnits.
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
        self._splitter = self.tools.get("spacy_splitter") or self._simple_comment_split

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "comment_decomposition"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Split multi-concern pseudocode comments into separate single-concern comments"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Translation failure from comments that describe multiple things"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.TRANSLATION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if translation_context has multi-concern comment.

        A comment is multi-concern if it contains conjunctions, semicolons,
        or multiple verb phrases suggesting distinct actions.
        """
        tc = context.translation_context
        if tc is None:
            return False

        comment = tc.comment_text.lower()
        multi_concern_indicators = [" and ", " or ", "; ", ", and ", ", or ", " then "]
        return any(indicator in comment for indicator in multi_concern_indicators)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Split the comment, create separate TrackedUnits per concern."""
        actions: list[str] = []
        issues: list[str] = []
        output_units: list[TrackedUnit] = []

        tc = context.translation_context
        if tc is None:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=["No translation context available"],
                metrics={"splits_performed": 0},
            )

        comment_text = tc.comment_text
        parts = self._splitter(comment_text)

        if len(parts) <= 1:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=[],
                metrics={"splits_performed": 0},
            )

        actions.append(f"Decomposed comment into {len(parts)} single-concern parts")

        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            content_hash = hashlib.sha256(part.encode()).hexdigest()
            unit_id = f"comment_part_{i + 1}_{content_hash[:8]}"

            new_unit = TrackedUnit(
                id=unit_id,
                content=part,
                unit_type=UnitType.PROSE,
                source=context.units[0].source if context.units else None,
                introduced_by="comment_decomposition",
                granularity=GranularityLevel.SENTENCE,
                content_hash=content_hash,
            )

            lineage_table = getattr(context, "lineage_table", None)
            if lineage_table is not None and context.units:
                lineage_table.add_edge(
                    from_unit=context.units[0].id,
                    to_unit=new_unit.id,
                    transformation="split",
                )

            output_units.append(new_unit)

        return StrategyResult(
            units=output_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "input_units": len(context.units),
                "output_units": len(output_units),
                "splits_performed": len(parts),
            },
        )

    @staticmethod
    def _simple_comment_split(comment: str) -> list[str]:
        """Split a comment on conjunctions and semicolons.

        This is a simple heuristic splitter. A spacy_splitter tool
        would produce better results.
        """
        # Strip comment markers
        stripped = re.sub(r"^#\s*", "", comment.strip())

        # Split on semicolons first
        if "; " in stripped:
            parts = [p.strip() for p in stripped.split("; ") if p.strip()]
            if all(len(p.split()) >= 2 for p in parts):
                return [f"# {p}" for p in parts]

        # Split on ' and ' if both parts have substance
        if " and " in stripped.lower() and stripped.lower().count(" and ") == 1:
            parts = re.split(r"\s+and\s+", stripped, flags=re.IGNORECASE)
            if all(len(p.split()) >= 2 for p in parts):
                return [f"# {p.strip()}" for p in parts]

        # Split on ' then '
        if " then " in stripped.lower():
            parts = re.split(r"\s+then\s+", stripped, flags=re.IGNORECASE)
            if all(len(p.split()) >= 2 for p in parts):
                return [f"# {p.strip()}" for p in parts]

        return [comment]

"""Stub promotion strategy for the translation paradigm.

Promotes stub functions with enough context to real implementations.
Checks if a stub (pass/raise NotImplementedError) has enough surrounding
context (docstrings, comments, adjacent implementations) to attempt
translation.
"""

from __future__ import annotations

from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.provenance import TrackedUnit
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)


class StubPromotionStrategy(Strategy):
    """Promotes stub functions with enough context to real implementations.

    Checks if a stub (pass/raise NotImplementedError) has enough surrounding
    context (docstrings, comments, adjacent implementations) to attempt translation.
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
        self._stub_detector = self.tools.get("stub_detector")
        self._context_analyzer = self.tools.get("context_analyzer")

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "stub_promotion"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Promote stub functions with sufficient context into real implementations"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Stubs remain unimplemented despite having enough context to translate"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.TRANSLATION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if function is a stub with surrounding context.

        Uses LLM-based code analysis to detect stubs (language-agnostic).
        Checks for surrounding context that might provide implementation details.
        """
        tc = context.translation_context
        if tc is None:
            return False

        # Use LLM-based analysis to detect stubs (language-agnostic)
        code_to_analyze = "\n".join(tc.surrounding_code)
        analysis = analyze_source(
            content=code_to_analyze,
            filepath=tc.file_path or "unknown",
        )

        # Check if any function in the surrounding code is a stub
        has_stub = any(func.is_stub for func in analysis.functions)

        if not has_stub:
            return False

        # Check for context that could guide implementation
        has_context = bool(tc.comment_text.strip()) or bool(tc.function_signature)
        return has_context

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Gather context, produce translation-ready augmented context."""
        actions: list[str] = []
        issues: list[str] = []
        evidence_records: list[dict[str, object]] = []

        tc = context.translation_context
        if tc is None:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=["No translation context available"],
                metrics={"stubs_promoted": 0},
            )

        # Gather all available context for the stub
        context_pieces: list[str] = []

        if tc.function_signature:
            context_pieces.append(f"Function signature: {tc.function_signature}")

        if tc.comment_text:
            context_pieces.append(f"Comment: {tc.comment_text}")

        # Use LLM-based analysis to collect comments and docstrings (language-agnostic)
        code_to_analyze = "\n".join(tc.surrounding_code)
        analysis = analyze_source(
            content=code_to_analyze,
            filepath=tc.file_path or "unknown",
        )

        # Add detected comments
        for comment in analysis.comments:
            context_pieces.append(f"Context: {comment.text}")

        # Add docstrings from functions
        for func in analysis.functions:
            if func.has_docstring and func.docstring:
                context_pieces.append(f"Context: {func.docstring}")

        # Use tools if available
        if self._stub_detector:
            try:
                detection = self._stub_detector(
                    code="\n".join(tc.surrounding_code),
                    function_signature=tc.function_signature,
                )
                if detection:
                    context_pieces.append(f"Stub detection: {detection}")
            except Exception as exc:
                issues.append(f"Stub detection failed: {exc}")

        if self._context_analyzer:
            try:
                analysis = self._context_analyzer(
                    context_pieces=context_pieces,
                    neighbors=tc.call_graph_neighbors,
                )
                if analysis:
                    context_pieces.append(f"Context analysis: {analysis}")
            except Exception as exc:
                issues.append(f"Context analysis failed: {exc}")

        promotable = len(context_pieces) >= 2  # Need at least signature + comment

        output_units: list[TrackedUnit] = []
        if promotable:
            actions.append(
                f"Stub promotion candidate identified with {len(context_pieces)} context pieces"
            )
            evidence_records.append(
                {
                    "category": "stub_promotion",
                    "type": "promotion_candidate",
                    "severity": "info",
                    "details": {
                        "function_signature": tc.function_signature,
                        "context_count": len(context_pieces),
                        "file_path": tc.file_path,
                        "line_number": tc.line_number,
                    },
                }
            )

            # Create augmented units with gathered context
            for unit in context.units:
                augmented_content = (
                    unit.content + "\n\n[Stub promotion context]:\n" + "\n".join(context_pieces)
                )
                new_unit = unit.derive(
                    augmented_content,
                    new_id=f"{unit.id}_promoted",
                    modifier="stub_promotion",
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
            issues.append("Insufficient context to promote stub")
            output_units = list(context.units)

        return StrategyResult(
            units=output_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "stubs_promoted": 1 if promotable else 0,
                "context_pieces": len(context_pieces),
            },
            evidence_records=evidence_records,
        )

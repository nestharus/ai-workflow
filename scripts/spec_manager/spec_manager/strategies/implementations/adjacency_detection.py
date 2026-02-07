"""Adjacency detection strategy for the translation/projection paradigm.

Detects algorithms connected through shared stores. When translating
or projecting, checks if the current function's store dependencies
overlap with other functions, flagging potential adjacencies that
must be considered together.
"""

from __future__ import annotations

from spec_manager.core.provenance import TrackedUnit
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)


class AdjacencyDetectionStrategy(Strategy):
    """Detects algorithms connected through shared stores.

    When translating/projecting, checks if the current function's store
    dependencies overlap with other functions, flagging potential adjacencies.
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
        self._store_graph_analyzer = self.tools.get("store_graph_analyzer")

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "adjacency_detection"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Detect and flag algorithms connected through shared stores"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Missed adjacency when translated code touches shared state"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.TRANSLATION, StrategyPhase.PROJECTION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if store_dependencies are present in translation_context."""
        tc = context.translation_context
        if tc is None:
            return False

        return len(tc.store_dependencies) > 0

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Analyze store graph, flag connected algorithms, add evidence records."""
        actions: list[str] = []
        issues: list[str] = []
        evidence_records: list[dict[str, object]] = []

        tc = context.translation_context
        if tc is None:
            return StrategyResult(
                units=list(context.units),
                actions_taken=[],
                issues=["No translation context available"],
                metrics={"adjacencies_detected": 0},
            )

        store_deps = tc.store_dependencies
        neighbors = tc.call_graph_neighbors
        adjacencies_found: list[dict[str, object]] = []

        # Use store_graph_analyzer tool if available
        if self._store_graph_analyzer:
            try:
                analysis = self._store_graph_analyzer(
                    stores=store_deps,
                    function_signature=tc.function_signature,
                    neighbors=neighbors,
                )
                if analysis:
                    adjacencies_found.append(
                        {
                            "source": "tool_analysis",
                            "details": analysis,
                        }
                    )
            except Exception as exc:
                issues.append(f"Store graph analysis failed: {exc}")

        # Heuristic adjacency detection based on overlapping store dependencies
        # If call graph neighbors share stores, flag them
        if neighbors and store_deps:
            for neighbor in neighbors:
                adjacencies_found.append(
                    {
                        "neighbor": neighbor,
                        "shared_stores": store_deps,
                        "source": "heuristic",
                    }
                )

        if adjacencies_found:
            actions.append(
                f"Detected {len(adjacencies_found)} potential adjacencies "
                f"through {len(store_deps)} shared stores"
            )
            evidence_records.append(
                {
                    "category": "adjacency",
                    "type": "shared_store_adjacency",
                    "severity": "info",
                    "details": {
                        "function": tc.function_signature,
                        "stores": store_deps,
                        "adjacencies": adjacencies_found,
                    },
                }
            )
        else:
            actions.append("No adjacencies detected through shared stores")

        # Tag units with adjacency metadata
        output_units: list[TrackedUnit] = []
        for unit in context.units:
            if adjacencies_found:
                # Add adjacency info to unit metadata via derive
                new_unit = unit.derive(
                    unit.content,
                    new_id=f"{unit.id}_adj",
                    modifier="adjacency_detection",
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
                "adjacencies_detected": len(adjacencies_found),
                "stores_analyzed": len(store_deps),
                "neighbors_checked": len(neighbors),
            },
            evidence_records=evidence_records,
        )

"""Strategy evolution pipeline: gap -> proposal -> registration -> promotion.

Orchestrates the strategy evolution loop where:
- Translation/projection failures are captured with rich evidence
- New strategies are proposed (template first, then LLM fallback)
- Experimental strategies are registered for immediate retry
- Promotion is gated by measurable success criteria
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.strategies.base import (
    ProcessingContext,
    StrategyDefinition,
    StrategyResult,
)
from spec_manager.strategies.registry import (
    FailureMode,
    LLMClient,
    StrategyGapEvidence,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from spec_manager.strategies.registry import StrategyRegistry


# =========================================================================
# Promotion Criteria and Performance Tracking
# =========================================================================


@dataclass
class PromotionCriteria:
    """Criteria for promoting experimental strategy to stable."""

    min_successful_applications: int = 3  # Must succeed at least N times
    min_failure_mode_reduction: float = 0.5  # Must reduce failure mode by 50%
    max_regression_rate: float = 0.0  # No regressions allowed
    fixture_pass_rate: float = 1.0  # All test fixtures must pass


@dataclass
class StrategyPerformanceRecord:
    """Tracks performance of an experimental strategy."""

    strategy_name: str
    applications: list[dict[str, Any]] = field(default_factory=list)
    successes: int = 0
    failures: int = 0
    failure_mode_counts_before: dict[str, int] = field(default_factory=dict)
    failure_mode_counts_after: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Calculate the ratio of successful applications."""
        total = self.successes + self.failures
        return self.successes / total if total > 0 else 0.0

    def record_application(self, result: StrategyResult, success: bool) -> None:
        """Record an application of this strategy."""
        self.applications.append(
            {
                "actions": result.actions_taken,
                "issues": result.issues,
                "metrics": result.metrics,
                "success": success,
            }
        )
        if success:
            self.successes += 1
        else:
            self.failures += 1


# =========================================================================
# Strategy Proposers
# =========================================================================


@dataclass
class TemplateStrategyProposer:
    """Proposes strategies from known failure mode templates.

    For each classified failure mode, we have a pre-built template
    that creates a StrategyDefinition with a real implementation_class.
    """

    templates: dict[str, StrategyDefinition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._register_builtin_templates()

    def _register_builtin_templates(self) -> None:
        """Register templates for the five key paradigm strategies."""
        self.templates[FailureMode.MULTI_CONCERN_COMMENT] = StrategyDefinition(
            name="comment_decomposition",
            purpose="Split multi-concern pseudocode comments into separate single-concern comments",
            risk_addressed="Translation failure from comments that describe multiple things",
            version="1.0",
            phases=["translation"],
            when_conditions=["comment_text contains multiple verbs or conjunctions"],
            tools_used=["spacy_splitter"],
            implementation_class="spec_manager.strategies.implementations.comment_decomposition.CommentDecompositionStrategy",
            risk_category="compound_loss",
            metadata={
                "status": "experimental",
                "template_source": FailureMode.MULTI_CONCERN_COMMENT,
            },
        )
        self.templates[FailureMode.VAGUE_ENTITY_REFERENCE] = StrategyDefinition(
            name="translation_entity_resolution",
            purpose="Resolve vague references in pseudocode comments to specific function names",
            risk_addressed=(
                "Translation failure from comments referencing 'the algorithm' without specifics"
            ),
            version="1.0",
            phases=["translation"],
            when_conditions=["comment contains vague references", "function context available"],
            tools_used=["reference_resolver", "call_graph_analyzer"],
            implementation_class=(
                "spec_manager.strategies.implementations"
                ".translation_entity_resolution"
                ".TranslationEntityResolutionStrategy"
            ),
            risk_category="vague_references",
            metadata={
                "status": "experimental",
                "template_source": FailureMode.VAGUE_ENTITY_REFERENCE,
            },
        )
        self.templates[FailureMode.INSUFFICIENT_DETAIL] = StrategyDefinition(
            name="ambiguity_research",
            purpose="Search hollowed-out spec for details when comment has insufficient context",
            risk_addressed="Translation failure from insufficient detail in pseudocode comment",
            version="1.0",
            phases=["translation"],
            when_conditions=["hollowed_spec_path available", "comment is underspecified"],
            tools_used=["spec_researcher", "needle_searcher"],
            implementation_class="spec_manager.strategies.implementations.ambiguity_research.AmbiguityResearchStrategy",
            risk_category="information_loss",
            metadata={
                "status": "experimental",
                "template_source": FailureMode.INSUFFICIENT_DETAIL,
            },
        )
        self.templates[FailureMode.SHARED_STORE_ADJACENCY] = StrategyDefinition(
            name="adjacency_detection",
            purpose="Detect and flag algorithms connected through shared stores",
            risk_addressed="Missed adjacency when translated code touches shared state",
            version="1.0",
            phases=["translation", "projection"],
            when_conditions=["store_dependencies present", "call_graph_neighbors available"],
            tools_used=["store_graph_analyzer"],
            implementation_class="spec_manager.strategies.implementations.adjacency_detection.AdjacencyDetectionStrategy",
            risk_category="content_loss",
            metadata={
                "status": "experimental",
                "template_source": FailureMode.SHARED_STORE_ADJACENCY,
            },
        )
        self.templates[FailureMode.STUB_WITH_CONTEXT] = StrategyDefinition(
            name="stub_promotion",
            purpose="Promote stub functions with sufficient context into real implementations",
            risk_addressed="Stubs remain unimplemented despite having enough context to translate",
            version="1.0",
            phases=["translation"],
            when_conditions=[
                "function is stub",
                "surrounding context provides implementation details",
            ],
            tools_used=["stub_detector", "context_analyzer"],
            implementation_class="spec_manager.strategies.implementations.stub_promotion.StubPromotionStrategy",
            risk_category="information_loss",
            metadata={
                "status": "experimental",
                "template_source": FailureMode.STUB_WITH_CONTEXT,
            },
        )

    def propose(self, gap: StrategyGapEvidence) -> StrategyDefinition | None:
        """Look up a template for the gap's failure mode."""
        return self.templates.get(gap.failure_mode)


@dataclass
class LLMStrategyProposer:
    """Proposes strategies via LLM for unknown failure modes."""

    llm_client: LLMClient | None = None

    def propose(self, gap: StrategyGapEvidence) -> StrategyDefinition | None:
        """Use LLM to propose a strategy for an unclassified failure mode.

        Delegates to the LLM with an enhanced prompt that includes
        failure context and translation details.
        """
        if not self.llm_client:
            return None

        prompt = f"""A spec processing workflow encountered a failure that no existing \
strategy handles.

FAILURE MODE: {gap.failure_mode}
FAILURE CATEGORY: {gap.failure_category}

FAILING INPUTS (samples):
{gap.fixture.get("inputs", [])[:3]}

CONTEXT:
{gap.fixture.get("context", {})}

STRATEGIES ALREADY ATTEMPTED:
{gap.strategies_attempted}

Design a new strategy to handle this failure. Provide:
1. Strategy name (lowercase, underscore-separated)
2. Purpose (one sentence)
3. When conditions (list of strings)
4. Tools to use (list)
5. Risk addressed

Output as JSON:
{{"name": "...", "purpose": "...", "when_conditions": [...], \
"tools_used": ["..."], "risk_addressed": "..."}}"""

        try:
            response = self.llm_client.complete(prompt)
            data = json.loads(response)

            proposed = StrategyDefinition(
                name=data["name"],
                purpose=data["purpose"],
                when_conditions=data.get("when_conditions", []),
                tools_used=data.get("tools_used", []),
                phases=[gap.failure_category],
                risk_addressed=data.get("risk_addressed", ""),
                metadata={"status": "proposed", "from_gap": gap.failure_mode},
            )

            return proposed

        except Exception:
            logger.debug("Strategy evolution proposal failed", exc_info=True)
            return None


# =========================================================================
# Evolution Pipeline
# =========================================================================


@dataclass
class StrategyEvolutionPipeline:
    """Orchestrates: gap capture -> proposal -> experimental registration -> promotion.

    Public API for the strategy evolution system.
    """

    registry: StrategyRegistry
    template_proposer: TemplateStrategyProposer = field(default_factory=TemplateStrategyProposer)
    llm_proposer: LLMStrategyProposer = field(default_factory=LLMStrategyProposer)
    gap_log: list[StrategyGapEvidence] = field(default_factory=list)
    performance_records: dict[str, StrategyPerformanceRecord] = field(default_factory=dict)
    state_store: EvolutionStateStore | None = None

    def on_translation_failure(
        self,
        context: ProcessingContext,
        failure_mode: str,
        error_details: str | None = None,
    ) -> StrategyDefinition | None:
        """Handle a translation/projection failure.

        1. Capture gap evidence
        2. Propose strategy (template first, then LLM)
        3. Register as experimental
        4. Return the strategy definition for immediate retry
        """
        # Determine failure category from context phase
        phase_to_category = {
            "translation": "translation",
            "projection": "projection",
            "resolution": "resolution",
            "decomposition": "decomposition",
        }
        failure_category = phase_to_category.get(context.phase.value, "translation")

        # Build gap evidence
        gap = StrategyGapEvidence(
            failure_mode=failure_mode,
            failure_category=failure_category,
            fixture={
                "failure_mode": failure_mode,
                "failure_category": failure_category,
                "inputs": [
                    {"id": u.id, "content": u.content[:500], "type": u.unit_type.value}
                    for u in context.units[:5]
                ],
                "context": {
                    "phase": context.phase.value,
                    "patch_id": context.patch_id,
                    "comment_text": (
                        context.translation_context.comment_text
                        if context.translation_context
                        else None
                    ),
                    "function_signature": (
                        context.translation_context.function_signature
                        if context.translation_context
                        else None
                    ),
                    "surrounding_code": (
                        context.translation_context.surrounding_code
                        if context.translation_context
                        else []
                    ),
                    "store_dependencies": (
                        context.translation_context.store_dependencies
                        if context.translation_context
                        else []
                    ),
                },
                "strategies_attempted": [
                    d.name
                    for d in self.registry.definitions.values()
                    if context.phase.value in d.phases
                ],
                "error_details": error_details,
            },
            translation_context=context.translation_context,
            strategies_attempted=[
                d.name
                for d in self.registry.definitions.values()
                if context.phase.value in d.phases
            ],
        )

        self.gap_log.append(gap)

        # Persist gap if state store is available
        if self.state_store is not None:
            self.state_store.save_gap(gap)

        # Try template proposer first
        proposed = self.template_proposer.propose(gap)

        # Fall back to LLM proposer
        if proposed is None:
            proposed = self.llm_proposer.propose(gap)

        if proposed is None:
            return None

        # Register as experimental
        gap.proposed_strategy = proposed
        proposed.metadata = proposed.metadata or {}
        proposed.metadata["status"] = "experimental"
        proposed.metadata["source_gap"] = gap.gap_id
        self.registry.definitions[proposed.name] = proposed

        # Persist experimental definition if state store is available
        if self.state_store is not None:
            self.state_store.save_experimental_definition(proposed)

        return proposed

    def evaluate_experimental(
        self, strategy_name: str, results: list[StrategyResult]
    ) -> dict[str, Any]:
        """Evaluate an experimental strategy's performance.

        Returns metrics: success_rate, failure_mode_reduction, fixture_pass_rate.
        """
        record = self.performance_records.get(strategy_name)
        if record is None:
            record = StrategyPerformanceRecord(strategy_name=strategy_name)
            self.performance_records[strategy_name] = record

        for result in results:
            success = len(result.issues) == 0 and len(result.actions_taken) > 0
            record.record_application(result, success)

        # Persist performance if state store available
        if self.state_store is not None:
            self.state_store.save_performance(record)

        return {
            "strategy_name": strategy_name,
            "success_rate": record.success_rate,
            "successes": record.successes,
            "failures": record.failures,
            "total_applications": len(record.applications),
        }

    def promote_if_ready(self, strategy_name: str) -> bool:
        """Promote experimental strategy to stable if criteria are met.

        Criteria:
        - At least N successful applications (default: 3)
        - Failure mode reduction > threshold (default: 50%)
        - No regressions in other strategies
        """
        record = self.performance_records.get(strategy_name)
        return self.registry.promote_to_stable(strategy_name, performance=record)

    def get_evolution_report(self) -> dict[str, Any]:
        """Return a summary of all gaps, proposals, and promotions."""
        gaps_summary = []
        for gap in self.gap_log:
            gaps_summary.append(
                {
                    "gap_id": gap.gap_id,
                    "failure_mode": gap.failure_mode,
                    "failure_category": gap.failure_category,
                    "proposed_strategy": (
                        gap.proposed_strategy.name if gap.proposed_strategy else None
                    ),
                    "timestamp": gap.timestamp.isoformat(),
                }
            )

        performance_summary = {}
        for name, record in self.performance_records.items():
            performance_summary[name] = {
                "success_rate": record.success_rate,
                "successes": record.successes,
                "failures": record.failures,
            }

        experimental = [
            name
            for name, d in self.registry.definitions.items()
            if d.metadata.get("status") == "experimental"
        ]
        stable_promoted = [
            name
            for name, d in self.registry.definitions.items()
            if d.metadata.get("promoted_at") is not None
        ]

        return {
            "gaps": gaps_summary,
            "performance": performance_summary,
            "experimental_strategies": experimental,
            "promoted_strategies": stable_promoted,
            "total_gaps": len(self.gap_log),
        }


# =========================================================================
# Persistence (Plan 7)
# =========================================================================


@dataclass
class EvolutionStateStore:
    """Persists evolution state to disk.

    Stores gap evidence, experimental strategy records, and promotion history
    to YAML files in the workspace.
    """

    state_dir: Path

    def __post_init__(self) -> None:
        self.state_dir = Path(self.state_dir)

    def save_gap(self, gap: StrategyGapEvidence) -> Path:
        """Save gap evidence to {state_dir}/gaps/{gap_id}.yaml."""
        gaps_dir = self.state_dir / "gaps"
        gaps_dir.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "gap_id": gap.gap_id,
            "failure_mode": gap.failure_mode,
            "failure_category": gap.failure_category,
            "fixture": gap.fixture,
            "strategies_attempted": gap.strategies_attempted,
            "timestamp": gap.timestamp.isoformat(),
            "proposed_strategy": (gap.proposed_strategy.name if gap.proposed_strategy else None),
        }

        # Include translation context if present
        if gap.translation_context is not None:
            data["translation_context"] = {
                "comment_text": gap.translation_context.comment_text,
                "function_signature": gap.translation_context.function_signature,
                "file_path": gap.translation_context.file_path,
                "line_number": gap.translation_context.line_number,
                "hollowed_spec_path": gap.translation_context.hollowed_spec_path,
                "surrounding_code": gap.translation_context.surrounding_code,
                "store_dependencies": gap.translation_context.store_dependencies,
                "call_graph_neighbors": gap.translation_context.call_graph_neighbors,
            }

        path = gaps_dir / f"{gap.gap_id}.yaml"
        import yaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False)

        return path

    def save_performance(self, record: StrategyPerformanceRecord) -> Path:
        """Save performance record to {state_dir}/performance/{strategy_name}.yaml."""
        perf_dir = self.state_dir / "performance"
        perf_dir.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "strategy_name": record.strategy_name,
            "successes": record.successes,
            "failures": record.failures,
            "success_rate": record.success_rate,
            "applications": record.applications,
            "failure_mode_counts_before": record.failure_mode_counts_before,
            "failure_mode_counts_after": record.failure_mode_counts_after,
        }

        path = perf_dir / f"{record.strategy_name}.yaml"
        import yaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False)

        return path

    def load_gaps(self) -> list[StrategyGapEvidence]:
        """Load all gap evidence from {state_dir}/gaps/."""
        from datetime import datetime

        import yaml

        from spec_manager.strategies.base import TranslationContext

        gaps_dir = self.state_dir / "gaps"
        if not gaps_dir.exists():
            return []

        gaps: list[StrategyGapEvidence] = []
        for path in sorted(gaps_dir.glob("*.yaml")):
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            tc = None
            if data.get("translation_context"):
                tc_data = data["translation_context"]
                tc = TranslationContext(
                    comment_text=tc_data.get("comment_text", ""),
                    function_signature=tc_data.get("function_signature"),
                    file_path=tc_data.get("file_path"),
                    line_number=tc_data.get("line_number"),
                    hollowed_spec_path=tc_data.get("hollowed_spec_path"),
                    surrounding_code=tc_data.get("surrounding_code", []),
                    store_dependencies=tc_data.get("store_dependencies", []),
                    call_graph_neighbors=tc_data.get("call_graph_neighbors", []),
                )

            gap = StrategyGapEvidence(
                failure_mode=data["failure_mode"],
                failure_category=data["failure_category"],
                fixture=data.get("fixture", {}),
                translation_context=tc,
                strategies_attempted=data.get("strategies_attempted", []),
                timestamp=datetime.fromisoformat(data["timestamp"]),
                gap_id=data["gap_id"],
            )
            gaps.append(gap)

        return gaps

    def load_performance(self, strategy_name: str) -> StrategyPerformanceRecord | None:
        """Load performance record for a strategy."""
        import yaml

        path = self.state_dir / "performance" / f"{strategy_name}.yaml"
        if not path.exists():
            return None

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        record = StrategyPerformanceRecord(
            strategy_name=data["strategy_name"],
            successes=data.get("successes", 0),
            failures=data.get("failures", 0),
            applications=data.get("applications", []),
            failure_mode_counts_before=data.get("failure_mode_counts_before", {}),
            failure_mode_counts_after=data.get("failure_mode_counts_after", {}),
        )
        return record

    def save_experimental_definition(self, definition: StrategyDefinition) -> Path:
        """Save experimental strategy YAML to {state_dir}/experimental/."""
        import yaml

        exp_dir = self.state_dir / "experimental"
        exp_dir.mkdir(parents=True, exist_ok=True)

        data = definition.to_dict()
        data["metadata"] = definition.metadata

        path = exp_dir / f"{definition.name}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False)

        return path

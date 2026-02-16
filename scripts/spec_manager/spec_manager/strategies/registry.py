"""Strategy registry - manages available strategies.

The registry:
- Loads strategy definitions from YAML
- Provides strategies that apply to a given context
- Allows adding new strategies at runtime
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

if TYPE_CHECKING:
    from spec_manager.strategies.evolution import (
        StrategyEvolutionPipeline,
        StrategyPerformanceRecord,
    )

from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    Tool,
    TranslationContext,
)

logger = logging.getLogger(__name__)


class FailureMode:
    """Classified failure modes that trigger strategy evolution."""

    MULTI_CONCERN_COMMENT = "multi_concern_comment"  # Comment describes multiple things
    VAGUE_ENTITY_REFERENCE = "vague_entity_reference"  # "the algorithm" without specifics
    INSUFFICIENT_DETAIL = "insufficient_detail"  # Not enough info to translate
    SHARED_STORE_ADJACENCY = "shared_store_adjacency"  # Missed connected algorithm
    STUB_WITH_CONTEXT = "stub_with_context"  # Stub has enough info to implement
    CONFLICTING_REQUIREMENTS = "conflicting_requirements"  # Contradictory spec elements
    UNKNOWN_PROJECTION_TYPE = "unknown_projection_type"  # No known projection pattern applies


@dataclass
class StrategyGapEvidence:
    """Evidence for a strategy gap -- no strategy could handle this failure mode.

    This is a FIRST-CLASS evidence type that triggers strategy evolution.
    """

    failure_mode: str  # Classified failure type
    failure_category: str  # "translation" | "projection" | "resolution" | "decomposition"
    fixture: dict[str, Any]  # Minimal failing fixture (rich format)
    translation_context: TranslationContext | None = None  # If translation failure
    strategies_attempted: list[str] = field(default_factory=list)
    proposed_strategy: StrategyDefinition | None = None
    proposed_strategy_name: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    gap_id: str = ""  # Unique ID for tracking (auto-generated)

    def __post_init__(self) -> None:
        """Generate unique gap ID if not provided."""
        if self.proposed_strategy is not None and self.proposed_strategy_name is None:
            self.proposed_strategy_name = self.proposed_strategy.name
        if not self.gap_id:
            content = f"{self.failure_mode}:{self.failure_category}:{self.timestamp.isoformat()}"
            self.gap_id = f"gap_{hashlib.sha256(content.encode()).hexdigest()[:12]}"

    @property
    def severity(self) -> str:
        """Evidence severity level."""
        return "warning"

    @property
    def message(self) -> str:
        """Human-readable message describing the gap."""
        return f"Strategy gap: {self.failure_mode}"

    @property
    def location(self) -> str:
        """Location identifier for the failed context."""
        return self.fixture.get("context", {}).get("patch_id", "unknown")


# Maps risk categories to the evidence_summary keys they depend on.
# A strategy is only considered if its risk category's evidence exceeds the threshold.
_RISK_TO_EVIDENCE: dict[str, str] = {
    "compound_loss": "prose_ratio",
    "content_loss": "remainder_ratio",
    "information_loss": "prose_ratio",
    "vague_references": "unresolved_references",
    "low_confidence": "low_confidence_mappings",
}

# Default thresholds per risk category. Strategies whose evidence is at or below
# this level are skipped (the risk is not present enough to warrant running them).
# Phase 5: vague_references threshold set to 0 to trigger on any unresolved refs
_DEFAULT_RISK_THRESHOLDS: dict[str, float] = {
    "compound_loss": 0.1,
    "content_loss": 0.01,
    "information_loss": 0.1,
    "vague_references": 0.0,  # Phase 5: trigger on any unresolved references
    "low_confidence": 1.0,
}


class LLMClient(Protocol):
    """Protocol for LLM clients used in strategy proposal."""

    def complete(self, prompt: str) -> str:
        """Return the LLM completion for the given prompt."""
        ...


class StrategyRegistry:
    """Registry of available strategies.

    Usage:
        registry = StrategyRegistry()
        registry.load_from_directory(Path("strategies/definitions"))

        # Get strategies for a context
        context = ProcessingContext(units=my_units, phase=StrategyPhase.CLEANING)
        applicable = registry.get_applicable(context)

        # Execute each
        for strategy in applicable:
            result = strategy.execute(context)
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self.definitions: dict[str, StrategyDefinition] = {}
        self.strategies: dict[str, Strategy] = {}
        self.tools: dict[str, Tool] = {}
        self.evolution_pipeline: StrategyEvolutionPipeline | None = None
        self.degraded_events: list[dict[str, str]] = []

    def _record_degraded_event(self, stage: str, detail: str) -> None:
        self.degraded_events.append({"stage": stage, "detail": detail})

    @property
    def is_degraded(self) -> bool:
        """Whether any recoverable load/applicability failures have occurred."""
        return bool(self.degraded_events)

    def register_definition(
        self,
        definition: StrategyDefinition,
        *,
        source: str,
        allow_overwrite: bool = False,
    ) -> None:
        """Store a strategy definition with centralized validation."""
        if not definition.name.strip():
            raise ValueError(f"Invalid strategy name from {source!r}")

        existing = self.definitions.get(definition.name)
        if existing is not None and not allow_overwrite:
            raise ValueError(
                f"Strategy '{definition.name}' already exists; refusing overwrite from {source}"
            )

        self.definitions[definition.name] = definition
        # Strategy instances are keyed by definition name and must be rebuilt after updates.
        self.strategies.pop(definition.name, None)

    def enable_evolution(self, llm_client: LLMClient | None = None) -> None:
        """Enable the strategy evolution pipeline."""
        from spec_manager.strategies.evolution import (
            LLMStrategyProposer,
            StrategyEvolutionPipeline,
            TemplateStrategyProposer,
        )

        self.evolution_pipeline = StrategyEvolutionPipeline(
            registry=self,
            template_proposer=TemplateStrategyProposer(),
            llm_proposer=LLMStrategyProposer(llm_client=llm_client),
        )

    def register_tool(self, name: str, tool: Tool) -> None:
        """Register a tool that strategies can use."""
        self.tools[name] = tool

    def load_definition(self, path: Path) -> StrategyDefinition:
        """Load a strategy definition from YAML file."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        definition = StrategyDefinition(
            name=data["name"],
            version=data.get("version", "1.0"),
            purpose=data["purpose"],
            risk_addressed=data["risk_addressed"],
            phases=data.get("phases", []),
            when_conditions=data.get("when_conditions", []),
            risk_category=data.get("risk_category"),
            tools_used=data.get("tools_used", []),
            implementation_class=data.get("implementation_class"),
            example_input=data.get("example", {}).get("input")
            if isinstance(data.get("example"), dict)
            else None,
            example_output=data.get("example", {}).get("output")
            if isinstance(data.get("example"), dict)
            else None,
            metadata=data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        )

        self.register_definition(
            definition,
            source=f"load_definition:{path}",
            allow_overwrite=False,
        )
        return definition

    def load_from_directory(self, directory: Path) -> int:
        """Load all strategy definitions from a directory. Returns count."""
        count = 0
        if not directory.exists():
            return count

        for path in directory.glob("*.yaml"):
            try:
                self.load_definition(path)
                count += 1
            except Exception as e:
                message = f"Failed to load strategy definition from {path}: {e}"
                logger.warning(message, exc_info=True)
                self._record_degraded_event("load_from_directory", message)
        return count

    def instantiate(self, name: str) -> Strategy:
        """Instantiate a strategy from its definition.

        Raises ValueError if the strategy is unknown or has no implementation_class.
        """
        if name in self.strategies:
            return self.strategies[name]

        if name not in self.definitions:
            raise ValueError(f"Unknown strategy: {name}")

        definition = self.definitions[name]
        if not definition.implementation_class:
            raise ValueError(
                f"Strategy '{name}' has no implementation_class and cannot be instantiated"
            )

        strategy = definition.to_strategy(self.tools)
        self.strategies[name] = strategy
        return strategy

    def get_applicable(self, context: ProcessingContext) -> list[Strategy]:
        """Get all strategies that apply to the given context.

        Gating order:
        1. Phase match (existing)
        2. Evidence/threshold gating - skip if the strategy's risk category
           has evidence below the configured threshold
        3. Strategy-level applies_to check (existing)
        """
        applicable = []
        risk_thresholds: dict[str, float] = context.config.get("risk_thresholds", {})

        for name, definition in self.definitions.items():
            # 1. Check phase match
            phase_match = not definition.phases or context.phase.value in definition.phases

            if not phase_match:
                continue

            # 2. Evidence/threshold gating
            if not self._risk_exceeds_threshold(definition, context, risk_thresholds):
                continue

            # 3. Skip definitions without an implementation class
            if not definition.implementation_class:
                continue

            # 4. Instantiate and check applies_to
            try:
                strategy = self.instantiate(name)
                if strategy.applies_to(context):
                    applicable.append(strategy)
            except Exception as e:
                message = f"Failed applicability check for strategy '{name}': {e}"
                logger.warning(message, exc_info=True)
                self._record_degraded_event("get_applicable", message)

        return applicable

    def _risk_exceeds_threshold(
        self,
        definition: StrategyDefinition,
        context: ProcessingContext,
        risk_thresholds: dict[str, float],
    ) -> bool:
        """Check whether evidence justifies running this strategy.

        Returns True (allow strategy) when:
        - The definition has no risk_category (ungated, always eligible)
        - The context has no evidence_summary (no data to gate on)
        - The evidence level for the risk category exceeds the threshold
        """
        risk_category = definition.risk_category
        if not risk_category:
            return True

        if not context.evidence_summary:
            return True

        evidence_key = _RISK_TO_EVIDENCE.get(risk_category)
        if not evidence_key:
            return True

        evidence_level = context.evidence_summary.get(evidence_key)
        if evidence_level is None:
            return True

        threshold = risk_thresholds.get(
            risk_category, _DEFAULT_RISK_THRESHOLDS.get(risk_category, 0.0)
        )
        return evidence_level > threshold

    def add_strategy(
        self,
        definition: StrategyDefinition,
        *,
        source: str = "runtime",
        allow_overwrite: bool = False,
    ) -> None:
        """Add a new strategy definition at runtime."""
        self.register_definition(
            definition,
            source=source,
            allow_overwrite=allow_overwrite,
        )

    def save_definition(self, name: str, path: Path) -> None:
        """Save a strategy definition to YAML."""
        if name not in self.definitions:
            raise ValueError(f"Unknown strategy: {name}")

        definition = self.definitions[name]
        data = definition.to_dict()

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False)

    def list_strategies(self) -> list[dict[str, Any]]:
        """List all available strategies with summary info."""
        return [
            {
                "name": d.name,
                "purpose": d.purpose,
                "phases": d.phases,
                "tools": d.tools_used,
                "status": (d.metadata or {}).get("status", "stable"),  # stable/experimental
            }
            for d in self.definitions.values()
        ]

    @staticmethod
    def _extract_failure_mode_reduction(
        performance: StrategyPerformanceRecord,
    ) -> float | None:
        total_before = sum(performance.failure_mode_counts_before.values())
        total_after = sum(performance.failure_mode_counts_after.values())
        if total_before <= 0:
            return None
        return (total_before - total_after) / total_before

    @staticmethod
    def _extract_regression_rate(
        performance: StrategyPerformanceRecord,
    ) -> float | None:
        if not performance.applications:
            return None

        rates: list[float] = []
        for app in performance.applications:
            metrics = app.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            explicit_rate = metrics.get("regression_rate")
            if isinstance(explicit_rate, int | float):
                rates.append(float(explicit_rate))
                continue
            if "regression" in metrics:
                rates.append(1.0 if bool(metrics["regression"]) else 0.0)

        if not rates:
            return None
        return sum(rates) / len(rates)

    @staticmethod
    def _extract_fixture_pass_rate(
        performance: StrategyPerformanceRecord,
    ) -> float | None:
        if not performance.applications:
            return None

        rates: list[float] = []
        for app in performance.applications:
            metrics = app.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            explicit_rate = metrics.get("fixture_pass_rate")
            if isinstance(explicit_rate, int | float):
                rates.append(float(explicit_rate))
                continue
            if "fixture_passed" in metrics:
                rates.append(1.0 if bool(metrics["fixture_passed"]) else 0.0)

        if not rates:
            return None
        return sum(rates) / len(rates)

    def promote_to_stable(
        self, name: str, performance: StrategyPerformanceRecord | None = None
    ) -> bool:
        """Promote an experimental strategy to stable after validation.

        When performance record is provided, validates against PromotionCriteria.
        """
        if name not in self.definitions:
            return False

        definition = self.definitions[name]
        if definition.metadata.get("status") != "experimental":
            return False

        from spec_manager.strategies.evolution import PromotionCriteria

        criteria = PromotionCriteria()
        if performance is None:
            return False

        failure_mode_reduction = self._extract_failure_mode_reduction(performance)
        regression_rate = self._extract_regression_rate(performance)
        fixture_pass_rate = self._extract_fixture_pass_rate(performance)
        if failure_mode_reduction is None or regression_rate is None or fixture_pass_rate is None:
            return False

        if performance.successes < criteria.min_successful_applications:
            return False
        if failure_mode_reduction < criteria.min_failure_mode_reduction:
            return False
        if regression_rate > criteria.max_regression_rate:
            return False
        if fixture_pass_rate < criteria.fixture_pass_rate:
            return False

        definition.metadata["status"] = "stable"
        definition.metadata["promoted_at"] = datetime.now().isoformat()
        definition.metadata["promotion_evidence"] = {
            "successes": performance.successes,
            "success_rate": performance.success_rate,
            "failure_mode_reduction": failure_mode_reduction,
            "regression_rate": regression_rate,
            "fixture_pass_rate": fixture_pass_rate,
        }
        return True

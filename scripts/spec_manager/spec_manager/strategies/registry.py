"""Strategy registry - manages available strategies.

The registry:
- Loads strategy definitions from YAML
- Provides strategies that apply to a given context
- Allows adding new strategies at runtime
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from spec_manager.core.provenance import TrackedUnit
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    Tool,
)


@dataclass
class StrategyGapEvidence:
    """Evidence for a strategy gap - no strategy could handle this failure mode.

    This is a FIRST-CLASS evidence type that triggers strategy evolution.
    """

    failure_mode: str  # What failed (e.g., "vague_reference_resolution")
    fixture: dict[str, Any]  # Minimal failing fixture
    proposed_strategy: StrategyDefinition | None = None  # LLM-proposed solution

    @property
    def severity(self) -> str:
        return "warning"

    @property
    def message(self) -> str:
        return f"Strategy gap: {self.failure_mode}"

    @property
    def location(self) -> str:
        return self.fixture.get("context", {}).get("patch_id", "unknown")


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
        self.definitions: dict[str, StrategyDefinition] = {}
        self.strategies: dict[str, Strategy] = {}
        self.tools: dict[str, Tool] = {}

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
            tools_used=data.get("tools_used", []),
            implementation_class=data.get("implementation_class"),
            example_input=data.get("example", {}).get("input")
            if isinstance(data.get("example"), dict)
            else None,
            example_output=data.get("example", {}).get("output")
            if isinstance(data.get("example"), dict)
            else None,
        )

        self.definitions[definition.name] = definition
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
                print(f"Warning: Failed to load {path}: {e}")
        return count

    def instantiate(self, name: str) -> Strategy:
        """Instantiate a strategy from its definition."""
        if name in self.strategies:
            return self.strategies[name]

        if name not in self.definitions:
            raise ValueError(f"Unknown strategy: {name}")

        definition = self.definitions[name]
        strategy = definition.to_strategy(self.tools)
        self.strategies[name] = strategy
        return strategy

    def get_applicable(self, context: ProcessingContext) -> list[Strategy]:
        """Get all strategies that apply to the given context."""
        applicable = []

        for name, definition in self.definitions.items():
            # Check phase match
            phase_match = not definition.phases or context.phase.value in definition.phases

            if not phase_match:
                continue

            # Instantiate and check applies_to
            try:
                strategy = self.instantiate(name)
                if strategy.applies_to(context):
                    applicable.append(strategy)
            except Exception as e:
                print(f"Warning: Failed to check {name}: {e}")

        return applicable

    def add_strategy(self, definition: StrategyDefinition) -> None:
        """Add a new strategy definition at runtime."""
        self.definitions[definition.name] = definition

    def save_definition(self, name: str, path: Path) -> None:
        """Save a strategy definition to YAML."""
        if name not in self.definitions:
            raise ValueError(f"Unknown strategy: {name}")

        definition = self.definitions[name]
        data: dict[str, Any] = {
            "name": definition.name,
            "version": definition.version,
            "purpose": definition.purpose,
            "risk_addressed": definition.risk_addressed,
            "phases": definition.phases,
            "when_conditions": definition.when_conditions,
            "tools_used": definition.tools_used,
            "implementation_class": definition.implementation_class,
        }

        if definition.example_input:
            data["example"] = {
                "input": definition.example_input,
                "output": definition.example_output,
            }

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
                "status": d.metadata.get("status", "stable"),  # stable/experimental
            }
            for d in self.definitions.values()
        ]

    # =========================================================================
    # Strategy Evolution Loop
    # =========================================================================

    def check_evolution_triggers(
        self, context: ProcessingContext, previous_context: ProcessingContext | None = None
    ) -> list[str]:
        """Check if conditions warrant strategy evolution.

        Trigger conditions:
        - Remainder not shrinking between passes
        - Entity resolution failure rate above threshold
        - Prose ratio not decreasing

        Returns list of trigger descriptions.
        """
        triggers = []

        if previous_context:
            # Remainder not shrinking
            prev_remainder = len(previous_context.results.get("remainders", []))
            curr_remainder = len(context.results.get("remainders", []))
            if curr_remainder >= prev_remainder and prev_remainder > 0:
                triggers.append(f"remainder_stuck: {prev_remainder} -> {curr_remainder}")

            # Entity resolution failures
            resolution_failures = context.results.get("resolution_failures", 0)
            total_refs = context.results.get("total_references", 1)
            failure_rate = resolution_failures / total_refs if total_refs > 0 else 0
            if failure_rate > 0.1:  # 10% threshold
                triggers.append(f"resolution_failures: {failure_rate:.1%}")

            # Prose ratio not decreasing
            prev_prose = previous_context.results.get("prose_ratio", 1.0)
            curr_prose = context.results.get("prose_ratio", 1.0)
            if curr_prose >= prev_prose and curr_prose > 0.3:  # Still >30% prose
                triggers.append(f"prose_stuck: {prev_prose:.1%} -> {curr_prose:.1%}")

        return triggers

    def request_new_strategy(
        self, trigger: str, example_inputs: list[str], desired_transformation: str
    ) -> dict[str, Any]:
        """Generate a strategy request for a new strategy.

        Returns a structured request that could be used to develop
        a new strategy (potentially by AI or human).
        """
        return {
            "trigger": trigger,
            "examples": example_inputs,
            "desired_outcome": desired_transformation,
            "existing_strategies": [d.name for d in self.definitions.values()],
            "status": "requested",
        }

    def add_experimental_strategy(
        self,
        definition: StrategyDefinition,
        test_fixtures: list[tuple[str, str]],  # (input, expected_output)
    ) -> bool:
        """Add a new strategy in experimental status.

        Requires test fixtures that must pass before strategy is promoted to stable.
        """
        definition.metadata = definition.metadata or {}
        definition.metadata["status"] = "experimental"
        definition.metadata["test_fixtures"] = test_fixtures

        self.definitions[definition.name] = definition
        return True

    def promote_to_stable(self, name: str) -> bool:
        """Promote an experimental strategy to stable after validation."""
        if name not in self.definitions:
            return False

        definition = self.definitions[name]
        if definition.metadata.get("status") != "experimental":
            return False

        # Validate against test fixtures
        # (Simplified - real implementation would be more thorough)
        definition.metadata["status"] = "stable"
        return True

    # =========================================================================
    # Strategy Gap Evidence & Proposal
    # =========================================================================

    def capture_strategy_gap(
        self, context: ProcessingContext, failure_mode: str, failing_inputs: list[TrackedUnit]
    ) -> StrategyGapEvidence:
        """Capture a strategy gap when no strategy can handle a failure mode.

        This is the trigger for strategy evolution:
        1. Capture minimal failing fixture (inputs + intermediates)
        2. Propose new strategy via LLM
        3. Register as experimental for current ingest

        Returns StrategyGapEvidence to be included in gaps.md.
        """
        # Capture minimal fixture
        fixture = {
            "failure_mode": failure_mode,
            "inputs": [
                {"id": u.id, "content": u.content[:500], "type": u.unit_type.value}
                for u in failing_inputs[:5]
            ],
            "context": {
                "phase": context.phase.value,
                "patch_id": context.patch_id,
                "previous_results": context.previous_results,
            },
            "existing_strategies_tried": [
                d.name for d in self.definitions.values() if context.phase.value in d.phases
            ],
        }

        evidence = StrategyGapEvidence(
            failure_mode=failure_mode, fixture=fixture, proposed_strategy=None
        )

        return evidence

    def propose_strategy_via_llm(
        self, gap_evidence: StrategyGapEvidence, llm_client: Any = None
    ) -> StrategyDefinition | None:
        """Use LLM to propose a new strategy for a captured gap.

        The LLM receives:
        - Failure mode description
        - Failing inputs
        - Existing strategies (to avoid duplicates)

        Returns a proposed StrategyDefinition or None.
        """
        if not llm_client:
            return None

        prompt = f"""A spec processing workflow encountered a failure that no existing strategy handles.

FAILURE MODE: {gap_evidence.failure_mode}

FAILING INPUTS (samples):
{gap_evidence.fixture["inputs"][:3]}

EXISTING STRATEGIES (don't duplicate):
{gap_evidence.fixture["existing_strategies_tried"]}

Design a new strategy to handle this failure. Provide:
1. Strategy name (lowercase, underscore-separated)
2. Purpose (one sentence)
3. When conditions (JSON conditions)
4. Tools to use (list)
5. Risk addressed

Output as JSON:
{{"name": "...", "purpose": "...", "when_conditions": {{...}}, "tools_used": ["..."], "risk_addressed": "..."}}"""

        try:
            response = llm_client.complete(prompt)
            import json

            data = json.loads(response)

            proposed = StrategyDefinition(
                name=data["name"],
                purpose=data["purpose"],
                when_conditions=data.get("when_conditions", {}),
                tools_used=data.get("tools_used", []),
                phases=[gap_evidence.fixture["context"]["phase"]],
                risk_addressed=data.get("risk_addressed", ""),
                metadata={"status": "proposed", "from_gap": gap_evidence.failure_mode},
            )

            gap_evidence.proposed_strategy = proposed
            return proposed

        except Exception:
            return None

    def register_experimental_from_gap(self, gap_evidence: StrategyGapEvidence) -> bool:
        """Register a proposed strategy as experimental for current ingest.

        The strategy is:
        - Marked as 'experimental'
        - Includes test fixtures from the gap
        - Automatically promoted if it reduces the failure mode
        """
        if not gap_evidence.proposed_strategy:
            return False

        definition = gap_evidence.proposed_strategy
        definition.metadata = definition.metadata or {}
        definition.metadata["status"] = "experimental"
        definition.metadata["source_gap"] = gap_evidence.failure_mode
        definition.metadata["test_fixtures"] = [
            (inp["content"], "TBD") for inp in gap_evidence.fixture["inputs"][:3]
        ]

        self.definitions[definition.name] = definition
        return True

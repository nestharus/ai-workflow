"""Rule definitions with composition patterns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from spec_manager.labyrinth.core.record import InputRecord, OutputRecord
from spec_manager.labyrinth.engine.conditions import ConditionGroup


class CompositionMode(str, Enum):
    """How sub-rules are composed."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"


# Type for rule transform functions
RuleFunction = Callable[[InputRecord], dict[str, Any]]


@dataclass
class Rule:
    """A single processing rule.

    Attributes:
        rule_id: Unique identifier (e.g., 'RULE-L1-0001').
        name: Human-readable domain name (e.g., 'reconcile_ledger_delta').
        group: Rule group for categorization.
        conditions: When this rule should fire.
        transform: Function that processes InputRecord -> output data dict.
        dependencies: Rule IDs that must execute before this one.
        topics: Bus topics this rule subscribes to.
        output_topic: Topic to publish results to.
    """
    rule_id: str
    name: str
    group: str = ""
    conditions: ConditionGroup = field(default_factory=ConditionGroup)
    transform: RuleFunction | None = None
    dependencies: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    output_topic: str = ""

    def evaluate(self, record: InputRecord) -> OutputRecord | None:
        """Evaluate the rule against an input record.

        Returns None if conditions are not met or no transform is defined.
        """
        if not self.conditions.evaluate(record):
            return None

        if self.transform is None:
            return None

        output_data = self.transform(record)
        return OutputRecord(
            record_id=record.record_id,
            source_rule_id=self.rule_id,
            data=output_data,
            applied_rules=[self.rule_id],
        )


@dataclass
class CompositeRule:
    """A rule composed of sub-rules in sequential, parallel, or conditional mode.

    Attributes:
        rule_id: Unique identifier.
        name: Human-readable name.
        mode: How sub-rules are composed.
        sub_rules: List of Rule or CompositeRule instances.
        conditions: Optional top-level conditions.
    """
    rule_id: str
    name: str
    mode: CompositionMode = CompositionMode.SEQUENTIAL
    sub_rules: list[Rule | CompositeRule] = field(default_factory=list)
    conditions: ConditionGroup = field(default_factory=ConditionGroup)

    def evaluate(self, record: InputRecord) -> OutputRecord | None:
        """Evaluate the composite rule."""
        if not self.conditions.evaluate(record):
            return None

        if self.mode == CompositionMode.SEQUENTIAL:
            return self._evaluate_sequential(record)
        elif self.mode == CompositionMode.PARALLEL:
            return self._evaluate_parallel(record)
        elif self.mode == CompositionMode.CONDITIONAL:
            return self._evaluate_conditional(record)
        return None

    def _evaluate_sequential(self, record: InputRecord) -> OutputRecord | None:
        """Execute sub-rules sequentially, feeding output into next input."""
        current_record = record
        all_applied: list[str] = []
        last_output: OutputRecord | None = None

        for sub_rule in self.sub_rules:
            result = sub_rule.evaluate(current_record)
            if result is not None:
                last_output = result
                all_applied.extend(result.applied_rules)
                # Feed output back as enriched input for next rule
                enriched_data = {**current_record.data, **result.data}
                current_record = InputRecord(
                    record_id=record.record_id,
                    data=enriched_data,
                    metadata=current_record.metadata,
                )

        if last_output is not None:
            last_output.applied_rules = all_applied
        return last_output

    def _evaluate_parallel(self, record: InputRecord) -> OutputRecord | None:
        """Execute all sub-rules independently and merge results."""
        merged_data: dict[str, Any] = {}
        all_applied: list[str] = []
        any_matched = False

        for sub_rule in self.sub_rules:
            result = sub_rule.evaluate(record)
            if result is not None:
                any_matched = True
                merged_data.update(result.data)
                all_applied.extend(result.applied_rules)

        if not any_matched:
            return None

        return OutputRecord(
            record_id=record.record_id,
            source_rule_id=self.rule_id,
            data=merged_data,
            applied_rules=all_applied,
        )

    def _evaluate_conditional(self, record: InputRecord) -> OutputRecord | None:
        """Execute first matching sub-rule only."""
        for sub_rule in self.sub_rules:
            result = sub_rule.evaluate(record)
            if result is not None:
                return result
        return None


@dataclass
class RuleChain:
    """An ordered chain of rules with dependency tracking.

    Attributes:
        chain_id: Unique identifier for the chain.
        rules: Ordered list of rules.
    """
    chain_id: str
    rules: list[Rule | CompositeRule] = field(default_factory=list)

    def get_execution_order(self) -> list[Rule | CompositeRule]:
        """Return rules in dependency-resolved order.

        Uses topological sort based on dependencies.
        """
        # Build dependency graph
        rule_map = {}
        for rule in self.rules:
            rule_map[rule.rule_id] = rule

        visited: set[str] = set()
        order: list[Rule | CompositeRule] = []

        def visit(rule_id: str) -> None:
            if rule_id in visited:
                return
            visited.add(rule_id)
            rule = rule_map.get(rule_id)
            if rule is None:
                return
            deps = getattr(rule, "dependencies", [])
            for dep_id in deps:
                visit(dep_id)
            order.append(rule)

        for rule in self.rules:
            visit(rule.rule_id)

        return order

"""Steering script generator for interactive disambiguation.

Generates JSON steering scripts that map ambiguity triggers to
concrete clarifying responses. Used in auto-mode to simulate
interactive specification refinement.
"""

from __future__ import annotations

import random
import re
from typing import Any

from spec_manager.labyrinth.engine.conditions import (
    Condition,
    ConditionGroup,
    LogicOperator,
)
from spec_manager.labyrinth.engine.rule import CompositeRule, Rule
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.wiring import SideEffectChain


class SteeringScriptGenerator:
    """Generates steering scripts for ambiguity resolution."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def generate(
        self,
        level: int,
        rules: list[Rule | CompositeRule],
        integration_points: list[IntegrationPoint],
        chains: list[SideEffectChain],
    ) -> dict[str, Any]:
        """Generate a steering script.

        Returns:
            Steering script as a JSON-serializable dict.
        """
        ambiguities: list[dict[str, Any]] = []
        counter = 0

        # Generate ambiguities for integration points
        for ip in integration_points:
            counter += 1
            ambiguities.append(
                {
                    "ambiguity_id": f"AMB-{counter:03d}",
                    "trigger_patterns": [
                        f"integration.*point.*{re.escape(ip.point_id)}",
                        f"where.*register.*{re.escape(ip.name)}",
                        "where.*rule.*register",
                    ],
                    "question_patterns": [
                        f"where.*{re.escape(ip.point_id)}",
                        f"register.*{re.escape(ip.topic)}",
                    ],
                    "response": (
                        f"Rules should register at {ip.point_id}, "
                        f"subscribing to '{ip.topic}', at position {ip.position}"
                        + (f", after {', '.join(ip.after_rules)}" if ip.after_rules else "")
                        + f". Required rules: {', '.join(ip.required_rules)}."
                    ),
                    "clarifies_rules": list(ip.required_rules),
                    "clarifies_integration_points": [ip.point_id],
                }
            )

        # Generate ambiguities for rule conditions
        for rule in rules:
            if not isinstance(rule, Rule):
                continue
            if not rule.conditions.conditions:
                continue

            counter += 1
            cond_desc = self._describe_conditions(rule.conditions)
            ambiguities.append(
                {
                    "ambiguity_id": f"AMB-{counter:03d}",
                    "trigger_patterns": [
                        f"condition.*{re.escape(rule.name)}",
                        f"when.*{re.escape(rule.name)}.*fire",
                        f"handle.*{re.escape(rule.group)}.*appropriately",
                    ],
                    "question_patterns": [
                        f"condition.*{re.escape(rule.rule_id)}",
                        f"when.*{re.escape(rule.name)}",
                    ],
                    "response": (
                        f"Rule {rule.rule_id} ({rule.name}) should fire when: {cond_desc}. "
                        f"Dependencies: "
                        f"{', '.join(rule.dependencies) if rule.dependencies else 'none'}."
                    ),
                    "clarifies_rules": [rule.rule_id],
                    "clarifies_integration_points": [],
                }
            )

        # Generate ambiguities for side-effect chains
        for chain in chains:
            counter += 1
            ambiguities.append(
                {
                    "ambiguity_id": f"AMB-{counter:03d}",
                    "trigger_patterns": [
                        f"side.*effect.*{re.escape(chain.chain_id)}",
                        f"service.*{re.escape(chain.trigger_topic)}",
                        "logging.*notification.*exist",
                    ],
                    "question_patterns": [
                        f"chain.*{re.escape(chain.chain_id)}",
                        f"trigger.*{re.escape(chain.trigger_topic)}",
                    ],
                    "response": (
                        f"Chain {chain.chain_id} triggers on topic '{chain.trigger_topic}'. "
                        f"Services: {', '.join(chain.services)}. "
                        f"Expected log entries: {', '.join(chain.expected_log_entries)}."
                    ),
                    "clarifies_rules": [],
                    "clarifies_integration_points": [],
                }
            )

        return {
            "level": level,
            "ambiguities": ambiguities,
        }

    def _describe_conditions(self, group: ConditionGroup) -> str:
        """Describe a condition group in natural language."""
        if not group.conditions:
            return "always"

        parts: list[str] = []
        for cond in group.conditions:
            if isinstance(cond, Condition):
                parts.append(f"{cond.field_name} {cond.operator.value} {cond.value}")
            elif isinstance(cond, ConditionGroup):
                parts.append(f"({self._describe_conditions(cond)})")

        joiner = " AND " if group.logic == LogicOperator.AND else " OR "
        return joiner.join(parts)

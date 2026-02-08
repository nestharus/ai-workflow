"""Spec generators: Dense (complete, no ambiguity) and Sparse (with systematic removal).

Dense specs are complete specifications with all information.
Sparse specs systematically remove information to test ambiguity detection.
"""

from __future__ import annotations

import random

from spec_manager.labyrinth.engine.conditions import (
    Condition,
    ConditionGroup,
    LogicOperator,
)
from spec_manager.labyrinth.engine.rule import CompositeRule, Rule
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.wiring import SideEffectChain


class DenseSpecGenerator:
    """Generates complete, unambiguous specifications."""

    def generate(
        self,
        level: int,
        rules: list[Rule | CompositeRule],
        integration_points: list[IntegrationPoint],
        chains: list[SideEffectChain],
        topics: list[str],
    ) -> str:
        """Generate a dense spec markdown document.

        Args:
            level: Complexity level.
            rules: All generated rules.
            integration_points: All integration points.
            chains: All side-effect chains.
            topics: All bus topics.

        Returns:
            Markdown spec string.
        """
        lines: list[str] = []

        # Header
        lines.append(f"# Algorithm Integration Specification - Level {level}")
        lines.append("")

        # Section 1: System Architecture
        lines.append("## 1. System Architecture")
        lines.append("")
        lines.append("The system uses an async message bus for pub/sub communication.")
        lines.append("Rules are executed in a thread pool and dispatch results via bus topics.")
        lines.append(
            "Side-effect services (audit, notification, metrics) subscribe to rule output topics."
        )
        lines.append("")
        lines.append(f"**Bus Topics:** {len(topics)}")
        lines.append(f"**Integration Points:** {len(integration_points)}")
        lines.append(f"**Side Effect Chains:** {len(chains)}")
        lines.append("")

        # Section 2: Existing Rules
        lines.append("## 2. Existing Rules")
        lines.append("")
        lines.append("| Rule ID | Name | Group | Dependencies | Conditions | Output Topic |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for rule in rules:
            if not isinstance(rule, Rule):
                continue
            deps = ", ".join(rule.dependencies) if rule.dependencies else "none"
            conds = self._format_conditions(rule.conditions)
            lines.append(
                f"| {rule.rule_id} | {rule.name} | {rule.group} | "
                f"{deps} | {conds} | {rule.output_topic} |"
            )
        lines.append("")

        # Section 3: New Rules to Integrate
        lines.append("## 3. New Rules to Integrate")
        lines.append("")
        for rule in rules:
            if isinstance(rule, CompositeRule):
                lines.append(f"### {rule.rule_id}: {rule.name}")
                lines.append(f"- **Type:** Composite ({rule.mode.value})")
                lines.append(f"- **Sub-rules:** {', '.join(sr.rule_id for sr in rule.sub_rules)}")
                lines.append(f"- **Conditions:** {self._format_conditions(rule.conditions)}")
                lines.append("")
            elif isinstance(rule, Rule):
                lines.append(f"### {rule.rule_id}: {rule.name}")
                lines.append(f"- **Group:** {rule.group}")
                lines.append(f"- **Conditions:** {self._format_conditions(rule.conditions)}")
                lines.append(
                    f"- **Dependencies:** "
                    f"{', '.join(rule.dependencies) if rule.dependencies else 'none'}"
                )
                lines.append(f"- **Input Topic:** {', '.join(rule.topics)}")
                lines.append(f"- **Output Topic:** {rule.output_topic}")

                # Generate output specification
                if rule.transform is not None:
                    from spec_manager.labyrinth.core.record import InputRecord

                    sample = InputRecord(
                        record_id="sample",
                        data={"amount": 5000, "type": "INVOICE", "currency": "USD"},
                    )
                    try:
                        output = rule.transform(sample)
                        output_str = ", ".join(
                            f"{k}={v}" for k, v in output.items() if not k.startswith("_")
                        )
                        lines.append(f"- **Output:** {output_str}")
                    except Exception:
                        lines.append("- **Output:** (computed at runtime)")
                lines.append("")

        # Section 4: Integration Points
        lines.append("## 4. Integration Points")
        lines.append("")
        for ip in integration_points:
            lines.append(f"### {ip.point_id}: {ip.name}")
            lines.append(f"- **Topic:** {ip.topic}")
            lines.append(f"- **Position:** {ip.position}")
            lines.append(f"- **Required Rules:** {', '.join(ip.required_rules)}")
            if ip.after_rules:
                lines.append(f"- **After:** {', '.join(ip.after_rules)}")
            lines.append("")

        # Section 5: Side Effect Requirements
        lines.append("## 5. Side Effect Requirements")
        lines.append("")
        for chain in chains:
            lines.append(f"### {chain.chain_id}")
            lines.append(f"- **Trigger Topic:** {chain.trigger_topic}")
            lines.append(f"- **Services:** {', '.join(chain.services)}")
            lines.append(f"- **Expected Log Entries:** {', '.join(chain.expected_log_entries)}")
            lines.append("")

        # Section 6: Verification Examples
        lines.append("## 6. Verification Examples")
        lines.append("")
        lines.append("See generated test suite for input/output verification pairs.")
        lines.append("")

        return "\n".join(lines)

    def _format_conditions(self, group: ConditionGroup) -> str:
        """Format a condition group as a readable string."""
        if not group.conditions:
            return "always"

        parts: list[str] = []
        for cond in group.conditions:
            if isinstance(cond, Condition):
                parts.append(f"{cond.field_name} {cond.operator.value} {cond.value}")
            elif isinstance(cond, ConditionGroup):
                parts.append(f"({self._format_conditions(cond)})")

        joiner = " AND " if group.logic == LogicOperator.AND else " OR "
        return joiner.join(parts)


class SparseSpecGenerator:
    """Generates specs with systematic information removal for ambiguity testing.

    Takes a dense spec and removes information according to strategies:
    1. Remove conditions -> "should handle appropriately"
    2. Remove integration details -> "integrate into the pipeline"
    3. Remove side-effect wiring -> "logging and notifications exist"
    4. Merge related rules -> combine into vague paragraphs
    5. Inject ambiguity -> "handle edge cases appropriately"
    """

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def generate(
        self,
        level: int,
        rules: list[Rule | CompositeRule],
        integration_points: list[IntegrationPoint],
        chains: list[SideEffectChain],
    ) -> str:
        """Generate a sparse spec with systematic information removal."""
        lines: list[str] = []

        lines.append(f"# Algorithm Integration Specification - Level {level}")
        lines.append("")

        # Vague architecture section
        lines.append("## System Overview")
        lines.append("")
        lines.append("The system processes records through a pipeline of rules.")
        lines.append("Rules are organized into groups and may have dependencies.")
        lines.append("Various services handle logging and monitoring.")
        lines.append("")

        # Merged rules section - combine related rules into vague paragraphs
        lines.append("## Processing Requirements")
        lines.append("")

        # Group rules by group name
        groups: dict[str, list[Rule | CompositeRule]] = {}
        for rule in rules:
            g = getattr(rule, "group", "general")
            if g not in groups:
                groups[g] = []
            groups[g].append(rule)

        for group_name, group_rules in groups.items():
            lines.append(f"### {group_name.title()} Processing")
            lines.append("")

            # Strategy 1: Remove specific conditions
            if len(group_rules) <= 4:
                for rule in group_rules:
                    lines.append(
                        f"- **{rule.name}**: Should handle {group_name} records appropriately"
                    )
            else:
                # Strategy 4: Merge related rules into paragraphs
                lines.append(
                    f"The {group_name} module contains {len(group_rules)} processing rules "
                    f"that handle various {group_name}-related operations. "
                    f"Rules should be integrated into the existing pipeline."
                )
            lines.append("")

        # Strategy 2: Vague integration section
        lines.append("## Integration")
        lines.append("")
        lines.append("New rules should be integrated into the existing pipeline.")
        lines.append("Rules must register at the appropriate integration points.")
        lines.append("Dependencies between rules should be respected.")
        lines.append("")

        # Strategy 3: Vague side effects
        lines.append("## Side Effects")
        lines.append("")
        lines.append(
            "The system includes audit logging, notification services, and metrics tracking."
        )
        lines.append("These services should be properly triggered when rules execute.")
        lines.append("")

        # Strategy 5: Inject ambiguity
        lines.append("## Additional Requirements")
        lines.append("")
        lines.append("- Handle edge cases appropriately")
        lines.append("- Ensure proper error handling")
        lines.append("- Maintain system consistency")
        lines.append("")

        return "\n".join(lines)

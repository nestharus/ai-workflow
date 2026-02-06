"""Dynamic rule registry for lookup by ID."""

from __future__ import annotations

from typing import Any

from spec_manager.labyrinth.engine.rule import CompositeRule, Rule


class RuleRegistry:
    """Registry for dynamic rule lookup by ID.

    Rules register themselves here. The executor uses the registry
    to find rules dynamically rather than through direct references.
    """

    def __init__(self) -> None:
        self._rules: dict[str, Rule | CompositeRule] = {}
        self._groups: dict[str, list[str]] = {}  # group -> [rule_ids]

    def register(self, rule: Rule | CompositeRule) -> None:
        """Register a rule."""
        self._rules[rule.rule_id] = rule
        group = getattr(rule, "group", "default")
        if group not in self._groups:
            self._groups[group] = []
        self._groups[group].append(rule.rule_id)

    def get(self, rule_id: str) -> Rule | CompositeRule | None:
        """Look up a rule by ID."""
        return self._rules.get(rule_id)

    def get_by_group(self, group: str) -> list[Rule | CompositeRule]:
        """Get all rules in a group."""
        rule_ids = self._groups.get(group, [])
        return [self._rules[rid] for rid in rule_ids if rid in self._rules]

    def get_all(self) -> list[Rule | CompositeRule]:
        """Get all registered rules."""
        return list(self._rules.values())

    def get_all_ids(self) -> list[str]:
        """Get all registered rule IDs."""
        return list(self._rules.keys())

    def has(self, rule_id: str) -> bool:
        """Check if a rule is registered."""
        return rule_id in self._rules

    def remove(self, rule_id: str) -> None:
        """Remove a rule from the registry."""
        rule = self._rules.pop(rule_id, None)
        if rule is not None:
            group = getattr(rule, "group", "default")
            if group in self._groups:
                self._groups[group] = [
                    rid for rid in self._groups[group] if rid != rule_id
                ]

    def clear(self) -> None:
        """Remove all rules."""
        self._rules.clear()
        self._groups.clear()

    def __len__(self) -> int:
        return len(self._rules)

"""Integration points - named slots where new rules must register.

This is the central puzzle of the labyrinth. Models must figure out
where to register new rules by understanding the existing integration
point topology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntegrationPoint:
    """A named slot in the pipeline where rules can register.

    Attributes:
        point_id: Unique identifier (e.g., 'IP-001').
        name: Human-readable name.
        topic: Bus topic this integration point listens on.
        position: Ordering position (rules execute in position order).
        registered_rules: Rule IDs registered at this point.
        required_rules: Rule IDs that MUST be registered here.
        after_rules: Rules that must execute before this point.
    """
    point_id: str
    name: str
    topic: str
    position: int = 0
    registered_rules: list[str] = field(default_factory=list)
    required_rules: list[str] = field(default_factory=list)
    after_rules: list[str] = field(default_factory=list)

    def register_rule(self, rule_id: str) -> None:
        """Register a rule at this integration point."""
        if rule_id not in self.registered_rules:
            self.registered_rules.append(rule_id)

    def unregister_rule(self, rule_id: str) -> None:
        """Remove a rule from this integration point."""
        self.registered_rules = [r for r in self.registered_rules if r != rule_id]

    def is_satisfied(self) -> bool:
        """Check if all required rules are registered."""
        return all(r in self.registered_rules for r in self.required_rules)

    def get_missing_rules(self) -> list[str]:
        """Get required rules that are not registered."""
        return [r for r in self.required_rules if r not in self.registered_rules]


class IntegrationPointRegistry:
    """Registry of all integration points in the system.

    Models must discover these points and register rules at the
    correct ones to pass integration tests.
    """

    def __init__(self) -> None:
        self._points: dict[str, IntegrationPoint] = {}

    def add(self, point: IntegrationPoint) -> None:
        """Add an integration point."""
        self._points[point.point_id] = point

    def get(self, point_id: str) -> IntegrationPoint | None:
        """Get an integration point by ID."""
        return self._points.get(point_id)

    def get_by_topic(self, topic: str) -> list[IntegrationPoint]:
        """Get all integration points for a topic, ordered by position."""
        points = [p for p in self._points.values() if p.topic == topic]
        return sorted(points, key=lambda p: p.position)

    def get_all(self) -> list[IntegrationPoint]:
        """Get all integration points ordered by position."""
        return sorted(self._points.values(), key=lambda p: (p.topic, p.position))

    def check_all_satisfied(self) -> dict[str, list[str]]:
        """Check which integration points have missing rules.

        Returns:
            Dict mapping point_id to list of missing rule IDs.
            Empty dict means all points are satisfied.
        """
        missing: dict[str, list[str]] = {}
        for point_id, point in self._points.items():
            gaps = point.get_missing_rules()
            if gaps:
                missing[point_id] = gaps
        return missing

    def get_all_ids(self) -> list[str]:
        """Get all integration point IDs."""
        return list(self._points.keys())

    def clear(self) -> None:
        """Remove all integration points."""
        self._points.clear()

    def __len__(self) -> int:
        return len(self._points)

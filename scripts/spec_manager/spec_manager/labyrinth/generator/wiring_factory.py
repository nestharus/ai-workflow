"""Factory for generating integration point configurations."""

from __future__ import annotations

import random

from spec_manager.labyrinth.engine.rule import CompositeRule, Rule
from spec_manager.labyrinth.generator.level_config import LevelConfig
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint


class WiringFactory:
    """Factory for generating integration points."""

    def __init__(self, config: LevelConfig, rng: random.Random) -> None:
        self._config = config
        self._rng = rng

    def generate_integration_points(
        self,
        rules: list[Rule | CompositeRule],
        topics: list[str],
    ) -> list[IntegrationPoint]:
        """Generate integration points for the configured level.

        Args:
            rules: All generated rules.
            topics: Available bus topics.

        Returns:
            List of IntegrationPoint definitions.
        """
        points: list[IntegrationPoint] = []
        rule_ids = [r.rule_id for r in rules]

        for i in range(self._config.num_integration_points):
            point_id = f"IP-L{self._config.level}-{i + 1:04d}"
            topic = self._rng.choice(topics) if topics else f"topic.ip.{i}"

            # Each IP requires 1-4 rules to be registered
            num_required = self._rng.randint(1, min(4, len(rule_ids)))
            required = self._rng.sample(rule_ids, num_required)

            # Some rules may depend on others at previous positions
            after: list[str] = []
            if i > 0 and points:
                prev_rules = points[-1].registered_rules
                if prev_rules:
                    after = [self._rng.choice(prev_rules)]

            point = IntegrationPoint(
                point_id=point_id,
                name=f"integration_slot_{i + 1}",
                topic=topic,
                position=i,
                registered_rules=[],  # Start empty - rules must be registered
                required_rules=required,
                after_rules=after,
            )
            points.append(point)

        return points

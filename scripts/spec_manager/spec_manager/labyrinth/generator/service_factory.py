"""Factory for generating side-effect service configurations."""

from __future__ import annotations

import random

from spec_manager.labyrinth.generator.level_config import LevelConfig
from spec_manager.labyrinth.integration.wiring import SideEffectChain

SERVICE_NAMES = ["audit_service", "notification_service", "metrics_service"]


class ServiceFactory:
    """Factory for generating side-effect chains."""

    def __init__(self, config: LevelConfig, rng: random.Random) -> None:
        self._config = config
        self._rng = rng

    def generate_chains(self, available_topics: list[str]) -> list[SideEffectChain]:
        """Generate side-effect chains for the configured level.

        Args:
            available_topics: Bus topics that rules publish to.

        Returns:
            List of SideEffectChain definitions.
        """
        chains: list[SideEffectChain] = []

        for i in range(self._config.num_side_effect_chains):
            chain_id = f"CHAIN-L{self._config.level}-{i + 1:04d}"

            # Pick a trigger topic
            topic = self._rng.choice(available_topics) if available_topics else f"topic.chain.{i}"

            # Pick 1-3 services for this chain
            num_services = self._rng.randint(1, min(3, len(SERVICE_NAMES)))
            services = self._rng.sample(SERVICE_NAMES, num_services)

            # Expected log entries based on services
            expected: list[str] = []
            for svc in services:
                if svc == "audit_service":
                    expected.append("audit_logged")
                elif svc == "notification_service":
                    expected.append("notification_sent")
                elif svc == "metrics_service":
                    expected.append("metrics_updated")

            chains.append(
                SideEffectChain(
                    chain_id=chain_id,
                    trigger_topic=topic,
                    services=services,
                    expected_log_entries=expected,
                )
            )

        return chains

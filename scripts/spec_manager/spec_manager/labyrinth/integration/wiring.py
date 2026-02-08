"""Wiring - connects rules to side-effect service chains.

The wiring is intentionally non-obvious: rules connect to services
through topic subscriptions and chain definitions, not direct calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog
from spec_manager.labyrinth.services.audit_service import AuditService
from spec_manager.labyrinth.services.metrics_service import MetricsService
from spec_manager.labyrinth.services.notification_service import NotificationService


@dataclass
class SideEffectChain:
    """A chain of side effects triggered by rule execution.

    Attributes:
        chain_id: Unique identifier.
        trigger_topic: Bus topic that triggers this chain.
        services: Ordered list of service names to invoke.
        expected_log_entries: EventLog entry types that must appear (for testing).
    """

    chain_id: str
    trigger_topic: str
    services: list[str] = field(default_factory=list)
    expected_log_entries: list[str] = field(default_factory=list)


class WiringManager:
    """Manages wiring between rules and side-effect services.

    Sets up bus subscriptions so that when rules publish to topics,
    the appropriate service chains are triggered.
    """

    def __init__(
        self,
        bus: AsyncMessageBus,
        event_log: EventLog,
    ) -> None:
        self._bus = bus
        self._event_log = event_log
        self._chains: dict[str, SideEffectChain] = {}
        self._services: dict[str, AuditService | NotificationService | MetricsService] = {}

    def register_service(
        self, name: str, service: AuditService | NotificationService | MetricsService
    ) -> None:
        """Register a named service."""
        self._services[name] = service

    def add_chain(self, chain: SideEffectChain) -> None:
        """Add a side-effect chain and wire it up.

        Subscribes the specified services to the trigger topic.
        """
        self._chains[chain.chain_id] = chain

        for service_name in chain.services:
            service = self._services.get(service_name)
            if service is not None:
                service.subscribe_to_topic(chain.trigger_topic)

    def get_chain(self, chain_id: str) -> SideEffectChain | None:
        """Get a chain by ID."""
        return self._chains.get(chain_id)

    def get_chains_for_topic(self, topic: str) -> list[SideEffectChain]:
        """Get all chains triggered by a topic."""
        return [c for c in self._chains.values() if c.trigger_topic == topic]

    def verify_chains_fired(self) -> dict[str, list[str]]:
        """Verify that all chains fired their expected log entries.

        Returns:
            Dict mapping chain_id to list of missing log entry types.
            Empty dict means all chains fired correctly.
        """
        missing: dict[str, list[str]] = {}
        log_types = {e.event_type for e in self._event_log.entries}

        for chain_id, chain in self._chains.items():
            gaps = [et for et in chain.expected_log_entries if et not in log_types]
            if gaps:
                missing[chain_id] = gaps

        return missing

    def get_all_chains(self) -> list[SideEffectChain]:
        """Get all registered chains."""
        return list(self._chains.values())

    def clear(self) -> None:
        """Remove all chains."""
        self._chains.clear()

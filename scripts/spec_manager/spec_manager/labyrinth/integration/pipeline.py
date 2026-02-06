"""Pipeline - chains bus, executor, and services for end-to-end flow."""

from __future__ import annotations

import asyncio
from typing import Any

from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog
from spec_manager.labyrinth.core.record import InputRecord, OutputRecord
from spec_manager.labyrinth.core.worker_pool import WorkerPool
from spec_manager.labyrinth.engine.executor import RuleExecutor
from spec_manager.labyrinth.engine.registry import RuleRegistry
from spec_manager.labyrinth.integration.integration_points import (
    IntegrationPoint,
    IntegrationPointRegistry,
)
from spec_manager.labyrinth.integration.wiring import WiringManager
from spec_manager.labyrinth.services.audit_service import AuditService
from spec_manager.labyrinth.services.metrics_service import MetricsService
from spec_manager.labyrinth.services.notification_service import NotificationService


class Pipeline:
    """End-to-end processing pipeline.

    Wires together the bus, executor, and services into a complete
    processing pipeline that can process InputRecords and produce
    OutputRecords while triggering all side effects.
    """

    def __init__(
        self,
        bus: AsyncMessageBus | None = None,
        event_log: EventLog | None = None,
        worker_pool: WorkerPool | None = None,
    ) -> None:
        self.bus = bus or AsyncMessageBus()
        self.event_log = event_log or EventLog()
        self.worker_pool = worker_pool or WorkerPool()

        self.rule_registry = RuleRegistry()
        self.integration_points = IntegrationPointRegistry()
        self.executor = RuleExecutor(
            bus=self.bus,
            registry=self.rule_registry,
            event_log=self.event_log,
            worker_pool=self.worker_pool,
        )

        # Services
        self.audit_service = AuditService(self.bus, self.event_log)
        self.notification_service = NotificationService(self.bus, self.event_log)
        self.metrics_service = MetricsService(self.bus, self.event_log)

        # Wiring
        self.wiring = WiringManager(self.bus, self.event_log)
        self.wiring.register_service("audit_service", self.audit_service)
        self.wiring.register_service("notification_service", self.notification_service)
        self.wiring.register_service("metrics_service", self.metrics_service)

    async def process(self, record: InputRecord) -> list[OutputRecord]:
        """Process an input record through the full pipeline.

        1. Log pipeline start
        2. Execute all rules via executor (respects dependencies)
        3. Side effects fire via bus subscriptions
        4. Log pipeline complete

        Args:
            record: Input record to process.

        Returns:
            List of output records from rule execution.
        """
        self.event_log.append(
            event_type="pipeline_started",
            source="pipeline",
            data={"record_id": record.record_id},
        )

        results = await self.executor.execute_all(record)

        self.event_log.append(
            event_type="pipeline_completed",
            source="pipeline",
            data={
                "record_id": record.record_id,
                "rules_fired": len(results),
            },
        )

        return results

    def process_sync(self, record: InputRecord) -> list[OutputRecord]:
        """Synchronous wrapper for process().

        Creates a new event loop if needed for sync callers.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We're in an async context - use a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.process(record))
                return future.result()
        else:
            return asyncio.run(self.process(record))

    def verify_integration(self) -> dict[str, Any]:
        """Verify that all integration points are satisfied and chains fired.

        Returns:
            Dict with 'integration_gaps' and 'chain_gaps' keys.
            Both empty means everything is properly integrated.
        """
        return {
            "integration_gaps": self.integration_points.check_all_satisfied(),
            "chain_gaps": self.wiring.verify_chains_fired(),
        }

    def shutdown(self) -> None:
        """Clean up resources."""
        self.worker_pool.shutdown(wait=True)

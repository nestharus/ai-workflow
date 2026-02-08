"""Rule executor orchestrating rule evaluation via the message bus."""

from __future__ import annotations

import logging

from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog
from spec_manager.labyrinth.core.record import InputRecord, OutputRecord
from spec_manager.labyrinth.core.worker_pool import WorkerPool
from spec_manager.labyrinth.engine.registry import RuleRegistry

logger = logging.getLogger(__name__)


class RuleExecutor:
    """Orchestrates rule evaluation through the message bus.

    Uses the bus for dispatch and the worker pool for execution.
    Logs all execution steps to the event log for verification.
    """

    def __init__(
        self,
        bus: AsyncMessageBus,
        registry: RuleRegistry,
        event_log: EventLog,
        worker_pool: WorkerPool | None = None,
    ) -> None:
        self._bus = bus
        self._registry = registry
        self._event_log = event_log
        self._worker_pool = worker_pool or WorkerPool()
        self._results: dict[str, list[OutputRecord]] = {}

    async def execute_rule(self, rule_id: str, record: InputRecord) -> OutputRecord | None:
        """Execute a single rule by ID against an input record.

        Args:
            rule_id: ID of the rule to execute.
            record: Input record to process.

        Returns:
            OutputRecord if the rule matched, None otherwise.
        """
        rule = self._registry.get(rule_id)
        if rule is None:
            logger.warning("Rule not found: %s", rule_id)
            return None

        self._event_log.append(
            event_type="rule_started",
            source=rule_id,
            topic="",
            data={"record_id": record.record_id},
        )

        # Execute rule in worker pool for thread boundary
        result = await self._worker_pool.submit(rule.evaluate, record)

        if result is not None:
            self._event_log.append(
                event_type="rule_executed",
                source=rule_id,
                topic=getattr(rule, "output_topic", ""),
                data={
                    "record_id": record.record_id,
                    "output_keys": list(result.data.keys()),
                },
            )

            # Publish result to the bus
            output_topic = getattr(rule, "output_topic", "")
            if output_topic:
                await self._bus.publish(
                    output_topic,
                    {
                        "rule_id": rule_id,
                        "record_id": record.record_id,
                        "output": result.data,
                    },
                )

            # Store result
            if record.record_id not in self._results:
                self._results[record.record_id] = []
            self._results[record.record_id].append(result)
        else:
            self._event_log.append(
                event_type="rule_skipped",
                source=rule_id,
                data={"record_id": record.record_id, "reason": "conditions_not_met"},
            )

        return result

    async def execute_all(self, record: InputRecord) -> list[OutputRecord]:
        """Execute all registered rules against an input record.

        Respects dependency ordering.

        Args:
            record: Input record to process.

        Returns:
            List of OutputRecords from rules that matched.
        """
        from spec_manager.labyrinth.engine.rule import RuleChain

        # Build a chain from all rules for dependency ordering
        all_rules = self._registry.get_all()
        chain = RuleChain(chain_id="all", rules=all_rules)
        ordered = chain.get_execution_order()

        results: list[OutputRecord] = []
        current_record = record

        for rule in ordered:
            result = await self.execute_rule(rule.rule_id, current_record)
            if result is not None:
                results.append(result)
                # Enrich the record for subsequent rules
                enriched_data = {**current_record.data, **result.data}
                current_record = InputRecord(
                    record_id=record.record_id,
                    data=enriched_data,
                    metadata=record.metadata,
                )

        return results

    def get_results(self, record_id: str) -> list[OutputRecord]:
        """Get all results for a record ID."""
        return self._results.get(record_id, [])

    def clear_results(self) -> None:
        """Clear all stored results."""
        self._results.clear()

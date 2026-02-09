# System: CONSTRAINTS


([=CON-SYS-002])
<!-- source: cross_system_invariants.md:3-3 -->
Several invariants span multiple libraries and must hold at all times regardless of which processing path an instruction takes.


([=CON-SYS-003])
<!-- source: cross_system_invariants.md:5-5 -->
**Rate freshness invariant**: Any FX rate used for conversion must have been captured within the preceding 6 hours. If the rate cache returns a rate whose capture timestamp is older than 6 hours, the SettlementProcessor must emit a `rate.stale` alert on the EventPipeline before proceeding with conversion so that the operations team can verify the rate manually. This invariant applies to both the initial conversion in [settlement_processing.md](settlement_processing.md) and the independent rate fetch in the [reconciliation.md](reconciliation.md).


([=CON-SYS-004])
<!-- source: cross_system_invariants.md:7-7 -->
**Dead-letter audit invariant**: Every event that lands in the dead-letter queue must appear in the next daily regulatory summary produced by the RegulatoryCompliance module, regardless of the event's original topic. This ensures that dropped events are never silently lost.


([=CON-SYS-005])
<!-- source: cross_system_invariants.md:9-9 -->
**Settlement finality invariant**: Once a settlement instruction has been confirmed (see [settlement_processing.md](settlement_processing.md)) no system may mutate that record. Corrections are exclusively handled by issuing new offsetting instructions through the normal pipeline. Any attempt to modify a confirmed record must be rejected and logged as a `finality.violation` audit event.


([=CON-SYS-006])
<!-- source: cross_system_invariants.md:29-29 -->
**Correlation tracing invariant**: The correlation ID assigned at ingestion by the TransactionValidator must propagate unchanged through every downstream event emitted by every library. Reconciliation, audit, and regulatory events all carry this ID, enabling end-to-end trace queries.


([=CON-SYS-001])
<!-- source: event_pipeline.md:33-33 -->
All events must carry a correlation ID that links them back to the originating settlement instruction, enabling end-to-end trace reconstruction across the entire pipeline (see [cross_system_invariants.md](cross_system_invariants.md) for the correlation tracing invariant). The pipeline emits its own operational metrics, including throughput per topic, consumer lag, and dead-letter queue depth, which the AuditNotification service consumes for operational alerting.

# Event Pipeline

The EventPipeline is the nervous system of the settlement engine. It implements a pub/sub architecture where each event is published to a named topic and consumers subscribe to the topics they care about.

The topic configuration is:

```yaml
topics:
  - name: settlement.confirmed
    partitions: 8
    retention_days: 30
  - name: settlement.rejected
    partitions: 4
    retention_days: 7
  - name: risk.breach
    partitions: 2
    retention_days: 90
  - name: reconciliation.break
    partitions: 4
    retention_days: 90
  - name: audit.snapshot
    partitions: 1
    retention_days: 365
  - name: validation.duplicate
    partitions: 2
    retention_days: 7
```

Ordering is guaranteed within a topic partition, so consumers processing events from a single partition will always see them in the order they were produced; however, ordering across partitions is not guaranteed and consumers must tolerate out-of-order delivery when reading from multiple partitions. If a consumer fails to acknowledge an event within thirty seconds the pipeline retries delivery. The retry policy uses exponential backoff with a base of one second and a multiplier of four, producing intervals of 1s, 4s, and 16s for the first, second, and third attempts respectively. After the third failed attempt the event is moved to a dead-letter queue where it remains for ninety days before automatic purging.

The pipeline also supports transactional publishing, meaning that a producer can publish events to multiple topics atomically; if any publication in the transaction fails, all publications in that transaction are rolled back. Event payloads are serialised as JSON and must not exceed 256 KB per message; oversized payloads are rejected at the producer side with a `PayloadTooLarge` error.

All events must carry a correlation ID that links them back to the originating settlement instruction, enabling end-to-end trace reconstruction across the entire pipeline (see [cross_system_invariants.md](cross_system_invariants.md) for the correlation tracing invariant). The pipeline emits its own operational metrics, including throughput per topic, consumer lag, and dead-letter queue depth, which the AuditNotification service consumes for operational alerting.

# Goals Library

Goals and requirements for the event processing system.

---

### G1 - Low Latency ([=G1])

Goal: P99 latency < 100ms from ingestion to all sinks.

This is aggressive. Might need to revisit. Depends on how heavy the
transformations are.

---

### G2 - At Least Once Delivery ([=G2])

Goal: Every event reaches every applicable sink at least once.

We need retry logic. If send_to_sink() fails, retry with backoff.
But what about poison messages? Need a dead letter queue like D5.

Actually D5 isn't defined yet. Let me add it.

---

### G3 - Observability ([=G3])

Need metrics:
- events_processed
- events_failed
- sink_latency_p50, p99
- queue_depth

These feed into monitoring_system() which sends alerts. But that's
external to this spec.

---
Section 5: Scalability
---

We haven't thought about scaling yet.

---

### G4 - Horizontal Scaling ([=G4])

Goal: System should scale linearly up to 100 workers.

This is aspirational. Need to validate with load testing.

Depends on Algorithm 5 working correctly and no shared state
that becomes a bottleneck.

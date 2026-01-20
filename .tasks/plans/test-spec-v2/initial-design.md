# Event Processing System - Initial Design

Just dumping my thoughts here. Will refine later.

## Core Idea

We need to process events from multiple sources, transform them, and route
them to different sinks. Pretty standard ETL but realtime.

---
Section 1: Data Model
---

### D1 - Event ([=D1])

Basic event structure:
- id (uuid)
- source (string - where it came from)
- payload (json)
- timestamp
- type (string)

We probably need more fields but this is v1.

### D2 - Source ([=D2])

A source is where events come from:
- id
- name
- config (json - connection details, etc.)

Hmm, should config include auth? Probably need to call authenticate_source()
before we can pull events. TODO: figure out auth flow.

### D3 - Sink ([=D3])

Where we send processed events:
- id
- name
- type (kafka, s3, webhook, etc.)
- config

Not sure if we need a separate Transform entity or if that's part of routing.

---
Section 2: Processing
---

### Algorithm 1 - Event Ingestion ([=Algorithm 1])

When event arrives:
1. Parse and validate
2. Assign internal id
3. Add to processing queue

This uses the validate_event() function which... actually I don't think
we've defined that anywhere. Need to spec it out.

### Algorithm 2 - Event Transformation ([=Algorithm 2])

For each event in queue:
1. Look up transformation rules based on event.type
2. Apply transformations in order
3. Produce transformed event

The transformation rules come from... somewhere? Maybe call get_rules_for_type()
but that's not defined yet either.

This replaces any manual mapping we were doing before.

### Algorithm 3 - Event Routing ([=Algorithm 3])

After transformation:
1. Evaluate routing conditions
2. For each matching sink:
   - Format event for sink type
   - Send to sink via send_to_sink()
3. Track delivery status

The send_to_sink() function depends on D3 config. Different sinks need
different protocols.

---
Section 3: Goals
---

### G1 - Low Latency ([=G1])

Goal: P99 latency < 100ms from ingestion to all sinks.

This is aggressive. Might need to revisit. Depends on how heavy the
transformations are.

### G2 - At Least Once Delivery ([=G2])

Goal: Every event reaches every applicable sink at least once.

We need retry logic. If send_to_sink() fails, retry with backoff.
But what about poison messages? Need a dead letter queue like D5.

Actually D5 isn't defined yet. Let me add it.

### D5 - Dead Letter Queue ([=D5])

Events that fail after max retries go here:
- original_event (copy of D1)
- error_reason
- failed_at
- retry_count

---
Section 4: Reliability
---

### Algorithm 4 - Retry Logic ([=Algorithm 4])

When sink delivery fails:
1. Check retry_count against max_retries
2. If under limit: requeue with exponential backoff
3. If over limit: move to D5

This conflicts a bit with G2 - at-least-once means we retry forever?
No, we need to bound it. Maybe configurable max_retries in D3?

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

### Algorithm 5 - Partitioned Processing ([=Algorithm 5])

To scale horizontally:
1. Partition events by source or type
2. Assign partitions to workers
3. Each worker processes its partition independently

This needs coordination. Maybe use consistent_hash() to assign
partitions? Or call the partition_service() that we don't have.

Hmm this is getting complicated. Might need to split this into
separate components later.

### G4 - Horizontal Scaling ([=G4])

Goal: System should scale linearly up to 100 workers.

This is aspirational. Need to validate with load testing.

Depends on Algorithm 5 working correctly and no shared state
that becomes a bottleneck.

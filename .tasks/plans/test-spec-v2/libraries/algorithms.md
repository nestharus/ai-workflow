# Algorithms Library

Algorithms for the event processing system.

---

### Algorithm 1 - Event Ingestion ([=Algorithm 1])

When event arrives:
1. Parse and validate
2. Assign internal id
3. Add to processing queue

This uses the validate_event() function which... actually I don't think
we've defined that anywhere. Need to spec it out.

---

### Algorithm 2 - Event Transformation ([=Algorithm 2])

For each event in queue:
1. Look up transformation rules based on event.type
2. Apply transformations in order
3. Produce transformed event

The transformation rules come from... somewhere? Maybe call get_rules_for_type()
but that's not defined yet either.

This replaces any manual mapping we were doing before.

---

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

---

### Algorithm 4 - Retry Logic ([=Algorithm 4])

When sink delivery fails:
1. Check retry_count against max_retries
2. If under limit: requeue with exponential backoff
3. If over limit: move to D5

This conflicts a bit with G2 - at-least-once means we retry forever?
No, we need to bound it. Maybe configurable max_retries in D3?

---

### Algorithm 5 - Partitioned Processing ([=Algorithm 5])

To scale horizontally:
1. Partition events by source or type
2. Assign partitions to workers
3. Each worker processes its partition independently

This needs coordination. Maybe use consistent_hash() to assign
partitions? Or call the partition_service() that we don't have.

Hmm this is getting complicated. Might need to split this into
separate components later.

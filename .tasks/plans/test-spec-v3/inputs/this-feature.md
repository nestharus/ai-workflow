# This Feature - Event Routing

Adds routing capabilities to the event system.

---

### D3 - RoutingRule ([=D3])

Rules for directing events to sinks:
- id: uuid
- source_pattern: regex matching D2 names
- type_pattern: regex matching event types
- sink_id: reference to D4
- priority: int

Higher priority rules evaluated first.

---

### Algorithm 2 - Event Routing ([=Algorithm 2])

After ingestion:
1. Load routing rules from rule_store()
2. Match event against rules by priority
3. For each match, queue event for that sink
4. Track routing decisions in audit_log()

This depends on Algorithm 1 completing first.

---

### G1 - Routing Latency ([=G1])

Goal: Route events within 10ms of ingestion.

Might conflict with complex rule matching. Need to benchmark.
How should we handle no matching rules? Drop or default sink?

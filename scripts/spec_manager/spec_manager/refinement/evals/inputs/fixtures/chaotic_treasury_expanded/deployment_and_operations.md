# Deployment and Operations

The deployment configuration is maintained as infrastructure-as-code. The critical operational parameters are:

```yaml
settlement_engine:
  max_batch_size: 500
  netting_threshold_usd: 1000000
  rate_staleness_hours: 6
  dedup_window_seconds: 5
  retry_base_seconds: 1
  retry_multiplier: 4
  retry_max_attempts: 3
  dead_letter_retention_days: 90
  audit_write_latency_ms: 50
  risk_suspension_minutes: 30
  risk_suspension_threshold: 10
  reconciliation_escalation_days: 7
  regulatory_report_retention_years: 7
  notification_batch_size: 50
  notification_batch_window_seconds: 60
  notification_batch_trigger: 20
```

The operations team monitors the engine through a unified dashboard that aggregates metrics from all eight components. Alerting rules are defined in pseudocode:

```
FOR counterparty IN active_counterparties:
    exposure = sum(pending_settlements[counterparty].notional)
    IF exposure > 0.8 * credit_limit[counterparty]:
        ALERT("margin_call", counterparty, exposure)
    IF exposure > 0.25 * total_exposure:
        ALERT("concentration_breach", counterparty, exposure)

FOR event IN dead_letter_queue:
    IF event.age > 1 hour:
        ALERT("stale_dead_letter", event.topic, event.id)
```

The pseudocode above describes monitoring logic, not business rules; the actual margin-call and concentration thresholds are defined in the [risk_engine.md](risk_engine.md) section and are authoritative. Stale dead-letter alerts at the one-hour mark are an operational warning only; the regulatory requirement is that dead-letter events appear in the daily summary (see [cross_system_invariants.md](cross_system_invariants.md)).

Health checks run every 30 seconds and verify connectivity to the rate cache, the reference-data service, the event broker, and the audit data store. If any downstream dependency is unreachable the engine enters degraded mode, accepting instructions into the retry buffer but not processing them until the dependency recovers.

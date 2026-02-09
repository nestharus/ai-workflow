# Operations and Deployment: DETAIL — ALGORITHM


([=ALG-LIB-07-001])
<!-- source: deployment_and_operations.md:25-38 -->
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


([=ALG-LIB-07-002])
<!-- source: deployment_and_operations.md:42-42 -->
Health checks run every 30 seconds and verify connectivity to the rate cache, the reference-data service, the event broker, and the audit data store. If any downstream dependency is unreachable the engine enters degraded mode, accepting instructions into the retry buffer but not processing them until the dependency recovers.

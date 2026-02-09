# Operations and Deployment: ANALYSIS


([=ANL-LIB-07-001])
<!-- source: deployment_and_operations.md:40-40 -->
The pseudocode above describes monitoring logic, not business rules; the actual margin-call and concentration thresholds are defined in the [risk_engine.md](risk_engine.md) section and are authoritative. Stale dead-letter alerts at the one-hour mark are an operational warning only; the regulatory requirement is that dead-letter events appear in the daily summary (see [cross_system_invariants.md](cross_system_invariants.md)).

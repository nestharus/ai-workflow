# Operations and Deployment: DETAIL — STORE


([=STO-LIB-07-001])
<!-- source: deployment_and_operations.md:3-23 -->
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

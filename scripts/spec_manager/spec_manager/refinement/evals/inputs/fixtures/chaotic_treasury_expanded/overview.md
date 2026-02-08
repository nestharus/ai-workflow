# Treasury Settlement Engine

The treasury settlement engine is the backbone of our clearing infrastructure and it touches practically every downstream system we operate. At the highest level an inbound settlement instruction passes through a pipeline that can be summarised in function-composition style as `process(instructions) = instructions |> validate(schema) |> risk_check(limits) |> apply_netting(counterparty, value_date) |> submit_clearing()` but that tidy notation hides a tremendous amount of machinery.

The TransactionValidator performs upfront deduplication and schema validation before the SettlementProcessor decides whether a batch should be netted or sent through gross, and the SettlementProcessor consults the RiskEngine before any netting decision is finalised because the exposure windows maintained by the RiskEngine determine whether additional margin is required. If the RiskEngine flags an exposure breach the entire batch is held and a margin call is issued, which in turn must be recorded by the AuditNotification service so that compliance can review the event later. Meanwhile the EventPipeline carries every state transition as a typed event across the organisation, feeding the ReconciliationService which detects breaks between our internal ledger and the counterparty's acknowledgement. The RegulatoryCompliance module watches for reportable thresholds and hold-period triggers, injecting regulatory holds into the settlement flow before final confirmation. All of this must happen with enough speed that the AuditNotification service can persist a full snapshot within its latency budget while still routing alerts to the right team through the right channel.

Settlement instructions that arrive with FX rates older than 6 hours must trigger a staleness alert before the rate is used for conversion (see [settlement_processing.md](settlement_processing.md) for the conversion mechanics and [cross_system_invariants.md](cross_system_invariants.md) for the rate freshness invariant).

The interplay between these eight systems — seven libraries plus the TransactionValidator — is what makes the engine both powerful and treacherous to change, because a modification to one library's timing assumptions can cascade into reconciliation breaks, missed regulatory windows, or silent audit gaps. The full architecture is documented across the following files:

- [Settlement Processing](settlement_processing.md)
- [Risk Engine](risk_engine.md)
- [Reconciliation Service](reconciliation.md)
- [Event Pipeline](event_pipeline.md)
- [Regulatory Compliance](regulatory_compliance.md)
- [Notification and Audit](notification_audit.md)
- [Transaction Validation](transaction_validation.md)
- [Cross-System Invariants](cross_system_invariants.md)
- [Deployment and Operations](deployment_operations.md)

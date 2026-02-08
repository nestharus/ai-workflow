# Regulatory Compliance

The RegulatoryCompliance module enforces reporting obligations and hold periods dictated by the applicable regulatory framework. Settlement transactions whose notional exceeds $10M must be reported to the regulator within 15 minutes of confirmation; the module listens for `settlement.confirmed` events and evaluates the notional against this threshold, queuing a regulatory report if the condition is met. Cross-border settlements with a notional exceeding $5M are subject to a 24-hour hold period during which the settlement cannot be finalised; the module injects a regulatory hold status into the settlement record and only releases it after the hold window has elapsed and no objection has been received from the compliance desk.

Transactions above $25M trigger an additional suspicious-transaction flag that is forwarded to the financial-intelligence unit for review; this flag does not block settlement but must be attached to the audit snapshot so that the AuditNotification service can include it in downstream reports. The module also monitors for structuring patterns where a series of sub-threshold transactions from the same counterparty within a single business day aggregate to an amount that would have triggered the $10M reporting threshold had they been submitted as a single instruction, and if such a pattern is detected the entire series is retroactively reported.

Regulatory reports are transmitted via a secure SFTP channel and the module must retain a local copy for seven years in accordance with record-retention policy.

The compliance workflow is best understood through the following sequence:

```mermaid
sequenceDiagram
    participant SP as SettlementProcessor
    participant RC as RegulatoryCompliance
    participant FIU as FinancialIntelligenceUnit
    participant AN as AuditNotification
    SP->>RC: settlement.confirmed event
    RC->>RC: evaluate thresholds
    alt notional > $10M
        RC->>Regulator: file report (15 min SLA)
    end
    alt cross-border > $5M
        RC->>SP: inject 24h hold
    end
    alt notional > $25M
        RC->>FIU: suspicious flag
        RC->>AN: attach flag to audit
    end
```

This diagram illustrates the decision tree but the actual reporting algorithm walks through the threshold checks sequentially, evaluating the $10M domestic threshold first, then the $5M cross-border hold, and finally the $25M suspicious-transaction flag; this ordering is an implementation convenience rather than a business requirement.

# Reconciliation: DETAIL — ALGORITHM


([=ALG-LIB-03-001])
<!-- source: reconciliation_service.md:3-3 -->
Reconciliation runs continuously against the internal ledger and the counterparty acknowledgement feed. The matching algorithm considers a tuple of exact amount, counterparty identifier, and value date; if all three fields match the entry is considered reconciled. Breaks are classified by the magnitude of the discrepancy relative to the expected amount. For domestic settlements the tolerance band is 0.01%, meaning that any mismatch whose absolute value is less than or equal to 0.01% of the expected amount is treated as a rounding artefact and auto-reconciled. Cross-border settlements use a wider tolerance of 0.05% to account for FX conversion variance, and the rate used for this comparison is the same ECB reference rate applied during settlement processing, although the ReconciliationService fetches it independently from the rate cache rather than trusting the value embedded in the settlement payload. Breaks below $1,000 in absolute terms are auto-resolved regardless of the percentage because the cost of manual investigation exceeds the risk.


([=ALG-LIB-03-002])
<!-- source: reconciliation_service.md:5-5 -->
A subtle interaction exists with the RegulatoryCompliance module: any reconciliation break on a settlement that is currently under a regulatory hold (see [regulatory_compliance.md](regulatory_compliance.md) for hold mechanics) must be escalated immediately to the compliance desk regardless of the break magnitude, bypassing the normal tolerance-based classification.


([=ALG-LIB-03-003])
<!-- source: reconciliation_service.md:7-7 -->
Breaks that exceed the tolerance band or the $1,000 absolute ceiling are published as `reconciliation.break` events on the EventPipeline and routed to the operations team for manual resolution. The ReconciliationService must also detect duplicate acknowledgements from counterparties and suppress them to prevent double-counting, and it maintains a sliding window of seven business days beyond which unmatched entries are escalated to a senior reconciliation analyst.

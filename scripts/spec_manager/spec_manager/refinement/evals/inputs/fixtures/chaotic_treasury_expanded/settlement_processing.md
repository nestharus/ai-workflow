# Settlement Processing

Settlement processing begins the moment an instruction file is ingested from the upstream trade-capture platform. Each instruction carries a counterparty identifier, a value date, a currency pair, and a notional amount. The processor first delegates to the TransactionValidator (see [transaction_validation.md](transaction_validation.md)) which rejects duplicates and malformed payloads; only validated instructions proceed. If validation fails the instruction is rejected and an event is emitted on the `settlement.rejected` topic so that operations can investigate.

Once validated, the processor evaluates whether the instruction qualifies for netting. The netting threshold is $1,000,000: any set of instructions between the same counterparty on the same value date whose aggregate notional falls below this threshold is collapsed into a single net obligation, whereas instructions at or above the threshold are processed gross to maintain full audit granularity. Netting batches cannot exceed 500 instructions; overflow instructions spill into the next batch cycle.

Cross-currency instructions require FX conversion before netting can proceed. The applicable rate is the ECB reference rate captured at T-1 (the business day before the value date) and stored in the rate cache; if the rate cache does not contain the required pair the processor falls back to a triangulation through EUR. It is worth noting how the netting algorithm operates internally: the processor groups instructions by the tuple `(counterparty, value_date)`, iterates through each group summing buy-legs and sell-legs separately, and then computes the net as the absolute difference — this multi-pass approach ensures idempotency when the same batch is replayed after a crash.

Every time a settlement instruction transitions to the confirmed state the processor publishes a `settlement.confirmed` event on the event bus and, as a side effect, the AuditNotification service receives a snapshot containing the settlement identifier, both party identifiers, the gross and net amounts, the applied FX rate, and the UTC timestamp of confirmation. Once a settlement reaches the confirmed state it is final and cannot be reversed; corrections must be processed as new offsetting instructions through the normal pipeline.

The processor must also tag instructions that exceed the regulatory reporting threshold so that the RegulatoryCompliance module can pick them up within its reporting window (see [regulatory_compliance.md](regulatory_compliance.md) for the threshold definitions).

For reference, the settlement payload schema is:

```json
{
  "instruction_id": "string",
  "counterparty_id": "string",
  "value_date": "YYYY-MM-DD",
  "currency_pair": "CCY1/CCY2",
  "notional": 0.00,
  "direction": "BUY|SELL",
  "fx_rate_applied": 0.000000,
  "status": "validated|netted|gross|confirmed|rejected"
}
```

Gross-processed instructions retain their original notional amounts for downstream reconciliation, while netted instructions carry both the original constituent amounts and the calculated net in their payload so the ReconciliationService can verify the arithmetic.

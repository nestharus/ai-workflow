# Settlement Processing: DETAIL — ALGORITHM


([=ALG-LIB-01-010])
<!-- source: overview.md:3-3 -->
The treasury settlement engine is the backbone of our clearing infrastructure and it touches practically every downstream system we operate. At the highest level an inbound settlement instruction passes through a pipeline that can be summarised in function-composition style as `process(instructions) = instructions |> validate(schema) |> risk_check(limits) |> apply_netting(counterparty, value_date) |> submit_clearing()` but that tidy notation hides a tremendous amount of machinery.


([=ALG-LIB-01-011])
<!-- source: overview.md:7-7 -->
Settlement instructions that arrive with FX rates older than 6 hours must trigger a staleness alert before the rate is used for conversion (see [settlement_processing.md](settlement_processing.md) for the conversion mechanics and [cross_system_invariants.md](cross_system_invariants.md) for the rate freshness invariant).


([=ALG-LIB-01-001])
<!-- source: settlement_processing.md:3-3 -->
Settlement processing begins the moment an instruction file is ingested from the upstream trade-capture platform. Each instruction carries a counterparty identifier, a value date, a currency pair, and a notional amount. The processor first delegates to the TransactionValidator (see [transaction_validation.md](transaction_validation.md)) which rejects duplicates and malformed payloads; only validated instructions proceed. If validation fails the instruction is rejected and an event is emitted on the `settlement.rejected` topic so that operations can investigate.


([=ALG-LIB-01-002])
<!-- source: settlement_processing.md:5-5 -->
Once validated, the processor evaluates whether the instruction qualifies for netting. The netting threshold is $1,000,000: any set of instructions between the same counterparty on the same value date whose aggregate notional falls below this threshold is collapsed into a single net obligation, whereas instructions at or above the threshold are processed gross to maintain full audit granularity. Netting batches cannot exceed 500 instructions; overflow instructions spill into the next batch cycle.


([=ALG-LIB-01-003])
<!-- source: settlement_processing.md:7-7 -->
Cross-currency instructions require FX conversion before netting can proceed. The applicable rate is the ECB reference rate captured at T-1 (the business day before the value date) and stored in the rate cache; if the rate cache does not contain the required pair the processor falls back to a triangulation through EUR. It is worth noting how the netting algorithm operates internally: the processor groups instructions by the tuple `(counterparty, value_date)`, iterates through each group summing buy-legs and sell-legs separately, and then computes the net as the absolute difference — this multi-pass approach ensures idempotency when the same batch is replayed after a crash.


([=ALG-LIB-01-004])
<!-- source: settlement_processing.md:9-9 -->
Every time a settlement instruction transitions to the confirmed state the processor publishes a `settlement.confirmed` event on the event bus and, as a side effect, the AuditNotification service receives a snapshot containing the settlement identifier, both party identifiers, the gross and net amounts, the applied FX rate, and the UTC timestamp of confirmation. Once a settlement reaches the confirmed state it is final and cannot be reversed; corrections must be processed as new offsetting instructions through the normal pipeline.


([=ALG-LIB-01-005])
<!-- source: settlement_processing.md:11-11 -->
The processor must also tag instructions that exceed the regulatory reporting threshold so that the RegulatoryCompliance module can pick them up within its reporting window (see [regulatory_compliance.md](regulatory_compliance.md) for the threshold definitions).


([=ALG-LIB-01-006])
<!-- source: settlement_processing.md:28-28 -->
Gross-processed instructions retain their original notional amounts for downstream reconciliation, while netted instructions carry both the original constituent amounts and the calculated net in their payload so the ReconciliationService can verify the arithmetic.


([=ALG-LIB-01-007])
<!-- source: transaction_validation.md:3-3 -->
The TransactionValidator sits at the ingestion boundary and enforces two critical checks before any instruction enters the settlement pipeline. First, schema validation: every incoming instruction must conform to the settlement payload schema (see [settlement_processing.md](settlement_processing.md) for the JSON definition) and any instruction missing a required field or carrying an invalid currency code is rejected immediately with a `validation.rejected` event. Second, deduplication: instructions with identical `(counterparty_id, value_date, currency_pair, notional, direction)` tuples arriving within a 5-second window are treated as duplicates and the second copy is silently dropped after publishing a `validation.duplicate` event on the EventPipeline for traceability.


([=ALG-LIB-01-008])
<!-- source: transaction_validation.md:5-5 -->
The validator uses a Bloom filter with a false-positive rate of 0.1% for the initial deduplication check and falls back to an exact hash-table lookup when the Bloom filter signals a potential duplicate — this two-stage approach is an implementation optimisation, not a functional requirement. The 5-second dedup window is aligned to the wall clock rather than instruction timestamps to avoid clock-skew issues between upstream systems.


([=ALG-LIB-01-009])
<!-- source: transaction_validation.md:7-7 -->
If the reference-data service is unavailable during validation, the validator must queue the instruction in a retry buffer and attempt revalidation every 10 seconds for up to 2 minutes; if the reference-data service does not recover within that window the instruction is rejected with a `service.unavailable` reason.

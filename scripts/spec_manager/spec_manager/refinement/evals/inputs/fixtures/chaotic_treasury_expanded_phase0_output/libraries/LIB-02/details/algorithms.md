# Risk Management: DETAIL — ALGORITHM


([=ALG-LIB-02-001])
<!-- source: risk_engine.md:3-3 -->
The RiskEngine maintains a real-time exposure model for every active counterparty. Each counterparty is assigned a credit limit and the current implementation caps that limit at $50M per counterparty, though the limit can be adjusted by the credit-risk team through the admin console. Exposure is calculated across a window spanning T+0 to T+2 inclusive, meaning that any settlement instruction with a value date falling within the next two business days contributes to the counterparty's current exposure. The exposure calculation itself follows a weighted-sum approach: for each pending instruction the engine multiplies the notional by a time-decay factor computed as `1.0 / (1 + days_to_value_date * 0.1)` and accumulates the weighted notionals — this weighting is purely an implementation detail of how the engine prioritises near-term risk over far-term exposure and is not a configurable threshold.


([=ALG-LIB-02-002])
<!-- source: risk_engine.md:5-5 -->
When the aggregate exposure for a counterparty reaches 80% of its assigned limit the RiskEngine automatically issues a margin call, which is published as a `risk.breach` event on the EventPipeline and simultaneously triggers a notification to the risk desk via a dashboard push. If more than 10 consecutive settlement instructions for the same counterparty fail the risk check, the RiskEngine must temporarily suspend that counterparty for 30 minutes during which no new instructions are accepted.


([=ALG-LIB-02-003])
<!-- source: risk_engine.md:7-7 -->
Concentration risk is also monitored: no single counterparty may represent more than 25% of the total outstanding exposure across all counterparties at any point in time, and if this threshold is breached the RiskEngine blocks new instructions for that counterparty until the concentration drops below the limit. There is however a Tier-1 override provision for systemically important counterparties designated by the central bank; when a Tier-1 flag is present the RiskEngine must allow the instruction to proceed even if the $50M cap or the 25% concentration limit would otherwise be breached, creating a deliberate conflict with the standard risk controls that must be resolved by the compliance team post-facto.


([=ALG-LIB-02-004])
<!-- source: risk_engine.md:9-9 -->
The RiskEngine also feeds exposure snapshots to the AuditNotification service at five-minute intervals so that the audit trail reflects the near-real-time risk posture. See [notification_audit.md](notification_audit.md) for how these snapshots are persisted and [cross_system_invariants.md](cross_system_invariants.md) for related invariants.

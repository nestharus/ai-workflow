## Still apply (no changes needed)

* **PRD #2 (typed cross-references):** Standardizing labeled relations in references (e.g., `members:`, `requires:`, `produces:`) to preserve machine-parseability/traceability.
* **PRD #4 (no-orphan/actionability invariant):** Enforcing that requirements/constraints are referenced (so they’re actionable) aligns with the “unreferenced constraints are meaningless” point.
* **Plan #1 (Refs everywhere):** Adding explicit `Refs:` fields so plan artifacts trace back to PRD IDs (prevents “recreated” requirements and supports coverage).

## Needs updates (conflicts with the conversation or depends on revised doc intent)

* **PRD #1 (CHO-XX + prose for choices):** Needs update because the conversation rejects embedding decision history/justifications inside the PRD and rejects expanding prose allowances.
* **PRD #2 (SET-XX usage as contract-format membership):** Needs update because the conversation accepts constraint grouping but rejects using SET-XX as “rules about how to write rules/contracts” (meta-formatting).
* **PRD #3 (SUR-XX added to the first PRD):** Needs update because the conversation flags (a) “audience” leakage risk and (b) that many surfaces are iteratively discovered and belong in a later structural/design layer, not the timeless PRD.
* **PRD #5 (algorithms declaring produced surfaces inside the PRD):** Needs update because it assumes surfaces live in the PRD and are stable there; the conversation shifts surfaces largely to the iterative structural layer.
* **Plan #2 (protocol payload change inside plan.md):** Needs update because it assumes plan.md is the place where Protocols live; the conversation questions whether plan.md should contain design topology at all.
* **Plan #3 (contracts include constraint sets inside plan.md):** Needs update for the same reason as above (plan vs design spec split), and because SET-XX semantics change.
* **Plan #4 (ticket acceptance criteria includes CHO / surface anchors):** Needs update because CHO-XX is rejected and because surface anchoring may move out of the PRD into the structural layer.
* **Plan #5 (choice refs CHO-XX in plan entities):** Needs update because CHO-XX is rejected from the PRD (and choice history is pushed elsewhere).

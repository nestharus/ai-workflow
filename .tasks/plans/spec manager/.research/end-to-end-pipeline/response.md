## Q1: Layer Activation and CI

**Recommended answer**

* **Propagation is necessary but not sufficient.** Keep `propagate_clean_to_next_layer()` as the mechanism that moves verified code upward, **and add an explicit “Downstream Readiness CI” check immediately after propagation** (before any creative L2/L3 work starts).
* **Demotion should switch the active creative layer downward.** When L2 emits any demotion → L1, **pause L2 creative work** (at least for MVP) until L1 rework lands in **L1 clean** and is **re-propagated** to L2 dirty.
* **Passive CI at upper layers is still valuable** (it catches merge/conflict/test regressions early), but creative work should remain single-layer-at-a-time.

**Rationale (1–3 sentences)**
Propagation proves “code moved”; it does not prove “code runs in the downstream lane/worktree”. A readiness CI step prevents starting architecture work on an un-runnable baseline and avoids wasting L2 tokens on work that will be invalidated by imminent L1 rework.

**Design implications**

* Drives **Q12** (what readiness tests are) and **Q2** (when tests run: after every propagation/batch).
* Drives **Q14** (conflict strategy) because demotions + propagation are the primary conflict source.
* Drives **Q5** (loop prevention): demotion-triggered active-layer switching must be budgeted.

---

## Q2: Batch Promotion Mechanics

**Recommended answer**

* **MVP default: batch size = 1 for dirty→clean.** Merge **one completed slice** into layer dirty, snapshot candidate, run CI, and if it passes promote to clean. This makes blame and recovery deterministic.
* **Tests at dirty→clean:** run **layer-appropriate “gate + test tier”** (see Q12). At minimum: (a) compile/import smoke, (b) all tests affected by the change set, and (c) a small integration tier. Prefer full suite at L3.
* **If dirty→clean fails:** with batch size=1, culprit is the merged slice. With batching enabled later, use **bisect on merge commits** and/or **DownwardFlowEngine** tracing to failing pins/atoms to route demotions.
* **Call `tick_pipeline()` after each slice integration** (not “after all slices”), but enforce backpressure so you don’t start a new candidate while one is failing.

**Rationale (1–3 sentences)**
Early end-to-end reliability depends more on deterministic blame than on throughput. Batch size=1 gives you clean failure attribution and simpler demotion routing, which you need before turning on higher-parallelism batching.

**Design implications**

* Drives **Q13** (Investigator invocation) because recovery can be scoped to a single slice commit.
* Drives **Q8/Q9** (CI stability and first-pass metrics become meaningful).
* Drives **Q5** (candidate-in-flight backpressure prevents infinite accumulation of unverified merges).

---

## Q3: Demotion Rework During Transitions

**Recommended answer**

* **Do not re-run “everything” blindly.** When a transition refinement emits tickets, re-run only the **owning slice** but pass **focus targets** derived from the ticket (`failing_files`, `failing_pins`, `failing_atoms`, `location.symbol`) so Plan/Implement converge on the right patch.

  * MVP: “owning slice + focus targets” (no new slice type needed).
  * Later: true narrow “ticket slice” objects.
* **After L1 rework, always flow through normal promotion again:** L1 rework → merge into L1 dirty → dirty→clean CI → **propagate clean→L2 dirty**. Do not “direct merge into L2 dirty” bypassing L1 clean.
* **Transition demotion loop limit:** cap each transition at **N rounds** (recommend **3**) before surfacing a “transition stuck” report and requiring human constraints or changing the manifest/spec.

**Rationale (1–3 sentences)**
Bypassing the “clean” lane breaks the invariant that higher layers only consume verified inputs. Focused rework avoids wasting iterations while keeping the safety guarantees of the normal promotion pipeline.

**Design implications**

* Drives **Q14** (propagation conflicts are resolved by rebase + re-run, not ad-hoc merges).
* Drives **Q5** (demotion-round caps + per-ticket retry budgets).
* Drives **Q6** (demotion history must record transition round/attempt context).

---

## Q4: Human Approval

**Recommended answer**

* **Keep L1 approval as mandatory** (it’s where under-spec decisions and intent alignment happen).
* Add an **optional L2 checkpoint** in interactive mode: approve **component manifest + topology + key tradeoffs** before starting L3 (because L3 “polishes” whatever architecture you froze).
* **Final signoff after L3** should exist as a lightweight “release approval” step (can auto-approve in auto/steering mode).

**Rationale (1–3 sentences)**
L1 approval prevents building the wrong thing; L2 checkpoint prevents polishing the wrong structure; L3 signoff gates release readiness and governance completeness.

**Design implications**

* Drives **Q7** (final consolidated report must support L2/L3 signoff).
* Drives **Q15** (governance checks must run on approval artifacts).
* Drives **Q5** (approval loops need a budget and must not induce infinite cycling).

---

## Q5: Termination and Loop Limits

**Recommended answer**

* **Per-slice max iterations:** make it layer-specific and configurable.

  * L1: **20** (reasonable)
  * L2: **30** (more search space + LLM gate tuning)
  * L3: **15** (review/refactor loop is expensive; stagnation should cut earlier)
* **Exit refinement demotions:** treat them as **new tickets** that reopen the necessary lower-layer work; do not “finish the layer anyway.”
* **Prevent infinite cycling via 4 budgets:**

  1. **Per-ticket retry budget** (e.g., same failing_files+gate repeats > 3 → escalate).
  2. **Per-transition demotion rounds** (e.g., L1→L2 gate demotes > 3 → stop).
  3. **Per-layer global demotion budget** (e.g., > X tickets in L2 without net progress → stop).
  4. **Overall pipeline pass cap** (e.g., > 2 full L1→L2→L3 restarts → stop).
* Add **stagnation detection**: if open gaps don’t decrease for K iterations (e.g., 3) or keep reappearing with high similarity, mark slice `STAGNATED` and escalate.

**Rationale (1–3 sentences)**
Without budgets, demotion + LLM variability can create perpetual loops. Stagnation detection makes “no progress” explicit and forces escalation rather than burning tokens.

**Design implications**

* Drives **Q8/Q9** (iteration efficiency becomes a score dimension and a stop condition).
* Drives **Q13** (Investigator budget should be bounded and counted against retries).
* Drives **Q1/Q3** (active-layer switching needs clear termination semantics).

---

## Q6: What Artifacts Should the Pipeline Produce?

**Recommended answer**

### MVP essentials (must exist)

1. **Working code**

   * L3 clean merged to `main` (or a release branch if you want manual merge).
2. **Evidence trail (append-only)**

   * All `EvidenceBundle` files + step outputs for every slice/iteration.
3. **Demotion ledger**

   * All tickets, hop traces, resolution status, and links to evidence.
4. **Architecture artifacts**

   * `component_manifest.json` + architecture graph/topology snapshot(s).
5. **Quality artifacts**

   * Aggregated reviewer findings + closure receipts per file/slice.
6. **Run summary + scorecard**

   * A single machine-readable `run_summary.json` plus a human-readable `final_report.md`.
7. **Approval artifacts** (interactive mode)

   * L1 overview(s), alignment summary, and recorded approval decisions/feedback.

### Can wait (post-MVP)

* Full **traceability matrix** requirement → function → tests (valuable but non-trivial).
* Deep **POWER alignment** lineage analysis beyond “findings + receipts”.
* Rich visualization dashboards (graphs, HTML reports).

**Rationale (1–3 sentences)**
MVP must support debugging, auditability, and repeatability. Traceability and rich reporting are additive once the end-to-end pipeline is stable.

**Design implications**

* Drives **Q7** (final consolidated report references these artifacts).
* Drives **Q11** (where scoring is computed and stored).
* Drives **Q15** (governance must validate artifact completeness).

---

## Q7: Human Review Document

**Recommended answer**

* Produce a **single consolidated run-level document** (separate from per-library overview.md) that references all artifacts.
* Contents (recommended minimum):

  * Executive summary (what was built, what changed, status)
  * Architecture topology summary (components, pins consumed, key flows)
  * Scorecard (per-layer + cross-layer)
  * Demotion summary (what got pushed down, why, final disposition)
  * Known risks / unresolved issues (if any)
  * Links/paths to evidence bundles and reports
* Include POWER alignment as:

  * **Embedded summary** (counts + high severity items)
  * References to the detailed alignment artifacts
* Treat the L1 approval doc as an **input checkpoint artifact**, not the final report.

**Rationale (1–3 sentences)**
Reviewers want one artifact that answers “is this shippable and why.” Per-library docs remain useful, but they’re not a run deliverable.

**Design implications**

* Drives **Q4** (L2/L3 signoffs become “approve sections” in this report).
* Drives **Q15** (governance checks must run on the final report content).
* Drives **Q6** (report must index the artifact set consistently).

---

## Q8: Scoring Dimensions

**Recommended answer**

* Your proposed mechanical dimensions are the right backbone. Add a small set of operational and governance dimensions so scoring reflects real pipeline health:

  * **CI stability**: dirty→clean pass rate per layer (first attempt and eventual).
  * **Stagnation rate**: % slices hitting stagnation detection or max iterations.
  * **Governance compliance**: count of governance FAIL/WARN; missing receipts.
  * **Blocking under-spec rate**: number of BLOCKED events per slice (L1 heavy).
* **LLM-as-judge numeric ratings** (e.g., “architecture 1–10”) can exist only as **soft signals** and must never gate promotion. If you include them, record them as “perception metrics” with low weight.

**Rationale (1–3 sentences)**
You need scores that diagnose throughput killers (CI instability, stagnation) and safety failures (governance). Numeric LLM judgments are unstable and are best treated as advisory.

**Design implications**

* Drives **Q9** (hard vs soft thresholds).
* Drives **Q11** (score aggregation must include CI + governance receipts).
* Drives **Q5** (stagnation is both a metric and a termination control).

---

## Q9: Score Computation and Thresholds

**Recommended answer**

* Prefer **mechanical computation** from stored artifacts whenever feasible:

  * L1 comment/stub counts via compliance scanner (deterministic).
  * CI results from test runner outputs (deterministic).
  * Iteration counts, ticket counts from orchestration state (deterministic).
* For L2/L3, some raw inputs are produced by LLM gates/reviewers; that’s fine, but scoring should be computed mechanically over their outputs (no second “judge pass” to count things).
* **Hard gates vs soft signals:**

  * **Hard gates (block pipeline / block merge):**

    * All required promotion gates PASS at final iteration (per slice).
    * Dirty→clean CI PASS at required tier.
    * Governance status != FAIL.
    * No HIGH-severity POWER drift/reward hacking.
  * **Soft signals (warnings, not blockers):**

    * First-attempt gate pass rate thresholds.
    * Demotion rate, churn, iteration efficiency.
* Avoid LLM scoring for counts; treat Phase 0’s fuzzy matching lesson as a general rule: use LLMs to *find candidates*, not to be the source of truth for arithmetic.

**Rationale (1–3 sentences)**
Hard gating should be based on deterministic or already-required pass/fail receipts. Scores should help interpret efficiency and risk, not introduce a second, noisy acceptance system.

**Design implications**

* Drives **Q11** (run emits raw receipts; separate report computes scores).
* Drives **Q12** (tests define CI pass receipts).
* Drives **Q10** (ground truth is optional for eval, not required for production).

---

## Q10: Ground Truth for L2/L3

**Recommended answer**

* **Production:** do not require a fixed “ground truth architecture” beyond what you already have:

  * component manifest + drift gate + pin consumption + boundary gates.
* **Evaluation mode:** optionally support:

  * “expected manifest constraints” (e.g., required components, forbidden edges),
  * or a “reference implementation” comparison (diff-based or behavior-based).
* Keep these as **eval-only**. Production should rely on gate convergence + CI.

**Rationale (1–3 sentences)**
Architecture and cleanliness are context-dependent; enforcing invariants is more robust than asserting a single intended structure. Eval can use stronger oracles without burdening production.

**Design implications**

* Drives **Q8/Q9** (some scores are best-effort indicators, not hard truth).
* Drives **Q6** (store manifest/topology snapshots to enable eval comparisons).

---

## Q11: Production Scores vs Eval Scores

**Recommended answer**

* **Production:** gates + CI receipts decide pass/fail/demotion (already true).
* **Scoring/reporting:** implement a **RunReporter** that reads:

  * EvidenceBundles, demotion ledger, CI receipts, and approval artifacts
  * and writes `scores.json` + `final_report.md`.
* `pdd_lifecycle.run()` should write:

  1. raw receipts and state (for machine use), and
  2. the computed scorecard (for humans/CI dashboards).
     EvalRunner can remain separate and additionally compute benchmark metrics.

**Rationale (1–3 sentences)**
Keep decision logic simple and auditable. Reporting is a pure aggregation step and should not affect control flow.

**Design implications**

* Drives **Q6/Q7** (final deliverables).
* Drives **Q9** (mechanical aggregation is feasible if receipts are persisted).

---

## Q12: Test Strategy

**Recommended answer**

### Test tiers (recommended)

* **Tier 0: Smoke**

  * `python -m compileall` (or equivalent)
  * “import graph smoke” (import key modules)
* **Tier 1: Unit**

  * fast unit tests, per-library or per-slice selection
* **Tier 2: Integration**

  * component wiring tests (L2), cross-library integration (L1/L2)
* **Tier 3: Full regression**

  * entire suite, plus any slow e2e checks

### What runs where

* **L1 dirty→clean:** Tier 0 + Tier 1 + minimal Tier 2 (cross-library sanity).
* **L2 dirty→clean:** Tier 0 + Tier 1 + Tier 2 (wiring/topology).
* **L3 dirty→clean:** Tier 0 + Tier 1 + Tier 2 + Tier 3 (full regression) + diff-impact classifier.
* **Cross-layer principle:** upper layers run **all lower-layer tests relevant to the code they contain**, but you can skip redundant reruns when commits are identical.

### If the target codebase has no tests

* L1 should generate minimal tests around atoms/stores as part of implementation (enough to satisfy ALL_TESTS_PASS meaningfully).
* Always run Tier 0 smoke as the baseline safety check.

**Rationale (1–3 sentences)**
L1 validates behavior; L2 validates wiring; L3 validates preservation. Tiering lets you enforce safety while controlling cost.

**Design implications**

* Drives **Q2** (what dirty→clean runs).
* Drives **Q13** (Investigator needs a reproducible test command).
* Drives **Q9** (CI stability metrics).

---

## Q13: Recovery from Test Failures

**Recommended answer**

* **IntegrateStep failure flow (recommended):**

  1. Capture failure evidence (logs, failing files, stack traces).
  2. Invoke **Investigator** immediately with a strict budget:

     * max attempts (e.g., 2)
     * must produce a patch that respects layer constraints
     * must produce root-cause summary + evidence references
  3. If Investigator succeeds: apply patch in the correct layer worktree and retry CI.
  4. If Investigator fails: invoke **DownwardFlowEngine** to trace pins/atoms and emit DemotionTickets.
* Do not invoke Investigator “instead of tickets”; invoke it **before tickets** and attach its report to the ticket when it gives up.

**Rationale (1–3 sentences)**
Many failures are small integration issues that can be fixed locally without demotion churn. When a fix requires illegal changes, demotion is still the correct mechanism.

**Design implications**

* Drives **Q2** (batch size 1 makes Investigator scope small).
* Drives **Q6** (store Investigator reports as artifacts).
* Drives **Q5** (Investigator attempts count toward retry budgets).

---

## Q14: Worktree Merge Conflicts

**Recommended answer**

* **Yes, conflicts can arise** (especially when L1 demotions happen while L2 has diverged).
* Preferred resolution strategy:

  1. **Rebase downstream dirty onto upstream clean** (preserve downstream commits if possible).
  2. If conflicts remain, **do not “manual merge” logic.** Instead:

     * emit tickets to re-run the affected downstream slices (L2 wiring re-assembly, L3 refactor re-application) against the new upstream baseline.
  3. Use an LLM merge agent only when:

     * conflict is confined to **wiring_only** or **refactor_only** regions, and
     * diff-impact classifier indicates no behavior ambiguity.
  4. If still unresolved: block and escalate (interactive approval required).

**Rationale (1–3 sentences)**
Most downstream work is derivative and can be regenerated; forcing merges risks silent logic drift. Rebase + re-run preserves invariants and keeps layer legality intact.

**Design implications**

* Drives **Q1/Q3** (demotion pauses higher-layer creative to reduce conflicts).
* Drives **Q12** (tests validate conflict resolution).
* Drives **Q15** (governance must flag “unreceipted conflict resolutions”).

---

## Q15: Governance Integration

**Recommended answer**

VerifyStep integration is necessary, but add governance at three additional levels:

1. **Transition governance gate** (L1→L2, L2→L3)

   * Ensure no open governance findings; ensure required receipts exist; ensure manifest/alignment artifacts are present.
2. **Dirty→clean promotion governance gate**

   * Confirm candidate has full CI receipts; confirm no missing evidence files; confirm decision logs updated.
3. **Final governance gate (pre-merge / pre-release)**

   * Whole-run oversight pass + report validation + artifact completeness checks.

Also run governance on the **final report** to ensure it includes mandatory sections and links to evidence.

**Rationale (1–3 sentences)**
Per-slice oversight can miss run-level omissions (missing reports, missing approvals, incomplete ledgers). Governance must also validate the integrity of the pipeline’s final outputs.

**Design implications**

* Drives **Q6/Q7** (reports must be structured and checkable).
* Drives **Q5** (governance FAIL is a hard stop).
* Drives **Q9/Q11** (scores include governance status).

---

# Complete End-to-End Pipeline Execution Flow

Below is the recommended end-to-end orchestration (compatible with your current sequential lifecycle, but adds the missing CI/readiness/governance loops).

## 0) Run setup

1. Allocate `run_id`.
2. Create run directories:

   * `.pdd_runs/<run_id>/...` (evidence + ledgers)
   * `reports/pdd/<run_id>/...` (human + scorecard outputs)
3. Create `pdd/<run_id>/base` ref (optional but recommended).

## 1) Phase 0 intake (optional)

**Decision:** input is raw prose?

* If yes: Phase 0 Intake → PDD skeletons (libraries) + coverage ledger.
* Commit result to `pdd/<run_id>/base`.

**Loop limit:** Phase 0 rework max 2 passes (only if coverage < 100% or fatal routing overlap).

## 2) Worktree setup

* `setup_layers(base_ref = pdd/<run_id>/base or main HEAD)`
* Worktrees: `l1/{dirty,clean}`, `l2/{dirty,clean}`, `l3/{dirty,clean}`, plus slice worktrees for the active layer.

## 3) L1 (Code-as-Spec)

1. **Entry library refinement** (L1 entry).
2. Discover L1 slices (libraries).
3. Run L1 PromotionLoops in parallel (max_parallel configurable).

   * After each slice integrates: **tick CI pipeline** (dirty→candidate→clean→propagate).
4. **Exit library refinement** (L1 exit).
5. Generate:

   * per-library overview.md
   * alignment summary
6. **Human approval loop** (max 3 iterations):

   * approve → continue
   * feedback → re-enter L1 (repeat steps 1–5)
   * quit → stop

**Loop limits**

* Per-slice: max 20 iterations + stagnation detection
* Approval: max 3 iterations (already)

## 4) L1→L2 transition gate

1. Run architectural refinement (transition).

2. If demotion tickets emitted:

   * enqueue tickets (target L1)
   * run L1 rework (focused slices)
   * require CI pass and re-propagation
   * repeat transition gate (max 3 rounds)

3. **Propagation**: ensure `L1 clean → L2 dirty` is up-to-date.

4. **Downstream readiness CI (L2 dirty)**: smoke + baseline tests.

## 5) L2 (Architecture)

1. L2 entry architectural refinement (establish/refresh component manifest).
2. Discover L2 slices (components).
3. Run L2 PromotionLoops in parallel.

   * After each slice integrates: tick CI pipeline.
4. L2 exit architectural refinement.
5. Optional human checkpoint (interactive): approve architecture topology before L3.

**Loop limits**

* Per-slice: max 30 iterations + stagnation detection

## 6) L2→L3 transition gate

Same structure as L1→L2:

* transition refinement (code quality)
* demotions → rework at L2 or L1 (focused)
* max 3 rounds
* ensure `L2 clean → L3 dirty`
* readiness CI (L3 dirty)

## 7) L3 (Clean Code)

1. L3 entry code quality refinement baseline.
2. Discover L3 slices (files).
3. Run L3 PromotionLoops in parallel.

   * After each slice integrates: tick CI pipeline.
4. L3 exit code quality refinement.

**Loop limits**

* Per-slice: max 15 iterations + stagnation detection

## 8) Final QA + final governance + merge

1. Run QA eval framework.
2. Run final governance gate (whole-run).
3. Generate final report + scorecard.
4. Merge L3 clean to main (or produce release branch + tag).

---

# Final Output Specification

## Directory layout (recommended)

### Evidence + ledgers (append-only, machine-first)

`/.pdd_runs/<run_id>/`

* `run_config.json` (inputs, thresholds, test commands, model IDs)
* `run_state.json` (active layer, SHAs, budgets consumed)
* `slices/<slice_id>/iter_###/bundle.json` (+ all step artifacts referenced by bundle)
* `demotions/`

  * `tickets/<ticket_id>.json`
  * `ledger.jsonl` (state transitions: emitted → applied → resolved)
* `ci/`

  * `l1/batches/<batch_id>.json` (candidate SHA, test results, promotion receipts)
  * `l2/batches/...`
  * `l3/batches/...`
* `approvals/`

  * `l1/iteration_#/decision.json` (+ referenced overview/alignment)
  * `l2/decision.json` (if enabled)
  * `l3/release_decision.json`

### Human deliverables (stable paths, easy to read)

`/reports/pdd/<run_id>/`

* `final_report.md` (single consolidated run doc)
* `scorecard.json` (machine-readable)
* `scorecard.md` (human-readable)
* `architecture/`

  * `component_manifest.json`
  * `architecture_graph.json` (or snapshots per iteration)
  * `architecture_decisions.md` (if you record decisions separately)
* `quality/`

  * `review_findings.json` (aggregated)
  * `closure_receipts.json` (what passed, when)
* `alignment/`

  * `alignment_summary.json`
  * `alignment_findings.json`
* `traceability/` (post-MVP)

  * `traceability.csv/json`

## Git refs (recommended)

* `pdd/<run_id>/base` (post-intake baseline)
* `pdd/<run_id>/l1/clean`, `.../l2/clean`, `.../l3/clean`
* Tags:

  * `pdd/<run_id>/l1-approved`
  * `pdd/<run_id>/l2-approved` (optional)
  * `pdd/<run_id>/final`

---

# Scoring Framework

## Scorecard model (recommended)

Each metric emits:

* `raw` (measured value)
* `score` (0–100 normalized)
* `status` (PASS/WARN/FAIL)
* `hard_gate` (bool)
* `evidence_refs` (paths into `.pdd_runs/<run_id>/...`)

## Metrics, computation, thresholds

### Hard gates (block merge/release)

| Metric                  | Layer    |                                             Computation | Pass threshold | Notes                                        |
| ----------------------- | -------- | ------------------------------------------------------: | -------------: | -------------------------------------------- |
| `gates.final_pass`      | L1/L2/L3 |      all promotion gates PASS on final slice completion |           100% | Already enforced by loop; recorded for audit |
| `ci.final_pass`         | L1/L2/L3 | dirty→clean promotion CI receipts PASS at required tier |           100% | Defines “verified”                           |
| `governance.no_fail`    | All      |                    governance findings with status FAIL |              0 | WARN allowed but scored                      |
| `alignment.no_high`     | All      |             HIGH severity drift/reward-hacking findings |              0 | Blocks release                               |
| `l3.no_behavior_change` | L3       |               diff-impact classifier != behavior_change |           PASS | Blocks release                               |

### Soft signals (diagnostics / quality indicators)

| Metric                          | Layer |                                            Raw computation | PASS / WARN / FAIL (default)         | Why it matters                |
| ------------------------------- | ----- | ---------------------------------------------------------: | ------------------------------------ | ----------------------------- |
| `l1.gap_closure`                | L1    |                  1 - (final_open_gaps / initial_open_gaps) | PASS=1.0, WARN≥0.99, FAIL<0.99       | Detects dropped spec work     |
| `l1.gate_first_attempt_rate`    | L1    | slices passing all gates on first promote attempt / slices | PASS≥0.6, WARN≥0.4                   | Planning quality              |
| `l2.pin_consumption_rate`       | L2    |                     consumed_pins / promoted_pins_in_scope | PASS=1.0, WARN≥0.95                  | Architecture completeness     |
| `l2.component_coverage`         | L2    |               implemented_components / manifest_components | PASS=1.0, WARN≥0.98                  | Manifest realization          |
| `l2.gate_first_attempt_rate`    | L2    |                                first-attempt pass / slices | PASS≥0.5, WARN≥0.3                   | Architecture iteration health |
| `l3.reviewer_first_pass_rate`   | L3    |        files passing all reviewers on first review / files | PASS≥0.4, WARN≥0.2                   | Clean-code efficiency         |
| `l3.refactor_churn`             | L3    |                 changed_LOC / total_LOC (in touched files) | PASS≤0.15, WARN≤0.30                 | Risk proxy                    |
| `pipeline.total_demotions`      | All   |                                      total tickets emitted | PASS≤(slices*0.5), WARN≤(slices*1.0) | Stability signal              |
| `pipeline.iteration_efficiency` | All   |                            total_iterations / total_slices | PASS≤3, WARN≤6                       | Throughput signal             |
| `pipeline.ci_first_pass_rate`   | All   |       successful dirty→clean on first attempt / promotions | PASS≥0.8, WARN≥0.6                   | CI health                     |
| `pipeline.stagnation_rate`      | All   |                            stagnated_slices / total_slices | PASS=0, WARN≤0.05                    | Detects “stuck” behavior      |

**Threshold policy**

* Hard gates: always block.
* Soft signals: warnings by default; optionally block in strict CI mode.

**Where to compute**

* Compute in a `RunReporter` at end of `pdd_lifecycle.run()` (and optionally after each layer) by aggregating EvidenceBundles + CI receipts + demotion ledger.

---

# CI Flow: Worktrees, Tests, Promotions, Conflicts

## Core pipeline mechanics

```text
(active layer only does creative work)

Slice worktree (grandchild)
  → merge → Layer dirty
     → snapshot candidate (dirty HEAD)
        → run layer CI (tests + required gates)
           PASS → fast-forward Layer clean to candidate
                 → propagate Layer clean → next Layer dirty
                 → (repeat upward)
           FAIL → recovery (Investigator) else DownwardFlow demotion
```

## Recommended CI locking / backpressure

* One candidate per layer at a time.
* If candidate FAILS: freeze promotion for that layer until fixed (don’t create new candidate).
* Optional: allow merging more slices into dirty while candidate in flight, but do not include them in the current candidate (keep candidate ref stable).

## Conflict handling (recommended default)

* Slice→dirty merge conflict:

  * try rebase slice onto dirty and re-merge once
  * if still conflict → emit ticket + block slice
* Clean→next dirty propagation conflict:

  * attempt rebase downstream dirty onto upstream clean
  * if conflicts persist → emit ticket to regenerate/re-run affected downstream slices
  * LLM merge agent only when conflict is wiring_only/refactor_only

---

# Termination Criteria

## Per-slice termination (PromotionLoop)

A slice is complete when:

* `open_gaps == 0`
* last iteration ends with PROMOTE + INTEGRATE + VERIFY + ALIGN all returning OK
* no unresolved demotion tickets remain targeting the slice

## Per-layer termination

A layer is done when:

* all discovered slices are COMPLETE (or explicitly SKIPPED with receipt)
* layer is **clean**: `dirty == clean` (no pending commits)
* no pending demotions target this layer
* exit refinement produced no new blockers/demotions

## Overall termination

Pipeline completes when:

* L3 clean is produced and CI receipts PASS
* QA run executed (pass rate recorded; can be hard/soft per config)
* final governance gate PASS
* final report + scorecard written
* merge/tag action completed

## Infinite-loop prevention (summary)

* Per-slice max iterations (layer-specific)
* Per-ticket retry budget
* Per-transition demotion round cap
* Global pipeline pass cap
* Stagnation detection and escalation

---

# Recovery Flow: Investigator vs DemotionTickets

## When Investigator runs

Trigger Investigator on:

* dirty→clean test failure
* propagation failure that breaks CI
* intermittent failures that reproduce deterministically in the candidate worktree

**Investigator constraints**

* fixed attempt budget
* must respect layer legality
* must produce: root cause, reproduction steps, patch, evidence refs

## When DemotionTickets are created

Create tickets when:

* Investigator cannot fix within legality/budget
* gate failure indicates illegal change required in current layer
* VerifyStep governance FAIL (block immediately)
* diff-impact classifier says behavior_change (L3→L1) or wiring_only (L3→L2)

Tickets must include:

* hop trace
* failing files/pins/atoms where available
* evidence refs (logs, verify notes, reviewer output)

---

# Governance Model Beyond VerifyStep

## Where governance runs (recommended)

1. **Per-slice, per-iteration** (already in VerifyStep)
2. **Per-layer dirty→clean promotion gate**

   * validates CI receipts + evidence completeness before advancing clean
3. **At transitions (L1→L2, L2→L3)**

   * validates: no open governance FAIL, manifest/decision artifacts present
4. **Final whole-run governance**

   * validates final report completeness, no missing receipts, no decision injection patterns

## Governance failure semantics

* **FAIL**: hard stop + ticket targeting current layer (category=GOVERNANCE)
* **WARN**: allowed but recorded and scored; may block in strict mode

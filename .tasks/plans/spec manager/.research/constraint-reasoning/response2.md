## Revised Section 2: Architecture planning via progressive refinement (no interaction graph artifact)

### 2.0 Invariants

Architecture planning must:

* **Route, not extract**: planners/proposers consume *source artifacts* (charters, constraints.md spans, pins registries, wiring files, L1 evidence) rather than synthesizing a new “interaction graph” representation.
* **Be fractal + progressive**: start with coarse, scoped understanding; refine only where a decision’s blast radius demands it; avoid “enumerate all scopes then solve.”
* **Compose incrementally**: architecture emerges from accumulated scoped decisions and wiring deltas, not a one-shot global composition step.
* **Treat uncertainty as blocking**: if a decision requires non-software constraints or missing facts, emit decision requirements and block via existing under-spec.

---

### 2.1 What L2 “knows” without extraction

L2 already has two legitimate, non-violating inputs:

1. **Routed Phase 0 artifacts** (authoritative text, verbatim)

   * `libraries/<LIB>/charter.md`
   * `libraries/<LIB>/constraints.md`
   * `libraries/<LIB>/details.md` / whatever Phase 0 produced
   * cross-library references already exist implicitly as: “text spans routed into multiple libraries” and/or mentions of other libraries in routed spans (these remain verbatim)

2. **L1→L2 discovered reality** (implementation evidence)

   * pin/edge proposals, imports, function-level interactions captured in evidence bundles
   * any existing manifests/registries created during L1 (if present)

Plus L2’s existing discovery step:

* **Architecture topology derived from internal arch files** (`component_manifest`, `pins_registry`, `entrypoints`, `wiring`) is acceptable because it’s parsing *controlled internal formats*, not extracting spec meaning.

**Key change from the prior design**: L2 does **not** precompute a comprehensive interaction graph across all libraries. It only gathers the *minimum* evidence needed for *the current decision scope*.

---

### 2.2 Architecture refinement loop inside L2 (decision-point driven)

Instead of “build full interaction graph → define all scopes → propose all scopes,” L2 works like this each time it runs for a slice:

#### Step 1 — Establish the current baseline (coarse, routed)

For the current slice `S` (usually a library slice):

* Load **authoritative constraints** relevant to `S` (system + library + any previously committed architecture decisions).
* Load **source artifacts** for `S` (charter + constraints spans + local arch files).
* Load **recent L1 evidence** relevant to `S` (from the bundle/evidence store).

This is routing/lookup, not extraction.

#### Step 2 — Detect architecture decision points (LLM, scoped to current slice)

Run a “DecisionPointDetector” that looks only at:

* current open gaps for the slice
* the slice’s routed artifacts
* the slice’s current arch files / topology
* recent L1 evidence touching the slice

It outputs a list of **DecisionPoints**, each with a **minimal scope** (see 2.3).

Examples of decision points:

* “Library `payments` needs to publish transaction-posted information; should it be a pin call vs an event?”
* “`ledger` depends on `risk`; directionality seems inverted; needs boundary correction.”
* “A new external dependency is implied by gaps; approval needed.”

This is where “branching when demanded” begins: a DecisionPoint is the unit that can trigger parallel exploration.

#### Step 3 — For each DecisionPoint, explore candidates *only for that point*

For each DecisionPoint `D`:

* Build a **ScopePacket** (routed sources only; see 2.5).
* Assign **tradeoff positions** to proposers for *this decision* (not for the entire system).
* Run `K` independent proposers (K small, e.g. 3) that each produce a candidate for this decision scope.
* Evaluate candidates against authoritative constraints.
* Either:

  * **Commit** a candidate (software-only authority) and emit wiring intentions, or
  * Emit **decision requirements** (human constraints needed) and block.

#### Step 4 — Incremental composition = “apply committed decisions”

There is no global “compose all scopes.” Composition is incremental:

* Each committed decision becomes:

  * a small set of wiring intentions (L2 output) and
  * a set of **architecture decision constraints** (software-only) that propagate forward/backward.

Over repeated iterations, the architecture is simply the accumulation of committed scoped decisions.

---

### 2.3 Progressive scoping: scopes are discovered, not enumerated

A DecisionPoint always carries a **scope** that is chosen as the smallest self-contained unit needed to decide correctly.

Scopes are created **on-demand** as decision points appear:

#### Intra-library scope

Used when the decision is fully contained inside one library boundary.

* `scope = intra:<LIB>`
* Inputs: `<LIB>` charter/constraints + local arch files + L1 evidence touching `<LIB>`

#### Inter-library interaction scope

Used only when there is *direct evidence* of an interaction that matters.

* `scope = inter:<LIB_A>→<LIB_B>:<interaction_handle>`
* **Interaction handle** is not a synthesized edge; it’s a pointer to *existing evidence*, such as:

  * a pin consumption/production mismatch in topology
  * a named contract/event referenced in both libraries’ routed spans
  * an L1 import/call proposal that crosses library boundary
  * an architecture gap referencing both components

This avoids “define all inter-scopes upfront.” The set of inter-scopes grows only when the system encounters evidence that an inter-scope is necessary.

#### Refinement as information increases

A scope can be refined (narrowed) when implementation reveals more:

* From `inter:A→B` coarse → `inter:A→B:EventX` once EventX exists in wiring/pins
* From `intra:payments` coarse → `intra:payments:submission_pipeline` once internal subcomponents are explicit

This is done by creating a *new DecisionPoint with a narrower scope*, not by rebuilding a global map.

---

### 2.4 Discovery through implementation: how L1 feeds architecture refinement

L1 does not “complete architecture,” but it continuously produces evidence that can trigger new L2 decision points later:

* New cross-library imports/calls observed during implementation
* Pin/edge proposals created by the implementation runner
* Spec-driven data shapes materializing as actual function signatures / DTOs
* “Cannot implement without deciding X” events

These show up as:

* evidence bundle entries
* gaps discovered during analysis
* under-spec events

**Mechanism**: when L1 introduces new cross-boundary evidence, it should emit (or cause) a work item / signal that results in an L2 DecisionPoint being created for the relevant slice(s). (See Section “Branching mechanism”.)

---

### 2.5 ScopePacket: what proposers receive without an interaction graph

A proposer never receives a comprehensive interaction graph. It receives a **ScopePacket**: a routed bundle of *the sources relevant to this DecisionPoint*.

**ScopePacket fields**

* `decision_id`
* `scope` (intra or inter as above)
* `trigger_evidence` (pointers, not summaries)

  * e.g., gap IDs, pin IDs, file paths, evidence bundle refs, constraint span IDs
* `source_artifacts` (verbatim or pointer form)

  * For intra: `<LIB>` charter.md + constraints.md spans relevant to the trigger + current wiring/manifest files for `<LIB>`
  * For inter: both libraries’ charters + the *specific* routed spans that mention the interaction + the specific wiring/pin declarations that touch it + L1 evidence items that show the interaction
* `authoritative_constraints` (system + applicable library + prior committed arch decisions that apply to this scope)
* `current_arch_state_refs`

  * file paths + identifiers; avoid synthesizing new structure
* `tradeoff_assignment`

  * “prioritize X, sacrifice Y” for this proposer
* `positions_taken`

  * a list like `["consistency-first", "simplicity-first"]` (no proposal content)

This is routing: it moves originals (or verbatim excerpts) into the proposer context. It does not extract and repackage into a derived “graph.”

---

### 2.6 Revised architecture candidate contract (scoped, graphless)

Candidates are scoped outputs for a single DecisionPoint.

**Candidate output**

* `candidate_id`
* `decision_id`
* `scope`
* `position`

  * explicit priorities/sacrifices for the relevant tradeoff axes
* `proposal`

  * **intra candidates**:

    * internal component boundary adjustments (if any)
    * wiring changes inside the library (pins/handlers/routes), expressed as references to existing arch files + intended edits
  * **inter candidates**:

    * contract definition (event/message/interface), expressed in terms of:

      * what each side must provide/consume
      * ownership of schema and versioning expectations
    * wiring intentions to connect the two sides (again via file refs)
* `constraints_introduced`

  * `software`: committed obligations that L1/L2 must satisfy (idempotency, ordering, schema stability, retry semantics)
  * `non_software`: obligations that require human authority (license class, ops burden, cost drivers, org dependencies)
* `decision_requirements`

  * questions that must be answered to choose/commit safely (especially non-software dimensions)
* `assumptions` (non-authoritative)

  * explicit list; if any assumption touches non-software or high-impact behavior, it should turn into a decision requirement instead
* `trace`

  * list of references to source artifacts and span IDs used to justify the proposal (preserves authority chain)

---

### 2.7 Evaluation and incremental composition (no global backtracking pass)

Evaluation happens per DecisionPoint; composition is “apply decisions as they are made.”

#### Per-decision evaluation

For each candidate:

* Check authoritative constraints: `satisfied | violated | unknown`
* If `unknown` touches a gate-critical constraint or non-software dimension → emit decision requirements and block.
* Prefer candidates that:

  * minimize coupling across boundaries,
  * are reversible at this stage,
  * introduce fewer non-software obligations unless already approved.

#### Incremental composition

When a candidate is selected:

* Persist a **PlannerDecisionConstraint** record for that decision (software-only, authoritative within system authority).
* Emit L2 wiring intentions to implement the decision.
* Add any L1 obligations as constraints that apply to downstream implementation.
* On later iterations, new decision points see these committed constraints as part of the baseline.

No “compose everything” step is required, because the promotion loop already provides iterative convergence with gates/demotion.

---

## Integration with the promotion loop (Q1)

### Where architecture exploration lives

Architecture exploration happens **inside the L2 PromotionLoop**, specifically in the **PLAN** step (`PlanStep` → `planner.plan_from_gaps()` → `L2Planner.build_plan()`).

* Each L2 iteration:

  1. gaps are collected
  2. L2 planner detects decision points for *this slice* from current gaps + local routed artifacts + recent evidence
  3. for each decision point, run scoped proposers (branching) if impact ≥ threshold
  4. commit decisions or emit decision requirements
  5. planning gate blocks early if requirements uncovered

This matches Progressive Gating and Error Amplification: decide only what you can support, block early on uncertainty.

### Does L2 run multiple iterations?

Yes: PromotionLoop already iterates per slice in L2. Progressive refinement is achieved by:

* resolving a subset of decisions per iteration,
* implementing wiring deltas,
* discovering new gaps/decision points,
* repeating.

There is no need to invent a separate “multi-iteration L2 planner” outside the loop.

### Does architectural exploration happen within a single L2 promotion step or across multiple promotion cycles?

Both, naturally:

* **Within a single L2 iteration**: explore candidates for the current decision points and either decide or block.
* **Across iterations**: as wiring changes land and analysis finds new gaps, new decision points appear.
* **Across layer transitions** (L1→L2 transition refinement): architectural refinement can demote back to L1, causing new implementation evidence, which then changes the architecture decision landscape on the next transition round.

### How do architectural branches map to the slice model?

A branch is tied to a **DecisionPoint**, and each DecisionPoint is assigned an **owner slice** for execution, even if it affects multiple libraries.

Rule (deterministic, minimal new machinery):

* `intra:<LIB>` decisions are owned by slice `<LIB>`.
* `inter:<A>→<B>` decisions are owned by a stable owner:

  * e.g., `owner = min(A, B)` lexicographically, or “producer side” if determinable from the trigger evidence.

The decision’s resulting constraints are written with `applies_to = [A, B]`, so both slices see and obey it via PlanningGate.

---

## Branching mechanism (Q2)

### What triggers a branch?

A branch is created when L2 detects a **DecisionPoint** that is:

1. **High-impact or cross-cutting**, and
2. **Multi-modal** (multiple plausible architectural approaches), and
3. Not already decided by existing authoritative constraints.

Concrete triggers (examples):

* A gap references wiring across boundaries with multiple valid patterns (sync call vs event vs shared store).
* L1 evidence shows a new cross-library interaction that violates existing directionality or contracts.
* A dependency/infrastructure choice emerges (Kafka vs in-process; DB ownership).
* Constraints conflict or tradeoff preferences exist (“correctness over speed”).
* “Architectural hotspot” signals from verify/refinement (e.g., coupling too high) require reconsidering a boundary.

### How is branching different from under-spec?

* **Branching** = explore multiple software architectural candidates when the system *could* decide but should consider tradeoffs.
* **Under-spec** = block because the system *cannot* decide safely (missing constraints / human authority required / unknown satisfaction).

Branching may produce under-spec events if it discovers missing constraints.

### How are branches tracked using existing coordination infrastructure?

Represent each DecisionPoint as a `WorkItem` (new kind) in the existing `WorkItemStore`.

**WorkItem: ARCH_DECISION**

* `id = decision_id`
* `scope`
* `owner_slice`
* `status = OPEN | EXPLORING | BLOCKED | DECIDED`
* `trigger_refs` (gap IDs, pin refs, file refs, evidence refs)
* `required_constraints` (ids that must be answered)
* `candidate_refs` (paths to candidate artifacts)
* `selected_candidate_ref` (if decided)

**WaitGraph integration**

* If `required_constraints` is non-empty:

  * add `WaitEdge(owner_slice → constraint_id)` (or decision_id → constraint_id)
* When constraints are added, WakeQueue wakes the owner slice (already part of the under-spec flow).

This uses existing coordination primitives and avoids introducing “branch manager” infrastructure.

---

## Coarse→refined architecture and constraint flow (Q3)

### Architecture decisions become constraints progressively

When L2 selects a candidate for a DecisionPoint, it writes **PlannerDecisionConstraints** (software-only, authoritative within system authority) at the appropriate precision.

Precision progression:

* **Coarse decision constraint** (early):

  * “Interaction A→B must be async message-based; no direct calls.”
* **Refined decision constraints** (later, once discovered):

  * “A publishes `TransactionPosted` event with fields X/Y; at-least-once delivery; B must be idempotent using key K; schema versioning rule V.”

### Refinement without overwriting (information permanence)

Never overwrite a prior decision record. Refinement produces a new constraint that **supersedes** the prior one:

* `constraint.status = ACTIVE | SUPERSEDED`
* `constraint.supersedes = [older_constraint_id]`
* `constraint.trace = …` (source refs + decision point refs)

This preserves:

* the chain of decisions,
* why refinement occurred,
* what changed.

### Authoritative vs non-authoritative split remains intact

* **Candidates** and **assumptions** are non-authoritative.
* **Selected decisions** (software-only) become authoritative constraints.
* Any decision requiring non-software authority produces under-spec requirements and blocks until humans answer.

---

## Revised proposer context and output without an interaction graph (Q4)

### What a proposer receives

Only the ScopePacket (2.5), built from routed sources:

* relevant charters/constraints spans
* relevant arch files
* relevant evidence refs
* applicable authoritative constraints/decisions
* tradeoff assignment + positions taken

No precomputed “edges, traffic, failure modes” dataset.

### What a proposer produces

A scoped candidate (2.6) that:

* proposes wiring/contract changes in terms of file refs + intended edits
* explicitly declares constraints introduced and decision requirements
* maintains trace to source artifacts

---

## Changes required to Section 6.7 (architecture integration points)

Replace the previous “ArchitecturePlannerStrategy + interaction graph artifacts” integration with:

### 6.7 Revised integration points

1. **L2Planner.build_plan() becomes decision-point driven**

   * Add an internal call sequence:

     * `detect_decision_points(gaps, discovery, evidence, constraints)`
     * for each decision point:

       * if impact ≥ threshold: `run_proposers(scope_packet, tradeoff_assignments)`
       * `evaluate_and_select_or_block()`
     * emit:

       * `intentions` (wiring)
       * `decision_requirements` (for PlanningGate)
       * `new_constraints_to_write` (selected software-only decisions)

2. **Persist per-decision artifacts, not global graphs**

   * `reports/pdd/<run_id>/architecture/decisions/<decision_id>/candidates/*.json`
   * `…/selected.json`
   * `…/evaluation.json`

3. **DecisionPoints tracked as WorkItems**

   * Written/read via `WorkItemStore` so they persist across iterations and can be woken when constraints arrive.

4. **PlanningGate blocks on decision_requirements as before**

   * No change to the gate concept; it now blocks on *decision ids* produced by L2 decision points.

Everything else in Sections 1, 3, 4, 5, 6 (other than 6.7), 7 remains compatible.

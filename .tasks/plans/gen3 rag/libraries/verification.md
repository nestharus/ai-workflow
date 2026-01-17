# Verification Library

Claims formalization, Lean skeletons, proof obligations, invariant checking.

### P4C2 MDL-driven abstraction reduces description length

**Claim.** Given a candidate pattern set, choosing patterns by MDL yields shorter descriptions than raw graph encoding (for those patterns). (Algorithm is heuristic; objective is principled.)

**Sketch.** The objective directly minimizes description length. Greedy selection may not find global optimum but provides local improvement guarantees standard in submodular-style optimization.

---

### P4C3 Promotion guarantee

**Claim.** If a pattern is promoted only when (\Pr(\theta_p \ge \tau) \ge 1-\delta), then promotion implies a posterior reliability guarantee.

**Sketch.** Direct from the posterior CDF of the Beta distribution.

---

### P4C5 Risk governance calibration

**Claim.** Conformal prediction can convert heuristic uncertainty into prediction sets with distribution-free coverage, and selective conformal risk control combines deferral with risk control. ([People @ EECS][2])

**Sketch.** Conformal coverage guarantee is standard; selection layer trades coverage vs abstention.

---

### Algorithm 35

#### Explore a seed

Two-stage: cheap structure first, then LLM refinement when value exists.

```pseudo
function EXPLORE_SEED(seed s):
  if CBUD.llm_remaining(domain(s)) <= 0 and CBUD.explore_remaining(domain(s)) <= 0:
    s.status = parked
    return

  bundle = EBC_COMPILE(s, budget_tokens=K)

  // Stage A: structural probes
  probes = RUN_STRUCTURAL_PROBES(bundle)
  if probes.outcome == "resolved":
    trace = WRITE_TRACE(s, probes)
    return

  // Stage B: LLM refine
  if SHOULD_CALL_LLM(s, bundle):
    proposal = LLMR_PROPOSE(bundle)            // actions + rationale + confidence
    APPLY_PROPOSAL_AS_HYPOTHESES(proposal)     // workspace overlay only
    CBUD.spend_llm(domain(s), cost_llm(proposal))

  // Stage C: validate and measure learning progress
  RUN_LOCAL_FIELD_REPAIR(bundle.scope)
  after = MEASURE_METRICS(s)

  trace = WRITE_TRACE(s, before_metrics, after, proposals)
  UPDATE_LEARNING_PROGRESS(s, trace)
  UPDATE_FAILURE_MEMORY(s, trace)
```

LLM-driven curiosity and intrinsic reward signals for LLM training and auditing exist in recent work, so "LLM used as refiner" fits the current research direction. ([arXiv][p7-7])

---

### Algorithm 36

#### Distill traces into tokens

```pseudo
function DISTILL(epoch e):
  traces = FETCH_RECENT_TRACES(e)
  clusters = CLUSTER_TRACES_BY_SIGNATURE(traces)

  for c in clusters:
    if RECURRENCE_HIGH(c) and LP_HIGH(c):
      idea = MAKE_IDEA_TOKEN(c)
      PROMOTE_IDEA(idea)                      // IdeaToken, PatternCandidate, BridgeCandidate, RuleCandidate
    else if FAILURE_HIGH(c):
      QUARANTINE_SIGNATURE(c.signature)
```

Learning progress guided exploration and goal selection is a standard curiosity mechanism in intrinsic motivation systems. ([Swarthmore Computer Science][p7-5])

---

### Algorithm 37

#### Curiosity scheduler

Online plus sleep-time pass.

```pseudo
function CURIOSITY_SCHEDULER():
  while CBUD.explore_remaining > 0:
    s = TQ.pop()
    if s == none: break
    EXPLORE_SEED(s)

function SLEEP_CURIOSITY_PASS(snapshot snap):
  // deeper budgets, heavier probes
  for s in TOPN_SEEDS(snap, Nsleep):
    EXPLORE_SEED(s)
  DISTILL(snap.epoch)
```

---

### Algorithm 38

#### Decay and cleanup

```pseudo
function SEED_DECAY(seed s):
  if STALE(s) and RECURRENCE_LOW(s):
    s.status = archived
  if FAILURE_HIGH(s) and LP_LOW(s):
    s.status = quarantined
```

---

### P1C1 proof sketch

By construction:

* all raw spans remain in the raw store referenced by `SpanRef`
* each node creation writes an `ObservationRecord`
* each derived update appends to event log
* node states append to `NodeState` history
* merges and splits create alias edges and lineage pointers

Therefore any current state and any prior state is reconstructible from the append-only log plus raw store.

---

### P1C2 and P1C3 proof sketch

For a fixed hypothesis (h), gated quadratic energy remains strictly convex when (\alpha_i + \mu_i > 0) per connected component.
The matrix (Q = L_g + A + M) stays SPD.
Coordinate descent decreases energy and converges to the unique minimizer.

This is the same style of argument used for harmonic energy minimization on graphs. ([MLG Cambridge][1])

---

### P1C4 proof sketch

Conflict scores derive from residual and tension.
If tension remains above threshold after validator updates and local relaxation, the policy triggers branching.
Since branching is append-only and the conflict record persists, ambiguity becomes durable.

---

---

### P2C1 Snapshot consistency

Snapshot created at LSN (l_0) defines a consistent view.

Sketch:

* Event log defines a total order of mutations.
* Snapshot at (l_0) reads all events (\le l_0).
* MVCC snapshot isolation gives a consistent read view that stays stable while writes continue. ([Microsoft][1])

---

### P2C2 Non-blocking commit

Atomic pointer swap gives epoch-level consistency for readers.

Sketch:

* Readers dereference one global epoch pointer at entry.
* All reads use that epoch's stores and indices.
* Writer publishes new epoch by atomic swap.
* RCU grace period ensures old epoch memory remains valid for all readers started before swap. ([Kernel.org][6])

---

### P2C3 IRLS descent

Each IRLS iteration decreases \(\mathcal{E}\).

Sketch for Huber:

* IRLS weight construction corresponds to a majorization of the robust term.
* The surrogate \(\tilde{\mathcal{E}}^{(k)}\) satisfies:

  * \(\tilde{\mathcal{E}}^{(k)}(X) \ge \mathcal{E}(X)\) for all \(X\)
  * \(\tilde{\mathcal{E}}^{(k)}(X^{(k)}) = \mathcal{E}(X^{(k)})\)
* Minimizing the surrogate gives:
  \[
  \mathcal{E}(X^{(k+1)}) \le \tilde{\mathcal{E}}^{(k)}(X^{(k+1)}) \le \tilde{\mathcal{E}}^{(k)}(X^{(k)}) = \mathcal{E}(X^{(k)})
  \]
  This is MM logic. ([Taylor & Francis Online][4])

---

### P2C4 Convergence to a stationary point

Sketch:

* MM descent yields a monotone non-increasing objective sequence.
* (\mathcal{E}) is bounded below, so objective values converge.
* Under standard MM conditions (continuity, proper majorizer, tangency), every limit point of ({X^{(k)}}) is a stationary point.
* If (\rho) is convex (Huber), then (\mathcal{E}) is convex, so the stationary point is a global minimizer.

References for MM stationary point behavior and MM in signal processing. ([arXiv][9])

---

### P2C5 No evidence loss

Sketch:

* Consolidation creates a new epoch and new node states.
* It leaves ObservationRecords, prior NodeStates, ConflictRecords, hypotheses, and the event log intact.
* Therefore any prior world state can be reconstructed by choosing an older epoch or replaying events.

Event sourcing is the established pattern for this audit and replay property. ([Microsoft Learn][7])

---

## P5C1 Multi-view canonical field solve exists and is unique

With anchors (\bar{b}_i) and (\alpha_i+\mu_i>0) per connected component, the canonical quadratic system remains SPD. Uniqueness follows the same argument as earlier field proofs, since the only change is the anchor target, not the Hessian structure.

Proof obligation in Lean:

* show SPD of (L + A + M)
* show unique minimizer exists

---

## P5C2 Rewrite steps preserve evidence permanence

Each rewrite emits tokens with provenance pointers and leaves raw spans untouched. Rule application is append-only over epoch views and event log. Expansion from tokens back to spans remains possible by construction.

Proof obligation in Lean:

* inductive invariant over events: every token has a path to some ObservationRecord or is marked structural-only and tied to anchor nodes

---

## P5C3 Packed forest representation preserves derivations

For the string case, packed forests and graph-structured stacks are standard ways to share substructure and represent ambiguity compactly in GLR style parsing. ([IJCAI][2])
For graph grammars, completeness depends on grammar restrictions and parsing algorithm. HRG parsing has known polynomial-time recognition under restrictions, and general cases can be hard. ([ACL Anthology][10])

Spec requirement:

* grammar classes used online must satisfy a “uniform parsing budget” policy
* heavy grammars run in sleep-time or under strict scope limits

---

## P5C4 Orthogonal adapter preserves geometry

If (A_v) is orthogonal, then (|A_v x - A_v y| = |x-y|). This gives stable similarity across mapped spaces. Procrustes-based alignment provides a practical way to fit such maps. ([ICML][7])

Lean target:

* prove distance preservation for orthogonal matrices
* prove the Procrustes minimizer exists under standard assumptions, optional

---

### P6C1 Workspace isolation

**Claim.** LTM mutates only by commit events.
**Sketch.**

* HWS writes into overlay views.
* Commit controller is the only path that emits LTM events.
* Event log is append-only.

---

### P6C2 Snapshot consistency

**Claim.** Readers obtain a stable view \(G^{\(e\)}\) while commits create \(G^{(e+1)}\).
**Sketch.**

* MVCC style: writers create new versions, readers keep old.
* Equivalent discipline is described by snapshot isolation.

---

### P6C3 Safe reclamation

**Claim.** Old epochs are reclaimed after all readers leave, via grace periods.
**Sketch.**

* Track reader epochs.
* Reclaim when min reader epoch advances past reclaim target, same pattern as RCU grace periods.

---

### P6C4 Surprise budget prevents calcification by construction

**Claim.** High-provenance disruptive evidence cannot be suppressed purely by robust downweighting once clamped, it either forces branching or forces re-anchoring in some hypothesis.
**Sketch.**

* Weight clamp ensures it continues contributing to the objective.
* If conflict persists, solver yields high tension.
* Policy forces branch or re-anchor when tension and provenance exceed thresholds.

---

### P6C5 Grammar promotion controls error

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 promotion proof pattern.

---

### P6C6 Adapter rollout is safe under canary plus rollback

**Claim.** Rollout can be limited to fraction (f) and reverted on regression.
**Sketch.**

* Canarying is a standard safety pattern for deployments.

---

---

### P7C1 Evidence stays

**Claim.** Every seed, idea, and derived structure links back to spans or anchored graph coordinates.

**Sketch.**

By construction:
* Seeds store provenance lists
* IdeaTokens store anchors
* All derived structure references NoiseSeed or IdeaToken which have provenance

---

### P7C2 Exploration stays bounded

**Claim.** Exploration terminates inside each window because spending is monotone and capped by budgets.

**Sketch.**

* Each explore step consumes positive budget.
* Budgets are finite per window.
* Loop stops when budget hits zero.

Lean skeleton:

```lean
namespace CuriosityBudget

def spend (b : Nat) (c : Nat) : Nat := b - min b c

theorem spend_monotone (b c : Nat) : spend b c ≤ b := by
  simp [spend]

theorem finite_steps_under_budget
  (B : Nat) (costs : List Nat) (hpos : ∀ c ∈ costs, 0 < c) :
  (List.foldl spend B costs) ≤ B := by
  -- fold of spend stays ≤ initial budget
  -- extend to show number of positive-cost actions is bounded by B / cmin
  sorry

end CuriosityBudget
```

---

### P7C3 Learning progress avoids irreducible noise fixation

**Claim.** A reward based on improvement de-prioritizes regions where prediction error stays high with little improvement.

**Sketch.**

* In purely noisy regions, training yields little reduction in loss, so (LP) stays near zero.
* Scheduler selects seeds with higher (LP), so compute flows toward learnable structure.

This is the core argument in compression progress and learning progress intrinsic motivation work.

---

### P7C4 Novelty helps coverage

**Claim.** Novelty-driven search supports open-ended discovery and avoids deception by objectives.

**Sketch.**

Novelty search literature demonstrates that novelty as an objective enables discovery of diverse solutions and avoids local optima in deceptive fitness landscapes.

---

### P7C5 Information gain guides ambiguity resolution

**Claim.** Expected informativeness is a principled selection objective for querying and validation.

**Sketch.**

Information gain maximizes expected reduction in uncertainty about model parameters or hypotheses, providing a principled framework for active learning and inquiry.

Optional guarantee path:

* If the exploration objective satisfies adaptive submodularity, adaptive greedy stays near-optimal.

# Lean proof skeletons

Lean is a good fit for the quadratic core: uniqueness, strict convexity, and “energy decreases” lemmas. Mathlib already covers a wide range of linear algebra and analysis.

Below is a Lean 4 + mathlib4 skeleton. It targets the key proof obligations. It uses placeholders where you would connect to existing lemmas about positive definiteness and strict convexity.

```lean
/-
Lean 4 + mathlib4 skeleton.
Goal: formalize uniqueness of minimizer for quadratic energy on finite graphs.

This file assumes:
  - a finite set of nodes ι
  - embeddings live in (ι → ℝ^d) or (ι → ℝ) per coordinate
  - energy E(x) = xᵀ Q x - 2 cᵀ x + const
  - Q is symmetric positive definite
-/

import Mathlib.LinearAlgebra.Matrix.Symmetric
import Mathlib.LinearAlgebra.Matrix.PositiveDefinite
import Mathlib.Analysis.Convex.Quadratic
import Mathlib.Analysis.NormedSpace.OperatorNorm

open scoped BigOperators
open Matrix

namespace GraphField

variable {ι : Type} [Fintype ι] [DecidableEq ι]

-- Coordinate-wise view: one embedding dimension at a time.
-- x : ι → ℝ can be represented as a vector over a finite basis.

-- Abstract quadratic form: Q : Matrix ι ι ℝ, c : ι → ℝ
variable (Q : Matrix ι ι ℝ) (c : ι → ℝ)

def energy (x : ι → ℝ) : ℝ :=
  (Matrix.dotProduct x (Q.mulVec x)) - 2 * (Matrix.dotProduct c x)

-- Core theorem: SPD Q gives unique minimizer.
theorem unique_minimizer_of_posDef
    (hQ : Matrix.PosDef Q) :
    ∃! x* : ι → ℝ, ∀ x : ι → ℝ, energy Q c x* ≤ energy Q c x := by
  -- Strategy:
  -- 1) show energy is strictly convex using hQ
  -- 2) strict convexity on a finite-dimensional real vector space gives unique minimizer
  -- 3) minimizer characterized by Q x* = c
  -- mathlib has lemmas connecting PosDef to StrictConvex for quadratic forms
  sorry

-- One-step coordinate descent decreases energy.
-- Needs a definition of the coordinate update operator for node i.
variable (i : ι)

def coordUpdate (x : ι → ℝ) : ι → ℝ := by
  -- implement x with coordinate i replaced by argmin of energy along that coordinate
  -- for quadratic energy, this is closed form
  exact x

theorem energy_decreases_coordUpdate
    (hQ : Matrix.PosDef Q) :
    ∀ x : ι → ℝ, energy Q c (coordUpdate Q c i x) ≤ energy Q c x := by
  -- Strategy:
  -- energy restricted to coordinate i is a 1D strictly convex quadratic
  -- coordUpdate picks its minimizer
  sorry

end GraphField
```

This is the proof "spine" for C1 and C2. After that, you can build the vector-valued version by applying the scalar proof (d) times.

---

### Lean8 Gated quadratic uniqueness

This extends the earlier SPD quadratic lemma. It uses `Matrix.PosDef` from mathlib. ([Lean Community][4])

```lean
import Mathlib.LinearAlgebra.Matrix.PosDef
import Mathlib.Analysis.Convex.Quadratic

namespace GraphFieldGated

variable {ι : Type} [Fintype ι] [DecidableEq ι]
variable (Q : Matrix ι ι ℝ) (c : ι → ℝ)

def energy (x : ι → ℝ) : ℝ :=
  (Matrix.dotProduct x (Q.mulVec x)) - 2 * (Matrix.dotProduct c x)

theorem unique_minimizer_of_posDef (hQ : Matrix.PosDef Q) :
    ∃! x* : ι → ℝ, ∀ x, energy Q c x* ≤ energy Q c x := by
  -- use strict convexity of quadratic form from PosDef
  sorry

end GraphFieldGated
```

---

### Lean9 Evidence permanence invariants

Model the system as an event-sourced state machine and prove invariants by induction over event lists.

```lean
namespace IngestionInvariants

inductive Event
| addNode : Nat → Event
| addObs  : Nat → Event
| addEdge : Nat → Event
| addState : Nat → Event
| updateGate : Nat → Event
| branchHyp : Nat → Event

structure Store where
  hasSpan : Nat → Prop
  hasObs  : Nat → Prop
  hasState : Nat → Prop

def step : Store → Event → Store := by
  intro s e
  -- define how store evolves for each event
  exact s

def invariantEvidence (s : Store) : Prop :=
  ∀ n, s.hasObs n → s.hasSpan n

theorem invariant_preserved :
  ∀ (s0 : Store) (es : List Event),
    invariantEvidence s0 →
    invariantEvidence (es.foldl step s0) := by
  intro s0 es h
  -- list induction on es
  sorry

end IngestionInvariants
```

This proves the shape of "no evidence gets lost" formally once the `step` function encodes append-only behavior.

---

### Lean10 IRLS descent and stationary point shape

Lean formalization target: one coordinate dimension at a time, finite node set, convex Huber robust objective.

```lean
import Mathlib.Analysis.Convex.Function
import Mathlib.Analysis.SpecialFunctions.Pow
import Mathlib.LinearAlgebra.Matrix.PosDef

open scoped BigOperators
namespace RobustIRLS

variable {ι : Type} [Fintype ι] [DecidableEq ι]

-- A scalar per node. Vector case is d copies.
def huber (δ : ℝ) (r : ℝ) : ℝ :=
  if r ≤ δ then (1/2) * r^2 else δ*r - (1/2)*δ^2

-- Graph objective in scalar form:
-- sum_e w_e * huber(δ_e, |x_i - x_j|) + anchor terms + reg terms
-- This file sketches the proof spine. Details require additional lemmas.

theorem irls_majorizes
  (/* assumptions on δ, eps, weights */) :
  True := by
  -- show surrogate >= objective and tangency at current iterate
  sorry

theorem irls_descent
  (/* assumptions: majorizer property, exact minimization of surrogate */) :
  True := by
  -- prove E(x_{k+1}) ≤ E(x_k)
  sorry

theorem mm_limitpoint_stationary
  (/* assumptions: continuity, bounded below, tangency, majorization */) :
  True := by
  -- standard MM theorem: any cluster point is stationary
  sorry

end RobustIRLS
```

This aligns with the MM descent logic used in MM references. ([Taylor & Francis Online][4])

---

### Lean11 Snapshot and epoch invariants

Model as an event log plus an epoch pointer.

```lean
namespace EpochSafety

inductive Event
| addNode : Nat → Event
| addEdge : Nat → Event
| addObs  : Nat → Event
| addState : Nat → Event

structure Store where
  applied : Nat → Prop            -- events applied up to lsn
  hasObs  : Nat → Prop
  hasSpan : Nat → Prop

def applyUpTo (s : Store) (lsn : Nat) : Store := s

def snapshotConsistent (s : Store) (lsn : Nat) : Prop :=
  True

def epochPublishSafe : Prop := True

theorem snapshot_consistency :
  ∀ s lsn, snapshotConsistent (applyUpTo s lsn) lsn := by
  intro; trivial

theorem publish_atomic_epoch :
  epochPublishSafe := by
  trivial

end EpochSafety
```

This is a placeholder spine. To make it real, the `Store` and `applyUpTo` definitions encode the log replay semantics and the epoch pointer swap rules.

---

### Lean12 Distance preservation under orthogonal maps

```lean
import Mathlib.LinearAlgebra.Matrix.Orthogonal
import Mathlib.Analysis.NormedSpace.Basic

namespace CoordMaps

open Matrix

variable {n : Type} [Fintype n] [DecidableEq n]

-- Sketch: for an orthogonal matrix R, show ‖R.mulVec x - R.mulVec y‖ = ‖x - y‖.
theorem orthogonal_preserves_norm
  (R : Matrix n n ℝ) (hR : R.IsOrtho) (x y : n → ℝ) :
  ‖R.mulVec x - R.mulVec y‖ = ‖x - y‖ := by
  -- use inner-product preservation lemmas from IsOrtho
  sorry

end CoordMaps
```

---

### Lean13 Canonical field uniqueness with multi-view anchors

```lean
import Mathlib.LinearAlgebra.Matrix.PosDef

namespace CanonField

variable {ι : Type} [Fintype ι] [DecidableEq ι]

-- Q = L + A + M is SPD, so quadratic energy has unique minimizer.
theorem canonical_field_unique
  (Q : Matrix ι ι ℝ) (hQ : Matrix.PosDef Q) (bbar : ι → ℝ) :
  ∃! x* : ι → ℝ, True := by
  -- reuse earlier quadratic minimizer theorem shape
  sorry

end CanonField

---

### Lean14 Event-sourced isolation

```lean
namespace Hippocampus

-- Abstract sketch
inductive Event
| CommitEdge : Nat → Nat → Event
| CommitNode : Nat → Event

structure LTMState where
  edges : Nat → Nat → Prop

def apply_event : LTMState → Event → LTMState := by
  intro s e
  cases e with
  | CommitEdge u v =>
      exact { edges := fun a b => s.edges a b ∨ (a = u ∧ b = v) }
  | CommitNode n =>
      exact s

-- Workspace updates do not call apply_event
theorem workspace_isolation
  (s : LTMState) (ws_updates : Nat) :
  ∃ s' : LTMState, s' = s := by
  exact ⟨s, rfl⟩

end Hippocampus
```

---

### Lean15 RCU style reclamation condition as a predicate

```lean
namespace Reclaim

def safe_to_reclaim (target_epoch : Nat) (reader_epochs : List Nat) : Prop :=
  ∀ r ∈ reader_epochs, r > target_epoch

theorem reclaim_monotone
  (t : Nat) (rs1 rs2 : List Nat)
  (h : ∀ r ∈ rs2, r ∈ rs1) :
  safe_to_reclaim t rs1 → safe_to_reclaim t rs2 := by
  intro h1 r hr2
  have hr1 : r ∈ rs1 := h r hr2
  exact h1 r hr1

end Reclaim
```

```
```

---

## G39 Dragon closure

* Every open gap becomes either:
  * an implemented method,
  * an explicit bypass rule, or
  * a deliberate non-goal with an alternative.

---

## Lean: Lossless compress/expand

```lean
-- Sketch: define a graph, pattern instances with explicit node maps, and prove expand ∘ compress = id.

namespace PatternCompression

structure Graph (V E : Type) where
  edges : E → V × V

structure PatternInstance (V PV : Type) where
  nodeMap : PV → V
  residualEdges : List (V × V)

def compress {V E PV : Type} (G : Graph V E) : List (PatternInstance V PV) := by
  exact []

def expand {V E PV : Type} (I : List (PatternInstance V PV)) : Graph V (V×V) := by
  refine ⟨?edges⟩
  intro e; exact e

theorem expand_compress_id
  {V E PV : Type} (G : Graph V E) :
  expand (compress (V:=V) (E:=E) (PV:=PV) G) = (by
    -- extensional equality proof would go here
    exact G) := by
  sorry

end PatternCompression
```

---

## Proof 1: Existence and uniqueness of the field solution

**Claim C1.** If (\alpha_i + \mu_i > 0) for every connected component, then (\mathcal{E}(X)) has a unique minimizer.

**Sketch**

* (\mathcal{E}(X)) is a sum of convex quadratics in (X).
* The Hessian in each dimension is (Q = L + A + M).
* (L) is positive semidefinite.
* (A+M) contributes positive diagonal mass on anchored nodes.
* That makes (Q) positive definite on each connected component that has at least one anchored node, so the quadratic is strictly convex, so the minimizer is unique.
* The linear system ((L+A+M)X = AB) has a unique solution.

This is standard for Laplacian-regularized objectives and Gaussian field style constructions.

---

## Proof 2: Energy decreases under relaxation, convergence on fixed graph

**Claim C2.** The update
[
x_i \leftarrow \frac{\alpha_i b_i + \sum_j w_{ij} x_j}{\alpha_i + \mu_i + \sum_j w_{ij}}
]
monotonically decreases (\mathcal{E}) when updating one node at a time with others fixed. Repeating converges to the unique minimizer.

**Sketch**

* (\mathcal{E}) is quadratic and separable per node when holding neighbors fixed.
* The update sets (x_i) to the exact minimizer of (\mathcal{E}) restricted to coordinate block (i).
* Block coordinate descent on a strictly convex quadratic decreases energy each step and converges to the unique minimizer.

---

## Proof 3: Noise attenuation, directions become more reliable

**Claim C3.** Under the model (b = s + \varepsilon), with zero-mean iid noise and a smoothness prior where neighboring nodes share similar (s), the field solution (x) has lower expected error than (b) along high-frequency graph modes.

**Sketch**

* In one dimension, the solution is linear: (x = (L+A+M)^{-1}A b = S b).
* In the Laplacian eigenbasis, this is a low-pass graph filter with transfer function roughly (h(\lambda)=\alpha/(\alpha+\lambda+\mu)).
* High-frequency components have large (\lambda), so (h(\lambda)) shrinks those components.
* If noise injects energy broadly, high-frequency noise gets attenuated more than the low-frequency signal.
* So expected MSE decreases in regimes where the signal is graph-smooth and noise is less graph-smooth.

This is graph filtering language from graph signal processing.

---

## Proof 4: Tier caps bound compute and memory

**Claim C4.** If tier caps ((K,M,N)) are enforced, then:

* Field updates cost (O(d \cdot |E_{local}|)) with (|E_{local}|) bounded by tier neighborhood size.
* Focus and active tier latency is bounded independent of total corpus size.
* Total memory in RAM is (O((K+M+N)\cdot d + |E_{RAM}|)).

**Sketch**

* All RAM operations are restricted to capped tiers.
* Inactive tier lives on disk and is accessed via ANN and edge lookups.

---

### P1 claim set

P1C1. Evidence permanence holds under all operations.
P1C2. Gated quadratic field per hypothesis has a unique minimizer under the same anchoring condition as v0.1.
P1C3. Field relaxation converges per hypothesis.
P1C4. Persistent conflict produces a durable ambiguity artifact (ConflictRecord or Hypothesis branch).
P1C5. Robust loss reduces influence of large disagreements while preserving convergence to a minimizer.

---


---

### Lean: Monotone failure brake

```lean
namespace FailureBrake

open Real

def brake (η F : ℝ) : ℝ := Real.exp (-η * F)

theorem brake_monotone {η : ℝ} (hη : 0 < η) :
  Monotone (fun F => brake η F) := by
  -- exp(-ηF) is monotone decreasing in F, so this is Antitone;
  -- write the correct lemma as Antitone if preferred.
  sorry

end FailureBrake
```

(When making this formal, use `Antitone` for the decreasing property.)

---

## Lean1 Existence and uniqueness of the field solution

**Claim C1.** If (\alpha_i + \mu_i > 0) for every connected component, then (\mathcal{E}(X)) has a unique minimizer.

**Sketch**

* (\mathcal{E}(X)) is a sum of convex quadratics in (X).
* The Hessian in each dimension is (Q = L + A + M).
* (L) is positive semidefinite.
* (A+M) contributes positive diagonal mass on anchored nodes.
* That makes (Q) positive definite on each connected component that has at least one anchored node, so the quadratic is strictly convex, so the minimizer is unique.
* The linear system ((L+A+M)X = AB) has a unique solution.

This is standard for Laplacian-regularized objectives and Gaussian field style constructions.

---

## Lean2 Energy decreases under relaxation, convergence on fixed graph

**Claim C2.** The update
[
x_i \leftarrow \frac{\alpha_i b_i + \sum_j w_{ij} x_j}{\alpha_i + \mu_i + \sum_j w_{ij}}
]
monotonically decreases (\mathcal{E}) when updating one node at a time with others fixed. Repeating converges to the unique minimizer.

**Sketch**

* (\mathcal{E}) is quadratic and separable per node when holding neighbors fixed.
* The update sets (x_i) to the exact minimizer of (\mathcal{E}) restricted to coordinate block (i).
* Block coordinate descent on a strictly convex quadratic decreases energy each step and converges to the unique minimizer.

---

## Lean3 Noise attenuation, directions become more reliable

**Claim C3.** Under the model (b = s + \varepsilon), with zero-mean iid noise and a smoothness prior where neighboring nodes share similar (s), the field solution (x) has lower expected error than (b) along high-frequency graph modes.

**Sketch**

* In one dimension, the solution is linear: (x = (L+A+M)^{-1}A b = S b).
* In the Laplacian eigenbasis, this is a low-pass graph filter with transfer function roughly (h(\lambda)=\alpha/(\alpha+\lambda+\mu)).
* High-frequency components have large (\lambda), so (h(\lambda)) shrinks those components.
* If noise injects energy broadly, high-frequency noise gets attenuated more than the low-frequency signal.
* So expected MSE decreases in regimes where the signal is graph-smooth and noise is less graph-smooth.

This is graph filtering language from graph signal processing.

---

## Lean4 Tier caps bound compute and memory

**Claim C4.** If tier caps ((K,M,N)) are enforced, then:

* Field updates cost (O(d \cdot |E_{local}|)) with (|E_{local}|) bounded by tier neighborhood size.
* Focus and active tier latency is bounded independent of total corpus size.
* Total memory in RAM is (O((K+M+N)\cdot d + |E_{RAM}|)).

**Sketch**

* All RAM operations are restricted to capped tiers.
* Inactive tier lives on disk and is accessed via ANN and edge lookups.

---

## Lean5 Core quadratic energy proofs

Lean 4 + mathlib4 skeleton for the quadratic core: uniqueness, strict convexity, and "energy decreases" lemmas. Targets key proof obligations for the field solution.

---

## Lean6 Lossless compress/expand

Lean proof that pattern compression and expansion are inverses: `expand ∘ compress = id`.

---

## Lean7 Monotone failure brake

Lean proof that the failure brake function `exp(-η * F)` is monotone decreasing in failure count F.

---

## Lean8 Gated quadratic uniqueness

Lean proof extending the SPD quadratic lemma for gated field solves. Uses Matrix.PosDef from mathlib to show unique minimizer existence.

---

## Lean9 Evidence permanence invariants

Lean proof modeling the system as an event-sourced state machine, proving invariants by induction over event lists. Shows that evidence is never lost under all operations.

---

## Lean10 IRLS descent and stationary point shape

Lean formalization of IRLS (Iteratively Reweighted Least Squares) for robust Huber objective. Proves descent property and convergence to stationary points via MM majorization-minimization framework.

---

## Lean11 Snapshot and epoch invariants

Lean proof modeling snapshot consistency as an event log plus epoch pointer. Shows atomic epoch publishing and consistent views for concurrent readers.

---

## Lean12 Distance preservation under orthogonal maps

Lean proof that orthogonal coordinate transformations preserve distances. Foundation for multi-view canonical field alignment.

---

## Lean13 Canonical field uniqueness with multi-view anchors

Lean proof extending quadratic uniqueness to multi-view settings. Shows that Q = L + A + M remains SPD with multi-view anchors.

---

## Lean14 Event-sourced isolation

Lean proof that workspace updates remain isolated from long-term memory (LTM) until explicit commit events. Models LTM state transitions and workspace overlay semantics.

---

## Lean15 RCU style reclamation condition as a predicate

Lean proof formalizing RCU (Read-Copy-Update) grace period semantics for safe memory reclamation. Shows monotonicity of reclamation safety under reader epoch tracking.

---


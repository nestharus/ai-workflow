# Lean proof skeletons

Lean is a good fit for the quadratic core: uniqueness, strict convexity, and “energy decreases” lemmas. Mathlib already covers a wide range of linear algebra and analysis.

Below is a Lean 4 (+[Lean5]) + mathlib4 skeleton. It targets the key proof obligations. It uses placeholders where you would connect to existing lemmas about positive definiteness and strict convexity.

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

This is the proof "spine" for C1 (+[C1]) and C2. After that, you can build the vector-valued version by applying the scalar proof (d) times.

---

### Lean8 Gated quadratic uniqueness [(=Lean8)]

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

### Lean9 Evidence permanence invariants [(=Lean9)]

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

### Lean10 IRLS descent and stationary point shape [(=Lean10)]

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

This aligns with the MM descent logic used in MM references.

---

### Lean11 Snapshot and epoch invariants [(=Lean11)]

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

### Lean12 Distance preservation under orthogonal maps [(=Lean12)]

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

### Lean13 Canonical field uniqueness with multi-view anchors [(=Lean13)]

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

### Lean14 Event-sourced isolation [(=Lean14)]

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

### Lean15 RCU style reclamation condition as a predicate [(=Lean15)]

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

## G39 Dragon closure [(=G39)]

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


---

### Lean7 Monotone failure brake [(=Lean7)]

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

## Lean1 Existence and uniqueness of the field solution [(=Lean1)]

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

## Lean2 Energy decreases under relaxation, convergence on fixed graph [(=Lean2)]

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

## Lean3 Noise attenuation, directions become more reliable [(=Lean3)]

**Claim C3.** Under the model (b = s + \varepsilon), with zero-mean iid noise and a smoothness prior where neighboring nodes share similar (s), the field solution (x) has lower expected error than (b) along high-frequency graph modes.

**Sketch**

* In one dimension, the solution is linear: (x = (L+A+M)^{-1}A b = S b).
* In the Laplacian eigenbasis, this is a low-pass graph filter with transfer function roughly (h(\lambda)=\alpha/(\alpha+\lambda+\mu)).
* High-frequency components have large (\lambda), so (h(\lambda)) shrinks those components.
* If noise injects energy broadly, high-frequency noise gets attenuated more than the low-frequency signal.
* So expected MSE decreases in regimes where the signal is graph-smooth and noise is less graph-smooth.

This is graph filtering language from graph signal processing.

---

## Lean4 Tier caps bound compute and memory [(=Lean4)]

**Claim C4.** If tier caps ((K,M,N)) are enforced, then:

* Field updates cost (O(d \cdot |E_{local}|)) with (|E_{local}|) bounded by tier neighborhood size.
* Focus and active tier latency is bounded independent of total corpus size.
* Total memory in RAM is (O((K+M+N)\cdot d + |E_{RAM}|)).

**Sketch**

* All RAM operations are restricted to capped tiers.
* Inactive tier lives on disk and is accessed via ANN and edge lookups.

## Lean5 Core quadratic energy proofs [(=Lean5)]

Lean is a good fit for the quadratic core: uniqueness, strict convexity, and "energy decreases" lemmas. Mathlib already covers a wide range of linear algebra and analysis.

Below is a Lean + mathlib4 skeleton. It targets the key proof obligations. It uses placeholders where you would connect to existing lemmas about positive definiteness and strict convexity.

```lean
/-
Lean + mathlib4 skeleton.
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

Two tracks: quadratic uniqueness and state machine invariants.

## Lean6 Lossless compress/expand [(=Lean6)]

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

## P1C6: Evidence permanence proof sketch [(=P1C6)] (+[P1C1])

## P1C7: Unique field minimizer and convergence proof sketch [(=P1C7)] (+[P1C2]) (+[P1C3])

## P1C8: Persistent conflict durability proof sketch [(=P1C8)] (+[P1C4])

# Feedback: requirements.md and design map structure.md

## Target outcomes (as stated)

1. `requirements.md` is the authoritative specification for **all algorithms** used by the implementation planner (including parallel top-down + bottom-up exploration and scoring).
2. `design map structure.md` defines **format/contracts only**. It should contain enough schema/semantics that a concrete Design Map instance can be used to deterministically derive an artifact.
3. Bottom-up exploration runs **in parallel** with top-down decomposition; bottom-up findings are used to **score and revise** top-down choices.
4. If something requires a choice:
   - if it is deterministically derivable from existing requirements + explored facts → record as an ADR decision;
   - if it is not derivable → surface the **missing requirement(s)** needed to derive it (not the choice itself).
5. Test units are paired with exploratory/map units; drift can be detected via coverage gaps (esp. branch coverage) and must be surfaced as new requirements (not silently patched into the artifact).

---

## 1) Feedback for `design map structure.md`

### What’s working

- Clear separation intent: components / contracts / internal artifacts with PRD traceability and ADR-only decision links.
- Provides minimal templates and an ID vocabulary that can be machine-checked.

### Issues (relative to “format only”)

1. **Algorithm leakage via schema examples and ID types**
   - The file defines `ALG-COM-*` as Design Map IDs and includes template sections named “Derived algorithms” and “Gap-filling algorithms.”
   - Even though these are placeholders, they push algorithm taxonomy into the Design Map format doc.

2. **Deterministic derivation contract is implicit**
   - The file says a Design Map defines components/contracts/boundaries, but it does not state **what minimum fields** must exist so an artifact can be derived deterministically.

3. **Pattern anchoring is underspecified**
   - You stated the Design Map is pattern-tied (not language/library-tied), yet the schema does not explicitly represent “pattern selection” per node (component/contract/artifact).

4. **No explicit representation for “requirement gaps surfaced during exploration”**
   - You described a critical behavior: when exploration hits underspecification, the system surfaces missing requirements, not decisions.
   - The Design Map schema currently has no canonical place to record “requires more requirements” for a node/boundary.

### Recommended changes

#### A) Remove algorithm node types from the Design Map format

- Remove `ALG-COM-*` from the “Design Map IDs” vocabulary.
- Remove the “Derived algorithms” / “Gap-filling algorithms” subsections from the templates.

Instead:
- Allow nodes to reference PRD requirements/algorithms by ID in `Implements:` / `Cross-references:` only.
- Add a field that captures **boundary obligations** without describing algorithms in this schema doc.

#### B) Rename invariant INV-DM-03 to avoid algorithm content

- Replace “Boundary gap algorithms” with “Boundary obligations” and make it schema-level:
  - boundaries **MUST list obligations** (by ID), but obligation semantics live in `requirements.md`.

#### C) Make “deterministic derivation” explicit

Add a short section that states what must be present in a Design Map instance for deterministic derivation, e.g.:

- Each `COM-*` must specify:
  - chosen **pattern** (name/ID) and its required contract types;
  - its inputs/outputs (typed to `ART-*` or `IAR-*`);
  - its boundary list (`CON-*`) with obligations.
- Each `CON-*` must specify:
  - protocol/data-shape identifiers (schema IDs, message types);
  - required invariants/constraint sets;
  - obligations IDs.
- Each `IAR-*` must specify:
  - kind + access contracts + schema IDs.

#### D) Add a schema-level “Pattern:” field

To match “pattern-tied” intent:
- Add `Pattern: (PAT-__ | {pattern-name})` to `COM-*`, `CON-*`, and `IAR-*` templates.

(If you don’t want a new ID namespace yet, allow `Pattern:` as a string with a later migration path.)

#### E) Add a canonical way to represent “missing requirement(s)” discovered

Add an optional field on each node:

- `Needs: (REQ-__/Q-__/MISSING-__)` — IDs that represent information the PRD must provide before this node can be deterministically derived.

(If you already have an “Open Questions” format elsewhere, use that ID type instead of introducing a new one.)

### Concrete template patch (illustrative)

Below is an illustrative re-shape of the templates to keep them “format only” while still encoding deterministic derivation requirements.

```diff
 ## Component: COM-__
 
+Pattern: {pattern-name-or-id}
 Implements: (ALG-__, RULE-__, GOAL-__)
 Consumes: (ART-__, IAR-__)
 Produces: (ART-__, IAR-__)
 Uses: (RES-__)
 Satisfies: (SET-__)
 Decisions: (decided-by: ADR-###)
+Needs: (Q-__/REQ-__)  # optional; missing requirements surfaced during exploration
 
 ### Contracts (boundaries)
-- CON-__: for (ART-__/IAR-__) (requires: INV-__; satisfies: SET-__; decided-by: ADR-###)
+ - CON-__: for (ART-__/IAR-__) (requires: INV-__; satisfies: SET-__; obligations: OBL-__, OBL-__; decided-by: ADR-###)
-
-### Derived algorithms (from chopped PRD logic)
-- ALG-COM-__-__: {read/process/write slice} (derived-from: ALG-__; satisfies: SET-__)
-
-### Gap-filling algorithms (exist only because boundary exists)
-- ALG-COM-__-__: retry/backoff (derived-from: CON-__; satisfies: INV-__/SET-__)
-- ALG-COM-__-__: serialization/framing (derived-from: CON-__; satisfies: INV-__/SET-__)
-- ALG-COM-__-__: authn/authz (derived-from: CON-__; satisfies: INV-__/SET-__)
-- ALG-COM-__-__: dedup/idempotency (derived-from: CON-__; satisfies: INV-__/SET-__)
```

(Where `OBL-*` semantics are defined in `requirements.md` as the authoritative algorithm spec.)

---

## 2) Feedback for `requirements.md`

### What’s working

- Strong coverage of execution environment constraints (worktree scoping, parallel I/O isolation).
- A clear model for decomposition/refactor behavior (patch vs regenerate, orphan handling, copy-on-write for shared nodes).
- A robust exploration philosophy (multi-branch, cautious pruning, loop control, evidence-based scoring).
- A correct debugging posture (symptom → minimal patch → derive new requirement → plan proper fix).
- Explicit test tier expectations and “tests as behavioral documentation.”

### Gaps relative to the target outcomes

1. **No PRD-style IDs → cannot satisfy Design Map traceability invariant**
   - `design map structure.md` expects `GOAL-*`, `INV-*`, `ALG-*`, `SET-*`, `ART-*`, etc.
   - `requirements.md` currently has no such IDs, so a Design Map cannot “Implements: (GOAL-__/ALG-__)” in a machine-checkable way.

2. **Planner outputs are not explicitly contracted**
   - The doc describes planning documentation in general, but it does not explicitly define the required outputs:
     - Design Map (instance) conforming to `design map structure.md`.
     - ADR records conforming to `ADR-000-template.md`.
     - Execution plan conforming to `plan.md`.

3. **Parallel top-down + bottom-up algorithm is not specified as a first-class algorithm**
   - The doc has:
     - top-down decomposition shape (`skeleton → components → integration mapping`), and
     - search/scoring mechanics (MCTS-like scheduling, multi-objective scoring).
   - But it does not explicitly define the *two-pass parallelism* and, critically, **how bottom-up findings update top-down scoring**.

4. **Decision gating rules (ADR vs missing requirements) are not formalized**
   - You need explicit rules for:
     - when a decision is allowed,
     - when an ADR must be emitted,
     - when the system must stop and request new requirements (or emit requirement-gaps) instead.

5. **Coverage-driven drift detection is not defined**
   - The doc expects exhaustive coverage, but does not define how coverage gaps become:
     - a drift signal,
     - a requirement update,
     - and a re-plan/refactor trigger (rather than “just patch code”).

### Recommended changes

#### A) Introduce (or migrate to) PRD-style IDs

Minimal migration path:

1. Add a short “ID Index” section near the top:
   - Define `GOAL-*`, `INV-*`, `ALG-*`, `SET-*`, `ART-*`, `MET-*`, `TEST-*`, and any domain prefixes.
2. Assign IDs to the most load-bearing requirements first:
   - workspace scoping invariants;
   - parallel I/O isolation rules;
   - decomposition/refactor rules;
   - exploration/scoring rules;
   - debugging workflow rules;
   - test tier/coverage rules.
3. Incrementally convert the rest.

This unlocks deterministic traceability into Design Maps and Plans.

#### B) Add an explicit “Artifacts produced” section

Define the planner’s outputs and contract ownership:

- `ART-PLN-01` — Design Map (instance)
  - Must conform to `design map structure.md`.
  - Must be sufficient (with PRD IDs) to deterministically derive implementation artifacts.
- `ART-PLN-02` — ADR set
  - Must conform to `ADR-000-template.md`.
  - Must be emitted for any non-trivial choice actually made.
- `ART-PLN-03` — Execution plan
  - Must conform to `plan.md`.

#### C) Add a first-class algorithm section: “Parallel top-down + bottom-up planning with scoring”

This should be written as *the* authoritative algorithm spec for:

1. Top-down pass: propose skeleton → components → contracts.
2. Bottom-up pass: explore leaf-level implications (ecosystem quirks, boundary obligations, testability constraints, drift risks).
3. Reconciliation: bottom-up emits **evidence items** that update a **scorecard** for each top-down branch/option.
4. Scheduling: your existing MCTS-like frontier selection chooses which node/branch to expand next using the updated scorecard.

Key requirement: the scorecard must be traceable to evidence.

#### D) Formalize “decision vs requirement gap” gating

Add rules like:

- If a choice is fully determined by existing `INV-*` / `SET-*` / `RULE-*` → select it and emit ADR with references.
- If a choice depends on an unspecified tradeoff/weight → do not decide; emit `REQ-GAP-*` describing what input is required to derive the decision.

#### E) Define drift detection as an algorithm, tied to coverage + debug flow

- Branch coverage gaps (or new uncovered branches created during implementation) are treated as “unplanned behavior surface.”
- The system must:
  1. identify whether the uncovered branch corresponds to ecosystem-required adaptation or instruction-following drift;
  2. surface the minimal new requirement(s) that explain/justify the branch;
  3. update Design Map/PRD and re-plan;
  4. only then implement.

This should explicitly connect to the existing “derive new requirement from symptom” workflow.

### Suggested drop-in section outline (example)

Below is a compact outline you can paste into `requirements.md` as a new section (or use to refactor existing sections). It shows what “algorithms in totality” could look like.

```markdown
## X) Parallel planning algorithm (top-down + bottom-up) with scoring

### X.1 State primitives
- DESIGN_NODE: a candidate unit/component/contract in the design DAG
- EVIDENCE_ITEM: a bottom-up finding with provenance + impact
- SCORECARD: multi-objective vector + hard-constraint flags

### X.2 Top-down pass (structure-first)
- Start from GOAL/INV/ART/ALG set
- Propose skeleton → component set → contract set
- Emit candidate branches when multiple patterns can satisfy the same interface

### X.3 Bottom-up pass (constraint discovery)
- For each frontier DESIGN_NODE:
  - enumerate boundary obligations implied by the pattern and ecosystem
  - enumerate test units needed for 100% branch coverage of the implied behavior
  - surface unknown-unknowns / library quirks / special handling
  - produce EVIDENCE_ITEMs linked to the DESIGN_NODE (and parents as needed)

### X.4 Scoring and reconciliation
- Maintain a SCORECARD per branch:
  - hard constraints: violated INV/SET? (boolean)
  - complexity: components/contracts/internal artifacts count
  - testability: projected effort to reach tier thresholds
  - drift risk: number/severity of uncovered obligation areas
  - unknowns: count/severity of EVIDENCE_ITEMs marked UNKNOWN
- Update the scorecard whenever new EVIDENCE_ITEMs arrive.

### X.5 Decision gating
- If a decision is required:
  - If deterministically implied by constraints → decide + emit ADR
  - Else → emit REQ-GAP describing required missing inputs; block finalize

### X.6 Scheduling
- Use MCTS-like frontier selection:
  - expand branches with highest expected information gain / uncertainty
  - avoid expanding branches that violate hard constraints
  - revisit top-level nodes when bottom-up evidence changes rankings
```

---

## Priority checklist

### Must fix for coherence

- [ ] Align ID vocabulary across `requirements.md` and the Design Map schema (or relax the schema to match the requirements doc).
- [ ] Remove algorithm content from `design map structure.md` (replace with obligation references).
- [ ] Add explicit “parallel top-down + bottom-up + scoring” algorithm spec to `requirements.md`.

### Should fix for determinism

- [ ] Add explicit deterministic-derivation requirements to the Design Map schema (minimum fields + pattern anchoring).
- [ ] Add explicit decision-gating rules (ADR vs requirement gaps).
- [ ] Add explicit drift-detection algorithm tied to coverage thresholds and the debug workflow.

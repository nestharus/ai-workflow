## Corrected single-layer phase model

Single-layer means **one codebase** and **one set of artifacts**, but it does **not** mean “invent new phases.” The phase scales remain the existing three:

1. **Libraries phase** (L1-equivalent)
2. **Architecture phase** (L2-equivalent)
3. **Quality phase** (L3-equivalent)

What changes is **representation and routing**, not the phase scales:

* **No cross-layer promotion of different representations**
* **No PIN bridge**
* **No demotion to earlier phases**
* **Shapes + matching + verifiers + work items** remain the routing/evidence backbone
* **Call graph becomes the algorithm representation only after deterministic classification against shapes**, not as raw edge output

---

# 1) RQ1 — Mapping to existing L1/L2/L3 infrastructure, minimal change for one codebase

## 1.1 What maps directly (keep)

The existing architecture already has the right abstraction boundary for three phases:

* **`PromotionLoop`** (10-step per-slice state machine) stays.
  It already embeds “build” as **IMPLEMENT** inside each loop. (Design overview shows this explicitly.)
* **Layer-aware step dispatch** becomes **phase-aware dispatch**, but phases == layers:

  * Libraries phase uses the L1 behaviors (gap scan, plan style, implementor, gates)
  * Architecture phase uses the L2 behaviors (wiring planning, architecture review/gates)
  * Quality phase uses the L3 behaviors (quality reviewers, refactor planning, diff-impact)

So the minimal structural change is not a new pipeline—it’s changing **where “layer separation” lives**.

## 1.2 What must change to become “single codebase”

Today, `PddLifecycle` is a **multi-representation pipeline** because it:

* runs L1 in one representation/worktree set
* *propagates* output to L2’s different worktree representation
* relies on **pins** for L2 assembly and **downward flow** for demotion

Single codebase requires removing the representation split:

### Minimal lifecycle change

* Keep the same top-level progression: **Phase 0 → Libraries → Architecture → Quality**
* Remove (or no-op) the “propagate clean → next dirty” mechanism between L1→L2 and L2→L3.
* Replace inter-layer “transition refinement + possible demotion” with:

  * **entry refinement** for the next phase (draft skeleton creation)
  * phase-local remediation (no going back)

This is a **PddLifecycle simplification**, not a PromotionLoop rewrite.

### Minimal promotion-loop change

* Keep the 10-step loop.
* Replace **demotion-to-earlier-layer** with:

  * **in-phase remediation** when allowed
  * **block** when remediation would violate a prior phase’s frozen skeleton contract
* Remove dependencies on **pins** and **downward flow**:

  * L2 review dimensions that exist purely for pins (PIN_COVERAGE, EDGE_REALIZATION, etc.) are replaced by **shape matching + contract verifiers** (already in the routing model you want to keep).

## 1.3 Infrastructure shared across all three phases (keep)

* Planner API (`planner/api.py`, `planner/router.py`) and capability routing
* Coordination (signals/work items/wake/wait graph)
* Evidence bundles and iteration artifacts
* Source analysis cache + call-graph extraction (as analysis inputs)
* Constraints store / under-spec manager

---

# 2) RQ2 — Skeleton propose/work/refine cycle inside each phase

The corrected model is: **each phase is a full cycle**:

1. **Propose skeleton (draft)**
2. **Do work** (PromotionLoop over slices; edits happen here)
3. **Refine skeleton (non-draft)** and record the commit boundary

Skeletons are **external structural artifacts** (“where code can exist at this scale”), not code markers.

## 2.1 Phase 0 outputs (feeds Libraries) — draft foundation

Phase 0 is not “just decomposition.” It produces the draft foundation artifacts that Libraries will solidify:

* **Draft shapes** (per library/package): ownership, declared dependencies, initial contracts to verify later
* **Draft algorithms**: algorithm inventory per library (names + entrypoints + responsibilities), not “edge extraction”
* **Draft stores**: store inventory + ownership + access boundaries (enables monogamy-style constraints without pins)

These are saved as **run-scoped artifacts** and treated as authoritative inputs to Libraries’ skeleton proposal.

## 2.2 Libraries phase skeleton (L1-scale)

**What “propose skeleton” means here**

* Confirm the set of libraries from Phase 0
* Establish library ownership boundaries (paths → library shape)
* Establish the **library API surface** and internal module layout sufficient to implement algorithms and stores

**Draft state**

* Libraries skeleton is editable: files/modules can be created; algorithm surfaces can be adjusted.

**Work cycle**

* Run `PromotionLoop` per library slice using L1 behaviors:

  * GAP_EXPLORATION: algorithmic gaps
  * PLAN/IMPLEMENT: create/edit code and tests
  * PROMOTE/VERIFY: run deterministic verifiers + (optional) LLM signals as routing aids

**Refine skeleton to non-draft**

* Freeze these *structural invariants*:

  * library roster (which libraries exist)
  * library ownership (path-to-library mapping)
  * store ownership boundaries (which library “owns” which store)
  * declared library shapes become non-draft
* Record commit/tag: `pdd/<run_id>/libraries-skeleton-final`

**What is not frozen**

* Function bodies and internal implementation details are still editable later.
* This is why Architecture can refine algorithms without “demotion.”

## 2.3 Architecture phase skeleton (L2-scale)

**What “propose skeleton” means here**

* Establish component decomposition (component roster, owned paths/files, external boundaries)
* Establish cross-component **contracts** (EVENT_FLOW, DI_BINDING, MIDDLEWARE_ORDERING, etc.)
* Attach deterministic **verifiers** to each contract

**Draft state**

* Component shapes and contracts are editable during Architecture.

**Work cycle**

* Run `PromotionLoop` per component slice using L2 behaviors:

  * Plan/Implement wiring and component boundaries
  * Update/extend contracts + tests
  * Fix algorithm issues discovered while wiring **in place** (see RQ3)

**Refine skeleton to non-draft**

* Freeze:

  * component roster and ownership
  * contract inventory (the set of required cross-component relationships)
  * contract verifier suite (tests/checks that define evidence)
* Record commit/tag: `pdd/<run_id>/architecture-skeleton-final`

## 2.4 Quality phase skeleton (L3-scale)

Quality is “internal organization,” so the skeleton is about refactor scope and invariants.

**What “propose skeleton” means here**

* Identify refactor scope per file/package (within component boundaries)
* Establish “behavior-preserving” expectations:

  * tests that must remain green
  * contract verifiers that must remain green
  * optional deterministic style/lint/format checks

**Work cycle**

* Run `PromotionLoop` per file slice using L3 behaviors:

  * refactor intentions + implementation
  * quality reviewers produce findings that become refactor work items
  * diff-impact classification is used as a guardrail (not sole authority)

**Refine skeleton to non-draft**

* Freeze:

  * internal organization decisions as “complete” for the run (receipts/report artifacts)
* Record commit/tag: `pdd/<run_id>/quality-final`

---

# 3) RQ3 — How Architecture refines algorithms without going back to Libraries

## 3.1 The enabling mechanism

Architecture can refine algorithms because:

* there is **one codebase**, not a promoted representation boundary
* the **classified call graph** provides a reliable internal map of “what algorithm is connected to what” (details in RQ7)

## 3.2 What Architecture is allowed to change

Within Architecture phase, edits can include:

* wiring changes (components, contracts, adapters)
* algorithm changes inside existing library boundaries when needed for:

  * interface alignment
  * error propagation correctness
  * missing invariant enforcement discovered during contract verification

This is not demotion. It is **phase-local remediation**.

## 3.3 What Architecture is *not* allowed to change (because Libraries skeleton is non-draft)

Architecture must not:

* create new libraries
* change library ownership boundaries (path→library)
* reassign store ownership across libraries

If Architecture encounters a need that would violate these invariants, the correct action is:

* **block** with explicit evidence (“requires library boundary change after Libraries skeleton final”)
  Not “demote.”

## 3.4 Can Architecture add new algorithms?

Yes, but only in the sense of:

* adding new internal flows/functions **within an existing library shape**
* attaching them to existing or new component contracts

It cannot introduce a new library-scale concern. That’s a Phase 0/Libraries completion failure → block/restart decision, not an in-run backtrack.

---

# 4) RQ4 — How Quality avoids changing behavior

Quality is constrained by **evidence**, not by intent.

## 4.1 Allowed transformations

Quality may:

* extract helpers
* rename identifiers
* reorganize within files/modules
* split/merge internal modules **within the same component ownership boundary**
* improve error handling structure *if behavior preserved*

## 4.2 Preventing behavior change (hard enforcement)

Behavior preservation is enforced by deterministic verifiers:

* full test suite (or at least contract + critical tests)
* all shape contract verifiers must remain green

If a change breaks tests:

* Quality phase must either fix the refactor or abandon it.
* It does **not** route backward; it blocks if it cannot complete within bounds.

## 4.3 Optional secondary guardrails (non-authoritative)

* Diff-impact reviewer (already in L3 pack) flags risk.
* Classified call graph stability can be a *signal*:

  * if cross-shape edges or contract-realizing edges change unexpectedly, raise a quality finding
  * but do not treat this as convergence authority (call graph still originates from LLM inference)

---

# 5) RQ5 — What Phase 0 produces and how it feeds Libraries

Phase 0 becomes the **foundation generator**. It produces:

## 5.1 Shapes (draft)

* One draft shape per proposed library
* Ownership rules (paths)
* Declared dependencies/consumers at a coarse level
* Initial contract inventory (especially cross-library communication needs)

## 5.2 Algorithms (draft inventory, not extracted graphs)

Algorithms produced by Phase 0 are **descriptions** and **entrypoint inventories**, such as:

* algorithm name
* owning library
* entrypoint(s) or “surface API” functions that represent the algorithm start
* required invariants and required communication contracts

These are fed into Libraries phase planning as “what to implement.”

## 5.3 Stores (draft inventory + boundaries)

Stores produced by Phase 0 are **structural decisions**, such as:

* store IDs and owning library
* allowed access paths (who can read/write)
* required adapters (repository modules) to enforce boundaries

Libraries phase then implements these store interfaces and their tests.

---

# 6) RQ6 — Compliance gates mapped to three phases

Gates remain organized by **aspect**, but they run within the three phases.

## 6.1 Libraries phase (L1) — converge on algorithm completeness + library structure

**Hard (deterministic)**

* library-level verifiers (tests/checks referenced by library shapes)
* required store boundary checks if deterministically enforceable (e.g., via import boundary rules)
* baseline suite (slice + periodic full)

**Soft (routing signals)**

* LLM-based “remaining gaps” scans
* call-graph connectivity checks (useful, but not authoritative)

## 6.2 Architecture phase (L2) — converge on component topology + contract satisfaction

**Hard (deterministic)**

* shape matching: declared vs observed dependency direction (import graph)
* contract verifiers for EVENT_FLOW / DI_BINDING / MIDDLEWARE_ORDERING
* integration tests that prove cross-component paths satisfy constraints

**Soft**

* L2 reviewers remain valuable, but findings must translate into:

  * a deterministic verifier addition, or
  * a concrete wiring work item with observable resolution

## 6.3 Quality phase (L3) — converge on refactor completion while preserving behavior

**Hard**

* all tests + all contract verifiers remain green
* deterministic style checks if configured

**Soft**

* quality reviewers (clarity/consistency/maintainability) produce refactor work items
* diff-impact classifier flags risk; failing it blocks only if policy says so

---

# 7) RQ7 — Call graph classification with shapes

This is the missing piece: the call graph is not just a local hint. It becomes the algorithm representation **after classification**, and that classification is driven by **deterministic matching against shapes**.

## 7.1 Inputs

1. **Shapes (authoritative structural spec)**

   * ownership: paths → shape_id
   * surface API list
   * contracts list + verifier references

2. **Observed structure (deterministic)**

   * import dependency scan (package/file → imports)
   * file tree + path canonicalization

3. **Raw call graph (advisory extraction)**

   * per-file CALL edges + evidence

## 7.2 Classification: deterministic matching over shapes

Classification is a deterministic transformation that takes:

* shape ownership + surface APIs + contracts
* observed import boundaries
* raw call graph edges

…and produces:

### A) Algorithm membership (subgraph → algorithm)

Within a shape:

* Treat shape’s **surface API entrypoints** as algorithm roots.
* Take the raw call graph edges in files owned by the shape.
* Compute reachable subgraphs from each root (within owned scope).
* Label nodes/edges with:

  * `shape_id`
  * `algorithm_id` (derived deterministically from `{shape_id, root entrypoint}` or allocated by a stable allocator)

This yields: “this subgraph is algorithm X” without semantic LLM labeling.

### B) Communication path classification (edges → contract)

Structural edges are not “guessed.” They are classified by match rules:

* If a relationship corresponds to a declared contract (EVENT_FLOW, DI_BINDING, MIDDLEWARE_ORDERING), then the relevant observed edges/config entries are labeled with that `contract_id`.
* Cross-shape edges (when present in call graph) are structural by default and must be justified by either:

  * a declared dependency allowance, or
  * a declared contract that explains the relationship

### C) Logical vs structural edges

After classification:

* **Logical** = within-shape edges that are in an algorithm subgraph and not part of a contract realization
* **Structural** = edges that either:

  * implement a contract, or
  * cross shape/component boundaries

This is deterministic and shape-driven.

## 7.3 What “authoritative” means here (important boundary)

* The **classified call graph** is authoritative as the system’s internal representation of “what algorithm structure we are operating on” for planning and routing within Architecture and Quality.
* It is **not** authoritative evidence of correctness or convergence.

  * Correctness/convergence remain tied to deterministic verifiers (tests/checks).
* If classification yields ambiguity (multiple candidate roots, unclear ownership), the system blocks per existing under-spec/coordination rules.

This satisfies the authority boundary while still giving the call graph the deeper role required for single-layer operation.

## 7.4 Constraints flow from algorithms to communication paths

The original requirement (“algorithms denote communication paths abstractly; constraints apply based on the logical algorithm”) is implemented as:

1. **Algorithm description in shapes** declares a required communication contract (abstractly).
2. The contract block includes constraints (ordering, conditionality, exactly-once, etc.).
3. Those constraints are implemented as **deterministic verifiers** (tests/checks).
4. Classified call graph links:

   * where the algorithm lives (subgraph)
   * where the contract is realized (edge/config locus)
   * so routing is precise when a verifier fails.

---

# 8) RQ8 — Convergence per phase

Each phase converges independently, forward-only.

## 8.1 Libraries convergence

Libraries phase is complete when:

* library skeleton is promoted to non-draft (commit recorded)
* all library shape verifiers pass
* dependency drift (declared vs observed) resolved per policy
* no open library-scoped work items remain
* within explicit bounds: `max_library_iterations_per_slice` and `max_total_library_slices`

## 8.2 Architecture convergence

Architecture phase is complete when:

* architecture skeleton is promoted to non-draft (commit recorded)
* all component contract verifiers pass
* import boundary + dependency direction rules satisfied
* no open architecture-scoped work items remain
* within explicit bounds: `max_component_iterations_per_slice`, plus a phase-wide cap

## 8.3 Quality convergence

Quality phase is complete when:

* all tests + all contract verifiers still pass
* refactor work items are closed
* diff-impact policy satisfied (if enforced)
* within explicit bounds: `max_file_iterations_per_slice`, plus a phase-wide cap

## 8.4 Global termination

The run terminates after Quality convergence, with optional QA evaluation/reporting.

---

# 9) Updated demotion model (no backtracking)

Demotion-as-layer-transfer is removed.

What remains is **classification of required change type**, but it is used only for:

* routing within the current phase’s work queues
* detecting illegal changes for the phase (e.g., behavior change in Quality)
* deciding block vs proceed

DownwardFlowEngine and pin tracing disappear because pins disappear.

---

# 10) Updated simplification inventory under the corrected phase model

## Deleted / collapsed

* Cross-layer propagation machinery (clean→dirty between layers)
* Layer-transition demotion loops
* Downward pin tracing (DownwardFlowEngine)
* PIN registry / snapshot / drift / projection types and all pin-only gates
* “Pipeline pass” multi-run machinery driven by demotion (max_pipeline_passes becomes structurally unnecessary)

## Kept

* PromotionLoop state machine
* Three sets of planner behaviors (L1/L2/L3) — now explicitly the three phases
* Review packs (L2 + L3), but their pin-dependent dimensions are replaced by shape-based checks
* Coordination infrastructure and evidence bundles

## Introduced (still minimal)

* Shape matcher (declared vs observed dependencies)
* Contract verifier runner (tests/checks referenced by shapes)
* Call graph classifier (deterministic matching that labels subgraphs/contracts)

These replace pins with **matching + classification**, not with code markers and not with a new pin-like registry.

---

## Net correction summary

* Phases are corrected to **Libraries → Architecture → Quality**, forward-only.
* “Build” is restored to its correct place: **inside IMPLEMENT in each phase**, not a separate phase.
* Each phase edits code in its own loop and promotes its own skeleton from draft→non-draft.
* No demotion to earlier phases; Architecture may refine algorithms in place within frozen library boundaries.
* Call graph is **hint before classification**, and becomes the **algorithm representation after deterministic classification against shapes**, while verifiers remain the only convergence authority.

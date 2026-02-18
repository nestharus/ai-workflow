## What the current 3-layer system gets right (keep these invariants)

* **Sequential stabilization works**: L1 stabilizes correctness/completeness before L2 invests in architecture, and L3 invests in refactors last. This matches the “source authority” + “error amplification” constraints.
* **L1 correctness gates are already strong**: comment/stub closure + tests + call-graph connectivity + store monogamy are crisp, cheap-to-fix early gates.
* **Multi-agent review packs work**: L2 reviewers surface topology/boundary issues; L3 reviewers surface maintainability/correctness issues with good routing metadata.
* **Demotion routing works**: it’s a correct *control plane* for “what kind of fix is needed” even if the *data plane* (pins + layer worktrees) is expensive.
* **Stagnation detection works**: sliding-window minimum is a good generic convergence guard.

The single-layer design must preserve these outcomes, even if it changes mechanisms.

---

## 1) Feasibility assessment: can you collapse to one layer without losing correctness?

### Bottom line

**Yes, it’s feasible to collapse to a single authoritative codebase** *if* you replace “layers” with **phase-scoped authority + progressive gating** and replace “PIN projections” with a **stable, evidence-carrying, cross-file annotated adjacency graph**.

However, “call graph alone” (CALL edges only) is **not sufficient** to replace all pin use-cases. What *is* sufficient is:

* A **cross-file adjacency graph** containing at least: `CALL`, `EVENT_{EMIT|HANDLE}`, `STORE_TOUCH`, `REFERENCE/IMPORT`
* **Edge role annotations**: `LOGICAL`, `STRUCTURAL`, `BOTH`, `UNKNOWN`
* **Projection/pattern annotations** on structural edges (PIN-like semantics): `PASS_THROUGH`, `EVENT_BRIDGE`, `MIDDLEWARE_WRAP`, etc.
* **Stable identities + evidence spans** for nodes *and* edges (micro-address replacement)
* A **graph diff/drift model** keyed by deterministic content identity (not by LLM variability)

### The specific correctness risks (and what you must do to make them acceptable)

#### Risk A — Missing “implicit” structural edges

Framework callbacks, routing tables, middleware chains, event subscriptions, reflection/dynamic dispatch often **do not appear as direct CALL edges**.

**Mitigation**: treat “architecture edges” as **adjacency signals**, not just CALL edges:

* request `EVENT_EMIT`, `EVENT_HANDLE`, `MIDDLEWARE_WRAP`, `ROUTE_DISPATCH`, `JOB_ENQUEUE/DEQUEUE` (names can vary) via the existing `infer_adjacency_signals(requested=...)` mechanism.
* allow “structural edges” to be inferred even without direct CALL syntax (still LLM-based, language-agnostic).

If the system cannot infer an edge with high confidence and it is required by constraints, **block on ambiguity** (do not guess).

#### Risk B — LLM variance makes “drift detection” noisy

PIN drift uses deterministic content hashes. A purely LLM-inferred graph can fluctuate and create false drift.

**Mitigation**: drift must be computed from **deterministic identities first**, and LLM inference should be:

* **cached by content hash** (already present in `infer_code_signals`)
* **re-run only for changed files/spans**
* **stability-gated**: a graph change is “real” only if (a) the code changed, or (b) multi-pass consensus agrees above a threshold

#### Risk C — Logical vs structural classification is sometimes ambiguous

Many edges are legitimately “both” (e.g., domain service calling repository is both algorithmic and architectural in some domains).

**Mitigation**:

* support multi-label classification: `LOGICAL`, `STRUCTURAL`, `BOTH`, `UNKNOWN`
* gates must treat `UNKNOWN` as **blocking only when the edge participates in a constraint**; otherwise it can be tracked as “needs refinement”
* require **evidence spans + rationale** so ambiguity is diagnosable and can be resolved with a constraint answer if needed

#### Risk D — Phase interference / oscillation

Architecture refactors can break tests; quality refactors can accidentally change behavior.

**Mitigation**: enforce **phase-scoped authority** via gates:

* “wiring-only” work may not change logical subgraph fingerprints
* “refactor-only” work may not change logical subgraph fingerprints *or* structural topology fingerprints
* violations route back as blocking findings

This is the single-layer equivalent of “demote to L1/L2”.

### Conclusion

A single-layer system is feasible **only if you treat the annotated adjacency graph as the replacement for pins**, not the raw call graph, and you add **phase authority invariants** to prevent regression.

---

## 2) Single-layer architecture: one codebase, multiple refinement phases

### Core idea

Keep **one authoritative codebase** and derive multiple **read-only projections** (graphs, metrics, receipts). Replace “layer promotion” with:

* **Progressive gating by aspect**
* **Work-item routing back into the same codebase**
* **Phase-scoped change authority** (enforced, not assumed)

### Replace “layers” with “aspects” + “change authority”

Use the system’s existing `required_change_type` semantics as the *control plane*:

* **Behavior change** (algorithm/spec correctness)
* **Wiring only** (architecture/communication paths, no business logic invention)
* **Refactor only** (code quality, no behavior or topology change)

Then define phases as *lenses* over the same codebase:

1. **Phase A — Build (implementation)**

   * Executes the highest-priority queued work items (behavior → wiring → refactor).
   * Uses specialized implementors (the current L1/L2/L3 implementors can remain as *modes*, not layers).

2. **Phase B — Algorithm refinement**

   * Builds/updates annotated graph projections.
   * Runs algorithm gates: comment/stub closure, tests, algorithm connectivity, store ownership, etc.
   * Emits work items tagged `behavior_change` when it fails.

3. **Phase C — Architecture refinement**

   * Uses the same annotated graph.
   * Runs architecture/topology/boundary/flow gates over **structural edges**.
   * Emits work items tagged `wiring_only` when it fails.

4. **Phase D — Code quality refinement**

   * Runs quality reviewers + diff-impact + maintainability metrics.
   * Emits work items tagged `refactor_only` when it fails.
   * If reviewers identify a behavior/topology change is required, they emit a **reclassification** to `behavior_change`/`wiring_only` (no demotion—just escalation).

### How this composes with the existing PromotionLoop state machine

You can keep the 10-step PromotionLoop shape, but remove layer dispatch:

* **BASELINE**: unchanged (manifest + changed files); additionally record `graph_fingerprint` baseline.
* **GAP_EXPLORATION**: becomes “collect work items” from all detectors:

  * code gaps (comments/stubs)
  * algorithm gates violations
  * architecture gates violations
  * quality reviewer findings
* **PLAN**: produces a unified plan where each intention/work item has:

  * `aspect` (`algorithm|architecture|quality`)
  * `required_change_type` (`behavior_change|wiring_only|refactor_only`)
  * `routing_anchor` (file + span OR graph node/edge id)
* **IMPLEMENT**: runs the implementor mode matching the next work item type (behavior first, then wiring, then refactor).
* **COORDINATE**: unchanged: under-spec + ambiguity resolution.
* **ANALYZE**: always builds projections (annotated graph, diffs, metrics).
* **PROMOTE**: runs progressive gates in strict order (algorithm → architecture → quality → governance). No layer promotion.
* **INTEGRATE/VERIFY**: unchanged (CI tick, final tests, receipts).

### What replaces layer promotion/demotion

* **No cross-layer promotion**: all work stays in the same slice root/branch.
* **No demotion**: failures are routed to work items with stronger/earlier authority.

  * Example: quality phase finds “refactor requires logic change” → emit `behavior_change` work item.

Mechanically, you can keep the existing `DemotionTicket` machinery but reinterpret:

* `target_layer` → `target_change_authority` (behavior/wiring/refactor)
* `hop_trace` becomes a trace of authority escalations, not layer jumps

This keeps the diagnostics value while removing the branching/worktree complexity.

---

## 3) Call graph extension design: cross-file + edge annotations + algorithm boundaries

### 3.1 Replace “call graph” with an **Annotated Adjacency Graph**

Use one unified graph type that can carry all relationships the pin graph carried, plus more.

#### Node schema (canonical identity)

A node id must be stable and path-canonicalized (matches your identity constraints):

* `node_id = "{canonical_rel_path}:{qualified_name}"` (this is already how spans are built in `build_candidate_spans`)
* node metadata:

  * `file`, `span {start_line,end_line,...}`
  * `kind` (function/logical_block/etc)
  * `content_hash` (hash of the span text) for deterministic drift
  * `component_id` (from component manifest / phase-0 boundaries)
  * optional tags: `handler`, `middleware`, `adapter`, `domain_rule`, `repo`, etc.

#### Edge schema

Each edge carries:

* `src_id`, `dst_id`
* `signal_type`: at least `{CALL, STORE_TOUCH, EVENT_EMIT, EVENT_HANDLE, REFERENCE}`
* `confidence`
* **evidence**:

  * call site file/span (micro-address)
  * rationale excerpt span (already supported by `infer_adjacency_signals`)
* **annotations**:

  * `edge_role`: `LOGICAL|STRUCTURAL|BOTH|UNKNOWN`
  * `projection_type`: PIN-like categories for structural edges
  * optional: `boundary_crossing` (computed), `latency_class`, etc.

### 3.2 Cross-file edges (Q2)

Do **not** require the LLM to see the entire repo at once. Use a two-stage approach that scales and stays cacheable.

#### Stage 1 — Per-file adjacency inference (already exists)

For each file:

* extract spans
* request adjacency facets: `CALL`, `STORE_TOUCH`, `EVENT`, `REFERENCE` (already done)
  This yields **within-file edges** with evidence.

#### Stage 2 — Cross-file resolution via “call-site linking”

For edges that are currently “within file only”, you need a second mechanism to add cross-file edges.

Two viable strategies (you can implement both; pick based on confidence/cost):

**Strategy A: Candidate-driven resolver (recommended)**

1. Build a **global symbol index** of nodes:

   * key: simple name + qualified name tokens
   * value: candidate `node_id`s
2. For each file, detect **external call tokens** that were not resolved to a local span:

   * add a new requested signal type, e.g. `CALL_TOKENS`, that returns:

     * call site span
     * callee textual name
     * confidence
3. For each token, generate top-K candidates from the global index (pure string match; language-agnostic).
4. Ask the LLM (small prompt) to choose the best target among candidates, returning:

   * chosen `dst_id` or `UNKNOWN`
   * confidence + rationale
5. Emit a cross-file edge `CALL` with evidence anchored at the call site.

This is **content-addressable** per call site and small enough to scale.

**Strategy B: Chunked multi-file inference**
For files with heavy cross-file interaction:

* provide the LLM:

  * the source file
  * a compact “API surface” summary of imported/likely-target files (signatures only, not full text)
* request `CALL` edges that can target any summarized signature.

This is more expensive but can handle cases where token-level resolution fails.

#### Confidence model

Cross-file edge confidence must be explicit:

* `confidence = token_detection_conf * resolver_conf`
* gate thresholds should treat low-confidence cross-file bridges as “AMBIGUOUS” (not “FAILED”) when they are the only thing preventing connectivity, matching your current `CALL_GRAPH_CONNECTED` behavior.

### 3.3 Logical vs structural edge classification (Q3)

Add a new adjacency facet, e.g. `EDGE_ROLE`, that classifies existing edges.

**Classification criteria (operational, not philosophical):**

Label an edge **STRUCTURAL** if most of the following are true:

* caller/callee are in “integration” zones: handlers, middleware, controllers, event adapters
* call exists to route/dispatch/serialize/authorize/log/retry/notify
* replacing the edge with an alternate transport (event bus vs direct call) would not change domain truth

Label an edge **LOGICAL** if:

* it enforces or computes domain rules (validation, calculations, state transitions)
* removing it changes domain correctness even if the plumbing remains

Label **BOTH** if:

* the callee both routes and enforces domain invariants (common in service-layer code)

Label **UNKNOWN** if:

* insufficient evidence or conflicting cues

**Reliability strategy**

* For edges that participate in gates/constraints, require:

  * either `LOGICAL/STRUCTURAL/BOTH` with confidence ≥ threshold
  * or block with an under-spec question (“is this edge architectural wiring or domain logic?”)

### 3.4 “What replaces ProjectionType”

Add `projection_type` on structural edges. A minimal mapping that covers PIN use-cases:

* `PASS_THROUGH` (thin adapter forwarding)
* `EVENT_BRIDGE` (emit/handle coupling)
* `MIDDLEWARE_WRAP` (A wraps B)
* `ROUTE_DISPATCH` (controller/router calling handler)
* `IO_ADAPTER` (domain calling external client)
* `REPO_ACCESS` (domain calling persistence adapter)
* `SCHEDULER_DISPATCH` (job enqueue/dequeue)
* `CONFIG_BINDING` (config injected into component)

You don’t need to perfectly classify every subtype to replace pins—only enough to satisfy the gates that previously used projection types.

### 3.5 Algorithm boundary detection (Q3/Q9)

Do this as **graph operations** first, then LLM naming/validation.

**Deterministic proposal**

* Build the **logical subgraph** (edges with role `LOGICAL` or `BOTH`)
* Identify candidate algorithm components via:

  * weakly connected components, or
  * clustering with weights (favor intra-file and high-confidence edges)
* Define **entrypoints** as nodes with incoming structural edges or with external callers.

**LLM refinement**
For each candidate cluster, ask:

* “Does this cluster represent one coherent algorithm?”
* “Where are the boundaries?”
* “What are the entrypoints and outputs?”
  Return an `AlgorithmGroup` with a stable `algo_id` (hash of sorted node_ids) and a human-readable name.

---

## 4) Gate reorganization: aspect-based progressive gating (Q4/Q8)

### Gate ordering (must be strict)

1. **Algorithm gates** (behavior authority)
2. **Architecture gates** (wiring authority)
3. **Quality gates** (refactor authority)
4. **Governance/receipts gates**
5. **Final verify**

This preserves “sequential stabilization” without separate layers.

### Mapping existing gates into the single-layer system

#### Algorithm gates (survive largely as-is)

* `NO_REMAINING_COMMENTS` (unchanged)
* `NO_STUB_FUNCTIONS` (unchanged)
* `ALL_TESTS_PASS` (unchanged)
* `CALL_GRAPH_CONNECTED` (reformulated to use cross-file graph; optionally logical-subgraph connectedness)
* `STORE_MONOGAMY` (recomputed from `STORE_TOUCH` edges grouped by store id)

Add two new gates that replace “implicit correctness from layer separation”:

* **`NO_UNRESOLVED_EDGE_ROLES`**: any edge required by constraints must not be `UNKNOWN`
* **`ALGORITHM_GROUP_COVERAGE`**: all public entrypoints belong to an AlgorithmGroup, or are explicitly marked utility/infra

#### Architecture gates (replace pin-dependent gates)

Replace PIN gates with graph equivalents:

* `PIN_COVERAGE` → **`STRUCTURAL_EDGE_COVERAGE`**

  * every declared communication path (from manifest/constraints) is realized in the structural graph
* `ARCH_DRIFT` → **`STRUCTURAL_DRIFT`**

  * structural topology fingerprint differs from last “architecture-stable” checkpoint only if authorized by a wiring work item
* `ARCH_BOUNDARY` (same intent)

  * structural edges cannot violate component boundary rules
* `TOPOLOGY` (same intent)

  * required reachability/order constraints hold
* `GOVERNANCE` (same intent)

  * config externalization, service ownership, event naming/versioning, etc.

Add a replacement for “NO_INLINED_ATOM_LOGIC”:

* **`NO_DOMAIN_LOGIC_IN_ARCH_ZONES`**

  * if a node is tagged structural (handler/middleware/adapter), its outgoing edges should be mostly structural, and it should not own store mutations except via domain calls (heuristic + block on ambiguity).

#### Quality gates (same reviewers, stronger invariants)

Keep the L3 reviewer pack, but enforce invariants using graph diffs:

* **`REFACTOR_ONLY_NO_LOGICAL_DRIFT`**

  * when executing refactor-only intentions, logical subgraph fingerprint must not change (node content hash changes allowed only if tests unchanged + logical edges unchanged, or stricter if you prefer)
* **`REFACTOR_ONLY_NO_STRUCTURAL_DRIFT`**

  * structural topology fingerprint must not change (unless the plan included wiring-only items)
* Existing “diff-impact” checks remain useful, but now grounded in graph diffs rather than layer comparisons.

### How a single-layer system prevents “merging code with issues”

* Merge is blocked unless **all gates across all aspects pass in the same iteration**.
* Quality fixes that break algorithm gates cause immediate failure and generate a `behavior_change` work item (escalation), not silent regression.

---

## 5) Routing mechanism without PINs (Q1/Q9)

PINs solved two routing problems:

1. “Where is the architectural location that consumes this atom?”
2. “If an atom changes, what architecture is impacted?”

The annotated adjacency graph solves both, but only if you preserve **edge evidence** and **stable identities**.

### Routing primitives

* **Node anchor**: `{node_id, file, span}`
* **Edge anchor**: `{edge_id, src_id, dst_id, callsite_span}`
* **Path witness** (for topology constraints): a list of edge_ids

### Change propagation without pins

When a node changes (content hash differs):

* impacted logical scope: its AlgorithmGroup cluster(s)
* impacted structural scope: all incident edges with role `STRUCTURAL|BOTH`
* impacted boundary scope: any cross-component structural edges on paths containing the node

This is strictly more general than pins, because it can propagate through multi-hop relationships without a special tracing engine.

### “Where do I put new code?”

Call graph alone doesn’t choose destinations for **new** nodes. You still need:

* phase-0 library/component boundaries
* component manifest ownership rules
* existing patterns (entrypoints/handlers/adapters)

Single-layer routing rule set:

1. If a requirement maps to an existing AlgorithmGroup → route to its entrypoint node(s).
2. If it requires a new AlgorithmGroup → create a stub entrypoint in the owning component (phase-0 boundary) and let Build implement.
3. If it is an architecture/wiring requirement → route to the structural edge anchor (call site) or to the component entrypoint responsible for the interaction.
4. If routing confidence is low → block with an under-spec question (“which component owns this behavior?”), not a guess.

### Work-item schema (replace “demotion target layer”)

Every finding/work item should carry:

* `required_change_type`: `behavior_change|wiring_only|refactor_only`
* `aspect`: `algorithm|architecture|quality`
* `anchor`: node/edge/callsite/span
* `expected_outcome`: short constraint-like statement
* `evidence_refs`: graph snapshot ids + excerpts

This is the “routing over extraction” contract.

---

## 6) Convergence strategy (Q5)

### Prevent phase interference by enforcing monotonic checkpoints

Introduce two stable checkpoints per slice:

1. **Algorithm-stable checkpoint**

   * recorded when all algorithm gates pass
   * stores `logical_fingerprint` (see below)

2. **Architecture-stable checkpoint**

   * recorded when architecture gates pass
   * stores `structural_fingerprint`

Then enforce:

* Wiring/refactor work may not regress algorithm checkpoint.
* Refactor work may not regress architecture checkpoint.

### Fingerprints (deterministic, not LLM-flaky)

Define fingerprints from deterministic inputs:

* `logical_fingerprint`:

  * sorted set of `(src_id, dst_id)` for edges with role `LOGICAL|BOTH` above confidence threshold
  * plus per-node `content_hash` for nodes in AlgorithmGroups
* `structural_fingerprint`:

  * sorted set of `(src_id, dst_id, projection_type)` for edges with role `STRUCTURAL|BOTH`
  * plus component boundary crossings summary

If edge roles are LLM-inferred, only include edges whose role confidence is above threshold; edges below threshold are tracked separately and can block when required by constraints.

### Stagnation detection

Extend the existing sliding-window minimum to track per-aspect:

* `open_gaps_algorithm`
* `open_gaps_architecture`
* `open_gaps_quality`
* `unknown_edge_roles_required_by_constraints`

Stop conditions:

* natural completion: all are zero and all gates pass
* bound hit: max iterations
* no-progress: minimum unchanged across window → block and surface top repeated findings + ambiguous edges

### Phase scheduling inside the loop

Even in a single layer, you should still **prioritize authority**:

1. Drain `behavior_change` work items first until algorithm checkpoint is stable.
2. Drain `wiring_only` next until architecture checkpoint is stable.
3. Drain `refactor_only` last.

This is how you preserve the value of the old “layer” sequencing without separate layers.

---

## 7) Communication path constraints as graph constraints (Q10)

### What a communication path constraint looks like

Represent constraints over the **structural subgraph**:

Examples:

* **Max hops**: `SettlementCompleted` notification must reach `RiskEngine` within 2 structural hops.
* **Ordering**: middleware `Auth` must wrap handler before `SettlementProcessor`.
* **Reachability**: `SettlementService` must eventually emit `SettlementCompleted` event on success.
* **Boundary**: `Payments` component may call `Risk` only via `RiskClient` adapter, not directly.

### Constraint representation (store-friendly, explicit serialization)

Add a new constraint fact type (conceptually) in the constraint store:

`GraphConstraint` fields:

* `constraint_id` (stable)
* `scope`: slice/component id(s)
* `applies_to`: `STRUCTURAL|LOGICAL|BOTH`
* `predicate`:

  * endpoints: node selectors (by node_id, component_id, tag, name match)
  * edge filter: role/signal/projection types
* `assertion`:

  * `PATH_MAX_HOPS(k)`
  * `MUST_REACH`
  * `MUST_NOT_REACH`
  * `ORDER_BEFORE`
  * `NO_CYCLE`
  * `ONLY_VIA {selector}`

### Checking constraints

Run deterministic graph algorithms over the annotated graph:

* BFS for reachability/hops
* topological order / path ordering checks
* boundary checks on edges crossing component ids
* path witness emission: return the violating path as evidence (edge_ids)

Violations become work items:

* typically `wiring_only` unless they require domain behavior changes

This composes cleanly with your existing constraint ingestion/QA architecture: constraints become authoritative facts; gates become checkers; work items become routed fixes.

---

## 8) Complexity comparison (Q7): what is eliminated vs introduced

### Eliminated modules/concepts (directly from the current architecture)

**PIN system (entirely removable)**

* `schemas/pin_functions.py` (PinFunction, ImportEdge, ProjectionType…)
* `core/pin_registry.py` (Index/Snapshot/Drift/MicroAddress…)
* `branches/pins.py` (PinRegistry + drift report)
* `downward_flow/engine.py` (pin tracing for demotion)
* `PinFunctionOrchestrator` usage in PROMOTE (promotion mechanics tied to pins)
* Pin coverage + pin drift gates and any pin-based evidence contracts

**Layer duplication**

* layer-aware dispatch branches in:

  * GAP_EXPLORATION
  * IMPLEMENT
  * ANALYZE
  * PROMOTE
  * COORDINATE
* layer-specific “slice types” and layer-specific worktree promotion/demotion loops
* distinct “review pack per layer” as *separate routing systems* (they can remain as reviewers but share one findings contract)

### Introduced concepts/modules (net-new)

* **Annotated adjacency graph** (single schema replacing both call graph and pin graph)
* **Cross-file resolution** pipeline (token extraction + resolver)
* **Edge role + projection annotations**
* **Algorithm groups** (boundary detection)
* **Graph fingerprints + drift** (for phase authority invariants)
* **Graph constraints** (communication path constraints)

### Net complexity outcome

You are trading:

* **N copies of orchestration logic + pin bridging machinery**
  for
* **one orchestration flow + one richer graph projection**

This is a net simplification if you enforce:

* one findings schema
* one routing schema
* one evidence chain (graph snapshot + diffs)

The primary risk is “annotation complexity inflation”; prevent that by:

* keeping projection types minimal
* treating UNKNOWN as a first-class state (block only when necessary)
* ensuring graph inference is incremental + cached

---

## 9) Migration path: incremental, evidence-driven (Q9 deliverable)

A safe migration is **not** “delete pins and layers and hope”. Do it in measured steps with parallel evidence.

### Step 0 — Add the new graph as a parallel artifact

* In current L1 ANALYZE, emit an **annotated adjacency snapshot** (even if cross-file is incomplete initially).
* Keep pins unchanged.
* Add a comparison report: “pin edges vs structural edges coverage”.

### Step 1 — Implement cross-file edges + evidence spans

* Add cross-file resolver and start using it for `CALL_GRAPH_CONNECTED` (still in L1 gates).
* Track ambiguity rate; block only when it affects a gate.

### Step 2 — Replace pin-dependent L2 gates with graph equivalents (still in L2 layer)

* Implement `STRUCTURAL_EDGE_COVERAGE`, `STRUCTURAL_DRIFT`, boundary/topology checks over structural edges.
* Keep pins as diagnostics only (no longer required for pass).

### Step 3 — Remove pin proposals from implementors

* Update L2/L3 implementor outputs to stop emitting pin proposals.
* Remove pin orchestrator from PROMOTE mechanics; keep graph snapshot emission.

### Step 4 — Collapse L1+L2 into one layer (phases), keep L3 separate temporarily

* This removes the biggest fidelity risk (L1→L2 projection loss) first.
* Enforce algorithm checkpoint invariants before architecture work.

### Step 5 — Fold L3 into phases

* Enforce refactor-only invariants with graph fingerprints + tests.
* Unify reviewer findings format and routing.

### Step 6 — Delete the PIN system and downward-flow tracing

* Only after you have stable graph-based drift + coverage checks and have demonstrated parity on eval runs.

This path is reversible until Step 6.

---

## 10) Agent prompt integration (Q6 deliverable)

### What agent prompts contribute in a single-layer system

They are not graph nodes, but they can be:

1. **Constraint sources** (policy/ordering/boundary rules the system must enforce)
2. **Annotation hints** (what edge roles/projection types matter for this repo)
3. **Routing heuristics** (where wiring changes are allowed)

### Deterministic extraction: make it explicit and enforceable

If prompt extraction is truly deterministic, formalize it:

* Require each agent prompt to include a machine-readable section, e.g. `## CONTRACT`:

  * `declares_signal_types`: list
  * `declares_constraints`: list of GraphConstraint-like records
  * `allowed_change_type`: behavior/wiring/refactor
* Parse deterministically; if parse fails, treat as **structural failure** (block), because the agent is unreliable anyway.

### Propagation

* Hash the extracted contract; include it in:

  * graph inference cache keys (requested signals set)
  * gate configuration snapshots
* When the prompt changes, the hash changes, which forces:

  * graph annotation recomputation (only where relevant)
  * gate reruns
    This preserves replayability and avoids stale derived behavior.

### Handling “prompt says call X before Y”

That becomes a **graph ordering constraint**:

* nodes: selectors matching X and Y
* assertion: `ORDER_BEFORE(X, Y)` on structural paths (or within a handler chain)
  If the graph cannot confirm it, it becomes either:
* a wiring work item, or
* an ambiguity question if ownership is unclear

---

## 11) What extraction is acceptable (Q11)

Within your constraints:

* **Acceptable**: LLM-based inference of adjacency signals (`infer_adjacency_signals`) because it is semantic and language-agnostic in principle.
* **Acceptable**: deterministic parsing of *controlled formats* (agent prompts, known manifests).
* **Conditionally acceptable**: deterministic heuristics over code as **non-authoritative candidate generation** (string matching for symbol candidates). This is not “parsing for truth”, it’s “ranking candidates for LLM resolution”.
* **Not acceptable as authority**: language-specific AST extraction that becomes required for correctness. If introduced, it violates robustness assumptions unless you treat it as optional hints.

The line is: deterministic extraction is fine only when you control the format or it is used as a hint; the authoritative interpretation of uncontrolled code structure must remain inference-validated and gate-checked.

---

## Direct answers to the headline questions

### Q1: Can a call graph replace PINs?

**Yes, if “call graph” means an annotated adjacency graph** with edge roles, projection types, cross-file edges, evidence spans, and drift via deterministic fingerprints.

### Q2: How to extract cross-file call graph?

Use per-file inference + token-based cross-file resolution with candidate lists and small cached LLM resolver calls; do not rely on whole-repo context windows.

### Q3: Distinguish logical vs structural edges?

Use multi-label edge roles with confidence and evidence; block only when an UNKNOWN edge is required by a constraint/gate.

### Q4: What happens to gates?

They reorganize by aspect: algorithm → architecture → quality, with new invariants that enforce “no regressions” across phases.

### Q5: How does refinement converge?

Through progressive gating + monotonic checkpoints + per-aspect stagnation detection + strict authority ordering of work items.

### Q6: How do agent prompts feed in?

Extract explicit contracts deterministically; translate ordering/boundary rules into graph constraints; use prompt hashes to invalidate caches.

---

If you want one design decision to make or break this effort: **treat “phase authority” as enforceable invariants (via graph fingerprints), not as a workflow convention.** That is what preserves the old correctness guarantees without keeping the old layers and pins.

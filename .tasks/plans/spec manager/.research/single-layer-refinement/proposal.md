## Single-Layer Iterative Refinement with Shape-Based Routing

**Goal:** retire **L1/L2/L3** and **PINs** by replacing “promotion across representations” with **one codebase** refined in **phases**, routed by **external shapes** (structural patterns) and converged by **deterministic evidence** (tests + deterministic checks), not by comments/markers.

---

# 1) Core reframing

### What’s being replaced

The current system uses **promotion** to move work across three representations:

* L1: algorithmic “code-as-spec” atoms
* L2: architectural assembly (pins bridge L1→L2)
* L3: code quality polish

The *real* problems created by that structure:

* You pay for **cross-layer handoffs** (fidelity loss + drift risk).
* You need **PINs** to bridge “what” to “where”.
* You need **demotion** to shuttle failures backwards.

### What replaces it

A single-layer system keeps **one representation**: the codebase.
It replaces “bridge & promote” with:

1. **Shapes** (external structural summaries / patterns)
2. **Matching** (compare shapes vs observed structure)
3. **Work items** (external TODOs, not code markers)
4. **Deterministic verifiers** (tests + deterministic checks) as convergence authority
5. **Phases** (Libraries → Architecture → Quality) that progress forward-only, each as its own cycle

**Key point:** the call graph is a **hint before classification**; after deterministic classification against shapes, it becomes the algorithm representation — but verifiers remain the only convergence authority.

---

# 2) What the existing call graph already does (and doesn’t)

## 2.1 What you already have

`compliance/promotion/call_graph.py` builds a per-file call graph:

* Functions are discovered via `analyze_source()` (LLM-based).
* Call edges are inferred via `infer_adjacency_signals(requested={"CALL"})` (LLM-based).
* Edges include provenance: file path + rationale span + raw evidence.

## 2.2 What it is genuinely good for (today)

**As a routing hint inside a file**, it already supports:

* Finding “what else is adjacent” when a function changes or fails.
* Explaining local algorithm structure as a chain of calls.
* Supporting the existing “call graph connected” completeness heuristic (as a heuristic).

## 2.3 What it cannot provide without new extraction machinery

The current extractor cannot reliably provide:

* **Cross-file call edges** (because spans are per-file; imported functions aren’t in span IDs).
* **Events / DI / middleware edges** (not CALL).
* **Reliable algorithm boundary detection** (clustering would be non-deterministic inference).
* **Reliable logical vs structural edge typing** (that’s semantic classification, also inference).

**Conclusion:** the existing call graph alone cannot replace PINs for architecture-level routing, because PIN value is primarily **cross-file and cross-mechanism** (import/event/middleware/DI), while your call graph is **intra-file CALL-only**.

That's exactly why shapes matter: they extend routing without turning the system into a graph-extraction project.

## 2.4 Call graph classification role (post-matching)

The call graph has a deeper role than just hints. After deterministic classification against shapes:

* **Algorithm membership**: surface API entrypoints as roots → reachable subgraphs within shape → labeled with shape_id + algorithm_id
* **Communication paths**: cross-shape edges classified by declared contracts
* **Logical vs structural**: within-shape non-contract = logical; contract-realizing or cross-shape = structural

The classified call graph is authoritative as the system's **internal representation** of algorithm structure (for planning and routing within Architecture and Quality). It is **not** authoritative evidence of correctness or convergence — that remains tied to deterministic verifiers.

If classification yields ambiguity (multiple candidate roots, unclear ownership), the system blocks per existing under-spec/coordination rules.

---

# 3) Shapes: what they are, and why they are “lighter than pins”

## 3.1 Definition

A **shape** is an **external, controlled-format structural description** of a scope (module/package/component) that answers:

* **What it is** (role/responsibility)
* **Where it lives** (owned paths)
* **What it exposes** (surface API *as documentation*)
* **What it depends on / who consumes it** (expected structural relationships)
* **How it is verified** (deterministic verifiers)

This is exactly the model already used by your `design/routing/*.md` summaries in context2.zip:
they are *structural shape documents* for spec_manager itself.

## 3.2 Shapes are not pins

Pins are:

* per-function bridge entities
* projection-typed edges
* registry snapshots + drift + microaddressing
* operationally authoritative

Shapes are:

* per-scope routing summaries (module/package/component)
* matchable by **stable, coarse invariants** (paths, dependency direction, contracts)
* authoritative only through **explicit verifiers** (tests/checks), not through inferred edges

Pins say: “function PFUNC-0007 is used at location X via EVENT_BRIDGE.”
Shapes say: “module A owns the event producer role; module B owns handler role; the contract is verified by test T.”

That is strictly less machinery, and it’s robust to internal refactors.

---

# 4) Shape format (concrete) and granularity

## 4.1 Reuse the existing routing-summary shape style

Do not invent a new schema-heavy DSL. Reuse the existing shape document conventions already present in `design/routing/*.md`:

* Header fields:

  * `Classification`
  * `Package`
  * `Files`
  * `Role`

* Sections:

  * `Systems` (optional)
  * `Surface API` (documentation)
  * `Dependencies` and `Consumers` (declared expectations)

**Minimal addition required for convergence:** a `Verifiers` section.

### Minimal verifier section (example)

```md
## Verifiers
- TEST: tests/test_orchestration_contracts.py::test_promotion_loop_step_order
- TEST: tests/test_orchestration_contracts.py::test_slice_completion_is_idempotent
- IMPORT_BOUNDARY: allow=[spec_manager/planner, spec_manager/refinement] deny=[spec_manager/projection]
```

This keeps shapes human-usable, LLM-usable, and deterministically parseable.

## 4.2 Shape granularity (three levels, minimal)

1. **Package/Component Shapes** (primary; like your routing summaries)

   * Stable routing unit for work items and boundary checks.

2. **Contract Shapes** (embedded inside a package shape)

   * Cross-module communication paths (events/DI/middleware) described *abstractly*.

3. **No function-level shapes**

   * This is how shapes stay lighter than pins.

---

# 5) Where shapes live, how they are derived, and how they are updated

## 5.1 Storage

* **System shapes (spec_manager itself):** `design/routing/`
* **Per-run/project shapes:** `workspace/routing/` (or `workspace/shapes/`)

The “shape pack” for a run is a folder of these files plus a small index:

* `routing/INDEX.md` (human)
* `routing/index.json` (machine; deterministic extraction output)

## 5.2 Derivation rule (keeps authority clean)

Shapes are derived from **controlled inputs**, not inferred from code:

* spec decomposition outputs (libraries/components)
* human-authored design docs (like context2)
* explicit decisions persisted by planner

Shapes may be *drafted* by LLMs, but **only as proposals**:

* they become active only when saved and referenced by deterministic verifiers
* shape mismatch never silently rewrites the shape

This avoids “LLM inferred authority”.

## 5.3 Update rule

Updating shapes is treated like updating any other specification artifact:

* done within each phase's authority scope when a structural change is intentionally introduced
* Libraries phase: library shapes updated during library skeleton refinement
* Architecture phase: component shapes and contracts updated during architecture skeleton refinement
* always accompanied by updating verifiers (tests/checks) when needed

No automatic "shape regeneration from code".

---

# 6) Matching: how shapes extend the call graph without new extraction machinery

## 6.1 Observed structure sources

**Deterministic (authoritative):**

* file tree + canonicalized paths
* import dependency scan (already exists in the system; also reflected in `design/routing/DEPENDENCIES.md`)
* test results / commands
* explicit manifests/configs when controlled format is used

**LLM-based (non-authoritative routing hints):**

* existing per-file call graph (CALL edges)
* per-file structural analysis (`analyze_source`) used only to locate candidate spans

## 6.2 Matching outputs (what the matcher produces)

The matcher produces:

* a **ShapeMatchReport** per shape:

  * observed dependencies (from import scan)
  * declared dependencies (from shape doc)
  * drift deltas (declared vs observed)
  * verifier results (pass/fail)
  * diagnostics if ambiguous

* **Work items** routed within the current phase's PromotionLoop (not markers in code)

## 6.3 Matching rules (minimal)

1. **Ownership match** (deterministic):
   A file belongs to the most specific shape whose `Package:` prefix contains it.

2. **Dependency match** (deterministic):
   Declared dependencies should be a superset of observed dependencies (or vice versa, policy-controlled).
   Any mismatch produces a **drift work item**:

   * either “update shape” or “remove illegal dependency”, based on policy.

3. **Contract match** (verifier-backed):
   Communication contracts are satisfied iff their verifiers pass.
   The implementation mechanism can change freely as long as verifiers hold.

4. **Call graph match** (non-authoritative):
   Used only to suggest *where* inside an owned file to implement a fix.

This is “matching over pinning”: relationships are not tracked as per-call edges in a registry; they’re checked against stable, coarse structure and verified by tests.

---

# 7) Handling non-call relationships (events, DI, middleware) without markers or pins

## 7.1 The principle

Non-call relationships are not “extracted”; they are:

* **described as contracts in shapes** (originating from spec/algorithms)
* **verified by deterministic verifiers** (tests and controlled config checks)
* **routed to implementation locations** via ownership + pattern templates

## 7.2 Contract patterns (small library)

A minimal pattern library contains **templates**, not new graph types:

### Pattern: Event flow

Shape declares:

* Producer shape
* Consumer shape
* Event name (string)
* Verifier test(s)

Example contract block inside a shape doc:

```md
### Contract: SettlementCompleted notifies RiskEngine
- Kind: EVENT_FLOW
- Producer: SH-SETTLEMENT
- Consumer: SH-RISK
- Payload: SettlementCompleted{settlement_id, timestamp, ...}
- Verifiers:
  - TEST: tests/test_settlement_events.py::test_risk_engine_receives_completion
```

Implementation may be:

* direct call
* pub/sub
* queue
* webhook
  Doesn’t matter, as long as verifier passes.

### Pattern: DI binding

Shape declares:

* Composition root location (file/module *as routing hint*)
* Binding contract (interface → implementation)
* Verifier test ensures container resolves & runtime wiring works

### Pattern: Middleware ordering

Shape declares:

* middleware chain semantics (A before B)
* verifier test asserts order (or behavior consequence)

**No code markers.** The verifier test is the evidence, the shape is the routing map.

---

# 8) Routing: how work items are generated without pins or code markers

## 8.1 What replaces “TODO comments”

Use the existing orchestration concept of **external work items** (durable artifacts), not code comments.

A work item includes:

* `work_item_id` (typed ID)
* `shape_id` (primary routing handle)
* optional file-path anchors
* `required_change_type`: `behavior_change | wiring_only | refactor_only | spec_change`
* evidence references (failing tests, drift report, constraint refs)

## 8.2 How routing works (mechanically)

Routing is two-step:

1. **Scope routing (deterministic)**

   * map failing file → owning shape
   * map failing verifier/test → shape(s) referenced in the contract
   * map import boundary violation → producer shape

2. **Intra-scope targeting (hint)**

   * use call graph (within owning files) + textual search to suggest specific functions
   * if ambiguous, emit a coordination signal and block (no guessing)

## 8.3 Change propagation without pins

When something changes:

* compute changed files (git diff)
* map files → shapes
* propagate to neighbor shapes via:

  * declared dependencies/consumers (shape docs)
  * observed dependencies (import scan)

Generate work items:

* rerun verifiers for impacted shapes
* update contracts if spec changed
* update tests if contract verification missing

This replaces pin-based “affected locations” with **shape-neighborhood propagation**.

---

# 9) Single-layer phase mechanism (end-to-end)

## 9.1 One codebase, three phases (forward-only)

A run progresses forward through three phases over the same workspace:

1. **Libraries** (L1-equivalent)
2. **Architecture** (L2-equivalent)
3. **Quality** (L3-equivalent)

"Build" is not a separate phase — it is what happens **inside IMPLEMENT** in each phase's PromotionLoop. Each phase edits code via its own PromotionLoop with phase-appropriate behaviors.

## 9.2 Skeleton lifecycle per phase

Each phase follows:

1. **Propose skeleton (draft)** — structural map at that scale ("where code can exist")
2. **Do work** — PromotionLoop over slices; edits happen here
3. **Refine skeleton (non-draft)** — freeze structural invariants; record commit tag

Skeletons are **external structural artifacts**, not code markers or specs.

**Libraries skeleton freeze:** library roster, ownership boundaries, store ownership, library shapes become non-draft. Function bodies and internal details remain editable.

**Architecture skeleton freeze:** component roster, contract inventory, contract verifier suite. Library shapes remain frozen from Libraries phase.

**Quality skeleton freeze:** internal organization decisions recorded as complete.

## 9.3 Phase authority boundaries (no backtracking)

* **Libraries** may perform any change type within library boundaries (full code+test authority).

* **Architecture** may:
  * edit wiring, components, contracts, adapters
  * edit algorithm implementations in-place within existing library boundaries (phase-local remediation)
  * **NOT** create new libraries, change library ownership, reassign store ownership
  * If it needs library boundary changes → **block** (not demote)

* **Quality** may:
  * extract helpers, rename, reorganize, restructure files
  * **NOT** change behavior (tests + contract verifiers must stay green)
  * If behavior change needed → **block** (not demote)

If a phase encounters something outside its authority, it **blocks with diagnostics**. No re-triage to an earlier phase. No demotion.

## 9.4 Phase 0 outputs (foundation for Libraries)

Phase 0 is not "just decomposition." It produces:

* **Draft shapes**: one per library, ownership paths, declared dependencies, initial contracts
* **Algorithm inventory**: names + owning library + entrypoints + required invariants
* **Store inventory**: IDs + owning library + access boundaries + required adapters

These are run-scoped artifacts treated as authoritative inputs to Libraries' skeleton proposal.

## 9.5 Explicit iteration bounds

Define these caps (configurable; defaults shown):

* `max_iterations_per_slice = 20` (per phase, per slice)
* `max_work_items_per_phase = 50` (prevents reviewer spew from thrashing)
* `stagnation_window = 2` — if the same verifier fails with no diff progress twice → block with diagnostics

No "repeat until convergence" across all phases. Each phase has its own bounded cycle.

## 9.6 Per-phase convergence (deterministic)

**Libraries convergence:** skeleton non-draft + all library shape verifiers pass + dependency drift resolved + no open work items + within iteration bounds.

**Architecture convergence:** skeleton non-draft + all contract verifiers pass + import boundary rules satisfied + no open work items + within bounds.

**Quality convergence:** all tests + all contract verifiers green + refactor items closed + diff-impact policy satisfied + within bounds.

**Global termination:** run terminates after Quality convergence, with optional QA evaluation/reporting.

LLM review findings alone cannot keep the system spinning forever; they must be converted into verifiable tasks (tests/checks) or they remain advisory.

---

# 10) Compliance gates reorganized for single-layer

## 10.1 Replace layer gates with aspect gates

Instead of "L1/L2/L3 gates", use **Aspect Gate Groups** that run within the three phases. Some hard verifiers (ALL_TESTS_PASS, contract verifiers) are required in multiple phases:

### Libraries phase gates

**Hard (deterministic):** library-level verifiers (tests/checks referenced by library shapes), required store boundary checks (import boundary rules), baseline test suite (slice + periodic full), ALL_TESTS_PASS.

**Soft (routing signals):** LLM-based "remaining gaps" scans, call-graph connectivity checks.

### Architecture phase gates

**Hard (deterministic):** shape matching (declared vs observed dependency direction), contract verifiers for EVENT_FLOW/DI_BINDING/MIDDLEWARE_ORDERING, integration tests proving cross-component paths, ALL_TESTS_PASS.

**Soft:** L2 reviewers (findings must translate into deterministic verifier additions or concrete wiring work items).

### Quality phase gates

**Hard (deterministic):** ALL_TESTS_PASS, all contract verifiers remain green, deterministic style checks if configured.

**Soft:** quality reviewers (clarity/consistency/maintainability) produce refactor work items, diff-impact classifier flags risk.

## 10.2 Mapping the current gates (what survives)

From your current tables:

### Keep (as hard, but reformulated around verifiers)

* `ALL_TESTS_PASS` → remains hard (primary authority, required in ALL phases)
* `NO_ARCH_BOUNDARY_VIOLATIONS` → becomes import-boundary verifier per shape
* `TESTS_PASS` → redundant with ALL_TESTS_PASS (merge)

### Convert to soft signals or "verifier-required"

* `CALL_GRAPH_CONNECTED` → soft routing signal unless you can define a deterministic verifier equivalent
* `NO_STUB_FUNCTIONS` → soft signal unless stub-ness is deterministically detectable for the language/tooling in use
* `STORE_MONOGAMY` → becomes:

  * either a deterministic boundary verifier (if store access is through controlled adapters)
  * or a contract test requirement

### Eliminate (pin/layer dependent)

* `PIN_*` gates (coverage, consumption, edge realization)
* `ARCH_DRIFT_PASS` as pin-registry drift
  → replaced by **shape drift** (declared vs observed deps) + verifier tests
* `NO_INLINED_ATOM_LOGIC` as atom/arch divide
  → replaced by: "shape contract verifiers pass" + quality review tasks

This is a large collapse in gate machinery.

---

# 11) Demotion in a single-layer system (no backtracking)

Demotion-as-layer-transfer is removed.

What remains is **classification of required change type**, but it is used only for:

* routing within the current phase's work queues
* detecting illegal changes for the phase (e.g., behavior change in Quality)
* deciding block vs proceed

Authority classification is **phase-context-dependent**:

* **Libraries phase:** behavior_change, spec_change, wiring_only, refactor_only → all within authority
* **Architecture phase:** wiring_only → within authority; behavior_change within existing library boundaries → within authority (in-place algorithm remediation); behavior_change requiring new library or ownership change → block; refactor_only → block
* **Quality phase:** refactor_only → within authority; behavior_change → block

DownwardFlowEngine and pin tracing disappear because pins disappear.

---

# 12) Net simplification inventory

## 12.1 Deleted / collapsed

* Cross-layer propagation machinery (clean→dirty between layers)
* Layer-transition demotion loops
* Downward pin tracing (DownwardFlowEngine)
* PIN registry / snapshot / drift / projection types and all pin-only gates
* "Pipeline pass" multi-run machinery driven by demotion (max_pipeline_passes becomes structurally unnecessary)
* Layers as separate representations (L1/L2/L3)
* Atoms vs architecture as distinct codebases
* ProjectionType as an operational routing primitive
* MicroAddress addressing

## 12.2 Kept

* PromotionLoop state machine (10-step, phase-aware)
* Three sets of planner behaviors (L1/L2/L3) — now explicitly the three phases
* Review packs (L2 + L3), but their pin-dependent dimensions are replaced by shape-based checks
* Coordination infrastructure and evidence bundles

## 12.3 Introduced (still minimal)

* Shape matcher (declared vs observed dependencies)
* Contract verifier runner (tests/checks referenced by shapes)
* Call graph classifier (deterministic matching that labels subgraphs/contracts)
* Skeleton lifecycle per phase (draft→non-draft with commit tags)

These replace pins with **matching + classification**, not with code markers and not with a new pin-like registry.

**Net effect:** you remove a bridging subsystem (pins + drift + tracing) and an entire layer-promotion pipeline, replacing them with a small, external "map + verifier + classify" mechanism.

---

# 13) Extraction boundary (explicit)

## 13.1 Deterministic (allowed as authority)

* Parsing shape docs (controlled format)
* Import dependency scan (deterministic tooling already present/assumed)
* Test execution results
* File hashes/diffs
* Controlled manifests/config parsing (only if format is explicitly defined)

## 13.2 LLM-based (allowed only as routing hints / diagnostics)

* call graph inference (`infer_adjacency_signals`)
* function span discovery (`analyze_source`)
* reviewer findings (architecture/quality)
* suggestion of which file/function to edit

## 13.3 Rule: no LLM output becomes convergence authority

If an LLM output matters, it must be converted into:

* a deterministic verifier (test/check), or
* an explicit human decision, or
* a blocked ambiguity requiring user input

This prevents “non-deterministic extraction as truth”.

---

# 14) Evaluation proposal (how to validate before committing)

## 14.1 Experiment design: A/B on the same fixtures

Run your existing eval harness twice:

* **Baseline:** current L1→L2→L3 + pins
* **Variant:** single-layer phases + shapes

Use the same specs, same seeds/models, same budgets.

## 14.2 Success criteria (must be met)

1. **Spec fidelity not worse**

   * QA/judge pass rate ≥ baseline
   * no increase in “dropped requirement” findings

2. **Reduced thrash**

   * fewer demotion-like cycles (work item churn) than baseline
   * fewer iterations to converge (within explicit bounds)

3. **Complexity reduction**

   * delete pin modules + layer transition machinery
   * fewer gate definitions and fewer dispatch branches

## 14.3 Failure criteria (stop)

* Shape drift becomes unmanageable (frequent “declared vs observed” mismatches that don’t converge)
* Architecture issues that pins previously caught now escape without verifiers
* The system relies on LLM heuristics to “declare success” (violates authority model)

## 14.4 Minimal proof-of-feasibility milestone

Before full migration, validate the core claim:

* Implement shape parsing + dependency drift check + verifier runner
* Attach a small set of verifiers to a few critical shapes
* Show that a failure routes to the right owner without pins, and converges after Build fixes it

If that routing loop works reliably, the rest is incremental.

---

# 15) What this design implies about “PIN retirement”

PINs are needed when:

* algorithm is authored somewhere *separate* from architecture
* you must track per-atom placement and projection

In a single-layer system:

* there is no second representation that needs bridging
* “where something lives” is owned by shapes (coarse scope)
* “does it work” is proven by verifiers (tests/checks)
* “how does it connect” is checked by import boundaries + contract tests

So **PINs can be retired** *if and only if* you accept this swap:

* from: function-level bridge registry + drift tracing
* to: scope-level shape contracts + deterministic verifiers

If you cannot write verifiers for key structural contracts (especially non-call relationships), pins were giving you a safety net you are not replacing. In that case, the single-layer system should not ship.

---

## Summary of the design in one sentence

Keep one codebase; progress forward through **Libraries → Architecture → Quality** phases (each with its own skeleton lifecycle and PromotionLoop); route all work via **external shapes** matched against **deterministic observations** (imports/tests); use the call graph as a **routing hint before classification** and the **algorithm representation after classification against shapes**; converge per-phase when **skeleton is non-draft + all shape verifiers pass + no open work items**, within explicit iteration bounds.

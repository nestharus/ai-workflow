## High-level finding

The current system’s *core control-flow and data-flow* are “compiler pipeline” shaped:

* **Code → mechanical extraction (AST/tokenize) → derived artifacts (reports/graphs) → LLM decisions**
* **One global pass P0→P10**, not an iterative per-slice promotion loop.

That shape contradicts the philosophy in **three structural ways** that are deeper than “uses Python AST”:

1. **Intermediate representations become the de facto spec** (because the system’s “understanding” lives in extracted artifacts), conflicting with **Code IS the Spec**.
2. **The system repeatedly “discovers” what to do** (scanning/parsing/routing) instead of having *process-triggered targets*, conflicting with **System always knows what to edit** and **Routing only at bottom layer**.
3. **The graph is downstream of code parsing** instead of being the primary object produced by LLM work and then verified, conflicting with **Graph operations** + **LLM does work during its task** + **No redundant mechanical steps**.

Everything else (missing demotion loop, duplicated analyzers, mechanical pinning, etc.) falls out of those three.

---

## Assessment of your 10 suspected violations

Severity scale used below:

* **Cosmetic**: naming/organization; doesn’t constrain future architecture
* **Structural**: interfaces/control-flow make the target materially harder
* **Philosophical**: the system’s invariants are opposite to the principles; must invert data/control flow

### Violation 1: Sequential pipeline vs iterative per-slice loop

**Is it a violation?** Yes.

**Severity:** **Structural → Philosophical**, depending on how entrenched the phase interfaces are.
Even if TODOs acknowledge the gap, the current architecture *bakes in* “one pass over the repo” assumptions.

**Why it violates the philosophy:**

* **Principle 9 (constant iteration):** a single pipeline encourages “analyze everything then act” rather than baby steps.
* **Principle 5 (always knows target):** the pipeline implies each phase must rediscover targets globally.
* **Target model conflict:** P1–P10 are supposed to be *tools* invoked as needed per slice; current design makes them *stages*.

**Correct design:**
A **PromotionLoop** that operates per slice/worktree:

```text
while gaps remain:
  slice = GapQueue.next()
  ctx   = WorkspaceManager.checkout(slice)

  # tools invoked opportunistically, not obligatorily
  gaps  = gap_exploration(ctx)        # may call P3-like logic
  patch = implementation(ctx, gaps)   # agent edits
  questions = under_spec_check(ctx)   # block if needed
  facts = analyze(ctx)                # shared evidence artifacts
  pins/edges = promote(ctx, facts)    # LLM outputs + verification
  integrate(ctx)                      # CI per worktree
  verify(ctx)                         # cross-library, lineage checks
  power_alignment(ctx)                # drift detection
```

**Migration path (incremental):**

1. **Introduce a new runner** (don’t rewrite orchestrator yet): `promotion_loop.py` that runs on *one slice*.
2. Refactor existing phases into **pure functions** with explicit inputs/outputs (no global scanning).
3. Make `pdd_orchestrator.py` a **compatibility wrapper** that calls the loop once (or runs “batch mode”), then slowly retire it.
4. Add parallelism only after slices are truly isolated (worktrees + artifact boundaries).

---

### Violation 2: Pin creation is mechanical, not during LLM work

**Is it a violation?** Yes, in the current form.

**Severity:** **Philosophical**.

**Core misalignment:**

* Pins are the *currency of the system* (Principle 6).
  If they’re created by AST scanning, the graph becomes an afterthought derived from language-specific parsing—directly opposing **Principle 8/12**.
* Mechanical pin discovery also reintroduces the assumption that “atoms are extractable” (Principle 1 and 2 conflicts).

**Correct design:**
Pins should be **an explicit output of the same LLM call that makes promotion/implementation decisions**.

A good pattern is:

* Implementation agent returns:

  * a patch (diff)
  * **PinProposals** (what spans correspond to atoms/functions/events/stores)
  * **EdgeProposals** (calls/events/store usage)
  * **Evidence** (why these pins/edges are correct)
  * **Questions** (if under-spec)

Then a **verifier** checks:

* spans exist and anchors are stable
* pins cover changed spans (diff coverage)
* graph constraints (gates) hold

**Is mechanical scanning acceptable as verification?**
Yes **only as an optional backend** that:

* does not define truth (LLM output does)
* is not required for correctness
* can be swapped per language (plugin), not core

**Migration path:**

1. Extend promotion/implementation agent output schema to include pins/edges.
2. Add a `PinVerifier` that checks anchors/diff coverage (text-based, not AST).
3. Keep `pin_functions/orchestrator.py` temporarily as a **fallback pin suggester** for Python, but move it behind `PinDiscoveryBackend`.
4. Gradually flip default from AST backend → LLM backend.

---

### Violation 3: Compliance gates parse code instead of consuming graph data

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

**Why:**
Gates are supposed to validate artifacts of the promotion loop (pins/graph/evidence).
If every gate re-parses Python AST, the system’s real substrate becomes “Python syntax trees,” not “graph of pinned evidence.”

**Correct design: “Gates = graph queries + runtime checks”**
Examples using your own suggested mappings:

* **NO_REMAINING_COMMENTS** → query `facts.remaining_gap_pins == ∅`
* **NO_STUB_FUNCTIONS** → query `facts.stub_nodes == ∅`
* **CALL_GRAPH_CONNECTED** → query `AdjacencyGraph.connected(atom_nodes)`
* **STORE_MONOGAMY** → query `StoreGraph.owners(store).size == 1`
* **ALL_TESTS_PASS** → runtime test execution result (language/toolchain specific; that’s fine)

For architectural gates:

* Some are crisp graph properties (PIN_COVERAGE via diff coverage)
* Some are fuzzy (NO_INLINED_ATOM_LOGIC) and should be **LLM-evaluated** using pinned evidence + diff

**Migration path:**

1. Create a single run-scoped **EvidenceBundle** (facts + pins + edges + diff metadata).
2. Refactor gates to accept `EvidenceBundle` and become **pure queries**.
3. Keep AST gates only as **optional cross-checks** (and only as Python plugins).

---

### Violation 4: Graph extractors parse code instead of consuming LLM data

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

**Correct design:**
Edges should be produced either:

* **as a byproduct of implementation/promotion** (best alignment with Principle 8), or
* via **one explicit LLM “relationship analysis” call** that outputs all edge types in one schema (calls/events/stores/import-like dependencies)

What’s incorrect is “three independent mechanical extractors” that each rebuilds understanding.

**Migration path:**

1. Define one `RelationshipFacts` schema:

   * `calls: [(caller_pin, callee_pin, confidence, evidence_pin)]`
   * `events: [(emitter_pin, event_id, consumer_pin?)]`
   * `stores: [(pin, store_id, access_type)]`
2. Make the adjacency runner build the graph from these facts.
3. Deprecate AST extractors; keep as plugin verifier if desired.

---

### Violation 5: `collapse.py` does extraction

**Is it a violation?** Mostly yes.

**Severity:** **Structural → Philosophical**, depending on scope.

**Key nuance (brownfield ingestion):**
Brownfield ingestion *does* require learning structure from existing code.
But the philosophy’s version of that is **routing and pinning**, not extracting a rigid representation.

**Correct design for brownfield:**

* Treat the existing codebase as “raw text to be pinned.”
* Build **Layer 1 skeletons** by:

  * creating atoms as pinned spans
  * attaching summaries as routing hints
  * avoiding copying algorithmic logic into new spec docs

So collapse should be “ingestion router,” not AST classifier.

**Migration path:**

1. Replace AST classification with an LLM ingestion pass that outputs:

   * atom candidates
   * pin spans
   * relationship hints
2. Reuse Phase 0’s summarize→discover→route mechanics, but with code-as-input.

---

### Violation 6: Separate analysis modules duplicate understanding

**Is it a violation?** Yes.

**Severity:** **Structural → Philosophical**.

**Important distinction:**
Per-phase *separation of concerns* is fine.
Per-phase *re-parsing and re-extracting* is not.

**Correct design:**
A single canonical **FileFacts / EvidenceFacts** service that produces:

* structure hints (not language constructs)
* gap pins (TODO/spec comments/stubs)
* relationship edges (calls/events/stores/import-like)
* test identity hints
* anything else gates need

Then P1/P2/P3/P6/P7 become:

* either no-ops
* or thin views over the same evidence bundle

**Migration path:**

1. Make `core/code_analysis.py` the canonical “facts provider.”
2. Add a run-scoped cache keyed by file content hash / diff.
3. Rewrite other modules to consume those facts (or delete them).

---

### Violation 7: PinFunction schema references code, not graph

**Is it a violation?** **No** (as stated).

Pins are *supposed* to point to text locations. That’s the whole mechanism.

**What would be a real violation here:**
If downstream modules operate on *source code semantics* directly (e.g., AST nodes) instead of operating on the **pin graph + evidence**.

**Recommended improvement (not required by principles but helps in practice):**
Augment pins with **stable anchors**:

* `anchor_before`, `anchor_after` snippets
* `content_fingerprint` of the span
  This supports refactors without treating line numbers as truth.

---

### Violation 8: No demotion chain (gate failures skip atoms)

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

Skipping is the opposite of promotion/demotion convergence. It turns gates into “filter what passes” instead of “generate the next concrete work item.”

**Correct design:**
Gate failure must produce a **DemotionTicket** that becomes a concrete edit target in Layer 1:

* includes pins to failing evidence
* includes the constraint/spec that was missing
* enqueues into GapQueue

**Migration path:**

1. Create `DemotionTicket` schema: `{gate, failing_pins, recommended_spec_patch, questions}`.
2. Implement `DemotionManager.apply(ticket)` that:

   * writes the patch into the Layer 1 skeleton (or queues an intake routing item if truly new)
   * records lineage
3. Replace “skip atom” with “demote atom,” then loop.

---

### Violation 9: Planning module uses AST to parse code it should already understand

**Is it a violation?** Yes.

**Severity:** **Structural**.

Planning should be scheduling and constraint management over:

* GapQueue items
* pins/evidence
* workspace status
* lineage/drift signals

Not AST.

**Correct design:**
Planning consumes the same EvidenceBundle used by gates and promotion.
If it needs additional facts, it asks `code_analysis.py`, not a parser.

**Migration path:**

1. Remove AST dependence from `planning/workflow.py` by swapping in `FileTranslationState` / EvidenceBundle.
2. Delete or convert `planning/code_parser.py` to a thin adapter over `code_analysis.py` (if legacy callers exist).

---

### Violation 10: Data flow direction (code→analysis→graph→decisions vs decisions→graph→verification)

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

The philosophy requires: the LLM is the pattern recognizer and the thing doing the task; the graph is the artifact of that work. Mechanical steps verify, not define.

**Correct data flow:**

```text
code/diff
  → LLM (implements + emits pins/edges/evidence/questions)
  → Graph store (PinRegistry + AdjacencyGraph + lineage)
  → Gates verify (graph queries + runtime tests + anchor checks)
  → if fail: demote (write constraints into L1), loop
```

**Migration path:**

1. Require LLM outputs structured pins/edges with evidence.
2. Make graph construction depend on LLM output, not AST.
3. Keep AST tools only as validators until confidence is sufficient.

---

## Violations you likely missed

### A) Phase 0 is “clean” but may be *misplaced* in the global pipeline

If `pdd_orchestrator.py` runs P0 every time regardless of trigger, that violates:

* **Principle 5:** you already know what to edit when change originates from demotion/gates
* **Principle 12:** redundant routing/discovery step
* Target architecture statement: “Routing only at the bottom layer.”

**Fix:** Make Phase 0 a *conditional entrypoint* used only for external intake (new prose requirements / demoted algorithm descriptions / genuinely new constraints). Otherwise bypass it.

---

### B) `pdd_lifecycle.py` stages (“Architecture” and “Code Quality”) risk direct-edit workflows

A separate “Architecture phase where agent proposes candidates” and “Code quality reviewers” often implies:

* discovering targets instead of using demotion tickets
* proposing direct edits to L2/L3 instead of promoting from L1 constraints

That conflicts with:

* **Principle 4 (promotion, not direct editing)**
* Target layering: architecture emerges from promotion, not a standalone stage

**Fix:** Convert these stages into **reviewers that only emit DemotionTickets**, not patches.

---

### C) Two sources of truth risk: extracted “atoms/graphs” vs “code-as-spec”

If AtomDescriptor/PinProjection become authoritative objects that downstream trusts more than pins + code, you’ve created an implicit separate spec layer.

This violates **Principle 3** even if code is still present.

**Fix:** Ensure every derived object is either:

* a view over pins/graph, or
* a cached “fact” that is always tied to evidence pins and invalidated by diffs

---

### D) Rigid type system may encode language assumptions

Even if you avoid AST, types like `Function`, `Class`, `Decorator`, `ImportGraph` can violate **Principle 7** if treated as mandatory structure.

**Fix:** Use typed wrappers only for *your own invariants* (pins, edges, gates), not for language constructs. Keep “what exists in the code” as dynamic facts emitted by LLM.

---

### E) “Block on ambiguity” may be unimplemented in a way that causes silent guessing

The presence of an under-spec step in the target loop is not enough; the architecture must support a hard stop.

Common failure mode: under-spec becomes “best effort” and gates become “skip.”

**Fix:** Under-spec must emit questions that become an explicit “waiting for constraints” state; no promotion continues until resolved.

---

## Parts that are well-designed and should not change (conceptually)

Based on what you described, these align with the philosophy and should be preserved:

* **Phase 0 intake routing pipeline** (summarize → discover → route spans → coverage check → assemble)
  This is the strongest alignment with Principles 1/2/10/12.
* **AdjacencyGraph (typed weighted directed graph)**
  This matches Principle 6—keep it as the core substrate.
* **PinRegistry** (forward/backward trace, drift detection)
  This is essential; it’s the ledger for evidence.
* **GapQueue** (aggregation + stagnation detection)
  This supports iterative convergence.
* **WorkspaceManager** (run-scoped workspace)
  Needed for per-slice loop.
* **core/code_analysis.py + edit_in_place.py (LLM-based, language-agnostic)**
  These are the nucleus of the correct architecture.
* **refinement_engine/detector.py (graph-based coupling/cohesion)**
  This is what later phases should look like.

---

## Is the overall architecture correct in concept?

Yes—with one condition:

* **Pins + graph must be the first-class artifact produced by LLM work**, not an artifact reconstructed from syntax.

The conceptual stack (Layer 1 code-as-spec → Layer 2 architecture via pins → Layer 3 clean code) matches the philosophy. The current implementation flips the causal arrow (syntax extraction first), which is why it feels misaligned.

---

## Priority order for fixing (what blocks what)

1. **Introduce the iterative per-slice PromotionLoop** (even if it still calls legacy phases internally).
   Without this, demotion and constant iteration can’t exist.
2. **Create the canonical EvidenceBundle** (facts + pins + edges + diff + provenance) produced once per slice.
   This is the prerequisite for removing redundant per-phase parsing.
3. **Move pin + edge creation into the LLM task outputs** (promotion/implementation).
   This inverts the data flow; AST becomes optional verification.
4. **Refactor gates to consume EvidenceBundle (graph queries + runtime results)**.
   This removes the AST-centric substrate.
5. **Implement full demotion chain** (gate failure → DemotionTicket → Layer 1 patch → GapQueue).
   This flips “skip” into “converge.”
6. **Make Phase 0 conditional** (external intake only).
7. **Delete/convert redundant analyzers and planning parsers**.

---

## Disposition for the AST-based modules

Legend:

* **Delete**: functionality becomes unnecessary in the PDD model
* **Rewire**: keep module, but make it consume EvidenceBundle/graph/pins (no parsing)
* **Convert**: keep module, but replace AST/tokenize with `code_analysis.py` (LLM facts)
* **Left alone**: acceptable as runtime verification/plugin; not part of core truth

> Note: I’m classifying everything you listed (it’s more than 25). If you want exactly the 25 from your LANGUAGE_AGNOSTIC catalog, this mapping still applies; just filter to that set.

### Phase 1–2

| Module                    | Current role                       | Disposition                                   | Why                                                                                                         |
| ------------------------- | ---------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `planning/code_parser.py` | AST structure parsing              | **Delete** (or **Convert** if legacy callers) | A “parser” is not a first-class concept; planning should consume EvidenceBundle.                            |
| `planning/reverser.py`    | AST boundaries + reverse-translate | **Delete**                                    | Reverse-translation implies a separate spec layer; ingestion should be routing/pinning, not reconstruction. |

### Phase 3 detection

| Module                                      | Current role                  | Disposition                          | Why                                                                                                    |
| ------------------------------------------- | ----------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `compliance/detection/comment_scanner.py`   | tokenize comment extraction   | **Delete**                           | “Find comments” is gap exploration; should be emitted as gap pins by LLM during real work.             |
| `compliance/detection/stub_scanner.py`      | AST stub detection            | **Delete**                           | Same: stub detection is a fact in EvidenceBundle, not a standalone parser.                             |
| `compliance/detection/runtime_detector.py`  | Python runtime probes         | **Left alone** (plugin)              | Runtime verification is fine, but must not be core truth or required for language-agnostic behavior.   |
| `compliance/detection/call_graph.py`        | AST call graph for compliance | **Rewire**                           | Compliance should query AdjacencyGraph / RelationshipFacts, not rebuild it.                            |
| `compliance/detection/coverage_analyzer.py` | AST + coverage.py mapping     | **Rewire** (keep coverage, drop AST) | If you keep coverage at all, map coverage to pins/diffs, not AST constructs. Treat as optional plugin. |
| `compliance/detection/orchestrator.py`      | aggregates scanners           | **Rewire**                           | Should orchestrate EvidenceBundle creation + plugin verifiers, not AST scanners.                       |

### Phase 4

| Module                 | Current role                | Disposition | Why                                                                                                  |
| ---------------------- | --------------------------- | ----------- | ---------------------------------------------------------------------------------------------------- |
| `branches/collapse.py` | AST codebase classification | **Convert** | Ingestion classification can be LLM-based, but output must be pins/routes, not extracted constructs. |

### Phase 5 pin & promotion

| Module                                          | Current role                                 | Disposition                                      | Why                                                                                                 |
| ----------------------------------------------- | -------------------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `pin_functions/orchestrator.py`                 | AST scan atoms + import graph to create pins | **Rewire**                                       | Pins should come from LLM outputs; this becomes a verifier/normalizer over pin proposals.           |
| `compliance/promotion/algorithmic_gates.py`     | 5 gates via AST                              | **Rewire**                                       | Gates must be graph queries + runtime checks over EvidenceBundle.                                   |
| `compliance/promotion/architectural_quality.py` | AST-based quality                            | **Convert**                                      | Architectural quality is fuzzy; use LLM evaluation over pinned evidence + diff.                     |
| `compliance/promotion/pin_coverage.py`          | AST pin coverage                             | **Rewire**                                       | Pin coverage is diff/span coverage; no AST needed.                                                  |
| `compliance/promotion/introduction_checker.py`  | AST intro checks                             | **Convert** (or **Rewire** if purely graph rule) | If “introduced algorithms/specs” is semantic, it’s LLM. If it’s a graph invariant, rewire to graph. |

### Phase 6 adjacency

| Module                                         | Current role            | Disposition | Why                                                     |
| ---------------------------------------------- | ----------------------- | ----------- | ------------------------------------------------------- |
| `analysis/adjacency/extractors/call_graph.py`  | AST calls               | **Rewire**  | Read RelationshipFacts emitted by LLM, then add edges.  |
| `analysis/adjacency/extractors/event_graph.py` | AST events              | **Rewire**  | Same.                                                   |
| `analysis/adjacency/extractors/store_graph.py` | AST stores              | **Rewire**  | Same.                                                   |
| `analysis/adjacency/runner.py`                 | orchestrates extractors | **Rewire**  | Becomes “merge relationship facts into AdjacencyGraph.” |

### Phase 7 projection/lineage and analysis utilities

| Module                                     | Current role            | Disposition                                 | Why                                                                              |
| ------------------------------------------ | ----------------------- | ------------------------------------------- | -------------------------------------------------------------------------------- |
| `projection/lineage/import_graph.py`       | AST imports             | **Rewire**                                  | Imports are just one dependency edge type; should come from RelationshipFacts.   |
| `projection/lineage/builder.py`            | AST patterns/decorators | **Convert**                                 | Pattern recognition is LLM territory; don’t encode Python constructs.            |
| `projection/lineage/test_pin_baseline.py`  | AST test signatures     | **Convert**                                 | Tests should be identified via LLM facts and/or runtime discovery; map to pins.  |
| `projection/lineage/test_pin_discovery.py` | AST test→pin mapping    | **Convert**                                 | This is semantic mapping; LLM + coverage (optional) beats AST.                   |
| `analysis/import_graph.py`                 | AST imports             | **Delete** (duplicate)                      | Consolidate import dependency into one relationship pipeline.                    |
| `analysis/import_scanner.py`               | AST import hits         | **Delete**                                  | Redundant once you have RelationshipFacts + pins.                                |
| `analysis/projection_classifier.py`        | AST projection types    | **Convert**                                 | Classification should be LLM-based (language-agnostic).                          |
| `analysis/data_flow.py`                    | AST data flow           | **Convert** (or **Delete** if nonessential) | If you truly need dataflow, it must be LLM-based; AST dataflow won’t generalize. |

---

## Direct answers to your embedded questions

* **(V1) “Is sequential architecture just not yet implemented, or does it make target harder?”**
  It makes the target harder because it encourages global discovery, global artifacts, and “stage outputs,” which fight per-slice iteration and demotion. Even if rewiring is possible, the architecture is currently training every module to assume pipeline semantics.

* **(V2) “Should pin creation happen inside the agent workflow?”**
  Yes. Pin creation is part of promotion decisions. Mechanical scanning is acceptable only as optional verification or bootstrapping, not as the source of truth.

* **(V3) “Should gates operate on data produced by prior phases?”**
  Yes, but not “prior phases” in the pipeline sense—on the **single EvidenceBundle** produced per slice. Gates should never re-parse source to re-learn facts that already exist.

* **(V4) “Should graph edges be byproduct of LLM work or single LLM call?”**
  Prefer byproduct of the implementation/promotion agent (best alignment). A single relationship-analysis call is acceptable as long as it emits edges and evidence; don’t split into multiple mechanical extractors.

* **(V5) “Is brownfield ingestion an exception to no-extraction?”**
  Brownfield ingestion can involve summarization and classification, but the output should be **routing + pins**, not extracted structured representations that become an alternate spec.

* **(V6) “One comprehensive LLM analysis per file?”**
  Yes as a conceptual model: one canonical facts provider per file/diff. Internally it can be multiple calls, but downstream must see **one shared evidence artifact**, not a parade of redundant parsers.

* **(V7) “Is pin schema referencing code a violation?”**
  No. Pins are pointers. The violation is *how they’re populated and used*.

* **(V8) “Is lack of demotion just not yet implemented or structurally hard?”**
  It’s structurally hard in the current pipeline because “skip” is the natural failure path. You need explicit DemotionTickets + Layer1 patching to make demotion the default behavior.

* **(V9) “Should planning consume FileTranslationState instead of having its own parser?”**
  Yes. Planning should be a consumer of the same evidence/pins used everywhere else.

* **(V10) “Should primary data flow be reversed?”**
  Yes: LLM produces graph/evidence as it works; mechanical steps verify. You still read code text as input, but you don’t treat syntax extraction as the system’s understanding.

---

If you want the next step to be maximally actionable: I can write a concrete target “interfaces and artifacts” spec (schemas for EvidenceBundle, RelationshipFacts, PinProposals, DemotionTickets, GateResults) that you can implement incrementally while keeping the current system runnable.

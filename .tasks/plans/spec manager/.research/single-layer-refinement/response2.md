## 1) Existing capability assessment: what the current call graph can already tell you

### What `build_call_graph()` actually produces (today)

From `compliance/promotion/call_graph.py` + `core/code_analysis.py`:

* **Per-file only**: it loops file-by-file and calls `infer_adjacency_signals(...)` on a single file’s text. It does not load or provide other files as context.
* **Edges are CALL-only**: `build_call_graph()` requests `{"CALL"}` and discards non-CALL signals.
* **Nodes are function spans** discovered by `analyze_source()` (LLM structural scan).
* **Endpoints are not file-qualified** in this wrapper:

  * span `id` is `func.qualified_name or func.name`, not `"{file}:{qualified_name}"`.
  * so two files can collide if they both contain the same qualified/name string.
* Each edge includes:

  * `caller`, `callee`
  * `confidence`
  * `evidence` that includes `source_file` and an LLM-provided `rationale_span` / `raw_evidence`.

### What this tells you about algorithms (from CALL edges alone)

What you can get *without inventing new extraction*:

* **Connectivity / neighborhood**:

  * for a function `f`, you can get its direct callers/callees (within the file) and a small k-hop neighborhood.
  * this is enough to identify “likely impacted” code when `f` changes.
* **Rough clustering inside a file**:

  * connected components (or dense neighborhoods) often correspond to “one coherent feature” *if* the file is feature-scoped.
  * this is a **hint**, not a guarantee: shared helpers and utilities will be pulled into multiple clusters.
* **Entry-ish / leaf-ish functions (within a file)**:

  * functions with no in-edges (within the file) tend to be entrypoints *for that file’s subgraph*.
  * leaves tend to be helpers.
  * this is useful for routing “where to attach behavior” inside a file.

What you **cannot** determine reliably from CALL edges alone:

* **Algorithm boundaries** with any guarantee:

  * CALL edges do not tell you whether a callee is “part of the algorithm” vs “shared utility” vs “plumbing”.
* **Business-rule vs wiring intent**:

  * the graph cannot distinguish “called because of a business rule” vs “called because of architecture wiring”.
  * you can sometimes *guess* from names (`handler`, `middleware`, `router`) but that’s heuristic and non-authoritative.
* **Communication paths that are not expressed as direct calls**:

  * event subscription tables, DI containers, middleware order configured in lists, reflection, framework callbacks, config-driven routing, queues/schedulers.
  * these are exactly the places pins tended to matter.
* **Any “must happen before/after” semantics**:

  * CALL edges don’t encode ordering or conditionality (branching, retries, async, “only on success”).
* **Cross-component boundaries** unless you already have explicit component ownership metadata elsewhere.

### Cross-file call graph: is it possible with existing infrastructure?

With **only** the current call-graph wrapper as written: **no** (not as a real graph).

* `infer_adjacency_signals()` sees one file, so it cannot *resolve* that `risk_engine.check_exposure()` is defined in `risk_engine.py` unless the model guesses and emits a stable identifier.
* `build_call_graph()` does not attempt any resolution step; it accepts whatever strings the LLM emits as `caller/callee`.
* Because span ids aren’t file-qualified in this wrapper, even “best effort” cross-file aggregation is collision-prone.

What is possible *without building a new system*:

* **Cross-file routing by deterministic search** (not “call graph extraction”):

  * use the call graph to get the callee name string (hint), then `ripgrep`/search the repo for that name to find definitions/usages.
  * this is crude, but it’s deterministic and works as a routing fallback.
* If you already have a deterministic import scanner (as stated), you can use it to narrow candidates, but that’s outside `build_call_graph()` today.

---

## 2) Can the existing call graph serve as a routing map?

### What it can cover well (PIN replacement surface that is actually covered)

The call graph is good for **change propagation inside code that is actually connected by calls**:

* **“If function X changes, what else is affected?”**

  * immediate callers need updates if signature/contract changed
  * immediate callees may need updates if behavior expectations changed
  * a bounded k-hop neighborhood catches most “local algorithm ripple”
* **“Where should I add the next TODO?”**

  * if a reviewer says “you must validate currency code before persisting”, and you know which function implements persistence, the call graph can route you to the callsite where validation must be inserted.

This covers the core “atom-to-usage” benefit of pins **when the usage is a callsite**.

### What falls through (routing cases the call graph does not cover)

These are the cases pins helped with and CALL edges won’t:

* **Framework wiring** (routes, handlers, middleware chains, lifecycle hooks)
* **Eventing** (publish/subscribe where handlers aren’t called directly)
* **DI/config binding** (a class used because it’s registered, not called)
* **Cross-process boundaries** (queues, RPC, cron jobs)
* **Dynamic dispatch/reflection**

If you retire pins, you need *some other* way to route TODOs in these areas. The simplest is not “richer extraction”; it’s **explicit anchors** (see PIN retirement section).

---

## 3) Single-layer phase mechanism: one codebase, simple iteration

Single-layer does not require a new state machine. It requires removing **layer promotion** and running **phases against the same working tree**.

### Minimal mechanism (conceptual)

Repeat until convergence:

1. **Phase A — Build**

   * Implement whatever TODO/spec notes exist in code.
   * Update tests.
   * Remove/resolve the TODO/spec notes you satisfied.

2. **Phase B — Algorithm refinement (routing-only)**

   * Re-run call graph on changed files (as a hint map).
   * If an algorithm change likely impacts neighbors, add *new TODO/spec notes* to the impacted functions/callsites.
   * Do **not** “fix” logic here; only route.

3. **Phase C — Architecture refinement (routing-only)**

   * Read the spec’s communication-path statements (see section 5).
   * Locate the boundary/orchestrator functions where those paths should be realized (usually explicit in code structure + component boundaries; call graph is only a helper).
   * Add TODO/spec notes where wiring is missing/unclear.
   * Do not invent structure here; only route.

4. **Phase D — Code quality refinement (routing-only)**

   * Add refactor TODOs (naming, clarity, duplication) if needed.
   * Refactor TODOs must be explicitly marked “refactor-only”.

Then loop back to Phase A.

### What each phase produces/consumes (simple, concrete)

* **Phase A consumes**: TODO/spec notes already present in code.
* **Phase A produces**: code changes + tests + fewer TODO/spec notes.
* **Phases B/C/D consume**: code + spec text + (optional) call graph as a map.
* **Phases B/C/D produce**: *more TODO/spec notes* at specific locations.

### Phase interference prevention (without new machinery)

Keep it procedural and deterministic:

* **Ordering rule**: do not run Phase C/D meaningfully until Phase A has cleared behavior TODOs and tests pass.
* If Phase C/D adds TODOs, Phase A runs again; nothing else “interferes” because only Phase A performs substantive edits.

### Termination condition (deterministic)

Stop when:

* **No TODO/spec notes remain** (deterministically detectable marker; see next section), and
* **Tests pass**.

Everything else (call-graph shape, reviewer opinions) is routing input, not authority.

---

## 4) TODO-routing mechanism: what the “notes” are and how you place them

### What a “note” should be (minimal, deterministic)

Use a **single, explicit marker format** that is detectable by literal search (deterministic), e.g.:

* `# PDD-TODO[behavior]: <text>`
* `# PDD-TODO[wiring]: <text>`
* `# PDD-TODO[refactor]: <text>`

That keeps “TODO presence” authoritative without relying on LLM comment extraction.

You can still *also* run the existing comment-gap extraction, but it must be treated as a hint unless you accept it as authoritative.

### Where to put the note (mechanical routing using the call graph map)

Given an algorithm change anchored at function `F`:

1. **Always attach the primary TODO to `F`** (the changed spec comment already does this in L1 style).
2. Use the call graph (within-file) to compute:

   * **Callers(F)**: functions that call `F`
   * **Callees(F)**: functions that `F` calls
3. Add secondary TODOs:

   * to **Callers(F)** if the change affects inputs/outputs/ordering (“update callsite to pass currency”, “handle new error result”)
   * to **Callees(F)** if the change affects expectations downstream (“callee must enforce stronger validation”)
4. Bound the propagation:

   * default: 1-hop neighborhood
   * 2-hop only when the change is declared “contract-level” (signature/return shape), otherwise you get TODO spam.

### What if the impacted callsites are in other files?

Do not invent cross-file extraction. Use deterministic fallback:

* repo search for `F` (or its qualified name string) to find external callsites/definitions, then attach TODO at those callsites.

If search yields multiple plausible targets and you can’t decide:

* **block on ambiguity** (ask), or
* attach a TODO at the *callsite you found* saying “resolve which definition is intended”.

### How this interacts with the existing spec comment system

Yes: in a single-layer system, TODO-routing can be as simple as:

* “Phase B/C/D produce *new spec comments* (or PDD-TODO comments) at routed locations.”
* “Phase A implements and deletes them.”

No new work-item system is required if comment markers already drive L1.

---

## 5) “Algorithms describe communication paths abstractly”: what that means operationally

### What an algorithm-described communication path looks like

It lives in the **spec/algorithm text**, not in extracted code structure.

Example (abstract, non-architectural):

* “On successful settlement, the risk engine must be notified of the completed settlement.”

This is *not*:

* “Publish `SettlementCompleted` on Kafka topic X and consume in service Y.”

### Where that information lives in the system

Single-layer, simplest placement:

* The spec statement is routed into code as a TODO/spec note on the **boundary/orchestrator function** that owns the lifecycle:

  * e.g., `process_settlement()` or `SettlementService.complete()`

So the “path” is described **at the point of responsibility**, not extracted from call edges.

### Where constraints come from, and how they apply

Constraints originate in the logical algorithm/spec, for example:

* “Must happen before returning success”
* “Must happen exactly once”
* “Must not happen if validation fails”

How they are expressed:

* As additional spec notes and/or explicit test requirements.

How they are checked:

* **By tests** (unit/integration), and/or deterministic receipts that are already part of your governance model.
* Not by extracted graph properties.

Call graph’s role here:

* only to help find the boundary function and its neighbors where wiring/code changes must be inserted.

---

## 6) PIN retirement assessment: can you actually retire them?

### What pins were bridging

Pins existed because the system had **separate algorithmic and architectural layers** and needed a durable mapping:

* “atom function” → “architectural location”

In a single-layer codebase:

* there is no separate architectural layer artifact that needs to “consume” atoms via projections.
* the “architectural location” is just *the callsite in code*.

So the primary reason for pins disappears.

### When you can retire pins cleanly

Pins can be retired if:

* Most “architecture” is expressed as ordinary function calls in code, and
* You accept that routing is:

  * call graph (local) + deterministic search (global) + component boundaries

This gives you “where is this used?” without maintaining a registry.

### The hard remainder (where pins gave you leverage)

Pins helped especially where “usage” isn’t a call:

* event subscriptions
* middleware ordering
* DI wiring
* framework registration

If you remove pins and also refuse richer extraction, the **minimum viable bridge** is:

* **Explicit anchors in code** for those wiring points, tied directly to spec paths.

  * e.g., `# PDD-PATH: SETTLEMENT_COMPLETE_NOTIFIES_RISK_ENGINE`
  * placed exactly where the wiring is realized (handler registration, middleware chain, event publish site)

This is not a pin system:

* no registry
* no projection types
* no drift engine
* no tracing across layers

It is simply a deterministic “signpost” so routing can find the right place without guessing.

If you refuse even explicit anchors, then routing those cases becomes “block and ask” frequently.

---

## 7) Extraction boundary: what’s acceptable “understanding” vs unacceptable authoritative extraction

### Treat call graph output as: routing hints only

Because `infer_adjacency_signals()` is LLM inference, its edges are:

* non-deterministic
* potentially incomplete
* potentially wrong

Therefore:

* use it to propose *where to place TODOs*
* do not use it to decide “done” / “not done”

### Deterministic authority set (minimal)

If you want correctness guarantees under the stated rules, gate on:

* **Tests passing** (deterministic)
* **No remaining PDD-TODO markers** (deterministic literal search)
* **File content hashes / diffs** (deterministic)
* **Deterministic parsing of controlled formats** (agent prompts, manifests)

Everything else (call graph, reviewer outputs) is input to routing, not convergence authority.

Implication:

* the existing `CALL_GRAPH_CONNECTED` style gate should be treated as a **routing alarm** (“likely missing wiring; add TODOs”) rather than a hard correctness gate, unless you can validate its claims deterministically (usually: via tests).

---

## 8) Net simplification inventory: eliminated vs introduced (must be dramatic)

### Eliminated (direct machinery removal)

* **Three-layer pipeline orchestration** (`orchestration/pdd_lifecycle.py` and all L1→L2→L3 transition machinery)
* **Layer-aware dispatch matrix** in PromotionLoop (layer × mode step dispatch, layer-specific behaviors)
* **PIN system**:

  * `schemas/pin_functions.py`
  * `core/pin_registry.py`
  * `branches/pins.py`
* **Pin tracing / downward flow** machinery used to demote and re-promote across layers (the whole “trace pin back down” concept)
* **Cross-layer promotion risk surface** (atoms extracted → projected → assembled)

### Introduced (minimal, shorter list)

* **One explicit TODO marker format** (`PDD-TODO[...]`) so TODO presence is deterministically checkable.
* **A routing rule**: “when something changes, add TODOs to the 1-hop call neighborhood + deterministic search hits.”
* (Optional, only if needed for non-call wiring) **Explicit path anchor comments** (`PDD-PATH: ...`) at wiring points.

That’s it. No new graph schemas, no new drift systems, no new “projection types renamed”.

---

### Summary answers to the refined questions

* **Q1 (existing call graph capability)**: good for local adjacency + routing hints; not sufficient to infer algorithm boundaries or structural vs logical meaning; not cross-file-resolving.
* **Q2 (routing map)**: yes for callsite-based propagation; no for non-call wiring without explicit anchors.
* **Q3 (single-layer phases)**: simple loop where only Build edits behavior; refiners only add TODO notes; terminate on tests + no TODO markers.
* **Q4 (TODO routing)**: deterministic TODO marker comments placed at function definitions/callsites chosen via 1-hop call graph + deterministic search.
* **Q5 (paths + constraints)**: paths/constraints originate in spec, are routed into code as TODOs, and validated by tests—not by extracted graphs.
* **Q6 (pins)**: retire pins if you accept callsite routing + explicit anchors for non-call wiring; otherwise you need *some* minimal bridge.
* **Q7 (extraction boundary)**: call graph is non-authoritative hint; only deterministic checks gate convergence.
* **Q8 (simplification)**: large removal of layer+pin machinery; minimal addition of TODO marker convention and routing rule.

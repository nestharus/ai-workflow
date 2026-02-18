# Research Refinement: Single-Layer Iterative Refinement

## Why This Refinement Exists

The original research prompt (prompt.md) asked whether the existing call
graph extractor could help us understand algorithms well enough to route
work via a single layer, retiring PINs and the three-layer promotion
pipeline. The response (response.md) reclassified that problem into a
different one and solved the wrong thing. This refinement redirects the
research back to the original intent.

---

## What the Original Prompt Actually Asked

The original prompt asked a chain of connected questions:

1. **Can the EXISTING call graph extractor understand algorithms?**
   Not "what new system do we need to build" — can what we already have
   (`build_call_graph()` + `infer_adjacency_signals()`) give us enough
   understanding of algorithms to work with?

2. **Can that understanding, combined with existing component boundaries,
   replace the need for PINs?** Not "build a PIN replacement system" —
   can we just NOT NEED PINs because the call graph gives us enough
   understanding to route work directly?

3. **Can we operate on a single layer with phases instead of layers?**
   Phases refine the same codebase iteratively. No cross-layer promotion.
   No worktree hierarchy per layer. Just one codebase, refined in passes.

4. **The mechanism is TODO-routing**: "extract a call graph and map it
   to our code and add notes to our code in the right places as todo
   when we update algorithms." The call graph is a MAP. You use the map
   to find WHERE to add TODOs. That's the routing mechanism.

5. **Algorithms describe communication paths abstractly**: "algorithms
   can denote communication paths without including structure and then
   those communication paths can have constraints applied to them based
   on the logical algorithm." Constraints come FROM the spec/algorithms,
   not from code extraction. Communication paths are described by
   algorithms, not extracted from code.

6. **Extraction must be deterministic only**: "only does extraction
   where extraction is deterministic like languages." Non-deterministic
   extraction is not acceptable. Agent prompt extraction is deterministic
   because controlled format — if extraction fails, the prompt is broken.

---

## How the Response Diverged

The response reclassified the problem from:

> "Can the existing call graph help us understand algorithms well enough
> to route work, so we can simplify to one layer?"

to:

> "How do I build a rich enough graph extraction system to replace PINs?"

This is a fundamentally different problem. Here is specifically what
went wrong:

### Divergence 1: Designed a new system instead of evaluating the existing one

The prompt asked "can the EXISTING call graph extractor understand
algorithms?" The response never answered this. Instead it designed an
entirely new system: cross-file resolution pipeline, edge role
classification, algorithm boundary detection, graph fingerprints,
GraphConstraint schema. It skipped the actual question.

### Divergence 2: Added non-deterministic extraction

The prompt said "only does extraction where extraction is deterministic."
The response added:
- LLM-based edge role classification (LOGICAL/STRUCTURAL/BOTH/UNKNOWN)
- LLM-based algorithm boundary detection via clustering + LLM naming
- LLM-based cross-file resolution via token matching + LLM resolver
- LLM-inferred fingerprints for convergence authority

All of these are non-deterministic extraction. The prompt explicitly
prohibited this.

### Divergence 3: Made the graph the authority instead of a routing aid

The prompt described the call graph as a MAP: "extract a call graph and
map it to our code and add notes to our code in the right places." The
call graph tells you WHERE — then you ADD A TODO there. It's a routing
aid.

The response made the graph the operational authority for gating,
convergence, drift detection, and constraint checking. The graph became
the system's source of truth rather than a read-only map for routing.

### Divergence 4: Designed more machinery instead of less

The prompt's goal was dramatic simplification: retire PINs, remove layers,
remove cross-layer promotion. The response introduced MORE concepts than
it eliminated:

**Eliminated**: PinFunction, ImportEdge, ProjectionType, PinRegistryIndex,
layer-aware dispatch

**Introduced**: Annotated adjacency graph, cross-file resolution pipeline,
edge role annotations, projection_type annotations (same as PIN
ProjectionType renamed), algorithm groups, graph fingerprints, graph
constraints, graph diff/drift model, monotonic checkpoints

The introduced set is larger than the eliminated set.

### Divergence 5: Ignored the constraint application model

The prompt said: "algorithms can denote communication paths without
including structure and then those communication paths can have
constraints applied to them based on the logical algorithm."

This means:
- Algorithms in the SPEC describe communication paths abstractly
- The logical algorithm (also in the spec) produces constraints
- Those constraints are applied TO the described paths
- Constraints originate in the spec, not from code extraction

The response designed constraints as GraphConstraint objects checked
against extracted graph edges — the constraints come from code extraction,
not from the spec. This inverts the flow described in the prompt.

### Divergence 6: PIN "retirement" is PIN renaming

The response claims to retire PINs but introduces `projection_type`
categories on structural edges (PASS_THROUGH, EVENT_BRIDGE,
MIDDLEWARE_WRAP, ROUTE_DISPATCH, IO_ADAPTER, REPO_ACCESS,
SCHEDULER_DISPATCH, CONFIG_BINDING). These are functionally identical
to PinFunction's ProjectionType enum. The concept survives under a
new name with a richer schema.

---

## Constraint Violations Found by Audit

A formal audit (Opus direction + Codex High2 execution) found 10
divergences against the design constraints (C00-C11, TRADEOFFS.md,
CORE_PATTERNS.md, LONG_TERM_GOALS.md design principles):

**3 CRITICAL:**
1. Extraction surface expansion — more extraction, not less (C01, DP#3)
2. Separate mechanical extraction pipeline — 4-5 standalone passes
   outside the task loop (DP#10)
3. LLM-inferred fingerprints as convergence authority — non-deterministic
   output treated as knowledge (C00, C03)

**7 SIGNIFICANT:**
4. Upfront schema commitment without evidence (C00)
5. Single graph as cross-cutting coupling surface (C04)
6. Mixed scopes in one representation (C05)
7. PIN renaming, not retirement (DP#7)
8. Derived work while source is moving (C02)
9. Identity scheme doesn't match canonical ID contract (C10)
10. Parallel truth representations during migration (C02)

### Detailed Audit Findings

**Divergence 1: Extraction Surface Expansion** (CRITICAL)
Response proposes replacing PIN projections with an annotated adjacency
graph requiring extraction of `edge_role`, `projection_type`, cross-file
tokens, and fingerprints. Conflicts with C01 "Route information, don't
extract it" — extractions are routing hints, not replacements for the
original. Also conflicts with Design Principle #3 "Routing over
extraction — avoids extraction wherever possible." The response makes
extracted graph annotations the operational authority for routing/gating,
expanding derived extraction work instead of minimizing it.

**Divergence 2: Separate Mechanical Extraction Pipeline** (CRITICAL)
Response proposes multi-step mechanical passes: per-file adjacency
inference, token detection, candidate resolver, edge-role classification,
algorithm boundary detection, fingerprint computation (response sections
3.2, 3.3, 3.5, 6). Conflicts with Design Principle #10 "LLM does work
during its actual task — there is no separate mechanical extraction
step." The response explicitly introduces multiple standalone
extraction/classification passes outside the task execution loop.

**Divergence 3: High-Detail Upfront Commitment Without Evidence** (SIGNIFICANT)
Response commits to full node/edge schemas, GraphConstraint schema,
fingerprint definitions, gate redefinitions, and 7-step migration plan
(response sections 3, 4, 6, 7, 9). Conflicts with C00 "Plan only as
far as current understanding reaches" and "Require evidence before
changing strategy." No comparative eval evidence is presented.

**Divergence 4: Single Graph as Cross-Cutting Coupling Surface** (SIGNIFICANT)
Response proposes "Use one unified graph type" consumed by all phases.
Conflicts with C04 "Give each agent only the context it needs." A single
universal graph schema becomes a shared dependency for algorithm,
architecture, quality, routing, and constraints, increasing coupling
surface and cross-phase sensitivity.

**Divergence 5: Mixed Scope Reasoning in One Representation** (SIGNIFICANT)
Same graph carries logical and structural edges (LOGICAL|STRUCTURAL|BOTH|
UNKNOWN) used for both algorithm and topology checks. Conflicts with C05
"Avoid mixing scopes in a single pass." Unit-level logical interpretation
and cross-boundary structural analysis are co-located in one model.

**Divergence 6: PIN Removal Keeps PIN Semantics Under New Name** (SIGNIFICANT)
Response claims "PIN system (entirely removable)" while adding
`projection_type` categories (PASS_THROUGH, EVENT_BRIDGE, etc.) to
structural edges — functionally identical to PinFunction ProjectionType.
Conflicts with Design Principle #7 "Pins as the bridge." The response
removes PIN modules but retains the same projection semantics as core
routing metadata: conceptual renaming, not retirement.

**Divergence 7: Convergence Authority Depends on LLM-Inferred Labels** (CRITICAL)
Fingerprints are called deterministic but include edges filtered by
LLM-inferred role/confidence; stability relies on thresholds/consensus.
Conflicts with C00 "Don't treat unverified output as knowledge" and C03
"Surface errors immediately, don't absorb them." Thresholding converts
uncertain inference into accepted state rather than immediate hard
failure at source.

**Divergence 8: Derived Architecture Work While Source Is Still Moving** (SIGNIFICANT)
One mutable codebase runs behavior/wiring/refactor phases with
architecture and refactor checkpoints in-loop. Conflicts with C02
"Don't invest in derived work while the source is changing."
Architecture/quality artifacts are continuously recomputed while
behavior-level code is still changing in the same branch.

**Divergence 9: Identity Scheme Does Not Match Canonical ID Contract** (SIGNIFICANT)
Response proposes `node_id = "{canonical_rel_path}:{qualified_name}"`
with name-based matching. Conflicts with C10 — IDs must be
typed-prefixed, single-authority allocated, validated. "Human-readable
names are labels, not identifiers." Path+name composite IDs are not
typed-prefix IDs from a single allocator.

**Divergence 10: Migration Keeps Parallel Truth Representations** (SIGNIFICANT)
Migration steps 0-2 keep pins and add annotated graph in parallel with
comparison reports; pin deletion deferred to step 6. Conflicts with C02
"Don't maintain parallel representations of the same truth." During most
of migration, pin edges and structural graph edges are concurrent
authorities for the same architectural truth.

---

## What We Actually Need Answered

### Q1: What can the existing call graph extractor already tell us?

The existing `build_call_graph()` processes files, extracts function
spans via `analyze_source()`, and infers CALL adjacency signals via
`infer_adjacency_signals()`. It produces `CallGraphEdge(caller, callee,
strategy, surface, confidence, evidence)`.

- What does this graph tell us about algorithms? Can we see which
  functions form coherent algorithms just from call relationships?
- What does it tell us about communication paths? Can we distinguish
  "function A calls function B because of a business rule" from
  "function A calls function B because of architectural wiring"?
- What are its limits? What CAN'T you determine from CALL edges alone?
- Is cross-file call graph possible with the existing infrastructure?
  `infer_adjacency_signals()` already works per-file. What would it
  take to link edges across files?

Do not design new systems. Evaluate what exists.

### Q2: Can the call graph serve as a routing map?

The prompt's mechanism is: call graph → map to code → add TODOs in the
right places.

- When an algorithm changes (a spec comment is updated, a function body
  needs rework), can the call graph tell you which OTHER functions are
  affected?
- Is this sufficient to replace PIN-based change propagation? PINs
  currently track "this atom function maps to this architectural
  location." Can "this function calls these other functions" serve the
  same routing purpose?
- What routing cases does the call graph NOT cover? What falls through?

### Q3: How does single-layer phase iteration actually work?

The prompt says: "still going through different phases but they wouldn't
be promoting through different layers." The current phases (Build → QA →
Architecture → Code Quality from simpler.md) are fine as concepts.

- How does a single-layer system iterate through phases on one codebase?
- What does Phase A (Build) produce that Phase B (Algorithm Refinement)
  consumes? What does Phase B produce that Phase C (Architecture
  Refinement) consumes?
- How do you prevent phases from interfering? If Phase C changes code
  structure, does Phase B need to re-run?
- What are the termination conditions?

The answer should be SIMPLE. The current system is complex because of
layer machinery. Single-layer should be simpler, not differently complex.

### Q4: What is the TODO-routing mechanism?

"Add notes to our code in the right places as todo when we update
algorithms."

- What does a "note" look like? Is it a code comment? A file annotation?
  A work item referencing a file location?
- How does the system decide WHERE to add the note? (The call graph
  tells you which functions are connected — but which connections matter
  for a given algorithm change?)
- How does this interact with the existing spec comment system? Spec
  comments on stub functions are already "TODOs" that the implementation
  phase fills in.
- Is this just: "when Phase B finds an algorithm issue, it adds a spec
  comment to the relevant function, and Phase A fills it in on the next
  iteration"?

### Q5: How do algorithms describe communication paths?

"Algorithms can denote communication paths without including structure."

- What does an algorithm-described communication path look like? Is it
  in the spec text? In the code? In the call graph?
- How is this different from a structural/architectural description?
- Where do constraints on communication paths come from? The prompt says
  "from the logical algorithm" — how are these constraints expressed?
- How are they checked? Against what?

This is the part of the prompt that the response most misunderstood.
The response designed constraints checked against extracted graph edges.
The prompt describes constraints that originate in algorithms/specs and
are applied to described paths.

### Q6: What happens to PINs — actually?

PINs bridge "what the algorithm does" (atoms/functions) to "where it
sits in the architecture" (services, events, middleware). The response
said you can replace this bridge with a richer graph. But the prompt
asked whether you can RETIRE the bridge — not replace it.

- In a single-layer system where there's no separate "algorithm layer"
  and "architecture layer," do you still need a bridge between them?
- If code IS the spec (PDD principle), and the code already contains
  both the algorithm and the architecture, what is the bridge bridging?
- Can the call graph provide enough understanding that you don't need
  explicit atom→architecture mapping at all?
- If some bridging IS still needed, what is the MINIMUM viable bridge?
  Not a rich graph — the simplest thing that works.

### Q7: Where is the extraction boundary?

"Only does extraction where extraction is deterministic like languages."

The call graph extractor uses LLM inference (`infer_adjacency_signals`).
Is this "extraction"?

The prompt seems to draw this line:
- **Understanding** (LLM reads code and tells you about it) = acceptable,
  because it's read-only insight used as a routing hint
- **Extraction** (creating new authoritative data from code) = only
  acceptable when deterministic
- **Deterministic extraction** (agent prompts, known file formats) =
  acceptable because failure = broken input

So the question is: is the call graph extractor producing routing hints
(acceptable) or authoritative data (must be deterministic)?

If it's a routing hint, it can be LLM-based and approximate.
If it's authoritative, it must be deterministic or not done.

How should the system treat call graph output? As hints for routing?
Or as authority for gating?

### Q8: What is the net simplification?

The entire motivation is simplification. If the single-layer approach
is not DRAMATICALLY simpler than the current three-layer approach, it's
not worth doing.

- List what gets eliminated (modules, concepts, code paths, machinery)
- List what gets introduced (new concepts, new mechanisms)
- The introduced list must be MUCH shorter than the eliminated list
- If it's not, the single-layer approach may not be worth it — and
  that's a valid answer

---

## Constraints on the Solution

All constraints from the original prompt still apply. Additionally:

1. **Evaluate existing tools first.** Do not design new systems until
   you've determined what the existing call graph extractor, component
   boundaries, and spec comment system can already do.

2. **Non-deterministic extraction is not acceptable as authority.** LLM
   inference can produce routing hints. It cannot produce authoritative
   data that gates/convergence depend on. Only deterministic properties
   (test results, spec comment presence, file content hashes) can be
   authority.

3. **Constraints come from specs/algorithms, not from code extraction.**
   When the prompt says "constraints applied to communication paths based
   on the logical algorithm," the constraints originate in the spec, not
   in extracted graph annotations.

4. **Simpler means LESS machinery, not different machinery.** If your
   answer introduces as many concepts as it eliminates, that's not
   simplification. The bar is dramatic reduction in moving parts.

5. **The call graph is a map, not an authority.** It helps you understand
   where things are and how they're connected. It routes you to the right
   place. It does not become the source of truth for convergence, drift,
   or gating.

6. **Do not commit to schemas without evidence.** If you need to propose
   data structures, keep them minimal and say what eval would validate
   them. Do not design detailed schemas for systems that haven't been
   proven to work.

---

## What the Response Got Right (Keep These)

1. **Phase-scoped authority is a good concept** — behavior work before
   wiring work before refactoring work. This preserves sequential
   stabilization without layers.

2. **Demotion → escalation reframing** — findings route to work items
   with stronger authority, not to lower layers. This is simpler.

3. **Progressive gating by aspect** — algorithm gates → architecture
   gates → quality gates preserves gate ordering value.

4. **Block on ambiguity for unknowns** — when classification is
   uncertain, block and ask. Don't guess.

5. **The hypothesis is plausible** — single-layer CAN be simpler. The
   problem was the mechanism, not the goal.

---

## Context Files

Same context.zip as the original prompt. response.md (the original
response being refined) is included — read it to understand what was
proposed so you can avoid the same mistakes.

---

## Deliverables

1. **Existing capability assessment** — what can the current call graph
   extractor already tell us about algorithms, communication paths, and
   routing? Be specific and honest about limits.

2. **Single-layer phase mechanism** — how phases iterate on one codebase.
   Must be SIMPLER than the current system, not differently complex.

3. **TODO-routing design** — how the system adds TODOs to code based on
   call graph understanding. The mechanical routing step.

4. **Algorithm-described communication paths** — what this means, how
   constraints from logical algorithms apply to them, where this
   information lives.

5. **PIN retirement assessment** — can PINs actually be retired? If yes,
   what provides the routing that PINs currently provide? If no, what is
   the minimum viable bridge?

6. **Extraction boundary** — where the line is between acceptable
   understanding (LLM reads and reports) and unacceptable extraction
   (creating authoritative data). How the call graph output should be
   treated.

7. **Net simplification inventory** — concrete list of what's eliminated
   vs introduced. Must show dramatic reduction.

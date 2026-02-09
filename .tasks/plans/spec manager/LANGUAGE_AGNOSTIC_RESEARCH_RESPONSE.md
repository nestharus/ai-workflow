## Target-state shift (what makes most AST modules disappear)

Treat **promotion** as a transaction that produces **two outputs at once**:

1. **Edited code** (Layer 1/2/3 files)
2. **Evidence artifacts** (language-agnostic metadata):

   * `GapInventory` (comment gaps, stub gaps, ambiguity gaps) as **spans**
   * `PinRegistry` updates (PinFunctions + PinProjections)
   * `AdjacencyGraph` updates (CALL / STORE_TOUCH / EVENT / REFERENCE edges)
   * file hashes to prove evidence matches current text

Then:

* Anything that “parses code to rediscover what the LLM just understood” becomes redundant.
* Compliance gates become **graph + evidence checks**, not syntax checks.
* Static “extractors” only exist as **optional on-demand LLM signal producers** (mainly for brownfield or missing evidence), not as routine mechanical steps.

---

## Module-by-module decision matrix (delete vs keep, and what replaces it)

Legend:

* **DELETE** = no place in target design (keep only a temporary shim if needed for incremental migration).
* **KEEP (Graph)** = becomes pure graph/pin algorithm, no code parsing.
* **KEEP (LLM)** = a real LLM task (pattern recognition / intent).
* **PLUGIN** = language/runtime-specific adapter behind an abstraction; not a core dependency.

| Module                                          |                      Target decision | What it becomes (language-agnostic)                                                         | Replacement mode        |
| ----------------------------------------------- | -----------------------------------: | ------------------------------------------------------------------------------------------- | ----------------------- |
| `planning/code_parser.py`                       |                           **DELETE** | Structure comes from `code_analysis.py` or promotion evidence; no separate “parser”         | A → then remove         |
| `planning/reverser.py`                          |                       **KEEP (LLM)** | Reverse-translate **spans** (functions/blocks) → intent comments/summaries                  | B                       |
| `compliance/detection/comment_scanner.py`       |                           **DELETE** | Fold into `gap_detection` (produce comment-gap spans)                                       | C (via GapInventory)    |
| `compliance/detection/stub_scanner.py`          |                           **DELETE** | Fold into `gap_detection` using `SourceAnalysis.functions[].is_stub`                        | C                       |
| `compliance/detection/runtime_detector.py`      |            **PLUGIN** (often delete) | Only via per-language runtime probe; never required for core gates                          | Plugin                  |
| `compliance/detection/coverage_analyzer.py`     |            **PLUGIN** (often delete) | Coverage is toolchain-specific; not a universal core step                                   | Plugin                  |
| `branches/gap_detection.py`                     |            **KEEP (Graph/Evidence)** | Canonical **GapInventory builder** (spans + reasons), using LLM classification where needed | A/B inside; outputs C   |
| `analysis/adjacency/extractors/call_graph.py`   |               **DEPRECATE → DELETE** | CALL edges come from promotion evidence; fallback: on-demand LLM signal extraction          | C primarily; B fallback |
| `analysis/adjacency/extractors/event_graph.py`  |               **DEPRECATE → DELETE** | EVENT edges come from promotion evidence; fallback: on-demand LLM signal extraction         | C primarily; B fallback |
| `analysis/adjacency/extractors/store_graph.py`  |               **DEPRECATE → DELETE** | STORE_TOUCH edges come from promotion evidence; fallback: on-demand LLM signal extraction   | C primarily; B fallback |
| `analysis/import_graph.py`                      |                           **DELETE** | Import relationships that matter are represented as **PinProjections / REFERENCE edges**    | C                       |
| `analysis/import_scanner.py`                    |                           **DELETE** | “Who uses pin X?” is a **PinRegistryIndex query**, not parsing                              | C                       |
| `analysis/data_flow.py`                         |  **DELETE (or optional LLM helper)** | If needed, make it an on-demand “explain IO contract” LLM query on a span                   | B (optional)            |
| `analysis/projection_classifier.py`             |                           **DELETE** | Projection type is chosen at creation (PinProjection), not inferred later                   | C                       |
| `compliance/detection/call_graph.py`            |                           **DELETE** | Connectivity uses existing `AdjacencyGraph` CALL edges                                      | C                       |
| `compliance/promotion/algorithmic_gates.py`     |                     **KEEP (Graph)** | Gates run on `GapInventory + AdjacencyGraph + PinRegistry + test results`                   | C                       |
| `compliance/promotion/architectural_quality.py` | **KEEP (Graph + text fingerprints)** | No AST similarity; use span fingerprints + pin registry; LLM only as tie-breaker            | C + (B tie-break)       |
| `compliance/promotion/pin_coverage.py`          |                     **KEEP (Graph)** | Coverage = span coverage via PinProjections/architecture nodes, not syntax                  | C                       |
| `compliance/promotion/introduction_checker.py`  |                  **KEEP (Evidence)** | INTRODUCTION nodes must have spec-comment spans (GapInventory / code_analysis)              | C (+A if needed)        |
| `projection/lineage/import_graph.py`            |                           **DELETE** | Lineage uses PinProjections + AdjacencyGraph edges                                          | C                       |
| `projection/lineage/builder.py`                 |                     **KEEP (Graph)** | Infer lineage purely from pin + adjacency relationships                                     | C                       |
| `projection/lineage/test_pin_baseline.py`       |                         **OPTIONAL** | Baseline = hash of **test spans** (via code_analysis), not AST                              | A (optional)            |
| `projection/lineage/test_pin_discovery.py`      |                **PLUGIN / OPTIONAL** | If you need “test → pin” mapping, do it via runtime instrumentation per language            | Plugin                  |
| `branches/collapse.py`                          |                       **KEEP (LLM)** | Brownfield → produce pins/graphs/gaps by **routing spans**, not parsing syntax              | B (+A for spans)        |
| `analysis/ast_extractor.py`                     |                           **DELETE** | Replaced by `code_analysis` + on-demand LLM signal extraction                               | A/B                     |

---

## Q1: Which modules should be deleted entirely?

### Delete in the target design (no conceptual need)

These exist mainly to **rediscover structure or relationships** after an LLM already had to understand the code to do its job:

* `planning/code_parser.py`
* `analysis/ast_extractor.py`
* `analysis/import_scanner.py`
* `analysis/import_graph.py`
* `analysis/projection_classifier.py`
* `compliance/detection/call_graph.py`
* `projection/lineage/import_graph.py`
* `compliance/detection/comment_scanner.py` (fold into `gap_detection`)
* `compliance/detection/stub_scanner.py` (fold into `gap_detection`)

### Remove from “core”; keep only behind abstractions if truly needed

These are inherently **language/toolchain-specific**, so they violate “language-agnostic” unless abstracted:

* `compliance/detection/runtime_detector.py`  → plugin
* `compliance/detection/coverage_analyzer.py` → plugin
* `projection/lineage/test_pin_discovery.py`  → plugin (if you still want it)

### Deprecate then delete

* `analysis/adjacency/extractors/{call_graph,event_graph,store_graph}.py`
  Target: edges are produced during promotion and stored; extractors become optional fallback.

---

## Q2: Which modules should become LLM-driven, and how?

### “Must be LLM” (real pattern recognition)

These are inherently semantic and should not be reconstructed mechanically:

1. **`planning/reverser.py`**

   * Input: `(file_path, line_start, line_end)` spans (usually PinFunctions or introduced architecture blocks).
   * Output: intent summary / pseudocode comments for review and constraint-surfacing.
   * No parsing beyond span selection.

2. **`branches/collapse.py` (brownfield ingestion)**

   * Input: repository snapshot (files + spans from `code_analysis`).
   * Output: routing plan:

     * which spans become PinFunctions
     * which files/blocks become slices/architecture nodes
     * initial Adjacency edges (CALL/STORE/EVENT) at coarse granularity
     * “ambiguity questions” that require human constraints

3. **Adjacency signal production (if evidence is missing/stale)**

   * Not as “extractors that run all the time”.
   * As an **on-demand LLM query**: “produce CALL/STORE/EVENT edges for these spans”.

### How to implement without turning everything into bespoke agents

Do **not** create 25 new agents. Create **one** language-agnostic interface that supports **facets**.

A practical shape:

* `analyze_source()` stays as-is (functions + comments).
* Add a second API: **signal/evidence inference** returning dynamic dicts:

```python
def infer_code_signals(
    *,
    file_path: str,
    source_text: str,
    spans: list[dict],           # optional: function/block spans
    requested: set[str],         # e.g. {"gaps", "call_edges", "store_edges", "event_edges", "arch_blocks"}
) -> dict[str, Any]:
    ...
```

* In production: implemented by LLM (cached by `(file_hash, requested)`).
* In tests: implemented by your existing AST-based test double (or fixtures), so the 2300 tests stay stable.

This gives you **Option B** capability without multiplying agents, and without rigid types.

---

## Q3: Compliance gates, language-agnostically

### Gates should not parse code. Gates consume evidence.

Define a single input bundle for gates:

* `GapInventory` (spans + gap kind + reason + confidence/ambiguity)
* `PinRegistry` snapshot
* `AdjacencyGraph` snapshot
* `FileHashIndex` (file → hash used when evidence was produced)
* `TestRunResult` (abstracted runner output)

If evidence hash ≠ current file hash: gate fails as **STALE_EVIDENCE** (not “recompute by parsing”).

### Algorithmic gates (5)

1. **NO_REMAINING_COMMENTS**

   * Pass if: `GapInventory` contains **zero** gaps of kind `SPEC_COMMENT_UNIMPLEMENTED`.
   * No scanning/tokenization in the gate.

2. **NO_STUB_FUNCTIONS**

   * Pass if: `GapInventory` contains **zero** gaps of kind `STUB_FUNCTION`.
   * Source for stubs:

     * `SourceAnalysis.functions[].is_stub` (already language-agnostic)
     * plus any “semantic stubs” the LLM flags (e.g., “TODO: implement”) as a gap span

3. **ALL_TESTS_PASS**

   * Language-agnostic via an abstraction:

     * `TestRunner.run(targets) -> TestRunResult`
   * Gate just checks `result.passed`.

4. **CALL_GRAPH_CONNECTED**

   * Gate runs a graph algorithm on `AdjacencyGraph` filtered to `signal_type == CALL`.
   * The “nodes” should be:

     * PinFunctions (or “algorithmic blocks”) as node IDs
   * Connectivity criterion should be redefined to avoid requiring full static call precision:

     * Example: “every PinFunction must be reachable from at least one slice entrypoint OR at least one test entrypoint”.
   * If edge confidence is low / ambiguous: return **AMBIGUOUS** and surface the question (don’t guess).

5. **STORE_MONOGAMY**

   * Use `STORE_TOUCH` edges: function/block → store node.
   * Check: each store node is owned by exactly one slice (ownership derived from PinProjections/slice nodes).
   * Pure graph check.

### Architectural gates (4)

1. **NO_INLINED_ATOM_LOGIC**

   * Replace AST similarity with **text fingerprinting on spans**:

     * Compare architecture spans vs PinFunction spans using language-agnostic substring/fingerprint similarity (e.g., winnowing/rolling hashes).
   * Fail on high similarity; for borderline cases, call LLM as adjudicator (tie-breaker only).

2. **FUNCTION_RECOMPOSITION**

   * Don’t “detect imports/calls”; verify recomposition via evidence:

     * Each architecture block node must have outgoing `PIN_PROJECTION` (or equivalent relationship) to at least one PinFunction.
     * AND must not violate `NO_INLINED_ATOM_LOGIC`.
   * This makes recomposition a **graph property**, not syntax.

3. **PIN_COVERAGE**

   * Define architecture blocks as nodes with spans (produced during promotion).
   * Coverage = every architecture block span is covered by ≥1 PinProjection span (or the node has ≥1 projection edge).
   * No parsing required.

4. **INTRODUCED_ALGORITHM_SPECS**

   * For architecture blocks flagged as `INTRODUCTION` (no origin pin):

     * Require: there exists at least one **spec-comment span** inside that block recorded in `GapInventory` as “spec present”.
   * If “spec present” classification is uncertain, gate returns **AMBIGUOUS**.

---

## Q4: “Language-agnostic” for graph extractors

### Target meaning

“Language-agnostic” does **not** mean “rebuild AST walking for every language.”

It means:

* Graph edges are **evidence produced by an understanding step** (LLM during promotion / ingestion),
* stored and consumed as **graph operations** afterward.

### What to do with the three extractors

* In the mature system: **do not keep three always-on extractors**.
* Replace with **one** concept:

  * `infer_adjacency_signals(requested={CALL, STORE_TOUCH, EVENT, REFERENCE}, spans=...)`
* Keep the old modules only as thin wrappers while migrating:

  * `call_graph.py` becomes: “return CALL edges from evidence; if missing, request signals.”

This avoids:

* duplicated LLM reads (three passes)
* rigid per-signal code paths
* reintroducing “parsing pipeline” thinking

---

## Q5: How `code_analysis.py` should evolve

### Don’t grow it into a mega-schema of language constructs

You already hit the failure mode: rigid dataclasses force language-specific fields.

### Keep `SourceAnalysis` minimal + add dynamic “facets”

Best target shape:

* Keep typed:

  * spans of “routines/blocks” (`RawFunctionInfo`, but conceptually “declared units”)
  * comment spans (`RawCommentInfo`)
  * stub detection (already present)
* Add a **dynamic** container for everything else:

  * `analysis.facets: dict[str, Any]` (optional)
  * or a separate `infer_code_signals()` function returning a dict

Key: facets should be **request-driven** (on-demand), cached, and test-doubled.

Examples of facet outputs (all span-based, no language constructs required):

* `arch_blocks`: list of `{id, line_start, line_end, kind}`
* `edges`: list of `{signal_type, src_id, dst_id, confidence, rationale_span?}`
* `stores`: list of `{store_id, touched_by:[block_id...]}`

### Single call vs multiple calls

Prefer a single “requested facets” call so one read produces multiple outputs when needed, but still avoid “always compute everything.”

---

## Q6: Role of pins in the conversion

### Pins become primary evidence, not something inferred afterward

So modules that currently “build pins by scanning imports” should flip direction:

* **PinProjections are produced at the moment architecture is written.**
* LLM already knows: “I’m wrapping atom X with middleware Y” → that is the projection type.

Therefore:

* `import_scanner.py` becomes unnecessary (query PinRegistryIndex instead).
* `projection_classifier.py` becomes unnecessary (classification is part of the promotion decision).
* The remaining need is **verification**, not discovery:

  * “Does the code still match the recorded projection?” (wrapper_hash / span hash checks)

### Recommended split

* **Producers (LLM during promotion):**

  * create/update `PinFunction`
  * create/update `PinProjection`
  * create/update adjacency edges
* **Consumers (deterministic code):**

  * gates
  * lineage builder
  * registry index queries
* **Verifiers (deterministic + optional LLM tie-break):**

  * wrapper_hash validation
  * similarity-based inlining detection
  * stale-evidence detection via hashes

---

## Q7: Brownfield ingestion (`collapse.py`) under “routing over extraction”

Brownfield ingestion is the one place where “understand existing code” is unavoidable. The way to keep it aligned is:

### Treat collapse as routing spans into the PDD graph

* Input: existing code
* Output: **span routing decisions**, not “facts extracted into a separate spec layer”

  * “These spans become PinFunctions”
  * “These spans are slice entrypoints”
  * “These blocks touch store S”
  * “These blocks publish/subscribe events”
  * “These files/blocks should be promoted into architecture vs algorithmic”

You may generate *summaries*, but only as routing hints (e.g., to name atoms/slices), not as a parallel spec.

### Language-agnostic implementation

* Use `code_analysis` to get candidate block spans (functions or “logical blocks”).
* Use an LLM collapse agent to:

  * choose which spans become atoms
  * generate initial PinFunctions/Projections
  * generate initial AdjacencyGraph edges with confidence
  * produce an ambiguity list (questions for constraints)

No AST required; only spans + graph outputs.

---

## Practical migration order (minimize risk to 2300 tests)

1. **Delete/neutralize leaf AST modules first** via adapters:

   * `analysis/ast_extractor.py` → route calls to `code_analysis`
   * `planning/code_parser.py` → wrapper over `code_analysis`

2. **Fold scanners into `gap_detection`:**

   * comment + stub scanners become internal implementations that call `code_analysis`

3. **Convert gates to consume `GapInventory + PinRegistry + AdjacencyGraph`**

   * stop calling any AST code from gates

4. **Make adjacency extractors “evidence-first”**

   * use stored edges if present; only infer via LLM when missing

5. **Move projection classification to pin creation time**

   * delete `projection_classifier.py`

This sequence keeps behavior stable while progressively eliminating parsing dependencies.

---

If you want one concrete litmus test for every remaining module:
**If it needs source text to rediscover relationships that could have been recorded as pins/edges at promotion time, it should be deleted or turned into an evidence consumer.**

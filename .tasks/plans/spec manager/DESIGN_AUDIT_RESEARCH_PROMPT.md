# Research: Full Design Audit Against PDD Philosophy

## What I Need From You

I need a comprehensive design review of the spec_manager system. The system was built following 11 implementation plans that may have violated core design principles. I need you to identify every design-level violation — not just "uses Python AST" (those are already cataloged), but deeper architectural misalignments where the system's structure contradicts its own philosophy.

This is not about code quality or missing features. This is about **philosophical alignment**: does the system's architecture match what the design documents say it should be?

---

## The Design Philosophy (12 Principles)

These principles come from `simpler.md` (the authoritative design document) and `WORKFLOW_ANALYSIS.md` (the promotion model analysis). They are not suggestions — they are the philosophy that every design decision must satisfy.

### Principle 1: LLM for Pattern Recognition
No hardcoding, no regex, no language-specific parsing. Patterns are recognized contextually by LLMs, not by scripts. "You cannot assume that any text within a spec follows a set pattern. These patterns cannot be extracted by regex or any type of script. They can be recognized as a pattern based on the order within them... The best thing to recognize general patterns is an LLM."

### Principle 2: Routing Over Extraction
The system avoids extraction. Phase 0 routes source spans to destinations — it does not extract content. Summaries are routing hints, not final output. If you find yourself extracting, you are likely solving a problem that doesn't need to exist.

### Principle 3: Code IS the Spec
No separate spec layer distinct from code. The PDD skeletons are simultaneously the spec and the code. When you implement, you fill in the same files that ARE the spec.

### Principle 4: Promotion, Not Direct Editing
Upper layers emerge from promotion. You never edit architecture or clean code directly. Changes flow through the promotion system.

### Principle 5: The System Always Knows What to Edit
Changes originate from processes (promotion, demotion, refinement, gate failure, review) that identify the target. You don't need to discover what to edit — the triggering process already knows.

### Principle 6: Graph Operations, Not Code Operations
The system operates on a graph of relationships between pins pointing to text locations. Downstream modules consume graph data, not source code syntax.

### Principle 7: Dynamic Structures Over Rigid Types
Language-agnostic means you cannot assume any language construct exists (classes, imports, decorators). Use dicts and dynamic structures when the structure varies by language. Only the LLM understands what the code contains.

### Principle 8: LLM Does Work During Its Actual Task
Pinning happens while the LLM is making promotion decisions — not as a separate mechanical extraction step. If the LLM already understands the code while doing its job, a separate parsing step is redundant.

### Principle 9: Minimal Planning, Constant Iteration
Plan as little as you can get away with. Constant baby steps. Each phase produces something messy, the next phase cleans it up.

### Principle 10: Block on Ambiguity
Don't guess. Surface the question. Human provides constraints, not solutions.

### Principle 11: Abstraction Over Implementation
Any solution the system didn't specify needs an abstraction so it can be changed.

### Principle 12: No Redundant Mechanical Steps
If the LLM already understands the code structure while performing its actual task, a separate mechanical parsing step that duplicates that understanding is redundant.

---

## The Target Architecture (from WORKFLOW_ANALYSIS.md)

### Promotion Layers
```
Layer 0: Raw prose → PROMOTION 1 (optional, if input is prose)
Layer 1: Code-as-spec (PDD skeletons) → PROMOTION 2 (main work)
Layer 2: Architecture (services/events/middleware via pins) → PROMOTION 3
Layer 3: Clean code (production-ready) → merge to main
```

### Promotion 2: The Iterative Per-Slice Loop
```
FOR EACH SLICE (in parallel across library worktrees):
  1. GAP EXPLORATION       → P3 finds remaining spec comments
  2. IMPLEMENTATION        → Agent writes code to fill gaps
  3. UNDER-SPEC CHECK      → Block on ambiguity, source constraints
  4. ANALYZE               → P1 structure, P2 intent verification
  5. PROMOTE               → P4 extract atoms, P5 pin through gates
  6. INTEGRATE             → CI on clean worktree
  7. VERIFY                → P6 cross-library, P7 lineage
  8. POWER ALIGNMENT       → Detect drift
  9. REPEAT for next slice
```

### Key: P1-P10 are TOOLS in an iterative loop, NOT a sequential pipeline.

### Compliance Gates
**Algorithmic (5):** NO_REMAINING_COMMENTS, NO_STUB_FUNCTIONS, ALL_TESTS_PASS, CALL_GRAPH_CONNECTED, STORE_MONOGAMY
**Architectural (4):** NO_INLINED_ATOM_LOGIC, FUNCTION_RECOMPOSITION, PIN_COVERAGE, INTRODUCED_ALGORITHM_SPECS

### Routing: Only at the Bottom Layer
Upper layers don't need routing because changes originate from processes that already know the target. Only Layer 1 needs routing (for incoming changes, demoted algorithms, new requirements).

### Demotion: All the Way Down
Issues at Layer 3 → evaluate at Layer 2 → if algorithmic, demote to Layer 1 → expand spec → implement → promote back up through ALL gates.

---

## What Actually Exists (Current Architecture)

### Orchestration Layer

**pdd_orchestrator.py** — Runs phases 0-10 SEQUENTIALLY:
```
P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9 → P10
```
Each phase is a separate handler method. No iteration. No per-slice loop. No parallelism across libraries. Post-phase refinement hook after P4+.

**pdd_lifecycle.py** — 4-phase lifecycle wrapper:
1. Build → runs PddOrchestrator.run() (all phases sequentially) + approval loop
2. QA → EvalRunner with judge
3. Architecture → agent proposes candidates
4. Code Quality → 4 reviewer agents

### Phase 0: Intake (Clean — built per research prompt)
5-step routing pipeline. Summarize → discover libraries → route spans → coverage check → assemble. Uses LLM for routing decisions. No AST. No extraction. This module follows the philosophy correctly.

### Phase 1-2: Structure Discovery + Decomposition
- `planning/code_parser.py` — Python AST parsing of functions, classes, comments
- `planning/reverser.py` — Python AST for function boundaries, then LLM for reverse-translation
- `core/edit_in_place.py` — Already converted to use code_analysis.py (LLM-based). Clean.

### Phase 3: Compliance/Gap Detection
- `compliance/detection/comment_scanner.py` — Python tokenize for comment extraction
- `compliance/detection/stub_scanner.py` — Python AST for stub detection
- `compliance/detection/runtime_detector.py` — Python-specific probe execution
- `compliance/detection/call_graph.py` — Python AST for call graph building
- `compliance/detection/coverage_analyzer.py` — Python AST + coverage.py
- `compliance/detection/orchestrator.py` — Aggregates all 5 scanners into ExecutableGapReport

### Phase 4: Library/Branch Organization
- `branches/collapse.py` — Python AST for codebase classification
- `branches/manager.py` — Facade integrating registries, promotion, navigation
- `branches/types.py` — Core data structures (AtomDescriptor, PinProjection, etc.)

### Phase 5: Spec Build / Pin Functions
- `pin_functions/orchestrator.py` — Scans atoms via AST, builds import graph via AST
- `branches/promotion.py` — Runs compliance gates, creates pins, records promotion
- `compliance/promotion/algorithmic_gates.py` — 5 gates, all use Python AST
- `compliance/promotion/architectural_quality.py` — AST-based quality checks
- `compliance/promotion/pin_coverage.py` — AST-based pin coverage
- `compliance/promotion/introduction_checker.py` — AST-based introduction checks

### Phase 6: Cross-Library Adjacency
- `analysis/adjacency/extractors/call_graph.py` — Python AST
- `analysis/adjacency/extractors/event_graph.py` — Python AST
- `analysis/adjacency/extractors/store_graph.py` — Python AST
- `analysis/adjacency/runner.py` — Orchestrates 4 extractors into AdjacencyReport

### Phase 7: Projection/Lineage
- `projection/lineage/import_graph.py` — Python AST for imports
- `projection/lineage/builder.py` — Python AST for patterns/decorators
- `projection/lineage/test_pin_baseline.py` — Python AST for test signatures
- `projection/lineage/test_pin_discovery.py` — Python AST for test→pin mapping
- `analysis/import_graph.py` — Python AST for imports
- `analysis/import_scanner.py` — Python AST for import hits
- `analysis/projection_classifier.py` — Python AST for projection types
- `analysis/data_flow.py` — Python AST for data flow

### Phase 8-9: Planning + Implementation
- `planning/workflow.py` — P8 integration with workspace
- P9 uses `core/edit_in_place.py` for gap analysis + report (no code writing yet)

### Phase 10: Continuous QA
- `strategies/evolution.py` — Strategy evolution pipeline
- `refinement_engine/detector.py` — Graph-based coupling/cohesion detection (no AST — clean)

### Infrastructure That Works
- **AdjacencyGraph** (analysis/adjacency/graph.py) — Signal-typed weighted directed graph
- **PinRegistry** (core/pin_registry.py) — Forward/backward trace, drift detection
- **GapQueue** (core/gap_queue.py) — Gap aggregation with stagnation detection
- **WorkspaceManager** (refinement/workspace/manager.py) — Run-scoped workspace
- **code_analysis.py** (core/) — LLM-based structural analysis
- **edit_in_place.py** (core/) — Already language-agnostic

---

## Suspected Violations

I've identified potential violations but I may be wrong about some and may be missing others. I need your review.

### Violation 1: Sequential Pipeline vs Iterative Per-Slice Loop
**Current**: pdd_orchestrator.py runs P0→P1→...→P10 sequentially
**Target**: P1-P10 are TOOLS invoked within an iterative per-slice loop with CI
**Principles violated**: 9 (minimal planning, constant iteration), 8 (LLM does work during its actual task)
**Question**: Is this a structural violation or just "not yet implemented"? The TODOs in the orchestrator acknowledge this gap. But does the sequential architecture make it HARDER to achieve the target, or is it a straightforward rewire?

### Violation 2: Pin Creation is Mechanical, Not During LLM's Work
**Current**: pin_functions/orchestrator.py scans atoms via AST and builds import graph via AST to create pins
**Target**: Principle 8 says pinning happens while the LLM is making promotion decisions
**Principles violated**: 1 (LLM for pattern recognition), 8 (LLM does work during its task), 12 (no redundant steps)
**Question**: Should pin creation happen INSIDE the implementation/promotion agent's workflow, with the agent producing pin data as part of its output? Or is mechanical scanning acceptable as a verification step?

### Violation 3: Compliance Gates Parse Code Instead of Consuming Graph Data
**Current**: All 9 gates independently parse Python AST to check conditions
**Target**: Principle 6 says operate on graph/pin data, not source code
**Principles violated**: 1 (language-specific parsing), 6 (graph operations), 12 (redundant parsing)
**Question**: Should gates operate on data already produced by prior phases? For example:
- NO_REMAINING_COMMENTS → code_analysis.py already found comments
- NO_STUB_FUNCTIONS → code_analysis.py already detected stubs
- CALL_GRAPH_CONNECTED → adjacency graph already built
- NO_INLINED_ATOM_LOGIC → pin content hashes already exist

### Violation 4: Graph Extractors Parse Code Instead of Consuming LLM Data
**Current**: Three extractors (call_graph, event_graph, store_graph) independently walk Python AST
**Target**: Principle 8 says the LLM already understands code during its work
**Principles violated**: 1, 8, 12
**Question**: Should graph edges be a byproduct of the LLM's actual work (implementing, analyzing, promoting)? Or should there be a single "analyze relationships" LLM call instead of three mechanical extractors?

### Violation 5: Collapse.py Does Extraction
**Current**: collapse.py extracts algorithmic intent from existing code via AST classification
**Target**: Principle 2 says avoid extraction, route instead
**Principles violated**: 1, 2
**Question**: Is brownfield ingestion an exception to the "no extraction" principle? Or should collapse use the same summarize → discover → route pattern as Phase 0?

### Violation 6: Separate Analysis Modules Duplicate LLM Understanding
**Current**: P1 parses code structure, P2 reverse-translates, P3 finds gaps, P6 builds adjacency graph, P7 builds lineage — each independently parsing the same code files
**Target**: Principle 12 says no redundant mechanical steps
**Principles violated**: 12, 8
**Question**: Should there be ONE comprehensive LLM analysis pass per file (functions, comments, stubs, calls, imports, stores, events — everything) that all downstream phases consume? Or is the per-phase separation correct?

### Violation 7: PinFunction Schema References Code, Not Graph
**Current**: PinFunction has file_path, line_start, line_end, signature, content_hash — references to source code locations
**Target**: Principle 6 says graph operations, not code operations
**Question**: Is this actually a violation? Pins ARE pointers to text locations — that's their purpose. The concern is not the schema but how pins are POPULATED (mechanical AST vs LLM during work).

### Violation 8: No Demotion Chain
**Current**: Gate failures skip atoms instead of fixing at L1
**Target**: WORKFLOW_ANALYSIS.md describes full demotion from L3→L2→L1 with re-promotion
**Question**: Is this just "not yet implemented" or is the current architecture structured in a way that makes demotion difficult?

### Violation 9: Planning Module Uses AST to Parse Code It Should Already Understand
**Current**: code_parser.py parses Python AST to find functions/comments for planning
**Target**: The planning agent should receive graph/pin data from prior analysis, not re-parse
**Principles violated**: 1, 6, 12
**Question**: Should the planning module consume FileTranslationState from edit_in_place.py (which already uses code_analysis.py) instead of having its own parser?

### Violation 10: Potential Violation in Data Flow Direction
**Current**: Data flows from code → analysis → graph → decisions
**Target**: Potentially should flow from LLM decisions → graph → verification
**Question**: Should the primary data flow be reversed? Instead of mechanically building a graph and then having the LLM make decisions based on it, should the LLM make decisions that produce graph data, with mechanical verification that the graph is consistent?

---

## What I Need You to Review

### For each suspected violation:
1. Is it actually a violation? (I may be wrong about some)
2. How severe is it? (Cosmetic / structural / philosophical)
3. What is the correct design?
4. What is the migration path from current to correct?

### Additionally:
5. Are there violations I missed?
6. Are there parts of the system that are well-designed and should NOT change?
7. Is the overall architecture (layers, promotion, pins, graph) correct in concept even if the implementation has violations?
8. What is the priority order for fixing violations? (Some may block others)

### Specifically for the 25 AST modules:
9. Given the violation analysis above, which modules should be:
   - **Deleted** (the design makes them unnecessary)
   - **Rewired** (consume graph/pin data instead of parsing code)
   - **Converted** (replace AST with LLM via code_analysis.py)
   - **Left alone** (they're actually fine)

---

## Reference Documents

- `simpler.md` — Authoritative design (PDD lifecycle + intake)
- `WORKFLOW_ANALYSIS.md` — Promotion model (correct target state)
- `ALGORITHM.md` — Design #1 (evidence preservation)
- `LONG_TERM_GOALS.md` — Phase history + eval methodology + design principles
- `PHASE0_RESEARCH_PROMPT.md` / `PHASE0_RESEARCH_RESPONSE.md` — How Phase 0 was designed
- `LANGUAGE_AGNOSTIC_RESEARCH_PROMPT.md` — Detailed catalog of the 25 AST modules

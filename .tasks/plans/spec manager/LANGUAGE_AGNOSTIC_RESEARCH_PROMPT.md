# Research: Converting 25 Python AST Modules to Language-Agnostic Design

## What I Need From You

I have 25 modules that use Python's `ast` and `tokenize` to mechanically parse source code. These modules need to become language-agnostic. I need you to analyze each module's PURPOSE in the system, determine whether it should exist at all under the system's design philosophy, and if it should exist, HOW it should work without language-specific parsing.

This is NOT a "replace ast.parse with LLM.parse" problem. The system's design philosophy may make some of these modules unnecessary. Mechanical parsing may be solving problems that don't need to exist.

---

## The System's Design Philosophy

The system (PDD — Prototype Driven Development) has deeply interconnected design principles. Violating one usually means violating several, because they reinforce each other.

### Principle 1: LLM for Pattern Recognition
"You cannot assume that any text within a spec follows a set pattern. These patterns cannot be extracted by regex or any type of script. They can be recognized as a pattern based on the order within them... The best thing to recognize general patterns is an LLM." (simpler.md lines 6-12)

No hardcoding, no regex, no language-specific parsing for pattern recognition.

### Principle 2: Routing Over Extraction
Phase 0 (the system's intake pipeline) routes source spans to destinations — it does NOT extract content. Summaries are routing hints, not final output. The system avoids extraction wherever possible. If you find yourself extracting, you are likely solving a problem that doesn't need to exist.

### Principle 3: Code IS the Spec
"The structured spec and the code are one and the same. The Python skeleton files — class/function signatures with spec comments and `pass` bodies — are simultaneously the structured spec and the code." (WORKFLOW_ANALYSIS.md lines 5-9)

There is no separate "spec layer" distinct from "code layer." When you implement, you fill in the same files that ARE the spec.

### Principle 4: Promotion, Not Direct Editing
Upper layers emerge from promotion. You never edit architecture or clean code directly. Changes flow through the promotion system. (WORKFLOW_ANALYSIS.md lines 293-306)

### Principle 5: The System Always Knows What to Edit
"Changes originate from processes (promotion, demotion, refinement, gate failure, review) that identify the target." (WORKFLOW_ANALYSIS.md line 306)

You don't need to discover what to edit — the process that triggered the change already knows.

### Principle 6: Graph Operations, Not Code Operations
The system operates on a graph of relationships between pins pointing to text locations. Downstream modules consume graph data, not source code syntax.

### Principle 7: Dynamic Structures Over Rigid Types
Language-agnostic means you cannot assume any language construct exists (classes, imports, decorators, etc.). Use dicts and dynamic structures when the structure varies by language. Only the LLM understands what the code contains.

### Principle 8: LLM Does Work During Its Actual Task
Pinning happens while the LLM is making promotion decisions — not as a separate mechanical extraction step. If the LLM already understands the code while doing its job, a separate parsing step is redundant.

### Principle 9: Minimal Planning, Constant Iteration
"Plan as little as you can get away with. Constant baby steps. Each phase produces something messy, the next phase cleans it up." (simpler.md lines 158-162)

### Principle 10: Block on Ambiguity
Don't guess, don't assume. Surface the question. Human provides CONSTRAINTS, not solutions. (WORKFLOW_ANALYSIS.md line 190)

### Principle 11: Abstraction Over Implementation
"Any area where you are taking a solution that I didn't specify (like using git) would need an abstraction so that the solution can be changed." (simpler.md lines 130-131)

### Principle 12: No Redundant Mechanical Steps
If the LLM already understands the code structure while performing its actual task (promoting, implementing, checking compliance), a separate mechanical parsing step that duplicates that understanding is redundant and violates the philosophy.

---

## How the System Works (Promotion Model)

```
Layer 0: Raw prose (uncontrolled input) — OPTIONAL entry point
    ↓ PROMOTION 1 (only if input is raw prose)
Layer 1: Code-as-spec (PDD skeletons — spec comments + code in same files)
    ↓ PROMOTION 2
Layer 2: Architecture (services/events/middleware assembled from pin-functions)
    ↓ PROMOTION 3
Layer 3: Clean code (production-ready, merged to main)
```

**Promotion 2 (the main work) iterative loop per slice:**
1. Gap exploration — P3 finds remaining spec comments not yet implemented
2. Implementation — Agent writes code to fill gaps
3. Under-specification check — block on ambiguity, source constraints
4. Analyze — P1 structure, P2 decomposition (reverse-translate for intent verification)
5. Promote — P4 extract atoms, P5 pin + push through compliance gates
6. Integrate — CI on clean worktree
7. Verify — P6 cross-library connections, P7 lineage traces
8. POWER alignment check

**P1-P10 are TOOLS invoked within this cycle, not a sequential pipeline.**

### Compliance Gates (what gets checked during promotion)

**Algorithmic layer (5 gates):**
1. NO_REMAINING_COMMENTS — No unimplemented spec comments
2. NO_STUB_FUNCTIONS — No functions with only placeholder bodies
3. ALL_TESTS_PASS — Algorithmic tests pass
4. CALL_GRAPH_CONNECTED — No orphaned functions
5. STORE_MONOGAMY — Each store accessed by single vertical slice

**Architectural layer (4 gates):**
1. NO_INLINED_ATOM_LOGIC — No copy-pasted atom logic in architecture
2. FUNCTION_RECOMPOSITION — Architecture properly imports and calls atoms
3. PIN_COVERAGE — All architectural code has algorithmic origin
4. INTRODUCED_ALGORITHM_SPECS — Infrastructure algorithms have spec comments

---

## Existing Pin Infrastructure

### PinFunction (from schemas/pin_functions.py)
```python
class PinFunction(BaseModel):
    pin_func_id: str           # e.g., "PFUNC-0001"
    function_name: str
    module_path: str
    file_path: str
    line_start: int
    line_end: int
    signature: str
    docstring: str
    content_hash: str          # SHA-256 of function body
```

### ProjectionType (how architectural locations use pin-functions)
- PASS_THROUGH — Direct import and call
- EVENT_BRIDGE — Wrapped in event handler
- MIDDLEWARE_WRAP — Wrapped in middleware layer
- RETRY_DECORATE — Wrapped with retry/resilience
- SLICE — Architecture uses subset of output
- SMEAR — Architecture combines multiple atoms
- AGGREGATION — Architecture combines multiple atoms
- INTRODUCTION — Architectural algorithm with no origin

### PinProjection (from branches/types.py)
- pin_id, atom_id, architectural_location, projection_type, wrapper_hash

### Storage
- In-memory: PinRegistry with forward/backward trace
- Persistent: JSON serialization
- Indexed: PinRegistryIndex for O(1) lookups

### Graph Infrastructure (analysis/adjacency/graph.py)
```python
class AdjacencyGraph:
    _nodes: dict[str, NodeInfo]        # node_id → metadata
    _adj: dict[str, dict[str, Edge]]   # source → {target → Edge}

    # Operations: add_node, add_edge, neighbors, connected_components, union, filter_by_signal_type
```

Signal types: CALL, REFERENCE, STORE_TOUCH, CO_OCCURRENCE, EVENT

---

## The 25 Modules and What They Do

Grouped by function, not by directory.

### Group A: Code Structure Parsing (what's in this file?)

| Module | What It Does | Python-Specific |
|--------|-------------|-----------------|
| `planning/code_parser.py` | Parse functions, comments, stubs from code files | ast, tokenize, `#` comments |
| `planning/reverser.py` | Convert existing code back into pseudocode comments | ast for function boundaries, LLM for translation |

### Group B: Comment/Stub Detection (what's NOT implemented?)

| Module | What It Does | Python-Specific |
|--------|-------------|-----------------|
| `compliance/detection/comment_scanner.py` | Extract unimplemented spec comments from code | tokenize, `#` delimiter |
| `compliance/detection/stub_scanner.py` | Find functions whose bodies are placeholders | ast.Pass, ast.Ellipsis, ast.Raise |
| `compliance/detection/runtime_detector.py` | Execute code in sandbox, catch NotImplementedError | .py filtering, Python exception types |
| `compliance/detection/coverage_analyzer.py` | Wrap coverage.py to find unexercised paths | ast for function ranges, `#` detection |
| `branches/gap_detection.py` | Aggregate gaps (comments + stubs + runtime) | Delegates to above, ast.Raise for RuntimeError |

### Group C: Call/Import/Store Graph Building (how does code connect?)

| Module | What It Does | Python-Specific |
|--------|-------------|-----------------|
| `analysis/adjacency/extractors/call_graph.py` | Build function-level call graph | ast.FunctionDef, ast.Call |
| `analysis/adjacency/extractors/event_graph.py` | Detect event publish/subscribe endpoints | ast.Call patterns, decorator analysis |
| `analysis/adjacency/extractors/store_graph.py` | Identify store read/write per function | ast type hints, naming conventions |
| `analysis/import_graph.py` | Build import graph (who imports what) | ast.Import, ast.ImportFrom |
| `analysis/import_scanner.py` | Find imports of specific atom functions | ast.ImportFrom, alias tracking |
| `analysis/data_flow.py` | Extract data flow summaries per atom | ast.unparse for types, parameter analysis |
| `analysis/projection_classifier.py` | Classify projection type of each import | ast.Call, ast.Return |
| `compliance/detection/call_graph.py` | Build call graph for connectivity checks | ast.FunctionDef, ast.Call, BFS |

### Group D: Promotion/Compliance Gates (is this ready to promote?)

| Module | What It Does | Python-Specific |
|--------|-------------|-----------------|
| `compliance/promotion/algorithmic_gates.py` | 5 gate checks for algorithmic layer | Delegates to B+C modules, ast, union-find |
| `compliance/promotion/architectural_quality.py` | Inlined logic detection, recomposition check | ast, body hash comparison, AST similarity |
| `compliance/promotion/pin_coverage.py` | Verify all architecture pins to algorithms | ast for class/function extraction, `#` detection |
| `compliance/promotion/introduction_checker.py` | Verify infrastructure algos have spec comments | ast for function bodies, `#` text extraction |

### Group E: Lineage/Projection (trace back to spec)

| Module | What It Does | Python-Specific |
|--------|-------------|-----------------|
| `projection/lineage/import_graph.py` | Build import graph for lineage tracing | ast.Import, ast.ImportFrom |
| `projection/lineage/builder.py` | Infer lineage edges from import relationships | ast for class/decorator patterns |
| `projection/lineage/test_pin_baseline.py` | Build signature baselines for test functions | ast for function discovery, MD5 hashing |
| `projection/lineage/test_pin_discovery.py` | Find which tests exercise which pin-functions | ast.ImportFrom, ast.Call analysis |

### Group F: Brownfield Ingestion (collapse existing codebase to Layer 1)

| Module | What It Does | Python-Specific |
|--------|-------------|-----------------|
| `branches/collapse.py` | Ingest existing codebase, extract algorithmic intent | ast for classification, keyword heuristics |
| `analysis/ast_extractor.py` | Core extraction: signatures, body hashes, shapes | ast throughout |

---

## What I Already Have (Language-Agnostic Foundation)

### code_analysis.py — LLM-based structural analysis
Already implemented. Calls `pdd-code-analyzer` agent and returns:
```python
@dataclass(frozen=True)
class RawFunctionInfo:
    name, qualified_name, start_line, end_line, is_async, is_stub,
    stub_reason, has_docstring, docstring, decorators, args,
    return_annotation, body_start_line, body_line_count

@dataclass(frozen=True)
class RawCommentInfo:
    line, col_offset, text, raw, enclosing_function

@dataclass
class SourceAnalysis:
    functions: list[RawFunctionInfo]
    comments: list[RawCommentInfo]
```

Content-hash cached. Used in tests via local Python AST test double.

### edit_in_place.py — Already converted to use code_analysis.py
Working. Tests pass. Language-agnostic.

### gap_bridge.py — Already converted to use code_analysis.py
Working. Tests pass. Converts comments/stubs to Gap objects.

---

## The Questions

### Question 1: Which modules should be DELETED entirely?

Some of these modules may be solving problems that the system's design makes unnecessary. If the LLM already understands the code while doing its actual work (implementing, promoting, checking compliance), do we need separate mechanical modules that parse the same code?

For example:
- If P9 (implementation agent) writes code AND knows what it wrote, does P1 (structure discovery via `code_parser.py`) need to mechanically re-parse what P9 just wrote?
- If the LLM creates pins DURING promotion decisions, does a separate `import_scanner.py` need to mechanically find those imports?
- If the LLM checks compliance AS PART of its promotion workflow, do separate gate modules need to independently parse code?

Which modules are solving problems that exist only because of a mechanical/sequential design, and would disappear under a properly LLM-integrated design?

### Question 2: Which modules should become LLM-driven?

For modules that genuinely need to exist (because they serve a purpose the LLM can't do inline), how should they work?

Option A: Replace ast.parse() calls with `analyze_source()` from code_analysis.py (the existing LLM-based analyzer). This is a 1:1 replacement — same structure, different engine.

Option B: Make the module's ENTIRE job an LLM task. Instead of parsing code → building graph → analyzing graph, just ask the LLM the question directly. For example, instead of building a call graph via AST, ask the LLM "what functions does X call?"

Option C: The module operates on graph/pin data that was already produced by a prior LLM step. No code parsing needed — it's a graph algorithm on existing data.

### Question 3: How should compliance gates work language-agnostically?

The 5 algorithmic gates and 4 architectural gates currently parse Python to check conditions. How should these work?

- NO_REMAINING_COMMENTS: Needs to find unimplemented spec comments in code. Currently uses tokenize. Could use code_analysis.py. Could ask the LLM directly.
- NO_STUB_FUNCTIONS: Needs to detect placeholder function bodies. Currently uses ast. Could use code_analysis.py (which already has is_stub). Could ask the LLM.
- CALL_GRAPH_CONNECTED: Needs to know if all functions are reachable. Currently builds a call graph via AST. Could build it from pin data. Could ask the LLM.
- NO_INLINED_ATOM_LOGIC: Needs to detect copy-pasted code between layers. Currently compares AST hashes. Could compare content hashes from pins. Could ask the LLM.
- PIN_COVERAGE: Needs to verify all architectural code has algorithmic origin. Currently uses AST to find functions. Could use pin registry data.

### Question 4: What does "language-agnostic" mean for graph extractors?

The three adjacency graph extractors (call_graph, event_graph, store_graph) currently build graphs by walking Python AST. In a language-agnostic world:

- Should these still exist as separate modules that call the LLM to extract graph edges?
- Should graph edges be produced as part of the LLM's promotion/analysis work and stored as pin data?
- Should there be a single "analyze adjacency" LLM call instead of three separate graph extractors?

### Question 5: How should code_analysis.py evolve?

Currently it returns functions and comments. The 25 modules need various things: imports, classes, call relationships, store access patterns, event endpoints, decorator meanings, type annotations, etc.

- Should code_analysis.py grow to return all of these? (Risks: rigid types, not every language has all concepts)
- Should there be multiple specialized LLM analysis agents? (Risks: duplicated work, many LLM calls)
- Should the analysis be on-demand — ask the LLM a specific question about the code when you need it? (Risks: no caching, repeated calls)
- Should the LLM produce a rich but dynamic (dict-based) analysis once, and modules query what they need from it?

### Question 6: What is the role of pins in this conversion?

Pins currently reference text locations via file_path + line_start + line_end + content_hash. Many of the 25 modules exist to BUILD pin data (import_scanner finds imports to create pins, projection_classifier classifies projection types for pins, etc.).

If pinning happens during the LLM's promotion work (Principle 8), do these modules become:
- (a) Consumers of pin data (reading what the LLM produced) rather than producers?
- (b) Verification agents (checking that the LLM's pin data is consistent)?
- (c) Unnecessary (the LLM both produces and verifies as part of its workflow)?

### Question 7: The brownfield ingestion problem

`collapse.py` ingests an existing codebase with no PDD structure and attempts to extract algorithmic intent. This is inherently a "parse code and understand it" problem. In a language-agnostic world:

- This seems like a legitimate use case for LLM-based code analysis — you genuinely need to understand code in any language.
- But Principle 2 says avoid extraction. Is collapsing an existing codebase "extraction" or "routing"?
- How does this work for non-Python codebases?

---

## What I've Tried and Why It Failed

### Attempt 1: Extend code_analysis.py with rigid dataclasses
Added `RawImportInfo`, `RawClassInfo`, `calls` field to `RawFunctionInfo`. Failed because:
- `RawImportInfo` had `is_from_import` — a Python-specific concept
- Not every language has classes, imports, or the same call patterns
- Rigid types can't represent what varies by language
- Violated Principles 1, 7, 8, 12

### Attempt 2: Replace ast.parse with analyze_source() in each module
Started converting modules to use `code_analysis.py` instead of `ast`. Failed because:
- This is a 1:1 mechanical replacement — same structure, different engine
- Doesn't question whether the MODULE ITSELF should exist
- Still treats the system as parsing code, just with a different parser
- May violate Principles 6, 8, 12

### What I have NOT tried
- Rethinking which modules should exist at all
- Making modules consume pin/graph data instead of parsing code
- Having the LLM produce richer output during its actual work (promotion, implementation, compliance checking) that eliminates the need for separate analysis modules

---

## Constraints On Your Design

1. **Respect all 12 design principles.** Every design decision must be validated against all principles, not just the obvious ones.
2. **The existing pin/graph infrastructure is good.** PinFunction, PinProjection, PinRegistry, AdjacencyGraph — these are well-designed and should be reused.
3. **code_analysis.py exists and works.** It provides language-agnostic function and comment analysis via LLM. It can be extended if needed (with dynamic structures, not rigid types).
4. **Tests must still work.** The root conftest injects a local Python AST test double for code_analysis.py so tests don't make LLM calls. Any new LLM calls need similar test doubles.
5. **2300 tests currently pass.** Changes should not break existing tests.
6. **Incremental migration.** Modules can be converted one at a time. They don't all have to change at once.
7. **The 11 implementation plans (01-11) prescribe Python AST usage. They are WRONG on this point.** Use WORKFLOW_ANALYSIS.md as the correct target state.
8. **Some modules may not need to change at all** — if they operate purely on graph/pin data and don't parse code, they're already language-agnostic.
9. **Some modules may need to be deleted entirely** — if the system's promotion model makes their function redundant.

# Phase 0 Execution Plan: Routing-Based Restructuring

## MANDATORY READING FOR ALL AGENTS

Before implementing ANY task in this plan, read these files in order:

1. `.tasks/plans/spec manager/CONSOLIDATION_CONCLUSIONS.md` — Section
   "Phase 0: Routing-Based Restructuring" explains the algorithm
2. `.tasks/plans/spec manager/PHASE0_RESEARCH_RESPONSE.md` — Why
   "refinement" must be routing, not rewriting
3. `.tasks/plans/spec manager/phase0/00_CLASSIFICATION.md` — The
   invariant trap and classification rules

## HARD RULES (violating any = immediate failure)

1. **NO REGEX for content analysis.** All pattern recognition uses LLMs.
   Regex is only allowed for parsing structured output (JSON, YAML, IDs).
2. **NO extraction.** Phase 0 is ROUTING. Source text is moved verbatim,
   not paraphrased, not decomposed into atoms, not summarized into output.
3. **NO parallel systems.** New code integrates into the existing package.
   Do not create new top-level packages or standalone systems.
4. **NO hardcoded keywords.** Libraries emerge from data. No lists of
   domain terms, normative indicators, or CamelCase patterns.
5. **Return for guidance** if requirements are unclear. Do NOT invent
   solutions, create stubs, or make assumptions. Stop and report what
   you don't know.

## What We're Replacing

The `orchestration/` directory is unauthorized code:
- `orchestration/extraction.py` — ProseExtractor (regex-based, violates all constraints)
- `orchestration/pdd_orchestrator.py` — PddOrchestrator (calls ProseExtractor)
- `orchestration/infrastructure.py` — PddInfrastructure (support for above)

These are imported by:
- `cli.py` lines 48, 85, 126 — `from spec_manager.orchestration.pdd_orchestrator import ...`
- `refinement/evals/workflow_integration.py` line 598 — `from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator`
- `tests/integration/orchestration/test_extraction.py` — test file for ProseExtractor

## What We're Building

A routing-based Phase 0 that:
1. Summarizes source files (LLM, for routing decisions only)
2. Discovers libraries from summaries (LLM)
3. Builds a routing table mapping source spans → destinations (LLM with reimplementation test)
4. Checks coverage (deterministic — all lines routed or ignored)
5. Assembles output by verbatim copy (deterministic)

## Where New Code Goes

New module: `spec_manager/intake/`

```
spec_manager/intake/
├── __init__.py          # Public API: run_phase0()
├── types.py             # RouteEntry, RoutingTable, CoverageLedger, LibraryDef
├── summarize.py         # Step 1: LLM summarization per source file
├── discover.py          # Step 2: Library discovery from summaries
├── route.py             # Step 3: Build routing table (LLM per file)
├── coverage.py          # Step 4: Coverage check (deterministic)
└── assemble.py          # Step 5: Verbatim copy assembly (deterministic)
```

New agents: `.agents/agents/`
- `spec-intake-summarize.md` — summarize a source file for routing
- `spec-intake-discover-libraries.md` — identify libraries from summaries
- `spec-intake-route.md` — classify and route source spans

---

## Task 1: Create routing data structures

**Module:** `spec_manager/intake/types.py`

Create dataclasses for the routing system. These are simple data
containers, no business logic.

```python
@dataclass
class SourceSpan:
    """A contiguous range of lines in a source file."""
    file: str          # relative path to source file
    start: int         # 1-based start line (inclusive)
    end: int           # 1-based end line (inclusive)

@dataclass
class RouteEntry:
    """One routing decision: source span → destination."""
    route_id: str           # unique ID, e.g. "R-000001"
    src: SourceSpan
    library: str            # library ID, e.g. "LIB-01"
    category: str           # "ANALYSIS" | "CONSTRAINTS" | "OVERVIEW" | "DETAIL/ALGORITHM" | "DETAIL/STORE" | "DETAIL/SHAPE"
    element_id: str         # e.g. "ALG-LIB01-001"
    notes: str = ""         # free-text from LLM explaining decision
    ref_stubs: list[str] = field(default_factory=list)  # unresolved cross-file references

@dataclass
class LibraryDef:
    """A discovered library."""
    lib_id: str             # e.g. "LIB-01"
    name: str               # human-readable name
    description: str        # one-line summary of responsibility

@dataclass
class CoverageLedgerEntry:
    """Coverage status for a line range."""
    file: str
    start: int
    end: int
    status: str             # "routed" | "ignored"
    route_ids: list[str] = field(default_factory=list)  # which routes cover these lines
    ignore_reason: str = "" # if ignored, why
```

Also create `spec_manager/intake/__init__.py` with just a docstring
and the public API import (placeholder until step functions exist):

```python
"""Phase 0: Routing-based restructuring of freeform prose into PDD format."""
```

**Files to create:**
- `scripts/spec_manager/spec_manager/intake/__init__.py`
- `scripts/spec_manager/spec_manager/intake/types.py`

**Files to modify:** None

**What NOT to do:**
- Do not add any logic, just data structures
- Do not import from orchestration/, refinement/, or any PDD module
- Do not add serialization yet (that comes in later tasks)

---

## Task 2: Create agent definitions

**Directory:** `.agents/agents/`

### Agent: spec-intake-summarize.md

Purpose: Summarize a single source file for routing decisions.

The agent receives:
- The full text of one source file

The agent produces (JSON):
- `file_id`: identifier for this file
- `summary`: high-level description of what the file contains
- `content_types`: list of content types found (e.g. ["algorithms", "shapes", "invariants", "analysis", "narrative"])
- `likely_libraries`: list of library candidates mentioned or implied
- `cross_references`: list of references to other files/sections

CRITICAL instructions in the agent prompt:
- This summary is for ROUTING DECISIONS ONLY, not for output
- Do NOT extract details — just characterize what's in the file
- Focus on: what AREAS does this file cover, what KINDS of content does it have
- Note any cross-file references ("see section X", "as defined in Y")

### Agent: spec-intake-discover-libraries.md

Purpose: Identify libraries from a set of file summaries.

The agent receives:
- All file summaries (from step 1)

The agent produces (JSON):
- `libraries`: list of {lib_id, name, description}
- `rationale`: why these libraries were chosen
- `overlap_notes`: any detected overlap between libraries

CRITICAL instructions:
- Libraries are BIG systems, not small components
- Libraries EMERGE from the data — do not use hardcoded terms
- Each library should answer: "What system capability does this provide?"
- When in doubt, fewer libraries is better (can split later)

### Agent: spec-intake-route.md

Purpose: Classify and route source spans from one file to destinations.

The agent receives:
- The full text of one source file (with line numbers)
- The library definitions (from step 2)
- The classification rules (invariant trap guidance from 00_CLASSIFICATION.md)

The agent produces (JSON):
- `routes`: list of routing decisions, each with:
  - `start`: start line number
  - `end`: end line number
  - `library`: which library ID
  - `category`: one of ANALYSIS, CONSTRAINTS, OVERVIEW, DETAIL/ALGORITHM, DETAIL/STORE, DETAIL/SHAPE
  - `element_id`: proposed element ID
  - `notes`: rationale for classification decision
  - `ref_stubs`: any unresolved cross-file references in this span

CRITICAL instructions in the agent prompt:
- **Every line must be covered.** Every line in the file must appear in
  exactly one route entry, OR be explicitly in an ignored entry.
- **Use the reimplementation test for classification.** Ask: "Does this
  statement survive if you completely change the implementation?"
  If yes → CONSTRAINTS. If no → DETAIL (algorithm/store/shape).
- **Do NOT paraphrase.** The route entries identify line ranges. The
  actual text is copied verbatim later. You are classifying, not rewriting.
- **Chunks of paragraphs are fine.** A route can span many lines. Only
  split when content changes category (e.g., an invariant sentence
  followed by algorithm steps).
- **Most "MUST" statements are algorithms, NOT constraints.** See the
  classification examples provided.
- **When unsure between constraint and algorithm:** if you could achieve
  the same GOAL with a completely different approach, the statement
  describes ONE approach (algorithm), not the goal itself (constraint).
- Cross-file references: record as ref_stubs, do not try to resolve them.

**Files to create:**
- `.agents/agents/spec-intake-summarize.md`
- `.agents/agents/spec-intake-discover-libraries.md`
- `.agents/agents/spec-intake-route.md`

**What NOT to do:**
- Do not create agents that extract or paraphrase content
- Do not include hardcoded keyword lists in agent prompts
- Do not include regex patterns in agent prompts

**GUIDANCE NEEDED:** Check `docs/development/writing-agents.md` for the
agent definition format (frontmatter, model selection, output_format).
If the format is unclear, return for guidance rather than guessing.

---

## Task 3: Implement summarization step

**Module:** `spec_manager/intake/summarize.py`

Implement `summarize_sources(source_dir: Path, output_dir: Path) -> list[dict]`

Logic:
1. Glob all `.md` files in source_dir
2. For each file, call the `spec-intake-summarize` agent via `run_agent()`
3. Parse JSON output (use `_strip_code_fences` + `json.loads`)
4. Write each summary to `output_dir/summaries/{file_stem}.json`
5. Return list of all summaries

**Imports allowed:**
- `from spec_manager.core.agent_utils import run_agent`
- `from spec_manager.refinement.formats import _strip_code_fences`
- `from spec_manager.intake.types import ...` (if needed)
- Standard library only otherwise

**What NOT to do:**
- Do not analyze content with regex
- Do not call any other agents
- Do not import from orchestration/
- If `run_agent` doesn't work as expected, return for guidance

---

## Task 4: Implement library discovery step

**Module:** `spec_manager/intake/discover.py`

Implement `discover_libraries(summaries: list[dict], output_dir: Path) -> list[LibraryDef]`

Logic:
1. Concatenate all summaries into a single context
2. Call the `spec-intake-discover-libraries` agent
3. Parse JSON output
4. Write to `output_dir/libraries.json`
5. Return list of LibraryDef

**Same import rules as Task 3.**

---

## Task 5: Implement routing step

**Module:** `spec_manager/intake/route.py`

Implement `route_sources(source_dir: Path, libraries: list[LibraryDef], output_dir: Path) -> list[RouteEntry]`

Logic:
1. Read classification guidance from `phase0/00_CLASSIFICATION.md`
   (or embed key rules in the agent prompt)
2. For each source file:
   a. Read file content with line numbers
   b. Call `spec-intake-route` agent with: file content + library defs + classification rules
   c. Parse JSON output into RouteEntry objects
   d. Validate: every line in the file is covered by some route
3. Write all routes to `output_dir/route_table.jsonl` (one JSON per line)
4. Return list of RouteEntry

**CRITICAL:** The routing agent prompt MUST include the invariant trap
guidance. Embed the classification rule ("does this survive
reimplementation?") and the examples from 00_CLASSIFICATION.md directly
in the prompt sent to the agent.

**What NOT to do:**
- Do not classify content using regex or keyword matching
- Do not paraphrase or rewrite source content
- Do not resolve cross-file references (record as ref_stubs)

---

## Task 6: Implement coverage check

**Module:** `spec_manager/intake/coverage.py`

Implement `check_coverage(source_dir: Path, routes: list[RouteEntry]) -> list[CoverageLedgerEntry]`

Logic:
1. For each source file, count total lines
2. Build a set of covered lines from route entries
3. Identify any uncovered lines
4. Return coverage ledger entries
5. Write to `output_dir/coverage_ledger.jsonl`

This is FULLY DETERMINISTIC — no LLM calls.

If coverage < 100%: return the uncovered line ranges so the caller
can decide whether to re-route or accept.

---

## Task 7: Implement assembly step

**Module:** `spec_manager/intake/assemble.py`

Implement `assemble_output(source_dir: Path, routes: list[RouteEntry], libraries: list[LibraryDef], output_dir: Path) -> Path`

Logic:
1. Group routes by library
2. Within each library, group by category
3. For each group:
   a. Read the source file lines for each route entry
   b. Copy lines VERBATIM into output file
   c. Add ([=element_id]) annotations
4. Create output directory structure:
   ```
   output_dir/
   ├── libraries/
   │   ├── LIB-01/
   │   │   ├── analysis.md       # Analysis content for this library
   │   │   ├── constraints.md    # Invariants for this library
   │   │   ├── overview.md       # Overview prose for this library
   │   │   └── details/
   │   │       ├── algorithms.md # Algorithm pseudocode
   │   │       ├── stores.md     # Store definitions
   │   │       └── shapes.md     # Data structure definitions
   │   └── LIB-02/
   │       └── ...
   └── route_table.jsonl         # The routing table (for traceability)
   ```
5. Return path to output_dir

This is FULLY DETERMINISTIC — no LLM calls. Just file I/O.

**CRITICAL:** The text copied into output files MUST be the exact source
text. No paraphrasing, no reformatting, no summarizing. The only additions
are ([=ID]) annotations and markdown headers for organization.

---

## Task 8: Wire pipeline together + integrate into system

**Module:** `spec_manager/intake/__init__.py`

Implement `run_phase0(source_dir: Path, output_dir: Path) -> dict`

Logic:
1. Step 1: `summarize_sources(source_dir, output_dir)`
2. Step 2: `discover_libraries(summaries, output_dir)`
3. Step 3: `route_sources(source_dir, libraries, output_dir)`
4. Step 4: `check_coverage(source_dir, routes)`
5. If coverage < 100%: log warning with uncovered ranges
6. Step 5: `assemble_output(source_dir, routes, libraries, output_dir)`
7. Return stats dict

**Then update imports in:**

### cli.py
Replace the 3 imports of `PddOrchestrator` with calls to `run_phase0`.
The CLI should dispatch Phase 0 to the intake module, not orchestration/.

### workflow_integration.py
Replace the import of `PddOrchestrator` (line 598) with `run_phase0`.
The `_run_pdd_phase` method should call `run_phase0` for the extraction
step instead of `orchestrator.run_phase(PddPhase.EXTRACTION)`.

**GUIDANCE NEEDED:** The exact CLI command structure and WorkspaceManager
integration need careful review. Read `cli.py` and
`workflow_integration.py` thoroughly before modifying. If the integration
points are unclear, return for guidance.

---

## Task 9: Update tests

### Delete:
- `tests/integration/orchestration/test_extraction.py` — tests ProseExtractor

### Create:
- `tests/unit/intake/test_types.py` — test data structure construction
- `tests/unit/intake/test_coverage.py` — test coverage check (deterministic)
- `tests/unit/intake/test_assemble.py` — test assembly (deterministic, use temp files)

### Update:
- `tests/evals/test_treasury_phases.py` — needs to use intake module
  instead of ProseExtractor for Phase 0

Tests for summarize/discover/route steps should mock `run_agent` since
they require LLM calls.

---

## Task 10: Remove orchestration/ directory

Only after Tasks 1-9 are complete and tests pass.

### Delete:
- `spec_manager/orchestration/` (entire directory)

### Verify:
- `grep -r "from spec_manager.orchestration" scripts/spec_manager/` returns nothing
- All tests pass: `uv run python -m pytest scripts/spec_manager/tests/ -p no:randomly -x -q`

---

## Execution Order

```
Task 1 (data structures)     — no dependencies
Task 2 (agent definitions)   — no dependencies
Task 3 (summarize step)      — depends on 1, 2
Task 4 (discover step)       — depends on 1, 2
Task 5 (route step)          — depends on 1, 2
Task 6 (coverage check)      — depends on 1
Task 7 (assembly)            — depends on 1
Task 8 (wire + integrate)    — depends on 3, 4, 5, 6, 7
Task 9 (tests)               — depends on 8
Task 10 (remove old code)    — depends on 9
```

Tasks 1-2 can run in parallel.
Tasks 3-7 can run in parallel (after 1-2).
Tasks 8-10 must be sequential.

---

## Open Questions (for guidance, not for agents to solve)

1. **WorkspaceManager integration.** The current system uses WorkspaceManager
   for directory structure. Should intake/ use WorkspaceManager or manage
   its own directories? The answer affects Task 7 (assembly) and Task 8
   (wiring).

2. **Model selection for agents.** simpler.md suggests GLM for summarizing,
   Opus for patterns, ChatGPT for details. Which model for each agent?
   See `docs/development/writing-agents.md` for available models.

3. **Treasury eval adaptation.** The eval framework currently measures
   sectionization/summarization/library_synthesis/spec_building as separate
   phases. With routing-based Phase 0, these become one operation. How
   should the eval phases map?

4. **Large file handling.** If a source file exceeds LLM context limits,
   how should it be chunked for the routing agent? The routing unit is
   contiguous spans, but the agent needs to see enough context to classify.

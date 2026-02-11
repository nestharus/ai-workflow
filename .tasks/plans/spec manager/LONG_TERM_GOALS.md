# Spec Manager: Long-Term Goals

## Phase 1: Consolidation & Implementation (COMPLETE)

Make sure everything is implemented correctly, nothing is extra, and
consolidate/remove old processes.

### Completed

* [x] Extract shared infrastructure from refinement/ to core/ (8 modules extracted)
* [x] Delete legacy dead code (workflow/, workspace/, staging/, discovery/, merging/, verification/)
* [x] Remove remaining cross-contamination (schemas->refinement, compliance->refinement)
* [x] Verify all PDD modules are complete and match their plans (11 plans + 5 refactors)
* [x] All CLI commands work (spec + spec-manager entry points)
* [x] Clean up dead imports, orphaned code, unused re-exports
* [x] PDD orchestrator (phases 0-10) with Phase enum
* [x] CLI exposes PDD operations as primary commands (run, phase, extract)
* [x] Eval framework supports PDD and refinement pipelines
* [x] Continuous library refinement engine (detector, operations, executor)
* [x] Infrastructure integration (signal resolver, ambiguity detection, evidence search)
* [x] LLM judge scorer for semantic eval scoring
* [x] All 2195 tests pass

## Phase 2: QA & Phase 0 Debugging (COMPLETE)

Step-by-step debugging of Phase 0 intake pipeline against treasury spec.

### Completed

* [x] Phase 0 intake module (`intake/`) implemented per PHASE0_RESEARCH_RESPONSE.md
  * Step 1: Summarize (LLM, routing hints only)
  * Step 2: Discover libraries = propose skeletons (LLM)
  * Step 3: Route source spans to destinations (LLM + reimplementation test)
  * Step 4: Coverage check (deterministic + LLM noise classification)
  * Step 5: Assemble output by verbatim copy (deterministic)

* [x] ProseExtractor (unauthorized regex-based extraction) removed
* [x] 4 LLM agent definitions created (spec-intake-summarize, \
  spec-intake-discover-libraries, spec-intake-route, spec-intake-coverage-filter)
* [x] 9 silent-default bugs fixed (all converted to raise ValueError)
* [x] JSON retry logic in all LLM-calling steps
* [x] Cross-system invariants handled as system-level constraints (not a library)
* [x] Rediscovery feedback loop for unroutable content
* [x] All 2195 tests pass

## QA Methodology (applies to ALL phases)

### Step-by-Step Eval with Root Cause Analysis

The eval process runs each pipeline step individually, inspects the output,
fixes bugs, and re-runs until the step passes. Only then does it advance
to the next step. This is NOT a full pipeline run with a judge — it is
manual step-by-step debugging.

#### Output chaining and preservation

Each step consumes the output of the previous step as its input. Outputs
must be preserved so later steps receive realistic inputs and so results
can be inspected after the fact.

1. **Preserve every step's output** — save to a named directory (e.g.
   `evals/<run_id>/step_N/`) before advancing. Never discard intermediate
   artifacts.
2. **Feed output forward** — the next step's input is the previous step's
   output, not the original fixture. For example: L1 produces implemented
   code → L2 receives that implemented code as input → L3 receives L2's
   output. Running L3 on the original skeleton is testing an impossible
   scenario.
3. **Re-run cascades** — if you fix a bug in step N, re-run step N AND
   re-run all subsequent steps with step N's new output. Their prior
   outputs are now stale.

#### Process per step

1. **Run the step** against the treasury spec in an isolated workspace,
   using the output of the previous step as input (or the original fixture
   if this is the first step)
2. **Inspect the output** — read actual LLM responses, check structure,
   verify content quality
3. **If a bug is found**:
   a. **Root cause analysis** — trace the bug to its origin. Don't fix
      the symptom. Ask: why did this happen? What assumption was wrong?
   b. **Assess blast radius** — if you change X, what else depends on X?
      Does the ground truth need updating? Do other steps break? Do agent
      definitions need changes? Do tests need updating?
   c. **Fix the root cause** — implement the proper solution. No silent
      defaults. No shortcuts. No overloading concepts. No reward hacking.
   d. **Propagate consequences** — update all affected files: ground truth,
      agent definitions, tests, other pipeline steps, types, schemas.
   e. **Re-run the step** from scratch to verify the fix
   f. **If the fix introduced new failures**, go back to step 3
4. **When the step passes**, preserve output and advance to the next step
5. **If a later step reveals a problem in an earlier step**, go back and
   fix the earlier step, then re-run all steps from that point forward
   with updated outputs

#### Anti-patterns (DO NOT)

* **DO NOT run all steps in one go** — you miss bugs that cascade
* **DO NOT run steps on the original fixture when a prior step produces
  output** — e.g. running L3 on skeleton code instead of L1-implemented
  code tests an impossible scenario. Always chain outputs.
* **DO NOT use silent defaults** — if LLM output is invalid, raise an error.
  Silent defaults hide bugs and are a form of reward hacking.

* **DO NOT overload concepts** — e.g. don't create a library called "SYSTEM"
  to hold system-level constraints. System constraints are not a library.

* **DO NOT skip blast radius analysis** — changing what a "library" means
  affects ground truth, agent definitions, validation code, assembly code,
  coverage code, tests, and CLI output.

* **DO NOT fabricate solutions** — e.g. don't make the routing agent propose
  libraries when the library discoverer is the one that discovers libraries.
  Use the right component for the right job.

* **DO NOT note bugs without fixing them** — every bug found must be fixed
  before moving on.

* **DO NOT retry past problems** — if the LLM returns Chinese text, the fix
  is telling the agent to respond in English, not adding a retry loop (though
  JSON parse retries for malformed output ARE appropriate since that's
  non-deterministic LLM behavior, not a systematic agent instruction issue).

#### When you hit an ambiguity or design gap

If something is undefined, underspecified, or seems brittle/strange — do NOT
guess or invent a solution. Instead:

1. **Write a research prompt** modeled after `PHASE0_RESEARCH_PROMPT.md`
2. **Include all context**: what the system does, what the constraints are,
   what prior designs exist, what specific question needs answering, and
   what options you've considered
3. **Present it to the user** — they will get an answer (possibly from
   external research)
4. **Record the answer** as a `*_RESEARCH_RESPONSE.md` file alongside the
   prompt for future sessions to reference

This is how Phase 0's routing algorithm was designed — a research prompt
produced the three required operators (routing unit, routing ledger,
invariant test) that no amount of guessing would have found.

#### When introducing anything new, validate against design principles

Every new data structure, module, parsing approach, or architectural
decision MUST be validated against the established design principles before
implementation. The principles are not just rules — they are the philosophy
behind how this system operates. Violating one principle usually means
violating several, because they reinforce each other.

**Core design principles** (derived from `simpler.md` and `WORKFLOW_ANALYSIS.md`):

1. **LLM for pattern recognition** — no hardcoding, no regex, no
   language-specific parsing. Patterns are recognized contextually by LLMs,
   not by scripts. (simpler.md lines 6-12)

2. **Abstraction over implementation** — any solution the system didn't
   specify needs an abstraction so it can be swapped. (simpler.md lines
   130-131)

3. **Routing over extraction** — Phase 0 routes, it doesn't extract.
   Summaries are routing hints, not final output. The system avoids
   extraction wherever possible. If you find yourself extracting, you are
   likely solving a problem that doesn't need to exist.

4. **Code IS the spec** — no separate spec layer distinct from code. The
   PDD skeletons are simultaneously the spec and the code.
   (WORKFLOW_ANALYSIS.md lines 5-9)

5. **Promotion, not direct editing** — upper layers emerge from promotion.
   You never edit architecture or clean code directly. Changes flow through
   the promotion system. (WORKFLOW_ANALYSIS.md lines 293-306)

6. **The system always knows what to edit** — changes originate from
   processes (promotion, demotion, refinement, gate failure, review) that
   already identify the target. (WORKFLOW_ANALYSIS.md line 306)

7. **Pins as the bridge** — pin-functions bridge layers. The pin projection
   type describes assembly. Promotion IS routing at upper layers.

8. **Graph operations, not code operations** — the system operates on a
   graph of relationships between pins pointing to text locations. It does
   NOT parse source code syntax. Downstream modules consume graph data.

9. **Dynamic structures over rigid types** — language-agnostic means you
   cannot assume any language construct exists (classes, imports, etc.).
   Use dicts and dynamic structures when the structure varies by language.
   Only the LLM understands what the code contains.

10. **LLM does work during its actual task** — pinning happens while the
    LLM is making promotion decisions. There is no separate mechanical
    extraction step. If the LLM already understands the code while doing
    its job, a separate parsing step is redundant.

11. **Minimal planning, constant iteration** — plan as little as you can
    get away with, constant baby steps. Each phase produces something messy,
    the next phase cleans it up. (simpler.md lines 158-162)

12. **Block on ambiguity** — don't guess, don't assume. Surface the
    question. Human provides CONSTRAINTS, not solutions.
    (WORKFLOW_ANALYSIS.md line 190)

**How to validate**: Before implementing, ask yourself for each principle:
"Does my introduction violate this?" If yes for ANY principle, either
redesign to comply or explicitly ask the user for permission to change the
philosophy, providing a clear reason why the change is necessary. Do NOT
silently violate principles — that causes rework.

**Example violation**: Introducing AST parsing violates principles 1
(hardcoded language), 2 (no abstraction), 3 (extraction instead of
routing), 8 (code operations instead of graph operations), 9 (rigid types),
10 (redundant mechanical step). One bad introduction can violate many
principles simultaneously.

---

## Phase 3: Wire PDD Orchestrator to Real Modules (COMPLETE)

All orchestrator phases delegate to real PDD module entry points. The
refinement engine is analysis-only (no mutations). 2197 tests pass.

### Completed

* [x] Fix `_run_refinement_engine()` to be analysis-only (removed executor.execute calls)
* [x] Wire P0 to use `intake/run_phase0()` (was already done in Phase 2)
* [x] Wire P1 to use `core/edit_in_place.analyze_project()` + `find_gaps()` + `parse_file()`
* [x] Wire P2 to use `planning/reverser.reverse_translate()` per function
* [x] Wire P3 to use `compliance/detection/orchestrator.scan_executable_gaps()` + `GapQueue`
* [x] Wire P4 to use `branches/manager.collapse_codebase()` + atom registration
* [x] Wire P5 to use `pin_functions/orchestrator.scan()` + `branches.promote()`
* [x] Wire P6 to use `analysis/adjacency/runner.run_adjacency_analysis()`
* [x] Wire P7 to use `projection/lineage/` + `analysis/generator.py` + `projection/generator`
* [x] Wire P8 to use `planning/workflow.run_planning_v2_phase()` with gap-derived intentions
* [x] Wire P9 to use `core/edit_in_place` for gap analysis + gap report (no silent defaults)
* [x] Wire P10 to use `strategies/evolution.StrategyEvolutionPipeline` + refinement engine
* [x] All 2197 tests pass

### What Each Phase Now Does

| Phase | Module(s) Called |
|-------|-----------------|
| P0 intake | `intake/run_phase0()` (5-step routing) |
| P1 structure | `planning.code_parser.parse_file()` + `core.edit_in_place.analyze_project()` + `find_gaps()` |
| P2 decomposition | `planning.reverser.reverse_translate()` per function |
| P3 compliance | `compliance.detection.orchestrator.scan_executable_gaps()` + `GapQueue` integration |
| P4 library | `branches.manager.collapse_codebase()` + atom registration + persist |
| P5 spec_build | `pin_functions.orchestrator.scan()` + `branches.promote()` |
| P6 cross_library | `analysis.adjacency.runner.run_adjacency_analysis()` |
| P7 projection | `ImportGraph.build()` + `LineageBuilder.build()` +
  `generate_analysis()` + `ProjectionGenerator.gen()` |
| P8 task_planning | `planning.workflow.run_planning_v2_phase()` with gap-derived intentions |
| P9 implementation | `core.edit_in_place.analyze_project()` + `find_gaps()` + `format_gap_report()` |
| P10 continuous_qa | `StrategyEvolutionPipeline` (promotion, report) + `refinement_engine` (analysis-only) |

### Refinement Engine (Correct Role)

* **Analysis-only**: detects coupling/cohesion issues, proposes operations, does NOT execute
* **Post-phase hook**: runs automatically after Phase 4+ to report grouping quality
* **Phase 10**: runs explicitly as core of continuous QA

## Phase 4: PDD Lifecycle Orchestration (COMPLETE)

Wire the 4-phase PDD model from `simpler.md` using existing plan
implementations. Most capabilities already exist as modules — the work
is orchestrating them into the lifecycle, not building from scratch.

### simpler.md's 4-Phase Model

**Phase 1 (Build)**: Research → sparse plan → worktree → implement in parallel
→ block on ambiguity → POWER alignment → human review → approve

**Phase 2 (QA)**: Create evals → detect failures → root cause → patch back

**Phase 3 (Architecture)**: Proposals → analysis → choice → refactor

**Phase 4 (Code Quality)**: N reviewers → refactor → merge to main

### What Existing Plans Already Cover

| PDD Lifecycle Step | Plan | Module | Status |
|--------------------|------|--------|--------|
| Research / evidence gathering | Plan 06 (Hollowed-Out Spec Evidence) | `refinement/hollowed_spec/` | Implemented |
| Planning / plan generation | Plan 03 (Planning Module) | `planning/` | Implemented |
| Implementation / code editing | Plan 01 (Edit-in-Place) | `core/edit_in_place.py` | Implemented |
| Gap detection | Plan 05 (Executable Gap Detection) | `compliance/detection/` | Implemented |
| Ambiguity detection | Plan 06 + `refinement/interactive/` | hollowed_spec + interactive | Implemented |
| Compliance / quality gating | Plan 08 (Compliance Gating) | `compliance/promotion/` | Implemented |
| Promotion between layers | Plan 04 (Branch Org) | `branches/promotion.py` | Implemented |
| Architecture analysis | Plan 07 (Adjacency) + Plan 11 (Analysis Gen) | `analysis/` | Implemented |
| Lineage tracking | Plan 09 (Lineage Tracking) | `projection/lineage/` | Implemented |
| Strategy evolution | Plan 10 (Strategy Evolution) | `strategies/` | Implemented |
| Pin-function mapping | Plan 02 (Pin-Functions) | `pin_functions/` | Implemented |
| Entity coverage | fix-03 (Spec Entity Coverage) | `compliance/coverage/` | Implemented |
| Test-pin validation | fix-02 (Test-Pin Validation) | `projection/lineage/` | Implemented |

### Lifecycle Orchestrator: `orchestration/pdd_lifecycle.py`

`PddLifecycle` class wires the 4-phase lifecycle using existing infrastructure:

| Lifecycle Phase | What It Does | Infrastructure Used |
|----------------|--------------|---------------------|
| Build | Run PDD pipeline + refine + align + overview + worktrees | `PddOrchestrator` \
| + `InteractiveWorkflow` + `opus-alignment-checker` \
| + `opus-overview-writer` + `WorktreeManager` |
| QA | Run eval framework with LLM judge | `EvalRunner` with `use_judge=True` |
| Architecture | Propose architectures, analyze tradeoffs | `opus-architecture-proposer` agent |
| Code Quality | N reviewers | 4 `chatgpt-*-reviewer` agents |

CLI: `spec lifecycle [run_id] [phase] --mode auto|interactive --research --steering PATH --worktrees`

### Worktree Management: `orchestration/vcs.py` + `orchestration/worktree_manager.py`

VCS abstraction (`VcsOperations` Protocol + `GitVcs` implementation) wraps git
operations for worktree management.  Per `simpler.md`: *"It could be jj. It
could be git. We don't care."*

`WorktreeManager` implements the worktree hierarchy:
* **Root (dirty) worktree** — where PDD pipeline runs
* **Per-library grandchild worktrees** — parallel implementation
* **Clean sibling worktree** — accumulates tested, promoted code

Methods: `setup()`, `create_library_worktree(lib_id)`,
`promote_library(lib_id)`, `rebase_root_on_clean()`, `cleanup()`.

### Human Approval Loop

`build_with_approval()` implements simpler.md steps 8-12:
* Build → overview → prompt user → approve or feedback → repeat
* Auto/steering modes: auto-approve (no user prompt)
* Interactive mode: present overview, collect approve/feedback/quit
* Max iterations guard prevents infinite loops
* Feedback written to `reports/feedback_iteration_N.txt`

### What's Genuinely Missing (not in any plan)

* [x] Worktree management — wired via `VcsOperations`/`GitVcs` + `WorktreeManager`
* [x] --auto mode orchestration — wired via `InteractiveWorkflow` + `ResearchCoordinator`
* [x] --interactive mode orchestration — wired via `InteractiveWorkflow`
* [x] POWER alignment check — wired via `opus-alignment-checker` agent
* [x] Human review document generation — wired via `opus-overview-writer` agent
* [x] Human approval loop — wired via `build_with_approval()` + `_request_approval()`

### End-to-End Eval Results (chaotic_treasury_expanded)

Phase 0 pipeline run with real LLM calls
against 10 source .md files:

| Dimension | Result |
|-----------|--------|
| Sectionization | 100% (10/10 sections) |
| Library discovery | 7 libraries (vs 8 ground truth) — LLM merged<br>TransactionValidator into Settlement Processing. |
| Requirement capture | **52/52** (manual verification — every requirement present in output) |
| Coverage | 100% (214/214 lines covered) |

**No code bugs found.** Pipeline works end-to-end.

**IMPORTANT**: The fuzzy scorer (`score_detail_capture`) reported 47/52 (90.4%).
Manual verification found ALL 52 requirements present. The fuzzy scorer produces
false negatives. **Always manually verify — do not trust fuzzy scores.**

Phase 0 output saved to fixtures:
`fixtures/chaotic_treasury_expanded_phase0_output/` (libraries/, summaries/, system/, etc.)

### Eval Strategy

Evals run in --interactive mode with Claude supplying answers to ambiguity
questions. This is the natural test harness — the treasury spec triggers
ambiguity blocking, Claude resolves it as the "user", and the pipeline
continues. This tests the full lifecycle end-to-end without requiring a
human in the loop during automated eval runs.

When answering ambiguity questions, Claude also runs the --auto research
algorithm (Opus + GPT + GLM + firecrawl) to produce answers. This serves
double duty: it evaluates the research algorithm's answer quality against
Claude's own judgment. If the research algorithm produces a bad answer,
that's a signal to improve the research pipeline — tune prompts, adjust
model routing, or add missing context. The eval loop becomes a feedback
mechanism for both the pipeline AND the research algorithm.

---

## How To Run Evals (Step-by-Step with Real LLM Calls)

**CRITICAL: Simulations prove nothing.** The eval runs each Phase 0 step
individually with REAL LLM calls, inspects the output, fixes bugs, and
only then advances to the next step.

### Eval Fixture Structure

```text
fixtures/
├── chaotic_treasury_expanded.yaml                  # MANIFEST for Phase 0 (prose markdown input)
├── chaotic_treasury_expanded/                      # 10 SOURCE .md files — Phase 0 INPUT
│   ├── overview.md
│   ├── settlement_processing.md
│   └── ... (10 files total)
├── chaotic_treasury_expanded_ground_truth.yaml     # GROUND TRUTH (52 requirements, 8 libraries)
├── chaotic_treasury_expanded_phase0_output/        # Phase 0 OUTPUT (verified 52/52 correct)
│   ├── libraries.json                              # 7 library definitions (+ LIB-08 from rediscovery)
│   ├── libraries/LIB-01/ through LIB-08/          # Assembled markdown per library
│   ├── summaries/*.json                            # Per-file summaries
│   ├── system/constraints.md                       # Cross-system invariants
│   ├── route_table.jsonl                           # Source span → destination mappings
│   └── coverage_ledger.jsonl                       # 100% coverage proof
├── chaotic_treasury_expanded_pdd.yaml              # MANIFEST for Phases 1-10 (Python code input)
├── chaotic_treasury_expanded_pdd/                  # 8 Python skeleton files — Phases 1-10 INPUT
│   ├── settlement_processor.py                     # 8 functions, 14 spec comments
│   ├── risk_engine.py                              # 7 functions, 8 spec comments
│   ├── reconciliation_service.py                   # 4 functions, 7 spec comments
│   ├── event_pipeline.py                           # 5 functions, 9 spec comments
│   ├── regulatory_compliance.py                    # 6 functions, 6 spec comments
│   ├── audit_notification.py                       # 4 functions, 6 spec comments
│   ├── transaction_validator.py                    # 2 functions, 2 spec comments
│   └── settlement_orchestration.py                 # 2 functions, 8 spec comments
└── ...                                             # Other specs
```

**File types:**
1. **Manifest** (`.yaml`): Points to sections_dir + ground_truth_path
2. **Source files** (in `sections_dir/`): THE ACTUAL SPEC — fed into pipeline
3. **Ground truth** (`*_ground_truth.yaml`): Expected outputs — NOT fed into pipeline
4. **Phase 0 output** (`*_phase0_output/`): Verified correct output from Phase 0 run
5. **PDD skeletons** (`*_pdd/`): Python code with spec comments for Phases 1-10

### Loading a Spec

```python
from spec_manager.refinement.evals.inputs.sequence_spec import load_sequence_spec
from pathlib import Path

fixtures = Path("scripts/spec_manager/spec_manager/refinement/evals/inputs/fixtures")
spec = load_sequence_spec(fixtures / "chaotic_treasury_expanded.yaml")
# spec.sections = {"OVERVIEW": "...", "SETTLEMENT_PROCESSING": "...", ...}  (10 sections)
# spec.ground_truth = GroundTruth(...)  (from ground_truth.yaml)
```

### Creating a Workspace from a Spec

```python
from spec_manager.refinement.evals.workflow_integration import WorkspaceIntegration

integration = WorkspaceIntegration(temp_dir=Path("/tmp/eval"), cleanup_on_exit=False, use_pdd=True)
manager = integration.create_workspace_from_spec(spec)
# This writes 10 .md files to a temp input_folder and initializes WorkspaceManager
# Input files: /tmp/eval/spec_input_chaotic_treasury_expanded_{uuid}/*.md
# Workspace: runs/eval_chaotic_treasury_expanded_{uuid}/
```

### Running Phase 0 Step-by-Step (Real LLM Calls)

Each step is a separate function call with real LLM invocations:

```python
from spec_manager.intake.summarize import summarize_sources
from spec_manager.intake.discover import discover_libraries
from spec_manager.intake.route import route_sources
from spec_manager.intake.coverage import check_coverage
from spec_manager.intake.assemble import assemble_output

source_dir = Path("/tmp/eval/spec_input_chaotic_treasury_expanded_{uuid}")
output_dir = Path("/tmp/eval/phase0_output")
output_dir.mkdir(parents=True, exist_ok=True)

# Step 1: Summarize (calls spec-intake-summarize agent per file, uses GLM)
summaries = summarize_sources(source_dir, output_dir)
# Inspect: output_dir/summaries/*.json — one per source file

# Step 2: Discover libraries (calls spec-intake-discover-libraries agent)
libraries = discover_libraries(summaries, output_dir)
# Inspect: output_dir/libraries.json

# Step 3: Route source spans (calls spec-intake-route agent per file)
routes, libraries = route_sources(source_dir, libraries, output_dir)
# Inspect: output_dir/route_table.jsonl

# Step 4: Coverage check (deterministic + LLM noise classification)
ledger = check_coverage(source_dir, routes, output_dir)
# Inspect: output_dir/coverage_ledger.jsonl

# Step 5: Assemble (deterministic verbatim copy)
libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)
# Inspect: output_dir/libraries/LIB-*/analysis.md, constraints.md, details/*.md
```

### Inspecting Outputs

After each step, read the output files and compare against ground truth:

```python
# Ground truth from spec
gt = spec.ground_truth
# gt.library_synthesis.expected_libraries = ["SettlementProcessor", "RiskEngine", ...]
# gt.library_synthesis.expected_requirements = ["Settlement instructions must contain...", ...]
# gt.sectionization.expected_sections = ["OVERVIEW", "SETTLEMENT_PROCESSING", ...]
```

### Using the EvalRunner (Full Pipeline Mode)

```bash
# Run with real LLM calls against specific spec
uv run python -m spec_manager.refinement.evals.cli run \
  --spec-ids chaotic_treasury_expanded \
  --use-real-workflows

# List available specs
uv run python -m spec_manager.refinement.evals.cli list
```

### Agent Definitions (LLM prompts)

Located in `.agents/agents/`:
* `spec-intake-summarize.md` — GLM model, JSON output
* `spec-intake-discover-libraries.md` — discovers library skeletons
* `spec-intake-route.md` — routes source spans to destinations
* `spec-intake-coverage-filter.md` — classifies uncovered content as noise vs missed

### How To Run PDD Phases 1-10 (Code-as-Spec)

Phases 1-10 operate on Python source files, not prose. Use the PDD fixture:
`chaotic_treasury_expanded_pdd/` (8 Python skeletons with spec comments).

The workspace also needs the Phase 0 output installed (libraries/, summaries/,
system/) because some phases reference that data.

#### Setting Up the Workspace

```python
from pathlib import Path
from spec_manager.refinement.workspace.manager import WorkspaceManager

fixtures = Path("scripts/spec_manager/spec_manager/refinement/evals/inputs/fixtures")

# Initialize workspace with Python skeleton files as spec_snapshot
manager = WorkspaceManager(
    run_id="treasury-pdd-qa",
    input_folder=fixtures / "chaotic_treasury_expanded_pdd",
)
issues = manager.initialize(force=True)

# Install Phase 0 output into workspace (libraries/, summaries/, system/)
from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
orchestrator = PddOrchestrator(manager)
orchestrator._install_phase0_output(fixtures / "chaotic_treasury_expanded_phase0_output")
```

#### Running Each Phase Individually

```python
from spec_manager.refinement.workspace.state import Phase

# Run one phase at a time
result = orchestrator.run_phase(Phase.STRUCTURE_DISCOVERY)  # P1
print(result)
# Inspect output, fix bugs, then advance:
# result = orchestrator.run_phase(Phase.DECOMPOSITION)      # P2
# result = orchestrator.run_phase(Phase.COMPLIANCE_CLEAN)    # P3
# ... etc through Phase.CONTINUOUS_QA (P10)
```

#### What Each Phase Expects and Produces

| Phase | Input | Output to Inspect |
|-------|-------|-------------------|
| P1 structure | `.py` files in spec_snapshot | files_parsed, gaps_detected, per-file function/class counts |
| P2 decomposition | `.py` files (AST parsed) | functions_processed, functions_with_comments |
| P3 compliance | `.py` files | gaps_found, comment_gaps, stub_gaps, gaps_queued |
| P4 library | spec_snapshot dir | atoms_extracted, stores_extracted, shapes_extracted |
| P5 spec_build | workspace root | pins_found, import_edges, promoted/blocked counts |
| P6 cross_library | source dirs | total_nodes, total_edges, num_components |
| P7 projection | workspace root | import_edges, lineage_edges, orphan_atoms, libraries_found |
| P8 task_planning | `.py` files + gap intentions | planning_result |
| P9 implementation | workspace root | files_analyzed, gaps_remaining |
| P10 continuous_qa | everything | strategies_registered, refinement issues |

#### Manual Verification (NOT fuzzy scoring)

After each phase, READ the actual output and verify correctness yourself.
Do NOT rely on `score_detail_capture()` or any fuzzy scorer — it produces
false negatives. Compare phase output against ground truth requirements
manually, one by one.

---

## Phase 5: Production Hardening

Final iteration cycle. Run complete pipeline on real specs, identify and
fix remaining issues. Scale treasury spec complexity with parallel ground
truth.

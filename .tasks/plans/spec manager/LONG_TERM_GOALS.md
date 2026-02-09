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
* [x] 4 LLM agent definitions created (spec-intake-summarize, spec-intake-discover-libraries, spec-intake-route, spec-intake-coverage-filter)
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

#### Process per step

1. **Run the step** against the treasury spec in an isolated workspace
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
4. **When the step passes**, advance to the next step
5. **If a later step reveals a problem in an earlier step**, go back and
   fix the earlier step, then re-run all steps from that point forward

#### Anti-patterns (DO NOT)

* **DO NOT run all steps in one go** — you miss bugs that cascade
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

---

## Phase 3: Wire PDD Orchestrator to Real Modules (CURRENT)

**The Problem**: The PDD orchestrator phases 1-10 are thin scaffolding that
only does structural analysis (counting, classifying, building indexes).
The 11 plan modules are built and tested but the orchestrator doesn't USE
them. Phase 0 (intake) is the only phase that does real work.

### What Each Phase Does vs Should Do

| Phase | Currently Does | Should Do |
|-------|---------------|-----------|
| P0 intake | Routing-based restructuring via `intake/` | DONE CORRECTLY |
| P1 structure | Parses files, counts functions | Entry point for Plan 01 (Edit-in-Place) |
| P2 decomposition | Marks functions with comments | Plan 03 (Planning) - pseudocode insertion |
| P3 compliance | Counts gaps/stubs | Plan 05 (Gap Detection) + Plan 08 (Compliance Gating) |
| P4 library | Counts atoms/stores/shapes | Plan 02 (Pin-Functions) atom extraction |
| P5 spec_build | Writes pin registry (no promotion) | Plan 04 (Branch Org) - PromotionEngine |
| P6 cross_library | Builds adjacency graph | Plan 07 (Adjacency Detection) |
| P7 projection | Reads libraries.json (no drift) | Plan 09 (Lineage) + Plan 11 (Analysis Generator) |
| P8 task_planning | Counts plans/gaps/adjacencies | Plan 03 (Planning) - actionable plans |
| P9 implementation | Counts files (no edit-in-place) | Edit-in-Place Engine for code changes |
| P10 continuous_qa | Creates empty StrategyRegistry | Plan 10 (Strategy Evolution) |

### Design Violation

`_run_refinement_engine()` calls `executor.execute(op)` which MUTATES the
branch manager. Per design, the refinement engine is analysis-only for
cohesion/coupling of skeletons (libraries). It should NEVER execute mutations.

### Refinement Engine's Correct Role

* **Phase 0**: Proposes libraries = initial skeletons (via `intake/` module, DONE)
* **Between phases**: Analyzes cohesion/coupling of skeletons to inform regrouping
* **NEVER executes mutations**: Only analyzes and reports groupings

### Work

* [ ] Fix `_run_refinement_engine()` to be analysis-only (remove executor.execute calls)
* [ ] Wire P1 to use `core/edit_in_place.py` properly
* [ ] Wire P2 to use `planning/reverser.py` + `planning/inserter.py`
* [ ] Wire P3 to use `compliance/detection/orchestrator.py` + `compliance/promotion/`
* [ ] Wire P4 to use `pin_functions/orchestrator.py` for atom extraction
* [ ] Wire P5 to use `branches/promotion.py` for PromotionEngine
* [ ] Wire P6 to use `analysis/adjacency/runner.py` fully
* [ ] Wire P7 to use `projection/lineage/` + `analysis/generator.py`
* [ ] Wire P8 to use `planning/workflow.py` for actionable plans
* [ ] Wire P9 to use `core/edit_in_place.py` for code changes
* [ ] Wire P10 to use `strategies/evolution.py` for strategy evaluation
* [ ] Run full pipeline end-to-end against treasury spec
* [ ] All tests pass

## Phase 4: PDD Lifecycle Orchestration

Wire the 4-phase PDD model from `simpler.md` using existing plan
implementations. Most capabilities already exist as modules — the work
is orchestrating them into the lifecycle, not building from scratch.

### simpler.md's 4-Phase Model

**Phase 1 (Build)**: Research → sparse plan → worktree → implement in
parallel → block on ambiguity → POWER alignment → human review → approve

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

### What's Genuinely Missing (not in any plan)

* [ ] Worktree management (create worktree per library, parallel execution, cleanup)
* [ ] --auto mode orchestration (multi-model research: Opus + GPT + GLM + firecrawl)
* [ ] --interactive mode orchestration (ambiguity collection → report → user responds → integrate)
* [ ] POWER alignment check (Problem→Outcome→What→Evidence→References)
* [ ] Human review document generation
* [ ] Human approval loop (iterative adjustment until approval)

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

## Phase 5: Production Hardening

Final iteration cycle. Run complete pipeline on real specs, identify and
fix remaining issues. Scale treasury spec complexity with parallel ground
truth.

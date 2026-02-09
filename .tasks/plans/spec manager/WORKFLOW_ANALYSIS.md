# Workflow Analysis: What Exists vs What Was Intended

## Three Systems Currently Exist

### System A: Refinement Pipeline (19 phases, Design #1)
- Documented in `system-analysis3.md`
- 19 sequential phases from sectionization through implementation
- Uses GLM/Opus/ChatGPT agents throughout
- Processes PROSE specs → structured libraries → tasks → patches
- **Status**: Some phases implemented, but this was replaced by Design #2/3

### System B: PddOrchestrator (11 phases, Design #3)
- Lives in `orchestration/pdd_orchestrator.py`
- 11 phases: P0(extraction) → P1(structure) → ... → P10(continuous_qa)
- P0 processes prose specs (intake/)
- P1-P10 process PYTHON CODE with spec comments
- **Status**: Wired to real modules. We just ran P1-P10 against treasury.
- **Problem**: Phases are analysis/planning only. Nothing implements code.

### System C: PddLifecycle (4 phases, Design #2)
- Lives in `orchestration/pdd_lifecycle.py`
- 4 lifecycle phases: Build → QA → Architecture → Code Quality
- Build calls `PddOrchestrator.run()` as step 1, then refines, aligns, overviews
- **Status**: Implemented but never tested against treasury.
- **Problem**: Even this doesn't implement code. Creates worktrees but doesn't populate them.

---

## What We Actually Ran

```
Manual setup:
  1. Copied Phase 0 output + Python skeletons into workspace
  2. Called _install_phase0_output() to populate libraries/

Then ran PddOrchestrator phases 1-10:
  P1  structure    → found 8 .py files, 60 gaps                    ✓ analysis
  P2  decomposition → reversed 38 functions (all just "pass")       ✓ no-op
  P3  compliance   → 60 comment gaps + 38 stub gaps = 98           ✓ analysis
  P4  library      → 37 shapes, 0 atoms                            ✓ analysis
  P5  spec_build   → 37 pins, 37 promoted (empty shells)           ✓ no-op
  P6  cross_library → 39 disconnected nodes, 0 edges               ✓ analysis
  P7  projection   → 0 lineage, 37 orphans                         ✓ analysis
  P8  task_planning → 38 generic plans                              ✓ planning
  P9  implementation → 60 gaps remaining, gap report                ✓ analysis
  P10 continuous_qa → 0 strategies, no vertical slices              ✓ analysis

Result: Everything still comments. Nothing implemented. Nothing promoted meaningfully.
```

---

## What simpler.md Says Should Happen

### PDD Phase 1 (Build): The Full Flow

```
1. Research                          → gather evidence from spec
2. Sparse planning                   → what to implement, in what order
3. Create worktree                   → dirty root + clean sibling
4. Implement in parallel             → on worktree grandchildren, no dependency tracking
5. Block on ambiguity                → rebase, merge, return to step 1
6. POWER alignment check             → detect drift and reward hacking
7. Return to step 1 for patch        → iterate
8. Overview document                 → for human review
9. Human skims                       →
10. Human references misalignment    →
11. Return to step 1                 → for realignment
12. Human approves                   →
```

### PDD Phase 2 (QA)
Create evaluations → detect failures → root cause → return to Phase 1

### PDD Phase 3 (Architecture)
Proposals → analysis → choice → refactor

### PDD Phase 4 (Code Quality)
N reviewers → refactor → merge to main

---

## Mapping: Current Code → simpler.md Steps

| simpler.md Step | Current Code | Gap |
|----------------|-------------|-----|
| Research (evidence gathering) | `refinement/hollowed_spec/` exists | Never called during pipeline |
| Sparse planning | `planning/workflow.py` exists (P8) | Generates comment-placement plans, not impl plans |
| Create worktree | `WorktreeManager` exists | Created AFTER phases, should be BEFORE |
| Implement in parallel | **NOTHING** | No implementation engine exists |
| Block on ambiguity | `InteractiveWorkflow` exists | Called as batch step in lifecycle, not during impl |
| POWER alignment | `opus-alignment-checker` agent exists | Called in lifecycle build, never tested |
| Overview document | `opus-overview-writer` agent exists | Called in lifecycle build, never tested |
| Human approval | `build_with_approval()` exists | Called in lifecycle, never tested |
| QA evaluations | `EvalRunner` exists | Called in lifecycle QA, never tested with treasury |
| Architecture proposals | `opus-architecture-proposer` agent | Called in lifecycle architecture, never tested |
| Code quality reviewers | 4x `chatgpt-*-reviewer` agents | Called in lifecycle code_quality, never tested |

---

## Specific Divergences

### 1. Worktree Timing
- **simpler.md**: Step 3 — create worktree BEFORE implementing
- **Current**: Step 5 of lifecycle Build — AFTER all 11 inner phases complete
- **Impact**: Everything runs without isolation. No dirty/clean separation.

### 2. Implementation Engine Missing
- **simpler.md**: "Implement everything in parallel on worktree grandchildren"
- **Current**: No code writes code. P8 plans comment insertions. P9 reports gaps.
- **Impact**: The pipeline is purely analytical. It can never close gaps.

### 3. Library Refinement Duplication
- **System B** (orchestrator): `_run_refinement_engine()` — runs after P4+ as post-phase hook. Operates on CODE atoms for coupling/cohesion. Analysis-only.
- **System C** (lifecycle): `_refine_libraries()` — runs after all phases. Uses `InteractiveWorkflow` for SPEC ambiguity resolution on `spec.md` files.
- **These are different things** (code coupling vs spec ambiguity) but the naming is confusing.
- **Neither runs at the right time**: spec refinement should happen during implementation (per simpler.md "continuous spec refinement should actually be done during implementation").

### 4. Spec-Level Quality After Phase 0
- **simpler.md**: "Between libraries detect overlap... Isolate all concerns"
- **Current**: Phase 0 produces libraries. No spec-level quality check runs immediately after.
- **Impact**: Library boundaries from Phase 0 go unvalidated until code phases run.

### 5. Phase 0 as Special Case (Correct)
- Phase 0 transforms uncontrolled prose → controlled spec format
- This IS the right approach per simpler.md's description
- Once Phase 0 completes, we have Analysis/Constraints/Overview/Details per library
- The question is: what runs NEXT? Not P1-P10 analysis of empty code.

### 6. Approval Loop Never Exercised
- `build_with_approval()` has approve/feedback/quit UI
- We ran inner pipeline directly, skipping the lifecycle entirely
- The approval loop was never tested

### 7. Research Algorithm Never Used
- `ResearchCoordinator` exists for --auto mode
- Meant to run Opus + GPT + GLM + firecrawl for ambiguity resolution
- Never triggered during our QA run

### 8. Ground Truth Missing for Later Phases
- Treasury ground truth covers: library discovery + 52 requirements
- No ground truth for: architecture decisions, code quality, implementation correctness
- Phases 3-4 of lifecycle have nothing to evaluate against

---

## P1-P10: What They're Actually For

Looking at what each phase does and what input it needs:

| Phase | Designed For | Our Input | Result |
|-------|-------------|-----------|--------|
| P1 structure | Analyzing EXISTING code | Empty skeletons | Found structure of empty code |
| P2 decomposition | Reversing IMPLEMENTED code to pseudocode | `pass` stubs | Reversed `pass` to `process pass` |
| P3 compliance | Finding gaps in PARTIALLY implemented code | 100% gaps | Confirmed everything is a gap |
| P4 library | Extracting algorithms/stores from CODE | Empty code | Found shapes only |
| P5 spec_build | Mapping code constructs to spec pins | Empty code | Promoted empty shells |
| P6 cross_library | Finding connections between code modules | Isolated stubs | Found 0 connections |
| P7 projection | Tracing code back to spec | Empty code | Found 0 lineage |
| P8 task_planning | Planning insertions based on gaps | 98 gaps | Generated generic plans |
| P9 implementation | Reporting remaining gaps + applying plans | Everything is a gap | Reported all gaps |
| P10 continuous_qa | Evolving strategies based on progress | No progress | Nothing to evolve |

**Conclusion**: P1-P10 are designed for analyzing EXISTING brownfield code, not for building from specs. They're useful when you HAVE code and want to verify it against specs. They're useless when you have specs and want to CREATE code.

---

## What Should Actually Happen After Phase 0

Per simpler.md, after we have structured specs (Phase 0 output):

```
1. Validate library quality (overlap, isolation, cohesion/coupling on SPECS)
2. Create worktree (dirty root + clean sibling)
3. For each library, create grandchild worktree
4. Implement library code in parallel (LLM agents)
   - Each agent gets: library spec (algorithms.md, constraints.md, stores.md, analysis.md)
   - Agent writes implementation code
   - Agent blocks on ambiguity → resolved via research or user input
5. Merge grandchild → parent → run tests on clean sibling
6. POWER alignment check on implementation vs spec
7. Generate overview → human review → approve
8. QA evals (does implementation match spec?)
9. Architecture review (is the code well organized?)
10. Code quality review (is the code clean?)
```

P1-P10 would then be useful AFTER step 4 to VERIFY the implementation:
- P1: Parse the now-implemented code
- P2: Reverse-translate to verify intent preservation
- P3: Find remaining gaps
- P6: Verify cross-library connections match spec
- P9: Report any remaining gaps
- P10: Assess overall quality

---

## Next Steps

1. **Document the intended end-to-end workflow** as a clear sequence
2. **Decide**: Should PddOrchestrator and PddLifecycle merge?
3. **Identify what's missing**: Implementation engine (the actual code-writing step)
4. **Fix ordering**: Worktrees before implementation, spec quality after Phase 0
5. **Build ground truth**: Architecture and code quality expectations for treasury
6. **Test the lifecycle**: Run `PddLifecycle.run()` against treasury, not just orchestrator

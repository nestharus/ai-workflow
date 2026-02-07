# Spec Manager: Long-Term Goals

## Phase 1: Consolidation & Implementation (COMPLETE)

Make sure everything is implemented correctly, nothing is extra, and
consolidate/remove old processes.

**Expected state when done**: See `EXPECTED_STATE.md`

**Completed**

* [x] Extract shared infrastructure from refinement/ to core/ (8 modules extracted)
* [x] Delete legacy dead code (workflow/, workspace/, staging/, discovery/, merging/, verification/)
* [x] Remove remaining cross-contamination (schemas→refinement, compliance→refinement)
* [x] Verify all PDD modules are complete and match their plans (11 plans + 5 refactors)
* [x] All CLI commands work (spec + spec-manager entry points)
* [x] Clean up dead imports, orphaned code, unused re-exports
* [x] All 700 tests pass

## Phase 2: QA & Eval Debugging (COMPLETE)

Run QA with evals on each step to debug the entire process.

**Findings**: See `PHASE2_QA_FINDINGS.md`

**Completed**:
* [x] Run eval framework step-by-step through each phase
* [x] Check for hardcoding and reward hacking in tests — assessed as acceptable mock patterns
* [x] Check for actual bugs, failures, and friction points
* [x] Fix eval stagnation bug (false cycling detection for single-pass phases)
* [x] Fix contract lint (0 errors, was 44 — scoped checks + missing agents)
* [x] Create missing agent definitions (2 agents for library review workflow)
* [x] All 700 tests pass

## Phase 3: Full E2E Eval (CURRENT)

Run a complete end-to-end evaluation and score it.

**Target**: 100% score from the LLM judge
**Baseline**: Raw LLMs get 87% capture and 100% precision
**Current**: 97.2% recall, 100% precision (last eval before stagnation fix)

**Work**:
- Run fresh eval to see actual recall without false stagnation bottlenecks
- Investigate the 2-5% recall gap (genuine single-pass misses)
- Run full e2e eval pipeline with LLM judge scoring
- Fix any remaining issues
- Iterate until 100% judge score

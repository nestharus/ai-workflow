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

## Phase 2: QA & Eval Debugging (CURRENT)

Run QA with evals on each step to debug the entire process.

**Work**:
- Run eval framework step-by-step through each phase
- Check for hardcoding and reward hacking in tests (solutions must be general)
- Check for actual bugs, failures, and friction points
- Check for scores that are way too low
- Fix issues found at each step before moving on
- Use LLM judge system (added for treasury spec evaluation) to score quality

## Phase 3: Full E2E Eval

Run a complete end-to-end evaluation and score it.

**Target**: 100% score from the LLM judge
**Baseline**: Raw LLMs get 87% capture and 100% precision

**Work**:
- Run full e2e eval pipeline
- Score with LLM judge
- Fix any remaining issues
- Iterate until 100% judge score

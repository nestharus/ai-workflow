# Spec Manager: Long-Term Goals

## Phase 1: Consolidation & Implementation (CURRENT)

Make sure everything is implemented correctly, nothing is extra, and
consolidate/remove old processes.

**Expected state when done**: See `EXPECTED_STATE.md`

**Work**:
- Extract shared infrastructure from refinement/ to core/ (gap types, agent_utils, evidence pointers — DONE)
- Delete legacy dead code (workflow/, workspace/, staging/, discovery/, merging/, verification/ — DONE)
- Remove remaining cross-contamination (schemas→refinement, compliance→refinement)
- Verify all PDD modules are complete and match their plans
- Verify refinement pipeline works correctly as-is (it IS the active system)
- Clean up any extras, dead imports, or orphaned code
- Ensure all tests pass and are testing real behavior

## Phase 2: QA & Eval Debugging

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

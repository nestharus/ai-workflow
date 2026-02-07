# Phase 2: QA & Eval Findings

## Current Eval Scores

Latest full 8-spec eval (eval_510d9318):

| Spec | Recall | Precision | F1 | Bottlenecks |
|------|--------|-----------|-----|-------------|
| ackermann_function | 95.7% | 100% | 97.8% | summarization:stagnation |
| collatz_extended | 97.7% | 100% | 98.9% | summarization:stagnation |
| complex_recurrence | 100% | 100% | 100% | - |
| fibonacci_modular | 95.5% | 100% | 97.7% | summarization:stagnation |
| lucas_numbers | 94.7% | 100% | 97.3% | summarization:stagnation |
| prime_sieve | 97.1% | 100% | 98.5% | summarization:stagnation |
| sylvester_sequence | 95.0% | 100% | 97.4% | summarization:stagnation |
| tribonacci | 95.5% | 100% | 97.7% | summarization:stagnation |
| **Overall** | **97.2%** | **100%** | **98.6%** | |

**Target**: 100% recall, 100% precision

---

## Issue 1: Summarization Stagnation (BLOCKING 100%)

**Severity**: HIGH - blocks 100% target
**Files**: `refinement/workflows/summarization.py`, `refinement/evals/runner.py`, `refinement/evals/loop_detector.py`

**Root Cause**: Architectural mismatch between the eval framework and the summarization phase.

- The eval framework (`runner.py`) iterates phases expecting iterative improvement
- Summarization is a single-pass phase (calls agent once per file, no retry)
- On iteration 2+, the eval reads the same disk state as iteration 1
- Same state hash -> detected as stagnation/cycling@2

**Impact**: 2-5% recall lost per spec because the agent misses some expected items on the single pass, and there's no mechanism to retry or refine.

**Fix Options**:
1. Add iterative refinement to summarization (prompt agent with feedback)
2. Skip iteration for single-pass phases in eval framework
3. Improve agent prompting to capture more on first pass
4. Lower fuzzy matching threshold (currently 0.8 for phase evals)

---

## Issue 2: Test Hardcoding (4 HIGH, 4 MEDIUM)

### HIGH Severity

1. **test_eval_sparse_to_dense.py:101-122** - Mocks both `InteractiveWorkflow.__init__` and `.run()` with fakes. `fake_run` returns hardcoded string. Tests the mock, not the workflow.

2. **test_coordinator_with_evidence_store.py:65,83** - Injects hardcoded JSON into mock, asserts result contains it. Tautological.

3. **test_interactive_workflow_with_resolver.py:58-74** - Patches AmbiguityDetector.detect_signals while testing workflow. Can't verify actual signal detection pipeline.

4. **test_phase_resolver.py:38-45** - Mocks `pr._detector.detect_signals` while testing PhaseResolver. Tests half-mocked flow.

### MEDIUM Severity

5. **test_branch_lifecycle.py:29-54** - Fixtures locked to exact function counts.
6. **test_signal_resolver.py:60-74** - `assert result is expected` after mocking (tautology).
7. **test_hooks.py:41-59** - Half-real half-mocked filesystem integration.
8. **test_signal_resolver.py:154-174** - Mock-returns-mock assertion.

All HIGH issues are in `tests/refinement/interactive/` — the interactive workflow test suite.

---

## Issue 3: Contract Lint Errors (44 errors)

**Files**: Various agent definition files in `.agents/agents/`

- 42 errors: Agent prompts missing required ID format examples
- 2 errors: Missing agent files (`chatgpt-library-boundary-judge.md`, `opus-library-split-planner.md`)

These affect LLM output quality — agents without ID format examples may produce malformed IDs.

---

## Issue 4: Missing Agent Definitions

**Severity**: MEDIUM
**Files**: Referenced in `refinement/workflows/` but not found in `.agents/agents/`:
- `chatgpt-library-boundary-judge.md`
- `opus-library-split-planner.md`

These agent definitions are needed for the library review (Phase 7) workflow.

---

## Priority Order

1. **Summarization stagnation** - Only thing preventing 100% on evals
2. **Test hardcoding (HIGH)** - Tests pass but exercise nothing
3. **Missing agent definitions** - Blocks full workflow execution
4. **Contract lint errors** - Degrades LLM output quality
5. **Test hardcoding (MEDIUM)** - Tests partially functional

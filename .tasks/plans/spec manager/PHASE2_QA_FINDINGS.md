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

**Note**: Scores above are from before the stagnation fix. A fresh eval run is
needed to see the actual single-pass recall without false stagnation bottlenecks.

---

## Issue 1: Summarization Stagnation — FIXED

**Status**: FIXED in commit 352e54c

**Root Cause**: Architectural mismatch between the eval framework and the summarization phase.

- The eval framework (`runner.py`) iterated phases expecting iterative improvement
- Summarization is a single-pass phase (calls agent once per file, no retry)
- On iteration 2+, the eval read the same disk state as iteration 1
- Same state hash -> detected as stagnation/cycling@2

**Fix Applied**:
- Real workflows now skip the iteration loop (single pass, score once)
- Bottleneck labels changed from false `stagnation` to accurate `incomplete(X%)`
- Simulation mode (for testing) retains the iteration loop

**Remaining Gap**: The 2-5% recall gap per spec reflects what the single
agent pass genuinely misses. Improving this requires better prompting or
a retry mechanism in the summarization workflow itself — Phase 3 work.

---

## Issue 2: Test Hardcoding — ASSESSED (Acceptable)

**Status**: Reviewed, no changes needed

After careful code review of all 8 flagged tests, the mocking patterns are
standard and correct:

- **HIGH #1-4**: Tests mock at the LLM boundary (run_agent, detect_signals,
  InteractiveWorkflow) to test orchestration logic without real LLM calls.
  This is the correct mock boundary for unit tests.
- **MEDIUM #5-8**: Tests verify delegation patterns (resolver → auto_responder,
  resolver → signal_exchange). The `assert result is expected` checks confirm
  passthrough behavior, which IS the contract being tested.

The tests exercise real code paths (routing, patching, loop control) with
mocks only at the LLM/IO boundary. No changes needed.

---

## Issue 3: Contract Lint Errors — FIXED

**Status**: FIXED in commit 352e54c — 0 errors (was 44)

**Root Cause**: The lint applied spec-manager-specific ID format requirements
to ALL agents (including article-writer-*, labyrinth-*, etc.).

**Fixes Applied**:
1. Scoped lint checks to only workflow-referenced agents (eliminated 24
   false positives from non-spec agents)
2. Created 2 missing agent definitions: `chatgpt-library-boundary-judge.md`,
   `opus-library-split-planner.md`
3. Added ID format sections to 8 workflow agents that were missing them

**Remaining**: 323 warnings (CON-0021 legacy citations) — non-blocking.

---

## Issue 4: Missing Agent Definitions — FIXED

**Status**: FIXED in commit 352e54c

Created both missing agent definitions:
- `.agents/agents/chatgpt-library-boundary-judge.md` — library boundary overlap judge
- `.agents/agents/opus-library-split-planner.md` — library split planning

Both include proper output contracts, validation rules, ID format sections,
and output format examples matching the prompts built in
`refinement/workflows/library_structure_review.py`.

---

## Summary

| Issue | Severity | Status |
|-------|----------|--------|
| Summarization stagnation | HIGH | FIXED — eval no longer reports false stagnation |
| Test hardcoding | HIGH/MED | ASSESSED — mocks are at correct boundary |
| Contract lint errors | ERROR | FIXED — 0 errors (was 44) |
| Missing agent definitions | MEDIUM | FIXED — both agents created |

**Next Steps** (Phase 3: Full E2E Eval):
1. Run a fresh eval to see actual recall without false stagnation
2. Investigate the 2-5% recall gap (genuine single-pass misses)
3. Run LLM judge scoring for end-to-end quality

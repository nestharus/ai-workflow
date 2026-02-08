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
* [x] Phase 0 extraction design (format-aware intake, coverage tracking, pre-structured input, classifier design)
* [x] PDD orchestrator (phases 0-10) with Phase enum
* [x] CLI exposes PDD operations as primary commands (run, phase, extract)
* [x] Eval framework supports PDD and refinement pipelines (--pdd default, --refinement flag)
* [x] Continuous library refinement engine (detector, operations, executor)
* [x] Infrastructure integration (signal resolver, ambiguity detection, evidence search)
* [x] LLM judge scorer for semantic eval scoring
* [x] All 721 tests pass

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

## Phase 3: Treasury Eval (CURRENT)

Run a complete end-to-end evaluation against the chaotic treasury spec
and score it.

**Target**: 100% score from the LLM judge
**Eval target**: `chaotic_treasury.yaml` (30 rules, 6 libraries, complexity 9)
**Baseline**: Raw LLMs get 87% capture and 100% precision
**Previous**: 97.2% recall (refinement pipeline, toy math fixtures — meaningless)

### Phase 0 extraction: IMPLEMENTED

Phase 0 extraction converts prose specs to PDD workspace format.
Implementation: `spec_manager/orchestration/extraction.py` (ProseExtractor)

**Current eval scores (fuzzy matching at 0.6 threshold):**
- **Sectionization**: 100% recall, 100% precision (7/7)
- **Summarization**: 66.7% recall (4/6) — 2 need LLM summarization
- **Library synthesis**: 83.3% recall (30/36) — vocabulary mismatches
- **Spec building**: 83.3% recall (25/30) — split requirements, vocabulary
- **Overall**: 83.5% recall, 33.5% precision

Remaining gap to 100% requires LLM judge (already implemented, needs API access):
- Vocabulary mismatches ("bypasses" vs "allow to proceed")
- Split requirements (two facts in one sentence → one match consumed)
- Library descriptions need LLM-level topic summarization

### Treasury spec complexity scaling

Instead of evaluating Workflow Engine 3 (which cannot be scored — no
ground truth exists), scale the treasury spec to capture WE3's failure
modes:
- Multi-file web with cross-references
- Invariant trap examples (MUST that are really algorithms)
- Format diversity (Mermaid, YAML, inline JSON, pseudocode)
- Scattered requirements across sections
- Implicit constraints requiring inference

**Ground truth scales in parallel** — every new rule/constraint must have
a corresponding expected output. Spec and ground truth are written
together, not sequentially.

### Reward hacking prevention

During treasury eval iteration, the spec manager's own code could game
scores by adding stopwords, TF-IDF weights, NLP heuristics, or fuzzy
matching tricks. Red flags:
- Adding stopword lists or TF-IDF weighting
- NLP-based fuzzy matching for extraction
- Confidence thresholds that can be tuned to match ground truth
- Any statistical/probabilistic approach to classification

PDD resists this by design (mechanical/AST-based, not statistical).
Strategy evolution must NOT access eval ground truth.

### Work

- [x] Implement Phase 0 extraction (prose → PDD format)
- [x] Run treasury eval with Phase 0 + PDD pipeline (83.5% recall)
- [x] Improve fuzzy matching with token containment scoring
- [x] Add normative patterns for settlement dates (T±N), written-out durations
- [x] LLM judge scorer infrastructure (implemented, needs API access to test)
- [ ] Run eval with --judge flag (requires LLM API access)
- [ ] Iterate until 100% judge score
- [ ] Scale treasury spec complexity with parallel ground truth
- [ ] Re-iterate at higher complexity

## Phase 4: Production Hardening

Final iteration cycle. Run complete pipeline on treasury spec, identify
and fix remaining issues.

# Current State Assessment (Feb 10 2026)

## What Has Been Evaluated with Real LLM Calls

### Phase 0 (Intake): FULLY EVALUATED
- Fixture: `chaotic_treasury_expanded` (10 source .md files)
- Results: 100% section coverage, 7/8 library discovery, 52/52 requirements, 100% line coverage
- Output saved: `fixtures/chaotic_treasury_expanded_phase0_output/`

### PDD Phases 1-10 at L1 (Library Level): FULLY EVALUATED
- Fixture: `chaotic_treasury_expanded_pdd/` (8 Python files, 60 spec comments)
- P1-P8: Analysis phases, all pass (no file modifications)
- P9 (Implementation): 38/38 functions, 0 errors, 0 gaps
- P10 (Continuous QA): No grouping units, passes
- 6 bugs found and fixed during P9 eval (see MEMORY.md)

### Architecture Proposer (OLD Pipeline Only)
- The `qa_clean_013` run used the **legacy 19-phase refinement pipeline**
- Produced architecture proposals/selection/mapping
- This was the OLD flat model, NOT the new L1→L2→L3 layer model
- State: summarization→library_synthesis→evidence_expansion→spec_building→
  sublibrary_detection→architecture_proposal→architecture_selection→architecture_mapping
- Stopped at interfaces (never reached implementation)

## What Has Been Implemented (Structurally Complete)

### L2/L3 Layer-Aware PromotionLoop Steps: IMPLEMENTED (Feb 10 2026)

All 6 PromotionLoop steps now dispatch by `ctx.layer` (L1/L2/L3):

| Step | L1 (unchanged) | L2 (Architecture) | L3 (Clean Code) |
|------|----------------|-------------------|-----------------|
| **GapExploration** | P3 compliance scan | LLM architecture continuity gaps (unconsumed pins, missing components, missing handlers, logic in arch files, manifest drift) | 4 quality reviewers (clarity/completeness/consistency/correctness), findings = gaps |
| **Plan** | Function implementation intentions | Wiring intentions (`layer_constraint: wiring_only`) | Refactor intentions grouped by file, MINOR first (`layer_constraint: refactor_only`) |
| **Implement** | ImplementationRunner (P9) | Architectural assembler via LLM (no business logic) | Clean-code refactorer via LLM (no behavior change) |
| **Analyze** | SourceAnalysisCache (P1+P2) | LLM architecture graph (components/edges/stats) | Simple file metrics (line count, function count) |
| **Promote** | LayerPromotionGate (5 L1 gates) | LLM evaluates 8 L2 gates (behavior_change→L1, wiring_only→retry) | Quality gaps check + diff-impact classifier (behavior_change→L1, wiring_only→L2) |
| **Verify** | Governance + cross-library + lineage | Governance + pin consumption + topology + manifest drift | Governance + reviewer closure + no-logic-change + drift |

### VerifyStep: FULLY IMPLEMENTED (Feb 10 2026)

Replaced the stub with ~120 lines of layer-aware verification:
- Governance check via `pipeline-oversight-enforcer` agent (fail closed)
- Layer-specific verification (L1/L2/L3 branches)
- Finding→DemotionTicket triage using deterministic rules
- Persists `verify.notes.json` to iteration directory
- BLOCKER or (tickets + MAJOR) → RETRY with emitted tickets

### Canonical Finding Schema: IMPLEMENTED (Feb 10 2026)

Added to `orchestration/evidence.py`:
- `Finding` dataclass with: dimension, category, severity, location, evidence, required_change_type, suggested_fix, confidence, tags
- `to_dict()` and `from_dict()` serialization
- Used by all reviewers, gates, and VerifyStep

### Demotion Triage: UPDATED (Feb 10 2026)

Updated `orchestration/demotion/triage.py`:
- `required_change_type` as highest-priority routing (behavior_change→L1, wiring_only→L2, refactor_only→fix-in-layer)
- All L2 gates (8) and L3 gates (5) added to gate routing table
- New categories: MAINTAINABILITY, GOVERNANCE (block in layer), CORRECTNESS, INLINE_LOGIC_AT_ARCH
- `triage_finding()` convenience function for Finding dicts

### L2 Slice Discovery: UPDATED (Feb 10 2026)

`_discover_slices("l2")` now checks `reports/component_manifest.json` first for component-based slices, falls back to per-library wrappers.

### End-to-End Pipeline Prompt: UPDATED (Feb 10 2026)

`.tasks/plans/spec manager/.research/end-to-end-pipeline/prompt.md` fully rewritten to reflect all implemented step semantics, concrete scoring dimensions, and more specific remaining questions.

## What Has NEVER Been Evaluated (With Real LLM Calls)

1. **The full `pdd_lifecycle.run()` pipeline** — never run end-to-end
2. **L2 PromotionLoop** — step implementations exist but never run with real LLM
3. **L3 PromotionLoop** — step implementations exist but never run with real LLM
4. **Cross-layer transitions** (`_run_transition()`) — demotion propagation never tested
5. **Worktree management in multi-layer mode** — `setup_layers()` never tested with real git
6. **No final output document** — no accuracy/precision/architecture quality/code quality scores
7. **No end-to-end scoring framework** for L2/L3 output quality

## Open Design Questions (End-to-End Pipeline)

Research prompt written and awaiting response: `.tasks/plans/spec manager/.research/end-to-end-pipeline/prompt.md`

Remaining questions:
- Layer activation and CI (passive CI on upper layers while active layer creates)
- Batch promotion mechanics (how multiple slices merge to dirty→clean)
- Demotion rework during transitions (narrow slices vs full re-run)
- Human approval points (after L1 only? After each layer?)
- Termination criteria and infinite-loop prevention
- Final output artifacts and format
- Scoring dimensions, thresholds, and hard gates vs soft signals
- Ground truth for L2/L3 (too subjective? reference implementation?)
- Test strategy per layer (integration tests at L2? regression at L3?)
- Recovery from test failures (Investigator agent? DemotionTickets?)
- Worktree merge conflict resolution strategy
- Governance integration points beyond VerifyStep

## Key Agent Definitions (All Exist)
- `opus-architecture-proposer.md` — architecture proposals + L2 gap/gate/implement
- `chatgpt-clarity-reviewer.md` — code quality (clarity)
- `chatgpt-completeness-reviewer.md` — code quality (completeness)
- `chatgpt-consistency-reviewer.md` — code quality (consistency)
- `chatgpt-correctness-reviewer.md` — code quality (correctness) + L3 implement
- `opus-alignment-checker.md` — POWER alignment (drift/reward hacking)
- `opus-overview-writer.md` — human review document generation
- `pipeline-oversight-enforcer` — governance in VerifyStep

## Next Steps

1. Get end-to-end pipeline research response (user takes prompt to external model)
2. Implement pipeline orchestration (scoring, CI, recovery, termination)
3. Run end-to-end eval on treasury spec through L1→L2→L3

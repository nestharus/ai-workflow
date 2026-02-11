# Research: End-to-End Pipeline, Final Output, and Scoring

## What I Need From You

I need the design for the end-to-end pipeline execution, final output format, and scoring framework. The L1→L2→L3 layer semantics are now fully implemented (steps are layer-aware, VerifyStep is real, compliance gates exist per layer). What remains is:

1. How the complete pipeline orchestrates these layers end-to-end
2. What the final deliverable looks like
3. How quality is measured and scored
4. How CI, recovery, and governance work across layers

---

## What Exists and Works

### Pipeline Flow (implemented in `pdd_lifecycle.py`)

```text
Raw Prose → Phase 0 (Intake) → PDD Skeletons (Libraries)
  → Library Refinement (L1 entry)
  → L1 per-slice PromotionLoop (parallel, via PromotionScheduler)
  → Library Refinement (L1 exit)
  → Human approval loop (overview + POWER alignment → approve/feedback/quit)
  → Architectural Refinement (L1→L2 transition, may demote to L1)
  → Propagate L1 clean → L2 dirty
  → Architectural Refinement (L2 entry)
  → L2 per-slice PromotionLoop (parallel)
  → Architectural Refinement (L2 exit)
  → Code Quality Refinement (L2→L3 transition, may demote to L2/L1)
  → Propagate L2 clean → L3 dirty
  → Code Quality Refinement (L3 entry)
  → L3 per-slice PromotionLoop (parallel)
  → Code Quality Refinement (L3 exit)
  → QA eval → main
```

### PromotionLoop Step Semantics (NOW IMPLEMENTED per layer)

Each step dispatches by `ctx.layer`. The 10 steps per slice:

```text
COLLECT → GAP → PLAN → IMPLEMENT → UNDER_SPEC → ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN → DONE?
```

**L1 (Code-as-Spec):**
- Gap = spec comments + stub functions (P3 compliance)
- Plan = function implementation intentions
- Implement = fill function bodies via ImplementationRunner (P9)
- Analyze = SourceAnalysisCache (P1 + P2)
- Promote = LayerPromotionGate (5 gates: NO_REMAINING_COMMENTS, NO_STUB_FUNCTIONS, ALL_TESTS_PASS, CALL_GRAPH_CONNECTED, STORE_MONOGAMY)
- Verify = governance + cross-library connectivity + lineage

**L2 (Architecture):**
- Gap = architecture continuity gaps via LLM (unconsumed pins, missing components, missing handlers, logic in arch files, manifest drift)
- Plan = wiring plan (component_id, target_files, approach, acceptance_criteria, layer_constraint=wiring_only)
- Implement = architectural assembler (create/adjust entrypoints, connect pins, add handlers; must NOT invent business logic)
- Analyze = LLM architecture graph (components, entrypoints, pins, edges, dependencies)
- Promote = LLM evaluates 8 gates (NO_INLINED_ATOM_LOGIC, FUNCTION_RECOMPOSITION, PIN_CONSUMPTION_COVERAGE, EDGE_REALIZATION, NO_ORPHAN_COMPONENTS, EVENT_HANDLER_COVERAGE, CONFIG_EXTERNALIZATION, ARCH_DRIFT_PASS). Gate failures demote: behavior_change→L1, wiring_only→retry L2
- Verify = governance + pin consumption + topology + manifest drift

**L3 (Clean Code):**
- Gap = quality closure gaps = run 4 reviewers (clarity, completeness, consistency, correctness), findings are gaps
- Plan = refactor plan grouped by file, smallest safe refactors first, "no behavior change" acceptance criteria
- Implement = clean-code refactorer (targeted refactors); logic changes emit demotion
- Analyze = simple file metrics (line count, function count)
- Promote = check open quality gaps (demote logic→L1, arch→L2) + diff-impact classifier (behavior_change→L1, wiring_only→L2)
- Verify = governance + reviewer closure + no-logic-change + drift

### Canonical Finding Schema (implemented in `evidence.py`)

```python
@dataclass
class Finding:
    dimension: str       # ARCH_BOUNDARY, PIN_COVERAGE, CLARITY, CORRECTNESS, DRIFT, GOVERNANCE
    category: str        # style | maintainability | architecture | logic | drift | governance
    severity: str        # BLOCKER | MAJOR | MINOR
    location: dict       # {file, symbol?, start_line?, end_line?}
    evidence: str
    required_change_type: str  # refactor_only | wiring_only | behavior_change | spec_change
    suggested_fix: str
    confidence: float
    tags: list[str]
```

### Demotion Triage (implemented in `demotion/triage.py`)

Priority: required_change_type > category > gate > source > default (L1).
- `behavior_change` → L1
- `wiring_only` → L2
- `refactor_only` → fix-in-layer (no demotion)
- `GOVERNANCE` category → block in current layer
- Layer constraint: target cannot be above active layer

### Slice Discovery (implemented in `pdd_lifecycle.py`)

- L1: one slice per library (concern boundary)
- L2: one slice per component from `component_manifest.json` (produced by architectural refinement), fallback to per-library wrappers
- L3: one slice per code file (finding clusters handled internally by reviewers)

### What Has Been Evaluated

- Phase 0 intake: 100% coverage on treasury spec (52/52 requirements)
- P1-P10 sequential at L1: 38/38 functions, 0 errors
- These were single-pass, not iterative loops
- L2 and L3 steps are structurally wired but have NEVER been run with real LLM calls

### What Has NOT Been Tested End-to-End

1. The full `pdd_lifecycle.run()` pipeline
2. Cross-layer transitions with demotion rework
3. Worktree management in multi-layer mode
4. Batch promotion mechanics (dirty→clean→next layer)
5. Recovery from test failures
6. Final output/scoring

---

## Questions About End-to-End Execution

### Q1: Layer Activation and CI

The pipeline runs layers sequentially. But WORKFLOW_ANALYSIS describes upper layers running CI passively while the active layer does creative work.

For the implemented sequential model:
- Is it sufficient that code flows L1 clean → L2 dirty → ... via `propagate_clean_to_next_layer()`?
- Or do we need an explicit CI verification step after propagation to confirm the code is runnable before L2 creative work starts?
- When L2 finds issues and demotes to L1, should L2 wait for L1 rework to complete, or should it continue with other slices?

### Q2: Batch Promotion Mechanics

The worktree pipeline has: slice→dirty, dirty→clean (with tests), clean→next layer.

Concretely:
- When multiple slices finish at L1, do they merge to dirty one at a time or in a batch?
- What test suite runs on the dirty→clean promotion? (Per-slice unit tests? Cross-library integration tests? Full suite?)
- If dirty→clean promotion fails, how does the system identify which slice caused the failure?
- Should `tick_pipeline()` be called after each slice, or batch-style after all slices complete?

### Q3: Demotion Rework During Transitions

`_run_transition()` currently re-runs the previous layer's slices on demotion. But:
- For tickets targeting a specific file/function, should we create a new narrow slice instead of re-running the entire library?
- After L1 rework from L2 demotion, does L1→L2 propagation repeat? Or does the rework merge directly to L2 dirty?
- Is there a loop limit on transition demotions? (e.g., L2 transition demotes 3 times, then what?)

### Q4: Human Approval

Currently `_run_l1_with_approval()` runs after L1 with max 3 iterations. Should approval also happen:
- After L2 completes (review architecture before code quality)?
- After L3 completes (final signoff)?
- Or is single approval after L1 sufficient (L2/L3 are automated quality gates)?

### Q5: Termination and Loop Limits

Per-layer termination = `open_gaps == 0` (PromotionLoop convergence). But:
- What is the max_iterations per slice per layer? (Currently 20 — is this enough for L2/L3?)
- What happens when a layer's exit refinement produces new demotions that create new gaps?
- How do we prevent infinite cycling: L1 fix → L2 demotion → L1 fix → L2 demotion → ...?
- Should there be an overall pipeline iteration limit (entire L1→L2→L3 restarts)?

---

## Questions About Final Output

### Q6: What Artifacts Should the Pipeline Produce?

After `pdd_lifecycle.run()` completes, what should exist in the workspace?

Candidates:
- **Working code**: L3 clean merged to main
- **Evidence trail**: All EvidenceBundle JSONs from all iterations
- **Architecture graph**: Component manifest + topology from L2 analysis
- **Quality report**: All reviewer findings and their resolution status
- **Traceability matrix**: Spec requirement → library → function → tests
- **Alignment report**: POWER alignment results per library
- **Demotion history**: All tickets, resolution status, hop traces
- **Human overview**: Generated by `opus-overview-writer`
- **Scoring summary**: Per-layer and overall quality scores

Which are essential for MVP? Which can wait?

### Q7: Human Review Document

The `opus-overview-writer` generates overview.md per library. For the final output:
- Should there be a single consolidated document covering the entire pipeline run?
- Should it include: executive summary, design decisions, architecture topology, quality scores, areas of concern, traceability?
- Should it embed or reference the POWER alignment results?
- Is this the same as the L1 approval document, or a separate final document?

---

## Questions About Scoring

### Q8: Scoring Dimensions

Now that gates and findings are defined per layer, scoring can be concrete. Proposed dimensions:

**Per-layer mechanical scores (from gate/finding counts):**
| Dimension | Layer | Computation |
|-----------|-------|-------------|
| Requirement coverage | L1 | % of spec comments resolved |
| Implementation completeness | L1 | % of functions with non-stub bodies |
| Gate pass rate | L1 | % of gates passing on first attempt |
| Pin utilization | L2 | % of promoted pins consumed by components |
| Component completeness | L2 | % of manifest components with implementations |
| Architecture gate pass rate | L2 | % of 8 L2 gates passing on first attempt |
| Reviewer pass rate | L3 | % of files passing all 4 quality reviewers |
| Demotion rate | L3 | % of findings requiring demotion (lower = better) |
| Refactoring churn | L3 | Lines changed / total lines (lower = less invasive) |

**Cross-layer scores:**
| Dimension | Computation |
|-----------|-------------|
| Overall demotion count | Total tickets emitted across all layers |
| Iteration efficiency | Total iterations / total slices (lower = better planning) |
| POWER alignment | Drift findings + reward hacking findings |

Are these the right dimensions? Should we add LLM-as-judge scores (e.g., "rate this architecture 1-10")?

### Q9: Score Computation and Thresholds

For each dimension:
- Is it computed mechanically from gate/finding counts (preferred), or via LLM-as-judge?
- What are reasonable pass/fail thresholds? (e.g., 90% requirement coverage = PASS)
- Should thresholds be hard gates (pipeline blocks) or soft signals (warnings)?
- Phase 0 eval showed LLM fuzzy matching produces false negatives — should we avoid LLM scoring for counts?

### Q10: Ground Truth for L2/L3

Phase 0 has ground truth for expected libraries and requirements. For L2/L3:
- Can we define ground truth for expected architecture? (e.g., "treasury spec should produce 3 services with event-driven communication")
- Or is L2/L3 too subjective for ground truth, and we rely on gate convergence?
- Could we use a "reference implementation" as ground truth instead of explicit assertions?

### Q11: Production Scores vs Eval Scores

The PromotionLoop already uses gate results to decide pass/fail/demotion. Are separate "scores" needed?
- Production: gate results ARE the scores (binary pass/fail per gate)
- Eval: aggregate gate results + iteration counts into a summary report
- Should the EvalRunner compute these summary scores, or should `pdd_lifecycle.run()` itself produce them?

---

## Questions About CI and Recovery

### Q12: Test Strategy

At L1, tests validate individual atoms. At L2/L3:
- L2: What tests run? Integration tests that verify component wiring? Service-level tests?
- L3: Regression suite (all L1+L2 tests) to confirm refactoring preserved behavior?
- Cross-layer: Should ALL lower-layer tests run at each layer? (L2 runs L1+L2 tests; L3 runs L1+L2+L3 tests)
- If the target codebase has no tests yet, does the pipeline generate them?

### Q13: Recovery from Test Failures

When `IntegrateStep` fails (merge conflict or test failure):
- Currently emits a DemotionTicket and returns RETRY
- The Investigator agent pattern is designed for exactly this: reproduce failure in isolated worktree, fix, produce root cause + patch
- Should IntegrateStep failures trigger the Investigator before creating a DemotionTicket?
- Or should the Investigator be invoked by DownwardFlowEngine as part of the demotion chain?

### Q14: Worktree Merge Conflicts

During L1→L2 propagation and L2 demotion rework:
- Can conflicts arise between L1 clean and L2 dirty? (If L2 has made wiring changes and L1 rework changes the same files)
- Should conflicts be resolved by: LLM merge agent? Prefer lower layer (L1 clean wins)? Block and escalate?

### Q15: Governance Integration

Pipeline Oversight Enforcer is now integrated into VerifyStep (runs at every iteration, per slice). Is this sufficient, or should governance also run:
- At layer transitions (L1→L2, L2→L3)?
- On the final output (before merge to main)?
- On the human review document?

---

## What I Need Back

For each question, provide:
1. Your recommended answer
2. Brief rationale (1-3 sentences)
3. Design implications for other questions

Also provide:
1. A **complete pipeline execution flow** from Phase 0 input to final merged output, with decision points and loop limits
2. A **final output specification** listing all artifacts and their format
3. A **scoring framework** with dimensions, computation methods, thresholds, and whether each is a hard gate or soft signal
4. A **CI flow** showing how worktrees, tests, and promotions compose, with conflict resolution strategy
5. **Termination criteria** — per-layer and overall, including infinite-loop prevention
6. A **recovery flow** showing when the Investigator agent is invoked vs when DemotionTickets are created
7. A **governance model** showing when/where Pipeline Oversight Enforcer runs beyond VerifyStep

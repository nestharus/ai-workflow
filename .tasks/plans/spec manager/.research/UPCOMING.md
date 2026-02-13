# Upcoming Research Prompts

Write these AFTER the prior response. Use the actual
implementation to inform the prompt.

## 1. Planning Module Architecture — DONE (response received)

## 2. QA Eval Architecture with Planner — DONE (implemented)

* Full eval package: ground_truth, trace_loader, scorers, reporter, harness, export_gt
* Planner enhanced: override_provider, model_id, auto-persist, decision_key, index.jsonl
* 204 new tests, all passing (3063 total)
* Prompt: `.research/qa-eval-architecture/prompt.md`
* Response: `.research/qa-eval-architecture/response.md`

## 3. Scoring and Multi-Model Comparison — DONE (implemented)

* 4 Pydantic judge schemas + JudgeClient + JudgeCache + 4 judge modules
* Digests, snapshot, QualityReporter, ModelProfile, CostLedger
* MultiModelRunner, ComparisonRunner (canonical alignment + pairwise)
* 170 new tests, all passing (3233 total)
* Prompt: `.research/scoring-multi-model/prompt.md`
* Response: `.research/scoring-multi-model/response.md`

## 4. Agent Coordination, Reactive Planner & JIT Monitors — DONE (implemented)

* New package: `orchestration/coordination/` (6 modules, 145+ tests)
* CoordinationSignal + WorkItemStore (3-stage search) + WakeQueue + WaitGraph
* MonitorSpec (declarative JSON DSL) + MonitorRegistry + MonitorExecutor
* ReactivePromotionScheduler (WAITING support, monitor thread, wake events)
* CoordinateStep replaces UnderSpecCheckStep for L1
* 22 new tests, all passing (3255 total)
* Prompt: `.research/agent-coordination/prompt.md`
* Response: `.research/agent-coordination/response.md`
* Context: `.research/agent-coordination/context.zip` (16 files)

## 5. Constraint Reasoning, Architectural Planning & Decision Authority — READY

* Planner constraint reasoning: problem understanding, constraint discovery,
  implied constraints, non-software constraint dimensions
* Architectural planning: fractal scoped proposals (intra-library, inter-library),
  multiple proposers with tradeoff hints, pick-and-choose composition
* Decision authority: when to decide autonomously vs. surface to humans
* Intake classification expansion (beyond binary CONSTRAINTS/DETAIL)
* Constraint flow: forward/backward propagation through pipeline layers
* Prompt: `.research/constraint-reasoning/prompt.md`
* Context: `.research/constraint-reasoning/context.zip` (37 files)
* Includes full design foundations: 6 constraint principles, tradeoffs, 7 patterns

## 6. Intent Ingest — User-Facing Intent Agent & Question Queue — READY

* Single user-facing Intent Agent mediates ALL user interaction
* Intent understanding: discover real problem, not just capture spec text
* Question queue: prioritized, reassessed on answer, deduplicated
* Signal flow: internal agent questions → Intent Agent → user → constraints → wake
* Skeleton output: constraints + patterns + tradeoffs + high-level functions with TODO prose
* Problem redefinition loop: as understanding deepens, confirm with user
* Session persistence: resume context across sessions
* Phase 0 relationship: subsume, wrap, or coexist
* Alpha interface for entire pipeline lifecycle
* Prompt: `.research/intent-ingest/prompt.md`
* Context: `.research/intent-ingest/context.zip` (31 files)
* Builds on: RP4 (coordination signals), RP5 (constraint reasoning + question composition)

## 7. Model Routing Refinement (if needed)

* Refine routing based on QA eval results
* Tune which models for which tasks based on actual performance
* Depends on: QA eval results

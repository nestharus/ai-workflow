# System Overview

## What spec_manager Is

spec_manager is a multi-agent system that transforms specifications into
implemented code through iterative promotion across quality layers. It
implements Prototype Driven Development (PDD) — building code and spec in
parallel, where each phase produces something messy and the next phase
cleans it up.

The core insight: **code IS the spec**. PDD skeleton files (class/function
signatures with spec comments and `pass` bodies) are simultaneously the
structured specification and the code. When you "implement," you fill in the
same files that ARE the spec.

---

## Package Inventory

### Core Infrastructure

| Package | Purpose |
|---------|---------|
| `core/` | Shared utilities — edit_in_place, JSON extraction, code fence stripping |
| `schemas/` | Pydantic models and JSON schemas for all data structures |

### Intake Pipeline (Phase 0)

| Package | Purpose |
|---------|---------|
| `intake/` | 5-step routing pipeline: summarize, discover, route, coverage, assemble |
| `intake/quality/` | Library quality validator (5-dimension scoring) |

### PDD Modules (Phases 1-10)

| Package | Purpose |
|---------|---------|
| `planning/` | Code parser, reverser, workflow planning |
| `compliance/` | Gap detection, promotion gating, entity coverage |
| `branches/` | Library collapse, atom extraction, promotion |
| `pin_functions/` | Pin-function scanning and orchestration |
| `analysis/` | Adjacency analysis, graph building, analysis generation |
| `projection/` | Lineage tracking, import graph, projection generation |
| `strategies/` | Strategy evolution pipeline |

### Orchestration

| Package | Purpose |
|---------|---------|
| `orchestration/` | PDD lifecycle, promotion loop, run state management |
| `orchestration/implementation/` | ImplementationRunner + types |
| `orchestration/under_spec/` | Under-specification blocking + constraints store |
| `orchestration/demotion/` | Demotion triage, routing, ledger |
| `orchestration/downward_flow/` | DownwardFlowEngine (pin tracing for demotion) |
| `orchestration/architecture/` | Architectural assembly agent |
| `orchestration/coordination/` | Agent coordination (signals, work items, monitors, wake queue, wait graph) |
| `orchestration/review/` | Review findings to demotion tickets |

### Planner

| Package | Purpose |
|---------|---------|
| `planner/` | Planning API, router, auto-persist, TRIAGE_SIGNAL |
| `planner/layers/` | L1, L2, L3 layer-specific planners |
| `planner/tools/` | Research, integration, constraints, evidence tools |
| `planner/jit/` | Micro-state-machine for planning decisions |

### Refinement & Workspace

| Package | Purpose |
|---------|---------|
| `refinement/` | Refinement engine (analysis-only, coupling/cohesion) |
| `refinement/workspace/` | WorkspaceManager, state management |
| `refinement/interactive/` | Interactive workflow, ambiguity resolution |
| `refinement/hollowed_spec/` | Hollowed-out spec evidence gathering |

### Eval Framework

| Package | Purpose |
|---------|---------|
| `refinement/evals/` | EvalRunner, fixtures, workflow integration |
| `refinement/evals/planner/` | Planner eval (ground truth, trace loader, 5 scorers, reporter, harness) |
| `refinement/evals/judges/` | Judge infrastructure (client, cache, 4 judge modules, pairwise) |

### Quality & Comparison

| Package | Purpose |
|---------|---------|
| `orchestration/scoring.py` | RunReporter + Scorecard (5 hard gates, 6 soft signals) |
| `orchestration/quality_scoring.py` | QualityReporter + QualityScorecard |
| `orchestration/model_profile.py` | ModelProfile (role-based model routing) |
| `orchestration/cost_ledger.py` | CostLedger + LLMCallRecord |
| `orchestration/multi_model_runner.py` | MultiModelRunner |
| `orchestration/comparison.py` | ComparisonRunner (canonical alignment + pairwise) |
| `orchestration/digests.py` | Architecture and code digest generation |
| `orchestration/snapshot.py` | Run snapshot creation |

### VCS & Worktrees

| Package | Purpose |
|---------|---------|
| `orchestration/vcs.py` | VcsOperations Protocol + GitVcs implementation |
| `orchestration/worktree_manager.py` | Dirty/clean/grandchild worktree hierarchy |

---

## Data Flow

```text
                        External Spec (prose markdown)
                                    |
                            [Phase 0: Intake]
                        summarize -> discover ->
                        route -> coverage -> assemble
                                    |
                        PDD Skeleton Files (code-as-spec)
                                    |
                    +---------------+----------------+
                    |               |                |
                [L1: Build]   [L2: Arch]      [L3: Quality]
                per-library   per-component   per-file
                worktrees     assembly        refinement
                    |               |                |
                    +-------+-------+--------+-------+
                            |                |
                    [Promotion Loop]   [Demotion Chain]
                    10-step state      all the way down
                    machine per slice  to code-as-spec
                            |
                        [Main Branch]
                    Production-ready code
```

### Phase 0 (Optional): Raw Prose -> PDD Skeletons

Only runs when input is unstructured prose. Produces PDD skeleton files
organized into libraries. If input is already PDD-formatted code, Phase 0
is skipped and processing starts at L1.

### L1: Code-as-Spec (Build Phase)

Working authority. Per-library worktrees. ImplementationRunner fills in
function bodies. CoordinateStep handles cross-slice dependencies. 5
compliance gates enforce quality before promotion.

### L2: Architecture (Assembly Phase)

Derived from L1 promotion via pin-functions. Assembles services, events,
middleware from promoted atoms. 8 LLM-evaluated gates.

### L3: Clean Code (Quality Phase)

Derived from L2 promotion. N quality reviewers enforce standards. Refactoring
must not change logic (logic changes trigger demotion to L1). Merges to main.

---

## Test Coverage

3255 tests across all packages (as of Feb 11, 2026). Includes:

* Unit tests per module
* Component tests for orchestration flows
* Eval framework tests with ground truth fixtures
* Coordination infrastructure tests (145+)

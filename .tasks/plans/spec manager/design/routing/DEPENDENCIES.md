# Cross-System Dependencies

Import-based dependency graph for spec_manager packages.

**Last updated**: Feb 12, 2026

---

## Dependency Matrix

Arrows show `FROM → TO` (package on left imports package on top).

```
                core  schemas  refine  orch  compl  proj  branch  plan  strat  analysis  cmtplan  intake  pin_fn  cohesion  vcs  eval
core              -      4       1      -      -     -      -      -      -       -        -        -       -       -       -     -
schemas           4      -       -      -      -     -      -      -      -       -        -        -       -       -       -     -
refinement       44     26       -      4      2     2      2      2      1       1        -        -       -       -       -     -
orchestration     6      1       7      -      2     1      -      3      1       1        1        1       2       1       1     1
compliance       16     11       -      1      -     3     10      -      -       -        -        -       -       -       -     -
projection        5     12       -      -      -     -      -      -      -       -        -        -       -       -       -     -
branches          2      2       1      -      2     -      -      -      -       1        -        -       -       -       -     -
planner           -      -       1      3      -     -      -      -      -       -        -        -       -       -       -     -
strategies       17      -       1      -      -     -      -      -      -       -        -        -       -       -       -     -
analysis          3      3       -      -      -     -      -      -      -       -        -        -       -       -       -     -
cmtplan           6      -       -      -      -     -      -      -      -       -        -        -       -       -       -     -
intake            4      -       4      -      -     -      -      -      -       -        -        -       -       -       -     -
pin_functions     1      2       -      -      -     2      -      -      -       -        -        -       -       -       -     -
cohesion          -      -       1      -      -     -      1      -      -       2        -        -       -       -       -     -
vcs               1      -       -      -      -     -      -      -      -       -        -        -       -       -       -     -
eval              1      -       2      1      1     -      -      -      -       -        -        -       -       -       -     -
```

---

## Hub Analysis

**Most depended-on** (in-degree = number of packages importing from):
1. `core` — 12 consumers (universal foundation)
2. `schemas` — 9 consumers (shared data models)
3. `refinement` — 7 consumers (execution engine)
4. `orchestration` — 4 consumers (pipeline coordinator)
5. `compliance` — 3 consumers
6. `projection` — 3 consumers

**Least depended-on** (0 external consumers):
- `decomposition` — isolated

---

## Bidirectional Dependencies

These package pairs import from each other (circular). All are
mitigated by lazy imports within function bodies.

| Pair | Total imports | Nature |
|------|-------------|--------|
| `core` ↔ `schemas` | 8 | Schemas use core data structures |
| `orchestration` ↔ `planner` | 6 | Coordinator ↔ decision-maker |
| `orchestration` ↔ `refinement` | 11 | Orchestrator ↔ executor |
| `compliance` ↔ `branches` | 12 | Gates need atoms, atoms need compliance |
| `planner` ↔ `refinement` | 3 | Planner needs output type info |
| `branches` ↔ `refinement` | 3 | Branch mgmt uses refinement output |
| `core` ↔ `refinement` | 45 | Highest coupling (expected: utilities ↔ primary user) |

---

## Data Flow (Primary Pipeline)

```
User Input
    │
    v
intake (Phase 0)
    │
    v
orchestration.PddLifecycle.run()
    │
    ├──> L1: planner.layers.l1 ──> refinement (implementation)
    │         │                          │
    │         v                          v
    │    compliance.promotion       orchestration.evidence
    │         │                          │
    │         v                          v
    ├──> L2: planner.layers.l2 ──> orchestration.architecture
    │         │
    │         v
    ├──> L3: planner.layers.l3 ──> refinement (code quality)
    │
    v
evaluation.report
evaluation.quality
```

---

## Bottleneck Points

These are single points through which most work flows:

1. **`orchestration.promotion_loop.PromotionLoop`** — all slice work
2. **`planner.api.Planner`** — all planning decisions
3. **`refinement.workspace.WorkspaceManager`** — all file I/O
4. **`orchestration.evidence.EvidenceBundle`** — all audit trails
5. **`core.agent_utils.run_agent()`** — all LLM calls

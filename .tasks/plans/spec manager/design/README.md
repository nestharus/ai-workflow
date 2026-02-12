# Spec Manager Design

Architecture documentation and design principles for the spec_manager system.

**Last updated**: Feb 12, 2026

---

## Directory Layout

```text
design/
├── README.md                              # This file
├── TRADEOFFS.md                           # Priority ordering and decision framework
├── constraints/                           # Fundamental principles (primary reference)
│   ├── 00_PROPORTIONAL_COMMITMENT.md      # Commit proportionally to knowledge
│   ├── 01_INFORMATION_PERMANENCE.md       # Information is permanent, computation is temporary
│   ├── 02_SOURCE_AUTHORITY.md             # Authority decreases with derivation distance
│   ├── 03_ERROR_AMPLIFICATION.md          # Error cost grows with propagation distance
│   ├── 04_COUPLING.md                     # Coupling through internals amplifies fragility
│   └── 05_FRACTAL_SCOPING.md             # Work at smallest scope, compose results
├── patterns/                              # Core algorithms (recurring problem solvers)
│   └── CORE_PATTERNS.md                   # 7 reusable algorithms for design decisions
├── overview/                              # Architecture overviews (how the system works)
│   ├── 00_SYSTEM_OVERVIEW.md              # Package inventory + data flow
│   ├── 01_PIPELINE_ARCHITECTURE.md        # Promotion loop, layer pipeline, coordination
│   └── 02_EXTERNAL_BOUNDARIES.md          # Inputs, outputs, LLM call sites, file I/O
└── routing/                               # Per-package routing summaries (WHERE things live)
    ├── INDEX.md                           # Master index with classification + dependency tiers
    ├── DEPENDENCIES.md                    # Cross-system dependency graph + bottlenecks
    ├── orchestration.md                   # Structural: PDD lifecycle, promotion loop, coordination
    ├── planner.md                         # Business: decision authority, layers, strategies
    ├── refinement.md                      # Business: workspace, evals, judges, evidence store
    ├── compliance.md                      # Business: coverage, detection, promotion gates
    ├── projection.md                      # Structural: lineage, drift, pin propagation
    ├── analysis.md                        # Business: adjacency, restructuring suggestions
    ├── branches.md                        # Structural: multi-branch atom/slice management
    ├── intake.md                          # Business: Phase 0 prose-to-spec routing
    ├── core.md                            # Utility: agent utils, code analysis, gaps, IDs
    ├── schemas.md                         # Utility: 40+ Pydantic data models
    ├── pin_functions.md                   # Business: pin extraction and registration
    ├── strategies.md                      # Business: reasoning strategy framework
    ├── comment_planning.md                # Business: algorithmic planning (comment insertion)
    ├── cohesion.md                        # Business: coupling/cohesion refinement
    ├── vcs.md                             # Structural: version control, worktree management
    ├── evaluation.md                      # Business: quality scoring, model comparison, reporting
    └── auxiliary.md                       # Mixed: decomposition, labyrinth
```

## What Goes Where

* **TRADEOFFS.md**: What the system prioritizes and what it sacrifices.
  Lexicographic priority ordering (fidelity > robustness > diagnosability
  > efficiency > speed) and a decision framework for resolving conflicts.

* **constraints/**: WHY the system works this way. Six fundamental
  principles from which all design decisions derive. Each file states the
  principle, explains why it's true, and shows the corollaries that follow
  from it. No class names, no module paths, no implementation details.

* **patterns/**: HOW the system solves recurring problems. Reusable
  algorithms that classify problem types and prescribe solutions. When you
  encounter a design problem, match it to a pattern. No class names, no
  module paths — just the abstract algorithm and the reasoning behind it.

* **overview/**: WHAT the system is and HOW it works. Package inventory,
  data flow diagrams, class names, module paths. These describe the current
  implementation.

* **routing/**: WHERE things live. Per-package routing summaries with
  classification (structural/business/utility), surface APIs, dependencies,
  and consumers. Use these to find which module handles what. Start with
  `INDEX.md` for the master index and `DEPENDENCIES.md` for the cross-system
  dependency graph.

## Reading Order

1. `TRADEOFFS.md` — Start here. What the system optimizes for, the
   priority ordering, and the decision framework.
2. `constraints/00_PROPORTIONAL_COMMITMENT.md` — The foundational
   principle: explore the problem space before committing to a solution,
   and commit only as specifically as your knowledge justifies.
3. `constraints/01_INFORMATION_PERMANENCE.md` — The asymmetry between
   information (permanent when lost) and computation (re-runnable).
4. `constraints/02_SOURCE_AUTHORITY.md` — Why authority decreases with
   derivation distance.
5. `constraints/03_ERROR_AMPLIFICATION.md` — Why errors must be caught
   early.
6. `constraints/04_COUPLING.md` — Why components interact through
   contracts, not internals.
7. `constraints/05_FRACTAL_SCOPING.md` — Why problems are solved at the
   smallest self-contained scope and composed.
8. `patterns/CORE_PATTERNS.md` — 7 algorithms for recurring design
   problems.
9. `overview/00_SYSTEM_OVERVIEW.md` — What the system actually is.
10. Remaining overview files as needed for specific topics.

## Authoritative Sources

These source documents in the parent directory are the origin of all
design principles:

| Source | What It Defines |
|--------|----------------|
| `LONG_TERM_GOALS.md` | Core design principles, QA methodology, eval strategy |
| `WORKFLOW_ANALYSIS.md` | Promotion model, pipeline architecture, demotion |
| `simpler.md` | PDD lifecycle, iteration philosophy, worktree hygiene |
| `ALGORITHM.md` | Evidence preservation, semantic framework |

## Historical Note

The `clean/`, `analysis/`, and `templates/` directories were removed in
a prior update. They contained Design #1 (evidence preservation model)
artifacts superseded by the current PDD implementation. See git history
for removed content.

The previous 8-file constraint structure (00-07, organized by domain)
was replaced by the current 6-file structure (organized by fundamental
principle). The domain-specific constraints were corollaries of the 6
fundamental principles and are now presented as such within each file.

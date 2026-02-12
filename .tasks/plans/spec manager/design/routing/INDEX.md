# Routing Index

Master index for all spec_manager systems. Use this to find where
functionality lives and route work to the correct module.

**Last updated**: Feb 12, 2026

---

## Quick Classification

| Package | File | Classification |
|---------|------|----------------|
| `orchestration/` | [orchestration.md](orchestration.md) | Structural (core pipeline) |
| `planner/` | [planner.md](planner.md) | Business (decision authority) |
| `refinement/` | [refinement.md](refinement.md) | Business (execution engine) |
| `compliance/` | [compliance.md](compliance.md) | Business (quality gates) |
| `projection/` | [projection.md](projection.md) | Structural (lineage + drift) |
| `analysis/` | [analysis.md](analysis.md) | Business (adjacency + restructuring) |
| `branches/` | [branches.md](branches.md) | Structural (multi-branch management) |
| `intake/` | [intake.md](intake.md) | Business (Phase 0 routing) |
| `core/` | [core.md](core.md) | Utility (shared primitives) |
| `schemas/` | [schemas.md](schemas.md) | Utility (shared data models) |
| `pin_functions/` | [pin_functions.md](pin_functions.md) | Business (pin extraction) |
| `strategies/` | [strategies.md](strategies.md) | Business (reasoning strategies) |
| `comment_planning/` | [comment_planning.md](comment_planning.md) | Business (algorithmic planning) |
| `cohesion/` | [cohesion.md](cohesion.md) | Business (coupling/cohesion) |
| `vcs/` | [vcs.md](vcs.md) | Structural (version control) |
| `evaluation/` | [evaluation.md](evaluation.md) | Business (quality assessment) |
| `auxiliary/` | [auxiliary.md](auxiliary.md) | Mixed (decomposition, labyrinth) |

Cross-system dependency graph: [DEPENDENCIES.md](DEPENDENCIES.md)

---

## Dependency Tiers

**Tier 1 — Foundation** (no spec_manager dependencies):
- `core/` — shared utilities, code analysis, gap structures, ID generation
- `schemas/` — 40+ Pydantic data models

**Tier 2 — Specialized Systems** (depend on Tier 1 only):
- `projection/` — lineage, import graphs, drift detection
- `analysis/` — adjacency graphs, restructuring suggestions
- `comment_planning/` — algorithmic comment insertion, reverse translation
- `strategies/` — reasoning strategy framework
- `pin_functions/` — pin extraction and registration
- `vcs/` — version control abstraction, worktree management
- `decomposition/` — spec decomposition (isolated)

**Tier 3 — Business Logic** (depend on Tier 1 + Tier 2):
- `intake/` — Phase 0 prose-to-spec routing
- `compliance/` — coverage gaps, executable gaps, promotion gates
- `refinement/` — workspace, evidence indexing, evals, judges
- `cohesion/` — coupling/cohesion refinement
- `evaluation/` — quality scoring, model comparison, reporting
- `branches/` — multi-branch atom/slice management

**Tier 4 — Orchestration** (depends on everything):
- `planner/` — decision authority (layers, tools, JIT, constraints, architecture)
- `orchestration/` — PDD lifecycle, promotion loop, coordination, demotion

---

## Communication Patterns

**Synchronous** (direct function calls): All inter-package communication
uses direct imports. Circular dependencies are mitigated by lazy imports
within function bodies.

**Asynchronous** (file-based signals):
- `CoordinationSignal` → `signals.json` in iteration directories
- `WorkItemStore` → `work_items.jsonl` + `index.json`
- `EvidenceBundle` → immutable audit trail per slice/iteration

**Shared State**:
- `WorkspaceManager` — all file I/O coordination
- `RunStateManager` — run config + metadata

# Design Analysis: Evidence-Preservation Reorganization (ALGORITHM.md)

## Core Thesis

- Never rewrite or summarize source material
- Operate directly on evidence lines
- Build an index/evidence-graph mapping evidence ranges ↔ entities
- Reorganize by moving exact line ranges into a component/taxonomy folder structure

## Strengths (Accuracy)

- Strongest non-loss posture:
  - evidence is always verbatim
  - coverage verification is explicit (Phase 10)
  - annotations are a second-stage check (evidence → annotation coverage)
- Entity-centric evidence graph enables:
  - “show me all evidence for X”
  - many-to-many evidence membership
- Explicit treatment of:
  - coupling/clustering
  - invariants and identity resolution
  - candidate tradeoffs and convergence loop (Phase 9)

## Weaknesses / Failure Modes

- Physical “move line ranges” is operationally expensive:
  - evidence that discusses multiple entities requires either duplication or complex referencing
  - line boundaries are not always the correct semantic split; forcing a line-range split can entangle topics
- Assumes early availability of entity types and flows:
  - entity type lists (Ticket/Project/Task/...) are domain-specific and effectively hardcoded
- Clustering and topology steps depend on:
  - tokenization and reference detection heuristics (risk under no-hardcoding constraint)
- Does not define a strict contract system:
  - no schema validation for extraction outputs
  - no quarantine mechanism for invalid outputs
- “No rewrite ever” is safe but can block usability:
  - implementers need coherent specs; pure evidence is hard to execute against
  - decisions/tradeoffs created during refinement become “new evidence”; requires an explicit authority model

## What the Hybrid Takes

- Evidence layer as canonical truth (L0)
- Evidence graph as first-class structure
- Coverage verification as a hard invariant
- Convergence loop framing:
  - unknowns, tradeoffs, risks, ambiguous evidence become explicit gaps/tasks
- Store monogamy and explicit interface edges as boundary discipline

## What the Hybrid Changes

- Evidence is not physically moved as the primary mechanism:
  - evidence is referenced via atom IDs; “materialization” is a projection
- Entity discovery is LLM-driven and local-pattern-based (no keyword heuristics on raw input)
- Derived spec elements exist (L1) but are always grounded in evidence atoms

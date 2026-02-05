# Design Analysis: LLM-First Pipeline Prototype (simpler.md)

## Core Thesis

- Specs contain many local patterns; no uniform structure can be assumed
- LLMs are the best mechanism for recognizing local patterns
- Use multiple models for different strengths:
  - summarization/selection
  - planning/pattern recognition
  - detail tracking and audits
- Partition the spec into “libraries”, then refine, design architecture, and implement bottom-up
- Use brute-force audits with powerful models when necessary

## Strengths

- Correctly identifies the primary constraint for arbitrary specs:
  - structure must be inferred locally, not via regex/templates
- Emphasizes model specialization and judge-based verification
- Architecture exploration is explicit and iterative
- Implementation planning focuses on minimizing dependency edges and handling cycles

## Weaknesses / Failure Modes

- Summarization-first is inherently lossy unless paired with a hard evidence layer:
  - “what summary” can omit edge-case details that later become critical
- No formal atom-level provenance:
  - difficult to prove nothing was dropped
  - difficult to trace an implementation choice back to exact lines
- Lacks a strict authority model:
  - projections, summaries, and derived specs can drift without detection
- Relies on “strong model audits” as the main safety net:
  - audits without deterministic coverage constraints can still miss omissions

## What the Hybrid Takes

- LLM-first for local structure inference (sectionization, entity recognition, decomposition)
- Multi-model role separation and escalation policy
- Architecture-candidate exploration + tradeoff judging
- Bottom-up implementation with explicit dependency negotiation

## What the Hybrid Adds

- Immutable evidence atoms + mandatory coverage accounting
- Derived specs are always grounded in atoms (traceability)
- Compliance gates + quarantine for invalid artifacts
- Drift detection and non-authoritative projections

# ADR-001 — Model Routing Infrastructure Selection
Status: Accepted
Date: 2025-12-30
Supersedes: None
Superseded-by: None

## Context
- Links: (GOAL-01, GOAL-04, COM-06, ROUTE-02, CLASS-04)
- Drivers: (INV-01, ROUTE-02, MET-01, MET-04)

The complexity router (COM-06) requires a local model for fast ambiguity classification to reduce cost and latency. The previous infrastructure used SmolLM 360M via Ollama. With changes to the orchestration harness (switching to OpenCode), model availability and performance characteristics have changed.

## Decision
- Use Ministral 3B 2512 Instruct via Ollama for prompts <=2500 characters, with GLM 4.7 (z-ai/glm-4.7) as fallback for larger prompts.

## Options considered
- Option A — SmolLM 360M (previous): Local Ollama model, very fast but limited context
- Option B — Ministral 3B 2512 Instruct + GLM 4.7 fallback (selected): Better quality classification with tiered routing
- Option C — GLM 4.7 only: Higher quality but increased latency for small prompts

## Consequences
- Positive:
  - Better classification accuracy for ambiguity scoring
  - Handles larger prompts via GLM 4.7 fallback
  - Maintains low latency for common cases (<=2500 chars)
  - Compatible with OpenCode orchestration harness
- Negative:
  - Slightly higher resource usage than SmolLM 360M
  - Requires GLM 4.7 API access for fallback cases

## References
- PRD: [requirements.md](../requirements.md) (ROUTE-02, CLASS-04, INV-01)
- Design Map: [design-map.md](../design-map.md) (COM-06, OBL-02)
- Plan: [plan.md](../plan.md) (PHASE-01, TASK-01)

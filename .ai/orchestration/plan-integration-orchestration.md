---
description: (INTEGRATE) Integrates strategy artifacts into a concrete stepwise plan artifact via integration planners.
name: Plan Integration Orchestration (Integrate)
agent: agent
tools: ['editFiles', 'usages', 'githubRepo']
model: Claude Opus 4.5 (Preview)
---

# Plan Integration Orchestration (INTEGRATE)

## Inputs (provided by caller)
- intent.md
- acceptance_criteria.md
- constraints.md
- strategy.md
- research_findings.md
- open_gaps.md
- pattern_pack.md (optional)
- repo_integration_map.md (optional)
- domain_structure_candidates.md (optional)

## Output (provided by caller)
- implementation_plan.md OR test_implementation_plan.md

---

## Step 1: Decompose into Planning Topics

CALL AGENT:
- `@planning-topic-decomposer` (Planner slice)
    - Reads acceptance_criteria.md + intent.md + strategy.md
    - Produces `planning_topics.md` with ordered list of focused topics
    - Each topic is a single coherent unit (one AC item, one feature slice, one integration point)

Output:
- `.tmp/create/implementation/20_planning/planning_topics.md`
- Receipt

Gate: `@pipeline-oversight-enforcer`

---

## Step 2: Iterative Plan Generation (one topic at a time)

For each topic in planning_topics.md, invoke the planner separately:

CALL AGENT (per topic, sequential):
- `@integration-planner` (Planner slice, integration)
    - Input: Single topic from planning_topics.md + all context artifacts
    - Reads existing implementation_plan.md (if exists)
    - Adds/updates plan section for THIS TOPIC ONLY
    - Writes updated plan back to implementation_plan.md

Wait for each planner invocation to complete before proceeding to the next topic.
Each pass refines the plan - later topics build on earlier ones.

After EACH topic:
- Validate plan structure (sequential numbering, required sections)
- If validation fails, re-run planner with feedback

Output (accumulative):
- `.tmp/create/implementation/20_planning/implementation_plan.md`
- Receipt per topic

Gate (after all topics): `@pipeline-oversight-enforcer`

---

## Step 3: Plan Review

CALL AGENTS:
- `@plan-structure-reviewer` (Artifact Reviewer slice, plan rules)
    - Ensures the plan is executable, ordered, and non-ambiguous
- `@pattern-plan-review` (Artifact Reviewer slice, pattern completeness)
    - Checks each plan step has Structures used + Code units
    - Checks side-effect boundaries are explicitly called out when external integrations exist
- `@plan-drift-reviewer` (Drift Reviewer slice)
    - Ensures plan covers acceptance criteria; gaps must be explicit

All produce receipts.
Gate: `@pipeline-oversight-enforcer`

---

## Why Iterative Per-Topic?

1. **Focused reasoning**: Each planner invocation handles ONE coherent topic, reducing cognitive load
2. **Accumulative refinement**: Later topics can reference/build on earlier plan sections
3. **Validation checkpoints**: Structure validated after each topic, catching errors early
4. **Traceable decisions**: Each topic's planning decisions are isolated in receipts
5. **Parallelization potential**: Independent topics could run in parallel (future optimization)

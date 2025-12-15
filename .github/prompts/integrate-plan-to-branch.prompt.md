---
description: INTEGRATE orchestration - Decomposes acceptance criteria into topics and iteratively integrates plans
---

# INTEGRATE Orchestration - Plan to Branch

Decomposes acceptance criteria into planning topics and iteratively invokes integration planners to build a concrete stepwise plan. Validates structure after each topic.

Input: `{{input}}` (strategy-artifact plan-type)

Format: `<strategy-artifact-path> <plan-type>`
Example: `.tmp/create/implementation/20_planning/strategy.md implementation`

## Orchestration Type

**INTEGRATE** - Transforms strategy artifacts into concrete executable plans through iterative integration planning.

## Prerequisites

- Strategy artifact must exist
- Plan type must be 'implementation' or 'test'
- Parent orchestration workspace with required context

## Reference

See `.ai/orchestration/plan-integration-orchestration.md` for complete orchestration design.

## Workspace Setup

All integration artifacts are created under `.tmp/integrate/`:

```
.tmp/integrate/
├── input/               # Strategy and context artifacts
├── planning/            # Planning topics decomposition
├── output/              # Generated implementation or test plans
└── 99_receipts/         # Agent receipts for pipeline oversight
```

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/integrate/{input,planning,output,99_receipts}
```

### Step 2: Parse Arguments

Extract strategy artifact path and plan type from input.

Validate plan type is 'implementation' or 'test'.

### Step 3: Gather Input Artifacts

Copy all required context artifacts to workspace:
- Strategy artifact
- Related context from parent workspace (intent, acceptance_criteria, constraints)
- Optional research artifacts if available

### Step 4: Decompose into Planning Topics

Invoke the planning topic decomposer using #agent to produce an ordered list of focused planning topics.

Each topic should be:
- A single coherent unit (one AC item, one feature slice, one integration point)
- Independent enough to plan separately
- Ordered to build on previous topics

Output: `.tmp/integrate/planning/planning_topics.md`

### Step 5: Validate Planning Topics

Verify planning_topics.md exists and has proper structure.

### Step 6: Iterative Plan Generation

For each topic in planning_topics.md, invoke integration planner separately using #agent:

**Important**: Wait for each topic's planner invocation to complete before proceeding to the next topic. This ensures later topics can build on earlier plan sections.

Instructions for planner:
1. Read all input artifacts for context
2. Read existing plan (if exists) to understand what has been planned
3. Focus ONLY on the current topic
4. Add/update plan sections for THIS TOPIC ONLY
5. Ensure plan steps have clear structures, code units, side-effect boundaries
6. Build on previous topics (if any)
7. Write updated plan to output directory
8. Write receipt

### Step 7: Validate Plan Structure After Each Topic

After each integration planner completes, validate the plan structure:
1. Find the first `---` separator (if exists)
2. Verify required headers appear in order
3. Verify plans are numbered sequentially with no gaps
4. If validation fails, re-run planner with feedback

### Step 8: Final Plan Review

After all topics are integrated, invoke plan reviewers using #agent references:
- plan-structure-reviewer
- pattern-plan-review
- plan-drift-reviewer

Aggregate findings. If any FAIL, provide feedback for plan refinement.

### Step 9: Pipeline Oversight Gate

Invoke pipeline oversight enforcer using #agent to verify:
1. All receipts exist
2. Planning topics decomposition is complete
3. Integration planner ran for each topic
4. Plan reviewers produced explicit pass/fail
5. No decision injection or suspicious patterns

### Step 10: Copy Output Plan

Copy the final plan to the parent orchestration workspace.

### Step 11: Final Report

Print summary including:
- Strategy artifact and plan type
- Topics decomposed and integrated
- Output plan location
- Receipts location
- Plan review result (PASS)

## Output

The command will output:
- Summary of integration process
- Number of topics processed
- Output plan location
- Review result

## Receipt Format

Every agent must write a receipt to `99_receipts/`:

Template: `99_receipts/<stage>__<agent>.md`

Required sections:
- Inputs used
- Outputs produced/modified
- Topic processed (integration planner only)
- Decisions made
- Deviations (required; "None" allowed)
- Assumptions
- Open questions / risks
- Next action recommended

## Error Handling

- If strategy artifact not found, report error and stop
- If planning topics decomposition fails, report error and stop
- If integration planner fails for a topic, report error and preserve workspace
- If plan validation fails, re-run planner with feedback (max 3 attempts per topic)
- If plan review fails, report findings and stop
- Always preserve workspace artifacts for debugging

## Why Iterative Per-Topic?

1. **Focused reasoning** - Each planner invocation handles ONE coherent topic
2. **Accumulative refinement** - Later topics build on earlier plan sections
3. **Validation checkpoints** - Structure validated after each topic
4. **Traceable decisions** - Each topic's planning isolated in receipts
5. **Parallelization potential** - Independent topics could run in parallel (future)

## Notes

- This is a sub-orchestration called by higher-level orchestrations
- The integration happens incrementally, topic by topic
- Each topic builds on the previous plan sections
- All decisions are tracked in receipts for audit

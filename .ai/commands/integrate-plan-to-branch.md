---
description: INTEGRATE orchestration - Decomposes acceptance criteria into topics and iteratively integrates plans
argument-hint: [strategy-artifact] [output-plan-type]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# INTEGRATE Orchestration Command - Plan to Branch

Decomposes acceptance criteria into planning topics and iteratively invokes integration planners
to build a concrete stepwise plan. Validates structure after each topic.

## Orchestration Type

**INTEGRATE** - Transforms strategy artifacts into concrete executable plans through iterative
integration planning.

## Reference

See `.ai/orchestration/plan-integration-orchestration.md` for complete orchestration design.

## Workspace Setup

All integration artifacts are created under `.tmp/integrate/`:

```bash
mkdir -p .tmp/integrate/{input,planning,output,99_receipts}
```

Required subfolders:
- `input/` - Strategy and context artifacts (intent, constraints, research)
- `planning/` - Planning topics decomposition
- `output/` - Generated implementation or test plans
- `99_receipts/` - Agent receipts for pipeline oversight

## Arguments

`$ARGUMENTS` format:
- `strategy-artifact` - Path to strategy document (required)
- `output-plan-type` - Type of plan to create: `implementation` or `test` (required)

Example:
```bash
.ai/commands/integrate-plan-to-branch.md .tmp/create/implementation/20_planning/strategy.md implementation
```

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/integrate/{input,planning,output,99_receipts}
```

### Step 2: Parse Arguments

Extract strategy artifact and plan type from `$ARGUMENTS`:

```bash
# Parse arguments
STRATEGY_PATH=$(echo "$ARGUMENTS" | awk '{print $1}')
PLAN_TYPE=$(echo "$ARGUMENTS" | awk '{print $2}')
```

Validate plan type:
```bash
if [ "$PLAN_TYPE" != "implementation" ] && [ "$PLAN_TYPE" != "test" ]; then
    echo "ERROR: Plan type must be 'implementation' or 'test'"
    exit 1
fi
```

### Step 3: Gather Input Artifacts

Copy all required context artifacts to workspace:

```bash
# Required inputs
cp "$STRATEGY_PATH" .tmp/integrate/input/strategy.md

# Copy related context (from parent orchestration workspace)
PARENT_WORKSPACE=$(dirname "$(dirname "$STRATEGY_PATH")")
cp "$PARENT_WORKSPACE/00_intake/intent.md" .tmp/integrate/input/
cp "$PARENT_WORKSPACE/00_intake/acceptance_criteria.md" .tmp/integrate/input/
cp "$PARENT_WORKSPACE/00_intake/constraints.md" .tmp/integrate/input/

# Optional research artifacts
if [ -f "$PARENT_WORKSPACE/10_research/research_findings.md" ]; then
    cp "$PARENT_WORKSPACE/10_research/research_findings.md" .tmp/integrate/input/
fi

if [ -f "$PARENT_WORKSPACE/10_research/open_gaps.md" ]; then
    cp "$PARENT_WORKSPACE/10_research/open_gaps.md" .tmp/integrate/input/
fi
```

### Step 4: Decompose into Planning Topics

Use the Task tool to invoke the planning topic decomposer:

```text
Task(subagent_type="planner", prompt="file:.tmp/integrate/input/acceptance_criteria.md
file:.tmp/integrate/input/intent.md
file:.tmp/integrate/input/strategy.md

## Decompose into Planning Topics

Analyze the acceptance criteria and strategy to produce an ordered list of focused planning topics.

Each topic should be:
- A single coherent unit (one AC item, one feature slice, one integration point)
- Independent enough to plan separately
- Ordered to build on previous topics

Output: .tmp/integrate/planning/planning_topics.md

Format:
```markdown
# Planning Topics

## Topic 1: [Topic Name]
- Acceptance criteria covered: [AC references]
- Dependencies: [None or references to previous topics]

## Topic 2: [Topic Name]
...
```

Write receipt to: .tmp/integrate/99_receipts/01_topic_decomposer.md")
```

### Step 5: Validate Planning Topics

Verify planning_topics.md exists and has proper structure:

```bash
if [ ! -f .tmp/integrate/planning/planning_topics.md ]; then
    echo "ERROR: Planning topics decomposition failed"
    exit 1
fi
```

### Step 6: Iterative Plan Generation

For each topic in planning_topics.md, invoke integration planner separately:

```text
Task(subagent_type="planner", prompt="file:.tmp/integrate/input/
file:.tmp/integrate/planning/planning_topics.md

## Integrate Plan for Topic: <TOPIC_NAME>

Context:
- Plan type: <PLAN_TYPE>
- Current topic: <TOPIC_NUMBER>
- Existing plan: .tmp/integrate/output/<PLAN_TYPE>_plan.md (if exists)

Instructions:
1. Read all input artifacts for context
2. Read existing plan (if exists) to understand what has been planned so far
3. Focus ONLY on the current topic: <TOPIC_NAME>
4. Add/update plan sections for THIS TOPIC ONLY
5. Ensure plan steps:
   - Have clear structures used
   - Reference specific code units
   - Call out side-effect boundaries for external integrations
   - Build on previous topics (if any)
6. Write updated plan to: .tmp/integrate/output/<PLAN_TYPE>_plan.md
7. Write receipt to: .tmp/integrate/99_receipts/02_integration_planner__topic_<N>.md

Plan structure must follow:
- Sequential numbering (Plan 1, Plan 2, Plan 3, ...)
- No letter suffixes (no Plan 2a)
- Required sections: # Implementation Plan, ## Plans, ### Plan N:")
```

**Important**: Wait for each topic's planner invocation to complete before proceeding to the
next topic. This ensures later topics can build on earlier plan sections.

### Step 7: Validate Plan Structure After Each Topic

After each integration planner completes, validate the plan structure:

1. Find the first `---` separator (if exists)
2. Verify required headers appear in order
3. Verify plans are numbered sequentially with no gaps
4. If validation fails, re-run planner with feedback

### Step 8: Final Plan Review

After all topics are integrated, invoke plan reviewers:

```text
Task(subagent_type="reviewer", prompt="file:.tmp/integrate/output/<PLAN_TYPE>_plan.md

## Review Integrated Plan

Invoke the following reviewers:
- @plan-structure-reviewer: Ensure plan is executable, ordered, non-ambiguous
- @pattern-plan-review: Check each step has structures + code units, side-effects explicit
- @plan-drift-reviewer: Ensure plan covers acceptance criteria, gaps explicit

Aggregate findings and write to: .tmp/integrate/output/plan_review_report.md
Write receipts to: .tmp/integrate/99_receipts/03_<reviewer>.md

If any FAIL, provide feedback for plan refinement.")
```

### Step 9: Pipeline Oversight Gate

Invoke pipeline oversight enforcer:

```text
Task(subagent_type="enforcer", prompt="## Pipeline Oversight Gate - INTEGRATE

Workspace: .tmp/integrate/

Verify:
1. All receipts exist in 99_receipts/
2. Planning topics decomposition is complete
3. Integration planner ran for each topic
4. Plan reviewers produced explicit pass/fail
5. No decision injection or suspicious patterns

Output gate result to: .tmp/integrate/99_receipts/99_pipeline_oversight.md")
```

### Step 10: Copy Output Plan

Copy the final plan to the parent orchestration workspace:

```bash
cp .tmp/integrate/output/"${PLAN_TYPE}_plan.md" "$PARENT_WORKSPACE/20_planning/"
```

### Step 11: Final Report

Print summary to terminal:

```text
================================================================================
INTEGRATE ORCHESTRATION COMPLETE
================================================================================

Strategy artifact: <STRATEGY_PATH>
Plan type: <PLAN_TYPE>

Topics decomposed: <N>
Topics integrated: <N>

Output plan: .tmp/integrate/output/<PLAN_TYPE>_plan.md
Copied to: <PARENT_WORKSPACE>/20_planning/<PLAN_TYPE>_plan.md

Planning topics: .tmp/integrate/planning/planning_topics.md
Receipts: .tmp/integrate/99_receipts/

Plan review result: PASS
================================================================================
```

## Receipt Format

Every agent must write a receipt to `99_receipts/`:

Template: `99_receipts/<stage>__<agent>.md`

```markdown
- **Inputs used**:
- **Outputs produced/modified**:
- **Topic processed** (integration planner only):
- **Decisions made**:
- **Deviations** (required; "None" allowed):
- **Assumptions**:
- **Open questions / risks**:
- **Next action recommended**:
```

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

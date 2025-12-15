---
description: Create implementation plan from Linear ticket (Stage 3-4 of Implementation Orchestration)
argument-hint: [ticket-id]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Create Implementation Plan from Ticket

Create a detailed implementation plan from a Linear ticket. This command implements **Stage 3-4** of the Implementation Orchestration (CREATE): Plan Integration and Plan Review.

## Prerequisites

The ticket must contain:
- Intent, acceptance criteria, constraints, unknowns (from create-ticket)
- Goals and strategy (from create-ticket)
- Optionally: research findings (from research orchestration)

## Workspace Structure

```
.tmp/create/implementation/
├── 00_intake/           # Intent, acceptance criteria (from ticket)
├── 10_research/         # Research findings (if available)
├── 20_planning/         # Strategy, planning topics, implementation plan
└── 99_receipts/         # All agent receipts
```

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/create/implementation/00_intake
mkdir -p .tmp/create/implementation/10_research
mkdir -p .tmp/create/implementation/20_planning
mkdir -p .tmp/create/implementation/99_receipts
```

### Step 2: Fetch Ticket from Linear

Fetch the ticket description:

```bash
uv run linear get-issue $ARGUMENTS
```

Extract and store the ticket ID, title, and URL.

### Step 3: Extract Ticket Artifacts to Workspace

Extract the ticket description to workspace files:

```bash
uv run linear get-issue-description $ARGUMENTS > .tmp/create/implementation/ticket_full.md
```

Parse the ticket description and extract sections into separate files:

**Expected sections in ticket (created by create-ticket command):**
- Intent -> `00_intake/intent.md`
- Acceptance Criteria -> `00_intake/acceptance_criteria.md`
- Constraints -> `00_intake/constraints.md`
- Unknowns -> `00_intake/unknowns.md`
- Questions for Human -> `00_intake/questions_for_human.md`
- Goals -> `20_planning/goals.md`
- Non-Goals -> `20_planning/non_goals.md`
- Goal to Acceptance Map -> `20_planning/goal_to_acceptance_map.md`
- Strategy -> `20_planning/strategy.md`
- Selected Structures -> `20_planning/selected_structures.md`
- Rejected Structures -> `20_planning/rejected_structures.md`

**Optional sections (if research was run):**
- Research Findings -> `10_research/research_findings.md`
- Evidence Table -> `10_research/evidence_table.md`
- Open Gaps -> `10_research/open_gaps.md`
- Domain Structure Candidates -> `10_research/domain_structure_candidates.md`
- Repo Integration Map -> `10_research/repo_integration_map.md`

If ticket doesn't have the expected structure:
- Stop and suggest running `/create-ticket` first to structure the ticket properly

### Step 4: Planning Topic Decomposition

Use the Task tool to invoke the planning topic decomposer:

```text
Task(subagent_type="agent", prompt="You are the @planning-topic-decomposer agent.

Workspace: .tmp/create/implementation/

Read these artifacts:
- .tmp/create/implementation/00_intake/intent.md
- .tmp/create/implementation/00_intake/acceptance_criteria.md
- .tmp/create/implementation/20_planning/strategy.md
- .tmp/create/implementation/20_planning/goals.md

Produce:
- .tmp/create/implementation/20_planning/planning_topics.md (ordered list of focused topics)
- .tmp/create/implementation/99_receipts/03_plan_topics__planning-topic-decomposer.md (receipt)

Each topic should be a single coherent unit (one AC item, one feature slice, one integration point).
Topics should be ordered by dependency and implementation sequence.

Follow the orchestration specification at: .ai/orchestration/plan-integration-orchestration.md")
```

Wait for the planning topic decomposer to complete.

### Step 5: Iterative Plan Integration (Stage 3)

Read the planning topics file to get the list of topics:

```bash
cat .tmp/create/implementation/20_planning/planning_topics.md
```

For each topic (sequentially, one at a time):

**Invoke Integration Planner:**

```text
Task(subagent_type="agent", prompt="You are the @integration-planner agent.

Workspace: .tmp/create/implementation/

Current topic: <TOPIC_TEXT>

Read these artifacts:
- .tmp/create/implementation/00_intake/intent.md
- .tmp/create/implementation/00_intake/acceptance_criteria.md
- .tmp/create/implementation/00_intake/constraints.md
- .tmp/create/implementation/20_planning/strategy.md
- .tmp/create/implementation/20_planning/selected_structures.md
- .tmp/create/implementation/20_planning/goals.md
- .tmp/create/implementation/20_planning/goal_to_acceptance_map.md
[If exists] - .tmp/create/implementation/10_research/research_findings.md
[If exists] - .tmp/create/implementation/10_research/repo_integration_map.md
[If exists] - .tmp/create/implementation/10_research/domain_structure_candidates.md
[If exists] - .tmp/create/implementation/20_planning/implementation_plan.md

For the current topic ONLY, add/update a plan section in implementation_plan.md.

Each plan step must include:
- Step number and description
- Structures used (from selected_structures.md)
- Code units (files, classes, functions)
- Side-effect boundaries (if external integrations exist)
- Acceptance criteria coverage

Write receipt to: .tmp/create/implementation/99_receipts/03_plan_integration__topic_<N>.md

Follow the agent specification at: .ai/agents/20-code-artifact/planners/integration-planner.md")
```

**Validate Plan Structure After Each Topic:**

```bash
# Check that implementation_plan.md exists and is valid
test -f .tmp/create/implementation/20_planning/implementation_plan.md
```

Verify the plan has:
- Proper markdown structure (headers, sections)
- Sequential step numbering (no gaps)
- Each step has structures, code units, and AC coverage

If validation fails:
- Re-run the integration planner with feedback explaining the structural issue

Repeat for all topics until complete.

### Step 6: Plan Review (Stage 3 - End)

Run plan reviewers to validate the plan:

**Plan Structure Review:**

```text
Task(subagent_type="agent", prompt="You are the @plan-structure-reviewer agent.

Review: .tmp/create/implementation/20_planning/implementation_plan.md

Ensure:
- Plan is executable and ordered correctly
- Steps are non-ambiguous
- Dependencies are clear
- All sections are present

Produce:
- .tmp/create/implementation/20_planning/plan_structure_review.md (PASS/FAIL + findings)
- .tmp/create/implementation/99_receipts/03_plan_review__plan-structure-reviewer.md (receipt)

Follow the agent specification at: .ai/agents/20-code-artifact/reviewers/plan-structure-reviewer.md")
```

**Pattern Plan Review:**

```text
Task(subagent_type="agent", prompt="You are the @pattern-plan-review agent.

Review: .tmp/create/implementation/20_planning/implementation_plan.md

Check:
- Each plan step has 'Structures used' and 'Code units' sections
- Side-effect boundaries are explicitly called out for external integrations
- Pattern library structures are referenced correctly

Produce:
- .tmp/create/implementation/20_planning/pattern_plan_review.md (PASS/FAIL + findings)
- .tmp/create/implementation/99_receipts/03_plan_review__pattern-plan-review.md (receipt)

Follow the agent specification at: .ai/agents/20-code-artifact/reviewers/pattern-plan-review.md")
```

**Plan Drift Review:**

```text
Task(subagent_type="agent", prompt="You are the @plan-drift-reviewer agent.

Spec: .tmp/create/implementation/00_intake/acceptance_criteria.md
Artifact: .tmp/create/implementation/20_planning/implementation_plan.md

Ensure:
- Plan covers all acceptance criteria
- Gaps are explicitly documented
- No drift from original intent

Produce:
- .tmp/create/implementation/20_planning/plan_drift_review.md (PASS/FAIL + findings)
- .tmp/create/implementation/99_receipts/03_plan_review__plan-drift-reviewer.md (receipt)

Follow the agent specification at: .ai/agents/20-code-artifact/reviewers/plan-drift-reviewer.md")
```

Wait for all reviewers to complete.

### Step 7: Check Review Results

Read all review reports:

```bash
cat .tmp/create/implementation/20_planning/plan_structure_review.md
cat .tmp/create/implementation/20_planning/pattern_plan_review.md
cat .tmp/create/implementation/20_planning/plan_drift_review.md
```

**If ANY review fails:**
- Use `@plan-patcher` to fix issues
- Re-run ALL reviewers
- Loop until all PASS

### Step 8: Artifact Review Orchestration (Stage 4 - Plan Review Loop)

**Note**: Stage 4 uses architecture-review and code-style-review on the plan.

Run the Artifact Review Orchestration for the plan:

```text
Task(subagent_type="orchestration", prompt="Run Artifact Review Orchestration (Review)

Artifact: .tmp/create/implementation/20_planning/implementation_plan.md

Reviewers (sequential):
- @architecture-review (ensure layer compliance, dependency direction)
- @code-style-review (ensure plan follows code style guidelines)

Patch agent: @plan-patcher

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

Loop until all reviewers PASS.

Follow: .ai/orchestration/artifact-review-orchestration.md")
```

**This orchestration will:**
1. Run architecture-review and code-style-review sequentially
2. Aggregate findings into review_report.md
3. If any FAIL: call @plan-patcher to fix, then re-run all reviewers
4. Exit only when all PASS

Wait for the orchestration to complete.

### Step 9: Update Linear Ticket with Plan

Append the implementation plan to the ticket description:

```bash
cat > .tmp/create/implementation/ticket_with_plan.md << 'EOF'
$(cat .tmp/create/implementation/ticket_full.md)

---

# Implementation Plan

$(cat .tmp/create/implementation/20_planning/implementation_plan.md)
EOF
```

Update the Linear ticket:

```bash
uv run linear update-issue $ARGUMENTS \
  --description-file .tmp/create/implementation/ticket_with_plan.md
```

### Step 10: Write Completion Receipt

Create a final receipt:

```bash
cat > .tmp/create/implementation/99_receipts/plan_creation_complete.md << 'EOF'
# Plan Creation Receipt

**Ticket ID**: $ARGUMENTS
**Title**: <TICKET_TITLE>

## Artifacts Created (Stage 3-4)

### Planning Topics
- planning_topics.md

### Implementation Plan
- implementation_plan.md (validated and reviewed)

### Review Reports
- plan_structure_review.md (PASS)
- pattern_plan_review.md (PASS)
- plan_drift_review.md (PASS)
- artifact_review_report.md (PASS)

## Receipts
- 03_plan_topics__planning-topic-decomposer.md
- 03_plan_integration__topic_*.md (per topic)
- 03_plan_review__*.md (all reviewers)
- 04_artifact_review__*.md (architecture, code-style)
- plan_creation_complete.md

## Next Steps

Run `/execute-plan $ARGUMENTS` to execute the plan (Stage 5-7).
Or run `/create-code $ARGUMENTS` to execute the full implementation orchestration.

## Review Status

All plan reviews PASSED:
- Structure: PASS
- Pattern Completeness: PASS
- Drift (vs Acceptance Criteria): PASS
- Architecture: PASS
- Code Style: PASS
EOF
```

### Step 11: Output Summary

Print the following to terminal:

```text
================================================================================
PLAN CREATION COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: $ARGUMENTS - <TICKET_TITLE>
Linear URL: https://linear.app/neshq/issue/$ARGUMENTS

View ticket with plan: uv run linear get-issue $ARGUMENTS

## Artifacts Created (Stage 3-4)

Planning artifacts:
- Planning topics (ordered by dependency)
- Implementation plan (stepwise, validated)

Review artifacts:
- All reviews PASSED

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

## Review Process

1. Read the implementation plan in the ticket description
2. Verify the plan adequately addresses all acceptance criteria
3. Check that plan steps are executable and ordered correctly
4. Verify structures and patterns are appropriate

YOU ARE REVIEWING THE IMPLEMENTATION PLAN FOR HOW TO CHANGE THE CODE,
NOT THAT THE CODE FOLLOWS THE PLAN

## Next Steps

Execute the plan: /execute-plan $ARGUMENTS
Or run full implementation: /create-code $ARGUMENTS

================================================================================
```

## Error Handling

- If ticket fetch fails, report the error and stop
- If ticket doesn't have expected structure, suggest running /create-ticket first
- If workspace creation fails, report the error and stop
- If planning topic decomposer fails, report the error output and stop
- If integration planner fails on any topic, report the error and stop
- If any plan reviewer fails after max iterations, escalate to human
- If artifact review orchestration fails, report the error and stop
- If Linear ticket update fails, report the error and preserve workspace
- Always preserve workspace on errors for debugging

## Notes

- This command implements Stage 3-4 of the Implementation Orchestration
- It assumes the ticket was created with `/create-ticket` (has proper structure)
- Research findings are optional but will be used if present
- The plan is validated through multiple review passes before being saved
- Workspace is preserved for use by `/execute-plan` command

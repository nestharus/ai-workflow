---
description: Create implementation plan from Linear ticket (Stage 3-4 of Implementation Orchestration)
---

# Create Implementation Plan from Ticket

Create a detailed implementation plan from a Linear ticket. This implements **Stage 3-4** of the Implementation Orchestration (CREATE): Plan Integration and Plan Review.

Input: `{{input}}` (ticket-id)

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
linear get-issue {{input}}
```

Extract and store the ticket ID, title, and URL.

### Step 3: Extract Ticket Artifacts to Workspace

Extract the ticket description to workspace files:

```bash
linear get-issue-description {{input}} > .tmp/create/implementation/ticket_full.md
```

Parse the ticket description and extract sections into separate files. Expected sections:
- Intent → `00_intake/intent.md`
- Acceptance Criteria → `00_intake/acceptance_criteria.md`
- Constraints → `00_intake/constraints.md`
- Unknowns → `00_intake/unknowns.md`
- Questions for Human → `00_intake/questions_for_human.md`
- Goals → `20_planning/goals.md`
- Non-Goals → `20_planning/non_goals.md`
- Goal to Acceptance Map → `20_planning/goal_to_acceptance_map.md`
- Strategy → `20_planning/strategy.md`
- Selected Structures → `20_planning/selected_structures.md`
- Rejected Structures → `20_planning/rejected_structures.md`

Optional sections (if research was run):
- Research Findings → `10_research/research_findings.md`
- Evidence Table → `10_research/evidence_table.md`
- Open Gaps → `10_research/open_gaps.md`
- Domain Structure Candidates → `10_research/domain_structure_candidates.md`
- Repo Integration Map → `10_research/repo_integration_map.md`

If ticket doesn't have the expected structure, stop and suggest running create-ticket first.

### Step 4: Planning Topic Decomposition

Invoke the planning topic decomposer using #agent:planning-topic-decomposer:

```text
#agent:planning-topic-decomposer

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
```

Wait for the planning topic decomposer to complete.

### Step 5: Iterative Plan Integration (Stage 3)

Read the planning topics file:

```bash
cat .tmp/create/implementation/20_planning/planning_topics.md
```

For each topic (sequentially, one at a time), invoke the integration planner using #agent:integration-planner:

```text
#agent:integration-planner

Workspace: .tmp/create/implementation/

Current topic: <TOPIC_TEXT>

Read all context artifacts and add/update a plan section in implementation_plan.md for the current topic ONLY.

Each plan step must include:
- Step number and description
- Structures used (from selected_structures.md)
- Code units (files, classes, functions)
- Side-effect boundaries (if external integrations exist)
- Acceptance criteria coverage

Write receipt to: .tmp/create/implementation/99_receipts/03_plan_integration__topic_<N>.md
```

Validate plan structure after each topic. Repeat for all topics until complete.

### Step 6: Plan Review (Stage 3 - End)

Run plan reviewers to validate the plan using #agent references:

1. **Plan Structure Review** (#agent:plan-structure-reviewer)
2. **Pattern Plan Review** (#agent:pattern-plan-review)
3. **Plan Drift Review** (#agent:plan-drift-reviewer)

Wait for all reviewers to complete. If ANY review fails, use plan-patcher to fix issues and re-run ALL reviewers. Loop until all PASS.

### Step 7: Check Review Results

Read all review reports and verify all passed.

### Step 8: Artifact Review Orchestration (Stage 4 - Plan Review Loop)

Run the Artifact Review Orchestration for the plan with architecture-review and code-style-review. Loop until all reviewers PASS.

### Step 9: Update Linear Ticket with Plan

Append the implementation plan to the ticket description and update the Linear ticket:

```bash
linear update-issue {{input}} \
  --description-file .tmp/create/implementation/ticket_with_plan.md
```

### Step 10: Write Completion Receipt

Create a final receipt in `99_receipts/plan_creation_complete.md`.

### Step 11: Output Summary

Print a comprehensive summary including:
- Ticket ID, title, and Linear URL
- Artifacts created (Stage 3-4)
- Review status (all PASSED)
- Workspace and receipts locations
- Review process instructions
- Next steps (execute plan or run full implementation)

## Output

The command will output:
- Ticket information and Linear URL
- Summary of planning artifacts created
- Review results (all PASSED)
- Instructions for reviewing the plan
- Next steps for execution

## Error Handling

- If ticket fetch fails, report the error and stop
- If ticket doesn't have expected structure, suggest running create-ticket first
- If workspace creation fails, report the error and stop
- If planning topic decomposer fails, report the error output and stop
- If integration planner fails on any topic, report the error and stop
- If any plan reviewer fails after max iterations, escalate to human
- If artifact review orchestration fails, report the error and stop
- If Linear ticket update fails, report the error and preserve workspace
- Always preserve workspace on errors for debugging

## Notes

- This command implements Stage 3-4 of the Implementation Orchestration
- It assumes the ticket was created with create-ticket (has proper structure)
- Research findings are optional but will be used if present
- The plan is validated through multiple review passes before being saved
- Workspace is preserved for use by execute-plan command
- You are reviewing the implementation plan for how to change the code, NOT that the code follows the plan

---
description: Create a Linear ticket from user intent (Stage 0-1 of Implementation Orchestration)
argument-hint: [description of work]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Create Ticket from User Intent

Create a structured Linear ticket from raw user intent. This command implements **Stage 0-1** of the Implementation Orchestration (CREATE), producing structured intake artifacts and strategy.

## Workspace Structure

```
.tmp/create/implementation/
├── 00_intake/           # Intent, acceptance criteria, constraints, unknowns
├── 20_planning/         # Strategy artifacts
└── 99_receipts/         # All agent receipts
```

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/create/implementation/00_intake
mkdir -p .tmp/create/implementation/20_planning
mkdir -p .tmp/create/implementation/99_receipts
```

### Step 2: Write Raw Input

Write the user's raw input to a file for the intent translator:

```bash
cat > .tmp/create/implementation/00_intake/raw_input.md << 'EOF'
$ARGUMENTS
EOF
```

### Step 3: Intent Translation (Stage 0 - Intake)

Use the Task tool to invoke the intent translator agent:

```text
Task(subagent_type="agent", prompt="You are the @intent-translator agent.

Workspace: .tmp/create/implementation/

Raw input is in: .tmp/create/implementation/00_intake/raw_input.md

Read the raw input and produce:
- .tmp/create/implementation/00_intake/intent.md (5-10 bullets: what is requested, no solutioning)
- .tmp/create/implementation/00_intake/acceptance_criteria.md (concrete, verifiable criteria)
- .tmp/create/implementation/00_intake/constraints.md (non-negotiables)
- .tmp/create/implementation/00_intake/unknowns.md (what is unknown, why it matters, resolution path)
- .tmp/create/implementation/00_intake/questions_for_human.md (blocking questions with assumptions)
- .tmp/create/implementation/99_receipts/00_intake__intent-translator.md (receipt)

Follow the agent specification at: .ai/agents/00-human-stage/intent-translator.md")
```

Wait for the intent translator to complete.

### Step 4: Validate Intake Outputs

Verify all required files were created:

```bash
ls -1 .tmp/create/implementation/00_intake/intent.md \
      .tmp/create/implementation/00_intake/acceptance_criteria.md \
      .tmp/create/implementation/00_intake/constraints.md \
      .tmp/create/implementation/00_intake/unknowns.md \
      .tmp/create/implementation/00_intake/questions_for_human.md \
      .tmp/create/implementation/99_receipts/00_intake__intent-translator.md
```

If any files are missing, stop and report the error.

### Step 5: Goal Planning

Use the Task tool to invoke the goal planner agent:

```text
Task(subagent_type="agent", prompt="You are the @goal-planner agent.

Workspace: .tmp/create/implementation/

Read these intake artifacts:
- .tmp/create/implementation/00_intake/intent.md
- .tmp/create/implementation/00_intake/acceptance_criteria.md
- .tmp/create/implementation/00_intake/constraints.md
- .tmp/create/implementation/00_intake/unknowns.md

Produce:
- .tmp/create/implementation/20_planning/goals.md (goal tree with 'Done when...' conditions)
- .tmp/create/implementation/20_planning/non_goals.md (explicit out-of-scope items)
- .tmp/create/implementation/20_planning/goal_to_acceptance_map.md (AC -> Goals -> Evidence)
- .tmp/create/implementation/99_receipts/00_5_goals__goal-planner.md (receipt)

Follow the agent specification at: .ai/agents/00-human-stage/goal-planner.md")
```

Wait for the goal planner to complete.

### Step 6: Strategy Planning (Stage 1)

Use the Task tool to invoke the strategy planner agent:

```text
Task(subagent_type="agent", prompt="You are the @strategy-planner agent.

Workspace: .tmp/create/implementation/

Read these artifacts:
- .tmp/create/implementation/00_intake/intent.md
- .tmp/create/implementation/00_intake/acceptance_criteria.md
- .tmp/create/implementation/00_intake/constraints.md
- .tmp/create/implementation/00_intake/unknowns.md
- .tmp/create/implementation/20_planning/goals.md
- .tmp/create/implementation/20_planning/non_goals.md
- .tmp/create/implementation/20_planning/goal_to_acceptance_map.md

Produce:
- .tmp/create/implementation/20_planning/strategy.md (short, decision-oriented strategy)
- .tmp/create/implementation/20_planning/selected_structures.md (chosen patterns/structures)
- .tmp/create/implementation/20_planning/rejected_structures.md (rejected alternatives)
- .tmp/create/implementation/99_receipts/01_strategy__strategy-planner.md (receipt)

Follow the agent specification at: .ai/agents/00-human-stage/strategy-planner.md")
```

Wait for the strategy planner to complete.

### Step 7: Check for Research Needs

Read the unknowns file to determine if research orchestration is needed:

```bash
cat .tmp/create/implementation/00_intake/unknowns.md
```

If unknowns require research (external APIs, domain patterns, integration points):
- Print a message: "Research is recommended. Run research orchestration before creating ticket."
- Note: Research orchestration is not yet implemented in this command

### Step 8: Determine Project

Get available Linear projects:

```bash
uv run linear list-projects
```

Analyze the intent and select the most appropriate project:
- "AI Workflow Application Phase N" - for app development work
- "Task System" - for task/agent system work
- "Test Framework" - for testing infrastructure
- "Documentation" - for documentation work
- "GitHub CI" - for CI/CD work
- "Knowledge System" - for knowledge/fact extraction work
- Default to "Task System" if unclear

### Step 9: Create Linear Ticket

Extract a concise title from intent.md (first bullet or summary).

Create the ticket description by combining all artifacts:

```bash
cat > .tmp/create/implementation/ticket_description.md << 'EOF'
# Intent

$(cat .tmp/create/implementation/00_intake/intent.md)

# Acceptance Criteria

$(cat .tmp/create/implementation/00_intake/acceptance_criteria.md)

# Constraints

$(cat .tmp/create/implementation/00_intake/constraints.md)

# Unknowns

$(cat .tmp/create/implementation/00_intake/unknowns.md)

# Questions for Human

$(cat .tmp/create/implementation/00_intake/questions_for_human.md)

---

# Goals

$(cat .tmp/create/implementation/20_planning/goals.md)

# Non-Goals

$(cat .tmp/create/implementation/20_planning/non_goals.md)

# Goal to Acceptance Map

$(cat .tmp/create/implementation/20_planning/goal_to_acceptance_map.md)

---

# Strategy

$(cat .tmp/create/implementation/20_planning/strategy.md)

# Selected Structures

$(cat .tmp/create/implementation/20_planning/selected_structures.md)

# Rejected Structures

$(cat .tmp/create/implementation/20_planning/rejected_structures.md)
EOF
```

Create the Linear ticket:

```bash
uv run linear create-issue --team Neshq \
  --title "<EXTRACTED_TITLE>" \
  --description-file .tmp/create/implementation/ticket_description.md \
  --project "<SELECTED_PROJECT>"
```

Capture the ticket ID from the response.

### Step 10: Write Completion Receipt

Create a final receipt summarizing the ticket creation:

```bash
cat > .tmp/create/implementation/99_receipts/ticket_creation_complete.md << 'EOF'
# Ticket Creation Receipt

**Ticket ID**: <TICKET_ID>
**Title**: <EXTRACTED_TITLE>
**Project**: <SELECTED_PROJECT>

## Artifacts Created

### Intake (Stage 0)
- intent.md
- acceptance_criteria.md
- constraints.md
- unknowns.md
- questions_for_human.md

### Goals
- goals.md
- non_goals.md
- goal_to_acceptance_map.md

### Strategy (Stage 1)
- strategy.md
- selected_structures.md
- rejected_structures.md

## Receipts
- 00_intake__intent-translator.md
- 00_5_goals__goal-planner.md
- 01_strategy__strategy-planner.md
- ticket_creation_complete.md

## Next Steps

Run `/create-plan <TICKET_ID>` to continue to Stage 3-4 (Plan Integration).
Or run `/create-code <TICKET_ID>` to execute the full implementation orchestration.

## Research Recommendation

[Include if unknowns require research]
Research is recommended for: [list unknowns requiring research]
EOF
```

### Step 11: Cleanup (Optional)

Ask user if they want to preserve or clean up the workspace:

```text
Workspace preserved at: .tmp/create/implementation/

To clean up: rm -rf .tmp/create/implementation/
To preserve: Keep for reference or subsequent commands
```

### Step 12: Output Summary

Print the following to terminal:

```text
================================================================================
TICKET CREATION COMPLETE
================================================================================

Ticket: <TICKET_ID> - <EXTRACTED_TITLE>
Project: <SELECTED_PROJECT>
Linear URL: https://linear.app/neshq/issue/<TICKET_ID>

View ticket: uv run linear get-issue <TICKET_ID>

## Artifacts Created (Stage 0-1)

Intake artifacts:
- Intent, acceptance criteria, constraints, unknowns, questions

Goals:
- Goal tree, non-goals, goal-to-acceptance mapping

Strategy:
- High-level approach, selected/rejected structures

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

## Next Steps

1. Review the ticket on Linear
2. Answer any blocking questions in questions_for_human.md
3. Run research if needed (unknowns flagged)
4. Create implementation plan: /create-plan <TICKET_ID>
5. Or run full implementation: /create-code <TICKET_ID>

[If research recommended]
RECOMMENDED: Run research orchestration for unknowns before planning.

================================================================================
```

## Error Handling

- If workspace creation fails, report the error and stop
- If intent translator fails, report the error output and stop
- If goal planner fails, report the error output and stop
- If strategy planner fails, report the error output and stop
- If Linear ticket creation fails, report the error and stop
- If any validation fails, report which files are missing and stop
- Always preserve workspace on errors for debugging

## Notes

- This command implements Stage 0-1 of the Implementation Orchestration
- It does NOT invoke research orchestration (Stage 2) - that's manual for now
- The ticket contains all intake + strategy artifacts for future planning
- Workspace is preserved for use by subsequent commands (create-plan, create-code)

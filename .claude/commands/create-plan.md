---
description: Create an implementation plan from a Linear ticket (or create ticket from prompt)
argument-hint: [<ticket-id> | <description of work>]
allowed-tools: Bash, Read, Write, Glob, Grep, mcp__linear-server__get_issue, mcp__linear-server__create_issue, mcp__linear-server__create_comment, mcp__linear-server__update_issue, mcp__linear-server__list_projects, mcp__linear-server__list_teams
---

Create an implementation plan. If `$ARGUMENTS` is a ticket ID (e.g., `NES-123`), fetch that ticket. Otherwise, create a new ticket using the arguments as a description.

## File Naming Convention

All plan and strategy files follow this naming convention and are attached to the ticket:
- `implementation-plan.md` - Implementation plan
- `implementation-strategy.md` - Implementation strategy
- `test-plan.md` - Test plan
- `test-strategy.md` - Test strategy

## Workflow

### Step 1: Determine Ticket

Check if `$ARGUMENTS` looks like a ticket ID (format: `XXX-NNN` where XXX is letters and NNN is numbers):

**If ticket ID provided:**
- Use `mcp__linear-server__get_issue` to fetch the ticket

**If no ticket ID (description provided instead):**
1. Use `mcp__linear-server__list_projects` to get available projects
2. Analyze the description to determine the most appropriate project:
   - "AI Workflow Application Phase N" - for app development work
   - "Task System" - for task/agent system work
   - "Test Framework" - for testing infrastructure
   - "Documentation" - for documentation work
   - "GitHub CI" - for CI/CD work
   - "Knowledge System" - for knowledge/fact extraction work
   - Default to "Task System" if unclear
3. Use `mcp__linear-server__list_teams` to get team ID (use "Neshq")
4. Create ticket with `mcp__linear-server__create_issue`:
   - `title`: Extract a concise title from the description (first sentence or main topic)
   - `description`: Full description from `$ARGUMENTS`
   - `team`: "Neshq"
   - `project`: Selected project name
5. Capture the created ticket ID

### Step 2: Run Planner Agent

Execute the planner agent with the ticket details:
```bash
uv run agent.tasks --agent planner --prompt "Ticket ID: <ID>
Title: <TITLE>
Description:
<DESCRIPTION>"
```
Capture the plan output from stdout.

### Step 3: Save Plan

Write the plan to `.tasks/plans/<ticket-id>/implementation-plan.md` (create directory if needed).

### Step 4: Update Linear

Add the plan as a comment on the ticket using `mcp__linear-server__create_comment` with the full plan content in markdown format.

### Step 5: Output Review Request

Print the following to terminal:

```
================================================================================
PLAN REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Plan saved to: .tasks/plans/<ticket-id>/implementation-plan.md
Plan posted to Linear as comment.

Please review the plan on the ticket:
1. Open the ticket in Linear
2. Review the attached plan comment against the ticket description
3. Verify the plan adequately addresses all requirements
4. Check that success criteria are measurable and complete

After review, run /execute-plan <ticket-id> to implement.
================================================================================
```

## Error Handling

- If ticket fetch fails, report the error and stop
- If ticket creation fails, report the error and stop
- If planner agent fails, report the error output and stop
- If Linear comment creation fails, still save the local plan file and notify the user

## Design Notes

The current implementation posts the concrete plan content as a comment on the Linear
ticket. It does not maintain a separate template artifact per ticket. If future work
requires a distinct reusable template object (separate from the generated plan), this
workflow will need to be extended to create and store that artifact.

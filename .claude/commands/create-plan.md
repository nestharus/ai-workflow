---
description: Create an implementation plan from a Linear ticket (or create ticket from prompt)
argument-hint: [<ticket-id> | <description of work>]
allowed-tools: Bash, Read, Write, Glob, Grep, mcp__linear-server__get_issue, mcp__linear-server__create_issue, mcp__linear-server__create_comment, mcp__linear-server__update_issue, mcp__linear-server__list_projects, mcp__linear-server__list_teams
---

Create an implementation plan. If `$ARGUMENTS` is a ticket ID (e.g., `NES-123`), fetch that ticket. Otherwise, create a new ticket using the arguments as a description.

## Plan Storage

Plans are stored directly in the Linear ticket description. When a plan is created or updated,
the ticket description is updated to include the full plan content below a `---` separator.

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

### Step 3: Update Linear Ticket

Update the ticket description using `mcp__linear-server__update_issue` to append the plan content:
1. Keep the original ticket description
2. Add a `---` separator
3. Add `# Implementation Plan` header
4. Add the full plan content in markdown format

The plan becomes part of the ticket description and is visible directly on the ticket.

### Step 4: Output Review Request

Print the following to terminal:

```
================================================================================
PLAN REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Plan attached to Linear ticket description.

Please review the plan on the ticket:
1. Open the ticket in Linear: <LINEAR_TICKET_URL>
2. Review the implementation plan in the ticket description
3. Verify the plan adequately addresses all requirements
4. Check that success criteria are measurable and complete

After review, run /execute-plan <ticket-id> to implement.
================================================================================
```

## Error Handling

- If ticket fetch fails, report the error and stop
- If ticket creation fails, report the error and stop
- If planner agent fails, report the error output and stop
- If Linear ticket update fails, report the error and stop

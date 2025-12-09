---
description: Create an implementation plan from a Linear ticket (or create ticket from prompt)
argument-hint: [ticket-id or description of work]
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Create Implementation Plan

Create an implementation plan. If `$ARGUMENTS` is a ticket ID (e.g., `NES-123`), fetch that
ticket. Otherwise, create a new ticket using the arguments as a description.

## Plan Storage

Plans are stored directly in the Linear ticket description. When a plan is created or updated,
the ticket description is updated to include the full plan content below a `---` separator.

## Workflow

### Step 1: Determine Ticket

Check if `$ARGUMENTS` looks like a ticket ID (format: `XXX-NNN` where XXX is letters and NNN is
numbers):

**If ticket ID provided:**

Fetch the ticket using the Linear CLI:

```bash
uv run linear get-issue <TICKET_ID>
```

**If no ticket ID (description provided instead):**

1. Get available projects using the Linear CLI:
2. Analyze the description to determine the most appropriate project:
   * "AI Workflow Application Phase N" - for app development work
   * "Task System" - for task/agent system work
   * "Test Framework" - for testing infrastructure
   * "Documentation" - for documentation work
   * "GitHub CI" - for CI/CD work
   * "Knowledge System" - for knowledge/fact extraction work
   * Default to "Task System" if unclear
3. Create ticket using the Linear CLI (use team name "Neshq" - the CLI resolves names to IDs):
4. Capture the created ticket ID from the response

List the available projects:

```bash
uv run linear list-projects
```

Then, create the ticket:

```bash
uv run linear create-issue --team Neshq --title "<EXTRACTED_TITLE>" --description "$ARGUMENTS" --project "<SELECTED_PROJECT>"
```

### Step 2: Run Planner Agent

Use the Task tool to invoke the planner agent:

```text
Task(subagent_type="planner", prompt="Ticket ID: <ID>
Title: <TITLE>
Description:
<DESCRIPTION>")
```

The planner agent will:

* Analyze the ticket requirements
* Explore the codebase for context
* Research unfamiliar patterns if needed
* Generate a comprehensive implementation plan

Wait for the planner agent to complete and capture its output (the plan content).

### Step 3: Update Linear Ticket

Update the ticket description using the Linear CLI to append the plan content:

```bash
uv run linear update-issue <TICKET_ID> --description "<ORIGINAL_DESCRIPTION>

---

# Implementation Plan

<PLAN_CONTENT>"
```

The plan becomes part of the ticket description and is visible directly on the ticket.

### Step 4: Output Review Request

Print the following to terminal:

```text
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

If the Linear MCP tool does not work you can use `uv run linear get-issue <TICKET_ID>`

After review, run /execute-plan <ticket-id> to implement.
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If ticket creation fails, report the error and stop
* If planner agent fails, report the error output and stop
* If Linear ticket update fails, report the error and stop

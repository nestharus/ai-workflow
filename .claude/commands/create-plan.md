---
description: Create an implementation plan from a Linear ticket (or create ticket from prompt)
argument-hint: [ticket-id or description of work]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
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

Fetch basic ticket info (title, URL) using the Linear CLI:

```bash
uv run linear get-issue <TICKET_ID>
```

Extract and store `title` and `url` from the JSON response.

**If no ticket ID (description provided instead):**

1. Get available projects using the Linear CLI
2. Analyze the description to determine the most appropriate project:
   * "AI Workflow Application Phase N" - for app development work
   * "Task System" - for task/agent system work
   * "Test Framework" - for testing infrastructure
   * "Documentation" - for documentation work
   * "GitHub CI" - for CI/CD work
   * "Knowledge System" - for knowledge/fact extraction work
   * Default to "Task System" if unclear
3. Create ticket using the Linear CLI (use team name "Neshq" - the CLI resolves names to IDs)
4. Capture the created ticket ID from the response

List the available projects:

```bash
uv run linear list-projects
```

Then, create the ticket:

```bash
uv run linear create-issue --team Neshq --title "<EXTRACTED_TITLE>" --description "$ARGUMENTS" --project "<SELECTED_PROJECT>"
```

### Step 2: Extract Description to Temp File

Extract the ticket description to a temp file for the planner agent:

```bash
mkdir -p .tmp
uv run linear get-issue-description <TICKET_ID> > .tmp/<TICKET_ID>.md
```

**IMPORTANT**: Do NOT read the temp file. The planner agent will read and update it.

### Step 3: Run Planner Agent

Use the Task tool to invoke the planner agent with the temp file:

```text
Task(subagent_type="planner", prompt="file:.tmp/<TICKET_ID>.md

## Create Plan

Ticket ID: <TICKET_ID>
Title: <TITLE>

Create a new implementation plan for this ticket. The file contains the ticket description.
Add the plan after a `---` separator.")
```

The planner agent will:

* Read the temp file to get the ticket description
* Analyze the ticket requirements
* Explore the codebase for context
* Research unfamiliar patterns if needed
* Generate a comprehensive implementation plan
* Write the plan back to the temp file (description + separator + plan)

Wait for the planner agent to complete.

Review the plan by grepping for "Implementation Plan", "Plans", and "Plan 1:".
If these are not found then rerun the planner with the file and comments that plan was
not found due to plan template not being followed. Expected to find Implementation Plan,
Plans, and Plan 1: per template.

### Step 4: Update Linear Ticket

Update the ticket description directly from the temp file:

```bash
uv run linear update-issue <TICKET_ID> --description-file .tmp/<TICKET_ID>.md
```

**IMPORTANT**: Do NOT read the temp file. Pass it directly to `update-issue` using `--description-file`.

### Step 5: Cleanup

Delete the temp file:

```bash
rm .tmp/<TICKET_ID>.md
```

### Step 6: Output Review Request

Print the following to terminal:

```text
================================================================================
PLAN CREATION COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Linear Ticket: `uv run linear get-issue <TICKET_ID>`

Please review the plan on the ticket:
1. Open the ticket in Linear: <LINEAR_TICKET_URL>
2. Review the implementation plan in the ticket description
3. Verify the plan adequately addresses all requirements
4. Check that success criteria are measurable and complete
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If ticket creation fails, report the error and stop
* If planner agent fails, report the error output and stop
* If Linear ticket update fails, report the error and stop
* Always clean up the temp file, even on errors

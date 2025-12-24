---
description: Create an implementation plan from a Linear ticket (or create ticket from prompt)
argument-hint: [ticket-id or description of work]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Create Implementation Plan

If `$ARGUMENTS` matches ticket ID format (`XXX-NNN` where XXX is letters, NNN is numbers), fetch it. Otherwise, create a new ticket.

Plans are stored in the Linear ticket description below a `---` separator.

## Step 1: Determine Ticket

**If ticket ID provided:**
```bash
uv run linear get-issue <TICKET_ID>
```
Extract `title` and `url` from the JSON response.

**If description provided:**
```bash
uv run linear list-projects
uv run linear create-issue --team Neshq --title "<TITLE>" --description "$ARGUMENTS" --project "<PROJECT>"
```
Capture the created ticket ID from the response.

**Project selection:**
- "AI Workflow Application Phase N" - app development work
- "Task System" - task/agent system work (default if unclear)
- "Test Framework" - testing infrastructure
- "Documentation" - documentation work
- "GitHub CI" - CI/CD work
- "Knowledge System" - knowledge/fact extraction work

## Step 2: Extract Description
```bash
mkdir -p .tmp
uv run linear get-issue-description <TICKET_ID> > .tmp/<TICKET_ID>.md
```
Do NOT read the temp file. The planner agent will read and update it.

## Step 3: Run Planner Agent

```text
Task(subagent_type="planner", prompt="file:.tmp/<TICKET_ID>.md

## Create Plan

Ticket ID: <TICKET_ID>
Title: <TITLE>

Create a new implementation plan for this ticket. The file contains the ticket description.
Add the plan after a `---` separator.")
```

The planner agent will: read the temp file, analyze requirements, explore codebase for context, research unfamiliar patterns, generate plan, and write the plan back to the temp file (description + separator + plan).

Wait for the planner agent to complete.

**Validate structure after completion:**
1. Find first `---` separator line in temp file
2. Verify line immediately after `---` (skipping blank lines) is `# Implementation Plan`
3. Verify `## Plans` appears after `# Implementation Plan`
4. Verify `### Plan 1:` appears after `## Plans`
5. Verify plans numbered sequentially (1, 2, 3, ...) with no gaps or letters

If validation fails, rerun planner with specific feedback explaining which structural requirement was not met.

## Step 4: Update Linear Ticket
```bash
uv run linear update-issue <TICKET_ID> --description-file .tmp/<TICKET_ID>.md
```
Do NOT read the temp file. Pass it directly using `--description-file`.

## Step 5: Cleanup
```bash
rm .tmp/<TICKET_ID>.md
```

## Step 6: Output
```text
================================================================================
PLAN CREATION COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Run `uv run linear get-issue <TICKET_ID>` to fetch plan.

Review the implementation plan in the ticket description:
1. Verify the plan adequately addresses all requirements
2. Check that success criteria are measurable and complete

YOU ARE REVIEWING THE IMPLEMENTATION PLAN FOR HOW TO CHANGE THE CODE,
NOT THAT THE CODE FOLLOWS THE PLAN
================================================================================
```

## Error Handling

- If ticket fetch fails, report error and stop
- If ticket creation fails, report error and stop
- If planner agent fails, report error output and stop
- If Linear ticket update fails, report error and stop
- Always clean up temp file, even on errors

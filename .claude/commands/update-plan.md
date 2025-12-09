---
description: Update an existing implementation plan with additional requirements
argument-hint: ticket-id and additional requirements
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Update Implementation Plan

Update the implementation plan for ticket `$ARGUMENTS`.

Parse arguments: first token is ticket ID, rest is the update prompt.

## Workflow

### Step 1: Fetch Existing Context

1. Fetch the ticket details using the Linear CLI:
2. Parse the existing plan from the ticket description (after the `---` separator)
3. Get any review feedback from the ticket using the Linear CLI:

Fetch ticket details:

```bash
uv run linear get-issue <TICKET_ID>
```

Get review feedback:

```bash
uv run linear list-comments <TICKET_ID>
```

### Step 2: Run Planner Agent with Update Context

Use the Task tool to invoke the planner agent with the existing plan and update request:

```text
Task(subagent_type="planner", prompt="Ticket ID: <ID>
Title: <TITLE>
Description:
<DESCRIPTION>

## Existing Plan
<EXISTING_PLAN_CONTENT>

## Update Request
<UPDATE_PROMPT>

## Instructions
Revise the existing plan to incorporate the update request. Preserve what is still valid, modify what needs to change, and add any new requirements. Output the complete revised plan.")
```

Wait for the planner agent to complete and capture its output (the updated plan content).

### Step 3: Update Linear Ticket

Update the ticket description using the Linear CLI:

```bash
uv run linear update-issue <TICKET_ID> --description "<ORIGINAL_DESCRIPTION>

---

# Implementation Plan

<UPDATED_PLAN_CONTENT>"
```

### Step 4: Add Update Comment

Add a comment on the ticket using the Linear CLI:

```bash
uv run linear create-comment <TICKET_ID> --body "## Plan Updated

Changes incorporated:
<SUMMARY_OF_UPDATE_REQUEST>

The implementation plan in the ticket description has been updated."
```

### Step 5: Output Confirmation

Print the following to terminal:

```text
================================================================================
PLAN UPDATED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Plan updated in Linear ticket description.

Changes incorporated:
<SUMMARY_OF_UPDATE_REQUEST>

Please review the updated plan on the ticket before executing:
<LINEAR_TICKET_URL>
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If existing plan not found in ticket description, suggest running /create-plan first
* If planner agent fails, report the error output and stop
* If Linear ticket update fails, report the error and stop

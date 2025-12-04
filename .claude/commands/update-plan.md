---
description: Update an existing implementation plan with additional requirements
argument-hint: <ticket-id> <additional requirements>
allowed-tools: Bash, Read, Write, Glob, Grep, mcp__linear-server__get_issue, mcp__linear-server__create_comment, mcp__linear-server__update_issue, mcp__linear-server__list_comments
---

Update the implementation plan for ticket `$ARGUMENTS`.

Parse arguments: first token is ticket ID, rest is the update prompt.

## Workflow

### Step 1: Fetch Existing Context

1. Use `mcp__linear-server__get_issue` to fetch the ticket details
2. Parse the existing plan from the ticket description (after the `---` separator)
3. Use `mcp__linear-server__list_comments` to get any review feedback from the ticket

### Step 2: Run Planner Agent with Update Context

Execute the planner agent with the existing plan and update request:
```bash
uv run agent.tasks --agent planner --prompt "Ticket ID: <ID>
Title: <TITLE>
Description:
<DESCRIPTION>

## Existing Plan
<EXISTING_PLAN_CONTENT>

## Update Request
<UPDATE_PROMPT>

## Instructions
Revise the existing plan to incorporate the update request. Preserve what is still valid, modify what needs to change, and add any new requirements. Output the complete revised plan."
```

### Step 3: Update Linear Ticket

Update the ticket description using `mcp__linear-server__update_issue`:
1. Keep the original ticket description (before the `---` separator)
2. Add a `---` separator
3. Add `# Implementation Plan` header
4. Add the full updated plan content in markdown format

### Step 4: Add Update Comment

Add a comment on the ticket using `mcp__linear-server__create_comment` with:
```markdown
## Plan Updated

Changes incorporated:
<SUMMARY_OF_UPDATE_REQUEST>

The implementation plan in the ticket description has been updated.
```

### Step 5: Output Confirmation

Print the following to terminal:

```
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

- If ticket fetch fails, report the error and stop
- If existing plan not found in ticket description, suggest running /create-plan first
- If planner agent fails, report the error output and stop
- If Linear ticket update fails, report the error and stop

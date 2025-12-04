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
2. Read the existing plan from `.tasks/plans/<ticket-id>/implementation-plan.md`
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

### Step 3: Save Updated Plan

1. Back up existing plan to `.tasks/plans/<ticket-id>/implementation-plan.md.bak`
2. Write the updated plan to `.tasks/plans/<ticket-id>/implementation-plan.md`

### Step 4: Update Linear

Add the updated plan as a new comment on the ticket using `mcp__linear-server__create_comment` with:
```markdown
## Plan Update

<UPDATED_PLAN_CONTENT>
```

### Step 5: Output Confirmation

Print the following to terminal:

```
================================================================================
PLAN UPDATED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Plan updated at: .tasks/plans/<ticket-id>/implementation-plan.md
Previous version backed up to: .tasks/plans/<ticket-id>/implementation-plan.md.bak
Updated plan posted to Linear as comment.

Changes incorporated:
<SUMMARY_OF_UPDATE_REQUEST>

Please review the updated plan on the ticket before executing.
================================================================================
```

## Error Handling

- If ticket fetch fails, report the error and stop
- If existing plan not found, suggest running /create-plan first
- If planner agent fails, report the error output and stop
- If Linear comment creation fails, still save the local plan file and notify the user

---
description: Update an existing implementation plan with additional requirements
argument-hint: ticket-id and additional requirements
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Update Implementation Plan

Update the implementation plan for ticket `$ARGUMENTS`.

Parse arguments: first token is ticket ID, rest is the update prompt (optional).

## Workflow

### Step 1: Fetch Existing Plan to Temp File

1. Create .tmp directory if it doesn't exist
2. Fetch the ticket description to a markdown file:

```bash
mkdir -p .tmp
uv run linear get-issue-description <TICKET_ID> > .tmp/<TICKET_ID>.md
```

3. Verify the file was created and is not empty:

```bash
test -s .tmp/<TICKET_ID>.md && echo "exists"
```

If the file is empty or doesn't exist, the ticket has no description - suggest running `/create-plan` first.

**IMPORTANT**: Do NOT read the temp file contents directly. The planner agent will handle
reading and updating the file. This step only extracts the ticket description for the planner
agent to process.

### Step 2: Determine Update Source

If an update prompt was provided in $ARGUMENTS (after the ticket ID), use that as the
review feedback.

Otherwise, fetch unresolved comments from the ticket:

```bash
uv run pr list-unresolved-comments <TICKET_ID>
```

Parse the comments output to extract individual comment bodies.

### Step 3: Run Planner Agent for Each Comment

For each comment (from prompt or fetched), invoke the planner agent separately:

```text
Task(subagent_type="planner", prompt="file:.tmp/<TICKET_ID>.md

## Update Request
<SINGLE_COMMENT_CONTENT>")
```

Wait for each planner agent invocation to complete before proceeding to the next comment.
The planner agent will read from and update the temp file directly.

**Collect the summary** returned by each planner invocation. These summaries will be used
in Step 5 for the update comment.

### Step 4: Update Linear Ticket

After all planner invocations complete, update the ticket description directly from the temp file:

```bash
uv run linear update-issue <TICKET_ID> --description-file .tmp/<TICKET_ID>.md
```

**IMPORTANT**: Do NOT read the temp file. Pass it directly to `update-issue` using `--description-file`.

### Step 5: Add Update Comment

Add a comment on the ticket summarizing the changes using the Linear CLI:

```bash
uv run linear create-comment <TICKET_ID> --body "## Plan Updated

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

The implementation plan in the ticket description has been updated."
```

### Step 6: Cleanup and Confirm

1. Delete the temp file

```bash
rm .tmp/<TICKET_ID>.md
```

2. Print confirmation message:

```text
================================================================================
PLAN UPDATED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Plan updated in Linear ticket description.

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

Please review the updated plan on the ticket before executing:
<LINEAR_TICKET_URL>

Get plan description with `uv run linear get-issue <TICKET_ID>`
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If existing plan not found in ticket description (empty file), suggest running /create-plan first
* If planner agent fails, report the error output and stop
* If Linear ticket update fails, report the error and stop
* Always clean up the temp file, even on errors

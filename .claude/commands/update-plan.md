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
2. Fetch the ticket details and pipe the entire output to `.tmp/<TICKET_ID>.md`

```bash
mkdir -p .tmp
uv run linear get-issue <TICKET_ID> > .tmp/<TICKET_ID>.md
```

3. Verify the file was created by reading the first line only (NOT the full file):

```bash
head -n 1 .tmp/<TICKET_ID>.md
```

**IMPORTANT**: Do NOT read or manipulate the temp file contents directly. The planner agent
will handle reading and updating the file. This command only fetches the ticket data for the
planner agent to process.

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
in Step 6 for the update comment.

### Step 4: Read Updated Plan

After all planner invocations complete, read the updated plan from the temp file:

```bash
cat .tmp/<TICKET_ID>.md
```

Extract the plan content (everything after the `---` separator line).

### Step 5: Update Linear Ticket

Update the ticket description with the new plan using the Linear CLI:

```bash
uv run linear update-issue <TICKET_ID> --description "<ORIGINAL_DESCRIPTION>

---

<UPDATED_PLAN_CONTENT>"
```

### Step 6: Add Update Comment

Add a comment on the ticket summarizing the changes using the Linear CLI:

```bash
uv run linear create-comment <TICKET_ID> --body "## Plan Updated

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

The implementation plan in the ticket description has been updated."
```

### Step 7: Request Review and Cleanup

1. Print confirmation message requesting review
2. Delete the temp file

```bash
rm .tmp/<TICKET_ID>.md
```

Print the following to terminal:

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
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If existing plan not found in ticket description, suggest running /create-plan first
* If planner agent fails, report the error output and stop
* If Linear ticket update fails, report the error and stop
* Always clean up the temp file, even on errors

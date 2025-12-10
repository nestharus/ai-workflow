---
description: Update an existing implementation plan with additional requirements
name: update-plan
argument-hint: ticket-id and additional requirements
agent: 'agent'
tools:
  - '*'
---

# Update Implementation Plan

Update the implementation plan for the specified ticket with additional requirements or feedback.

Parse arguments: first token is ticket ID, rest is the update prompt (optional).

## Workflow

### Step 1: Fetch Existing Plan to Temp File

1. Create .tmp directory if it doesn't exist
2. Fetch the ticket description to a markdown file using `#tool:terminal`:

```bash
mkdir -p .tmp
uv run linear get-issue-description ${input:ticketId} > .tmp/${input:ticketId}.md
```

3. Verify the file was created and is not empty using `#tool:terminal`:

```bash
test -s .tmp/${input:ticketId}.md && echo "exists"
```

If the file is empty or doesn't exist, the ticket has no description - suggest running `/create-plan` first.

**IMPORTANT**: Do NOT read the temp file contents directly. The Planner agent (via `#runSubagent`)
will handle reading and updating the file. This step only extracts the ticket description for the
Planner agent to process.

### Step 2: Determine Update Source

If an update prompt was provided in the arguments (after the ticket ID), use that as the
review feedback.

Otherwise, fetch unresolved comments from the ticket using `#tool:terminal`:

```bash
uv run pr list-unresolved-comments ${input:ticketId}
```

Parse the comments output to extract individual comment bodies.

### Step 3: Run Planner Agent for Each Comment

For each comment (from prompt or fetched), use `#runSubagent` to delegate to the Planner agent:

```text
#runSubagent to invoke the Planner agent with the prompt:
"file:.tmp/${input:ticketId}.md

## Update Request
<SINGLE_COMMENT_CONTENT>"
```

Wait for each Planner agent invocation to complete before proceeding to the next comment.
The Planner agent will read from and update the temp file directly.

**Collect the summary** returned by each Planner agent invocation. These summaries will be used
in Step 5 for the update comment.

### Step 4: Update Linear Ticket

After all Planner agent invocations complete, update the ticket description directly from the temp file using `#tool:terminal`:

```bash
uv run linear update-issue ${input:ticketId} --description-file .tmp/${input:ticketId}.md
```

**IMPORTANT**: Do NOT read the temp file. Pass it directly to `update-issue` using `--description-file`.

### Step 5: Add Update Comment

Add a comment on the ticket summarizing the changes using `#tool:terminal`:

```bash
uv run linear create-comment ${input:ticketId} --body "## Plan Updated

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

The implementation plan in the ticket description has been updated."
```

### Step 6: Cleanup and Confirm

1. Delete the temp file using `#tool:terminal`:

```bash
rm .tmp/${input:ticketId}.md
```

2. Print confirmation message:

```text
================================================================================
PLAN UPDATED
================================================================================

Ticket: ${input:ticketId} - <TITLE>
Plan updated in Linear ticket description.

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

Please review the updated plan on the ticket before executing:
<LINEAR_TICKET_URL>

If the Linear MCP tool does not work you can use `uv run linear get-issue ${input:ticketId}`
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If existing plan not found in ticket description (empty file), suggest running /create-plan first
* If Planner agent (via `#runSubagent`) fails, report the error output and stop
* If Linear ticket update fails, report the error and stop
* Always clean up the temp file, even on errors

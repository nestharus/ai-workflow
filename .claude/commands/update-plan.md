---
description: Update an existing implementation plan with additional requirements
argument-hint: ticket-id and additional requirements
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Update Implementation Plan

Update the implementation plan for ticket `$ARGUMENTS`.

Parse arguments: first token is ticket ID, rest is the update prompt (optional).

## Workflow

### Step 1: Fetch Existing Plan

```bash
mkdir -p .tmp
uv run linear get-issue-description <TICKET_ID> > .tmp/<TICKET_ID>.md
test -s .tmp/<TICKET_ID>.md && echo "exists"
```

If empty, suggest running `/create-plan` first.

**IMPORTANT**: Do NOT read the temp file directly. The planner agent handles reading and updating it.

### Step 2: Determine Update Source

If update prompt provided in $ARGUMENTS, use that. Otherwise fetch comments:

```bash
uv run pr list-unresolved-comments <TICKET_ID>
```

Parse the output to extract individual comment bodies.

### Step 3: Run Planner Agent

For each comment, invoke planner separately:

```text
Task(subagent_type="planner", prompt="file:.tmp/<TICKET_ID>.md

## Update Request
<COMMENT_CONTENT>")
```

**Wait for each invocation to complete** before proceeding to the next. The planner reads from and updates the temp file directly.

**Collect summaries** from each invocation for the update comment in Step 5.

**Validate plan structure** after each invocation:
1. First `---` separator, then `# Implementation Plan` (first header after `---`)
2. `## Plans` appears before any `### Plan N:`
3. Plans numbered sequentially (1, 2, 3...) - no gaps, no letter suffixes (e.g., "Plan 2a" invalid)

If validation fails, rerun planner with feedback explaining which requirement was not met.

### Step 4: Update Linear Ticket

```bash
uv run linear update-issue <TICKET_ID> --description-file .tmp/<TICKET_ID>.md
```

**IMPORTANT**: Do NOT read the temp file. Pass it directly using `--description-file`.

### Step 5: Add Update Comment

```bash
uv run linear create-comment <TICKET_ID> --body "## Plan Updated

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

The implementation plan has been updated."
```

### Step 6: Cleanup and Confirm

```bash
rm .tmp/<TICKET_ID>.md
```

Print confirmation:
```
================================================================================
PLAN UPDATE COMPLETE - Ticket: <TICKET_ID>
================================================================================
Run `uv run linear get-issue <TICKET_ID>` to fetch plan.

Review the implementation plan in the ticket description.
YOU ARE REVIEWING THE PLAN FOR HOW TO CHANGE THE CODE, NOT THAT CODE FOLLOWS THE PLAN.

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>
================================================================================
```

## Error Handling

- If ticket fetch fails or plan not found (empty file), suggest `/create-plan`
- If planner agent fails, report the error and stop
- If Linear ticket update fails, report the error and stop
- Always clean up temp file, even on errors

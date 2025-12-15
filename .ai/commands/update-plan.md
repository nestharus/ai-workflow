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
in Step 6 for the update comment.

**Validate the plan structure** after each planner invocation:

1. Find the first `---` separator line in the temp file
2. Verify the line immediately after `---` (skipping blank lines) is `# Implementation Plan`
3. Verify `## Plans` appears after `# Implementation Plan`
4. Verify `### Plan 1:` appears after `## Plans`
5. Verify plans are numbered sequentially (1, 2, 3, ...) with no gaps or letters (no "Plan 2a")

If any validation fails, rerun the planner with feedback explaining which structural
requirement was not met. The plan must follow this exact order after the `---` separator:
- `# Implementation Plan` (must be first header after `---`)
- `## Plans` (must appear before any `### Plan N:` headers)
- `### Plan 1:` (at minimum, Plan 1 must exist)
- Plans must be numbered sequentially: `### Plan 1:`, `### Plan 2:`, `### Plan 3:`, etc.
- No letter suffixes allowed (e.g., "Plan 2a" is invalid - renumber to "Plan 3")

### Step 4: Run Plan Drift Review

After all planner invocations complete and validation passes, run plan drift review:

```python
Task(subagent_type="plan-drift-reviewer", prompt="
ticket_id: <TICKET_ID>
plan_file: .tmp/<TICKET_ID>.md
")
```

If the drift review fails, the reviewer will report the specific drift issues. Address them
by invoking the planner again with the drift feedback, then re-run the drift review.

Loop until the drift review passes.

### Step 5: Update Linear Ticket

After drift review passes, update the ticket description directly from the temp file:

```bash
uv run linear update-issue <TICKET_ID> --description-file .tmp/<TICKET_ID>.md
```

**IMPORTANT**: Do NOT read the temp file. Pass it directly to `update-issue` using `--description-file`.

### Step 6: Write Receipt

Write a receipt documenting the update:

```bash
mkdir -p .tmp/receipts
cat > .tmp/receipts/update-plan-<TICKET_ID>.md << 'EOF'
# Plan Update Receipt

**Ticket**: <TICKET_ID>
**Timestamp**: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
**Operation**: UPDATE

## Inputs Used
- Existing plan from Linear ticket <TICKET_ID>
- Update requests: <LIST_OF_COMMENTS_OR_PROMPT>

## Outputs Produced
- Updated plan in Linear ticket <TICKET_ID>

## Changes Made
<SUMMARY_OF_ALL_UPDATES>

## Validation Performed
- Plan structure validation (passed)
- Plan drift review (passed)

## Deviations
None

## Next Action Recommended
Review the updated plan on the Linear ticket and verify it addresses all requirements.
EOF
```

### Step 7: Add Update Comment

Add a comment on the ticket summarizing the changes using the Linear CLI:

```bash
uv run linear create-comment <TICKET_ID> --body "## Plan Updated

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

The implementation plan in the ticket description has been updated."
```

### Step 8: Cleanup and Confirm

1. Delete the temp file

```bash
rm .tmp/<TICKET_ID>.md
```

2. Print confirmation message:

```text
================================================================================
PLAN UPDATE COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Run `uv run linear get-issue <TICKET_ID>` to fetch plan.

Please review the plan on the ticket:
1. Review the implementation plan in the ticket description
2. Verify the plan adequately addresses all requirements
3. Check that success criteria are measurable and complete

YOU ARE REVIEWING THE IMPLEMENTATION PLAN FOR HOW TO CHANGE THE CODE,
NOT THAT THE CODE FOLLOWS THE PLAN

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

Receipt written to: .tmp/receipts/update-plan-<TICKET_ID>.md
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If existing plan not found in ticket description (empty file), suggest running /create-plan first
* If planner agent fails, report the error output and stop
* If plan validation fails after retry, report the structural issues and stop
* If drift review fails after retry, report the drift issues and stop
* If Linear ticket update fails, report the error and stop
* Always clean up the temp file, even on errors
* Always write a receipt (mark as FAILED if errors occurred)

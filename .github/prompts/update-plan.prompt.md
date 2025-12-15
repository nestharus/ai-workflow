---
description: Update an existing implementation plan with additional requirements
---

# Update Implementation Plan

Update the implementation plan for ticket `{{input}}`.

Parse arguments: first token is ticket ID, rest is the update prompt (optional).

## Prerequisites

- The ticket must have an existing implementation plan
- If no update prompt is provided, unresolved comments will be fetched from the ticket

## Workflow

### Step 1: Fetch Existing Plan to Temp File

1. Create .tmp directory if it doesn't exist
2. Fetch the ticket description to a markdown file:

```bash
mkdir -p .tmp
linear get-issue-description <TICKET_ID> > .tmp/<TICKET_ID>.md
```

3. Verify the file was created and is not empty:

```bash
test -s .tmp/<TICKET_ID>.md && echo "exists"
```

If the file is empty or doesn't exist, the ticket has no description - suggest running create-plan first.

**IMPORTANT**: Do NOT read the temp file contents directly. The planner agent will handle reading and updating the file. This step only extracts the ticket description for the planner agent to process.

### Step 2: Determine Update Source

If an update prompt was provided in input (after the ticket ID), use that as the review feedback.

Otherwise, fetch unresolved comments from the ticket:

```bash
pr list-unresolved-comments <TICKET_ID>
```

Parse the comments output to extract individual comment bodies.

### Step 3: Run Planner Agent for Each Comment

For each comment (from prompt or fetched), invoke the planner agent separately using #agent:planner:

```text
#agent:planner file:.tmp/<TICKET_ID>.md

## Update Request
<SINGLE_COMMENT_CONTENT>
```

Wait for each planner agent invocation to complete before proceeding to the next comment. The planner agent will read from and update the temp file directly.

**Collect the summary** returned by each planner invocation. These summaries will be used in Step 6 for the update comment.

**Validate the plan structure** after each planner invocation:

1. Find the first `---` separator line in the temp file
2. Verify the line immediately after `---` (skipping blank lines) is `# Implementation Plan`
3. Verify `## Plans` appears after `# Implementation Plan`
4. Verify `### Plan 1:` appears after `## Plans`
5. Verify plans are numbered sequentially (1, 2, 3, ...) with no gaps or letters (no "Plan 2a")

If any validation fails, rerun the planner with feedback explaining which structural requirement was not met.

### Step 4: Run Plan Drift Review

After all planner invocations complete and validation passes, run plan drift review using #agent:plan-drift-reviewer:

```text
#agent:plan-drift-reviewer
ticket_id: <TICKET_ID>
plan_file: .tmp/<TICKET_ID>.md
```

If the drift review fails, address the drift issues by invoking the planner again with the drift feedback, then re-run the drift review. Loop until the drift review passes.

### Step 5: Update Linear Ticket

After drift review passes, update the ticket description directly from the temp file:

```bash
linear update-issue <TICKET_ID> --description-file .tmp/<TICKET_ID>.md
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

Add a comment on the ticket summarizing the changes:

```bash
linear create-comment <TICKET_ID> --body "## Plan Updated

Changes incorporated:
<SUMMARY_OF_ALL_UPDATES>

The implementation plan in the ticket description has been updated."
```

### Step 8: Cleanup and Confirm

1. Delete the temp file:

```bash
rm .tmp/<TICKET_ID>.md
```

2. Print confirmation message with ticket details and receipt location

## Output

The command will output a summary showing:
- Ticket ID and title
- Summary of changes made
- Validation results
- Receipt location
- Instructions for reviewing the updated plan

## Error Handling

- If ticket fetch fails, report the error and stop
- If existing plan not found in ticket description (empty file), suggest running create-plan first
- If planner agent fails, report the error output and stop
- If plan validation fails after retry, report the structural issues and stop
- If drift review fails after retry, report the drift issues and stop
- If Linear ticket update fails, report the error and stop
- Always clean up the temp file, even on errors
- Always write a receipt (mark as FAILED if errors occurred)

## Notes

- You are reviewing the implementation plan for how to change the code, NOT that the code follows the plan
- The planner agent handles reading and updating the temp file
- Plan structure must follow exact order: `# Implementation Plan`, `## Plans`, `### Plan 1:`, etc.
- Plans must be numbered sequentially with no gaps or letter suffixes

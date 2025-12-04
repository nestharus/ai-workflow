---
description: Create an implementation plan from a Linear ticket
argument-hint: <ticket-id>
allowed-tools: Bash, Read, Write, Glob, Grep, mcp__linear-server__get_issue, mcp__linear-server__create_comment
---

Create an implementation plan for Linear ticket `$ARGUMENTS`.

## File Naming Convention

All plan and strategy files follow this naming convention and are attached to the ticket:
- `implementation-plan.md` - Implementation plan
- `implementation-strategy.md` - Implementation strategy
- `test-plan.md` - Test plan
- `test-strategy.md` - Test strategy

## Workflow

1. **Fetch Ticket**: Use `mcp__linear-server__get_issue` to retrieve the ticket details including title and description.

2. **Run Planner Agent**: Execute the planner agent with the ticket details:
   ```bash
   uv run agent.tasks --agent planner --prompt "Ticket ID: <ID>
   Title: <TITLE>
   Description:
   <DESCRIPTION>"
   ```
   Capture the plan output from stdout.

3. **Save Plan**: Write the plan to `.tasks/plans/<ticket-id>/implementation-plan.md` (create directory if needed).

4. **Update Linear**: Add the plan as a comment on the ticket using `mcp__linear-server__create_comment` with the full plan content in markdown format.

5. **Output Review Request**: Print the following to terminal:

```
================================================================================
PLAN REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Plan saved to: .tasks/plans/<ticket-id>/implementation-plan.md
Plan posted to Linear as comment.

Please review the plan on the ticket:
1. Open the ticket in Linear
2. Review the attached plan comment against the ticket description
3. Verify the plan adequately addresses all requirements
4. Check that success criteria are measurable and complete

After review, run /apply-plan to execute the implementation.
================================================================================
```

## Error Handling

- If ticket fetch fails, report the error and stop
- If planner agent fails, report the error output and stop
- If Linear comment creation fails, still save the local plan file and notify the user

## Design Notes

The current implementation posts the concrete plan content as a comment on the Linear
ticket. It does not maintain a separate template artifact per ticket. If future work
requires a distinct reusable template object (separate from the generated plan), this
workflow will need to be extended to create and store that artifact.

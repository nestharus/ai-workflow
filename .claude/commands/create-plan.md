---
description: Create an implementation plan from a Linear ticket (or create ticket from prompt)
argument-hint: [<ticket-id> | <description of work>]
allowed-tools: Bash, Read, Write, Glob, Grep
---

Create an implementation plan. If `$ARGUMENTS` is a ticket ID (e.g., `NES-123`), fetch that ticket. Otherwise, create a new ticket using the arguments as a description.

## Plan Storage

Plans are stored directly in the Linear ticket description. When a plan is created or updated,
the ticket description is updated to include the full plan content below a `---` separator.

## Workflow

### Step 1: Determine Ticket

Check if `$ARGUMENTS` looks like a ticket ID (format: `XXX-NNN` where XXX is letters and NNN is numbers):

**If ticket ID provided:**
Fetch the ticket using the Linear client:
```bash
uv run python -c "
from scripts.clients.linear_client import LinearClient
import json
client = LinearClient()
issue = client.get_issue('$ARGUMENTS')
print(json.dumps(issue, indent=2))
"
```

**If no ticket ID (description provided instead):**
1. Get available projects using the Linear client:
```bash
uv run python -c "
from scripts.clients.linear_client import LinearClient
import json
client = LinearClient()
projects = client.list_projects()
print(json.dumps(projects, indent=2))
"
```
2. Analyze the description to determine the most appropriate project:
   - "AI Workflow Application Phase N" - for app development work
   - "Task System" - for task/agent system work
   - "Test Framework" - for testing infrastructure
   - "Documentation" - for documentation work
   - "GitHub CI" - for CI/CD work
   - "Knowledge System" - for knowledge/fact extraction work
   - Default to "Task System" if unclear
3. Get team ID using the Linear client (use "Neshq"):
```bash
uv run python -c "
from scripts.clients.linear_client import LinearClient
import json
client = LinearClient()
teams = client.list_teams()
print(json.dumps(teams, indent=2))
"
```
4. Create ticket using the Linear client:
```bash
uv run python -c "
from scripts.clients.linear_client import LinearClient
import json
client = LinearClient()
issue = client.create_issue(
    title='<EXTRACTED_TITLE>',
    description='$ARGUMENTS',
    team='Neshq',
    project='<SELECTED_PROJECT>'
)
print(json.dumps(issue, indent=2))
"
```
5. Capture the created ticket ID from the response

### Step 2: Run Planner Agent

Execute the planner agent using the MCP client (use `timeout: 600000`):
```bash
uv run agent.mcp wait --command "uv run agent.tasks --agent planner --prompt \"Ticket ID: <ID>
Title: <TITLE>
Description:
<DESCRIPTION>\"" --max-seconds 600
```

The `agent.mcp wait` command handles all polling internally and returns a final status.
No re-running is required in the normal case.

Handle each status:
- `"status": "completed"` → Agent finished, extract plan from `stdout`
- `"status": "failed"` → Check `error` field and `stderr` for details
- `"status": "timeout"` → Job exceeded time limit. Options:
  1. Increase `--max-seconds` and re-run if more time is needed
  2. Check agent logs for stuck processes
  3. Manually intervene if the task is inherently too long
- `"status": "killed"` → Job was externally terminated

### Step 3: Update Linear Ticket

Update the ticket description using the Linear client to append the plan content:
```bash
uv run python -c "
from scripts.clients.linear_client import LinearClient
client = LinearClient()
client.update_issue(
    issue_id='<TICKET_ID>',
    description='''<ORIGINAL_DESCRIPTION>

---

# Implementation Plan

<PLAN_CONTENT>'''
)
print('Ticket description updated with plan')
"
```

The plan becomes part of the ticket description and is visible directly on the ticket.

### Step 4: Output Review Request

Print the following to terminal:

```
================================================================================
PLAN REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Plan attached to Linear ticket description.

Please review the plan on the ticket:
1. Open the ticket in Linear: <LINEAR_TICKET_URL>
2. Review the implementation plan in the ticket description
3. Verify the plan adequately addresses all requirements
4. Check that success criteria are measurable and complete

After review, run /execute-plan <ticket-id> to implement.
================================================================================
```

## Error Handling

- If ticket fetch fails, report the error and stop
- If ticket creation fails, report the error and stop
- If planner agent fails, report the error output and stop
- If Linear ticket update fails, report the error and stop

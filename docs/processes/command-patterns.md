# Command Types and Invocation Patterns

This document describes how agents interact with the orchestrator and how workflows are
triggered.

## Orchestrator Message Submission

Agents invoke other agents or report status by submitting messages to the orchestrator:

```bash
# Agent submits a message to orchestrator
curl -X POST http://localhost:8000/api/v1/orchestrator/submit \
  -H "Content-Type: application/json" \
  -d '{
    "role": "R2 Tech Planner",
    "task": "break down phase X into tasks",
    "context": {"phase_doc": "docs/plans/phase1.md"},
    "requesting_agent": "R1 Tech Strategist"
  }'
```

The message payload includes:

* **role**: The target role to handle the task
* **task**: Description of what needs to be done
* **context**: Additional context data (file paths, metadata)
* **requesting_agent**: The agent submitting the message

## Orchestrator Invokes Agents

The orchestrator manages the execution environment and invokes agents using subprocess
calls to `droid exec`. Agents should not worry about this mechanism but should be aware
they are running in this context.

## GitHub Integration

All GitHub interactions start with a webhook to the receiver service, flow to the
orchestrator, and result in an agent being invoked with GitHub MCP access. Agents use
MCP to fetch PR details, issue information, and other GitHub data as needed for their
tasks.

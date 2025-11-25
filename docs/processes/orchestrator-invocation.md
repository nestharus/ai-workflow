# Orchestrator Invocation Examples

This document shows how the orchestrator internally invokes agents via `droid exec`.

> **Warning**: These commands are for internal orchestrator use only and should NOT be
> executed by humans or agents directly.

## Internal Invocation Command

The orchestrator executes agents using subprocess calls:

```bash
# INTERNAL USE ONLY: Orchestrator invoking an agent
droid exec --skip-permissions-unsafe --model custom:gemini-3-pro-preview-low \
  --f "/tmp/agent_context_123.json"
```

## Command Components

* **`droid exec`**: The base command for agent execution
* **`--skip-permissions-unsafe`**: Bypasses permission checks (orchestrator is trusted)
* **`--model`**: Specifies the AI model to use for the agent
* **`--f`**: Path to a JSON file containing the agent context

## Agent Execution Context

Agents run within this execution environment but do not need to manage it. The
orchestrator:

* Prepares the context file with task details, workflow state, and permissions
* Spawns the agent process with appropriate flags
* Monitors execution and captures output
* Processes results and continues the workflow

## Important Notes

* Agents should be aware they run in this context but not execute these commands
* The context file is temporary and cleaned up after execution
* Multiple agents may run concurrently in separate worktrees

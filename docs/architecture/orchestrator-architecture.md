# Orchestrator Architecture

The system is built around a central **FastAPI Orchestrator Service** that manages the
lifecycle of all workflows.

## Message Routing

The orchestrator receives messages from agents and routes them to the appropriate workflow
instance. Messages include role, task, context, and requesting agent information.

## Workflow State

Manages the state of active workflows and coordinates handoffs between roles. Tracks which
workflows are in progress and what stage each is at.

## Agent Invocation

Uses `app/services/agent_invoker.py` to spawn `droid exec` subprocesses for agent execution.
The orchestrator manages the execution environment and context for each agent invocation.

## Ticket Claiming

Implements a first-come-first-served mechanism for agents to claim tasks. The ticket manager
(`app/services/ticket_manager.py`) broadcasts availability and handles claim requests.

## PR Comment Routing

Analyzes PR comments and routes them to the appropriate agent based on context. The PR
comment router (`app/services/pr_comment_router.py`) determines which role should handle
each comment.

## Git Worktrees

Manages temporary git worktrees to allow multiple agents to work in parallel without
conflict. Each agent can work in an isolated worktree while the orchestrator coordinates
merging results.

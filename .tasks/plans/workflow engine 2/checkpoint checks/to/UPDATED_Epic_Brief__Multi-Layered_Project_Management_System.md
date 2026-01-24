# Epic Brief: Multi-Layered Project Management System

## Summary

This Epic introduces a local-only project planning and execution system that connects high-level planning artifacts to step-by-step implementation, with durable evidence and autonomous recovery.

The migrated target state uses:

- **Patch-Stream (jj-backed) change stacks** as the code-change backbone (tickets are change stacks; steps produce patches)
- a durable **Workspace State Store (WSS)** for planning docs and workflow state
- durable **sharded JSONL logs** as the execution evidence stream
- filesystem **Notifications** and **Control Actions** queues for out-of-band communication and user responses
- **ephemeral sandboxes** for lint/tests/build and any tooling that requires a hydrated filesystem view
- **flat orchestration** and **mandatory PAUSE** as core runtime invariants
- an optional **notifications-only UI** that does not gate workflows

**Constraints & Invariants**

- Local-only, single-machine execution. Not distributed, not cloud.
- Runtime artifacts are local and not committed to git.
- Prefer robustness over micro-optimizing I/O.
- Step logging is always on (step enter/exit + key events).
- Dynamic tracing is optional and enabled per-step when needed.
- Root orchestration is flat: root directly owns/controls all step/agent processes (no grandchildren).
- Pause is mandatory: on PAUSE, processes must stop promptly; enforcement is inside each process.
- Patch-Stream code-change model (jj-backed change graph). Persistent worktrees are not required for the system to function.
- Lint/tests/build run in ephemeral sandboxes (queued execution).
- UI is optional and must not gate workflows; MVP UI surfaces out-of-band notifications only.
- Users do not search logs by text; logs are retrieved and navigated by IDs.
- Keyword/fuzzy search is sufficient for project and ticket lookup; no embedding-model requirement.
- We avoid fixed iteration caps as termination criteria (progress-based circuit breakers instead).
- The system must support many concurrent writers without a single-writer bottleneck.
- All runtime files live under a single predictable root for easy cleanup and backup.


## Goals

- Preserve context across multi-step task execution and avoid “lost context” between steps.
- Provide durable, auditable evidence for debugging and self-healing without relying on a database service.
- Enable parallel ticket execution safely via independent change stacks (without persistent worktrees).
- Reduce repeated integration pain by persisting conflict resolution rationale and evidence.
- Keep runtime footprint minimal and predictable (single runtime root, no required ports).

## Philosophy

- Robustness and auditability come first: crash/power-loss tolerance is a requirement.
- Changes are patches, not mutable workspace files.
- The system is ID-driven: runs, steps, and notifications are navigated by stable IDs.
- Avoid fixed max-iteration caps; use progress-based circuit breakers and explicit give-up records.

## Scope & Assumptions

- Local-only, single machine execution.
- No external API integrations; planning docs are loaded manually (paste or file path).
- Runtime artifacts are not committed to git and live under `~/.workflow/`.
- The UI is optional and limited to notifications in MVP.

## Durability boundary

Persisted:

- WSS docs (projects, tickets, tasks, run and step metadata, evaluation reports, conflict records)
- log shards (JSONL)
- conclusions (tool/performance)
- notifications and control actions

Ephemeral:

- sandboxes
- hydrated workspaces
- caches

## Problem

Developers managing multi-ticket projects face:

- fragmented planning and execution context
- lost implementation rationale between steps
- opaque conflict resolution with no durable rationale
- manual gap tracking between planned and delivered work
- no workflow observability during long-running steps
- failures that require manual investigation

## Proposed solution

Five integrated components:

1. **Project Manager**
   - imports and indexes planning docs
   - infers dependencies and suggests ordering
   - opens Ticket Manager for execution
   - acts as QA interface for notifications and control actions

2. **Ticket Manager**
   - manages tasks for a ticket
   - decomposes tasks into steps with approval gates
   - executes steps sequentially, producing patches on the ticket’s change stack
   - records deviations and evaluation artifacts in WSS

3. **Enhanced Rebase**
   - rebases ticket stacks via jj pointer movement
   - treats conflicts as resolver jobs
   - uses planning docs and prior conclusions to resolve conflicts
   - persists conflict resolution records with evidence refs

4. **Evaluation**
   - runs sandbox validation and gap analysis
   - writes durable gap reports into WSS
   - drives gap-driven ticket creation

5. **Monitoring and self-healing**
   - always-on step logging and optional per-step tracing
   - investigate-first anomaly response
   - mandatory PAUSE control plane
   - investigator job contract and durable conclusions to avoid repeat debugging
   - notifications for unfixable issues requiring user action

## Success criteria

The system is successful when:

- Workflows remain debuggable using only durable evidence (WSS + log shards).
- Long-running or stuck steps can be paused promptly and safely.
- A meaningful fraction of failures can be auto-diagnosed and repaired as patches, validated in sandboxes.
- Integration and rebase conflicts produce durable resolution rationale and reduce repeated confusion.
- Users can run multiple tickets in parallel without persistent worktrees and without losing context.

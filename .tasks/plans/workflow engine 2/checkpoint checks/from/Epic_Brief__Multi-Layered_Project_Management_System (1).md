# Epic Brief: Multi-Layered Project Management System

## # Epic Brief: Multi-Layered Project Management System

## Summary

This Epic introduces a comprehensive project management and implementation system with integrated autonomous monitoring and self-healing infrastructure. The system bridges high-level planning (Traycer Epic mode) with granular execution through isolated git worktrees. It consists of five integrated components: a **Project Manager** that orchestrates documentation, tickets, and dependencies; a **Ticket Manager** that coordinates task execution; a **Task Execution Workflow** that breaks tasks into AI-guided steps with context preservation and deviation tracking; an **Enhanced Rebase** mechanism that intelligently resolves conflicts using project documentation; and an **Autonomous Monitoring System** (PostgreSQL logging + GLM anomaly detection + Rust/React UI) that detects failures, kills runaway processes, triggers repairs, and resumes workflows without user intervention. The system persists all artifacts (specs, tickets, tasks, deviations, conflict resolutions) **locally in PostgreSQL** (local Docker container; uncommitted) for auditability and enables iterative refinement through evaluation worktrees and gap-driven ticket creation. Artifacts can be exported to files for manual upload/sharing if desired. This creates a complete workflow from planning through implementation, review, conflict resolution, final integration, autonomous error recovery, and continuous monitoring.

## Scope & Assumptions

- **Local development only** (single dev machine; not distributed; not cloud).
- **No external API integrations** (no Traycer API, no Linear API). Documentation is loaded manually via paste or file paths.
- **PostgreSQL state is local and uncommitted**: stored in a local Docker volume (not in the repo). Any local `.env` / exported dumps must be `.gitignore`’d.
- **No external brokers/queues**. Real-time UI updates use PostgreSQL `LISTEN/NOTIFY` wakeups + cursor-based reads from `context_logs`.

## Context & Problem

### Who's Affected

**Primary Users:**

- Developers managing complex, multi-ticket projects with interdependencies
- Teams working on parallel features that may conflict during integration
- Project leads needing visibility into implementation deviations from plans

**Current Pain Points:**

1. **Fragmented Project Context**: Developers currently manage projects across multiple systems (Traycer for planning, optional external trackers such as Linear, git for implementation) with no unified workspace that maintains context across all three layers.
2. **Lost Implementation Context**: When implementing multi-step tasks, developers lose context between steps. There's no mechanism to track what was delivered in prior steps, why deviations occurred, or how changes relate to the original plan. Review agents see "NOT PART OF THE PLAN" without understanding legitimate adaptations.
3. **Opaque Conflict Resolution**: The existing rebase workflow (fil`.claude/commands/rebase.md`) resolves conflicts at the code level but doesn't understand *why* conflicts exist or what the conflicting projects were trying to accomplish. When two projects refactor the same code differently or implement conflicting approaches, there's no documentation of the resolution rationale, making future rebases encounter the same confusion.
4. **No Dependency-Aware Scheduling**: Tickets are executed sequentially even when some could run in parallel. There's no system to analyze dependencies and enable concurrent work on independent tickets.
5. **Manual Gap Tracking**: After implementation, identifying gaps between what was planned and what was delivered requires manual review. There's no automated evaluation that compares final implementation against all planning documents and surfaces missing functionality.
6. **Traceability Loss**: When conflicts are resolved by merging changes (not just picking one side), git history loses the ability to trace where merged lines came from. Future rebases can't understand the merged state's origin, leading to repeated confusion.
7. **No Workflow Observability**: When workflows fail, there's no execution trace to understand what went wrong. The workflow-repair agent operates on "vibes" without access to command history, outputs, or state transitions. Debugging requires manual investigation. Example: Infinite loops show only a timer with no visibility into what's happening.
8. **Invisible Execution**: Developers can't see what's happening during long-running workflows. There's no real-time visibility into step execution, agent reasoning, or deviation detection. Users must wait for completion to see results.
9. **Manual Intervention for Failures**: All workflow failures require manual investigation and repair. There's no autonomous detection of anomalies (e.g., processes running longer than expected) or automatic recovery.
10. **No Subprocess Management**: When workflows spawn subprocesses that go awry (infinite loops, hangs), there's no mechanism to kill them. Runaway processes continue consuming resources.
11. **Silent Errors**: Workflows can encounter errors (bad commands, missing dependencies) that slow execution but don't fail completely. These errors go unnoticed until manual review.

### Where in the Product

This affects the **development workflow layer** of the ai-workflow repository:

- **Existing touchpoints**: 
  - fil`.claude/commands/review-implementation.md` (implementation review)
  - fil`.claude/commands/update-pr.md` (PR updates)
  - fil`.claude/commands/rebase.md` (conflict resolution)
  - fil`.claude/commands/merge.md` (PR merging)
  - fil`scripts/pr/` (PR management utilities)
  - fil`scripts/agents/` (agent orchestration)
  - fil`scripts/article_writer/tools/workflow/` (context logging example)
- **New components**:
  - Project Manager command (interactive workspace management)
  - Ticket Manager command (task coordination)
  - Task Execution Workflow (step-by-step implementation with context)
  - Task Decomposition Agent (mutation-free task splitting)
  - Context Manager agent (GLM-based context preservation and deviation tracking)
  - Enhanced rebase investigation (project-aware conflict resolution)
  - Evaluation worktree workflow (gap analysis)
  - PostgreSQL logging system (workflow execution capture at step granularity)
  - Agent runner wrapper (stdout/stderr capture and parsing)
  - Autonomous monitoring agent (GLM-based anomaly detection and process management)
  - Rust/React monitoring UI (Tauri desktop app with notification center)
  - Enhanced workflow-repair agent (trace-based debugging with JIT scripting)
  - Suspended process manager (tracks killed processes pending repair)

### Current State

Developers use:

- Traycer Epic mode to create specs and tickets
- Optional external tracker (e.g., Linear) used manually (no API integration)
- Manual worktree creation for ticket isolation
- Existing review/rebase/merge commands that operate at code level only
- No systematic way to track deviations, manage dependencies, or preserve implementation context
- No visibility into workflow execution or debugging capabilities
- Loose file-based workspaces (not queryable or structured)
- Manual intervention required for all workflow failures
- No subprocess management (can't kill runaway processes)
- No anomaly detection (infinite loops go unnoticed)

The gap is the **missing orchestration and observability layer** that:

1. Connects planning artifacts to execution context
2. Maintains traceability through deviations and conflicts
3. Enables intelligent scheduling and review
4. Provides real-time visibility into workflow execution
5. Captures execution traces for debugging and self-healing
6. Structures workspace data for querying and analysis
7. Autonomously detects, investigates, repairs, and resumes failed workflows
8. Enables parallel execution of independent workflows

### Success Criteria

The system is successful when:

1. **Autonomous Error Resolution**: Errors auto-resolve without user intervention (monitoring agent detects anomalies, kills processes, triggers repair, resumes workflows)
2. **Parallel Execution**: User can run multiple Traycer planning workflows simultaneously without manual coordination
3. **Zero Manual Debugging**: User never needs to manually investigate workflow failures (agents handle all debugging via execution traces)


# Architecture

This module covers documentation for folder structure, services, endpoints, explanations
of how things integrate and work together, project overview and directory.

## Topics

### Project Overview

**File:** `project-overview.md`

Describes the Developing With AI 2.0 system: an automated AI workflow system using a
5-role skeleton across four domains (Product, UX, UI, Technical). Covers the FastAPI
orchestrator service, webhook receiver service, agent interaction model via `droid exec`,
and the goal of facilitating high-quality software development through structured
collaboration.

**Apply when:**

* Onboarding new agents or developers
* Understanding the overall system architecture
* Explaining the project to stakeholders

### Repository Structure

**File:** `repository-structure.md`

Provides a comprehensive directory and file reference for the codebase. Maps key
directories (`.factory/droids/`, `docs/`, `app/routes/`, `app/services/`, `app/contracts/`,
`webhook_receiver/`, `openapi/`, `tests/`, `tools/`, `scripts/`) to their purposes and
contents.

**Apply when:**

* Navigating the codebase for the first time
* Locating specific components or services
* Understanding code organization conventions

### The 5-Role Skeleton

**File:** `roles-skeleton.md`

Defines the five agent roles (R1: Strategy Planner, R2: Planner, R3: Implementor/Editor,
R4: Quality Reviewer, R5: QA & Maintenance) and their responsibilities within the
orchestrator-mediated workflow. Explains how roles interact and hand off work through
the orchestrator.

**Apply when:**

* Understanding agent role responsibilities
* Designing workflow handoffs between roles
* Troubleshooting workflow routing issues

### Orchestrator Architecture

**File:** `orchestrator-architecture.md`

Details the central FastAPI Orchestrator Service that manages workflow lifecycle. Covers
message routing, workflow state management, agent invocation via `app/services/agent_invoker.py`,
ticket claiming, PR comment routing, and git worktree management for parallel agent work.

**Apply when:**

* Understanding orchestrator capabilities
* Implementing new workflow routing logic
* Debugging agent invocation or message routing

### Webhook Receiver Service

**File:** `webhook-receiver.md`

Describes the standalone Webhook Receiver Service (`webhook_receiver/`) that handles
GitHub events. Covers signature verification (HMAC SHA256), event parsing (PR comments,
issues), event forwarding to the orchestrator, and the separation of concerns (no direct
MCP access).

**Apply when:**

* Integrating with GitHub webhooks
* Understanding event security and validation
* Debugging webhook event flow

### Event Flow Architecture

**File:** `event-flow.md`

Visualizes the end-to-end event flow from GitHub webhook to agent execution using a
Mermaid sequence diagram. Shows the path: GitHub -> Webhook Receiver -> Orchestrator ->
Agent -> GitHub MCP -> Orchestrator, with signature verification, routing, and result
processing.

**Apply when:**

* Understanding the complete event lifecycle
* Debugging event routing or processing issues
* Designing new event-driven workflows

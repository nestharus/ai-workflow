# Phase 1 — Implementation Plan

This document provides the Automated Orchestrator-Based Implementation Plan, realigning the strategy to create
a fully automated, orchestrator-driven system while maintaining the "Developing With AI 2" role structure.

The system replaces manual human orchestration with a FastAPI-based Orchestrator Service that routes messages
and invokes agents, and a standalone Webhook Receiver Service for GitHub integration.

This plan enforces the core tenets of "Developing With AI 2" within an automated framework:

1. **Orchestrator-Based Automation:** A central orchestrator service manages the workflow state and invokes
   agents via `droid exec` subprocesses.
2. **The 5-Role Skeleton:** Each domain (Product, UX, UI, Technical) utilizes specialized agents for Strategy
   (R1), Planning (R2), Implementation (R3), Quality Review (R4), and QA/Maintenance (R5).
3. **Automated Routing:** The orchestrator routes messages between agents and domains based on defined
   workflows.
4. **Documentation-First Knowledge Graph:** The system relies on structured documentation as the source of
   truth.

## Automated Orchestrator-Based Implementation Plan

### Phase 1: Initialize Project Structure and Knowledge Graph

We initialize the structure required for the orchestrator service and knowledge graph.

## 1.1. Create Root Directory and Basic Structure

```bash
# Initialize the root directory and core folders
mkdir -p dev-with-ai-v2-core
cd dev-with-ai-v2-core
git init

# Create the documentation-first knowledge graph structure
mkdir -p docs/product docs/ux docs/ui docs/tech docs/qa docs/architecture docs/guides

# Create directories for agent definitions (Custom Droids), tools, and scripts
mkdir -p .factory/droids/product .factory/droids/ux .factory/droids/ui .factory/droids/tech
mkdir -p .factory/droids/shared
mkdir -p tools
mkdir -p scripts

# Create application structure
mkdir -p app/contracts app/services app/routes app/core
mkdir -p webhook_receiver
```

## 1.2. Initialize `AGENTS.md` (The Entry Point)

```bash
cat << EOF > AGENTS.md
# AI Agent Entry Point

Welcome to the **Developing With AI 2.0** system. This repository follows an **automated, orchestrator-based architecture** where a central orchestrator service manages workflows and agent invocations.

## Repository Structure
* **\`.factory/droids/\`**: Agent definitions (POML) organized by domain.
* **\`docs/\`**: The Coarse Knowledge Graph (source of truth).
* **\`app/\`**: The FastAPI Orchestrator Service.
* **\`webhook_receiver/\`**: Standalone GitHub webhook handler.

## Operational Protocols
1. **Orchestrator Submission**: Agents submit messages to the orchestrator via POST to \`/api/v1/orchestrator/submit\` instead of calling other agents directly.
2. **No Long-Running Operations**: Agents must not make long-running tool calls directly; instead, submit messages to the orchestrator to request long-running tasks.
3. **Git Worktree Usage**: Agents may work in parallel using git worktrees managed by the orchestrator.
EOF
```

## 1.3. Initialize `docs/README.md` (The Index)

```bash
cat << EOF > docs/README.md
# Documentation Index (Coarse Knowledge Graph)

## Domains
* \`docs/product/\`: Strategy and requirements.
* \`docs/ux/\`: User flows and experience guidelines.
* \`docs/ui/\`: Component specs and visual guidelines.
* \`docs/tech/\`: Architecture and implementation details.
* \`docs/qa/\`: Quality assurance processes, SLOs, and metrics thresholds.

## Core Guides
* \`docs/architecture/overview.md\`: High-level architectural vision.
* \`docs/guides/workflow.md\`: Detailed description of the automated orchestrator workflow.
EOF
```

## 1.4. Initialize Orchestrator Workflow Guidelines

This document defines the automated process, replacing the human-in-the-loop process.

```bash
cat << EOF > docs/guides/workflow.md
# Automated Orchestrator Workflow Guidelines

## Architecture
1. **Orchestrator Service**: Central FastAPI service that routes messages and manages state.
2. **Webhook Receiver**: Standalone service that receives GitHub events and forwards them to the orchestrator.
3. **Agent Execution**: Agents are invoked by the orchestrator via \`droid exec\` in subprocesses.
4. **Message Bus**: Agents communicate by submitting messages to the orchestrator.

## Automated Workflow Execution
* **Submission**: Agents POST messages to \`/api/v1/orchestrator/submit\`.
* **Routing**: Orchestrator determines the next step/agent based on the message and workflow state.
* **Invocation**: Orchestrator spawns a new agent process with the required context.
* **Parallelism**: Multiple agents can run simultaneously using git worktrees.

## Git Worktree Management for Parallel Work
* The orchestrator creates a temporary worktree for each agent execution.
* Agents perform file operations within their assigned worktree.
* The orchestrator handles merging changes back to the main branch or PR branch.
EOF
```

## 1.5. Initialize Orchestrator Service Structure

```bash
# Create orchestrator contract definitions
cat << EOF > app/contracts/orchestrator_contracts.py
# Pydantic models for orchestrator messages
# - OrchestratorMessage: Agent submission schema
# - WorkflowEvent: Internal routing events
# - TicketClaimRequest/Response: Ticket claiming
# - PRCommentEvent: PR comment notifications
EOF

# Create orchestrator service
cat << EOF > app/services/orchestrator_service.py
# Message routing logic
# Workflow state management
# Integration with agent_invoker
EOF

# Create agent invoker service
cat << EOF > app/services/agent_invoker.py
# Execute droid exec via subprocess
# Timeout handling
# Git worktree management
EOF
```

## 1.6. Initialize Webhook Receiver Service

```bash
# Create webhook receiver FastAPI app
cat << EOF > webhook_receiver/main.py
# Standalone FastAPI application
# GitHub webhook endpoint with signature verification
# Event parsing and forwarding to orchestrator
EOF

# Create webhook receiver Dockerfile
cat << EOF > webhook_receiver/Dockerfile
# Docker configuration for webhook receiver
EOF
```

## 1.7. Document Orchestrator API Endpoints

**Note:** The file `docs/architecture/orchestrator_api.md` is the single canonical source of truth for all
orchestrator endpoints and payload schemas (including `submit`, `claim-ticket`, `route-comment`, and
`workflow/{id}/status`). Refer to it for the most up-to-date details.

```bash
cat << EOF > docs/architecture/orchestrator_api.md
# Orchestrator API Documentation

## Overview
This document is the single canonical source of truth for all orchestrator API request and response schemas.

## Endpoints

### POST /api/v1/orchestrator/submit
Agent message submission.
* Request Schema: \`OrchestratorMessage\`
* Response Schema: \`WorkflowStatus\`

### POST /api/v1/orchestrator/claim-ticket
Ticket claiming mechanism.
* Request Schema: \`TicketClaimRequest\`
* Response Schema: \`TicketClaimResponse\`

### POST /api/v1/orchestrator/route-comment
PR comment routing.
* Request Schema: \`PRCommentEvent\`
* Response Schema: \`RoutingStatus\`

### GET /api/v1/orchestrator/workflow/{id}/status
Get workflow status.
* Response Schema: \`WorkflowStatus\`

## Data Schemas

### OrchestratorMessage
* role: Agent role (e.g., "R2 Tech Planner")
* task: Task description
* context: Contextual data (files, URLs, etc.)
* requesting_agent: Originating agent identifier

### TicketClaimRequest
\`\`\`json
{
  "ticket_url": "https://github.com/owner/repo/issues/123",
  "agent_id": "R2 Tech Planner",
  "domain": "technical"
}
\`\`\`

### TicketClaimResponse
\`\`\`json
{
  "claimed": true,
  "claim_id": "claim-uuid-123",
  "subscription_id": "sub-uuid-456"
}
\`\`\`
EOF
```

## 1.8. Document GitHub Integration Flow

```bash
cat << EOF > docs/architecture/github_integration.md
# GitHub Integration Architecture

## Webhook Flow
1. GitHub sends webhook to receiver service
2. Receiver verifies signature
3. Receiver parses event (PR comment, new issue)
4. Receiver forwards to orchestrator
5. Orchestrator routes to appropriate workflow
6. Orchestrator invokes agent via droid exec
7. Agent uses GitHub MCP to fetch details
8. Agent submits result back to orchestrator

## Ticket Claiming
* First-come-first-served mechanism
* Agents subscribe to ticket updates
* Orchestrator manages claim state in database

## PR Comment Routing
* Orchestrator analyzes comment context
* Routes to appropriate agent based on file/domain
* Agent responds via GitHub MCP
EOF
```

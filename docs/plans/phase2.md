# Phase 2: Implement Orchestrator and Webhook Receiver Services

## 2.0. Install Tools

Deep research capabilities are required by the **R1 Research Agent**. This tool is always invoked **indirectly
via the Orchestrator**, not by regular agents directly. R1 Strategy Planners request research by submitting
messages to `/api/v1/orchestrator/submit` with `role` set to `R1 Research Agent`. The orchestrator is
responsible for invoking the deep research tool within that specialized agent (see `docs/plans/phase3.md` for
POML definition).

```bash
# Clone a pinned release of the deep research tool (update tag/SHA when upgrading)
git -c advice.detachedHead=false clone --depth 1 --branch v0.1.0 https://github.com/nickscamara/open-deep-research.git tools/deep-research
# If the project publishes signed tags or checksums, verify the ref before use (e.g., git verify-tag v0.1.0;
# otherwise compare git rev-parse HEAD to a published commit SHA or tarball checksum)
cd tools/deep-research && git rev-parse HEAD
```

Document the tool's license and any known risks in the project notes, and add `tools/deep-research/`
to `.gitignore` if it remains a runtime-only dependency.

## 2.1. Implement Orchestrator Router and Contracts

We implement the core communication structures for the orchestrator.

**Note:** Ensure implementation matches the canonical specifications in
`docs/architecture/orchestrator_api.md`.

```bash
# Implement orchestrator contracts following patterns from example_contract.py
# - OrchestratorMessage with role, task, context, requesting_agent fields
# - WorkflowEvent for internal routing
# - TicketClaimRequest/Response
# - PRCommentEvent
# Use ConfigDict(extra="forbid"), Annotated, Field, model_validator

# Implement orchestrator router following patterns from example_router.py
# - POST /api/v1/orchestrator/submit endpoint
# - POST /api/v1/orchestrator/claim-ticket endpoint
# - POST /api/v1/orchestrator/route-comment endpoint
# - GET /api/v1/orchestrator/workflow/{id}/status endpoint
# Register router in app/core/factory.py
```

## 2.2. Implement Orchestrator Service and Agent Invoker

We implement the logic for managing workflows and executing agents.

```bash
# Implement OrchestratorService following patterns from example_service.py
# - __init__: Initialize dependencies (database, agent_invoker)
# - submit_message(): Route incoming agent messages to workflows
# - route_to_workflow(): Determine target workflow based on message
# - manage_workflow_state(): Track workflow execution state
# - shutdown(): Cleanup resources

# Implement AgentInvokerService
# - __init__: Initialize droid exec configuration
# - invoke_agent(): Execute droid exec via subprocess.run()
# - manage_worktree(): Create/cleanup git worktrees for parallel work
# - handle_timeout(): Manage agent execution timeouts
# - parse_agent_output(): Extract results from agent execution
# - shutdown(): Cleanup worktrees and processes
```

## 2.3. Implement Ticket Manager and PR Comment Router

```bash
# Implement TicketManagerService
# - claim_ticket(): First-come-first-served claiming logic
# - subscribe_to_ticket(): Register agent for ticket updates
# - get_ticket_status(): Query claim state from database
# - release_ticket(): Release claim when work completes

# Implement PRCommentRouterService
# - route_comment(): Analyze PR comment and determine target agent
# - extract_context(): Parse file paths, line numbers from comment
# - determine_domain(): Map file paths to domains (Product/UX/UI/Tech)
# - determine_role(): Map comment type to role (R1/R2/R3)
```

## 2.4. Implement Webhook Receiver Service

```bash
# Create webhook_receiver/main.py
# - FastAPI application with single POST /webhook/github endpoint
# - Signature verification using HMAC SHA256
# - Event parsing for PR comments and new issues
# - HTTP client to forward events to orchestrator
# - Error handling and retry logic

# Create webhook_receiver/contracts.py
# - GitHubWebhookPayload: Schema for GitHub webhook events
# - OrchestratorEventForward: Schema for forwarding to orchestrator

# Create webhook_receiver/Dockerfile
# - Python 3.12+ base image
# - Install dependencies (FastAPI, uvicorn, httpx)
# - Expose port 5000
# - Health check endpoint

# Update docker-compose.yml
# - Add webhook_receiver service
# - Configure environment variables (WEBHOOK_SECRET, ORCHESTRATOR_URL)
# - Network configuration to allow receiver → orchestrator communication
```

**Webhook hardening (add to the design/implementation above):**

* Validate `X-Hub-Signature-256` as the HMAC of the payload and source timestamps from payload timestamp
  fields, the `Date` header, or server-side delivery tracking (e.g., combine `X-GitHub-Delivery` with stored
  timestamps). Reject requests older than a configurable window (e.g., 5 minutes) and enforce a maximum
  payload size on both the FastAPI endpoint and the forwarding HTTP client (set explicit ASGI body limits and
  httpx request limits). Apply rate limiting per IP and per repository with configurable ceilings; use
  exponential backoff on retries when forwarding to the orchestrator. Optionally enforce IP allowlisting using
  GitHub’s published webhook CIDR ranges and refresh the allowlist on a schedule.

## 2.5. Configure Orchestrator Settings

```bash
# Update app/core/settings.py
# Add orchestrator-specific settings:
# - DROID_EXEC_PATH: Path to droid executable
# - DROID_MODEL: Model to use (gemini-3-pro-preview or custom:gemini-3-pro-preview-low)
# - AGENT_TIMEOUT_SECONDS: Maximum agent execution time
# - WORKTREE_BASE_PATH: Base directory for git worktrees
# - ORCHESTRATOR_DB_TABLE: Database table for workflow state
# - GITHUB_WEBHOOK_SECRET: Secret for webhook signature verification
```

**Secret management requirements:**
* Never commit `GITHUB_WEBHOOK_SECRET` or database credentials; store them in environment variables or a
  secrets manager (Vault, AWS Secrets Manager, GCP Secret Manager, or CI secrets store). Git-ignore local
  `.env` files used for development and reference env vars in `app/core/settings.py` via `os.environ`. Enforce
  least-privilege access, encryption at rest, and regular rotation for all secrets. Configure CI/CD and
  deployment environments to source secrets from their managed stores rather than repository files.

## 2.6. Document Agent-to-Orchestrator Communication Protocol

**Note:** See `docs/architecture/orchestrator_api.md` for full API details.

```bash
cat << EOF > docs/architecture/agent_communication.md
# Agent-to-Orchestrator Communication Protocol

## Message Submission

Agents submit messages to the orchestrator via HTTP POST to /api/v1/orchestrator/submit.

## Message Schema

**Refer to \`docs/architecture/orchestrator_api.md\` for the formal \`OrchestratorMessage\` schema.**

## Response Handling

* Orchestrator returns workflow_id for tracking
* Agent can poll /api/v1/orchestrator/workflow/{id}/status for results
* Or orchestrator can invoke callback agent with results

## Long-Running Operations

Agents must NOT make long-running tool calls directly (they will timeout).
Instead, submit a message to the orchestrator requesting the operation.
The orchestrator will invoke a specialized agent to handle it.

## Example: Agent Requesting Deep Research

Instead of calling the research tool directly, agent submits:
\`\`\`json
{
  "role": "R1 Research Agent",
  "task": "perform deep research on topic X",
  "context": {"topic": "X", "sources": [...]},
  "requesting_agent": "R1 Tech Strategist"
}
\`\`\`
EOF
```

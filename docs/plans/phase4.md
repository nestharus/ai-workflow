# Phase 4: Integrate Automated Feedback Routing and QA Monitoring

This implements the Quality Reviewer (R4) and QA & Maintenance (R5) roles, utilizing the orchestrator service
to automatically route feedback and alerts to the appropriate agents.

## 4.1. Configure Quality Reviewer (R4 - CodeRabbit/Macroscope)

We configure CodeRabbit (R4) to apply labels that the **Orchestrator Service** uses for automatic routing.

```bash
cat << EOF > .coderabbit.yaml
reviews:
  profile: "assertive"
  request_changes_workflow: true
  auto_review:
    enabled: true
  # Intelligent Routing Labels for Automated Orchestrator
  # The orchestrator parses these labels from GitHub webhook events and routes feedback to the appropriate agent automatically.
  labeling_instructions:
    - label: "feedback:r1_strategy"
      instructions: "Apply if comments question fundamental strategy, architecture, or high-level phasing. (Route to Strategy Planner)."
    - label: "feedback:r2_planning"
      instructions: "Apply if the implementation does not match the defined tasks or the plan was incomplete. (Route to Planner)."
    - label: "feedback:r3_implementation"
      instructions: "Apply for code style, bugs, performance issues, or security vulnerabilities. (Route to Editor)."
EOF
```

## 4.2. Implement Automated Feedback Routing

We replace the manual feedback notifier with an automated routing architecture integrated into the
orchestrator.

```bash
cat << EOF > docs/architecture/feedback_routing.md
# Automated Feedback Routing Architecture

## R4 Feedback Flow (CodeRabbit)
1. CodeRabbit posts PR review comments with labels
2. GitHub sends webhook to webhook receiver service
3. Webhook receiver verifies signature and parses event
4. Webhook receiver forwards event to orchestrator
5. Orchestrator extracts labels (feedback:r1_strategy, etc.)
6. Orchestrator routes to appropriate agent based on label:
   - feedback:r1_strategy → R1 Strategy Planner
   - feedback:r2_planning → R2 Planner
   - feedback:r3_implementation → R3 Editor
7. Orchestrator invokes agent via droid exec with feedback context
8. Agent uses GitHub MCP to fetch full PR details
9. Agent addresses feedback and submits result to orchestrator
10. Orchestrator invokes GitHub Agent to post response comment

## Orchestrator Routing Logic
The OrchestratorService.route_feedback() method:
- Parses GitHub webhook payload
- Extracts PR URL and labels
- Determines target agent role from label
- Determines domain from file paths in PR
- Constructs agent invocation message
- Invokes agent via AgentInvokerService

## Agent Feedback Handling
Agents receive feedback context:
- pr_url: GitHub PR URL
- comment_id: Specific comment to address
- file_path: File mentioned in feedback
- line_number: Line number if applicable
- feedback_text: The actual feedback comment

Agents use GitHub MCP to:
- Fetch full PR diff
- Read comment thread
- Post response comments
- Update PR status
EOF
```

## 4.3. QA & Maintenance Monitoring Integration (R5)

The QA role (R5) lives in the cloud and observes metrics, feeding alerts back into the workflow via webhooks.

```bash
cat << EOF > docs/qa/r5_monitoring_integration.md
# QA & Maintenance Monitoring Integration (Role 5)

## Monitoring Platform Webhook Configuration
Configure monitoring platform (Datadog, Sentry, Prometheus Alertmanager) to send alerts to webhook receiver:
- Webhook URL: https://your-domain.com/webhook/monitoring
- Payload format: JSON with event_type, severity, metric_name, threshold
- Signature: HMAC SHA256 using MONITORING_WEBHOOK_SECRET

## Webhook Receiver Monitoring Event Handling
The webhook receiver parses monitoring alerts:
- SLO violations
- Error rate spikes
- Performance degradation
- Security incidents

Forwards to orchestrator with event type "monitoring_alert"

## Orchestrator R5 Routing
When orchestrator receives monitoring alert:
1. Determine severity (critical, warning, info)
2. For critical alerts, invoke R1 Strategy Planner to initiate new workflow cycle
3. For warnings, invoke R3 Editor to apply hotfix
4. For info, log to database for trend analysis

## R5 Feedback Loop
R5 monitoring creates tickets in GitHub:
- Orchestrator invokes GitHub Agent to create issue
- Issue includes alert details, metrics, logs
- Issue is labeled with "monitoring:r5" and severity
- Orchestrator routes issue to appropriate R1 agent
- R1 agent analyzes and initiates fix workflow

## Automated Incident Response
For critical production issues:
1. Monitoring alert triggers webhook
2. Orchestrator invokes R1 Strategy Planner (emergency mode)
3. R1 creates incident response plan
4. Orchestrator invokes R3 Editor to apply hotfix
5. R3 submits PR with fix
6. Orchestrator invokes GitHub Agent to request review
7. After approval, orchestrator triggers deployment
EOF
```

## 4.4. Configure Webhook Receiver for Multiple Event Sources

```bash
# Update webhook_receiver/main.py to handle multiple endpoints
# - POST /webhook/github: GitHub events (PR comments, issues)
# - POST /webhook/monitoring: Monitoring alerts (Datadog, Sentry)
# - POST /webhook/coderabbit: CodeRabbit-specific events

# Each endpoint has its own signature verification
# Each endpoint forwards to orchestrator with appropriate event type

# Update webhook_receiver/contracts.py
# - GitHubWebhookPayload
# - MonitoringAlertPayload
# - CodeRabbitWebhookPayload
```

## 4.5. Document Ticket Claiming and PR Comment Subscription

**Note:** Refer to `docs/architecture/orchestrator_api.md` for the canonical API definition for ticket
claiming.

```bash
cat << EOF > docs/architecture/ticket_claiming.md
# Ticket Claiming and Subscription Mechanism

## New Ticket Flow
1. GitHub webhook for new issue arrives at receiver
2. Receiver forwards to orchestrator
3. Orchestrator broadcasts "new_ticket" event
4. First available agent (determined by orchestrator) claims ticket
5. Orchestrator records claim in database
6. Orchestrator subscribes claiming agent to ticket updates

## Ticket Claiming API
POST /api/v1/orchestrator/claim-ticket

**Note:** See \`docs/architecture/orchestrator_api.md\` for the exact request and response fields.

## PR Comment Subscription
When agent creates PR:
1. Agent submits PR creation request to orchestrator
2. Orchestrator invokes GitHub Agent to create PR
3. Orchestrator automatically subscribes creating agent to PR comments
4. When new comment arrives via webhook, orchestrator routes to subscribed agent

## Subscription Management
- Orchestrator maintains subscription table in database
- Maps ticket/PR URLs to agent IDs
- Routes incoming webhook events based on subscriptions
- Agents can unsubscribe when work completes
EOF
```

## 4.6. Document User-Provided URL Handling

```bash
cat << EOF > docs/guides/user_url_handling.md
# User-Provided URL Handling

## Manual QA Response Workflow
User provides ticket URL to orchestrator:
\`\`\`bash
curl -X POST http://localhost:8000/api/v1/orchestrator/submit \\
  -H "Content-Type: application/json" \\
  -d '{
    "role": "GitHub Agent",
    "task": "fetch ticket details and route to appropriate agent",
    "context": {"ticket_url": "https://github.com/owner/repo/issues/123"},
    "requesting_agent": "user"
  }'
\`\`\`

Orchestrator:
1. Invokes GitHub Agent to fetch ticket details
2. Analyzes ticket labels and content
3. Determines appropriate domain and role
4. Routes to agent (e.g., R2 Tech Planner)
5. Agent processes ticket and submits response

## Manual PR Review Response Workflow
User provides PR URL with new comments:
\`\`\`bash
curl -X POST http://localhost:8000/api/v1/orchestrator/submit \\
  -H "Content-Type: application/json" \\
  -d '{
    "role": "GitHub Agent",
    "task": "fetch PR comments and route to appropriate agent",
    "context": {"pr_url": "https://github.com/owner/repo/pull/456"},
    "requesting_agent": "user"
  }'
\`\`\`

Orchestrator:
1. Invokes GitHub Agent to fetch PR comments
2. Identifies new comments since last check
3. Routes each comment to appropriate agent based on file/domain
4. Agents address comments and submit responses
EOF
```

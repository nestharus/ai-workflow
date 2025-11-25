# Webhook Receiver Service

A standalone **Webhook Receiver Service** (`webhook_receiver/`) handles all incoming events
from GitHub. This service is separate from the orchestrator to maintain security boundaries
and separation of concerns.

## Signature Verification

Verifies HMAC SHA256 signatures to ensure webhook payloads are authentic and have not been
tampered with. Rejects any requests that fail signature verification.

## Event Parsing

Parses PR comments, new issues, and other GitHub events into structured data. Extracts
relevant information for workflow routing decisions.

## Event Forwarding

Forwards validated events to the Orchestrator Service for routing. The webhook receiver
does not make routing decisions; it only validates and forwards events.

## No MCP Access

The receiver service does NOT use GitHub MCP directly. It delegates all GitHub API
interactions to agents via the orchestrator. This ensures that only authenticated agents
with proper context access GitHub resources.

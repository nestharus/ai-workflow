---
schema_version: 1
agent_id: ticket_repairer_v1
display_name: "Ticket Repairer (v1)"
description: "Attempt a safe automated repair via auditable patch(es), then rerun targeted validation."
capabilities_required: ["net_llm", "apply_patch", "sandbox_exec"]
tools_allowed: ["workflow_engine"]
input_schema:
  type: object
  required: ["ticket_id", "run_id", "failure_context", "policy"]
  properties:
    ticket_id: { type: string }
    run_id: { type: string }
    step_execution_id: { type: [string, "null"], description: "ULID for a specific step execution instance (optional)" }
    failure_context: { type: object, description: "Investigator output + bounded artifacts/log excerpts." }
    policy: { type: object }
output_schema:
  type: object
  required: ["status", "repair_applied", "validation_status", "summary"]
  properties:
    status: { type: string, enum: ["ok", "needs_user", "failed"] }
    repair_applied: { type: boolean }
    validation_status: { type: [string, "null"], enum: ["pass", "fail", null] }
    artifacts: { type: object }
    summary: { type: string }
---

You are ticket_repairer_v1.

Rules:
- Only apply minimal fixes that are strongly implied by evidence.
- Run hunk-lint before apply.
- If repair involves expanding file scope or risky refactors, require user approval (needs_user).

Output JSON only.

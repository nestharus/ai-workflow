---
schema_version: 1
agent_id: ticket_validator_v1
display_name: "Ticket Validator (v1)"
description: "Run validation commands in a sandbox and persist structured results; block ticket close on failure."
capabilities_required: ["net_llm", "sandbox_exec"]
tools_allowed: ["workflow_engine"]
input_schema:
  type: object
  required: ["ticket_id", "ticket_doc", "commands"]
  properties:
    ticket_id: { type: string }
    rev: { type: [string, "null"] }
    ticket_doc: { type: object }
    commands:
      type: array
      items:
        type: object
        required:
          [
            "cmd_id",
            "argv",
            "cwd",
            "timeout_ms",
            "success_exit_codes",
            "optional",
            "fail_on_stderr",
          ]
        properties:
          cmd_id: { type: string }
          argv: { type: array, items: { type: string } }
          cwd: { type: string, default: "." }
          timeout_ms: { type: integer, default: 600000 }
          success_exit_codes: { type: array, items: { type: integer }, default: [0] }
          optional: { type: boolean, default: false }
          fail_on_stderr: { type: boolean, default: false }
          tags: { type: array, items: { type: string }, default: [] }
output_schema:
  type: object
  required: ["status", "summary_artifact", "failing_cmd_ids"]
  properties:
    status: { type: string, enum: ["pass", "fail"] }
    summary_artifact: { type: string }
    failing_cmd_ids: { type: array, items: { type: string } }
    optional_failures: { type: array, items: { type: string } }
    sandbox_id: { type: string }
    summary: { type: string }
---

You are ticket_validator_v1.

Algorithm:
1) Create sandbox from the requested rev (default ticket head).
2) Capture env metadata (tool versions, fingerprint, platform).
3) Run commands in declared order. Persist per-command stdout/stderr/meta artifacts.
4) Emit a structured validation_summary.json with bounded excerpts.
5) status=pass only if all non-optional commands pass.

Output: JSON only in first fenced block.

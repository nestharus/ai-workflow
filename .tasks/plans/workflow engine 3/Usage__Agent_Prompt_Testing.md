# Usage — Agent Prompt Testing Commands

- **Doc**: Usage__Agent_Prompt_Testing.md
- **Updated**: 2026-01-29
- **Primary responsibility**: User-facing guidance for validating and testing workflow engine v3 agent prompt files (format v1) using `workflowctl`.
- **Related specs**:
  - Configuration & Onboarding §5–§7 (`Tech_Plan__Configuration_&_Onboarding.md`)
  - Agent prompt format v1 + built-ins (`Tech_Plan__Agent_Prompt_Definitions.md`)
  - Integration §2 CLI contract (`Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md`)
  - Runtime root layout (`Tech_Plan__Core_Infrastructure/01_Runtime_Root_Layout.md`)

## Overview

These commands help prompt authors validate schemas, inspect IO contracts, and test agent prompts in isolation before integrating them into workflows:

- `workflowctl agents validate <path>`
- `workflowctl agents show-io <agent_id> [--format yaml|json]`
- `workflowctl agents test <agent_id> --input <json|@file> [--model <name>]`

All commands:
- print structured JSON to stdout (machine-readable)
- print human-readable errors to stderr (best-effort)
- exit `0` on success and `1` on validation/execution errors

Agent resolution uses the agent precedence rules (Configuration & Onboarding §6.1).

## Validate

Validate agent prompt files (YAML front matter + restricted schema subset) without executing any model calls:

```bash
workflowctl agents validate <path>
```

`<path>` may be:
- a single `*.md` agent file, or
- a directory (recursively validate all `*.md` files).

Output (success example):
```json
{
  "ok": true,
  "validated": [
    { "path": ".workflow/agents/step_patch_author_v1.md", "agent_id": "step_patch_author_v1" }
  ]
}
```

Output (failure example):
```json
{
  "ok": false,
  "errors": [
    {
      "path": ".workflow/agents/step_patch_author_v1.md",
      "agent_id": "step_patch_author_v1",
      "issues": [
        { "field": "input_schema", "path": "properties.context", "message": "Unsupported schema keyword: oneOf" }
      ]
    }
  ]
}
```

## Show IO (`show-io`)

Display an agent’s `input_schema` and `output_schema`:

```bash
workflowctl agents show-io <agent_id> [--format yaml|json]
```

The output includes (when present):
- `agent_id`, `display_name`, `description`
- `input_schema`
- `output_schema`

## Test (`test`)

Execute an agent prompt in isolation with a provided input payload:

```bash
workflowctl agents test <agent_id> --input <json|@file> [--model <name>]
```

Rules:
- `--input` MUST be either an inline JSON object string or `@<file>` containing JSON (UTF-8).
- input MUST validate against the agent’s `input_schema` before execution.
- the agent’s first fenced `json` block is parsed and validated against `output_schema`.

### Test run bundles (stored on disk)

Each test stores an evidence bundle under:

```text
~/.workflow/repos/<repo_uid>/agent_tests/<test_id>/
  prompt.txt        # rendered prompt (redacted)
  output.txt        # raw model output
  tools.jsonl       # tool transcript (redacted; one JSON per line)
  metadata.json     # agent_id, timestamp, model, input hash, validation results
```

## Troubleshooting

- `AGENT_NOT_FOUND`: verify agent precedence paths and the agent ID (Configuration & Onboarding §6.1).
- `INVALID_FRONT_MATTER`: ensure YAML front matter exists and `schema_version: 1`.
- `INPUT_SCHEMA_FAILED`: input JSON does not match `input_schema`; fix required fields/types.
- `OUTPUT_SCHEMA_FAILED`: agent output JSON does not match `output_schema`; fix the prompt’s output contract and/or agent instructions.

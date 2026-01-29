# Tech Plan: Agent Prompt Definitions

- **Doc**: Tech_Plan__Agent_Prompt_Definitions.md
- **Updated**: 2026-01-29
- **Component**: Built-in agent prompts for workflow engine v3
- **Purpose**: Define all built-in agent prompt implementations referenced throughout the workflow engine v3 specification

## 1) Overview

This document provides the index and specification for all built-in agents used by workflow engine v3. These agents are referenced by the built-in workflows defined in `Tech_Plan__Built-in_Workflow_Definitions.md`.

All built-in agents follow the agent prompt format v1 specification defined in `Tech_Plan__Configuration_&_Onboarding.md` §5.

**Agent prompt files location**: `workflows/agents/<agent_id>.md` (relative to this plan directory)

## 2) Agent Registry and Search Paths

Agent prompt files are searched in the following order (highest precedence first):

1. **CLI flag**: `--agent <path>`
2. **Repo-shared**: `<repo>/.workflow/agents/<agent_id>.md`
3. **Repo machine-local**: `~/.workflow/repos/<repo_uid>/agents/<agent_id>.md`
4. **Global personal**: `~/.workflow/agents/<agent_id>.md`
5. **Built-in packaging path**: `agents/builtin/<agent_id>.md` (packaged with `workflowctl`)

This document defines the built-in agents that must be packaged with `workflowctl`.

## 3) Agent Prompt Format v1

All agent prompts use the following format:

### 3.1 YAML Front Matter (Required)

```yaml
---
schema_version: 1
agent_id: <unique_id>
display_name: "Display Name"
description: "One-line description of what the agent does"
capabilities_required: ["capability1", "capability2"]
tools_allowed: ["tool1", "tool2"]  # optional; default []
input_schema:
  type: object
  required: ["field1"]
  properties:
    field1: { type: string }
    field2: { type: [string, "null"] }
output_schema:
  type: object
  required: ["result"]
  properties:
    result: { type: string }
    status: { type: string }
---
```

### 3.2 Markdown Body Requirements

- First fenced code block MUST be JSON output
- Body describes what the agent must do
- Hard constraints (scope limits, formatting rules)
- Output format instructions
- Algorithm/processing steps if applicable

### 3.3 Expanded Agent Inputs

Built-in workflow YAMLs pass only agent IDs. Implementation MUST expand those IDs into the expanded input schema before calling the LLM:

- Load WSS documents (ticket_doc, task_doc, step_spec)
- Load step specs from step_plan.yaml
- Load workflow/config-defined commands (may be filtered by test selection before validation)
- Load any required artifacts

This avoids adding "wss_read" tooling to the gateway and keeps a single auditable tool surface.

### 3.4 Agent prompt testing commands (`workflowctl agents`)

Developers SHOULD validate and test prompts in isolation before integrating them into workflows:

- `workflowctl agents validate <path>`: validate agent prompt files (single file or directory recursion)
- `workflowctl agents show-io <agent_id> [--format yaml|json]`: display `input_schema` and `output_schema`
- `workflowctl agents test <agent_id> --input <json|@file> [--model <name>]`: run the prompt with a provided input payload and validate the output against `output_schema`

Test runs are stored under:
- `~/.workflow/repos/<repo_uid>/agent_tests/<test_id>/`

See: `Usage__Agent_Prompt_Testing.md`.

## 4) Built-in Agent Definitions

The following agents are defined as individual prompt files in `workflows/agents/`:

| Agent ID | File | Description |
|----------|------|-------------|
| task_decomposer_v1 | [task_decomposer_v1.md](workflows/agents/task_decomposer_v1.md) | Turn a task input into a converged, executable step plan |
| step_executor_v1 | [step_executor_v1.md](workflows/agents/step_executor_v1.md) | Execute one step: hydrate/sandbox, author patch, hunk-lint, apply |
| step_patch_author_v1 | [step_patch_author_v1.md](workflows/agents/step_patch_author_v1.md) | Generate a unified diff patch for a single planned step |
| ticket_validator_v1 | [ticket_validator_v1.md](workflows/agents/ticket_validator_v1.md) | Run validation commands in a sandbox and persist results |
| ticket_evaluator_v1 | [ticket_evaluator_v1.md](workflows/agents/ticket_evaluator_v1.md) | Produce evaluation report: planned vs implemented, deviations, gaps |
| rebase_driver_v1 | [rebase_driver_v1.md](workflows/agents/rebase_driver_v1.md) | Perform rebase, detect conflicts, propose resolution options |
| investigator_v1 | [investigator_v1.md](workflows/agents/investigator_v1.md) | Gather evidence for failure/stall and classify next actions |
| ticket_repairer_v1 | [ticket_repairer_v1.md](workflows/agents/ticket_repairer_v1.md) | Attempt safe automated repair via auditable patches |
| approval_agent_v1 | [approval_agent_v1.md](workflows/agents/approval_agent_v1.md) | Summarize decision points and produce user-facing prompts |

## 5) Agent-Workflow Mapping

| Workflow | Step | Agent |
|----------|------|-------|
| task_decompose_v1 | decompose | task_decomposer_v1 |
| step_execute_v1 | execute | step_executor_v1 |
| ticket_validate_v1 | validate | ticket_validator_v1 |
| rebase_enhanced_v1 | rebase | rebase_driver_v1 |
| ticket_evaluate_v1 | evaluate | ticket_evaluator_v1 |
| investigate_v1 | investigate | investigator_v1 |
| ticket_repair_v1 | repair | ticket_repairer_v1 |
| gc_v1 | gc | (tool only) |
| migrate_v1 | migrate | (tool only) |

## 6) Implementation Notes

### 6.1 Agent Invocation Pattern

When a workflow step declares `kind: agent` with `entrypoint: agent:<agent_id>`:

1. Runner resolves the agent ID using the agent registry search paths (§2)
2. Runner loads the agent prompt file content
3. Runner expands the workflow step `with:` bindings into the agent's full input_schema:
   - Load WSS documents (ticket_doc, task_doc, step_spec)
   - Load artifacts referenced by step inputs
   - Apply policy defaults
4. Runner calls the LLM with:
   - System prompt: full agent prompt (YAML front matter + Markdown body)
   - User message: JSON object matching input_schema
5. Runner parses the first ```json``` fence from response
6. Runner validates against output_schema
7. On failure: step follows `on_failure` mode (stop, pause, investigate, continue)

### 6.2 Tool Access Enforcement

Tool access requires ALL of:
1. Workflow step declares `capabilities_required` matching the tool
2. Agent prompt front matter includes the tool in `tools_allowed`
3. Repo trust policy allows the tool (if gating enabled)

If any check fails, the step fails with `E_TOOL_ACCESS_DENIED`.

### 6.3 Capability Mappings

| Agent | net_llm | read_stack | apply_patch | sandbox_exec | control_send |
|-------|---------|------------|-------------|--------------|--------------|
| task_decomposer_v1 | ✓ | - | - | - | - |
| step_executor_v1 | ✓ | ✓ | ✓ | ✓ | ✓ |
| step_patch_author_v1 | ✓ | - | - | - | - |
| ticket_validator_v1 | ✓ | - | - | ✓ | - |
| ticket_evaluator_v1 | ✓ | - | - | ✓ | - |
| rebase_driver_v1 | ✓ | - | ✓ | ✓ | - |
| investigator_v1 | ✓ | - | - | ✓ | - |
| ticket_repairer_v1 | ✓ | - | ✓ | ✓ | - |
| approval_agent_v1 | ✓ | - | - | - | - |

## 7) Distribution

Built-in agents are packaged with `workflowctl` at:
```
workflowctl/
  agents/
    builtin/
      task_decomposer_v1.md
      step_executor_v1.md
      step_patch_author_v1.md
      ticket_validator_v1.md
      ticket_evaluator_v1.md
      rebase_driver_v1.md
      investigator_v1.md
      ticket_repairer_v1.md
      approval_agent_v1.md
```

These files are installed to the system distribution directory by the `workflowctl` package.

During implementation, the agent files from `workflows/agents/` in this plan should be copied to the built-in packaging path.

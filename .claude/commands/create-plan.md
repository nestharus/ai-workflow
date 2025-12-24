---
description: Create implementation design using neuro-symbolic decomposition with layer review
argument-hint: "<ticket-id> or <description of work>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Create Implementation Design

Decompose requirements into a layered design with building block primitives and expected capabilities.

**Capabilities**: Each unit expresses expected capabilities from children (contracts). Each capability gets one test during execution.

**Arguments**: Either a ticket ID or a description to create a new ticket.

Examples:
```bash
/create-plan NES-123                           # Fetch existing ticket
/create-plan "Add user authentication flow"   # Create new ticket
```

## Step 1: Determine Ticket

```bash
# Check if argument matches ticket ID format (XXX-NNN)
if [[ "$ARGUMENTS" =~ ^[A-Z]+-[0-9]+$ ]]; then
    # Fetch existing ticket
    ticket_id="$ARGUMENTS"
    uv run linear get-issue $ticket_id
else
    # Create new ticket from description
    uv run linear list-projects  # Show available projects
    uv run linear create-issue --team Neshq --title "<TITLE>" --description "$ARGUMENTS" --project "<PROJECT>"
    # Capture ticket_id from response
fi
```

**Project selection**:
- "AI Workflow Application Phase N" - app development work
- "Task System" - task/agent system work (default if unclear)
- "Test Framework" - testing infrastructure
- "Documentation" - documentation work
- "GitHub CI" - CI/CD work
- "Knowledge System" - knowledge/fact extraction work

Extract `title`, `description`, and `url` from the ticket.

## Step 2: Initialize State Machine

```bash
uv run planner init $ticket_id --workflow create-plan
```

Returns JSON: `{ "ok": true, "workspace": ".tmp/design/$ticket_id", "ticket_id": "...", "title": "..." }`

## Step 3: Execute State Machine Loop

```bash
while true; do
    action=$(uv run planner next .tmp/design/$ticket_id)
    action_type=$(echo "$action" | jq -r '.action')

    case "$action_type" in
        "complete") break ;;
        "error") echo "Error: $(echo "$action" | jq -r '.message')"; exit 1 ;;

        "call_decomposer")
            # Spawn one decomposer per unit IN PARALLEL
            # target_units is an array like ["root"] or ["root.1", "root.2"]
            history_prompt=$(echo "$action" | jq -r '.prompt // ""')
            target_units=$(echo "$action" | jq -r '.target_units[]')
            for unit_id in $target_units; do
                Task(subagent_type="decomposer", prompt="workspace: .tmp/design/$ticket_id unit: $unit_id $history_prompt")
            done
            # All decomposer tasks run in parallel, wait for all to complete
            ;;

        "call_layer_reviewer")
            history_prompt=$(echo "$action" | jq -r '.prompt // ""')
            Task(subagent_type="layer-reviewer", prompt="workspace: .tmp/design/$ticket_id $history_prompt")
            ;;

        "call_design_refactorer")
            Task(subagent_type="design-refactorer", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "generate_docs")
            Task(subagent_type="diagram-generator", prompt="workspace: .tmp/design/$ticket_id")
            Task(subagent_type="design-formatter", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "post_to_linear")
            uv run linear upsert-comment $ticket_id --title "Architecture Design" --body-file .tmp/design/$ticket_id/architecture.md
            uv run linear upsert-comment $ticket_id --title "Implementation Design" --body-file .tmp/design/$ticket_id/implementation.md
            ;;
    esac

    uv run planner process .tmp/design/$ticket_id
done
```

## Step 4: Output

```bash
uv run planner status .tmp/design/$ticket_id
```

Print:
```
================================================================================
DESIGN CREATION COMPLETE - REVIEW REQUESTED
================================================================================
Ticket: $ticket_id - <TITLE>
Linear: <LINEAR_TICKET_URL>

Decomposition Summary:
  Layers: <N>
  Total units: <count>
  Atomic units: <count>

Capabilities:
  Expected: <count> (contracts from parent units)
  Provided: <count> (fulfilled by child units)
  Types: output, behavior, integration, data, guarantee

Plan Types:
  CREATE: <count> (new code)
  PATCH: <count> (same pattern, modify existing)
  REGENERATE: <count> (pattern change, rewrite)
  DELETE: <count> (remove code)

Pattern Distribution:
  Stream (Walker, Visitor, Filter, Collector, Splitter, Zip): <count>
  Data Access (Extractor, Mutator, Getter, Setter): <count>
  Data Model (Entity, Projection): <count>
  Construction (Builder, Mapper, Reducer): <count>
  Control Flow (Guard, Router, Classifier, Orchestrator): <count>
  Validation (Validator): <count>

================================================================================
LINEAR COMMENTS CREATED
================================================================================

The following comments were posted to the Linear ticket. Each serves a specific
purpose for different audiences:

1. "Architecture Design"
   - PURPOSE: Human-readable overview with Mermaid diagrams
   - AUDIENCE: Humans reviewing the high-level structure
   - CONTAINS: Component diagrams, layer breakdown, pattern locations
   - REVIEW FOR: Logical organization, missing components, unclear boundaries
   - FETCH: uv run linear get-comment $ticket_id --title "Architecture Design"

2. "Implementation Design"
   - PURPOSE: Machine-readable unit tree with detailed plans
   - AUDIENCE: AI agents executing the design, technical reviewers
   - CONTAINS: Full unit hierarchy, pattern assignments, patch/regenerate plans
   - REVIEW FOR: Correct pattern selection, complete coverage, valid plans
   - FETCH: uv run linear get-comment $ticket_id --title "Implementation Design"

================================================================================
REVIEW INSTRUCTIONS
================================================================================

Fetch and review both comments:
  uv run linear get-comment $ticket_id --title "Architecture Design"
  uv run linear get-comment $ticket_id --title "Implementation Design"

VERIFY:
1. Every requirement from the ticket is covered by a unit
2. Pattern assignments match operation semantics:
   - Walker/Visitor for iteration
   - Extractor/Mutator for data access
   - Builder/Mapper for construction
   - Guard/Router for control flow
   - Validator for validation
3. Plan types are appropriate:
   - PATCH: Same pattern, small changes
   - REGENERATE: Pattern changes fundamentally
   - CREATE: New code from scratch
4. Layer structure makes sense (atomics at bottom, compositions above)
5. Capabilities form valid contracts:
   - Each expected capability has a provider_unit_id
   - Provided capabilities match what children actually do
   - No dangling capabilities (expected but not provided)
   - Capability types match operation semantics

YOU ARE REVIEWING THE DESIGN FOR HOW TO BUILD THE CODE.
NOT reviewing actual code - that comes after /execute-plan.

Next: /execute-plan $ticket_id
State: .tmp/design/$ticket_id/
================================================================================
```

## Notes

- State machine handles all decomposition logic internally
- Orchestrator only passes workspace path to agents
- Agents read from `agent_input.yaml`, write to `agent_output.yaml`
- State persisted in `state.yaml` for resumability
- **Capabilities**: Contracts between units; one test per capability
- For updating existing designs, use `/update-plan`
- For refactoring existing code structure, use `/create-refactor-plan`

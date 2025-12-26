---
description: Analyze existing code and document architecture without refactoring
argument-hint: "<paths...> [--ticket <ticket-id>]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Analyze Existing Code

Discover and document existing architecture using iterative top-down discovery.

**Use Cases**:
- Understand a codebase before making changes
- Identify component boundaries and integrations
- Capture pattern inventory and risks without planning refactors

## Step 1: Parse Arguments and Initialize

Parse `$ARGUMENTS` for paths and optional `--ticket` flag:

```
# Pseudocode - Claude interprets $ARGUMENTS
ARGUMENTS = "<paths...> [--ticket <ticket-id>]"

if "--ticket" not in ARGUMENTS:
    # Create new ticket with paths in title
    ticket_id = uv run linear create-issue --team Neshq --title "Analyze: {paths}" --description "..."
else:
    # Extract ticket ID from --ticket flag
    ticket_id = extract_ticket_id(ARGUMENTS)

# Initialize the analyze workflow
uv run planner init $ticket_id --workflow analyze --paths "{paths}"
```

Returns JSON: `{ "ok": true, "workspace": ".tmp/design/$ticket_id", "paths": [...] }`

## Step 2: Execute State Machine Loop

```bash
while true; do
    action=$(uv run planner next .tmp/design/$ticket_id)
    action_type=$(echo "$action" | jq -r '.action')

    case "$action_type" in
        "complete") break ;;
        "error") echo "Error: $(echo "$action" | jq -r '.message')"; exit 1 ;;

        "call_skeleton_analyzer")
            # Analyze folder structure, entry points, component boundaries
            Task(subagent_type="skeleton-analyzer", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "call_component_analyzer")
            # Analyze each component: capabilities, patterns, dependencies
            Task(subagent_type="component-analyzer", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "call_integration_mapper")
            # Map imports, dependencies, circular refs
            Task(subagent_type="integration-mapper", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "generate_docs")
            # diagram-generator reads: .tmp/design/$ticket_id/agent_input.yaml
            # diagram-generator writes: .tmp/design/$ticket_id/diagrams.yaml
            # See .claude/agents/diagram-generator.md for contract details
            Task(subagent_type="diagram-generator", prompt="workspace: .tmp/design/$ticket_id")
            # design-formatter reads: .tmp/design/$ticket_id/agent_input.yaml, diagrams.yaml
            # design-formatter writes: .tmp/design/$ticket_id/architecture.md, implementation.md
            # See .claude/agents/design-formatter.md for contract details
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

## Step 3: Output

```bash
uv run planner status .tmp/design/$ticket_id
```

Print:
```
================================================================================
ANALYSIS COMPLETE - REVIEW REQUESTED
================================================================================
Ticket: $ticket_id - Analyze: <paths>
Linear: <LINEAR_TICKET_URL>

Discovery Summary:
  Layers analyzed: <N>
  Components discovered: <count>
  Files analyzed: <count>
  Integration points: <count>

Analysis Findings:
  Pattern inventory entries: <count>
  Problem areas identified: <count>

================================================================================
LINEAR COMMENTS CREATED
================================================================================

Two comments were posted to the Linear ticket, each serving a distinct purpose:

1. "Architecture Design"
   - PURPOSE: Document what exists NOW
   - AUDIENCE: Anyone needing to understand current state
   - CONTAINS:
     * Folder structure analysis
     * Component boundaries (as discovered)
     * Integration map (who imports who)
     * Pattern inventory (what patterns are currently used)
     * Problem areas (circular deps, dead code, mismatches)
   - FETCH: uv run linear get-comment $ticket_id --title "Architecture Design"

2. "Implementation Design"
   - PURPOSE: Document concrete implementation details
   - AUDIENCE: Developers navigating the code
   - CONTAINS:
     * Component responsibilities
     * Entry points and internal flows
     * Capability and integration summaries
   - FETCH: uv run linear get-comment $ticket_id --title "Implementation Design"

================================================================================
REVIEW INSTRUCTIONS
================================================================================

Fetch both comments:
  uv run linear get-comment $ticket_id --title "Architecture Design"
  uv run linear get-comment $ticket_id --title "Implementation Design"

VERIFY ARCHITECTURE:
1. All existing code is accounted for (no orphans missed)
2. Integration map is complete (all imports captured)
3. Problem areas are correctly identified

VERIFY IMPLEMENTATION DETAILS:
1. Entry points and internal flows are accurate
2. Pattern inventory matches actual usage
3. Capabilities align with component responsibilities

State: .tmp/design/$ticket_id/
================================================================================
```

---
description: Create refactoring design from existing code using iterative top-down discovery
argument-hint: "<paths...> [--ticket <ticket-id>]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Create Refactoring Design

Analyze existing code and create a restructuring design using iterative top-down discovery.

**Difference from `/create-plan`**:
- `/create-plan`: Decomposes requirements into new code design
- `/create-refactor-plan`: Discovers existing code structure, plans restructuring

**Use Cases**:
- Restructure messy codebase into clean components
- Migrate between architectures
- Extract reusable libraries
- Consolidate duplicated functionality

## Step 1: Parse Arguments and Initialize

```bash
# If no ticket provided, create one
if [[ "$ARGUMENTS" != *"--ticket"* ]]; then
    ticket_id=$(uv run linear create-issue --team Neshq --title "Refactor: <paths>" --description "..." | jq -r '.id')
else
    ticket_id=<extracted from args>
fi

uv run planner init $ticket_id --workflow refactor-plan --paths "<paths>"
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

        "call_refactor_planner")
            # Plan moves, renames, splits, merges
            Task(subagent_type="refactor-planner", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "call_layer_reviewer")
            Task(subagent_type="layer-reviewer", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "generate_docs")
            Task(subagent_type="diagram-generator", prompt="workspace: .tmp/design/$ticket_id")
            Task(subagent_type="design-formatter", prompt="workspace: .tmp/design/$ticket_id")
            ;;

        "post_to_linear")
            uv run linear upsert-comment $ticket_id --title "Current Architecture" --body-file .tmp/design/$ticket_id/current_architecture.md
            uv run linear upsert-comment $ticket_id --title "Target Architecture" --body-file .tmp/design/$ticket_id/target_architecture.md
            uv run linear upsert-comment $ticket_id --title "Refactoring Design" --body-file .tmp/design/$ticket_id/refactoring_design.md
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
REFACTORING DESIGN COMPLETE - REVIEW REQUESTED
================================================================================
Ticket: $ticket_id - Refactor: <paths>
Linear: <LINEAR_TICKET_URL>

Discovery Summary:
  Layers analyzed: <N>
  Components discovered: <count>
  Files analyzed: <count>
  Integration points: <count>

Current State Analysis:
  Top-level folders: <count>
  Pattern mismatches: <count>
  Circular dependencies: <count>
  Dead code identified: <count>

Refactoring Plan:
  MOVE: <count> (relocate without change)
  RESTRUCTURE: <count> (change internal organization)
  MERGE: <count> (combine components)
  SPLIT: <count> (separate components)
  EXTRACT: <count> (pull out reusable parts)
  DELETE: <count> (remove dead code)

Pattern Migrations:
  <current_pattern> → <target_pattern>: <count> units

================================================================================
LINEAR COMMENTS CREATED
================================================================================

Three comments were posted to the Linear ticket, each serving a distinct purpose:

1. "Current Architecture"
   - PURPOSE: Document what exists NOW before refactoring
   - AUDIENCE: Anyone needing to understand current state
   - CONTAINS:
     * Folder structure analysis
     * Component boundaries (as discovered)
     * Integration map (who imports who)
     * Pattern inventory (what patterns are currently used)
     * Problem areas (circular deps, dead code, mismatches)
   - FETCH: uv run linear get-comment $ticket_id --title "Current Architecture"

2. "Target Architecture"
   - PURPOSE: Document what we're building TOWARD
   - AUDIENCE: Architects, reviewers validating direction
   - CONTAINS:
     * Proposed folder structure
     * Clean component boundaries
     * Proper pattern assignments
     * Integration simplification
   - FETCH: uv run linear get-comment $ticket_id --title "Target Architecture"

3. "Refactoring Design"
   - PURPOSE: HOW to get from current to target (the actual plan)
   - AUDIENCE: AI agents executing, developers implementing
   - CONTAINS:
     * Unit tree with refactoring operations
     * Move/rename/split/merge instructions
     * Migration order (what depends on what)
     * Breaking change warnings
   - FETCH: uv run linear get-comment $ticket_id --title "Refactoring Design"

================================================================================
REVIEW INSTRUCTIONS
================================================================================

Fetch all three comments:
  uv run linear get-comment $ticket_id --title "Current Architecture"
  uv run linear get-comment $ticket_id --title "Target Architecture"
  uv run linear get-comment $ticket_id --title "Refactoring Design"

VERIFY CURRENT ARCHITECTURE:
1. All existing code is accounted for (no orphans missed)
2. Integration map is complete (all imports captured)
3. Problem areas are correctly identified

VERIFY TARGET ARCHITECTURE:
1. Addresses identified problems
2. Pattern assignments match operation semantics
3. Component boundaries make sense
4. No over-engineering (don't fix what isn't broken)

VERIFY REFACTORING DESIGN:
1. Migration can be done incrementally (or justify big-bang)
2. Breaking changes are identified and planned for
3. Dependencies are refactored in correct order
4. External consumers are considered

DISCOVERY VERIFICATION:
- Iterative discovery may have found files not in original paths
- Verify all discovered files are relevant
- Check that discovery didn't miss obvious connections

YOU ARE REVIEWING THE REFACTORING DESIGN.
Current → Target → How to get there.

Next: /execute-plan $ticket_id
State: .tmp/design/$ticket_id/
================================================================================
```

## Iterative Discovery Model

Unlike `/create-plan` which decomposes requirements top-down, refactoring DISCOVERS existing code:

```
Layer 0: Skeleton Analysis
  - Identify folder structure from input paths
  - Find entry points (main.py, __init__ exports, CLI)
  - Map top-level imports between folders
  - Create initial component units

Layer 1: Component Analysis (for each Layer 0 unit)
  - Analyze internal structure
  - Discover sub-modules
  - Identify patterns currently used
  - Discover CONNECTED FILES not in original paths  ← key difference

Layer 2+: Continue drilling down
  - Each layer may discover MORE files
  - Design grows as analysis reveals structure
  - Stop when atomics reached
```

**Key**: Each layer discovers NEW files. The design expands as we understand the actual code.

## Notes

- Discovery-first, then planning
- Each layer may add files to the design
- Integration mapping critical for safe refactoring
- Consider incremental vs big-bang migration

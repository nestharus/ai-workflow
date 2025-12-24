---
name: design-refactorer
description: Executes restructuring actions on the design tree (merge, split, move, remove, recompose)
model: opus
tools: Read, Write, Grep, Glob
---

# Design Refactorer Agent

Execute restructuring actions on the design tree. Called for refactoring actions identified by the layer-reviewer.

**Key**: This agent reads actions from the workspace and writes changes to `agent_output.yaml`.

## Workflow

1. Extract workspace path from prompt (e.g., "workspace: .tmp/design/NES-126")
2. Read `{workspace}/agent_input.yaml` for actions to execute
3. Read `{workspace}/state.yaml` for current design state
4. Execute all actions
5. Write results to `{workspace}/agent_output.yaml`

## Input Format

Read from `{workspace}/agent_input.yaml`:

```yaml
actions:
  - action: <merge|split|move|remove|add|recompose>
    target_units: [<unit IDs>]
    description: <what to do>
    new_structure: <proposed structure if applicable>
```

## Action Types

### MERGE
Combine multiple units into one.

### SPLIT
Break one unit into multiple.

### MOVE
Relocate unit to different parent.

### REMOVE
Delete unit from design.

### ADD
Insert new structural unit.

### RECOMPOSE
Change relationships between units without moving.

## Output Format

Write to `{workspace}/agent_output.yaml`:

```yaml
agent: design-refactorer
status: <success|failure>
changes:
  - type: <update|add|remove>
    unit_id: <affected unit ID>
    # For update:
    description: <new description if changed>
    pattern: <new pattern if changed>
    plan: <new plan if changed>
    # For add:
    unit:
      id: <new unit ID>
      description: <description>
      operation: <CREATE|MODIFY|DELETE>
      status: <pending|atomic|decomposed>
      pattern: <if atomic>
      children: [<if decomposed>]
    parent_id: <parent unit ID>
    # For remove:
    # (just unit_id is needed)

error: <error message if failure>
```

## Rules

1. Execute all actions provided in input
2. Preserve unit metadata during restructuring
3. Update all affected parent-child relationships
4. For splits: new units start as `pending` for further decomposition
5. For merges: determine if merged unit is atomic or needs decomposition
6. Maintain ID consistency (IDs reflect tree position)

## Critical Requirements

1. **MUST** write output to `{workspace}/agent_output.yaml`
2. **MUST** include `agent: design-refactorer` at the top
3. **MUST** include `status: success` or `status: failure`

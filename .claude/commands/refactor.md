---
description: Neuro-symbolic refactoring using layered decomposition and bottom-up implementation
argument-hint: "<path-to-refactor> [--research-hints 'domain hints']"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Neuro-Symbolic Refactor Command

Refactor code using dynamic layered decomposition with building block primitives.

## Algorithm Overview

**Phase 1: Iterative Decomposition**
- Start with high-level refactoring goal
- Recursively decompose into smaller units
- Skeleton evolves as deeper layers reveal structure
- Continue until all leaves are atomic (building block primitives)

**Phase 2: Bottom-Up Implementation**
- Implement all atomic leaves
- Compose upward, substituting children into parents
- Continue until reaching root

## Step 1: Initialize Refactor Session

Parse `$ARGUMENTS` to extract:
- `target_path`: Path to code being refactored
- `research_hints`: Optional domain hints (e.g., "git operations", "API gateway")

```bash
mkdir -p .tmp/refactor
REFACTOR_ID=$(date +%Y%m%d_%H%M%S)
mkdir -p .tmp/refactor/$REFACTOR_ID
```

Create initial state file `.tmp/refactor/$REFACTOR_ID/state.yaml`:
```yaml
root:
  id: root
  description: <parsed from user's refactoring request>
  status: pending  # pending | decomposing | atomic | composed

units: {}  # Will be populated during decomposition
```

## Step 2: Analyze Target Code

Before decomposition, understand what exists:

```bash
# Get file structure
find <target_path> -type f -name "*.py" | head -50
```

Read key files to understand current structure. Document findings in `.tmp/refactor/$REFACTOR_ID/analysis.md`.

## Step 3: Iterative Decomposition Loop

**The decomposition is iterative, not strictly hierarchical.** As we go deeper, we may restructure earlier layers.

```
while units with status != 'atomic' and status != 'composed' exist:

  1. Select next unit to decompose (prefer breadth-first, but context may dictate otherwise)

  2. Run decomposer agent:
     Task(subagent_type="decomposer", model="opus", prompt="
     unit:
       id: <unit.id>
       description: <unit.description>
       context: <parent context + sibling context>

     codebase_path: <target_path>
     research_hints: <research_hints if provided>
     ")

  3. Parse decomposer output (YAML):

     If is_atomic: true
       - Update unit status to 'atomic'
       - Store pattern and specification

     If is_atomic: false
       - Check if decomposition suggests restructuring parent layers
       - If restructuring needed:
         - Update affected parent units
         - Re-queue them for re-decomposition if necessary
       - Add sub_units to units map with status 'pending'
       - Update current unit's children list

  4. Update state file after each iteration
```

**Restructuring Detection:**
When decomposer returns a decomposition that implies the parent structure should change (e.g., "this should actually be a separate service, not part of the parent"), propagate that change upward before continuing.

## Step 4: Verify All Leaves Are Atomic

```bash
# Check state.yaml - all units should be either 'atomic' or have children
```

List of atomic units with their patterns:
```yaml
atomic_units:
  - id: root.services.git.extract_branch
    pattern: Extractor
    specification: {...}
  - id: root.services.git.validate_repo
    pattern: Validator
    specification: {...}
```

## Step 5: Bottom-Up Implementation

Process in reverse depth order (leaves first):

```
# Sort units by depth (deepest first)
for unit in sorted_by_depth_desc(units):

  if unit.status == 'atomic':
    # Implement using atomic-implementor (Haiku)
    Task(subagent_type="atomic-implementor", model="haiku", prompt="
    pattern: <unit.pattern>
    specification: <unit.specification>

    target_path: <computed path based on unit.id>
    language: python
    conventions_path: docs/development/
    ")

    - Parse output
    - Store file_path and exports in unit
    - Update status to 'composed'

  else:  # Unit has children
    # Compose using composer (Haiku)
    Task(subagent_type="composer", model="haiku", prompt="
    parent:
      id: <unit.id>
      description: <unit.description>
      pattern_used: <unit.pattern_used if any>

    children:
      - id: <child.id>
        file_path: <child.file_path>
        exports: <child.exports>
      ...

    target_path: <computed path>
    language: python
    conventions_path: docs/development/
    ")

    - Parse output
    - Store file_path and exports in unit
    - Update status to 'composed'
```

## Step 6: Finalize

After root is composed:

1. Run lint-fixer on changed files:
   ```
   Task(subagent_type="lint-fixer", prompt="--changed-only")
   ```

2. Run tests if applicable

3. Output summary:
   ```
   ================================================================================
   REFACTOR COMPLETE
   ================================================================================
   Target: <target_path>
   Units decomposed: <count>
   Atomic patterns used: <list>
   Files created/modified: <list>

   Decomposition tree saved: .tmp/refactor/$REFACTOR_ID/
   ================================================================================
   ```

## State File Format

`.tmp/refactor/$REFACTOR_ID/state.yaml`:
```yaml
root:
  id: root
  description: "Refactor sandbox server into clean architecture"
  status: composed
  children: [root.api, root.services, root.client]
  file_path: scripts/servers/sandbox/__init__.py
  exports: [SandboxServer]

units:
  root.api:
    id: root.api
    description: "API layer with contracts and endpoints"
    status: composed
    pattern_used: "Service Layer"
    children: [root.api.contracts, root.api.endpoints]
    file_path: scripts/servers/sandbox/api/__init__.py

  root.services.git.extract_branch:
    id: root.services.git.extract_branch
    description: "Extract current branch from git repo"
    status: composed  # Was atomic, now implemented
    pattern: Extractor
    specification:
      purpose: "Get current git branch name"
      inputs: "repo_path: str"
      outputs: "branch_name: str"
    file_path: scripts/servers/sandbox/services/git/extractors.py
    exports: [extract_current_branch]
```

## Error Handling

- If decomposer fails: retry once, then pause for human review
- If atomic-implementor fails: log error, mark unit as 'failed', continue with others
- If composer fails: ensure all children are implemented, retry
- Save state after each step for resumability
- Keep `.tmp/refactor/$REFACTOR_ID/` for debugging

## Resuming

To resume an interrupted refactor:
```
/refactor --resume .tmp/refactor/<REFACTOR_ID>
```

Load state.yaml and continue from where decomposition/implementation left off.

## Notes

- Decomposition discovers layers dynamically - could be 2 or 10 layers deep
- The skeleton evolves as we learn more from deeper decomposition
- Opus handles all planning/decomposition (understanding shapes)
- Haiku handles all code generation (filling in specifics)
- Building block primitives from `.ai/docs/code-patterns.md` are the atomic units

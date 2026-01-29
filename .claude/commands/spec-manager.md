---
description: Manage specification libraries with multi-agent workflow
argument-hint: "<spec_folder> [--phase staging|planning|merging|verification|analysis|all]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Spec Manager

Orchestrate specification library management using a multi-phase workflow.

**Capabilities:**
- Stage: Validate and legalize incoming content (annotations, formats)
- Plan: Decompose changes into safe batches
- Merge: Apply batches to library files
- Verify: Confirm no drift or duplication
- Analyze: Detect divergence/convergence patterns for library restructuring

**Arguments:**
- `spec_folder`: Path to the specification folder (required)
- `--phase`: Run specific phase (default: all)

## Step 1: Parse Arguments

Extract from `$ARGUMENTS`:
- `spec_folder`: The first positional argument (path to spec folder)
- `phase`: If `--phase <name>` is provided, extract the phase name

## Step 2: Invoke Orchestrator Agent

Execute the spec-manager-orchestrator agent with the parsed arguments:

```bash
uv run agents spec-manager-orchestrator "Manage spec folder: $spec_folder. Phase: ${phase:-all}"
```

The orchestrator will:
1. Initialize the workspace
2. Route each phase to the appropriate sub-agent
3. Handle errors and spawn QA agents if needed
4. Generate the final report

## Alternative: Direct CLI Usage

For advanced users, the CLI can be invoked directly:

```bash
# Run from the spec_manager package directory
cd scripts/spec_manager

# Initialize workspace
uv run spec-manager init <spec_folder>

# Run specific phases
uv run spec-manager stage <spec_folder> --normalize
uv run spec-manager plan <spec_folder>
uv run spec-manager merge <spec_folder> --apply
uv run spec-manager verify <spec_folder>
uv run spec-manager analyze <spec_folder> --json

# Run all phases
uv run spec-manager run <spec_folder> --apply

# Check status
uv run spec-manager status <spec_folder>
```

## Phase Details

### Staging Phase
Validates:
- Annotation formats (([=ID]), (@[+ID]), (@[=ID]))
- ID patterns (Algorithm #, G#, P#I#, etc.)
- Duplicate declarations
- Missing declarations on headers
- Unannotated references

### Planning Phase
- Compares IDs between plan.md, libs.md, and library files
- Detects sequence gaps and duplicates
- Identifies conflicts (IDs in multiple libraries)
- Creates batches for merging

### Merging Phase
- Extracts new sections from plan.md to libraries
- Moves misplaced sections to correct library
- Removes duplicate sections
- Sorts library sections by ID

### Verification Phase
- Checks content matches between plan.md and libraries
- Ensures no duplicate IDs across libraries
- Verifies all IDs in correct primary library

### Analysis Phase
Detects:
- **Divergence**: Libraries that should be split
- **Convergence**: Libraries that should be merged
- **Reference patterns**: Cross-library dependencies

## Agent Architecture

The spec-manager uses multiple specialized agents:

| Agent | Model | Purpose |
|-------|-------|---------|
| spec-manager-orchestrator | glm-flash | Coordinates phases, handles routing |
| spec-manager-staging | smollm2-360/glm-flash | Fast validation |
| spec-manager-planning | glm-flash/glm | Batch decomposition |
| spec-manager-merging | smollm2-360/glm-flash | Section extraction |
| spec-manager-verification | smollm2-360/glm-flash | Consistency checks |
| spec-manager-analysis | glm/claude-opus | Complex pattern detection |
| spec-manager-qa | claude-opus | Troubleshooting |

## Example Usage

```bash
# Full workflow with agent orchestration
/spec-manager .tasks/plans/my-spec

# Just validate
/spec-manager .tasks/plans/my-spec --phase staging

# Run analysis only
/spec-manager .tasks/plans/my-spec --phase analysis
```

## Output

```
================================================================================
SPEC MANAGER - PROCESSING COMPLETE
================================================================================
Spec Folder: .tasks/plans/my-spec

Phase Results:
  ✅ Staging: 5 warnings, 0 errors
  ✅ Planning: 3 batches created
  ✅ Merging: 12 sections extracted, 2 moved
  ✅ Verification: All checks passed

Analysis Suggestions:
  [split] Consider splitting 'field' library (15 algorithms could form 'field_ops')
  [merge] Consider merging 'graph' and 'storage' (8 shared references)

Report: .tasks/plans/my-spec/.workspace/reports/summary.md
================================================================================
```

---
description: Execute recomposed specs into code by iterating until only gaps remain
allowed-tools: Read, Write, Bash, Task, Glob, Grep
---

# Execute Spec

Turn a recomposed spec (facts + entities + relations) into implementation work.

## Core Ideas

- We do **not** assume we can detect dependencies up-front.
- We implement until we hit an **unmet need**, then we record a **gap**.
- We keep iterating until the remaining work is only gaps (spec underspecified).
- We track what we implemented by **Spec IDs** (E-..., R-..., C-..., O-..., F-...).
- Each ID is protected by a **hash** so edits to specs are detectable.

## Alias Resolution

Aliases are resolved during implementation, not decomposition. When an implementor discovers that an existing system already fulfills a role, they record the alias link in the execution ledger.

## Dependency Resolution

Dependencies are not reliably detectable up-front. Implementation uses an iterative approach:

1. Implement what you can from the current spec
2. When blocked, record the missing need as a gap (with the IDs you were working on)
3. Investigate specs to find what provides that need
4. Implement those dependencies next
5. Resume original implementation

This is a list-based approach (not a stack) since things may rely on each other cyclically.

## Inputs

- `--workspace`: The workspace used for decomposition (contains recomposed output)
- `--repo`: The implementation repo root (optional; default: current directory)

## Usage

### Initialize / Run

```bash
uv run python -m scripts.spec_decomposition execute-spec \
  --workspace .tmp/spec_decomposition \
  --repo .
```

This command:

1. Computes current ID hashes from the recomposed spec
2. Loads/updates a ledger at `workspace/execution/ledger.json`
3. Selects the next runnable unit(s) based on status
4. Emits prompt files for agents:
   - `workspace/execution/prompts/plan_*.md`
   - `workspace/execution/prompts/implement_*.md`
   - `workspace/execution/prompts/review_*.md`

### Agent Execution

Execute the generated prompt files via the agent runner:

```bash
# Planning (uses Opus for understanding patterns)
uv run agents spec-planner --file workspace/execution/prompts/plan_001.md

# Implementation (uses Minimax for grunt work)
uv run agents spec-implementor --file workspace/execution/prompts/implement_001.md

# Review (uses GPT-5.2-high for verification)
uv run agents spec-reviewer --file workspace/execution/prompts/review_001.md
```

### Record Results

The implementor writes an evidence map linking implementation files to spec IDs:

```
workspace/execution/evidence/<run_id>/implementation_map.json
```

Format:

```json
{
  "run_id": "run_001",
  "timestamp": "2026-01-25T12:00:00Z",
  "implementations": [
    {
      "spec_id": "E-001",
      "status": "complete",
      "files": ["src/auth/service.py", "src/auth/models.py"],
      "notes": "Implemented AuthService with all methods"
    },
    {
      "spec_id": "E-002",
      "status": "partial",
      "files": ["src/user/store.py"],
      "needs": ["Database connection pool"],
      "notes": "UserStore implemented but needs DB pool from infrastructure"
    }
  ],
  "gaps": [
    {
      "description": "Database connection pool",
      "blocking": ["E-002"],
      "investigated": false
    }
  ]
}
```

Then re-run execute-spec to ingest results and continue:

```bash
uv run python -m scripts.spec_decomposition execute-spec \
  --workspace .tmp/spec_decomposition \
  --ingest workspace/execution/evidence/run_001/implementation_map.json
```

## Ledger Structure

The ledger (`workspace/execution/ledger.json`) tracks:

```json
{
  "version": 1,
  "spec_hashes": {
    "E-001": "sha256:abc123...",
    "E-002": "sha256:def456..."
  },
  "statuses": {
    "E-001": {
      "status": "complete",
      "run_id": "run_001",
      "files": ["src/auth/service.py"]
    },
    "E-002": {
      "status": "partial",
      "run_id": "run_001",
      "files": ["src/user/store.py"],
      "needs": ["Database connection pool"]
    }
  },
  "gaps": [
    {
      "id": "gap_001",
      "description": "Database connection pool",
      "blocking": ["E-002"],
      "resolved_by": null
    }
  ],
  "alias_links": {
    "UserStore": "UserRepository"
  }
}
```

## Detecting Spec Edits

When execute-spec runs, it computes fresh hashes for all spec IDs. If a hash differs from the ledger:

- **New ID**: Added to ledger with status "pending"
- **Modified ID**: Marked for re-review, status becomes "modified"
- **Deleted ID**: Marked as "orphaned" (implementation may need cleanup)

## Output

- `workspace/execution/ledger.json` - Implementation state
- `workspace/execution/gaps.json` - Current gaps blocking progress
- `workspace/execution/prompts/` - Generated prompt files for agents
- `workspace/execution/evidence/` - Implementation evidence from runs

## Workflow Summary

```
1. decompose-spec creates entity/relation/fact artifacts
2. tag-facts assigns stable F-IDs to source lines
3. recompose creates implementable spec bundle
4. execute-spec iterates:
   a. Pick next runnable IDs
   b. Generate prompts for plan/implement/review
   c. Agent writes implementation + evidence map
   d. Ingest evidence, update ledger
   e. Surface gaps if blocked
   f. Repeat until only gaps remain
5. User refines spec to fill gaps
6. Continue execution
```

---
description: Implements spec IDs and produces evidence map
model: cerebras
---

Implement the given spec IDs and track what files are created/modified.

## Input

- `workspace`: Path to decomposition workspace
- `repo`: Path to implementation repository
- `target_ids`: List of spec IDs to implement
- `run_id`: Unique identifier for this implementation run
- `output_file`: Where to write the evidence map

## Task

For each target ID:

1. Read the spec content from workspace
2. Implement the required functionality in the repo
3. Track all files created or modified
4. If blocked by a missing dependency, record the gap

Rules (critical):

- **Implement faithfully.** Follow the spec exactly as written.
- **Track everything.** Every file touched must be recorded in the evidence map.
- **Record blockers immediately.** If you cannot proceed due to a missing need, record it as a gap and move to the next ID.
- **No assumptions.** If the spec is unclear, record a gap rather than guessing.

## Output File Format

Write JSON to the output_file:

```json
{
  "run_id": "run_001",
  "timestamp": "2026-01-25T12:00:00Z",
  "implementations": [
    {
      "spec_id": "E-001",
      "status": "complete",
      "files": ["src/auth/service.py", "src/auth/models.py"],
      "notes": "Implemented all methods specified"
    },
    {
      "spec_id": "E-002",
      "status": "partial",
      "files": ["src/user/store.py"],
      "needs": ["Database connection pool"],
      "notes": "Core implementation done but needs DB pool from infrastructure"
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

Status values:
- `complete`: All spec requirements implemented
- `partial`: Some requirements implemented but blocked by a gap

## Response

Return only the output filename.

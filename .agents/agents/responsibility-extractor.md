---
description: Extracts responsibility from a statement
model: glm
---

You identify what responsibility a statement describes.

## Definition

A **responsibility** is what something DOES in a flow. Examples:
- "durable logging" - persisting log events
- "conflict resolution" - handling merge conflicts
- "step orchestration" - managing step execution

## Input

A statement like: "Logs use sharded JSONL files"

## Output

```json
{
  "statement": "Logs use sharded JSONL files",
  "responsibility": "durable logging",
  "labels": ["logs", "JSONL"],
  "flow_context": "logging subsystem"
}
```

## Rules

- Focus on WHAT it does, not HOW
- Responsibilities are abstract (not implementation-specific)
- A statement may touch multiple responsibilities - list primary one
- Always output valid JSON
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]


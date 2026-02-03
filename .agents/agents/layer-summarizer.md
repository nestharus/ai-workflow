---
description: Updates layer summaries when components change
model: glm
---

You update collapsed layer summaries when underlying components change.

## Purpose

Each layer has a summary file that enables fast routing. When components in that layer change, the summary must be updated.

## Input

1. A component that changed
2. The layer it belongs to
3. Current layer summary

## Algorithm

1. Re-read all components in the layer
2. Extract each component's **responsibility** (not implementation details)
3. Generate new summary with:
   - Component name
   - Primary responsibility
   - Key labels it owns

## Summary Format

```markdown
# [Layer Name] Summary

## Components

### ComponentA
- Responsibility: durable logging
- Labels: logs, JSONL, shards

### ComponentB
- Responsibility: step orchestration
- Labels: steps, execution, root
```

## Rules

- Summaries describe INTENT, not implementation
- Keep summaries concise for fast routing
- Labels enable grep-based discovery
- Update parent layer summary too (bubble up)
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]


---
description: Finds split points within a content segment
routing:
  - model: cerebras
---

You find line numbers where content should be split into sub-sections.

## Input

A markdown file containing mixed content (questions, answers, conclusions).

## Algorithm

1. Read the content line by line
2. Identify natural break points:
   - New question headers (lines starting with topic/question text)
   - Numbered list restarts (1. after previous list ended)
   - Section dividers (blank lines followed by new topic)
3. Return line numbers where splits should occur

## Output

```json
{
  "file": "1.md",
  "split_lines": [15, 42, 78],
  "segment_count": 4
}
```

## Rules

- Each segment should be self-contained
- Don't split in the middle of a question or answer
- Minimum segment size: 3 lines
- Always output valid JSON

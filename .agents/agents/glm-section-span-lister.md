---
description: Extracts section spans from spec files with stable section IDs. Evidence pointers will migrate to [spec_snapshot/<relpath>::SEC-...].
model: glm
output_format: json
---

## OUTPUT CONTRACT (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"file_id": "string", "sections": [{"section_id": "string", "start_line": int, "end_line": int, "label": "string"}]}
- Use the file_id exactly as provided in INPUT DATA. Do NOT invent or modify it.
- Section IDs MUST follow format `SEC-{file_id}-{ordinal:04d}` where ordinal starts at 1 and increments by 1.
- Sections MUST cover every line exactly once (no gaps, no overlaps).
- Sections MUST be ordered sequentially by line number.
- start_line and end_line are 1-indexed, inclusive.
- Labels MUST be topic-only routing aids (e.g., "Introduction", "Requirements", "Constraints").
- Outputs MUST validate against FileSections schema (scripts/spec_manager/spec_manager/schemas/sections.py).
- NOTE: Section IDs are used for evidence pointers; use [spec_snapshot/<relpath>::SEC-F####-####]
  (preferred) or [F####::SECTION] (legacy accepted).

FORBIDDEN:
- Overlapping spans.
- Gaps in coverage.
- Non-sequential ordering.
- Invented file_id.
- Any output outside the JSON object.

## INPUT DATA

- File ID: {file_id}
- File path: {relpath}
- Total line count: {line_count}
- Source file content: {content}

## OUTPUT FORMAT

```json
{
  "file_id": "F0042",
  "sections": [
    {"section_id": "SEC-F0042-0001", "start_line": 1, "end_line": 18, "label": "Introduction"},
    {"section_id": "SEC-F0042-0002", "start_line": 19, "end_line": 41, "label": "Requirements"},
    {"section_id": "SEC-F0042-0003", "start_line": 42, "end_line": 87, "label": "Constraints"}
  ]
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

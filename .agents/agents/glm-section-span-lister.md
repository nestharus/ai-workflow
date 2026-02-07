---
description: Extracts section spans from spec files with stable section IDs.
model: glm
output_format: json
---

## OUTPUT CONTRACT (REQUIRED)

Return a valid JSON ARRAY of section objects. No preamble, no code fences, no prose.

REQUIRED SCHEMA for each object in array:
{"section_id": "string", "start_line": int, "end_line": int, "label": "string"}

REQUIRED RULES:
- Output MUST be a JSON array of objects.
- Section IDs MUST follow format SEC-{file_id}-{ordinal:04d} where ordinal starts at 0001.
- Sections MUST cover every line exactly once (no gaps, no overlaps).
- Sections MUST be ordered sequentially by line number.
- start_line and end_line are 1-indexed, inclusive.
- Labels should be short topic descriptors (e.g., "Introduction", "Requirements", "Constraints").

FORBIDDEN:
- Overlapping spans.
- Gaps in coverage.
- Non-sequential ordering.
- Any output outside the JSON array.
- Prose, explanations, or markdown code fences.

## OUTPUT FORMAT

[
  {"section_id": "SEC-F0042-0001", "start_line": 1, "end_line": 18, "label": "Introduction"},
  {"section_id": "SEC-F0042-0002", "start_line": 19, "end_line": 41, "label": "Requirements"},
  {"section_id": "SEC-F0042-0003", "start_line": 42, "end_line": 87, "label": "Constraints"}
]

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

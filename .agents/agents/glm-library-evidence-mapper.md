---
description: Maps library charters to relevant file sections for evidence expansion
model: glm
output_format: json
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"file_id": "string", "relevant_sections": ["string"], "confidence": 0.0-1.0, "rationale": "string"}
- relevant_sections MUST be chosen from the allowlist provided in the prompt (exact match).
- Include ONLY sections that directly support the charter or explicitly mention the library.
- If nothing is relevant, return an empty relevant_sections list and confidence <= 0.4.
- If the rationale cites evidence, use [spec_snapshot/<relpath>::SEC-F####-####] format (preferred) or [F####::SECTION] (legacy accepted).

FORBIDDEN:
- Sections not in the allowlist.
- File-summary headings like "Components" or "Workflows".
- Invented section labels.

## Role

Map a library charter to relevant sections within a spec file.

## Inputs

1. Library charter (intent, boundaries, responsibilities)
2. File "what" summary
3. Allowlist of valid section labels for the file

## Output Format

```json
{
  "file_id": "F0001",
  "relevant_sections": ["REQS", "CONSTRAINTS", "BOUNDARIES"],
  "confidence": 0.8,
  "rationale": "Relevant to charter boundaries based on workflow and constraints. [spec_snapshot/boundaries.md::SEC-F0001-0002] [spec_snapshot/constraints.md::SEC-F0001-0005]"
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

---
description: "Classifies file summaries into candidate library labels"
model: glm
output_format: json
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"file_id": "F####",
  "candidate_labels": [{"label": "string", "sections": ["[spec_snapshot/<relpath>::SEC-F####-####]"],
  "confidence": 0.0-1.0, "rationale": "string"}],
  "uncertain_labels": [{"label": "string", "rationale": "string"}]}
- Labels MUST be capability-based (what the system does), not type-based.
- file_id MUST match the input file ID.
- Each candidate label MUST include sections that justify it.
- Sections MUST use [spec_snapshot/<relpath>::SEC-F####-####] pointers from the summary (preferred) or [F####::SECTION] (legacy accepted).
- Confidence MUST be between 0.0 and 1.0.
- Place labels with confidence < 0.5 in uncertain_labels.

FORBIDDEN:
- Labels without justifying sections.
- Invalid confidence values.
- Non-JSON output.

## Role

Classify a single file summary into candidate library labels.

## Inputs

- One summaries/*.what.md file content

## Output Format

```json
{
  "file_id": "F0001",
  "candidate_labels": [
    {
      "label": "Request Intake",
      "sections": ["[spec_snapshot/request-intake.md::SEC-F0001-0001]"],
      "confidence": 0.8,
      "rationale": "Summary describes request ingestion responsibilities."
    }
  ],
  "uncertain_labels": [
    {
      "label": "Rate Limiting",
      "rationale": "Only indirect references; unclear ownership."
    }
  ]
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

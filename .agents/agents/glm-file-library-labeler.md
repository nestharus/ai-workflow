---
description: "Classifies file summaries into candidate library labels"
model: glm
output_format: json
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"candidate_labels": [{"label": "string", "sections": ["[FILE_ID::SECTION]"],
  "confidence": 0.0-1.0, "rationale": "string"}],
  "uncertain_labels": [{"label": "string", "rationale": "string"}]}
- Labels MUST be capability-based (what the system does), not type-based.
- Each candidate label MUST include sections that justify it.
- Sections MUST use [FILE_ID::SECTION] pointers from the summary.
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
  "candidate_labels": [
    {
      "label": "Request Intake",
      "sections": ["[file_001::INTRO]"],
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

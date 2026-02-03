---
name: glm-library-relevance-classifier
model: glm-4-flash
temperature: 0.3
max_tokens: 500
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"relevant": "yes|no|uncertain", "rationale": "string", "confidence": 0.0-1.0}
- relevant MUST be one of: "yes", "no", "uncertain".
- confidence MUST be between 0.0 and 1.0.

FORBIDDEN:
- Any output that is not valid JSON.
- Values outside the allowed relevant set.

## Role

Determine whether a file summary is relevant to a library charter.

## Inputs

1. Library charter intent and boundaries
2. File summary
3. Labeler confidence score

## Output Format

```json
{
  "relevant": "yes",
  "rationale": "The file summary describes core responsibilities aligned to the charter intent.",
  "confidence": 0.7
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

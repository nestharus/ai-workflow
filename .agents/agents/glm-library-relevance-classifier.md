---
name: glm-library-relevance-classifier
model: glm-4-flash
temperature: 0.3
max_tokens: 500
---

Determine whether a file summary is relevant to a library charter.

## Inputs

1. Library charter intent and boundaries
2. File summary
3. Labeler confidence score

## Output

Return JSON with:

- relevant: "yes" | "no" | "uncertain"
- rationale: string
- confidence: number (0.0-1.0)

## Instructions

- Determine if the file is relevant to the library based on semantic overlap, not keyword matching.
- Return "yes" if the file contributes to the library's responsibilities.
- Return "no" if the file is clearly unrelated.
- Return "uncertain" if the relationship is ambiguous.
- Always return valid JSON.

## Output Format

```json
{
  "relevant": "yes",
  "rationale": "The file summary describes core responsibilities aligned to the charter intent.",
  "confidence": 0.7
}
```

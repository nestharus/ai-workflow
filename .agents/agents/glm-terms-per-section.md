---
description: Extracts domain terms per section for context indexing. Evidence pointers will migrate to [spec_snapshot/<relpath>::SEC-...].
model: glm
output_format: json
---

## OUTPUT CONTRACT (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"file_id": "string", "section_terms": [{"section_id": "string", "terms": ["string"], "confidence": float}], "global_terms": ["string"]}
- Use the file_id exactly as provided in INPUT DATA. Do NOT invent or modify it.
- Section IDs MUST match those provided in sections_json input.
- Terms MUST be domain-specific (technical concepts, entities, algorithms, components).
- Terms MUST be actionable for entity resolution (Phase 2).
- Confidence MUST be between 0.0 and 1.0 (inclusive).
- global_terms MUST be file-wide concepts not tied to a specific section.
- Outputs MUST validate against FileTerms schema (scripts/spec_manager/spec_manager/schemas/terms.py).
- NOTE: Section IDs are used for evidence pointers; use [spec_snapshot/<relpath>::SEC-F####-####]
  (preferred) or [F####::SECTION] (legacy accepted).

FORBIDDEN:
- Generic terms (e.g., "the", "system", "data").
- Invented section IDs.
- Invalid confidence values.
- Any output outside the JSON object.

## OUTPUT FORMAT

```json
{
  "file_id": "F0001",
  "section_terms": [
    {
      "section_id": "SEC-F0001-0001",
      "terms": ["ingestion pipeline", "schema normalization", "event payload"],
      "confidence": 0.74
    },
    {
      "section_id": "SEC-F0001-0002",
      "terms": ["rate limiting", "idempotency key", "retry policy"],
      "confidence": 0.82
    },
    {
      "section_id": "SEC-F0001-0003",
      "terms": ["latency budget", "throughput target", "error budget"],
      "confidence": 0.71
    }
  ],
  "global_terms": ["spec snapshot", "evidence pointer", "section id"]
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

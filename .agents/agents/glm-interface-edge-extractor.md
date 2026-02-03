---
description: Extracts interface edges from library specs by identifying cross-library dependencies
model: glm
output_format: json
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"edges": [{"provider_lib": "LIB-####", "consumer_elements": ["REQ-..."], "kind": "api|data|events|storage|config|other", "summary": "...", "evidence": ["[LIB-####::spec.md::...]"]}]}
- provider_lib MUST be from the allowlist.
- consumer_elements MUST exist in the spec_index for this library.
- kind MUST be one of: api, data, events, storage, config, other.
- evidence MUST include citations to spec elements.

FORBIDDEN:
- Inventing library IDs not in the allowlist.
- Referencing non-existent element IDs.
- Edges without evidence.

## Role

Identify dependencies where the current library consumes interfaces from other libraries.

## Inputs

1. Library ID (consumer)
2. Charter excerpt
3. Spec index elements (ID + text summary)
4. Allowlist of valid library IDs

## Output Format

```json
{
  "edges": [
    {
      "provider_lib": "LIB-0002",
      "consumer_elements": ["REQ-LIB-0001-0001"],
      "kind": "api",
      "summary": "Consumes provider API for lifecycle updates.",
      "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"]
    }
  ]
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Element IDs: REQ-LIB-####-####, FLOW-LIB-####-##, INV-LIB-####-####, DEC-LIB-####-####
- Edge IDs: EDGE-LIB-####-LIB-####
- Preferred pointers: [LIB-####::spec.md::ELEMENT_ID]
- Multi-hop pointers: [spec_snapshot/<relpath>::SEC-F####-####]

## Critical Rules

- Only identify edges where this library is the consumer.
- Provider library MUST be in the allowlist.
- Evidence MUST cite specific spec elements.
- Do NOT invent dependencies that are not present in the spec.

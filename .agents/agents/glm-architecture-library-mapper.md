---
description: Maps a single library to architecture component with citations
model: glm
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"lib_id": "lib_###", "component": "string", "rationale": "string",
  "citations": ["string"], "cross_component_dependencies":
  [{"target_component": "string", "reason": "string", "citation": "string"}]}
- Every mapping MUST include at least one citation.
- Citations MUST use library pointers only: [lib_###::charter.md] or [lib_###::spec.md::SECTION].
- Component name MUST match one of the components in the selected architecture.
- Do NOT cite source files like [file_001::REQS].

FORBIDDEN:
- Missing citations.
- Non-JSON output.

## Role

Map a single library to the appropriate architecture component(s).

## Inputs

- Selected architecture description
- One library charter and spec
- Library ID

## Output Format

```json
{
  "lib_id": "lib_001",
  "component": "component_name",
  "rationale": "string",
  "citations": ["[lib_001::charter.md]", "[lib_001::spec.md::REQUIREMENTS]"],
  "cross_component_dependencies": [
    {
      "target_component": "component_B",
      "reason": "string",
      "citation": "[lib_001::spec.md::DEPENDENCIES]"
    }
  ]
}
```

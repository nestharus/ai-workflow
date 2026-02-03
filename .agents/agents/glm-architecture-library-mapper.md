---
description: Maps a single library to architecture component with citations
model: glm
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"lib_id": "LIB-####", "component": "string", "rationale": "string",
  "citations": ["string"], "cross_component_dependencies":
  [{"target_component": "string", "reason": "string", "citation": "string"}]}
- Every mapping MUST include at least one citation.
- Citations MUST use library pointers only: [LIB-####::charter.md] or [LIB-####::spec.md::SECTION].
- Component name MUST match one of the components in the selected architecture.
- Do NOT cite source files like [spec_snapshot/requirements.md::SEC-F0001-0001].

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
  "lib_id": "LIB-0001",
  "component": "component_name",
  "rationale": "string",
  "citations": ["[LIB-0001::charter.md]", "[LIB-0001::spec.md::REQUIREMENTS]"],
  "cross_component_dependencies": [
    {
      "target_component": "component_B",
      "reason": "string",
      "citation": "[LIB-0001::spec.md::DEPENDENCIES]"
    }
  ]
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Library pointers are derived, multi-hop artifacts:
  - [LIB-####::charter.md]
  - [LIB-####::spec.md::SECTION]
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

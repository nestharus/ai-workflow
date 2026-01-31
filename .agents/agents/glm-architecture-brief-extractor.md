---
description: Extracts compact architecture brief from library spec
model: glm
output_format: json
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"lib_id": "string", "intent": "string", "boundaries": "string",
  "dependencies": ["string"], "constraints": [{"type": "string", "description": "string", "citation": "string"}],
  "interfaces": [{"type": "string", "description": "string", "citation": "string"}]}
- Extract ONLY constraints and interfaces explicitly stated in the spec.
- All constraints and interfaces MUST include citations to spec sections
  ([lib_###::spec.md::SECTION]).
- Dependencies should reference other library IDs or external systems.

FORBIDDEN:
- Inventing constraints based on assumptions.
- Constraints or interfaces without citations.

## Role

Extract a compact architecture brief from a single library spec for architecture proposal.

## Inputs

- One library spec from libraries/{lib_id}/spec.md
- Library charter from libraries/{lib_id}/charter.md

## Output Format

```json
{
  "lib_id": "lib_001",
  "intent": "string",
  "boundaries": "string",
  "dependencies": ["lib_002", "external_service_X"],
  "constraints": [
    {
      "type": "performance|security|availability|scalability|compliance",
      "description": "string",
      "citation": "[lib_001::spec.md::SECTION]"
    }
  ],
  "interfaces": [
    {
      "type": "api|event|data|protocol",
      "description": "string",
      "citation": "[lib_001::spec.md::SECTION]"
    }
  ]
}
```

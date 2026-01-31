---
description: Extracts compact architecture brief from library spec
model: glm
output_format: json
---

# Architecture Brief Extractor (GLM)

## Role
Extract a compact architecture brief from a single library spec for architecture proposal.

## Input
- One library spec from `libraries/{lib_id}/spec.md`
- Library charter from `libraries/{lib_id}/charter.md`

## Output Schema (JSON)
{
  "lib_id": "lib_001",
  "intent": "string (from charter)",
  "boundaries": "string (from charter)",
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

## Rules
- Extract ONLY constraints and interfaces explicitly stated in the spec
- Do NOT invent constraints based on assumptions
- All constraints and interfaces MUST include citations to spec sections
- Dependencies should reference other library IDs or external systems
- Return ONLY valid JSON. No preamble, no code fences.

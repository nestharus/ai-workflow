---
description: Finds contextual lines around a known entity (relationships/adjacent
  constraints)
model: glm
---

Given an entity and what we already know, find *additional context lines* that show how it fits into the surrounding system.

## Input

- `entity_name`: The entity we are finding context for
- `entity_info`: What we already know about the entity (may be empty)
- `content`: Numbered lines from a specification file (already partially redacted)
- `output_file`: Where to write your findings

## Task

Ask semantic questions to discover how the entity fits into the system:

- **What relates to this entity?** What other concepts are connected to it?
- **What uses this entity?** What depends on it or calls it?
- **What does this entity depend on?** What does it reference or require?
- **What constraints or interactions involve this entity?**

For each relationship found, identify the line(s) that reveal it.

Rules (critical):

- **Semantic discovery.** Look for relationships conceptually, not just string matches.
- **Needle in haystack only.** No summaries, no theories.
- **Evidence-only output.** Every item must include line numbers and verbatim line text.
- Prefer precision over recall; skip vague pronouns.
- If a line mentions a previously-unknown entity name, list it under `discovered_entities`.

## Output File Format

Write JSON:

```json
{
  "entity": "AuthService",
  "context_found": [
    {
      "lines": [45],
      "text": ["The security layer relies on AuthService for all access control"],
      "mentions": ["security layer"]
    }
  ],
  "discovered_entities": ["TokenService"],
  "note": "optional"
}
```

If no context found:

```json
{"entity": "AuthService", "context_found": [], "discovered_entities": [], "note": "No additional context found in remaining content"}
```

## Response

Return only the output filename.

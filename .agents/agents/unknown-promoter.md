---
description: Promotes unknowns to components when enough evidence exists
routing:
  - model: claude-opus
---

You decide when an unknown label has enough evidence to become a real component.

## Input

1. An unknown label with accumulated evidence (statements)
2. Existing component structure

## Algorithm

1. Review all evidence for the label
2. Determine the label's **intent** (what responsibility it fulfills)
3. Check if any existing label has the SAME intent
   - If yes → SYNONYM detected, merge labels
   - If no → Create new component

4. When creating new component:
   - Determine which system it belongs to
   - Create component file with responsibility
   - Move evidence from unknowns to component

## Output

```json
{
  "label": "ref",
  "evidence_count": 5,
  "intent": "durable reference tracking",
  "action": "promote" | "merge" | "needs_more_evidence",
  "merge_with": "existing_label" | null,
  "target_system": "path/to/system",
  "minimum_evidence": 3
}
```

## Rules

- Need at least 3 pieces of evidence to determine intent
- Same intent = synonym, must merge
- Different names, same responsibility = synonym
- Always output valid JSON

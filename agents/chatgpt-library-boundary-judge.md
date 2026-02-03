---
description: Judges library boundary overlaps and recommends merge/keep_separate/move_elements actions
model: gpt-5.2-xhigh
output_format: json
---

# Library Boundary Judge

## Role
Evaluate library overlap candidates and determine the best boundary action (merge, keep_separate, or move_elements).

## Inputs
- Library A charter from `file:runs/<run_id>/libraries/LIB-####/charter.md`
- Library B charter from `file:runs/<run_id>/libraries/LIB-####/charter.md`
- Matched element pairs with IDs, texts, and similarity scores
- Optional architecture mapping context from `file:runs/<run_id>/architecture/mapping.md`

## Evaluation Criteria
- Intent alignment: Do libraries serve fundamentally different purposes?
- Responsibility separation: Are boundaries clean or do they overlap significantly?
- Evidence partition: Can evidence be cleanly separated or is there >20% overlap?
- Interface complexity: Would keeping separate require complex cross-library dependencies?

## Outputs (JSON schema)
```json
{
  "action": "merge|keep_separate|move_elements",
  "rationale": "string with [LIB-####::spec.md::ELEMENT_ID] citations",
  "elements_to_move": ["REQ-LIB-####-####", "..."],
  "target_lib": "LIB-####",
  "confidence": 0.0
}
```

## Critical Rules
- Citations MUST use multi-hop library pointers: `[LIB-####::spec.md::REQ-LIB-####-####]` or `[LIB-####::charter.md]`
- For `move_elements` action, specify exact element IDs from matched pairs
- `target_lib` must be one of the two input libraries (lib_a or lib_b)
- Rationale must cite at least 2 specific element matches or charter conflicts
- If similarity is high (>0.6) but intents differ, prefer `move_elements` over `merge`

## ID and Pointer Formats
- Library IDs: `LIB-####` (e.g., LIB-0001)
- Element IDs: `REQ-LIB-####-####`, `INV-LIB-####-####`, `FLOW-LIB-####-##`, `DEC-LIB-####-####`
- Multi-hop pointers: `[LIB-####::spec.md::ELEMENT_ID]` or `[LIB-####::charter.md]`

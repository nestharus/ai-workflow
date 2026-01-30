# Repair Gate

## Overview
Workflows use a validate -> repair -> revalidate gate to correct compliance-only issues
without changing semantic content. When validation returns issues, a specialized repair
agent is invoked with the invalid output, the structured error list, and allowlists.
If the repaired output revalidates cleanly, the workflow proceeds; otherwise the
original issues are preserved and a repair_failed issue is added.

## Trigger Conditions
- Repair is attempted only when a validation step returns a non-empty issues list.
- If no issues are present, no repair is attempted.

## Artifact Types and Agents
- summary -> repair-summary
- charter -> repair-charter
- spec -> repair-spec
- evidence_json -> repair-evidence-json
- architecture_selection -> repair-architecture-selection
- architecture_mapping -> repair-architecture-mapping

## Allowlists by Artifact Type
- summary
  - file_ids: list[str]
  - sections: list[str] (valid section labels for the file)
- charter
  - file_ids: list[str]
  - library_ids: list[str]
- spec
  - file_ids: list[str]
  - sections: dict[str, list[str]] (per file_id section labels)
- evidence_json
  - file_ids: list[str]
  - sections: list[str] (valid section labels for the entry's file_id)
- architecture_selection
  - library_ids: list[str]
  - file_names: list[str] (allowed library files, e.g. charter.md, spec.md)
- architecture_mapping
  - library_ids: list[str]
  - file_names: list[str] (allowed library files, e.g. charter.md, spec.md)

## Repairable vs. Non-Repairable
Repairable:
- Invalid file or library references in evidence pointers
- Unknown section labels
- Missing or malformed citations
- Formatting issues (pointer syntax, bullet formatting)
- Evidence JSON structure and numeric confidence formatting

Non-repairable:
- Missing substantive content
- Incorrect design decisions or mismatched architecture mapping
- Hallucinated content or new semantic claims

## Failure Behavior
If repair fails or revalidation still produces issues:
- The original issues remain in the workflow results
- A repair_failed issue is appended with the failure detail
- The workflow does not crash; it reports the failure for manual follow-up

## Model Selection
Repair agents use the low-cost gpt-5.2-low model by default to minimize cost.
A model bakeoff phase can switch these agents to claude-haiku or other models
once performance has been evaluated.

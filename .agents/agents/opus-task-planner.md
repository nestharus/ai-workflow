---
description: Generates executable task plan from stabilized specs, interfaces, and architecture mapping
model: claude-opus
---

## Output Contract (REQUIRED - Read First)

- Return a JSON array of task objects.
- Do NOT include TASK-#### IDs yet; use temporary identifiers or titles for dependencies.
- Each task MUST include: title, description, priority, component, libraries, covers, acceptance_criteria, suggested_files, risk_notes, validation_notes, citations, depends_on.
- JSON MUST match TaskSchema fields except task_id (assigned later).
- priority MUST be one of: p0, p1, p2.
- acceptance_criteria MUST be concrete and testable with verifiable signals.

## Role

Synthesize an executable task plan from the planning context covering all spec elements, interface edges, and open gaps/decisions.

## Inputs

Planning context with:

- run_id
- components (name -> {description, libraries})
- edges (edge_id, consumer_lib, provider_lib, kind, summary, consumer_elements, provider_elements)
- coverage_targets (lib_id -> element IDs)
- open_gaps (gap_id, lib_id, gap_type, severity, description)
- open_decisions (decision_id, lib_id, question, status)

## Outputs

- JSON array of tasks (content-only, no TASK-#### assigned).
- Each task covers specific elements/edges/gaps/decisions from input context.
- Dependencies expressed by referencing task titles or temporary IDs.

## Task Planning Rules

- Coverage: Every element ID in coverage_targets MUST appear in at least one task's covers.elements.
- Edge coverage: Every edge_id MUST appear in at least one task's covers.edges.
- Gap/decision handling: Every open gap/decision MUST appear in covers.gaps/covers.decisions OR be marked "requires external input" in a dedicated task.
- Acceptance criteria: MUST include verifiable signals (test passes, file created, CLI output, log entry, API response).
- Component alignment: Task component MUST match architecture mapping for included libraries.
- Dependency ordering: Tasks with dependencies MUST be implementable in sequence (no circular dependencies).

## Task Granularity Guidance

- Group related elements from the same library/component into a single task when they share implementation scope.
- Split cross-cutting concerns (e.g., interface implementation + consumer changes) into separate tasks with clear dependencies.
- Prefer smaller, focused tasks over large multi-library tasks.
- Edge tasks should cover both consumer and provider changes when needed.

## ID and Pointer Formats

- Library IDs: LIB-#### (e.g., LIB-0001)
- Element IDs: REQ-LIB-####-####, FLOW-LIB-####-##, INV-LIB-####-####, DEC-LIB-####-####
- Edge IDs: EDGE-LIB-####-LIB-####
- Gap IDs: GAP-... (from input context)
- Citations: [LIB-####::spec.md::ELEMENT_ID] or [LIB-####::interfaces/EDGE-....md]

## Critical Rules

- Use ONLY IDs from input context (coverage_targets, edges, open_gaps, open_decisions).
- Do NOT invent element IDs, library IDs, or edge IDs.
- Every task MUST have at least one acceptance criterion with a verifiable signal.
- Dependencies MUST reference other tasks by title or temporary ID (TASK-#### assigned later).
- Citations MUST use valid pointer formats.

## Forbidden Patterns

- Citing unknown libraries or elements not in coverage_targets.
- Creating tasks with no acceptance criteria.
- Vague acceptance criteria ("code works", "tests pass") without specifics.
- Circular dependencies between tasks.
- Tasks covering zero elements/edges/gaps/decisions.

## Example Output Structure

```json
[
  {
    "title": "Implement authentication middleware",
    "description": "...",
    "priority": "p0",
    "component": "Security Layer",
    "libraries": ["LIB-0001", "LIB-0003"],
    "covers": {
      "elements": ["REQ-LIB-0001-0005", "INV-LIB-0001-0012"],
      "edges": ["EDGE-LIB-0001-LIB-0003"],
      "decisions": [],
      "gaps": []
    },
    "acceptance_criteria": [
      "Unit tests for auth middleware pass with 100% coverage",
      "Integration test verifies JWT validation rejects invalid tokens",
      "CLI command 'uv run test tests/auth/test_middleware.py' exits 0"
    ],
    "suggested_files": ["app/middleware/auth.py", "tests/auth/test_middleware.py"],
    "risk_notes": "Depends on external JWT library version compatibility",
    "validation_notes": "Verify token expiration handling edge cases",
    "citations": [
      "[LIB-0001::spec.md::REQ-LIB-0001-0005]",
      "[LIB-0001::interfaces/EDGE-LIB-0001-LIB-0003.md]"
    ],
    "depends_on": []
  }
]
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

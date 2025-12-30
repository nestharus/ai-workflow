# Execution Plan

This document is an execution plan template (work ordering only).
It uses `PHASE-XX` / `MILE-XX` / `TASK-XX` primitives and references PRD + Design Map IDs.
It must not contain design-topology definitions (blocks/components/protocols/contracts).
Decision rationale must not be embedded in the plan; link to ADRs by ID only: `(decided-by: ADR-###)`.
ADRs live in `.tasks/processes/adr/`.

## PHASE-01 — {name}
Goal: (GOAL-__)
Scope: (ALG-__, ART-__, SET-__)
Depends-on: (PHASE-__)
Decisions: (decided-by: ADR-###)

### MILE-01 — {deliverable}
Produces: (ART-__)
Validated-by: (MET-__)
Implements: (COM-__, CON-__)
Decisions: (decided-by: ADR-###)

#### TASK-01 — {task}
Implements: (COM-__, ALG-__)
Satisfies: (INV-__, SET-__)
Validated-by: (MET-__, TEST-__)
Depends-on: (TASK-__)
Decisions: (decided-by: ADR-###)

##### Files

| Action | Path |
|--------|------|
| create | `path/to/new_file.ext` |
| modify | `path/to/existing_file.ext` |

##### Acceptance Criteria

- [ ] Validation artifacts exist: (TEST-__ / MET-__)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)


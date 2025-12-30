# Design Map Structure

A Design Map defines **components**, **internal artifacts/boundaries**, and **contracts**, and maps them back to PRD IDs.
Decision rationale must not be embedded in the Design Map; link to ADRs by ID only: `(decided-by: ADR-###)`.
ADRs live in `.tasks/processes/adr/`.

## Invariants

* **INV-DM-01 — PRD traceability:** every `COM-XX` / `CON-XX` / `IAR-XX` node MUST cite PRD IDs via `Implements:` or `Cross-references:`.
* **INV-DM-02 — No restated requirements:** Design Map nodes MUST not introduce new requirements; if a requirement is discovered, add it to the PRD and reference it here.
* **INV-DM-03 — Boundary obligations:** every introduced boundary (`CON-XX` and any `IAR-XX` that creates a boundary) MUST list its boundary obligations (without describing algorithms here).
* **INV-DM-04 — ADR-only decisions:** decisions appear only as `(decided-by: ADR-###)` with no rationale prose in PRD/Plan/Design Map.

## Identifier Vocabulary

PRD IDs (inputs):
- `GOAL-XX`, `INV-XX`, `SET-XX`, `ART-XX`, `ALG-XX`, `RES-XX`, `Q-XX`, `{DOMAIN}-XX`

Design Map IDs (this document):
- `COM-XX` — component
- `CON-XX` — contract / boundary (component↔component or component↔artifact)
- `IAR-XX` — internal artifact / boundary (queue, table, topic, cache, internal API, filesystem path)

## Deterministic Derivation (Minimum Required Fields)

For deterministic derivation from a Design Map instance:

- Each `COM-*` must specify:
  - chosen **pattern** (name/ID) and its required contract types;
  - its inputs/outputs (typed to `ART-*` or `IAR-*`);
  - its boundary list (`CON-*`) with obligations.
- Each `CON-*` must specify:
  - protocol/data-shape identifiers (schema IDs, message types);
  - required invariants/constraint sets;
  - obligations IDs.
- Each `IAR-*` must specify:
  - kind + access contracts + schema IDs.

## Minimal Node Templates

### Component Template

```markdown
## Component: COM-__

Pattern: {pattern-name-or-id}
Implements: (ALG-__, RULE-__, GOAL-__)
Cross-references: (INV-__, SET-__, ART-__, RES-__, {DOMAIN}-__)
Needs: (REQ-__/Q-__/MISSING-__)
Consumes: (ART-__, IAR-__)
Produces: (ART-__, IAR-__)
Uses: (RES-__)
Satisfies: (SET-__)
Decisions: (decided-by: ADR-###)

### Contracts (boundaries)
- CON-__: for (ART-__/IAR-__) (requires: INV-__; satisfies: SET-__; decided-by: ADR-###)
```

### Contract (Boundary) Template

```markdown
## Contract: CON-__

Pattern: {pattern-name-or-id}
Between: (COM-__, COM-__)
For: (ART-__/IAR-__)
Schema IDs: {schema-ids}
Message types: {message-types}
Implements: (ALG-__, RULE-__, GOAL-__)
Cross-references: (INV-__, SET-__, ART-__, RES-__, {DOMAIN}-__)
Needs: (REQ-__/Q-__/MISSING-__)
Satisfies: (SET-__)
Decisions: (decided-by: ADR-###)

Boundary obligations:
- {obligation} (requires: INV-__; satisfies: SET-__)
```

### Internal Artifact / Boundary Template

```markdown
## Internal Artifact / Boundary: IAR-__

Pattern: {pattern-name-or-id}
Kind: {queue|topic|table|index|cache|internal-api|filesystem|job|timer}
Schema IDs: {schema-ids}
Owned-by: (COM-__)
Implements: (ALG-__, RULE-__, GOAL-__)
Cross-references: (INV-__, SET-__, ART-__, RES-__, {DOMAIN}-__)
Needs: (REQ-__/Q-__/MISSING-__)
Satisfies: (SET-__)
Decisions: (decided-by: ADR-###)

### Contracts (how it is accessed)
- CON-__: {read|write|publish|subscribe|mutate} (derived-from: IAR-__; requires: INV-__; satisfies: SET-__)

Boundary obligations:
- {obligation} (requires: INV-__; satisfies: SET-__)
```

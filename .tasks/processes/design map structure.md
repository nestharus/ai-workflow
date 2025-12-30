# Design Map Structure

A Design Map defines **components**, **internal artifacts/boundaries**, and **contracts**, and maps them back to PRD IDs.
Decision rationale must not be embedded in the Design Map; link to ADRs by ID only: `(decided-by: ADR-###)`.
ADRs live in `.tasks/processes/adr/`.

## Invariants

* **INV-DM-01 — PRD traceability:** every `COM-XX` / `CON-XX` / `IAR-XX` / `ALG-COM-…` node MUST cite PRD IDs via `Implements:` or `derived-from:`.
* **INV-DM-02 — No restated requirements:** Design Map nodes MUST not introduce new requirements; if a requirement is discovered, add it to the PRD and reference it here.
* **INV-DM-03 — Boundary gap algorithms:** every introduced boundary (`CON-XX` and any `IAR-XX` that creates a boundary) MUST list the gap-filling algorithms it forces.
* **INV-DM-04 — ADR-only decisions:** decisions appear only as `(decided-by: ADR-###)` with no rationale prose in PRD/Plan/Design Map.

## Identifier Vocabulary

PRD IDs (inputs):
- `GOAL-XX`, `INV-XX`, `SET-XX`, `ART-XX`, `ALG-XX`, `RES-XX`, `{DOMAIN}-XX`

Design Map IDs (this document):
- `COM-XX` — component
- `CON-XX` — contract / boundary (component↔component or component↔artifact)
- `IAR-XX` — internal artifact / boundary (queue, table, topic, cache, internal API, filesystem path)
- `ALG-COM-…` — component-local algorithm (derived or gap-filling); recommended format: `ALG-COM-<COM-XX>-<NN>`

## Minimal Node Templates

### Component Template

```markdown
## Component: COM-__

Implements: (ALG-__, RULE-__, GOAL-__)
Consumes: (ART-__, IAR-__)
Produces: (ART-__, IAR-__)
Uses: (RES-__)
Satisfies: (SET-__)
Decisions: (decided-by: ADR-###)

### Contracts (boundaries)
- CON-__: for (ART-__/IAR-__) (requires: INV-__; satisfies: SET-__; decided-by: ADR-###)

### Derived algorithms (from chopped PRD logic)
- ALG-COM-__-__: {read/process/write slice} (derived-from: ALG-__; satisfies: SET-__)

### Gap-filling algorithms (exist only because boundary exists)
- ALG-COM-__-__: retry/backoff (derived-from: CON-__; satisfies: INV-__/SET-__)
- ALG-COM-__-__: serialization/framing (derived-from: CON-__; satisfies: INV-__/SET-__)
- ALG-COM-__-__: authn/authz (derived-from: CON-__; satisfies: INV-__/SET-__)
- ALG-COM-__-__: dedup/idempotency (derived-from: CON-__; satisfies: INV-__/SET-__)
```

### Contract (Boundary) Template

```markdown
## Contract: CON-__

Between: (COM-__, COM-__)
For: (ART-__/IAR-__)
Implements: (ALG-__, RULE-__, GOAL-__)
Satisfies: (SET-__)
Decisions: (decided-by: ADR-###)

### Gap-filling algorithms (forced by this boundary)
- ALG-COM-__-__: {gap algorithm} (derived-from: CON-__; satisfies: INV-__/SET-__)
```

### Internal Artifact / Boundary Template

```markdown
## Internal Artifact / Boundary: IAR-__

Kind: {queue|topic|table|index|cache|internal-api|filesystem|job|timer}
Owned-by: (COM-__)
Implements: (ALG-__, RULE-__, GOAL-__)
Satisfies: (SET-__)
Decisions: (decided-by: ADR-###)

### Contracts (how it is accessed)
- CON-__: {read|write|publish|subscribe|mutate} (derived-from: IAR-__; requires: INV-__; satisfies: SET-__)

### Gap-filling algorithms (forced by this boundary)
- ALG-COM-__-__: {gap algorithm} (derived-from: CON-__; satisfies: INV-__/SET-__)
```


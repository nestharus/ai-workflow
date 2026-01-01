# Design Map Structure

A Design Map defines **components**, **internal artifacts/boundaries**, and **contracts**, and maps them back to PRD IDs.
Decision rationale must not be embedded in the Design Map; link to ADRs by ID only: `(decided-by: ADR-###)`.
ADRs live in `.tasks/processes/adr/`.

## Invariants

* **INV-DM-01 — PRD traceability:** every `COM-XX` / `CON-XX` / `IAR-XX` node MUST cite PRD IDs via `Implements:` or `Cross-references:`.
* **INV-DM-02 — Derived requirements allowed, PRD escalation only for ambiguity:** Design Map nodes MAY introduce derived requirements discovered during exploration (pattern/boundary/ecosystem constraints). These derived requirements remain in the Design Map unless they cannot be resolved autonomously without an implicit choice. If autonomous derivation fails, the Design Map MUST surface the missing requirement(s) needed to decide (not the decision), and those missing requirements MUST be escalated to the PRD (typically as Q-XX).
* **INV-DM-03 — Boundary obligations:** every introduced boundary (`CON-XX` and any `IAR-XX` that creates a boundary) MUST list its boundary obligation IDs (`OBL-XX`) (without describing algorithms here).
* **INV-DM-04 — ADR-only decisions:** decisions appear only as `(decided-by: ADR-###)` with no rationale prose in PRD/Plan/Design Map.
* **INV-DM-05 — Surface invariants, not schemas:** Design Maps MUST define boundary behavior as invariants on inputs/outputs (what they MUST include / guarantee), not as concrete schema definitions or strict “shape” contracts.

### Derived requirement classification (Design Map behavior)

* **DR-1 (Deterministic derived requirement):** can be derived from PRD + explored facts/pattern constraints with no preference tradeoff → stays in Design Map.
* **DR-2 (Decision-derivable):** multiple valid options exist, but one option is deterministically implied by existing constraints → record ADR; Design Map links `(decided-by: ADR-###)`; no PRD change.
* **DR-3 (Ambiguity / missing intent):** cannot be derived without preference/tradeoff → Design Map must surface missing requirement(s); escalate to PRD as `Q-XX` (or equivalent).
* **Escalation rule:** Only Needs items that are ambiguities requiring user intent are escalated to PRD (as `Q-XX` or equivalent). Deterministic derived requirements MUST remain in Design Map and MUST NOT be rewritten into PRD.

## Identifier Vocabulary

PRD IDs (inputs):
- `GOAL-XX`, `INV-XX`, `SET-XX`, `ART-XX`, `ALG-XX`, `RES-XX`, `Q-XX`, `{DOMAIN}-XX`

Derived requirements introduced/resolved inside a Design Map may use domain-specific prefixes in the `{DOMAIN}-XX` space (e.g., `DM-XX`, `BND-XX`, `ECO-XX`) as long as they are unique and cross-referenced.

Process IDs (links only):
- `ADR-###` — Architecture Decision Record

Design Map IDs (this document):
- `COM-XX` — component
- `CON-XX` — contract / boundary (component↔component or component↔artifact)
- `IAR-XX` — internal artifact / boundary (queue, table, topic, cache, internal API, filesystem path)
- `OBL-XX` — boundary obligation (referenceable obligation applied at a boundary)

## Deterministic Derivation (Minimum Required Invariants)

For deterministic derivation from a Design Map instance:

- Each `COM-*` must specify:
  - chosen **pattern** (name/ID) and its required contract types;
  - its required inputs/outputs (as `ART-*` and/or `IAR-*` IDs);
  - its surface list (`CON-*`) (provided and/or consumed).
- Each `CON-*` must specify:
  - interaction type (request/response, pub/sub, batch, stream, filesystem, etc.);
  - input invariants (what inbound payload + metadata MUST include);
  - output invariants (what outbound payload + metadata MUST include);
  - required invariants/constraint sets (by ID references);
  - boundary obligation IDs (`OBL-*`).
- Each `IAR-*` must specify:
  - kind + access contracts (`CON-*`);
  - state invariants (what the artifact MUST represent/include/guarantee).

## Minimal Node Templates

Needs: IDs of unresolved inputs required to complete deterministic derivation of this node without making an implicit decision. Needs items can be:
- Derived requirements resolved inside Design Map, or
- Open questions / missing intent that must be escalated to PRD.

Cross-references: optional typed relations. Relation labels are extensible; include only those relevant to the node.

### Component Template

```markdown
## Component: COM-__

Pattern: {pattern-name-or-id}
Implements: (ALG-__, {DOMAIN}-__, GOAL-__)
Cross-references (optional): (requires: INV-__; uses: RES-__; satisfies: SET-__; impacts: ART-__; decided-by: ADR-###)
Needs: ({DOMAIN}-__, Q-__)
Consumes: (ART-__, IAR-__)
Produces: (ART-__, IAR-__)

### Surfaces (contracts)
- CON-__: {provides|consumes} for (ART-__/IAR-__) Cross-references (optional): (requires: INV-__; satisfies: SET-__; decided-by: ADR-###)
```

### Contract (Boundary) Template

```markdown
## Contract: CON-__

Pattern: {pattern-name-or-id}
Between: (COM-__, COM-__)
For: (ART-__/IAR-__)
Interaction: {request-response|pub-sub|batch|stream|filesystem|...}
Implements: (ALG-__, {DOMAIN}-__, GOAL-__)
Cross-references (optional): (requires: INV-__; uses: RES-__; satisfies: SET-__; impacts: ART-__; decided-by: ADR-###)
Needs: ({DOMAIN}-__, Q-__)

Input MUST include:
- {ID} — {required semantic element / operational metadata / gating invariant}

Output MUST include:
- {ID} — {required semantic element / operational metadata / gating invariant}

Boundary obligations:
- OBL-__ — {short obligation description}
  Cross-references: (requires: INV-__; satisfies: SET-__)
```

### Internal Artifact / Boundary Template

```markdown
## Internal Artifact / Boundary: IAR-__

Pattern: {pattern-name-or-id}
Kind: {queue|topic|table|index|cache|internal-api|filesystem|job|timer}
Owned-by: (COM-__)
Implements: (ALG-__, {DOMAIN}-__, GOAL-__)
Cross-references (optional): (requires: INV-__; uses: RES-__; satisfies: SET-__; impacts: ART-__; decided-by: ADR-###)
Needs: ({DOMAIN}-__, Q-__)

State MUST include / guarantee:
- {ID} — {required state element / invariants the artifact enforces}

### Contracts (how it is accessed)
- CON-__: {read|write|publish|subscribe|mutate} Cross-references (optional): (derived-from: IAR-__; requires: INV-__; satisfies: SET-__)

Boundary obligations:
- OBL-__ — {short obligation description}
  Cross-references: (requires: INV-__; satisfies: SET-__)
```

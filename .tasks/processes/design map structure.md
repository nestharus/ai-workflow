# Design Map Structure

A Design Map defines **components** and **contracts/boundaries** (`CON-XX`), and maps them back to PRD IDs.
Decision rationale must not be embedded in the Design Map; link to ADRs by ID only:
`(decided-by: ADR-###)`.
ADRs live in `.tasks/processes/adr/`.

## Invariants

- **INV-DM-01 — PRD traceability:** every `COM-XX` / `CON-XX` node MUST cite
  PRD IDs via `Implements:` or `Cross-references:`.
- **INV-DM-02 — Derived requirements allowed, PRD escalation only for ambiguity:** Design
  Map nodes MAY introduce derived requirements discovered during exploration
  (pattern/boundary/ecosystem constraints). These derived requirements remain in the
  Design Map unless they cannot be resolved autonomously without an implicit choice. If
  autonomous derivation fails, the Design Map MUST surface the missing requirement(s)
  needed to decide (not the decision), and those missing requirements MUST be escalated
  to the PRD (typically as Q-XX).
- **INV-DM-03 — Boundary obligations:** every introduced boundary (`CON-XX`) MUST list its boundary obligation IDs (`OBL-XX`)
  (without describing algorithms here).
- **INV-DM-04 — ADR-only decisions:** decisions appear only as `(decided-by: ADR-###)`
  with no rationale prose in PRD/Plan/Design Map.
- **INV-DM-05 — Surface invariants, not shapes:** Design Maps MUST define boundary
  behavior as invariants/obligations identified by IDs (what inputs/outputs MUST include
  / guarantee), not as concrete schema definitions, field/key names, data types, or
  example payload shapes.
- **INV-DM-06 — Graph-first IDs:** every node and relationship in a Design Map instance
  MUST be representable as IDs + typed edges/relationships (avoid free-form prose that
  cannot be attached to an ID).

### Derived requirement classification (Design Map behavior)

- **DR-1 (Deterministic derived requirement):** can be derived from PRD + explored
  facts/pattern constraints with no preference tradeoff → stays in Design Map.
- **DR-2 (Decision-derivable):** multiple valid options exist, but one option is
  deterministically implied by existing constraints → record ADR; Design Map links
  `(decided-by: ADR-###)`; no PRD change.
- **DR-3 (Ambiguity / missing intent):** cannot be derived without preference/tradeoff →
  Design Map must surface missing requirement(s); escalate to PRD as `Q-XX` (or
  equivalent).
- **Escalation rule:** Only Needs items that are ambiguities requiring user intent are
  escalated to PRD (as `Q-XX` or equivalent). Deterministic derived requirements MUST
  remain in Design Map and MUST NOT be rewritten into PRD.

## Identifier Vocabulary

PRD IDs (inputs):

- `GOAL-XX`, `INV-XX`, `SET-XX`, `ART-XX`, `RES-XX`, `Q-XX`, `{DOMAIN}-XX`

Derived requirements introduced/resolved inside a Design Map may use domain-specific
prefixes in the `{DOMAIN}-XX` space (e.g., `DM-XX`, `BND-XX`, `ECO-XX`) as long as they
are unique and cross-referenced.

Process IDs (links only):

- `ADR-###` — Architecture Decision Record

Design Map IDs (this document):

- `COM-XX` — component (implementation unit)
- `SUR-XX` — surface (public boundary of a component; 1:1 with COM-XX)
- `CON-XX` — contract (bundle of INV/OBL on a surface; what the surface guarantees/demands)
- `CAP-XX` — capability (component responsibility; derived from GOAL-XX)
- `ALG-XX` — algorithm (implementation logic within a component)
- `OBL-XX` — obligation (boundary-specific constraint; localized INV at a contract)

**Structural model:**

```
COM-XX (component)
├── SUR-XX (surface, 1:1 with COM)
│   └── CON-XX (contracts on surface)
│       ├── INV-XX (guarantees)
│       └── OBL-XX (demands)
├── CAP-XX (capabilities — what this component does)
├── ALG-XX (algorithms — how it does it)
└── INV-XX (component invariants — including state storage requirements)
```

**Key relationships:**

- Each COM has exactly one SUR (its public boundary)
- SUR is a package of CON contracts
- CON bundles INV (what it guarantees) and OBL (what it demands)
- CAP derives from GOAL (GOAL → CAP decomposition)
- OBL is a localized INV at a boundary
- ALGs communicate through surfaces (not directly with other ALGs)

## Deterministic Derivation (Minimum Required Invariants)

For deterministic derivation from a Design Map instance:

- Each `COM-XX` must specify:
  - chosen **pattern** (name/ID) and its required contract types;
  - optional composition (`Composed-of: (COM-*, ...)`) for purely architectural
    components;
  - its capabilities (`CAP-*`) — what this component is responsible for;
  - its surface (`SUR-XX`) — 1:1 with the component;
  - its algorithms (`ALG-*`) — implementation logic;
  - its invariants (`INV-*`) — component guarantees, including state storage requirements (e.g., INV-STORES-FILE-REGISTRY).
- Each `SUR-XX` must specify:
  - owner component (`COM-XX`);
  - its contracts (`CON-*`) — what this surface exposes.
- Each `CON-XX` must specify:
  - owning surface (`SUR-XX`);
  - interaction type (request/response, pub/sub, batch, stream, filesystem, etc.);
  - guarantees (`INV-*`) — what invariants this contract promises;
  - demands (`OBL-*`) — what obligations callers must satisfy.
- Each `CAP-XX` must specify:
  - owning component (`COM-XX`);
  - derived from (`GOAL-*`) — which PRD goals this capability fulfills.
- Each `ALG-XX` must specify:
  - owning component (`COM-XX`);
  - guarantees (`INV-*`) — what invariants this algorithm promises;
  - we detect violations when ALG guarantees ≠ CON guarantees.

## Minimal Node Templates

Needs: IDs of unresolved inputs required to complete deterministic derivation of this
node without making an implicit decision. Needs items can be:

- Derived requirements resolved inside Design Map, or
- Open questions / missing intent that must be escalated to PRD.

Cross-references: optional typed relations. Relation labels are extensible; include only
those relevant to the node.

### Component Template

```markdown
## Component: COM-__

Composed-of (optional): (COM-__, COM-__)
Pattern: {pattern-name-or-id}
Implements: (GOAL-__, {DOMAIN}-__)
Cross-references (optional): (requires: INV-__; uses: RES-__; satisfies: SET-__;
  impacts: ART-__; decided-by: ADR-###)
Needs: ({DOMAIN}-__, Q-__)

### Capabilities

- CAP-__: {capability description}
  Derived-from: (GOAL-__)

### Surface: SUR-__

Contracts: (CON-__, CON-__)

### Algorithms

- ALG-__: {algorithm name}
  Guarantees: (INV-__)

### Component Invariants

- INV-__: {component invariant, e.g., state storage requirements}
  Example: INV-STORES-FILE-REGISTRY — Component maintains a file registry with {properties}
```

### Surface Template

```markdown
## Surface: SUR-__

Owner: (COM-__)
Contracts: (CON-__, CON-__)
```

### Capability Template

```markdown
## Capability: CAP-__

Owner: (COM-__)
Derived-from: (GOAL-__)
Description: {what this component is responsible for}
```

### Contract Template

```markdown
## Contract: CON-__

Surface: (SUR-__)
Pattern: {pattern-name-or-id}
Interaction: {request-response|pub-sub|batch|stream|filesystem|...}
Cross-references (optional): (requires: INV-__; uses: RES-__; satisfies: SET-__;
  decided-by: ADR-###)
Needs: ({DOMAIN}-__, Q-__)

### Guarantees (what this contract promises)

- INV-__ — {invariant this contract guarantees}

### Demands (what callers must satisfy)

- OBL-__ — {obligation callers must fulfill}
  Cross-references: (requires: INV-__; satisfies: SET-__)
```

**Note:** Contracts are one-sided (owned by a surface). Communication between components
happens when ALGs in one COM interact through their SUR's CONs with another COM's SUR.

### Component Invariant Template

```markdown
## Component Invariant: INV-__

Owner: (COM-__)
Type: {state-storage|consistency|performance|security|...}
Cross-references (optional): (requires: INV-__; uses: RES-__; satisfies: SET-__;
  decided-by: ADR-###)
Needs: ({DOMAIN}-__, Q-__)

### Description

{What this invariant guarantees about the component}

Examples:
- INV-STORES-FILE-REGISTRY — Component maintains a persistent file registry storing {properties}
- INV-CACHES-PARSED-RESULTS — Component caches parsed results in memory with {eviction policy}
- INV-QUEUES-PENDING-TASKS — Component maintains a queue of pending tasks with {ordering guarantees}
```

**Note:** State storage invariants describe what state a component maintains and its properties.
Access to state is always through the component's surface contracts, not directly.

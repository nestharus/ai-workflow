# Components (Algorithms) — Structure

Component packages are where **algorithms** live. A component package groups:
- `ALG-XX` algorithms (Mermaid flowcharts + cross-references back to PRD IDs)
- `CON-XX` surfaces (contracts/boundaries) expressed as input/output invariants (not schemas)
- optional internal artifacts (`IAR-XX`) used or owned by the component

This module defines the standard structure for component packages. It intentionally specifies **invariants on inputs/outputs** (what they MUST include / guarantee), not concrete schemas or strict data “shapes”.

## Invariants

* **INV-COM-01 — PRD traceability:** every `ALG-XX` and `CON-XX` section MUST cite PRD IDs via `Cross-references:` or `Implements:`.
* **INV-COM-02 — Surfaces are invariant contracts:** surfaces MUST be documented as input/output invariants per `.tasks/processes/design map structure.md`.
* **INV-COM-03 — Start with one component:** begin with a single root component package that contains all algorithms; split only when the decomposition is clear.
* **INV-COM-04 — No schema embedding:** do not embed schema definitions inside component packages; express “shape” requirements as invariant IDs and reference them.

## Root Component Package: `architecture.md`

The root component package is the starting point:
- Contains **all** `ALG-XX` algorithms initially
- Defines the component’s surfaces (`CON-XX`) and their input/output invariants
- Acts as the index when additional component packages are created

When splitting into multiple components:
- Create new component packages as `com-XX-<kebab-name>.md`
- Move the relevant `ALG-XX` sections into the new package
- Keep `architecture.md` as the root index + cross-component invariants + system diagram

## Templates

### Template: Root component package (`architecture.md`)

````markdown
# Component: Architecture (root)

Sources: {links to PRD, Design Map, ADRs}

## Component and surface map (optional until split)

```mermaid
flowchart LR
  %% Components + boundaries; keep internal IAR detail in the Design Map
  A["COM-__"] -->|CON-__| B["COM-__"]
```

## Surfaces (CON-XX)

### Contract: CON-__

Between: (COM-__, COM-__)
For: (ART-__/IAR-__)
Interaction: {request-response|pub-sub|batch|stream|filesystem|...}
Cross-references: (requires: INV-__; satisfies: SET-__; decided-by: ADR-###)

Input MUST include:
- {ID} — {required semantic element / operational metadata / gating invariant}

Output MUST include:
- {ID} — {required semantic element / operational metadata / gating invariant}

Boundary obligations:
- OBL-__ — {short obligation description}
  Cross-references: (requires: INV-__; satisfies: SET-__)

## Algorithms (ALG-XX)

### ALG-01: {algorithm name}

```mermaid
flowchart TD
  %% Cross-references: (requires: RULE-01, INV-02)
  A["Start"] --> B{"Decision?"}
  B -->|Yes| C["Action"]
  B -->|No| D["Other action"]
```
````

### Template: Split component package (`com-XX-*.md`)

````markdown
# Component: COM-__ — {component name}

Sources: {links}

## Surfaces (CON-XX)

### Contract: CON-__
... (same surface fields/invariants as above)

## Algorithms (ALG-XX)

### ALG-__: {algorithm name}
... (Mermaid flowchart; cite PRD IDs in Cross-references)
````

## Reference Example (splitting)

For a concrete example of a root `architecture.md` plus split component package(s), see:
- `.tasks/plans/parallel linter/lint dispatcher/architecture.md`
- `.tasks/plans/parallel linter/lint dispatcher/com-02-run-linters-orchestrator.md`


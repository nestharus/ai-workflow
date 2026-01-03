# State Holder: IAR-04 — File Registry

Sources: [design-map.md](../design-map.md) | [requirements.md](../requirements.md) | [design map structure.md](../../../../processes/design%20map%20structure.md)

Pattern: state-object
Kind: internal-api
Owner: (COM-02)
Implements: (PROC-02)
Cross-references: (requires: INV-01, INV-03, INV-04; satisfies: GOAL-02)

## State Invariants (IDs only; no schema fields/types)

- FR-01 — Current file list (repo-relative, deterministic order)
  Cross-references: (requires: INV-02)
- FR-02 — Fileset cache keyed by linter instance identity
  Cross-references: (requires: INV-01)
- FR-03 — Existence-only pruning support (no new git queries / no fileset recompute)
  Cross-references: (requires: INV-03)
- FR-04 — Drop-instances support after preflight
  Cross-references: (requires: EXEC-03)
- FR-05 — Phase-boundary mutation rule (no mutation while tasks are in flight)
  Cross-references: (requires: PROC-08)

## Access via contracts

- CON-03: read/write (fileset cache ownership boundary)
  Cross-references: (derived-from: IAR-04; requires: INV-01)
- CON-05: read/write (existence-only pruning + chunk re-evaluation boundary)
  Cross-references: (derived-from: IAR-04; requires: INV-03, PROC-08)

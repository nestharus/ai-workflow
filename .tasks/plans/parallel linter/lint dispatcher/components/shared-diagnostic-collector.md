# State Holder: IAR-07 — Output Meta (Diagnostic Collector)

Sources: [design-map.md](../design-map.md) | [requirements.md](../requirements.md) | [design map structure.md](../../../../processes/design%20map%20structure.md)

Pattern: state-object
Kind: internal-api
Owner: (COM-07)
Cross-references: (requires: OUT-01; satisfies: OUT-05)

## State Invariants (IDs only; no schema fields/types)

- OM-01 — Warning accumulation for non-fatal issues
  Cross-references: (requires: OUT-01)
- OM-02 — Error accumulation for fatal issues
  Cross-references: (requires: OUT-05)

## Usage Rules (IDs only; no algorithms)

- OM-03 — Orchestrator-level warnings/errors are recorded here (not printed ad-hoc)
  Cross-references: (requires: OUT-01)
- OM-04 — Domains contribute warnings/errors via merge semantics; OutputDomain is the sole renderer/exit-code owner
  Cross-references: (requires: OUT-01, OUT-05)
- OM-05 — Main-thread confinement for accumulation; concurrent work returns diagnostics in chunk/phase results
  Cross-references: (requires: PROC-11)

## Access via contracts

- CON-06: write/read
  Cross-references: (derived-from: IAR-07)

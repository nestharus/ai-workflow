# Component: COM-11 — LintWorkflow

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md)

## Capabilities

- CAP-11 — Lint run orchestration and diagnostics ingestion
  Derived-from: (GOAL-02, GOAL-03, GOAL-04)

## Surface: SUR-11

Contracts: (CON-05, CON-12, CON-13)

## Contracts (CON-XX)

### Contract: CON-05

Surface: (SUR-11)
Interaction: request-response
Guarantees: (INV-02, INV-06)
Demands: (OBL-05)

Pattern: in-process call
Between: (COM-14, COM-11)
For: (ART-02, IAR-01, IAR-02, IAR-05)
Implements: (ALG-11, INV-02, PROC-04, PROC-05, GOAL-04)
Cross-references: (requires: INV-02, PROC-04, PROC-05; satisfies: GOAL-04)
Needs: ()

Input MUST include (IDs only; no schema fields/types):

- CTX-52 — Change set (targets changed + change classification)
- CTX-53 — Candidate stalled file set (for selective re-linting)
- CTX-03 — Locked targets set
- CTX-05 — Unlintable targets set

Output MUST include (IDs only; no schema fields/types):

- CTX-54 — Updated diagnostics ingestion
- CTX-55 — Updated passed-cache and dirty-target state
- CTX-56 — Updated linter staleness state

Boundary obligations:

- OBL-05 — Preserve locked/unlintable diagnostics and enforce staleness transitions
  Cross-references: (requires: INV-02, PROC-04, PROC-05; satisfies: GOAL-04)

### Contract: CON-12

Surface: (SUR-11)
Interaction: request-response
Guarantees: (INV-02)
Demands: (OBL-12)

Pattern: in-process call
Between: (COM-12, COM-11)
For: (ART-02, IAR-01, IAR-02, IAR-05)
Implements: (ALG-11, GOAL-03)
Cross-references: (satisfies: GOAL-03)
Needs: ()

Input MUST include (IDs only; no schema fields/types):

- CTX-52 — Change set (investigator-applied changes)
- CTX-03 — Locked targets set
- CTX-05 — Unlintable targets set

Output MUST include (IDs only; no schema fields/types):

- CTX-54 — Updated diagnostics ingestion
- CTX-55 — Updated passed-cache and dirty-target state

Boundary obligations:

- OBL-12 — Post-investigation lint refresh is conservative and deterministic
  Cross-references: (satisfies: GOAL-03)

### Contract: CON-13

Surface: (SUR-11)
Interaction: request-response
Guarantees: (INV-02)
Demands: (OBL-13)

Pattern: in-process call
Between: (COM-13, COM-11)
For: (ART-02, IAR-01, IAR-02, IAR-05)
Implements: (ALG-11, PROC-06)
Cross-references: (requires: PROC-06; satisfies: GOAL-02)
Needs: ()

Input MUST include (IDs only; no schema fields/types):

- CTX-52 — Change set (external-change classification)
- CTX-03 — Locked targets set
- CTX-05 — Unlintable targets set

Output MUST include (IDs only; no schema fields/types):

- CTX-54 — Updated diagnostics ingestion
- CTX-55 — Updated passed-cache and dirty-target state

Boundary obligations:

- OBL-13 — External-change-triggered lint refresh is conservative
  Cross-references: (requires: PROC-06; satisfies: GOAL-02)

## Algorithms (ALG-XX)

### ALG-11: Run linters and ingest diagnostics (post-change and refresh-only)

Owner: (COM-11)
Guarantees: (INV-02, INV-06)
Cross-references: (requires: INV-02, PROC-04, PROC-05; satisfies: GOAL-04)

- Dirty targets are not actionable until their diagnostics refresh has been ingested and the dirty mark cleared.

```mermaid
flowchart TD
  %% Cross-references: (requires: INV-02, PROC-04, PROC-05)
  L0["Run post-change lint tick"] --> L1{Project-level change?}
  L1 -->|Yes| L2["Clear passed-cache globally"]
  L1 -->|No| L3["Clear passed-cache for changed file targets"]

  L2 --> L3B["Mark changed targets dirty (awaiting refreshed diagnostics)"]
  L3 --> L3B
  L3B --> L4["For each configured linter"]

  L4 --> L5["Determine linter scope (project-level vs file-level)"]
  L5 --> L6{Project-level?}

  %% Project-level linters
  L6 -->|Yes| P0["Compute blockers (e.g., locked targets)"]
  P0 --> P1{Blockers empty OR linter supports excluding blockers?}
  P1 -->|No| P2["Mark linter stale (blocked-by = blockers)"] --> L4

  P1 -->|Yes| P3["Run project-level linter (exclude blockers if supported)"]
  P3 --> P4{Run succeeded?}
  P4 -->|No| P5["Record linter run failure (excluded until recovered)"] --> L4

  P4 -->|Yes| P6["Ingest diagnostics (preserve locked ∪ unlintable)"]
  P6 --> P7["Record linter run success / clear staleness"]
  P7 --> P8["Update passed-cache for files that now pass"]
  P8 --> L4

  %% File-level linters
  L6 -->|No| F0{Project-level change?}
  F0 -->|Yes| F1["Select files to check: whole repo (minus locked/unlintable/project-sentinel)"]
  F0 -->|No| F2["Select files to check: changed ∪ candidate-stalled (minus locked/unlintable/project-sentinel)"]

  F1 --> F3{files_to_check empty?}
  F2 --> F3
  F3 -->|Yes| F4["Skip this linter (no updates)"] --> L4

  F3 -->|No| F5["Run file-level linter once on files_to_check"]
  F5 --> F6{Run succeeded?}
  F6 -->|No| F7["Record linter run failure (excluded until recovered)"] --> L4

  F6 -->|Yes| F8["Ingest diagnostics for files_to_check (preserve locked ∪ unlintable)"]
  F8 --> F9["Record linter run success / clear staleness"]
  F9 --> F10["Update passed-cache for files that now pass"]
  F10 --> L4
```

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-04)
  R0["Run refresh-only tick"] --> R1["Prepare refresh-only (validate blockers for pending refresh)"]
  R1 --> R2{Any linter safely pending refresh?}
  R2 -->|No| R3["Skip refresh-only tick (nothing safe)"]
  R2 -->|Yes| R4["Run post-change lint tick with an empty change set tagged refresh-only"]
```

# Synthesized Feedback: PRD Structure, Design Map, Plan, and Decision Records

Inputs:
- `prd structure.md`
- `plan.md`
- `prd feedback 1.md`
- `prd feedback 1 mistakes.md`
- `prd feedback 2.md`

## 0) Net conclusion on “3 docs vs 4 docs”

You now have **four distinct concerns** that should not cohabitate:

1. **PRD (timeless “what”)** — goals, invariants, rules, metrics, logical algorithms.
2. **Design Map / Technical Spec (solution topology “how it is structured”)** — components, internal boundaries, contracts, derived/gap algorithms created by boundaries.
3. **Execution Plan (work ordering “how we ship it”)** — phases/milestones/tasks, dependencies, sequencing, resourcing.
4. **Decision Records (transparency “why we chose X”)** — ADR-style history and rationale.

Recommended model:
- **3 core documents + an ADR folder** (effectively “4 documents” in practice).
- Keep PRD clean; keep decisions out of the PRD and instead *link to ADRs*.

## 1) Corrections vs the first-pass feedback

This section reconciles Feedback #1 with its mistakes analysis and the second iteration.

### Keep (still valid)
- **Typed cross-references** (labeled relations inside parentheses) for machine parseability and DRY.
- **No-orphan/actionability invariant** to prevent “floating” requirements.
- **Explicit `Refs:` fields everywhere** in non-PRD docs to prevent a parallel requirements universe.

### Replace / revise
- **CHO-XX “Choices” inside PRD:** rejected. Use ADRs instead; PRD stays timeless.
- **SET-XX as contract-format membership (“must contain Preconditions section”):** rejected. SET-XX is for *attribute/constraint grouping*, not meta-formatting.
- **SUR-XX in the First PRD as broad “surfaces”:** adopt, but constrain:
    - external, requirement-level artifacts/boundaries may live in PRD;
    - internal artifacts/boundaries belong in the Design Map (they’re architecture choices/discoveries).
- **Blocks/protocols/contracts inside `plan.md`:** those are Design Map material, not Execution Plan material.

## 2) Update `prd structure.md` (rules for PRDs)

### 2.1 Keep “No Prose” strict (do not expand prose allowances)
- Retain your existing constraint that PRDs avoid narrative paragraphs.
- If you keep a prose exception at all, keep it limited to **Problem Statement** only.

### 2.2 Add/standardize typed references (machine-parseable)
In `prd structure.md`, replace “free-form parentheses cross-references” with **labeled relations**.

Example grammar (pick one delimiter style and keep it consistent):
```markdown
Cross-references: (requires: INV-01; uses: RES-03; satisfies: SET-02; validated-by: MET-01)
```

Suggested initial relation vocabulary (extend only when needed):
- `requires:` hard dependency
- `uses:` resource/tooling dependency
- `satisfies:` compliance/constraint satisfaction (often a SET)
- `validated-by:` metric or test artifact
- `derived-from:` when a rule is a decomposition of another rule/goal
- `impacts:` when something non-required is affected (keep rare)
- `decided-by:` ADR link (no prose, just an ID)

### 2.3 Introduce constraint grouping with `SET-XX` (but not meta-formatting)
Add `SET-XX` to your identifier conventions as **Constraint Sets**.

**Definition:** a named bundle of constraints/invariants/rules that are commonly applied together.

Template:
```markdown
* **SET-01 — {set name}:** includes (INV-05, SEC-02, RET-01).
  Cross-references: (includes: INV-05, SEC-02, RET-01)
```

Rules:
- SET members should be **actual system constraints** (INV/RULE), not “document must contain a section.”
- SET-XX should be **reused by attachment** (to an artifact/boundary or algorithm), not restated.

### 2.4 Introduce “artifact/boundary” identifiers for external deliverables
You need a stable noun for “the things constraints attach to” without implying an audience.

Adopt one of:
- `ART-XX` — Artifact / Boundary (recommended; avoids UI connotations)
- `SUR-XX` — Surface (acceptable if you enforce “audience-neutral artifact” wording)

Template:
```markdown
* **ART-01 — {artifact/boundary name}:** exists as an external interface/deliverable.
  Cross-references: (satisfies: SET-01; validated-by: MET-03; requires: INV-02)
```

Rules:
- PRD should list **external ART/SUR only** (inputs/outputs that are requirements).
- **Internal** artifacts (queues, tables, internal APIs) live in the Design Map.

### 2.5 Add the no-orphan invariant (actionability)
Add a PRD invariant that forbids unreachable requirements.

Suggested form:
```markdown
### Invariants

* **INV-REF-01 — No orphan requirements:** every non-invariant rule MUST be referenced by at least one of:
  - an `ALG-XX` header, or
  - an external `ART-XX` requirement, or
  - a `MET-XX` success metric.
```

This ensures “constraints don’t get dropped downstream.”

## 3) Split `plan.md` into two documents (Design Map vs Execution Plan)

Your current `plan.md` contains building blocks, protocols, contracts, tickets. That content is **design topology**.

### 3.1 New document: Design Map / Technical Spec (the “Second PRD”)
Create a new document (name options):
- `design map.md`
- `decomposition spec.md`
- `tech spec.md`
- `second prd.md`

Purpose:
- Define **components** and **internal artifacts/boundaries**
- Map PRD logic/algorithms onto structure
- Make explicit the **gap-filling algorithms** created by boundaries

Minimal node template (audience-neutral):
```markdown
## Component: COM-{ID}

Implements: (ALG-__, RULE-__, GOAL-__)
Consumes: (ART-__/SUR-__)
Produces: (ART-__/SUR-__)
Uses: (RES-__)
Satisfies: (SET-__)

### Contracts
- CON-{N}: for {ART/SUR} (requires: INV-__; satisfies: SET-__)

### Derived algorithms (from chopped PRD logic)
- ALG-COM-{N}: {read/process/write slice} (derived-from: ALG-__)

### Gap-filling algorithms (exist only because boundary exists)
- ALG-COM-{M}: retry/backoff
- ALG-COM-{K}: serialization/framing
- ALG-COM-{L}: authn/authz
- ALG-COM-{P}: dedup/idempotency
```

Design Map invariants (recommended):
- Every COM/CON/ART-internal item must cite PRD IDs via `Implements:` or `derived-from:`.
- Every introduced boundary must list the *gap-filling algorithms* it forces.

### 3.2 Revise `plan.md` into an Execution Plan only
Keep `plan.md` for sequencing and work management.

Suggested primitives:
- `PHASE-XX`
- `MILE-XX`
- `TASK-XX`

Template:
```markdown
## PHASE-01 — {name}
Goal: (GOAL-__)
Scope: (ALG-__, ART-__, SET-__)
Depends-on: (PHASE-__)

### MILE-01 — {deliverable}
Produces: (ART-__)
Validated-by: (MET-__)
Implements: (COM-__, CON-__)

#### TASK-01 — {task}
Implements: (COM-__, ALG-__)
Satisfies: (INV-__, SET-__)
Validated-by: (MET-__, TEST-__)
Depends-on: (TASK-__)
```

Key rule:
- Plan must **not redefine** requirements; it only references PRD/Design IDs.

## 4) Add Decision Records (ADRs) for transparency (without contaminating the PRD)

Create `adr/` (or `decisions/`) as a folder of decision documents.

ADR template:
```markdown
# ADR-### — {decision title}
Status: {Proposed | Accepted | Superseded | Deprecated}
Date: YYYY-MM-DD

## Context
- Links: (GOAL-__, INV-__, ART-__, COM-__, TASK-__)

## Decision
- {one-line decision}

## Options considered
- Option A — {short}
- Option B — {short}

## Consequences
- Positive:
  - ...
- Negative:
  - ...

## References
- PRD: (INV-__, RULE-__)
- Design Map: (COM-__, CON-__, SUR/ART-__)
- Plan: (PHASE-__, TASK-__)
```

PRD linkage pattern (no prose, just IDs):
- Put ADR links in PRD references, e.g. `(decided-by: ADR-012)` on an INV/RULE/RES when relevant.

## 5) Minimal change path (recommended edits without rewriting everything)

1. **Rename current `plan.md` → `design map structure.md`** (or similar), because its content is design-topology structure.
2. Create a new `plan.md` that is purely **PHASE/MILESTONE/TASK**.
3. Update `prd structure.md`:
    - add typed reference convention
    - add `SET-XX`
    - add `ART-XX` (or constrained `SUR-XX`)
    - add `INV-REF-01` no-orphan invariant
4. Add `adr/ADR-000-template.md` and enforce cross-links from PRD/Design/Plan.

## 6) Practical tests for whether the split is working

- If a paragraph starts with “we chose X because…”, it belongs in an **ADR**.
- If a section defines “components/protocols/contracts/queues/tables”, it belongs in the **Design Map**, not the Plan.
- If a section contains “what order do we do things / dependencies / milestones”, it belongs in the **Plan**.
- If a statement is timeless and must remain true regardless of implementation strategy, it belongs in the **PRD** as GOAL/INV/RULE/MET/ART/SET.

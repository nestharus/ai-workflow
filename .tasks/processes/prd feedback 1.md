## Feedback for `prd structure.md`

### 1) Update the prose rule to allow *exactly one* additional prose enclave: Choices

Right now the document declares the Problem Statement as “the only prose allowed.” That conflicts with your requirement that *choice justifications* are also allowed prose.

**Change:**

* Keep the “No Prose” principle intact.
* Amend the exception list from:

    * “Problem Statement is the only prose allowed”
      to:
    * “Problem Statement + Choice Justifications are the only prose allowed”

**Suggested template addition (new required or strongly recommended section):**

```markdown
## Choices (prose allowed)

### CHO-01 — {short title}
Refs: (GOAL-__, INV-__, RULE-__, ALG-__, SUR-__)
Decision: {one line}
Justification: {prose paragraph; <= 200 words}
Consequences:
- {structured bullets only}
```

Why this fits your intent:

* Preserves “no prose” everywhere else.
* Keeps reasoning auditable without smearing narrative into rules/algorithms.

---

### 2) Add first-class support for “membership constraints” via reusable **constraint sets**

You described the core gap correctly: you’re not trying to define schemas; you’re trying to prevent “constraint categories” from getting dropped downstream by defining **membership requirements** once and reusing them.

Your current format supports atomic rules + cross-references and explicitly supports “expanded sections” for complex rules. You can use that existing mechanism to define reusable membership bundles.

**Change: Introduce a rule prefix for constraint sets**
Add to the identifier conventions table (you already allow domain-specific prefixes):

* `SET-XX` — Constraint Set (membership bundle)
* `SUR-XX` — Surface (see next section)
* `CHO-XX` — Choice (prose-allowed)

**Constraint set rule format (pure membership, no prose):**

```markdown
### QA rules  (or Maintenance rules; anywhere in the Indexed Rule List)

* **SET-01 — Contract constraint membership:** any contract-spec artifact MUST include members (CON-01, CON-02, CON-03, CON-04).
  Cross-references: (members: CON-01, CON-02, CON-03, CON-04)

#### SET-01 (expanded)
* **CON-01 — Preconditions present:** contract includes preconditions section.
* **CON-02 — Postconditions present:** contract includes postconditions section.
* **CON-03 — Invariants present:** contract includes invariants section.
* **CON-04 — Errors present:** contract includes error table with condition/response.
```

This is intentionally “membership only”:

* It is verifiable (“does the artifact contain these member constraint IDs?”).
* It doesn’t prescribe field names, payload formats, or schemas.
* It doesn’t encode “responsibilities” or “where used” (usage is expressed by references elsewhere).

**Important improvement: make cross-references typed**
Right now cross-references are free-form parentheses. For membership constraints, you want machines (and humans) to distinguish “members” from “requires” from “validates” without prose.

**Change: standardize labeled relations inside parentheses**
Example:

* `(members: CON-01, CON-02)`
* `(requires: INV-01)`
* `(validated-by: MET-01)`
* `(produces: SUR-01)`
* `(uses: RES-03)`

This is consistent with “machine parsing for coverage analysis” as a stated goal.

---

### 3) Introduce **Surface entities** as requirements (not UI, not contracts-as-prose)

You’re missing a stable “thing” that algorithms produce and other packages/users consume. Without that, outputs drift into implicit assumptions, and constraints become unanchored.

You do *not* need a special UI section, and you do *not* need to define consumers. The fix is to add a **Surface** ID type and treat surfaces as requirements.

**Change: represent surfaces as rules (usually under Output rules)**
This uses existing category structure (“Output rules” already exists in your standard taxonomy).

**Surface rule format (structured; no prose):**

```markdown
### Output rules

* **SUR-01 — {surface name}:** surface exists.
  Cross-references: (produced-by: ALG-01, constrained-by: SET-01, SET-02)
```

Key point: surfaces are not “UI requirements” or “contract requirements.”
They’re a generic requirement object that can represent:

* a contract boundary,
* a UI screen,
* a file artifact,
* a machine-facing API,
* a stream/event topic,
* anything else that is externally consumable.

**How surfaces keep constraints actionable**

* Constraints become actionable when referenced by a surface (or algorithm).
* Algorithms become actionable when they (directly or indirectly) produce surfaces.
* You don’t need to say “who consumes it” to make it actionable.

---

### 4) Tighten the “actionability/coverage” rule so constraints don’t orphan

You already emphasize traceability and machine parsing, but the structure lacks an explicit requirement that rules must be reachable from algorithms/surfaces/metrics.

**Change: add an invariant for reference-graph coverage**
Put it in Invariants (because it’s a global constitutional rule).

Example invariant:

```markdown
### Invariants

* **INV-REF-01 — No orphan requirements:** every non-invariant rule MUST be referenced by at least one of:
  (a) an ALG-XX flowchart header, (b) a SUR-XX rule, or (c) a MET-XX row.
```

This directly addresses your “constraints get left out later phases” concern by making “unreferenced constraints” invalid by definition.

---

### 5) Update algorithm flowchart conventions to declare surfaces without introducing prose

Your algorithm section already requires `ALG-XX` and references rules at the top of the diagram.

**Change: standardize an algorithm header comment that includes surfaces**
Example:

```mermaid
flowchart TD
  %% produces: SUR-01
  %% uses: (INV-01, EXEC-02, SET-01)
  ...
```

This keeps “where it’s used” outside constraints, and instead expresses usage by reference at the algorithm level (your stated preference).

Also: in component diagrams, include surfaces as nodes and annotate with rule IDs (your existing guidance explicitly encourages annotation).

---

## Feedback for `plan.md`

Your plan document is already the right place to define *structure* of blocks/protocols/contracts/tickets. The improvements below align it with the PRD upgrades: surfaces, membership constraint sets, typed references, and “no schema too early.”

### 1) Make Plan entities reference PRD IDs to preserve DRY and prevent “recreated contracts”

Right now `plan.md` invites duplicative descriptions (`{what this block can do}`, `{how the capability is realized}`). That’s where requirements drift.

**Change: add explicit `Refs:` fields everywhere**

* Block → refs GOAL/INV/SUR
* Capability → refs RULE/GOAL/SUR
* Algorithm → refs PRD ALG-XX and any RULE IDs

Suggested block template adjustment:

```markdown
## Block: {BLOCK-ID}

Refs: (GOAL-__, INV-__, SUR-__)
...
### Capabilities
| ID | Refs | Description |
|----|------|-------------|
| CAP-{BLOCK}-{N} | (GOAL-__, SUR-__) | {short phrase} |

### Algorithms
| ID | Refs | Implements | Description |
|----|------|------------|-------------|
| ALG-{BLOCK}-{N} | (ALG-__, RULE-__, SUR-__) | CAP-{BLOCK}-{N} | {short phrase} |
```

This makes the plan a *projection of PRD IDs*, not a parallel requirements universe.

---

### 2) Remove “payload is a data schema” from Protocols; replace with “payload requirements”

Your Protocol schema currently hardcodes `Payload = {data schema}`. That contradicts your “PRD dictates membership, later docs dictate structure” direction.

**Change:**
Replace payload column with references:

```markdown
### Messages
| ID | From | To | Payload Refs |
|----|------|----|--------------|
| MSG-{PROTOCOL}-{N} | {BLOCK-A} | {BLOCK-B} | (SUR-__, SET-__, RULE-__) |
```

This keeps plan-level protocols schema-agnostic while still being complete.

---

### 3) Update Contract schema to explicitly “include constraint sets”

The current Contract schema already has the right *sections* (Preconditions/Postconditions/Invariants/Errors). What it’s missing is the mechanism to ensure later artifacts don’t omit categories (membership).

**Change: add a required header field**

```markdown
## Contract: {CONTRACT-ID}

Refs: (SUR-__, SET-01, CHO-__)
Between: ...
Via: ...

Includes constraint sets: (SET-01, SET-02)
```

Then the sections themselves should *reference* member constraints (or define them inline as atomic constraints), but do not require prose.

This makes contracts “complete by construction” without inventing extra PRD sections.

---

### 4) Ticket schema: acceptance criteria should be “ID-complete,” not narrative

Current acceptance criteria are generic (“Capability functional”, “Tests pass”).

**Change: require acceptance criteria to cite PRD verification artifacts**
Example:

```markdown
## Acceptance Criteria
- [ ] Satisfies: (INV-REF-01, SET-01)
- [ ] Produces: (SUR-01)
- [ ] Validated-by: (MET-01, MET-02)
- [ ] Choice recorded (if applicable): (CHO-__)
```

This aligns with your “traceability” goal and supports automated coverage checks.

---

### 5) Add “Choice refs” to plan entities (but keep prose only in PRD Choices section)

Plan shouldn’t contain justifications; it should link to them.

**Change: add `Decision refs: (CHO-__)` fields**

* Block
* Protocol
* Contract
* Ticket

This preserves your “prose is centralized” rule while keeping the execution plan auditable.

---

## Net result (what this fixes)

* **Contract constraints** become reusable membership bundles (`SET-XX`) instead of scattered prose or implicit expectations.
* **Surfaces** become first-class requirements (`SUR-XX`) so outputs/interfaces don’t become “implicit” and lose constraints.
* **Actionability** is enforced by a reference-graph invariant (no orphan rules).
* **Plan** stops recreating requirements by making all major entities reference PRD IDs, and by removing “schema too early” from protocols/contracts.

All of this stays consistent with your existing PRD goals: structured, indexed, cross-referenced, machine-parseable, and anti-duplication.

## 1) What belongs in the PRD vs. what must be kept out

* **A PRD defines the timeless State of the Product (“the What”).**
  It should remain an invariant description of goals, rules, and constraints, not a log of how decisions were made.

* **“Choices” / “Decisions / Justifications” (CHO-XX) do *not* belong in a PRD.**
  Putting CHO-XX into a PRD is a category error because it injects *history* (“how we got here”) and turns the PRD into meeting minutes or an approval forum.

* **Where decisions go instead:**

    * If the “decision” is effectively a **scope constraint** (“We will not support PDF”), it becomes a **product Invariant (INV-XX)**.
    * If the “decision” is a **technical/implementation choice** (“Use Postgres”), it belongs in an **Architecture Decision Record (ADR)** and/or a design/architecture document (not the PRD).

* **Prose is rejected for justification inside the PRD.**
  The conclusion is to preserve strict “No Prose” (except the Problem Statement if you allow it), because justifications in PRDs rot quickly and reintroduce approval/audience dynamics.

## 2) “Surfaces” are required, but must be defined as artifacts/boundaries (not “audience experiences”)

* The conversation concludes you **should adopt SUR-XX**, because you need a stable way to name the **things that exist as boundaries/artifacts** so constraints can attach to something testable.

* **The key correction:** Surfaces must be defined as **boundaries or produced artifacts**, not as UI experiences that imply an audience.

    * Bad (leaks “Audience”): `SUR-01 — Admin Panel` (implicitly defines “Admin” as an audience).
    * Good (audience-neutral artifact/boundary):

        * `SUR-01 — Config API Spec`
        * `SUR-02 — CSV Export File`

* **Renaming to avoid the “Audience” backdoor is endorsed.**
  The adjusted conclusion explicitly accepts SUR-XX but recommends renaming them to something like **ART-XX (Artifacts)** (or similar) to prevent UI/audience implication.

* **Why surfaces/artifacts must exist at all:**
  Constraint Sets and constraints are meaningless “floating” statements unless they attach to a concrete boundary/artifact.
  Example conclusion: a constraint like “Must be encrypted” becomes testable only when attached to a specific named surface/artifact.

## 3) Constraint Sets (SET-XX) are accepted, with a specific “correct” usage

* **SET-XX is accepted** as a DRY mechanism, but with a strict interpretation.

* **Rejected usage:** SET-XX should *not* contain meta-formatting rules like “CON-01 Preconditions present.”
  That’s a rule-about-writing-rules, not a product/system constraint.

* **Accepted usage:** SET-XX is for **attribute grouping** (security, compliance, performance, retention, etc.).
  Canonical example conclusion from the conversation:

    * `SET-01 — PII Compliance: includes (INV-05 Encryption, INV-09 Audit Log, RET-02 30-day Retention)`
    * Then a surface/artifact can declare:

        * `SUR-05 — User Export (Satisfies: SET-01)`

## 4) The Plan document is not a design spec

* The conversation concludes the other AI’s “plan.md” interpretation was wrong for your philosophy.

* **Plan (Execution Plan) should contain only planning constructs:**

    * `PHASE`, `MILESTONE`, `TASK`
    * sequencing, resources, dependencies

* **Design/Architecture content should not be moved into the Plan.**
  Blocks/capabilities/protocols in the Plan risks turning it into a secondary PRD.

* **Correct separation of concerns concluded:**

    * **PRD:** `GOAL`, `INV`, `RULE` (timeless requirements/constraints)
    * **Design / Tech Spec:** `BLOCK`, `COMPONENT` (mapping PRD logic into structure)
    * **Plan:** `PHASE`, `MILESTONE`, `TASK` (execution ordering)

## 5) Two-document model is required: “First PRD” vs. “Second PRD” (system design map)

### 5.1 What each document owns

* **First PRD (Problem Space):**
  Owns the clean, abstract **logical flow/algorithms** and the timeless constraints.

* **Second PRD (Solution Space)** (also described as System Design / Technical Specification / Decomposition Spec):
  Owns the **structural topology**: components, boundaries, contracts, and the internal artifacts/surfaces discovered during implementation design.

### 5.2 Surfaces “cut” algorithms and force new work to exist

* A core conclusion: **Adding structure adds surfaces**; surfaces require contracts; and surfaces fracture the logical algorithm.

* When a surface/boundary is introduced between logical steps, the single PRD algorithm becomes:

    * **Producer-side algorithm:** compute then *write to surface*
    * **Consumer-side algorithm:** *read from surface* then continue
    * **Gap-filling algorithms (new logic created by the surface):** serialization, transport, auth, retries, error handling, deduplication, pooling, etc.

* **Key implication concluded:**
  Introducing a queue/database/API/file boundary introduces “space you created,” and you must explicitly “fill that space” with additional algorithms and behavior that do not exist in the original problem statement.

### 5.3 What the “Second PRD” contains structurally (a concluded template)

The conversation converges on a node-based structure, where each node is a component bounded by surfaces, with explicit links back to PRD logic:

**Decomposition Node template (conclusion):**

* **Component:** `{COM-ID}` (e.g., Ingestion Worker)
  **Implements:** part of `ALG-XX` from PRD
* **Surfaces (Boundaries):**

    * Input surface(s): consumes
    * Output surface(s): produces
* **Contracts:** schema/spec for each surface + links to applicable invariants
* **Derived Algorithms:** the “chopped” pieces of original PRD logic (read → process → write)
* **Gap-Filling Algorithms:** new algorithms required only because the boundary exists (retry, dedup, pooling, etc.)

### 5.4 External vs. internal surfaces allocation

* **Conclusion reached:**

    * **First PRD** contains **external surfaces** only (e.g., user inputs, final outputs) because those are requirements.
    * **Second PRD** contains **internal surfaces** (queues, IPC, tables, internal APIs) because those are architecture choices/discoveries.

## 6) The architecture-generation method evolved, and the final answer favors bottom-up composition over top-down decomposition

The conversation explicitly shifts from “recursive decomposition” to a more accurate approach.

### 6.1 Top-down decomposition is judged inferior for this PRD style

Final conclusions about top-down:

* Relies heavily on heuristics (“guess patterns first”).
* Subjective and fragile.
* Tends to create “God Components” grouped by semantic convenience.
* Risks orphaning requirements that don’t fit the chosen high-level pattern.

### 6.2 Bottom-up composition is concluded to be both more accurate and produces a better solution

**Accuracy conclusions:**

* **Derivation vs prediction:** Bottom-up *derives* boundaries; top-down *predicts* them.
* **Coverage guarantee:** Starting from leaves of the dependency graph ensures 100% requirements coverage; you can’t proceed until the lower-layer rules are encapsulated.
* **PRD as AST:** The PRD acts like an abstract syntax tree; design becomes a deterministic compilation-like process.

**Quality conclusions:**

* **Coupling control:** Bottom-up groups by functional dependency, producing cohesive, loosely coupled components.
* **Emergent architecture:** Patterns that appear are native to the domain, not imposed.
* **Refactoring safety:** Dependency-explicit refactoring is safer than untangling heuristic monoliths.

### 6.3 The replacement “mechanical” algorithm concluded: Dependency Composition (Linker/Loader model)

The conversation lands on a concrete mechanical procedure:

1. **Topologically sort the PRD dependency graph.**
2. **Layering:**

    * Layer 0: invariants/resources/external contracts
    * Layer 1: atomic rules referencing only Layer 0
3. **Synthesize tiny components:**

    * Group Layer 1 rules that share the same state/resources → Units (Unit A, Unit B)
4. **Compose upward by dependency injection:**

    * For Layer 2 rules referencing Layer 1: determine which units are required
    * Decide co-location vs boundary:

        * If they can live in the same memory space → compose into a block
        * If not → **create a surface** (this is where surfaces are *derived*, not guessed)
5. **Refactor/Elevate:**

    * Treat composed blocks as new atomic units
    * Repeat for Layer 3, Layer 4, etc.

## 7) Emergent Architecture is the final organizing principle: patterns are discovered, then formalized and strengthened

The conversation concludes a stable workflow:

1. **Assembly:** build tiny components from PRD rules mechanically
2. **Recognition:** observe clusters and behaviors that form
3. **Formalization:** map to known design patterns and adopt precise vocabulary (buffer, backpressure, multiplexer, channels, framing, etc.)
4. **Fortification (Gap Analysis):** use the pattern’s “missing pieces checklist” to discover what’s absent (e.g., DLQ, fairness, rate limiting), which can reveal real requirement gaps

Key conclusion: **Design patterns become diagnostic tools applied after emergence**, not templates chosen upfront.

## 8) The “Second PRD” is ultimately concluded to be a map, not a blueprint

Final framing:

* The “Second PRD” (design/decomposition spec) is not drawn fully in advance.
* It is iteratively produced as you explore and assemble the system.
* It naturally evolves in layers:

    * Layer 1 map: atomic components
    * Layer 2 map: small clusters/modules
    * Layer 3 map: recognized patterns (the architecture)

This preserves the core philosophy:

* PRD stays timeless and free of approvals/justifications/audience leakage.
* The design map grows mechanically from the PRD graph, with surfaces and gap-algorithms made explicit and traceable.

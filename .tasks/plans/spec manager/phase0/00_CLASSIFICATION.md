# Phase 0: Three-Way Classification

## The Problem

Phase 0 classifies each piece of input into one of three PDD categories:

1. **Analysis docs** — decisions made, options explored, tradeoff reasoning
2. **Constraints / Invariants** — guiding principles, priorities, rules
   that must always hold regardless of implementation
3. **Details** — algorithms, shapes, and stores (pseudocode in code files)

The classification seems simple until you encounter real specs.

---

## The Invariant Trap

Real specs write algorithmic implementation details using constraint
language. The word "MUST" does not make something an invariant.

**Invariants are WHY.** They express guiding principles — things that
must always hold regardless of how you implement the system. They don't
prescribe specific files, locks, fields, or sequences. They tell you
why durability matters, why correctness is required, why something is a
priority.

**Algorithms are HOW.** They describe steps, procedures, sequences —
even when written as "MUST do X, then MUST do Y." The "MUST" language
makes them sound like constraints, but they're implementation steps.

**Shapes are WHAT.** They describe data structures, field definitions,
schemas — even when written as "field X MUST be present when Y."

---

## Examples from a Real Spec

Source: Workflow Engine 3 (78 files, 13,700 lines)

### Looks like a constraint, actually an ALGORITHM:

> "TM MUST perform ticket status transitions under
> `locks/ticket.<ticket_id>.lock`"

This tells you HOW to do a transition safely (acquire this specific
lock). A different implementation might use a database transaction
or compare-and-swap instead of file locks.

**The underlying invariant**: "Concurrent modifications must never
corrupt ticket state."

### Looks like a constraint, actually a SHAPE detail:

> "`blocker_kind` MUST be present when `status == blocked`"

This is a field validation rule — part of the ticket.json schema.
A different implementation might use a different field name or model
this with a separate table.

**The underlying invariant**: "Blocked tickets must always explain
why they're blocked."

### Looks like a constraint, actually an ALGORITHM step:

> "Steps MUST emit `step_start` / `step_stop` events"

This prescribes specific event names at specific times — an
implementation detail. A different system might use different events
or a different evidence mechanism.

**The underlying invariant**: "Every step must produce evidence
sufficient to reconstruct what happened."

### Actually an INVARIANT:

> "Trust > Friction > Performance" (product priority ordering)

This IS a guiding principle. It tells you WHY you might choose a
slower but more durable approach. It survives any reimplementation.

### Actually an INVARIANT:

> "No silent termination — no fixed max iteration caps as
> termination criteria"

This IS a guiding principle. It constrains ALL algorithms to use
evidence-based stopping, not arbitrary limits. No matter how you
implement the system, this rule applies.

### Actually an INVARIANT:

> "Flat orchestration — root owns all step/agent OS processes"

This IS an architectural constraint. It prevents all algorithms from
spawning grandchild processes, regardless of implementation details.
It constrains the solution space, not a specific implementation.

### Actually ANALYSIS:

> "We chose file-based queues over database-backed queues because
> this is a local-first CLI tool with no daemon requirement."

This explains WHY a decision was made — the tradeoff reasoning.

### Actually ANALYSIS:

> "Patch-stream (jj) is superior for organizing many small steps
> and parallel ticket work. Complexity cost is acceptable because
> users do not interact with the patch graph directly."

This justifies a technology choice with tradeoff reasoning.

---

## The Classification Rule

Ask: **Does this statement survive if you completely change the
implementation?**

- "Trust > Friction > Performance" → Yes. Even with a totally
  different architecture, trust still comes first. → **Invariant**

- "Acquire locks/ticket.<ticket_id>.lock" → No. A different
  implementation might use a database or CAS instead of file locks.
  → **Algorithm detail**

- "`blocker_kind` MUST be present" → No. A different implementation
  might use a different field name or a separate table. → **Shape
  detail**

- "We chose X because Y" → This is reasoning, not a rule. →
  **Analysis**

---

## Scale of the Problem

In the Workflow Engine 3 spec (~500+ "MUST" statements):

| Actual category | % of "MUST" statements | Example |
|----------------|----------------------|---------|
| Algorithm steps | ~60% | "MUST acquire lock", "MUST emit event", "MUST write artifact" |
| Shape details | ~30% | "MUST be a ULID", "MUST include field X", "MUST be one of [enum]" |
| Invariants | ~5% | "Trust > Friction > Performance", "No silent termination" |
| Analysis | ~5% | "We chose X because Y" (rarely uses "MUST") |

A naive "MUST = constraint" classifier would put 95% of content in
the wrong category. This is expected to be the COMMON case with real
specs — people write algorithms as rules.

---

## Common Patterns That Fool Naive Classifiers

1. **"MUST" does not mean invariant.** Most "MUST" sentences are
   algorithms or shapes.

2. **"normative" does not mean invariant.** Normative sections contain
   ALL three categories interleaved.

3. **"non-negotiable" does not mean invariant.** Sometimes it means
   "this algorithm must be followed exactly" — still an algorithm.

4. **JSON schema field rules.** Written as rules ("MUST be present
   when X") but they're shape definitions with validation logic.

5. **State machine transitions.** Written as rules ("MUST transition
   via these paths only") but they're algorithms defining a procedure.

6. **Lock ordering rules.** Written as rules ("MUST acquire in this
   order") but they're algorithms for concurrency control.

7. **Evidence emission rules.** Written as rules ("MUST emit event X")
   but they're algorithm steps in a logging procedure.

8. **Error handling rules.** Written as rules ("MUST return error with
   actionable guidance") but they're algorithm branches for failure
   cases.

---

## Classifier Guidance

When classifying a fragment, ask these questions in order:

1. **Is it describing a decision that was made and why?**
   → Analysis doc

2. **Is it expressing a priority, principle, or tradeoff that applies
   regardless of implementation?**
   → Constraint / Invariant

3. **Is it defining a data structure, schema, field, or type?**
   → Shape (Detail)

4. **Is it describing a procedure, sequence of steps, or "what to do
   when"?**
   → Algorithm (Detail)

5. **Is it describing a data store, persistence mechanism, or storage
   layout?**
   → Store (Detail)

When in doubt between invariant and algorithm: if you could implement
the same GOAL with a completely different approach, the statement is
describing ONE approach (algorithm), not the goal itself (invariant).

---

## Interleaved Classification

Real specs interleave categories within single sections. A section
titled "Ticket Lifecycle" might contain:

- **Shape**: The 5 states (open, in_progress, blocked, done, abandoned)
  + `blocker_kind` enum
- **Invariant**: "Terminal states MUST NOT transition except via explicit
  reopen" (this constrains ALL implementations)
- **Algorithm**: Concurrency conflict resolution sequence (reload →
  re-evaluate → retry or fail)
- **Analysis**: A Mermaid state diagram (informative, explaining the
  design)
- **Algorithm**: Transition recording requirements (write these specific
  fields)
- **Shape**: Audit log record structure

Phase 0's Surgical Decomposition step must be prepared to split
individual sections across categories. A single paragraph might
contain an invariant sentence followed by an algorithm sentence.

The split should be at the sentence level for normative content.
For informative content, keep blocks together.

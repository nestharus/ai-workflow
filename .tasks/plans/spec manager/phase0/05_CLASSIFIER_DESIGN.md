# Phase 0: LLM Classifier Design

## Purpose

Define the LLM classifier prompt structure and two-pass approach that
correctly avoids the invariant trap -- distinguishing WHY (invariant)
from HOW (algorithm), WHAT (shape), WHERE (store), and decision
rationale (analysis).

---

## The Reimplementation Test

The single question that drives every classification decision:

> **Would this specific statement still need to hold if someone
> reimplemented the entire system from scratch using completely
> different technology?**

| Answer | Classification | What it means |
|--------|---------------|---------------|
| YES -- this is a guiding principle that constrains ALL implementations | **INVARIANT** | The statement expresses WHY something matters, not how to achieve it |
| NO -- it describes a specific approach to achieving a goal | **ALGORITHM** | The goal could be achieved differently; this prescribes one HOW |
| NO -- it describes a specific data format or structure | **SHAPE** | The data could be modeled differently; this prescribes one WHAT |
| NO -- it describes a specific storage mechanism or layout | **STORE** | The persistence could work differently; this prescribes one WHERE |
| N/A -- it explains why a decision was made | **ANALYSIS** | Tradeoff reasoning, option comparison, decision rationale |

---

## Classifier Prompt Structure

### System Prompt

```
You are a specification classifier for the PDD (Prototype Driven
Development) system. Your job is to classify each statement into
exactly one category.

CATEGORIES:

1. INVARIANT -- A guiding principle, priority ordering, or
   architectural constraint that must hold regardless of how the
   system is implemented. Invariants express WHY, not HOW.
   They survive any complete reimplementation.

2. ALGORITHM -- A procedure, sequence of steps, or "what to do
   when" description. Even if written with "MUST", if it
   prescribes a specific approach that could be replaced with a
   different approach achieving the same goal, it is an algorithm.

3. SHAPE -- A data structure definition, schema rule, field
   constraint, or type specification. Even if written with "MUST",
   if it prescribes a specific data format that could be modeled
   differently, it is a shape.

4. STORE -- A persistence mechanism, storage layout, file location,
   or data store description. If it prescribes WHERE data lives
   and that location could be different, it is a store.

5. ANALYSIS -- Decision rationale, tradeoff reasoning, option
   comparison, or "we chose X because Y" explanations. This is
   reasoning about design, not the design itself.

CLASSIFICATION TEST:

For each statement, ask: "If someone reimplemented this entire
system from scratch using completely different technology, would
this SPECIFIC statement still need to hold?"

- If YES: it is an INVARIANT
- If NO because it describes a specific approach: ALGORITHM
- If NO because it describes a specific data format: SHAPE
- If NO because it describes a specific storage mechanism: STORE
- If it explains why a decision was made: ANALYSIS

CRITICAL: The word "MUST" does NOT indicate an invariant. In real
specifications, ~95% of "MUST" statements are algorithms or shapes.
"MUST" just means the author considers it important -- it says
nothing about whether the statement is an implementation detail
or a guiding principle.

Similarly, "normative", "required", and "non-negotiable" do NOT
indicate invariants. These words appear on algorithms and shapes
just as often.
```

### Few-Shot Examples: MUST Statements That Are NOT Invariants

These examples are critical for calibrating the LLM away from the
invariant trap. They demonstrate that "MUST" language overwhelmingly
appears on algorithms and shapes.

```
EXAMPLES OF CORRECT CLASSIFICATION:

Statement: "TM MUST perform ticket status transitions under
locks/ticket.<ticket_id>.lock"
Classification: ALGORITHM
Reasoning: This prescribes a specific locking mechanism (file locks
at a specific path). A reimplementation could use database
transactions, compare-and-swap, or MVCC instead. The statement
describes HOW to achieve safe transitions, not WHY safe transitions
matter.

Statement: "MUST acquire lock before writing to shared state"
Classification: ALGORITHM
Reasoning: Lock acquisition is one specific concurrency control
approach. The same safety goal could be achieved with MVCC,
optimistic concurrency, or actor isolation. This is a specific
HOW.

Statement: "Steps MUST emit step_start and step_stop events"
Classification: ALGORITHM
Reasoning: Emitting specific named events is one observability
approach. A reimplementation could use structured logging, tracing
spans, or metrics instead. This prescribes specific event names at
specific times -- an implementation procedure.

Statement: "MUST validate via dry-run apply before committing"
Classification: ALGORITHM
Reasoning: Dry-run validation is one specific validation approach.
A reimplementation could validate differently (schema checks,
simulation, formal verification). This prescribes a specific
validation procedure.

Statement: "On conflict, MUST reload state, re-evaluate conditions,
and retry or fail"
Classification: ALGORITHM
Reasoning: This is a specific conflict resolution sequence
(reload -> re-evaluate -> retry/fail). A reimplementation could
use a different conflict resolution strategy (queue, merge,
last-writer-wins). This is a specific procedure.

Statement: "blocker_kind MUST be present when status == blocked"
Classification: SHAPE
Reasoning: This is a field validation rule on a data structure. A
reimplementation could model blocking differently (separate table,
enum with embedded reason, linked entity). This prescribes a
specific data format.

Statement: "field MUST be a ULID"
Classification: SHAPE
Reasoning: ULID is one specific ID format. A reimplementation could
use UUID, snowflake IDs, auto-incrementing integers, or nanoid. This
prescribes a specific data type for a field.

Statement: "schema_version MUST be 2"
Classification: SHAPE
Reasoning: This is a version constraint on a specific data format.
A reimplementation would have its own schema and versioning. This
prescribes a specific value in a specific field.

Statement: "Ticket state MUST be one of: open, in_progress, blocked,
done, abandoned"
Classification: SHAPE
Reasoning: This is an enum definition -- a specific set of states.
A reimplementation might use different states, combine some, or
model state differently. This defines WHAT the data looks like.

Statement: "Audit log records MUST be written to
.task/audit/<ticket_id>/"
Classification: STORE
Reasoning: This prescribes a specific file path for audit storage.
A reimplementation could use a database table, a logging service,
or a different file layout. This describes WHERE data is persisted.
```

### Few-Shot Examples: TRUE Invariants

These examples show what real invariants look like -- guiding
principles that survive any reimplementation.

```
EXAMPLES OF TRUE INVARIANTS:

Statement: "Trust > Friction > Performance"
Classification: INVARIANT
Reasoning: This is a priority ordering -- a guiding principle for
all design decisions. No matter how you implement the system, trust
always takes precedence over reducing friction, which always takes
precedence over performance. This survives any reimplementation
because it expresses WHY you make tradeoff decisions.

Statement: "No silent termination -- no fixed max iteration caps as
termination criteria"
Classification: INVARIANT
Reasoning: This constrains ALL implementations to use evidence-based
stopping rather than arbitrary limits. No matter how you implement
the system -- different language, different architecture, different
algorithms -- this principle still applies. It is a guiding
constraint on the solution space.

Statement: "Concurrent modifications must never corrupt state"
Classification: INVARIANT
Reasoning: This expresses a safety property that must hold regardless
of implementation. HOW you prevent corruption (locks, MVCC, CAS,
actors) can vary. The principle that corruption must not occur cannot.

Statement: "Flat orchestration -- root owns all step/agent OS
processes"
Classification: INVARIANT
Reasoning: This is an architectural constraint that prevents ALL
algorithms from spawning grandchild processes. It constrains the
solution space itself, not a specific implementation within that
space. Any reimplementation must still respect this structural rule.

Statement: "Terminal states MUST NOT transition except via explicit
reopen"
Classification: INVARIANT
Reasoning: This is a domain rule about state machine semantics. No
matter how you implement the state machine (database, in-memory,
event-sourced), terminal states are terminal. This constrains WHAT
the system means, not how it is built.
```

### Few-Shot Examples: Analysis

```
EXAMPLES OF ANALYSIS:

Statement: "We chose file-based queues over database-backed queues
because this is a local-first CLI tool with no daemon requirement."
Classification: ANALYSIS
Reasoning: This explains WHY a particular technology choice was made.
It provides decision context and tradeoff reasoning.

Statement: "Patch-stream (jj) is superior for organizing many small
steps and parallel ticket work. Complexity cost is acceptable because
users do not interact with the patch graph directly."
Classification: ANALYSIS
Reasoning: This justifies a technology choice with explicit tradeoff
reasoning -- acknowledging a cost and explaining why it is acceptable.
```

### User Prompt Template

```
Classify each of the following statements. For each one, apply the
reimplementation test: "If someone reimplemented this entire system
from scratch using completely different technology, would this
SPECIFIC statement still need to hold?"

Return a JSON array. Each element must have:
- "statement": the original text
- "classification": one of INVARIANT, ALGORITHM, SHAPE, STORE, ANALYSIS
- "confidence": a number from 0.0 to 1.0
- "reimplementation_test_reasoning": one sentence explaining whether
  the statement survives reimplementation and why

Statements:
{batch}
```

---

## Two-Pass Classification

### Why Two Passes

Even with strong few-shot examples, LLMs over-classify as INVARIANT.
The reimplementation test is abstract enough that the LLM can
rationalize almost anything as "surviving reimplementation" on first
pass. The second pass forces a concrete re-examination.

### Pass 1: Initial Classification

Run the classifier prompt above on batches of 10-20 statements. This
produces an initial classification for every statement.

Expected outcome: the majority of statements are correctly classified
as ALGORITHM, SHAPE, STORE, or ANALYSIS. But some fraction of
ALGORITHM and SHAPE statements will be incorrectly classified as
INVARIANT.

### Pass 2: Invariant Challenge

For every item classified as INVARIANT in Pass 1, run a focused
challenge prompt:

```
You previously classified these statements as INVARIANT -- meaning
they are guiding principles that survive any complete reimplementation.

For each one, answer this concrete question:

"Imagine a team is reimplementing this system using a completely
different technology stack (different language, different database,
different architecture). They have never seen the original
implementation. Would they INDEPENDENTLY arrive at this exact
statement as a requirement, or would they solve the same underlying
problem differently?"

If they would independently arrive at this statement: CONFIRMED
INVARIANT.

If they would solve the same problem differently: RECLASSIFY as
ALGORITHM, SHAPE, or STORE (whichever applies).

Key distinction:
- "Concurrent modifications must never corrupt state" -- any team
  would require this. CONFIRMED INVARIANT.
- "MUST acquire lock before writing" -- a different team might use
  MVCC or CAS instead. RECLASSIFY as ALGORITHM.
- "Trust > Friction > Performance" -- this is a product value that
  any implementation must respect. CONFIRMED INVARIANT.
- "MUST emit step_start event" -- a different team might use
  different observability. RECLASSIFY as ALGORITHM.

For each statement, return:
- "statement": the original text
- "original_classification": "INVARIANT"
- "challenge_result": "CONFIRMED" or "RECLASSIFIED"
- "final_classification": the final category
- "confidence": a number from 0.0 to 1.0
- "reasoning": why this does or does not survive reimplementation

Statements classified as INVARIANT:
{invariant_batch}
```

### Expected Pass 2 Behavior

In real specs with ~500 "MUST" statements:
- Pass 1 might classify ~50-80 as INVARIANT (10-16%)
- Pass 2 should reclassify ~70-80% of those back to ALGORITHM/SHAPE
- Final invariant count should be ~5-10% of total (matching the real
  distribution from `00_CLASSIFICATION.md`)

If Pass 2 confirms more than ~15% of total statements as INVARIANT,
something is wrong. Real specs have very few true invariants.

---

## Output Format

Each classified statement produces a JSON object:

```json
{
  "statement": "TM MUST perform ticket status transitions under locks/ticket.<ticket_id>.lock",
  "classification": "ALGORITHM",
  "confidence": 0.92,
  "reimplementation_test_reasoning": "File-lock-based transitions are one concurrency approach; a reimplementation could use database transactions or CAS instead.",
  "source_file": "ticket_manager.md",
  "source_line": 47,
  "pass": 1,
  "challenged": false
}
```

For items that went through Pass 2:

```json
{
  "statement": "No silent termination",
  "classification": "INVARIANT",
  "confidence": 0.95,
  "reimplementation_test_reasoning": "Evidence-based stopping is a guiding principle that constrains all implementations regardless of technology.",
  "source_file": "constraints.md",
  "source_line": 12,
  "pass": 2,
  "challenged": true,
  "challenge_result": "CONFIRMED"
}
```

```json
{
  "statement": "MUST emit step_start event before executing",
  "classification": "ALGORITHM",
  "confidence": 0.88,
  "reimplementation_test_reasoning": "Specific event emission is one observability approach; a reimplementation could use tracing, metrics, or structured logging instead.",
  "source_file": "execution.md",
  "source_line": 23,
  "pass": 2,
  "challenged": true,
  "challenge_result": "RECLASSIFIED",
  "original_classification": "INVARIANT"
}
```

---

## Batch Processing

### Batch Size: 10-20 Statements Per Call

- **Not 1 at a time**: Too slow and expensive. A 500-statement spec
  would require 500 LLM calls for Pass 1 alone.
- **Not entire files**: Too much context. The LLM loses focus and
  classification quality degrades past ~30 statements. Large batches
  also increase the chance of the LLM skipping statements silently.
- **10-20 is the sweet spot**: Enough context for the LLM to see
  related statements together, small enough to maintain classification
  quality, and practical for throughput (~25-50 calls for a 500-
  statement spec).

### Batching Strategy

1. **Group by source section**: Statements from the same section of
   the input spec should be batched together. This preserves local
   context (a statement about "lock acquisition" makes more sense next
   to other statements about "concurrency control").

2. **Do not split related statements across batches**: If a paragraph
   contains 3 related statements, keep them in the same batch even if
   it means a batch has 22 items instead of 20.

3. **Include section header as context**: Each batch should include
   the section title and a one-line description of what the section
   covers, so the LLM has context for classification.

### Parallel Execution

Pass 1 batches are independent and can run in parallel. Pass 2 depends
on Pass 1 results but its batches are also independent of each other.

---

## Common Failure Modes and Mitigations

### 1. "MUST" Inflation

**Problem**: The LLM sees "MUST" and defaults to INVARIANT.

**Mitigation**: The system prompt explicitly states that ~95% of "MUST"
statements are algorithms or shapes. The few-shot examples heavily
weight toward "MUST" statements that are NOT invariants (10 examples
of ALGORITHM/SHAPE vs 5 examples of INVARIANT). This ratio is
intentional -- it reflects real-world distributions.

### 2. Abstraction Laundering

**Problem**: The LLM rephrases a specific statement into an abstract
principle to justify INVARIANT classification. For example, "MUST
acquire lock" becomes "the system must ensure safe concurrent access"
in the reasoning, and then the LLM classifies based on its own
rephrasing rather than the original statement.

**Mitigation**: The Pass 2 challenge prompt asks about "this SPECIFIC
statement" and whether a reimplementing team would "arrive at this
exact statement." This anchors classification to the actual text, not
an abstracted version.

### 3. Domain Rule Confusion

**Problem**: Some statements look like invariants but are actually
domain model choices. "Tickets have exactly 5 states" could be seen
as a domain invariant, but a reimplementation could model ticket
lifecycle differently.

**Mitigation**: The few-shot examples include "Ticket state MUST be
one of: open, in_progress, blocked, done, abandoned" classified as
SHAPE. The distinction: true domain invariants constrain the problem
space (like "terminal states are final"), while domain model choices
constrain one specific model of the problem.

### 4. Thin Invariant Layer

**Problem**: After two passes, only 5-10% of statements are
invariants. This feels "wrong" to reviewers who expect more
constraints.

**Reality**: This IS correct. Most of a spec is implementation detail.
The invariant layer is thin by nature -- it is the small set of
principles that all implementations must respect. If the invariant
layer is thick, the classifier is broken.

### 5. Ambiguous Statements

**Problem**: Some statements genuinely straddle categories. "All
mutations must be auditable" could be an invariant (auditability is
a guiding principle) or an algorithm (emit audit events for every
mutation).

**Mitigation**: The confidence score captures this uncertainty.
Statements with confidence < 0.7 should be flagged for human review.
The reimplementation_test_reasoning field makes the classification
logic transparent and reviewable.

---

## Integration with Phase 0 Pipeline

### Where Classification Runs

Classification is step 4 in the per-file processing pipeline
(from `PDD_SOURCES_OF_TRUTH.md`):

1. **Intake** -- Read file, detect format
2. **Sectionize** -- Split into logical sections
3. **Decompose** -- Split interleaved content at sentence level
   (see `00_CLASSIFICATION.md` "Interleaved Classification")
4. **Classify** -- Run the two-pass classifier on decomposed
   statements (THIS DESIGN)
5. **Record cross-references** -- Note references to other files

### Input to Classifier

The decompose step (step 3) produces individual statements extracted
from sections. Each statement arrives with:
- The statement text
- Source file and line number
- The section title it came from
- Whether it was marked normative or informative in the source

### Output from Classifier

Each statement gets a classification, confidence, and reasoning.
These flow into:
- **INVARIANT** statements -> constraint docs
- **ALGORITHM** statements -> pseudocode in detail files
- **SHAPE** statements -> pseudocode in detail files
- **STORE** statements -> pseudocode in detail files
- **ANALYSIS** statements -> analysis docs

### Coverage Tracking

Every input statement must appear in exactly one output category.
The classifier must not drop statements. Coverage is verified by
checking that the count of classified statements equals the count
of input statements, and that every source_line is accounted for.

---

## Agent Contract

The classifier runs as an LLM agent invocation following the pattern
in `clean/12_AGENT_CONTRACTS.md`:

- **Agent ID**: `phase0_classifier`
- **Input**: Batch of statements with section context
- **Output schema**: JSON array of classified statements (validated
  against the output format above)
- **Repair policy**: On schema validation failure, repair via
  `RepairInvalidAgentOutput`. Common repair: the LLM returns
  markdown-wrapped JSON instead of raw JSON -- strip code fences
  before parsing (use `_strip_code_fences()` from
  `spec_manager/refinement/formats.py`).
- **Fallback**: On persistent failure, classify the batch as
  ALGORITHM (the most common category) with confidence 0.0 and
  flag for human review.

Pass 2 uses a separate agent invocation:
- **Agent ID**: `phase0_classifier_challenge`
- **Input**: Batch of INVARIANT-classified statements
- **Output schema**: JSON array of challenge results
- **Repair/fallback**: Same as Pass 1

---

## Validation Heuristics

After classification completes, run these sanity checks:

1. **Invariant percentage**: If > 15% of statements are INVARIANT,
   the classifier is likely broken. Flag for review.

2. **Algorithm percentage**: If < 40% of statements are ALGORITHM,
   the classifier may be under-classifying algorithms. In real specs,
   algorithms are the plurality category.

3. **Zero invariants**: If a non-trivial spec (50+ statements) has
   zero invariants, the classifier may be over-correcting. Most real
   specs have at least a few guiding principles.

4. **Low confidence cluster**: If > 30% of statements have confidence
   < 0.7, the input may be genuinely ambiguous, or the batch context
   may be insufficient. Consider re-running with smaller batches and
   more section context.

5. **Challenge flip rate**: If Pass 2 reclassifies > 90% of
   invariants, Pass 1 is miscalibrated. If Pass 2 reclassifies < 30%,
   Pass 2 may not be aggressive enough (given the ~95% algorithm/shape
   base rate for "MUST" statements).

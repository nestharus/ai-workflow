# Core Patterns

Reusable algorithms for recurring problem classes. When you encounter a
design problem, match it to one of these patterns. Each pattern describes
a class of problems, the algorithm that solves it, why the algorithm works,
and what breaks without it.

These are not principles (those are in `constraints/` — they say what to
value). These are not workflows (those describe specific sequences). These
are algorithms that classify and solve recurring structural problems.

---

## Classify-and-Dispatch

**Problem class**: Inputs differ in kind, not just degree. Different kinds
require fundamentally different processing, and no single handler can be
optimal for all kinds.

**Algorithm**:

1. Examine the input to determine its kind
2. Route it to a handler specialized for that kind
3. The classifier does not do the work — it only determines the destination

**Why it works**: Specialization beats generalization when inputs differ in
kind. Each specialist is optimized for its narrow domain. Adding a new kind
requires only a new specialist — existing specialists and the classifier
are unchanged.

**What breaks without it**: A monolithic handler embeds case-switching logic
throughout its body. Adding new kinds requires modifying the handler,
risking regressions in existing cases. Complexity grows multiplicatively —
every new kind interacts with every existing code path.

---

## Progressive Gating

**Problem class**: Quality is multi-dimensional and cannot be achieved in a
single transformation. No single check covers all dimensions, and the cost
of a defect grows the further it propagates before detection.

**Algorithm**:

1. Define a sequence of gates, each checking one quality dimension
2. Pass work through gates in order
3. Work advances only when the current gate passes
4. Failed work is sent back to the appropriate stage for correction

**Why it works**: Each gate narrows the error space independently. Early
gates catch cheap-to-fix problems before they compound into expensive
downstream failures. The sequence can be optimized so that the gates most
likely to fail (and cheapest to retry) come first.

**What breaks without it**: A single monolithic quality check either misses
dimensions (insufficient checking) or is expensive to run, hard to debug
when it fails, and gives no indication of which dimension caused the
failure. Defects that would have been cheap to catch at stage 2 are instead
discovered at stage 8, requiring rework of everything in between.

---

## Emit-React

**Problem class**: Independent agents need to coordinate without being
coupled to each other. A producer of information should not need to know
all possible consumers, and adding a consumer should not require changing
the producer.

**Algorithm**:

1. Producers emit structured signals describing what happened
2. Consumers subscribe to signal types they care about
3. Consumers react independently — the producer is unaware of who reacts
   or how
4. The signal format is the contract; producer and consumer are otherwise
   independent

**Why it works**: Coupling between components is reduced to a shared signal
format. Producers and consumers evolve independently. New consumers are
added without any change to producers. The signal format itself becomes
the stable interface.

**What breaks without it**: Direct calls from producer to consumer create
tight coupling. Adding a new consumer requires modifying the producer. The
producer becomes a coordination bottleneck that must know about all
consumers. Changes to one consumer's needs can break the producer's logic
for other consumers.

---

## Accumulate-then-Assess

**Problem class**: Individual observations are noisy, partial, or
unreliable. A decision based on a single observation has a high error rate.
The cost of a wrong decision exceeds the cost of gathering additional
evidence.

**Algorithm**:

1. Collect observations from multiple independent perspectives
2. Aggregate observations into a body of evidence
3. Assess the aggregated evidence holistically
4. Decide only when the evidence crosses a confidence threshold

**Why it works**: Independent observations have uncorrelated errors.
Aggregation cancels out noise. Multiple perspectives cover blind spots that
any single perspective would miss. The assessment step can weigh conflicting
evidence rather than picking one arbitrarily.

**What breaks without it**: Decisions based on a single observation are
subject to that observation's noise and blind spots. False positives and
false negatives both increase. Wrong decisions propagate downstream where
they are more expensive to correct. The system oscillates between
conflicting single-observation decisions.

---

## Projection

**Problem class**: Multiple consumers need different representations of the
same underlying truth. Consumers have different needs — detail level,
format, subset — but all derive from the same source.

**Algorithm**:

1. Maintain a single authoritative source
2. Derive views for each consumer by transforming the source
3. Views are read-only — consumers never modify the source through views
4. If the source changes, views are regenerated, not patched

**Why it works**: A single source of truth eliminates consistency problems.
Views can be tailored to each consumer without compromising the source. If
a view is wrong or stale, regenerating it from the source is always safe.

**What breaks without it**: Multiple representations of the same
information drift apart. When they conflict, there is no resolution
mechanism. Consumers modify "their" copy, and changes are lost when another
representation is treated as authoritative. Reconciliation between
divergent copies becomes increasingly expensive.

---

## Bounded Convergence

**Problem class**: An iterative process approaches a goal but may never
reach it, or may reach it after an unpredictable number of iterations.
Running forever is unacceptable, but stopping too early wastes prior work.

**Algorithm**:

1. Define a natural completion condition (the goal has been achieved)
2. Define an artificial bound (maximum iterations, time, or cost)
3. On each iteration, check the natural condition first, then the bound
4. When stopping for any reason, report why — natural completion,
   bound hit, or no forward progress

**Why it works**: The natural condition ensures correctness — you stop when
the goal is actually achieved. The bound ensures safety — you stop even if
the goal is unreachable. The diagnostic ensures debuggability — you know
why it stopped and can adjust.

**What breaks without it**: Without a natural condition, the process always
runs to the bound, wasting resources on already-completed work. Without a
bound, the process may run forever. Without a diagnostic, a bound hit
looks identical to natural completion, hiding convergence failures.

---

## Content-Addressed Identity

**Problem class**: A system repeatedly transforms content, and the same
input may be presented multiple times. Redundant transformations waste the
most expensive resource — whether that is time, compute, or inference cost.

**Algorithm**:

1. Compute a content hash of the transformation input, including all
   parameters that affect output
2. Check if a cached output exists for that hash
3. If yes, return the cached output without re-running the transformation
4. If no, run the transformation and cache the output keyed by the hash

**Why it works**: Identity based on content — not name, location, or time —
means structurally identical inputs always match regardless of how they
arrived. A hash comparison is effectively free compared to the cost of the
transformation it replaces.

**What breaks without it**: Every presentation of the same input triggers a
full transformation. In iterative systems, unchanged content is presented
many times across cycles. Total cost scales with the number of iterations
instead of scaling with the amount of unique content.

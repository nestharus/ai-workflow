# Information Permanence

Information destroyed during transformation is unrecoverable from within
the system. Computation destroyed during transformation can be re-run.

This asymmetry makes information the critical resource. The record of what
happened, what was decided, what the source said — once lost, no amount of
computation can reconstruct it. But the process of deriving new information
from existing information is repeatable, as long as the inputs were
preserved.

The implication: protect information aggressively. Treat computation as
expendable and re-runnable.

---

## Route information, don't extract it

Moving the original to its destination preserves it. Summarizing,
rewriting, or extracting creates a new representation that is necessarily
lossy — the original contained nuance, context, and detail that the
extraction does not.

Summaries and extractions are useful as routing hints — metadata that
helps determine where information should go. They are not replacements
for the original. The original must arrive at its destination intact.

---

## Account for all inputs through every transformation

Every transformation must account for all of its inputs. If an input
element is not carried forward, that omission must be explicit and
recorded, never silent.

Silent loss is the worst failure mode because it is undetectable from
within the system. If you know something was dropped, you can investigate
and recover. If you don't know, the loss propagates through every
downstream consumer and compounds.

---

## Maintain unbroken chains from output to origin

For any piece of output, the chain back to the original source input must
be traceable. What was the original source? What transformations produced
this? What decisions were made along the way?

Traceability is the mechanism by which loss can be detected, investigated,
and corrected. Without it, the system is a black box — you can see what
went in and what came out, but not whether anything was lost in between.

---

## Add, don't replace

New work arrives as additions to the system, not as replacements that
destroy previous state. Prior versions, prior outputs, and prior decisions
are retained and accessible. If new work supersedes old work, the
supersession is recorded — the old work remains available for reference,
comparison, and recovery.

Destructive changes are irreversible. If the new version is wrong, the
old version is gone. Additive changes preserve the ability to compare,
revert, and audit. The cost of storage is negligible compared to the cost
of lost work.

---

## Preserve inputs so computation can be replayed

Given the same inputs and configuration, the same operation should produce
the same output. This requires that inputs, configuration, and operation
parameters are preserved alongside outputs.

Replayability makes every failure recoverable (re-run the operation),
every result auditable (verify the output matches the input), and every
bug diagnosable (what was the input that produced the wrong output?). It
depends entirely on having preserved the inputs — the computation itself
is the expendable part.

---

## Persist in proportion to reconstruction cost

Not all state needs durable storage. The decision depends on what it
would cost to reconstruct the state if it were lost.

State that can be cheaply recomputed from preserved inputs — in-memory
caches, computed indexes, derived views — is expendable. Losing it costs
a fast local recomputation.

State that requires expensive operations to reconstruct — operations that
consume significant time, external API calls, or human attention — must
be persisted. The information is not expensive, but the computation to
recreate it is, and computation is only expendable when it's cheap.

---

## Use content identity to avoid redundant computation

If the input to a transformation has not changed, the output will not
change. A content hash of the input detects whether the transformation
can be skipped. The hash comparison is effectively free relative to the
cost of the transformation it replaces.

This is a direct application of the asymmetry: the result (information)
is worth preserving; the process (computation) is worth skipping when the
result is already known.

---

## Redact through projection, not destruction

When sensitive content must be hidden from certain consumers, the
mechanism is projection — a derived view with certain content removed.
The original remains available under appropriate access controls.

Destroying the original to achieve redaction is permanent information
loss. Projection preserves the original while serving the redaction
requirement.

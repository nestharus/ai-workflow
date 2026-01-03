### 6. Progress Test for Reconstruction Failures

When reconstruction fails for a region, the system does NOT attempt to classify failure causes directly. Instead, it applies a **progress test** through **anchoring**:

1. Re-attempt extraction over the failing region with expanded context (see Anchoring Unanchored Text below).
2. If reconstruction improves (even partially), the failure was due to insufficient prior understanding. The system continues extraction.
3. If reconstruction does NOT improve after bounded attempts, the system treats the region as **not computably understandable**.

No claim is made about *why* reconstruction failed - whether a fact was missed, the text expresses an unextractable concept, or a relation is implicit or underspecified. This uncertainty is fundamental and unavoidable.

When reconstruction remains impossible (anchoring fails after bounded attempts), the system MUST emit a **Clarification Question** artifact. This is not a recovery mechanism; it is an honest admission of non-understanding.

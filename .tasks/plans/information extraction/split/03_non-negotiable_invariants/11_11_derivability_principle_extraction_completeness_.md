### 11. Derivability Principle (Extraction Completeness via Logical Derivability)

Extraction completeness is defined by **derivability**, not exhaustive enumeration. Even if the system does not extract every implication, it preserves the **base facts from which implications can be derived**. This is sufficient for correctness.

**Formal Statement:**

If a text T implies facts {F1, F2, ..., Fn}, and the system extracts a subset S ⊂ {F1...Fn} such that:
1. Reconstruction of T succeeds from S (reconstruction threshold met), AND
2. All facts in {F1...Fn} are logically derivable from S

Then extraction is COMPLETE for T, even though not all facts were explicitly extracted.

**Why This Matters:**

- **Efficiency**: The system does not need to extract every possible implication at extraction time
- **Correctness**: Base facts preserve all information needed for derivation when implications are later needed
- **Adaptability**: When the corpus is edited or new context is added, implications can surface on-demand through derivation
- **No Information Loss**: Implications can always be derived from base facts when needed - the information is preserved

**Example:**

Source text: "red flowers scattered across the floor"

- **Extracted (base fact)**: (red flowers, scattered across, the floor)
- **Not extracted (derivable implications)**:
  - "red flowers are on the floor" (spatial containment inference)
  - "red flowers went through the air" (motion/trajectory inference)
  - "some event caused the scattering" (causation inference)
- **Status**: These implications are DERIVABLE from the extracted base fact - no information was lost
- **When needed**: If new context asks "what is on the floor?", the spatial containment implication can be derived from the base fact

**Relationship to Reconstruction Threshold:**

The Derivability Principle extends the Reconstruction Threshold Principle (Invariant #1). Reconstruction success proves we have sufficient facts to rebuild the text. The Derivability Principle further ensures that we have sufficient facts to derive all implications the text conveys - even if those implications were not explicitly extracted.

**Impact on Clarification Questions:**

Clarification Questions are emitted only when:
- Reconstruction fails AND anchoring fails (the system cannot find base facts to explain the text), OR
- Base facts exist but derivation is impossible (the logic connecting base facts to required implications is unclear)

Clarification Questions are NOT emitted merely because an implication was not explicitly extracted. If the implication is derivable from extracted base facts, no clarification is needed.

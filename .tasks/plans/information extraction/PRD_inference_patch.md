# PRD Patch — Inference Validation and Derivability

This document contains distinct conceptual patches that must be woven throughout `requirements.md`. Each patch has cascading side effects that require consistency updates across multiple sections.

---

## Patch A — Reconstruction Threshold Principle

### Core Concept
Reconstruction success proves we have **enough facts to rebuild the original text**. It does NOT prove we extracted **every fact** the text expresses or implies.

### Key Distinction
- **Reconstruction threshold**: The minimum set of facts needed to reproduce the original text byte-for-byte
- **Exhaustive extraction**: Every fact (including implications) the text could yield

These are NOT the same. Reconstruction is a sufficiency test, not a completeness test.

### Example
Source: "red flowers scattered across the floor"
- **Threshold facts** (enough to reconstruct): (red flowers, scattered across, the floor)
- **Additional implied facts** (not required for reconstruction):
  - Red flowers are on the floor (location implication)
  - Red flowers went through the air (motion/trajectory implication)
  - Some event caused the scattering (causation implication)

Reconstruction succeeds with just the threshold facts. The implied facts are derivable but not required.

### Side Effects (sections to update)
1. **Non-negotiable Invariant #1** (Byte-exact Provenance and Reconstruction): Add clarification that reconstruction tests sufficiency, not exhaustive extraction
2. **Non-negotiable Invariant #4** (Span Lifecycle States): PROVEN means "sufficient facts" not "all facts"
3. **Fact Extraction → Exhaustive Iteration**: Clarify that "exhaustive" means "until reconstruction succeeds" not "until all possible facts extracted"
4. **Termination criteria**: Update to reflect threshold-based termination
5. **Opus-Led Formal Proof Reconstruction**: Clarify what success means

---

## Patch B — Fact Taxonomy: Base Facts vs Implied Facts

### Core Concept
Facts exist on a spectrum from directly extractable to inferentially derivable:

1. **Base Facts**: Directly extractable from source text grammar
   - The source text syntactically contains all elements of the triplet
   - NLTK can validate structural presence
   - Example: "The device supports Wi-Fi" → (The device, supports, Wi-Fi)

2. **Implied Facts**: Derivable from base facts through logical inference
   - Not directly stated in source grammar
   - Require reasoning beyond syntax
   - May become concrete with additional context
   - Example: "red flowers scattered across the floor" implies "red flowers are on the floor"

### Key Principle
The system extracts base facts primarily. Implied facts may be extracted when:
- They are contextually important
- They make coreference resolution possible
- They are needed for reconstruction of related text

### Side Effects (sections to update)
1. **Fact Extraction → Identify Atomic Facts**: Add base/implied distinction
2. **Entity Declarations vs Relation Triplets**: Extend taxonomy with implied facts
3. **Illegal Fact Fabrication**: Distinguish illegal fabrication from valid inference
4. **Coreference Resolution**: Some coreference requires inference

---

## Patch C — Inference Validation Layer

### Core Concept
The system has two distinct validation layers:

1. **Grammar Validation** (NLTK - already exists):
   - Validates that extracted triplets are syntactically supported by source text
   - Catches structural fabrications (Hidden Copula, Forced Subject, etc.)
   - Deterministic, rule-based

2. **Inference Validation** (NEW):
   - Validates that implied facts are logically derivable from base facts
   - Catches incorrect inferences (wrong coreference, invalid implication)
   - Requires reasoning, not just grammar checking

### Example of Invalid Inference
Source: "red flowers scattered across the floor, erupting from the palms of its hands"
- Base fact: (red flowers, scattered across, the floor)
- Invalid inference: "it" (from "its hands") = "flowers"
- Why invalid: "flowers" is plural, "its" is singular possessive - grammatical mismatch
- This is NOT a grammar fabrication (the triplet structure exists) - it's an inference error

### Inference Validation Rules
1. **Coreference Consistency**: Pronoun references must agree in number/gender/person
2. **Logical Entailment**: Implied facts must actually follow from base facts
3. **Context Scope**: Inferences must respect document/section boundaries
4. **No Phantom Entities**: Cannot infer entities not mentioned or implied anywhere

### Side Effects (sections to update)
1. **NLTK-Based Grammar Validation**: Rename/clarify scope as "Grammar Validation"
2. **Add new section**: "Inference Validation Layer" after Grammar Validation
3. **Validation Flow Integration**: Show both layers in pipeline
4. **Illegal Fact Fabrication**: Add "Illegal Inference" as distinct category
5. **Opus Reconstruction Proof**: Opus handles inference validation (reasoning required)

---

## Patch D — Derivability Principle

### Core Concept
Even if the system does not extract every implication, it preserves the **base facts from which implications can be derived**. This is sufficient for correctness.

### Formal Statement
> If a text T implies facts {F1, F2, ..., Fn}, and the system extracts a subset S ⊂ {F1...Fn} such that:
> 1. Reconstruction of T succeeds from S, AND
> 2. All facts in {F1...Fn} are logically derivable from S
>
> Then extraction is COMPLETE for T, even though not all facts were explicitly extracted.

### Why This Matters
1. **Efficiency**: Don't need to extract every possible implication
2. **Correctness**: Base facts preserve all information needed for derivation
3. **Adaptability**: When corpus is edited, new context can surface implications
4. **No Information Loss**: Implications can always be derived when needed

### Example
Source: "red flowers scattered across the floor"
- Extracted: (red flowers, scattered across, the floor)
- Not extracted: "flowers are on the floor", "flowers went through air"
- These are DERIVABLE from the extracted fact - no information lost
- When context changes (e.g., new sentence asks "what is on the floor?"), the implication surfaces

### Side Effects (sections to update)
1. **Non-negotiable Invariants**: Add Derivability Principle as new invariant
2. **Completeness claims**: Define completeness as "sufficient for derivation"
3. **Termination criteria**: Reconstruction + derivability = complete
4. **Clarification Questions**: Only needed when derivation is impossible, not just when implications weren't extracted

---

## Patch E — Illegal Inference (extends Illegal Fact Fabrication)

### Core Concept
Illegal Fact Fabrication currently covers **grammatical fabrication** (adding structure not in source). We must extend it to cover **inference fabrication** (claiming implications that don't follow).

### New Fabrication Type: Invalid Inference
In addition to the existing 5 fabrication types (Hidden Copula, Attribute-to-Process, Pronoun Concord, Tense Fabrication, Forced Subject), add:

6. **Invalid Coreference Inference**: Assigning a referent to a pronoun without valid antecedent
   - Source: "...its hands..." (no singular entity established)
   - Fabricated inference: "its" refers to "flowers" (plural)
   - Illegality: Number mismatch makes this inference invalid

7. **Ungrounded Implication**: Claiming an implication that doesn't logically follow
   - Source: "the device is portable"
   - Fabricated inference: "the device is wireless"
   - Illegality: Portability does not entail wirelessness

8. **Context Boundary Violation**: Inferring across document sections without explicit connection
   - Source section A: "The server handles requests"
   - Source section B: "It uses Redis for caching"
   - Fabricated inference: "The server uses Redis" (if sections are unrelated)
   - Illegality: "It" in section B may refer to something else

### Detection
- Grammar validation (NLTK) catches structural issues
- Inference validation catches logical issues
- Both must pass for a fact to be valid

### Side Effects (sections to update)
1. **Illegal Fact Fabrication → Types of Illegal Fabrication**: Add new types 6, 7, 8
2. **Validation Rules for Illegal Fact Detection**: Add inference validation rules
3. **NLTK section**: Clarify that NLTK handles grammar, not inference
4. **Opus role**: Opus performs inference validation as part of reconstruction proof

---

## Application Order

These patches have dependencies and should be applied in order:

1. **Patch A** (Reconstruction Threshold) - foundational concept change
2. **Patch B** (Base/Implied Taxonomy) - requires Patch A's threshold concept
3. **Patch D** (Derivability Principle) - requires Patches A and B
4. **Patch C** (Inference Validation Layer) - requires Patch B's taxonomy
5. **Patch E** (Illegal Inference) - requires Patch C's validation layer

Each patch must update all listed side-effect sections before the next patch is applied.

---

## Consistency Checklist

After all patches are applied, verify:

1. [ ] No section claims reconstruction = exhaustive extraction
2. [ ] Base/implied distinction is used consistently
3. [ ] Grammar validation and inference validation are clearly separated
4. [ ] Derivability principle is referenced in termination criteria
5. [ ] Illegal fabrication includes inference types
6. [ ] NLTK scope is clearly limited to grammar
7. [ ] Opus scope includes inference validation
8. [ ] All "completeness" language uses derivability definition

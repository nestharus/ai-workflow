### 10. No Formal Proof Languages for Semantic Equivalence

Formal proof languages (such as Lean, Coq, Isabelle, etc.) are **out of scope** for this system's validation mechanism. The reasons are:

- The system's correctness criterion is **byte-exact reconstruction testing**, not semantic equivalence under synonymy or entailment.
- Synonym and entailment equivalence are not decidable with certainty from natural language text alone; formal proof languages would require axioms that reintroduce uncertainty.
- Validation is implemented through:
  - **Opus-led formal reconstruction proofs**: Step-by-step derivation from facts to reproduce original text (not formal logic proofs).
  - **Python deterministic helpers**: Grammar mechanics, dictionary/synonym substitutions (logged), and character-level diff.
  - **Human clarification**: Clarification Question artifacts when reconstruction remains impossible.

The term "formal proof" in this document refers to Opus's structured, step-by-step reasoning process for deriving reconstructed text from extracted facts - similar to showing work in a math problem. It does NOT refer to machine-verified proofs in formal proof languages.

Lean or similar proof assistants may be considered in the future for internal invariant checking (optional), but they are explicitly out of scope for this PRD's core validation mechanism.

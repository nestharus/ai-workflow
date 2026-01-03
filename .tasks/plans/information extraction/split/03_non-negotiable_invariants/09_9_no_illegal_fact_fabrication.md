### 9. No Illegal Fact Fabrication

The extraction process MUST NOT hallucinate grammatical structure to force incomplete text into valid-looking triplets. An "illegal fact" is a triplet that appears syntactically correct but contains fabricated elements not present in the source text.

**Critical Distinction: Illegal Fabrication vs. Valid Inference**
- **Illegal Fabrication**: Inventing grammatical structure (verbs, subjects, tense markers) not present or implied by the source text
- **Valid Inference**: Deriving implied facts through logical reasoning from base facts (e.g., "scattered across the floor" → "on the floor"). Valid inference produces **Implied Facts**, which are legitimate extractions when contextually important.
- Illegal fabrication violates source text grammar; valid inference extends base facts through sound reasoning.

**Fabrication Types (all prohibited):**
- **Hidden Copula Hallucination**: Adding verbs (is/are/was/were) to noun phrases when no predicate relationship is implied
- **Attribute-to-Process Hallucination**: Converting static adjectives to temporal verbs without temporal implication
- **Pronoun Concord Violation**: Producing triplets with agreement mismatches
- **Tense Fabrication**: Assigning tense to timeless/inherent-property constructions
- **Forced Subject Hallucination**: Inventing entities to complete triplets when no entity is implied

**When triplet extraction is not syntactically supported:**
1. Assess whether a valid inference (Implied Fact) can be derived from base facts
2. If no valid inference exists, record Entity Declarations (entity exists) or Attribute Annotations (modifier present) instead
3. Mark the fragment as a **Syntactic Orphan**
4. Emit a Clarification Question asking what assertion the author intended
5. NEVER fabricate structure to produce a complete-looking triplet

**Key Principle**: Illegal facts are worse than missing facts. Honest incompleteness (Entity Declaration + Clarification Question) is always preferred over fabricated completeness (illegal triplet). Valid Implied Facts derived through sound inference are permitted and valuable. **Two validation layers prevent illegal facts:**
- **NLTK Grammar Validation** catches structural fabrications (grammar issues)
- **Inference Validation Layer** catches invalid inferences (logical issues)
Both must pass for a fact to be valid. See the "Illegal Fact Fabrication" section under Fact Validation and Refinement for detailed validation rules and handling protocols.

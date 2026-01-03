### Illegal Fact Fabrication

The extraction process itself can hallucinate structure to force incomplete text into valid-looking
triplets. These "illegal facts" appear syntactically correct but contain hidden fabrications that
violate the source text's actual grammar and meaning. Illegal fabrication includes BOTH **grammar
fabrication** (inventing syntactic structure not present in source text) and **inference fabrication**
(claiming logical inferences that don't validly follow from base facts). This section defines the
types of illegal fabrication, distinguishes entity declarations from relation triplets, and specifies
how to handle syntactic orphans.

```
Types of Illegal Fabrication: The following fabrication types represent violations where the
extraction process invents grammatical or semantic structure not present in the source text.
Illegal fabrications fall into two categories: **Grammar Fabrications** (types 1-5) which violate
syntactic structure, and **Inference Fabrications** (types 6-8) which violate logical derivability.

**Grammar Fabrications (caught by NLTK deterministic validation):**

1. Hidden Copula Hallucination: Adding a verb (typically "is", "are", "was", "were") to transform
   a noun phrase or description into an assertion.
   - Source text: "...red flowers scattered across the pavement..." (noun phrase, not sentence)
   - Fabricated fact: (Red flowers, ARE scattered across, the pavement)
   - Illegality: The verb "are" was added; the source text uses a participial phrase, not a predicate
   - Detection: Check if the source span contains a finite verb; if not, any triplet with a copula is fabricated

2. Attribute-to-Process Hallucination: Converting a static adjective into a temporal verb implying
   change or continuity.
   - Source text: "...the canonical input string..." (static adjective modifying noun)
   - Fabricated fact: (The input string, REMAINS, canonical)
   - Illegality: "Remains" implies temporal process; the source uses an inherent property adjective
   - Detection: Adjectives modifying nouns should not become predicates with temporal verbs
     (remains, becomes, stays, continues)

3. Pronoun Concord Violation: Producing a triplet where grammatical agreement (number, person,
   gender) is violated between the extracted subject and other elements.
   - Source text: "...red flowers ... erupting from the palms of ITS hands..."
   - Fabricated fact: (Red flowers, are erupting from, the palms of its hands)
   - Illegality: "flowers" (plural) cannot grammatically possess "its" (singular possessive) hands
   - Detection: Validate number/person/gender agreement across all triplet elements; flag mismatches

4. Tense Fabrication: Assigning a tense (past, future, conditional) when the source text uses
   timeless or inherent-property constructions.
   - Source text: "partition-style span fragmentation" (compound noun phrase)
   - Fabricated fact: (The span fragmentation, WAS, partition-style)
   - Illegality: Past tense "was" implies prior state; the source describes an inherent property
   - Detection: Compound nouns and attributive adjectives should not be converted to past/future tense predicates

5. Forced Subject Hallucination: Inventing a subject or object to complete a triplet when the
   source text provides none.
   - Source text: "also buffalo sauce" (no subject, no verb - fragment)
   - Fabricated fact: (Buffalo sauce, is included in, THE SCENARIO)
   - Illegality: "scenario" does not exist in the source text; it was fabricated to complete the triplet
   - Detection: Every entity in a triplet must be traceable to source text spans; invented entities are illegal

**Inference Fabrications (caught by Opus inference validation, see Inference Validation Layer):**

6. Invalid Coreference Inference: Assigning a referent to a pronoun without valid antecedent or
   with grammatical agreement violations.
   - Source text: "...its hands..." (no singular entity established in context)
   - Fabricated inference: (its hands, belong to, flowers) where "flowers" is plural
   - Illegality: Number mismatch makes this inference invalid; "its" (singular) cannot refer to
     "flowers" (plural)
   - Detection: Validate that pronoun-antecedent pairs agree in number, gender, and person; check
     that antecedents exist in accessible context

7. Ungrounded Implication: Claiming an implication that doesn't logically follow from available
   base facts.
   - Source text: "the device is portable"
   - Fabricated inference: (the device, is, wireless)
   - Illegality: Portability does not entail wirelessness; this inference has no logical basis in
     the source facts
   - Detection: Validate that implied facts are derivable through valid logical inference from base
     facts; reject implications that introduce unwarranted assumptions

8. Context Boundary Violation: Inferring relationships across document sections without explicit
   connection.
   - Source section A: "The server handles requests"
   - Source section B (unrelated): "It uses Redis for caching"
   - Fabricated inference: (The server, uses, Redis) - assuming "it" in section B refers to "server"
     in section A
   - Illegality: "It" in section B may refer to a different entity; cross-section inference without
     explicit connection violates context boundaries
   - Detection: Validate that coreferences and inferences respect document structure (headings,
     paragraphs, section boundaries); reject inferences that span unrelated contexts

Entity Declarations vs. Relation Triplets: Not all extractable information fits the
(Subject, Predicate, Object) triplet form. The system must distinguish:

- Base Fact (Relation Triplet): A complete assertion with subject, predicate, and object, where all
  three elements are syntactically supported by the source text. Example: "The device supports Wi-Fi"
  yields (The device, supports, Wi-Fi) - all elements present in source. These are directly extractable
  from source grammar.

- Implied Fact (Inferred Relation): A triplet derivable through logical inference from base facts,
  though not directly stated in source grammar. Example: "red flowers scattered across the floor"
  allows the inference (red flowers, are on, the floor) - a spatial containment relationship not
  explicitly stated. Implied facts are VALID extractions when correctly derivable and contextually
  important, but must be distinguished from base facts.

- Entity Declaration: Recognition that an entity exists without asserting a relation. When the
  source text mentions an entity but provides no predicate or complete assertion, record:
  - Entity: [entity name]
  - Source context: [character offsets]
  - Status: DECLARED (not asserted in a relation)

- Attribute Annotation: When an entity has a modifier but no predicate, record the attribute
  separately rather than fabricating a copula:
  - Entity: buffalo sauce
  - Attribute: also (modifier present in source)
  - Status: ATTRIBUTED (modifier noted, no relation asserted)

Attempting to force Entity Declarations or Attribute Annotations into Relation Triplets
through grammatical fabrication (not valid inference) constitutes Illegal Fact Fabrication.

Syntactic Orphans: Text fragments that lack the grammatical structure required to form valid
triplets are "syntactic orphans." These include:

- Noun phrases without predicates: "also buffalo sauce", "the red flowers"
- Participial phrases without subjects: "erupting from the palms"
- Prepositional phrases without anchoring clauses: "over the canonical input string"
- Fragments with pronouns lacking antecedents: "its hands" (when "its" has no referent)

Syntactic Orphan Handling Protocol:
1. DO NOT fabricate structure to complete a triplet
2. Record as Entity Declaration or Attribute Annotation (not Relation Triplet)
3. Flag for Clarification Question with request: "The text fragment '[orphan text]' cannot be
   extracted as a fact because it lacks [missing element: subject/predicate/object]. What
   assertion, if any, does this fragment represent?"
4. Mark the orphan's source context for potential resolution when author provides clarification
5. If the orphan is part of a larger sentence that WAS successfully extracted, note the linkage
   but do not force the orphan into that extraction

Validation Rules for Illegal Fact Detection: Every extracted triplet MUST pass these checks.
These rules are divided into **Grammar Validation Rules** (for Base Facts) and **Inference
Validation Rules** (for Implied Facts).

**Grammar Validation Rules (NLTK deterministic checks for types 1-5):**

1. Verb Presence Check: If the source span contains no finite verb, any triplet with a verb
   (especially copulas) is potentially fabricated. Flag for review.

2. Concord Check: Subject-verb agreement, pronoun-antecedent agreement, and number agreement
   must hold across the triplet. Mismatches indicate fabrication.

3. Tense Justification Check: If the triplet uses past/future/conditional tense, verify that
   the source text contains corresponding tense markers. Timeless descriptions should not
   become tensed assertions.

4. Entity Provenance Check: Every entity (subject, object) in the triplet must map to a
   character offset range in the source text. Entities not present in source are fabricated.

5. Predicate Source Check: The predicate (verb/relation) must be derivable from source text.
   Allowed derivations:
   - Direct extraction: verb present in source
   - Morphological transformation: "supports" from "support" (logged substitution)
   - NOT allowed: invention of predicates not implied by source grammar

**Inference Validation Rules (Opus-led logical checks for types 6-8):**

6. Coreference Validity Check: For any inferred pronoun-antecedent relationship, validate that:
   - The antecedent exists in accessible context (same sentence, previous sentence, or explicitly
     connected section)
   - Number agreement holds (singular pronouns with singular antecedents, plural with plural)
   - Gender agreement holds (he/she with gendered entities)
   - Person agreement holds (first/second/third person consistency)
   - If validation fails, reject the inference as Invalid Coreference Inference (type 6)

7. Logical Entailment Check: For any Implied Fact claiming to derive from base facts, validate that:
   - The inference follows through valid logical steps (not assumption or speculation)
   - Properties are not invented (e.g., "portable" does not entail "wireless")
   - Spatial/temporal/causal relationships are justified by source facts
   - Negative inferences are not fabricated from positive statements
   - If validation fails, reject the inference as Ungrounded Implication (type 7)

8. Context Boundary Check: For any inference connecting entities across text spans, validate that:
   - The connection respects document structure (headings, paragraphs, sections)
   - Cross-section references have explicit linguistic markers or clear continuation
   - Pronouns do not span unrelated sections without bridging context
   - Context windows are properly scoped (no inference across large gaps without justification)
   - If validation fails, reject the inference as Context Boundary Violation (type 8)

All Inference Validation Rules are enforced by the Inference Validation Layer (see below).
Grammar fabrications (types 1-5) and inference fabrications (types 6-8) are both illegal -
the system must not produce either type.

NLTK-Based Grammar Validation (Deterministic Pre-Filter): Before triplets enter the validation
pipeline, NLTK performs deterministic grammar analysis on the source text to FLAG potential
fabrications. NLTK validates that the source text actually contains the grammatical structures
the LLM claims to have extracted. **NLTK's scope is limited to syntax and grammar** - it validates
that the structural elements (verbs, subjects, agreement) exist in the source text. NLTK does NOT
validate logical inferences or semantic relationships; that is handled by the Inference Validation
Layer (see below).

**Validation Function:**
```python
import nltk
from nltk import pos_tag, word_tokenize
from nltk.parse import CoreNLPParser  # or use nltk.RegexpParser for simpler parsing

def validate_triplet(source_text: str, triplet: Triplet) -> list[ValidationFlag]:
    tokens = word_tokenize(source_text)
    tagged = pos_tag(tokens)  # Returns [(word, POS), ...]
    flags = []

    # 1. Verb Presence Check
    # NLTK POS tags: VB, VBD, VBG, VBN, VBP, VBZ are verb tags
    verb_tags = {'VB', 'VBD', 'VBG', 'VBN', 'VBP', 'VBZ'}
    has_verb = any(tag in verb_tags for word, tag in tagged)
    if triplet.has_verb() and not has_verb:
        flags.append(ValidationFlag("HIDDEN_COPULA", "No verb in source"))

    # 2. Subject Presence Check (using simple noun detection before verb)
    # NLTK POS tags: NN, NNS, NNP, NNPS, PRP are noun/pronoun tags
    noun_tags = {'NN', 'NNS', 'NNP', 'NNPS', 'PRP'}
    has_subject = any(tag in noun_tags for word, tag in tagged)
    if triplet.has_subject() and not has_subject:
        flags.append(ValidationFlag("FORCED_SUBJECT", "No noun/pronoun subject in source"))

    # 3. Pronoun Concord Check
    # PRP = personal pronoun, check singular vs plural patterns
    pronouns = [(word.lower(), tag) for word, tag in tagged if tag == 'PRP']
    singular_pronouns = {'he', 'she', 'it', 'him', 'her', 'his', 'its'}
    plural_pronouns = {'they', 'them', 'their', 'theirs'}
    nouns = [(word, tag) for word, tag in tagged if tag in {'NN', 'NNP'}]  # Singular nouns
    plural_nouns = [(word, tag) for word, tag in tagged if tag in {'NNS', 'NNPS'}]  # Plural nouns

    for pron, _ in pronouns:
        if pron in singular_pronouns and plural_nouns and not nouns:
            flags.append(ValidationFlag("PRONOUN_CONCORD",
                f"Singular pronoun '{pron}' but only plural nouns in source"))
        elif pron in plural_pronouns and nouns and not plural_nouns:
            flags.append(ValidationFlag("PRONOUN_CONCORD",
                f"Plural pronoun '{pron}' but only singular nouns in source"))

    # 4. Tense Check
    # VBD = past tense, VBP/VBZ = present, VB = base form
    tense_map = {'VBD': 'past', 'VBP': 'present', 'VBZ': 'present', 'VB': 'base'}
    source_tenses = {tense_map[tag] for word, tag in tagged if tag in tense_map}
    if triplet.claimed_tense and triplet.claimed_tense not in source_tenses:
        flags.append(ValidationFlag("TENSE_FABRICATION",
            f"Claimed tense '{triplet.claimed_tense}' not in source tenses {source_tenses}"))

    # 5. Missing Predicate Check (only nouns, no verbs = noun phrase)
    if not has_verb and has_subject and triplet.has_predicate():
        flags.append(ValidationFlag("MISSING_PREDICATE",
            "Source parses as noun phrase (no verb), not sentence"))

    return flags
```

**Flag Handling Protocol:**
- Flags do NOT auto-reject triplets; they trigger additional review
- Flagged triplets are routed to:
  1. Human review queue (if available)
  2. Clarification Question emission (if human review unavailable)
  3. FabricationAttempt artifact creation (for audit trail)
- Users can override flags with justification (recorded in audit log)
- Override justifications become part of the provenance chain

**NLTK Validation Flow Integration:**
1. Source text enters NLTK grammar analysis (deterministic)
2. NLTK produces POS tags and parse structure
3. Extracted triplet is validated against parse structure
4. Flags are generated for structural mismatches (grammar only)
5. Flagged triplets enter review/escalation path
6. Clean triplets proceed to Inference Validation Layer (see below)
7. Both validated triplets proceed to Opus reconstruction proof
8. **NLTK validates SOURCE GRAMMAR (syntax only); Inference Validation validates LOGICAL DERIVABILITY;
   Opus validates FACT DERIVATION via reconstruction proof**

Illegal Fact Escalation: When validation detects an illegal fact:

1. DO NOT include the illegal triplet in the fact list
2. Record the attempted extraction in a FabricationAttempt artifact (for grammar fabrications,
   types 1-5) or InvalidInferenceAttempt artifact (for inference fabrications, types 6-8):
   - source_text: verbatim source span
   - attempted_triplet: the illegal (S, P, O) that was generated
   - violation_type: one of [HIDDEN_COPULA, ATTRIBUTE_TO_PROCESS, PRONOUN_CONCORD,
     TENSE_FABRICATION, FORCED_SUBJECT, INVALID_COREFERENCE, UNGROUNDED_IMPLICATION,
     CONTEXT_BOUNDARY_VIOLATION]
   - missing_element: what grammatical element was fabricated (for types 1-5) or what logical
     justification is missing (for types 6-8)
3. Extract what IS legally extractable:
   - Entity Declarations for mentioned entities
   - Attribute Annotations for present modifiers
4. Emit Clarification Question for the syntactic orphan requesting author clarification
5. The Clarification Question MUST NOT suggest the fabricated triplet as a possibility;
   it should ask what the author intended without leading toward the illegal interpretation

Key Principle: If the grammar/syntax of the source text does not support a triplet structure,
DO NOT FORCE IT. The system must prefer honest incompleteness (Entity Declaration + Clarification
Question) over fabricated completeness (illegal triplet). Illegal facts are worse than missing
facts because they introduce false information that appears authoritative.

Inference Validation Layer: After NLTK grammar validation, triplets that claim to be Implied Facts
(derived through inference) must pass through a second validation layer that checks logical derivability.
While NLTK validates that the source text contains the necessary grammatical structures, Inference
Validation ensures that any inferences drawn from base facts are logically sound.

**Scope and Purpose:**
- **Grammar Validation (NLTK)**: Checks that triplet elements are syntactically supported by source text
  (deterministic, rule-based)
- **Inference Validation (Opus-led)**: Checks that Implied Facts are logically derivable from base facts
  (requires reasoning, not just grammar checking)

**Key Distinction:**
An Implied Fact may be grammatically well-formed (passing NLTK validation) but still be an invalid
inference if it doesn't logically follow from the available base facts. Example:

Source: "red flowers scattered across the floor, erupting from the palms of its hands"
- Base fact: (red flowers, scattered across, the floor) - passes NLTK validation
- Attempted implied fact: (its hands, belong to, red flowers) - passes NLTK validation (grammatically valid)
- **Inference validation failure**: "flowers" is plural, "its" is singular possessive - grammatical agreement
  mismatch indicates invalid coreference inference

This is NOT a grammar fabrication (the triplet structure exists in the source text). It IS an inference error
(the logical connection between "its hands" and "red flowers" is invalid due to number disagreement).

**Inference Validation Rules:**

1. **Coreference Consistency**: Pronoun references must agree in number, gender, and person with
   their claimed antecedents. The system must validate that:
   - Singular pronouns (it, its, he, she) refer to singular entities
   - Plural pronouns (they, their, them) refer to plural entities
   - Gender agreement holds (he/she with appropriate gendered entities)
   - Person agreement holds (first/second/third person consistency)

2. **Logical Entailment**: Implied Facts must actually follow from base facts through valid logical
   inference. The system must validate that:
   - Spatial inferences are justified (e.g., "scattered across X" → "on X" is valid)
   - Temporal inferences preserve causation and sequence
   - Property inferences don't introduce unwarranted assumptions
   - Negative inferences are not fabricated from positive statements

3. **Context Scope**: Inferences must respect document/section boundaries. The system must validate that:
   - Coreferences don't span unrelated sections without explicit connection
   - Implied relationships are grounded in the same context window
   - Document structure is respected (headings, paragraphs, etc.)

4. **No Phantom Entities**: Cannot infer entities not mentioned or implied anywhere in the source text
   or base facts. The system must validate that:
   - Every entity in an Implied Fact appears in base facts or source text
   - Entity transformations are justified (e.g., "the device" → "it" is valid)
   - No entities are synthesized from missing antecedents

**Inference Validation Process:**

For each triplet marked as an Implied Fact:
1. Identify the base facts from which the implication is claimed to derive
2. Check that all entities in the Implied Fact are present in the base facts or source text
3. Validate that the logical connection is sound according to Inference Validation Rules
4. If validation fails, classify the failure type:
   - INVALID_COREFERENCE: Pronoun reference violates agreement rules
   - UNGROUNDED_IMPLICATION: Claimed implication doesn't logically follow
   - CONTEXT_BOUNDARY_VIOLATION: Inference spans unrelated sections
   - PHANTOM_ENTITY: Inferred entity not present in base facts/source
5. Record failed inferences in InvalidInferenceAttempt artifacts (parallel to FabricationAttempt)
6. DO NOT include invalid inferences in the fact list
7. Emit Clarification Questions for invalid inferences requesting author clarification

**Integration with Opus Reconstruction Proof:**

Opus performs inference validation as part of the reconstruction proof process. When Opus attempts
to derive reconstructed text R(S) from facts, it must show that:
- Base facts are directly grounded in source text (validated by NLTK)
- Implied Facts are logically derivable from base facts (validated by Inference Validation)
- All substitutions and transformations are justified and logged

Opus's reconstruction proof trace must include inference justifications for any Implied Facts used.
If Opus cannot justify an inference through valid logical steps, the inference is rejected and flagged
as invalid.

**Validation Flow with Both Layers:**

```
Extracted Triplet
     |
     v
[NLTK Grammar Validation]
     |
     +---> Flagged (grammar issue) --> Review/Escalation
     |
     v
Clean (grammar valid)
     |
     v
Is Implied Fact?
     |
     +---> No (Base Fact) --------> Proceed to Opus Reconstruction
     |
     +---> Yes (Implied Fact)
              |
              v
     [Inference Validation Layer]
              |
              +---> Invalid inference --> InvalidInferenceAttempt artifact
              |                      --> Clarification Question
              |
              v
     Valid inference
              |
              v
     Proceed to Opus Reconstruction Proof
```

**Key Principle:**
Both validation layers must pass for a fact to be valid. Grammar validation (NLTK) is deterministic
and catches structural fabrications. Inference validation (Opus-led) requires reasoning and catches
logical errors in implied facts. NLTK validates syntax; Opus validates semantics and logical derivability.
```

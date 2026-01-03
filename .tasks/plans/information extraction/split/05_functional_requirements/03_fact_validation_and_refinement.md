### Fact Validation and Refinement

```
Atomicity Validation: Every extracted fact will be validated to ensure it represents only one atomic
piece of information. If an extracted fact statement still contains multiple assertions or conjunctions
(e.g. "X and Y are enabled"), it should be flagged as invalid. The system should then attempt to either
split it into separate facts or adjust the extraction process (e.g. refine the prompt or logic) to
produce truly atomic facts. The goal is that the final fact list has no compound facts.
Coreference Resolution and Dual Representation: Each extracted fact has two representations that
serve distinct purposes:

1. **Canonical Fact Text** (used for search, deduplication, and semantic operations):
   - Should be self-contained and clear without relying on the original sentence's context when possible.
   - May resolve pronouns (e.g., replacing "It" with "The device"), normalize formatting, and split conjunctions.
   - For example, if the text says "It will have a battery life of 10 hours", the canonical fact text should
     replace "It" with the actual subject (e.g., "The device will have a battery life of 10 hours") based on context.
   - **Coreference resolution uses the Entity Position Index**: When encountering a pronoun or reference
     at position X in the canonical string, the system queries the Entity Position Index (see Deduplication
     and Similarity Management) to find entities whose spans are positionally closest to X. This spatial
     nearest neighbor search returns candidate antecedents sorted by distance - entities that appeared
     just before the pronoun are the most likely referents.
   - **Resolution algorithm**:
     1. Identify the pronoun/reference and its character position X in the canonical string
     2. Query the Entity Position Index for entities with spans ending before X, sorted by proximity
     3. Filter candidates by grammatical agreement (number, gender, person)
     4. If a single unambiguous candidate remains, resolve the reference
     5. If multiple candidates remain, use surrounding text context to disambiguate
     6. If resolution is NOT computable, produce a symbolic placeholder (e.g., `UNKNOWN_REF_7`)
   - **Example**: "The device has 8GB RAM. It supports multitasking."
     - "It" appears at position 30; Entity Position Index query finds "The device" at [0, 10] and "8GB RAM" at [15, 22]
     - "The device" is closer to position 30 and matches singular agreement
     - Resolution: "It" → "The device"; Base fact 2 (resolved): (The device, supports, multitasking)
   - **Coreference resolution may require inference**: Resolving pronouns and references often requires
     deriving Implied Facts from base facts in the surrounding context. This is a valid use of inference -
     the system extracts base facts from antecedent text, then infers the referent relationship to resolve
     the pronoun.
   - When coreference resolution is NOT computable (the referent cannot be determined from available context),
     the system MUST produce a symbolic placeholder (e.g., `UNKNOWN_REF_7`) rather than guessing or omitting.
     Symbolic placeholders preserve the fact structure while honestly marking unresolved references.

2. **Source Context** (used for reconstruction, traceability, and provenance):
   - Always references the work region(s) from which the fact was extracted via character offsets into the
     canonical input string.
   - May contain pronouns, original phrasing, and unresolved references as they appeared in the source.
   - These are NOT ownership claims; they are provenance markers indicating where the system was looking
     when it discovered the fact.
   - Multiple facts may share the same source context; one fact may have multiple source contexts.
   - Source context enables reconstruction testing by preserving the verbatim original text that the fact
     is meant to explain.
   - Facts explain text; they do not own it.

The dual representation ensures that:
- Semantic operations (search, deduplication) work on normalized, self-contained canonical facts.
- Reconstruction and traceability work on preserved source context with exact provenance.
- Information loss is prevented by never discarding the original surface form.
- Unresolvable references are honestly marked rather than fabricated.
- Coreference resolution leverages Implied Facts when needed to connect pronouns to their antecedents.
Conditional Statements: If the source text contains conditional or contextual facts (using words like
"if", "when", "unless", etc.), the system should extract those into separate facts and capture the
relationship:
The condition part (antecedent) becomes one fact, and the consequence part becomes another fact.
A link is recorded indicating that the second fact is related to the first fact. This link may be untyped
and treated as a hypothesis; the system is not required to classify it as "prerequisite" or any other
semantic type. For example, "If the user is an admin, they can access the dashboard." would yield
Fact A: "The user is an admin" and Fact B: "The user can access the dashboard," with an untyped
link between them indicating a relationship exists.
This maintains the contextual dependency explicitly, rather than merging the conditional into a
single opaque statement.
Recording Relationships: Besides conditional dependencies, if any facts have inherent relationships
(like hierarchy or parent-child context in the text), those may be noted as untyped links. (E.g., a fact
that "Feature X has sub-features Y and Z" might be broken into facts about X and Y, X and Z, with
links between them.) The system is not required to assign semantic types such as "includes",
"entails", or "is-part-of" to these links. Links are treated as hypotheses for comprehension completeness
(extracting base facts sufficient for deriving all implications, per the Derivability Principle), not as
ontology construction. Any graph of facts and links produced is assumed to be incomplete; incompleteness
is surfaced only through reconstruction failures and Clarification Questions.
```

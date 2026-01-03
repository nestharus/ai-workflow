# Atomic Fact Extraction and Management System

# PRD

## Introduction

Large unstructured text documents often contain repetitive and interdependent details, making
it hard to manage updates or ensure consistency. This project aims to create a system that **extracts all
unique, atomic facts** from a given document (or set of documents) and organizes them into a structured
knowledge base (a "detail index"). The system will deduplicate facts, resolve references, and record
contextual relationships, so that each piece of information is stored exactly once. This allows easier
reviewing, editing, and conflict checking, since updating a fact in one place will effectively update it
everywhere it was referenced in the original text. The solution focuses on **local execution** (no cloud
services) with simple, fast-starting tools, and it prioritizes **accuracy and completeness** (no loss of
information, where completeness is defined by derivability - sufficient base facts to derive all implications).

## System Architecture Overview

The system uses **Claude Code as the execution harness** with a **two-phase extraction pipeline** followed by validation:

| Role | Model | Function |
|------|-------|----------|
| Detail Extraction | Haiku 4.5 (sub-agent 1) | Scans source text for raw details |
| Fact Construction | Haiku 4.5 (sub-agent 2) | Constructs triplets, anchors details, reasons about structure |
| Orchestration & Reconstruction | Opus 4.5 | Orchestrates pipeline, runs reconstruction proofs, QA validation |

**Execution Model:**
- **Claude Code is the harness** - all agents are Claude Code sub-agents (no separate services or Python workflow orchestration needed)
- **Sub-agents communicate via file I/O** - to avoid filling orchestrator context, sub-agents write outputs to files and the orchestrator reads them
- **Python scripts are invoked as tools by agents** - helpers for deterministic operations (grammar checks, string diffs, etc.)
- **QA mode** - agents can QA themselves during validation runs

**Key Distinctions:**
- **Details** (Phase 1): Raw observations extracted from text - may be incomplete, unanchored, or not yet in triplet form
- **Facts** (Phase 2): Anchored, validated, triplet-structured atomic statements with source context
- **Anchoring** (Phase 2): The sub-agent connects raw details to source text and validates triplet structure
- **This is NOT an ensemble**: The pipeline is sequential, not parallel. Phase 2 depends on Phase 1 output.

## Non-negotiable Invariants

The following invariants apply globally to all aspects of this system and take precedence over any conflicting requirements elsewhere in this document:

### 1. Byte-exact Provenance and Reconstruction

- The "source text" is the **canonical input string produced by the ingestion step** (after any one-time format decoding, e.g., PDF to text).
- Every reference back to the source document is stored as **character offsets** into that canonical string (source context for provenance, not ownership claims).
- Reconstruction is an **explanation test**, not a coverage proof:
  - The system attempts to **re-explain the original text region** using its current internal understanding (anchors + facts + links).
  - Reconstruction succeeds only if the system can reproduce the **exact original substring** (byte-for-byte), without paraphrasing or inference.
  - Reconstruction never assigns text ownership to facts.
  - **Reconstruction success is a sufficiency test, not a completeness test**: Successful reconstruction proves the system has **enough facts to rebuild the original text**, NOT that it has extracted **every fact** the text expresses or implies. The reconstruction threshold is the minimum set of facts needed to reproduce the original text byte-for-byte.
- If reconstruction fails for a region, the system knows only one thing: **the current understanding is insufficient to explain the text.**
- If reconstruction remains impossible after bounded attempts, the system must emit a **Clarification Question** artifact (see Output and Storage section).

### 2. No Semantic Classification Requirement

- The system is not required to assign relation types (e.g., "prerequisite", "is-a", etc.) as part of the core pipeline.
- Links between facts may be untyped and treated as hypotheses. The objective is comprehension completeness
  (extracting base facts sufficient for deriving all implications, per the Derivability Principle), not ontology construction.

### 3. Incomplete Structures are Expected

- Any graph produced (facts, anchors, spans) is assumed incomplete.
- Incompleteness is surfaced only through reconstruction failures and Clarification Questions, not through explicit completeness claims.

### 4. Span Lifecycle States

Span computability is a *claim*, not a guarantee. The system may decide a span is "computable enough to attempt" based on the current partial graph / current covering node set. The only authoritative test is the **reconstruction attempt** itself.

The span lifecycle includes three states:
- `ATTEMPTABLE` - we think we have enough coverage to try reconstruction
- `PROVEN` - reconstruction succeeds; no uncovered words/phrases remain. **This means we have sufficient facts to reconstruct the text**, not that we have extracted every possible fact from it. PROVEN status indicates the reconstruction threshold has been met.
- `FAILED` - reconstruction fails; uncovered words/phrases remain

No design assumes that "computable" implies success. A span can be attempted and still fail; failure is a normal outcome that drives additional search (or escalation to Clarification Questions).

### 5. Facts Do Not Own Text

- Facts are latent explanations, not text owners.
- Multiple facts may explain overlapping text; some text may only be explainable through composition.
- The mapping between facts and source text is not computable.
- Reconstruction exists precisely because this mapping is unknowable.

### 6. Progress Test for Reconstruction Failures

When reconstruction fails for a region, the system does NOT attempt to classify failure causes directly. Instead, it applies a **progress test** through **anchoring**:

1. Re-attempt extraction over the failing region with expanded context (see Anchoring Unanchored Text below).
2. If reconstruction improves (even partially), the failure was due to insufficient prior understanding. The system continues extraction.
3. If reconstruction does NOT improve after bounded attempts, the system treats the region as **not computably understandable**.

No claim is made about *why* reconstruction failed - whether a fact was missed, the text expresses an unextractable concept, or a relation is implicit or underspecified. This uncertainty is fundamental and unavoidable.

When reconstruction remains impossible (anchoring fails after bounded attempts), the system MUST emit a **Clarification Question** artifact. This is not a recovery mechanism; it is an honest admission of non-understanding.

### 7. Anchoring Unanchored Text

When reconstruction fails and produces uncovered text (via Python diff), that text is **unanchored** - no fact in the current set explains it.

**Example:**
- **Target T(S)**: "Replace partition-style span fragmentation with **work region tracking** over the canonical input string"
- **Reconstructed R(S)**: "Replace partition-style span fragmentation with **work region tracking**"
- **Uncovered text**: "over the canonical input string"
- **Status**: This phrase is UNANCHORED - we don't know what fact/entity explains it

**The Anchoring Operation:**

"Targeted extraction against uncovered words/phrases" is actually an **anchoring search**:

1. **Entity Position Index query**: Given the character position of the uncovered phrase, query the Entity
   Position Index (see Deduplication and Similarity Management) to find entities whose spans are
   positionally closest. These nearby entities provide context for what the uncovered phrase might relate
   to - they are the subjects/objects that appeared in the surrounding text.
2. **Existing fact search via nearby entities**: Using the entities found in step 1, search the fact graph
   for facts involving those entities. These facts may contain relations that explain the uncovered text.
   For example, if the uncovered phrase is "over the canonical input string" at position 100, and the
   Entity Position Index returns "work region tracking" at [80, 99], search for facts involving
   "work region tracking" to find potential explanations.
3. **Context expansion**: If the Entity Position Index and fact search don't yield explanations, expand
   to surrounding text in the source document for additional clues.
4. **New fact extraction**: Pass the uncovered phrase + nearby entities + expanded context to the detail
   extraction sub-agent (Haiku 4.5) to extract NEW details, which are then transformed into anchored
   facts by the fact construction sub-agent (Haiku 4.5).
5. **Anchor validation**: If new facts are extracted, re-run reconstruction to see if uncovered text shrinks.

**Anchoring Outcome Semantics:**

The anchoring search is the mechanism that distinguishes:
- **Missed facts** (anchoring succeeds → new facts reduce uncovered text → continue iteration)
- **Incomprehensible structure** (anchoring fails → no new facts anchor the text → Clarification Question)

**If Anchoring Fails:**

If after bounded attempts we CANNOT find an anchor for the uncovered text:
- The LLM was **unable to understand the structure** of the text
- This is NOT a "missed fact" - it is a structural comprehension failure
- The system MUST emit a **Clarification Question** asking the author what the unanchored text means/belongs to

Anchoring failure is the specific trigger for Clarification Question emission, not merely "stalled progress" in the abstract.

### 8. Island Join Failures

When reconstruction operates on complex text, the system may successfully prove multiple independent segments (called **islands**) but fail to connect them. This is a distinct failure mode from unanchored text.

**Terminology:**
- **Island**: A segment of text that can be independently proven through reconstruction (all its words/phrases are anchored by facts)
- **Join anchor**: The connector that would link two adjacent islands - this could be a conjunction ("and"), preposition ("over", "from"), punctuation (comma), or a relation triplet connecting concepts across the boundary
- **Unanchored join**: Two proven islands with no join anchor between them
- **Boundary**: The character offset where one island ends and another begins

**Example:**
- **Target T(S)**: "Replace partition-style span fragmentation with work region tracking over the canonical input string red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce."
- **Island 1**: "Replace partition-style span fragmentation with work region tracking over the canonical input string" - PROVEN (technical facts anchor all words)
- **Island 2**: "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce." - PROVEN (nonsense facts anchor all words)
- **Join failure**: No fact or relation connects "...input string" to "red flowers..." - the boundary between the two islands has no anchor

**Distinguishing Island Join Failures from Unanchored Text:**
- **Unanchored text**: A segment exists that no fact can explain (the anchoring operation fails to find facts for some words/phrases)
- **Unanchored join**: Both segments ARE explained by facts, but no fact/relation provides a JOIN between them

The key insight is that both islands are individually PROVEN - all their words/phrases are anchored. The failure occurs at the composition level: the system cannot explain why these two proven segments appear adjacent in the source text.

**What Unanchored Joins Indicate:**
The source text may be:
- Malformed or corrupted (accidental concatenation)
- Missing punctuation or explicit connectors that the author intended
- Concatenated from two unrelated sources without proper transition
- Containing an implicit semantic boundary the author did not mark

**System Response to Island Join Failures:**
When the system detects two proven islands that cannot be joined:
1. Record both islands as independently PROVEN with their respective fact anchors
2. Identify the JOIN boundary (character offset where Island 1 ends and Island 2 begins)
3. Attempt bounded join anchoring: search existing facts for any relation that could connect the terminal concept of Island 1 to the initial concept of Island 2
4. If join anchoring fails after bounded attempts, emit a **Clarification Question** specifically requesting: "What is the relationship between [Island 1 terminal phrase] and [Island 2 initial phrase]? These segments appear adjacent but no connecting relation was found."
5. The ReconstructionFailure artifact includes both proven islands and marks the unanchored boundary

This is NOT a case where more extraction would help - both islands already have complete fact coverage. The failure is structural: the source text lacks an explicit connector that the system requires to explain the composition.

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

### 12. Transitive Anchors (Contextual Relations)

Facts can have **transitive anchors** - relations that provide contextual meaning without being part of the fact itself.

**Structure:**
```
Section A conditions ──┐
                       ├──→ Fact D
Section B conditions ──┘
```

The same fact can appear under different condition groups:
- Group A conditions (from Section A) → Fact D
- Group B conditions (from Section B) → Fact D

**Key Properties:**
- Transitive nodes are relations that change the contextual meaning of facts
- Some transitive nodes are conditional (if X then Y applies to Fact D)
- Transitive nodes can be chained (conditions tied to other conditions)
- A fact can present itself under particular groups of conditions
- **Condition groups are deduplicated** - if the same condition appears in multiple sections, it's stored once with multiple references
- This preserves the "same fact, different contexts" relationship without losing information

**Example:**
```
Source text:
  Section A: "If the user is an admin, the system allows deletion."
  Section B: "If the user is an admin, the system allows modification."

Extracted structure:
  Condition: (user, is, admin) [referenced by Section A, Section B]
  Fact 1: (system, allows, deletion) [under Condition]
  Fact 2: (system, allows, modification) [under Condition]
```

The condition is deduplicated; the facts are distinct but share the transitive anchor.

**Implications for Deduplication:**
- When the same condition appears in multiple contexts, it is stored once with pointers to all contexts where it appears
- Facts that appear under the same conditions are not automatically duplicates - they may be distinct facts that share contextual conditions
- The deduplication process (described in "Deduplication and Similarity Management") must consider both fact content AND transitive anchors to determine true duplicates

**Relationship to Reconstruction:**
- Transitive anchors must be preserved during reconstruction - a fact reconstructed in a specific context must include its contextual conditions
- Reconstruction success for a region that contains conditional facts requires reproducing both the facts AND their transitive anchors
- When anchoring unanchored text, the system must consider whether missing transitive anchors (rather than missing facts) are causing reconstruction failures

---

## Objectives and Goals

```
Comprehensive Fact Extraction: Parse an input document of arbitrary length (potentially hundreds of
pages) and extract base facts sufficient for reconstructing the text and deriving all implied facts.
Completeness is defined by derivability: the system must preserve base facts from which all
implications can be logically derived, not extract every possible implication explicitly. This includes
capturing all details, conditions, and relationships described in the text.
Atomic Information Units: Break down complex or compound sentences into atomic facts – each
fact represents a single, indivisible piece of information or a single relationship. No extracted fact
should contain an “and” or multiple assertions in one; each atomic fact should be one complete,
standalone truth.
Deduplication of Repeated Details: If the same fact or detail appears multiple times in the
document (even phrased differently), it should be extracted only once. The system will maintain
references to all locations where that fact appeared, instead of storing duplicates. This creates a
single source of truth for each fact.
Context and Conditional Relationships: Preserve contextual logic. If a fact is only true under
certain conditions (e.g. "If X, then Y"), the system must capture that conditional relationship by
linking the prerequisite fact (X) to the conditional fact (Y) instead of merging them into one
statement. This ensures that context-dependent facts are not lost but represented as such (with a
parent/child or dependency relation).
Traceability: For every extracted fact, provide traceability back to the original document. The output
must include references as character offsets into the canonical input string, indicating where each fact
was found in the source document. If the same fact came from multiple locations, all such character offset
references are recorded.
Ease of Updates: Make it straightforward to add, remove, or modify individual facts in the
knowledge base. Because each fact is stored once, updates to a fact (e.g. changing a requirement
value) can be done in one place and are inherently reflected in all original contexts. The system
should handle merging new information (when new documents or sections are added) by extracting
and deduplicating those new facts as well.
Output for LLM Consumption: Provide the resulting fact database in a format that can be easily
packaged (zipped) and supplied to an LLM or other tools. This includes a clear README/
documentation explaining the contents and how to use them. The facts could be stored as a CSV or
JSON list of facts (with metadata like references and context links), along with any vector index files,
making it easy for an LLM or developer to navigate and search the facts.
Local, Lightweight Implementation: All components should run on a local developer machine (no
cloud dependencies) and favor simplicity and a small footprint. The solution should use Python for
orchestration, and prioritize libraries that are easy to install and quick to initialize. We prefer local
models or open-source tools for NLP tasks. For example, use a local embedding model and an
embedded database instead of a heavy external service. The process should be as automated as
possible (script-driven) so a user can run it on a document file or folder and get the outputs without
manual intervention.
```
## Functional Requirements

### Input Handling

```
Input Format: The system shall accept any document as input. The document could be plain
text, JSON, or other formats (to be clarified, but at minimum unstructured text). No special
formatting is required from the user; the system should be able to process raw text. Multiple
documents or an entire folder of documents should be supported as input (process each file and
aggregate facts).
Large Document Support: It must handle very large documents (hundreds of pages) by processing
them in a streaming or chunked manner so as not to exceed memory or context limits of models.
The entire content will be considered, ensuring no sections are ignored.
```
### Fact Extraction

```
Identify Atomic Facts: The system shall scan the input text and identify individual facts or details
expressed. A fact is defined as a single assertion about one subject (with optionally one predicate
and one object, akin to a single relationship or property). Facts exist on a spectrum from directly
extractable to inferentially derivable:

**Base Facts**: Directly extractable from source text grammar. The source text syntactically contains
all elements of the triplet, and NLTK can validate structural presence. Example: "The widget
supports Bluetooth" → (The widget, supports, Bluetooth).

**Implied Facts**: Derivable from base facts through logical inference. Not directly stated in source
grammar; require reasoning beyond syntax. May become concrete with additional context. Example:
"red flowers scattered across the floor" implies "red flowers are on the floor" (spatial containment
inference). Implied facts are extracted only when contextually important, needed for coreference
resolution, or required for reconstruction of related text.

The system prioritizes base fact extraction. For example, a sentence "The widget supports Bluetooth
and Wi-Fi" contains two base facts: "The widget supports Bluetooth" and "The widget supports Wi-Fi".
Each of these should be extracted separately.
No Compound Statements: If a sentence or phrase contains multiple pieces of information joined
by conjunctions ( and, or, but ), each piece must be extracted as a separate fact. The extraction process
should avoid outputting a combined statement that has more than one independent fact. Any
extracted candidate containing an "and" (or other conjunction implying multiple facts) should be
flagged for splitting or rejected as non-atomic.
Exhaustive Iteration: The extraction should be iterative and continue **until reconstruction succeeds**,
not until all possible facts are extracted. The system will continue attempting to extract facts from
unprocessed work regions until the reconstruction threshold is met - that is, until enough facts have
been found to reconstruct the original text. This implies multiple passes over the content:
Initially, the document is chunked into work regions at sentence boundaries to avoid exceeding model
context limits. Each work region is processed independently for fact extraction. After extracting facts
from a region, mark it as processed and run additional extraction on any remaining unprocessed work
regions to catch facts that may have been missed in earlier passes. Note: Anchoring and reconstruction
validation operate across the entire document and are not affected by chunk boundaries - only the
extraction phase (searching for details) respects chunk boundaries for memory safety. **Termination is
based on reconstruction success** (reaching the sufficiency threshold), not on facts "owning" text
intervals or on exhaustive extraction of every possible fact.
This iterative refinement continues until every work region has been either successfully reconstructed
from extracted facts (reconstruction threshold met) or determined (via validation) to contain only
connective fluff with no meaningful content. This approach ensures we extract **sufficient facts for
reconstruction**, mitigating issues where an LLM might miss critical facts on a first pass. The goal is
sufficiency for reconstruction, not exhaustive extraction of all possible implications.
Span Handling and Work Regions: The system uses interval-based work region tracking rather than
partition-style span fragmentation:
- Canonical text representation: Convert all inputs into a canonical UTF-8 string once at ingestion.
  All subsequent processing operates on this canonical string.
- Work items as unprocessed regions: Maintain a set of unprocessed work regions per validation region.
  Initially, the unprocessed set is the entire region. A Span is an interval [start_char, end_char) into the
  canonical input string. Spans may overlap and nest; they are not required to form a disjoint list.
- Extraction returns source context: Each extracted atomic fact must include source context (character
  offsets for provenance) indicating where the fact was derived from. This is NOT a claim that the fact
  "owns" or "covers" that text - facts EXPLAIN text, they do not own it.
- Update work regions: After extraction from a region, mark it as processed. The system then validates
  via reconstruction: can the original text be explained by the extracted facts? Reconstruction success
  (not "coverage by evidence offsets") determines whether the extraction threshold has been met.
- **Termination**: The extraction/validation loop terminates when **reconstruction succeeds for all work
  regions** (sufficient facts extracted to meet the reconstruction threshold and derivability criterion), or
  when remaining unprocessed regions are classified as allowable connective material ("fluff"), or when the
  system emits Clarification Question artifacts for regions where reconstruction remains impossible after
  bounded progress test attempts. **Termination indicates sufficiency for reconstruction and derivability**:
  the system has extracted enough base facts to (1) reconstruct the original text byte-for-byte, AND (2) derive
  all implied facts when needed. Termination does NOT indicate exhaustive extraction of all possible facts
  and implications. Clarification Questions are required outputs when the progress test shows no improvement -
  the system does not attempt to classify why reconstruction failed.
Per-Region Work Tracking: The system tracks work regions per validation region (document, section,
paragraph, etc.). The unprocessed ranges within each region become the next extraction work items.
Regions that yield no facts during extraction will be evaluated: if the region contains meaningful
words beyond pure fluff, those unprocessed regions are sent back for additional extraction. This
continues **until reconstruction succeeds for all regions** (reconstruction threshold and derivability
criterion met - sufficient base facts to rebuild the text and derive all implications, not exhaustive
extraction of all possible facts) or only connective fluff intervals remain, or until Clarification
Question artifacts are emitted for regions where the progress test shows no improvement after bounded
attempts (see Non-negotiable Invariant #6).
```
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
### Deduplication and Similarity Management

```
Embedding-Based Similarity: The system shall use semantic embedding to compare facts and find
duplicates or near-duplicates. Each extracted fact (as text) will be converted into a high-dimensional
vector representation using a pre-trained embedding model. We will use the Qwen-3 Embedding
model (by Alibaba/QwenLM) for this purpose, leveraging its strong semantic representation
capabilities. This model provides state-of-the-art text embeddings and can capture nuances
in meaning, ensuring that semantically identical facts (even if worded differently) are mapped to
similar vectors in the embedding space.
Local Embedding Computation: The embedding model will be run locally via PyTorch. The Qwen-
series has various sizes (0.6B, 4B, 8B parameters); for a balance of speed and accuracy on a dev
machine, we can start with the 0.6B model variant which yields 1024-dimensional embeddings.
PyTorch will load this model (likely via HuggingFace Transformers), and compute embeddings for
each fact string. This step requires that the system’s environment has the model files (which can be
downloaded or cached) and a capable CPU/GPU. (A GPU is optional but would accelerate embedding
computation).
Vector Database Storage: All fact embeddings will be stored in a vector database to enable
efficient similarity search. We will use an embedded database solution to keep everything local.
SQLite with the sqlite-vss extension is a strong candidate, as it allows storing vectors and
performing k-nearest-neighbor similarity searches directly in a lightweight database file. This
provides privacy (all data is local), simplicity, and portability (a single SQLite file), aligning with
our local-first requirement. The vector DB will maintain columns for: the fact ID, the canonical fact
text, the embedding vector (computed from canonical text), and source context references (character
offsets as provenance markers, NOT ownership claims). An index will be built on the embedding column
(the sqlite-vss extension uses FAISS internally for efficient similarity queries). Note: embeddings
are computed on canonical fact text (not source context) to enable semantic similarity operations on
normalized, self-contained facts.
Entity Position Index: Alongside the semantic vector database, the system maintains a **positional
index** mapping entities to their character offset spans in the canonical input string. This index
enables spatial nearest neighbor search - finding entities that are positionally close to a given
location in the text, regardless of semantic similarity.

The entity position index stores:
- **entity_id**: Unique identifier for each entity (subjects and objects from extracted facts)
- **entity_text**: The normalized entity string (e.g., "the device", "dog")
- **spans**: List of `[start_char, end_char)` ranges where this entity appears in the canonical string
- **fact_ids**: List of facts in which this entity participates

**Spatial Nearest Neighbor Search**: Given a character position X, the index returns entities whose
spans are closest to X, sorted by distance. Distance is computed as `min(|X - span_start|, |X - span_end|)`
for each span. This is fundamentally different from semantic embedding similarity - it finds entities
that are **positionally proximate** in the source text.

**Use Cases**:
1. **Coreference Resolution**: When encountering a pronoun "it" at position 100, query the index for
   entities with spans ending before position 100. The closest entity (e.g., "dog" at [80, 83]) is the
   most likely antecedent candidate.
2. **Anchoring Unanchored Text**: When text at position X cannot be explained by existing facts,
   find nearby entities in the position index. These entities provide context for what the unanchored
   text might relate to.
3. **Island Join Resolution**: When two proven islands cannot be connected, find entities near the
   boundary offset to identify potential bridging concepts.

The position index is built incrementally as facts are extracted. Each fact's subject and object
entities are indexed with their source context spans. This enables efficient positional lookups
without rescanning the source text.
Duplicate Fact Detection: For each fact in the extracted list, the system will query the vector
database for similar entries. Using cosine similarity on embeddings , it will retrieve the nearest
neighbors – i.e., other facts that are potentially semantically identical or overlapping. A similarity
threshold (for example, >0.9 cosine similarity) or a top-K approach will be used to shortlist
candidates. This finds facts that might be duplicates of the current one.
LLM-Assisted Consolidation: The candidate similar facts will be passed to the fact construction
sub-agent for a final determination. The Haiku 4.5 sub-agent will receive
the list of a fact and its nearest neighbors and will analyze their meanings to decide which ones are
truly identical in meaning:
If two or more facts express the same thing, the LLM will label them as duplicates. In that case, those
facts should be consolidated into one. The system will keep one canonical instance of the fact and
remove the others from the list (and from the vector index) to eliminate redundancy.
Prior to removal, all references from the duplicate facts are merged into the canonical fact's
reference list (so no source information is lost). For example, if Fact X and Fact Y are judged identical,
and Fact X came from pages 3 and 10 of the document while Fact Y came from page 15, the unified Fact X
entry will note references to pages 3, 10, and 15.
If the LLM determines the facts are similar but not actually identical in meaning or scope, then they
remain as separate entries. (The similarity search might sometimes group things that are related but
not true duplicates; the LLM can use its understanding to make the call.)
Iterative Duplicate Removal: The deduplication process will iterate through all facts. Each fact
serves as the "query" to find duplicates, which are then consolidated. The order of iteration will be
managed such that once a fact is consolidated and marked as canonical, it won't be processed again
as a duplicate of something else (to avoid bouncing back and forth). By the end of this process, every
remaining fact in the list should be unique in content. This approach, combining embeddings and an
LLM, ensures high accuracy in deduplication – we leverage the speed of vector similarity to narrow
candidates and the judgment of an LLM to handle nuanced cases, rather than relying on a simple
threshold alone.
No Information Loss: Deduplication must not drop any unique information. This means if two
statements differ in any detail (even subtle), they should not be merged. Only truly identical facts (or
ones where one is a rephrasing of another) get merged. The LLM comparison helps guard against
mistakenly merging non-identical facts. All original fact references and context are preserved as
noted.
Transitive Anchors and Context-Aware Deduplication: Per Invariant #12 (Transitive Anchors), the
same fact appearing under different contextual conditions is NOT automatically a duplicate. For
example, if "the system allows deletion" appears under condition A ("if user is admin") and also under
condition B ("if user is superuser"), these are the SAME fact with different transitive anchors (contextual
relations). The fact is stored once, and both conditions reference it. However, if the fact content itself
differs (e.g., "system allows deletion" vs "system allows modification"), these are DIFFERENT facts
even if they share the same conditions. The deduplication process must consider:
- **Fact content deduplication**: Merge identical fact content regardless of transitive anchors
- **Condition deduplication**: Merge identical conditions appearing in multiple contexts (per Invariant #12)
- **Preserve transitive anchor relationships**: Maintain all condition-to-fact and condition-to-condition links
This ensures that "same fact, different contexts" relationships are preserved without information loss,
enabling future editing systems to handle context-specific fact variants (see "Scope Boundary: Extraction
vs Editing" in Ambiguities and Assumptions).
```
### Output and Storage

```
Fact List CSV/JSON: The final output will include a master list of all unique facts extracted from the
input. This can be provided as a CSV file (for easy viewing and editing in spreadsheets) or a JSON file
(for structured programmatic access). Each entry in this list will contain:
A unique Fact ID or index.
**Canonical Fact Text**: The normalized, self-contained atomic statement used for search and deduplication.
This text may have resolved pronouns (or symbolic placeholders like `UNKNOWN_REF_N` for unresolvable
references), normalized formatting, and split conjunctions. This is the primary representation for
semantic operations.
**Source Context** (provenance, not ownership):
- Character offset ranges `[start_char, end_char)` into the canonical input string, indicating the work
  region(s) from which the fact was derived. Multiple ranges are recorded if the fact was discovered
  in multiple locations.
- Optional: verbatim original text snippet(s) corresponding to the source context offsets.
- Note: Source context is provenance (where the system was looking when it discovered the fact),
  NOT text ownership. Facts explain text; they do not own it. Multiple facts may share the same
  source context.
(Optional) untyped link metadata (e.g. if this fact is linked to another fact, list that link without
requiring semantic classification of the relationship type).
(Optional) symbolic placeholder registry: if the canonical fact text contains symbolic placeholders
(e.g., `UNKNOWN_REF_7`), record which placeholders appear and their context for later resolution.
Vector Database File: The SQLite database containing the fact embeddings will be saved (likely as a
.db file). This can be used by an LLM or any tool to perform semantic searches on the facts. For
example, an LLM-based assistant could use the vector DB to find relevant facts given a user query,
enabling question-answering or consistency checking against the extracted facts.
Clarification Questions (Required Output): When reconstruction remains impossible for a region
after bounded progress test attempts, the system MUST emit a Clarification Question artifact. This
is not a recovery mechanism; it is an honest admission of non-understanding. **Clarification Questions
are emitted only when:**
- Reconstruction fails AND anchoring fails (the system cannot find base facts to explain the text), OR
- Base facts exist but derivation is impossible (the logic connecting base facts to required implications is unclear)

**Clarification Questions are NOT emitted** merely because an implied fact was not explicitly extracted.
If the implication is derivable from extracted base facts (per the Derivability Principle, Invariant #11),
no clarification is needed - the information is preserved and can be derived when required.

Each Clarification Question includes:
- doc_id: Identifier of the source document
- region_offsets: Character offset range [start_char, end_char) of the failing region
- original_text: Verbatim quoted original text (exact bytes) from the region
- failure_type: One of:
  - "UNANCHORED_TEXT": Standard failure where some words/phrases cannot be explained by any fact
  - "ISLAND_JOIN_FAILURE": Special failure where multiple proven islands cannot be connected
  - "SYNTACTIC_ORPHAN": Text fragment lacks grammatical structure for triplet extraction
- failure_statement: Varies by failure_type:
  - For UNANCHORED_TEXT: "The system cannot explain how this text should be interpreted using its
    current understanding."
  - For ISLAND_JOIN_FAILURE: "The system can explain each segment independently but cannot
    determine the relationship between them."
  - For SYNTACTIC_ORPHAN: "The text fragment lacks the grammatical structure required to extract
    a fact. The system detected [orphan_type] and cannot legally complete the extraction."
- clarification_request: A minimal request to the author for clarification. Varies by failure_type:
  - For UNANCHORED_TEXT: Request explaining what the unanchored text means/belongs to
  - For ISLAND_JOIN_FAILURE: "What is the relationship between [terminal phrase of Island 1] and
    [initial phrase of Island 2]? These segments appear adjacent but no connecting relation was found."
  - For SYNTACTIC_ORPHAN: "The text fragment '[orphan_text]' cannot be extracted as a fact because
    it lacks [missing_element]. What assertion, if any, does this fragment represent? Please provide
    the complete statement you intended."
- island_context (optional, present for ISLAND_JOIN_FAILURE): Additional context including:
  - islands: List of proven islands with their text and anchoring facts
  - boundary_offset: Character offset of the unanchored join
  - terminal_phrase: Last phrase/concept of Island 1
  - initial_phrase: First phrase/concept of Island 2
- orphan_context (optional, present for SYNTACTIC_ORPHAN): Additional context including:
  - orphan_text: Verbatim text of the syntactic orphan
  - orphan_type: Classification (NOUN_PHRASE_NO_PREDICATE, PARTICIPIAL_PHRASE_NO_SUBJECT, etc.)
  - missing_element: What grammatical element is absent (subject, predicate, object, finite verb)
  - detected_entities: Entities that were legally declared from the orphan
  - detected_attributes: Attributes that were legally annotated
  - fabrication_attempt_id: Reference to FabricationAttempt artifact if illegal extraction was attempted
- author_response: Space for the author's response, which becomes authoritative source data
  when provided. For ISLAND_JOIN_FAILURE, the response should specify the missing connector
  or relationship, or confirm that the segments are indeed unrelated (indicating source text error).
  For SYNTACTIC_ORPHAN, the response should provide the complete assertion intended, which
  the system will then extract as a legal triplet.
Clarification Questions preserve alignment by refusing to invent meaning. They are stored as
structured artifacts (JSON format) alongside the fact list output.
ReconstructionFailure Artifact (Required Output): When reconstruction fails for a span S (i.e., the
span transitions to FAILED state), the system MUST produce a ReconstructionFailure artifact before
attempting bounded iteration recovery. Each ReconstructionFailure artifact includes:
- span_id: Unique identifier for the span
- original_text: Verbatim T(S) - the exact original text of the span
- reconstructed_text: R(S) - the reconstructed candidate produced by Opus
- uncovered_words_phrases: List of exact substrings from T(S) not covered by the reconstruction
  (these are UNANCHORED - no fact in the current set explains them)
- substitutions_used: List of all substitutions applied (from Python + Opus), each with:
  - input_token: Original token
  - substituted_token: Replacement token
  - source: Dictionary/library source and version
- facts_used: List of fact IDs / building blocks used in the reconstruction attempt
- proof_trace: The step-by-step derivation trace from Opus
- anchoring_attempts: List of anchoring operations performed on uncovered text, each with:
  - attempt_number: Sequential attempt number (1, 2, ..., max_attempts)
  - uncovered_phrase: The unanchored text being targeted
  - context_expansion: Surrounding text used to provide clues
  - existing_facts_searched: Fact IDs checked for related concepts
  - new_facts_extracted: List of new fact IDs extracted (if any)
  - uncovered_reduction: Whether uncovered text shrank after this attempt (true/false)
- island_join_failure (optional, present when failure is due to unanchored join): Structure for
  island join failures containing:
  - failure_type: "ISLAND_JOIN_FAILURE" (distinguishes from standard unanchored text failures)
  - islands: List of proven islands, each with:
    - island_id: Unique identifier for this island
    - text: Verbatim text of the island
    - char_offsets: [start_char, end_char) into original_text
    - status: "PROVEN" (all words/phrases anchored)
    - anchoring_facts: List of fact IDs that anchor this island
  - unanchored_boundaries: List of boundaries between islands that lack join anchors, each with:
    - boundary_offset: Character offset where Island N ends and Island N+1 begins
    - island_before_id: ID of the island ending at this boundary
    - island_after_id: ID of the island starting at this boundary
    - terminal_phrase: Last phrase/concept of the preceding island
    - initial_phrase: First phrase/concept of the following island
    - join_anchoring_attempts: List of attempts to find a join anchor, each with:
      - attempt_number: Sequential attempt number
      - relations_searched: Relation triplets checked for connecting the islands
      - connectors_searched: Conjunctions/prepositions/punctuation patterns checked
      - join_anchor_found: false (always false if this artifact exists)
After producing this artifact, the system executes bounded anchoring iterations:
1. Anchoring search against uncovered words/phrases (context expansion + existing fact search +
   new fact extraction via two-phase pipeline: detail extraction with Haiku 4.5 sub-agent 1, then fact construction with Haiku 4.5 sub-agent 2)
2. Update the partial graph/fact set with any newly anchored facts
3. Rerun Opus reconstruction (with Python helpers)
If anchoring stalls (no reduction in uncovered words/phrases after bounded attempts), the system
escalates to Clarification Question emission. This indicates structural comprehension failure, not
merely a missed fact. ReconstructionFailure artifacts are stored as structured JSON and provide
essential debugging/audit information for the reconstruction and anchoring process.
FabricationAttempt Artifact (Required Output): When the validation layer detects an illegal fact
(a triplet that violates source grammar through fabricated structure), the system MUST produce a
FabricationAttempt artifact instead of including the illegal triplet in the fact list. Each
FabricationAttempt artifact includes:
- artifact_id: Unique identifier for this fabrication attempt
- source_text: Verbatim text span from which extraction was attempted
- source_offsets: Character offset range [start_char, end_char) of the source span
- attempted_triplet: The illegal triplet that was generated, structured as:
  - subject: The extracted subject (may be fabricated)
  - predicate: The extracted predicate/verb (may be fabricated)
  - object: The extracted object (may be fabricated)
- violation_type: One of:
  - "HIDDEN_COPULA": Verb added to noun phrase (is/are/was/were fabricated)
  - "ATTRIBUTE_TO_PROCESS": Static adjective converted to temporal verb
  - "PRONOUN_CONCORD": Number/person/gender agreement violation
  - "TENSE_FABRICATION": Tense assigned to timeless construction
  - "FORCED_SUBJECT": Entity invented to complete triplet
- fabricated_element: Specific element that was fabricated:
  - element_type: "subject" | "predicate" | "object" | "tense" | "agreement"
  - fabricated_value: The value that was invented
  - source_justification: null (no source justification exists - that's why it's fabricated)
- legal_extractions: What WAS legally extractable from the source text:
  - entity_declarations: List of entities that can be declared (name + source offsets)
  - attribute_annotations: List of attributes/modifiers present (entity + attribute + source offsets)
- syntactic_analysis: Grammatical analysis of why the triplet is illegal:
  - source_structure: Detected grammatical structure (e.g., "noun_phrase", "participial_phrase")
  - required_structure: Structure required for valid triplet (e.g., "finite_clause")
  - missing_elements: List of grammatical elements absent from source
- clarification_question_id: Reference to the Clarification Question emitted for this orphan
- detection_rule: Which validation rule caught the fabrication (e.g., "VERB_PRESENCE_CHECK")
FabricationAttempt artifacts serve as audit records showing that the system detected and rejected
illegal extractions. They enable debugging of extraction prompts and provide transparency about
why certain text fragments yielded Entity Declarations rather than Relation Triplets. These artifacts
are stored as structured JSON alongside other output artifacts.
InvalidInferenceAttempt Artifact (Required Output): When the Inference Validation Layer detects an
invalid inference (an Implied Fact that is not logically derivable from base facts), the system MUST
produce an InvalidInferenceAttempt artifact instead of including the invalid inference in the fact list.
Each InvalidInferenceAttempt artifact includes:
- artifact_id: Unique identifier for this invalid inference attempt
- source_text: Verbatim text span from which the inference was attempted
- source_offsets: Character offset range [start_char, end_char) of the source span
- base_facts: List of base fact IDs from which the inference was claimed to derive
- attempted_inference: The invalid Implied Fact that was generated, structured as:
  - subject: The inferred subject
  - predicate: The inferred predicate/relation
  - object: The inferred object
  - claimed_derivation: The logical steps claimed to derive this inference
- inference_violation_type: One of:
  - "INVALID_COREFERENCE": Pronoun reference violates agreement rules (number/gender/person mismatch)
  - "UNGROUNDED_IMPLICATION": Claimed implication doesn't logically follow from base facts
  - "CONTEXT_BOUNDARY_VIOLATION": Inference spans unrelated sections without explicit connection
  - "PHANTOM_ENTITY": Inferred entity not present in base facts or source text
- violation_details: Specific details about why the inference is invalid:
  - For INVALID_COREFERENCE:
    - pronoun: The pronoun used
    - claimed_antecedent: The entity it was claimed to refer to
    - agreement_mismatch: Description of number/gender/person disagreement
  - For UNGROUNDED_IMPLICATION:
    - claimed_logical_step: The inference rule that was claimed
    - why_invalid: Explanation of why the implication doesn't follow
  - For CONTEXT_BOUNDARY_VIOLATION:
    - section_1: The section containing the antecedent
    - section_2: The section containing the pronoun/reference
    - boundary_type: Type of boundary crossed (e.g., "heading", "paragraph")
  - For PHANTOM_ENTITY:
    - phantom_entity: The entity that was fabricated
    - searched_facts: List of fact IDs searched for the entity
- valid_base_facts: List of base facts that WERE validly extracted from the same source text
- clarification_question_id: Reference to the Clarification Question emitted for this invalid inference
- detection_layer: "INFERENCE_VALIDATION" (to distinguish from grammar fabrications caught by NLTK)
- opus_trace: The reconstruction proof trace where Opus detected the invalid inference
InvalidInferenceAttempt artifacts serve as audit records showing that the system detected and rejected
invalid logical inferences. They enable debugging of inference logic and provide transparency about
why certain Implied Facts were rejected even though they were grammatically well-formed. These artifacts
complement FabricationAttempt artifacts (which catch grammar issues) by catching logical/inference issues.
Both artifact types are stored as structured JSON alongside other output artifacts.
Syntactic Orphan Registry (Required Output): The system MUST maintain a registry of all syntactic
orphans encountered during extraction. Each entry includes:
- orphan_id: Unique identifier
- orphan_text: Verbatim text of the orphan fragment
- source_offsets: Character offset range [start_char, end_char)
- orphan_type: Classification of the grammatical incompleteness:
  - "NOUN_PHRASE_NO_PREDICATE": Noun phrase without verb
  - "PARTICIPIAL_PHRASE_NO_SUBJECT": Participle without subject
  - "PREPOSITIONAL_PHRASE_UNANCHORED": Prepositional phrase without clause
  - "PRONOUN_NO_ANTECEDENT": Pronoun without identifiable referent
  - "FRAGMENT_UNCLASSIFIED": Other incomplete structure
- legal_extraction: What was extracted (Entity Declaration or Attribute Annotation)
- fabrication_attempt_id: Reference to FabricationAttempt artifact if extraction was attempted
- clarification_question_id: Reference to emitted Clarification Question
- resolution_status: "PENDING" | "RESOLVED" (updated when author responds)
- author_resolution: Author's clarification response (when provided)
The Syntactic Orphan Registry enables tracking of all text fragments that could not be legally
extracted as triplets, ensuring none are silently dropped or illegally fabricated.
Work Region Report (for Review): For transparency and verification, the system can output an
additional report or log that shows the processing state for each region of the original document:
which work regions have been processed and successfully reconstructed, which regions remain
as connective fluff, and which regions have Clarification Questions emitted. After the
extraction/validation cycle completes, any remaining unprocessed regions should either contain
only connective fluff (e.g., "Therefore," "In addition,") or have corresponding Clarification
Questions. These fluff regions will be listed in the report with the determination that they contain
no meaningful content. This allows human reviewers to verify that unprocessed regions were
correctly identified as fluff rather than missing actual facts. The report functions as a complete
work region map showing each text region and its extracted facts, confirmation of fluff status,
or reference to emitted Clarification Questions.
README/Documentation: A README file will accompany the output, explaining the structure of the
files and how to use them. It will document:
The format of the fact list and how to interpret the references and relations.
How to load and query the vector database (with example Python code or SQL queries using sqlite3).
How to update a fact (e.g., editing the CSV and re-running a script to update the vector index).
How to add a new document and merge it (e.g., running the extraction on a new file and then using
the deduplication routine to integrate new facts).
Potential pitfalls or things to note (for instance, that contextual relationships exist and must be
considered when interpreting a fact).
```
### Update and Maintenance Requirements

```
Adding New Documents: The system should allow new documents or updated documents to be
processed and merged into the existing fact base. This means the extraction pipeline can be re-run
on new input, yielding new facts which are then compared (via embeddings) against the existing
facts to integrate without duplication. The output should remain a single consolidated fact list.
(Internally, we might either re-run the entire extraction on the combined old+new corpus or do an
incremental extraction on just the new text and then deduplicate against the stored facts.)
Removing/Modifying Facts: If a fact is identified as outdated or incorrect, one should be able to
remove or edit that fact in the fact list. Because the facts are atomic and referenced, removal/edit is
straightforward: e.g., delete or change the entry in the CSV/JSON, and then update the vector store
accordingly (remove or recompute that vector). The documentation will include instructions for this.
There should be scripts or functions to facilitate these updates (for instance, a script to regenerate
the SQLite index from the CSV after manual edits).
No Duplication on Re-run: If the extraction is re-run on the same document (or overlapping
documents), the system should not create duplicate fact entries. This implies either the
deduplication step must recognize and merge them, or the extraction process itself can be made
aware of an existing facts database to avoid extracting something already known. A simpler
implementation is to always run extraction fresh and then rely on the dedup step to merge
duplicates, ensuring idempotency over multiple runs.
Conflict Detection (Future): While not in the initial scope, the groundwork laid by this system will
make it easier to detect contradictory facts in the future. Once all facts are unique and atomic, one
can programmatically or via LLM check for logical conflicts (e.g., Fact A says the limit is 5, Fact B says
the limit is 10). The system’s design should not preclude adding such a feature later. (At present,
contradiction resolution is not handled – similar academic efforts note that conflict resolution may
require additional logic .)
```
### Performance and Constraints

```
Local Execution: The entire pipeline (extraction, embedding, storage, querying) must run locally on
a developer's machine. It should not require any cloud services. The system uses Claude Code as the
execution harness with Claude sub-agents for fact extraction:
- **Haiku 4.5 (sub-agent 1)** performs detail extraction, scanning source text for raw observations, statements, and claims
- **Haiku 4.5 (sub-agent 2)** performs fact construction, transforming details into anchored atomic facts with triplet structure
- **Opus 4.5** orchestrates the pipeline, runs reconstruction proofs, and performs QA validation
- Sub-agents communicate via file I/O to avoid filling orchestrator context
- Python scripts are invoked as tools by agents for deterministic operations
- If local models + deterministic rules suffice, the reasoning model is not invoked.
Startup Time: Tools and models chosen should favor fast initialization. For example, SQLite starts
near-instantly. The Qwen-3 0.6B embedding model, while not tiny, is reasonably sized and can load
on CPU or GPU without excessive delay (compared to very large models). We avoid heavy
frameworks that require lengthy setup. The embedding and database libraries will be added to the
project's Python environment (e.g., listed in pyproject.toml) so they can be installed easily. This
includes transformers (for the Qwen model), torch, sqlite-vss (for vector search), and
nltk (for grammar validation). NLTK model loading is fast and the averaged perceptron tagger
can be cached between validation runs. For higher accuracy, NLTK can integrate with Stanford
CoreNLP or use the more sophisticated parsing models available in the library.
Memory/Storage Footprint: All data (embeddings, facts, indices) will be stored either in memory or
lightweight files. The SQLite DB ensures the entire vector index can reside in a single file (which
could be a few MBs to hundreds of MBs depending on number of facts and vector size). The fact list
CSV/JSON will be as large as the information content of the source document, which is unavoidable, but
eliminating duplicates means it could be smaller than the original document if there were many
repetitions.
Accuracy Priority: The system favors accuracy over speed. It is acceptable if the extraction and
consolidation take multiple passes or LLM calls, as long as the final result meets the reconstruction
threshold. For instance, multiple iterations of LLM extraction (per span) will be used to ensure
**sufficient facts for reconstruction are extracted**. We acknowledge this may be time-consuming on a
very large document, but reaching the sufficiency threshold is critical.
The process can be semi-automated such that an orchestrating script or agent handles the multi-
step pipeline without user intervention (the user only waits for the final outputs).
No UI (Script-Driven): There will be no graphical user interface. The system will be operated via
scripts/command-line or through an AI agent interface (for example, an LLM with tool use abilities
could trigger the scripts). This means all interactions are via files and console logs. For example, a
developer or an agent provides the input file path to a script, the script runs extraction and outputs
the files, and then perhaps the agent or developer reviews the results. The lack of UI is acceptable
because the primary consumer of this output might be another LLM or a developer doing analysis.
```
## System Design and Implementation Details

### Overall Architecture

The system is organized as an **automated pipeline** of steps, each responsible for a part of the
transformation from raw document to structured facts. Below is a high-level breakdown of the workflow:

```
Initial Span Creation: Read the entire input document (or documents) and treat it as one large text
span. This span is the initial search space from which facts will be extracted.
Two-Phase Fact Extraction Pipeline: The extraction process consists of two sequential phases:

**Phase 1 - Detail Extraction (Haiku 4.5 sub-agent 1):** Scan the current span of text to identify
raw "details" - observations, statements, and claims present in the text. The prompt instructs the sub-agent
to extract any factual content without requiring it to be in final triplet form or fully anchored. Details
may be incomplete, unanchored, or not yet in proper atomic fact structure.

**Phase 2 - Fact Construction (Haiku 4.5 sub-agent 2):** Take the details from Phase 1 and transform
them into proper atomic facts. This phase anchors each detail to the source text, validates the triplet
structure (subject-predicate-object), and ensures each fact is self-contained and properly contextualized.
The sub-agent is responsible for the anchoring operation - connecting raw details to their source
context and forming valid triplet-structured facts.
Fact Post-processing: For each extracted candidate, apply validation and cleaning:
Ensure it's atomic (split or refine if not).
Resolve any co-references when possible (replace pronouns with actual nouns using context). When
coreference resolution is NOT computable, produce symbolic placeholders (e.g., `UNKNOWN_REF_7`)
rather than guessing.
Normalize formatting (e.g., remove trailing periods, ensure consistent capitalization for facts).
Preserve source context: record the character offsets of the work region(s) from which the fact was
extracted. This source context is provenance (not ownership) and enables reconstruction testing.
**NLTK Grammar Validation (Pre-Filter):** Before triplets proceed to Inference Validation and Opus
reconstruction, run NLTK validation on the source text to flag potential illegal fabrications. **NLTK's
scope is limited to syntax and grammar** - it checks that the source text contains the grammatical
structures (verbs, subjects, proper agreement) that the extracted triplet claims. NLTK does NOT validate
logical inferences; that is handled by the Inference Validation Layer. Flagged triplets are routed to
review/escalation rather than auto-rejected. See the "Illegal Fact Fabrication" section for detailed
validation rules and the "Grammar Validation Layer (NLTK)" section in Tools and Technologies for
configuration options.
After this step, we have a list of cleaned atomic facts, each with both canonical fact text (normalized,
self-contained) and source context (provenance markers into the canonical input string).
Work Region Tracking: After extraction from each region, update the processing state:
Each extracted atomic fact includes source context (character offsets for provenance) indicating
where the fact was derived from. This is NOT a claim that facts "own" text.
Mark processed regions and validate via reconstruction: can the original text be explained by the
extracted facts? Spans may overlap and nest; they are not required to form a disjoint partition.
The unprocessed ranges within each validation region become the next extraction work items.
Iterative Extraction Loop: For each remaining unprocessed work region that has not yet yielded facts,
repeat steps 2-4:
Run the two-phase extraction pipeline (Phase 1: Detail Extraction with Haiku 4.5 sub-agent 1,
then Phase 2: Fact Construction with Haiku 4.5 sub-agent 2) on the unprocessed work region.
Validate and add new facts, then test reconstruction success. This loop continues **until reconstruction
succeeds for all work regions** (reconstruction threshold and derivability criterion met - sufficient base
facts to rebuild the text and derive all implications). At that point, the extraction phase is complete.
Remaining unprocessed regions will be verified via reconstruction; those containing meaningful
content will cycle back for additional extraction. The process ends when reconstruction succeeds
(reconstruction threshold and derivability criterion met - enough base facts to reconstruct and derive
all implications, not all possible facts explicitly extracted) or only connective fluff regions remain,
along with a comprehensive list of facts with references, or when the system emits clarification
questions for unresolved gaps (anchoring failure or derivation impossibility, not merely unextracted
implications).
Note: This extraction phase is done by the two-phase pipeline (detail extraction followed by fact formation).
After the pipeline completes, Opus performs formal proof reconstruction (next step) which may identify gaps
that trigger additional extraction iterations, creating a feedback cycle **until reconstruction confirms
success** (spans transition to PROVEN - sufficient base facts for reconstruction and derivability, not
all facts explicitly extracted) or emits Clarification Questions for regions that cannot be explained
(after spans FAILED and bounded iterations stalled - indicating anchoring failure or derivation
impossibility, not merely unextracted implications). A larger reasoning model is only invoked when
strictly necessary (e.g., borderline dedup adjudication or fluff classification when deterministic
rules fail).
Opus-Led Formal Proof Reconstruction: After the two-phase extraction pipeline completes,
Opus (the reconstruction agent) performs formal proof reconstruction. This is the core validation
mechanism. **Opus performs both reconstruction validation AND inference validation** - it validates
that facts can rebuild the text AND that any Implied Facts are logically derivable from base facts.
For each target span S in ATTEMPTABLE state:

**Reconstruction Proof Algorithm:**
- Input to Opus: span text T(S) (verbatim), current fact set/building blocks, prior failure artifacts
- Opus task: produce step-by-step formal reconstruction of T(S) from facts ("like solving a math problem")
- **Inference validation**: For any Implied Facts used, Opus must justify the inference through valid logical steps
- Opus output: reconstructed candidate R(S) + proof trace describing derivation from facts + substitutions + inference justifications
- Validation: compare R(S) to T(S), compute uncovered words/phrases

**Python Helper Substeps (Deterministic Only):**
Opus may delegate to Python for mechanical operations (Python does NOT infer missing structure):
- A) Grammar mechanics: deterministic clause joining, conjunction scaffolding, punctuation/whitespace
- B) Dictionary/synonym substitutions: logged with input token -> substituted token, source/version
- C) Deterministic alignment/diff: character-level diff between R(S) and T(S), returns uncovered segments

**Span State Transitions:**
- If uncovered words/phrases is empty and proof trace is consistent: span -> PROVEN (success).
  **PROVEN means sufficient facts for reconstruction**, not all facts extracted.
- If uncovered words/phrases remain: span -> FAILED, produce ReconstructionFailure artifact

**Failure Handling:**
If reconstruction fails (span is FAILED), Opus knows only one thing: the current understanding is
insufficient to explain the text. Opus does NOT determine whether a fact was missed, the text
expresses an unextractable concept, or a relation is implicit. This uncertainty is fundamental.

The system produces a ReconstructionFailure artifact with: span_id, verbatim T(S), R(S), uncovered
words/phrases (exact substrings), substitutions used, facts/building blocks used, and proof trace.

**Progress Test on Failure (via Anchoring):** After producing the ReconstructionFailure artifact, execute
bounded anchoring iterations to attempt to anchor the uncovered (unanchored) text:
1. **Anchoring search** against uncovered words/phrases:
   - Entity Position Index query: Find entities positionally closest to the uncovered phrase
   - Existing fact search via nearby entities: Search facts involving those entities for explanations
   - Context expansion: Look at surrounding text for additional clues
   - New fact extraction: Pass uncovered phrase + nearby entities + context to the two-phase pipeline
     (Phase 1: Detail Extraction with Haiku 4.5 sub-agent 1, then Phase 2: Fact Construction/Anchoring
     with Haiku 4.5 sub-agent 2)
2. Update the partial graph/fact set with any newly extracted facts
3. Rerun Opus reconstruction (with Python helpers)
4. If uncovered text shrinks, anchoring succeeded for some text - continue iterations
If anchoring stalls (no reduction in uncovered words/phrases after bounded attempts), emit a Clarification
Question. This indicates structural comprehension failure - the system cannot understand what the
unanchored text means or belongs to.

**Clarification Question Emission:** When anchoring fails after bounded attempts (uncovered/unanchored
text cannot be reduced), the system MUST emit a Clarification Question artifact containing doc_id,
region_offsets, verbatim original text (including the unanchored portions), a failure statement, and
space for author response. This is an honest admission of structural comprehension failure - the system
cannot understand what the unanchored text means or belongs to. This is not a recovery mechanism.
**Per the Derivability Principle (Invariant #11)**, Clarification Questions are emitted only when:
(1) the system cannot find base facts to explain the text (anchoring failure), OR (2) base facts exist
but the logic connecting them to required implications is unclear (derivation impossibility). Clarification
Questions are NOT emitted merely because an implied fact was not explicitly extracted - if the implication
is derivable from base facts, no clarification is needed. Author responses become authoritative source
data. A larger reasoning model may optionally be used to generate high-quality Clarification Questions,
but template-driven generation is acceptable if local resources suffice.

**Zero-Fact Span Handling:** For spans with no atomic facts, Opus applies the same formal reconstruction
test. If meaningful content exists beyond pure fluff, reconstruction fails (uncovered words/phrases
remain) and triggers the progress test cycle. Only pure fluff spans (e.g., "Therefore,") legitimately
have zero facts and transition to PROVEN with empty reconstruction.

This formal proof approach is more epistemically honest than claiming "coverage" because it
acknowledges that the mapping between facts and source text is not computable.
Embedding of Facts: Take the final list of extracted facts (at this stage, duplicates may still exist in
the list) and compute embeddings for each canonical fact text using the Qwen-3 Embedding model.
Embeddings are computed on canonical text (the normalized, self-contained representation) rather
than source context, enabling semantic similarity operations on normalized facts. This involves
tokenizing each canonical fact text and running it through the model to obtain a numeric vector.
This step will be implemented as a Python module (e.g., using HuggingFace's transformers and
AutoModel for Qwen). All embeddings are stored in memory initially. Source context (provenance
markers) is preserved alongside embeddings but not used for embedding computation.
Initialize Vector Store: Set up the SQLite database with the vector similarity extension. Create a
table for facts, and insert each fact with its embedding. (If using sqlite-vss, we define a VSS
index on the embedding column which allows ANN searches via Faiss under the hood .) This step
may be encapsulated in a script (for example, store_facts.py) which reads the facts list and
builds the database. The pyproject.toml will include dependencies like sqlite-vss to ensure
the environment has the extension available.
Semantic Deduplication Loop: Iterate through the fact list and perform the deduplication:
For a given fact (call it Fact A), query the vector index for the top N most similar other facts.
Collect those candidates (excluding Fact A itself) that exceed a certain similarity threshold or that
form the top results up to a reasonable number.
Invoke the Haiku 4.5 fact construction sub-agent (in deduplication mode) with a prompt that lists Fact A and
the candidate facts, asking the sub-agent to compare them and identify which of these are essentially
the same fact. The prompt will emphasize to only mark facts as duplicates if they truly mean the
same thing in the context of the product (ignoring trivial wording differences). For borderline cases
where the local models disagree, a larger reasoning model may optionally be invoked to adjudicate,
but this is minimized - local models + deterministic rules should handle most cases.
The models return a decision, for example: " Fact B and Fact C describe the same detail as Fact A,
Fact D is slightly different. "
Based on this, the system merges duplicates:
Mark Facts B and C as duplicates of A. Merge their reference locations into Fact A’s record.
Remove B and C from the fact list (or mark them as inactive). Also remove them from the
SQLite index (or we could keep them but flagged as dupes not to be returned – however,
simplest is to remove to avoid further confusion).
Fact A remains as the canonical fact for that piece of information.
Continue this for each fact in the list. (If a fact has already been removed as a duplicate of a previous
one, skip it.) This results in a reduced list where ideally each entry is unique. The order of traversal
can be the original extraction order or sorted by some key; it shouldn’t matter as long as all get
checked. We just ensure that once a fact is merged into another, we don't process it again separately.
Note: This approach is a conservative, LLM-verified deduplication. It ensures we don't accidentally
merge non-identical facts, at the cost of more LLM calls. In the future, if performance needs to be
improved for large sets, a purely embedding similarity threshold could auto-merge obvious
duplicates without an LLM. However, given the focus on accuracy and zero info loss , we use the
LLM to double-check each merge in this design.
Finalize Unique Facts Database: After deduplication, update the outputs:
Generate the final CSV/JSON of facts with dual representation:
- Each entry includes canonical fact text (for search/dedup) and source context (provenance markers).
- Updated references (after merging) preserve all source context from merged duplicates.
- Any noted relationships are included as untyped links.
- Each fact has a stable identifier (e.g., Fact1, Fact2, ... or a UUID) for reference.
- Symbolic placeholders (e.g., `UNKNOWN_REF_N`) are catalogued if present in canonical text.
Update the vector database if needed: rebuild the vector index with only the unique facts.
(Clear the table and re-insert all final facts with their canonical text and embeddings. Source
context is stored for provenance but NOT used for embedding computation. Since the number is
now smaller, queries might be faster and there's no risk of matching a removed duplicate.)
Produce the work region report for completeness.
Collate the documentation (if not already written, finalize the README instructions now,
possibly automatically appending any statistics like number of facts extracted, etc.).
Packaging: All output files (fact CSV/JSON, SQLite .db, README, and any other logs) will be placed in
a designated output folder. This folder can be zipped by the user or agent and shared or used by
other tools. The README will guide how to utilize these files for further tasks (like loading into an
LLM context or running queries).
```
### Roles of LLM Sub-Agents

```
Two-Phase Extraction Pipeline (Detail Extraction & Fact Construction): The system uses a sequential
two-phase pipeline with specialized sub-agents for each phase:

**Phase 1 - Detail Extraction (Haiku 4.5 sub-agent 1):**
- **Role**: Scan source text for raw "details" - observations, statements, claims
- **Output**: Raw details that may be incomplete, unanchored, or not yet in triplet form
- **Prompt Example**: "Extract all observations, statements, and claims from the following text. List
  them as bullet points. Details do not need to be in final triplet form - just capture what you observe."
- **Key Distinction**: This phase extracts content WITHOUT requiring it to be fully formed facts. Details
  are raw material for the next phase.

**Phase 2 - Fact Construction & Anchoring (Haiku 4.5 sub-agent 2):**
- **Role**: Transform raw details into anchored atomic facts with triplet structure
- **Input**: Details from Phase 1 + source text context
- **Output**: Anchored facts in subject-predicate-object triplet form with source context
- **Anchoring Operation**: This phase is responsible for anchoring - connecting raw details to source text,
  validating triplet structure, and ensuring facts are self-contained and properly contextualized
- **Prompt Example**: "Transform the following details into atomic facts. Each fact must: (1) be anchored
  to specific text in the source, (2) follow subject-predicate-object structure, (3) be self-contained.
  Use actual names instead of pronouns."

**Phase 3 - Duplicate Consolidation (Haiku 4.5 sub-agent 2):**
- **Role**: Given a set of facts that are potentially duplicates, decide which ones mean the same thing
- **Prompt Example**: "We have the following facts from a document. Determine if any of these are
  semantically identical (i.e., they describe the same requirement or detail). List which ones are
  duplicates of each other."
- For borderline cases, a larger reasoning model may optionally adjudicate, but this is minimized.

Reconstruction Agent (Opus-Led Formal Proof Reconstruction): The reconstruction agent (Opus)
constructs a formal reconstruction proof for each target span. This is the core validation mechanism.
Reconstruction is an explanation test, not a coverage proof. **Opus validates whether the system's
current understanding is sufficient to explain the original text through step-by-step formal reasoning,
AND validates that any Implied Facts are logically derivable from base facts.**

**Opus's Dual Validation Role:**
1. **Reconstruction validation**: Can the facts rebuild the original text byte-for-byte?
2. **Inference validation**: Are any Implied Facts logically sound and properly derived from base facts?

Opus performs inference validation (requires reasoning) while NLTK performs grammar validation
(deterministic, rule-based). Both must pass for facts to be valid.

**Opus Reconstruction Proof Algorithm:**
For each target span S with original text T(S):

* Input to Opus:
  - The span text T(S) (verbatim) and immediate context if allowed
  - The current fact set / building blocks relevant to S (from the partial graph)
  - Any prior failure artifacts for S (uncovered words/phrases, prior attempts)

* Opus task:
  - Produce a **step-by-step formal reconstruction** of T(S) from the facts ("like solving a math problem")
  - Use substitutions / logical connections where needed
  - **Validate any Implied Facts**: For each Implied Fact used, provide inference justification showing
    logical derivability from base facts according to Inference Validation Rules
  - Output:
    - A reconstructed candidate R(S) (string)
    - A proof trace describing how it was derived from facts + substitutions + inference justifications

* Validation for the span:
  - Compare R(S) to T(S)
  - Compute uncovered words/phrases in T(S) not covered by the reconstruction
  - **Check inference validity**: If any Implied Facts were used, verify inference justifications are sound
  - Uncovered words/phrases become the next extraction targets
  - Invalid inferences trigger InvalidInferenceAttempt artifacts

**Python Helper (Deterministic Substeps Only):**
Python is introduced only to reduce Opus cost on mechanical operations. Python does NOT infer
missing structure. Python may be used by Opus (explicitly invoked) for:

A) Grammar mechanics (hard rules):
   - Deterministic clause joining
   - Deterministic conjunction scaffolding
   - Deterministic punctuation/whitespace handling per a fixed library/rule set

B) Dictionary/synonym substitutions (explicitly allowed):
   - Synonym/lemma/morphology substitution via a dictionary library
   - All substitutions must be logged (input token -> substituted token, dictionary source/version)

C) Deterministic alignment/diff:
   - Character-level diff between R(S) and T(S)
   - Return uncovered words/phrases in T(S) (verbatim segments)

Python outputs are utilities; Opus remains responsible for the proof decisions.

**Success Criteria (Span is "Proven Computable"):**
A span is only *proven* computable when:
- uncovered words/phrases is empty (per the compare step), and
- the proof trace is internally consistent (substitutions logged; facts referenced)

**PROVEN status means the reconstruction threshold has been met** - the system has sufficient facts to
reconstruct the text, NOT that it has extracted every possible fact from it. This is a **sufficiency test**,
not a **completeness test**.

This explicitly allows: "we thought it was computable; we tried; it failed."

**Failure Semantics:** If reconstruction fails for a region, Opus knows only one thing: the current
understanding is insufficient to explain the text. Opus does NOT determine whether a fact was
missed, the text expresses an unextractable concept, or a relation is implicit or underspecified.
This uncertainty is fundamental and unavoidable.

**Progress Test (via Anchoring):** When reconstruction fails, Opus applies a progress test via the
anchoring operation rather than attempting to classify failure causes:
1. **Anchoring search** on uncovered (unanchored) text:
   - Entity Position Index query: Find entities positionally closest to the uncovered phrase
   - Existing fact search via nearby entities: Search facts involving those entities for explanations
   - Context expansion: Look at surrounding text for additional clues
   - New fact extraction: Pass uncovered phrase + nearby entities + context to the two-phase pipeline
     (Phase 1: Detail Extraction with Haiku 4.5 sub-agent 1, then Phase 2: Fact Construction/Anchoring
     with Haiku 4.5 sub-agent 2)
2. If reconstruction improves (uncovered text shrinks), anchoring succeeded - continue iterations.
3. If reconstruction does NOT improve after bounded anchoring attempts, treat the region as not
   computably understandable (structural comprehension failure).

**Clarification Question Emission:** When anchoring fails after bounded attempts (no reduction in
uncovered/unanchored text), the system MUST emit a Clarification Question artifact. This is not a
recovery mechanism; it is an honest admission of structural comprehension failure - the system
cannot understand what the unanchored text means or belongs to. **Per the Derivability Principle
(Invariant #11)**, Clarification Questions are emitted only when: (1) the system cannot find base facts
to explain the text (anchoring failure), OR (2) base facts exist but derivation is impossible (the logic
connecting base facts to required implications is unclear). Clarification Questions are NOT emitted
merely because an implied fact was not explicitly extracted. The Clarification Question contains
doc_id, region_offsets, verbatim original text (including the unanchored portions), a failure statement,
and space for author response which becomes authoritative source data. A larger reasoning model may
optionally be used to generate high-quality Clarification Questions, but template-driven generation is
acceptable.

**Zero-Fact Span Handling:** For spans where the extraction pipeline found no facts, Opus applies the
same formal reconstruction test. If the span contains meaningful content beyond pure fluff
(connectives, articles), reconstruction will fail and trigger the progress test cycle. Only pure fluff
spans (e.g., "However,") legitimately have zero facts and successful "empty" reconstruction.

Reasoning Model Policy (Minimized): A larger reasoning model is used only when strictly necessary:
- Generating high-quality Clarification Questions (optional; can be template-driven)
- Adjudicating borderline dedup merges when local models disagree (optional)
- Classifying text as fluff vs meaningful when deterministic rules cannot decide (optional)
If local models + deterministic rules suffice, the reasoning model is NOT invoked. This minimizes
cost and latency while maintaining accuracy.

This formal proof approach is more epistemically honest than claiming "coverage" because it
acknowledges that the mapping between facts and source text is not computable.
These agents will be integrated via Python calls to local model inference (e.g., using llama.cpp,
Ollama, or HuggingFace Transformers for local models). The code will likely have functions like:
- `extract_facts_pipeline(text) -> facts`: runs two-phase pipeline (detail extraction, then fact formation)
- `opus_reconstruct(span, facts, prior_failures) -> ReconstructionResult`: Opus produces step-by-step
  formal reconstruction proof with R(S), proof trace, and delegates to Python helpers
- `python_grammar_helper(facts) -> joined_text`: deterministic clause joining/scaffolding
- `python_synonym_substitute(token, dict_source) -> (substituted, log_entry)`: logged substitutions
- `python_diff(R_S, T_S) -> uncovered_words_phrases`: character-level diff returning exact substrings
The ReconstructionResult indicates span state (ATTEMPTABLE -> PROVEN or FAILED), includes proof trace,
and produces ReconstructionFailure artifact on failure or Clarification Question on escalation. The design
will document these interfaces so that they can be swapped or adjusted.
```
### Tools and Technologies

```
Programming Language: Python 3.x will be used for deterministic helper scripts (grammar checks, string diffs, etc.).
Execution Harness: Claude Code orchestrates the entire pipeline as the execution harness.
Local Extraction Pipeline Models: The system uses a two-phase sequential pipeline with Claude sub-agents:
- **Haiku 4.5 (sub-agent 1)**: Detail extraction - scans source text for raw observations, statements, claims
- **Haiku 4.5 (sub-agent 2)**: Fact construction and anchoring - transforms details into anchored triplet-structured facts
- **Opus 4.5**: Orchestrates pipeline, runs reconstruction proofs, performs QA validation
Sub-agents communicate via file I/O to avoid filling orchestrator context. The pipeline is
sequential: detail extraction produces raw details (written to files), which are then read by fact construction
for anchoring and triplet structure validation (results written to files).
Reasoning Model (Minimized, Optional): A larger reasoning model may be invoked only when:
- Local models cannot adjudicate borderline dedup merges
- Deterministic rules cannot classify text as fluff vs meaningful
- High-quality Clarification Questions are needed (though template-driven is acceptable)
If local models + deterministic rules suffice, the reasoning model is NOT invoked. This keeps the
system local-first while allowing optional escalation for edge cases.
Embedding Model: Qwen-3 Embedding model (0.6B) via HuggingFace Transformers. Requires
torch and possibly transformers library. If the model is proprietary, the user must agree to its
license (the Qwen models are proprietary but free for research purposes, as of writing). Alternatively,
if license or model size is a concern, an open embedding model like SentenceTransformer or
OpenAI's text-embedding-ada-002 (if allowed locally via API) could be configured. But Qwen-3 is
chosen for its strong performance and local run capability.
Vector Database: SQLite with the sqlite-vss extension (installed via pip). This gives a simple
way to create a vector index in a local file and query it using SQL. The extension uses Faiss internally
for efficient similarity search, so it’s quite performant for our needs. The schema might look like: a
table facts(fact_id INTEGER PRIMARY KEY, fact_text TEXT, embedding VECTOR)
where VECTOR is a datatype provided by the extension (e.g., 1024-dimensional). We will use
statements like SELECT fact_id, fact_text, vss_similarity(embedding, ?) as sim
FROM facts ORDER BY sim DESC LIMIT 5; to get nearest neighbors to a given embedding
(passing the query embedding as a parameter).
Data Structures: In-memory, we will likely use Python lists or pandas DataFrames to hold facts
during processing. Each fact record contains dual representation: canonical fact text (for search/dedup)
and source context (for provenance). We will use interval data structures to track unprocessed work
regions and map source context (character offsets) to their associated facts. Source context is
provenance (where the system was looking when it discovered the fact), NOT text ownership.
Multiple facts may share the same source context; one fact may have multiple source contexts.
Agent Communication: Sub-agents communicate via file I/O to avoid filling orchestrator context:
- **Detail extraction sub-agent** writes raw details to files
- **Fact construction sub-agent** reads details from files and writes facts to files
- **Opus orchestrator** reads fact files and coordinates reconstruction proofs
- **Python helper scripts** are invoked as tools by agents for deterministic operations
The choice depends on hardware and deployment preferences. All support quantized models for
reduced memory footprint.
Documentation & Packaging: Markdown for README. Possibly small helper scripts like
run_extraction.py, run_deduplication.py, etc., which can be combined or sequentially
invoked. These will be documented so a user (or an LLM agent) knows how to execute the full
pipeline step by step.
Grammar Validation Layer (NLTK): NLTK is used as a deterministic pre-filter to FLAG potential
illegal fact fabrications before they enter the knowledge base. NLTK provides a fast, production-ready
grammar analysis layer that complements the Opus reconstruction proof mechanism. **NLTK's scope is
limited to syntax and grammar validation** - it does NOT validate logical inferences or semantic
relationships. Inference validation is handled by Opus as part of the reconstruction proof process.

**Why NLTK:**
- Production-ready, fast, well-documented NLP library with Python 3.14 support
- Provides POS tagging, chunking, and parsing capabilities
- Pure Python implementation (no binary wheel dependencies)
- Pluggable architecture - can integrate with Stanford CoreNLP for advanced parsing

**What NLTK Can Detect:**

| Illegal Fabrication | NLTK Detection Method |
|---------------------|------------------------|
| Hidden Copula Hallucination | No token with VB* POS tag in source, but LLM claims verb |
| Forced Subject Hallucination | No token with NN*/PRP tag before verb in source, but LLM claims subject exists |
| Pronoun Concord Violation | Singular/plural mismatch between noun tags (NN vs NNS) and pronoun patterns |
| Tense Fabrication | Verb POS tag (VBD=past, VBP/VBZ=present) doesn't match LLM's claimed tense |
| Missing Predicate | Source has only noun tags (no VB*), parsed as noun phrase not sentence |

**Configuration Modes (Speed/Accuracy Tradeoff):**

1. **Fast Mode (Default)** - For high-volume validation:
   ```python
   import nltk
   from nltk import pos_tag, word_tokenize
   tokens = word_tokenize(text)
   tagged = pos_tag(tokens)  # Averaged Perceptron Tagger
   # Speed: ~15,000+ words/sec CPU
   # Accuracy: ~97% POS tagging accuracy
   ```

2. **Accurate Mode** - For critical validation with parsing:
   ```python
   from nltk.parse import CoreNLPParser
   parser = CoreNLPParser()  # Requires Stanford CoreNLP server
   parse_tree = list(parser.parse(tokens))
   # Speed: ~500-1000 words/sec
   # Accuracy: State-of-the-art dependency parsing
   ```

**Important Limitations:**
NLTK is statistical, not ground truth:
- FLAGS potential violations, does NOT auto-reject triplets
- Complex/malformed sentences may parse incorrectly
- Flags trigger additional review or Clarification Questions
- User can override flags with justification

**Integration with Existing Concepts:**
- Flags feed into the Illegal Fact Fabrication detection pipeline
- Flagged facts go to Clarification Questions or human review
- Works alongside Inference Validation Layer and Opus reconstruction proof:
  - **NLTK validates SOURCE GRAMMAR** (syntax only - deterministic, rule-based)
  - **Inference Validation validates LOGICAL DERIVABILITY** (Opus-led - requires reasoning)
  - **Opus validates FACT DERIVATION** via reconstruction proof (requires reasoning)
- NLTK is a deterministic pre-filter that catches structural violations; it does NOT validate inferences or replace Opus reconstruction
```
### Example Walk-through (Hypothetical)

To illustrate, consider a simple example input text:

```
The device will support Wi-Fi and Bluetooth connectivity. It can operate for 10
hours on battery. If the temperature falls below 0°C, the system shuts down to
prevent damage.
```
The system would process this as follows: - **Two-Phase Extraction Pipeline:**

  **Phase 1 - Detail Extraction (Haiku 4.5 sub-agent 1):** Scans the text for raw details:
  - Detail1: "device supports Wi-Fi connectivity"
  - Detail2: "device supports Bluetooth connectivity"
  - Detail3: "device operates for 10 hours on battery"
  - Detail4: "if temperature falls below 0°C, system shuts down to prevent damage"

  **Phase 2 - Fact Construction (Haiku 4.5 sub-agent 2):** Transforms details into anchored facts:
  - Extracted Fact1:
"The device will support Wi-Fi connectivity." - Extracted Fact2: "The device will support Bluetooth
connectivity." - Extracted Fact3: "The device can operate for 10 hours on battery." - Extracted Fact4: "If the
temperature falls below 0°C, the system shuts down to prevent damage." (This one is conditional.) -
**Validation:** Fact4 contains an "if", so split it: - Fact4a: "The temperature falls below 0°C." (condition) - Fact4b:
"The system shuts down to prevent damage." (outcome) - Link: An untyped link is recorded between Fact4a
and Fact4b indicating a relationship exists (no semantic classification such as "prerequisite" is required). - **Co-reference and Dual Representation:** Fact3 originally started as "It can operate for 10 hours..."
The canonical fact text resolves the pronoun "It" to "The device" for search/dedup purposes.
The source context preserves the original character offsets (provenance) where the fact was discovered.
Both representations are stored: canonical text for semantic operations, source context for reconstruction. - **Work Region Tracking:** The first sentence had two facts (Wi-Fi and Bluetooth).
The region is marked as processed; reconstruction validates that only the connective "and" remains
unexplained (fluff). The second sentence (battery life fact) is processed. The third sentence yields two
facts (temp condition and shutdown action); reconstruction validates all meaningful content is explained. -
**Iteration:** After first pass, reconstruction succeeds for all work regions (sufficient facts extracted to
meet the reconstruction threshold). -
**Opus-Led Formal Proof Reconstruction:** For each span in ATTEMPTABLE state, Opus (the reconstruction
agent) constructs a step-by-step formal reconstruction proof:
  - Span 1 original T(S): "The device will support Wi-Fi and Bluetooth connectivity."
  - Facts/Building Blocks: [Fact1, Fact2]
  - Span state: ATTEMPTABLE (we believe we have enough coverage to try)
  - Opus task: produce formal reconstruction R(S) from facts
  - Opus proof trace: "Fact1 provides 'device supports Wi-Fi'. Fact2 provides 'device supports Bluetooth'.
    Python grammar helper joins with conjunction 'and'. Python substitution: 'supports' -> 'will support'
    (logged). Reconstructed: 'The device will support Wi-Fi and Bluetooth connectivity.'"
  - Python helper (deterministic diff): compare R(S) to T(S), uncovered words/phrases = empty
  - Result: Span -> PROVEN. The word "and" is connective fluff handled by Python grammar mechanics.
    Facts do not "own" this text; they explain it.
  - Span 2 original T(S): "It can operate for 10 hours on battery."
  - Facts: [Fact3 with resolved pronoun]
  - Opus proof trace: "Fact3 provides 'The device can operate for 10 hours on battery'. No substitutions."
  - Python helper (deterministic diff): uncovered words/phrases = empty
  - Result: Span -> PROVEN.
  - Span 3: Similar formal proof for conditional facts, spans -> PROVEN.
  - If reconstruction failed (uncovered words/phrases remain), the span -> FAILED and Opus produces a
    ReconstructionFailure artifact with: span_id, verbatim T(S), R(S), uncovered words/phrases (UNANCHORED
    text that no fact explains), substitutions, facts used, proof trace, and anchoring_attempts. Then bounded
    anchoring iterations: anchoring search (context expansion + existing fact search + new fact extraction)
    against unanchored text, update graph with any newly anchored facts, rerun Opus reconstruction. If
    anchoring stalls (no reduction in unanchored text), emit Clarification Question artifact - this indicates
    structural comprehension failure, not merely a missed fact. -
**Embedding & Dedup:** Compute embeddings for the canonical fact texts of Fact1..Fact5. Embeddings
are computed on canonical text (not source context) for semantic similarity. Suppose Fact1 and Fact2 are
very similar (both about support connectivity) – the vector search might flag them, but the local dedup
models will say they are _not duplicates_ but related (different connectivity types, so keep separate). No
duplicates in this small example, so final facts remain the same. - **Output:** We get facts with dual
representation:
1. Canonical: "The device will support Wi-Fi connectivity." | Source context: char offsets 0-55 (provenance)
2. Canonical: "The device will support Bluetooth connectivity." | Source context: char offsets 0-55 (provenance)
3. Canonical: "The device can operate for 10 hours on battery." | Source context: char offsets 56-95 (provenance)
   (Note: canonical text has resolved "It" to "The device"; source context preserves original location)
4. Canonical: "The temperature falls below 0°C." | Source context: char offsets 96-175 (provenance), linked to fact5
5. Canonical: "The system shuts down to prevent damage." | Source context: char offsets 96-175 (provenance), linked to fact4
These would be listed in CSV/JSON with both canonical fact text and source context (character offsets as
provenance markers, NOT ownership claims). The link between 4 and 5 is recorded as an untyped hypothesis
(no semantic classification required). Source context enables reconstruction testing; canonical text enables
search and deduplication.

The above example is simplistic; the system is intended to handle much larger and more complex
documents with possibly hundreds of facts and many duplicates.

### Example Walk-through: Island Join Failure

To illustrate the Island Join Failure mode, consider this malformed input text:

```
Replace partition-style span fragmentation with work region tracking over the canonical input
string red flowers scattered across the pavement, erupting from the palms of its hands also
buffalo sauce.
```

Assume we have two sets of facts from different sources:
- **Technical facts**: (Work region tracking, replaces, partition-style span fragmentation), (Work region tracking, operates over, canonical input string), etc.
- **Nonsense facts**: (Red flowers, are scattered across, the pavement), (Red flowers, erupting from, palms of hands), (Hands, also have, buffalo sauce), etc.

The system would process this as follows:

**Phase 1 - Two-Phase Extraction Pipeline:** The detail extraction sub-agent (Haiku 4.5 sub-agent 1) scans
the text and extracts raw details from both segments. The fact construction sub-agent (Haiku 4.5 sub-agent 2)
transforms these into anchored facts. Due to the concatenated nature, technical facts are extracted from the
first part, nonsense facts from the second.

**Phase 2 - Opus-Led Formal Proof Reconstruction:**
- Initial span: entire text
- Opus attempts reconstruction...
- Opus identifies two independently reconstructable segments:

**Island 1 Discovery:**
  - Text: "Replace partition-style span fragmentation with work region tracking over the canonical input string"
  - Char offsets: [0, 104)
  - Facts used: [TechFact1, TechFact2, TechFact3]
  - Reconstruction proof succeeds: all words/phrases anchored
  - Status: PROVEN

**Island 2 Discovery:**
  - Text: "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce."
  - Char offsets: [105, 203)
  - Facts used: [NonsenseFact1, NonsenseFact2, NonsenseFact3]
  - Reconstruction proof succeeds: all words/phrases anchored
  - Status: PROVEN

**Join Failure Detection:**
  - Boundary offset: 104 (between "...input string" and "red flowers...")
  - Terminal phrase of Island 1: "canonical input string"
  - Initial phrase of Island 2: "red flowers"
  - Join anchor search:
    - Check all facts for relation connecting "canonical input string" to "red flowers": NONE FOUND
    - Check for valid conjunctions/prepositions at boundary: NONE PRESENT
    - Check grammar rules for valid noun phrase concatenation: INVALID (two noun phrases cannot be adjacent without connector)
  - Result: UNANCHORED JOIN detected

**Phase 3 - ReconstructionFailure Artifact Produced:**
```json
{
  "span_id": "span_001",
  "original_text": "Replace partition-style span fragmentation with work region tracking over the canonical input string red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.",
  "reconstructed_text": null,
  "uncovered_words_phrases": [],
  "island_join_failure": {
    "failure_type": "ISLAND_JOIN_FAILURE",
    "islands": [
      {
        "island_id": "island_001",
        "text": "Replace partition-style span fragmentation with work region tracking over the canonical input string",
        "char_offsets": [0, 104],
        "status": "PROVEN",
        "anchoring_facts": ["TechFact1", "TechFact2", "TechFact3"]
      },
      {
        "island_id": "island_002",
        "text": "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.",
        "char_offsets": [105, 203],
        "status": "PROVEN",
        "anchoring_facts": ["NonsenseFact1", "NonsenseFact2", "NonsenseFact3"]
      }
    ],
    "unanchored_boundaries": [
      {
        "boundary_offset": 104,
        "island_before_id": "island_001",
        "island_after_id": "island_002",
        "terminal_phrase": "canonical input string",
        "initial_phrase": "red flowers",
        "join_anchoring_attempts": [
          {
            "attempt_number": 1,
            "relations_searched": ["(canonical input string, ?, red flowers)", "(input string, ?, flowers)"],
            "connectors_searched": ["and", "or", "with", ",", ";"],
            "join_anchor_found": false
          }
        ]
      }
    ]
  },
  "facts_used": ["TechFact1", "TechFact2", "TechFact3", "NonsenseFact1", "NonsenseFact2", "NonsenseFact3"],
  "proof_trace": "Islands proven independently. Join anchor search failed at boundary 104."
}
```

**Phase 4 - Clarification Question Emitted:**
```json
{
  "doc_id": "doc_001",
  "region_offsets": [0, 203],
  "original_text": "Replace partition-style span fragmentation with work region tracking over the canonical input string red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.",
  "failure_type": "ISLAND_JOIN_FAILURE",
  "failure_statement": "The system can explain each segment independently but cannot determine the relationship between them.",
  "clarification_request": "What is the relationship between 'canonical input string' and 'red flowers'? These segments appear adjacent but no connecting relation was found.",
  "island_context": {
    "islands": [
      {"text": "Replace partition-style span fragmentation with work region tracking over the canonical input string", "status": "PROVEN"},
      {"text": "red flowers scattered across the pavement, erupting from the palms of its hands also buffalo sauce.", "status": "PROVEN"}
    ],
    "boundary_offset": 104,
    "terminal_phrase": "canonical input string",
    "initial_phrase": "red flowers"
  },
  "author_response": null
}
```

**Key Observations:**
1. This is NOT an unanchored text failure - every word in both islands has fact coverage
2. The failure is at the JOIN level - no relation or connector explains why these segments are adjacent
3. The system correctly identifies this as likely source text corruption (concatenation from unrelated sources)
4. The Clarification Question targets the specific boundary, not the entire text
5. A valid author response might be: "These are two unrelated sentences that were accidentally merged. They should be separated." or "Missing comma - should read '...input string, and red flowers...'"

This example demonstrates that Island Join Failures require a different diagnostic approach than standard unanchored text failures. The system must track islands separately and explicitly test join anchors at boundaries.

## Ambiguities and Assumptions

### Scope Boundary: Extraction vs Editing

This system focuses exclusively on **extraction** from source text. Editing operations (modifying facts after extraction) are explicitly **out of scope**.

**Extraction vs Editing:**

| Concern | In Scope? | Description |
|---------|-----------|-------------|
| Fact extraction | YES | Extract facts from source text |
| Transitive anchors | YES | Capture contextual relations |
| Condition deduplication | YES | Dedupe shared conditions |
| **Fact splitting** | NO | When editing diverges a fact in one context |

**Fact Splitting (Out of Scope):**

When a user edits a fact within a specific context, the fact may need to "split" - diverging from its shared form into context-specific variants. This is an **editing concern**, not an extraction concern.

Example of fact splitting (out of scope):
```
Before edit:
  Condition A → Fact D
  Condition B → Fact D  (same fact)

After edit (user changes Fact D only in context B):
  Condition A → Fact D  (original)
  Condition B → Fact D' (modified variant)
```

This splitting behavior is part of a future editing system, not the extraction system.

**Key Invariant:**

The extraction structure must NOT lose information. All transitive anchors and condition groups must be preserved (per Invariant #12: Transitive Anchors) so that editing can be implemented later without information loss.

**Why This Matters:**

- The extraction system's job is to preserve all information from the source text in a structured form
- Editing concerns (like fact splitting, variant management, edit propagation) require different semantics and are deferred to future work
- The current system guarantees that no information is lost during extraction, making future editing systems possible
- Transitive anchors (Invariant #12) enable this by preserving "same fact, different contexts" relationships

---

### Additional Assumptions

During the design process, a few ambiguities were identified and addressed with assumptions: - **Choice of
Vector DB:** We assume using SQLite with its extension for vectors as it meets the local and simplicity
requirement. Alternatives (like a pure Python in-memory search or using an open-source vector DB such as
Chroma) were considered. SQLite was chosen for its lightweight nature and ease of integration into the dev
environment. This decision assumes the scale (number of facts) is manageable (hundreds or a few
thousand facts, which is likely for a 200-page document). If scale grew to millions of facts, a more specialized
solution might be needed, but that's beyond our current scope. - **Sub-Agent Prompt and Behavior:** The
exact prompting strategy for the two-phase extraction pipeline (Haiku 4.5 sub-agent 1 for detail
extraction, Haiku 4.5 sub-agent 2 for fact construction) is to be refined during implementation. The
sequential pipeline design allows the detail extraction sub-agent to focus on extracting raw content while the fact
construction sub-agent handles the more complex task of anchoring and triplet structure validation. The PRD assumes we can
get the sub-agents to output their respective artifacts (details, then facts) cleanly. In practice, it may require
iterative prompt tuning or even some post-processing of model output (like regex to split bullet points, etc.).
We also assume the models are reliable in not hallucinating facts that aren't in the text - we will need to
instruct them clearly to only extract given information. The explanation-driven reconstruction approach
provides a built-in verification mechanism: by attempting to re-explain the original text using extracted
facts, we can test whether the current understanding is sufficient. When reconstruction fails, the anchoring
operation attempts to find facts that explain the uncovered (unanchored) text. If anchoring succeeds
(uncovered text shrinks), the failure was due to missed facts. If anchoring fails after bounded attempts
(no reduction in unanchored text), this indicates structural comprehension failure - the system cannot
understand what the unanchored text means or belongs to. In this case, the system emits Clarification
Questions rather than inventing meaning - preserving alignment through honest admission of non-understanding. A larger reasoning model
is only invoked when strictly necessary (e.g., borderline dedup adjudication, fluff classification when
deterministic rules fail, or high-quality Clarification Question generation). If local models + deterministic
rules suffice, the reasoning model is not invoked. - **Atomic Fact Definition Edge Cases:** Some information might be arguable
whether it’s one fact or two. For example, "The device is compact and lightweight" – one could see this as
two facts ("device is compact", "device is lightweight") or as one combined characteristic. Our rule is to split
on "and", so we’d make it two. This should be fine, but we note that sometimes combined adjectives or lists
will increase fact count. This is acceptable as we prefer granularity. - **Context Link Representation:** The
format for storing links between contextual facts is not yet formalized. Links are stored as untyped
hypotheses; the system is not required to assign semantic types such as "prerequisite" or "is-a". It could
be as simple as a note in the fact text (like "Linked to Fact ID X") or a separate structure linking Fact IDs.
For now, we will likely add a column like linked_fact_ids for any fact that has related facts. The
graph of facts and links is assumed to be incomplete; incompleteness is surfaced only through
reconstruction failures and Clarification Questions. - **Contradiction Handling:** As stated, the
system currently does not resolve contradictions. It will happily store contradictory facts if the source document contains
them. We assume for now the source document is internally consistent, or if not, that highlighting contradictions will be
done later by analyzing the fact list. The main objective now is to gather facts and unify duplicates, not to
decide which conflicting fact is correct. A future extension could use logical checks or domain rules to flag
such issues. - **Integration with LLM for Use:** We expect the output to be used by an LLM for tasks like
question answering or updating the source document. We assume that the consumer LLM/tool can ingest either the CSV/
JSON or query the SQLite. For instance, a script could load all facts into a vector store in-memory and then
given a user query, find relevant facts and present them to the LLM. The details of that integration (like a
chatbot that uses this data) are outside this PRD's scope, but our output is designed to be general-purpose
for any such use case.

## Conclusion

In summary, this PRD specifies a system that transforms a raw unstructured document into a curated, duplicate-free
set of facts with full traceability via character offsets into the canonical input string. **Completeness is
defined by the Derivability Principle (Invariant #11)**: the system extracts base facts sufficient for
reconstructing the text and deriving all implied facts, not every possible implication explicitly. Each fact
has dual representation: canonical fact text (normalized, self-contained, used for search/dedup) and source
context (character offsets as provenance markers, NOT ownership claims). By leveraging Claude Code as the
execution harness with a two-phase extraction pipeline (Haiku 4.5 sub-agent 1 for detail extraction,
Haiku 4.5 sub-agent 2 for fact construction and anchoring), file I/O communication between sub-agents,
a vector database for semantic similarity on canonical facts, and an Opus-led formal proof
reconstruction mechanism, the system will achieve a thorough and verified decomposition of the document's
knowledge while preserving derivability.

**Core Reconstruction Architecture:**
- **Opus constructs the reconstruction proof**: For each target span S, Opus produces a step-by-step formal
  reconstruction of T(S) from facts ("like solving a math problem"), outputting R(S) + proof trace.
- **Python executes deterministic substeps**: Grammar mechanics, synonym substitutions (logged), and
  character-level diff between R(S) and T(S). Python does NOT infer missing structure.
- **Span computability is provisional**: Spans follow a lifecycle (ATTEMPTABLE -> PROVEN/FAILED). A span
  can be attempted and still fail; failure is a normal outcome that drives additional search.

**Span Lifecycle States:**
- `ATTEMPTABLE` - we think we have enough to try reconstruction
- `PROVEN` - reconstruction succeeds; no uncovered words/phrases remain. **This means sufficient base facts for
  reconstruction and derivability (reconstruction threshold and Derivability Principle met), not that all
  possible facts and implications have been explicitly extracted.**
- `FAILED` - reconstruction fails; produces ReconstructionFailure artifact with span_id, T(S), R(S),
  uncovered words/phrases (UNANCHORED text), substitutions, facts used, proof trace, and anchoring_attempts

**Anchoring Operation:** When reconstruction fails, uncovered text is UNANCHORED - no fact explains it.
The anchoring operation attempts to find facts that explain this text through context expansion, existing
fact search, and new fact extraction via the two-phase pipeline (detail extraction, then fact construction).
**Phase 2 (Fact Construction with Haiku 4.5 sub-agent 2) is responsible for the anchoring operation** -
it transforms raw details into facts anchored to source text. If anchoring succeeds (uncovered text shrinks),
continue iterations. If anchoring fails after bounded attempts, emit Clarification Question (structural
comprehension failure).
**Per the Derivability Principle (Invariant #11)**, Clarification Questions are emitted only when base facts
cannot be found or derivation is impossible - NOT merely because an implied fact was not explicitly extracted.

**Island Join Failures:** A distinct failure mode where multiple segments (islands) can be proven independently
but cannot be joined. This occurs when two proven islands are adjacent without a connecting relation or
connector (conjunction, preposition, punctuation). Island Join Failures indicate potential source text
corruption, missing punctuation, or concatenation from unrelated sources. The system records both proven
islands, identifies the boundary offset, and emits a targeted Clarification Question asking about the
relationship between the terminal phrase of one island and the initial phrase of the next.

**Fact Dual Representation:**
- **Canonical fact text**: Normalized, self-contained; pronouns resolved when possible, otherwise marked
  with symbolic placeholders (e.g., `UNKNOWN_REF_N`). Used for embedding computation, search, and dedup.
- **Source context**: Character offsets as provenance markers (NOT ownership claims). Enables reconstruction
  testing. Facts explain text; they do not own it. Multiple facts may share the same source context.

A larger reasoning model is only invoked when strictly necessary - local models + deterministic rules handle
most cases. Reconstruction is an explanation test, not a coverage proof - facts do not own text, they explain
it. When reconstruction fails, the anchoring operation attempts to find facts that explain the uncovered
(unanchored) text. When anchoring fails after bounded attempts (structural comprehension failure), the
system emits Clarification Questions as honest admissions of non-understanding rather than inventing meaning.
**Per the Derivability Principle (Invariant #11)**, the system achieves completeness by extracting base facts
sufficient for deriving all implications, not by exhaustively extracting every possible implication. The
resulting graph of facts and links is assumed to be incomplete; incompleteness is surfaced through
reconstruction failures and Clarification Questions. Links between facts are stored as untyped hypotheses,
with no requirement for semantic classification. All technical choices (Python, two-phase extraction pipeline,
local embedding model, SQLite) align with a **local-first,** **simple deployment** philosophy, ensuring
developers can run this on their machines with minimal setup.
The end result will significantly ease the maintenance of large requirement documents – instead of editing
many scattered statements, a user can adjust a single fact in the index; and instead of manually searching
for inconsistencies, an LLM can quickly pinpoint conflicts using the fact database. This PRD covers the what
(functional goals) and the how (design and algorithms) for implementing this system, providing a clear
roadmap to a working solution. The next steps would involve prototyping each component, refining the
local model prompts, and testing the pipeline on sample documents to tune its performance and accuracy. With
this foundation in place, future enhancements like contradiction detection or automatic fact update
propagation can be built on top of the robust fact index we will have created.
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

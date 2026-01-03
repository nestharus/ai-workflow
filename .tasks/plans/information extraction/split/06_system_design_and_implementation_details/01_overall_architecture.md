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

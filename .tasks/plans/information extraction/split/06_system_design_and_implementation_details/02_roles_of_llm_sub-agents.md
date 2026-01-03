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

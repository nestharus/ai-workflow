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

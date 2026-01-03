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

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

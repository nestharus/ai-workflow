# Phase 0: Normative Content Coverage Tracking

## The Problem

Dense specs have 500+ normative statements. Dropping any is a defect.
A missing lock acquisition step causes data corruption. A missing
evidence emission step causes silent failures. A missing schema field
causes data loss. There is no acceptable loss rate for normative content.

Phase 0 must track every normative sentence through extraction and
report any sentence that does not have a home in the output. Coverage
tracking operates at the sentence level because normative content is
interleaved with non-normative content within the same sections and
even within the same paragraphs.

---

## What Is Normative Content

### Normative sentences

A sentence is normative if it meets ANY of these criteria:

1. **Contains RFC 2119 keywords**: MUST, MUST NOT, SHALL, SHALL NOT,
   REQUIRED, SHALL BE, SHOULD, SHOULD NOT (case-insensitive matching
   for the keyword itself, but typically appears in uppercase)

2. **Resides in a section marked normative**: Sections with headers
   containing "(normative)" or explicitly labeled as normative in the
   document structure. ALL sentences in such sections are normative
   regardless of whether they individually contain RFC 2119 keywords.

3. **Contains imperative definitions**: Sentences that define state
   transitions ("X transitions to Y"), field requirements ("field X
   is present when Y"), or step sequences ("first do A, then B")
   within normative sections.

### Non-normative content

Non-normative content includes:

- **Examples**: Sentences in "Example" sections or inline examples
  ("e.g.", "for instance", "such as")
- **Rationale**: Explanations of why decisions were made ("We chose X
  because Y", "The reason for...")
- **Notes**: Sections marked "Note:", "NOTE:", "(informative)"
- **Diagrams**: Mermaid diagrams and other visualizations (these are
  informative renderings of normative content defined elsewhere)
- **Reading guides**: Table of contents, reading order, "see also"

Non-normative content is tracked but NOT required to have a home in
the output. It receives TrackedUnits with appropriate status but does
not count toward the coverage requirement. Non-normative content that
IS successfully classified (e.g., rationale becomes an analysis doc,
a diagram becomes an analysis atom) improves completeness but its
absence does not constitute an extraction failure.

### The boundary

Some content is ambiguous. A sentence like "The system validates
payments against fraud rules" contains no RFC 2119 keyword but may
describe a required algorithm step. The rule:

- If the sentence is in a normative section, it is normative.
- If the sentence contains an RFC 2119 keyword, it is normative.
- Otherwise, it is non-normative and tracked but not required.

This produces false negatives (normative sentences without keywords in
non-normative sections). That is acceptable. The alternative -- trying
to semantically classify every sentence as normative or not -- would
introduce false positives and make the coverage metric unreliable.
Deterministic rules produce a reliable denominator.

---

## Sentence-Level Tracking

### Sentence extraction

During intake (Pass 1), Phase 0 splits each file into sentences. A
sentence is defined as:

- Text terminated by a period, colon followed by a list, or end of a
  block element (table row, list item, code block boundary)
- Code blocks are treated as single units (one atom per code block),
  not split into sentences
- Table rows are individual sentences
- List items are individual sentences (nested lists: each item at
  every level is a separate sentence)
- YAML key-value pairs are individual sentences

### TrackedUnit assignment

Each normative sentence becomes a TrackedUnit (DS-PROV-0001 from
`clean/02_PROVENANCE_AND_MEMBERSHIP.md`):

```
TrackedUnit:
  unit_id:    deterministic ID from content hash (ALG-PROV-0001)
  unit_type:  initial = PROSE (refined during classification)
  atom_ids:   [single atom_id for this sentence]
  content_preview:  first 120 chars of the sentence
  status:     PENDING (before classification)
  introduced_by:  "phase0:intake:{file_uid}"
  modified_by:    []
  membership_evidence:  {}  (populated during classification)
  lineage_edges:  []  (populated during transformation)
  tags:       {normative_keywords found, section_path}
```

Each sentence also gets a SourceLocation (DS-PROV-0002):

```
SourceLocation:
  file_uid:       source file identifier
  rev_id:         intake revision
  start_atom_id:  atom at sentence start
  end_atom_id:    atom at sentence end (same for single-sentence units)
```

### Atom granularity

The atom is the smallest trackable unit. For normative content:

- One sentence = one atom = one TrackedUnit
- This 1:1 mapping is the default during intake

For non-normative content:

- One paragraph or block = one atom = one TrackedUnit
- Coarser granularity is acceptable because non-normative content does
  not have a coverage requirement

### ID stability

Atom IDs are deterministic: derived from a hash of the source file UID,
the section path, and the sentence content. This means:

- Re-running intake on the same file produces the same atom IDs
- Coverage reports are comparable across runs
- Lineage edges can reference atoms from previous runs

---

## Coverage Verification

### The coverage invariant

After extraction is complete (Pass 4), every normative TrackedUnit MUST
have status != PENDING. Acceptable terminal statuses:

| Status | Meaning | Counts as covered? |
|--------|---------|--------------------|
| MAPPED | Sentence classified and placed in output (algorithm, shape, store, constraint, or analysis) | Yes |
| MERGED | Sentence merged with another sentence during cross-reference resolution (LineageEdge tracks the merge) | Yes |
| NON_AUTHORITATIVE | Sentence is a satellite reference; the authoritative version is elsewhere and is MAPPED | Yes |
| DROPPED | Sentence explicitly excluded with justification (Exclusion record) | Yes (excluded) |
| QUARANTINED | Sentence could not be classified; reported as extraction failure | No -- this is a failure |
| PENDING | Sentence was never processed | No -- this is a failure |

Coverage percentage = (MAPPED + MERGED + NON_AUTHORITATIVE) / total_normative_atoms * 100

Excluded atoms (DROPPED with valid Exclusion) are removed from the
denominator. QUARANTINED and PENDING atoms are extraction failures.

### Per-file verification

Coverage is verified per file using CoverageReport (DS-PROV-0005):

```
CoverageReport:
  file_uid:           source file
  rev_id:             intake revision
  total_atoms:        count of all atoms from this file
  mapped_atoms:       count with status in {MAPPED, MERGED, NON_AUTHORITATIVE}
  remainder_atoms:    count with status in {PENDING, QUARANTINED}
  excluded_atoms:     count with status DROPPED
  unaccounted_atom_ids:  list of atom_ids with PENDING or QUARANTINED status
```

The algorithm ALG-PROV-0002 (UpdateCoverageReport) computes this from
the atoms, units, and exclusions for each file.

### Verification algorithm

After Pass 4 completes:

```
for each input file:
  atoms = all atoms from this file
  normative_atoms = [a for a in atoms if a.tags contains "normative"]
  units = all TrackedUnits containing these atoms
  exclusions = all Exclusions for these atoms

  report = UpdateCoverageReport(atoms=normative_atoms, units=units, exclusions=exclusions)

  if report.unaccounted_atom_ids is not empty:
    for atom_id in report.unaccounted_atom_ids:
      unit = lookup_unit(atom_id)
      emit ExtractionFailure(
        atom_id=atom_id,
        source_location=unit.source_location,
        content=unit.content_preview,
        reason=unit.status  # PENDING or QUARANTINED
      )

  VerifyCoverageOrEmitGap(report)  # ALG-PROV-0003
```

---

## Extraction Failures

### What constitutes a failure

An extraction failure occurs when a normative sentence has no home in
the output. Specifically:

1. **PENDING status after Pass 4**: The sentence was ingested but never
   processed. This indicates a bug in the extraction pipeline (a file
   or section was skipped).

2. **QUARANTINED status**: The sentence was processed but could not be
   classified into any PDD category. The classifier could not determine
   whether it is an algorithm, shape, store, invariant, or analysis.

### Failure record

Each extraction failure produces a structured record:

```
ExtractionFailure:
  atom_id:          the unaccounted atom
  file_uid:         source file
  section_path:     hierarchical section path (e.g., "§5.4.2.B")
  line_range:       start and end line in the source file
  original_text:    the full text of the normative sentence
  normative_signal: what made it normative (keyword: "MUST", or
                    section_marker: "(normative)")
  failure_reason:   UNPROCESSED (PENDING) or UNCLASSIFIABLE (QUARANTINED)
  classification_attempts:  list of attempted classifications and why
                            each was rejected (empty for UNPROCESSED)
```

### Failure handling

Extraction failures are NOT silently dropped. They are:

1. **Collected** into a failures list on the CoverageReport
2. **Reported** in the final coverage summary with full source context
3. **Available** for manual review or re-processing
4. **Counted** against the coverage percentage

The system does NOT attempt to force-classify failures. A quarantined
sentence with an honest "could not classify" is better than a
misclassified sentence that corrupts the output.

---

## Lineage Tracking

### Why lineage matters for coverage

During extraction, sentences are not always preserved 1:1. They may be:

- **SPLIT**: One sentence becomes two TrackedUnits (e.g., a compound
  sentence with both an invariant clause and an algorithm clause)
- **MERGED**: Two sentences from different files become one TrackedUnit
  (e.g., when cross-reference resolution combines a delegation with its
  referent)
- **REWRITTEN**: A sentence is restructured during classification (e.g.,
  a prose paragraph is converted to pseudocode steps)

Without lineage tracking, a SPLIT produces one MAPPED unit and one
apparently-new unit that looks unaccounted. A MERGE makes two source
sentences disappear into one output. Coverage cannot be verified
without knowing what transformations occurred.

### LineageEdge (DS-PROV-0004)

Every transformation is recorded as a LineageEdge:

```
LineageEdge:
  edge_id:             unique edge identifier
  from_id:             source TrackedUnit.unit_id (or atom_id)
  to_id:               target TrackedUnit.unit_id (or atom_id)
  transformation:      SPLIT | MERGE | REWRITE | PROMOTE | DEMOTE
  evidence_atom_ids:   atoms that justify this transformation
  confidence:          1.0 for deterministic transforms, <1.0 for
                       LLM-driven transforms
```

### Transformation types in Phase 0

| Transformation | When it happens | Coverage implication |
|---------------|-----------------|---------------------|
| SPLIT | Compound sentence split during classification (invariant clause + algorithm clause) | Both children must be MAPPED. Parent becomes MAPPED if all children are MAPPED. |
| MERGE | Cross-reference resolution combines delegation with referent | Source sentences covered if the merged unit is MAPPED. |
| REWRITE | Prose converted to pseudocode during classification | Source sentence covered if the rewritten unit is MAPPED. |
| PROMOTE | Non-normative content elevated to normative during review | New normative atom added to coverage denominator. |
| DEMOTE | Sentence reclassified as non-normative (was in normative section but is actually an example) | Removed from coverage denominator with Exclusion record. |

### Coverage through lineage chains

To verify coverage for a source atom that was transformed:

```
function verify_atom_coverage(atom_id, lineage_graph):
  edges = lineage_graph.edges_from(atom_id)

  if edges is empty:
    # No transformation -- check unit status directly
    return lookup_unit(atom_id).status in {MAPPED, MERGED, NON_AUTHORITATIVE}

  # Follow the lineage chain to leaf nodes
  for edge in edges:
    target = edge.to_id
    if not verify_atom_coverage(target, lineage_graph):
      return false

  return true
```

This recursive check ensures that even through chains of SPLIT, MERGE,
and REWRITE, every original normative sentence can be traced to a
MAPPED output.

### Lineage graph integrity

The lineage graph must satisfy:

1. **No orphans**: Every `to_id` in a LineageEdge must reference a
   valid TrackedUnit or atom.
2. **No cycles**: The lineage graph is a DAG. A sentence cannot be
   transformed into an ancestor.
3. **Full coverage of children**: For SPLIT edges, ALL children must
   be accounted for. A split that produces 3 children requires all 3
   to be MAPPED.
4. **Source preservation**: REWRITE edges preserve a link to the
   original text. The original atom is not deleted.

---

## Reporting

### Final coverage report

After Pass 4, Phase 0 produces a summary coverage report:

```
Phase0CoverageReport:
  # Totals
  total_input_sentences:      count of all sentences across all files
  total_normative_sentences:  count of normative sentences
  total_non_normative:        count of non-normative sentences

  # Normative coverage breakdown
  classified:
    algorithms:    count of normative sentences mapped to algorithms
    shapes:        count of normative sentences mapped to shapes
    stores:        count of normative sentences mapped to stores
    invariants:    count of normative sentences mapped to constraints
    analysis:      count of normative sentences mapped to analysis docs

  merged:          count of normative sentences merged via cross-ref
  non_authoritative: count marked as satellite references
  excluded:        count with valid Exclusion records
  extraction_failures: count of PENDING + QUARANTINED

  # Derived
  coverage_percentage:  (classified + merged + non_authoritative) /
                        (total_normative - excluded) * 100

  # Per-file breakdown
  per_file: list<CoverageReport>  # one per input file

  # Failures detail
  failures: list<ExtractionFailure>  # full records for each failure

  # Lineage summary
  transformations:
    splits:    count of SPLIT edges
    merges:    count of MERGE edges
    rewrites:  count of REWRITE edges
    promotes:  count of PROMOTE edges
    demotes:   count of DEMOTE edges
```

### Report interpretation

| Coverage % | Interpretation |
|-----------|---------------|
| 100% | Every normative sentence has a home. No extraction failures. |
| 95-99% | A few sentences could not be classified. Review failures manually. |
| 90-95% | Significant extraction issues. Likely a format or section type that the classifier does not handle. |
| <90% | Systemic extraction failure. The intake or classifier needs work. |

### Report output

The coverage report is:

1. **Written to the run folder** as `coverage_report.json` (machine-readable)
2. **Summarized to stderr** during extraction (human-readable one-liner:
   "Coverage: 487/500 normative sentences (97.4%), 13 failures")
3. **Available via CLI** (`spec-manager coverage` shows the latest report)

### Per-file breakdown example

```
File: Tech_Plan__Core_Infrastructure/00_Foundation.md
  Normative sentences: 47
  Classified: 42 (algorithms: 28, shapes: 8, stores: 2, invariants: 3, analysis: 1)
  Merged: 3 (via cross-ref resolution with Lifecycle.md)
  Excluded: 1 (duplicate of Lifecycle §1.2)
  Failures: 1 (QUARANTINED: "MUST comply with the operational evidence protocol"
               -- could not determine if algorithm step or invariant)
  Coverage: 45/46 (97.8%)
```

---

## Integration with Phase 0 Passes

### Pass 1: Per-file extraction

- Intake each file
- Sectionize into hierarchical sections
- Split sections into sentences
- Tag each sentence: normative (keyword or section marker) or non-normative
- Create a TrackedUnit per normative sentence (status: PENDING)
- Create a TrackedUnit per non-normative block (status: PENDING)
- Record SourceLocation for each unit

### Pass 2: Cross-reference resolution

- Resolve delegation references (follow references to referent content)
- Establish authority chains (mark satellites as NON_AUTHORITATIVE)
- Merge overlapping content from different files (create MERGE LineageEdges)
- Deduplicate: authoritative source keeps MAPPED status; satellites get
  NON_AUTHORITATIVE status
- All transformations produce LineageEdges

### Pass 3: Organization and classification

- Classify each PENDING TrackedUnit into a PDD category
- Set status to MAPPED on success
- Set status to QUARANTINED on failure (record classification attempts)
- SPLIT compound sentences (create SPLIT LineageEdges, classify children)
- REWRITE prose to pseudocode where needed (create REWRITE LineageEdges)
- Place classified units into library structure
- Non-normative content: classify if possible, leave as PENDING if not
  (does not count as failure)

### Pass 4: Coverage verification

- Build CoverageReport per file (ALG-PROV-0002)
- Verify coverage through lineage chains
- Collect extraction failures
- Build Phase0CoverageReport (aggregate)
- Emit report
- If coverage < 100%, report failures with full source context

---

## Relationship to Existing Design

### TrackedUnit (DS-PROV-0001)

Used as-is. Each normative sentence becomes a TrackedUnit. The `status`
field tracks coverage state. The `atom_ids` field provides atom-level
granularity. The `membership_evidence` field records why a sentence was
classified the way it was (method: LLM_ATOM_MAP for LLM classification,
HEURISTIC_FALLBACK for keyword-based classification).

### CoverageReport (DS-PROV-0005)

Used as-is for per-file verification. The `unaccounted_atom_ids` field
directly identifies extraction failures. Phase0CoverageReport is an
aggregate wrapper around per-file CoverageReports.

### LineageEdge (DS-PROV-0004)

Used as-is. Transformations during extraction (SPLIT, MERGE, REWRITE)
are recorded as LineageEdges. The `confidence` field distinguishes
deterministic transforms (1.0) from LLM-driven transforms (<1.0).

### Exclusion (DS-PROV-0006)

Used for sentences removed from the coverage denominator. Reason codes:
- DUPLICATE: Sentence is a non-authoritative duplicate of another
- FORMAT: Sentence is formatting/markup incorrectly tagged as normative
- OUT_OF_SCOPE: Sentence references content outside the input set

### ALG-PROV-0002 (UpdateCoverageReport)

The core algorithm for building per-file coverage. Called after each
pass completes to track incremental progress.

### ALG-PROV-0003 (VerifyCoverageOrEmitGap)

The final verification step. Called in Pass 4 to produce the gap
report for any file with incomplete coverage.

---

## Design Decisions

### Why sentence-level, not paragraph-level

Real specs interleave normative and non-normative content within
single paragraphs. A paragraph might contain an invariant sentence,
an algorithm sentence, and an example sentence. Paragraph-level
tracking would either force the entire paragraph into one category
(losing the interleaved content) or require splitting anyway.
Sentence-level tracking from the start avoids this problem.

### Why deterministic normative detection, not semantic

Using RFC 2119 keywords and section markers to identify normative
content produces a reliable, reproducible denominator. Semantic
classification ("does this sentence describe a requirement?") would
vary between LLM runs and make the coverage metric unstable. A
stable denominator is essential for tracking progress across
iterations.

### Why non-normative content is tracked but not required

Non-normative content (examples, rationale, notes) adds value when
classified (rationale becomes analysis docs, examples become test
cases) but its absence does not indicate a defect. Requiring 100%
coverage of ALL content would dilute the metric and create noise
from formatting artifacts, section headers, and boilerplate.

### Why QUARANTINED, not force-classified

A sentence quarantined with "could not classify" preserves the
information for human review. A sentence force-classified into the
wrong category corrupts the output silently. Honest failures are
better than hidden misclassifications.

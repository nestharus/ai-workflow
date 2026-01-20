# Spec Manager Evolution Plan

## Executive Summary

This plan transforms spec_manager from a static validation tool into an adaptive, strategy-driven specification processing system. The core insight is that specification development is fundamentally a **risk minimization problem** - we cannot deterministically verify that meaning is preserved through transformations, so we apply strategies that maximize the probability of preservation.

---

## Part 1: The Problem We're Solving

### 1.1 The Challenge

Specification inputs are messy:
- **Prose with embedded requirements** - meaning hidden in paragraphs
- **Cascading patches** - p5 patches p3 which patched p1, with vague references
- **Vague entity references** - "patching the algorithm" but which one?
- **Smeared state** - final output scattered across multiple inputs
- **Lossy translations** - every prose → structure conversion risks fidelity loss

### 1.2 Why Traditional Approaches Fail

You cannot:
- Look at a line and determine if "all detail was captured"
- Automatically verify semantic equivalence between prose and structure
- Know if a dropped line was intentional or accidental

### 1.3 The Solution: Strategy-Based Risk Minimization

Instead of trying to verify fidelity (impossible), we:
1. Apply **strategies** that minimize risk of information loss
2. Track **provenance** so we can trace what came from where
3. Use **intermediate files** to guarantee nothing lost between steps
4. Build a **strategy library** that evolves as new challenges emerge
5. Accept that some risk remains, but minimize it systematically

---

## Part 2: The Core Methodology

### 2.1 Line Membership Guarantee

**Principle**: Every line from source must appear in target OR be explicitly handled.

```
source_lines - target_lines = handled_lines (not empty set = error)
```

This is tracked through **provenance stamps** during processing.

### 2.1.1 Many-to-Many Membership

With prose fragments scattered across sources, mapping is often **many source atoms → one structured element** (or vice versa). A membership model that assumes one-to-one or contiguous provenance will fail.

### 2.1.2 Explicit Lineage Edges

With heavy rewriting, decomposition, and recomposition, we need **explicit lineage edges** to reconstruct "what became what" - beyond just a string in `drop_reason`.

**Design**:
```python
# TrackedUnit has:
parents: list[str]     # Unit IDs this was created from
children: list[str]    # Unit IDs created from this

# Plus a separate lineage table in workspace state:
class LineageTable:
    edges: list[LineageEdge]  # (from_unit, to_unit, transformation, timestamp)
```

**Why this matters**:
- When LLM inference transforms scattered prose fragments into structured units, we need to prove (mechanically) how those fragments were handled
- Enables "trace_transformation(from_unit, to_unit)" queries
- Supports debugging information loss
- Enables undo/revert of transformations

**Design (Many-to-Many Membership)**:
```python
# TrackedUnit has:
source_atom_ids: list[str]           # Source atoms that contributed to this
target_element_ids: list[str]        # Elements this contributed to
membership_evidence: dict[str, MembershipEvidence]  # target → evidence
```

**Coverage verification** must accept:
- Multiple prose fragments can be "handled" by one structured element
- "Handled" needs evidence: link fragments to target with rationale (LLM or similarity/diff), not just token match
- One source atom can contribute to multiple target elements

**Example**:
```yaml
# Prose fragment "The relaxation algorithm must converge and maintain stability"
# gets handled by TWO structured elements:
_prose_p5_47:
  source_atom_ids: []  # This IS a source atom
  target_element_ids: ["Algorithm 3", "I7"]
  membership_evidence:
    "Algorithm 3":
      rationale: "Convergence requirement implemented in relaxation loop"
      confidence: 0.9
      method: "llm_inference"
    "I7":
      rationale: "Stability requirement captured as invariant"
      confidence: 0.85
      method: "llm_inference"
```

### 2.2 Projection with Pinning

**Principle**: When transforming between artifact types, pin output back to source.

```
Source Line 47: "The algorithm must handle edge cases"
    ↓ projects to
Algorithm 5, line 12: "if edge_case: handle()" @from:source:47
```

### 2.3 Decomposition Before Projection

**Principle**: Break compound content into atomic units before transforming.

```
"The algorithm must handle edge cases and log errors"
    ↓ decompose
"The algorithm must handle edge cases"  →  Algorithm logic
"The algorithm must log errors"         →  Logging requirement
```

Tools like spaCy sentence splitting enable finer-grained tracking.

### 2.4 Structured Content Priority

**Principle**: Structured content (algorithms, claims, data structures) must be preserved exactly. Prose can collapse once its meaning is captured in structure.

| Content Type | Behavior |
|--------------|----------|
| Algorithm, Claim, D#, I# | Must appear in target exactly |
| Prose with "must/should/always" | Should become structure |
| Explanatory prose | Can drop after meaning captured |
| Questions, TODOs, uncertainty | Must be resolved or flagged |

---

## Part 3: The Workflow Phases

### 3.1 Phase 1: Input Cleaning (Iterative)

**Goal**: Transform messy inputs into clean, compliant, annotated files.

**Process**:
```
Messy Inputs (p0.md, p1.md, p2.md...)
    ↓ Pass 1: Basic normalization
Intermediate v1
    ↓ Pass 2: Entity resolution
Intermediate v2
    ↓ Pass 3: Annotation completion
Intermediate v3
    ↓ ... (as many passes as needed)
Clean Compliant Files
```

**Key Requirements**:
- **Keep all intermediate files** - can trace any transformation
- **Keep original inputs** - reference for entity resolution
- **Track remainders** - content that didn't fit anywhere yet
- **Compositing** - intermediate files may combine parts of multiple inputs

**Entity Resolution Challenge**:
When p5 says "patch the relaxation algorithm", we need to:
1. Look at what p5 is patching (p4? p3?)
2. Find "relaxation algorithm" in that context
3. Resolve to specific ID (Algorithm 3)
4. Annotations help: `(@[+Algorithm 3])` makes this explicit

### 3.2 Phase 2: Library Discovery

**Goal**: Identify BIG systems (not small components) that elements belong to.

**Process**:
```
Clean Elements (all annotated)
    ↓ Step 1: Identify candidate libraries
Candidate Libraries (first guesses - BIG systems)
    ↓ Step 2: Multi-label everything
Elements with Soft Labels ("looks like X, Y, Z")
    ↓ Step 3: Aggregate per library
Library Shapes (see convergence/divergence)
    ↓ Step 4: Discover new libraries from clusters
Refined Library Set
    ↓ Step 5: Iterate until single primary
Elements with Primary Label + Relation Annotations
```

**Key Insight**: Libraries EMERGE from the data. You don't predefine them.

### 3.2.1 Library Identity Stability

**Critical**: Library NAMES can change during discovery, but each candidate needs a **stable internal ID** for tracking.

**Design**:
- Each candidate library gets a stable **ingest ID** (e.g., `LIB_TMP_013`)
- Display name can churn freely during discovery (`field_solver` → `field_ops` → `field_system`)
- Track rename/merge/split events in intermediate state:
  ```yaml
  library_events:
    - type: rename
      id: LIB_TMP_013
      from: "field_solver"
      to: "field_operations"
      reason: "Shape analysis suggested broader scope"
    - type: merge
      source_ids: [LIB_TMP_013, LIB_TMP_017]
      target_id: LIB_TMP_013
      reason: "85% element overlap"
    - type: split
      source_id: LIB_TMP_008
      target_ids: [LIB_TMP_020, LIB_TMP_021]
      reason: "Bimodal distribution detected"
  ```
- At finalization: emit "clean" display names, discard internal IDs
- Membership checks use internal ID (stable) not display name (churning)

**Multi-Labeling**:
```yaml
Algorithm 5:
  candidates:
    - field_solver: 0.8      # strong match
    - graph_ops: 0.4         # some overlap
    - uncertainty: 0.2       # weak relation
  primary: null              # not yet decided
```

**Shape Aggregation**:
After labeling all elements, aggregate per library:
```yaml
field_solver:
  strong_matches: [Algorithm 3, Algorithm 5, D12, D15]
  weak_matches: [Algorithm 8, D20]
  total_weight: 4.2
  convergence: high  # elements agree this is a thing
```

This reveals:
- Which guesses were good (high convergence)
- Which should split (bimodal distribution)
- Which should merge (high overlap)
- New libraries needed (orphan clusters)

### 3.3 Phase 3: Library Review

**Goal**: Refine libraries by analyzing overlap, resolving what we can.

**Process**:
```
Libraries with labeled elements
    ↓ Analyze overlap between libraries
Convergence/Divergence Map
    ↓ Resolve what we can
    - Redefine ambiguous elements
    - Drop true duplicates
    - Mark legacy artifacts
    - Split overloaded libraries
    - Merge redundant libraries
Refined Libraries
    ↓ Flag what we can't resolve
gaps.md (remaining ambiguities)
```

**Using Provenance for Priority**:
When two patches conflict, stamps tell us which is newer:
```
Algorithm 5 @from:p1 @modified:p5,p7
```
p7 takes priority over p1 for this element.

### 3.4 Phase 4: Finalization

**Goal**: Clean up temporary state, libraries become authoritative.

**Process**:
```
Processing Complete
    ↓ Remove provenance stamps (temporary)
    ↓ Archive intermediate files
    ↓ Generate final gaps.md
Permanent State:
  - libraries/*.md (authoritative)
  - plan.md (unified view)
  - gaps.md (remaining issues)
```

**Critical**: Stamps are ONLY useful during current ingest. Next ingest starts fresh with new stamps. Don't persist them.

---

## Part 4: Provenance Stamps (Temporary State)

### 4.1 Purpose

During ingest, stamp each element with:
- **@from:p#** - which patch introduced this
- **@modified:p#,p#** - which patches modified this
- **@line:#** - source line number for fine-grained tracking

### 4.2 Format

```markdown
## Algorithm 5 ([=Algorithm 5]) <!-- @from:p1 @modified:p5,p7 @line:234 -->

Algorithm content here...
```

Or in processing state (not in files):
```yaml
elements:
  "Algorithm 5":
    introduced_by: p1
    modified_by: [p5, p7]
    source_lines:
      p1: [234, 235, 236]
      p5: [89, 90]
      p7: [156]
```

### 4.3 Lifecycle

```
Ingest Start
    ↓ Elements get stamps as they flow in
Processing (stamps help resolve conflicts, trace provenance)
    ↓ Ingest complete
Stamps Discarded
    ↓ Libraries are now authoritative
Next Ingest (fresh stamps, doesn't care about previous)
```

### 4.4 Conflict Resolution Using Stamps

When same element appears in multiple patches:
1. Check stamps to see ordering: p1 < p5 < p7
2. Later patches supersede earlier ones
3. But check if later patch is MODIFYING or REPLACING
4. Merge if modifying, replace if replacing

---

## Part 5: Strategy Library Framework

### 5.1 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      WORKFLOW                           │
│  (orchestrates strategy selection and application)      │
└─────────────────────────┬───────────────────────────────┘
                          │ selects/applies
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  STRATEGY LIBRARY                       │
│  (extensible - workflow can add new strategies)         │
│                                                         │
│  strategies/                                            │
│    sentence_decomposition.yaml                          │
│    line_membership.yaml                                 │
│    structured_extraction.yaml                           │
│    entity_resolution.yaml                               │
│    multi_labeling.yaml                                  │
│    ...                                                  │
└─────────────────────────┬───────────────────────────────┘
                          │ implemented by
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    TOOL LIBRARY                         │
│  (concrete implementations)                             │
│                                                         │
│  tools/                                                 │
│    spacy_splitter.py                                    │
│    line_comparator.py                                   │
│    similarity_scorer.py                                 │
│    pattern_extractor.py                                 │
│    ...                                                  │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Strategy Definition Schema

```yaml
# strategies/sentence_decomposition.yaml
name: sentence_decomposition
version: 1.0

purpose: |
  Split compound sentences into atomic units so each unit
  can be tracked independently through transformations.
  Reduces risk of losing part of a compound statement.

when_to_apply:
  - Content contains conjunctions (and, or, but)
  - Sentences have multiple clauses
  - Semicolon-separated statements
  - Content will be projected to different artifact types

risk_addressed: |
  Compound meaning lost in translation. When "A and B" becomes
  just "A" in the output, B is silently dropped.

tools_used:
  - spacy_splitter: Split sentences using NLP
  - line_tracker: Track each atomic unit's provenance

inputs:
  - content: str  # The text to decompose
  - source_file: str
  - source_lines: list[int]

outputs:
  - atoms: list[TrackedUnit]  # Each unit with provenance

example:
  input: "The algorithm must handle edge cases and log errors"
  output:
    - unit: "The algorithm must handle edge cases"
      source: "original:47"
    - unit: "The algorithm must log errors"
      source: "original:47"
```

### 5.3 Core Strategies Needed

| Strategy | Purpose | Tools |
|----------|---------|-------|
| sentence_decomposition | Split compounds to atoms | spacy, line_tracker |
| line_membership | Track source → target mapping | diff, line_comparator |
| structured_extraction | Pull algo/claim/D# first | pattern_extractor |
| entity_resolution | Resolve "the algorithm" → Algorithm 5 | context_analyzer, id_matcher |
| coverage_verification | Ensure nothing dropped | set_comparator |
| multi_labeling | Soft assignment to libraries | similarity_scorer |
| shape_aggregation | See library convergence | aggregator |
| conflict_resolution | Handle overlapping patches | stamp_analyzer |
| iterative_reduction | Simplify until structure emerges | multi-pass orchestrator |

### 5.4 Strategy Evolution

The system can add new strategies:
```python
# When existing strategies insufficient
def add_strategy(name: str, definition: StrategyDef):
    """
    Add a new strategy to the library.
    Called when workflow encounters situation not handled by existing strategies.
    """
    validate_strategy(definition)
    save_strategy(f"strategies/{name}.yaml", definition)
    register_strategy(name, definition)
```

---

## Part 6: Enhanced Gap Detection

### 6.0 LLM Inference as First-Class Detection

**Critical Design Principle**: Much of the detection work is **LLM inferencing meaning from scattered prose fragments**. This is a first-class detection method, not an afterthought.

**What the LLM infers**:
- Likely requirement statements hidden in prose
- Likely intended patch targets when references are vague
- Likely missing proof obligations implied by prose
- Clause/sentence boundaries in run-on text
- Entity references that span multiple patches

**How we treat LLM outputs**:
- **Evidence, not truth**: LLM outputs are `GapEvidence` with `confidence` field
- **Provenance spans**: Every inference links back to source text locations
- **Iterative reduction**: Prose fragments are reduced over passes as inferences are confirmed

**Key Detectors**:
| Detector | Purpose |
|----------|---------|
| `ProseFragmentInferenceDetector` | Infer requirements/claims from prose |
| `VagueReferenceResolver` | Infer patch targets when references are ambiguous |
| `ProofObligationInferrer` | Infer missing proof chains from prose |

**Key Strategies**:
| Strategy | Purpose |
|----------|---------|
| `ProseFragmentReduction` | Transform inferred requirements into structured elements |
| `InferredClaimPromotion` | Promote high-confidence inferences to real claims |

### 6.1 Gap as First-Class Element

**Critical Design Principle**: Gap is a **first-class spec element**, not a "gap type" taxonomy. Detectors produce **evidence**; gaps are **synthesized** from evidence by clustering issues that affect the same underlying problem.

**What we DON'T do**:
- Scan for specific labels like "dragon" or "GAP-P#.#"
- Create "gap types" for every detector output
- Treat source text labels as classifiers

**What we DO**:
- Detect invariant violations (coverage, membership, conflicts)
- Attach source labels as **evidence** only
- Synthesize gaps by clustering related evidence

### 6.2 Evidence Categories (Invariant-Driven)

| Evidence Category | What Triggers It |
|------------------|------------------|
| Coverage Failure | Unaccounted atoms (source - target ≠ ∅) |
| Membership Failure | Line not tracked through projection |
| Entity Resolution Failure | Vague reference couldn't resolve |
| Proof Chain Break | Algorithm without Claim, Claim without Proof |
| Sequence Violation | Duplicate IDs, holes, conflicts |
| Content Mismatch | plan.md ↔ library drift |
| Uncertainty Marker | sorry, TODO, ?, hedging language |
| Format Violation | Legacy patterns, malformed IDs |

### 6.3 gaps.md Output Structure

gaps.md is a **multi-section report with stable headings**:

```markdown
# Gaps

## Patch Ledger
<!-- By patch: what it introduced/modified, unresolved patch-intent statements -->

## Proof Obligations
<!-- By patch + by element: Claim→ProofSketch→Lean chain status -->

## Undefined Functions
<!-- Grouped by category/prefix -->

## Structural Health
<!-- Coupling, cohesion, underspecified elements -->

## Unresolved Elements
<!-- Elements that couldn't be placed or resolved -->
```

### 6.4 Proof Chain Validator

**Principle**: "A hypothesis of a design must be proven with mathematics before an algorithm is allowed to be created."

The proof chain validator enforces:
1. Algorithm # must reference Claim(s) (P#C# / C#)
2. Claim must have Proof Sketch (or Math section P#.#)
3. Proof Sketch must have Lean skeleton (or explicit "non-lean proof accepted")

Output is grouped **by patch** (what patch introduced broken chains).

**Workflow gating**: Elements with broken proof chains are flagged "non-authoritative" until chain is complete.

### 6.5 Integration with Existing Scripts

The scripts in `gen3 rag/scripts/` produce **evidence** (not "gap types"):

**Staging Scripts** (format compliance evidence):
- `lint_patterns.py` → format violation evidence
- `check_duplicate_declarations.py` → duplicate declaration evidence
- `find_headers_missing_declarations.py` → missing declaration evidence
- `find_references.py` → unannotated reference evidence
- `find_undefined_functions.py` → undefined function evidence

**Planning Scripts** (coverage evidence):
- `compare_ids.py` → missing_in_plan, missing_in_library evidence
- `check_sequences.py` → sequence_hole, conflict evidence

**Verification Scripts** (content evidence):
- `verify_content.py` → content_mismatch evidence
- `find_empty_stubs.py` → empty_stub evidence
- `find_unique_library_lines.py` → library_only_content evidence

### 6.6 Evidence Collection → Gap Synthesis Flow

```
All Sources (patches, plan.md, libraries)
    ↓
┌─────────────────────────────────────┐
│ Evidence Collection (detectors)     │
│ - Format compliance                 │
│ - Coverage/membership               │
│ - Sequence analysis                 │
│ - Proof chain validation            │
│ - Content comparison                │
│ - Uncertainty detection             │
│ - Provenance tracking               │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Evidence Objects                    │
│ (severity, message, location,       │
│  element_id, detector, details)     │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Gap Synthesis                       │
│ Cluster evidence by:                │
│ - Same underlying element           │
│ - Same root cause                   │
│ - Same patch origin                 │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Gap Elements (first-class)          │
│ GAP-0001, GAP-0002, ...             │
│ Each with: summary, affects,        │
│ evidence list, severity             │
└─────────────────────────────────────┘
    ↓
gaps.md (multi-section report)
```

---

## Part 7: Data Structures

### 7.0 Membership Granularity Ladder

Processing uses multiple granularity levels depending on messiness:

| Level | Granularity | When Used |
|-------|-------------|-----------|
| 1 | Line | Dirty prose, maximum tracking |
| 2 | Sentence | Semi-structured content |
| 3 | Clause | Complex compound statements |
| 4 | Section | Clean, annotated content |

The cleaning/decomposition phase explicitly chooses granularity based on input messiness. Finer granularity = more tracking overhead but lower loss risk.

### 7.0.1 Unitizer Strategies

The granularity ladder requires **real unitizer implementations** as strategies:

| Unitizer | Granularity | Tool | When Applied |
|----------|-------------|------|--------------|
| LineUnitizer | LINE | None (string split) | Unannotated prose, maximum tracking |
| SentenceUnitizer | SENTENCE | spaCy sentence splitter | Semi-structured text |
| ClauseUnitizer | CLAUSE | spaCy + dependency parse | Complex compound statements |
| SectionUnitizer | SECTION | Header regex | Clean, annotated content |
| LLMUnitizer | CLAUSE | LLM-assisted | Hard-to-segment prose |

**Key Principle**: When annotations are sparse, emit **fine atoms** (line/sentence/clause) even with zero declarations. Don't wait for ([=...]) boundaries to unitize.

```python
class UnitizationSelector:
    """Selects unitizer based on content analysis."""

    def select_unitizer(self, content: str) -> Unitizer:
        # Count annotation density
        decl_count = content.count("([=")
        line_count = len(content.splitlines())
        density = decl_count / max(line_count, 1)

        if density > 0.1:  # Well-annotated
            return SectionUnitizer()
        elif self._has_clear_sentences(content):
            return SentenceUnitizer()
        else:
            return LineUnitizer()  # Fallback for messy prose
```

**LLM-Assisted Unitization**: For prose that resists deterministic segmentation, use LLM to identify:
- Clause boundaries in run-on sentences
- Implicit requirements hidden in narrative
- Logical units that span multiple sentences

### 7.1 TrackedUnit (Atomic Content Unit)

```python
class UnitType(Enum):
    """Types of content units - including GAP as first-class."""
    ALGORITHM = "algorithm"
    CLAIM = "claim"
    DATA_STRUCTURE = "data_structure"
    INVARIANT = "invariant"
    GOAL = "goal"
    PROOF = "proof"
    LEAN = "lean"
    PROSE = "prose"
    MATH = "math"
    PSEUDOCODE = "pseudocode"
    GAP = "gap"              # ← FIRST-CLASS GAP ELEMENT
    UNKNOWN = "unknown"

@dataclass
class TrackedUnit:
    """An atomic unit of content with full provenance."""

    id: str                          # Unique identifier
    content: str                     # The actual text
    unit_type: UnitType              # algorithm, claim, GAP, etc.

    # Provenance
    source_file: str                 # Original file
    source_lines: tuple[int, ...]    # Line numbers in source
    introduced_by: str               # Patch that introduced this
    modified_by: list[str]           # Patches that modified this

    # Labeling
    annotations: list[str]           # ([=ID]), (@[+ID]), etc.
    candidate_libraries: dict[str, float]  # library → confidence
    primary_library: str | None      # Final assignment
    relation_libraries: list[str]    # Secondary relations

    # Status
    status: Literal["pending", "mapped", "dropped", "merged"]
    mapped_to: list[tuple[str, int]] | None  # (target_file, target_line)
```

### 7.2 IntermediateState (Processing Snapshot)

```python
@dataclass
class IntermediateState:
    """
    Snapshot of processing state at a point in time.

    CRITICAL: Store FULL content (not just previews/hashes) so that
    line-by-line membership checks can be performed between states.
    """

    version: int                     # Increment each pass
    timestamp: datetime
    phase: str                       # cleaning, discovery, review

    units: dict[str, TrackedUnit]    # All tracked units (FULL content)
    remainders: list[TrackedUnit]    # Units not yet placed

    # Reconstructed intermediate markdown for diffing
    intermediate_files: dict[str, str]  # filename → FULL content (not hash)

    # Library discovery state
    candidate_libraries: list[str]
    library_shapes: dict[str, LibraryShape]

    # Membership tracking for verification
    atom_mapping: dict[str, str]     # atom_id → target_location
```

### 7.2.1 GapEvidence (Detector Output)

```python
@dataclass
class GapEvidence:
    """
    Evidence produced by a detector - NOT a gap itself.
    Gaps are synthesized by clustering evidence.
    """
    severity: Severity               # error, warning, info
    message: str                     # Human-readable description
    location: str                    # Where found (file:line)
    element_id: str | None           # Related element ID
    detector: str                    # Which detector found this
    details: dict[str, Any]          # Detector-specific details
```

### 7.2.2 GapElement (First-Class Gap)

```python
@dataclass
class GapElement:
    """
    A synthesized gap - first-class spec element.
    Multiple evidence objects cluster into a single gap.
    """
    id: str                          # e.g., GAP-0001
    severity: Severity               # Highest severity from evidence
    summary: str                     # What's wrong
    affects: list[str]               # Element IDs and/or source refs
    evidence: list[GapEvidence]      # All evidence supporting this gap
    patch_origin: str | None         # Which patch introduced this
```

### 7.3 LibraryShape (Aggregated View)

```python
@dataclass
class LibraryShape:
    """Aggregated view of what a library looks like."""

    name: str

    # Elements pointing to this library
    strong_matches: list[str]        # confidence > 0.7
    medium_matches: list[str]        # 0.4 < confidence <= 0.7
    weak_matches: list[str]          # confidence <= 0.4

    # Metrics
    total_weight: float              # Sum of all confidences
    convergence: float               # How much elements agree

    # Overlap with other libraries
    overlaps: dict[str, float]       # other_library → overlap_score

    # Suggested actions
    should_split: bool
    should_merge_with: str | None
    new_library_candidates: list[str]  # Clusters that might be new libs
```

### 7.4 Strategy (Executable Strategy)

```python
@dataclass
class Strategy:
    """A strategy for risk minimization."""

    name: str
    version: str
    purpose: str

    when_to_apply: list[str]         # Conditions
    risk_addressed: str
    tools_used: list[str]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if this strategy should be applied."""
        ...

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute the strategy."""
        ...
```

---

## Part 8: Implementation Phases

### Phase A: Foundation (Provenance + Intermediates)

**Goal**: Add provenance tracking and intermediate file support.

**Files to create/modify**:
- `spec_manager/core/provenance.py` - TrackedUnit, provenance stamps
- `spec_manager/core/intermediate.py` - IntermediateState, snapshots
- `spec_manager/workflow/ingest.py` - Modified to use provenance

**Deliverables**:
1. TrackedUnit dataclass with full provenance
2. IntermediateState for snapshots
3. Stamp parsing/generation (`@from:p#`, `@modified:p#`)
4. Snapshot save/load to `.workspace/intermediates/`

### Phase B: Strategy Framework + Entity Resolution

**Goal**: Create extensible strategy library with entity resolution as first-class.

**Files to create**:
- `spec_manager/strategies/base.py` - Strategy base class
- `spec_manager/strategies/registry.py` - Strategy registry
- `spec_manager/strategies/*.yaml` - Strategy definitions
- `spec_manager/tools/*.py` - Tool implementations
- `spec_manager/resolution/entity_resolver.py` - Entity resolution engine
- `spec_manager/resolution/reference_store.py` - Context retrieval

**Deliverables**:
1. Strategy definition schema (YAML)
2. Strategy registry with load/save
3. Core strategies implemented:
   - sentence_decomposition
   - line_membership
   - structured_extraction
   - coverage_verification
4. **Entity Resolution (first-class)**:
   - Patch dependency graph ("p5 patches p3 patched p1")
   - Context index over: originals, intermediates, current composites
   - Reference Store interface: "given vague mention, retrieve top-k candidates"
   - Failure mode: "unresolved reference" → gaps.md + keep remainder unit
5. **Strategy Evolution Loop**:
   - Trigger conditions: remainder not shrinking, entity resolution failures > threshold
   - Output: "new strategy request" with example inputs and desired transformation
   - Validation: required unit tests + before/after diffs
   - Registry notion of "experimental" vs "stable" strategies

### Phase C: Library Discovery

**Goal**: Implement multi-label discovery workflow. Libraries emerge from data.

**Critical Constraint**: NO HARDCODED SYSTEM_KEYWORDS. Candidate libraries are identified from:
- Content clustering (data-driven)
- Reference graph analysis
- Strategy configuration (YAML, not code)

**Files to create/modify**:
- `spec_manager/discovery/candidate.py` - Candidate library identification (data-driven)
- `spec_manager/discovery/labeling.py` - Multi-label assignment
- `spec_manager/discovery/aggregation.py` - Shape aggregation
- `spec_manager/discovery/refinement.py` - Iterative refinement

**Deliverables**:
1. Candidate library identification (BIG systems) - **DATA-DRIVEN**, not hardcoded keywords
2. Multi-label element assignment
3. LibraryShape aggregation
4. Convergence/divergence analysis
5. Primary label assignment with relations
6. **Relations Output Convention**: Per-element `(@[+rel:library_name])` + library-level cross-links index

### Phase D: Script Integration (Evidence Extraction + Gap Synthesis)

**Goal**: Integrate existing gen3 rag scripts as **evidence extractors**, then synthesize gaps.

**Critical Design**:
- Scripts produce **GapEvidence** objects (not "gap types")
- Gap synthesis clusters evidence into **GapElement** objects
- GapElement is a first-class spec element (UnitType.GAP)

**Files to modify**:
- `spec_manager/core/gaps.py` - Evidence extraction + gap synthesis
- `spec_manager/core/proof_chain.py` - Proof chain validation
- Import/adapt logic from:
  - `lint_patterns.py`
  - `find_undefined_functions.py`
  - `check_sequences.py`
  - `verify_content.py`

**Deliverables**:
1. Evidence extraction from all detectors
2. Gap synthesis by clustering related evidence
3. Proof chain validator (Algorithm→Claim→Proof→Lean)
4. Multi-section gaps.md output:
   - Patch ledger
   - Proof obligations (by patch)
   - Undefined functions (by category)
   - Structural health
   - Unresolved elements

### Phase E: Workflow Integration

**Goal**: Wire everything together with compliance gating, compositing, and plan.md sync.

**Files to modify**:
- `spec_manager/cli.py` - New commands
- `spec_manager/workflow/orchestrator.py` - Phase orchestration
- `spec_manager/workflow/compositing.py` - Merge + remainder partition
- `spec_manager/workflow/plan_sync.py` - plan.md ↔ libraries sync

**Deliverables**:
1. `spec_manager ingest` command (full workflow)
2. `spec_manager discover` command (library discovery)
3. **Compliance Gate**: Clean→Validate→Fix→Snapshot loop until compliance threshold met
   - Library discovery BLOCKED until compliance score > threshold
4. **Compositing as Merge + Remainder Partition**:
   - If patch text partially updates a unit, keep unchanged atoms + updated atoms
   - Carry unresolved atoms as remainder
   - Persist composite artifacts as intermediate markdown
5. **plan.md ↔ libraries sync**:
   - Define authority rules (plan.md authoritative OR libraries authoritative)
   - ProjectionComparator for membership checks between states
   - Drift detection as gaps
6. **Relations written to output**: Per-element `(@[+rel:library_name])` preserved in library files
7. **Library Review Actions**:
   - Merge/split recommendations
   - "Legacy artifact" tagging
   - Conflict resolution using provenance stamps
   - Emitted as patch plan (manual or auto-apply)
8. `spec_manager strategies` command (manage strategies)
9. Updated `run` command using new infrastructure

**Path Discovery + Configuration**:
- Accept either `patches/*.md` or `p*.md` in root (configurable)
- Accept existing plan.md + libraries/ as starting state
- Staging detectors become cleaning validators
- Merge actions become fix-strategies
- Verification remains the final guardrail

---

## Part 9: Success Criteria

### 9.1 Provenance Tracking Works

```bash
# Can trace any element back to source
spec_manager trace "Algorithm 5"
# Output:
# Algorithm 5:
#   Introduced: p1.md:234
#   Modified: p5.md:89, p7.md:156
#   Current: libraries/field.md:45
```

### 9.2 Nothing Silently Dropped

```bash
# After ingest, can verify coverage
spec_manager verify-coverage
# Output:
# Source lines: 2,847
# Mapped lines: 2,831
# Explicitly dropped: 12 (explanatory prose)
# Unaccounted: 4 (GAPS - see gaps.md)
```

### 9.3 Libraries Emerge from Data

```bash
# Discovery produces sensible libraries
spec_manager discover
# Output:
# Candidate libraries identified: 8
# After multi-labeling: 12 (4 new emerged)
# After refinement: 10 (2 merged)
# Convergence score: 0.87
```

### 9.4 Strategies Apply Appropriately

```bash
# Workflow applies strategies based on content
spec_manager ingest --verbose
# Output:
# Applying: sentence_decomposition (compound statements detected)
# Applying: entity_resolution (vague references in p5.md)
# Applying: coverage_verification (post-merge check)
# Strategies applied: 7
# New strategy needed: 0
```

### 9.5 Gaps as First-Class Elements

```bash
# Gap detection produces Gap elements with evidence
spec_manager gaps
# Output:
# Gap elements synthesized: 23
# Evidence pieces collected: 64
#
# gaps.md sections:
# - Patch Ledger: 8 entries
# - Proof Obligations: 12 broken chains
# - Undefined Functions: 23 by category
# - Structural Health: 5 issues
# - Unresolved Elements: 6 remainders
```

### 9.6 Proof Chain Validation

```bash
# All algorithms have proof chains
spec_manager verify-proofs
# Output:
# Algorithms: 15
# With claims: 14 (93%)
# With proof sketches: 12 (80%)
# With Lean skeletons: 8 (53%)
# Broken chains → gaps.md (3 algorithms flagged non-authoritative)
```

### 9.7 Entity Resolution Works

```bash
# Vague references resolved using context
spec_manager ingest --verbose
# Output:
# Entity resolution:
#   Resolved: 45 references
#   Unresolved: 3 (→ gaps.md)
#   Context used: originals (23), intermediates (18), composites (4)
```

### 9.8 Relations Preserved

```bash
# Cross-cutting concerns captured as relations
grep "@\[+rel:" libraries/*.md | wc -l
# Output: 34 relation annotations preserved
```

---

## Part 10: File Structure After Implementation

```
spec_manager/
├── core/
│   ├── annotations.py      # Existing - annotation parsing
│   ├── ids.py              # Existing - ID validation
│   ├── gaps.py             # Enhanced - evidence extraction + gap synthesis
│   ├── proof_chain.py      # NEW - Proof chain validation
│   ├── provenance.py       # NEW - TrackedUnit, stamps
│   └── intermediate.py     # NEW - IntermediateState with full content
│
├── resolution/
│   ├── entity_resolver.py  # NEW - Entity resolution engine
│   ├── reference_store.py  # NEW - Context retrieval interface
│   └── patch_graph.py      # NEW - Patch dependency graph
│
├── strategies/
│   ├── base.py             # Strategy base class
│   ├── registry.py         # Strategy registry (with evolution loop)
│   └── definitions/
│       ├── sentence_decomposition.yaml
│       ├── line_membership.yaml
│       ├── structured_extraction.yaml
│       ├── entity_resolution.yaml
│       ├── coverage_verification.yaml
│       ├── multi_labeling.yaml
│       └── ...
│
├── tools/
│   ├── spacy_splitter.py   # Sentence decomposition
│   ├── line_comparator.py  # Line membership tracking
│   ├── projection_comparator.py  # NEW - Membership checks between states
│   ├── pattern_extractor.py # Structured extraction
│   ├── similarity_scorer.py # Multi-labeling support
│   └── ...
│
├── discovery/
│   ├── candidate.py        # Candidate library identification (data-driven)
│   ├── labeling.py         # Multi-label assignment
│   ├── aggregation.py      # Shape aggregation
│   └── refinement.py       # Iterative refinement
│
├── workflow/
│   ├── ingest.py           # Full ingest workflow
│   ├── orchestrator.py     # Phase orchestration
│   ├── compositing.py      # NEW - Merge + remainder partition
│   ├── plan_sync.py        # NEW - plan.md ↔ libraries sync
│   └── phases/
│       ├── cleaning.py     # Iterative cleaning with compliance gate
│       ├── discovery.py    # Library discovery
│       ├── review.py       # Library review with concrete actions
│       └── finalize.py     # Stamp removal, finalization
│
└── cli.py                  # Enhanced CLI
```

---

## Part 11: Provenance Stamp Lifecycle

**Clarification**: Stamps are discarded from **final artifacts** but kept in `.workspace/` for debugging.

```
Ingest Start
    ↓ Elements get stamps as they flow in
Processing (stamps help resolve conflicts, trace provenance)
    ↓ Ingest complete
Stamps Discarded FROM OUTPUT FILES (libraries/*.md, plan.md)
    ↓ BUT: Stamps preserved in .workspace/intermediates/
    ↓ For: debugging, traceability until next ingest
Next Ingest (fresh stamps, archived previous state)
```

**Stamps influence conflict resolution**:
- Detect modify vs replace (not just "latest wins")
- Incorporate patch chain evidence
- Priority: p1 < p5 < p7 (later patches supersede earlier)

---

## Part 12: Sub-Agent Task Cards

Each phase should have a task card for sub-agent implementation:

### Task Card Template

```yaml
Phase: [A/B/C/D/E]
Goal: [One-line summary]

Files to Touch:
  - path/to/file.py (create/modify)

APIs/Contracts:
  Inputs:
    - name: description
  Outputs:
    - name: description

Required Fixtures:
  - Sample messy patch with specific characteristics
  - Expected intermediate state after processing

Acceptance Tests:
  - "Unit extraction produces TrackedUnits with provenance"
  - "Coverage report shows nothing unaccounted"

Non-Goals/Risks:
  - Don't persist stamps to final output (temporary state)
  - Don't hardcode library keywords (data-driven)

Conversation Constraints:
  - Must support smeared state (elements from multiple inputs)
  - Must support vague references (entity resolution)
  - Must track line membership (not just section)
```

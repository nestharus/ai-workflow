# QA Strategy: Atomic Fact Extraction System

## Purpose

This document defines a **step-by-step validation strategy** for proving that the system meets its invariants. The goal is not to verify exhaustive fact coverage (which is unknowable) but to detect when invariants are violated.

**Key Insight**: We cannot know what wasn't covered, but we CAN know when something didn't work correctly.

---

## QA Philosophy

### Why Step-by-Step Validation

Simple input/output systems can be tested with straightforward assertions:
```
input → system → output
assert output == expected
```

This system has **hidden processes and variable outcomes**:
- Multiple LLM calls with non-deterministic responses
- Iterative extraction loops with variable termination
- Complex validation pipelines with multiple decision points
- Edge cases that may appear similar but trigger different paths

**Problem**: An I/O test might pass for the wrong reasons, or fail for unrelated reasons.

**Solution**: Step-by-step validation with expected outcome comparison at each step:

```
input → step1 → [compare: expected1 vs actual1] → step2 → [compare: expected2 vs actual2] → ...
                 ↓ unexpected                              ↓ unexpected
              STOP + REPORT                             STOP + REPORT
```

### Tests as Hypotheses

Each QA test is a **hypothesis** about what invariants it captures. The hypothesis may be wrong:

- We might think we're testing "Pronoun Concord Violation" but actually testing "Forced Subject Hallucination"
- We might design for one edge case but hit a different one
- A test might pass while masking a deeper issue

**Discovery Process**: Run tests, analyze failures, refine hypotheses, repeat.

---

## Invariants to Validate

The PRD defines 11 Non-negotiable Invariants. Each must be testable.

| # | Invariant | Validation Approach |
|---|-----------|---------------------|
| 1 | Byte-exact Provenance and Reconstruction | Compare R(S) to T(S) byte-for-byte |
| 2 | No Semantic Classification Requirement | Verify links are untyped (no forced ontology) |
| 3 | Incomplete Structures are Expected | Verify no false completeness claims |
| 4 | Span Lifecycle States | Verify ATTEMPTABLE → PROVEN/FAILED transitions |
| 5 | Facts Do Not Own Text | Verify no "evidence offset" language in outputs |
| 6 | Progress Test for Reconstruction Failures | Verify anchoring attempts before Clarification Questions |
| 7 | Anchoring Unanchored Text | Verify anchoring operation produces expected artifacts |
| 8 | Island Join Failures | Verify detection of proven islands with unanchored joins |
| 9 | No Illegal Fact Fabrication | Verify NLTK catches grammar fabrications (types 1-5) |
| 10 | No Formal Proof Languages | Verify no Lean/Coq/etc. in pipeline |
| 11 | Derivability Principle | Verify termination uses derivability criterion |

**Additional Invariants from Patches:**
| Concept | Validation Approach |
|---------|---------------------|
| Reconstruction Threshold | Verify PROVEN ≠ "all facts extracted" |
| Base/Implied Taxonomy | Verify facts are categorized correctly |
| Inference Validation | Verify Opus catches inference fabrications (types 6-8) |

---

## Pipeline Steps and Expected Outcomes

The system has distinct pipeline steps. At each step, we define what outcomes are valid.

### Step 1: Ingestion
**Input**: Raw document (text, PDF, JSON)
**Expected Outcome**:
- Canonical UTF-8 string produced
- Character offsets are valid indices into canonical string
- No format artifacts remain (PDF headers, JSON syntax, etc.)

**Unexpected Outcomes (STOP + REPORT)**:
- Encoding errors
- Offset out of bounds
- Format artifacts in canonical string

### Step 2: Work Region Initialization
**Input**: Canonical string
**Expected Outcome**:
- Unprocessed region set = entire document
- No spans in PROVEN or FAILED state yet
- All regions marked ATTEMPTABLE

**Unexpected Outcomes (STOP + REPORT)**:
- Empty region set
- Pre-existing PROVEN/FAILED spans
- Overlapping regions that shouldn't overlap

### Step 3: Fact Extraction (Gemma/Ministral)
**Input**: Work region
**Expected Outcome**:
- Zero or more facts extracted
- Each fact has:
  - Canonical fact text (normalized)
  - Source context (character offsets as provenance)
  - Categorization: Base Fact or Implied Fact
- No compound facts (no "and" joining assertions)
- Offsets valid for source region

**Unexpected Outcomes (STOP + REPORT)**:
- Compound facts extracted
- Invalid offsets
- Missing source context
- No categorization

### Step 4: NLTK Grammar Validation
**Input**: Extracted triplet + source text
**Expected Outcome**:
- ValidationFlags produced for structural mismatches
- Grammar fabrications (types 1-5) flagged:
  - HIDDEN_COPULA
  - ATTRIBUTE_TO_PROCESS
  - PRONOUN_CONCORD
  - TENSE_FABRICATION
  - FORCED_SUBJECT
- Clean triplets pass through unflagged

**Unexpected Outcomes (STOP + REPORT)**:
- Grammar fabrication not flagged (false negative)
- Clean triplet flagged (false positive - acceptable for review)
- NLTK crashes/errors

### Step 5: Inference Validation (Opus)
**Input**: Implied Fact + base facts it claims to derive from
**Expected Outcome**:
- Inference fabrications (types 6-8) flagged:
  - INVALID_COREFERENCE
  - UNGROUNDED_IMPLICATION
  - CONTEXT_BOUNDARY_VIOLATION
- Valid implied facts pass through
- InvalidInferenceAttempt artifact created for failures

**Unexpected Outcomes (STOP + REPORT)**:
- Invalid inference not flagged (false negative)
- Valid inference flagged (false positive - review)
- Missing artifact for flagged inference

### Step 6: Opus Reconstruction Proof
**Input**: Target span T(S) + relevant facts
**Expected Outcome**:
- Reconstructed candidate R(S) produced
- Proof trace describing derivation steps
- Uncovered words/phrases identified (if any)
- Span state transition: ATTEMPTABLE → PROVEN or FAILED

**Unexpected Outcomes (STOP + REPORT)**:
- No proof trace produced
- Span stuck in ATTEMPTABLE
- R(S) produced but no comparison to T(S)

### Step 7: Reconstruction Comparison
**Input**: T(S) and R(S)
**Expected Outcome**:
- Byte-for-byte comparison performed
- If match: span → PROVEN
- If mismatch: uncovered words/phrases list produced

**Unexpected Outcomes (STOP + REPORT)**:
- Semantic comparison instead of byte-exact
- Paraphrased R(S) accepted as match
- Missing uncovered list on mismatch

### Step 8: Anchoring Operation (on failure)
**Input**: Uncovered words/phrases from failed reconstruction
**Expected Outcome**:
- Context expansion attempted
- Existing fact search performed
- New fact extraction attempted
- Anchor validation via re-reconstruction
- Progress tracked (did uncovered shrink?)

**Unexpected Outcomes (STOP + REPORT)**:
- No anchoring attempted
- Anchoring skipped straight to Clarification Question
- No progress tracking

### Step 9: Clarification Question Emission
**Input**: Anchoring failure after bounded attempts
**Expected Outcome**:
- Clarification Question artifact produced ONLY when:
  - Anchoring failed after bounded attempts, OR
  - Derivation is impossible
- NOT produced when implied facts simply weren't extracted
- Contains: doc_id, region_offsets, verbatim quoted text, failure statement

**Unexpected Outcomes (STOP + REPORT)**:
- Clarification Question for derivable facts
- Missing artifact fields
- No bounded attempts before emission

### Step 10: Termination
**Input**: All work regions processed
**Expected Outcome**:
- All spans in PROVEN or FAILED (with Clarification Questions)
- Termination criteria met:
  - Reconstruction threshold (sufficient facts)
  - Derivability criterion (base facts can derive implications)
- No unprocessed regions remain

**Unexpected Outcomes (STOP + REPORT)**:
- Spans stuck in ATTEMPTABLE
- Termination without derivability check
- Silent failure (no FAILED state, no Clarification Question)

---

## Test Scenario Hypotheses

Each test scenario is a hypothesis about what invariants it exercises. We design minimal inputs that we BELIEVE will trigger specific behaviors.

### Hypothesis Format

```yaml
scenario_id: TS-001
name: Short descriptive name
hypothesis: What invariants we THINK this tests
input: The test input
expected_steps:
  - step: Step name
    expected: What should happen
    captures_invariant: Which invariant this step tests
stop_conditions:
  - What unexpected outcome would cause STOP + REPORT
actual_captures: [To be filled after running - what we ACTUALLY tested]
```

### Scenario Categories

**Category A: Clean Path (Happy Path)**
Tests where everything should work correctly. Validates that the system doesn't break on valid input.

**Category B: Grammar Fabrication Detection**
Inputs designed to trigger each of the 5 grammar fabrication types.

**Category C: Inference Fabrication Detection**
Inputs designed to trigger each of the 3 inference fabrication types.

**Category D: Reconstruction Threshold**
Inputs where reconstruction succeeds but not all facts are extracted.

**Category E: Anchoring Path**
Inputs that require anchoring before reconstruction succeeds.

**Category F: Island Join Failures**
Inputs with proven islands but unanchored joins.

**Category G: Clarification Question Path**
Inputs that should legitimately require Clarification Questions.

---

## Initial Test Scenarios

### TS-001: Simple Base Fact Extraction

```yaml
scenario_id: TS-001
name: Simple Base Fact Extraction
hypothesis: Tests basic pipeline for clean base fact
input: "The device supports Wi-Fi."
expected_steps:
  - step: Ingestion
    expected: Canonical string = "The device supports Wi-Fi."
    captures_invariant: "#1 - byte-exact provenance"
  - step: Fact Extraction
    expected:
      - fact: (The device, supports, Wi-Fi)
      - type: Base Fact
      - offsets: [0, 26]
    captures_invariant: "Base/Implied Taxonomy"
  - step: NLTK Validation
    expected: No flags (verb ROOT present, nsubj present)
    captures_invariant: "#9 - no illegal fabrication"
  - step: Reconstruction
    expected: R(S) = "The device supports Wi-Fi." (exact match)
    captures_invariant: "#1 - byte-exact reconstruction"
  - step: Termination
    expected: Span → PROVEN
    captures_invariant: "#4 - span lifecycle"
stop_conditions:
  - Compound fact extracted
  - Any NLTK flags raised
  - R(S) != T(S)
```

### TS-002: Hidden Copula Detection

```yaml
scenario_id: TS-002
name: Hidden Copula Detection
hypothesis: Tests that NLTK catches Hidden Copula Hallucination (type 1)
input: "red flowers scattered across the floor"
expected_steps:
  - step: Fact Extraction
    expected:
      - Attempted triplet: (red flowers, ARE scattered across, the floor)
      - Note: LLM may try to add "are"
    captures_invariant: "Grammar fabrication detection"
  - step: NLTK Validation
    expected:
      - Flag: HIDDEN_COPULA
      - Reason: No verb ROOT in source (participial phrase, not sentence)
    captures_invariant: "#9 - type 1 detection"
  - step: Escalation
    expected:
      - FabricationAttempt artifact created
      - Entity Declaration recorded instead
    captures_invariant: "#9 - correct handling"
stop_conditions:
  - Triplet with "are" passes NLTK without flag
  - No FabricationAttempt artifact
```

### TS-003: Forced Subject Detection

```yaml
scenario_id: TS-003
name: Forced Subject Detection
hypothesis: Tests that NLTK catches Forced Subject Hallucination (type 5)
input: "also buffalo sauce"
expected_steps:
  - step: Fact Extraction
    expected:
      - Attempted triplet: (Buffalo sauce, is included in, THE SCENARIO)
      - Note: LLM may fabricate "scenario" as subject
    captures_invariant: "Grammar fabrication detection"
  - step: NLTK Validation
    expected:
      - Flag: FORCED_SUBJECT
      - Reason: No nsubj in source
    captures_invariant: "#9 - type 5 detection"
  - step: Escalation
    expected:
      - FabricationAttempt artifact created
      - Entity Declaration: "buffalo sauce" with attribute "also"
    captures_invariant: "#9 - syntactic orphan handling"
stop_conditions:
  - "scenario" or any invented entity passes validation
  - No Entity Declaration fallback
```

### TS-004: Invalid Coreference Inference

```yaml
scenario_id: TS-004
name: Invalid Coreference Inference
hypothesis: Tests that Opus catches Invalid Coreference Inference (type 6)
input: "red flowers scattered across the floor, erupting from the palms of its hands"
expected_steps:
  - step: Fact Extraction
    expected:
      - Base fact: (red flowers, scattered across, the floor)
      - Attempted inference: "its" refers to "flowers"
    captures_invariant: "Base/Implied Taxonomy"
  - step: Inference Validation
    expected:
      - Flag: INVALID_COREFERENCE
      - Reason: Number mismatch (flowers=plural, its=singular)
    captures_invariant: "#9 - type 6 detection"
  - step: Escalation
    expected:
      - InvalidInferenceAttempt artifact created
      - Clarification Question about "its" referent
    captures_invariant: "#6 - progress test"
stop_conditions:
  - "its" = "flowers" inference passes
  - No InvalidInferenceAttempt artifact
```

### TS-005: Reconstruction Threshold vs Exhaustive

```yaml
scenario_id: TS-005
name: Reconstruction Threshold vs Exhaustive Extraction
hypothesis: Tests that PROVEN ≠ all facts extracted
input: "red flowers scattered across the floor"
expected_steps:
  - step: Fact Extraction
    expected:
      - Extracted: (red flowers, scattered across, the floor)
      - NOT extracted: "flowers are on the floor" (implication)
    captures_invariant: "Reconstruction Threshold"
  - step: Reconstruction
    expected:
      - R(S) = "red flowers scattered across the floor" (exact match)
      - Span → PROVEN
    captures_invariant: "#4 - span lifecycle"
  - step: Termination
    expected:
      - PROVEN despite implication not explicitly extracted
      - Derivability criterion satisfied (implication derivable)
    captures_invariant: "#11 - Derivability Principle"
stop_conditions:
  - System continues extracting after reconstruction succeeds
  - System claims incomplete because implication wasn't extracted
```

### TS-006: Anchoring Path

```yaml
scenario_id: TS-006
name: Anchoring Path Triggered
hypothesis: Tests anchoring operation when reconstruction fails
input: "Replace partition-style span fragmentation with work region tracking over the canonical input string"
expected_steps:
  - step: Fact Extraction (pass 1)
    expected:
      - Extracted: Facts about "span fragmentation" and "work region tracking"
      - Missed: "over the canonical input string"
    captures_invariant: "Partial extraction expected"
  - step: Reconstruction (pass 1)
    expected:
      - R(S) missing "over the canonical input string"
      - Span → FAILED
      - Uncovered: "over the canonical input string"
    captures_invariant: "#1 - byte-exact comparison"
  - step: Anchoring
    expected:
      - Context expansion around uncovered phrase
      - Search for facts mentioning "canonical", "input", "string"
      - Re-extraction attempted
    captures_invariant: "#7 - anchoring operation"
  - step: Reconstruction (pass 2)
    expected:
      - New facts anchor the phrase
      - R(S) now complete
      - Span → PROVEN
    captures_invariant: "#6 - progress test"
stop_conditions:
  - No anchoring attempted after failure
  - Immediate Clarification Question without anchoring
```

### TS-007: Island Join Failure

```yaml
scenario_id: TS-007
name: Island Join Failure Detection
hypothesis: Tests detection of proven islands with unanchored join
input: "The server handles requests buffalo sauce"
expected_steps:
  - step: Fact Extraction
    expected:
      - Island 1: (The server, handles, requests) - Base Fact
      - Island 2: Entity Declaration for "buffalo sauce"
    captures_invariant: "Base/Implied Taxonomy"
  - step: Reconstruction
    expected:
      - Island 1: PROVEN
      - Island 2: PROVEN (as entity declaration)
      - Join: UNANCHORED (no relation connects them)
    captures_invariant: "#8 - island join failures"
  - step: Escalation
    expected:
      - ReconstructionFailure artifact with:
        - Both islands marked PROVEN
        - Unanchored boundary identified
      - Clarification Question about relationship
    captures_invariant: "#8 - system response"
stop_conditions:
  - System forces a relation between islands
  - No detection of unanchored join
```

### TS-008: Derivability Criterion

```yaml
scenario_id: TS-008
name: Derivability Criterion in Termination
hypothesis: Tests that termination checks derivability, not just reconstruction
input: "The device is portable and lightweight."
expected_steps:
  - step: Fact Extraction
    expected:
      - Base fact 1: (The device, is, portable)
      - Base fact 2: (The device, is, lightweight)
    captures_invariant: "Base Fact extraction"
  - step: Reconstruction
    expected:
      - R(S) = "The device is portable and lightweight." (exact match)
    captures_invariant: "#1 - byte-exact"
  - step: Termination
    expected:
      - Verify derivability: can implications be derived from base facts?
      - Example derivable: "The device can be carried" (from portable)
      - Criterion: derivable → COMPLETE
    captures_invariant: "#11 - Derivability Principle"
stop_conditions:
  - Termination without derivability check
  - False incomplete due to unextracted implications
```

### TS-009: Clarification Question Only on Failure

```yaml
scenario_id: TS-009
name: No Clarification Question for Derivable Facts
hypothesis: Tests that Clarification Questions aren't emitted for merely unextracted implications
input: "The flowers fell from the vase."
expected_steps:
  - step: Fact Extraction
    expected:
      - Extracted: (The flowers, fell from, the vase)
      - Not extracted: "The flowers are below the vase" (implication)
    captures_invariant: "Reconstruction Threshold"
  - step: Reconstruction
    expected:
      - R(S) = "The flowers fell from the vase." (exact match)
      - Span → PROVEN
    captures_invariant: "#1 - byte-exact"
  - step: Termination
    expected:
      - NO Clarification Question emitted
      - Implication is derivable from base fact
    captures_invariant: "#11 - CQ only on failure"
stop_conditions:
  - Clarification Question about unextracted implication
  - System claims incomplete
```

### TS-010: Ungrounded Implication Detection

```yaml
scenario_id: TS-010
name: Ungrounded Implication Detection
hypothesis: Tests that Opus catches Ungrounded Implication (type 7)
input: "The device is portable."
expected_steps:
  - step: Fact Extraction
    expected:
      - Base fact: (The device, is, portable)
      - Attempted implication: (The device, is, wireless)
    captures_invariant: "Base/Implied detection"
  - step: Inference Validation
    expected:
      - Flag: UNGROUNDED_IMPLICATION
      - Reason: Portability does not entail wirelessness
    captures_invariant: "#9 - type 7 detection"
  - step: Escalation
    expected:
      - InvalidInferenceAttempt artifact
      - Only base fact retained
    captures_invariant: "Correct handling"
stop_conditions:
  - "wireless" inference passes
  - No InvalidInferenceAttempt artifact
```

---

## Discovery Process

### Phase 1: Initial Run

1. Run all initial test scenarios
2. For each scenario, record at each step:
   - Expected outcome
   - Actual outcome
   - Match/Mismatch
3. STOP on first mismatch per scenario
4. Collect all mismatches

### Phase 2: Hypothesis Refinement

For each mismatch:
1. Analyze: Did we test what we thought we tested?
2. Update `actual_captures` field
3. If different invariant was exercised:
   - Create new scenario for intended invariant
   - Rename current scenario for actual invariant

### Phase 3: Coverage Analysis

1. Map all scenarios to invariants they actually capture
2. Identify uncovered invariants
3. Design new scenarios targeting gaps
4. Add to test suite

### Phase 4: Iteration

Repeat Phases 1-3 until:
- All invariants have at least one capturing scenario
- All scenarios have clean runs (or documented known issues)

---

## Bug Reporting Protocol

When a step produces unexpected outcome:

```yaml
bug_report:
  scenario_id: TS-XXX
  step: Step where mismatch occurred
  expected: What we expected
  actual: What we got
  invariant_at_risk: Which invariant may be violated
  severity: critical/major/minor
  reproducible: yes/no/intermittent
  notes: Additional context
```

### Severity Levels

- **Critical**: Invariant definitely violated (e.g., fabricated fact passed validation)
- **Major**: Invariant likely violated (e.g., anchoring skipped)
- **Minor**: Unexpected behavior but invariant may still hold (e.g., extra flags raised)

---

## Artifact Requirements

Each test run must produce:

1. **Step Trace**: Log of each step with expected/actual comparison
2. **Artifacts Collected**: All FabricationAttempt, InvalidInferenceAttempt, ReconstructionFailure, Clarification Question artifacts
3. **Final State**: Span states, fact list, uncovered regions
4. **Pass/Fail Summary**: Which steps passed, where first failure occurred

### Directory Structure

```
.tasks/qa/
├── scenarios/
│   ├── TS-001.yaml
│   ├── TS-002.yaml
│   └── ...
├── runs/
│   ├── run-2025-01-15/
│   │   ├── TS-001-trace.json
│   │   ├── TS-001-artifacts/
│   │   └── summary.json
│   └── ...
├── bugs/
│   ├── BUG-001.yaml
│   └── ...
└── coverage/
    └── invariant-coverage.md
```

---

## Next Steps

1. **Implement Test Harness**: Script that runs scenarios and produces traces
2. **Create Scenario Files**: Convert hypotheses above to executable format
3. **Run Initial Suite**: Execute Phase 1
4. **Analyze Results**: Refine hypotheses, identify gaps
5. **Iterate**: Until coverage is satisfactory

---

## Appendix: Invariant Quick Reference

| # | Short Name | Key Test |
|---|------------|----------|
| 1 | Byte-exact Provenance | R(S) == T(S) character-for-character |
| 2 | No Semantic Classification | Links are untyped |
| 3 | Incomplete Expected | No false completeness claims |
| 4 | Span Lifecycle | ATTEMPTABLE → PROVEN/FAILED only |
| 5 | Facts Don't Own Text | No "evidence offset" ownership |
| 6 | Progress Test | Anchoring before Clarification |
| 7 | Anchoring Operation | Context expand → search → extract → validate |
| 8 | Island Join Failures | Detect proven islands + unanchored join |
| 9 | No Illegal Fabrication | NLTK (1-5) + Opus (6-8) catch all types |
| 10 | No Formal Proof Languages | No Lean/Coq in pipeline |
| 11 | Derivability Principle | Termination uses derivability criterion |

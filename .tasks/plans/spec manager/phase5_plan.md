# Phase 5 Implementation Plan: Remove Hardcoded Semantic Heuristics

## Overview

Phase 5 eliminates keyword/regex-based semantic inference on uncontrolled text per CON-0003 and CON-0004. All semantic decisions must come from (a) LLM contract outputs or (b) purely structural metrics, with heuristics allowed only as explicitly non-authoritative fallbacks emitting GapElements with confidence < 0.5.

## Current State Analysis

**Identified Violations:**

| File | Location | Violation Type | Description |
|------|----------|----------------|-------------|
| `strategies/implementations/entity_resolution.py` | L23-30 | Regex on uncontrolled text | `_VAGUE_REFERENCE_PATTERNS` scans raw text for "this", "that", "the algorithm" |
| `strategies/implementations/entity_resolution.py` | L32-37 | Semantic word list | `_GENERIC_NOUN_TYPES` maps words to unit types |
| `strategies/implementations/llm_inference.py` | L94-99 | Keyword patterns | `requirement_patterns` in `_heuristic_inference()` |
| `core/gaps.py` | L1039-1044 | Keyword patterns | `_detect_requirement_patterns()` uses modal verb regex |
| `core/gaps.py` | L1078-1083 | Keyword patterns | `_detect_claim_patterns()` uses semantic word patterns |
| `core/gaps.py` | L261-312 | Semantic word lists | `UndefinedFunctionDetector.DEFAULT_BUILTINS/CATEGORIES` |

**Compliant Infrastructure Already Available:**

1. `hardcoding_scanner.py` - Phase 1 scanner that detects violations
2. `StrategyRegistry.evidence_summary` - structural signals for gating
3. `RiskSignal` enum with structural metrics: `PROSE_RATIO`, `REMAINDER_RATIO`, `UNRESOLVED_REF_COUNT`, `COVERAGE_GAP_COUNT`
4. LLM inference framework in `llm_inference.py`
5. `GapElement` / `DetectorFinding` output structures with confidence fields

---

## Work Item 1: Strategy Gating Without Raw-Text Scanning

**Goal:** Replace vague-reference regex gating in entity resolution with always-run on scoped units OR LLM-produced "unresolved reference count" signal.

**Current Problem:**
```python
# entity_resolution.py L73-75
def applies_to(self, context: ProcessingContext) -> bool:
    return any(self._find_vague_references(unit.content) for unit in context.units)
```
This scans raw text with `_VAGUE_REFERENCE_PATTERNS`.

**Solution:**

1. **Option A: Always-run on scoped units**
   - Remove `applies_to()` text scanning
   - Run on all PROSE-type units in RESOLUTION phase
   - Let LLM determine if resolution is needed

2. **Option B: Structural signal gating**
   - Add new risk signal `UNRESOLVED_REF_COUNT` to `ProcessingContext.evidence_summary`
   - Gate strategy on `evidence_summary.get("unresolved_references", 0) > 0`
   - Signal computed from structural analysis (count of `(@[+ID])` patterns not matching declared IDs)

**Implementation:**
- Modify `EntityResolutionStrategy.applies_to()` to use structural gating
- Add `compute_unresolved_references()` function to compute signal from ID registry
- Remove `_VAGUE_REFERENCE_PATTERNS` and `_find_vague_references()` method

**Files to Modify:**
- `scripts/spec_manager/spec_manager/strategies/implementations/entity_resolution.py`
- `scripts/spec_manager/spec_manager/strategies/registry.py` (add signal mapping)

---

## Work Item 2: Rewrite Gap Detectors Using LLM or Structural Methods

**Goal:** Convert keyword-list detectors to structural detectors OR LLM detectors outputting schema-validated `DetectorFinding`.

### 2.1 ProseFragmentInferenceDetector Refactor

**Current Problem:** Uses hardcoded keyword patterns for requirement/claim detection.

**Solution:**
- Primary: LLM-based detection with schema-validated output
- Fallback: Structural analysis (sentence length, question marks, ID density)
- Remove: `_detect_requirement_patterns()`, `_detect_claim_patterns()` keyword lists

**New Structure:**
```python
class ProseFragmentInferenceDetector:
    def detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        if self._llm:
            return self._llm_detect(content, file_path)
        else:
            return self._structural_detect(content, file_path)

    def _structural_detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        # Structural signals only:
        # - Sentence count
        # - ID reference density
        # - Question mark presence (uncertainty)
        # No keyword matching
        ...
```

### 2.2 UndefinedFunctionDetector Refactor

**Current Problem:** `DEFAULT_BUILTINS` and `DEFAULT_CATEGORIES` are hardcoded word lists.

**Solution:**
- Move all word lists to YAML config (already partially done)
- Make detector emit non-authoritative findings (confidence < 0.5) when using defaults
- Document that config-based lists are "configurable hints, not semantic rules"

**Files to Modify:**
- `scripts/spec_manager/spec_manager/core/gaps.py`

---

## Work Item 3: Heuristic Fallbacks Become Non-Authoritative

**Goal:** Any residual heuristics must emit `GapElement`, set confidence < 0.5, never overwrite authority without confirmation.

**Implementation:**

1. **Add `is_authoritative` field to DetectorFinding**
   ```python
   @dataclass
   class DetectorFinding:
       ...
       is_authoritative: bool = True  # False for heuristic fallbacks
   ```

2. **Update heuristic fallback paths:**
   - `EntityResolutionStrategy._resolve_with_heuristic()` - already returns confidence 0.55-0.6, update to < 0.5
   - `ProseFragmentInferenceDetector._heuristic_inference()` - update to return confidence < 0.5
   - All pattern-based detections in `_structural_detect()` - mark non-authoritative

3. **Add policy enforcement in GapSynthesis:**
   - Non-authoritative findings route to `GAP_TYPE.NON_AUTHORITATIVE`
   - Non-authoritative gaps require auditor confirmation before promoting

**Files to Modify:**
- `scripts/spec_manager/spec_manager/core/gaps.py`
- `scripts/spec_manager/spec_manager/strategies/implementations/entity_resolution.py`
- `scripts/spec_manager/spec_manager/strategies/implementations/llm_inference.py`

---

## Work Item 4: Introduce Regression Fixtures

**Goal:** Regression fixtures that assert no forbidden heuristic signatures and stable outputs.

**Implementation:**

1. **Create fixture directory structure:**
   ```
   tests/spec_manager/compliance/fixtures/
     phase5/
       entity_resolution/
         input_vague_refs.md
         expected_structural_signal.json
       gap_detection/
         input_prose_fragment.md
         expected_structural_output.json
   ```

2. **Create compliance test module:**
   ```python
   # tests/spec_manager/compliance/test_no_hardcoding_compliance.py

   class TestEntityResolutionNoHardcoding:
       def test_applies_to_uses_structural_gating(self):
           # Verify applies_to() does not scan raw text
           ...

       def test_no_forbidden_patterns_in_strategy(self):
           # Scan strategy code for forbidden heuristic signatures
           scanner = HardcodingScanner()
           findings = scanner.scan_file(entity_resolution_path)
           assert len(findings) == 0

   class TestGapDetectorsNoHardcoding:
       def test_prose_detector_uses_llm_or_structural(self):
           ...

       def test_undefined_function_config_driven(self):
           ...
   ```

3. **Add forbidden signature assertions:**
   - No `re.compile(r"...(must|shall|should)...")` in detection paths
   - No `if "keyword" in text.lower()` patterns
   - Config-loaded lists must have audit trail

**Files to Create:**
- `tests/spec_manager/compliance/test_no_hardcoding_compliance.py`
- `tests/spec_manager/compliance/fixtures/phase5/` directory structure

---

## Implementation Sequence

```
Phase 5.1: Strategy Gating Refactor
  ├── Add compute_unresolved_references() function
  ├── Modify EntityResolutionStrategy.applies_to()
  ├── Remove _VAGUE_REFERENCE_PATTERNS
  └── Tests for structural gating

Phase 5.2: Gap Detector Rewrites
  ├── Refactor ProseFragmentInferenceDetector
  ├── Move keyword detection to LLM contract or structural
  ├── Add structural-only fallback
  └── Update UndefinedFunctionDetector config loading

Phase 5.3: Non-Authoritative Heuristics
  ├── Add is_authoritative field to DetectorFinding
  ├── Update all heuristic fallbacks to confidence < 0.5
  ├── Add NON_AUTHORITATIVE gap handling
  └── Policy enforcement in gap synthesis

Phase 5.4: Regression Fixtures
  ├── Create fixture directory structure
  ├── Add compliance test module
  ├── Add forbidden signature assertions
  └── Verify no hardcoding scanner findings
```

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `strategies/implementations/entity_resolution.py` | MODIFY | Remove regex patterns, use structural gating |
| `strategies/registry.py` | MODIFY | Add structural signal computation |
| `core/gaps.py` | MODIFY | Refactor detectors, add is_authoritative |
| `strategies/implementations/llm_inference.py` | MODIFY | Update heuristic confidence to < 0.5 |
| `tests/spec_manager/compliance/test_no_hardcoding_compliance.py` | NEW | Compliance regression tests |
| `tests/spec_manager/compliance/fixtures/phase5/` | NEW | Test fixtures |

---

## Constraints Addressed

| Constraint | Implementation |
|------------|----------------|
| CON-0003 | No keyword inference from raw spec text |
| CON-0004 | Regex only on system-owned patterns |
| CON-0015 | Strategy gating via structural signals |
| AUTH-0001 | Heuristics non-authoritative (confidence < 0.5) |

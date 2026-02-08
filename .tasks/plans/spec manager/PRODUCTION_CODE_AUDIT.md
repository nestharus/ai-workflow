# Spec Manager Production Code Audit

## Date: 2026-02-07

## Scope

Audit of spec_manager production source code (NOT evals, NOT tests) for
reward hacking, hardcoding, stopwords, and suspicious patterns.

Directories audited:
- `scripts/spec_manager/spec_manager/refinement/workflows/`
- `scripts/spec_manager/spec_manager/refinement/formats.py`
- `scripts/spec_manager/spec_manager/refinement/` (all non-eval files)
- `scripts/spec_manager/spec_manager/core/`
- `scripts/spec_manager/spec_manager/schemas/`

---

## Finding 1: Stopword Filters in formats.py (HIGH)

Four places silently drop content matching hardcoded stopword sets.

### 1a. Overlap Resolution Filtering (line 510)

`_parse_overlap_resolutions()`:
```python
if raw.lower() in {"none", "n/a", "no overlaps"}:
    continue
```
Silently removes overlap entries containing "none", "n/a", or "no overlaps"
without logging. Removes negative evidence that could indicate missing overlaps.

### 1b. Library ID Filtering (lines 1310-1320)

`_extract_component_mappings()`:
```python
lowered = lib_id.lower()
if lowered in {"none", "n/a"} or lowered.startswith("none"):
    continue
```
Filters library components labeled as "none" without logging.

### 1c. Unmapped Libraries Filtering (lines 1365-1375)

`parse_architecture_mapping()`:
```python
lowered = item.lower()
if item and lowered not in {"none", "n/a"} and not lowered.startswith("none"):
    unmapped.append(item)
```
Double filtering for "none/n/a" variants. Prevents them from appearing
in the unmapped libraries list.

### 1d. Evidence Placeholder Acceptance (summarization.py line 181)

`_validate_evidence_in_summary()`:
```python
if "evidence: n/a" in lowered or "evidence: none" in lowered:
    continue
```
Accepts "evidence: n/a" and "evidence: none" as valid placeholders without
requiring actual evidence pointers. Files pass validation with no evidence.

---

## Finding 2: Hardcoded LLM Output Allowlists in formats.py (HIGH)

`parse_concern_assignment_judge()` forces LLM output into narrow choices.

### 2a. Gap Type Validation (line 689)

```python
valid_gap_types = {"out_of_scope", "ambiguous"}
```
Only 2 allowed gap types. Any LLM output with a different gap type
(e.g., "incomplete", "unclear", "conflicting") is rejected.

### 2b. Decision Type Validation (line 690)

```python
valid_decisions = {"deferred", "needs_clarification"}
```
Only 2 allowed decision types. Forces the LLM into binary choices.

---

## Finding 3: Placeholder TF-IDF Fallback (MEDIUM)

`library_structure_review.py` lines 271-282, `_fit_tfidf_vectorizer()`:
```python
if not lib_ids:
    vectorizer.fit(["placeholder"])
    return {}, vectorizer

try:
    ...
except ValueError as exc:
    logger.warning("TF-IDF vectorization failed (%s); using placeholder vocab", exc)
    vectorizer.fit(["placeholder"])
    matrix = vectorizer.transform(documents)
```
When vectorization fails, silently fits on `["placeholder"]` and continues
with dummy vectors instead of failing. Biases similarity scores.

---

## Finding 4: Magic Confidence Thresholds (MEDIUM)

### 4a. sublibrary_detection.py (line 637)

```python
if confidence_value is None or confidence_value < 0.5:
    continue
```
Silently skips findings below 0.5 confidence. No logging, no reporting.

### 4b. sublibrary_detection.py (line 583)

```python
_process_evidence_expansion(raw_summary, valid_sections, 0.5, ...)
```
Hardcoded 0.5 threshold with no explanation or configuration.

---

## Finding 5: Undocumented Magic Constants (MEDIUM)

### 5a. library_structure_review.py (lines 65-70)

```python
_DEFAULT_THRESHOLDS = {
    "overlap_similarity": 0.35,
    "min_shared_elements": 5,
    "split_silhouette": 0.3,
    "split_min_elements": 10,
}
```
4 thresholds with no justification, no documentation, no override mechanism.

### 5b. library_structure_review.py (line 337)

Hardcoded `threshold: float = 0.70` for element similarity in
`_find_shared_elements()`.

---

## Finding 6: Silent Error Swallowing (MEDIUM)

`library_labeling.py` lines 110-127, `_normalize_labeler_output()`:
```python
except json.JSONDecodeError as exc:
    return {}, [{"type": "invalid_json", ...}]

if not isinstance(data, dict):
    return {}, [{"type": "invalid_payload", ...}]
```
Returns empty `{}` on parse failures instead of raising. Downstream code
receives empty output that may be indistinguishable from legitimate
empty responses.

---

## Summary

| # | Finding | File | Severity |
|---|---------|------|----------|
| 1a | "none/n/a" stopword filter | formats.py:510 | HIGH |
| 1b | "none/n/a" stopword filter | formats.py:1310-1320 | HIGH |
| 1c | "none/n/a" stopword filter | formats.py:1365-1375 | HIGH |
| 1d | "evidence: n/a" acceptance | summarization.py:181 | HIGH |
| 2a | 2-option gap type allowlist | formats.py:689 | HIGH |
| 2b | 2-option decision allowlist | formats.py:690 | HIGH |
| 3 | Placeholder TF-IDF fallback | library_structure_review.py:271 | MEDIUM |
| 4a | Silent confidence cutoff | sublibrary_detection.py:637 | MEDIUM |
| 4b | Hardcoded threshold | sublibrary_detection.py:583 | MEDIUM |
| 5a | 4 undocumented thresholds | library_structure_review.py:65 | MEDIUM |
| 5b | Undocumented similarity threshold | library_structure_review.py:337 | MEDIUM |
| 6 | Silent error swallowing | library_labeling.py:110 | MEDIUM |

Total: 6 HIGH, 6 MEDIUM

---

## Evaluation Against the Spirit of the Plans

### Context

The plans in `.tasks/plans/spec manager/plans/` (01-11) define a completely
different architecture called PDD (Plan-Driven Development). Per
`CONSOLIDATION_CONCLUSIONS.md`, the refinement pipeline (19 phases in
`refinement/workflows/`) is **THE WRONG SYSTEM** and the PDD modules
(branches/, pin_functions/, planning/, core/edit_in_place.py) are **THE RIGHT
SYSTEM**.

**Every single finding in this audit is located in the refinement pipeline.**
None are in PDD module code.

### Per-Finding Evaluation

**Finding 1 (Stopword Filters):** The refinement pipeline parses LLM output
as text and applies stopword filters to clean it. The PDD system eliminates
this entire category of problem:
- Plan 01 (edit-in-place): "Comments = gaps, period" -- mechanical detection
  via `ast`/`tokenize`, no LLM text to filter.
- Plan 05 (executable gap detection): Comment scanner uses `tokenize` to
  extract Python comments. Stubs detected via AST. No "none/n/a" filtering
  because the inputs are Python source, not LLM prose.
- Plan 06 (hollowed-out evidence): Uses keyword + entity indexing with
  deterministic scoring, not LLM output parsing.

**Verdict: MOOT.** These filters exist because the refinement pipeline
depends on LLM output parsing. The PDD system eliminates LLM-dependent
parsing for gap detection entirely.

---

**Finding 2 (Hardcoded Allowlists):** The refinement pipeline forces LLM
gap judgments into 2-option buckets. The PDD system replaces LLM gap
judgment with mechanical detection:
- Plan 05 defines five mechanical gap types: `unimplemented_comment`,
  `stub_function`, `runtime_not_implemented`, `disconnected_subgraph`,
  `uncovered_path`. These are binary (present/absent), not probabilistic.
- Plan 08 (compliance gating): Gate checks are pass/fail against explicit
  thresholds (`GateMode.REQUIRED` / `GateMode.ADVISORY`), not LLM
  classifications.

**Verdict: MOOT.** LLM output allowlists become irrelevant when gap
detection is mechanical.

---

**Finding 3 (Placeholder TF-IDF):** The refinement pipeline uses TF-IDF
similarity for library structure review. The PDD system replaces this:
- Plan 04 (branch organization): Structure is explicit
  (algorithmic/architectural/analysis branches), not inferred by TF-IDF
  similarity.
- Plan 07 (adjacency detection): Uses call graph + store touch analysis,
  not text similarity.

**Verdict: MOOT.** TF-IDF-based structure review is replaced by explicit
branch organization.

---

**Finding 4 (Magic Confidence Thresholds):** Sublibrary detection uses
hardcoded 0.5 confidence cutoffs. The PDD system:
- Plan 04: Replaces sublibrary detection with explicit branch types
  (`BranchKind.ALGORITHMIC`, `ARCHITECTURAL`, `ANALYSIS`).
- No confidence scoring needed when structure is defined, not inferred.

**Verdict: MOOT.** Sublibrary detection is eliminated.

---

**Finding 5 (Undocumented Constants):** Library structure review has
5 unexplained thresholds. The PDD system:
- Plan 08: Compliance gates have explicit, documented thresholds in
  `PromotionGateConfig` with configurable `GateMode` per check.
- Plan 02: Pin-function similarity uses content hashes (SHA-256), not
  floating-point similarity thresholds.

**Verdict: MOOT.** Opaque thresholds are replaced by explicit, configurable
gate criteria.

---

**Finding 6 (Silent Error Swallowing):** Library labeling returns `{}` on
parse failure. The PDD system:
- All plans use Pydantic `BaseModel` for schemas with strict validation.
  Invalid data raises `ValidationError`, not silent empty returns.
- Plan 01: Uses `ast.parse()` which raises `SyntaxError` on invalid Python.
  No silent fallback.

**Verdict: MOOT.** Pydantic schemas and AST parsing replace silent error
swallowing with explicit validation failures.

---

### Systemic Conclusion

The audit confirms what `CONSOLIDATION_CONCLUSIONS.md` identifies as the
fundamental problem: **the refinement pipeline is inherently LLM-dependent
and probabilistic**, leading to defensive patterns (stopword filters,
confidence thresholds, allowlists, error swallowing) that mask quality
problems rather than preventing them.

The PDD system addresses this architecturally:

| Refinement Anti-Pattern | PDD Replacement |
|------------------------|-----------------|
| LLM output parsing + stopwords | AST/tokenize mechanical detection |
| Allowlisted LLM judgments | Binary pass/fail compliance gates |
| TF-IDF similarity inference | Explicit branch structure |
| Confidence thresholds | Content hashes (SHA-256) |
| Magic constants | Configurable gate configs |
| Silent error swallowing | Pydantic strict validation |

**No findings require fixing in the refinement pipeline.** The correct
action is to complete the consolidation described in
`CONSOLIDATION_CONCLUSIONS.md`: replace the refinement pipeline's
orchestration with the PDD module architecture.

### Risk Note

Until consolidation happens, the refinement pipeline remains the active
system. The findings documented above are live code paths. If the refinement
pipeline is exercised before consolidation, these patterns will affect
results. The priority should be completing the consolidation, not patching
the refinement pipeline.

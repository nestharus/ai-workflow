# Phase 4 Implementation Plan: Migrate to EVID-only Citations

## Overview

Phase 4 enforces that all evidence references in L1 artifacts use canonical EVID IDs (`EVID-F####-R####-L#-L#`) instead of legacy formats like `[F####::SECTION]` or `[spec_snapshot/<relpath>::SEC-...]`. This aligns with CON-0021 (forbidden output signatures) and the authority model (AUTH-0002).

## Current State Analysis

**Existing Infrastructure:**
1. **Evidence Ranges** (`schemas/evidence_ranges.py`)
   - `EVIDENCE_ID_PATTERN = r"^EVID-(?P<file_uid>F\d{4})-(?P<rev_id>R\d{4})-L(?P<start>\d+)-L(?P<end>\d+)$"`
   - EvidenceRange model with validation

2. **Contract Lint** (`refinement/qa/contract_lint.py`)
   - Existing pattern detection: `PREFERRED_POINTER_RE`, `EVIDENCE_POINTER_RE`, `LEGACY_FILE_ID_RE`
   - Integration with hardcoding_scanner for CON-0003/CON-0004

3. **Bad Signatures Scanner** (`refinement/qa/bad_signatures.py`)
   - Detects `derived_pointer`, `arch_file_pointer`, `legacy_pointer_format`
   - Used by QA validators

4. **Legacy Citation Formats in Use:**
   - `[F####::SECTION]` - legacy file pointer
   - `[spec_snapshot/<relpath>::SEC-F####-####]` - new format (not EVID)
   - `[LIB-####::spec.md::REQ-...]` - multi-hop library pointer

---

## Work Item 1: Define Canonical EVID Citation Syntax

**Goal:** Standardize on bracketed EVID format `[EVID-F####-R####-L####-L####]` for human-readable docs.

**Implementation Steps:**

1. **Add EVID_CITATION_PATTERN to evidence_ranges.py**
   ```python
   # Bracketed citation format for human-readable documents
   EVID_CITATION_PATTERN = re.compile(
       r"\[EVID-F\d{4}-R\d{4}-L\d+-L\d+\]"
   )
   ```

2. **Create evid_citation module** (`schemas/evid_citation.py`)
   - `parse_evid_citation(text: str) -> EvidCitation | None`
   - `format_evid_citation(evid: str) -> str` - returns `[EVID-...]`
   - `validate_evid_format(evid: str) -> bool`

3. **Tests** (`tests/spec_manager/schemas/test_evid_citation.py`)
   - Valid/invalid pattern matching
   - Round-trip parsing/formatting

---

## Work Item 2: Add Migration Path from Existing Pointer Formats

**Goal:** Resolve `[F####::SECTION]` and `[spec_snapshot/<relpath>::SEC-...]` to covering EVID range(s).

**Implementation Steps:**

1. **Create citation_migrator module** (`refinement/workflows/citation_migrator.py`)

   Key functions:
   ```python
   def resolve_section_to_evid_ranges(
       file_uid: str,
       section_id: str,
       evidence_ranges: list[EvidenceRange],
   ) -> list[str]:
       """Map a section ID to its covering EVID range(s)."""

   def migrate_legacy_citation(
       citation: str,
       file_manifest: dict,
       section_map: dict,
       evidence_index: dict,
   ) -> list[str]:
       """Convert legacy [F####::SECTION] to [EVID-...] format."""

   def migrate_spec_snapshot_citation(
       citation: str,
       evidence_index: dict,
   ) -> list[str]:
       """Convert [spec_snapshot/<relpath>::SEC-...] to [EVID-...] format."""

   def migrate_document_citations(
       content: str,
       evidence_index: dict,
       file_manifest: dict,
   ) -> tuple[str, list[MigrationIssue]]:
       """Migrate all citations in a document, returning issues for unmapped."""
   ```

2. **Build evidence index** (section_id -> EVID mapping)
   - Use existing `EvidenceRangesArtifact` data from Phase 3
   - Index by file_uid + section_id for fast lookup

3. **Integration with formats.py**
   - Extend `migrate_pointers_to_new_format()` in `refinement/formats.py`
   - Add EVID migration as final step after section resolution

4. **Tests** (`tests/spec_manager/workflows/test_citation_migrator.py`)
   - Legacy format migration
   - spec_snapshot format migration
   - Multi-section range expansion
   - Unmapped citation handling

---

## Work Item 3: Update Contract Lint for EVID-only Enforcement

**Goal:** Evidence fields must contain only `EVID-*` (hard error). Free-text scan warns on derived-artifact tokens.

**Implementation Steps:**

1. **Add EVID validation to contract_lint.py**

   New patterns:
   ```python
   # Per CON-0021: Evidence fields must be EVID-* only
   EVID_FIELD_PATTERN = re.compile(r"^EVID-F\d{4}-R\d{4}-L\d+-L\d+$")

   # Derived artifact tokens to warn on (per CON-0021)
   DERIVED_ARTIFACT_TOKENS = [
       re.compile(r"runs/"),
       re.compile(r"views/"),
       re.compile(r"spec_snapshot/"),
       re.compile(r"\.json$"),
       re.compile(r"\.yaml$"),
   ]
   ```

2. **Create evidence_field_lint module** (`compliance/evidence_field_lint.py`)

   Implements `ALG-COMP-0005: ScanForForbiddenOutputSignatures` from design doc:
   ```python
   def scan_evidence_fields(
       artifact: dict,
       allowlists: dict[str, list[str]] | None = None,
   ) -> tuple[list[str], list[str]]:
       """Scan artifact for evidence field violations.

       Returns (errors, warnings) per CON-0021.
       - errors: evidence fields with non-EVID values (hard error)
       - warnings: free-text with derived artifact references
       """

   def lint_l1_artifact(
       artifact_path: Path,
       artifact_type: str,
   ) -> LintResult:
       """Lint an L1 artifact for EVID-only compliance."""
   ```

3. **Integrate with existing contract lint**
   - Add to `run_contract_lint()` function
   - Scan L1 artifacts (libraries/*.md, spec_index.json)
   - Hard error for non-EVID evidence references
   - Warning for derived artifact paths in free text

4. **Update bad_signatures.py**
   - Add new signature for legacy pointers in evidence fields
   - Add signature for spec_snapshot in evidence context

5. **Tests** (`tests/spec_manager/compliance/test_evidence_field_lint.py`)
   - Valid EVID-only artifact passes
   - Legacy pointer in evidence field fails
   - spec_snapshot in evidence field fails
   - Derived path in free text warns
   - Allowlist suppression works

---

## Work Item 4: Update Agent Prompts and Repairers

**Goal:** Prompts demonstrate EVID format examples and prohibit path-based citations.

**Implementation Steps:**

1. **Update evidence-producing agent prompts** in `.agents/agents/`:

   Key files to update (if they exist):
   - `glm-library-evidence-mapper.md` - Add EVID output format
   - `glm-library-spec-integrator.md` - Update citations field
   - `chatgpt-evidence-gap-judge.md` - EVID in rationale
   - `chatgpt-concern-assignment-judge.md` - EVID citations
   - `chatgpt-patch-repairer.md` - EVID-only repairs
   - `chatgpt-task-plan-judge.md` - Task citation validation
   - `opus-task-planner.md` - Task citations

2. **Add EVID examples to prompts**
   ```markdown
   ## Evidence Citation Format

   Evidence MUST use EVID format: `[EVID-F####-R####-L#-L#]`

   FORBIDDEN:
   - Legacy pointers: [F0001::INTRO]
   - Spec snapshot paths: [spec_snapshot/file.md::SEC-F0001-0001]
   - File paths: runs/001/artifacts/file.json
   - Library pointers in evidence fields: [LIB-0001::...]

   ALLOWED:
   - EVID ranges: [EVID-F0001-R0001-L1-L25]
   - Multiple ranges: [EVID-F0001-R0001-L1-L10] [EVID-F0001-R0001-L15-L20]
   ```

3. **Create/update repairers**:
   - Add `repair-evid-citations.md` agent prompt
   - Update `chatgpt-patch-repairer.md` to enforce EVID-only

4. **Update contract lint for agent prompts**
   - Extend `lint_agent_prompts()` to require EVID examples
   - Add check for EVID format documentation in evidence-producing prompts

5. **Tests**
   - Lint agent prompts for required EVID documentation
   - Verify repairer outputs EVID-only citations

---

## Implementation Sequence

```
Phase 4.1: Define EVID Citation Syntax
  ├── Add EVID_CITATION_PATTERN
  ├── Create evid_citation.py module
  └── Tests for pattern validation

Phase 4.2: Build Migration Infrastructure
  ├── Create citation_migrator.py
  ├── Build section -> EVID index
  ├── Extend formats.py migration
  └── Migration tests

Phase 4.3: Contract Lint Enforcement
  ├── Create evidence_field_lint.py
  ├── Implement ALG-COMP-0005
  ├── Integrate with run_contract_lint()
  └── Enforcement tests

Phase 4.4: Agent Prompt Updates
  ├── Update evidence-producing prompts
  ├── Add EVID format examples
  ├── Create repairer prompt
  └── Prompt lint tests
```

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `schemas/evid_citation.py` | NEW | EVID citation parsing/formatting utilities |
| `refinement/workflows/citation_migrator.py` | NEW | Legacy to EVID migration functions |
| `compliance/evidence_field_lint.py` | NEW | ALG-COMP-0005 implementation |
| `schemas/evidence_ranges.py` | MODIFY | Add EVID_CITATION_PATTERN |
| `refinement/qa/contract_lint.py` | MODIFY | Add EVID enforcement rules |
| `refinement/qa/bad_signatures.py` | MODIFY | Add legacy pointer signatures |
| `refinement/formats.py` | MODIFY | Extend migration to include EVID |

---

## Test Strategy

1. **Unit Tests**
   - EVID pattern parsing/validation
   - Migration function correctness
   - Lint rule detection

2. **Integration Tests**
   - End-to-end migration of sample documents
   - Contract lint on real L1 artifacts
   - Full workflow with Phase 3 evidence ranges

3. **Regression Tests**
   - Existing citation formats still parseable (for reading)
   - Migration preserves semantic meaning
   - No false positives in lint

---

## Constraints Addressed

| Constraint | Implementation |
|------------|----------------|
| CON-0021 | Evidence fields EVID-only; derived artifact warnings |
| CON-0004 | Regex only on system-owned EVID format |
| AUTH-0002 | L1 artifacts use canonical evidence references |

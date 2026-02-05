# Phase 7 Implementation Plan: Projection Pins, Atom-Aware Drift, and Legacy Removal

## Overview

**Phase 7 Goal:** Enforce the authority model where L2 docs (plan.md, tasks.md, architecture.md) are regenerated projections pinned to L1 IDs, drift-checked via atom alignment, and never treated as source-of-truth. Consolidate duplicate orchestration and remove legacy gap detection APIs.

**Key Design References:**
- `09_PROJECTION_AND_SYNC.md`: DS-PROJ-0001..0004, ALG-PROJ-0001..0003
- `projection_pin_format.md`: Pin format `[@pin:<pin_id> target:<kind>:<id>]`
- `03_TRANSFORM_AND_COMPOSITING.md`: ALG-XFORM-0001 (AtomAwareAlignment), DS-XFORM-0002..0003
- `15_WORKFLOW_ORCHESTRATOR.md`: DS-WF-0001..0007, ALG-WF-0001..0004
- `16_CLI_SCRIPTS.md`: DS-CLI-0001..0003, canonical command set

**Constraints to Honor:** CON-0010 (plan.md as projection), CON-0007 (atom alignment), CON-0013 (drift to GapElement)

**Dependencies from Previous Phases:**
- Phase 2: Atom fingerprints via ALG-CORE-0004/0005 (implemented in `atom_emitter.py`)
- Phase 3: Evidence graph with coverage gates
- Phase 6: SpecIndexV2 with bidirectional atom-element maps (implemented in `spec_index_v2.py`)

---

## Work Item 1: Projection Generation with Pins

**Gap:** Current `_generate_plan_projection()` in `orchestrator.py` and `_generate_plan_md()` in `cli.py` generate plan.md without pins mapping offsets to authoritative L1 IDs. Design requires DS-PROJ-0001 (ProjectionArtifact) and DS-PROJ-0002 (Pin).

**Implementation Steps:**

1.1 **Create projection schemas** in `scripts/spec_manager/spec_manager/schemas/projection.py`:
```python
class Pin(BaseModel):
    """DS-PROJ-0002 compliant pin."""
    pin_id: str  # PIN-####
    from_projection_offset: int  # Character offset in projection
    target_id: str  # LIB-####, REQ-LIB-####-####, ATOM-F####-R####-L####
    target_kind: Literal["LIBRARY", "ELEMENT", "ATOM_RANGE"]
    target_path: str | None = None

class ProjectionArtifact(BaseModel):
    """DS-PROJ-0001 compliant projection."""
    projection_id: str
    kind: Literal["PLAN_MD", "COMPOSITE_MD", "TASKS_MD", "ARCH_MD"]
    generated_from: Literal["LIBRARIES", "SPEC_INDEX", "EVIDENCE_GRAPH"]
    content: str
    pins: list[Pin]
    created_at: str
```

1.2 **Create projection generator** in `scripts/spec_manager/spec_manager/projection/generator.py`:
```python
def generate_plan_from_libraries(
    libraries: list[Library],
    elements: list[DerivedElement],
    policy: ProjectionPolicy
) -> ProjectionArtifact:
    """ALG-PROJ-0001 implementation."""
    # Build content from libraries, inserting pins inline
    # Pin format: [@pin:PIN-0001 target:LIBRARY:LIB-0003]
```

1.3 **Integrate into orchestrator** `_phase_sync()`:
- Replace `_generate_plan_projection()` with `generate_plan_from_libraries()`
- Write both `plan.md` (with inline pins) and `projection.json` (artifact metadata)
- Pins file stored at `workspace/projections/plan_pins.json`

1.4 **Update CLI discover command** in `cli.py`:
- Replace `_generate_plan_md()` with projection generator
- Ensure pins are inserted for all library entries

**Tests:** `tests/spec_manager/schemas/test_projection.py`, `tests/spec_manager/projection/test_generator.py`
- Validate Pin format (PIN-####)
- Test pin insertion at correct offsets
- Test roundtrip: projection -> parse pins -> verify target IDs exist

---

## Work Item 2: Atom-Aware Drift Comparator

**Gap:** Current drift detection in `generate_drift_report()` uses element coverage heuristics, not atom alignment. Design requires ALG-PROJ-0002 (AtomAwareProjectionComparator) using atom fingerprints from Phase 2.

**Implementation Steps:**

2.1 **Create drift comparator** in `scripts/spec_manager/spec_manager/projection/drift.py`:
```python
@dataclass
class DriftItem:
    """DS-PROJ-0003 compliant drift item."""
    drift_type: Literal["PLAN_ONLY", "MISMATCH", "MISSING_PIN", "PIN_TARGET_MISSING"]
    evidence_atom_ids: list[str]
    projection_excerpt: str
    best_match_score: float

class AtomAwareDriftComparator:
    """ALG-PROJ-0002 implementation."""

    def compare(
        self,
        projection: ProjectionArtifact,
        spec_index: SpecIndexV2,
        atoms: list[LineAtom]
    ) -> DriftReport:
        # Use atom fingerprints for cross-revision matching
        alignment = self._align_atoms(old_atoms, new_atoms)
        similarity = self._compute_similarity(alignment.opcodes)
        return DriftReport(...)
```

2.2 **Implement atom alignment** using fingerprints from Phase 2:
```python
def _align_atoms(self, old_atoms: list[LineAtom], new_atoms: list[LineAtom]) -> AtomAlignment:
    """ALG-XFORM-0001 implementation."""
    # Match atoms by fingerprint first, then fallback to content similarity
    fingerprint_map = {a.atom_fingerprint: a for a in old_atoms}
    # Build sequence opcodes (EQUAL/REPLACE/DELETE/INSERT)
```

2.3 **Implement drift-to-gap conversion** (ALG-PROJ-0003, CON-0013):
```python
def convert_drift_to_gaps(
    drift_report: DriftReport,
    policy: DriftPolicy
) -> list[GapElement]:
    """Convert drift items exceeding floor into GapElements."""
    if drift_report.similarity >= policy.drift_similarity_floor:
        return []
    return [GapElement(
        id=f"GAP-DRIFT-{sig}",
        severity=policy.drift_severity,
        summary="Projection drift exceeds floor",
        affects=[...],
        evidence=[...]
    )]
```

2.4 **Integrate into reports workflow**:
- Update `generate_drift_report()` to use `AtomAwareDriftComparator`
- Add atom-level drift details to drift.md output

**Tests:** `tests/spec_manager/projection/test_drift.py`
- Test atom fingerprint matching across revisions
- Test drift detection when atoms inserted/deleted/modified
- Test gap conversion thresholds
- Test drift with PIN_TARGET_MISSING scenarios

---

## Work Item 3: CLI and Orchestrator Convergence

**Gap:** Two separate CLI/orchestration paths exist: `cli.py` (legacy phases) and `refinement/cli.py` (design-aligned phases). Commands don't match the design's canonical set from `16_CLI_SCRIPTS.md`.

**Implementation Steps:**

3.1 **Create unified command mapping**:
```
Design Command     | Current Implementation          | Target
-------------------|--------------------------------|--------
CMD-validate       | N/A                            | NEW
CMD-clean          | cmd_stage (cli.py)             | RENAME
CMD-discover       | cmd_discover (cli.py)          | KEEP
CMD-refine         | spec synthesize+expand (ref)   | CONSOLIDATE
CMD-project        | N/A                            | NEW (WI-1)
CMD-plan-tasks     | spec plan-tasks (ref)          | KEEP
CMD-trace          | trace atom/section/... (ref)   | KEEP
CMD-run            | cmd_run (cli.py)               | ALIGN
```

3.2 **Add CMD-validate command** for structure phase:
```python
def cmd_validate(args: argparse.Namespace) -> int:
    """Run STRUCTURE phase validation (CMD-validate)."""
    # Validate atoms and sections exist
    # Check coverage report
    # Emit gaps_report
```

3.3 **Add CMD-project command** for projection:
```python
def cmd_project(args: argparse.Namespace) -> int:
    """Generate plan.md projection with pins (CMD-project)."""
    # Uses generate_plan_from_libraries from WI-1
    # Runs drift detection from WI-2
    # Outputs plan_md, drift_report, gaps_report
```

3.4 **Deprecate legacy workflow path** in `orchestrator.py`:
- Mark `WorkflowOrchestrator.run()` as deprecated
- Add migration warnings when called
- Direct users to use refinement CLI phases instead

3.5 **Consolidate spec_folder vs run_id patterns**:
- Legacy CLI uses `spec_folder` argument
- Refinement CLI uses `run_id` argument
- Add adapter layer to support both during transition

**Tests:** `tests/spec_manager/test_cli_commands.py`
- Test new CMD-validate command
- Test new CMD-project command
- Test deprecation warnings trigger

---

## Work Item 4: Remove Legacy Gap Detection API

**Gap:** Two gap systems coexist: dict-based gaps in `core/gaps.py` (DetectorFinding, GapElement) and dataclass-based gaps in `refinement/core/gap.py` (Gap, GapEvidence). Callers use both inconsistently.

**Implementation Steps:**

4.1 **Audit current gap API usage**:
```
File                           | Uses Dict Gaps | Uses Gap Class
-------------------------------|----------------|----------------
core/gaps.py                   | YES (primary)  | NO
refinement/core/gap.py         | NO             | YES (primary)
workflow/orchestrator.py       | YES (detect_gaps) | NO
compliance/scorer.py           | YES            | NO
refinement/workflows/*.py      | NO             | YES
```

4.2 **Create migration adapter** in `scripts/spec_manager/spec_manager/core/gap_compat.py`:
```python
def detector_finding_to_gap_evidence(finding: DetectorFinding) -> GapEvidence:
    """Convert legacy DetectorFinding to v2.0 GapEvidence."""
    return GapEvidence(
        invariant_family=_infer_invariant_family(finding),
        description=finding.message,
        details={
            "element_id": finding.element_id,
            "detector": finding.detector,
            **finding.details
        },
        confidence=1.0 if finding.is_authoritative else 0.5,
        location=finding.location,
        detector=finding.detector,
    )

def gap_element_to_gap(element: GapElement) -> Gap:
    """Convert legacy GapElement to v2.0 Gap."""
    # Map fields and convert evidence list
```

4.3 **Migrate orchestrator to unified Gap flow**:
- Replace `detect_gaps()` calls with `GapSynthesizer.cluster_evidence()`
- Update `_collect_evidence()` to return `list[GapEvidence]`
- Update `_generate_run_level_gaps_report()` to use `Gap` class

4.4 **Migrate compliance scorer**:
- Update `ComplianceScorer.score_compliance()` to accept `list[GapEvidence]`
- Replace dict-based evidence with typed `GapEvidence`

4.5 **Deprecate and remove legacy APIs**:
- Add deprecation warnings to `detect_gaps()`, `format_gaps_md()`
- Mark `GapElement` class as deprecated
- After migration, remove from `core/gaps.py`

**Tests:** `tests/spec_manager/core/test_gap_compat.py`, `tests/spec_manager/compliance/test_unified_gaps.py`
- Test migration adapters produce equivalent output
- Test orchestrator with unified gaps
- Test compliance scorer with unified gaps

---

## Implementation Sequence

```
Phase 7 Dependencies:
  [4] Unified Gap Flow -----> [3] CLI CMD-validate
  [1] Projection + Pins -----> [3] CLI CMD-project
                           \
                            --> [2] Atom-Aware Drift
```

**Recommended Order:**
1. Work Item 4 (Unified Gaps) - Foundation for all gap flows
2. Work Item 1 (Projection + Pins) - New projection infrastructure
3. Work Item 2 (Atom-Aware Drift) - Depends on WI-1 projections
4. Work Item 3 (CLI Convergence) - Depends on WI-1, WI-2, WI-4

---

## Files to Create

| File | Purpose |
|------|---------|
| `schemas/projection.py` | Pin, ProjectionArtifact schemas (DS-PROJ-0001/0002) |
| `projection/__init__.py` | Projection module |
| `projection/generator.py` | Plan projection generator (ALG-PROJ-0001) |
| `projection/drift.py` | Atom-aware drift comparator (ALG-PROJ-0002/0003) |
| `core/gap_compat.py` | Gap migration adapters |

---

## Files to Modify

| File | Modifications |
|------|---------------|
| `workflow/orchestrator.py` | Use unified gaps, deprecate `run()` method |
| `cli.py` | Add CMD-validate, CMD-project; consolidate with refinement CLI |
| `refinement/cli.py` | Add CMD-validate, CMD-project commands |
| `refinement/workflows/reports.py` | Use atom-aware drift in `generate_drift_report()` |
| `compliance/scorer.py` | Accept `list[GapEvidence]` instead of dicts |
| `core/gaps.py` | Add deprecation warnings, keep for backward compat |
| `refinement/workflows/finalize.py` | Generate projections with pins |
| `docs/testing/spec-refinement-qa.md` | Add Phase 7 QA checklist |

---

## Constraints Addressed

| Constraint | Implementation |
|------------|----------------|
| CON-0010 | plan.md generated as projection with pins, not source-of-truth |
| CON-0007 | Atom alignment for drift comparison (fingerprint-based) |
| CON-0013 | Drift items converted to GapElements when exceeding threshold |

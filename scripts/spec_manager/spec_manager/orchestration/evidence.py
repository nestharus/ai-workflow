"""EvidenceBundle schema for the per-slice promotion loop.

The EvidenceBundle is the single artifact produced per slice per iteration
that all downstream consumers read.  It is an index file (``bundle.json``)
pointing to step output files in ``.pdd_runs/<run_id>/slices/<slice_id>/iter_NNN/``.

Each ``*Ref`` dataclass is a lightweight pointer to a file artifact on disk.
Steps produce files; the bundle aggregates references to those files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# ------------------------------------------------------------------
# Canonical Finding schema (used by reviewers, gates, and VerifyStep)
# ------------------------------------------------------------------


@dataclass
class Finding:
    """Canonical finding emitted by any reviewer, gate, or verification step.

    Language-agnostic: never requires imports, AST nodes, or framework-specific
    concepts.  Findings flow through the triage system to become DemotionTickets
    when the required change is illegal at the current layer.
    """

    dimension: str = (
        ""  # e.g., ARCH_BOUNDARY, PIN_COVERAGE, CLARITY, CORRECTNESS, DRIFT, GOVERNANCE
    )
    category: str = "style"  # style | maintainability | architecture | logic | drift | governance
    severity: str = "MINOR"  # BLOCKER | MAJOR | MINOR
    location: dict[str, Any] = field(
        default_factory=dict
    )  # {file, symbol?, start_line?, end_line?}
    evidence: str = ""  # short snippet or description
    required_change_type: str = (
        "refactor_only"  # refactor_only | wiring_only | behavior_change | spec_change
    )
    suggested_fix: str = ""
    confidence: float = 0.7
    tags: list[str] = field(default_factory=list)  # optional pattern IDs

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        import dataclasses

        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        """Reconstruct from a dict."""
        return cls(
            dimension=data.get("dimension", ""),
            category=data.get("category", "style"),
            severity=data.get("severity", "MINOR"),
            location=data.get("location", {}),
            evidence=data.get("evidence", ""),
            required_change_type=data.get("required_change_type", "refactor_only"),
            suggested_fix=data.get("suggested_fix", ""),
            confidence=data.get("confidence", 0.7),
            tags=data.get("tags", []),
        )


# ------------------------------------------------------------------
# Sub-reference types (pointers to step output files)
# ------------------------------------------------------------------


@dataclass
class ManifestRef:
    """Files included in this slice iteration + hashes."""

    path: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    slice_patterns: list[str] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)


@dataclass
class DiffRef:
    """Diff since previous iteration or baseline."""

    path: str = ""
    base_commit: str = ""
    head_commit: str = ""
    changed_files: list[str] = field(default_factory=list)
    content_hash: str = ""


@dataclass
class ProvenanceBlock:
    """Step tool versions, model IDs, prompt hashes."""

    path: str = ""
    entries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SourceIndexRef:
    """Per-file SourceAnalysis outputs from analyze_source()."""

    path: str = ""
    entries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FactsRef:
    """Normalized facts extracted from analyses + LLM claims."""

    path: str = ""
    functions: dict[str, Any] = field(default_factory=dict)
    stores: dict[str, Any] = field(default_factory=dict)
    atoms: dict[str, Any] = field(default_factory=dict)
    constraints_refs: list[str] = field(default_factory=list)
    llm_claims: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GapReportRef:
    """Pointer to gap exploration output."""

    path: str = ""
    open_gaps: list[dict[str, Any]] = field(default_factory=list)
    stagnation: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanRef:
    """Pointer to planning step output."""

    path: str = ""
    intentions: list[dict[str, Any]] = field(default_factory=list)
    edit_targets: list[dict[str, Any]] = field(default_factory=list)
    test_plan: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ImplementationRef:
    """Pointer to implementation step output."""

    patch_path: str = ""
    result_path: str = ""
    applied_edits: list[dict[str, Any]] = field(default_factory=list)
    gap_inventory: list[dict[str, Any]] = field(default_factory=list)
    pin_proposals: list[dict[str, Any]] = field(default_factory=list)
    edge_proposals: list[dict[str, Any]] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    tests_added: list[str] = field(default_factory=list)


@dataclass
class UnderSpecRef:
    """Resolved decisions or blockers."""

    path: str = ""
    decisions: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PinsSnapshotRef:
    """Pointer to serialized PinRegistry snapshot."""

    path: str = ""
    snapshot_hash: str = ""
    schema_version: str = "1"


@dataclass
class GraphSnapshotRef:
    """Pointer to serialized AdjacencyGraph snapshot."""

    path: str = ""
    snapshot_hash: str = ""
    schema_version: str = "1"


@dataclass
class GraphDeltaRef:
    """Pointer to pin/edge proposals or merge operations."""

    path: str = ""
    delta_type: str = ""  # "pin_proposal", "edge_proposal", "merge"
    produced_by: str = ""  # step name


@dataclass
class PromotionReportRef:
    """Pointer to promotion step report."""

    path: str = ""


@dataclass
class GatesReportRef:
    """Pointer to gates evaluation report."""

    path: str = ""
    gates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RefinementRef:
    """Pointer to coupling/cohesion analysis."""

    path: str = ""


@dataclass
class IntegrationRef:
    """Pointer to integration/merge/CI results."""

    path: str = ""


@dataclass
class TestsRef:
    """Pointer to test execution results."""

    slice_path: str = ""
    full_path: str = ""


@dataclass
class VerificationRef:
    """Pointer to P6/P7 verification report."""

    path: str = ""


@dataclass
class DemotionsRef:
    """Pointers to demotion tickets for this iteration."""

    path: str = ""
    emitted: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# EvidenceBundle (top-level)
# ------------------------------------------------------------------


@dataclass
class EvidenceBundle:
    """Per-slice, per-iteration evidence bundle.

    This is the single artifact that all loop steps consume and produce.
    Serialized as ``bundle.json`` in the iteration directory.
    """

    # Identity
    run_id: str = ""
    slice_id: str = ""
    iteration: int = 0
    created_at: str = ""
    mode: Literal["interactive", "auto"] = "auto"
    workspace_root: str = ""
    slice_root: str = ""

    # Input set
    manifest: ManifestRef = field(default_factory=ManifestRef)
    diff: DiffRef = field(default_factory=DiffRef)
    provenance: ProvenanceBlock = field(default_factory=ProvenanceBlock)

    # Analysis + facts
    source_index: SourceIndexRef = field(default_factory=SourceIndexRef)
    facts: FactsRef = field(default_factory=FactsRef)

    # Gaps + planning + implementation
    gaps: GapReportRef = field(default_factory=GapReportRef)
    plan: PlanRef = field(default_factory=PlanRef)
    implementation: ImplementationRef = field(default_factory=ImplementationRef)
    under_spec: UnderSpecRef = field(default_factory=UnderSpecRef)

    # Graph artifacts (canonical)
    pins_snapshot: PinsSnapshotRef = field(default_factory=PinsSnapshotRef)
    graph_snapshot: GraphSnapshotRef = field(default_factory=GraphSnapshotRef)
    graph_deltas: list[GraphDeltaRef] = field(default_factory=list)

    # Promotion + gates + quality
    promotion: PromotionReportRef = field(default_factory=PromotionReportRef)
    gates: GatesReportRef = field(default_factory=GatesReportRef)
    refinement: RefinementRef = field(default_factory=RefinementRef)

    # Integration + verification
    integration: IntegrationRef = field(default_factory=IntegrationRef)
    tests: TestsRef = field(default_factory=TestsRef)
    verification: VerificationRef = field(default_factory=VerificationRef)

    # Demotions (feedback)
    demotions: DemotionsRef = field(default_factory=DemotionsRef)
    status: Literal["IN_PROGRESS", "BLOCKED", "COMPLETE", "FAILED"] = "IN_PROGRESS"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def iter_dir(self, base: Path) -> Path:
        """Return the iteration directory path under *base*."""
        return (
            base
            / ".pdd_runs"
            / self.run_id
            / "slices"
            / self.slice_id
            / f"iter_{self.iteration:03d}"
        )

    def save(self, base: Path) -> Path:
        """Write ``bundle.json`` to the iteration directory."""
        import dataclasses

        out_dir = self.iter_dir(base)
        out_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = out_dir / "bundle.json"
        bundle_path.write_text(
            json.dumps(dataclasses.asdict(self), indent=2),
            encoding="utf-8",
        )
        return bundle_path

    @classmethod
    def load(cls, path: Path) -> EvidenceBundle:
        """Load a bundle from ``bundle.json``."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return _bundle_from_dict(data)


def _bundle_from_dict(data: dict[str, Any]) -> EvidenceBundle:
    """Reconstruct an EvidenceBundle from a dict (JSON round-trip)."""
    import dataclasses
    import typing

    hints = typing.get_type_hints(EvidenceBundle)
    bundle = EvidenceBundle()
    for f in dataclasses.fields(bundle):
        if f.name not in data:
            continue
        val = data[f.name]
        resolved_type = hints.get(f.name)
        # Handle nested dataclass refs
        if isinstance(val, dict) and dataclasses.is_dataclass(resolved_type):
            setattr(bundle, f.name, resolved_type(**val))
        elif isinstance(val, list) and val and isinstance(val[0], dict):
            # Handle list[GraphDeltaRef] etc.
            origin = getattr(resolved_type, "__origin__", None)
            if origin is list:
                args = getattr(resolved_type, "__args__", ())
                if args and dataclasses.is_dataclass(args[0]):
                    setattr(bundle, f.name, [args[0](**item) for item in val])
                else:
                    setattr(bundle, f.name, val)
            else:
                setattr(bundle, f.name, val)
        else:
            setattr(bundle, f.name, val)
    return bundle

"""Pin-function change propagation engine.

Detects when pin-functions change and traces all affected architectural
locations. Supports urgency classification based on change type and
projection type, and integration with the existing drift detection pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import ImportEdge, PinFunctionRegistry

from spec_manager.core.pin_registry import PinRegistryIndex
from spec_manager.projection.drift import DriftItem


@dataclass
class PinChange:
    """A detected change in a pin-function."""

    pin_func_id: str
    function_name: str
    change_type: str  # "modified", "added", "removed", "signature_changed"
    old_content_hash: str | None = None
    new_content_hash: str | None = None
    old_signature: str | None = None
    new_signature: str | None = None
    old_evidence_atom_ids: list[str] = field(default_factory=list)
    new_evidence_atom_ids: list[str] = field(default_factory=list)
    diff_summary: str = ""


@dataclass
class PropagationItem:
    """An architectural location that needs review due to a pin-function change."""

    import_edge: ImportEdge
    pin_change: PinChange
    review_urgency: str  # "auto_propagated", "review_required", "breaking_change"
    reason: str  # Why this location is affected


@dataclass
class PropagationReport:
    """Report of change propagation from pin-function changes."""

    changes: list[PinChange] = field(default_factory=list)
    propagation_items: list[PropagationItem] = field(default_factory=list)
    auto_propagated_count: int = 0
    review_required_count: int = 0
    breaking_change_count: int = 0


class PinChangePropagator:
    """Detects pin-function changes and propagates to affected architectural locations."""

    def __init__(self, registry_index: PinRegistryIndex) -> None:
        self._index = registry_index

    def detect_changes(
        self,
        old_registry: PinFunctionRegistry,
        new_registry: PinFunctionRegistry,
    ) -> list[PinChange]:
        """Detect changes between two pin-function registries.

        Compares old and new registries to find added, removed, modified,
        and signature-changed pin-functions.

        Args:
            old_registry: The previous state of the registry.
            new_registry: The current state of the registry.

        Returns:
            List of PinChange objects describing all detected changes.
        """
        changes: list[PinChange] = []

        old_by_id = {pf.pin_func_id: pf for pf in old_registry.pin_functions}
        new_by_id = {pf.pin_func_id: pf for pf in new_registry.pin_functions}

        old_ids = set(old_by_id.keys())
        new_ids = set(new_by_id.keys())

        # Removed functions
        for pid in sorted(old_ids - new_ids):
            old_pf = old_by_id[pid]
            changes.append(
                PinChange(
                    pin_func_id=pid,
                    function_name=old_pf.function_name,
                    change_type="removed",
                    old_content_hash=old_pf.content_hash,
                    new_content_hash=None,
                    old_signature=old_pf.signature,
                    new_signature=None,
                    old_evidence_atom_ids=list(old_pf.evidence_atom_ids),
                    new_evidence_atom_ids=[],
                    diff_summary=f"Function '{old_pf.function_name}' was removed",
                )
            )

        # Added functions
        for pid in sorted(new_ids - old_ids):
            new_pf = new_by_id[pid]
            changes.append(
                PinChange(
                    pin_func_id=pid,
                    function_name=new_pf.function_name,
                    change_type="added",
                    old_content_hash=None,
                    new_content_hash=new_pf.content_hash,
                    old_signature=None,
                    new_signature=new_pf.signature,
                    old_evidence_atom_ids=[],
                    new_evidence_atom_ids=list(new_pf.evidence_atom_ids),
                    diff_summary=f"Function '{new_pf.function_name}' was added",
                )
            )

        # Modified or signature-changed functions
        for pid in sorted(old_ids & new_ids):
            old_pf = old_by_id[pid]
            new_pf = new_by_id[pid]

            if old_pf.signature != new_pf.signature:
                changes.append(
                    PinChange(
                        pin_func_id=pid,
                        function_name=new_pf.function_name,
                        change_type="signature_changed",
                        old_content_hash=old_pf.content_hash,
                        new_content_hash=new_pf.content_hash,
                        old_signature=old_pf.signature,
                        new_signature=new_pf.signature,
                        old_evidence_atom_ids=list(old_pf.evidence_atom_ids),
                        new_evidence_atom_ids=list(new_pf.evidence_atom_ids),
                        diff_summary=(
                            f"Signature changed: '{old_pf.signature}' -> '{new_pf.signature}'"
                        ),
                    )
                )
            elif old_pf.content_hash != new_pf.content_hash:
                changes.append(
                    PinChange(
                        pin_func_id=pid,
                        function_name=new_pf.function_name,
                        change_type="modified",
                        old_content_hash=old_pf.content_hash,
                        new_content_hash=new_pf.content_hash,
                        old_signature=old_pf.signature,
                        new_signature=new_pf.signature,
                        old_evidence_atom_ids=list(old_pf.evidence_atom_ids),
                        new_evidence_atom_ids=list(new_pf.evidence_atom_ids),
                        diff_summary=f"Body of '{new_pf.function_name}' was modified",
                    )
                )

        return changes

    def propagate(self, changes: list[PinChange]) -> PropagationReport:
        """Propagate pin-function changes to all affected architectural locations.

        Args:
            changes: List of detected pin-function changes.

        Returns:
            PropagationReport with all affected locations and urgency classifications.
        """
        report = PropagationReport(changes=changes)

        for change in changes:
            # Added functions have no existing importers
            if change.change_type == "added":
                continue

            edges = self._index.get_importers(change.pin_func_id)
            for edge in edges:
                urgency = self.classify_urgency(change, edge)
                reason = self._build_reason(change, edge, urgency)

                item = PropagationItem(
                    import_edge=edge,
                    pin_change=change,
                    review_urgency=urgency,
                    reason=reason,
                )
                report.propagation_items.append(item)

                if urgency == "auto_propagated":
                    report.auto_propagated_count += 1
                elif urgency == "review_required":
                    report.review_required_count += 1
                elif urgency == "breaking_change":
                    report.breaking_change_count += 1

        return report

    def classify_urgency(
        self,
        change: PinChange,
        edge: ImportEdge,
    ) -> str:
        """Classify the urgency of a propagation item.

        Classification logic:
        - Signature changes or removals are always breaking_change
        - Body modifications with PASS_THROUGH are auto_propagated
        - Body modifications with WRAP or SMEAR are review_required

        Args:
            change: The detected pin-function change.
            edge: The import edge to the affected architectural location.

        Returns:
            Urgency string: "auto_propagated", "review_required", or "breaking_change".
        """
        if change.change_type in ("signature_changed", "removed"):
            return "breaking_change"

        if change.change_type == "modified":
            if edge.projection_type == "pass_through":
                return "auto_propagated"
            # wrap variants, smear, introduction
            return "review_required"

        return "review_required"

    def _build_reason(
        self,
        change: PinChange,
        edge: ImportEdge,
        urgency: str,
    ) -> str:
        """Build a human-readable reason for a propagation item."""
        func = change.function_name
        loc = edge.arch_location
        proj = edge.projection_type

        if urgency == "breaking_change":
            if change.change_type == "removed":
                return (
                    f"Pin-function '{func}' was removed; "
                    f"'{loc}' (projection: {proj}) will fail to import"
                )
            return (
                f"Signature of '{func}' changed; '{loc}' (projection: {proj}) may fail at call site"
            )

        if urgency == "auto_propagated":
            return (
                f"Body of '{func}' modified; '{loc}' uses PASS_THROUGH "
                f"and will automatically reflect the change"
            )

        return (
            f"Body of '{func}' modified; '{loc}' uses {proj} "
            f"and should be reviewed for compatibility"
        )


def _merge_evidence_atom_ids(old_ids: list[str], new_ids: list[str]) -> list[str]:
    """Merge evidence IDs while preserving order and uniqueness."""
    merged: list[str] = []
    seen: set[str] = set()
    for atom_id in old_ids + new_ids:
        if atom_id in seen:
            continue
        seen.add(atom_id)
        merged.append(atom_id)
    return merged


def _jaccard_similarity(old_ids: list[str], new_ids: list[str]) -> float:
    """Compute Jaccard similarity between two evidence-ID sets."""
    old_set = set(old_ids)
    new_set = set(new_ids)
    if not old_set and not new_set:
        return 1.0
    union_size = len(old_set | new_set)
    if union_size == 0:
        return 1.0
    return len(old_set & new_set) / union_size


def _calculate_change_similarity(change: PinChange) -> float:
    """Estimate similarity from concrete change evidence."""
    score_parts: list[float] = []

    if change.old_signature is not None and change.new_signature is not None:
        score_parts.append(
            SequenceMatcher(None, change.old_signature, change.new_signature).ratio()
        )

    if change.old_content_hash is not None and change.new_content_hash is not None:
        score_parts.append(1.0 if change.old_content_hash == change.new_content_hash else 0.0)

    if change.old_evidence_atom_ids or change.new_evidence_atom_ids:
        score_parts.append(
            _jaccard_similarity(change.old_evidence_atom_ids, change.new_evidence_atom_ids)
        )

    if not score_parts:
        return 0.0

    return sum(score_parts) / len(score_parts)


def convert_propagation_to_drift(report: PropagationReport) -> list[DriftItem]:
    """Convert a PropagationReport to DriftItem objects for the drift pipeline.

    Bridges the pin-function change propagation system with the existing
    atom-aware drift detection pipeline.

    Args:
        report: PropagationReport from pin-function change detection.

    Returns:
        List of DriftItem objects suitable for the drift pipeline.
    """
    drift_items: list[DriftItem] = []

    for item in report.propagation_items:
        urgency_to_drift_type = {
            "breaking_change": "MISMATCH",
            "review_required": "MISMATCH",
            "auto_propagated": "PLAN_ONLY",
        }
        drift_type = urgency_to_drift_type.get(item.review_urgency, "MISMATCH")

        evidence_ids = _merge_evidence_atom_ids(
            item.pin_change.old_evidence_atom_ids,
            item.pin_change.new_evidence_atom_ids,
        )
        projection_type = getattr(
            item.import_edge.projection_type,
            "value",
            item.import_edge.projection_type,
        )
        match_score = _calculate_change_similarity(item.pin_change)

        drift_item = DriftItem(
            drift_type=drift_type,
            evidence_atom_ids=list(evidence_ids),
            projection_excerpt=item.reason,
            best_match_score=match_score,
            pin_id=item.pin_change.pin_func_id,
            target_id=item.import_edge.arch_location,
            urgency=item.review_urgency,
            trace_details={
                "change_type": item.pin_change.change_type,
                "function_name": item.pin_change.function_name,
                "old_content_hash": item.pin_change.old_content_hash,
                "new_content_hash": item.pin_change.new_content_hash,
                "old_signature": item.pin_change.old_signature,
                "new_signature": item.pin_change.new_signature,
                "old_evidence_atom_ids": item.pin_change.old_evidence_atom_ids,
                "new_evidence_atom_ids": item.pin_change.new_evidence_atom_ids,
                "import_edge_id": item.import_edge.edge_id,
                "projection_type": str(projection_type),
                "arch_file_path": item.import_edge.arch_file_path,
                "arch_line": item.import_edge.arch_line,
                "reason": item.reason,
            },
        )
        drift_items.append(drift_item)

    return drift_items


__all__ = [
    "PinChange",
    "PinChangePropagator",
    "PropagationItem",
    "PropagationReport",
    "convert_propagation_to_drift",
]

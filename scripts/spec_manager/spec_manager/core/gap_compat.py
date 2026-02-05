"""Gap migration adapters for v1 to v2.0 gap conversion.

This module provides compatibility adapters between:
- DetectorFinding (v1 detector output) -> GapEvidence (v2.0)
- GapElement (v1 synthesized gap) -> Gap (v2.0)

Phase 7 Work Item 4: Unified Gap Flow
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from spec_manager.core.gaps import DetectorFinding, GapElement, Severity
from spec_manager.refinement.core.gap import (
    Gap,
    GapEvidence,
    GapType,
    compute_evidence_signature,
)

if TYPE_CHECKING:
    pass


def _infer_invariant_family(finding: DetectorFinding) -> str:
    """Infer invariant family from detector name and details.

    Maps detector names to v2.0 invariant families:
    - format_violation, duplicate_* -> format
    - undefined_function, undefined_reference -> resolution
    - coverage_*, membership_* -> coverage
    - sequence_*, conflict -> sequence
    - content_*, drift_* -> content
    - proof_* -> proof
    - uncertainty_* -> uncertainty
    """
    detector = finding.detector.lower() if finding.detector else ""

    # Check detector prefix patterns
    if any(
        p in detector
        for p in ("format", "duplicate", "legacy", "pattern", "escape")
    ):
        return "format"

    if any(p in detector for p in ("undefined", "unresolved", "entity")):
        return "entity_resolution"

    if any(p in detector for p in ("coverage", "membership", "unaccounted")):
        return "coverage"

    if any(p in detector for p in ("sequence", "conflict", "hole", "overlap")):
        return "sequence"

    if any(p in detector for p in ("content", "drift", "mismatch")):
        return "content"

    if any(p in detector for p in ("proof", "lean", "claim", "algorithm")):
        return "proof"

    if any(p in detector for p in ("sorry", "todo", "hedging", "uncertainty")):
        return "uncertainty"

    # Check severity for fallback
    if finding.severity == Severity.ERROR:
        return "coverage"

    return "format"


def detector_finding_to_gap_evidence(finding: DetectorFinding) -> GapEvidence:
    """Convert legacy DetectorFinding to v2.0 GapEvidence.

    Args:
        finding: DetectorFinding from v1 detector output

    Returns:
        Equivalent GapEvidence object
    """
    # Build details dict with legacy fields
    details: dict[str, Any] = {
        "element_id": finding.element_id,
        "detector": finding.detector,
        **finding.details,
    }

    # Determine confidence based on is_authoritative
    confidence = 1.0 if finding.is_authoritative else 0.5

    return GapEvidence(
        invariant_family=_infer_invariant_family(finding),
        description=finding.message,
        details=details,
        confidence=confidence,
        location=finding.location,
        detector=finding.detector,
    )


def gap_element_to_gap(element: GapElement) -> Gap:
    """Convert legacy GapElement to v2.0 Gap.

    Args:
        element: GapElement from v1 gap synthesis

    Returns:
        Equivalent Gap object
    """
    # Convert evidence list
    evidence_list = [
        detector_finding_to_gap_evidence(e) for e in element.evidence
    ]

    # Infer gap type from evidence
    gap_type = _infer_gap_type_from_element(element, evidence_list)

    # Convert severity
    severity = element.severity

    # Build source list from affects
    sources = list(element.affects)

    # Compute derived artifact target
    target = _infer_target(element)

    return Gap(
        id=element.id,
        gap_type=gap_type,
        severity=severity,
        source=sources,
        derived_artifact_target=target,
        description=element.summary,
        evidence=evidence_list,
        status="open" if not element.bypassed else "deferred",
        resolution_notes=element.drop_reason,
    )


def _infer_gap_type_from_element(
    element: GapElement, evidence: list[GapEvidence]
) -> GapType:
    """Infer GapType from GapElement content.

    Maps element ID patterns and evidence to GapType:
    - GAP-DRIFT-* -> content_mismatch
    - GAP-COV-* -> coverage_failure
    - GAP-SEQ-* -> sequence_violation
    - GAP-FMT-* -> format_violation
    """
    gap_id = element.id.upper()

    if "DRIFT" in gap_id:
        return GapType.content_mismatch
    if "COV" in gap_id:
        return GapType.coverage_failure
    if "SEQ" in gap_id:
        return GapType.sequence_violation
    if "FMT" in gap_id or "FORMAT" in gap_id:
        return GapType.format_violation
    if "PROOF" in gap_id:
        return GapType.proof_chain_break
    if "MEMBER" in gap_id:
        return GapType.membership_failure
    if "ENTITY" in gap_id or "RESOLUTION" in gap_id:
        return GapType.entity_resolution_failure

    # Fallback: infer from evidence invariant families
    if evidence:
        families = {e.invariant_family for e in evidence}
        if "coverage" in families:
            return GapType.coverage_failure
        if "sequence" in families:
            return GapType.sequence_violation
        if "format" in families:
            return GapType.format_violation
        if "content" in families:
            return GapType.content_mismatch
        if "proof" in families:
            return GapType.proof_chain_break

    return GapType.missing_detail


def _infer_target(element: GapElement) -> str:
    """Infer derived artifact target from GapElement.

    Checks element.affects for file paths or element IDs.
    """
    for affected in element.affects:
        # Check for file path patterns
        if "/" in affected or affected.endswith(".md"):
            return affected
        # Check for library element patterns
        if affected.startswith("LIB-") or affected.startswith("REQ-"):
            return affected

    # Default to first affected or unknown
    return element.affects[0] if element.affects else "unknown"


def batch_convert_findings(findings: list[DetectorFinding]) -> list[GapEvidence]:
    """Convert a batch of DetectorFinding objects to GapEvidence.

    Args:
        findings: List of DetectorFinding from v1 detectors

    Returns:
        List of GapEvidence objects
    """
    return [detector_finding_to_gap_evidence(f) for f in findings]


def batch_convert_elements(elements: list[GapElement]) -> list[Gap]:
    """Convert a batch of GapElement objects to Gap.

    Args:
        elements: List of GapElement from v1 synthesis

    Returns:
        List of Gap objects
    """
    return [gap_element_to_gap(e) for e in elements]


__all__ = [
    "detector_finding_to_gap_evidence",
    "gap_element_to_gap",
    "batch_convert_findings",
    "batch_convert_elements",
]

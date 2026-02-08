"""Tests for gap migration adapters (Phase 7 Work Item 4).

Tests:
- test_detector_finding_to_gap_evidence: Basic conversion
- test_gap_element_to_gap: Full element conversion
- test_batch_convert_findings: Batch conversion
- test_batch_convert_elements: Batch element conversion
- test_invariant_family_inference: Mapping detector -> invariant family
- test_gap_type_inference: Mapping element ID patterns -> GapType
"""

from __future__ import annotations

from spec_manager.core.gap import GapType
from spec_manager.core.gap_compat import (
    batch_convert_elements,
    batch_convert_findings,
    detector_finding_to_gap_evidence,
    gap_element_to_gap,
)
from spec_manager.core.gaps import DetectorFinding, GapElement, Severity


class TestDetectorFindingToGapEvidence:
    """Test conversion of DetectorFinding to GapEvidence."""

    def test_basic_conversion(self) -> None:
        """Test basic conversion with all fields."""
        finding = DetectorFinding(
            severity=Severity.WARNING,
            message="Test message",
            location="test.md:42",
            element_id="ELEM-001",
            detector="format_violation",
            details={"key": "value"},
        )

        evidence = detector_finding_to_gap_evidence(finding)

        assert evidence.description == "Test message"
        assert evidence.location == "test.md:42"
        assert evidence.detector == "format_violation"
        assert evidence.confidence == 0.5
        assert evidence.details["element_id"] == "ELEM-001"
        assert evidence.details["key"] == "value"

    def test_default_confidence(self) -> None:
        """Test finding gets default 0.5 confidence."""
        finding = DetectorFinding(
            severity=Severity.INFO,
            message="Test",
            location="test.md",
        )

        evidence = detector_finding_to_gap_evidence(finding)

        assert evidence.confidence == 0.5

    def test_format_invariant_family(self) -> None:
        """Test format-related detectors map to format family."""
        for detector in ["format_violation", "duplicate_header", "legacy_pattern"]:
            finding = DetectorFinding(
                severity=Severity.WARNING,
                message="Test",
                location="test.md",
                detector=detector,
            )
            evidence = detector_finding_to_gap_evidence(finding)
            assert evidence.invariant_family == "format", f"Failed for {detector}"

    def test_coverage_invariant_family(self) -> None:
        """Test coverage-related detectors map to coverage family."""
        for detector in ["coverage_gap", "membership_failure", "unaccounted_atom"]:
            finding = DetectorFinding(
                severity=Severity.ERROR,
                message="Test",
                location="test.md",
                detector=detector,
            )
            evidence = detector_finding_to_gap_evidence(finding)
            assert evidence.invariant_family == "coverage", f"Failed for {detector}"

    def test_entity_resolution_invariant_family(self) -> None:
        """Test resolution-related detectors map to entity_resolution family."""
        for detector in ["undefined_function", "unresolved_reference"]:
            finding = DetectorFinding(
                severity=Severity.WARNING,
                message="Test",
                location="test.md",
                detector=detector,
            )
            evidence = detector_finding_to_gap_evidence(finding)
            assert evidence.invariant_family == "entity_resolution", f"Failed for {detector}"


class TestGapElementToGap:
    """Test conversion of GapElement to Gap."""

    def test_basic_conversion(self) -> None:
        """Test basic conversion with evidence."""
        finding = DetectorFinding(
            severity=Severity.WARNING,
            message="Test finding",
            location="test.md:10",
            detector="format_violation",
        )
        element = GapElement(
            id="GAP-0001",
            severity=Severity.WARNING,
            summary="Test gap",
            affects=["ELEM-001", "test.md"],
            evidence=[finding],
        )

        gap = gap_element_to_gap(element)

        assert gap.id == "GAP-0001"
        assert gap.severity == Severity.WARNING
        assert gap.description == "Test gap"
        assert "ELEM-001" in gap.source
        assert len(gap.evidence) == 1
        assert gap.status == "open"

    def test_bypassed_status(self) -> None:
        """Test bypassed element gets deferred status."""
        element = GapElement(
            id="GAP-0002",
            severity=Severity.INFO,
            summary="Bypassed gap",
            affects=["test.md"],
            evidence=[],
            bypassed=True,
            drop_reason="Intentionally skipped",
        )

        gap = gap_element_to_gap(element)

        assert gap.status == "deferred"
        assert gap.resolution_notes == "Intentionally skipped"

    def test_drift_gap_type(self) -> None:
        """Test GAP-DRIFT-* gets content_mismatch type."""
        element = GapElement(
            id="GAP-DRIFT-abc123",
            severity=Severity.WARNING,
            summary="Drift detected",
            affects=["plan.md"],
            evidence=[],
        )

        gap = gap_element_to_gap(element)

        assert gap.gap_type == GapType.content_mismatch

    def test_coverage_gap_type(self) -> None:
        """Test GAP-COV-* gets coverage_failure type."""
        element = GapElement(
            id="GAP-COV-0001",
            severity=Severity.ERROR,
            summary="Coverage failure",
            affects=["spec.md"],
            evidence=[],
        )

        gap = gap_element_to_gap(element)

        assert gap.gap_type == GapType.coverage_failure


class TestBatchConversion:
    """Test batch conversion functions."""

    def test_batch_convert_findings(self) -> None:
        """Test converting multiple findings."""
        findings = [
            DetectorFinding(
                severity=Severity.WARNING,
                message=f"Finding {i}",
                location=f"test.md:{i}",
                detector="format_violation",
            )
            for i in range(3)
        ]

        evidence_list = batch_convert_findings(findings)

        assert len(evidence_list) == 3
        assert all(e.invariant_family == "format" for e in evidence_list)

    def test_batch_convert_elements(self) -> None:
        """Test converting multiple elements."""
        elements = [
            GapElement(
                id=f"GAP-{i:04d}",
                severity=Severity.WARNING,
                summary=f"Gap {i}",
                affects=[f"elem-{i}"],
                evidence=[],
            )
            for i in range(3)
        ]

        gaps = batch_convert_elements(elements)

        assert len(gaps) == 3
        assert all(g.status == "open" for g in gaps)

    def test_empty_batch(self) -> None:
        """Test empty batch returns empty list."""
        assert batch_convert_findings([]) == []
        assert batch_convert_elements([]) == []

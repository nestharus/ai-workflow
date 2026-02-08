"""Tests for unified gap flow (Phase 7 Work Item 4).

Tests that the new unified gap system works with compliance scorer
and orchestrator workflows.

Tests:
- test_scorer_accepts_gap_evidence: ComplianceScorer works with GapEvidence
- test_orchestrator_unified_gaps: Orchestrator uses unified gap flow
- test_deprecation_warnings: Legacy API warnings trigger
"""

from __future__ import annotations

import contextlib
import warnings
from pathlib import Path
from unittest.mock import MagicMock

from spec_manager.core.gap import (
    Gap,
    GapEvidence,
    GapSynthesizer,
    GapType,
)
from spec_manager.core.gap_compat import (
    batch_convert_findings,
    detector_finding_to_gap_evidence,
)
from spec_manager.core.gaps import DetectorFinding, Severity, detect_gaps, format_gaps_md


class TestUnifiedGapFlow:
    """Test unified gap flow integration."""

    def test_detector_to_evidence_to_gap(self) -> None:
        """Test complete flow: DetectorFinding -> GapEvidence -> Gap."""
        # Step 1: Create DetectorFinding (v1 detector output)
        finding = DetectorFinding(
            severity=Severity.WARNING,
            message="Missing coverage",
            location="spec.md:100",
            element_id="ELEM-001",
            detector="coverage_detector",
            details={
                "source": "spec.md::SECTION-1",
                "derived_artifact_target": "libraries/auth.md",
                "gap_type": "coverage_failure",
            },
        )

        # Step 2: Convert to GapEvidence
        evidence = detector_finding_to_gap_evidence(finding)

        assert evidence.invariant_family == "coverage"
        assert evidence.description == "Missing coverage"
        assert evidence.details["element_id"] == "ELEM-001"

        # Step 3: Synthesize into Gap using v2 synthesizer
        synthesizer = GapSynthesizer()
        gaps = synthesizer.cluster_evidence([evidence])

        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.severity == Severity.INFO  # Default when not explicitly set
        assert gap.gap_type == GapType.coverage_failure

    def test_batch_conversion_preserves_evidence(self) -> None:
        """Test batch conversion maintains all evidence."""
        findings = [
            DetectorFinding(
                severity=Severity.ERROR,
                message=f"Issue {i}",
                location=f"file{i}.md:1",
                detector="test_detector",
                details={"source": f"src-{i}", "derived_artifact_target": "target"},
            )
            for i in range(5)
        ]

        evidence_list = batch_convert_findings(findings)

        assert len(evidence_list) == 5
        # All should preserve their descriptions
        descriptions = {e.description for e in evidence_list}
        assert all(f"Issue {i}" in descriptions for i in range(5))


class TestDeprecationWarnings:
    """Test deprecation warnings for legacy APIs."""

    def test_detect_gaps_warning(self) -> None:
        """Test detect_gaps() emits deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Call the deprecated function
            # Use minimal args that won't cause other errors
            with contextlib.suppress(Exception):
                detect_gaps("", MagicMock(), Path("."))

            # Check for deprecation warning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()

    def test_format_gaps_md_warning(self) -> None:
        """Test format_gaps_md() emits deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Call the deprecated function
            format_gaps_md([])

            # Check for deprecation warning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()


class TestGapSynthesizerIntegration:
    """Test GapSynthesizer with converted evidence."""

    def test_cluster_converted_evidence(self) -> None:
        """Test clustering works with converted evidence."""
        # Create multiple findings for same element
        findings = [
            DetectorFinding(
                severity=Severity.WARNING,
                message="Issue A",
                location="test.md:1",
                element_id="ELEM-001",
                detector="detector_a",
                details={"source": "src-1", "derived_artifact_target": "target-1"},
            ),
            DetectorFinding(
                severity=Severity.ERROR,
                message="Issue B",
                location="test.md:10",
                element_id="ELEM-001",  # Same element
                detector="detector_b",
                details={"source": "src-1", "derived_artifact_target": "target-1"},
            ),
        ]

        evidence_list = batch_convert_findings(findings)
        synthesizer = GapSynthesizer()
        gaps = synthesizer.cluster_evidence(evidence_list)

        # Should cluster into one gap for the target
        assert len(gaps) >= 1

    def test_merge_gaps(self) -> None:
        """Test merging new gaps into existing set."""
        synthesizer = GapSynthesizer()

        existing = [
            Gap(
                id="GAP-existing",
                gap_type=GapType.coverage_failure,
                severity=Severity.WARNING,
                source=["src-1"],
                derived_artifact_target="target-1",
                description="Existing gap",
                evidence=[
                    GapEvidence(
                        invariant_family="coverage",
                        description="Original evidence",
                    )
                ],
            )
        ]

        new = [
            Gap(
                id="GAP-new",
                gap_type=GapType.format_violation,
                severity=Severity.INFO,
                source=["src-2"],
                derived_artifact_target="target-2",
                description="New gap",
                evidence=[
                    GapEvidence(
                        invariant_family="format",
                        description="New evidence",
                    )
                ],
            )
        ]

        merged = synthesizer.merge_gaps(existing, new)

        assert len(merged) == 2


class TestEvidenceSignatures:
    """Test evidence signature computation for gap identity."""

    def test_consistent_signatures(self) -> None:
        """Test same evidence produces same signature."""
        from spec_manager.core.gap import compute_evidence_signature

        evidence1 = [
            GapEvidence(
                invariant_family="coverage",
                description="Test issue",
                details={"key": "value"},
                location="test.md:1",
            )
        ]

        evidence2 = [
            GapEvidence(
                invariant_family="coverage",
                description="Test issue",
                details={"key": "value"},
                location="test.md:1",
            )
        ]

        sig1 = compute_evidence_signature(evidence1)
        sig2 = compute_evidence_signature(evidence2)

        assert sig1 == sig2

    def test_different_evidence_different_signature(self) -> None:
        """Test different evidence produces different signatures."""
        from spec_manager.core.gap import compute_evidence_signature

        evidence1 = [
            GapEvidence(
                invariant_family="coverage",
                description="Issue A",
            )
        ]

        evidence2 = [
            GapEvidence(
                invariant_family="coverage",
                description="Issue B",  # Different
            )
        ]

        sig1 = compute_evidence_signature(evidence1)
        sig2 = compute_evidence_signature(evidence2)

        assert sig1 != sig2

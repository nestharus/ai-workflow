"""Tests for atom-aware drift comparator (ALG-PROJ-0002, ALG-PROJ-0003).

Tests:
- test_drift_report_basic: Basic drift report
- test_pin_target_missing: Detection of missing targets
- test_similarity_calculation: Similarity scoring
- test_atom_alignment: Fingerprint-based matching
- test_convert_drift_to_gaps: Gap conversion (CON-0013)
- test_drift_threshold: Threshold enforcement
"""

from __future__ import annotations

import pytest

from spec_manager.projection.drift import (
    AtomAlignment,
    AtomAwareDriftComparator,
    DriftItem,
    DriftPolicy,
    DriftReport,
    convert_drift_to_gaps,
)
from spec_manager.refinement.core.gap import GapType
from spec_manager.schemas.atoms import LineAtom
from spec_manager.schemas.projection import Pin, ProjectionArtifact
from spec_manager.schemas.spec_index_v2 import Library, SpecIndexV2


class TestDriftItem:
    """Test DriftItem dataclass."""

    def test_drift_item_creation(self) -> None:
        """Test creating a drift item."""
        item = DriftItem(
            drift_type="PLAN_ONLY",
            evidence_atom_ids=["ATOM-1", "ATOM-2"],
            projection_excerpt="Some content...",
            best_match_score=0.75,
        )

        assert item.drift_type == "PLAN_ONLY"
        assert len(item.evidence_atom_ids) == 2
        assert item.best_match_score == 0.75

    def test_missing_pin_drift_item(self) -> None:
        """Test drift item for missing pin target."""
        item = DriftItem(
            drift_type="PIN_TARGET_MISSING",
            evidence_atom_ids=[],
            projection_excerpt="...content around pin...",
            best_match_score=0.0,
            pin_id="PIN-0001",
            target_id="LIB-9999",
        )

        assert item.drift_type == "PIN_TARGET_MISSING"
        assert item.pin_id == "PIN-0001"
        assert item.target_id == "LIB-9999"


class TestDriftReport:
    """Test DriftReport dataclass."""

    def test_empty_report(self) -> None:
        """Test empty drift report."""
        report = DriftReport(
            projection_id="PROJ-001",
            drift_items=[],
            similarity=1.0,
            total_pins=0,
            valid_pins=0,
        )

        assert report.similarity == 1.0
        assert not report.has_significant_drift()

    def test_significant_drift(self) -> None:
        """Test report with significant drift."""
        report = DriftReport(
            projection_id="PROJ-001",
            drift_items=[DriftItem(drift_type="MISMATCH")],
            similarity=0.5,
            total_pins=10,
            valid_pins=5,
        )

        assert report.has_significant_drift(threshold=0.8)
        assert not report.has_significant_drift(threshold=0.4)


class TestDriftPolicy:
    """Test DriftPolicy configuration."""

    def test_default_policy(self) -> None:
        """Test default policy values."""
        policy = DriftPolicy()

        assert policy.drift_similarity_floor == 0.8
        assert policy.include_excerpts is True
        assert policy.max_excerpt_length == 200

    def test_custom_policy(self) -> None:
        """Test custom policy values."""
        policy = DriftPolicy(
            drift_similarity_floor=0.9,
            include_excerpts=False,
            max_excerpt_length=100,
        )

        assert policy.drift_similarity_floor == 0.9
        assert policy.include_excerpts is False


class TestAtomAwareDriftComparator:
    """Test AtomAwareDriftComparator class."""

    def test_compare_empty_projection(self) -> None:
        """Test comparing empty projection."""
        comparator = AtomAwareDriftComparator()
        artifact = ProjectionArtifact(
            projection_id="PROJ-001",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content="",
            pins=[],
        )
        spec_index = SpecIndexV2()

        report = comparator.compare(artifact, spec_index)

        assert report.similarity == 1.0  # No pins to validate
        assert report.total_pins == 0

    def test_compare_with_valid_pins(self) -> None:
        """Test comparing with valid pin targets."""
        comparator = AtomAwareDriftComparator()

        library = Library(lib_id="LIB-0001", name="Test")
        spec_index = SpecIndexV2(libraries=[library])

        artifact = ProjectionArtifact(
            projection_id="PROJ-001",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content="Test content",
            pins=[
                Pin(
                    pin_id="PIN-0001",
                    from_projection_offset=0,
                    target_id="LIB-0001",
                    target_kind="LIBRARY",
                )
            ],
        )

        report = comparator.compare(artifact, spec_index)

        assert report.valid_pins == 1
        assert report.missing_targets == 0

    def test_compare_with_missing_target(self) -> None:
        """Test comparing with missing pin target."""
        comparator = AtomAwareDriftComparator()

        spec_index = SpecIndexV2()  # Empty - no libraries

        artifact = ProjectionArtifact(
            projection_id="PROJ-001",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content="Test content",
            pins=[
                Pin(
                    pin_id="PIN-0001",
                    from_projection_offset=0,
                    target_id="LIB-9999",
                    target_kind="LIBRARY",
                )
            ],
        )

        report = comparator.compare(artifact, spec_index)

        assert report.valid_pins == 0
        assert report.missing_targets == 1
        assert len(report.drift_items) == 1
        assert report.drift_items[0].drift_type == "PIN_TARGET_MISSING"

    def test_excerpt_extraction(self) -> None:
        """Test excerpt extraction around offset."""
        policy = DriftPolicy(include_excerpts=True, max_excerpt_length=20)
        comparator = AtomAwareDriftComparator(policy)

        spec_index = SpecIndexV2()
        content = "0123456789ABCDEFGHIJ"  # 20 chars

        artifact = ProjectionArtifact(
            projection_id="PROJ-001",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content=content,
            pins=[
                Pin(
                    pin_id="PIN-0001",
                    from_projection_offset=10,
                    target_id="LIB-9999",
                    target_kind="LIBRARY",
                )
            ],
        )

        report = comparator.compare(artifact, spec_index)

        # Should have excerpt around offset 10
        assert len(report.drift_items) == 1
        excerpt = report.drift_items[0].projection_excerpt
        assert len(excerpt) <= 30  # max_excerpt_length + ellipsis buffer


class TestAtomAlignment:
    """Test AtomAlignment functionality."""

    def test_align_identical_atoms(self) -> None:
        """Test alignment of identical atom lists."""
        comparator = AtomAwareDriftComparator()

        # Create atoms with unique fingerprints (each line has different fingerprint)
        atoms = [
            LineAtom(
                atom_id=f"ATOM-F0001-R0001-L{i:04d}",
                atom_fingerprint=f"{i:064d}",  # Each atom has unique fingerprint
                file_uid="F0001",
                rev_id="R0001",
                line_no=i,
                sequence_index=i - 1,
                section_id="SEC-001",
                sha256="b" * 64,
                text=f"Line {i}",
            )
            for i in range(1, 4)
        ]

        alignment = comparator.align_atoms(atoms, atoms)

        assert len(alignment.matched_pairs) == 3
        assert alignment.old_only == []
        assert alignment.new_only == []

    def test_align_different_atoms(self) -> None:
        """Test alignment of different atom lists."""
        comparator = AtomAwareDriftComparator()

        old_atoms = [
            LineAtom(
                atom_id="ATOM-F0001-R0001-L0001",
                atom_fingerprint="a" * 64,
                file_uid="F0001",
                rev_id="R0001",
                line_no=1,
                sequence_index=0,
                section_id="SEC-001",
                sha256="b" * 64,
                text="Old line",
            )
        ]

        new_atoms = [
            LineAtom(
                atom_id="ATOM-F0001-R0002-L0001",
                atom_fingerprint="c" * 64,  # Different fingerprint
                file_uid="F0001",
                rev_id="R0002",
                line_no=1,
                sequence_index=0,
                section_id="SEC-001",
                sha256="d" * 64,
                text="New line",
            )
        ]

        alignment = comparator.align_atoms(old_atoms, new_atoms)

        assert len(alignment.matched_pairs) == 0
        assert len(alignment.old_only) == 1
        assert len(alignment.new_only) == 1


class TestConvertDriftToGaps:
    """Test drift to gap conversion (ALG-PROJ-0003, CON-0013)."""

    def test_no_gaps_above_threshold(self) -> None:
        """Test no gaps created when similarity above threshold."""
        report = DriftReport(
            projection_id="PROJ-001",
            drift_items=[],
            similarity=0.9,
            total_pins=10,
            valid_pins=10,
        )
        policy = DriftPolicy(drift_similarity_floor=0.8)

        gaps = convert_drift_to_gaps(report, policy)

        assert gaps == []

    def test_gaps_below_threshold(self) -> None:
        """Test gaps created when similarity below threshold."""
        report = DriftReport(
            projection_id="PROJ-001",
            drift_items=[
                DriftItem(
                    drift_type="PIN_TARGET_MISSING",
                    pin_id="PIN-0001",
                    target_id="LIB-9999",
                )
            ],
            similarity=0.5,
            total_pins=10,
            valid_pins=5,
            missing_targets=5,
        )
        policy = DriftPolicy(drift_similarity_floor=0.8)

        gaps = convert_drift_to_gaps(report, policy)

        assert len(gaps) >= 1
        # Should have overall drift gap
        overall_gap = gaps[0]
        assert overall_gap.gap_type == GapType.content_mismatch
        assert "drift exceeds floor" in overall_gap.description.lower()

    def test_gap_for_missing_target(self) -> None:
        """Test individual gap created for missing pin target."""
        report = DriftReport(
            projection_id="PROJ-001",
            drift_items=[
                DriftItem(
                    drift_type="PIN_TARGET_MISSING",
                    pin_id="PIN-0001",
                    target_id="LIB-9999",
                    projection_excerpt="Some content",
                )
            ],
            similarity=0.5,
            total_pins=1,
            valid_pins=0,
            missing_targets=1,
        )
        policy = DriftPolicy(drift_similarity_floor=0.8)

        gaps = convert_drift_to_gaps(report, policy)

        # Should have gap for missing target
        target_gaps = [g for g in gaps if "LIB-9999" in g.derived_artifact_target]
        assert len(target_gaps) >= 1

    def test_default_policy(self) -> None:
        """Test conversion with default policy."""
        report = DriftReport(
            projection_id="PROJ-001",
            similarity=0.5,
        )

        gaps = convert_drift_to_gaps(report)  # No policy

        assert len(gaps) >= 1  # Should use default threshold

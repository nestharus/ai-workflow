"""Tests for coverage gate (INV-ACC-0101, CON-0009).

Tests:
- test_gate_passes_on_complete_coverage: 100% coverage passes
- test_gate_fails_on_incomplete_coverage: Non-100% coverage fails
- test_gap_element_emitted_on_failure: GAP element created
- test_fallback_state_valid_on_failure: CON-0009 compliance
"""

from spec_manager.compliance.coverage_gate import (
    CoverageReport,
    build_coverage_report,
    verify_coverage_or_emit_gap,
)
from spec_manager.core.gaps import Severity


class TestCoverageReport:
    """Test CoverageReport dataclass."""

    def test_coverage_ratio_complete(self) -> None:
        """Test coverage ratio with full coverage."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=100,
            remainder_atoms=0,
            excluded_atoms=0,
        )
        assert report.coverage_ratio == 1.0
        assert report.is_complete

    def test_coverage_ratio_partial(self) -> None:
        """Test coverage ratio with partial coverage."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=75,
            remainder_atoms=0,
            excluded_atoms=0,
            unaccounted_atom_ids=["ATOM-1", "ATOM-2"],
        )
        assert report.coverage_ratio == 0.75
        assert not report.is_complete

    def test_coverage_ratio_empty_file(self) -> None:
        """Test coverage ratio for empty file (0 atoms)."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=0,
            mapped_atoms=0,
            remainder_atoms=0,
            excluded_atoms=0,
        )
        # Empty file should report 100% coverage
        assert report.coverage_ratio == 1.0
        assert report.is_complete

    def test_is_complete_with_unaccounted_atoms(self) -> None:
        """Test is_complete when unaccounted atoms exist."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=100,  # All mapped
            remainder_atoms=0,
            excluded_atoms=0,
            unaccounted_atom_ids=["ATOM-1"],  # But still has unaccounted
        )
        # coverage_ratio is 1.0, but is_complete is False
        assert report.coverage_ratio == 1.0
        assert not report.is_complete


class TestVerifyCoverageOrEmitGap:
    """Test verify_coverage_or_emit_gap function."""

    def test_gate_passes_on_complete_coverage(self) -> None:
        """Test gate passes with 100% coverage."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=100,
            remainder_atoms=0,
            excluded_atoms=0,
        )

        result = verify_coverage_or_emit_gap(report, "run_001")

        assert result.passed
        assert result.coverage_report == report
        assert result.gap_element is None
        assert result.fallback_state_valid

    def test_gate_fails_on_incomplete_coverage(self) -> None:
        """Test gate fails with incomplete coverage."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=75,
            remainder_atoms=0,
            excluded_atoms=0,
            unaccounted_atom_ids=["ATOM-1", "ATOM-2"],
        )

        result = verify_coverage_or_emit_gap(report, "run_001")

        assert not result.passed
        assert result.coverage_report == report

    def test_gap_element_emitted_on_failure(self) -> None:
        """Test GAP element is created on failure."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=50,
            remainder_atoms=0,
            excluded_atoms=0,
            unaccounted_atom_ids=["ATOM-1", "ATOM-2", "ATOM-3"],
        )

        result = verify_coverage_or_emit_gap(report, "run_001")

        assert result.gap_element is not None
        gap = result.gap_element

        # Verify gap structure
        assert gap.id == "GAP-COVERAGE-F0001-run_001"
        assert gap.severity == Severity.ERROR
        assert "Incomplete atom coverage" in gap.summary
        assert "50.0%" in gap.summary
        assert "F0001" in gap.affects

        # Verify evidence
        assert len(gap.evidence) == 1
        evidence = gap.evidence[0]
        assert evidence.detector == "coverage_gate"
        assert "3 atoms unaccounted" in evidence.message

    def test_fallback_state_valid_on_failure(self) -> None:
        """Test fallback state is valid on failure (CON-0009)."""
        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=0,  # 0% coverage
            remainder_atoms=0,
            excluded_atoms=0,
            unaccounted_atom_ids=["ATOM-1"],
        )

        result = verify_coverage_or_emit_gap(report, "run_001")

        assert not result.passed
        # Per CON-0009: even with 0% coverage, fallback state is valid
        assert result.fallback_state_valid

    def test_gap_element_details_contain_atom_ids(self) -> None:
        """Test gap evidence contains unaccounted atom IDs."""
        unaccounted = [f"ATOM-{i:04d}" for i in range(25)]

        report = CoverageReport(
            file_uid="F0001",
            rev_id="R0001",
            total_atoms=100,
            mapped_atoms=75,
            remainder_atoms=0,
            excluded_atoms=0,
            unaccounted_atom_ids=unaccounted,
        )

        result = verify_coverage_or_emit_gap(report, "run_001")

        gap = result.gap_element
        assert gap is not None

        evidence = gap.evidence[0]
        details = evidence.details

        # Should truncate to first 20
        assert len(details["unaccounted_atoms"]) == 20
        assert details["total_unaccounted"] == 25


class TestBuildCoverageReport:
    """Test build_coverage_report helper function."""

    def test_build_coverage_report_complete(self) -> None:
        """Test building report with complete coverage."""
        total = {"ATOM-1", "ATOM-2", "ATOM-3"}
        mapped = {"ATOM-1", "ATOM-2", "ATOM-3"}
        remainder: set[str] = set()

        report = build_coverage_report(
            file_uid="F0001",
            rev_id="R0001",
            total_atom_ids=total,
            mapped_atom_ids=mapped,
            remainder_atom_ids=remainder,
        )

        assert report.total_atoms == 3
        assert report.mapped_atoms == 3
        assert report.remainder_atoms == 0
        assert report.excluded_atoms == 0
        assert report.is_complete

    def test_build_coverage_report_with_remainder(self) -> None:
        """Test building report with remainder atoms."""
        total = {"ATOM-1", "ATOM-2", "ATOM-3"}
        mapped = {"ATOM-1"}
        remainder = {"ATOM-2", "ATOM-3"}

        report = build_coverage_report(
            file_uid="F0001",
            rev_id="R0001",
            total_atom_ids=total,
            mapped_atom_ids=mapped,
            remainder_atom_ids=remainder,
        )

        assert report.mapped_atoms == 1
        assert report.remainder_atoms == 2
        assert report.is_complete  # All atoms accounted

    def test_build_coverage_report_with_excluded(self) -> None:
        """Test building report with excluded atoms."""
        total = {"ATOM-1", "ATOM-2", "ATOM-3"}
        mapped = {"ATOM-1"}
        remainder = {"ATOM-2"}
        excluded = {"ATOM-3"}

        report = build_coverage_report(
            file_uid="F0001",
            rev_id="R0001",
            total_atom_ids=total,
            mapped_atom_ids=mapped,
            remainder_atom_ids=remainder,
            excluded_atom_ids=excluded,
        )

        assert report.excluded_atoms == 1
        assert report.is_complete

    def test_build_coverage_report_with_unaccounted(self) -> None:
        """Test building report with unaccounted atoms."""
        total = {"ATOM-1", "ATOM-2", "ATOM-3"}
        mapped = {"ATOM-1"}
        remainder: set[str] = set()

        report = build_coverage_report(
            file_uid="F0001",
            rev_id="R0001",
            total_atom_ids=total,
            mapped_atom_ids=mapped,
            remainder_atom_ids=remainder,
        )

        assert report.mapped_atoms == 1
        assert len(report.unaccounted_atom_ids) == 2
        assert not report.is_complete
        assert set(report.unaccounted_atom_ids) == {"ATOM-2", "ATOM-3"}

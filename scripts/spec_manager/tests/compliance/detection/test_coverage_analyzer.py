"""Tests for coverage analyzer."""

from __future__ import annotations

from spec_manager.compliance.detection.coverage_analyzer import (
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    coverage_to_gap_evidence,
)


class TestCoverageToGapEvidence:
    """Test conversion of coverage data to gap evidence."""

    def test_uncovered_function_becomes_evidence(self) -> None:
        func = FunctionCoverage(
            file_path="/tmp/module.py",
            function_name="untested_func",
            line_start=10,
            line_end=20,
            total_statements=5,
            covered_statements=0,
            coverage_ratio=0.0,
        )
        report = CoverageReport(
            files=[],
            functions=[func],
            overall_ratio=0.5,
            uncovered_functions=[func],
        )

        evidence = coverage_to_gap_evidence(report)
        assert len(evidence) == 1
        e = evidence[0]
        assert e.invariant_family == "executable_coverage"
        assert e.detector == "coverage_analyzer"
        assert "untested_func" in e.description
        assert e.details["function_name"] == "untested_func"
        assert e.details["coverage_ratio"] == 0.0
        assert e.confidence == 0.8

    def test_covered_function_not_flagged(self) -> None:
        func = FunctionCoverage(
            file_path="/tmp/module.py",
            function_name="tested_func",
            line_start=1,
            line_end=5,
            total_statements=3,
            covered_statements=3,
            coverage_ratio=1.0,
        )
        report = CoverageReport(
            files=[],
            functions=[func],
            overall_ratio=1.0,
            uncovered_functions=[],
        )

        evidence = coverage_to_gap_evidence(report)
        assert len(evidence) == 0

    def test_threshold_logic(self) -> None:
        func_zero = FunctionCoverage(
            file_path="/tmp/module.py",
            function_name="zero_func",
            line_start=1,
            line_end=5,
            total_statements=3,
            covered_statements=0,
            coverage_ratio=0.0,
        )
        func_half = FunctionCoverage(
            file_path="/tmp/module.py",
            function_name="half_func",
            line_start=10,
            line_end=15,
            total_statements=4,
            covered_statements=2,
            coverage_ratio=0.5,
        )
        func_full = FunctionCoverage(
            file_path="/tmp/module.py",
            function_name="full_func",
            line_start=20,
            line_end=25,
            total_statements=3,
            covered_statements=3,
            coverage_ratio=1.0,
        )
        report = CoverageReport(
            files=[],
            functions=[func_zero, func_half, func_full],
            overall_ratio=0.5,
            uncovered_functions=[func_zero],
        )

        # Default threshold (0.0) -- only completely uncovered
        evidence_default = coverage_to_gap_evidence(report, min_function_coverage=0.0)
        assert len(evidence_default) == 1
        assert "zero_func" in evidence_default[0].description

        # Higher threshold (0.5) -- includes half_func too
        evidence_half = coverage_to_gap_evidence(report, min_function_coverage=0.5)
        assert len(evidence_half) == 2
        names = {e.details["function_name"] for e in evidence_half}
        assert "zero_func" in names
        assert "half_func" in names

    def test_empty_report(self) -> None:
        report = CoverageReport()
        evidence = coverage_to_gap_evidence(report)
        assert evidence == []

    def test_evidence_location_format(self) -> None:
        func = FunctionCoverage(
            file_path="/tmp/module.py",
            function_name="func",
            line_start=10,
            line_end=20,
            total_statements=5,
            covered_statements=0,
            coverage_ratio=0.0,
        )
        report = CoverageReport(
            files=[],
            functions=[func],
            overall_ratio=0.0,
            uncovered_functions=[func],
        )

        evidence = coverage_to_gap_evidence(report)
        assert evidence[0].location == "/tmp/module.py:10-20"

    def test_evidence_serializes(self) -> None:
        func = FunctionCoverage(
            file_path="/tmp/module.py",
            function_name="func",
            line_start=1,
            line_end=5,
            total_statements=3,
            covered_statements=0,
            coverage_ratio=0.0,
        )
        report = CoverageReport(
            files=[],
            functions=[func],
            overall_ratio=0.0,
            uncovered_functions=[func],
        )

        evidence = coverage_to_gap_evidence(report)
        d = evidence[0].to_dict()
        assert d["invariant_family"] == "executable_coverage"
        assert d["detector"] == "coverage_analyzer"


class TestFileCoverageDataclass:
    """Test FileCoverage dataclass."""

    def test_basic_creation(self) -> None:
        fc = FileCoverage(
            file_path="/tmp/test.py",
            total_statements=10,
            covered_statements=7,
            missing_lines=[3, 5, 8],
            coverage_ratio=0.7,
        )
        assert fc.file_path == "/tmp/test.py"
        assert fc.total_statements == 10
        assert fc.covered_statements == 7
        assert fc.missing_lines == [3, 5, 8]
        assert fc.coverage_ratio == 0.7


class TestCoverageReportDataclass:
    """Test CoverageReport dataclass."""

    def test_default_creation(self) -> None:
        report = CoverageReport()
        assert report.files == []
        assert report.functions == []
        assert report.overall_ratio == 0.0
        assert report.uncovered_functions == []

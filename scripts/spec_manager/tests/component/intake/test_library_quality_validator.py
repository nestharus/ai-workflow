from __future__ import annotations

import json

import pytest

from spec_manager.intake.quality.library_quality_validator import (
    DimensionScore,
    LibraryQualityReport,
    LibraryQualityValidator,
    validate_libraries,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def phase0_output(tmp_path):
    output_dir = tmp_path / "phase0_output"
    output_dir.mkdir()

    # route_table.jsonl — 10 lines, all routed to lib-a
    route_table = output_dir / "route_table.jsonl"
    lines = [
        json.dumps({"source_file": "spec.md", "line": i, "library_id": "lib-a"})
        for i in range(10)
    ]
    route_table.write_text("\n".join(lines))

    # coverage_ledger.jsonl — 10 lines, all routed
    ledger = output_dir / "coverage_ledger.jsonl"
    entries = [json.dumps({"line": i, "status": "routed"}) for i in range(10)]
    ledger.write_text("\n".join(entries))

    # libraries.json — two distinct libraries
    libs = output_dir / "libraries.json"
    libs.write_text(json.dumps({"libraries": [
        {"name": "AuthService", "description": "handles authentication and authorization"},
        {"name": "PaymentProcessor", "description": "processes payments and refunds"},
    ]}))

    return output_dir


@pytest.fixture
def phase0_output_with_overlap(tmp_path):
    """Same line routed to two different libraries -> routing overlap."""
    output_dir = tmp_path / "phase0_output_overlap"
    output_dir.mkdir()

    route_table = output_dir / "route_table.jsonl"
    lines = []
    for i in range(10):
        lines.append(json.dumps({"source_file": "spec.md", "line": i, "library_id": "lib-a"}))
    # Duplicate the first 5 lines with a different library
    for i in range(5):
        lines.append(json.dumps({"source_file": "spec.md", "line": i, "library_id": "lib-b"}))
    route_table.write_text("\n".join(lines))

    ledger = output_dir / "coverage_ledger.jsonl"
    entries = [json.dumps({"line": i, "status": "routed"}) for i in range(10)]
    ledger.write_text("\n".join(entries))

    libs = output_dir / "libraries.json"
    libs.write_text(json.dumps({"libraries": [
        {"name": "AuthService", "description": "handles authentication and authorization"},
        {"name": "PaymentProcessor", "description": "processes payments and refunds"},
    ]}))

    return output_dir


@pytest.fixture
def phase0_output_semantic_overlap(tmp_path):
    """Libraries with highly overlapping descriptions -> semantic overlap."""
    output_dir = tmp_path / "phase0_output_semantic"
    output_dir.mkdir()

    route_table = output_dir / "route_table.jsonl"
    lines = [
        json.dumps({"source_file": "spec.md", "line": i, "library_id": "lib-a"})
        for i in range(10)
    ]
    route_table.write_text("\n".join(lines))

    ledger = output_dir / "coverage_ledger.jsonl"
    entries = [json.dumps({"line": i, "status": "routed"}) for i in range(10)]
    ledger.write_text("\n".join(entries))

    libs = output_dir / "libraries.json"
    libs.write_text(json.dumps({"libraries": [
        {"name": "AuthServiceA", "description": "handles authentication and authorization for users"},
        {"name": "AuthServiceB", "description": "handles authentication and authorization for admins"},
    ]}))

    return output_dir


# ------------------------------------------------------------------
# DimensionScore
# ------------------------------------------------------------------


def test_dimension_score_construction():
    d = DimensionScore(name="test_dim", score=95.0, passed=True)
    assert d.name == "test_dim"
    assert d.score == 95.0
    assert d.passed is True
    assert d.mode == "gate"
    assert d.details == {}
    assert d.issues == []


def test_dimension_score_advisory_mode():
    d = DimensionScore(name="dep", score=80.0, passed=True, mode="advisory")
    assert d.mode == "advisory"


# ------------------------------------------------------------------
# LibraryQualityReport
# ------------------------------------------------------------------


def test_report_gate_passed_all_gates_pass():
    report = LibraryQualityReport(dimensions=[
        DimensionScore(name="completeness", score=100.0, passed=True, mode="gate"),
        DimensionScore(name="routing_overlap", score=100.0, passed=True, mode="gate"),
        DimensionScore(name="dep_min", score=50.0, passed=False, mode="advisory"),
    ])
    assert report.gate_passed is True


def test_report_gate_passed_one_gate_fails():
    report = LibraryQualityReport(dimensions=[
        DimensionScore(name="completeness", score=100.0, passed=True, mode="gate"),
        DimensionScore(name="routing_overlap", score=20.0, passed=False, mode="gate"),
    ])
    assert report.gate_passed is False


def test_report_gate_passed_empty_dimensions():
    report = LibraryQualityReport()
    assert report.gate_passed is True


# ------------------------------------------------------------------
# LibraryQualityValidator — all passing
# ------------------------------------------------------------------


def test_validate_all_passing(tmp_path, phase0_output):
    validator = LibraryQualityValidator(tmp_path)
    report = validator.validate(phase0_output)

    assert report.overall_passed is True
    assert report.library_count == 2
    assert report.source_line_count == 10
    assert len(report.dimensions) == 5

    # All gate dimensions should pass
    for d in report.dimensions:
        if d.mode == "gate":
            assert d.passed is True, f"Gate dimension '{d.name}' unexpectedly failed"


# ------------------------------------------------------------------
# LibraryQualityValidator — routing overlap failure
# ------------------------------------------------------------------


def test_validate_routing_overlap_failure(tmp_path, phase0_output_with_overlap):
    # Use a very tight threshold so the 50% overlap definitely fails
    validator = LibraryQualityValidator(tmp_path, overlap_threshold=0.01)
    report = validator.validate(phase0_output_with_overlap)

    overlap_dim = next(d for d in report.dimensions if d.name == "routing_overlap")
    assert overlap_dim.passed is False
    assert overlap_dim.details["overlap_count"] == 5
    assert len(overlap_dim.issues) > 0
    assert report.overall_passed is False


# ------------------------------------------------------------------
# LibraryQualityValidator — semantic overlap failure
# ------------------------------------------------------------------


def test_validate_semantic_overlap_failure(tmp_path, phase0_output_semantic_overlap):
    # Use a very tight threshold so the high word overlap definitely fails
    validator = LibraryQualityValidator(tmp_path, semantic_overlap_threshold=0.10)
    report = validator.validate(phase0_output_semantic_overlap)

    semantic_dim = next(d for d in report.dimensions if d.name == "semantic_overlap")
    assert semantic_dim.passed is False
    assert len(semantic_dim.issues) > 0


# ------------------------------------------------------------------
# validate_libraries convenience function
# ------------------------------------------------------------------


def test_validate_libraries_convenience(tmp_path, phase0_output):
    report = validate_libraries(tmp_path, phase0_output_dir=phase0_output)
    assert report.overall_passed is True
    assert report.library_count == 2


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


def test_validate_empty_output_dir(tmp_path):
    """Empty output directory -> trivially passes (no artifacts)."""
    empty_dir = tmp_path / "empty_output"
    empty_dir.mkdir()
    validator = LibraryQualityValidator(tmp_path)
    report = validator.validate(empty_dir)
    # No libraries, no route table -> everything trivially passes
    assert report.overall_passed is True
    assert report.library_count == 0


def test_report_to_dict(tmp_path, phase0_output):
    validator = LibraryQualityValidator(tmp_path)
    report = validator.validate(phase0_output)
    d = report.to_dict()
    assert isinstance(d, dict)
    assert "dimensions" in d
    assert "overall_passed" in d
    assert len(d["dimensions"]) == 5

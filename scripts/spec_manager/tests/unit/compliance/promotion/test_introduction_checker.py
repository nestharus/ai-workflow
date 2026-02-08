"""Tests for introduced algorithm spec checker."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.introduction_checker import (
    _classify_category,
    check_introduced_algorithm_specs,
    find_introduced_algorithms,
)
from spec_manager.compliance.promotion.pin_coverage import (
    PinCoverageItem,
    PinCoverageReport,
)


def _write_py(tmpdir: Path, name: str, content: str) -> Path:
    path = tmpdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _make_coverage_report(
    items: list[PinCoverageItem],
) -> PinCoverageReport:
    total = len(items)
    pinned = sum(1 for i in items if i.has_pin)
    introductions = sum(1 for i in items if i.is_introduction)
    unpinned = total - pinned - introductions
    denominator = total - introductions
    ratio = pinned / denominator if denominator > 0 else 1.0
    return PinCoverageReport(
        total_locations=total,
        pinned_locations=pinned,
        introduction_locations=introductions,
        unpinned_locations=unpinned,
        coverage_ratio=ratio,
        items=items,
    )


class TestClassifyCategory:
    def test_retry_classification(self) -> None:
        assert _classify_category("retry_with_backoff", "infra/retry.py") == "retry"

    def test_circuit_breaker_classification(self) -> None:
        assert _classify_category("circuit_breaker_check", "infra/cb.py") == "circuit_breaker"

    def test_routing_classification(self) -> None:
        assert _classify_category("route_to_handler", "routing.py") == "routing"

    def test_serialization_classification(self) -> None:
        assert _classify_category("serialize_payload", "util.py") == "serialization"

    def test_infrastructure_fallback(self) -> None:
        assert _classify_category("do_stuff", "infrastructure/misc.py") == "infrastructure"

    def test_unknown_default(self) -> None:
        assert _classify_category("foo_bar", "some/module.py") == "unknown"


class TestFindIntroducedAlgorithms:
    def test_finds_introduced_with_spec_comments(self, tmp_path: Path) -> None:
        arch_file = _write_py(
            tmp_path,
            "retry.py",
            """\
            def retry_operation():
                # Spec: retry with exponential backoff
                for i in range(3):
                    try:
                        return do_work()
                    except Exception:
                        pass
        """,
        )
        coverage = _make_coverage_report(
            [
                PinCoverageItem(
                    arch_location=f"{arch_file}:retry_operation",
                    arch_file_path=str(arch_file),
                    arch_line=1,
                    has_pin=False,
                    is_introduction=True,
                    introduction_has_spec=True,
                )
            ]
        )
        result = find_introduced_algorithms(coverage, [arch_file])
        assert len(result) == 1
        assert result[0].function_name == "retry_operation"
        assert result[0].has_spec_comments is True
        assert result[0].spec_comment_count >= 1

    def test_finds_introduced_without_spec_comments(self, tmp_path: Path) -> None:
        arch_file = _write_py(
            tmp_path,
            "handler.py",
            """\
            def dispatch_event():
                return route()
        """,
        )
        coverage = _make_coverage_report(
            [
                PinCoverageItem(
                    arch_location=f"{arch_file}:dispatch_event",
                    arch_file_path=str(arch_file),
                    arch_line=1,
                    has_pin=False,
                    is_introduction=True,
                    introduction_has_spec=False,
                )
            ]
        )
        result = find_introduced_algorithms(coverage, [arch_file])
        assert len(result) == 1
        assert result[0].has_spec_comments is False

    def test_no_introductions(self, tmp_path: Path) -> None:
        arch_file = _write_py(
            tmp_path,
            "service.py",
            """\
            def handle():
                return 1
        """,
        )
        coverage = _make_coverage_report(
            [
                PinCoverageItem(
                    arch_location=f"{arch_file}:handle",
                    arch_file_path=str(arch_file),
                    arch_line=1,
                    has_pin=True,
                    is_introduction=False,
                )
            ]
        )
        result = find_introduced_algorithms(coverage, [arch_file])
        assert len(result) == 0


class TestCheckIntroducedAlgorithmSpecs:
    def test_all_have_specs_passes(self, tmp_path: Path) -> None:
        arch_file = _write_py(
            tmp_path,
            "retry.py",
            '''\
            def retry_operation():
                """Retry with exponential backoff."""
                # Spec: retry with exponential backoff
                for i in range(3):
                    try:
                        return do_work()
                    except Exception:
                        pass
        ''',
        )
        coverage = _make_coverage_report(
            [
                PinCoverageItem(
                    arch_location=f"{arch_file}:retry_operation",
                    arch_file_path=str(arch_file),
                    arch_line=1,
                    has_pin=False,
                    is_introduction=True,
                    introduction_has_spec=True,
                )
            ]
        )
        gate_spec = GateSpec(gate_id=GateId.INTRODUCED_ALGORITHM_SPECS)
        result = check_introduced_algorithm_specs(coverage, [arch_file], gate_spec)
        assert result.passed is True

    def test_missing_specs_fails(self, tmp_path: Path) -> None:
        arch_file = _write_py(
            tmp_path,
            "handler.py",
            """\
            def dispatch_event():
                return route()
        """,
        )
        coverage = _make_coverage_report(
            [
                PinCoverageItem(
                    arch_location=f"{arch_file}:dispatch_event",
                    arch_file_path=str(arch_file),
                    arch_line=1,
                    has_pin=False,
                    is_introduction=True,
                    introduction_has_spec=False,
                )
            ]
        )
        gate_spec = GateSpec(
            gate_id=GateId.INTRODUCED_ALGORITHM_SPECS,
            params={"require_docstring": False},
        )
        result = check_introduced_algorithm_specs(coverage, [arch_file], gate_spec)
        assert result.passed is False
        assert len(result.findings) >= 1

    def test_missing_docstring_fails_when_required(self, tmp_path: Path) -> None:
        arch_file = _write_py(
            tmp_path,
            "retry.py",
            """\
            def retry_operation():
                # Spec: retry logic
                for i in range(3):
                    pass
        """,
        )
        coverage = _make_coverage_report(
            [
                PinCoverageItem(
                    arch_location=f"{arch_file}:retry_operation",
                    arch_file_path=str(arch_file),
                    arch_line=1,
                    has_pin=False,
                    is_introduction=True,
                    introduction_has_spec=True,
                )
            ]
        )
        gate_spec = GateSpec(
            gate_id=GateId.INTRODUCED_ALGORITHM_SPECS,
            params={"require_docstring": True},
        )
        result = check_introduced_algorithm_specs(coverage, [arch_file], gate_spec)
        assert result.passed is False
        assert any(
            "Missing docstring" in issue
            for finding in result.findings
            for issue in finding.get("issues", [])
        )

    def test_no_introductions_passes(self) -> None:
        coverage = _make_coverage_report([])
        gate_spec = GateSpec(gate_id=GateId.INTRODUCED_ALGORITHM_SPECS)
        result = check_introduced_algorithm_specs(coverage, [], gate_spec)
        assert result.passed is True
        assert result.score == 1.0

"""Tests for pin coverage checker."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.compliance.promotion.config import GateId, GateMode, GateSpec
from spec_manager.compliance.promotion.pin_coverage import (
    PinCoverageItem,
    PinCoverageReport,
    build_pin_coverage_report,
    check_pin_coverage,
)
from spec_manager.schemas.pin_functions import (
    ImportEdge,
    PinFunction,
    PinFunctionRegistry,
)


def _write_py(tmpdir: Path, name: str, content: str) -> Path:
    path = tmpdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _make_registry(
    pin_funcs: list[PinFunction] | None = None,
    edges: list[ImportEdge] | None = None,
) -> PinFunctionRegistry:
    return PinFunctionRegistry(
        schema_version="1.0",
        pin_functions=pin_funcs or [],
        import_edges=edges or [],
        created_at="2024-01-01T00:00:00Z",
    )


class TestBuildPinCoverageReport:
    def test_all_pinned(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def handle_request():
                return process()
        """)
        registry = _make_registry(
            pin_funcs=[PinFunction(
                pin_func_id="PFUNC-0001",
                function_name="process",
                module_path="atoms.process",
                file_path="atoms/process.py",
                line_start=1, line_end=5,
                signature="def process()", docstring="Process data",
                content_hash="abc123",
            )],
            edges=[ImportEdge(
                edge_id="IMEDGE-0001",
                pin_func_id="PFUNC-0001",
                arch_location=f"{arch_file}:handle_request",
                arch_file_path=str(arch_file),
                arch_line=1,
                projection_type="pass_through",
            )],
        )
        report = build_pin_coverage_report(registry, [arch_file])
        assert report.total_locations == 1
        assert report.pinned_locations == 1
        assert report.unpinned_locations == 0
        assert report.coverage_ratio == 1.0

    def test_unpinned_location(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def handle_request():
                return 42
        """)
        registry = _make_registry()
        report = build_pin_coverage_report(registry, [arch_file])
        assert report.total_locations == 1
        assert report.pinned_locations == 0
        assert report.unpinned_locations == 1
        assert report.coverage_ratio == 0.0

    def test_introduction_excluded_from_coverage(self, tmp_path: Path) -> None:
        infra_dir = tmp_path / "infrastructure"
        infra_dir.mkdir()
        arch_file = _write_py(infra_dir, "retry.py", """\
            def retry_with_backoff():
                # Retry logic
                return True
        """)
        registry = _make_registry()
        report = build_pin_coverage_report(registry, [arch_file])
        # Infrastructure files are classified as introductions
        assert report.introduction_locations == 1
        assert report.unpinned_locations == 0
        # Coverage should be 1.0 since all non-introductions are pinned (trivially)
        assert report.coverage_ratio == 1.0

    def test_introduction_marker_comment(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "handler.py", """\
            def dispatch_event():
                # @introduced
                return route()
        """)
        registry = _make_registry()
        report = build_pin_coverage_report(registry, [arch_file])
        assert report.introduction_locations == 1
        assert report.unpinned_locations == 0

    def test_introduction_edge_type(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def middleware_handler():
                return True
        """)
        registry = _make_registry(
            edges=[ImportEdge(
                edge_id="IMEDGE-0001",
                pin_func_id="PFUNC-0001",
                arch_location=f"{arch_file}:middleware_handler",
                arch_file_path=str(arch_file),
                arch_line=1,
                projection_type="introduction",
            )],
        )
        report = build_pin_coverage_report(registry, [arch_file])
        assert report.introduction_locations == 1

    def test_empty_files(self) -> None:
        registry = _make_registry()
        report = build_pin_coverage_report(registry, [])
        assert report.total_locations == 0
        assert report.coverage_ratio == 1.0

    def test_mixed_coverage(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "mixed.py", """\
            def pinned_func():
                return process()

            def unpinned_func():
                return 42
        """)
        registry = _make_registry(
            edges=[ImportEdge(
                edge_id="IMEDGE-0001",
                pin_func_id="PFUNC-0001",
                arch_location=f"{arch_file}:pinned_func",
                arch_file_path=str(arch_file),
                arch_line=1,
                projection_type="pass_through",
            )],
        )
        report = build_pin_coverage_report(registry, [arch_file])
        assert report.total_locations == 2
        assert report.pinned_locations == 1
        assert report.unpinned_locations == 1
        assert report.coverage_ratio == 0.5


class TestCheckPinCoverage:
    def test_full_coverage_passes(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def handle():
                return process()
        """)
        registry = _make_registry(
            edges=[ImportEdge(
                edge_id="IMEDGE-0001",
                pin_func_id="PFUNC-0001",
                arch_location=f"{arch_file}:handle",
                arch_file_path=str(arch_file),
                arch_line=1,
                projection_type="pass_through",
            )],
        )
        gate_spec = GateSpec(gate_id=GateId.PIN_COVERAGE, threshold=1.0)
        result = check_pin_coverage(registry, [arch_file], gate_spec)
        assert result.passed is True
        assert result.score == 1.0

    def test_partial_coverage_with_threshold(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def pinned():
                return process()

            def unpinned():
                return 1
        """)
        registry = _make_registry(
            edges=[ImportEdge(
                edge_id="IMEDGE-0001",
                pin_func_id="PFUNC-0001",
                arch_location=f"{arch_file}:pinned",
                arch_file_path=str(arch_file),
                arch_line=1,
                projection_type="pass_through",
            )],
        )
        # Threshold 0.4 should pass since we have 50% coverage
        gate_spec = GateSpec(gate_id=GateId.PIN_COVERAGE, threshold=0.4)
        result = check_pin_coverage(registry, [arch_file], gate_spec)
        assert result.passed is True

    def test_below_threshold_fails(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def unpinned():
                return 1
        """)
        registry = _make_registry()
        gate_spec = GateSpec(gate_id=GateId.PIN_COVERAGE, threshold=1.0)
        result = check_pin_coverage(registry, [arch_file], gate_spec)
        assert result.passed is False
        assert len(result.findings) >= 1

    def test_findings_contain_location(self, tmp_path: Path) -> None:
        arch_file = _write_py(tmp_path, "service.py", """\
            def orphan():
                return 1
        """)
        registry = _make_registry()
        gate_spec = GateSpec(gate_id=GateId.PIN_COVERAGE, threshold=1.0)
        result = check_pin_coverage(registry, [arch_file], gate_spec)
        assert result.passed is False
        finding = result.findings[0]
        assert "arch_location" in finding
        assert "arch_file_path" in finding

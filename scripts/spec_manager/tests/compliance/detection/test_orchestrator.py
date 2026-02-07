"""Tests for the unified orchestrator and compliance integration."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.compliance.detection.orchestrator import (
    ExecutableGapReport,
    ScanConfig,
    integrate_with_gap_queue,
    scan_executable_gaps,
)
from spec_manager.refinement.core.gap import GapEvidence, GapSynthesizer
from spec_manager.refinement.core.gap_queue import GapQueue


class TestScanConfig:
    """Test ScanConfig defaults."""

    def test_default_config(self) -> None:
        config = ScanConfig()
        assert config.enable_comments is True
        assert config.enable_stubs is True
        assert config.enable_runtime is False
        assert config.enable_call_graph is True
        assert config.enable_coverage is False
        assert config.runtime_timeout_seconds == 5.0
        assert config.coverage_min_threshold == 0.0
        assert config.call_graph_min_component_size == 2


class TestScanExecutableGaps:
    """Test the unified orchestrator."""

    def test_scan_with_comments_and_stubs(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def real_function():
                return 42

            def stub_function():
                # Implement tax calculation
                pass

            def another_stub():
                raise NotImplementedError("TODO")
        """)
        filepath = tmp_path / "code.py"
        filepath.write_text(source, encoding="utf-8")

        config = ScanConfig(
            enable_comments=True,
            enable_stubs=True,
            enable_runtime=False,
            enable_call_graph=False,
            enable_coverage=False,
        )

        report = scan_executable_gaps([filepath], tmp_path, config)

        assert len(report.comment_gaps) >= 1
        assert len(report.stub_gaps) == 2
        assert len(report.all_evidence) >= 3  # 1 comment + 2 stubs
        assert report.scan_duration_ms >= 0

    def test_scan_with_call_graph(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def cluster1_a():
                cluster1_b()

            def cluster1_b():
                return 1

            def cluster2_a():
                cluster2_b()

            def cluster2_b():
                return 2
        """)
        filepath = tmp_path / "graph.py"
        filepath.write_text(source, encoding="utf-8")

        config = ScanConfig(
            enable_comments=False,
            enable_stubs=False,
            enable_runtime=False,
            enable_call_graph=True,
            enable_coverage=False,
        )

        report = scan_executable_gaps([filepath], tmp_path, config)
        assert report.call_graph is not None
        assert len(report.call_graph.nodes) >= 4

    def test_scan_default_config(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def working():
                return 1
        """)
        filepath = tmp_path / "simple.py"
        filepath.write_text(source, encoding="utf-8")

        report = scan_executable_gaps([filepath], tmp_path)
        assert isinstance(report, ExecutableGapReport)
        assert report.scan_duration_ms >= 0

    def test_scan_empty_file_list(self, tmp_path: Path) -> None:
        report = scan_executable_gaps([], tmp_path)
        assert report.comment_gaps == []
        assert report.stub_gaps == []
        assert report.all_evidence == []

    def test_scan_nonexistent_file_skipped(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "nonexistent.py"
        config = ScanConfig(
            enable_comments=True,
            enable_stubs=True,
            enable_call_graph=False,
        )
        report = scan_executable_gaps([bad_path], tmp_path, config)
        assert isinstance(report, ExecutableGapReport)

    def test_all_evidence_combined(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # Module-level spec comment
            def stub():
                pass
        """)
        filepath = tmp_path / "combined.py"
        filepath.write_text(source, encoding="utf-8")

        config = ScanConfig(
            enable_comments=True,
            enable_stubs=True,
            enable_call_graph=False,
            enable_runtime=False,
            enable_coverage=False,
        )

        report = scan_executable_gaps([filepath], tmp_path, config)
        comment_evidence = [
            e for e in report.all_evidence if e.invariant_family == "executable_comment"
        ]
        stub_evidence = [
            e for e in report.all_evidence if e.invariant_family == "executable_stub"
        ]
        assert len(comment_evidence) >= 1
        assert len(stub_evidence) == 1


class TestIntegrateWithGapQueue:
    """Test integration with GapQueue."""

    def test_merge_into_empty_queue(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def stub():
                pass
        """)
        filepath = tmp_path / "code.py"
        filepath.write_text(source, encoding="utf-8")

        config = ScanConfig(
            enable_comments=False,
            enable_stubs=True,
            enable_call_graph=False,
        )

        report = scan_executable_gaps([filepath], tmp_path, config)
        queue = GapQueue()
        updated = integrate_with_gap_queue(report, queue)

        assert len(updated.gaps) > 0
        assert updated.gaps[0].gap_type.value == "stub_function"

    def test_merge_with_existing_gaps(self, tmp_path: Path) -> None:
        from spec_manager.core.gaps import Severity
        from spec_manager.refinement.core.gap import Gap, GapType

        # Create existing gap
        existing_evidence = GapEvidence(
            invariant_family="coverage",
            description="Existing coverage gap",
            details={"source": "test.py"},
        )
        existing_gap = Gap(
            id="GAP-existing",
            gap_type=GapType.coverage_failure,
            severity=Severity.WARNING,
            source=["test.py"],
            derived_artifact_target="unknown",
            description="Existing gap",
            evidence=[existing_evidence],
        )
        queue = GapQueue(gaps=[existing_gap])

        # Create new executable gaps
        source = textwrap.dedent("""\
            def stub():
                raise NotImplementedError
        """)
        filepath = tmp_path / "code.py"
        filepath.write_text(source, encoding="utf-8")

        config = ScanConfig(
            enable_comments=False,
            enable_stubs=True,
            enable_call_graph=False,
        )

        report = scan_executable_gaps([filepath], tmp_path, config)
        updated = integrate_with_gap_queue(report, queue)

        # Should have both existing and new gaps
        assert len(updated.gaps) >= 2

    def test_empty_report_no_change(self) -> None:
        queue = GapQueue()
        report = ExecutableGapReport()

        updated = integrate_with_gap_queue(report, queue)
        assert len(updated.gaps) == 0

    def test_custom_synthesizer(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def stub():
                pass
        """)
        filepath = tmp_path / "code.py"
        filepath.write_text(source, encoding="utf-8")

        config = ScanConfig(
            enable_comments=False,
            enable_stubs=True,
            enable_call_graph=False,
        )

        report = scan_executable_gaps([filepath], tmp_path, config)
        queue = GapQueue()
        synthesizer = GapSynthesizer()

        updated = integrate_with_gap_queue(report, queue, synthesizer)
        assert len(updated.gaps) > 0


class TestComplianceScorerIntegration:
    """Test ComplianceScorer.check_executable_gaps integration."""

    def test_no_algorithmic_files(self, tmp_path: Path) -> None:
        from spec_manager.compliance.scorer import ComplianceScorer

        scorer = ComplianceScorer()
        blockers = scorer.check_executable_gaps(tmp_path)
        assert blockers == []

    def test_clean_files_no_blockers(self, tmp_path: Path) -> None:
        from spec_manager.compliance.scorer import ComplianceScorer

        source = textwrap.dedent("""\
            def clean_function():
                return 42
        """)
        filepath = tmp_path / "clean.py"
        filepath.write_text(source, encoding="utf-8")

        scorer = ComplianceScorer()
        blockers = scorer.check_executable_gaps(tmp_path, algorithmic_files=[filepath])
        assert len(blockers) == 0

    def test_comments_create_blocker(self, tmp_path: Path) -> None:
        from spec_manager.compliance.scorer import ComplianceScorer

        source = textwrap.dedent("""\
            def incomplete():
                # Need to implement tax calculation
                return 0
        """)
        filepath = tmp_path / "incomplete.py"
        filepath.write_text(source, encoding="utf-8")

        scorer = ComplianceScorer()
        blockers = scorer.check_executable_gaps(tmp_path, algorithmic_files=[filepath])
        comment_blockers = [b for b in blockers if b["type"] == "unimplemented_comments"]
        assert len(comment_blockers) == 1
        assert comment_blockers[0]["details"]["count"] >= 1

    def test_stubs_create_blocker(self, tmp_path: Path) -> None:
        from spec_manager.compliance.scorer import ComplianceScorer

        source = textwrap.dedent("""\
            def unimplemented():
                pass
        """)
        filepath = tmp_path / "stubs.py"
        filepath.write_text(source, encoding="utf-8")

        scorer = ComplianceScorer()
        blockers = scorer.check_executable_gaps(tmp_path, algorithmic_files=[filepath])
        stub_blockers = [b for b in blockers if b["type"] == "stub_functions"]
        assert len(stub_blockers) == 1
        assert stub_blockers[0]["details"]["count"] == 1

    def test_both_comments_and_stubs(self, tmp_path: Path) -> None:
        from spec_manager.compliance.scorer import ComplianceScorer

        source = textwrap.dedent("""\
            # Initialization logic
            def stub():
                pass
        """)
        filepath = tmp_path / "both.py"
        filepath.write_text(source, encoding="utf-8")

        scorer = ComplianceScorer()
        blockers = scorer.check_executable_gaps(tmp_path, algorithmic_files=[filepath])
        types = {b["type"] for b in blockers}
        assert "unimplemented_comments" in types
        assert "stub_functions" in types

    def test_nonexistent_file_handled(self, tmp_path: Path) -> None:
        from spec_manager.compliance.scorer import ComplianceScorer

        scorer = ComplianceScorer()
        bad_path = tmp_path / "nonexistent.py"
        blockers = scorer.check_executable_gaps(tmp_path, algorithmic_files=[bad_path])
        assert blockers == []

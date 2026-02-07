"""Unified orchestrator for executable gap detection.

Wires all five scanners (comment, stub, runtime, call graph, coverage)
into a single orchestration callable that produces a unified report.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.compliance.detection.call_graph import (
    CallGraph,
    build_call_graph,
    detect_adjacency_gaps,
)
from spec_manager.compliance.detection.comment_scanner import (
    EXCLUDED_PREFIXES,
    CommentGap,
    comments_to_gap_evidence,
    scan_comments,
)
from spec_manager.compliance.detection.coverage_analyzer import (
    CoverageReport,
    coverage_to_gap_evidence,
    parse_coverage_report,
    run_coverage,
)
from spec_manager.compliance.detection.runtime_detector import (
    RuntimeProbeResult,
    probe_stubs,
    runtime_results_to_gap_evidence,
)
from spec_manager.compliance.detection.stub_scanner import (
    StubFunction,
    scan_stubs,
    stubs_to_gap_evidence,
)
from spec_manager.refinement.core.gap import GapEvidence, GapSynthesizer
from spec_manager.refinement.core.gap_queue import GapQueue


@dataclass
class ScanConfig:
    """Configuration for which scanners to run."""

    enable_comments: bool = True
    enable_stubs: bool = True
    enable_runtime: bool = False
    enable_call_graph: bool = True
    enable_coverage: bool = False
    comment_excluded_prefixes: tuple[str, ...] = EXCLUDED_PREFIXES
    runtime_timeout_seconds: float = 5.0
    coverage_min_threshold: float = 0.0
    call_graph_min_component_size: int = 2


@dataclass
class ExecutableGapReport:
    """Unified report from all executable gap scanners."""

    comment_gaps: list[CommentGap] = field(default_factory=list)
    stub_gaps: list[StubFunction] = field(default_factory=list)
    runtime_gaps: list[RuntimeProbeResult] = field(default_factory=list)
    adjacency_gaps: list[GapEvidence] = field(default_factory=list)
    coverage_gaps: list[GapEvidence] = field(default_factory=list)
    all_evidence: list[GapEvidence] = field(default_factory=list)
    call_graph: CallGraph = field(default_factory=CallGraph)
    scan_duration_ms: float = 0.0


def scan_executable_gaps(
    filepaths: list[Path],
    project_root: Path,
    config: ScanConfig | None = None,
    test_command: list[str] | None = None,
) -> ExecutableGapReport:
    """Run all configured scanners and produce a unified report.

    Orchestration order:
    1. Comment scanner (all files)
    2. Stub scanner (all files)
    3. Runtime detector (probe stubs if enabled)
    4. Call graph builder (all files)
    5. Coverage analyzer (if enabled and test_command provided)

    Collects all GapEvidence into a single list for downstream synthesis.

    Args:
        filepaths: Python files to scan.
        project_root: Project root for module resolution.
        config: Scanner configuration.
        test_command: Command for coverage analysis (e.g., ["pytest", "tests/"]).

    Returns:
        ExecutableGapReport with all findings.
    """
    if config is None:
        config = ScanConfig()

    start_time = time.monotonic()
    report = ExecutableGapReport()
    all_evidence: list[GapEvidence] = []

    # 1. Comment scanner
    if config.enable_comments:
        for filepath in filepaths:
            try:
                comments = scan_comments(filepath)
                report.comment_gaps.extend(comments)
            except (OSError, UnicodeDecodeError):
                continue
        comment_evidence = comments_to_gap_evidence(report.comment_gaps)
        all_evidence.extend(comment_evidence)

    # 2. Stub scanner
    if config.enable_stubs:
        for filepath in filepaths:
            try:
                stubs = scan_stubs(filepath)
                report.stub_gaps.extend(stubs)
            except (OSError, UnicodeDecodeError):
                continue
        stub_evidence = stubs_to_gap_evidence(report.stub_gaps)
        all_evidence.extend(stub_evidence)

    # 3. Runtime detector
    if config.enable_runtime and report.stub_gaps:
        runtime_results = probe_stubs(
            report.stub_gaps,
            project_root,
            timeout_seconds=config.runtime_timeout_seconds,
        )
        report.runtime_gaps = runtime_results
        runtime_evidence = runtime_results_to_gap_evidence(runtime_results)
        all_evidence.extend(runtime_evidence)

    # 4. Call graph builder
    if config.enable_call_graph:
        call_graph = build_call_graph(filepaths, project_root)
        report.call_graph = call_graph
        adjacency_evidence = detect_adjacency_gaps(
            call_graph,
            min_component_size=config.call_graph_min_component_size,
        )
        report.adjacency_gaps = adjacency_evidence
        all_evidence.extend(adjacency_evidence)

    # 5. Coverage analyzer
    if config.enable_coverage and test_command is not None:
        source_dirs = list({fp.parent for fp in filepaths})
        try:
            coverage_data_file = run_coverage(
                test_command, source_dirs, project_root
            )
            cov_report = parse_coverage_report(coverage_data_file, filepaths)
            coverage_evidence = coverage_to_gap_evidence(
                cov_report,
                min_function_coverage=config.coverage_min_threshold,
            )
            report.coverage_gaps = coverage_evidence
            all_evidence.extend(coverage_evidence)
        except Exception:
            pass

    report.all_evidence = all_evidence
    report.scan_duration_ms = (time.monotonic() - start_time) * 1000

    return report


def integrate_with_gap_queue(
    report: ExecutableGapReport,
    gap_queue: GapQueue,
    synthesizer: GapSynthesizer | None = None,
) -> GapQueue:
    """Feed executable gap evidence into the existing gap queue.

    Uses GapSynthesizer to cluster evidence into Gaps, then merges
    into the existing GapQueue.

    Args:
        report: ExecutableGapReport from scan_executable_gaps.
        gap_queue: Existing GapQueue to merge into.
        synthesizer: Optional GapSynthesizer (uses default if None).

    Returns:
        Updated GapQueue with executable gaps merged in.
    """
    if not report.all_evidence:
        return gap_queue

    if synthesizer is None:
        synthesizer = GapSynthesizer()

    new_gaps = synthesizer.cluster_evidence(report.all_evidence)
    merged = synthesizer.merge_gaps(gap_queue.gaps, new_gaps)
    gap_queue.update(merged)

    return gap_queue

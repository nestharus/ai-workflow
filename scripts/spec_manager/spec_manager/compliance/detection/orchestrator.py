"""Unified orchestrator for executable gap detection.

Aggregates evidence emitted by runtime/coverage plugins and upstream
EvidenceBundle producers. This module does not run comment/stub scanners.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.compliance.detection.coverage_analyzer import (
    coverage_to_gap_evidence,
    parse_coverage_report,
    run_coverage,
)
from spec_manager.compliance.detection.runtime_detector import (
    RuntimeProbeResult,
    probe_stubs,
    runtime_results_to_gap_evidence,
)
from spec_manager.core.gap import GapEvidence, GapSynthesizer
from spec_manager.core.gap_queue import GapQueue

if TYPE_CHECKING:
    from spec_manager.branches.gap_detection import StubFunction
    from spec_manager.schemas.pin_functions import PinFunctionRegistry

logger = logging.getLogger(__name__)


@dataclass
class ScanConfig:
    """Configuration for plugin verifier execution."""

    enable_runtime: bool = False
    enable_coverage: bool = False
    runtime_timeout_seconds: float = 5.0
    coverage_min_uncovered_ratio: float = 0.0
    changed_line_spans: dict[str, list[tuple[int, int]]] = field(default_factory=dict)


@dataclass
class ExecutableGapReport:
    """Unified report from plugin evidence and verifiers."""

    runtime_gaps: list[RuntimeProbeResult] = field(default_factory=list)
    coverage_gaps: list[GapEvidence] = field(default_factory=list)
    plugin_evidence: list[GapEvidence] = field(default_factory=list)
    all_evidence: list[GapEvidence] = field(default_factory=list)
    scan_duration_ms: float = 0.0


def scan_executable_gaps(
    filepaths: list[Path],
    project_root: Path,
    config: ScanConfig | None = None,
    test_command: list[str] | None = None,
    *,
    plugin_evidence: list[GapEvidence] | None = None,
    runtime_stub_candidates: list[StubFunction] | None = None,
    pin_registry: PinFunctionRegistry | None = None,
) -> ExecutableGapReport:
    """Run enabled plugin verifiers and aggregate executable gap evidence.

    Args:
        filepaths: Source files scoped for runtime/coverage verifiers.
        project_root: Project root for runtime/coverage tooling.
        config: Plugin verifier configuration.
        test_command: Command for coverage analysis (for example, ["pytest", "tests/"]).
        plugin_evidence: Gap evidence collected upstream (for example EvidenceBundle facts).
        runtime_stub_candidates: Optional runtime probe targets prepared by upstream plugins.
        pin_registry: Optional pin registry used for pin-span coverage mapping.

    Returns:
        ExecutableGapReport with aggregated evidence.
    """
    if config is None:
        config = ScanConfig()

    start_time = time.monotonic()
    report = ExecutableGapReport()
    all_evidence: list[GapEvidence] = []

    report.plugin_evidence = list(plugin_evidence or [])
    all_evidence.extend(report.plugin_evidence)

    if config.enable_runtime and runtime_stub_candidates:
        runtime_results = probe_stubs(
            runtime_stub_candidates,
            project_root,
            timeout_seconds=config.runtime_timeout_seconds,
        )
        report.runtime_gaps = runtime_results
        all_evidence.extend(runtime_results_to_gap_evidence(runtime_results))

    if config.enable_coverage and test_command is not None:
        source_dirs = list({fp.parent for fp in filepaths})
        try:
            coverage_data_file = run_coverage(test_command, source_dirs, project_root)
            cov_report = parse_coverage_report(coverage_data_file, filepaths)
            coverage_evidence = coverage_to_gap_evidence(
                cov_report,
                pin_registry=pin_registry,
                changed_line_spans=config.changed_line_spans,
                min_uncovered_ratio=config.coverage_min_uncovered_ratio,
            )
            report.coverage_gaps = coverage_evidence
            all_evidence.extend(coverage_evidence)
        except Exception:
            logger.debug(
                "Coverage analysis failed; continuing without coverage evidence",
                exc_info=True,
            )

    report.all_evidence = all_evidence
    report.scan_duration_ms = (time.monotonic() - start_time) * 1000
    return report


def integrate_with_gap_queue(
    report: ExecutableGapReport,
    gap_queue: GapQueue,
    synthesizer: GapSynthesizer | None = None,
) -> GapQueue:
    """Feed executable gap evidence into the existing gap queue."""
    if not report.all_evidence:
        return gap_queue

    if synthesizer is None:
        synthesizer = GapSynthesizer()

    new_gaps = synthesizer.cluster_evidence(report.all_evidence)
    merged = synthesizer.merge_gaps(gap_queue.gaps, new_gaps)
    gap_queue.update(merged)

    return gap_queue

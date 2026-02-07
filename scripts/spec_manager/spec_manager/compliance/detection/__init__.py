"""Executable gap detection for algorithmic code.

Provides scanners that mechanically identify unimplemented spec elements
by analyzing comments, detecting stubs, probing runtime behavior,
building call graphs, and analyzing code coverage.

Public API:
    scan_executable_gaps: Run all configured scanners.
    integrate_with_gap_queue: Feed results into existing gap queue.
    ExecutableGapReport: Unified report from all scanners.
    ScanConfig: Configuration for scanner selection.
"""

from __future__ import annotations

from spec_manager.compliance.detection.orchestrator import (
    ExecutableGapReport,
    ScanConfig,
    integrate_with_gap_queue,
    scan_executable_gaps,
)

__all__ = [
    "ExecutableGapReport",
    "ScanConfig",
    "integrate_with_gap_queue",
    "scan_executable_gaps",
]

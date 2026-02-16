"""Executable gap detection evidence aggregation.

Aggregates plugin-emitted executable evidence and optional runtime/coverage
verifier output into a single report.
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

"""Compliance metrics computation for spec management.

This module provides functions to compute compliance metrics for specification
content based on tracked units.

Public API:
    compute_compliance_metrics: Main entry point for compliance analysis
    compute_format_compliance: Check annotation format compliance
    compute_annotation_coverage: Check structured element annotation coverage
    compute_id_normalization: Check ID format canonicalization

Usage:
    from spec_manager.compliance import compute_compliance_metrics

    metrics = compute_compliance_metrics(units)
    if metrics.gate_passed():
        print("Quality gate passed!")
"""

from spec_manager.compliance.metrics import (
    compute_annotation_coverage,
    compute_compliance_metrics,
    compute_format_compliance,
    compute_id_normalization,
)

__all__ = [
    "compute_compliance_metrics",
    "compute_format_compliance",
    "compute_annotation_coverage",
    "compute_id_normalization",
]

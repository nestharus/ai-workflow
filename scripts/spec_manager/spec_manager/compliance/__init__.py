"""Compliance metrics computation for spec management.

This module provides functions to compute compliance metrics for specification
content based on tracked units, as well as contract validation for agent outputs.

Public API:
    compute_compliance_metrics: Main entry point for compliance analysis
    compute_format_compliance: Check annotation format compliance
    compute_annotation_coverage: Check structured element annotation coverage
    compute_id_normalization: Check ID format canonicalization
    ContractValidationResult: Result of contract validation (DS-COMP-0001)
    SchemaRegistry: Centralized registry for JSON schemas
    validate_artifact_contract: Validate artifact against schema (ALG-COMP-0001)
    get_default_registry: Get the singleton schema registry
    CoverageReport: Coverage report for atom accounting (DS-PROV-0005)
    CoverageGateResult: Result of coverage gate check
    verify_coverage_or_emit_gap: Coverage verification (ALG-PROV-0003)
    build_coverage_report: Build coverage report from atom sets

Usage:
    from spec_manager.compliance import compute_compliance_metrics

    metrics = compute_compliance_metrics(units)
    if metrics.gate_passed():
        print("Quality gate passed!")

    from spec_manager.compliance import validate_artifact_contract

    result = validate_artifact_contract(artifact, "derived_elements")
    if not result.valid:
        print(f"Validation errors: {result.errors}")

    from spec_manager.compliance import verify_coverage_or_emit_gap

    gate_result = verify_coverage_or_emit_gap(coverage_report, "run_001")
    if not gate_result.passed:
        print(f"Coverage gate failed: {gate_result.gap_element.summary}")
"""

from spec_manager.compliance.coverage_gate import (
    CoverageGateResult,
    CoverageReport,
    build_coverage_report,
    verify_coverage_or_emit_gap,
)
from spec_manager.compliance.evidence_field_lint import (
    LintResult,
    is_evidence_field,
    lint_l1_artifact,
    scan_evidence_fields,
    scan_for_forbidden_output_signatures,
    validate_evid_value,
)
from spec_manager.compliance.metrics import (
    compute_annotation_coverage,
    compute_compliance_metrics,
    compute_format_compliance,
    compute_id_normalization,
)
from spec_manager.compliance.schema_registry import (
    SchemaRegistry,
    get_default_registry,
)
from spec_manager.compliance.validation import (
    ContractValidationResult,
    validate_artifact_contract,
)

__all__ = [
    "ContractValidationResult",
    "CoverageGateResult",
    "CoverageReport",
    "LintResult",
    "SchemaRegistry",
    "build_coverage_report",
    "compute_annotation_coverage",
    "compute_compliance_metrics",
    "compute_format_compliance",
    "compute_id_normalization",
    "get_default_registry",
    "is_evidence_field",
    "lint_l1_artifact",
    "scan_evidence_fields",
    "scan_for_forbidden_output_signatures",
    "validate_artifact_contract",
    "validate_evid_value",
    "verify_coverage_or_emit_gap",
]

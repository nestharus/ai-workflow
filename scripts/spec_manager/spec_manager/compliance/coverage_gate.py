"""Coverage verification gate implementing INV-ACC-0101 (100% atom accounting).

This module provides the coverage report structure and verification gate that
blocks promotion on non-100% coverage but produces valid fallback state per CON-0009.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spec_manager.core.gaps import DetectorFinding, GapElement, Severity


@dataclass
class CoverageReport:
    """Coverage report per DS-PROV-0005.

    Tracks atom accounting for a single file revision.

    Attributes:
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        total_atoms: Total number of atoms in the file
        mapped_atoms: Number of atoms mapped to sections
        remainder_atoms: Number of atoms in UNKNOWN/remainder spans
        excluded_atoms: Number of intentionally excluded atoms
        unaccounted_atom_ids: List of atom IDs not accounted for
    """

    file_uid: str
    rev_id: str
    total_atoms: int
    mapped_atoms: int
    remainder_atoms: int
    excluded_atoms: int
    unaccounted_atom_ids: list[str] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        """Calculate coverage ratio (0.0-1.0).

        Returns:
            Ratio of mapped atoms to total atoms
        """
        if self.total_atoms == 0:
            return 1.0
        return self.mapped_atoms / self.total_atoms

    @property
    def is_complete(self) -> bool:
        """Check if all atoms are accounted for.

        Returns:
            True if no unaccounted atoms remain
        """
        return len(self.unaccounted_atom_ids) == 0


@dataclass
class CoverageGateResult:
    """Result of coverage gate check.

    Attributes:
        passed: Whether the coverage gate passed
        coverage_report: The coverage report
        gap_element: Gap element if gate failed
        fallback_state_valid: Whether fallback state is valid (per CON-0009)
    """

    passed: bool
    coverage_report: CoverageReport
    gap_element: GapElement | None = None
    fallback_state_valid: bool = True


def verify_coverage_or_emit_gap(
    coverage_report: CoverageReport,
    run_id: str,
) -> CoverageGateResult:
    """ALG-PROV-0003: Verify 100% coverage or emit gap.

    Per CON-0009: Non-100% coverage blocks promotion but produces
    valid fallback state.

    Args:
        coverage_report: The coverage report to verify
        run_id: Current run ID for gap identification

    Returns:
        CoverageGateResult indicating pass/fail and any gap element
    """
    if coverage_report.is_complete and coverage_report.coverage_ratio == 1.0:
        return CoverageGateResult(
            passed=True,
            coverage_report=coverage_report,
        )

    # Emit GAP(COVERAGE) element
    gap = GapElement(
        id=f"GAP-COVERAGE-{coverage_report.file_uid}-{run_id}",
        severity=Severity.ERROR,
        summary=f"Incomplete atom coverage: {coverage_report.coverage_ratio:.1%}",
        affects=[coverage_report.file_uid],
        evidence=[
            DetectorFinding(
                severity=Severity.ERROR,
                message=f"{len(coverage_report.unaccounted_atom_ids)} atoms unaccounted",
                location=f"{coverage_report.file_uid}:{coverage_report.rev_id}",
                detector="coverage_gate",
                details={
                    "unaccounted_atoms": coverage_report.unaccounted_atom_ids,
                    "unaccounted_atoms_preview": coverage_report.unaccounted_atom_ids[:20],
                    "total_unaccounted": len(coverage_report.unaccounted_atom_ids),
                },
            )
        ],
    )

    return CoverageGateResult(
        passed=False,
        coverage_report=coverage_report,
        gap_element=gap,
        fallback_state_valid=True,  # CON-0009: fallback is valid
    )


def build_coverage_report(
    file_uid: str,
    rev_id: str,
    total_atom_ids: set[str],
    mapped_atom_ids: set[str],
    remainder_atom_ids: set[str],
    excluded_atom_ids: set[str] | None = None,
) -> CoverageReport:
    """Build a coverage report from atom ID sets.

    Args:
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        total_atom_ids: Set of all atom IDs
        mapped_atom_ids: Set of atom IDs mapped to sections
        remainder_atom_ids: Set of atom IDs in remainder/UNKNOWN spans
        excluded_atom_ids: Optional set of intentionally excluded atom IDs

    Returns:
        A CoverageReport summarizing the coverage state
    """
    excluded = excluded_atom_ids or set()
    accounted = mapped_atom_ids | remainder_atom_ids | excluded
    unaccounted = total_atom_ids - accounted

    return CoverageReport(
        file_uid=file_uid,
        rev_id=rev_id,
        total_atoms=len(total_atom_ids),
        mapped_atoms=len(mapped_atom_ids),
        remainder_atoms=len(remainder_atom_ids),
        excluded_atoms=len(excluded),
        unaccounted_atom_ids=sorted(unaccounted),
    )

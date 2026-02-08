"""Tests for CON-0002: 100% Atom Accounting.

CON-0002 specifies that every atom must be accounted for in exactly one state:
- mapped: Atom has been mapped to a derived element
- remainder: Atom is in the remainder queue (not yet processed)
- excluded: Atom has been explicitly excluded (noise)

This module contains:
- xfail tests for features not yet implemented (atom accounting verification)
- passing tests for current coverage tracking functionality
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from spec_manager.core.coverage import CoverageTracker, FragmentStatus


@dataclass
class AtomAccountingResult:
    """Result of atom accounting verification.

    This is a placeholder for the full atom accounting verification
    that will be implemented in later phases.
    """

    all_accounted: bool
    unaccounted_atoms: list[str]
    mapped_count: int
    remainder_count: int
    excluded_count: int
    total_count: int

    @property
    def coverage_complete(self) -> bool:
        """Check if all atoms are accounted for."""
        return self.all_accounted and len(self.unaccounted_atoms) == 0


def verify_atom_accounting_from_tracker(
    tracker: CoverageTracker, file_path: str
) -> AtomAccountingResult:
    """Verify atom accounting using the existing CoverageTracker.

    This is a helper function that bridges the CoverageTracker with the
    atom accounting invariant defined in CON-0002.

    Args:
        tracker: The CoverageTracker with fragment data.
        file_path: The file path to check coverage for.

    Returns:
        AtomAccountingResult with coverage statistics.
    """
    leaves = tracker.get_leaves(file_path)

    mapped_count = 0
    remainder_count = 0
    excluded_count = 0
    unaccounted: list[str] = []

    for fragment in leaves:
        if fragment.status == FragmentStatus.PROJECTED:
            mapped_count += 1
        elif fragment.status == FragmentStatus.NOISE:
            excluded_count += 1
        elif fragment.status in (FragmentStatus.PROSE, FragmentStatus.STUCK, FragmentStatus.MOBILE):
            remainder_count += 1
        elif fragment.status == FragmentStatus.UNDERSPECIFIED:
            # Underspecified fragments are in the remainder queue
            remainder_count += 1
        else:
            # Status not accounted for
            unaccounted.append(fragment.id)

    total = mapped_count + remainder_count + excluded_count + len(unaccounted)
    all_accounted = len(unaccounted) == 0 and total == len(leaves)

    return AtomAccountingResult(
        all_accounted=all_accounted,
        unaccounted_atoms=unaccounted,
        mapped_count=mapped_count,
        remainder_count=remainder_count,
        excluded_count=excluded_count,
        total_count=len(leaves),
    )


class TestAtomAccountingWithCoverageTracker:
    """Tests for atom accounting using the existing CoverageTracker.

    These tests verify that the CoverageTracker correctly tracks fragments
    through different states, which forms the foundation for CON-0002.
    """

    def test_all_projected_atoms_accounted(
        self,
        coverage_tracker_all_projected: CoverageTracker,
    ) -> None:
        """All projected atoms should be accounted as 'mapped'."""
        result = verify_atom_accounting_from_tracker(coverage_tracker_all_projected, "test.md")

        assert result.all_accounted is True
        assert result.unaccounted_atoms == []
        assert result.mapped_count == 3
        assert result.remainder_count == 0
        assert result.excluded_count == 0

    def test_some_remainder_atoms_accounted(
        self,
        coverage_tracker_some_remainder: CoverageTracker,
    ) -> None:
        """Atoms in remainder queue should be accounted as 'remainder'."""
        result = verify_atom_accounting_from_tracker(coverage_tracker_some_remainder, "test.md")

        assert result.all_accounted is True
        assert result.unaccounted_atoms == []
        assert result.mapped_count == 1
        assert result.remainder_count == 2
        assert result.excluded_count == 0

    def test_some_excluded_atoms_accounted(
        self,
        coverage_tracker_some_excluded: CoverageTracker,
    ) -> None:
        """Atoms marked as noise should be accounted as 'excluded'."""
        result = verify_atom_accounting_from_tracker(coverage_tracker_some_excluded, "test.md")

        assert result.all_accounted is True
        assert result.unaccounted_atoms == []
        assert result.mapped_count == 2
        assert result.remainder_count == 0
        assert result.excluded_count == 1

    def test_coverage_complete_property(
        self,
        coverage_tracker_all_projected: CoverageTracker,
    ) -> None:
        """coverage_complete should be True when all atoms accounted."""
        result = verify_atom_accounting_from_tracker(coverage_tracker_all_projected, "test.md")

        assert result.coverage_complete is True


class TestCoverageTrackerVerification:
    """Tests for CoverageTracker.verify_coverage() integration with CON-0002."""

    def test_verify_coverage_complete(
        self,
        coverage_tracker_all_projected: CoverageTracker,
    ) -> None:
        """verify_coverage should return True when all content is covered."""
        is_complete, gaps = coverage_tracker_all_projected.verify_coverage("test.md")

        assert is_complete is True
        assert gaps == []

    def test_coverage_report_contains_status_breakdown(
        self,
        coverage_tracker_some_remainder: CoverageTracker,
    ) -> None:
        """Coverage report should show status breakdown."""
        report = coverage_tracker_some_remainder.get_coverage_report("test.md")

        assert report["complete"] is True
        assert "by_status" in report
        assert "projected" in report["by_status"]
        assert "prose" in report["by_status"]


class TestAtomAccountingInvariant:
    """Tests for the CON-0002 invariant: every atom in exactly one state.

    These tests are marked as xfail because the full verify_atom_accounting()
    function with manifest-based tracking is not yet implemented.
    """

    @pytest.mark.xfail(reason="Full atom accounting verification not yet implemented")
    def test_atom_accounting_invariant_all_mapped(
        self,
        atom_manifest_all_mapped: dict[str, Any],
    ) -> None:
        """Every atom must be in exactly one state (all mapped scenario).

        CON-0002 invariant: Every atom is either mapped, remainder, or excluded.
        """
        # This requires the full verify_atom_accounting() function
        from spec_manager.compliance import verify_atom_accounting  # type: ignore[attr-defined]

        result = verify_atom_accounting(atom_manifest_all_mapped)

        assert result.all_accounted is True
        assert result.unaccounted_atoms == []
        assert result.mapped_count == 3

    @pytest.mark.xfail(reason="Full atom accounting verification not yet implemented")
    def test_atom_accounting_invariant_some_remainder(
        self,
        atom_manifest_some_remainder: dict[str, Any],
    ) -> None:
        """Every atom must be in exactly one state (some remainder scenario).

        CON-0002 invariant: Atoms in remainder queue are properly tracked.
        """
        from spec_manager.compliance import verify_atom_accounting  # type: ignore[attr-defined]

        result = verify_atom_accounting(atom_manifest_some_remainder)

        assert result.all_accounted is True
        assert result.unaccounted_atoms == []
        assert result.mapped_count == 1
        assert result.remainder_count == 2

    @pytest.mark.xfail(reason="Full atom accounting verification not yet implemented")
    def test_atom_accounting_invariant_some_excluded(
        self,
        atom_manifest_some_excluded: dict[str, Any],
    ) -> None:
        """Every atom must be in exactly one state (some excluded scenario).

        CON-0002 invariant: Excluded atoms are properly tracked.
        """
        from spec_manager.compliance import verify_atom_accounting  # type: ignore[attr-defined]

        result = verify_atom_accounting(atom_manifest_some_excluded)

        assert result.all_accounted is True
        assert result.unaccounted_atoms == []
        assert result.excluded_count == 1

    @pytest.mark.xfail(reason="Full atom accounting verification not yet implemented")
    def test_coverage_reports_detect_silent_drops(
        self,
        atom_manifest_all_mapped: dict[str, Any],
    ) -> None:
        """Coverage reports must detect atoms that silently dropped.

        CON-0002 requirement: No atom can be silently dropped. The coverage
        report must flag any atom that is not in mapped, remainder, or excluded.
        """
        from spec_manager.compliance import verify_atom_accounting  # type: ignore[attr-defined]

        # Simulate a manifest with a dropped atom (not in any state)
        manifest_with_drop = {
            "atoms": [
                {"atom_id": "ATOM-0001", "status": "mapped", "mapped_to": "ELEM-0001"},
                {"atom_id": "ATOM-0002", "status": "unknown"},  # Silent drop
            ],
            "coverage_summary": {
                "total": 2,
                "mapped": 1,
                "remainder": 0,
                "excluded": 0,
            },
        }

        result = verify_atom_accounting(manifest_with_drop)

        assert result.all_accounted is False
        assert "ATOM-0002" in result.unaccounted_atoms

    @pytest.mark.xfail(reason="Remainder queue population not yet implemented")
    def test_remainder_queue_populated_for_unmapped(
        self,
        atom_manifest_some_remainder: dict[str, Any],
    ) -> None:
        """Unmapped atoms must be added to remainder queue.

        CON-0002 requirement: Atoms that are not mapped must be tracked
        in the remainder queue for processing in subsequent iterations.
        """
        from spec_manager.compliance import (  # type: ignore[attr-defined]
            get_remainder_queue,
            verify_atom_accounting,
        )

        result = verify_atom_accounting(atom_manifest_some_remainder)
        queue = get_remainder_queue(atom_manifest_some_remainder)

        assert result.remainder_count == 2
        assert "ATOM-0002" in queue.items
        assert "ATOM-0003" in queue.items

"""File-based scheduling for parallel execution.

Units targeting the same file must run sequentially to avoid conflicts.
Units targeting different files can run in parallel for throughput.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.planner.state import DesignState


class FileScheduler:
    """Schedules units for execution based on target files.

    Same-file units: sequential (avoid conflicts)
    Different-file units: parallel (maximize throughput)
    """

    def __init__(self, state: DesignState) -> None:
        """Initialize file scheduler.

        Args:
            state: The design state to schedule from
        """
        self.state = state

    def group_by_file(self, unit_ids: list[str]) -> dict[str, list[str]]:
        """Group unit IDs by their target file.

        Args:
            unit_ids: List of unit IDs to group

        Returns:
            Dict mapping file path to list of unit IDs.
            Units without a target file are grouped under "__no_file__".
        """
        groups: dict[str, list[str]] = {}
        no_file: list[str] = []

        for uid in unit_ids:
            unit = self.state.units.get(uid)
            if unit and unit.plan and unit.plan.target_file:
                target = unit.plan.target_file
                if target not in groups:
                    groups[target] = []
                groups[target].append(uid)
            else:
                no_file.append(uid)

        # Units without target file go in their own group
        if no_file:
            groups["__no_file__"] = no_file

        return groups

    def get_parallel_groups(self, unit_ids: list[str]) -> list[list[str]]:
        """Get groups that can run in parallel.

        Each inner list contains units for the same file (run sequentially).
        Outer lists represent different files (run in parallel).

        Args:
            unit_ids: List of unit IDs to schedule

        Returns:
            List of groups, where each group is a list of unit IDs
        """
        by_file = self.group_by_file(unit_ids)
        return list(by_file.values())

    def get_file_count(self, unit_ids: list[str]) -> int:
        """Get the number of unique files targeted by units.

        Args:
            unit_ids: List of unit IDs to check

        Returns:
            Number of unique target files
        """
        by_file = self.group_by_file(unit_ids)
        return len(by_file)

    def get_max_sequential_depth(self, unit_ids: list[str]) -> int:
        """Get the maximum number of units targeting the same file.

        This represents the minimum number of sequential steps needed.

        Args:
            unit_ids: List of unit IDs to check

        Returns:
            Maximum units per file (sequential depth)
        """
        by_file = self.group_by_file(unit_ids)
        if not by_file:
            return 0
        return max(len(units) for units in by_file.values())

    def estimate_parallelism(self, unit_ids: list[str]) -> dict[str, int | float]:
        """Estimate parallelism metrics for scheduling.

        Args:
            unit_ids: List of unit IDs to analyze

        Returns:
            Dict with parallelism metrics:
            - total_units: Total number of units
            - file_count: Number of unique files (parallel groups)
            - max_sequential: Max units per file (sequential depth)
            - parallelism_ratio: Ratio of parallel to sequential work
        """
        by_file = self.group_by_file(unit_ids)
        total = len(unit_ids)
        files = len(by_file)
        max_seq = max(len(units) for units in by_file.values()) if by_file else 0

        return {
            "total_units": total,
            "file_count": files,
            "max_sequential": max_seq,
            "parallelism_ratio": files / max_seq if max_seq > 0 else 0,
        }

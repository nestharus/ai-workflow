"""
Planning phase operations.

These operations decompose changes into safe batches for merging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.ids import IdValidator, IdCategory
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.sections import SectionExtractor


@dataclass
class IdComparison:
    """Result of comparing IDs between sources."""

    in_both: list[str] = field(default_factory=list)
    only_in_source: list[str] = field(default_factory=list)  # e.g., only in plan
    only_in_target: list[str] = field(default_factory=list)  # e.g., only in libs.md

    def to_dict(self) -> dict[str, Any]:
        return {
            "in_both": len(self.in_both),
            "only_in_source": self.only_in_source,
            "only_in_target": self.only_in_target,
        }


@dataclass
class SequenceIssue:
    """A sequence issue (gap or duplicate)."""

    category: str  # e.g., "algorithm", "goal"
    issue_type: str  # "gap" or "duplicate"
    numbers: list[int]  # The problematic numbers
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "issue_type": self.issue_type,
            "numbers": self.numbers,
            "message": self.message,
        }


@dataclass
class Batch:
    """A batch of changes to apply."""

    id: str
    description: str
    ids: list[str]  # IDs included in this batch
    operation: str  # "extract", "move", "update"
    source_library: str | None = None
    target_library: str | None = None
    priority: int = 0  # Lower = higher priority

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "ids": self.ids,
            "operation": self.operation,
            "source_library": self.source_library,
            "target_library": self.target_library,
            "priority": self.priority,
        }


@dataclass
class PlanningResult:
    """Result of planning phase."""

    id_comparison: IdComparison = field(default_factory=IdComparison)
    missing_in_registry: list[str] = field(default_factory=list)
    missing_in_libraries: list[str] = field(default_factory=list)
    sequence_issues: list[SequenceIssue] = field(default_factory=list)
    batches: list[Batch] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        return len(self.conflicts) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id_comparison": self.id_comparison.to_dict(),
            "missing_in_registry": self.missing_in_registry,
            "missing_in_libraries": self.missing_in_libraries,
            "sequence_issues": [s.to_dict() for s in self.sequence_issues],
            "batches": [b.to_dict() for b in self.batches],
            "conflicts": self.conflicts,
            "has_blocking_issues": self.has_blocking_issues,
        }


def compare_ids(
    source_ids: set[str], target_ids: set[str]
) -> IdComparison:
    """
    Compare two sets of IDs.

    Args:
        source_ids: IDs from source (e.g., plan.md)
        target_ids: IDs from target (e.g., libs.md)

    Returns:
        IdComparison with sets of IDs
    """
    return IdComparison(
        in_both=sorted(source_ids & target_ids),
        only_in_source=sorted(source_ids - target_ids),
        only_in_target=sorted(target_ids - source_ids),
    )


def find_missing_in_registry(
    plan_content: str, registry: LibsRegistry
) -> list[str]:
    """
    Find IDs declared in plan but not in libs.md registry.

    Args:
        plan_content: Content of plan.md
        registry: The libs.md registry

    Returns:
        List of missing ID values
    """
    extractor = SectionExtractor()
    result = extractor.extract(plan_content)

    plan_ids = set(result.sections.keys())
    registry_ids = set(registry.entries.keys())

    return sorted(plan_ids - registry_ids)


def find_missing_in_libraries(
    registry: LibsRegistry, libraries_dir: Path
) -> list[str]:
    """
    Find IDs in libs.md that don't exist in any library file.

    Args:
        registry: The libs.md registry
        libraries_dir: Path to libraries directory

    Returns:
        List of missing ID values
    """
    extractor = SectionExtractor()
    library_results = extractor.extract_from_directory(libraries_dir)

    # Collect all IDs found in libraries
    library_ids: set[str] = set()
    for result in library_results.values():
        library_ids.update(result.sections.keys())

    # Find registry IDs not in any library
    registry_ids = set(registry.entries.keys())
    return sorted(registry_ids - library_ids)


def check_sequences(content: str) -> list[SequenceIssue]:
    """
    Check for sequence issues (gaps, duplicates) in numbered IDs.

    Checks:
    - Algorithm numbers (1, 2, 3, ...)
    - Goal numbers (G1, G2, G3, ...)
    - Patch invariants per patch (P1I1, P1I2, ...)
    - Patch claims per patch (P1C1, P1C2, ...)

    Returns:
        List of SequenceIssue objects
    """
    issues: list[SequenceIssue] = []
    validator = IdValidator()

    # Extract all IDs
    extractor = SectionExtractor()
    result = extractor.extract(content)

    # Group IDs by category
    algorithms: list[int] = []
    goals: list[int] = []
    patch_invariants: dict[int, list[int]] = {}
    patch_claims: dict[int, list[int]] = {}

    for id_value in result.sections.keys():
        category = validator.get_category(id_value)
        numbers = validator.extract_numbers(id_value)

        if category == IdCategory.ALGORITHM:
            algorithms.append(numbers.get("number", 0))
        elif category == IdCategory.GOAL:
            goals.append(numbers.get("number", numbers.get("goal", 0)))
        elif category == IdCategory.PATCH_INVARIANT:
            patch = numbers.get("patch", 0)
            inv = numbers.get("invariant", 0)
            patch_invariants.setdefault(patch, []).append(inv)
        elif category == IdCategory.PATCH_CLAIM:
            patch = numbers.get("patch", 0)
            claim = numbers.get("claim", 0)
            patch_claims.setdefault(patch, []).append(claim)

    # Check algorithms
    issues.extend(_check_number_sequence("algorithm", algorithms))

    # Check goals
    issues.extend(_check_number_sequence("goal", goals))

    # Check patch invariants per patch
    for patch_num, invariants in patch_invariants.items():
        issues.extend(
            _check_number_sequence(f"P{patch_num} invariant", invariants)
        )

    # Check patch claims per patch
    for patch_num, claims in patch_claims.items():
        issues.extend(
            _check_number_sequence(f"P{patch_num} claim", claims)
        )

    return issues


def _check_number_sequence(category: str, numbers: list[int]) -> list[SequenceIssue]:
    """Check a sequence of numbers for gaps and duplicates."""
    issues: list[SequenceIssue] = []

    if not numbers:
        return issues

    sorted_nums = sorted(numbers)

    # Check for duplicates
    from collections import Counter
    counts = Counter(numbers)
    duplicates = [n for n, c in counts.items() if c > 1]
    if duplicates:
        issues.append(
            SequenceIssue(
                category=category,
                issue_type="duplicate",
                numbers=duplicates,
                message=f"Duplicate {category} numbers: {duplicates}",
            )
        )

    # Check for gaps (only if starting from 1)
    unique_sorted = sorted(set(numbers))
    if unique_sorted and unique_sorted[0] == 1:
        expected = set(range(1, max(unique_sorted) + 1))
        actual = set(unique_sorted)
        gaps = sorted(expected - actual)
        if gaps:
            issues.append(
                SequenceIssue(
                    category=category,
                    issue_type="gap",
                    numbers=gaps,
                    message=f"Missing {category} numbers: {gaps}",
                )
            )

    return issues


def create_batches(
    plan_content: str,
    registry: LibsRegistry,
    libraries_dir: Path,
    batch_size: int = 10,
) -> list[Batch]:
    """
    Create batches of changes to apply.

    Args:
        plan_content: Content of plan.md
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        batch_size: Maximum IDs per batch

    Returns:
        List of Batch objects
    """
    batches: list[Batch] = []

    extractor = SectionExtractor()
    plan_result = extractor.extract(plan_content)
    library_results = extractor.extract_from_directory(libraries_dir)

    # Collect all IDs in libraries
    library_ids: dict[str, set[str]] = {}
    for lib_name, result in library_results.items():
        library_ids[lib_name] = set(result.sections.keys())

    all_library_ids = set()
    for ids in library_ids.values():
        all_library_ids.update(ids)

    # Find IDs to extract (in plan, in registry, not in libraries)
    to_extract: dict[str, list[str]] = {}  # library -> IDs
    for id_value in plan_result.sections.keys():
        if id_value in registry.entries and id_value not in all_library_ids:
            target_lib = registry.get_primary(id_value)
            if target_lib:
                to_extract.setdefault(target_lib, []).append(id_value)

    # Create extraction batches
    batch_id = 0
    for target_lib, ids in to_extract.items():
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_id += 1
            batches.append(
                Batch(
                    id=f"extract_{batch_id}",
                    description=f"Extract {len(batch_ids)} IDs to {target_lib}",
                    ids=batch_ids,
                    operation="extract",
                    target_library=target_lib,
                    priority=1,
                )
            )

    # Find IDs in wrong library (need move)
    to_move: list[tuple[str, str, str]] = []  # (id, from_lib, to_lib)
    for id_value, entry in registry.entries.items():
        expected_lib = entry.primary
        for lib_name, ids in library_ids.items():
            if id_value in ids and lib_name != expected_lib:
                to_move.append((id_value, lib_name, expected_lib))

    # Create move batches
    if to_move:
        for i in range(0, len(to_move), batch_size):
            batch_moves = to_move[i : i + batch_size]
            batch_id += 1
            batches.append(
                Batch(
                    id=f"move_{batch_id}",
                    description=f"Move {len(batch_moves)} IDs to correct libraries",
                    ids=[m[0] for m in batch_moves],
                    operation="move",
                    priority=2,
                )
            )

    return batches


def run_planning(
    plan_content: str,
    registry: LibsRegistry,
    libraries_dir: Path,
) -> PlanningResult:
    """
    Run all planning operations.

    Args:
        plan_content: Content of plan.md
        registry: The libs.md registry
        libraries_dir: Path to libraries directory

    Returns:
        PlanningResult with all findings
    """
    result = PlanningResult()

    # Extract IDs from plan
    extractor = SectionExtractor()
    plan_result = extractor.extract(plan_content)
    plan_ids = set(plan_result.sections.keys())
    registry_ids = set(registry.entries.keys())

    # Compare IDs
    result.id_comparison = compare_ids(plan_ids, registry_ids)

    # Find missing
    result.missing_in_registry = find_missing_in_registry(plan_content, registry)
    result.missing_in_libraries = find_missing_in_libraries(registry, libraries_dir)

    # Check sequences
    result.sequence_issues = check_sequences(plan_content)

    # Detect conflicts (IDs in multiple libraries)
    library_results = extractor.extract_from_directory(libraries_dir)
    id_locations = extractor.collect_all_ids(libraries_dir)

    for id_value, locations in id_locations.items():
        if len(locations) > 1:
            expected = registry.get_primary(id_value)
            result.conflicts.append({
                "type": "duplicate",
                "id": id_value,
                "expected_library": expected,
                "found_in": [f"{lib}:{line}" for lib, line in locations],
            })

    # Create batches (only if no blocking conflicts)
    if not result.has_blocking_issues:
        result.batches = create_batches(plan_content, registry, libraries_dir)

    return result

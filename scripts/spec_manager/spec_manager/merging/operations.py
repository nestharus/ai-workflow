"""
Merging phase operations.

These operations apply changes to library files.
All operations support dry-run mode by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.sections import SectionExtractor, Section


@dataclass
class MergeAction:
    """An action to perform during merging."""

    action_type: str  # "extract", "move", "remove", "sort"
    id_value: str | None = None
    source_file: str | None = None
    target_file: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "id_value": self.id_value,
            "source_file": self.source_file,
            "target_file": self.target_file,
            "description": self.description,
        }


@dataclass
class MergingResult:
    """Result of merging operations."""

    actions_planned: list[MergeAction] = field(default_factory=list)
    actions_applied: list[MergeAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = True

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "actions_planned": len(self.actions_planned),
            "actions_applied": len(self.actions_applied),
            "errors": self.errors,
            "success": self.success,
        }


def extract_to_libraries(
    plan_content: str,
    registry: LibsRegistry,
    libraries_dir: Path,
    apply: bool = False,
) -> MergingResult:
    """
    Extract sections from plan.md to library files.

    Only extracts IDs that:
    - Are in the registry (have primary assignment)
    - Are not already in any library file

    Args:
        plan_content: Content of plan.md
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        apply: If True, write changes; otherwise dry-run

    Returns:
        MergingResult with planned/applied actions
    """
    result = MergingResult(dry_run=not apply)
    extractor = SectionExtractor()

    # Extract sections from plan
    plan_result = extractor.extract(plan_content)

    # Get existing IDs in libraries
    library_results = extractor.extract_from_directory(libraries_dir)
    existing_ids: set[str] = set()
    for lib_result in library_results.values():
        existing_ids.update(lib_result.sections.keys())

    # Group sections by target library
    to_add: dict[str, list[Section]] = {}

    for id_value, section in plan_result.sections.items():
        # Skip if not in registry
        if id_value not in registry.entries:
            continue

        # Skip if already exists
        if id_value in existing_ids:
            continue

        target = registry.get_primary(id_value)
        if target:
            to_add.setdefault(target, []).append(section)
            result.actions_planned.append(
                MergeAction(
                    action_type="extract",
                    id_value=id_value,
                    source_file="plan.md",
                    target_file=f"{target}.md",
                    description=f"Extract {id_value} to {target}",
                )
            )

    if apply:
        for lib_name, sections in to_add.items():
            lib_file = libraries_dir / f"{lib_name}.md"

            # Read existing content
            if lib_file.exists():
                existing = lib_file.read_text(encoding="utf-8")
            else:
                existing = ""

            # Append new sections
            new_content = existing.rstrip()
            for section in sections:
                new_content += "\n\n---\n\n" + section.full_content
            new_content += "\n"

            lib_file.write_text(new_content, encoding="utf-8")
            result.actions_applied.extend(
                [a for a in result.actions_planned if a.target_file == f"{lib_name}.md"]
            )

    return result


def move_to_correct_library(
    registry: LibsRegistry,
    libraries_dir: Path,
    apply: bool = False,
) -> MergingResult:
    """
    Move sections to their correct primary library.

    Args:
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        apply: If True, write changes; otherwise dry-run

    Returns:
        MergingResult with planned/applied actions
    """
    result = MergingResult(dry_run=not apply)
    extractor = SectionExtractor()

    # Extract sections from all libraries
    library_results = extractor.extract_from_directory(libraries_dir)

    # Find misplaced sections
    to_move: list[tuple[str, str, str, Section]] = []  # (id, from_lib, to_lib, section)

    for lib_name, lib_result in library_results.items():
        for id_value, section in lib_result.sections.items():
            if id_value not in registry.entries:
                continue

            expected = registry.get_primary(id_value)
            if expected and expected != lib_name:
                to_move.append((id_value, lib_name, expected, section))
                result.actions_planned.append(
                    MergeAction(
                        action_type="move",
                        id_value=id_value,
                        source_file=f"{lib_name}.md",
                        target_file=f"{expected}.md",
                        description=f"Move {id_value} from {lib_name} to {expected}",
                    )
                )

    if apply and to_move:
        # Group by source and target
        removals: dict[str, list[str]] = {}  # lib -> IDs to remove
        additions: dict[str, list[Section]] = {}  # lib -> sections to add

        for id_value, from_lib, to_lib, section in to_move:
            removals.setdefault(from_lib, []).append(id_value)
            additions.setdefault(to_lib, []).append(section)

        # Apply removals
        for lib_name, ids_to_remove in removals.items():
            lib_file = libraries_dir / f"{lib_name}.md"
            lib_result = library_results[lib_name]

            # Rebuild without removed IDs
            remaining_sections = {
                k: v for k, v in lib_result.sections.items() if k not in ids_to_remove
            }
            new_content = extractor.rebuild_content(remaining_sections)
            lib_file.write_text(new_content, encoding="utf-8")

        # Apply additions
        for lib_name, sections in additions.items():
            lib_file = libraries_dir / f"{lib_name}.md"

            if lib_file.exists():
                existing = lib_file.read_text(encoding="utf-8")
            else:
                existing = ""

            new_content = existing.rstrip()
            for section in sections:
                new_content += "\n\n---\n\n" + section.full_content
            new_content += "\n"

            lib_file.write_text(new_content, encoding="utf-8")

        result.actions_applied = result.actions_planned.copy()

    return result


def fix_duplicates(
    registry: LibsRegistry,
    libraries_dir: Path,
    apply: bool = False,
) -> MergingResult:
    """
    Remove duplicate sections, keeping only the primary library entry.

    Args:
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        apply: If True, write changes; otherwise dry-run

    Returns:
        MergingResult with planned/applied actions
    """
    result = MergingResult(dry_run=not apply)
    extractor = SectionExtractor()

    # Collect all ID locations
    id_locations = extractor.collect_all_ids(libraries_dir)

    # Find duplicates to remove
    to_remove: dict[str, list[str]] = {}  # lib -> IDs to remove

    for id_value, locations in id_locations.items():
        if len(locations) <= 1:
            continue

        primary = registry.get_primary(id_value)
        if not primary:
            continue

        # Remove from all non-primary libraries
        for lib_name, _ in locations:
            if lib_name != primary:
                to_remove.setdefault(lib_name, []).append(id_value)
                result.actions_planned.append(
                    MergeAction(
                        action_type="remove",
                        id_value=id_value,
                        source_file=f"{lib_name}.md",
                        description=f"Remove duplicate {id_value} from {lib_name} (primary: {primary})",
                    )
                )

    if apply and to_remove:
        library_results = extractor.extract_from_directory(libraries_dir)

        for lib_name, ids_to_remove in to_remove.items():
            lib_file = libraries_dir / f"{lib_name}.md"
            lib_result = library_results.get(lib_name)

            if not lib_result:
                continue

            # Rebuild without removed IDs
            remaining_sections = {
                k: v for k, v in lib_result.sections.items() if k not in ids_to_remove
            }
            new_content = extractor.rebuild_content(remaining_sections)
            lib_file.write_text(new_content, encoding="utf-8")

        result.actions_applied = result.actions_planned.copy()

    return result


def sort_by_id(
    libraries_dir: Path,
    apply: bool = False,
) -> MergingResult:
    """
    Sort sections within each library file by ID.

    Args:
        libraries_dir: Path to libraries directory
        apply: If True, write changes; otherwise dry-run

    Returns:
        MergingResult with planned/applied actions
    """
    result = MergingResult(dry_run=not apply)
    extractor = SectionExtractor()

    for lib_file in sorted(libraries_dir.glob("*.md")):
        lib_name = lib_file.stem
        lib_result = extractor.extract_from_file(lib_file)

        if not lib_result.sections:
            continue

        # Check if already sorted
        current_order = list(lib_result.sections.keys())
        sorted_order = sorted(
            current_order,
            key=lambda x: extractor.validator.sort_key(x),
        )

        if current_order == sorted_order:
            continue

        result.actions_planned.append(
            MergeAction(
                action_type="sort",
                source_file=f"{lib_name}.md",
                description=f"Sort {len(lib_result.sections)} sections in {lib_name}",
            )
        )

        if apply:
            new_content = extractor.rebuild_content(lib_result.sections, sort_by_id=True)
            lib_file.write_text(new_content, encoding="utf-8")
            result.actions_applied.append(result.actions_planned[-1])

    return result


def run_merging(
    plan_content: str,
    registry: LibsRegistry,
    libraries_dir: Path,
    apply: bool = False,
) -> MergingResult:
    """
    Run all merging operations in correct order.

    Order:
    1. Extract new sections from plan
    2. Move misplaced sections
    3. Fix duplicates
    4. Sort libraries

    Args:
        plan_content: Content of plan.md
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        apply: If True, write changes; otherwise dry-run

    Returns:
        Combined MergingResult
    """
    combined = MergingResult(dry_run=not apply)

    # Run operations in order
    operations = [
        ("extract", lambda: extract_to_libraries(plan_content, registry, libraries_dir, apply)),
        ("move", lambda: move_to_correct_library(registry, libraries_dir, apply)),
        ("dedupe", lambda: fix_duplicates(registry, libraries_dir, apply)),
        ("sort", lambda: sort_by_id(libraries_dir, apply)),
    ]

    for op_name, op_func in operations:
        result = op_func()
        combined.actions_planned.extend(result.actions_planned)
        combined.actions_applied.extend(result.actions_applied)
        combined.errors.extend(result.errors)

    return combined

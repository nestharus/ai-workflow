"""Restructuring resolution operations.

Actually applies restructuring suggestions to make libraries consistent:
- Merge: Combine two libraries into one
- Split: Extract IDs from a library into a new one
- Move IDs: Relocate IDs between libraries

Updates both library files and libs.md registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_manager.analysis.operations import RestructuringSuggestion
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.sections import Section, SectionExtractor


def _cleanup_stale_references(content: str, deleted_lib: str) -> str:
    """Clean explicit markdown links to a deleted library.

    This only transforms machine-readable markdown links and leaves natural
    language mentions untouched to avoid accidental data loss.
    """
    escaped_lib = re.escape(deleted_lib)
    link_pattern = re.compile(rf"\[([^\]]+)\]\((?:[^)]+/)?{escaped_lib}\.md(?:#[^)]+)?\)")
    return link_pattern.sub(r"\1", content)


def _create_backup(path: Path) -> Path:
    """Create an additive backup copy before mutating or deleting a file."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = path.parent / ".restructure_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"{path.name}.{timestamp}.bak"
    counter = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{path.name}.{timestamp}.{counter}.bak"
        counter += 1

    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


@dataclass
class ResolutionAction:
    """A resolved restructuring action with details of what was done."""

    action: str
    success: bool
    description: str
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "success": self.success,
            "description": self.description,
            "files_modified": self.files_modified,
            "files_created": self.files_created,
            "files_deleted": self.files_deleted,
            "error": self.error,
        }


@dataclass
class ResolutionResult:
    """Result of resolving all restructuring suggestions."""

    actions: list[ResolutionAction] = field(default_factory=list)
    total_applied: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    registry_updated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "total_applied": self.total_applied,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "registry_updated": self.registry_updated,
        }


def resolve_merge(
    lib1: str,
    lib2: str,
    libraries_dir: Path,
    registry: LibsRegistry,
) -> ResolutionAction:
    """Merge two libraries into one.

    The smaller library is merged into the larger one.
    All sections from the smaller are appended to the larger.
    Registry is updated to point to the merged library.

    Args:
        lib1: First library name (without .md)
        lib2: Second library name (without .md)
        libraries_dir: Path to libraries directory
        registry: The libs.md registry to update

    Returns:
        ResolutionAction with result
    """
    lib1_path = libraries_dir / f"{lib1}.md"
    lib2_path = libraries_dir / f"{lib2}.md"

    if not lib1_path.exists():
        return ResolutionAction(
            action="merge",
            success=False,
            description=f"Merge {lib1} and {lib2}",
            error=f"Library not found: {lib1_path}",
        )

    if not lib2_path.exists():
        return ResolutionAction(
            action="merge",
            success=False,
            description=f"Merge {lib1} and {lib2}",
            error=f"Library not found: {lib2_path}",
        )

    extractor = SectionExtractor()

    # Extract sections from both
    result1 = extractor.extract(lib1_path.read_text(encoding="utf-8"))
    result2 = extractor.extract(lib2_path.read_text(encoding="utf-8"))

    # Merge smaller into larger
    if len(result1.sections) >= len(result2.sections):
        target_lib, source_lib = lib1, lib2
        target_path, source_path = lib1_path, lib2_path
        target_result, source_result = result1, result2
    else:
        target_lib, source_lib = lib2, lib1
        target_path, source_path = lib2_path, lib1_path
        target_result, source_result = result2, result1

    # Append source sections to target
    target_content = target_path.read_text(encoding="utf-8").rstrip()

    # Strip trailing separators from target
    while target_content.endswith("---"):
        target_content = target_content[:-3].rstrip()

    # Add sections from source that don't already exist in target
    # This prevents duplicates when merging
    sections_added = 0
    for section in source_result.sections.values():
        section_id = section.id_value
        if section_id in target_result.sections:
            # Section already exists in target, skip to avoid duplicates
            continue
        sections_added += 1
        target_content += "\n\n---\n\n"
        # Strip trailing separator from section content
        section_content = section.full_content.rstrip()
        while section_content.endswith("---"):
            section_content = section_content[:-3].rstrip()
        target_content += section_content

    # Add final separator
    target_content += "\n\n---\n"

    # Clean up any references to the deleted source library
    target_content = _cleanup_stale_references(target_content, source_lib)

    target_backup = _create_backup(target_path)
    source_backup = _create_backup(source_path)

    # Write merged content
    target_path.write_text(target_content, encoding="utf-8")

    # Update registry: change all source_lib primaries to target_lib
    ids_moved = []
    for entry in registry.iter_entries():
        if entry.primary == source_lib:
            registry.move_entry(entry.id_value, target_lib)
            ids_moved.append(entry.id_value)

    # Delete source file
    source_path.unlink()

    return ResolutionAction(
        action="merge",
        success=True,
        description=(
            f"Merged {source_lib} ({len(source_result.sections)} sections) into {target_lib}"
        ),
        files_modified=[str(target_path)],
        files_created=[str(target_backup), str(source_backup)],
        files_deleted=[str(source_path)],
    )


def resolve_split(
    library: str,
    new_library: str,
    ids_to_move: list[str],
    libraries_dir: Path,
    registry: LibsRegistry,
) -> ResolutionAction:
    """Split a library by extracting IDs into a new library.

    Args:
        library: Source library name (without .md)
        new_library: New library name to create (without .md)
        ids_to_move: List of IDs to move to the new library
        libraries_dir: Path to libraries directory
        registry: The libs.md registry to update

    Returns:
        ResolutionAction with result
    """
    source_path = libraries_dir / f"{library}.md"
    new_path = libraries_dir / f"{new_library}.md"

    if not source_path.exists():
        return ResolutionAction(
            action="split",
            success=False,
            description=f"Split {library} -> {new_library}",
            error=f"Library not found: {source_path}",
        )

    if new_path.exists():
        return ResolutionAction(
            action="split",
            success=False,
            description=f"Split {library} -> {new_library}",
            error=f"Target library already exists: {new_path}",
        )

    extractor = SectionExtractor()
    result = extractor.extract(source_path.read_text(encoding="utf-8"))

    # Partition sections
    sections_to_move: dict[str, Section] = {}
    sections_to_keep: dict[str, Section] = {}

    for id_value, section in result.sections.items():
        if id_value in ids_to_move:
            sections_to_move[id_value] = section
        else:
            sections_to_keep[id_value] = section

    if not sections_to_move:
        return ResolutionAction(
            action="split",
            success=False,
            description=f"Split {library} -> {new_library}",
            error="No matching sections found to move",
        )

    # Build new library content
    new_content = f"# {new_library.replace('_', ' ').title()}\n\n"
    new_content += f"Split from {library}.\n\n"
    new_content += "---\n\n"

    for section in sections_to_move.values():
        new_content += section.full_content
        new_content += "\n\n---\n\n"

    # Rebuild source library without moved sections
    source_lines = source_path.read_text(encoding="utf-8").split("\n")
    kept_content = []
    skip_until_separator = False

    for line in source_lines:
        # Detect section start
        if line.strip().startswith("### "):
            # Check if this section should be skipped
            for id_value in sections_to_move:
                if f"([={id_value}])" in line or f"[={id_value}]" in line:
                    skip_until_separator = True
                    break
            else:
                skip_until_separator = False
                kept_content.append(line)
        elif line.strip() == "---":
            if skip_until_separator:
                skip_until_separator = False
            else:
                kept_content.append(line)
        elif not skip_until_separator:
            kept_content.append(line)

    # Write files
    source_backup = _create_backup(source_path)
    new_path.write_text(new_content.rstrip() + "\n", encoding="utf-8")
    source_path.write_text("\n".join(kept_content).rstrip() + "\n", encoding="utf-8")

    # Update registry
    for id_value in sections_to_move:
        registry.move_entry(id_value, new_library)

    return ResolutionAction(
        action="split",
        success=True,
        description=f"Split {len(sections_to_move)} sections from {library} into {new_library}",
        files_modified=[str(source_path)],
        files_created=[str(new_path), str(source_backup)],
    )


def resolve_move_ids(
    source_lib: str,
    target_lib: str,
    ids_to_move: list[str],
    libraries_dir: Path,
    registry: LibsRegistry,
) -> ResolutionAction:
    """Move specific IDs from one library to another.

    Args:
        source_lib: Source library name (without .md)
        target_lib: Target library name (without .md)
        ids_to_move: List of IDs to move
        libraries_dir: Path to libraries directory
        registry: The libs.md registry to update

    Returns:
        ResolutionAction with result
    """
    source_path = libraries_dir / f"{source_lib}.md"
    target_path = libraries_dir / f"{target_lib}.md"

    if not source_path.exists():
        return ResolutionAction(
            action="move_ids",
            success=False,
            description=f"Move IDs from {source_lib} to {target_lib}",
            error=f"Source library not found: {source_path}",
        )

    if not target_path.exists():
        return ResolutionAction(
            action="move_ids",
            success=False,
            description=f"Move IDs from {source_lib} to {target_lib}",
            error=f"Target library not found: {target_path}",
        )

    extractor = SectionExtractor()
    source_result = extractor.extract(source_path.read_text(encoding="utf-8"))

    # Find sections to move
    sections_to_move: dict[str, Section] = {}
    for id_value in ids_to_move:
        if id_value in source_result.sections:
            sections_to_move[id_value] = source_result.sections[id_value]

    if not sections_to_move:
        return ResolutionAction(
            action="move_ids",
            success=False,
            description=f"Move IDs from {source_lib} to {target_lib}",
            error="No matching sections found to move",
        )

    # Append to target
    target_content = target_path.read_text(encoding="utf-8").rstrip()
    target_content += "\n\n---\n\n"

    for section in sections_to_move.values():
        target_content += section.full_content
        target_content += "\n\n---\n\n"

    # Remove from source (similar to split logic)
    source_lines = source_path.read_text(encoding="utf-8").split("\n")
    kept_content = []
    skip_until_separator = False

    for line in source_lines:
        if line.strip().startswith("### "):
            for id_value in sections_to_move:
                if f"([={id_value}])" in line or f"[={id_value}]" in line:
                    skip_until_separator = True
                    break
            else:
                skip_until_separator = False
                kept_content.append(line)
        elif line.strip() == "---":
            if skip_until_separator:
                skip_until_separator = False
            else:
                kept_content.append(line)
        elif not skip_until_separator:
            kept_content.append(line)

    # Write files
    source_backup = _create_backup(source_path)
    target_backup = _create_backup(target_path)
    target_path.write_text(target_content.rstrip() + "\n", encoding="utf-8")
    source_path.write_text("\n".join(kept_content).rstrip() + "\n", encoding="utf-8")

    # Update registry
    for id_value in sections_to_move:
        registry.move_entry(id_value, target_lib)

    return ResolutionAction(
        action="move_ids",
        success=True,
        description=f"Moved {len(sections_to_move)} IDs from {source_lib} to {target_lib}",
        files_modified=[str(source_path), str(target_path)],
        files_created=[str(source_backup), str(target_backup)],
    )


def _build_skipped_action(
    suggestion: RestructuringSuggestion,
    reason: str,
    *,
    dry_run: bool = False,
) -> ResolutionAction:
    """Build a structured skipped action for diagnosability."""
    mode_prefix = "[DRY RUN] " if dry_run else ""
    return ResolutionAction(
        action=suggestion.action,
        success=False,
        description=f"{mode_prefix}Skipped {suggestion.description}",
        error=reason,
    )


def resolve_suggestions(
    suggestions: list[RestructuringSuggestion],
    libraries_dir: Path,
    registry: LibsRegistry,
    min_confidence: float = 0.7,
    dry_run: bool = False,
) -> ResolutionResult:
    """Apply restructuring suggestions to achieve consistent state.

    Only applies suggestions above the confidence threshold.

    Args:
        suggestions: List of restructuring suggestions
        libraries_dir: Path to libraries directory
        registry: The libs.md registry to update
        min_confidence: Minimum confidence to auto-apply (default 0.7)
        dry_run: If True, don't actually modify files

    Returns:
        ResolutionResult with all actions taken
    """
    result = ResolutionResult()

    if dry_run:
        for suggestion in suggestions:
            if suggestion.confidence < min_confidence:
                result.actions.append(
                    _build_skipped_action(
                        suggestion,
                        (
                            f"confidence {suggestion.confidence:.2f} is below "
                            f"minimum {min_confidence:.2f}"
                        ),
                        dry_run=True,
                    )
                )
                result.total_skipped += 1
                continue

            result.actions.append(
                ResolutionAction(
                    action=suggestion.action,
                    success=True,
                    description=f"[DRY RUN] Would {suggestion.description}",
                )
            )
            result.total_applied += 1
        return result

    # Apply each suggestion
    for suggestion in suggestions:
        if suggestion.confidence < min_confidence:
            result.actions.append(
                _build_skipped_action(
                    suggestion,
                    (
                        f"confidence {suggestion.confidence:.2f} is below "
                        f"minimum {min_confidence:.2f}"
                    ),
                )
            )
            result.total_skipped += 1
            continue

        if suggestion.action == "merge" and suggestion.source_library and suggestion.target_library:
            action = resolve_merge(
                suggestion.source_library,
                suggestion.target_library,
                libraries_dir,
                registry,
            )
            result.actions.append(action)
            if action.success:
                result.total_applied += 1
            else:
                result.total_failed += 1

        elif (
            suggestion.action == "split"
            and suggestion.source_library
            and suggestion.new_library
            and suggestion.ids
        ):
            action = resolve_split(
                suggestion.source_library,
                suggestion.new_library,
                suggestion.ids,
                libraries_dir,
                registry,
            )
            result.actions.append(action)
            if action.success:
                result.total_applied += 1
            else:
                result.total_failed += 1

        elif (
            suggestion.action == "move_ids"
            and suggestion.source_library
            and suggestion.target_library
            and suggestion.ids
        ):
            action = resolve_move_ids(
                suggestion.source_library,
                suggestion.target_library,
                suggestion.ids,
                libraries_dir,
                registry,
            )
            result.actions.append(action)
            if action.success:
                result.total_applied += 1
            else:
                result.total_failed += 1
        else:
            result.actions.append(
                _build_skipped_action(
                    suggestion,
                    "unsupported action or missing required library fields",
                )
            )
            result.total_skipped += 1

    # Save updated registry if any changes were made
    if result.total_applied > 0:
        result.registry_updated = True

    return result

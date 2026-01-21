"""Verification operations for the FINALIZATION phase.

This module provides consistency checking and validation operations.
Legacy module name 'verification' maps to the FINALIZATION workflow phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.sections import SectionExtractor


@dataclass
class ContentMismatch:
    """A mismatch between plan and library content."""

    id_value: str
    library: str
    similarity: float  # 0.0 to 1.0
    plan_length: int
    library_length: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id_value,
            "library": self.library,
            "similarity": round(self.similarity, 2),
            "plan_length": self.plan_length,
            "library_length": self.library_length,
            "description": self.description,
        }


@dataclass
class DuplicateEntry:
    """A duplicate ID found across libraries."""

    id_value: str
    locations: list[tuple[str, int]]  # (library, line_number)
    expected_library: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id_value,
            "locations": [{"library": lib, "line": line} for lib, line in self.locations],
            "expected_library": self.expected_library,
        }


@dataclass
class EmptyStub:
    """A section with empty body."""

    id_value: str
    library: str
    has_plan_content: bool  # True if plan.md has content for this ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id_value,
            "library": self.library,
            "has_plan_content": self.has_plan_content,
        }


@dataclass
class AssignmentIssue:
    """An assignment issue (ID in wrong library)."""

    id_value: str
    expected_library: str
    actual_libraries: list[str]
    issue_type: str  # "wrong_library", "missing", "not_registered"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id_value,
            "expected_library": self.expected_library,
            "actual_libraries": self.actual_libraries,
            "issue_type": self.issue_type,
        }


@dataclass
class VerificationResult:
    """Result of verification operations."""

    content_mismatches: list[ContentMismatch] = field(default_factory=list)
    duplicates: list[DuplicateEntry] = field(default_factory=list)
    empty_stubs: list[EmptyStub] = field(default_factory=list)
    assignment_issues: list[AssignmentIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.duplicates) == 0 and len(self.assignment_issues) == 0

    @property
    def total_issues(self) -> int:
        return (
            len(self.content_mismatches)
            + len(self.duplicates)
            + len(self.empty_stubs)
            + len(self.assignment_issues)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "total_issues": self.total_issues,
            "content_mismatches": [m.to_dict() for m in self.content_mismatches],
            "duplicates": [d.to_dict() for d in self.duplicates],
            "empty_stubs": [s.to_dict() for s in self.empty_stubs],
            "assignment_issues": [a.to_dict() for a in self.assignment_issues],
        }


def verify_content(
    plan_content: str,
    libraries_dir: Path,
    min_similarity: float = 0.8,
) -> list[ContentMismatch]:
    """Compare library content against plan.md.

    Args:
        plan_content: Content of plan.md
        libraries_dir: Path to libraries directory
        min_similarity: Minimum similarity threshold (0.0 to 1.0)

    Returns:
        List of ContentMismatch for sections below threshold
    """
    mismatches: list[ContentMismatch] = []
    extractor = SectionExtractor()

    # Extract from plan
    plan_result = extractor.extract(plan_content)

    # Extract from libraries
    library_results = extractor.extract_from_directory(libraries_dir)

    # Compare each library section against plan
    for lib_name, lib_result in library_results.items():
        for id_value, lib_section in lib_result.sections.items():
            plan_section = plan_result.sections.get(id_value)

            if not plan_section:
                # Not in plan - might be intentional library-only content
                continue

            # Compare content
            plan_body = plan_section.body.strip()
            lib_body = lib_section.body.strip()

            if not plan_body and not lib_body:
                continue

            similarity = SequenceMatcher(None, plan_body, lib_body).ratio()

            if similarity < min_similarity:
                mismatches.append(
                    ContentMismatch(
                        id_value=id_value,
                        library=lib_name,
                        similarity=similarity,
                        plan_length=len(plan_body),
                        library_length=len(lib_body),
                        description=f"Content differs: {int(similarity * 100)}% similar",
                    )
                )

    return mismatches


def detect_duplicates(
    libraries_dir: Path,
    registry: LibsRegistry | None = None,
) -> list[DuplicateEntry]:
    """Find IDs that appear in multiple library files.

    Args:
        libraries_dir: Path to libraries directory
        registry: Optional registry for expected library lookup

    Returns:
        List of DuplicateEntry for duplicated IDs
    """
    duplicates: list[DuplicateEntry] = []
    extractor = SectionExtractor()

    # Collect all ID locations
    id_locations = extractor.collect_all_ids(libraries_dir)

    for id_value, locations in id_locations.items():
        if len(locations) > 1:
            expected = registry.get_primary(id_value) if registry else None
            duplicates.append(
                DuplicateEntry(
                    id_value=id_value,
                    locations=locations,
                    expected_library=expected,
                )
            )

    return duplicates


def find_empty_stubs(
    plan_content: str,
    libraries_dir: Path,
) -> list[EmptyStub]:
    """Find library sections with empty bodies.

    Args:
        plan_content: Content of plan.md
        libraries_dir: Path to libraries directory

    Returns:
        List of EmptyStub for sections with no body content
    """
    stubs: list[EmptyStub] = []
    extractor = SectionExtractor()

    # Extract from plan
    plan_result = extractor.extract(plan_content)

    # Extract from libraries
    library_results = extractor.extract_from_directory(libraries_dir)

    for lib_name, lib_result in library_results.items():
        for id_value, section in lib_result.sections.items():
            if section.is_empty:
                has_plan_content = (
                    id_value in plan_result.sections and not plan_result.sections[id_value].is_empty
                )
                stubs.append(
                    EmptyStub(
                        id_value=id_value,
                        library=lib_name,
                        has_plan_content=has_plan_content,
                    )
                )

    return stubs


def verify_assignments(
    registry: LibsRegistry,
    libraries_dir: Path,
) -> list[AssignmentIssue]:
    """Verify all IDs are in their correct libraries per registry.

    Checks:
    - IDs in registry are in their primary library
    - IDs in libraries are registered
    - No IDs appear in wrong libraries

    Args:
        registry: The libs.md registry
        libraries_dir: Path to libraries directory

    Returns:
        List of AssignmentIssue for any problems found
    """
    issues: list[AssignmentIssue] = []
    extractor = SectionExtractor()

    # Get library contents
    library_results = extractor.extract_from_directory(libraries_dir)

    # Build maps
    library_ids: dict[str, set[str]] = {}
    for lib_name, lib_result in library_results.items():
        library_ids[lib_name] = set(lib_result.sections.keys())

    all_lib_ids: set[str] = set()
    for ids in library_ids.values():
        all_lib_ids.update(ids)

    # Check each registry entry
    for id_value, entry in registry.entries.items():
        expected = entry.primary

        # Check if ID exists in any library
        if id_value not in all_lib_ids:
            issues.append(
                AssignmentIssue(
                    id_value=id_value,
                    expected_library=expected,
                    actual_libraries=[],
                    issue_type="missing",
                )
            )
            continue

        # Check if ID is in correct library
        actual_libs = [lib for lib, ids in library_ids.items() if id_value in ids]

        if expected not in actual_libs:
            issues.append(
                AssignmentIssue(
                    id_value=id_value,
                    expected_library=expected,
                    actual_libraries=actual_libs,
                    issue_type="wrong_library",
                )
            )

    # Check for unregistered IDs in libraries
    registry_ids = set(registry.entries.keys())
    for lib_name, ids in library_ids.items():
        for id_value in ids:
            if id_value not in registry_ids:
                issues.append(
                    AssignmentIssue(
                        id_value=id_value,
                        expected_library="unknown",
                        actual_libraries=[lib_name],
                        issue_type="not_registered",
                    )
                )

    return issues


def run_verification(
    plan_content: str,
    registry: LibsRegistry,
    libraries_dir: Path,
    min_similarity: float = 0.8,
) -> VerificationResult:
    """Run all verification operations.

    Args:
        plan_content: Content of plan.md
        registry: The libs.md registry
        libraries_dir: Path to libraries directory
        min_similarity: Minimum similarity threshold for content comparison

    Returns:
        VerificationResult with all findings
    """
    result = VerificationResult()

    result.content_mismatches = verify_content(plan_content, libraries_dir, min_similarity)
    result.duplicates = detect_duplicates(libraries_dir, registry)
    result.empty_stubs = find_empty_stubs(plan_content, libraries_dir)
    result.assignment_issues = verify_assignments(registry, libraries_dir)

    return result

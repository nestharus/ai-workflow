"""Citation migration from legacy formats to EVID-only (CON-0021).

This module provides functions to migrate legacy citation formats like
[F####::SECTION] and [spec_snapshot/<relpath>::SEC-...] to canonical
EVID citations [EVID-F####-R####-L#-L#].

The migration process:
1. Parse legacy citation format
2. Look up section in evidence index
3. Find covering EVID range(s) for the section
4. Replace citation with EVID reference(s)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from spec_manager.schemas.evid_citation import format_evid_citation
from spec_manager.schemas.evidence_ranges import EvidenceRange

# Legacy citation patterns
LEGACY_FILE_POINTER_RE = re.compile(r"\[F(\d{4})::([^\]]+)\]")
SPEC_SNAPSHOT_POINTER_RE = re.compile(r"\[spec_snapshot/([^:]+)::(SEC-F\d{4}-\d{4})\]")


@dataclass
class MigrationIssue:
    """Record of a citation that could not be migrated.

    Attributes:
        citation: Original citation text
        reason: Why migration failed
        line: Line number where citation appeared (optional)
    """

    citation: str
    reason: str
    line: int | None = None


@dataclass
class EvidenceIndex:
    """Index for looking up EVID ranges by section.

    Attributes:
        by_file_section: Mapping of (file_uid, section_id) -> list of EVID strings
        by_section: Mapping of section_id -> list of EVID strings (cross-file)
    """

    by_file_section: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    by_section: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def build_from_ranges(cls, ranges: list[EvidenceRange]) -> "EvidenceIndex":
        """Build an index from a list of EvidenceRange objects.

        Args:
            ranges: List of EvidenceRange objects

        Returns:
            EvidenceIndex for fast lookups
        """
        index = cls()
        for evr in ranges:
            if evr.section_id:
                key = (evr.file_uid, evr.section_id)
                index.by_file_section.setdefault(key, []).append(evr.evidence_id)
                index.by_section.setdefault(evr.section_id, []).append(evr.evidence_id)
        return index


def resolve_section_to_evid_ranges(
    file_uid: str,
    section_id: str,
    evidence_index: EvidenceIndex,
) -> list[str]:
    """Map a section ID to its covering EVID range(s).

    Args:
        file_uid: File UID (e.g., F0001)
        section_id: Section ID (e.g., SEC-F0001-0001)
        evidence_index: Index for looking up EVID ranges

    Returns:
        List of EVID strings covering the section
    """
    # Try file-specific lookup first
    key = (file_uid, section_id)
    if key in evidence_index.by_file_section:
        return evidence_index.by_file_section[key]

    # Fall back to cross-file lookup
    if section_id in evidence_index.by_section:
        return evidence_index.by_section[section_id]

    return []


def migrate_legacy_citation(
    citation: str,
    file_manifest: dict[str, dict[str, str]],
    section_alias_map: dict[str, str] | None,
    evidence_index: EvidenceIndex,
) -> tuple[list[str], MigrationIssue | None]:
    """Convert legacy [F####::SECTION] to [EVID-...] format.

    Args:
        citation: Legacy citation string (e.g., '[F0001::INTRO]')
        file_manifest: Mapping of file_uid -> file metadata
        section_alias_map: Mapping of section aliases to canonical section IDs
        evidence_index: Index for looking up EVID ranges

    Returns:
        Tuple of (list of EVID citations, optional MigrationIssue if failed)
    """
    match = LEGACY_FILE_POINTER_RE.fullmatch(citation)
    if not match:
        return [], MigrationIssue(
            citation=citation,
            reason="Not a valid legacy citation format",
        )

    file_uid = f"F{match.group(1)}"
    section_label = match.group(2).strip()

    # Check file exists in manifest
    if file_uid not in file_manifest:
        return [], MigrationIssue(
            citation=citation,
            reason=f"File {file_uid} not found in manifest",
        )

    # Try to resolve section label to canonical section ID
    section_id = section_label
    if section_alias_map and section_label in section_alias_map:
        section_id = section_alias_map[section_label]

    # Look up EVID ranges
    evid_ranges = resolve_section_to_evid_ranges(file_uid, section_id, evidence_index)
    if not evid_ranges:
        # Try with normalized section label
        normalized = section_label.strip().lower().replace(" ", "_").replace("-", "_")
        if section_alias_map and normalized in section_alias_map:
            section_id = section_alias_map[normalized]
            evid_ranges = resolve_section_to_evid_ranges(file_uid, section_id, evidence_index)

    if not evid_ranges:
        return [], MigrationIssue(
            citation=citation,
            reason=f"No EVID range found for section '{section_label}' in {file_uid}",
        )

    return [format_evid_citation(evid) for evid in evid_ranges], None


def migrate_spec_snapshot_citation(
    citation: str,
    evidence_index: EvidenceIndex,
) -> tuple[list[str], MigrationIssue | None]:
    """Convert [spec_snapshot/<relpath>::SEC-...] to [EVID-...] format.

    Args:
        citation: Spec snapshot citation string
        evidence_index: Index for looking up EVID ranges

    Returns:
        Tuple of (list of EVID citations, optional MigrationIssue if failed)
    """
    match = SPEC_SNAPSHOT_POINTER_RE.fullmatch(citation)
    if not match:
        return [], MigrationIssue(
            citation=citation,
            reason="Not a valid spec_snapshot citation format",
        )

    # relpath = match.group(1)  # Not used for lookup currently
    section_id = match.group(2)

    # Extract file_uid from section_id (SEC-F####-####)
    section_match = re.match(r"SEC-(F\d{4})-\d{4}", section_id)
    if not section_match:
        return [], MigrationIssue(
            citation=citation,
            reason=f"Invalid section ID format: {section_id}",
        )

    file_uid = section_match.group(1)

    # Look up EVID ranges
    evid_ranges = resolve_section_to_evid_ranges(file_uid, section_id, evidence_index)
    if not evid_ranges:
        return [], MigrationIssue(
            citation=citation,
            reason=f"No EVID range found for section '{section_id}'",
        )

    return [format_evid_citation(evid) for evid in evid_ranges], None


def migrate_document_citations(
    content: str,
    evidence_index: EvidenceIndex,
    file_manifest: dict[str, dict[str, str]] | None = None,
    section_alias_map: dict[str, str] | None = None,
) -> tuple[str, list[MigrationIssue]]:
    """Migrate all citations in a document to EVID format.

    Args:
        content: Document content with citations
        evidence_index: Index for looking up EVID ranges
        file_manifest: Optional mapping of file_uid -> file metadata
        section_alias_map: Optional mapping of section aliases to canonical IDs

    Returns:
        Tuple of (migrated content, list of MigrationIssue for unmapped citations)
    """
    if not content:
        return content, []

    issues: list[MigrationIssue] = []
    file_manifest = file_manifest or {}

    def _replace_legacy(match: re.Match[str]) -> str:
        citation = match.group(0)
        migrated, issue = migrate_legacy_citation(
            citation, file_manifest, section_alias_map, evidence_index
        )
        if issue:
            issues.append(issue)
            return citation  # Keep original on failure
        return " ".join(migrated)

    def _replace_spec_snapshot(match: re.Match[str]) -> str:
        citation = match.group(0)
        migrated, issue = migrate_spec_snapshot_citation(citation, evidence_index)
        if issue:
            issues.append(issue)
            return citation  # Keep original on failure
        return " ".join(migrated)

    # Migrate legacy citations first
    migrated = LEGACY_FILE_POINTER_RE.sub(_replace_legacy, content)

    # Then migrate spec_snapshot citations
    migrated = SPEC_SNAPSHOT_POINTER_RE.sub(_replace_spec_snapshot, migrated)

    return migrated, issues


def detect_legacy_citations(content: str) -> list[tuple[str, str, int | None]]:
    """Detect legacy citations in content without migrating.

    Args:
        content: Document content to scan

    Returns:
        List of (citation, format_type, line_number) tuples
    """
    citations: list[tuple[str, str, int | None]] = []

    for line_no, line in enumerate(content.splitlines(), start=1):
        for match in LEGACY_FILE_POINTER_RE.finditer(line):
            citations.append((match.group(0), "legacy_file_pointer", line_no))
        for match in SPEC_SNAPSHOT_POINTER_RE.finditer(line):
            citations.append((match.group(0), "spec_snapshot_pointer", line_no))

    return citations

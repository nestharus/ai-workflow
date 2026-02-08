"""Tests for citation migration from legacy formats to EVID-only (CON-0021).

Tests:
- test_resolve_section_to_evid_ranges: Section lookup in evidence index
- test_migrate_legacy_citation: [F####::SECTION] migration
- test_migrate_spec_snapshot_citation: [spec_snapshot/...::SEC-...] migration
- test_migrate_document_citations: Full document migration
- test_detect_legacy_citations: Detection without migration
"""

import pytest
from spec_manager.refinement.workflows.citation_migrator import (
    EvidenceIndex,
    detect_legacy_citations,
    migrate_document_citations,
    migrate_legacy_citation,
    migrate_spec_snapshot_citation,
    resolve_section_to_evid_ranges,
)
from spec_manager.schemas.evidence_ranges import EvidenceRange


@pytest.fixture
def sample_evidence_ranges() -> list[EvidenceRange]:
    """Create sample evidence ranges for testing."""
    return [
        EvidenceRange(
            evidence_id="EVID-F0001-R0001-L1-L10",
            file_uid="F0001",
            rev_id="R0001",
            start_line=1,
            end_line=10,
            atom_ids=[f"ATOM-F0001-R0001-L{i:04d}" for i in range(1, 11)],
            section_id="SEC-F0001-0001",
            label="Introduction",
        ),
        EvidenceRange(
            evidence_id="EVID-F0001-R0001-L11-L25",
            file_uid="F0001",
            rev_id="R0001",
            start_line=11,
            end_line=25,
            atom_ids=[f"ATOM-F0001-R0001-L{i:04d}" for i in range(11, 26)],
            section_id="SEC-F0001-0002",
            label="Requirements",
        ),
        EvidenceRange(
            evidence_id="EVID-F0002-R0001-L1-L15",
            file_uid="F0002",
            rev_id="R0001",
            start_line=1,
            end_line=15,
            atom_ids=[f"ATOM-F0002-R0001-L{i:04d}" for i in range(1, 16)],
            section_id="SEC-F0002-0001",
            label="Overview",
        ),
    ]


@pytest.fixture
def evidence_index(sample_evidence_ranges: list[EvidenceRange]) -> EvidenceIndex:
    """Build evidence index from sample ranges."""
    return EvidenceIndex.build_from_ranges(sample_evidence_ranges)


@pytest.fixture
def file_manifest() -> dict[str, dict[str, str]]:
    """Create sample file manifest."""
    return {
        "F0001": {"relpath": "requirements/core.md", "rev_id": "R0001"},
        "F0002": {"relpath": "design/overview.md", "rev_id": "R0001"},
    }


@pytest.fixture
def section_alias_map() -> dict[str, str]:
    """Create sample section alias mapping."""
    return {
        "INTRO": "SEC-F0001-0001",
        "REQUIREMENTS": "SEC-F0001-0002",
        "introduction": "SEC-F0001-0001",
        "intro": "SEC-F0001-0001",
    }


class TestEvidenceIndex:
    """Test EvidenceIndex building and lookups."""

    def test_build_from_ranges(self, sample_evidence_ranges: list[EvidenceRange]) -> None:
        """Test building index from ranges."""
        index = EvidenceIndex.build_from_ranges(sample_evidence_ranges)

        # Check by_file_section
        assert ("F0001", "SEC-F0001-0001") in index.by_file_section
        assert index.by_file_section[("F0001", "SEC-F0001-0001")] == ["EVID-F0001-R0001-L1-L10"]

        # Check by_section
        assert "SEC-F0001-0001" in index.by_section
        assert "SEC-F0002-0001" in index.by_section

    def test_build_empty_ranges(self) -> None:
        """Test building index from empty list."""
        index = EvidenceIndex.build_from_ranges([])
        assert len(index.by_file_section) == 0
        assert len(index.by_section) == 0


class TestResolveSectionToEvidRanges:
    """Test section to EVID range resolution."""

    def test_resolve_existing_section(self, evidence_index: EvidenceIndex) -> None:
        """Test resolving a section that exists."""
        evids = resolve_section_to_evid_ranges("F0001", "SEC-F0001-0001", evidence_index)
        assert evids == ["EVID-F0001-R0001-L1-L10"]

    def test_resolve_nonexistent_section(self, evidence_index: EvidenceIndex) -> None:
        """Test resolving a section that doesn't exist."""
        evids = resolve_section_to_evid_ranges("F0001", "SEC-F0001-9999", evidence_index)
        assert evids == []

    def test_resolve_cross_file(self, evidence_index: EvidenceIndex) -> None:
        """Test cross-file section lookup."""
        evids = resolve_section_to_evid_ranges("F9999", "SEC-F0002-0001", evidence_index)
        assert evids == ["EVID-F0002-R0001-L1-L15"]


class TestMigrateLegacyCitation:
    """Test legacy [F####::SECTION] citation migration."""

    def test_migrate_valid_citation(
        self,
        evidence_index: EvidenceIndex,
        file_manifest: dict[str, dict[str, str]],
        section_alias_map: dict[str, str],
    ) -> None:
        """Test migrating a valid legacy citation."""
        migrated, issue = migrate_legacy_citation(
            "[F0001::INTRO]", file_manifest, section_alias_map, evidence_index
        )
        assert issue is None
        assert migrated == ["[EVID-F0001-R0001-L1-L10]"]

    def test_migrate_with_section_id_directly(
        self,
        evidence_index: EvidenceIndex,
        file_manifest: dict[str, dict[str, str]],
    ) -> None:
        """Test migration when section_id is used directly."""
        migrated, issue = migrate_legacy_citation(
            "[F0001::SEC-F0001-0002]", file_manifest, None, evidence_index
        )
        assert issue is None
        assert migrated == ["[EVID-F0001-R0001-L11-L25]"]

    def test_migrate_unknown_file(
        self,
        evidence_index: EvidenceIndex,
        file_manifest: dict[str, dict[str, str]],
    ) -> None:
        """Test migration with unknown file ID."""
        migrated, issue = migrate_legacy_citation(
            "[F9999::INTRO]", file_manifest, None, evidence_index
        )
        assert migrated == []
        assert issue is not None
        assert "F9999 not found" in issue.reason

    def test_migrate_unknown_section(
        self,
        evidence_index: EvidenceIndex,
        file_manifest: dict[str, dict[str, str]],
    ) -> None:
        """Test migration with unknown section."""
        migrated, issue = migrate_legacy_citation(
            "[F0001::UNKNOWN_SECTION]", file_manifest, None, evidence_index
        )
        assert migrated == []
        assert issue is not None
        assert "No EVID range found" in issue.reason

    def test_invalid_citation_format(
        self,
        evidence_index: EvidenceIndex,
        file_manifest: dict[str, dict[str, str]],
    ) -> None:
        """Test with invalid citation format."""
        migrated, issue = migrate_legacy_citation(
            "not a citation", file_manifest, None, evidence_index
        )
        assert migrated == []
        assert issue is not None
        assert "Not a valid legacy citation" in issue.reason


class TestMigrateSpecSnapshotCitation:
    """Test [spec_snapshot/...::SEC-...] citation migration."""

    def test_migrate_valid_citation(self, evidence_index: EvidenceIndex) -> None:
        """Test migrating a valid spec_snapshot citation."""
        migrated, issue = migrate_spec_snapshot_citation(
            "[spec_snapshot/requirements/core.md::SEC-F0001-0001]", evidence_index
        )
        assert issue is None
        assert migrated == ["[EVID-F0001-R0001-L1-L10]"]

    def test_migrate_unknown_section(self, evidence_index: EvidenceIndex) -> None:
        """Test migration with unknown section."""
        migrated, issue = migrate_spec_snapshot_citation(
            "[spec_snapshot/file.md::SEC-F0001-9999]", evidence_index
        )
        assert migrated == []
        assert issue is not None
        assert "No EVID range found" in issue.reason

    def test_invalid_citation_format(self, evidence_index: EvidenceIndex) -> None:
        """Test with invalid citation format."""
        migrated, issue = migrate_spec_snapshot_citation("[F0001::INTRO]", evidence_index)
        assert migrated == []
        assert issue is not None
        assert "Not a valid spec_snapshot" in issue.reason


class TestMigrateDocumentCitations:
    """Test full document citation migration."""

    def test_migrate_document_with_legacy_citations(
        self,
        evidence_index: EvidenceIndex,
        file_manifest: dict[str, dict[str, str]],
        section_alias_map: dict[str, str],
    ) -> None:
        """Test migrating a document with legacy citations."""
        content = """
        # Document

        See [F0001::INTRO] for introduction.
        Also check [F0001::REQUIREMENTS] for details.
        """
        migrated, issues = migrate_document_citations(
            content, evidence_index, file_manifest, section_alias_map
        )

        assert len(issues) == 0
        assert "[EVID-F0001-R0001-L1-L10]" in migrated
        assert "[EVID-F0001-R0001-L11-L25]" in migrated
        assert "[F0001::INTRO]" not in migrated

    def test_migrate_document_with_spec_snapshot(self, evidence_index: EvidenceIndex) -> None:
        """Test migrating a document with spec_snapshot citations."""
        content = "Reference: [spec_snapshot/file.md::SEC-F0001-0001]"
        migrated, issues = migrate_document_citations(content, evidence_index)

        assert len(issues) == 0
        assert "[EVID-F0001-R0001-L1-L10]" in migrated

    def test_migrate_document_with_mixed_citations(
        self,
        evidence_index: EvidenceIndex,
        file_manifest: dict[str, dict[str, str]],
        section_alias_map: dict[str, str],
    ) -> None:
        """Test migrating a document with mixed citation formats."""
        content = """
        Legacy: [F0001::INTRO]
        Snapshot: [spec_snapshot/file.md::SEC-F0002-0001]
        Already EVID: [EVID-F0001-R0001-L1-L10]
        """
        migrated, issues = migrate_document_citations(
            content, evidence_index, file_manifest, section_alias_map
        )

        assert len(issues) == 0
        # Check legacy was migrated
        assert "[F0001::INTRO]" not in migrated
        # Check snapshot was migrated
        assert "[spec_snapshot/file.md::SEC-F0002-0001]" not in migrated
        # Check EVID citations are present
        assert "[EVID-F0001-R0001-L1-L10]" in migrated
        assert "[EVID-F0002-R0001-L1-L15]" in migrated

    def test_migrate_document_with_unmapped_citations(
        self, evidence_index: EvidenceIndex, file_manifest: dict[str, dict[str, str]]
    ) -> None:
        """Test that unmapped citations are preserved and reported."""
        content = "Unknown: [F0001::UNKNOWN_SECTION]"
        migrated, issues = migrate_document_citations(content, evidence_index, file_manifest)

        assert len(issues) == 1
        assert issues[0].citation == "[F0001::UNKNOWN_SECTION]"
        assert "No EVID range found" in issues[0].reason
        # Original citation preserved
        assert "[F0001::UNKNOWN_SECTION]" in migrated

    def test_migrate_empty_content(self, evidence_index: EvidenceIndex) -> None:
        """Test migrating empty content."""
        migrated, issues = migrate_document_citations("", evidence_index)
        assert migrated == ""
        assert len(issues) == 0


class TestDetectLegacyCitations:
    """Test legacy citation detection."""

    def test_detect_legacy_file_pointers(self) -> None:
        """Test detecting legacy file pointers."""
        content = """
        Line 1: [F0001::INTRO]
        Line 2: [F0002::SECTION_A]
        """
        citations = detect_legacy_citations(content)

        assert len(citations) == 2
        assert citations[0] == ("[F0001::INTRO]", "legacy_file_pointer", 2)
        assert citations[1] == ("[F0002::SECTION_A]", "legacy_file_pointer", 3)

    def test_detect_spec_snapshot_pointers(self) -> None:
        """Test detecting spec_snapshot pointers."""
        content = "See [spec_snapshot/file.md::SEC-F0001-0001] for details."
        citations = detect_legacy_citations(content)

        assert len(citations) == 1
        assert citations[0][0] == "[spec_snapshot/file.md::SEC-F0001-0001]"
        assert citations[0][1] == "spec_snapshot_pointer"

    def test_detect_mixed_formats(self) -> None:
        """Test detecting mixed citation formats."""
        content = """
        Legacy: [F0001::INTRO]
        Snapshot: [spec_snapshot/file.md::SEC-F0001-0001]
        EVID: [EVID-F0001-R0001-L1-L10]
        """
        citations = detect_legacy_citations(content)

        # Should detect legacy and snapshot, not EVID
        assert len(citations) == 2
        formats = [c[1] for c in citations]
        assert "legacy_file_pointer" in formats
        assert "spec_snapshot_pointer" in formats

    def test_detect_no_legacy(self) -> None:
        """Test with no legacy citations."""
        content = "Only EVID: [EVID-F0001-R0001-L1-L10]"
        citations = detect_legacy_citations(content)
        assert len(citations) == 0

    def test_detect_empty_content(self) -> None:
        """Test with empty content."""
        citations = detect_legacy_citations("")
        assert len(citations) == 0

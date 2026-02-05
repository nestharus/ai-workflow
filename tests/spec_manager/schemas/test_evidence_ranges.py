"""Tests for evidence ranges schema (DS-EVID-0003).

Tests:
- test_evidence_range_id_format: EVID-F0001-R0001-L1-L25 validates
- test_evidence_range_atom_ids_count_matches_lines: Validation enforced
- test_evidence_range_serialization_roundtrip: Model serialization
"""

import pytest
from pydantic import ValidationError

from spec_manager.schemas.evidence_ranges import (
    EVIDENCE_ID_PATTERN,
    EvidenceRange,
    EvidenceRangesArtifact,
)


class TestEvidenceIdPattern:
    """Test EVIDENCE_ID_PATTERN regex."""

    def test_valid_pattern(self) -> None:
        """Test valid evidence ID format."""
        match = EVIDENCE_ID_PATTERN.fullmatch("EVID-F0001-R0001-L1-L25")
        assert match is not None
        assert match.group("file_uid") == "F0001"
        assert match.group("rev_id") == "R0001"
        assert match.group("start") == "1"
        assert match.group("end") == "25"

    def test_invalid_patterns(self) -> None:
        """Test invalid evidence ID formats."""
        invalid_patterns = [
            "EVID-F001-R0001-L1-L25",  # Wrong file_uid format
            "EVID-F0001-R001-L1-L25",  # Wrong rev_id format
            "EVID-F0001-R0001-L1",  # Missing end line
            "evid-F0001-R0001-L1-L25",  # Wrong case
            "ATOM-F0001-R0001-L1-L25",  # Wrong prefix
        ]
        for pattern in invalid_patterns:
            assert EVIDENCE_ID_PATTERN.fullmatch(pattern) is None, f"Expected {pattern} to fail"


class TestEvidenceRange:
    """Test EvidenceRange model validation."""

    def test_valid_evidence_range(self) -> None:
        """Test valid evidence range creation."""
        evr = EvidenceRange(
            evidence_id="EVID-F0001-R0001-L1-L3",
            file_uid="F0001",
            rev_id="R0001",
            start_line=1,
            end_line=3,
            atom_ids=[
                "ATOM-F0001-R0001-L0001",
                "ATOM-F0001-R0001-L0002",
                "ATOM-F0001-R0001-L0003",
            ],
            section_id="SEC-001",
            label="Introduction",
        )
        assert evr.evidence_id == "EVID-F0001-R0001-L1-L3"
        assert evr.file_uid == "F0001"
        assert evr.rev_id == "R0001"
        assert evr.start_line == 1
        assert evr.end_line == 3
        assert len(evr.atom_ids) == 3
        assert evr.section_id == "SEC-001"
        assert evr.label == "Introduction"

    def test_evidence_range_id_format_validation(self) -> None:
        """Test evidence_id format must match pattern."""
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRange(
                evidence_id="INVALID-ID",
                file_uid="F0001",
                rev_id="R0001",
                start_line=1,
                end_line=1,
                atom_ids=["ATOM-F0001-R0001-L0001"],
            )
        assert "evidence_id must match" in str(exc_info.value)

    def test_evidence_range_file_uid_consistency(self) -> None:
        """Test evidence_id file_uid must match file_uid field."""
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRange(
                evidence_id="EVID-F0002-R0001-L1-L1",
                file_uid="F0001",  # Mismatch
                rev_id="R0001",
                start_line=1,
                end_line=1,
                atom_ids=["ATOM-F0001-R0001-L0001"],
            )
        assert "file_uid must match" in str(exc_info.value)

    def test_evidence_range_rev_id_consistency(self) -> None:
        """Test evidence_id rev_id must match rev_id field."""
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRange(
                evidence_id="EVID-F0001-R0002-L1-L1",
                file_uid="F0001",
                rev_id="R0001",  # Mismatch
                start_line=1,
                end_line=1,
                atom_ids=["ATOM-F0001-R0001-L0001"],
            )
        assert "rev_id must match" in str(exc_info.value)

    def test_evidence_range_line_range_validation(self) -> None:
        """Test end_line must be >= start_line."""
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRange(
                evidence_id="EVID-F0001-R0001-L5-L3",
                file_uid="F0001",
                rev_id="R0001",
                start_line=5,
                end_line=3,  # Invalid: end < start
                atom_ids=["ATOM-F0001-R0001-L0003"],
            )
        assert "end_line must be >= start_line" in str(exc_info.value)

    def test_evidence_range_atom_ids_count_validation(self) -> None:
        """Test atom_ids count must match line range."""
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRange(
                evidence_id="EVID-F0001-R0001-L1-L3",
                file_uid="F0001",
                rev_id="R0001",
                start_line=1,
                end_line=3,
                atom_ids=["ATOM-F0001-R0001-L0001"],  # Only 1 atom for 3 lines
            )
        assert "atom_ids count" in str(exc_info.value)
        assert "must match line range" in str(exc_info.value)

    def test_evidence_range_single_line(self) -> None:
        """Test evidence range for single line."""
        evr = EvidenceRange(
            evidence_id="EVID-F0001-R0001-L5-L5",
            file_uid="F0001",
            rev_id="R0001",
            start_line=5,
            end_line=5,
            atom_ids=["ATOM-F0001-R0001-L0005"],
        )
        assert evr.start_line == evr.end_line == 5
        assert len(evr.atom_ids) == 1

    def test_evidence_range_with_tags(self) -> None:
        """Test evidence range with tags."""
        evr = EvidenceRange(
            evidence_id="EVID-F0001-R0001-L1-L1",
            file_uid="F0001",
            rev_id="R0001",
            start_line=1,
            end_line=1,
            atom_ids=["ATOM-F0001-R0001-L0001"],
            tags={"remainder", "GAP(COVERAGE)"},
        )
        assert "remainder" in evr.tags
        assert "GAP(COVERAGE)" in evr.tags

    def test_evidence_range_serialization_roundtrip(self) -> None:
        """Test model serialization roundtrip."""
        evr = EvidenceRange(
            evidence_id="EVID-F0001-R0001-L1-L3",
            file_uid="F0001",
            rev_id="R0001",
            start_line=1,
            end_line=3,
            atom_ids=[
                "ATOM-F0001-R0001-L0001",
                "ATOM-F0001-R0001-L0002",
                "ATOM-F0001-R0001-L0003",
            ],
            section_id="SEC-001",
            label="Introduction",
            content_sha256="a" * 64,
            tags={"test"},
        )
        data = evr.model_dump()
        restored = EvidenceRange.model_validate(data)
        assert restored == evr


class TestEvidenceRangesArtifact:
    """Test EvidenceRangesArtifact container model."""

    def test_artifact_creation(self) -> None:
        """Test artifact container creation."""
        evr = EvidenceRange(
            evidence_id="EVID-F0001-R0001-L1-L1",
            file_uid="F0001",
            rev_id="R0001",
            start_line=1,
            end_line=1,
            atom_ids=["ATOM-F0001-R0001-L0001"],
        )
        artifact = EvidenceRangesArtifact(
            file_uid="F0001",
            rev_id="R0001",
            ranges=[evr],
            uncovered_atoms=["ATOM-F0001-R0001-L0002"],
        )
        assert artifact.schema_version == "1.0"
        assert artifact.file_uid == "F0001"
        assert artifact.rev_id == "R0001"
        assert len(artifact.ranges) == 1
        assert len(artifact.uncovered_atoms) == 1

    def test_artifact_json_serialization(self) -> None:
        """Test artifact JSON serialization."""
        evr = EvidenceRange(
            evidence_id="EVID-F0001-R0001-L1-L1",
            file_uid="F0001",
            rev_id="R0001",
            start_line=1,
            end_line=1,
            atom_ids=["ATOM-F0001-R0001-L0001"],
        )
        artifact = EvidenceRangesArtifact(
            file_uid="F0001",
            rev_id="R0001",
            ranges=[evr],
        )
        json_str = artifact.model_dump_json()
        assert "EVID-F0001-R0001-L1-L1" in json_str
        assert "schema_version" in json_str

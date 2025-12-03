"""Tests for scripts.knowledge.residue_manager module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge.residue_manager import (
    clear_artifact_snapshots,
    delete_residue_snapshot,
    get_snapshot_metadata,
    list_residue_snapshots,
    load_residue_snapshot,
    save_residue_snapshot,
)


class TestSaveResidueSnapshot:
    """Tests for save_residue_snapshot function."""

    def test_saves_before_snapshot(self, tmp_path: Path) -> None:
        """Should save before snapshot with correct filename."""
        knowledge_path = tmp_path / ".knowledge"

        result = save_residue_snapshot(
            "artifact-123",
            "Original artifact text",
            "before",
            knowledge_path=knowledge_path,
        )

        assert result.exists()
        assert result.name == "artifact-123.before.txt"
        assert result.read_text() == "Original artifact text"

    def test_saves_after_snapshot(self, tmp_path: Path) -> None:
        """Should save after snapshot with correct filename."""
        knowledge_path = tmp_path / ".knowledge"

        result = save_residue_snapshot(
            "artifact-123",
            "Final residual text",
            "after",
            knowledge_path=knowledge_path,
        )

        assert result.exists()
        assert result.name == "artifact-123.after.txt"
        assert result.read_text() == "Final residual text"

    def test_saves_intermediate_snapshot(self, tmp_path: Path) -> None:
        """Should save intermediate snapshot with pass_id in filename."""
        knowledge_path = tmp_path / ".knowledge"

        result = save_residue_snapshot(
            "artifact-123",
            "Intermediate state text",
            "intermediate",
            pass_id="pass-001",
            knowledge_path=knowledge_path,
        )

        assert result.exists()
        assert result.name == "artifact-123.pass-001.txt"
        assert result.read_text() == "Intermediate state text"

    def test_requires_pass_id_for_intermediate(self, tmp_path: Path) -> None:
        """Should raise ValueError when pass_id missing for intermediate."""
        knowledge_path = tmp_path / ".knowledge"

        with pytest.raises(ValueError, match="pass_id is required"):
            save_residue_snapshot(
                "artifact-123",
                "text",
                "intermediate",
                knowledge_path=knowledge_path,
            )

    def test_creates_residue_directory(self, tmp_path: Path) -> None:
        """Should create residue directory if it doesn't exist."""
        knowledge_path = tmp_path / ".knowledge"
        residue_dir = knowledge_path / "facts" / "residue"

        assert not residue_dir.exists()

        save_residue_snapshot(
            "artifact-123",
            "text",
            "before",
            knowledge_path=knowledge_path,
        )

        assert residue_dir.exists()

    def test_uses_default_knowledge_path(self, tmp_path: Path) -> None:
        """Should use default .knowledge path when not specified."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            result = save_residue_snapshot(
                "artifact-123",
                "text",
                "before",
            )

            expected_dir = tmp_path / ".knowledge" / "facts" / "residue"
            assert result.parent == expected_dir

    def test_raises_for_unknown_snapshot_type(self, tmp_path: Path) -> None:
        """Should raise ValueError for unknown snapshot type."""
        knowledge_path = tmp_path / ".knowledge"

        with pytest.raises(ValueError, match="Unknown snapshot type"):
            save_residue_snapshot(
                "artifact-123",
                "text",
                "invalid",  # type: ignore[arg-type]
                knowledge_path=knowledge_path,
            )


class TestLoadResidueSnapshot:
    """Tests for load_residue_snapshot function."""

    def test_loads_before_snapshot(self, tmp_path: Path) -> None:
        """Should load before snapshot content."""
        knowledge_path = tmp_path / ".knowledge"
        save_residue_snapshot(
            "artifact-123",
            "Original text content",
            "before",
            knowledge_path=knowledge_path,
        )

        result = load_residue_snapshot(
            "artifact-123",
            "before",
            knowledge_path=knowledge_path,
        )

        assert result == "Original text content"

    def test_loads_after_snapshot(self, tmp_path: Path) -> None:
        """Should load after snapshot content."""
        knowledge_path = tmp_path / ".knowledge"
        save_residue_snapshot(
            "artifact-123",
            "Final text",
            "after",
            knowledge_path=knowledge_path,
        )

        result = load_residue_snapshot(
            "artifact-123",
            "after",
            knowledge_path=knowledge_path,
        )

        assert result == "Final text"

    def test_loads_intermediate_snapshot(self, tmp_path: Path) -> None:
        """Should load intermediate snapshot content."""
        knowledge_path = tmp_path / ".knowledge"
        save_residue_snapshot(
            "artifact-123",
            "Intermediate state",
            "intermediate",
            pass_id="pass-002",
            knowledge_path=knowledge_path,
        )

        result = load_residue_snapshot(
            "artifact-123",
            "intermediate",
            pass_id="pass-002",
            knowledge_path=knowledge_path,
        )

        assert result == "Intermediate state"

    def test_raises_for_missing_snapshot(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError when snapshot doesn't exist."""
        knowledge_path = tmp_path / ".knowledge"

        with pytest.raises(FileNotFoundError, match="Snapshot not found"):
            load_residue_snapshot(
                "nonexistent",
                "before",
                knowledge_path=knowledge_path,
            )

    def test_requires_pass_id_for_intermediate(self, tmp_path: Path) -> None:
        """Should raise ValueError when pass_id missing for intermediate."""
        knowledge_path = tmp_path / ".knowledge"

        with pytest.raises(ValueError, match="pass_id is required"):
            load_residue_snapshot(
                "artifact-123",
                "intermediate",
                knowledge_path=knowledge_path,
            )


class TestListResidueSnapshots:
    """Tests for list_residue_snapshots function."""

    def test_returns_empty_for_no_snapshots(self, tmp_path: Path) -> None:
        """Should return empty list when no snapshots exist."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts" / "residue").mkdir(parents=True)

        result = list_residue_snapshots("artifact-123", knowledge_path=knowledge_path)

        assert result == []

    def test_returns_all_snapshots_for_artifact(self, tmp_path: Path) -> None:
        """Should return all snapshots for the artifact."""
        knowledge_path = tmp_path / ".knowledge"

        save_residue_snapshot("artifact-123", "before", "before", knowledge_path=knowledge_path)
        save_residue_snapshot("artifact-123", "after", "after", knowledge_path=knowledge_path)
        save_residue_snapshot(
            "artifact-123",
            "intermediate",
            "intermediate",
            pass_id="pass-001",
            knowledge_path=knowledge_path,
        )

        result = list_residue_snapshots("artifact-123", knowledge_path=knowledge_path)

        assert len(result) == 3
        filenames = [p.name for p in result]
        assert "artifact-123.before.txt" in filenames
        assert "artifact-123.after.txt" in filenames
        assert "artifact-123.pass-001.txt" in filenames

    def test_does_not_include_other_artifacts(self, tmp_path: Path) -> None:
        """Should only return snapshots for specified artifact."""
        knowledge_path = tmp_path / ".knowledge"

        save_residue_snapshot("artifact-A", "text", "before", knowledge_path=knowledge_path)
        save_residue_snapshot("artifact-B", "text", "before", knowledge_path=knowledge_path)

        result = list_residue_snapshots("artifact-A", knowledge_path=knowledge_path)

        assert len(result) == 1
        assert result[0].name == "artifact-A.before.txt"

    def test_returns_sorted_snapshots(self, tmp_path: Path) -> None:
        """Should return snapshots sorted by name."""
        knowledge_path = tmp_path / ".knowledge"

        save_residue_snapshot("artifact-123", "c", "after", knowledge_path=knowledge_path)
        save_residue_snapshot("artifact-123", "a", "before", knowledge_path=knowledge_path)
        save_residue_snapshot(
            "artifact-123",
            "b",
            "intermediate",
            pass_id="pass-001",
            knowledge_path=knowledge_path,
        )

        result = list_residue_snapshots("artifact-123", knowledge_path=knowledge_path)

        # Should be sorted alphabetically
        assert result == sorted(result)


class TestDeleteResidueSnapshot:
    """Tests for delete_residue_snapshot function."""

    def test_deletes_existing_snapshot(self, tmp_path: Path) -> None:
        """Should delete snapshot and return True."""
        knowledge_path = tmp_path / ".knowledge"
        snapshot_path = save_residue_snapshot(
            "artifact-123",
            "text",
            "before",
            knowledge_path=knowledge_path,
        )
        assert snapshot_path.exists()

        result = delete_residue_snapshot(
            "artifact-123",
            "before",
            knowledge_path=knowledge_path,
        )

        assert result is True
        assert not snapshot_path.exists()

    def test_returns_false_for_missing_snapshot(self, tmp_path: Path) -> None:
        """Should return False when snapshot doesn't exist."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts" / "residue").mkdir(parents=True)

        result = delete_residue_snapshot(
            "nonexistent",
            "before",
            knowledge_path=knowledge_path,
        )

        assert result is False

    def test_deletes_intermediate_snapshot(self, tmp_path: Path) -> None:
        """Should delete intermediate snapshot with pass_id."""
        knowledge_path = tmp_path / ".knowledge"
        save_residue_snapshot(
            "artifact-123",
            "text",
            "intermediate",
            pass_id="pass-001",
            knowledge_path=knowledge_path,
        )

        result = delete_residue_snapshot(
            "artifact-123",
            "intermediate",
            pass_id="pass-001",
            knowledge_path=knowledge_path,
        )

        assert result is True


class TestClearArtifactSnapshots:
    """Tests for clear_artifact_snapshots function."""

    def test_deletes_all_snapshots_for_artifact(self, tmp_path: Path) -> None:
        """Should delete all snapshots for the artifact."""
        knowledge_path = tmp_path / ".knowledge"

        save_residue_snapshot("artifact-123", "before", "before", knowledge_path=knowledge_path)
        save_residue_snapshot("artifact-123", "after", "after", knowledge_path=knowledge_path)
        save_residue_snapshot(
            "artifact-123",
            "intermediate",
            "intermediate",
            pass_id="pass-001",
            knowledge_path=knowledge_path,
        )

        result = clear_artifact_snapshots("artifact-123", knowledge_path=knowledge_path)

        assert result == 3
        remaining = list_residue_snapshots("artifact-123", knowledge_path=knowledge_path)
        assert remaining == []

    def test_returns_zero_for_no_snapshots(self, tmp_path: Path) -> None:
        """Should return 0 when no snapshots exist."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts" / "residue").mkdir(parents=True)

        result = clear_artifact_snapshots("nonexistent", knowledge_path=knowledge_path)

        assert result == 0

    def test_does_not_delete_other_artifacts(self, tmp_path: Path) -> None:
        """Should not delete snapshots for other artifacts."""
        knowledge_path = tmp_path / ".knowledge"

        save_residue_snapshot("artifact-A", "text", "before", knowledge_path=knowledge_path)
        save_residue_snapshot("artifact-B", "text", "before", knowledge_path=knowledge_path)

        clear_artifact_snapshots("artifact-A", knowledge_path=knowledge_path)

        remaining_b = list_residue_snapshots("artifact-B", knowledge_path=knowledge_path)
        assert len(remaining_b) == 1


class TestGetSnapshotMetadata:
    """Tests for get_snapshot_metadata function."""

    def test_returns_empty_dict_for_no_snapshots(self, tmp_path: Path) -> None:
        """Should return empty dict when no snapshots exist."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts" / "residue").mkdir(parents=True)

        result = get_snapshot_metadata("nonexistent", knowledge_path=knowledge_path)

        assert result == {}

    def test_returns_metadata_for_before_snapshot(self, tmp_path: Path) -> None:
        """Should return metadata for before snapshot."""
        knowledge_path = tmp_path / ".knowledge"
        save_residue_snapshot(
            "artifact-123",
            "Original text content",
            "before",
            knowledge_path=knowledge_path,
        )

        result = get_snapshot_metadata("artifact-123", knowledge_path=knowledge_path)

        assert "before" in result
        assert "path" in result["before"]
        assert "size" in result["before"]
        assert "modified" in result["before"]
        assert result["before"]["size"] > 0

    def test_returns_metadata_for_all_snapshot_types(self, tmp_path: Path) -> None:
        """Should return metadata for all snapshot types."""
        knowledge_path = tmp_path / ".knowledge"

        save_residue_snapshot("artifact-123", "before text", "before", knowledge_path=knowledge_path)
        save_residue_snapshot("artifact-123", "after text", "after", knowledge_path=knowledge_path)
        save_residue_snapshot(
            "artifact-123",
            "intermediate text",
            "intermediate",
            pass_id="pass-001",
            knowledge_path=knowledge_path,
        )

        result = get_snapshot_metadata("artifact-123", knowledge_path=knowledge_path)

        assert "before" in result
        assert "after" in result
        assert "intermediate:pass-001" in result

    def test_returns_correct_size(self, tmp_path: Path) -> None:
        """Should return correct file size in metadata."""
        knowledge_path = tmp_path / ".knowledge"
        content = "Test content with known length"
        save_residue_snapshot(
            "artifact-123",
            content,
            "before",
            knowledge_path=knowledge_path,
        )

        result = get_snapshot_metadata("artifact-123", knowledge_path=knowledge_path)

        assert result["before"]["size"] == len(content.encode("utf-8"))

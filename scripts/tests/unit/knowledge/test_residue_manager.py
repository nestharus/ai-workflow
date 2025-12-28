from pathlib import Path
from unittest.mock import patch

from scripts.knowledge.residue_manager import (
    clear_artifact_snapshots,
    delete_residue_snapshot,
    get_snapshot_metadata,
    list_residue_snapshots,
    load_residue_snapshot,
    save_residue_snapshot,
)


class TestSaveResidueSnapshot:
    def test_saves_with_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should convert relative knowledge_path to absolute using REPO_ROOT."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            # Pass a relative path - it should be joined with REPO_ROOT
            result = save_residue_snapshot(
                "artifact-rel",
                "Text with relative path",
                "before",
                knowledge_path=Path("subdir/.knowledge"),
            )

            assert result.exists()
            assert result.name == "artifact-rel.before.txt"
            assert result.read_text() == "Text with relative path"
            # Should be under tmp_path/subdir/.knowledge/facts/residue
            assert tmp_path in result.parents

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


class TestLoadResidueSnapshot:
    def test_loads_with_default_knowledge_path(self, tmp_path: Path) -> None:
        """Should use default .knowledge path when not specified."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            # First save a snapshot using default path
            save_residue_snapshot(
                "artifact-default",
                "Default path content",
                "before",
            )

            # Load without specifying knowledge_path
            result = load_residue_snapshot("artifact-default", "before")

            assert result == "Default path content"

    def test_loads_with_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should convert relative knowledge_path to absolute using REPO_ROOT."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            # First save with relative path
            save_residue_snapshot(
                "artifact-rel",
                "Relative path content",
                "before",
                knowledge_path=Path("subdir/.knowledge"),
            )

            # Load with the same relative path
            result = load_residue_snapshot(
                "artifact-rel",
                "before",
                knowledge_path=Path("subdir/.knowledge"),
            )

            assert result == "Relative path content"


class TestListResidueSnapshots:
    def test_lists_with_default_knowledge_path(self, tmp_path: Path) -> None:
        """Should use default .knowledge path when not specified."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            # First save snapshots using default path
            save_residue_snapshot("artifact-default", "before", "before")
            save_residue_snapshot("artifact-default", "after", "after")

            # List without specifying knowledge_path
            result = list_residue_snapshots("artifact-default")

            assert len(result) == 2
            filenames = [p.name for p in result]
            assert "artifact-default.before.txt" in filenames
            assert "artifact-default.after.txt" in filenames

    def test_lists_with_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should convert relative knowledge_path to absolute using REPO_ROOT."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            # First save with relative path
            save_residue_snapshot(
                "artifact-rel",
                "before",
                "before",
                knowledge_path=Path("subdir/.knowledge"),
            )

            # List with the same relative path
            result = list_residue_snapshots(
                "artifact-rel",
                knowledge_path=Path("subdir/.knowledge"),
            )

            assert len(result) == 1
            assert result[0].name == "artifact-rel.before.txt"


class TestDeleteResidueSnapshot:
    def test_deletes_with_default_knowledge_path(self, tmp_path: Path) -> None:
        """Should use default .knowledge path when not specified."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            # First save a snapshot using default path
            snapshot_path = save_residue_snapshot(
                "artifact-default",
                "text",
                "before",
            )
            assert snapshot_path.exists()

            # Delete without specifying knowledge_path
            result = delete_residue_snapshot("artifact-default", "before")

            assert result is True
            assert not snapshot_path.exists()

    def test_deletes_with_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should convert relative knowledge_path to absolute using REPO_ROOT."""
        with patch("scripts.knowledge.residue_manager.REPO_ROOT", tmp_path):
            # First save with relative path
            snapshot_path = save_residue_snapshot(
                "artifact-rel",
                "text",
                "before",
                knowledge_path=Path("subdir/.knowledge"),
            )
            assert snapshot_path.exists()

            # Delete with the same relative path
            result = delete_residue_snapshot(
                "artifact-rel",
                "before",
                knowledge_path=Path("subdir/.knowledge"),
            )

            assert result is True
            assert not snapshot_path.exists()

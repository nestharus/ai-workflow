from pathlib import Path

from scripts.pr import git_dao


class TestRemoveSharedClone:
    def test_returns_success_when_removed(self, tmp_path: Path) -> None:
        """Should return success when clone is removed."""
        clone = tmp_path / "clone"
        clone.mkdir()
        (clone / "file.txt").write_text("test")

        success, error = git_dao.remove_shared_clone(clone)

        assert success is True
        assert error == ""
        assert not clone.exists()

    def test_returns_success_when_not_exists(self, tmp_path: Path) -> None:
        """Should return success when clone doesn't exist."""
        clone = tmp_path / "nonexistent"

        success, error = git_dao.remove_shared_clone(clone)

        assert success is True
        assert error == ""

from pathlib import Path

from scripts.servers.sandbox.operations import (
    ensure_sandbox_exists,
    get_conflicts,
    is_rebase_in_progress,
    merge_in_sandbox,
    push_from_sandbox,
    rebase_in_sandbox,
    sync_sandbox_branch,
)


class TestIsRebaseInProgress:
    def test_returns_false_when_no_rebase(self, tmp_path: Path) -> None:
        """Return False when no rebase directories exist."""
        # Create .git directory but no rebase directories
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        result = is_rebase_in_progress(tmp_path)

        assert result is False

    def test_returns_true_when_rebase_merge_exists(self, tmp_path: Path) -> None:
        """Return True when .git/rebase-merge directory exists."""
        # Create .git/rebase-merge directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "rebase-merge").mkdir()

        result = is_rebase_in_progress(tmp_path)

        assert result is True

    def test_returns_true_when_rebase_apply_exists(self, tmp_path: Path) -> None:
        """Return True when .git/rebase-apply directory exists."""
        # Create .git/rebase-apply directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "rebase-apply").mkdir()

        result = is_rebase_in_progress(tmp_path)

        assert result is True

    def test_returns_false_when_git_dir_missing(self, tmp_path: Path) -> None:
        """Return False when .git directory is missing."""
        # tmp_path exists but has no .git directory

        result = is_rebase_in_progress(tmp_path)

        assert result is False

    def test_returns_false_when_rebase_merge_is_file(self, tmp_path: Path) -> None:
        """Return False when .git/rebase-merge exists but is a file, not directory."""
        # Create .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        # Create rebase-merge as a file, not a directory
        (git_dir / "rebase-merge").write_text("not a directory")

        result = is_rebase_in_progress(tmp_path)

        assert result is False

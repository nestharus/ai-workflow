"""Tests for sandbox operations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.servers.sandbox.operations import (
    ensure_sandbox_exists,
    get_conflicts,
    merge_in_sandbox,
    push_from_sandbox,
    rebase_in_sandbox,
    sync_sandbox_branch,
)


def make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Create a mock CompletedProcess object."""
    return subprocess.CompletedProcess(
        args=["git"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestEnsureSandboxExists:
    """Tests for ensure_sandbox_exists function."""

    def test_raises_if_git_init_fails(self, tmp_path: Path) -> None:
        """Raise RuntimeError and cleanup if git init fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init fails
                make_completed_process(returncode=1, stderr="init failed"),
            ]

            with pytest.raises(RuntimeError, match="Failed to initialize sandbox"):
                ensure_sandbox_exists(tmp_path)

    def test_raises_if_git_init_returns_none(self, tmp_path: Path) -> None:
        """Raise RuntimeError with git not available message when init returns None."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init returns None (git not available)
                None,
            ]

            with pytest.raises(RuntimeError, match="git not available"):
                ensure_sandbox_exists(tmp_path)

    def test_raises_if_git_remote_add_fails(self, tmp_path: Path) -> None:
        """Raise RuntimeError and cleanup if git remote add fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init succeeds
                make_completed_process(),
                # git remote add fails
                make_completed_process(returncode=1, stderr="remote add failed"),
            ]

            with pytest.raises(RuntimeError, match="Failed to add remote"):
                ensure_sandbox_exists(tmp_path)

    def test_raises_if_git_remote_add_returns_none(self, tmp_path: Path) -> None:
        """Raise RuntimeError with git not available message when remote add returns None."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init succeeds
                make_completed_process(),
                # git remote add returns None
                None,
            ]

            with pytest.raises(RuntimeError, match="git not available"):
                ensure_sandbox_exists(tmp_path)

    def test_cleans_up_existing_invalid_sandbox_directory(self, tmp_path: Path) -> None:
        """Remove existing invalid sandbox directory before creating new one."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sandbox_path = git_dir / "sandbox"
        sandbox_path.mkdir()  # Create a directory (invalid sandbox, no .git)
        (sandbox_path / "stale_file.txt").write_text("stale content")

        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir for repo_root
                make_completed_process(stdout=".git\n"),
                # git rev-parse --git-dir to check sandbox validity (fails - not a valid repo)
                make_completed_process(returncode=128, stderr="not a git repository"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init
                make_completed_process(),
                # git remote add
                make_completed_process(),
                # git config user.name
                make_completed_process(),
                # git config user.email
                make_completed_process(),
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == sandbox_path
            assert result.exists()
            assert result.is_dir()
            # The stale file should be gone (directory was cleaned up)
            assert not (sandbox_path / "stale_file.txt").exists()

    def test_creates_sandbox_without_user_name(self, tmp_path: Path) -> None:
        """Create sandbox when user.name is not set."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name - not set (returns None, no returncode=0)
                make_completed_process(returncode=1, stdout=""),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init
                make_completed_process(),
                # git remote add
                make_completed_process(),
                # git config user.email (user.name is skipped since it's not set)
                make_completed_process(),
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == tmp_path / ".git" / "sandbox"
            assert result.exists()

    def test_creates_sandbox_without_user_email(self, tmp_path: Path) -> None:
        """Create sandbox when user.email is not set."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email - not set (returns None, no returncode=0)
                make_completed_process(returncode=1, stdout=""),
                # git init
                make_completed_process(),
                # git remote add
                make_completed_process(),
                # git config user.name (user.email is skipped since it's not set)
                make_completed_process(),
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == tmp_path / ".git" / "sandbox"
            assert result.exists()

    def test_creates_sandbox_without_any_user_config(self, tmp_path: Path) -> None:
        """Create sandbox when neither user.name nor user.email is set."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name - not set
                make_completed_process(returncode=1, stdout=""),
                # Get user.email - not set
                make_completed_process(returncode=1, stdout=""),
                # git init
                make_completed_process(),
                # git remote add
                make_completed_process(),
                # No config calls since both are not set
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == tmp_path / ".git" / "sandbox"
            assert result.exists()

    def test_returns_existing_sandbox_if_valid(self, tmp_path: Path) -> None:
        """Return existing sandbox path if it's already a valid git repo."""
        sandbox_path = tmp_path / ".git" / "sandbox"
        sandbox_path.mkdir(parents=True)
        (sandbox_path / ".git").mkdir()

        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir for repo_root
                make_completed_process(stdout=".git\n"),
                # git rev-parse --git-dir to check sandbox is valid repo
                make_completed_process(stdout=".git\n"),
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == sandbox_path

    def test_returns_existing_sandbox_with_gitfile(self, tmp_path: Path) -> None:
        """Return existing sandbox path when .git is a file (gitdir pointer)."""
        sandbox_path = tmp_path / ".git" / "sandbox"
        sandbox_path.mkdir(parents=True)
        # Create .git as a file (gitdir pointer) instead of directory
        (sandbox_path / ".git").write_text("gitdir: /some/other/path/.git")

        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir for repo_root
                make_completed_process(stdout=".git\n"),
                # git rev-parse --git-dir to check sandbox is valid repo
                make_completed_process(stdout="/some/other/path/.git\n"),
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == sandbox_path

    def test_creates_new_sandbox_if_not_exists(self, tmp_path: Path) -> None:
        """Create new sandbox if it doesn't exist."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init
                make_completed_process(),
                # git remote add
                make_completed_process(),
                # git config user.name
                make_completed_process(),
                # git config user.email
                make_completed_process(),
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == tmp_path / ".git" / "sandbox"
            assert result.exists()

    def test_raises_if_git_dir_resolution_fails(self, tmp_path: Path) -> None:
        """Raise RuntimeError if git dir resolution fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(returncode=1, stderr="not a git repo")

            with pytest.raises(RuntimeError, match="Failed to resolve git dir"):
                ensure_sandbox_exists(tmp_path)

    def test_raises_if_no_remote_url(self, tmp_path: Path) -> None:
        """Raise RuntimeError if can't get remote URL."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL fails
                make_completed_process(returncode=1, stderr="not a git repo"),
            ]

            with pytest.raises(RuntimeError, match="Cannot get remote URL"):
                ensure_sandbox_exists(tmp_path)

    def test_raises_if_remote_url_is_empty(self, tmp_path: Path) -> None:
        """Raise RuntimeError if remote URL is empty."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir
                make_completed_process(stdout=".git\n"),
                # Get remote URL succeeds but returns empty string
                make_completed_process(returncode=0, stdout=""),
            ]

            with pytest.raises(RuntimeError, match=r"Cannot get remote URL.*empty"):
                ensure_sandbox_exists(tmp_path)

    def test_cleans_up_non_directory_sandbox_path(self, tmp_path: Path) -> None:
        """Remove non-directory file at sandbox path before creating directory."""
        # Pre-create .git directory and a regular file (not dir) where sandbox should be
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sandbox_path = git_dir / "sandbox"
        sandbox_path.write_text("stale file")  # Create a regular file, not a directory

        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir for repo_root
                make_completed_process(stdout=".git\n"),
                # git rev-parse --git-dir to check sandbox validity (fails - not a valid repo)
                make_completed_process(returncode=128, stderr="not a git repository"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init
                make_completed_process(),
                # git remote add
                make_completed_process(),
                # git config user.name
                make_completed_process(),
                # git config user.email
                make_completed_process(),
            ]

            result = ensure_sandbox_exists(tmp_path)

            assert result == sandbox_path
            assert result.exists()
            assert result.is_dir()

    def test_handles_worktree_with_absolute_git_dir(self, tmp_path: Path) -> None:
        """Handle worktrees where git dir is an absolute path outside repo."""
        # Simulate worktree: git rev-parse --git-dir returns absolute path
        main_git_dir = tmp_path / "main-repo" / ".git" / "worktrees" / "branch"
        main_git_dir.mkdir(parents=True)
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git rev-parse --git-dir returns absolute path to worktree git dir
                make_completed_process(stdout=f"{main_git_dir}\n"),
                # Get remote URL
                make_completed_process(stdout="https://github.com/user/repo.git\n"),
                # Get user.name
                make_completed_process(stdout="Test User\n"),
                # Get user.email
                make_completed_process(stdout="test@example.com\n"),
                # git init
                make_completed_process(),
                # git remote add
                make_completed_process(),
                # git config user.name
                make_completed_process(),
                # git config user.email
                make_completed_process(),
            ]

            result = ensure_sandbox_exists(worktree_path)

            # Sandbox should be in the actual git dir, not in worktree/.git
            assert result == main_git_dir / "sandbox"
            assert result.exists()


class TestSyncSandboxBranch:
    """Tests for sync_sandbox_branch function."""

    def test_syncs_existing_branch(self, tmp_path: Path) -> None:
        """Sync an existing local branch."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git fetch origin
                make_completed_process(),
                # git rebase --abort (cleanup)
                make_completed_process(),
                # git merge --abort (cleanup)
                make_completed_process(),
                # git show-ref (branch exists)
                make_completed_process(returncode=0),
                # git checkout
                make_completed_process(),
                # git reset --hard
                make_completed_process(),
            ]

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is True
            assert error == ""

    def test_creates_new_branch_if_not_exists(self, tmp_path: Path) -> None:
        """Create new branch tracking remote if doesn't exist locally."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git fetch origin
                make_completed_process(),
                # git rebase --abort (cleanup)
                make_completed_process(),
                # git merge --abort (cleanup)
                make_completed_process(),
                # git show-ref (branch doesn't exist)
                make_completed_process(returncode=1),
                # git checkout -b
                make_completed_process(),
            ]

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is True
            assert error == ""

    def test_returns_error_on_fetch_failure(self, tmp_path: Path) -> None:
        """Return error if fetch fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(returncode=1, stderr="fetch failed")

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is False
            assert "fetch failed" in error

    def test_returns_error_when_reset_hard_fails(self, tmp_path: Path) -> None:
        """Return error when branch exists but git reset --hard fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git fetch origin
                make_completed_process(),
                # git rebase --abort (cleanup)
                make_completed_process(),
                # git merge --abort (cleanup)
                make_completed_process(),
                # git show-ref (branch exists)
                make_completed_process(returncode=0),
                # git checkout succeeds
                make_completed_process(),
                # git reset --hard fails
                make_completed_process(returncode=1, stderr="error: could not reset index"),
            ]

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is False
            assert "reset failed" in error
            assert "could not reset index" in error

    def test_returns_error_when_checkout_new_branch_fails(self, tmp_path: Path) -> None:
        """Return error when branch doesn't exist and git checkout -b fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git fetch origin
                make_completed_process(),
                # git rebase --abort (cleanup)
                make_completed_process(),
                # git merge --abort (cleanup)
                make_completed_process(),
                # git show-ref (branch doesn't exist)
                make_completed_process(returncode=1),
                # git checkout -b fails
                make_completed_process(
                    returncode=1, stderr="fatal: 'origin/feature-x' is not a commit"
                ),
            ]

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is False
            assert "checkout failed" in error
            assert "not a commit" in error

    def test_returns_error_when_fetch_returns_none(self, tmp_path: Path) -> None:
        """Return error when git fetch returns None (git not available)."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = None

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is False
            assert "git not available" in error

    def test_returns_error_when_checkout_existing_branch_returns_none(self, tmp_path: Path) -> None:
        """Return error when branch exists but git checkout returns None."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git fetch origin
                make_completed_process(),
                # git rebase --abort (cleanup)
                make_completed_process(),
                # git merge --abort (cleanup)
                make_completed_process(),
                # git show-ref (branch exists)
                make_completed_process(returncode=0),
                # git checkout returns None (git not available)
                None,
            ]

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is False
            assert "checkout failed" in error
            assert "git not available" in error

    def test_removes_claude_directory_if_exists(self, tmp_path: Path) -> None:
        """Remove .claude directory if it exists after sync."""
        # Create .claude directory
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "config.json").write_text("{}")

        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git fetch origin
                make_completed_process(),
                # git rebase --abort (cleanup)
                make_completed_process(),
                # git merge --abort (cleanup)
                make_completed_process(),
                # git show-ref (branch doesn't exist)
                make_completed_process(returncode=1),
                # git checkout -b
                make_completed_process(),
            ]

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is True
            assert error == ""
            assert not claude_dir.exists()

    def test_removes_tasks_directory_if_exists(self, tmp_path: Path) -> None:
        """Remove .tasks directory if it exists after sync."""
        # Create .tasks directory
        tasks_dir = tmp_path / ".tasks"
        tasks_dir.mkdir()
        (tasks_dir / "task.yaml").write_text("task: test")

        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # git fetch origin
                make_completed_process(),
                # git rebase --abort (cleanup)
                make_completed_process(),
                # git merge --abort (cleanup)
                make_completed_process(),
                # git show-ref (branch doesn't exist)
                make_completed_process(returncode=1),
                # git checkout -b
                make_completed_process(),
            ]

            success, error = sync_sandbox_branch(tmp_path, "feature-x")

            assert success is True
            assert error == ""
            assert not tasks_dir.exists()


class TestGetConflicts:
    """Tests for get_conflicts function."""

    def test_returns_empty_list_when_no_conflicts(self, tmp_path: Path) -> None:
        """Return empty list when no conflicts."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(stdout="")

            conflicts = get_conflicts(tmp_path)

            assert conflicts == []

    def test_returns_conflicted_files(self, tmp_path: Path) -> None:
        """Return list of files with UU (both modified) status."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(
                stdout="UU file1.py\nUU file2.py\nM  file3.py\n"
            )

            conflicts = get_conflicts(tmp_path)

            assert conflicts == ["file1.py", "file2.py"]

    def test_handles_aa_conflicts(self, tmp_path: Path) -> None:
        """Return files with AA (both added) status."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(stdout="AA newfile.py\n")

            conflicts = get_conflicts(tmp_path)

            assert conflicts == ["newfile.py"]

    def test_handles_dd_conflicts(self, tmp_path: Path) -> None:
        """Return files with DD (both deleted) status."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(stdout="DD deleted.py\n")

            conflicts = get_conflicts(tmp_path)

            assert conflicts == ["deleted.py"]

    def test_returns_empty_list_when_git_not_available(self, tmp_path: Path) -> None:
        """Return empty list and log error when git returns None."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = None

            conflicts = get_conflicts(tmp_path)

            assert conflicts == []

    def test_returns_empty_list_on_git_status_failure(self, tmp_path: Path) -> None:
        """Return empty list and log error when git status fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(
                returncode=1, stderr="fatal: not a git repository"
            )

            conflicts = get_conflicts(tmp_path)

            assert conflicts == []

    def test_skips_lines_shorter_than_three_chars(self, tmp_path: Path) -> None:
        """Skip lines with fewer than 3 characters."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            # Mix of valid and too-short lines
            mock_run.return_value = make_completed_process(
                stdout="UU file1.py\nXY\n \nUU file2.py\n"
            )

            conflicts = get_conflicts(tmp_path)

            assert conflicts == ["file1.py", "file2.py"]


class TestRebaseInSandbox:
    """Tests for rebase_in_sandbox function."""

    def test_successful_rebase(self, tmp_path: Path) -> None:
        """Return success result on successful rebase."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target
                make_completed_process(),
                # rebase
                make_completed_process(),
            ]

            result = rebase_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is True
            assert result.has_conflicts is False
            assert result.conflicts == []

    def test_rebase_with_conflicts(self, tmp_path: Path) -> None:
        """Return conflict result when rebase has conflicts."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target
                make_completed_process(),
                # rebase (fails with conflicts)
                make_completed_process(returncode=1),
                # get_conflicts calls git status
                make_completed_process(stdout="UU conflict.py\n"),
            ]

            result = rebase_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is True
            assert result.conflicts == ["conflict.py"]

    def test_returns_error_when_sync_fails(self, tmp_path: Path) -> None:
        """Return error when sync_sandbox_branch fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch: fetch fails
                make_completed_process(returncode=1, stderr="fetch failed"),
            ]

            result = rebase_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "fetch failed" in result.error

    def test_returns_error_when_fetch_target_returns_none(self, tmp_path: Path) -> None:
        """Return error when fetch target returns None (git not available)."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target returns None
                None,
            ]

            result = rebase_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "git not available" in result.error

    def test_returns_error_when_rebase_returns_none(self, tmp_path: Path) -> None:
        """Return error when git rebase returns None (git not available)."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target succeeds
                make_completed_process(),
                # rebase returns None
                None,
            ]

            result = rebase_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "git not available" in result.error

    def test_returns_error_when_rebase_fails_without_conflicts(self, tmp_path: Path) -> None:
        """Return error when rebase fails but no conflicts are detected."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target succeeds
                make_completed_process(),
                # rebase fails
                make_completed_process(returncode=1, stderr="rebase error"),
                # get_conflicts returns empty (no conflicts, just failure)
                make_completed_process(stdout=""),
            ]

            result = rebase_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "rebase failed" in result.error
            assert "rebase error" in result.error


class TestMergeInSandbox:
    """Tests for merge_in_sandbox function."""

    def test_successful_merge(self, tmp_path: Path) -> None:
        """Return success result on successful merge."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target
                make_completed_process(),
                # merge
                make_completed_process(),
            ]

            result = merge_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is True
            assert result.has_conflicts is False
            assert result.conflicts == []

    def test_merge_with_conflicts(self, tmp_path: Path) -> None:
        """Return conflict result when merge has conflicts."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target
                make_completed_process(),
                # merge (fails with conflicts)
                make_completed_process(returncode=1),
                # get_conflicts calls git status
                make_completed_process(stdout="UU conflict.py\n"),
            ]

            result = merge_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is True
            assert result.conflicts == ["conflict.py"]

    def test_returns_error_when_sync_fails(self, tmp_path: Path) -> None:
        """Return error when sync_sandbox_branch fails."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch: fetch fails
                make_completed_process(returncode=1, stderr="fetch failed"),
            ]

            result = merge_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "fetch failed" in result.error

    def test_returns_error_when_fetch_target_returns_none(self, tmp_path: Path) -> None:
        """Return error when fetch target returns None (git not available)."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target returns None
                None,
            ]

            result = merge_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "git not available" in result.error

    def test_returns_error_when_merge_returns_none(self, tmp_path: Path) -> None:
        """Return error when git merge returns None (git not available)."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target succeeds
                make_completed_process(),
                # merge returns None
                None,
            ]

            result = merge_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "git not available" in result.error

    def test_returns_error_when_merge_fails_without_conflicts(self, tmp_path: Path) -> None:
        """Return error when merge fails but no conflicts are detected."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.side_effect = [
                # sync_sandbox_branch calls
                make_completed_process(),  # fetch
                make_completed_process(),  # rebase --abort
                make_completed_process(),  # merge --abort
                make_completed_process(returncode=0),  # show-ref
                make_completed_process(),  # checkout
                make_completed_process(),  # reset --hard
                # fetch target succeeds
                make_completed_process(),
                # merge fails
                make_completed_process(returncode=1, stderr="merge error"),
                # get_conflicts returns empty (no conflicts, just failure)
                make_completed_process(stdout=""),
            ]

            result = merge_in_sandbox(tmp_path, "feature-x", "main")

            assert result.success is False
            assert result.has_conflicts is False
            assert "merge failed" in result.error
            assert "merge error" in result.error


class TestPushFromSandbox:
    """Tests for push_from_sandbox function."""

    def test_successful_push(self, tmp_path: Path) -> None:
        """Return success on successful push."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process()

            success, error = push_from_sandbox(tmp_path, "feature-x")

            assert success is True
            assert error == ""

    def test_force_push(self, tmp_path: Path) -> None:
        """Use force-with-lease when force=True."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process()

            push_from_sandbox(tmp_path, "feature-x", force=True)

            # Verify force-with-lease was in the command at correct position
            call_args = mock_run.call_args[0][0]
            assert "--force-with-lease" in call_args
            # Verify flag position: git push --force-with-lease origin branch
            assert call_args[2] == "--force-with-lease"

    def test_push_failure(self, tmp_path: Path) -> None:
        """Return error on push failure."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = make_completed_process(returncode=1, stderr="rejected")

            success, error = push_from_sandbox(tmp_path, "feature-x")

            assert success is False
            assert "rejected" in error

    def test_returns_error_when_git_not_available(self, tmp_path: Path) -> None:
        """Return error when git returns None (git not available)."""
        with patch("scripts.servers.sandbox.operations._run_git") as mock_run:
            mock_run.return_value = None

            success, error = push_from_sandbox(tmp_path, "feature-x")

            assert success is False
            assert "git not available" in error

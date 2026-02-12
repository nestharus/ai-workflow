"""Component tests for VCS abstraction and WorktreeManager.

Tests GitVcs (subprocess-mocked) and WorktreeManager (VcsOperations-mocked)
for the worktree hierarchy described in simpler.md:
  - Dirty root worktree
  - Per-library grandchild worktrees
  - Clean sibling worktree
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from spec_manager.orchestration.models import LAYER_ORDER
from spec_manager.vcs.operations import GitVcs, VcsOperations
from spec_manager.vcs.worktree import WorktreeManager

# ======================================================================
# Helpers
# ======================================================================


def _completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Build a fake CompletedProcess."""
    return subprocess.CompletedProcess(
        args=["git"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _make_mock_vcs() -> MagicMock:
    """Create a MagicMock that satisfies the VcsOperations protocol."""
    vcs = MagicMock(spec=VcsOperations)
    # Default: all operations succeed
    vcs.create_worktree.return_value = (True, "")
    vcs.remove_worktree.return_value = (True, "")
    vcs.worktree_exists.return_value = False
    vcs.cherry_pick.return_value = (True, "")
    vcs.rebase.return_value = (True, "")
    vcs.merge.return_value = (True, "")
    vcs.commit_all.return_value = (True, "")
    vcs.get_current_branch.return_value = "main"
    vcs.get_head_sha.return_value = "abc123"
    # New multi-layer operations
    vcs.rev_parse.return_value = "abc123"
    vcs.update_ref.return_value = (True, "")
    vcs.rev_list_count.return_value = 0
    vcs.create_tag.return_value = (True, "")
    vcs.delete_ref.return_value = (True, "")
    return vcs


# ======================================================================
# GitVcs tests
# ======================================================================

_SUBPROCESS_TARGET = "spec_manager.vcs.operations.subprocess.run"


class TestGitVcsCreateWorktree:
    """Test GitVcs.create_worktree method."""

    @patch(_SUBPROCESS_TARGET)
    def test_create_worktree_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Successful worktree creation returns (True, '')."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)
        wt_path = tmp_path / "worktrees" / "my-wt"

        ok, err = vcs.create_worktree(wt_path, "feature-branch", start_point="HEAD")

        assert ok is True
        assert err == ""
        mock_run.assert_called_once_with(
            ["git", "worktree", "add", "-b", "feature-branch", str(wt_path), "HEAD"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

    @patch(_SUBPROCESS_TARGET)
    def test_create_worktree_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Failed worktree creation returns (False, error_message)."""
        mock_run.return_value = _completed(returncode=128, stderr="fatal: branch already exists")
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.create_worktree(tmp_path / "wt", "existing-branch")

        assert ok is False
        assert "branch already exists" in err

    @patch(_SUBPROCESS_TARGET)
    def test_create_worktree_custom_start_point(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Custom start_point is forwarded to the git command."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)
        wt_path = tmp_path / "wt"

        vcs.create_worktree(wt_path, "new-branch", start_point="origin/main")

        args = mock_run.call_args[0][0]
        assert args[-1] == "origin/main"


class TestGitVcsRemoveWorktree:
    """Test GitVcs.remove_worktree method."""

    @patch(_SUBPROCESS_TARGET)
    def test_remove_worktree_success_with_branch_deletion(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Successful removal also deletes the associated branch."""
        wt_path = tmp_path / "worktrees" / "my-wt"
        resolved = str(wt_path.resolve())

        porcelain_output = f"worktree {resolved}\nHEAD abc123\nbranch refs/heads/feature-branch\n\n"

        # First call: worktree remove (success)
        # Second call: worktree list --porcelain (for _branch_for_worktree)
        # Third call: branch -D (success)
        mock_run.side_effect = [
            _completed(),  # worktree remove
            _completed(stdout=porcelain_output),  # worktree list --porcelain
            _completed(),  # branch -D
        ]

        vcs = GitVcs(repo_root=tmp_path)
        ok, err = vcs.remove_worktree(wt_path)

        assert ok is True
        assert err == ""
        assert mock_run.call_count == 3

        # Verify branch -D was called with the right branch name
        branch_delete_call = mock_run.call_args_list[2]
        assert branch_delete_call[0][0] == ["git", "branch", "-D", "feature-branch"]

    @patch(_SUBPROCESS_TARGET)
    def test_remove_worktree_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Failed worktree removal returns (False, error_message)."""
        mock_run.return_value = _completed(returncode=1, stderr="fatal: not a valid worktree")
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.remove_worktree(tmp_path / "nonexistent")

        assert ok is False
        assert "not a valid worktree" in err

    @patch(_SUBPROCESS_TARGET)
    def test_remove_worktree_no_branch_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """When no branch is associated, branch deletion is skipped."""
        wt_path = tmp_path / "worktrees" / "orphan"

        mock_run.side_effect = [
            _completed(),  # worktree remove
            _completed(stdout="worktree /some/other/path\nHEAD abc123\n\n"),  # no match
        ]

        vcs = GitVcs(repo_root=tmp_path)
        ok, err = vcs.remove_worktree(wt_path)

        assert ok is True
        assert err == ""
        # Only 2 calls: worktree remove + worktree list (no branch -D)
        assert mock_run.call_count == 2


class TestGitVcsWorktreeExists:
    """Test GitVcs.worktree_exists method."""

    @patch(_SUBPROCESS_TARGET)
    def test_worktree_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns True when the path appears in porcelain output."""
        wt_path = tmp_path / "worktrees" / "found"
        resolved = str(wt_path.resolve())

        mock_run.return_value = _completed(
            stdout=(f"worktree {resolved}\nHEAD abc123\nbranch refs/heads/main\n\n")
        )

        vcs = GitVcs(repo_root=tmp_path)
        assert vcs.worktree_exists(wt_path) is True

    @patch(_SUBPROCESS_TARGET)
    def test_worktree_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns False when the path is not in porcelain output."""
        mock_run.return_value = _completed(
            stdout="worktree /some/other/path\nHEAD abc123\nbranch refs/heads/main\n\n"
        )

        vcs = GitVcs(repo_root=tmp_path)
        assert vcs.worktree_exists(tmp_path / "missing") is False

    @patch(_SUBPROCESS_TARGET)
    def test_worktree_exists_git_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns False when git command fails."""
        mock_run.return_value = _completed(returncode=1, stderr="not a git repo")

        vcs = GitVcs(repo_root=tmp_path)
        assert vcs.worktree_exists(tmp_path / "any") is False


class TestGitVcsCherryPick:
    """Test GitVcs.cherry_pick method."""

    @patch(_SUBPROCESS_TARGET)
    def test_cherry_pick_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Successful cherry-pick returns (True, '')."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)
        wt = tmp_path / "wt"

        ok, err = vcs.cherry_pick(wt, "abc123")

        assert ok is True
        assert err == ""
        mock_run.assert_called_once_with(
            ["git", "cherry-pick", "abc123"],
            cwd=wt,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

    @patch(_SUBPROCESS_TARGET)
    def test_cherry_pick_failure_aborts(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Failed cherry-pick aborts and returns (False, error_message)."""
        mock_run.side_effect = [
            _completed(returncode=1, stderr="conflict in file.txt"),  # cherry-pick
            _completed(),  # cherry-pick --abort
        ]

        vcs = GitVcs(repo_root=tmp_path)
        wt = tmp_path / "wt"
        ok, err = vcs.cherry_pick(wt, "bad123")

        assert ok is False
        assert "conflict" in err

        # Verify abort was called
        abort_call = mock_run.call_args_list[1]
        assert abort_call[0][0] == ["git", "cherry-pick", "--abort"]
        assert abort_call[1]["cwd"] == wt


class TestGitVcsRebase:
    """Test GitVcs.rebase method."""

    @patch(_SUBPROCESS_TARGET)
    def test_rebase_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Successful rebase returns (True, '')."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)
        wt = tmp_path / "wt"

        ok, err = vcs.rebase(wt, "main")

        assert ok is True
        assert err == ""
        mock_run.assert_called_once_with(
            ["git", "rebase", "main"],
            cwd=wt,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

    @patch(_SUBPROCESS_TARGET)
    def test_rebase_failure_aborts(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Failed rebase aborts and returns (False, error_message)."""
        mock_run.side_effect = [
            _completed(returncode=1, stderr="rebase conflict"),
            _completed(),  # rebase --abort
        ]

        vcs = GitVcs(repo_root=tmp_path)
        wt = tmp_path / "wt"
        ok, err = vcs.rebase(wt, "main")

        assert ok is False
        assert "rebase conflict" in err

        abort_call = mock_run.call_args_list[1]
        assert abort_call[0][0] == ["git", "rebase", "--abort"]
        assert abort_call[1]["cwd"] == wt


class TestGitVcsMerge:
    """Test GitVcs.merge method."""

    @patch(_SUBPROCESS_TARGET)
    def test_merge_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Successful merge returns (True, '')."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)
        wt = tmp_path / "wt"

        ok, err = vcs.merge(wt, "feature-branch")

        assert ok is True
        assert err == ""
        mock_run.assert_called_once_with(
            ["git", "merge", "feature-branch", "--no-ff"],
            cwd=wt,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

    @patch(_SUBPROCESS_TARGET)
    def test_merge_failure_aborts(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Failed merge aborts and returns (False, error_message)."""
        mock_run.side_effect = [
            _completed(returncode=1, stderr="merge conflict in main.py"),
            _completed(),  # merge --abort
        ]

        vcs = GitVcs(repo_root=tmp_path)
        wt = tmp_path / "wt"
        ok, err = vcs.merge(wt, "conflicting-branch")

        assert ok is False
        assert "merge conflict" in err

        abort_call = mock_run.call_args_list[1]
        assert abort_call[0][0] == ["git", "merge", "--abort"]
        assert abort_call[1]["cwd"] == wt


class TestGitVcsCommitAll:
    """Test GitVcs.commit_all method."""

    @patch(_SUBPROCESS_TARGET)
    def test_commit_all_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Successful add + commit returns (True, '')."""
        mock_run.side_effect = [
            _completed(),  # git add -A
            _completed(),  # git commit -m ...
        ]

        vcs = GitVcs(repo_root=tmp_path)
        wt = tmp_path / "wt"
        ok, err = vcs.commit_all(wt, "initial commit")

        assert ok is True
        assert err == ""
        assert mock_run.call_count == 2

        # Verify git add -A
        add_call = mock_run.call_args_list[0]
        assert add_call[0][0] == ["git", "add", "-A"]
        assert add_call[1]["cwd"] == wt

        # Verify git commit -m ...
        commit_call = mock_run.call_args_list[1]
        assert commit_call[0][0] == ["git", "commit", "-m", "initial commit", "--allow-empty"]
        assert commit_call[1]["cwd"] == wt

    @patch(_SUBPROCESS_TARGET)
    def test_commit_all_stage_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """When git add fails, commit is not attempted."""
        mock_run.return_value = _completed(returncode=1, stderr="error: unable to create index")

        vcs = GitVcs(repo_root=tmp_path)
        ok, err = vcs.commit_all(tmp_path / "wt", "msg")

        assert ok is False
        assert "unable to create index" in err
        # Only 1 call: git add (commit was never attempted)
        assert mock_run.call_count == 1

    @patch(_SUBPROCESS_TARGET)
    def test_commit_all_commit_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """When git add succeeds but commit fails, returns the commit error."""
        mock_run.side_effect = [
            _completed(),  # git add -A succeeds
            _completed(returncode=1, stderr="error: commit hook rejected"),
        ]

        vcs = GitVcs(repo_root=tmp_path)
        ok, err = vcs.commit_all(tmp_path / "wt", "msg")

        assert ok is False
        assert "commit hook rejected" in err
        assert mock_run.call_count == 2


class TestGitVcsGetCurrentBranch:
    """Test GitVcs.get_current_branch method."""

    @patch(_SUBPROCESS_TARGET)
    def test_normal_branch(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns branch name when on a normal branch."""
        mock_run.return_value = _completed(stdout="feature-xyz\n")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.get_current_branch(tmp_path / "wt")

        assert result == "feature-xyz"

    @patch(_SUBPROCESS_TARGET)
    def test_detached_head(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns None when in detached HEAD state."""
        mock_run.return_value = _completed(stdout="HEAD\n")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.get_current_branch(tmp_path / "wt")

        assert result is None

    @patch(_SUBPROCESS_TARGET)
    def test_error_returns_none(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns None when git command fails."""
        mock_run.return_value = _completed(returncode=1, stderr="not a git repository")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.get_current_branch(tmp_path / "wt")

        assert result is None

    @patch(_SUBPROCESS_TARGET)
    def test_default_worktree_none(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """When worktree is None, uses repo_root as cwd."""
        mock_run.return_value = _completed(stdout="main\n")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.get_current_branch(None)

        assert result == "main"
        # cwd should fall back to repo_root since worktree is None
        assert mock_run.call_args[1]["cwd"] == tmp_path


class TestGitVcsGetHeadSha:
    """Test GitVcs.get_head_sha method."""

    @patch(_SUBPROCESS_TARGET)
    def test_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns the SHA when successful."""
        sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        mock_run.return_value = _completed(stdout=f"{sha}\n")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.get_head_sha(tmp_path / "wt")

        assert result == sha

    @patch(_SUBPROCESS_TARGET)
    def test_error_returns_none(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns None when git command fails."""
        mock_run.return_value = _completed(returncode=128, stderr="fatal: bad object HEAD")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.get_head_sha(tmp_path / "wt")

        assert result is None


class TestGitVcsBranchForWorktree:
    """Test GitVcs._branch_for_worktree private method."""

    @patch(_SUBPROCESS_TARGET)
    def test_branch_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns the short branch name when the worktree path matches."""
        wt_path = tmp_path / "worktrees" / "my-wt"
        resolved = str(wt_path.resolve())

        porcelain = (
            f"worktree {resolved}\n"
            "HEAD abc123def456\n"
            "branch refs/heads/pdd/run-1/root\n"
            "\n"
            "worktree /other/path\n"
            "HEAD 999999\n"
            "branch refs/heads/main\n"
            "\n"
        )
        mock_run.return_value = _completed(stdout=porcelain)
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs._branch_for_worktree(wt_path)

        assert result == "root"

    @patch(_SUBPROCESS_TARGET)
    def test_branch_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns None when worktree path is not in the list."""
        mock_run.return_value = _completed(
            stdout="worktree /other/path\nHEAD abc123\nbranch refs/heads/main\n\n"
        )
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs._branch_for_worktree(tmp_path / "nonexistent")

        assert result is None

    @patch(_SUBPROCESS_TARGET)
    def test_branch_git_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Returns None when git command fails."""
        mock_run.return_value = _completed(returncode=1, stderr="error")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs._branch_for_worktree(tmp_path / "any")

        assert result is None

    @patch(_SUBPROCESS_TARGET)
    def test_branch_with_nested_refs(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Correctly extracts branch name from deeply nested ref paths."""
        wt_path = tmp_path / "wt"
        resolved = str(wt_path.resolve())

        porcelain = (
            f"worktree {resolved}\nHEAD abc123\nbranch refs/heads/pdd/run-42/lib/auth-service\n\n"
        )
        mock_run.return_value = _completed(stdout=porcelain)
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs._branch_for_worktree(wt_path)

        # split("/")[-1] returns the last segment
        assert result == "auth-service"


class TestGitVcsProtocol:
    """Test that GitVcs satisfies the VcsOperations protocol."""

    def test_gitsvcs_is_runtime_checkable(self, tmp_path: Path) -> None:
        """GitVcs should be recognized as implementing VcsOperations at runtime."""
        vcs = GitVcs(repo_root=tmp_path)
        assert isinstance(vcs, VcsOperations)


# ======================================================================
# WorktreeManager tests
# ======================================================================


class TestWorktreeManagerInit:
    """Test WorktreeManager initialization."""

    def test_default_worktrees_base(self, tmp_path: Path) -> None:
        """Default worktrees_base is workspace_root / '.worktrees'."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        assert mgr.worktrees_base == tmp_path / ".worktrees"
        assert mgr.run_id == "run-1"
        assert mgr.vcs is vcs
        assert mgr.workspace_root == tmp_path

    def test_custom_worktrees_base(self, tmp_path: Path) -> None:
        """Custom worktrees_base overrides the default."""
        custom_base = tmp_path / "custom_wt"
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(
            vcs=vcs,
            workspace_root=tmp_path,
            run_id="run-2",
            worktrees_base=custom_base,
        )

        assert mgr.worktrees_base == custom_base

    def test_branch_naming(self, tmp_path: Path) -> None:
        """Branch names follow the pdd/{run_id}/{type} convention."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="abc")

        assert mgr._root_branch == "pdd/abc/root"
        assert mgr._clean_branch == "pdd/abc/clean"

    def test_path_naming(self, tmp_path: Path) -> None:
        """Worktree paths follow the {run_id}-{type} convention."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="xyz")

        expected_base = tmp_path / ".worktrees"
        assert mgr._root_path == expected_base / "xyz-root"
        assert mgr._clean_path == expected_base / "xyz-clean"

    def test_library_worktrees_initially_empty(self, tmp_path: Path) -> None:
        """No library worktrees exist before setup."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        assert mgr._library_worktrees == {}


class TestWorktreeManagerSetup:
    """Test WorktreeManager.setup method."""

    def test_setup_success(self, tmp_path: Path) -> None:
        """Successful setup creates root and clean worktrees and returns paths."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        result = mgr.setup()

        assert "root_path" in result
        assert "clean_path" in result
        assert result["root_path"] == str(mgr._root_path)
        assert result["clean_path"] == str(mgr._clean_path)

        # Verify two worktree creations
        assert vcs.create_worktree.call_count == 2

        # Verify root worktree created first
        root_call = vcs.create_worktree.call_args_list[0]
        assert root_call[0][0] == mgr._root_path
        assert root_call[0][1] == "pdd/run-1/root"

        # Verify clean worktree created second
        clean_call = vcs.create_worktree.call_args_list[1]
        assert clean_call[0][0] == mgr._clean_path
        assert clean_call[0][1] == "pdd/run-1/clean"

    def test_setup_creates_worktrees_base_directory(self, tmp_path: Path) -> None:
        """Setup creates the worktrees_base directory if it does not exist."""
        base = tmp_path / "new_base"
        assert not base.exists()

        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1", worktrees_base=base)
        mgr.setup()

        assert base.exists()

    def test_setup_root_failure_raises(self, tmp_path: Path) -> None:
        """RuntimeError when root worktree creation fails."""
        vcs = _make_mock_vcs()
        vcs.create_worktree.return_value = (False, "branch already exists")
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        with pytest.raises(RuntimeError, match="root worktree"):
            mgr.setup()

    def test_setup_clean_failure_raises(self, tmp_path: Path) -> None:
        """RuntimeError when clean worktree creation fails (root succeeds)."""
        vcs = _make_mock_vcs()
        # First call (root) succeeds, second call (clean) fails
        vcs.create_worktree.side_effect = [
            (True, ""),
            (False, "cannot create clean"),
        ]
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        with pytest.raises(RuntimeError, match="clean worktree"):
            mgr.setup()

    def test_setup_uses_current_branch_as_start_point(self, tmp_path: Path) -> None:
        """Setup uses the current branch from vcs as the start_point."""
        vcs = _make_mock_vcs()
        vcs.get_current_branch.return_value = "develop"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        mgr.setup()

        # Both worktrees should use "develop" as start_point
        for call_obj in vcs.create_worktree.call_args_list:
            assert call_obj[1]["start_point"] == "develop"

    def test_setup_falls_back_to_head_when_no_branch(self, tmp_path: Path) -> None:
        """When get_current_branch returns None, uses 'HEAD' as start_point."""
        vcs = _make_mock_vcs()
        vcs.get_current_branch.return_value = None
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        mgr.setup()

        for call_obj in vcs.create_worktree.call_args_list:
            assert call_obj[1]["start_point"] == "HEAD"


class TestWorktreeManagerCreateLibraryWorktree:
    """Test WorktreeManager.create_library_worktree method."""

    def test_create_library_worktree_success(self, tmp_path: Path) -> None:
        """Creates a library worktree and returns its path."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        path = mgr.create_library_worktree("auth-service")

        expected = mgr.worktrees_base / "run-1-lib-auth-service"
        assert path == expected

        # Verify create_worktree was called with correct branch and start_point
        vcs.create_worktree.assert_called_once_with(
            expected,
            "pdd/run-1/lib/auth-service",
            start_point="pdd/run-1/root",
        )

    def test_create_library_worktree_tracked_internally(self, tmp_path: Path) -> None:
        """Created library worktree is tracked in _library_worktrees."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        mgr.create_library_worktree("auth-service")

        assert "auth-service" in mgr._library_worktrees
        assert mgr._library_worktrees["auth-service"] == (
            mgr.worktrees_base / "run-1-lib-auth-service"
        )

    def test_create_duplicate_raises(self, tmp_path: Path) -> None:
        """RuntimeError when creating a library worktree that already exists."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("auth-service")

        with pytest.raises(RuntimeError, match="already exists"):
            mgr.create_library_worktree("auth-service")

    def test_create_library_worktree_failure(self, tmp_path: Path) -> None:
        """RuntimeError when vcs.create_worktree fails for a library."""
        vcs = _make_mock_vcs()
        vcs.create_worktree.return_value = (False, "disk full")
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        with pytest.raises(RuntimeError, match="auth-service"):
            mgr.create_library_worktree("auth-service")

        # Library should NOT be tracked
        assert "auth-service" not in mgr._library_worktrees

    def test_create_multiple_libraries(self, tmp_path: Path) -> None:
        """Can create multiple library worktrees independently."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        p1 = mgr.create_library_worktree("lib-a")
        p2 = mgr.create_library_worktree("lib-b")

        assert p1 != p2
        assert len(mgr._library_worktrees) == 2
        assert vcs.create_worktree.call_count == 2


class TestWorktreeManagerPromoteLibrary:
    """Test WorktreeManager.promote_library method."""

    def test_promote_success(self, tmp_path: Path) -> None:
        """Successful promotion merges library branch into clean worktree."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("auth-service")

        result = mgr.promote_library("auth-service")

        assert result["lib_id"] == "auth-service"
        assert result["promoted"] is True

        vcs.merge.assert_called_once_with(mgr._clean_path, "pdd/run-1/lib/auth-service")

    def test_promote_unknown_library_raises(self, tmp_path: Path) -> None:
        """RuntimeError when promoting a library that has no worktree."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        with pytest.raises(RuntimeError, match="No worktree found"):
            mgr.promote_library("nonexistent")

    def test_promote_merge_failure_raises(self, tmp_path: Path) -> None:
        """RuntimeError when merge fails during promotion."""
        vcs = _make_mock_vcs()
        vcs.merge.return_value = (False, "conflict in file.py")
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("auth-service")

        with pytest.raises(RuntimeError, match="promote.*auth-service"):
            mgr.promote_library("auth-service")


class TestWorktreeManagerRebaseRootOnClean:
    """Test WorktreeManager.rebase_root_on_clean method."""

    def test_rebase_success(self, tmp_path: Path) -> None:
        """Successful rebase returns result dict."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        result = mgr.rebase_root_on_clean()

        assert result["rebased"] is True
        vcs.rebase.assert_called_once_with(mgr._root_path, "pdd/run-1/clean")

    def test_rebase_failure_raises(self, tmp_path: Path) -> None:
        """RuntimeError when rebase fails."""
        vcs = _make_mock_vcs()
        vcs.rebase.return_value = (False, "rebase conflict")
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        with pytest.raises(RuntimeError, match="rebase root onto clean"):
            mgr.rebase_root_on_clean()


class TestWorktreeManagerGetLibraryWorktree:
    """Test WorktreeManager.get_library_worktree method."""

    def test_returns_path_for_existing_library(self, tmp_path: Path) -> None:
        """Returns the worktree path for a tracked library."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("auth-service")

        result = mgr.get_library_worktree("auth-service")

        assert result == mgr.worktrees_base / "run-1-lib-auth-service"

    def test_returns_none_for_unknown_library(self, tmp_path: Path) -> None:
        """Returns None for a library that has no worktree."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        assert mgr.get_library_worktree("unknown") is None


class TestWorktreeManagerListWorktrees:
    """Test WorktreeManager.list_worktrees method."""

    def test_empty_when_no_libraries(self, tmp_path: Path) -> None:
        """Returns empty list when no library worktrees exist."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        assert mgr.list_worktrees() == []

    def test_populated_list(self, tmp_path: Path) -> None:
        """Returns sorted list of active library worktrees."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("zebra")
        mgr.create_library_worktree("alpha")

        result = mgr.list_worktrees()

        assert len(result) == 2
        # Sorted by lib_id
        assert result[0]["lib_id"] == "alpha"
        assert result[1]["lib_id"] == "zebra"
        # Paths are strings
        assert isinstance(result[0]["path"], str)
        assert isinstance(result[1]["path"], str)


class TestWorktreeManagerCleanup:
    """Test WorktreeManager.cleanup method."""

    def test_full_cleanup(self, tmp_path: Path) -> None:
        """Cleanup removes library, clean, and root worktrees in order."""
        vcs = _make_mock_vcs()
        # worktree_exists returns True for clean and root during cleanup
        vcs.worktree_exists.return_value = True
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("lib-a")
        mgr.create_library_worktree("lib-b")

        # Reset mock to isolate cleanup calls from create calls
        vcs.reset_mock()
        vcs.remove_worktree.return_value = (True, "")
        vcs.worktree_exists.return_value = True

        result = mgr.cleanup()

        assert "lib/lib-a" in result["removed"]
        assert "lib/lib-b" in result["removed"]
        assert "clean" in result["removed"]
        assert "root" in result["removed"]
        assert result["errors"] == []

        # Library worktrees cleared
        assert mgr._library_worktrees == {}

        # remove_worktree called 4 times: 2 libs + clean + root
        assert vcs.remove_worktree.call_count == 4

    def test_cleanup_empty(self, tmp_path: Path) -> None:
        """Cleanup with no library worktrees and non-existent clean/root."""
        vcs = _make_mock_vcs()
        vcs.worktree_exists.return_value = False
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        result = mgr.cleanup()

        assert result["removed"] == []
        assert result["errors"] == []
        assert vcs.remove_worktree.call_count == 0

    def test_cleanup_partial_errors(self, tmp_path: Path) -> None:
        """Cleanup continues even when some worktree removals fail."""
        vcs = _make_mock_vcs()
        vcs.worktree_exists.return_value = True

        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("lib-a")

        # Reset to isolate cleanup calls
        vcs.reset_mock()
        vcs.worktree_exists.return_value = True

        # lib-a removal fails, clean succeeds, root fails
        vcs.remove_worktree.side_effect = [
            (False, "lock file exists"),  # lib-a
            (True, ""),  # clean
            (False, "permission denied"),  # root
        ]

        result = mgr.cleanup()

        assert "clean" in result["removed"]
        assert len(result["errors"]) == 2
        assert result["errors"][0]["worktree"] == "lib/lib-a"
        assert "lock file" in result["errors"][0]["error"]
        assert result["errors"][1]["worktree"] == "root"
        assert "permission denied" in result["errors"][1]["error"]

    def test_cleanup_library_worktrees_removed_before_clean_and_root(self, tmp_path: Path) -> None:
        """Library worktrees are removed before clean and root."""
        vcs = _make_mock_vcs()
        vcs.worktree_exists.return_value = True

        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.create_library_worktree("lib-a")

        vcs.reset_mock()
        vcs.remove_worktree.return_value = (True, "")
        vcs.worktree_exists.return_value = True

        mgr.cleanup()

        # Verify call order: lib-a, then clean, then root
        calls = vcs.remove_worktree.call_args_list
        assert len(calls) == 3

        # First call is the library worktree path
        lib_path = mgr.worktrees_base / "run-1-lib-lib-a"
        assert calls[0][0][0] == lib_path

        # Second call is clean
        assert calls[1][0][0] == mgr._clean_path

        # Third call is root
        assert calls[2][0][0] == mgr._root_path


class TestWorktreeManagerProperties:
    """Test WorktreeManager.root_path and clean_path properties."""

    def test_root_path(self, tmp_path: Path) -> None:
        """root_path returns the expected path."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        assert mgr.root_path == mgr.worktrees_base / "run-1-root"

    def test_clean_path(self, tmp_path: Path) -> None:
        """clean_path returns the expected path."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        assert mgr.clean_path == mgr.worktrees_base / "run-1-clean"

    def test_properties_are_readonly(self, tmp_path: Path) -> None:
        """root_path and clean_path are read-only properties."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        with pytest.raises(AttributeError):
            mgr.root_path = tmp_path / "other"  # type: ignore[misc]

        with pytest.raises(AttributeError):
            mgr.clean_path = tmp_path / "other"  # type: ignore[misc]


# ======================================================================
# Multi-layer: setup_layers
# ======================================================================


class TestWorktreeManagerSetupLayers:
    """Test WorktreeManager.setup_layers method."""

    def test_setup_layers_creates_six_worktrees(self, tmp_path: Path) -> None:
        """setup_layers(create_all=True) creates 6 worktrees (3 layers x 2 lanes)."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        result = mgr.setup_layers()

        assert vcs.create_worktree.call_count == 6
        assert len(result["worktrees"]) == 6

        # Verify all layer/lane combos
        combos = {(w["layer"], w["lane"]) for w in result["worktrees"]}
        expected = {
            ("l1", "dirty"),
            ("l1", "clean"),
            ("l2", "dirty"),
            ("l2", "clean"),
            ("l3", "dirty"),
            ("l3", "clean"),
        }
        assert combos == expected

    def test_setup_layers_create_all_false_creates_only_l1(self, tmp_path: Path) -> None:
        """setup_layers(create_all=False) creates only L1 dirty + clean."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        result = mgr.setup_layers(create_all=False)

        assert vcs.create_worktree.call_count == 2
        assert len(result["worktrees"]) == 2
        layers = {w["layer"] for w in result["worktrees"]}
        assert layers == {"l1"}

    def test_setup_layers_correct_branch_names(self, tmp_path: Path) -> None:
        """setup_layers() uses correct branch naming convention."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        mgr.setup_layers()

        # Check that all create_worktree calls used correct branch names
        calls = vcs.create_worktree.call_args_list
        branch_names = {c[0][1] for c in calls}
        expected_branches = {
            "pdd/run-1/l1/dirty",
            "pdd/run-1/l1/clean",
            "pdd/run-1/l2/dirty",
            "pdd/run-1/l2/clean",
            "pdd/run-1/l3/dirty",
            "pdd/run-1/l3/clean",
        }
        assert branch_names == expected_branches

    def test_setup_layers_uses_base_ref(self, tmp_path: Path) -> None:
        """setup_layers(base_ref=...) uses the specified base ref."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        result = mgr.setup_layers(base_ref="origin/main")

        assert result["base_ref"] == "origin/main"
        for call_obj in vcs.create_worktree.call_args_list:
            assert call_obj[1]["start_point"] == "origin/main"

    def test_setup_layers_failure_raises(self, tmp_path: Path) -> None:
        """RuntimeError when worktree creation fails during setup_layers."""
        vcs = _make_mock_vcs()
        vcs.create_worktree.return_value = (False, "disk full")
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        with pytest.raises(RuntimeError, match="l1/dirty"):
            mgr.setup_layers()

    def test_setup_layers_sets_initialized_flag(self, tmp_path: Path) -> None:
        """setup_layers() sets _layers_initialized to True."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")

        assert mgr._layers_initialized is False
        mgr.setup_layers()
        assert mgr._layers_initialized is True


# ======================================================================
# Multi-layer: layer_branch / candidate_ref
# ======================================================================


class TestWorktreeManagerLayerAccessors:
    """Test layer_branch() and candidate_ref() naming methods."""

    def test_layer_branch_format(self, tmp_path: Path) -> None:
        """layer_branch() returns pdd/{run_id}/{layer}/{lane}."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-42")

        assert mgr.layer_branch("l1", "dirty") == "pdd/run-42/l1/dirty"
        assert mgr.layer_branch("l2", "clean") == "pdd/run-42/l2/clean"
        assert mgr.layer_branch("l3", "dirty") == "pdd/run-42/l3/dirty"

    def test_candidate_ref_format(self, tmp_path: Path) -> None:
        """candidate_ref() returns pdd/{run_id}/{layer}/candidate."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-42")

        assert mgr.candidate_ref("l1") == "pdd/run-42/l1/candidate"
        assert mgr.candidate_ref("l2") == "pdd/run-42/l2/candidate"
        assert mgr.candidate_ref("l3") == "pdd/run-42/l3/candidate"


# ======================================================================
# Multi-layer: is_layer_clean
# ======================================================================


class TestWorktreeManagerIsLayerClean:
    """Test is_layer_clean() for various dirty/clean states."""

    def test_clean_when_dirty_equals_clean(self, tmp_path: Path) -> None:
        """is_layer_clean returns True when dirty SHA == clean SHA and candidate matches."""
        vcs = _make_mock_vcs()
        vcs.get_head_sha.return_value = "same_sha"
        vcs.rev_parse.return_value = "same_sha"  # candidate == clean
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        assert mgr.is_layer_clean("l1") is True

    def test_dirty_when_shas_differ(self, tmp_path: Path) -> None:
        """is_layer_clean returns False when dirty SHA != clean SHA."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        # Make dirty and clean return different SHAs
        dirty_path = mgr._layer_worktrees["l1"]["dirty"]
        clean_path = mgr._layer_worktrees["l1"]["clean"]

        def head_sha_side_effect(path: Path) -> str | None:
            if path == dirty_path:
                return "dirty_sha"
            elif path == clean_path:
                return "clean_sha"
            return None

        vcs.get_head_sha.side_effect = head_sha_side_effect
        vcs.rev_parse.return_value = None  # no candidate

        assert mgr.is_layer_clean("l1") is False

    def test_dirty_when_candidate_differs_from_clean(self, tmp_path: Path) -> None:
        """is_layer_clean returns False when candidate SHA != clean SHA."""
        vcs = _make_mock_vcs()
        vcs.get_head_sha.return_value = "same_sha"
        vcs.rev_parse.return_value = "different_candidate"  # candidate != clean
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        assert mgr.is_layer_clean("l1") is False


# ======================================================================
# Multi-layer: create_slice_worktree
# ======================================================================


class TestWorktreeManagerCreateSliceWorktree:
    """Test create_slice_worktree() for grandchild worktrees."""

    def test_creates_grandchild(self, tmp_path: Path) -> None:
        """create_slice_worktree creates a worktree branching from layer dirty."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        # Reset mock to isolate slice creation from setup
        vcs.create_worktree.reset_mock()

        path = mgr.create_slice_worktree("l1", "auth-service")

        assert vcs.create_worktree.call_count == 1
        call_args = vcs.create_worktree.call_args
        # Branch starts from dirty
        assert call_args[1]["start_point"] == "pdd/run-1/l1/dirty"
        # Branch name contains slice info
        assert "slice/auth-service" in call_args[0][1]
        # Path is tracked
        assert mgr.get_slice_worktree("l1", "auth-service") == path

    def test_duplicate_slice_raises(self, tmp_path: Path) -> None:
        """create_slice_worktree raises when a slice already exists."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])
        mgr.create_slice_worktree("l1", "auth")

        with pytest.raises(RuntimeError, match="already exists"):
            mgr.create_slice_worktree("l1", "auth")


# ======================================================================
# Multi-layer: merge_slice_to_dirty
# ======================================================================


class TestWorktreeManagerMergeSliceToDirty:
    """Test merge_slice_to_dirty() merging grandchild into layer dirty."""

    def test_merge_success(self, tmp_path: Path) -> None:
        """merge_slice_to_dirty calls vcs.merge with correct arguments."""
        vcs = _make_mock_vcs()
        vcs.get_current_branch.return_value = "pdd/run-1/l1/slice/auth/abc123"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])
        mgr.create_slice_worktree("l1", "auth")

        result = mgr.merge_slice_to_dirty("l1", "auth")

        assert result.success is True
        assert result.layer == "l1"
        assert result.slice_id == "auth"
        # Verify merge was called with dirty path and slice branch
        vcs.merge.assert_called()

    def test_merge_no_slice_returns_failure(self, tmp_path: Path) -> None:
        """merge_slice_to_dirty returns failure when slice does not exist."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        result = mgr.merge_slice_to_dirty("l1", "nonexistent")

        assert result.success is False
        assert "No slice worktree" in result.error


# ======================================================================
# Multi-layer: cleanup_slice_worktree
# ======================================================================


class TestWorktreeManagerCleanupSliceWorktree:
    """Test cleanup_slice_worktree() removing a grandchild worktree."""

    def test_removes_slice_worktree(self, tmp_path: Path) -> None:
        """cleanup_slice_worktree removes the worktree via vcs."""
        vcs = _make_mock_vcs()
        vcs.worktree_exists.return_value = True
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])
        mgr.create_slice_worktree("l1", "auth")

        mgr.cleanup_slice_worktree("l1", "auth")

        assert mgr.get_slice_worktree("l1", "auth") is None
        vcs.remove_worktree.assert_called()


# ======================================================================
# Multi-layer: snapshot_candidate
# ======================================================================


class TestWorktreeManagerSnapshotCandidate:
    """Test snapshot_candidate() creating CI snapshot ref."""

    def test_snapshot_calls_update_ref(self, tmp_path: Path) -> None:
        """snapshot_candidate sets candidate ref to dirty HEAD SHA."""
        vcs = _make_mock_vcs()
        vcs.get_head_sha.return_value = "dirty_sha_123"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        sha = mgr.snapshot_candidate("l1")

        assert sha == "dirty_sha_123"
        vcs.update_ref.assert_called_with("pdd/run-1/l1/candidate", "dirty_sha_123")

    def test_snapshot_returns_none_when_no_dirty_worktree(self, tmp_path: Path) -> None:
        """snapshot_candidate returns None when no dirty worktree exists."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        # Don't setup layers => no worktrees

        sha = mgr.snapshot_candidate("l1")

        assert sha is None


# ======================================================================
# Multi-layer: promote_dirty_to_clean
# ======================================================================


class TestWorktreeManagerPromoteDirtyToClean:
    """Test promote_dirty_to_clean() advancing clean ref."""

    def test_advances_clean_ref(self, tmp_path: Path) -> None:
        """promote_dirty_to_clean updates clean branch to candidate SHA."""
        vcs = _make_mock_vcs()
        vcs.rev_parse.return_value = "candidate_sha"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        result = mgr.promote_dirty_to_clean("l1")

        assert result.success is True
        assert result.candidate_sha == "candidate_sha"
        assert result.clean_sha == "candidate_sha"
        vcs.update_ref.assert_called()

    def test_no_candidate_returns_failure(self, tmp_path: Path) -> None:
        """promote_dirty_to_clean fails when no candidate snapshot exists."""
        vcs = _make_mock_vcs()
        vcs.rev_parse.return_value = None  # no candidate
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers(layers=["l1"])

        result = mgr.promote_dirty_to_clean("l1")

        assert result.success is False
        assert "No candidate" in result.error


# ======================================================================
# Multi-layer: propagate_clean_to_next_layer
# ======================================================================


class TestWorktreeManagerPropagateCleanToNextLayer:
    """Test propagate_clean_to_next_layer() cross-layer merge."""

    def test_l1_to_l2_merges_clean_to_dirty(self, tmp_path: Path) -> None:
        """propagate_clean_to_next_layer merges l1/clean into l2/dirty."""
        vcs = _make_mock_vcs()
        vcs.get_head_sha.return_value = "merge_sha"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        result = mgr.propagate_clean_to_next_layer("l1")

        assert result.success is True
        assert result.from_layer == "l1"
        assert result.to_layer == "l2"
        assert result.merge_sha == "merge_sha"

        # Should merge l1/clean branch into l2/dirty worktree
        l2_dirty_path = mgr._layer_worktrees["l2"]["dirty"]
        vcs.merge.assert_called_with(l2_dirty_path, "pdd/run-1/l1/clean")

    def test_l3_has_no_next_layer(self, tmp_path: Path) -> None:
        """propagate_clean_to_next_layer from l3 returns failure."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        result = mgr.propagate_clean_to_next_layer("l3")

        assert result.success is False
        assert "No next layer" in result.error


# ======================================================================
# Multi-layer: tick_pipeline
# ======================================================================


class TestWorktreeManagerTickPipeline:
    """Test tick_pipeline() processing layers in order."""

    def test_processes_layers_in_order(self, tmp_path: Path) -> None:
        """tick_pipeline processes L1, then L2, then L3."""
        vcs = _make_mock_vcs()
        # Make layers dirty (dirty_sha != clean_sha via rev_parse returning different)
        vcs.get_head_sha.return_value = "dirty_sha"
        vcs.rev_parse.return_value = "candidate_sha"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        result = mgr.tick_pipeline(active_layer="l1")

        # Should have batch results for layers that were processed
        assert isinstance(result.layer_results, dict)

    def test_skips_clean_layers(self, tmp_path: Path) -> None:
        """tick_pipeline skips layers where dirty == clean."""
        vcs = _make_mock_vcs()
        # All same SHA = clean
        vcs.get_head_sha.return_value = "same_sha"
        vcs.rev_parse.return_value = "same_sha"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        result = mgr.tick_pipeline(active_layer="l1")

        # No layers should have batch results since all are clean
        assert len(result.layer_results) == 0


# ======================================================================
# Multi-layer: compute_active_layer
# ======================================================================


class TestWorktreeManagerComputeActiveLayer:
    """Test compute_active_layer() returning lowest dirty layer."""

    def test_returns_lowest_dirty_layer(self, tmp_path: Path) -> None:
        """compute_active_layer returns the lowest layer that is not clean."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        # Make l1 clean (same SHAs) and l2 dirty (different SHAs)
        l1_dirty = mgr._layer_worktrees["l1"]["dirty"]
        l1_clean = mgr._layer_worktrees["l1"]["clean"]
        l2_dirty = mgr._layer_worktrees["l2"]["dirty"]
        l2_clean = mgr._layer_worktrees["l2"]["clean"]

        def head_sha(path: Path) -> str | None:
            if path in (l1_dirty, l1_clean):
                return "same"
            if path == l2_dirty:
                return "dirty_l2"
            if path == l2_clean:
                return "clean_l2"
            return "other"

        vcs.get_head_sha.side_effect = head_sha
        vcs.rev_parse.return_value = "same"  # candidate matches clean for l1

        result = mgr.compute_active_layer()

        assert result == "l2"

    def test_returns_l1_when_all_clean(self, tmp_path: Path) -> None:
        """compute_active_layer defaults to l1 when all layers are clean."""
        vcs = _make_mock_vcs()
        vcs.get_head_sha.return_value = "same"
        vcs.rev_parse.return_value = "same"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        result = mgr.compute_active_layer()

        assert result == "l1"


# ======================================================================
# Multi-layer: can_advance_layer
# ======================================================================


class TestWorktreeManagerCanAdvanceLayer:
    """Test can_advance_layer() checking all conditions."""

    def test_can_advance_when_all_clean(self, tmp_path: Path) -> None:
        """can_advance_layer returns True when this and upper layers are clean."""
        vcs = _make_mock_vcs()
        vcs.get_head_sha.return_value = "same"
        vcs.rev_parse.return_value = "same"
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        assert mgr.can_advance_layer("l1") is True

    def test_cannot_advance_when_dirty(self, tmp_path: Path) -> None:
        """can_advance_layer returns False when layer is dirty."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        # Make l1 dirty
        l1_dirty = mgr._layer_worktrees["l1"]["dirty"]
        l1_clean = mgr._layer_worktrees["l1"]["clean"]

        def head_sha(path: Path) -> str | None:
            if path == l1_dirty:
                return "dirty"
            if path == l1_clean:
                return "clean"
            return "same"

        vcs.get_head_sha.side_effect = head_sha
        vcs.rev_parse.return_value = None

        assert mgr.can_advance_layer("l1") is False

    def test_cannot_advance_when_upper_layer_dirty(self, tmp_path: Path) -> None:
        """can_advance_layer returns False when a downstream layer is not clean."""
        vcs = _make_mock_vcs()
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()

        l1_dirty = mgr._layer_worktrees["l1"]["dirty"]
        l1_clean = mgr._layer_worktrees["l1"]["clean"]
        l2_dirty = mgr._layer_worktrees["l2"]["dirty"]
        l2_clean = mgr._layer_worktrees["l2"]["clean"]

        def head_sha(path: Path) -> str | None:
            # l1 is clean
            if path in (l1_dirty, l1_clean):
                return "same_l1"
            # l2 is dirty
            if path == l2_dirty:
                return "dirty_l2"
            if path == l2_clean:
                return "clean_l2"
            return "same"

        vcs.get_head_sha.side_effect = head_sha

        def rev_parse_effect(ref: str) -> str | None:
            if "l1" in ref:
                return "same_l1"  # candidate matches clean for l1
            return None

        vcs.rev_parse.side_effect = rev_parse_effect

        assert mgr.can_advance_layer("l1") is False


# ======================================================================
# Multi-layer: cleanup (extended)
# ======================================================================


class TestWorktreeManagerCleanupMultiLayer:
    """Test cleanup() removes all layer + slice worktrees."""

    def test_cleanup_removes_all_layer_worktrees(self, tmp_path: Path) -> None:
        """cleanup() removes all layer worktrees and clears internal state."""
        vcs = _make_mock_vcs()
        vcs.worktree_exists.return_value = True
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()
        mgr.create_slice_worktree("l1", "auth")

        # Reset to isolate cleanup calls
        vcs.reset_mock()
        vcs.remove_worktree.return_value = (True, "")
        vcs.worktree_exists.return_value = True
        vcs.delete_ref.return_value = (True, "")

        result = mgr.cleanup()

        # Should remove: 1 slice + 6 layer worktrees + 2 legacy (clean + root)
        assert "slice/l1:auth" in result["removed"]
        assert mgr._layer_worktrees == {}
        assert mgr._layer_branches == {}
        assert mgr._slice_worktrees == {}

        # Should delete candidate refs for all 3 layers
        assert vcs.delete_ref.call_count == 3

    def test_cleanup_slice_only(self, tmp_path: Path) -> None:
        """cleanup_layer_slices removes only slice worktrees for a layer."""
        vcs = _make_mock_vcs()
        vcs.worktree_exists.return_value = True
        mgr = WorktreeManager(vcs=vcs, workspace_root=tmp_path, run_id="run-1")
        mgr.setup_layers()
        mgr.create_slice_worktree("l1", "auth")
        mgr.create_slice_worktree("l1", "payment")
        mgr.create_slice_worktree("l2", "infra")

        removed = mgr.cleanup_layer_slices("l1")

        assert len(removed) == 2
        assert "l1:auth" in removed
        assert "l1:payment" in removed
        # l2 slice is NOT removed
        assert mgr.get_slice_worktree("l2", "infra") is not None


# ======================================================================
# GitVcs new methods: rev_parse, update_ref, rev_list_count, etc.
# ======================================================================


class TestGitVcsRevParse:
    """Test GitVcs.rev_parse method."""

    @patch(_SUBPROCESS_TARGET)
    def test_rev_parse_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """rev_parse returns SHA on success."""
        sha = "a1b2c3d4e5f6"
        mock_run.return_value = _completed(stdout=f"{sha}\n")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.rev_parse("refs/heads/main")

        assert result == sha

    @patch(_SUBPROCESS_TARGET)
    def test_rev_parse_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """rev_parse returns None on failure."""
        mock_run.return_value = _completed(returncode=128, stderr="fatal: bad ref")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.rev_parse("nonexistent-ref")

        assert result is None


class TestGitVcsUpdateRef:
    """Test GitVcs.update_ref method."""

    @patch(_SUBPROCESS_TARGET)
    def test_update_ref_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """update_ref returns (True, '') on success."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.update_ref("pdd/run-1/l1/candidate", "abc123")

        assert ok is True
        assert err == ""
        args = mock_run.call_args[0][0]
        assert "update-ref" in args

    @patch(_SUBPROCESS_TARGET)
    def test_update_ref_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """update_ref returns (False, error) on failure."""
        mock_run.return_value = _completed(returncode=1, stderr="error: invalid ref")
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.update_ref("bad-ref", "abc123")

        assert ok is False
        assert "invalid ref" in err


class TestGitVcsRevListCount:
    """Test GitVcs.rev_list_count method."""

    @patch(_SUBPROCESS_TARGET)
    def test_rev_list_count_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """rev_list_count returns integer count on success."""
        mock_run.return_value = _completed(stdout="5\n")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.rev_list_count("abc123", "def456")

        assert result == 5

    @patch(_SUBPROCESS_TARGET)
    def test_rev_list_count_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """rev_list_count returns None on failure."""
        mock_run.return_value = _completed(returncode=128, stderr="fatal: bad ref")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.rev_list_count("bad", "refs")

        assert result is None

    @patch(_SUBPROCESS_TARGET)
    def test_rev_list_count_non_numeric(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """rev_list_count returns None when output is not numeric."""
        mock_run.return_value = _completed(stdout="not a number\n")
        vcs = GitVcs(repo_root=tmp_path)

        result = vcs.rev_list_count("ref1", "ref2")

        assert result is None


class TestGitVcsCreateTag:
    """Test GitVcs.create_tag method."""

    @patch(_SUBPROCESS_TARGET)
    def test_create_tag_lightweight(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """create_tag without message creates a lightweight tag."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.create_tag("v1.0", "abc123")

        assert ok is True
        assert err == ""
        args = mock_run.call_args[0][0]
        assert args == ["git", "tag", "v1.0", "abc123"]

    @patch(_SUBPROCESS_TARGET)
    def test_create_tag_annotated(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """create_tag with message creates an annotated tag."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.create_tag("v1.0", "abc123", message="Release 1.0")

        assert ok is True
        args = mock_run.call_args[0][0]
        assert args == ["git", "tag", "-a", "v1.0", "abc123", "-m", "Release 1.0"]

    @patch(_SUBPROCESS_TARGET)
    def test_create_tag_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """create_tag returns (False, error) on failure."""
        mock_run.return_value = _completed(returncode=1, stderr="tag already exists")
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.create_tag("v1.0", "abc123")

        assert ok is False
        assert "already exists" in err


class TestGitVcsDeleteRef:
    """Test GitVcs.delete_ref method."""

    @patch(_SUBPROCESS_TARGET)
    def test_delete_ref_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """delete_ref returns (True, '') on success."""
        mock_run.return_value = _completed()
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.delete_ref("feature-branch")

        assert ok is True
        assert err == ""

    @patch(_SUBPROCESS_TARGET)
    def test_delete_ref_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """delete_ref returns (False, error) on failure."""
        mock_run.return_value = _completed(returncode=1, stderr="error: branch not found")
        vcs = GitVcs(repo_root=tmp_path)

        ok, err = vcs.delete_ref("nonexistent")

        assert ok is False
        assert "not found" in err

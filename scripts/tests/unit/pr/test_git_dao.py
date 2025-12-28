import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.pr import git_dao


def mock_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Create a mock CompletedProcess."""
    return subprocess.CompletedProcess(
        args=["git"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestGetStatus:
    def test_returns_status_on_success(self, tmp_path: Path) -> None:
        """Should return status output when git succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="M file.py\n")
            status, error = git_dao.get_status(tmp_path)

        assert status == "M file.py"
        assert error is None

    def test_returns_empty_for_clean_repo(self, tmp_path: Path) -> None:
        """Should return empty string for clean repository."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="")
            status, error = git_dao.get_status(tmp_path)

        assert status == ""
        assert error is None

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            status, error = git_dao.get_status(tmp_path)

        assert status == ""
        assert error == "git is not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="fatal: not a git repository",
            )
            status, error = git_dao.get_status(tmp_path)

        assert status == ""
        assert error == "fatal: not a git repository"

    def test_returns_default_error_when_stderr_empty(self, tmp_path: Path) -> None:
        """Should return default error when stderr is empty."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1, stderr="")
            status, error = git_dao.get_status(tmp_path)

        assert status == ""
        assert error == "git status failed"


class TestStageAll:
    def test_returns_true_on_success(self, tmp_path: Path) -> None:
        """Should return True when staging succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            result = git_dao.stage_all(tmp_path)

        assert result is True

    def test_returns_false_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return False when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.stage_all(tmp_path)

        assert result is False

    def test_returns_false_on_git_failure(self, tmp_path: Path) -> None:
        """Should return False when git fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.stage_all(tmp_path)

        assert result is False


class TestCommit:
    def test_returns_true_on_success(self, tmp_path: Path) -> None:
        """Should return True when commit succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            result = git_dao.commit(tmp_path, "Test commit")

        assert result is True

    def test_returns_false_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return False when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.commit(tmp_path, "Test commit")

        assert result is False

    def test_returns_false_on_git_failure(self, tmp_path: Path) -> None:
        """Should return False when commit fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.commit(tmp_path, "Test commit")

        assert result is False


class TestPush:
    def test_returns_success_on_push(self, tmp_path: Path) -> None:
        """Should return success tuple when push succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.push(tmp_path)

        assert success is True
        assert error == ""

    def test_returns_success_with_set_upstream(self, tmp_path: Path) -> None:
        """Should return success when pushing with upstream."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.push(tmp_path, set_upstream=True)

        assert success is True
        assert error == ""
        # Verify the command included -u flag
        call_args = mock_run.call_args[0][0]
        assert "-u" in call_args
        assert "origin" in call_args
        assert "HEAD" in call_args

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.push(tmp_path)

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="error: failed to push",
            )
            success, error = git_dao.push(tmp_path)

        assert success is False
        assert error == "error: failed to push"


class TestFetchBranch:
    def test_returns_success_on_fetch(self, tmp_path: Path) -> None:
        """Should return success tuple when fetch succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.fetch_branch(tmp_path, "main")

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.fetch_branch(tmp_path, "main")

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="fatal: couldn't find remote ref main",
            )
            success, error = git_dao.fetch_branch(tmp_path, "main")

        assert success is False
        assert error == "fatal: couldn't find remote ref main"


class TestCountCommitsAhead:
    def test_returns_count_on_success(self, tmp_path: Path) -> None:
        """Should return commit count when successful."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="5\n")
            count, error = git_dao.count_commits_ahead(tmp_path, "main")

        assert count == 5
        assert error == ""

    def test_returns_zero_when_even(self, tmp_path: Path) -> None:
        """Should return 0 when branch is even with base."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="0\n")
            count, error = git_dao.count_commits_ahead(tmp_path, "main")

        assert count == 0
        assert error == ""

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            count, error = git_dao.count_commits_ahead(tmp_path, "main")

        assert count == -1
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="fatal: bad revision",
            )
            count, error = git_dao.count_commits_ahead(tmp_path, "main")

        assert count == -1
        assert error == "fatal: bad revision"


class TestGetMergeBase:
    def test_returns_sha_on_success(self, tmp_path: Path) -> None:
        """Should return merge base SHA when successful."""
        sha = "abc123def456"
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout=f"{sha}\n")
            result, error = git_dao.get_merge_base(tmp_path, "main")

        assert result == sha
        assert error == ""

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result, error = git_dao.get_merge_base(tmp_path, "main")

        assert result == ""
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="fatal: Not a valid object name",
            )
            result, error = git_dao.get_merge_base(tmp_path, "main")

        assert result == ""
        assert error == "fatal: Not a valid object name"


class TestGetLastCommitMessage:
    def test_returns_message_on_success(self, tmp_path: Path) -> None:
        """Should return commit message when successful."""
        message = "feat: add new feature"
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout=f"{message}\n")
            result = git_dao.get_last_commit_message(tmp_path)

        assert result == message

    def test_returns_default_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return default message when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.get_last_commit_message(tmp_path)

        assert result == "Squashed commits"

    def test_returns_default_on_git_failure(self, tmp_path: Path) -> None:
        """Should return default message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.get_last_commit_message(tmp_path)

        assert result == "Squashed commits"


class TestSoftReset:
    def test_returns_success(self, tmp_path: Path) -> None:
        """Should return success when reset succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.soft_reset(tmp_path, "abc123")

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.soft_reset(tmp_path, "abc123")

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="fatal: ambiguous argument",
            )
            success, error = git_dao.soft_reset(tmp_path, "abc123")

        assert success is False
        assert error == "fatal: ambiguous argument"


class TestRebase:
    def test_returns_success(self, tmp_path: Path) -> None:
        """Should return success when rebase succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, has_conflicts, error = git_dao.rebase(tmp_path, "main")

        assert success is True
        assert has_conflicts is False
        assert error == ""

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, has_conflicts, error = git_dao.rebase(tmp_path, "main")

        assert success is False
        assert has_conflicts is False
        assert error == "git not available"

    def test_detects_conflicts_in_stdout(self, tmp_path: Path) -> None:
        """Should detect conflicts from stdout."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stdout="CONFLICT (content): Merge conflict in file.py",
            )
            success, has_conflicts, _error = git_dao.rebase(tmp_path, "main")

        assert success is False
        assert has_conflicts is True

    def test_detects_conflicts_in_stderr(self, tmp_path: Path) -> None:
        """Should detect conflicts from stderr."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="CONFLICT (content): Merge conflict",
            )
            success, has_conflicts, _error = git_dao.rebase(tmp_path, "main")

        assert success is False
        assert has_conflicts is True


class TestGetRepoRoot:
    def test_returns_path_on_success(self) -> None:
        """Should return Path when successful."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="/home/user/repo\n")
            result = git_dao.get_repo_root()

        assert result == Path("/home/user/repo")

    def test_returns_none_when_git_unavailable(self) -> None:
        """Should return None when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.get_repo_root()

        assert result is None

    def test_returns_none_on_git_failure(self) -> None:
        """Should return None on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.get_repo_root()

        assert result is None


class TestRemoveWorktree:
    def test_returns_success(self, tmp_path: Path) -> None:
        """Should return success when removal succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            # First call is get_repo_root, second is worktree remove
            mock_run.side_effect = [
                mock_completed_process(stdout="/home/user/repo\n"),
                mock_completed_process(returncode=0),
            ]
            success, error = git_dao.remove_worktree(tmp_path)

        assert success is True
        assert error == ""

    def test_returns_error_when_not_in_repo(self, tmp_path: Path) -> None:
        """Should return error when not in a git repo."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            success, error = git_dao.remove_worktree(tmp_path)

        assert success is False
        assert error == "not in a git repo"

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="/home/user/repo\n"),
                None,
            ]
            success, error = git_dao.remove_worktree(tmp_path)

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="/home/user/repo\n"),
                mock_completed_process(returncode=1, stderr="worktree not found"),
            ]
            success, error = git_dao.remove_worktree(tmp_path)

        assert success is False
        assert error == "worktree not found"


class TestDeleteBranch:
    def test_returns_success(self) -> None:
        """Should return success when deletion succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.delete_branch("feature-branch")

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.delete_branch("feature-branch")

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="error: branch not found",
            )
            success, error = git_dao.delete_branch("feature-branch")

        assert success is False
        assert error == "error: branch not found"


class TestFetchAllPrune:
    def test_calls_git_fetch(self) -> None:
        """Should call git fetch with correct arguments."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            git_dao.fetch_all_prune()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "fetch" in call_args
        assert "--all" in call_args
        assert "--prune" in call_args

    def test_ignores_git_unavailable(self) -> None:
        """Should silently ignore when git is unavailable."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            # Should not raise
            git_dao.fetch_all_prune()


class TestStash:
    def test_returns_true_when_changes_stashed(self) -> None:
        """Should return True when changes were stashed."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                stdout="Saved working directory and index state"
            )
            result = git_dao.stash()

        assert result is True

    def test_returns_false_when_no_changes(self) -> None:
        """Should return False when no changes to stash."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="No local changes to save")
            result = git_dao.stash()

        assert result is False

    def test_returns_false_when_git_unavailable(self) -> None:
        """Should return False when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.stash()

        assert result is False

    def test_returns_false_on_git_failure(self) -> None:
        """Should return False when git fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.stash()

        assert result is False


class TestStashPop:
    def test_returns_success(self) -> None:
        """Should return success when pop succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.stash_pop()

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.stash_pop()

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="No stash entries found",
            )
            success, error = git_dao.stash_pop()

        assert success is False
        assert error == "No stash entries found"


class TestCheckout:
    def test_returns_success(self) -> None:
        """Should return success when checkout succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.checkout("main")

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.checkout("main")

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="error: pathspec 'main' did not match",
            )
            success, error = git_dao.checkout("main")

        assert success is False
        assert error == "error: pathspec 'main' did not match"


class TestPull:
    def test_returns_success(self) -> None:
        """Should return success when pull succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.pull()

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.pull()

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="error: cannot pull with rebase",
            )
            success, error = git_dao.pull()

        assert success is False
        assert error == "error: cannot pull with rebase"


class TestBranchExistsLocal:
    def test_returns_true_when_exists(self) -> None:
        """Should return True when branch exists locally."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            result = git_dao.branch_exists_local("feature-branch")

        assert result is True

    def test_returns_false_when_not_exists(self) -> None:
        """Should return False when branch does not exist."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.branch_exists_local("feature-branch")

        assert result is False

    def test_returns_false_when_git_unavailable(self) -> None:
        """Should return False when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.branch_exists_local("feature-branch")

        assert result is False


class TestBranchExistsRemote:
    def test_returns_true_when_exists(self) -> None:
        """Should return True when branch exists on remote."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                stdout="abc123\trefs/heads/feature-branch\n"
            )
            result = git_dao.branch_exists_remote("feature-branch")

        assert result is True

    def test_returns_false_when_not_exists(self) -> None:
        """Should return False when branch does not exist."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="")
            result = git_dao.branch_exists_remote("feature-branch")

        assert result is False

    def test_returns_false_when_git_unavailable(self) -> None:
        """Should return False when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.branch_exists_remote("feature-branch")

        assert result is False

    def test_returns_false_on_git_failure(self) -> None:
        """Should return False when git fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.branch_exists_remote("feature-branch")

        assert result is False

    def test_exact_match_not_partial(self) -> None:
        """Should not match partial branch names."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            # "foo" should not match "foobar"
            mock_run.return_value = mock_completed_process(stdout="abc123\trefs/heads/foobar\n")
            result = git_dao.branch_exists_remote("foo")

        assert result is False


class TestBranchExists:
    def test_returns_true_when_exists_locally(self) -> None:
        """Should return True when branch exists locally."""
        with (
            patch("scripts.pr.git_dao.branch_exists_local", return_value=True),
            patch("scripts.pr.git_dao.branch_exists_remote", return_value=False),
        ):
            result = git_dao.branch_exists("feature-branch")

        assert result is True

    def test_returns_true_when_exists_remotely(self) -> None:
        """Should return True when branch exists on remote."""
        with (
            patch("scripts.pr.git_dao.branch_exists_local", return_value=False),
            patch("scripts.pr.git_dao.branch_exists_remote", return_value=True),
        ):
            result = git_dao.branch_exists("feature-branch")

        assert result is True

    def test_returns_false_when_not_exists(self) -> None:
        """Should return False when branch does not exist anywhere."""
        with (
            patch("scripts.pr.git_dao.branch_exists_local", return_value=False),
            patch("scripts.pr.git_dao.branch_exists_remote", return_value=False),
        ):
            result = git_dao.branch_exists("feature-branch")

        assert result is False


class TestGetCurrentBranch:
    def test_returns_branch_name(self) -> None:
        """Should return branch name when successful."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="feature-branch\n")
            result = git_dao.get_current_branch()

        assert result == "feature-branch"

    def test_returns_none_when_git_unavailable(self) -> None:
        """Should return None when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.get_current_branch()

        assert result is None

    def test_returns_none_on_git_failure(self) -> None:
        """Should return None on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.get_current_branch()

        assert result is None

    def test_returns_none_when_detached_head(self) -> None:
        """Should return None when in detached HEAD state."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="")
            result = git_dao.get_current_branch()

        assert result is None


class TestIsInsideWorktree:
    def test_returns_true_when_in_worktree(self) -> None:
        """Should return True when inside a worktree."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="/repo/.git/worktrees/feature\n"),
                mock_completed_process(stdout="/repo/.git\n"),
            ]
            result = git_dao.is_inside_worktree()

        assert result is True

    def test_returns_false_when_in_main_repo(self) -> None:
        """Should return False when in main repository."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="/repo/.git\n"),
                mock_completed_process(stdout="/repo/.git\n"),
            ]
            result = git_dao.is_inside_worktree()

        assert result is False

    def test_returns_false_when_git_unavailable(self) -> None:
        """Should return False when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.is_inside_worktree()

        assert result is False

    def test_returns_false_on_git_failure(self) -> None:
        """Should return False when git fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(returncode=0, stdout="/repo/.git"),
                mock_completed_process(returncode=1),
            ]
            result = git_dao.is_inside_worktree()

        assert result is False


class TestFetchOrigin:
    def test_returns_success(self) -> None:
        """Should return success when fetch succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.fetch_origin()

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.fetch_origin()

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="Could not resolve host: github.com",
            )
            success, error = git_dao.fetch_origin()

        assert success is False
        assert error == "Could not resolve host: github.com"


class TestCreateWorktree:
    def test_returns_success_with_new_branch(self, tmp_path: Path) -> None:
        """Should return success when creating worktree with new branch."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.create_worktree(tmp_path, "new-branch", True)

        assert success is True
        assert error == ""
        # Verify -b flag was included
        call_args = mock_run.call_args[0][0]
        assert "-b" in call_args

    def test_returns_success_with_existing_branch(self, tmp_path: Path) -> None:
        """Should return success when creating worktree for existing branch."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.create_worktree(tmp_path, "existing-branch", False)

        assert success is True
        assert error == ""
        # Verify -b flag was NOT included
        call_args = mock_run.call_args[0][0]
        assert "-b" not in call_args

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.create_worktree(tmp_path, "branch", True)

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="fatal: 'branch' is already checked out",
            )
            success, error = git_dao.create_worktree(tmp_path, "branch", True)

        assert success is False
        assert error == "fatal: 'branch' is already checked out"


class TestWorktreeExists:
    def test_returns_true_when_exists(self, tmp_path: Path) -> None:
        """Should return True when worktree exists."""
        # Create a real directory for path comparison
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                stdout=f"worktree {worktree_path}\nHEAD abc123\nbranch refs/heads/main\n"
            )
            result = git_dao.worktree_exists(worktree_path)

        assert result is True

    def test_returns_false_when_not_exists(self, tmp_path: Path) -> None:
        """Should return False when worktree does not exist."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                stdout="worktree /other/path\nHEAD abc123\nbranch refs/heads/main\n"
            )
            result = git_dao.worktree_exists(tmp_path / "worktree")

        assert result is False

    def test_returns_false_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return False when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.worktree_exists(tmp_path / "worktree")

        assert result is False

    def test_returns_false_on_git_failure(self, tmp_path: Path) -> None:
        """Should return False when git fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.worktree_exists(tmp_path / "worktree")

        assert result is False


class TestCreateWorktreeTracking:
    def test_returns_success(self, tmp_path: Path) -> None:
        """Should return success when creating tracking worktree."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.create_worktree_tracking(tmp_path, "remote-branch")

        assert success is True
        assert error == ""
        # Verify --track flag was included
        call_args = mock_run.call_args[0][0]
        assert "--track" in call_args

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.create_worktree_tracking(tmp_path, "remote-branch")

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="fatal: remote branch not found",
            )
            success, error = git_dao.create_worktree_tracking(tmp_path, "remote-branch")

        assert success is False
        assert error == "fatal: remote branch not found"


class TestGetConflictedFiles:
    def test_returns_conflicted_files(self, tmp_path: Path) -> None:
        """Should return list of conflicted files."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                stdout="UU file1.py\nUU src/file2.py\nM  other.py\n"
            )
            result = git_dao.get_conflicted_files(tmp_path)

        assert result == ["file1.py", "src/file2.py"]

    def test_returns_empty_when_no_conflicts(self, tmp_path: Path) -> None:
        """Should return empty list when no conflicts."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="M  file.py\n")
            result = git_dao.get_conflicted_files(tmp_path)

        assert result == []

    def test_returns_empty_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return empty list when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.get_conflicted_files(tmp_path)

        assert result == []

    def test_returns_empty_on_git_failure(self, tmp_path: Path) -> None:
        """Should return empty list on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.get_conflicted_files(tmp_path)

        assert result == []


class TestGetCommitsBetween:
    def test_returns_commit_list(self, tmp_path: Path) -> None:
        """Should return list of commit SHAs."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                stdout="abc123 First commit\ndef456 Second commit\n"
            )
            result = git_dao.get_commits_between(tmp_path, "base", "target")

        assert result == ["abc123", "def456"]

    def test_returns_empty_when_no_commits(self, tmp_path: Path) -> None:
        """Should return empty list when no commits between refs."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="")
            result = git_dao.get_commits_between(tmp_path, "base", "target")

        assert result == []

    def test_returns_empty_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return empty list when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.get_commits_between(tmp_path, "base", "target")

        assert result == []

    def test_returns_empty_on_git_failure(self, tmp_path: Path) -> None:
        """Should return empty list on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.get_commits_between(tmp_path, "base", "target")

        assert result == []


class TestGetHeadSha:
    def test_returns_sha(self, tmp_path: Path) -> None:
        """Should return HEAD SHA."""
        sha = "abc123def456789"
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(stdout=f"{sha}\n")
            result = git_dao.get_head_sha(tmp_path)

        assert result == sha

    def test_returns_empty_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return empty string when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            result = git_dao.get_head_sha(tmp_path)

        assert result == ""

    def test_returns_empty_on_git_failure(self, tmp_path: Path) -> None:
        """Should return empty string on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=1)
            result = git_dao.get_head_sha(tmp_path)

        assert result == ""


class TestForcePush:
    def test_returns_success(self, tmp_path: Path) -> None:
        """Should return success when force push succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(returncode=0)
            success, error = git_dao.force_push(tmp_path)

        assert success is True
        assert error == ""

    def test_returns_error_when_git_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.force_push(tmp_path)

        assert success is False
        assert error == "git not available"

    def test_returns_error_on_git_failure(self, tmp_path: Path) -> None:
        """Should return error message on git failure."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="error: rejected - protected branch",
            )
            success, error = git_dao.force_push(tmp_path)

        assert success is False
        assert error == "error: rejected - protected branch"


class TestResetHardToRemote:
    def test_returns_success(self, tmp_path: Path) -> None:
        """Should return success when reset succeeds."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(returncode=0),  # fetch
                mock_completed_process(returncode=0),  # reset
            ]
            success, error = git_dao.reset_hard_to_remote(tmp_path, "main")

        assert success is True
        assert error == ""

    def test_returns_error_when_fetch_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available during fetch."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.reset_hard_to_remote(tmp_path, "main")

        assert success is False
        assert error == "git not available"

    def test_returns_error_when_fetch_fails(self, tmp_path: Path) -> None:
        """Should return error when fetch fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="Could not resolve host",
            )
            success, error = git_dao.reset_hard_to_remote(tmp_path, "main")

        assert success is False
        assert "fetch failed" in error

    def test_returns_error_when_reset_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available during reset."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(returncode=0),  # fetch succeeds
                None,  # reset - git not available
            ]
            success, error = git_dao.reset_hard_to_remote(tmp_path, "main")

        assert success is False
        assert error == "git not available"

    def test_returns_error_when_reset_fails(self, tmp_path: Path) -> None:
        """Should return error when reset fails."""
        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(returncode=0),  # fetch succeeds
                mock_completed_process(returncode=1, stderr="ambiguous argument"),
            ]
            success, error = git_dao.reset_hard_to_remote(tmp_path, "main")

        assert success is False
        assert "reset failed" in error


class TestCreateSharedClone:
    def test_returns_success(self, tmp_path: Path) -> None:
        """Should return success when clone creation succeeds."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(
                    stdout="https://github.com/org/repo.git\n"
                ),  # get remote URL
                mock_completed_process(stdout="Test User\n"),  # user.name
                mock_completed_process(stdout="test@example.com\n"),  # user.email
                mock_completed_process(stdout="ABCD1234\n"),  # signingkey
                mock_completed_process(stdout="true\n"),  # gpgsign
                mock_completed_process(returncode=0),  # git init
                mock_completed_process(returncode=0),  # remote add
                mock_completed_process(returncode=0),  # config user.name
                mock_completed_process(returncode=0),  # config user.email
                mock_completed_process(returncode=0),  # config signingkey
                mock_completed_process(returncode=0),  # config gpgsign
                mock_completed_process(returncode=0),  # fetch
                mock_completed_process(returncode=0),  # checkout
            ]
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is True
        assert error == ""

    def test_returns_error_when_get_remote_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git is not available."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = None
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is False
        assert error == "git not available"

    def test_returns_error_when_get_remote_fails(self, tmp_path: Path) -> None:
        """Should return error when getting remote URL fails."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.return_value = mock_completed_process(
                returncode=1,
                stderr="No such remote 'origin'",
            )
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is False
        assert "failed to get remote URL" in error

    def test_returns_error_when_init_unavailable(self, tmp_path: Path) -> None:
        """Should return error when git init is not available."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="https://github.com/org/repo.git\n"),
                mock_completed_process(returncode=1),  # user.name fails (ok)
                mock_completed_process(returncode=1),  # user.email fails (ok)
                mock_completed_process(returncode=1),  # signingkey fails (ok)
                mock_completed_process(returncode=1),  # gpgsign fails (ok)
                None,  # git init not available
            ]
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is False
        assert error == "git not available"

    def test_returns_error_when_init_fails(self, tmp_path: Path) -> None:
        """Should return error when git init fails."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="https://github.com/org/repo.git\n"),
                mock_completed_process(returncode=1),  # user.name
                mock_completed_process(returncode=1),  # user.email
                mock_completed_process(returncode=1),  # signingkey
                mock_completed_process(returncode=1),  # gpgsign
                mock_completed_process(returncode=1, stderr="init error"),  # git init fails
            ]
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is False
        assert "git init failed" in error

    def test_returns_error_when_remote_add_fails(self, tmp_path: Path) -> None:
        """Should return error when remote add fails."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="https://github.com/org/repo.git\n"),
                mock_completed_process(returncode=1),  # user.name
                mock_completed_process(returncode=1),  # user.email
                mock_completed_process(returncode=1),  # signingkey
                mock_completed_process(returncode=1),  # gpgsign
                mock_completed_process(returncode=0),  # git init
                mock_completed_process(
                    returncode=1, stderr="remote add failed"
                ),  # remote add fails
            ]
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is False
        assert "failed to add remote" in error

    def test_returns_error_when_fetch_fails(self, tmp_path: Path) -> None:
        """Should return error when fetch fails."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="https://github.com/org/repo.git\n"),
                mock_completed_process(returncode=1),  # user.name
                mock_completed_process(returncode=1),  # user.email
                mock_completed_process(returncode=1),  # signingkey
                mock_completed_process(returncode=1),  # gpgsign
                mock_completed_process(returncode=0),  # git init
                mock_completed_process(returncode=0),  # remote add
                mock_completed_process(returncode=1, stderr="fetch failed"),  # fetch fails
            ]
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is False
        assert "failed to fetch branch" in error

    def test_returns_error_when_checkout_fails(self, tmp_path: Path) -> None:
        """Should return error when checkout fails."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="https://github.com/org/repo.git\n"),
                mock_completed_process(returncode=1),  # user.name
                mock_completed_process(returncode=1),  # user.email
                mock_completed_process(returncode=1),  # signingkey
                mock_completed_process(returncode=1),  # gpgsign
                mock_completed_process(returncode=0),  # git init
                mock_completed_process(returncode=0),  # remote add
                mock_completed_process(returncode=0),  # fetch
                mock_completed_process(returncode=1, stderr="checkout failed"),  # checkout fails
            ]
            success, error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is False
        assert "checkout failed" in error

    def test_cleans_existing_clone_path(self, tmp_path: Path) -> None:
        """Should clean existing clone path before creating new clone."""
        source = tmp_path / "source"
        source.mkdir()
        clone = tmp_path / "clone"
        clone.mkdir()
        (clone / "existing_file.txt").write_text("existing")

        with patch("scripts.pr.git_dao._run_git") as mock_run:
            mock_run.side_effect = [
                mock_completed_process(stdout="https://github.com/org/repo.git\n"),
                mock_completed_process(returncode=1),  # user.name
                mock_completed_process(returncode=1),  # user.email
                mock_completed_process(returncode=1),  # signingkey
                mock_completed_process(returncode=1),  # gpgsign
                mock_completed_process(returncode=0),  # git init
                mock_completed_process(returncode=0),  # remote add
                mock_completed_process(returncode=0),  # fetch
                mock_completed_process(returncode=0),  # checkout
            ]
            success, _error = git_dao.create_shared_clone(source, clone, "feature-branch")

        assert success is True
        # The existing file should have been removed
        assert not (clone / "existing_file.txt").exists()


class TestRemoveSharedClone:
    def test_returns_error_on_remove_failure(self, tmp_path: Path) -> None:
        """Should return error when removal fails."""
        clone = tmp_path / "clone"
        clone.mkdir()

        with patch("shutil.rmtree") as mock_rmtree:
            mock_rmtree.side_effect = OSError("Permission denied")
            success, error = git_dao.remove_shared_clone(clone)

        assert success is False
        assert "Permission denied" in error


class TestRunGit:
    def test_returns_completed_process_on_success(self) -> None:
        """Should return CompletedProcess when git command succeeds."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = mock_completed_process(stdout="output")
            result = git_dao._run_git(["git", "status"])

        assert result is not None
        assert result.stdout == "output"

    def test_returns_none_on_file_not_found(self) -> None:
        """Should return None when git is not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = git_dao._run_git(["git", "status"])

        assert result is None

    def test_returns_none_on_os_error(self) -> None:
        """Should return None on OSError."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError()
            result = git_dao._run_git(["git", "status"])

        assert result is None

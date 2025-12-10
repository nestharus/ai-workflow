"""Sandbox git operations for isolated rebase/merge.

Provides functions for managing a persistent sandbox checkout and running
rebase/merge operations safely isolated from the user's main checkout.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_git(
    args: list[str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run a git command safely, catching missing git errors.

    Args:
        args: Command arguments (including "git").
        cwd: Working directory.

    Returns:
        CompletedProcess result, or None if git is not available.
    """
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None


@dataclass
class OperationResult:
    """Result of a git operation (rebase or merge)."""

    success: bool
    has_conflicts: bool
    conflicts: list[str]
    error: str


# Type aliases for semantic clarity - callers can use distinct names
RebaseResult = OperationResult
MergeResult = OperationResult


def _get_remote_url(repo_path: Path) -> tuple[str, str]:
    """Get the origin remote URL from a repository.

    Args:
        repo_path: Path to the repository.

    Returns:
        Tuple of (url, error_message). URL is empty on error.
    """
    result = _run_git(["git", "remote", "get-url", "origin"], cwd=repo_path)
    if result is None:
        return "", "git not available"
    if result.returncode != 0:
        return "", f"failed to get remote URL: {result.stderr}"
    url = result.stdout.strip()
    if not url:
        return "", "remote URL is empty"
    return url, ""


def _get_git_config(repo_path: Path, key: str) -> str | None:
    """Get a git config value from a repository.

    Args:
        repo_path: Path to the repository.
        key: Config key (e.g., "user.name").

    Returns:
        Config value, or None if not set or git unavailable.
    """
    result = _run_git(["git", "config", "--", key], cwd=repo_path)
    if result and result.returncode == 0:
        return result.stdout.strip()
    return None


def _set_git_config(repo_path: Path, key: str, value: str) -> bool:
    """Set a git config value in a repository.

    Args:
        repo_path: Path to the repository.
        key: Config key (e.g., "user.name").
        value: Value to set.

    Returns:
        True if successful, False otherwise.
    """
    result = _run_git(["git", "config", "--", key, value], cwd=repo_path)
    return result is not None and result.returncode == 0


def ensure_sandbox_exists(repo_root: Path) -> Path:
    """Ensure the sandbox directory exists and is initialized.

    Creates the sandbox as a git repository that shares the same remote origin
    as the main repository. The sandbox is created in .git/sandbox/ to be
    automatically ignored by git.

    Args:
        repo_root: Path to the main repository root.

    Returns:
        Path to the sandbox directory.

    Raises:
        RuntimeError: If sandbox creation fails.
    """
    # Resolve the real git dir (handles worktrees and gitfile .git)
    git_dir_result = _run_git(["git", "rev-parse", "--git-dir"], cwd=repo_root)
    if git_dir_result is None or git_dir_result.returncode != 0:
        err_msg = git_dir_result.stderr if git_dir_result else "git not available"
        raise RuntimeError(f"Failed to resolve git dir: {err_msg}")
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (repo_root / git_dir).resolve()
    sandbox_path = git_dir / "sandbox"

    # If sandbox already exists and is a valid git repo, return it
    if sandbox_path.exists():
        # Use git rev-parse to detect a valid repo (handles .git as file or directory)
        check_result = _run_git(["git", "rev-parse", "--git-dir"], cwd=sandbox_path)
        if check_result is not None and check_result.returncode == 0:
            return sandbox_path

    # Get remote URL and user config from main repo.
    # NOTE: The sandbox assumes a single 'origin' remote and clones only that.
    # Additional remotes configured in the main repo are not copied to the sandbox.
    # If your workflow requires multiple remotes, you'll need to add them manually
    # to the sandbox after it's created.
    remote_url, err = _get_remote_url(repo_root)
    if err:
        raise RuntimeError(f"Cannot get remote URL from main repo: {err}")

    user_name = _get_git_config(repo_root, "user.name")
    user_email = _get_git_config(repo_root, "user.email")

    # Clean up any partial sandbox
    if sandbox_path.exists():
        if sandbox_path.is_dir():
            shutil.rmtree(sandbox_path, ignore_errors=True)
        else:
            sandbox_path.unlink()

    # Create sandbox directory
    sandbox_path.mkdir(parents=True, exist_ok=True)

    # Initialize git repo
    result = _run_git(["git", "init"], cwd=sandbox_path)
    if result is None or result.returncode != 0:
        shutil.rmtree(sandbox_path, ignore_errors=True)
        err_msg = result.stderr if result else "git not available"
        raise RuntimeError(f"Failed to initialize sandbox: {err_msg}")

    # Add origin remote
    result = _run_git(["git", "remote", "add", "origin", remote_url], cwd=sandbox_path)
    if result is None or result.returncode != 0:
        shutil.rmtree(sandbox_path, ignore_errors=True)
        err_msg = result.stderr if result else "git not available"
        raise RuntimeError(f"Failed to add remote: {err_msg}")

    # Copy user config
    if user_name:
        _set_git_config(sandbox_path, "user.name", user_name)
    if user_email:
        _set_git_config(sandbox_path, "user.email", user_email)

    return sandbox_path


def sync_sandbox_branch(sandbox_path: Path, branch: str) -> tuple[bool, str]:
    """Fetch and checkout a branch in the sandbox.

    Fetches the latest from origin and checks out the specified branch,
    resetting to match the remote state.

    Args:
        sandbox_path: Path to the sandbox directory.
        branch: Branch name to checkout.

    Returns:
        Tuple of (success, error_message).
    """
    # Fetch latest from origin
    result = _run_git(["git", "fetch", "origin"], cwd=sandbox_path)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, f"fetch failed: {result.stderr}"

    # Abort any in-progress rebase
    _run_git(["git", "rebase", "--abort"], cwd=sandbox_path)

    # Abort any in-progress merge
    _run_git(["git", "merge", "--abort"], cwd=sandbox_path)

    # Check if branch exists locally
    result = _run_git(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=sandbox_path,
    )
    branch_exists_local = result is not None and result.returncode == 0

    if branch_exists_local:
        # Checkout existing branch
        result = _run_git(["git", "checkout", branch], cwd=sandbox_path)
        if result is None or result.returncode != 0:
            err_msg = result.stderr if result else "git not available"
            return False, f"checkout failed: {err_msg}"

        # Hard reset to match remote
        result = _run_git(["git", "reset", "--hard", f"origin/{branch}"], cwd=sandbox_path)
        if result is None or result.returncode != 0:
            err_msg = result.stderr if result else "git not available"
            return False, f"reset failed: {err_msg}"
    else:
        # Create new branch tracking remote
        result = _run_git(
            ["git", "checkout", "-b", branch, f"origin/{branch}"],
            cwd=sandbox_path,
        )
        if result is None or result.returncode != 0:
            err_msg = result.stderr if result else "git not available"
            return False, f"checkout failed: {err_msg}"

    return True, ""


def get_conflicts(sandbox_path: Path) -> list[str]:
    """Get list of files with conflicts in the sandbox.

    Args:
        sandbox_path: Path to the sandbox directory.

    Returns:
        List of file paths with conflicts.
    """
    # Get status with porcelain format
    result = _run_git(["git", "status", "--porcelain"], cwd=sandbox_path)
    if result is None:
        logger.error(
            "Conflict detection failed: git not available in sandbox at %s",
            sandbox_path,
        )
        return []
    if result.returncode != 0:
        logger.error(
            "Conflict detection failed: git status returned non-zero exit code "
            "(rc=%d, stderr=%s) in sandbox at %s",
            result.returncode,
            result.stderr.strip() if result.stderr else "(empty)",
            sandbox_path,
        )
        return []

    conflicts = []
    for line in result.stdout.splitlines():
        if len(line) >= 3:
            # Check for conflict markers (UU, AA, DD, AU, UA, DU, UD)
            status = line[:2]
            if "U" in status or status == "AA" or status == "DD":
                # Find first space after status field to get file path
                space = line.find(" ")
                if space != -1:
                    conflicts.append(line[space + 1 :])

    return conflicts


def rebase_in_sandbox(sandbox_path: Path, branch: str, target: str) -> RebaseResult:
    """Perform a rebase operation in the sandbox.

    Rebases the specified branch onto the target branch.

    Args:
        sandbox_path: Path to the sandbox directory.
        branch: Branch to rebase.
        target: Target branch to rebase onto.

    Returns:
        RebaseResult with operation outcome.
    """
    # Sync the branch first
    success, err = sync_sandbox_branch(sandbox_path, branch)
    if not success:
        return RebaseResult(success=False, has_conflicts=False, conflicts=[], error=err)

    # Fetch target branch
    result = _run_git(["git", "fetch", "origin", target], cwd=sandbox_path)
    if result is None or result.returncode != 0:
        err_msg = result.stderr if result else "git not available"
        return RebaseResult(
            success=False,
            has_conflicts=False,
            conflicts=[],
            error=f"fetch target failed: {err_msg}",
        )

    # Perform rebase
    result = _run_git(["git", "rebase", f"origin/{target}"], cwd=sandbox_path)
    if result is None:
        return RebaseResult(
            success=False,
            has_conflicts=False,
            conflicts=[],
            error="git not available",
        )

    if result.returncode != 0:
        # Check if it's a conflict
        conflicts = get_conflicts(sandbox_path)
        if conflicts:
            return RebaseResult(
                success=False,
                has_conflicts=True,
                conflicts=conflicts,
                error="rebase stopped due to conflicts",
            )
        return RebaseResult(
            success=False,
            has_conflicts=False,
            conflicts=[],
            error=f"rebase failed: {result.stderr}",
        )

    return RebaseResult(success=True, has_conflicts=False, conflicts=[], error="")


def merge_in_sandbox(sandbox_path: Path, branch: str, target: str) -> MergeResult:
    """Perform a merge operation in the sandbox.

    Merges the target branch into the specified branch.

    Args:
        sandbox_path: Path to the sandbox directory.
        branch: Branch to merge into.
        target: Target branch to merge from.

    Returns:
        MergeResult with operation outcome.
    """
    # Sync the branch first
    success, err = sync_sandbox_branch(sandbox_path, branch)
    if not success:
        return MergeResult(success=False, has_conflicts=False, conflicts=[], error=err)

    # Fetch target branch
    result = _run_git(["git", "fetch", "origin", target], cwd=sandbox_path)
    if result is None or result.returncode != 0:
        err_msg = result.stderr if result else "git not available"
        return MergeResult(
            success=False,
            has_conflicts=False,
            conflicts=[],
            error=f"fetch target failed: {err_msg}",
        )

    # Perform merge
    result = _run_git(["git", "merge", f"origin/{target}"], cwd=sandbox_path)
    if result is None:
        return MergeResult(
            success=False,
            has_conflicts=False,
            conflicts=[],
            error="git not available",
        )

    if result.returncode != 0:
        # Check if it's a conflict
        conflicts = get_conflicts(sandbox_path)
        if conflicts:
            return MergeResult(
                success=False,
                has_conflicts=True,
                conflicts=conflicts,
                error="merge stopped due to conflicts",
            )
        return MergeResult(
            success=False,
            has_conflicts=False,
            conflicts=[],
            error=f"merge failed: {result.stderr}",
        )

    return MergeResult(success=True, has_conflicts=False, conflicts=[], error="")


def push_from_sandbox(sandbox_path: Path, branch: str, force: bool = False) -> tuple[bool, str]:
    """Push changes from sandbox to origin.

    Args:
        sandbox_path: Path to the sandbox directory.
        branch: Branch to push.
        force: If True, force push.

    Returns:
        Tuple of (success, error_message).
    """
    cmd = ["git", "push", "origin", branch]
    if force:
        cmd.insert(2, "--force-with-lease")

    result = _run_git(cmd, cwd=sandbox_path)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, f"push failed: {result.stderr}"
    return True, ""

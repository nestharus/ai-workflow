"""Git data access operations.

Provides low-level functions for git operations via subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_status(worktree: Path) -> str:
    """Get git status output.

    Args:
        worktree: Path to the git worktree.

    Returns:
        Porcelain status output.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def stage_all(worktree: Path) -> bool:
    """Stage all changes.

    Args:
        worktree: Path to the git worktree.

    Returns:
        True if successful.
    """
    result = subprocess.run(
        ["git", "add", "-A"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def commit(worktree: Path, message: str) -> bool:
    """Create a commit.

    Args:
        worktree: Path to the git worktree.
        message: Commit message.

    Returns:
        True if successful.
    """
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def push(worktree: Path) -> bool:
    """Push to remote.

    Args:
        worktree: Path to the git worktree.

    Returns:
        True if successful.
    """
    result = subprocess.run(
        ["git", "push"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def fetch_branch(worktree: Path, branch: str) -> tuple[bool, str]:
    """Fetch a branch from origin.

    Args:
        worktree: Path to the git worktree.
        branch: Branch name to fetch.

    Returns:
        Tuple of (success, error_message).
    """
    result = subprocess.run(
        ["git", "fetch", "origin", branch],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def count_commits_ahead(worktree: Path, base_branch: str) -> tuple[int, str]:
    """Count commits ahead of base branch.

    Args:
        worktree: Path to the git worktree.
        base_branch: Base branch to compare against.

    Returns:
        Tuple of (count, error_message). Count is -1 on error.
    """
    result = subprocess.run(
        ["git", "rev-list", "--count", f"origin/{base_branch}..HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return -1, result.stderr
    return int(result.stdout.strip()), ""


def get_merge_base(worktree: Path, base_branch: str) -> tuple[str, str]:
    """Get the merge base commit.

    Args:
        worktree: Path to the git worktree.
        base_branch: Base branch to find merge base with.

    Returns:
        Tuple of (commit_sha, error_message). SHA is empty on error.
    """
    result = subprocess.run(
        ["git", "merge-base", f"origin/{base_branch}", "HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "", result.stderr
    return result.stdout.strip(), ""


def get_last_commit_message(worktree: Path) -> str:
    """Get the last commit message.

    Args:
        worktree: Path to the git worktree.

    Returns:
        Commit message or default string.
    """
    result = subprocess.run(
        ["git", "log", "--format=%B", "-1"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "Squashed commits"


def soft_reset(worktree: Path, commit_sha: str) -> tuple[bool, str]:
    """Soft reset to a commit.

    Args:
        worktree: Path to the git worktree.
        commit_sha: Commit SHA to reset to.

    Returns:
        Tuple of (success, error_message).
    """
    result = subprocess.run(
        ["git", "reset", "--soft", commit_sha],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def rebase(worktree: Path, base_branch: str) -> tuple[bool, bool, str]:
    """Rebase onto a branch.

    Args:
        worktree: Path to the git worktree.
        base_branch: Branch to rebase onto.

    Returns:
        Tuple of (success, has_conflicts, error_message).
    """
    result = subprocess.run(
        ["git", "rebase", f"origin/{base_branch}"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        has_conflicts = "CONFLICT" in result.stdout or "CONFLICT" in result.stderr
        return False, has_conflicts, result.stderr
    return True, False, ""


def get_repo_root() -> Path | None:
    """Get the root directory of the git repository.

    Returns:
        Path to the repo root, or None if not in a git repo.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def remove_worktree(worktree: Path) -> tuple[bool, str]:
    """Remove a git worktree.

    Args:
        worktree: Path to the git worktree.

    Returns:
        Tuple of (success, error_message).
    """
    repo_root = get_repo_root()
    result = subprocess.run(
        ["git", "worktree", "remove", str(worktree)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def delete_branch(branch_name: str) -> tuple[bool, str]:
    """Delete a local branch.

    Args:
        branch_name: Name of the branch to delete.

    Returns:
        Tuple of (success, error_message).
    """
    result = subprocess.run(
        ["git", "branch", "-D", branch_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def fetch_all_prune() -> None:
    """Fetch all remotes and prune."""
    subprocess.run(
        ["git", "fetch", "--all", "--prune"],
        capture_output=True,
        text=True,
        check=False,
    )


def stash() -> bool:
    """Stash local changes.

    Returns:
        True if there were changes to stash.
    """
    result = subprocess.run(
        ["git", "stash"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "No local changes" not in result.stdout


def stash_pop() -> tuple[bool, str]:
    """Pop stashed changes.

    Returns:
        Tuple of (success, error_message).
    """
    result = subprocess.run(
        ["git", "stash", "pop"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def checkout(branch: str) -> tuple[bool, str]:
    """Checkout a branch.

    Args:
        branch: Branch name to checkout.

    Returns:
        Tuple of (success, error_message).
    """
    result = subprocess.run(
        ["git", "checkout", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def pull() -> tuple[bool, str]:
    """Pull from remote.

    Returns:
        Tuple of (success, error_message).
    """
    result = subprocess.run(
        ["git", "pull"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def branch_exists_local(branch_name: str) -> bool:
    """Check if a branch exists locally.

    Args:
        branch_name: Name of the branch to check.

    Returns:
        True if the branch exists locally.
    """
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def branch_exists_remote(branch_name: str) -> bool:
    """Check if a branch exists on the remote.

    Args:
        branch_name: Name of the branch to check.

    Returns:
        True if the branch exists on the remote.
    """
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def branch_exists(branch_name: str) -> bool:
    """Check if a branch exists locally or on the remote.

    Args:
        branch_name: Name of the branch to check.

    Returns:
        True if the branch exists locally or on the remote.
    """
    return branch_exists_local(branch_name) or branch_exists_remote(branch_name)

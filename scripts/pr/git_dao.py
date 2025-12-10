"""Git data access operations.

Provides low-level functions for git operations via subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


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


def get_status(worktree: Path) -> tuple[str, str | None]:
    """Get git status output.

    Args:
        worktree: Path to the git worktree.

    Returns:
        Tuple of (status, error). On success, status contains porcelain output
        (empty string if clean) and error is None. On failure, status is empty
        and error contains the error message.
    """
    result = _run_git(["git", "status", "--porcelain"], cwd=worktree)
    if result is None:
        return "", "git is not available"
    if result.returncode != 0:
        err = result.stderr.strip() or "git status failed"
        return "", err
    return result.stdout.strip(), None


def stage_all(worktree: Path) -> bool:
    """Stage all changes.

    Args:
        worktree: Path to the git worktree.

    Returns:
        True if successful, False if git unavailable or error.
    """
    result = _run_git(["git", "add", "-A"], cwd=worktree)
    if result is None:
        return False
    return result.returncode == 0


def commit(worktree: Path, message: str) -> bool:
    """Create a commit.

    Args:
        worktree: Path to the git worktree.
        message: Commit message.

    Returns:
        True if successful, False if git unavailable or error.
    """
    result = _run_git(["git", "commit", "-m", message], cwd=worktree)
    if result is None:
        return False
    return result.returncode == 0


def push(worktree: Path, set_upstream: bool = False) -> tuple[bool, str]:
    """Push to remote.

    Args:
        worktree: Path to the git worktree.
        set_upstream: If True, set upstream tracking with -u flag.

    Returns:
        Tuple of (success, error_message).
    """
    cmd = ["git", "push"]
    if set_upstream:
        cmd.extend(["-u", "origin", "HEAD"])

    result = _run_git(cmd, cwd=worktree)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def fetch_branch(worktree: Path, branch: str) -> tuple[bool, str]:
    """Fetch a branch from origin.

    Args:
        worktree: Path to the git worktree.
        branch: Branch name to fetch.

    Returns:
        Tuple of (success, error_message).
    """
    result = _run_git(["git", "fetch", "origin", branch], cwd=worktree)
    if result is None:
        return False, "git not available"
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
    result = _run_git(
        ["git", "rev-list", "--count", f"origin/{base_branch}..HEAD"],
        cwd=worktree,
    )
    if result is None:
        return -1, "git not available"
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
    result = _run_git(
        ["git", "merge-base", f"origin/{base_branch}", "HEAD"],
        cwd=worktree,
    )
    if result is None:
        return "", "git not available"
    if result.returncode != 0:
        return "", result.stderr
    return result.stdout.strip(), ""


def get_last_commit_message(worktree: Path) -> str:
    """Get the last commit message.

    Args:
        worktree: Path to the git worktree.

    Returns:
        Commit message or default string if git unavailable or error.
    """
    result = _run_git(["git", "log", "--format=%B", "-1"], cwd=worktree)
    if result is None or result.returncode != 0:
        return "Squashed commits"
    return result.stdout.strip()


def soft_reset(worktree: Path, commit_sha: str) -> tuple[bool, str]:
    """Soft reset to a commit.

    Args:
        worktree: Path to the git worktree.
        commit_sha: Commit SHA to reset to.

    Returns:
        Tuple of (success, error_message).
    """
    result = _run_git(["git", "reset", "--soft", commit_sha], cwd=worktree)
    if result is None:
        return False, "git not available"
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
    result = _run_git(["git", "rebase", f"origin/{base_branch}"], cwd=worktree)
    if result is None:
        return False, False, "git not available"
    if result.returncode != 0:
        has_conflicts = "CONFLICT" in result.stdout or "CONFLICT" in result.stderr
        return False, has_conflicts, result.stderr
    return True, False, ""


def get_repo_root() -> Path | None:
    """Get the root directory of the git repository.

    Returns:
        Path to the repo root, or None if not in a git repo or git unavailable.
    """
    result = _run_git(["git", "rev-parse", "--show-toplevel"])
    if result is None or result.returncode != 0:
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
    if repo_root is None:
        return False, "not in a git repo"
    result = _run_git(["git", "worktree", "remove", str(worktree)], cwd=repo_root)
    if result is None:
        return False, "git not available"
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
    result = _run_git(["git", "branch", "-D", branch_name])
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def fetch_all_prune() -> None:
    """Fetch all remotes and prune.

    Silently ignores if git is unavailable.
    """
    _run_git(["git", "fetch", "--all", "--prune"])


def stash() -> bool:
    """Stash local changes.

    Returns:
        True if there were changes to stash, False if no changes or git unavailable.
    """
    result = _run_git(["git", "stash"])
    if result is None:
        return False
    if result.returncode != 0:
        return False
    return "No local changes" not in result.stdout


def stash_pop() -> tuple[bool, str]:
    """Pop stashed changes.

    Returns:
        Tuple of (success, error_message).
    """
    result = _run_git(["git", "stash", "pop"])
    if result is None:
        return False, "git not available"
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
    result = _run_git(["git", "checkout", branch])
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def pull() -> tuple[bool, str]:
    """Pull from remote.

    Returns:
        Tuple of (success, error_message).
    """
    result = _run_git(["git", "pull"])
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def branch_exists_local(branch_name: str) -> bool:
    """Check if a branch exists locally.

    Args:
        branch_name: Name of the branch to check.

    Returns:
        True if the branch exists locally, False if not or git unavailable.
    """
    result = _run_git(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
    )
    if result is None:
        return False
    return result.returncode == 0


def branch_exists_remote(branch_name: str) -> bool:
    """Check if a branch exists on the remote.

    Args:
        branch_name: Name of the branch to check.

    Returns:
        True if the branch exists on the remote, False if not or git unavailable.
    """
    result = _run_git(["git", "ls-remote", "--heads", "origin", branch_name])
    if result is None:
        return False
    if result.returncode != 0:
        return False
    # Check for exact match (output format: "<sha>\trefs/heads/<branch>")
    # git ls-remote does pattern matching, so "foo" would also match "foobar"
    # Using partition to split on tab and compare ref field exactly
    expected_ref = f"refs/heads/{branch_name}"
    return any(
        ref == expected_ref
        for _, _, ref in (line.partition("\t") for line in result.stdout.strip().splitlines())
    )


def branch_exists(branch_name: str) -> bool:
    """Check if a branch exists locally or on the remote.

    Args:
        branch_name: Name of the branch to check.

    Returns:
        True if the branch exists locally or on the remote.
    """
    return branch_exists_local(branch_name) or branch_exists_remote(branch_name)


def get_current_branch() -> str | None:
    """Get the name of the current branch.

    Returns:
        Branch name, or None if not on a branch or git unavailable.
    """
    result = _run_git(["git", "branch", "--show-current"])
    if result is None or result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch else None


def is_inside_worktree() -> bool:
    """Check if current directory is inside a git worktree (not the main repo).

    Returns:
        True if inside a worktree, False if in main repo or git unavailable.
    """
    git_dir = _run_git(["git", "rev-parse", "--git-dir"])
    common_dir = _run_git(["git", "rev-parse", "--git-common-dir"])

    if git_dir is None or common_dir is None:
        return False
    if git_dir.returncode != 0 or common_dir.returncode != 0:
        return False

    # If git-dir and git-common-dir differ, we're in a worktree
    return git_dir.stdout.strip() != common_dir.stdout.strip()


def fetch_origin() -> tuple[bool, str]:
    """Fetch from origin remote.

    Returns:
        Tuple of (success, error_message).
    """
    result = _run_git(["git", "fetch", "origin"])
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def create_worktree(worktree_path: Path, branch_name: str, create_branch: bool) -> tuple[bool, str]:
    """Create a git worktree.

    Args:
        worktree_path: Path where the worktree should be created.
        branch_name: Name of the branch to checkout in the worktree.
        create_branch: If True, create a new branch with -b flag.

    Returns:
        Tuple of (success, error_message).
    """
    cmd = ["git", "worktree", "add"]
    if create_branch:
        cmd.extend(["-b", branch_name, "--", str(worktree_path)])
    else:
        cmd.extend(["--", str(worktree_path), branch_name])

    result = _run_git(cmd)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def worktree_exists(worktree_path: Path) -> bool:
    """Check if a worktree exists at the given path.

    Args:
        worktree_path: Path to check.

    Returns:
        True if a worktree exists at the path, False if not or git unavailable.
    """
    result = _run_git(["git", "worktree", "list", "--porcelain"])
    if result is None or result.returncode != 0:
        return False

    # Check if the path appears in the worktree list
    abs_path = str(worktree_path.resolve())
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            worktree_dir = line[9:]  # len("worktree ") == 9
            # Use casefold() for case-insensitive comparison on Windows
            if str(Path(worktree_dir).resolve()).casefold() == abs_path.casefold():
                return True
    return False


def create_worktree_tracking(worktree_path: Path, branch_name: str) -> tuple[bool, str]:
    """Create a git worktree tracking a remote branch.

    Creates a new local branch that tracks the remote branch of the same name.
    This is used when the branch only exists on the remote.

    Args:
        worktree_path: Path where the worktree should be created.
        branch_name: Name of the remote branch to track.

    Returns:
        Tuple of (success, error_message).
    """
    # git worktree add --track -b <branch_name> <worktree_path> origin/<branch_name>
    cmd = [
        "git",
        "worktree",
        "add",
        "--track",
        "-b",
        branch_name,
        "--",
        str(worktree_path),
        f"origin/{branch_name}",
    ]

    result = _run_git(cmd)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def create_shared_clone(source_path: Path, clone_path: Path, branch_name: str) -> tuple[bool, str]:
    """Create a sandbox clone for safe rebase/merge operations.

    Creates a fresh git repository that fetches from GitHub (not the local worktree).
    This avoids issues with:
    - Worktree branch locks preventing checkout of the same branch
    - Origin pointing to local worktree instead of GitHub
    - Missing git user config in cloned repos

    Args:
        source_path: Path to the source worktree or repo.
        clone_path: Path where the sandbox should be created.
        branch_name: Name of the branch to checkout in the sandbox.

    Returns:
        Tuple of (success, error_message).
    """
    import shutil

    # Get the GitHub remote URL from the source repo
    result = _run_git(["git", "remote", "get-url", "origin"], cwd=source_path)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, f"failed to get remote URL: {result.stderr}"
    github_url = result.stdout.strip()

    # Get git user config from source repo
    user_name = None
    user_email = None
    result = _run_git(["git", "config", "user.name"], cwd=source_path)
    if result and result.returncode == 0:
        user_name = result.stdout.strip()
    result = _run_git(["git", "config", "user.email"], cwd=source_path)
    if result and result.returncode == 0:
        user_email = result.stdout.strip()

    # Ensure parent directory exists and clone path is clean
    clone_path.parent.mkdir(parents=True, exist_ok=True)
    if clone_path.exists():
        shutil.rmtree(clone_path)

    # Initialize fresh git repo
    clone_path.mkdir(parents=True)
    result = _run_git(["git", "init"], cwd=clone_path)
    if result is None:
        shutil.rmtree(clone_path, ignore_errors=True)
        return False, "git not available"
    if result.returncode != 0:
        shutil.rmtree(clone_path, ignore_errors=True)
        return False, f"git init failed: {result.stderr}"

    # Add GitHub as origin
    result = _run_git(["git", "remote", "add", "origin", github_url], cwd=clone_path)
    if result is None or result.returncode != 0:
        shutil.rmtree(clone_path, ignore_errors=True)
        return False, f"failed to add remote: {result.stderr if result else 'git not available'}"

    # Set git user config if available
    if user_name:
        _run_git(["git", "config", "user.name", user_name], cwd=clone_path)
    if user_email:
        _run_git(["git", "config", "user.email", user_email], cwd=clone_path)

    # Fetch the branch
    result = _run_git(["git", "fetch", "origin", branch_name], cwd=clone_path)
    if result is None or result.returncode != 0:
        shutil.rmtree(clone_path, ignore_errors=True)
        return False, f"failed to fetch branch: {result.stderr if result else 'git not available'}"

    # Checkout as a new local branch (avoids worktree lock on same branch name)
    # Use a sandbox-specific branch name to avoid conflicts
    result = _run_git(
        ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"],
        cwd=clone_path,
    )
    if result is None or result.returncode != 0:
        shutil.rmtree(clone_path, ignore_errors=True)
        return False, f"checkout failed: {result.stderr if result else 'git not available'}"

    return True, ""


def remove_shared_clone(clone_path: Path) -> tuple[bool, str]:
    """Remove a shared clone directory.

    Args:
        clone_path: Path to the shared clone to remove.

    Returns:
        Tuple of (success, error_message).
    """
    import shutil

    if not clone_path.exists():
        return True, ""

    try:
        shutil.rmtree(clone_path)
        return True, ""
    except OSError as e:
        return False, str(e)


def get_conflicted_files(worktree: Path) -> list[str]:
    """Get list of files with merge conflicts.

    Args:
        worktree: Path to the git worktree.

    Returns:
        List of file paths with conflicts (empty if none or error).
    """
    result = _run_git(["git", "status", "--porcelain"], cwd=worktree)
    if result is None or result.returncode != 0:
        return []

    conflicted: list[str] = []
    for line in result.stdout.splitlines():
        # UU = both modified (conflict)
        if line.startswith("UU "):
            conflicted.append(line[3:])
    return conflicted


def get_commits_between(worktree: Path, base_commit: str, target_ref: str) -> list[str]:
    """Get list of commit SHAs between two refs.

    Args:
        worktree: Path to the git worktree.
        base_commit: Base commit SHA.
        target_ref: Target ref (e.g., origin/main).

    Returns:
        List of commit SHAs from oldest to newest (empty if none or error).
    """
    result = _run_git(
        ["git", "log", "--oneline", "--reverse", f"{base_commit}..{target_ref}"],
        cwd=worktree,
    )
    if result is None or result.returncode != 0:
        return []

    commits: list[str] = []
    for line in result.stdout.splitlines():
        if line:
            # Format: "sha message" - extract just the SHA
            sha = line.split()[0]
            commits.append(sha)
    return commits


def get_head_sha(worktree: Path) -> str:
    """Get the SHA of HEAD.

    Args:
        worktree: Path to the git worktree.

    Returns:
        SHA string, or empty string on error.
    """
    result = _run_git(["git", "rev-parse", "HEAD"], cwd=worktree)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout.strip()


def force_push(worktree: Path) -> tuple[bool, str]:
    """Force push with lease to remote.

    Args:
        worktree: Path to the git worktree.

    Returns:
        Tuple of (success, error_message).
    """
    result = _run_git(["git", "push", "--force-with-lease"], cwd=worktree)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


def reset_hard_to_remote(worktree: Path, branch_name: str) -> tuple[bool, str]:
    """Reset worktree to match remote branch.

    Args:
        worktree: Path to the git worktree.
        branch_name: Branch name to reset to (will use origin/<branch_name>).

    Returns:
        Tuple of (success, error_message).
    """
    # First fetch
    result = _run_git(["git", "fetch", "origin"], cwd=worktree)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, f"fetch failed: {result.stderr}"

    # Then reset
    result = _run_git(["git", "reset", "--hard", f"origin/{branch_name}"], cwd=worktree)
    if result is None:
        return False, "git not available"
    if result.returncode != 0:
        return False, f"reset failed: {result.stderr}"
    return True, ""

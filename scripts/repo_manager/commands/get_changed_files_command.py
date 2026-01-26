"""Get all changed files from the repository.

This module aggregates across all staged/unstaged/untracked/tracked files
and returns the unique filenames that could go into a commit.
"""

import subprocess
import sys
from pathlib import Path


class GitCommandError(Exception):
    """Raised when a git command fails."""

    def __init__(self, cmd: list[str], returncode: int, stderr: str) -> None:
        """Initialize GitCommandError with command details.

        Args:
            cmd: Command that failed.
            returncode: Exit code returned by the command.
            stderr: Standard error output from the command.
        """
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        cmd_str = " ".join(cmd)
        super().__init__(f"Git command failed: {cmd_str!r} (exit {returncode}): {stderr}")


def run_git_command(cmd: list[str], cwd: Path) -> str:
    """Run a git command and return its stdout.

    Args:
        cmd: Command and arguments to run.
        cwd: Working directory for the command.

    Returns:
        The stdout from the command.

    Raises:
        GitCommandError: If the command fails (non-zero exit code).
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
        )
    except OSError as e:
        raise GitCommandError(cmd, -1, str(e)) from e

    if result.returncode != 0:
        raise GitCommandError(cmd, result.returncode, result.stderr.strip())

    return result.stdout


def get_staged_files(cwd: Path) -> set[Path]:
    """Get staged files that have been added but not committed.

    Args:
        cwd: Working directory for git command.

    Returns:
        Set of Path objects for staged files that exist on disk.
    """
    try:
        stdout = run_git_command(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=d"], cwd=cwd
        )
    except GitCommandError:
        return set()

    files: set[Path] = set()
    for line in stdout.strip().split("\n"):
        if line:
            file_path = cwd / line
            if file_path.is_file():
                files.add(file_path)
    return files


def get_unstaged_files(cwd: Path) -> set[Path]:
    """Get unstaged modified files.

    Args:
        cwd: Working directory for git command.

    Returns:
        Set of Path objects for unstaged modified files that exist on disk.
    """
    try:
        stdout = run_git_command(["git", "diff", "--name-only", "--diff-filter=d"], cwd=cwd)
    except GitCommandError:
        return set()

    files: set[Path] = set()
    for line in stdout.strip().split("\n"):
        if line:
            file_path = cwd / line
            if file_path.is_file():
                files.add(file_path)
    return files


def get_untracked_files(cwd: Path) -> set[Path]:
    """Get untracked files that are not in git.

    Args:
        cwd: Working directory for git command.

    Returns:
        Set of Path objects for untracked files that exist on disk.
    """
    try:
        stdout = run_git_command(["git", "ls-files", "--others", "--exclude-standard"], cwd=cwd)
    except GitCommandError:
        return set()

    files: set[Path] = set()
    for line in stdout.strip().split("\n"):
        if line:
            file_path = cwd / line
            if file_path.is_file():
                files.add(file_path)
    return files


def get_tracked_files(cwd: Path) -> set[Path]:
    """Get all tracked files in the repository.

    Args:
        cwd: Working directory for git command.

    Returns:
        Set of Path objects for all tracked files that exist on disk.
    """
    try:
        stdout = run_git_command(["git", "ls-files"], cwd=cwd)
    except GitCommandError:
        return set()

    files: set[Path] = set()
    for line in stdout.strip().split("\n"):
        if line:
            file_path = cwd / line
            if file_path.is_file():
                files.add(file_path)
    return files


def get_all_changed_files(cwd: Path) -> list[Path]:
    """Get all files that are newly created or modified that could go into a commit.

    Aggregates across staged, unstaged, and untracked files.

    Args:
        cwd: Working directory for git commands.

    Returns:
        Sorted list of unique Path objects for changed files.
    """
    staged = get_staged_files(cwd)
    unstaged = get_unstaged_files(cwd)
    untracked = get_untracked_files(cwd)

    all_files = staged | unstaged | untracked
    return sorted(all_files)


def get_changed_files_command(root: Path) -> int:
    """Get and print all changed files from the repository.

    Args:
        root: Root path for git operations. All files are returned relative to this path.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        files = get_all_changed_files(root)
    except GitCommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Convert to relative paths for output
    for file_path in files:
        try:
            rel_path = file_path.relative_to(root)
            print(rel_path)
        except ValueError:
            # File is not under root path, print absolute path
            print(file_path)

    return 0

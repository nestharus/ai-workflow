"""Create a zip archive of changed files.

Collects changed files from git (uncommitted or from a specific commit)
and creates a zip archive with files in their appropriate directory structure.

Usage:
    uv run zip-changes          # Uncommitted changes (staged + unstaged)
    uv run zip-changes <sha>    # Files changed in a specific commit
"""

import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


class GitCommandError(Exception):
    """Raised when a git command fails."""

    def __init__(self, cmd: list[str], returncode: int, stderr: str) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        cmd_str = " ".join(cmd)
        super().__init__(f"Git command failed: {cmd_str!r} (exit {returncode}): {stderr}")


def run_git_command(cmd: list[str]) -> str:
    """Run a git command and return its stdout.

    Args:
        cmd: Command and arguments to run.

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
        )
    except OSError as e:
        raise GitCommandError(cmd, -1, str(e)) from e

    if result.returncode != 0:
        raise GitCommandError(cmd, result.returncode, result.stderr.strip())

    return result.stdout


def get_uncommitted_files() -> list[Path]:
    """Get all uncommitted changed files (staged and unstaged).

    Returns:
        List of Path objects for changed files that exist on disk.

    Raises:
        GitCommandError: If git status command fails.
    """
    stdout = run_git_command(["git", "status", "--porcelain"])

    files: list[Path] = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        # Status is first 2 chars, then space, then path
        # Handle renamed files (e.g., "R  old -> new")
        status = line[:2]
        path_part = line[3:]

        # Skip deleted files (they don't exist to zip)
        if status.startswith("D") or status.endswith("D"):
            continue

        # Handle renames: "old -> new" - take the new path
        if " -> " in path_part:
            path_part = path_part.split(" -> ")[1]

        file_path = Path(path_part)
        if file_path.exists() and file_path.is_file():
            files.append(file_path)

    return files


def get_commit_files(sha: str) -> list[Path]:
    """Get all files changed in a specific commit.

    Args:
        sha: Git commit SHA.

    Returns:
        List of Path objects for changed files that exist on disk.

    Raises:
        GitCommandError: If git diff-tree command fails (e.g., invalid SHA).
    """
    stdout = run_git_command(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", sha])

    files: list[Path] = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        # Format: "STATUS\tPATH" or "STATUS\tOLD\tNEW" for renames
        parts = line.split("\t")
        status = parts[0]

        # Skip deleted files
        if status.startswith("D"):
            continue

        # For renames (R100, R095, etc.), take the new path (last part)
        if status.startswith("R"):
            path_part = parts[-1]
        else:
            path_part = parts[1]

        file_path = Path(path_part)
        if file_path.exists() and file_path.is_file():
            files.append(file_path)

    return files


def create_zip_archive(files: list[Path], output_path: Path) -> None:
    """Create a zip archive containing the specified files.

    Args:
        files: List of file paths to include in the archive.
        output_path: Path for the output zip file.
    """
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in files:
            zipf.write(file_path, file_path)


def main() -> int:
    """Create a zip archive of changed files.

    Usage:
        zip-changes          # Uncommitted changes
        zip-changes <sha>    # Files from a specific commit

    Returns:
        Exit code (0 for success, 1 for no changes/error).
    """
    sha = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        if sha:
            files = get_commit_files(sha)
            source_desc = f"commit {sha[:8]}"
        else:
            files = get_uncommitted_files()
            source_desc = "uncommitted changes"
    except GitCommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not files:
        print(f"No files found in {source_desc}.")
        return 1

    # Generate output filename with timestamp
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    if sha:
        output_path = Path(f"changes_{sha[:8]}_{timestamp}.zip")
    else:
        output_path = Path(f"changes_{timestamp}.zip")

    create_zip_archive(files, output_path)

    print(f"Created {output_path} with {len(files)} file(s) from {source_desc}:")
    for file_path in sorted(files):
        print(f"  {file_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

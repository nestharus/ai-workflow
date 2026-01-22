"""Discover files in scope based on git history since start commit."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.pr import git_dao


@dataclass
class ScopeState:
    """State for tracking scope across review cycles."""

    start_commit: str
    last_head: str
    files: set[str]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "start_commit": self.start_commit,
            "last_head": self.last_head,
            "files": sorted(self.files),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScopeState:
        """Create from dict."""
        return cls(
            start_commit=data["start_commit"],
            last_head=data["last_head"],
            files=set(data["files"]),
        )


def _get_files_changed_since(working_dir: Path, start_commit: str) -> list[str]:
    """Get files changed between start_commit and HEAD.

    Args:
        working_dir: Git working directory.
        start_commit: Starting commit SHA.

    Returns:
        List of file paths that have changed.
    """
    result = git_dao._run_git(
        ["git", "diff", "--name-only", f"{start_commit}..HEAD"],
        cwd=working_dir,
    )
    if result is None or result.returncode != 0:
        return []
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def _get_uncommitted_files(working_dir: Path) -> list[str]:
    """Get files with uncommitted changes.

    Args:
        working_dir: Git working directory.

    Returns:
        List of file paths with uncommitted changes.
    """
    status, error = git_dao.get_status(working_dir)
    if error:
        return []

    files: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        # Status format: "XY filename" where XY are status codes
        # Skip status codes and space to get filename
        filename = line[3:].strip()
        # Handle renamed files: "old -> new"
        if " -> " in filename:
            filename = filename.split(" -> ")[1]
        files.append(filename)
    return files


def discover_scope_files_command(
    working_dir: Path,
    start_commit: str,
    state_file: Path | None = None,
) -> int:
    """Discover files in scope since start commit.

    This command:
    1. Gets all files changed between start_commit and HEAD
    2. Gets all uncommitted files
    3. Combines into a unique set
    4. If state_file exists, merges with previous state

    Args:
        working_dir: Git working directory.
        start_commit: Starting commit SHA from implementation-scope agent.
        state_file: Optional path to persist/load state for incremental updates.

    Returns:
        Exit code (0 for success).
    """
    # Resolve working_dir
    if not working_dir.exists():
        print(f"Error: working_dir does not exist: {working_dir}", file=sys.stderr)
        return 1

    # Get current HEAD
    current_head = git_dao.get_head_sha(working_dir)
    if not current_head:
        print("Error: Could not get HEAD SHA", file=sys.stderr)
        return 1

    # Load existing state if available
    existing_state: ScopeState | None = None
    if state_file and state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            existing_state = ScopeState.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not load state file: {e}", file=sys.stderr)

    # Get committed changes since start
    committed_files = _get_files_changed_since(working_dir, start_commit)

    # Get uncommitted changes
    uncommitted_files = _get_uncommitted_files(working_dir)

    # Combine into set
    all_files = set(committed_files) | set(uncommitted_files)

    # Merge with existing state if available
    if existing_state:
        all_files = existing_state.files | all_files

    # Create new state
    new_state = ScopeState(
        start_commit=start_commit,
        last_head=current_head,
        files=all_files,
    )

    # Save state if path provided
    if state_file:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(new_state.to_dict(), indent=2))

    # Output result
    result = {
        "status": "success",
        "start_commit": start_commit,
        "current_head": current_head,
        "files": sorted(all_files),
        "committed_count": len(committed_files),
        "uncommitted_count": len(uncommitted_files),
        "total_count": len(all_files),
        "is_incremental": existing_state is not None,
    }
    print(json.dumps(result, indent=2))
    return 0

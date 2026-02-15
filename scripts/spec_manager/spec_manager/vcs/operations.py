"""VCS abstraction layer for worktree management.

Wraps git operations behind an abstract interface so the underlying
VCS can be changed (per ``simpler.md``: *"It could be jj. It could be
git.  We don't care."*).

Only the operations needed by :class:`WorktreeManager` are exposed.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class VcsOperations(Protocol):
    """Abstract VCS operations for worktree management."""

    def create_worktree(
        self, path: Path, branch: str, *, start_point: str = "HEAD"
    ) -> tuple[bool, str]:
        """Create a new worktree with a new branch.

        Args:
            path: Filesystem path for the worktree.
            branch: Branch name to create.
            start_point: Commit/branch to start from.

        Returns:
            ``(success, error_message)``.
        """
        ...

    def remove_worktree(self, path: Path) -> tuple[bool, str]:
        """Remove a worktree and its branch.

        Args:
            path: Path of the worktree to remove.

        Returns:
            ``(success, error_message)``.
        """
        ...

    def worktree_exists(self, path: Path) -> bool:
        """Check whether a worktree exists at *path*."""
        ...

    def cherry_pick(self, worktree: Path, commit_sha: str) -> tuple[bool, str]:
        """Cherry-pick a single commit into *worktree*.

        Returns:
            ``(success, error_message)``.
        """
        ...

    def rebase(self, worktree: Path, onto: str) -> tuple[bool, str]:
        """Rebase *worktree*'s branch onto *onto*.

        Returns:
            ``(success, error_message)``.
        """
        ...

    def merge(self, worktree: Path, branch: str) -> tuple[bool, str]:
        """Merge *branch* into *worktree*.

        Returns:
            ``(success, error_message)``.
        """
        ...

    def commit_all(self, worktree: Path, message: str) -> tuple[bool, str]:
        """Stage all changes and commit in *worktree*.

        Returns:
            ``(success, error_message)``.
        """
        ...

    def get_current_branch(self, worktree: Path | None = None) -> str | None:
        """Return the current branch name for *worktree*.

        Returns ``None`` if detached or on error.
        """
        ...

    def get_head_sha(self, worktree: Path) -> str | None:
        """Return the HEAD commit SHA for *worktree*.

        Returns ``None`` on error.
        """
        ...

    def rev_parse(self, ref: str) -> str | None:
        """Resolve *ref* (branch, tag, SHA) to a full commit SHA.

        Returns ``None`` on error.
        """
        ...

    def update_ref(self, branch: str, target_sha: str) -> tuple[bool, str]:
        """Move *branch* to *target_sha* (fast-forward ref update).

        Returns:
            ``(success, error_message)``.
        """
        ...

    def rev_list_count(self, from_ref: str, to_ref: str) -> int | None:
        """Count commits in the range ``from_ref..to_ref``.

        Returns ``None`` on error.
        """
        ...

    def create_tag(self, tag_name: str, target: str, message: str = "") -> tuple[bool, str]:
        """Create an annotated tag at *target*.

        Returns:
            ``(success, error_message)``.
        """
        ...

    def delete_ref(self, ref: str) -> tuple[bool, str]:
        """Delete a branch or ref.

        Returns:
            ``(success, error_message)``.
        """
        ...


class GitVcs:
    """Git implementation of :class:`VcsOperations`."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo_root,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

    # ------------------------------------------------------------------
    # VcsOperations implementation
    # ------------------------------------------------------------------

    def create_worktree(
        self, path: Path, branch: str, *, start_point: str = "HEAD"
    ) -> tuple[bool, str]:
        result = self._run(["worktree", "add", "-b", branch, str(path), start_point])
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    def remove_worktree(self, path: Path) -> tuple[bool, str]:
        result = self._run(["worktree", "remove", str(path), "--force"])
        if result.returncode != 0:
            return False, result.stderr.strip()
        # Also delete the branch
        branch = self._branch_for_worktree(path)
        if branch:
            self._run(["branch", "-D", branch])
        return True, ""

    def worktree_exists(self, path: Path) -> bool:
        result = self._run(["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            return False
        resolved = str(path.resolve())
        for line in result.stdout.splitlines():
            if line.startswith("worktree ") and line[9:] == resolved:
                return True
        return False

    def cherry_pick(self, worktree: Path, commit_sha: str) -> tuple[bool, str]:
        result = self._run(["cherry-pick", commit_sha], cwd=worktree)
        if result.returncode != 0:
            # Abort on failure
            self._run(["cherry-pick", "--abort"], cwd=worktree)
            return False, result.stderr.strip()
        return True, ""

    def rebase(self, worktree: Path, onto: str) -> tuple[bool, str]:
        result = self._run(["rebase", onto], cwd=worktree)
        if result.returncode != 0:
            self._run(["rebase", "--abort"], cwd=worktree)
            return False, result.stderr.strip()
        return True, ""

    def merge(self, worktree: Path, branch: str) -> tuple[bool, str]:
        result = self._run(["merge", branch, "--no-ff"], cwd=worktree)
        if result.returncode != 0:
            self._run(["merge", "--abort"], cwd=worktree)
            return False, result.stderr.strip()
        return True, ""

    def commit_all(self, worktree: Path, message: str) -> tuple[bool, str]:
        stage = self._run(["add", "-A"], cwd=worktree)
        if stage.returncode != 0:
            return False, stage.stderr.strip()
        result = self._run(["commit", "-m", message, "--allow-empty"], cwd=worktree)
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    def get_current_branch(self, worktree: Path | None = None) -> str | None:
        result = self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree)
        if result.returncode != 0:
            return None
        branch = result.stdout.strip()
        return None if branch == "HEAD" else branch

    def get_head_sha(self, worktree: Path) -> str | None:
        result = self._run(["rev-parse", "HEAD"], cwd=worktree)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def rev_parse(self, ref: str) -> str | None:
        result = self._run(["rev-parse", ref])
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def update_ref(self, branch: str, target_sha: str) -> tuple[bool, str]:
        ref = f"refs/heads/{branch}" if not branch.startswith("refs/") else branch
        result = self._run(["update-ref", ref, target_sha])
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    def rev_list_count(self, from_ref: str, to_ref: str) -> int | None:
        result = self._run(["rev-list", "--count", f"{from_ref}..{to_ref}"])
        if result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def create_tag(self, tag_name: str, target: str, message: str = "") -> tuple[bool, str]:
        if message:
            result = self._run(["tag", "-a", tag_name, target, "-m", message])
        else:
            result = self._run(["tag", tag_name, target])
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    def delete_ref(self, ref: str) -> tuple[bool, str]:
        result = self._run(["branch", "-D", ref])
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _branch_for_worktree(self, path: Path) -> str | None:
        """Return the branch name associated with a worktree path."""
        result = self._run(["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            return None
        resolved = str(path.resolve())
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("worktree ") and line[9:] == resolved:
                # The branch line follows the worktree line
                for j in range(i + 1, min(i + 4, len(lines))):
                    if lines[j].startswith("branch "):
                        ref = lines[j][7:]
                        if ref.startswith("refs/heads/"):
                            return ref[len("refs/heads/") :]
                        return ref
        return None

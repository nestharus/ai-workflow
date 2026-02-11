"""Project root detection via git rev-parse --show-toplevel.

Provides worktree-aware path resolution so all relative paths resolve
correctly regardless of CWD or git worktree.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path


class ProjectRootError(RuntimeError):
    """Raised when the project root cannot be determined (not in a git repo)."""


@lru_cache(maxsize=1)
def get_project_root() -> Path:
    """Return the absolute resolved project root via git.

    Uses ``git rev-parse --show-toplevel`` which works from any
    subdirectory and any worktree.  The result is cached for the
    lifetime of the process since the git root is immutable.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ProjectRootError(
            "Cannot determine project root. Are you inside a git repository?"
        ) from exc
    return Path(result.stdout.strip()).resolve()


def resolve_from_root(*parts: str) -> Path:
    """Join *parts* relative to the project root and return an absolute path."""
    return get_project_root().joinpath(*parts)

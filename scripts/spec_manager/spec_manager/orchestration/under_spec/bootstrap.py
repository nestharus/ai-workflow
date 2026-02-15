"""Under-spec orchestration bootstrap helpers.

Phase 0 intake writes ``constraints.md`` (and optional
``constraints_index.json``) artifacts under ``libraries/`` and ``system/``.
This helper materializes those artifacts into the constraints store so
downstream planning and gating can consume them immediately.
"""

from __future__ import annotations

from pathlib import Path

from spec_manager.planner.constraints.bootstrap import (
    bootstrap_constraints_from_intake as _bootstrap_constraints_from_intake,
)


def bootstrap_constraints_from_intake(
    workspace_root: Path,
    libraries_dir: Path,
    system_dir: Path | None = None,
) -> dict[str, int]:
    """Seed constraint store entries from Phase 0 intake artifacts."""
    return _bootstrap_constraints_from_intake(
        workspace_root=workspace_root,
        libraries_dir=libraries_dir,
        system_dir=system_dir,
    )

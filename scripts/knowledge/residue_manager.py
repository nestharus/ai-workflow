"""Residue snapshots manager for artifact-level extraction.

This module manages the `.knowledge/facts/residue/` directory for storing
artifact text snapshots before, during, and after extraction.

Residue snapshots enable debugging of artifact-level extraction by preserving
the state of the text at various points in the extraction process.

Snapshot Types:
    - before: Initial artifact text before any extraction
    - after: Final residual text after all extractions complete
    - intermediate: Snapshot at a specific pass during extraction

File Naming:
    - <artifact_id>.before.txt: Initial state
    - <artifact_id>.after.txt: Final state
    - <artifact_id>.<pass_id>.txt: Intermediate state after a pass

Usage:
    from scripts.knowledge.residue_manager import (
        save_residue_snapshot,
        load_residue_snapshot,
        list_residue_snapshots,
    )

    # Save snapshots
    save_residue_snapshot("artifact_123", text, "before")
    save_residue_snapshot("artifact_123", text, "intermediate", pass_id="pass_001")
    save_residue_snapshot("artifact_123", text, "after")

    # Load snapshot
    text = load_residue_snapshot("artifact_123", "before")

    # List all snapshots
    snapshots = list_residue_snapshots("artifact_123")

References:
    - docs/plans/fact_redesign.md lines 886-891
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from scripts.dev.utils import REPO_ROOT


def _get_residue_dir(knowledge_path: Path) -> Path:
    """Get the residue directory path.

    Args:
        knowledge_path: Base knowledge directory.

    Returns:
        Path to the residue directory.
    """
    residue_dir = knowledge_path / "facts" / "residue"
    residue_dir.mkdir(parents=True, exist_ok=True)
    return residue_dir


def _get_snapshot_filename(
    artifact_id: str,
    snapshot_type: Literal["before", "after", "intermediate"],
    pass_id: str | None = None,
) -> str:
    """Get the filename for a snapshot.

    Args:
        artifact_id: ID of the artifact.
        snapshot_type: Type of snapshot.
        pass_id: Pass ID for intermediate snapshots.

    Returns:
        Snapshot filename.
    """
    if snapshot_type == "before":
        return f"{artifact_id}.before.txt"
    elif snapshot_type == "after":
        return f"{artifact_id}.after.txt"
    elif snapshot_type == "intermediate":
        if not pass_id:
            raise ValueError("pass_id is required for intermediate snapshots")
        return f"{artifact_id}.{pass_id}.txt"
    else:
        raise ValueError(f"Unknown snapshot type: {snapshot_type}")


def save_residue_snapshot(
    artifact_id: str,
    state_text: str,
    snapshot_type: Literal["before", "after", "intermediate"],
    pass_id: str | None = None,
    knowledge_path: Path | None = None,
) -> Path:
    """Save a residue snapshot to disk.

    Args:
        artifact_id: ID of the artifact.
        state_text: Current state text to save.
        snapshot_type: Type of snapshot ('before', 'after', 'intermediate').
        pass_id: Pass ID for intermediate snapshots (required if type is 'intermediate').
        knowledge_path: Base knowledge directory (default: .knowledge).

    Returns:
        Path to the saved snapshot file.

    Raises:
        ValueError: If snapshot_type is 'intermediate' but pass_id is not provided.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / ".knowledge"
    elif not knowledge_path.is_absolute():
        knowledge_path = REPO_ROOT / knowledge_path

    residue_dir = _get_residue_dir(knowledge_path)
    filename = _get_snapshot_filename(artifact_id, snapshot_type, pass_id)
    snapshot_path = residue_dir / filename

    snapshot_path.write_text(state_text, encoding="utf-8")
    return snapshot_path


def load_residue_snapshot(
    artifact_id: str,
    snapshot_type: Literal["before", "after", "intermediate"],
    pass_id: str | None = None,
    knowledge_path: Path | None = None,
) -> str:
    """Load a residue snapshot from disk.

    Args:
        artifact_id: ID of the artifact.
        snapshot_type: Type of snapshot ('before', 'after', 'intermediate').
        pass_id: Pass ID for intermediate snapshots (required if type is 'intermediate').
        knowledge_path: Base knowledge directory (default: .knowledge).

    Returns:
        Snapshot text content.

    Raises:
        FileNotFoundError: If snapshot does not exist.
        ValueError: If snapshot_type is 'intermediate' but pass_id is not provided.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / ".knowledge"
    elif not knowledge_path.is_absolute():
        knowledge_path = REPO_ROOT / knowledge_path

    residue_dir = _get_residue_dir(knowledge_path)
    filename = _get_snapshot_filename(artifact_id, snapshot_type, pass_id)
    snapshot_path = residue_dir / filename

    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    return snapshot_path.read_text(encoding="utf-8")


def list_residue_snapshots(
    artifact_id: str,
    knowledge_path: Path | None = None,
) -> list[Path]:
    """List all residue snapshots for an artifact.

    Args:
        artifact_id: ID of the artifact.
        knowledge_path: Base knowledge directory (default: .knowledge).

    Returns:
        List of paths to snapshot files, sorted by name.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / ".knowledge"
    elif not knowledge_path.is_absolute():
        knowledge_path = REPO_ROOT / knowledge_path

    residue_dir = _get_residue_dir(knowledge_path)

    # Find all snapshots for this artifact
    pattern = f"{artifact_id}.*"
    snapshots = list(residue_dir.glob(pattern))

    return sorted(snapshots)


def delete_residue_snapshot(
    artifact_id: str,
    snapshot_type: Literal["before", "after", "intermediate"],
    pass_id: str | None = None,
    knowledge_path: Path | None = None,
) -> bool:
    """Delete a residue snapshot.

    Args:
        artifact_id: ID of the artifact.
        snapshot_type: Type of snapshot ('before', 'after', 'intermediate').
        pass_id: Pass ID for intermediate snapshots.
        knowledge_path: Base knowledge directory (default: .knowledge).

    Returns:
        True if deleted, False if not found.
    """
    if knowledge_path is None:
        knowledge_path = REPO_ROOT / ".knowledge"
    elif not knowledge_path.is_absolute():
        knowledge_path = REPO_ROOT / knowledge_path

    residue_dir = _get_residue_dir(knowledge_path)
    filename = _get_snapshot_filename(artifact_id, snapshot_type, pass_id)
    snapshot_path = residue_dir / filename

    if snapshot_path.exists():
        snapshot_path.unlink()
        return True
    return False


def clear_artifact_snapshots(
    artifact_id: str,
    knowledge_path: Path | None = None,
) -> int:
    """Delete all residue snapshots for an artifact.

    Args:
        artifact_id: ID of the artifact.
        knowledge_path: Base knowledge directory (default: .knowledge).

    Returns:
        Number of snapshots deleted.
    """
    snapshots = list_residue_snapshots(artifact_id, knowledge_path)
    count = 0
    for snapshot_path in snapshots:
        snapshot_path.unlink()
        count += 1
    return count


def get_snapshot_metadata(
    artifact_id: str,
    knowledge_path: Path | None = None,
) -> dict[str, dict[str, str | int | float]]:
    """Get metadata about all snapshots for an artifact.

    Args:
        artifact_id: ID of the artifact.
        knowledge_path: Base knowledge directory (default: .knowledge).

    Returns:
        Dictionary mapping snapshot type to metadata (size, modified time).
    """
    snapshots = list_residue_snapshots(artifact_id, knowledge_path)
    metadata: dict[str, dict[str, str | int | float]] = {}

    for snapshot_path in snapshots:
        # Parse snapshot type from filename
        filename = snapshot_path.name
        if filename.endswith(".before.txt"):
            snapshot_type = "before"
        elif filename.endswith(".after.txt"):
            snapshot_type = "after"
        else:
            # Intermediate snapshot: artifact_id.pass_id.txt
            parts = filename.replace(".txt", "").split(".")
            if len(parts) >= 2:
                snapshot_type = f"intermediate:{parts[-1]}"
            else:
                continue

        stat = snapshot_path.stat()
        metadata[snapshot_type] = {
            "path": str(snapshot_path),
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }

    return metadata

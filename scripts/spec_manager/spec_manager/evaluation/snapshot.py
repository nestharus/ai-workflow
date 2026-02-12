"""Run snapshot — preserves produced files at pipeline completion.

Copies touched/produced files into ``.pdd_runs/{run_id}/snapshot/files/``
and writes a manifest with SHA-256 hashes for reproducibility.

Usage::

    snapshot_run(workspace_root, run_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def snapshot_run(workspace_root: Path, run_id: str) -> Path:
    """Snapshot produced files for the given run.

    Copies files from ``reports/pdd/{run_id}/`` and the run directory
    into ``.pdd_runs/{run_id}/snapshot/files/`` and writes a manifest.

    Args:
        workspace_root: Root of the PDD workspace.
        run_id: The run identifier.

    Returns:
        Path to the snapshot manifest.
    """
    run_dir = workspace_root / ".pdd_runs" / run_id
    snapshot_dir = run_dir / "snapshot"
    files_dir = snapshot_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[dict[str, Any]] = []

    # Snapshot report artifacts
    run_reports = workspace_root / "reports" / "pdd" / run_id
    if run_reports.exists():
        manifest_entries.extend(_copy_tree(run_reports, files_dir / "reports", run_reports))

    # Snapshot slice evidence
    slices_dir = run_dir / "slices"
    if slices_dir.exists():
        manifest_entries.extend(_copy_tree(slices_dir, files_dir / "slices", slices_dir))

    # Snapshot demotions
    demotions_dir = run_dir / "demotions"
    if demotions_dir.exists():
        manifest_entries.extend(_copy_tree(demotions_dir, files_dir / "demotions", demotions_dir))

    # Write manifest
    manifest = {
        "run_id": run_id,
        "snapshot_time": time.time(),
        "file_count": len(manifest_entries),
        "files": manifest_entries,
    }
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Mark complete
    (snapshot_dir / "COMPLETE").write_text("", encoding="utf-8")

    logger.info("Snapshot complete: %d files → %s", len(manifest_entries), snapshot_dir)
    return manifest_path


def _copy_tree(src: Path, dst: Path, base: Path) -> list[dict[str, Any]]:
    """Recursively copy files from src to dst, returning manifest entries."""
    entries: list[dict[str, Any]] = []
    dst.mkdir(parents=True, exist_ok=True)

    for fp in sorted(src.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(base)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fp, target)

        try:
            sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        except OSError:
            sha = ""

        entries.append({
            "path": str(rel),
            "sha256": sha,
            "size_bytes": fp.stat().st_size if fp.exists() else 0,
        })

    return entries

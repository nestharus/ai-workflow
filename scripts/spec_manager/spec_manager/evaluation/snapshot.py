"""Run snapshot for immutable run-scoped artifact preservation.

Copies run artifacts into ``.pdd_runs/{run_id}/snapshot/files/`` and writes
``.pdd_runs/{run_id}/snapshot/manifest.json`` with provenance and content
hashes for comparison-ready runs.

Usage::

    snapshot_run(workspace_root, run_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def snapshot_run(
    workspace_root: Path,
    run_id: str,
    *,
    comparison_id: str = "",
    spec_hash: str = "",
    pipeline_git_sha: str = "",
    producer_model_id: str = "",
    judge_model_id: str = "",
    created_at: str = "",
) -> Path:
    """Snapshot run artifacts for immutable comparison.

    Copies the produced source tree (``spec_snapshot``) and run-scoped reports
    (``reports/pdd/{run_id}``) into ``.pdd_runs/{run_id}/snapshot/files/``.
    Writes a rich manifest with run identity and digest hashes.

    Args:
        workspace_root: Root of the PDD workspace.
        run_id: The run identifier.
        comparison_id: Optional multi-model comparison identifier.
        spec_hash: Optional spec hash. Resolved from run artifacts when omitted.
        pipeline_git_sha: Optional pipeline git SHA for provenance.
        producer_model_id: Optional producer model ID.
        judge_model_id: Optional judge model ID.
        created_at: Optional creation timestamp (ISO-8601). Defaults to now.

    Returns:
        Path to the snapshot manifest.
    """
    run_dir = workspace_root / ".pdd_runs" / run_id
    snapshot_dir = run_dir / "snapshot"
    files_dir = snapshot_dir / "files"
    run_reports = workspace_root / "reports" / "pdd" / run_id
    produced_tree = workspace_root / "spec_snapshot"

    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[dict[str, Any]] = []

    if produced_tree.exists():
        manifest_entries.extend(
            _copy_tree(
                src=produced_tree,
                snapshot_files_root=files_dir,
                snapshot_prefix=Path("spec_snapshot"),
                source_prefix=Path("spec_snapshot"),
            )
        )
    else:
        logger.warning("Produced source tree missing for snapshot: %s", produced_tree)

    if run_reports.exists():
        reports_prefix = Path("reports") / "pdd" / run_id
        manifest_entries.extend(
            _copy_tree(
                src=run_reports,
                snapshot_files_root=files_dir,
                snapshot_prefix=reports_prefix,
                source_prefix=reports_prefix,
            )
        )
    else:
        logger.warning("Run-scoped reports missing for snapshot: %s", run_reports)

    model_ids = _read_model_ids(run_dir)
    resolved_created_at = created_at or datetime.now(UTC).isoformat()
    resolved_spec_hash = spec_hash or _read_spec_hash(run_dir)
    resolved_producer_model_id = (
        producer_model_id or model_ids.get("refinement", "") or model_ids.get("producer", "")
    )
    resolved_judge_model_id = judge_model_id or model_ids.get("judge", "")

    architecture_digest_hash = _hash_file(run_reports / "architecture_digest.json")
    code_digest_hash = _hash_file(run_reports / "code_digest.json")
    scorecard_paths = sorted(run_reports.glob("*scorecard*.json"))
    scorecards_hash = _hash_file_set(scorecard_paths)

    manifest = {
        "run_id": run_id,
        "comparison_id": comparison_id,
        "spec_hash": resolved_spec_hash,
        "pipeline_git_sha": pipeline_git_sha,
        "producer_model_id": resolved_producer_model_id,
        "judge_model_id": resolved_judge_model_id,
        "created_at": resolved_created_at,
        "paths": {
            "run_dir": f".pdd_runs/{run_id}/",
            "reports_dir": f"reports/pdd/{run_id}/",
            "snapshot_files_dir": f".pdd_runs/{run_id}/snapshot/files/",
        },
        "hashes": {
            "architecture_digest": architecture_digest_hash,
            "code_digest": code_digest_hash,
            "scorecards": scorecards_hash,
        },
        "file_count": len(manifest_entries),
        "files": manifest_entries,
    }
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (snapshot_dir / "snapshot_complete").write_text(resolved_created_at, encoding="utf-8")

    logger.info("Snapshot complete: %d files → %s", len(manifest_entries), snapshot_dir)
    return manifest_path


def _copy_tree(
    *,
    src: Path,
    snapshot_files_root: Path,
    snapshot_prefix: Path,
    source_prefix: Path,
) -> list[dict[str, Any]]:
    """Recursively copy files from src into snapshot files, returning entries."""
    entries: list[dict[str, Any]] = []
    dst = snapshot_files_root / snapshot_prefix
    dst.mkdir(parents=True, exist_ok=True)

    for fp in sorted(src.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fp, target)

        try:
            copied_bytes = target.read_bytes()
            sha = hashlib.sha256(copied_bytes).hexdigest()
            size_bytes = len(copied_bytes)
        except OSError:
            sha = ""
            size_bytes = 0

        snapshot_path = (snapshot_prefix / rel).as_posix()
        entries.append(
            {
                "path": snapshot_path,
                "snapshot_path": snapshot_path,
                "source_path": (source_prefix / rel).as_posix(),
                "sha256": sha,
                "size_bytes": size_bytes,
            }
        )

    return entries


def _hash_file(path: Path) -> str:
    """Return SHA-256 for file content, empty string if unavailable."""
    if not path.exists() or not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _hash_file_set(paths: list[Path]) -> str:
    """Return deterministic SHA-256 across a set of files."""
    if not paths:
        return ""

    tokens: list[str] = []
    for path in paths:
        file_hash = _hash_file(path)
        if file_hash:
            tokens.append(f"{path.as_posix()}:{file_hash}")
    if not tokens:
        return ""
    payload = "\n".join(sorted(tokens)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_spec_hash(run_dir: Path) -> str:
    """Read spec_hash from run artifacts when available."""
    spec_summary_path = run_dir / "spec_summary.json"
    data = _load_json(spec_summary_path)
    if isinstance(data, dict):
        value = data.get("spec_hash", "")
        if isinstance(value, str):
            return value
    return ""


def _read_model_ids(run_dir: Path) -> dict[str, str]:
    """Read model_ids from run_config.json when available."""
    config_path = run_dir / "run_config.json"
    config = _load_json(config_path)
    if not isinstance(config, dict):
        return {}
    model_ids = config.get("model_ids", {})
    if not isinstance(model_ids, dict):
        return {}
    return {str(k): str(v) for k, v in model_ids.items() if isinstance(v, str)}


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    """Read JSON from path, returning None when unavailable or invalid."""
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

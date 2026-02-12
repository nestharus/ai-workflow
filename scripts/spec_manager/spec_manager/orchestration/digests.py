"""Digest builders for architecture and code quality evaluation.

Build deterministic JSON digests from preserved pipeline artifacts.
These digests serve as inputs for LLM judges and mechanical scorers.

Usage::

    arch_digest = build_architecture_digest(workspace_root, run_id)
    code_digest = build_code_digest(workspace_root, run_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def build_architecture_digest(workspace_root: Path, run_id: str) -> dict[str, Any]:
    """Build architecture digest from pipeline artifacts.

    Reads component manifest, L2 findings, and architecture proposals
    to produce a unified architecture_digest.json.

    Args:
        workspace_root: Root of the PDD workspace.
        run_id: The run identifier.

    Returns:
        Architecture digest dict.
    """
    run_reports = workspace_root / "reports" / "pdd" / run_id
    global_reports = workspace_root / "reports"

    # Load component manifest
    manifest = _load_json(run_reports / "component_manifest.json") or _load_json(
        global_reports / "component_manifest.json"
    ) or {}

    components = manifest.get("components", [])
    topology = _build_topology(components)

    # Load architecture proposals
    proposals = _load_json(run_reports / "architecture_proposals.json") or _load_json(
        global_reports / "architecture_proposals.json"
    ) or {}

    # Load L2 findings
    l2_findings = _load_json(run_reports / "code_quality_report.json") or _load_json(
        global_reports / "code_quality_report.json"
    ) or {}
    l2_severity = _count_severity(l2_findings.get("findings", []))

    # Load spec summary if available
    spec_summary_path = workspace_root / ".pdd_runs" / run_id / "spec_summary.json"
    spec_summary = _load_json(spec_summary_path) or {}

    return {
        "run_id": run_id,
        "spec": {
            "spec_id": spec_summary.get("spec_id", ""),
            "spec_hash": spec_summary.get("spec_hash", ""),
        },
        "pipeline": {
            "git_sha": "",
            "pipeline_version": "",
        },
        "model": {
            "producer_model_id": "",
        },
        "topology": topology,
        "coverage": {
            "requirements_total": spec_summary.get("requirements_total", 0),
            "requirements_mapped": spec_summary.get("requirements_mapped", 0),
            "unmapped_requirements": spec_summary.get("unmapped_requirements", []),
        },
        "l2_review": {
            "final_findings": l2_severity,
        },
        "notes": {
            "architecture_proposals_path": str(
                run_reports / "architecture_proposals.json"
            ),
            "component_manifest_path": str(
                run_reports / "component_manifest.json"
            ),
        },
    }


def build_code_digest(workspace_root: Path, run_id: str) -> dict[str, Any]:
    """Build code digest from pipeline artifacts.

    Reads file list from snapshot, L3 findings, and CI results
    to produce a unified code_digest.json.

    Args:
        workspace_root: Root of the PDD workspace.
        run_id: The run identifier.

    Returns:
        Code digest dict.
    """
    run_dir = workspace_root / ".pdd_runs" / run_id
    run_reports = workspace_root / "reports" / "pdd" / run_id
    global_reports = workspace_root / "reports"

    # Build file list from snapshot or workspace
    snapshot_dir = run_dir / "snapshot" / "files"
    files_info = _build_file_list(snapshot_dir if snapshot_dir.exists() else workspace_root)

    # Load L3 / code quality findings
    code_quality = _load_json(run_reports / "code_quality_report.json") or _load_json(
        global_reports / "code_quality_report.json"
    ) or {}
    findings = code_quality.get("findings", [])
    l3_severity = _count_severity(findings)
    top_files = _top_files_by_findings(findings)

    # Load CI results if available
    ci_path = run_dir / "ci" / "results.json"
    ci_data = _load_json(ci_path) or {}

    # Spec info
    spec_summary_path = run_dir / "spec_summary.json"
    spec_summary = _load_json(spec_summary_path) or {}

    total_loc = sum(f.get("loc", 0) for f in files_info)

    return {
        "run_id": run_id,
        "spec": {
            "spec_id": spec_summary.get("spec_id", ""),
            "spec_hash": spec_summary.get("spec_hash", ""),
        },
        "pipeline": {"git_sha": ""},
        "model": {"producer_model_id": ""},
        "codebase": {
            "files": files_info,
            "totals": {"files": len(files_info), "loc": total_loc},
        },
        "l3_review": {
            "final_findings": l3_severity,
            "top_files": top_files,
        },
        "ci": {
            "final_pass": ci_data.get("final_pass", False),
            "first_pass": ci_data.get("first_pass", False),
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict | list | None:
    """Load a JSON file, returning None on any failure."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def _build_topology(components: list[dict]) -> dict[str, Any]:
    """Build topology dict from component manifest entries."""
    nodes: list[dict] = []
    edges: list[dict] = []

    for comp in components:
        comp_id = comp.get("component_id", comp.get("id", "unknown"))
        nodes.append({
            "id": comp_id,
            "type": comp.get("type", "unknown"),
            "summary": comp.get("summary", ""),
            "responsibilities": comp.get("responsibilities", []),
            "owned_data": comp.get("owned_data", []),
            "public_contracts": comp.get("public_contracts", []),
            "depends_on": comp.get("depends_on", []),
            "depended_by": comp.get("depended_by", []),
        })
        for dep in comp.get("depends_on", []):
            edges.append({"from": comp_id, "to": dep, "kind": "import"})

    return {"components": nodes, "edges": edges}


def _count_severity(findings: list[dict]) -> dict[str, int]:
    """Count findings by severity level."""
    counts: dict[str, int] = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0}
    for f in findings:
        sev = f.get("severity", "MINOR").upper()
        if sev in counts:
            counts[sev] += 1
    return counts


def _top_files_by_findings(findings: list[dict], k: int = 5) -> list[dict]:
    """Return top K files sorted by finding count."""
    by_file: dict[str, dict[str, int]] = {}
    for f in findings:
        path = f.get("file", f.get("path", "unknown"))
        if path not in by_file:
            by_file[path] = {"path": path, "MAJOR": 0, "MINOR": 0}
        sev = f.get("severity", "MINOR").upper()
        if sev in ("MAJOR", "BLOCKER"):
            by_file[path]["MAJOR"] += 1
        else:
            by_file[path]["MINOR"] += 1

    sorted_files = sorted(by_file.values(), key=lambda x: x["MAJOR"] * 3 + x["MINOR"], reverse=True)
    return sorted_files[:k]


def _build_file_list(directory: Path) -> list[dict[str, Any]]:
    """Build file info list from a directory of files."""
    files: list[dict[str, Any]] = []
    if not directory.exists():
        return files

    for fp in sorted(directory.rglob("*")):
        if fp.is_file() and not fp.name.startswith("."):
            try:
                content = fp.read_bytes()
                loc = content.count(b"\n")
                sha = hashlib.sha256(content).hexdigest()
                files.append({
                    "path": str(fp.relative_to(directory)),
                    "loc": loc,
                    "sha256": sha,
                    "role_hint": "",
                })
            except OSError:
                continue

    return files

"""Digest builders for architecture and code quality evaluation.

Build deterministic JSON digests from preserved pipeline artifacts.
These digests serve as inputs for LLM judges and mechanical scorers.

Usage::

    arch_digest = build_architecture_digest(
        workspace_root, run_id, git_sha="<sha>", producer_model_id="<model>"
    )
    code_digest = build_code_digest(
        workspace_root, run_id, git_sha="<sha>", producer_model_id="<model>"
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def build_architecture_digest(
    workspace_root: Path,
    run_id: str,
    *,
    git_sha: str,
    producer_model_id: str,
) -> dict[str, Any]:
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
    manifest_path = run_reports / "component_manifest.json"
    proposals_path = run_reports / "architecture_proposals.json"

    # Load run-scoped component manifest (strict: no global fallback).
    manifest_data = _load_json(manifest_path)
    manifest = manifest_data if isinstance(manifest_data, dict) else {}
    if not manifest:
        logger.warning("Run-scoped component manifest missing or unreadable: %s", manifest_path)

    components = manifest.get("components", [])
    topology = _build_topology(components)

    # Load run-scoped architecture proposals.
    proposals_data = _load_json(proposals_path)
    proposals = proposals_data if isinstance(proposals_data, dict) else {}
    if not proposals:
        logger.warning(
            "Run-scoped architecture proposals missing or unreadable: %s", proposals_path
        )

    # Load run-scoped L2 architecture findings from architecture proposals.
    issues = proposals.get("issues", [])
    l2_issues = issues if isinstance(issues, list) else []
    l2_severity = _count_severity(l2_issues)

    # Load spec summary if available
    spec_summary_path = workspace_root / ".pdd_runs" / run_id / "spec_summary.json"
    spec_summary_data = _load_json(spec_summary_path)
    spec_summary = spec_summary_data if isinstance(spec_summary_data, dict) else {}
    if not spec_summary_data:
        logger.warning("Run-scoped spec summary missing or unreadable: %s", spec_summary_path)
    spec_requirements = _normalize_requirement_items(
        spec_summary.get("requirements", spec_summary.get("top_requirements", []))
    )
    if not spec_requirements:
        spec_requirements = _normalize_requirement_items(
            spec_summary.get("unmapped_requirements", [])
        )

    return {
        "run_id": run_id,
        "spec": {
            "spec_id": spec_summary.get("spec_id", ""),
            "spec_hash": spec_summary.get("spec_hash", ""),
            "summary": _extract_spec_summary_text(spec_summary),
            "requirements": spec_requirements,
        },
        "pipeline": {
            "git_sha": git_sha,
            "pipeline_version": "",
        },
        "model": {
            "producer_model_id": producer_model_id,
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
            "architecture_proposals_path": str(proposals_path),
            "architecture_candidates": len(proposals.get("candidates", [])),
            "architecture_issues": len(l2_issues),
            "component_manifest_path": str(manifest_path),
        },
    }


def build_code_digest(
    workspace_root: Path,
    run_id: str,
    *,
    git_sha: str,
    producer_model_id: str,
) -> dict[str, Any]:
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
    quality_report_path = run_reports / "code_quality_report.json"

    # Build file list from run snapshot only (no workspace/global fallback).
    snapshot_dir = run_dir / "snapshot" / "files" / "spec_snapshot"
    if snapshot_dir.exists():
        (
            files_info,
            duplication_ratio,
            long_line_ratio,
            inventory_read_errors,
        ) = _build_file_inventory(snapshot_dir, run_id)
    else:
        logger.warning("Run snapshot missing for code digest: %s", snapshot_dir)
        files_info = []
        duplication_ratio = 0.0
        long_line_ratio = 0.0
        inventory_read_errors = []

    # Load run-scoped L3 / code quality findings.
    quality_data = _load_json(quality_report_path)
    code_quality = quality_data if isinstance(quality_data, dict) else {}
    if not code_quality:
        logger.warning("Run-scoped quality report missing or unreadable: %s", quality_report_path)
    findings = code_quality.get("findings", [])
    l3_severity = _count_severity(findings)
    top_files = _top_files_by_findings(findings)

    # Load CI results if available
    ci_path = run_dir / "ci" / "results.json"
    ci_data_raw = _load_json(ci_path)
    ci_data = ci_data_raw if isinstance(ci_data_raw, dict) else {}

    # Spec info
    spec_summary_path = run_dir / "spec_summary.json"
    spec_summary_raw = _load_json(spec_summary_path)
    spec_summary = spec_summary_raw if isinstance(spec_summary_raw, dict) else {}

    total_loc = sum(f.get("loc", 0) for f in files_info)

    return {
        "run_id": run_id,
        "spec": {
            "spec_id": spec_summary.get("spec_id", ""),
            "spec_hash": spec_summary.get("spec_hash", ""),
        },
        "pipeline": {"git_sha": git_sha},
        "model": {"producer_model_id": producer_model_id},
        "codebase": {
            "files": files_info,
            "totals": {"files": len(files_info), "loc": total_loc},
            "metrics": {
                "duplication_ratio": duplication_ratio,
                "long_line_ratio": long_line_ratio,
            },
            "read_errors": inventory_read_errors,
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
        nodes.append(
            {
                "id": comp_id,
                "type": comp.get("type", "unknown"),
                "summary": comp.get("summary", ""),
                "responsibilities": comp.get("responsibilities", []),
                "owned_data": comp.get("owned_data", []),
                "public_contracts": comp.get("public_contracts", []),
                "depends_on": comp.get("depends_on", []),
                "depended_by": comp.get("depended_by", []),
            }
        )
        for dep in comp.get("depends_on", []):
            edges.append({"from": comp_id, "to": dep, "kind": "import"})

    return {"components": nodes, "edges": edges}


def _count_severity(findings: list[dict]) -> dict[str, int]:
    """Count findings by severity level."""
    counts: dict[str, int] = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        sev = finding.get("severity", "MINOR").upper()
        if sev in counts:
            counts[sev] += 1
    return counts


def _extract_spec_summary_text(spec_summary: dict[str, Any]) -> str:
    """Extract a concise summary text from a spec summary artifact."""
    for key in ("summary", "spec_summary", "description", "overview"):
        value = spec_summary.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_requirement_items(requirements: Any) -> list[str]:
    """Normalize requirement entries (strings/dicts) into concise text items."""
    if not isinstance(requirements, list):
        return []

    normalized: list[str] = []
    for requirement in requirements:
        text = ""
        if isinstance(requirement, str):
            text = requirement.strip()
        elif isinstance(requirement, dict):
            for key in ("requirement", "text", "description", "summary", "title"):
                value = requirement.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
        if text:
            normalized.append(text)

    return normalized


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


def _build_file_inventory(
    directory: Path, run_id: str
) -> tuple[list[dict[str, Any]], float, float, list[dict[str, str]]]:
    """Build code file list plus text-level mechanical metrics."""
    files: list[dict[str, Any]] = []
    read_errors: list[dict[str, str]] = []
    if not directory.exists():
        return files, 0.0, 0.0, read_errors

    shingle_size = 5
    shingle_counts: dict[str, int] = {}
    total_shingles = 0
    long_lines = 0
    total_lines = 0

    for fp in sorted(directory.rglob("*")):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        try:
            content = fp.read_bytes()
            text = content.decode("utf-8", errors="replace")
            lines = text.splitlines()
            loc = len(lines)
            sha = hashlib.sha256(content).hexdigest()
            rel_path = str(fp.relative_to(directory))
            files.append(
                {
                    "path": rel_path,
                    "loc": loc,
                    "sha256": sha,
                    "role_hint": "",
                    "snapshot_path": (
                        f".pdd_runs/{run_id}/snapshot/files/spec_snapshot/{rel_path}"
                    ),
                }
            )

            total_lines += loc
            long_lines += sum(1 for line in lines if len(line) > 120)

            normalized_lines = [line.rstrip() for line in lines]
            if len(normalized_lines) >= shingle_size:
                for index in range(0, len(normalized_lines) - shingle_size + 1):
                    shingle = "\n".join(normalized_lines[index : index + shingle_size])
                    shingle_hash = hashlib.sha256(shingle.encode("utf-8")).hexdigest()
                    shingle_counts[shingle_hash] = shingle_counts.get(shingle_hash, 0) + 1
                    total_shingles += 1
        except OSError:
            relative_path = fp.relative_to(directory).as_posix()
            logger.warning(
                "Failed to read snapshot file for digest inventory: %s", fp, exc_info=True
            )
            read_errors.append(
                {
                    "path": relative_path,
                    "error": "os_error",
                }
            )
            continue

    duplicated_occurrences = sum(count - 1 for count in shingle_counts.values() if count > 1)
    duplication_ratio = duplicated_occurrences / total_shingles if total_shingles > 0 else 0.0
    long_line_ratio = long_lines / total_lines if total_lines > 0 else 0.0

    return files, duplication_ratio, long_line_ratio, read_errors

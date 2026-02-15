"""Per-slice iterative PromotionLoop.

Replaces the sequential P0-P10 pipeline with a per-slice loop that
invokes phases as tools until all gaps are closed and all atoms are
promoted through compliance gates.

State machine (per slice)::

    START_ITER
      ↓
    COLLECT_BASELINE   (diff/hash + manifest)
      ↓
    GAP_EXPLORATION    (P3 + GapQueue view)
      ↓
    PLAN               (P8)
      ↓
    IMPLEMENT          (P9) ← emits patch + pin/edge proposals + evidence
      ↓
    UNDER_SPEC_CHECK   (block-or-decide)
      ↓
    ANALYZE            (P1 + P2 + analyze_source cache)
      ↓
    PROMOTE            (P4/P5 promotion + compliance gates + refinement)
      ├─ if gates fail → DEMOTE → RESTART_ITER
      ↓
    INTEGRATE          (merge to parent dirty + trigger CI tick)
      ├─ if merge conflicts persist → DEMOTE + BLOCK
      ↓
    VERIFY             (P6 + P7 + architectural gates)
      ├─ if verify fails → DEMOTE → RESTART_ITER
      ↓
    DONE?              (termination checks)
      ├─ if done → SLICE_COMPLETE
      └─ else → NEXT_ITER

Usage::

    loop = PromotionLoop(worktree_manager=wm, workspace_root=Path("."))
    result = loop.run_slice(slice_ref, run_context)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from difflib import unified_diff
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any, Literal, Protocol, cast

from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
from spec_manager.orchestration.evidence import EvidenceBundle
from spec_manager.orchestration.models import Layer

logger = logging.getLogger(__name__)


_DISABLE_L1_GAP_SCAN_KEY = "disable_l1_gap_scan"
_QUALITY_RECEIPTS_FILENAME = "quality.receipts.json"
_L3_REVIEWERS_CONFIG_KEY = "l3_reviewers"
InteractionMode = Literal["interactive", "auto"]
LifecycleRunMode = Literal["build", "qa", "architecture", "code_quality"]


@dataclass(frozen=True)
class ReviewerSpec:
    """Definition of one reviewer pass in a layer review pack."""

    reviewer_id: str
    agent_name: str
    dimension: str
    objective: str
    default_category: str = "style"
    default_required_change_type: str = "refactor_only"


L2_REVIEW_PACK: tuple[ReviewerSpec, ...] = (
    ReviewerSpec(
        reviewer_id="pdd-l2-arch-boundary-reviewer",
        agent_name="pdd-l2-arch-boundary-reviewer",
        dimension="ARCH_BOUNDARY",
        objective=(
            "Validate boundaries, responsibilities, and dependency direction between components."
        ),
        default_category="architecture",
        default_required_change_type="wiring_only",
    ),
    ReviewerSpec(
        reviewer_id="pdd-l2-topology-reviewer",
        agent_name="pdd-l2-topology-reviewer",
        dimension="TOPOLOGY",
        objective="Validate topology connectivity, reachability, and handler chain completeness.",
        default_category="architecture",
        default_required_change_type="wiring_only",
    ),
    ReviewerSpec(
        reviewer_id="pdd-l2-pin-edge-reviewer",
        agent_name="pdd-l2-pin-edge-reviewer",
        dimension="PIN_COVERAGE",
        objective="Validate pin consumption and edge realization against declared architecture.",
        default_category="architecture",
        default_required_change_type="wiring_only",
    ),
    ReviewerSpec(
        reviewer_id="pdd-l2-arch-drift-reviewer",
        agent_name="pdd-l2-arch-drift-reviewer",
        dimension="ARCH_DRIFT",
        objective="Detect drift between declared architecture artifacts and realized wiring.",
        default_category="drift",
        default_required_change_type="wiring_only",
    ),
    ReviewerSpec(
        reviewer_id="pdd-l2-governance-reviewer",
        agent_name="pdd-l2-governance-reviewer",
        dimension="GOVERNANCE",
        objective="Validate receipts, governance controls, and authorized wiring changes.",
        default_category="governance",
        default_required_change_type="wiring_only",
    ),
)

L3_REVIEW_PACK: tuple[ReviewerSpec, ...] = (
    ReviewerSpec(
        reviewer_id="chatgpt-clarity-reviewer",
        agent_name="chatgpt-clarity-reviewer",
        dimension="CLARITY",
        objective="Assess readability, naming intent, and cognitive load.",
        default_category="style",
    ),
    ReviewerSpec(
        reviewer_id="chatgpt-consistency-reviewer",
        agent_name="chatgpt-consistency-reviewer",
        dimension="CONSISTENCY",
        objective="Assess API and convention consistency across the touched scope.",
        default_category="style",
    ),
    ReviewerSpec(
        reviewer_id="chatgpt-maintainability-reviewer",
        agent_name="chatgpt-completeness-reviewer",
        dimension="MAINTAINABILITY",
        objective=(
            "Assess structure, complexity, decomposition quality, and avoidable duplication."
        ),
        default_category="maintainability",
    ),
    ReviewerSpec(
        reviewer_id="chatgpt-correctness-reviewer",
        agent_name="chatgpt-correctness-reviewer",
        dimension="CORRECTNESS",
        objective="Assess correctness, safety, invariants, and error-path robustness.",
        default_category="logic",
        default_required_change_type="behavior_change",
    ),
    ReviewerSpec(
        reviewer_id="pdd-l3-drift-reviewer",
        agent_name="pdd-l3-drift-reviewer",
        dimension="DRIFT",
        objective="Detect unplanned behavior and plan/design drift.",
        default_category="drift",
    ),
    ReviewerSpec(
        reviewer_id="pdd-l3-diff-impact-classifier",
        agent_name="chatgpt-correctness-reviewer",
        dimension="DIFF_IMPACT",
        objective=(
            "Classify whether the diff is behavior-preserving; flag any behavior-changing edits."
        ),
        default_category="diff-impact",
        default_required_change_type="behavior_change",
    ),
)


def _hash_bytes(content: bytes) -> str:
    """Return stable SHA256 hex digest for content."""
    return hashlib.sha256(content).hexdigest()


def _hash_text(content: str) -> str:
    """Return stable SHA256 hex digest for text."""
    return _hash_bytes(content.encode("utf-8"))


def _safe_rel(path: Path, root: Path) -> str:
    """Return path relative to root, or best-effort fallback."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _location_span(
    *,
    start_line: Any = None,
    end_line: Any = None,
    start_col: Any = None,
    end_col: Any = None,
) -> dict[str, int]:
    """Normalize location payload into an explicit span dict."""
    span: dict[str, int] = {}
    if isinstance(start_line, int) and start_line > 0:
        span["start_line"] = start_line
    if isinstance(end_line, int) and end_line > 0:
        span["end_line"] = end_line
    elif "start_line" in span:
        span["end_line"] = span["start_line"]
    if isinstance(start_col, int) and start_col >= 0:
        span["start_col"] = start_col
    if isinstance(end_col, int) and end_col >= 0:
        span["end_col"] = end_col
    return span


def _normalize_gap_record(gap: dict[str, Any]) -> dict[str, Any]:
    """Ensure every gap has explicit location/span metadata."""
    location = gap.get("location", {}) or {}
    span = gap.get("span", {}) or {}
    normalized_span = _location_span(
        start_line=span.get("start_line") or location.get("start_line"),
        end_line=span.get("end_line") or location.get("end_line"),
        start_col=span.get("start_col") or location.get("start_col"),
        end_col=span.get("end_col") or location.get("end_col"),
    )
    file_path = gap.get("file", "") or location.get("file", "")
    merged = dict(gap)
    merged["file"] = file_path
    merged["component_id"] = str(merged.get("component_id", "")).strip()
    merged["anchor"] = str(merged.get("anchor", "")).strip()
    merged["expected"] = str(merged.get("expected", "")).strip()
    merged["span"] = normalized_span
    merged["location"] = {"file": file_path, **normalized_span}
    return merged


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def _evidence_base_path(*, slice_root: str, workspace_root: str) -> Path:
    """Resolve the base directory used for evidence artifacts."""
    if workspace_root:
        return Path(workspace_root)
    if slice_root:
        return Path(slice_root)
    return Path(".")


def _bundle_json_path(base: Path, run_id: str, slice_id: str, iteration: int) -> Path:
    """Return the canonical bundle.json path for an iteration."""
    return (
        base / ".pdd_runs" / run_id / "slices" / slice_id / f"iter_{iteration:03d}" / "bundle.json"
    )


def _write_iteration_json(bundle: EvidenceBundle, evidence_root: Path, name: str, data: Any) -> str:
    """Write a JSON artifact in the current iteration directory and return filename."""
    iteration_dir = bundle.iter_dir(evidence_root)
    iteration_dir.mkdir(parents=True, exist_ok=True)
    path = iteration_dir / name
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path.name


def _read_json_file(path: Path) -> dict[str, Any] | list[Any] | None:
    """Load JSON payload from *path* when present and valid."""
    if not path.exists() or not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(loaded, dict | list):
        return loaded
    return None


def _normalize_focus_targets(raw: Any) -> dict[str, list[str]]:
    """Normalize focus targets payload to canonical string-list fields."""
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for key in ("failing_files", "failing_pins", "failing_atoms", "location_symbols"):
        values = raw.get(key, [])
        if not isinstance(values, list):
            continue
        seen: set[str] = set()
        cleaned: list[str] = []
        for value in values:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if cleaned:
            normalized[key] = cleaned
    return normalized


def _path_matches_focus(path: str, focus_files: set[str]) -> bool:
    """Return True when *path* matches one of the focused file hints."""
    normalized = str(path).strip().replace("\\", "/")
    if not normalized:
        return False
    return any(
        normalized == focused
        or normalized.endswith(f"/{focused}")
        or focused.endswith(f"/{normalized}")
        for focused in focus_files
    )


def _run_git_in_worktree(
    worktree: Path,
    args: list[str],
) -> tuple[bool, str, str]:
    """Run a git command in a worktree and return ``(ok, stdout, stderr)``."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=worktree,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return False, "", str(exc)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    return completed.returncode == 0, stdout, stderr


def _apply_investigator_patch(
    *,
    layer_worktree: Path,
    patch: str,
    run_id: str,
    layer: Layer,
    slice_id: str,
    attempt: int,
) -> dict[str, Any]:
    """Apply investigator patch in the active layer worktree and commit it."""
    if not patch.strip():
        return {"applied": False, "error": "Investigator returned an empty patch"}
    if not layer_worktree.exists() or not layer_worktree.is_dir():
        return {
            "applied": False,
            "error": f"Layer worktree does not exist: {layer_worktree}",
        }

    patch_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=layer_worktree,
            prefix="investigator_",
            suffix=".diff",
        ) as handle:
            handle.write(patch)
            patch_path = Path(handle.name)

        ok, _, err = _run_git_in_worktree(layer_worktree, ["apply", "--check", str(patch_path)])
        if not ok:
            return {"applied": False, "error": err or "git apply --check failed"}

        ok, _, err = _run_git_in_worktree(layer_worktree, ["apply", str(patch_path)])
        if not ok:
            return {"applied": False, "error": err or "git apply failed"}

        ok, _, err = _run_git_in_worktree(layer_worktree, ["add", "-A"])
        if not ok:
            return {"applied": False, "error": err or "git add failed"}

        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=layer_worktree,
            check=False,
            capture_output=True,
            text=True,
        )
        if staged.returncode not in (0, 1):
            return {
                "applied": False,
                "error": staged.stderr.strip() or "Unable to inspect staged changes",
            }
        if staged.returncode == 0:
            return {
                "applied": False,
                "error": "Investigator patch produced no staged changes",
            }

        message = (
            f"pdd investigator recovery run={run_id} layer={layer} "
            f"slice={slice_id} attempt={attempt}"
        )
        ok, _, err = _run_git_in_worktree(layer_worktree, ["commit", "-m", message])
        if not ok:
            return {"applied": False, "error": err or "git commit failed"}

        _, sha, _ = _run_git_in_worktree(layer_worktree, ["rev-parse", "HEAD"])
        return {"applied": True, "head_sha": sha}
    finally:
        if patch_path is not None:
            with contextlib.suppress(OSError):
                patch_path.unlink()


def attempt_investigator_recovery(
    *,
    run_id: str,
    slice_id: str,
    layer: Layer,
    workspace_root: Path,
    layer_worktree: Path,
    failure_refs: list[str],
    failure_evidence: dict[str, Any] | None = None,
    investigator_budget: int = 2,
    verify_callback: Callable[[int, dict[str, Any]], tuple[bool, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run bounded investigator recovery with patch apply + optional verification."""
    from spec_manager.core.agent_utils import run_agent
    from spec_manager.core.json_extraction import _extract_json_payload
    from spec_manager.refinement.formats import _strip_code_fences

    if not workspace_root.exists() or not workspace_root.is_dir():
        return {
            "fixed": False,
            "attempts": [],
            "error": f"Workspace root does not exist: {workspace_root}",
        }
    if not layer_worktree.exists() or not layer_worktree.is_dir():
        return {
            "fixed": False,
            "attempts": [],
            "error": f"Layer worktree does not exist: {layer_worktree}",
        }

    failure_refs = [str(ref).strip() for ref in failure_refs if str(ref).strip()]
    if not failure_refs:
        failure_refs = ["investigator-triggered-without-explicit-failure-ref"]
    evidence_payload = failure_evidence if isinstance(failure_evidence, dict) else {}
    evidence_json = json.dumps(evidence_payload, indent=2, ensure_ascii=False)

    layer_rules = (
        "- L1: may change function bodies\n"
        "- L2: wiring only, no new logic\n"
        "- L3: refactor only, no behavior change\n"
    )
    max_refs = 12
    report: dict[str, Any] = {
        "fixed": False,
        "run_id": run_id,
        "slice_id": slice_id,
        "layer": layer,
        "layer_worktree": str(layer_worktree),
        "budget": max(1, int(investigator_budget)),
        "attempts": [],
        "failure_refs": failure_refs[:max_refs],
    }

    for attempt in range(1, max(1, int(investigator_budget)) + 1):
        logger.info(
            "Investigator attempt %d/%d for layer '%s' slice '%s'",
            attempt,
            max(1, int(investigator_budget)),
            layer,
            slice_id,
        )
        attempt_entry: dict[str, Any] = {
            "attempt": attempt,
            "fixed": False,
            "patch_applied": False,
        }
        try:
            prompt = (
                "## TASK\n"
                "CI/integration failure occurred. Investigate and produce a legal "
                "layer-scoped fix.\n"
                "You are operating inside the active layer worktree.\n\n"
                f"Run ID: {run_id}\n"
                f"Slice ID: {slice_id}\n"
                f"Layer: {layer}\n\n"
                "Layer legality constraints:\n"
                f"{layer_rules}\n"
                "Failure refs:\n"
                + "\n".join(f"- {ref}" for ref in failure_refs[:max_refs])
                + "\n\nFailure evidence JSON:\n"
                + evidence_json[:12000]
                + "\n\nReturn ONLY JSON with this schema:\n"
                '{"fixed": true|false, "root_cause": "...", '
                '"reproduction_steps": ["..."], "patch": "...unified diff...", '
                '"evidence_refs": ["..."]}\n'
                "If not fixed, set fixed=false and still include root_cause, "
                "reproduction_steps, and evidence_refs."
            )
            output = run_agent(
                agent_name="pdd-investigator",
                prompt=prompt,
                workspace=layer_worktree,
            )
            cleaned = _strip_code_fences(output)
            raw = json.loads(_extract_json_payload(cleaned))
            root_cause = str(raw.get("root_cause", "")).strip()

            reproduction_raw = raw.get("reproduction_steps", [])
            if isinstance(reproduction_raw, str):
                reproduction_steps = [reproduction_raw.strip()] if reproduction_raw.strip() else []
            elif isinstance(reproduction_raw, list):
                reproduction_steps = [
                    str(step).strip() for step in reproduction_raw if str(step).strip()
                ]
            else:
                reproduction_steps = []

            refs_raw = raw.get("evidence_refs", [])
            if isinstance(refs_raw, str):
                evidence_refs = [refs_raw.strip()] if refs_raw.strip() else []
            elif isinstance(refs_raw, list):
                evidence_refs = [str(ref).strip() for ref in refs_raw if str(ref).strip()]
            else:
                evidence_refs = []

            patch = str(raw.get("patch", "")).strip()
            fixed = bool(raw.get("fixed", False))
            normalized = {
                "fixed": fixed,
                "root_cause": root_cause,
                "reproduction_steps": reproduction_steps,
                "patch": patch,
                "evidence_refs": evidence_refs,
            }
            attempt_entry["result"] = {
                "root_cause": root_cause,
                "reproduction_steps": reproduction_steps,
                "evidence_refs": evidence_refs,
                "fixed": fixed,
            }

            if not fixed:
                report["attempts"].append(attempt_entry)
                continue

            patch_result = _apply_investigator_patch(
                layer_worktree=layer_worktree,
                patch=patch,
                run_id=run_id,
                layer=layer,
                slice_id=slice_id,
                attempt=attempt,
            )
            attempt_entry["patch_result"] = patch_result
            if not patch_result.get("applied", False):
                report["attempts"].append(attempt_entry)
                continue
            attempt_entry["patch_applied"] = True

            verified = True
            verification_details: dict[str, Any] = {}
            if verify_callback is not None:
                try:
                    verified, verification_details = verify_callback(attempt, normalized)
                except Exception as exc:
                    verified, verification_details = False, {"error": str(exc)}
            attempt_entry["verified"] = bool(verified)
            attempt_entry["verification"] = verification_details
            report["attempts"].append(attempt_entry)

            if verified:
                attempt_entry["fixed"] = True
                report["fixed"] = True
                report["resolved_at_attempt"] = attempt
                report["investigator_result"] = normalized
                report["verification"] = verification_details
                return report
        except Exception as exc:
            attempt_entry["error"] = str(exc)
            report["attempts"].append(attempt_entry)

    report["fixed"] = False
    return report


def _quality_receipts_iteration_path(
    base: Path,
    *,
    run_id: str,
    slice_id: str,
    iteration: int,
) -> Path:
    """Return quality-receipt path for a specific slice iteration."""
    return (
        base
        / ".pdd_runs"
        / run_id
        / "slices"
        / slice_id
        / f"iter_{iteration:03d}"
        / _QUALITY_RECEIPTS_FILENAME
    )


def _normalize_receipt_status(raw: Any) -> str:
    status = str(raw or "PASS").strip().upper()
    return status if status in {"PASS", "FAIL"} else "FAIL"


def _normalize_quality_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Normalize a quality receipt into canonical key fields."""
    reviewer_id = str(
        receipt.get("reviewer_id") or receipt.get("reviewer") or receipt.get("agent_name") or ""
    ).strip()
    dimension = str(receipt.get("dimension") or "").strip()
    file_path = str(receipt.get("file") or receipt.get("target_file") or "").strip()
    file_hash = str(receipt.get("file_hash") or receipt.get("content_hash") or "").strip()
    status = _normalize_receipt_status(receipt.get("status"))
    findings = [item for item in receipt.get("findings", []) if isinstance(item, dict)]
    finding_count = receipt.get("finding_count")
    if not isinstance(finding_count, int):
        finding_count = len(findings)
    merged = dict(receipt)
    merged["reviewer_id"] = reviewer_id
    merged["dimension"] = dimension
    merged["file"] = file_path
    merged["file_hash"] = file_hash
    merged["status"] = status
    merged["findings"] = findings
    merged["finding_count"] = max(finding_count, 0)
    merged["recorded_at"] = str(receipt.get("recorded_at") or _now_iso())
    return merged


def _quality_receipts_from_payload(
    payload: dict[str, Any] | list[Any] | None,
) -> list[dict[str, Any]]:
    """Extract normalized receipt list from JSON payload."""
    raw: list[Any]
    if isinstance(payload, dict):
        raw = payload.get("receipts", [])
    elif isinstance(payload, list):
        raw = payload
    else:
        raw = []
    return [_normalize_quality_receipt(item) for item in raw if isinstance(item, dict)]


def _quality_receipt_key(receipt: dict[str, Any]) -> str:
    return "::".join(
        (
            str(receipt.get("reviewer_id") or "").strip(),
            str(receipt.get("file") or "").strip(),
            str(receipt.get("file_hash") or "").strip(),
        )
    )


def _latest_quality_receipts_by_key(receipts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return latest receipt per reviewer/file/hash key."""
    latest: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        key = _quality_receipt_key(receipt)
        if not key.strip(":"):
            continue
        latest[key] = receipt
    return latest


def _configured_l3_review_pack(
    config: dict[str, Any] | None,
    *,
    include_diff_impact: bool,
) -> tuple[ReviewerSpec, ...]:
    """Resolve configured L3 reviewers, falling back to default pack."""
    default_pack = tuple(
        reviewer
        for reviewer in L3_REVIEW_PACK
        if include_diff_impact or reviewer.dimension != "DIFF_IMPACT"
    )
    if not isinstance(config, dict):
        return default_pack

    configured = config.get(_L3_REVIEWERS_CONFIG_KEY)
    if not isinstance(configured, list) or not configured:
        return default_pack

    selected_tokens = {str(item).strip().lower() for item in configured if str(item).strip()}
    if not selected_tokens:
        return default_pack

    selected = [
        reviewer
        for reviewer in default_pack
        if (
            reviewer.reviewer_id.lower() in selected_tokens
            or reviewer.dimension.lower() in selected_tokens
            or reviewer.agent_name.lower() in selected_tokens
        )
    ]
    return tuple(selected or default_pack)


def _load_iteration_quality_receipts(
    *,
    evidence_root: Path,
    bundle: EvidenceBundle,
) -> list[dict[str, Any]]:
    """Load quality receipts for the current iteration when available."""
    path = bundle.iter_dir(evidence_root) / _QUALITY_RECEIPTS_FILENAME
    return _quality_receipts_from_payload(_read_json_file(path))


def _write_iteration_quality_receipts(
    *,
    ctx: SliceContext,
    bundle: EvidenceBundle,
    evidence_root: Path,
    stage: str,
    receipts: list[dict[str, Any]],
) -> None:
    """Persist normalized quality receipts for the current iteration."""
    normalized = [_normalize_quality_receipt(item) for item in receipts if isinstance(item, dict)]
    _write_iteration_json(
        bundle,
        evidence_root,
        _QUALITY_RECEIPTS_FILENAME,
        {
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "run_id": ctx.run_id,
            "iteration": bundle.iteration,
            "stage": stage,
            "content_hash": bundle.diff.content_hash,
            "receipts": normalized,
        },
    )
    if _QUALITY_RECEIPTS_FILENAME not in bundle.manifest.generated_files:
        bundle.manifest.generated_files.append(_QUALITY_RECEIPTS_FILENAME)


def _run_component_manifest_path(workspace_root: Path, run_id: str) -> Path:
    """Return canonical run-scoped component manifest path."""
    return workspace_root / "reports" / "pdd" / run_id / "component_manifest.json"


def _load_run_component_manifest(workspace_root: Path, run_id: str) -> list[dict[str, Any]]:
    """Load normalized run-scoped component manifest records."""
    payload = _read_json_file(_run_component_manifest_path(workspace_root, run_id))
    if not isinstance(payload, dict):
        return []

    components_raw = payload.get("components", [])
    if not isinstance(components_raw, list):
        return []

    components: list[dict[str, Any]] = []
    for comp in components_raw:
        if not isinstance(comp, dict):
            continue
        component_id = str(comp.get("component_id") or comp.get("id") or "").strip()
        if not component_id:
            continue
        files = [str(path) for path in (comp.get("files") or []) if isinstance(path, str)]
        owned_entrypoints = [
            str(item) for item in (comp.get("owned_entrypoints") or []) if isinstance(item, str)
        ]
        pins_consumed = [
            str(item) for item in (comp.get("pins_consumed") or []) if isinstance(item, str)
        ]
        components.append(
            {
                "component_id": component_id,
                "files": files,
                "owned_entrypoints": owned_entrypoints,
                "pins_consumed": pins_consumed,
                "upstream": [
                    str(item) for item in (comp.get("upstream") or []) if isinstance(item, str)
                ],
                "downstream": [
                    str(item) for item in (comp.get("downstream") or []) if isinstance(item, str)
                ],
            }
        )
    return components


def _load_pin_registry_snapshot(slice_root: Path) -> dict[str, Any]:
    """Load normalized pin/edge payload from ``.spec/pin_registry.json``."""
    path = slice_root / ".spec" / "pin_registry.json"
    payload = _read_json_file(path)
    if not isinstance(payload, dict):
        return {
            "path": str(path),
            "exists": False,
            "pins": [],
            "edges": [],
        }

    pins = [item for item in payload.get("pin_functions", []) if isinstance(item, dict)]
    edges = [item for item in payload.get("import_edges", []) if isinstance(item, dict)]
    return {
        "path": str(path),
        "exists": True,
        "pins": pins,
        "edges": edges,
    }


# ------------------------------------------------------------------
# Step protocol and result types
# ------------------------------------------------------------------


@dataclass
class StepResult:
    """Result of running a single loop step."""

    status: Literal["OK", "RETRY", "BLOCKED", "FAIL", "WAITING"] = "OK"
    bundle_path: str = ""
    emitted_tickets: list[DemotionTicket] = field(default_factory=list)
    notes_path: str | None = None
    error: str = ""


class LoopStep(Protocol):
    """Protocol for a single step in the promotion loop."""

    name: str

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Execute this step."""
        ...


@dataclass
class SliceRef:
    """Reference to a slice of work."""

    slice_id: str
    layer: Layer = "l1"
    library_id: str = ""
    worktree_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    """Run-scoped context shared across all slices."""

    run_id: str = ""
    mode: InteractionMode = "auto"
    lifecycle_mode: LifecycleRunMode = "build"
    workspace_root: str = ""
    max_iterations: int = 20
    max_iterations_by_layer: dict[str, int] = field(
        default_factory=lambda: {"l1": 20, "l2": 30, "l3": 15}
    )
    max_wait_cycles: int = 10
    config: dict[str, Any] = field(default_factory=dict)
    ci_tick_callback: Callable[[str], dict[str, Any] | None] | None = None
    ci_periodic_tick_callback: Callable[[], None] | None = None
    ci_periodic_tick_interval_sec: float = 20.0


@dataclass
class SeedGapSet:
    """Optional scheduler-provided gap set to seed iteration 1."""

    open_gaps: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""


@dataclass
class SliceContext:
    """Per-slice context for loop steps."""

    slice_id: str = ""
    slice_root: str = ""  # grandchild worktree path
    dirty_parent_root: str = ""
    clean_sibling_root: str = ""
    layer: Layer = "l1"
    run_id: str = ""
    mode: InteractionMode = "auto"
    lifecycle_mode: LifecycleRunMode = "build"
    workspace_root: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    ci_tick_callback: Callable[[str], dict[str, Any] | None] | None = None
    ci_periodic_tick_callback: Callable[[], None] | None = None
    ci_periodic_tick_interval_sec: float = 20.0
    worktree_manager: Any | None = None
    workspace_manager: Any | None = None
    branch_manager: Any | None = None


@dataclass
class SliceResult:
    """Final result of running the promotion loop on one slice."""

    slice_id: str = ""
    status: Literal[
        "COMPLETE",
        "SKIPPED",
        "BLOCKED",
        "FAILED",
        "MAX_ITERATIONS",
        "STAGNATED",
        "WAITING",
    ] = "COMPLETE"
    iterations: int = 0
    remaining_gaps: int = 0
    demotion_tickets: list[DemotionTicket] = field(default_factory=list)
    blocked_questions: list[str] = field(default_factory=list)
    pending_signals: list[dict] = field(default_factory=list)
    wake_count: int = 0
    error: str = ""


# ------------------------------------------------------------------
# Loop step implementations (delegate to existing modules)
# ------------------------------------------------------------------


class CollectBaselineStep:
    """Collect manifest + diff baseline for the slice."""

    name = "COLLECT_BASELINE"

    @staticmethod
    def _build_l2_component_inventory(
        *,
        ctx: SliceContext,
        slice_root: Path,
        files: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Build L2 component inventory and pin registry summary for baseline evidence."""
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else slice_root
        manifest_components = _load_run_component_manifest(workspace, ctx.run_id)
        pin_snapshot = _load_pin_registry_snapshot(slice_root)
        file_set = {str(item.get("path", "")).strip() for item in files if item.get("path")}

        inventory: list[dict[str, Any]] = []
        for comp in manifest_components:
            component_id = str(comp.get("component_id", "")).strip()
            if not component_id:
                continue
            component_files = [
                str(path).strip()
                for path in comp.get("files", [])
                if isinstance(path, str) and str(path).strip()
            ]
            in_scope = False
            if component_files:
                in_scope = bool(set(component_files) & file_set)
            if not in_scope and ctx.slice_id:
                normalized_slice = ctx.slice_id.removeprefix("arch-").lower()
                in_scope = component_id.lower() in normalized_slice
            if not in_scope:
                continue
            inventory.append(
                {
                    "component_id": component_id,
                    "files": sorted(set(component_files)),
                    "pins_referenced": sorted(
                        {
                            str(pin).strip()
                            for pin in comp.get("pins_consumed", [])
                            if isinstance(pin, str) and str(pin).strip()
                        }
                    ),
                    "entrypoints": sorted(
                        {
                            str(ep).strip()
                            for ep in comp.get("owned_entrypoints", [])
                            if isinstance(ep, str) and str(ep).strip()
                        }
                    ),
                }
            )

        fallback_component = (
            ctx.slice_id.removeprefix("arch-") if ctx.slice_id.startswith("arch-") else ""
        )
        if not inventory and file_set:
            inventory.append(
                {
                    "component_id": fallback_component or ctx.slice_id or "slice",
                    "files": sorted(file_set),
                    "pins_referenced": [],
                    "entrypoints": [],
                }
            )

        pin_ids = []
        edge_targets = []
        for pin in pin_snapshot.get("pins", []):
            pin_id = str(pin.get("pin_func_id") or pin.get("pin_id") or pin.get("id") or "").strip()
            if pin_id:
                pin_ids.append(pin_id)
        for edge in pin_snapshot.get("edges", []):
            target = str(edge.get("arch_location") or edge.get("dst") or "").strip()
            if target:
                edge_targets.append(target)

        pin_registry_summary = {
            "path": pin_snapshot.get("path", ""),
            "exists": bool(pin_snapshot.get("exists", False)),
            "pin_count": len(pin_snapshot.get("pins", [])),
            "edge_count": len(pin_snapshot.get("edges", [])),
            "pin_ids": sorted(set(pin_ids))[:200],
            "edge_targets": sorted(set(edge_targets))[:200],
        }
        return inventory, pin_registry_summary

    @staticmethod
    def _snapshot_l3_quality_receipts(
        ctx: SliceContext,
        bundle: EvidenceBundle,
        *,
        evidence_root: Path,
    ) -> list[dict[str, Any]]:
        """Snapshot prior L3 quality receipts into the current iteration."""
        prior_receipts: list[dict[str, Any]] = []
        copied_from_iteration = bundle.iteration - 1 if bundle.iteration > 1 else 0
        if bundle.iteration > 1:
            previous_path = _quality_receipts_iteration_path(
                evidence_root,
                run_id=bundle.run_id,
                slice_id=bundle.slice_id,
                iteration=bundle.iteration - 1,
            )
            prior_receipts = _quality_receipts_from_payload(_read_json_file(previous_path))

        _write_iteration_json(
            bundle,
            evidence_root,
            _QUALITY_RECEIPTS_FILENAME,
            {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "run_id": ctx.run_id,
                "iteration": bundle.iteration,
                "copied_from_iteration": copied_from_iteration,
                "content_hash": bundle.diff.content_hash,
                "receipts": prior_receipts,
            },
        )
        if _QUALITY_RECEIPTS_FILENAME not in bundle.manifest.generated_files:
            bundle.manifest.generated_files.append(_QUALITY_RECEIPTS_FILENAME)
        return prior_receipts

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Collect file hashes and diff from previous iteration."""
        from spec_manager.orchestration.evidence import DiffRef, ManifestRef

        slice_root = Path(ctx.slice_root)
        if not slice_root.exists():
            return StepResult(status="FAIL", error=f"Slice root does not exist: {ctx.slice_root}")

        # Collect manifest: list all source files with content hashes.
        files: list[dict[str, Any]] = []
        for p in sorted(slice_root.rglob("*")):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                try:
                    raw = p.read_bytes()
                except OSError as exc:
                    logger.debug("Baseline skip unreadable file %s: %s", p, exc)
                    continue
                rel_path = _safe_rel(p, slice_root)
                files.append(
                    {
                        "path": rel_path,
                        "sha256": _hash_bytes(raw),
                        "size_bytes": len(raw),
                    }
                )

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        manifest_hash_input = "\n".join(
            f"{f['path']}:{f.get('sha256', '')}" for f in sorted(files, key=lambda x: x["path"])
        )
        manifest_hash = _hash_text(manifest_hash_input) if files else ""

        previous_manifest: dict[str, str] = {}
        previous_head_commit = ""
        if bundle.iteration > 1:
            prev_bundle_path = _bundle_json_path(
                evidence_root,
                bundle.run_id,
                bundle.slice_id,
                bundle.iteration - 1,
            )
            if prev_bundle_path.exists():
                try:
                    previous_bundle = EvidenceBundle.load(prev_bundle_path)
                    previous_manifest = {
                        item.get("path", ""): item.get("sha256", "")
                        for item in (previous_bundle.manifest.files or [])
                        if item.get("path")
                    }
                    previous_head_commit = previous_bundle.diff.head_commit or ""
                except Exception as exc:
                    logger.debug(
                        "Failed loading previous bundle baseline %s: %s", prev_bundle_path, exc
                    )

        changed_files: list[str] = []
        for item in files:
            path = item.get("path", "")
            sha = item.get("sha256", "")
            if previous_manifest.get(path) != sha:
                changed_files.append(path)
        if not previous_manifest:
            changed_files = [item.get("path", "") for item in files if item.get("path")]

        component_inventory: list[dict[str, Any]] = []
        pin_registry_summary: dict[str, Any] = {}
        if ctx.layer == "l2":
            component_inventory, pin_registry_summary = self._build_l2_component_inventory(
                ctx=ctx,
                slice_root=slice_root,
                files=files,
            )

        bundle.manifest = ManifestRef(
            path="manifest.json",
            files=files,
            component_inventory=component_inventory,
            pin_registry_summary=pin_registry_summary,
        )
        bundle.diff = DiffRef(
            path="diff.json",
            base_commit=previous_head_commit or bundle.diff.base_commit,
            head_commit=manifest_hash,
            changed_files=changed_files,
            content_hash=manifest_hash,
        )

        quality_receipts_snapshot: dict[str, Any] = {}
        if ctx.layer == "l3":
            snapshot_receipts = self._snapshot_l3_quality_receipts(
                ctx,
                bundle,
                evidence_root=evidence_root,
            )
            quality_receipts_snapshot = {
                "path": _QUALITY_RECEIPTS_FILENAME,
                "receipt_count": len(snapshot_receipts),
            }

        _write_iteration_json(
            bundle,
            evidence_root,
            "manifest.json",
            {
                "files": bundle.manifest.files,
                "component_inventory": bundle.manifest.component_inventory,
                "pin_registry_summary": bundle.manifest.pin_registry_summary,
                "slice_patterns": bundle.manifest.slice_patterns,
                "generated_files": bundle.manifest.generated_files,
                "quality_receipts_snapshot": quality_receipts_snapshot,
            },
        )
        _write_iteration_json(
            bundle,
            evidence_root,
            "diff.json",
            {
                "base_commit": bundle.diff.base_commit,
                "head_commit": bundle.diff.head_commit,
                "changed_files": bundle.diff.changed_files,
                "content_hash": bundle.diff.content_hash,
            },
        )
        return StepResult(status="OK")


class GapExplorationStep:
    """Find remaining gaps — layer-aware.

    - L1: P3 compliance (spec comments + stub functions)
    - L2: Architecture continuity gaps (unconsumed pins, missing components,
      missing event handlers, logic in arch files, manifest drift)
    - L3: Quality closure gaps (run reviewers → findings are gaps)
    """

    name = "GAP_EXPLORATION"

    def __init__(self, planner: Any = None, gap_queue: Any | None = None) -> None:
        self._planner = planner
        self._gap_queue = gap_queue

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to layer-specific gap exploration."""
        if ctx.layer == "l1":
            return self._explore_l1(ctx, bundle)
        if ctx.layer == "l2":
            return self._explore_l2(ctx, bundle)
        if ctx.layer == "l3":
            return self._explore_l3(ctx, bundle)
        return StepResult(status="OK")

    @staticmethod
    def _reuse_previous_gaps_if_fresh(
        ctx: SliceContext, bundle: EvidenceBundle
    ) -> list[dict[str, Any]] | None:
        """Reuse previous iteration gaps if file hash is unchanged."""
        if bundle.iteration <= 1:
            return None
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        prev_bundle_path = _bundle_json_path(
            evidence_root,
            bundle.run_id,
            bundle.slice_id,
            bundle.iteration - 1,
        )
        if not prev_bundle_path.exists():
            return None

        try:
            prev = EvidenceBundle.load(prev_bundle_path)
        except Exception as exc:
            logger.debug(
                "Could not load previous bundle for gap reuse %s: %s", prev_bundle_path, exc
            )
            return None

        if prev.diff.content_hash and prev.diff.content_hash == bundle.diff.content_hash:
            return [dict(g) for g in (prev.gaps.open_gaps or [])]
        return None

    @staticmethod
    def _normalize_gap(gap: dict[str, Any]) -> dict[str, Any]:
        """Normalize prior gap evidence to span/location schema."""
        return _normalize_gap_record(gap)

    @staticmethod
    def _invariant_family_for_gap(kind: str) -> str:
        """Map gap kind labels to canonical invariant families."""
        if kind == "comment_gap":
            return "executable_comment"
        if kind == "stub_gap":
            return "executable_stub"
        if kind == "ambiguity_gap":
            return "ambiguity"
        return kind or "missing_detail"

    @classmethod
    def _report_from_gap_records(cls, gaps: list[dict[str, Any]]) -> Any:
        """Project normalized gap records into executable-gap report evidence."""
        from spec_manager.compliance.detection.orchestrator import ExecutableGapReport
        from spec_manager.core.gap import GapEvidence

        evidence: list[GapEvidence] = []
        for gap in gaps:
            file_path = str(gap.get("file", "")).strip()
            description = str(gap.get("description", "")).strip() or "Gap detected"
            kind = str(gap.get("kind", "gap")).strip()
            details: dict[str, Any] = {
                "derived_artifact_target": file_path or "unknown",
            }
            if file_path:
                details["source"] = [file_path]
            evidence.append(
                GapEvidence(
                    invariant_family=cls._invariant_family_for_gap(kind),
                    description=description,
                    details=details,
                    location=file_path or None,
                    detector="promotion_loop.gap_exploration",
                )
            )
        return ExecutableGapReport(all_evidence=evidence)

    def _merge_gap_queue(self, report: Any, bundle: EvidenceBundle) -> None:
        """Merge L1 gap evidence into the shared queue and expose queue metrics."""
        if self._gap_queue is None:
            return

        from spec_manager.compliance.detection.orchestrator import integrate_with_gap_queue
        from spec_manager.core.gap import GapSynthesizer

        integrate_with_gap_queue(report, self._gap_queue, GapSynthesizer())
        metrics = self._gap_queue.get_coverage_metrics()
        bundle.gaps.stagnation = {
            "stagnation_count": self._gap_queue.stagnation_count,
            "is_stagnant": self._gap_queue.is_stagnant,
            "open_gaps": metrics.get("open_gaps", 0),
            "total_gaps": metrics.get("total_gaps", 0),
        }

    @staticmethod
    def _pattern_library_path(workspace: Path) -> Path:
        """Return the run-shared pattern library path."""
        return workspace / ".pdd_runs" / "pattern_library.json"

    @staticmethod
    def _record_strategy_candidates(
        pattern_lib: Any,
        *,
        dimension: str,
        findings: list[dict[str, Any]],
    ) -> int:
        """Convert findings into strategy candidates for incremental evolution."""
        from spec_manager.orchestration.pattern_library import StrategyCandidate

        recorded = 0
        for finding in findings:
            evidence = str(finding.get("evidence") or finding.get("description") or "").strip()
            if not evidence:
                continue
            signal = " ".join(evidence.split())[:180]
            suggested_fix = str(finding.get("suggested_fix", "")).strip()
            candidate = StrategyCandidate(
                signal_patterns=[signal],
                approved_remediation=suggested_fix,
                exceptions=[],
                occurrences=1,
                source_dimension=dimension,
            )
            pattern_lib.record_candidate(candidate)
            recorded += 1
        return recorded

    @staticmethod
    def _load_review_files_from_manifest(
        slice_root: Path,
        bundle: EvidenceBundle,
        *,
        target_stem: str = "",
    ) -> tuple[dict[str, str], int]:
        """Load review file content using baseline manifest entries, not ad-hoc scans."""
        manifest_paths: list[str] = []
        for item in bundle.manifest.files or []:
            rel_path = str(item.get("path", "")).strip()
            if not rel_path:
                continue
            rel = Path(rel_path)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if target_stem and rel.stem != target_stem:
                continue
            manifest_paths.append(rel_path)

        changed = {str(path) for path in (bundle.diff.changed_files or []) if isinstance(path, str)}
        if changed:
            prioritized = [p for p in manifest_paths if p in changed]
            fallback = [p for p in manifest_paths if p not in changed]
            ordered_paths = prioritized + fallback
        else:
            ordered_paths = manifest_paths

        loaded: dict[str, str] = {}
        for rel_path in ordered_paths:
            candidate = slice_root / rel_path
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                loaded[rel_path] = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        return loaded, len(ordered_paths)

    def _discover_l2_topology(self, ctx: SliceContext, bundle: EvidenceBundle) -> dict[str, Any]:
        """Resolve L2 topology via planner discovery (or local fallback)."""
        from types import SimpleNamespace

        if self._planner is not None:
            try:
                from spec_manager.planner.api import PlanningContext, PlanningRequest

                planning_ctx = PlanningContext(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    iteration=bundle.iteration,
                    layer="l2",
                    mode=ctx.mode,
                    workspace_root=ctx.workspace_root,
                    slice_root=ctx.slice_root,
                    metadata={
                        "changed_files": list(bundle.diff.changed_files or []),
                    },
                )
                result = self._planner.plan(
                    PlanningRequest(
                        capability="GAP",
                        context=planning_ctx,
                        inputs={},
                    )
                )
                outputs = getattr(result, "outputs", {})
                discovery = outputs.get("discovery", {}) if isinstance(outputs, dict) else {}
                if isinstance(discovery, dict):
                    return discovery
            except Exception as exc:
                logger.debug("Planner L2 discovery failed: %s", exc, exc_info=True)

        try:
            from spec_manager.planner.layers.l2 import L2Planner

            fallback_ctx = SimpleNamespace(
                workspace_root=ctx.workspace_root,
                slice_root=ctx.slice_root,
                metadata={"changed_files": list(bundle.diff.changed_files or [])},
            )
            return L2Planner().discover(fallback_ctx)
        except Exception as exc:
            logger.warning("L2 topology discovery fallback failed: %s", exc, exc_info=True)
            return {
                "nodes": [],
                "edges": [],
                "arch_files": [],
                "discovery_status": "incomplete",
                "discovery_issues": [f"L2 topology discovery failed: {exc}"],
            }

    @staticmethod
    def _load_arch_artifacts(workspace: Path, arch_files: list[str]) -> list[dict[str, str]]:
        """Load architecture manifest/wiring files for reviewer context."""
        artifacts: list[dict[str, str]] = []
        for rel_path in arch_files[:12]:
            candidate = workspace / rel_path
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                artifacts.append(
                    {
                        "path": rel_path,
                        "content": candidate.read_text(encoding="utf-8"),
                    }
                )
            except OSError as exc:
                logger.debug("Failed reading architecture file %s: %s", candidate, exc)
        return artifacts

    @staticmethod
    def _l2_gap(
        *,
        kind: str,
        component_id: str,
        file_path: str,
        anchor: str,
        description: str,
        expected: str,
        severity: str = "MAJOR",
        required_change_type: str = "wiring_only",
    ) -> dict[str, Any]:
        """Build a normalized L2 architecture continuity gap record."""
        return _normalize_gap_record(
            {
                "kind": kind,
                "component_id": component_id,
                "file": file_path,
                "anchor": anchor,
                "description": description,
                "expected": expected,
                "severity": severity,
                "required_change_type": required_change_type,
                "span": {},
                "location": {"file": file_path},
            }
        )

    @staticmethod
    def _topology_node_id(node: dict[str, Any]) -> str:
        return str(node.get("id") or node.get("name") or node.get("symbol") or "").strip()

    @staticmethod
    def _topology_edge_endpoints(edge: dict[str, Any]) -> tuple[str, str]:
        source = str(edge.get("source") or edge.get("src") or "").strip()
        target = str(edge.get("target") or edge.get("dst") or "").strip()
        return source, target

    @staticmethod
    def _load_previous_promoted_evidence(
        ctx: SliceContext,
        bundle: EvidenceBundle,
        *,
        slice_root: Path,
    ) -> dict[str, Any]:
        """Load promoted pin/edge evidence from the previous iteration or pin registry."""
        pins: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        if bundle.iteration > 1:
            evidence_root = _evidence_base_path(
                slice_root=ctx.slice_root,
                workspace_root=ctx.workspace_root,
            )
            prev_bundle_path = _bundle_json_path(
                evidence_root,
                bundle.run_id,
                bundle.slice_id,
                bundle.iteration - 1,
            )
            if prev_bundle_path.exists():
                try:
                    prev = EvidenceBundle.load(prev_bundle_path)
                    prev_dir = prev.iter_dir(evidence_root)
                    if prev.pins_snapshot.path:
                        payload = _read_json_file(prev_dir / prev.pins_snapshot.path)
                        if isinstance(payload, dict):
                            pins = [
                                item for item in payload.get("pins", []) if isinstance(item, dict)
                            ]
                    if prev.graph_snapshot.path:
                        payload = _read_json_file(prev_dir / prev.graph_snapshot.path)
                        if isinstance(payload, dict):
                            edges = [
                                item for item in payload.get("edges", []) if isinstance(item, dict)
                            ]
                except Exception as exc:
                    logger.debug("Failed loading previous promoted evidence: %s", exc)

        pin_registry_payload = _load_pin_registry_snapshot(slice_root)
        if not pins:
            pins = [item for item in pin_registry_payload.get("pins", []) if isinstance(item, dict)]
        if not edges:
            edges = [
                item for item in pin_registry_payload.get("edges", []) if isinstance(item, dict)
            ]

        return {
            "pins": pins,
            "edges": edges,
            "pin_registry": pin_registry_payload,
        }

    @classmethod
    def _entrypoint_present(
        cls,
        *,
        entrypoint: str,
        topology_nodes: list[dict[str, Any]],
        topology_edges: list[dict[str, Any]],
        arch_artifacts: list[dict[str, str]],
    ) -> bool:
        """Heuristic check for whether an expected entrypoint appears in realized topology."""
        needle = entrypoint.strip().lower()
        if not needle:
            return True

        for node in topology_nodes:
            node_id = cls._topology_node_id(node).lower()
            if needle == node_id or needle in node_id:
                return True

        for edge in topology_edges:
            src, dst = cls._topology_edge_endpoints(edge)
            if needle in src.lower() or needle in dst.lower():
                return True

        for artifact in arch_artifacts:
            content = str(artifact.get("content", "")).lower()
            if needle in content:
                return True

        return False

    def _explore_l1(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L1: detect executable gaps for the slice and update queue view."""
        from spec_manager.orchestration.evidence import GapReportRef

        reused = self._reuse_previous_gaps_if_fresh(ctx, bundle)
        if reused is not None:
            normalized = [self._normalize_gap(g) for g in reused]
            bundle.gaps = GapReportRef(
                path="gaps.json",
                open_gaps=normalized,
            )
            self._merge_gap_queue(self._report_from_gap_records(normalized), bundle)
            return StepResult(status="OK")

        if bool(ctx.config.get(_DISABLE_L1_GAP_SCAN_KEY, False)):
            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=[])
            self._merge_gap_queue(self._report_from_gap_records([]), bundle)
            return StepResult(status="OK")

        slice_root = Path(ctx.slice_root)
        py_files = self._l1_gap_scan_targets(slice_root=slice_root, bundle=bundle)
        if not py_files:
            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=[])
            self._merge_gap_queue(self._report_from_gap_records([]), bundle)
            return StepResult(status="OK")

        try:
            from spec_manager.compliance.detection.orchestrator import (
                ScanConfig,
                scan_executable_gaps,
            )

            report = scan_executable_gaps(
                filepaths=py_files,
                project_root=slice_root,
                config=ScanConfig(enable_comments=True, enable_stubs=True),
            )

            gaps: list[dict[str, Any]] = []
            for ev in report.all_evidence:
                span = _location_span(
                    start_line=getattr(ev, "line_start", None) or getattr(ev, "start_line", None),
                    end_line=getattr(ev, "line_end", None) or getattr(ev, "end_line", None),
                    start_col=getattr(ev, "col_start", None) or getattr(ev, "start_col", None),
                    end_col=getattr(ev, "col_end", None) or getattr(ev, "end_col", None),
                )
                location_file = getattr(ev, "location", "") or ""
                gaps.append(
                    {
                        "file": location_file,
                        "description": getattr(ev, "description", ""),
                        "kind": getattr(ev, "invariant_family", "gap"),
                        "span": span,
                        "location": {"file": location_file, **span},
                    }
                )

            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=gaps)
            self._merge_gap_queue(report, bundle)
        except Exception as exc:
            logger.warning("L1 gap exploration failed: %s", exc, exc_info=True)
            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=[])
            return StepResult(status="RETRY", error=f"L1 gap exploration failed: {exc}")

        return StepResult(status="OK")

    @staticmethod
    def _l1_gap_scan_targets(*, slice_root: Path, bundle: EvidenceBundle) -> list[Path]:
        """Resolve gap scan targets from bundle evidence before falling back to deep scans."""
        targets: list[Path] = []
        seen: set[Path] = set()

        source_entries = bundle.source_index.entries or []
        for entry in source_entries:
            if not isinstance(entry, dict):
                continue
            rel_path = str(entry.get("path", "")).strip()
            if not rel_path or not rel_path.endswith(".py"):
                continue
            candidate = slice_root / rel_path
            if candidate in seen or not candidate.exists() or not candidate.is_file():
                continue
            seen.add(candidate)
            targets.append(candidate)

        if targets:
            return targets

        for item in bundle.manifest.files or []:
            if not isinstance(item, dict):
                continue
            rel_path = str(item.get("path", "")).strip()
            if not rel_path or not rel_path.endswith(".py"):
                continue
            candidate = slice_root / rel_path
            if candidate in seen or not candidate.exists() or not candidate.is_file():
                continue
            seen.add(candidate)
            targets.append(candidate)

        if targets:
            return targets

        from spec_manager.core.language import source_rglob

        return source_rglob(slice_root)

    def _explore_l2(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L2: architecture continuity gaps using authority artifacts + topology deltas."""
        from spec_manager.orchestration.evidence import GapReportRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None

        if not slice_root or not slice_root.exists():
            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=[])
            return StepResult(status="OK")

        reused = self._reuse_previous_gaps_if_fresh(ctx, bundle)
        if reused is not None:
            bundle.gaps = GapReportRef(
                path="gaps.json", open_gaps=[self._normalize_gap(g) for g in reused]
            )
            return StepResult(status="OK")

        component_manifest = _load_run_component_manifest(workspace, bundle.run_id)
        promoted = self._load_previous_promoted_evidence(ctx, bundle, slice_root=slice_root)
        promoted_pins = [item for item in promoted.get("pins", []) if isinstance(item, dict)]
        promoted_edges = [item for item in promoted.get("edges", []) if isinstance(item, dict)]

        discovery = self._discover_l2_topology(ctx, bundle)
        arch_files = [
            str(path)
            for path in discovery.get("arch_files", [])
            if isinstance(path, str) and path.strip()
        ]
        topology_nodes = [n for n in discovery.get("nodes", []) if isinstance(n, dict)]
        topology_edges = [e for e in discovery.get("edges", []) if isinstance(e, dict)]
        discovery_issues = [
            issue for issue in discovery.get("discovery_issues", []) if isinstance(issue, str)
        ]
        arch_artifacts = self._load_arch_artifacts(workspace, arch_files)

        gaps: list[dict[str, Any]] = []
        if not component_manifest:
            gaps.append(
                self._l2_gap(
                    kind="l2_component_manifest_missing",
                    component_id="",
                    file_path=str(_run_component_manifest_path(workspace, bundle.run_id)),
                    anchor="component_manifest",
                    description="Component manifest missing for L2 continuity checks.",
                    expected=(
                        "Run-scoped component manifest with declared components "
                        "and expected wiring."
                    ),
                    severity="BLOCKER",
                )
            )
        if not promoted_pins and not promoted_edges:
            gaps.append(
                self._l2_gap(
                    kind="l2_promoted_evidence_missing",
                    component_id="",
                    file_path=str(slice_root / ".spec" / "pin_registry.json"),
                    anchor="promoted_pin_edge_evidence",
                    description="No promoted pins/edges were available in scope for this slice.",
                    expected=(
                        "Promoted pins and edges should be loaded before L2 continuity analysis."
                    ),
                    severity="BLOCKER",
                )
            )

        for issue in discovery_issues:
            gaps.append(
                self._l2_gap(
                    kind="l2_discovery_issue",
                    component_id="",
                    file_path="",
                    anchor="topology_discovery",
                    description=issue,
                    expected=(
                        "Topology discovery should produce architecture files "
                        "plus non-empty nodes/edges."
                    ),
                    severity="BLOCKER",
                )
            )

        topology_node_ids: set[str] = set()
        topology_component_ids: set[str] = set()
        topology_pin_refs: set[str] = set()
        for node in topology_nodes:
            node_id = self._topology_node_id(node)
            if node_id:
                topology_node_ids.add(node_id)
            node_type = str(node.get("type") or node.get("kind") or "").strip().lower()
            if node_type == "component" and node_id:
                topology_component_ids.add(node_id)
            if node_type == "pin" and node_id:
                topology_pin_refs.add(node_id)

        for edge in topology_edges:
            src, dst = self._topology_edge_endpoints(edge)
            signal = str(edge.get("signal_type") or edge.get("type") or "").upper()
            if src:
                topology_pin_refs.add(src)
            if dst:
                topology_pin_refs.add(dst)
            if signal == "EVENT" and (not src or not dst):
                gaps.append(
                    self._l2_gap(
                        kind="l2_missing_event_handler",
                        component_id="",
                        file_path=str(edge.get("arch_file_path") or edge.get("file") or ""),
                        anchor=str(edge.get("edge_id") or "event_edge"),
                        description="Event wiring edge is missing source or destination endpoint.",
                        expected="Event edges should connect a producer and a handler endpoint.",
                    )
                )

        manifest_component_ids: set[str] = set()
        manifest_files: set[str] = set()
        component_for_pin: dict[str, str] = {}
        for component in component_manifest:
            component_id = str(component.get("component_id", "")).strip()
            if not component_id:
                continue
            manifest_component_ids.add(component_id)

            expected_files = [
                str(path).strip()
                for path in component.get("files", [])
                if isinstance(path, str) and str(path).strip()
            ]
            manifest_files.update(expected_files)
            for rel_path in expected_files:
                if not (slice_root / rel_path).exists():
                    gaps.append(
                        self._l2_gap(
                            kind="l2_missing_component_file",
                            component_id=component_id,
                            file_path=rel_path,
                            anchor=f"component_manifest:{component_id}",
                            description=f"Manifest-declared component file is missing: {rel_path}",
                            expected=(
                                "All component manifest files should exist in the slice baseline."
                            ),
                            severity="BLOCKER",
                        )
                    )

            if (topology_nodes or topology_edges) and (
                component_id not in topology_component_ids and component_id not in topology_node_ids
            ):
                gaps.append(
                    self._l2_gap(
                        kind="l2_missing_component_node",
                        component_id=component_id,
                        file_path=expected_files[0] if expected_files else "",
                        anchor=f"component:{component_id}",
                        description=("Manifest component is not represented in realized topology."),
                        expected=(
                            "Every manifest component should appear in topology nodes/edges."
                        ),
                        severity="MAJOR",
                    )
                )

            for pin_ref in component.get("pins_consumed", []):
                if not isinstance(pin_ref, str):
                    continue
                pin_id = pin_ref.strip()
                if pin_id:
                    component_for_pin.setdefault(pin_id, component_id)

            for entrypoint in component.get("owned_entrypoints", []):
                if not isinstance(entrypoint, str):
                    continue
                entrypoint_id = entrypoint.strip()
                if not entrypoint_id:
                    continue
                if not self._entrypoint_present(
                    entrypoint=entrypoint_id,
                    topology_nodes=topology_nodes,
                    topology_edges=topology_edges,
                    arch_artifacts=arch_artifacts,
                ):
                    gaps.append(
                        self._l2_gap(
                            kind="l2_missing_handler_registration",
                            component_id=component_id,
                            file_path=expected_files[0] if expected_files else "",
                            anchor=entrypoint_id,
                            description=(
                                "Expected entrypoint/handler is missing from realized architecture."
                            ),
                            expected=(
                                "Manifest-owned entrypoints should be present in "
                                "topology and wiring."
                            ),
                        )
                    )

        promoted_pin_ids: set[str] = set()
        for pin in promoted_pins:
            pin_id = str(pin.get("pin_func_id") or pin.get("pin_id") or pin.get("id") or "").strip()
            if pin_id:
                promoted_pin_ids.add(pin_id)
        for edge in promoted_edges:
            pin_id = str(edge.get("pin_func_id") or edge.get("src") or "").strip()
            if pin_id:
                promoted_pin_ids.add(pin_id)
            arch_target = str(edge.get("arch_location") or edge.get("dst") or "").strip()
            if arch_target:
                topology_pin_refs.add(arch_target)

        consumed_pin_ids = {
            pin_id
            for pin_id in promoted_pin_ids
            if any(pin_id == ref or pin_id in ref for ref in topology_pin_refs)
        }
        for pin_id in sorted(promoted_pin_ids - consumed_pin_ids):
            component_id = component_for_pin.get(pin_id, "")
            gaps.append(
                self._l2_gap(
                    kind="l2_unconsumed_pin",
                    component_id=component_id,
                    file_path="",
                    anchor=pin_id,
                    description=f"Promoted pin is not consumed by realized architecture: {pin_id}",
                    expected=(
                        "Every promoted pin should appear in topology wiring or "
                        "declared component consumption."
                    ),
                    severity="MAJOR",
                )
            )

        if manifest_component_ids:
            unexpected_components = sorted(
                cid for cid in topology_component_ids if cid and cid not in manifest_component_ids
            )
            for component_id in unexpected_components:
                gaps.append(
                    self._l2_gap(
                        kind="l2_manifest_drift_component",
                        component_id=component_id,
                        file_path="",
                        anchor=f"topology_component:{component_id}",
                        description="Topology contains a component not declared in the manifest.",
                        expected=(
                            "Realized topology components should match component "
                            "manifest declarations."
                        ),
                        severity="MAJOR",
                    )
                )

        for artifact in arch_artifacts:
            rel_path = str(artifact.get("path", "")).strip()
            if rel_path and manifest_files and rel_path not in manifest_files:
                gaps.append(
                    self._l2_gap(
                        kind="l2_manifest_drift_file",
                        component_id="",
                        file_path=rel_path,
                        anchor="manifest_drift:file",
                        description=(
                            "Architecture file exists outside declared component "
                            "manifest ownership."
                        ),
                        expected=(
                            "Architecture wiring files should be traceable to "
                            "declared manifest components."
                        ),
                        severity="MINOR",
                    )
                )

            content = str(artifact.get("content", ""))
            lowered = content.lower()
            logic_tokens = (" while ", " for ", " if ", " try:", " except ", " return ")
            if any(token in f" {lowered} " for token in logic_tokens):
                gaps.append(
                    self._l2_gap(
                        kind="l2_logic_like_architecture_code",
                        component_id="",
                        file_path=rel_path,
                        anchor="architecture_pre_gate_warning",
                        description=(
                            "Architecture artifact appears to contain logic-like flow control; "
                            "review for potential boundary violation."
                        ),
                        expected=(
                            "L2 architectural files should focus on wiring and "
                            "orchestration boundaries."
                        ),
                        severity="MINOR",
                    )
                )

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for gap in gaps:
            fingerprint = json.dumps(
                {
                    "kind": gap.get("kind", ""),
                    "component_id": gap.get("component_id", ""),
                    "file": gap.get("file", ""),
                    "anchor": gap.get("anchor", ""),
                    "description": gap.get("description", ""),
                    "expected": gap.get("expected", ""),
                },
                sort_keys=True,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            deduped.append(gap)

        bundle.gaps = GapReportRef(path="gaps.json", open_gaps=deduped)
        return StepResult(status="OK")

    def _explore_l3(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L3: quality closure gaps — run reviewers, findings are gaps.

        Each reviewer finding that hasn't been resolved is an open gap.
        """
        import json

        from spec_manager.orchestration.evidence import GapReportRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )

        if not slice_root or not slice_root.exists():
            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=[])
            return StepResult(status="OK")

        staged_receipts = _load_iteration_quality_receipts(
            evidence_root=evidence_root,
            bundle=bundle,
        )
        latest_receipts = _latest_quality_receipts_by_key(staged_receipts)

        # Gather code from baseline manifest entries so review input is explicit
        # and upstream-owned rather than scanner-owned at review time.
        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""
        code_files, candidate_count = self._load_review_files_from_manifest(
            slice_root,
            bundle,
            target_stem=target_stem,
        )

        if not code_files:
            open_gaps: list[dict[str, Any]] = []
            if candidate_count > 0:
                open_gaps.append(
                    {
                        "kind": "quality_review_input_unavailable",
                        "file": "",
                        "description": (
                            "L3 review input files were declared in the manifest but could not be "
                            "loaded for reviewer execution."
                        ),
                        "severity": "BLOCKER",
                        "category": "review_execution",
                        "required_change_type": "refactor_only",
                        "span": {},
                        "location": {"file": ""},
                    }
                )
            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=open_gaps)
            _write_iteration_quality_receipts(
                ctx=ctx,
                bundle=bundle,
                evidence_root=evidence_root,
                stage="GAP_EXPLORATION",
                receipts=list(latest_receipts.values()),
            )
            return StepResult(status="OK")

        # Pattern library for review context
        from spec_manager.orchestration.pattern_library import PatternLibrary

        pattern_lib = PatternLibrary(library_path=self._pattern_library_path(workspace))
        strategy_candidates_recorded = 0
        configured_reviewers = _configured_l3_review_pack(
            ctx.config if isinstance(ctx.config, dict) else None,
            include_diff_impact=False,
        )

        all_gaps: list[dict[str, Any]] = []

        for file_path, code_content in code_files.items():
            file_hash = _hash_text(code_content)
            for reviewer in configured_reviewers:
                receipt_key = "::".join((reviewer.reviewer_id, file_path, file_hash))
                prior_receipt = latest_receipts.get(receipt_key)
                if (
                    prior_receipt
                    and _normalize_receipt_status(prior_receipt.get("status")) == "PASS"
                ):
                    latest_receipts[receipt_key] = _normalize_quality_receipt(
                        {
                            **prior_receipt,
                            "status": "PASS",
                            "stage": "GAP_EXPLORATION",
                            "validated_at": _now_iso(),
                        }
                    )
                    continue

                pattern_section = pattern_lib.get_review_prompt_section(reviewer.dimension)
                reviewer_prompt = (
                    "## TASK\n"
                    "Review the following code for quality issues.\n"
                    "Execution stage: GAP_EXPLORATION (pre-implementation).\n"
                    f"Objective: {reviewer.objective}\n"
                    "For each finding include: severity (BLOCKER/MAJOR/MINOR),\n"
                    "category (style/maintainability/logic/architecture/drift/diff-impact),\n"
                    "required_change_type (refactor_only/wiring_only/behavior_change),\n"
                    "and description.\n"
                    'Return JSON: {"findings": [...]}\n\n'
                    f"{pattern_section}\n\n"
                    f"File: {file_path}\n\n"
                    f"```\n{code_content[:4000]}\n```\n"
                )

                try:
                    from spec_manager.core.agent_utils import run_agent
                    from spec_manager.core.json_extraction import _extract_json_payload
                    from spec_manager.refinement.formats import _strip_code_fences

                    output = run_agent(
                        agent_name=reviewer.agent_name,
                        prompt=reviewer_prompt,
                        workspace=workspace,
                    )
                    cleaned = _strip_code_fences(output)
                    data = json.loads(_extract_json_payload(cleaned))
                    findings = [f for f in data.get("findings", []) if isinstance(f, dict)]
                    strategy_candidates_recorded += self._record_strategy_candidates(
                        pattern_lib,
                        dimension=reviewer.dimension,
                        findings=findings,
                    )

                    for finding in findings:
                        location = finding.get("location", {}) or {}
                        span = _location_span(
                            start_line=location.get("start_line"),
                            end_line=location.get("end_line"),
                            start_col=location.get("start_col"),
                            end_col=location.get("end_col"),
                        )
                        all_gaps.append(
                            {
                                "kind": "quality_finding",
                                "file": file_path,
                                "reviewer": reviewer.reviewer_id,
                                "agent_name": reviewer.agent_name,
                                "dimension": reviewer.dimension,
                                "description": finding.get("description", ""),
                                "severity": finding.get("severity", "MINOR"),
                                "category": finding.get("category", reviewer.default_category),
                                "required_change_type": finding.get(
                                    "required_change_type",
                                    reviewer.default_required_change_type,
                                ),
                                "span": span,
                                "location": {"file": file_path, **span},
                            }
                        )
                    latest_receipts[receipt_key] = _normalize_quality_receipt(
                        {
                            "reviewer_id": reviewer.reviewer_id,
                            "agent_name": reviewer.agent_name,
                            "dimension": reviewer.dimension,
                            "file": file_path,
                            "file_hash": file_hash,
                            "status": "FAIL" if findings else "PASS",
                            "finding_count": len(findings),
                            "findings": findings,
                            "stage": "GAP_EXPLORATION",
                            "recorded_at": _now_iso(),
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        "L3 reviewer %s failed for %s: %s",
                        reviewer.reviewer_id,
                        file_path,
                        exc,
                    )
                    all_gaps.append(
                        {
                            "kind": "quality_finding",
                            "file": file_path,
                            "reviewer": reviewer.reviewer_id,
                            "agent_name": reviewer.agent_name,
                            "dimension": reviewer.dimension,
                            "description": (
                                f"Reviewer execution failed for {reviewer.reviewer_id}: {exc}"
                            ),
                            "severity": "BLOCKER",
                            "category": "review_execution",
                            "required_change_type": "refactor_only",
                            "span": {},
                            "location": {"file": file_path},
                        }
                    )
                    latest_receipts[receipt_key] = _normalize_quality_receipt(
                        {
                            "reviewer_id": reviewer.reviewer_id,
                            "agent_name": reviewer.agent_name,
                            "dimension": reviewer.dimension,
                            "file": file_path,
                            "file_hash": file_hash,
                            "status": "FAIL",
                            "finding_count": 1,
                            "findings": [
                                {
                                    "description": (
                                        f"Reviewer execution failed for "
                                        f"{reviewer.reviewer_id}: {exc}"
                                    ),
                                    "severity": "BLOCKER",
                                    "category": "review_execution",
                                    "required_change_type": "refactor_only",
                                }
                            ],
                            "stage": "GAP_EXPLORATION",
                            "recorded_at": _now_iso(),
                        }
                    )

        if strategy_candidates_recorded:
            try:
                pattern_lib.save()
            except Exception as exc:
                logger.warning("Failed to persist strategy candidates: %s", exc, exc_info=True)

        bundle.gaps = GapReportRef(path="gaps.json", open_gaps=all_gaps)
        _write_iteration_quality_receipts(
            ctx=ctx,
            bundle=bundle,
            evidence_root=evidence_root,
            stage="GAP_EXPLORATION",
            receipts=list(latest_receipts.values()),
        )
        return StepResult(status="OK")


class PlanStep:
    """Generate implementation plan from gaps — layer-aware.

    - L1: Convert spec gaps into function implementation intentions (P8)
    - L2: Convert architecture gaps into a wiring plan (which component
      to adjust, how to connect pins, handlers/routes to add)
    - L3: Convert quality findings into a refactor plan (group by
      function/span, sequence smallest safe refactors first, define
      "no behavior change" acceptance criteria)

    After generating intentions, checks decision requirements against
    the constraints store.  Uncovered decisions become under-spec events
    that block the slice before implementation begins.

    When a *planner* is provided, routes plan generation through the
    planner module instead of the static _plan_l2/_plan_l3
    methods.  The planner provides richer context-aware planning
    including integration analysis and constraint checking.
    """

    name = "PLAN"

    def __init__(self, planner: Any = None) -> None:
        self._planner = planner

    @staticmethod
    def _focus_targets(ctx: SliceContext) -> dict[str, list[str]]:
        """Return normalized focus targets for the active slice."""
        if not isinstance(ctx.config, dict):
            return {}
        return _normalize_focus_targets(ctx.config.get("focus_targets", {}))

    @staticmethod
    def _focus_score(intention: dict[str, Any], focus_targets: dict[str, list[str]]) -> int:
        """Score an intention by how directly it targets focused failures."""
        if not focus_targets:
            return 0
        score = 0
        focus_files = {path.replace("\\", "/") for path in focus_targets.get("failing_files", [])}
        focus_symbols = {
            symbol.lower().strip() for symbol in focus_targets.get("location_symbols", []) if symbol
        }

        target_file = str(intention.get("target_file", "")).strip()
        if target_file and _path_matches_focus(target_file, focus_files):
            score += 2

        target_files = intention.get("target_files", [])
        if isinstance(target_files, list) and any(
            _path_matches_focus(str(path), focus_files) for path in target_files
        ):
            score += 2

        target_function = str(intention.get("target_function", "")).strip().lower()
        if target_function and target_function in focus_symbols:
            score += 1
        return score

    @classmethod
    def _apply_focus_targets(
        cls,
        intentions: list[dict[str, Any]],
        focus_targets: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """Annotate/reorder intentions using transition focus targets."""
        if not intentions or not focus_targets:
            return intentions
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for idx, intention in enumerate(intentions):
            enriched = dict(intention)
            enriched["focus_targets"] = focus_targets
            scored.append((cls._focus_score(enriched, focus_targets), idx, enriched))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [row for _, _, row in scored]

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Generate layer-appropriate implementation plan from gaps."""
        from spec_manager.orchestration.evidence import PlanRef

        if not bundle.gaps.open_gaps:
            bundle.plan = PlanRef(path="plan.json", intentions=[])
            return StepResult(status="OK")

        # L1: generate function-oriented intentions from current open gaps.
        if ctx.layer == "l1":
            intentions = self._plan_l1(bundle.gaps.open_gaps)
        # Route through planner if available (L2/L3 only)
        elif self._planner is not None:
            intentions = self._plan_via_planner(ctx, bundle)
        elif ctx.layer == "l2":
            intentions = self._plan_l2(bundle.gaps.open_gaps)
        elif ctx.layer == "l3":
            intentions = self._plan_l3(bundle.gaps.open_gaps)
        else:
            intentions = []

        focus_targets = self._focus_targets(ctx)
        intentions = self._apply_focus_targets(intentions, focus_targets)
        bundle.plan = PlanRef(path="plan.json", intentions=intentions)

        # Run planning gate: check decision requirements against constraints
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else None
        if workspace:
            try:
                from spec_manager.orchestration.under_spec.planning_gate import (
                    run_planning_gate,
                )
                from spec_manager.planner.constraints.store import (
                    ConstraintsStore,
                )

                store = ConstraintsStore(workspace)
                gate_result = run_planning_gate(
                    constraints_store=store,
                    slice_id=ctx.slice_id,
                    intentions=intentions,
                )

                if not gate_result.all_covered:
                    existing = bundle.implementation.under_spec_events or []
                    bundle.implementation.under_spec_events = (
                        existing + gate_result.under_spec_events
                    )
                    return StepResult(status="BLOCKED")
            except Exception as exc:
                logger.debug("Planning gate skipped: %s", exc)

        return StepResult(status="OK")

    @staticmethod
    def _plan_l1(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """L1: convert executable gaps into concrete implementation intentions."""
        intentions: list[dict[str, Any]] = []
        for idx, gap in enumerate(gaps, start=1):
            file_path = str(gap.get("file", "")).strip()
            kind = str(gap.get("kind", "gap")).strip() or "gap"
            description = str(gap.get("description", "")).strip()
            location = gap.get("location", {}) or {}
            span = gap.get("span", {}) or {}
            target_function = (
                str(gap.get("function", "")).strip() or str(location.get("symbol", "")).strip()
            )
            target_id = file_path or target_function or f"gap-{idx}"
            approach_parts = [f"Resolve {kind}"]
            if target_function:
                approach_parts.append(f"in {target_function}")
            if file_path:
                approach_parts.append(f"at {file_path}")
            if description:
                approach_parts.append(f"by implementing: {description}")
            intentions.append(
                {
                    "intention_id": f"l1-intention-{idx}",
                    "gap_id": target_id,
                    "target_file": file_path,
                    "target_function": target_function,
                    "approach": " ".join(approach_parts),
                    "acceptance_criteria": "Executable gap no longer appears in GAP_EXPLORATION",
                    "layer_constraint": "implementation_only",
                    "required_change_type": gap.get("required_change_type", "behavior_change"),
                    "source_gap": {
                        "kind": kind,
                        "description": description,
                        "span": span,
                    },
                }
            )
        return intentions

    def _plan_via_planner(self, ctx: SliceContext, bundle: EvidenceBundle) -> list[dict[str, Any]]:
        """Route plan generation through the planner module."""
        from spec_manager.planner.api import PlanningContext

        planning_ctx = PlanningContext(
            run_id=ctx.run_id,
            slice_id=ctx.slice_id,
            layer=ctx.layer,
            mode=ctx.mode,
            workspace_root=ctx.workspace_root,
            slice_root=ctx.slice_root,
            bundle_ref=bundle,
            metadata={"focus_targets": self._focus_targets(ctx)},
        )
        return self._planner.plan_from_gaps(planning_ctx, bundle.gaps.open_gaps)

    @staticmethod
    def _plan_l2(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """L2: each gap becomes a wiring/assembly intention."""
        intentions = []
        for gap in gaps:
            component_id = gap.get("component_id", "")
            target_files = gap.get("target_files", [])
            if not isinstance(target_files, list):
                target_files = []
            if not target_files and gap.get("file"):
                target_files = [str(gap.get("file", ""))]
            intentions.append(
                {
                    "gap_id": gap.get("file", component_id or "unknown"),
                    "component_id": component_id,
                    "target_files": [str(path) for path in target_files if str(path).strip()],
                    "approach": f"Wire: {gap.get('description', '')}",
                    "acceptance_criteria": "Component assembled, pins connected, no inlined logic",
                    "layer_constraint": "wiring_only",
                }
            )
        return intentions

    @staticmethod
    def _plan_l3(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """L3: group findings by function/span and sequence smallest safe refactors first."""
        severity_order = {"MINOR": 0, "MAJOR": 1, "BLOCKER": 2}
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        for raw_gap in gaps:
            if not isinstance(raw_gap, dict):
                continue
            gap = _normalize_gap_record(raw_gap)
            file_path = str(gap.get("file", "")).strip() or "unknown"
            location = gap.get("location", {}) or {}
            span = gap.get("span", {}) or {}
            symbol = str(gap.get("function") or location.get("symbol") or "").strip()
            start_line = span.get("start_line") if isinstance(span.get("start_line"), int) else 0
            end_line = span.get("end_line") if isinstance(span.get("end_line"), int) else start_line

            if symbol:
                scope_key = f"function:{symbol}"
            elif start_line > 0:
                scope_key = f"span:{start_line}-{end_line or start_line}"
            else:
                scope_key = "file_scope"

            grouped[(file_path, scope_key)].append(gap)

        ordered_groups = sorted(
            grouped.items(),
            key=lambda item: (
                min(
                    severity_order.get(str(g.get("severity", "MINOR")).upper(), 1) for g in item[1]
                ),
                min(
                    (
                        (
                            int((g.get("span", {}) or {}).get("end_line", 0))
                            - int((g.get("span", {}) or {}).get("start_line", 0))
                            + 1
                        )
                        for g in item[1]
                        if isinstance((g.get("span", {}) or {}).get("start_line"), int)
                    ),
                    default=10_000,
                ),
                item[0][0],
                item[0][1],
            ),
        )

        intentions: list[dict[str, Any]] = []
        for idx, ((file_path, scope_key), scope_gaps) in enumerate(ordered_groups, start=1):
            ordered_scope_gaps = sorted(
                scope_gaps,
                key=lambda g: severity_order.get(str(g.get("severity", "MINOR")).upper(), 1),
            )
            first = ordered_scope_gaps[0]
            span = first.get("span", {}) or {}
            target_span = (
                {
                    "start_line": span.get("start_line"),
                    "end_line": span.get("end_line"),
                    "start_col": span.get("start_col"),
                    "end_col": span.get("end_col"),
                }
                if span
                else {}
            )
            target_function = ""
            if scope_key.startswith("function:"):
                target_function = scope_key.split(":", 1)[1]

            descriptions = [
                str(g.get("description") or "").strip()
                for g in ordered_scope_gaps
                if str(g.get("description") or "").strip()
            ]
            summary = "; ".join(descriptions[:4]) or "targeted clean-code refactor"
            scope_label = target_function or scope_key.replace(":", " ")
            acceptance_scope = f"{file_path} ({scope_label})"
            intentions.append(
                {
                    "intention_id": f"l3-intention-{idx}",
                    "gap_id": f"{file_path}:{scope_key}",
                    "target_file": file_path,
                    "target_function": target_function,
                    "target_span": target_span,
                    "approach": (
                        f"Apply smallest-safe refactors for {len(scope_gaps)} finding(s): {summary}"
                    ),
                    "acceptance_criteria": (
                        f"No behavior change within {acceptance_scope}; "
                        "fresh quality reviewers report no findings for this scope; "
                        "diff-impact classifier reports no logic/boundary impact."
                    ),
                    "layer_constraint": "refactor_only",
                    "required_change_type": "refactor_only",
                    "finding_count": len(scope_gaps),
                    "source_gaps": [
                        {
                            "kind": g.get("kind", ""),
                            "severity": g.get("severity", "MINOR"),
                            "description": g.get("description", ""),
                            "span": g.get("span", {}),
                        }
                        for g in ordered_scope_gaps[:20]
                    ],
                }
            )
        return intentions


class ImplementStep:
    """Execute the plan — layer-aware.

    - L1: Fill function bodies from spec comments via ImplementationRunner (P9)
    - L2: "Architectural assembler" — create/adjust component entrypoints,
      connect pins, add missing handlers/routes, refactor wiring.
      Must NOT invent business logic; emits under-spec or demotion if required.
    - L3: "Clean-code refactorer" — apply targeted refactors for planned
      finding set.  Must NOT change behavior; emits demotion if logic touched.
    """

    name = "IMPLEMENT"

    @staticmethod
    def _focus_targets(ctx: SliceContext) -> dict[str, list[str]]:
        """Return normalized focus targets for implementation hints."""
        if not isinstance(ctx.config, dict):
            return {}
        return _normalize_focus_targets(ctx.config.get("focus_targets", {}))

    @staticmethod
    def _focus_targets_prompt_section(focus_targets: dict[str, list[str]]) -> str:
        """Render focus targets as a compact prompt section."""
        if not focus_targets:
            return ""
        return json.dumps(focus_targets, indent=2)

    @staticmethod
    def _gap_focus_score(gap: dict[str, Any], focus_targets: dict[str, list[str]]) -> int:
        """Score a gap by overlap with focused failing files/symbols."""
        if not focus_targets:
            return 0
        focus_files = {path.replace("\\", "/") for path in focus_targets.get("failing_files", [])}
        focus_symbols = {
            symbol.lower().strip() for symbol in focus_targets.get("location_symbols", []) if symbol
        }
        file_path = str(gap.get("file", "")).strip()
        location = gap.get("location", {}) if isinstance(gap.get("location"), dict) else {}
        symbol = str(gap.get("function") or location.get("symbol") or "").strip().lower()
        score = 0
        if file_path and _path_matches_focus(file_path, focus_files):
            score += 2
        if symbol and symbol in focus_symbols:
            score += 1
        return score

    @classmethod
    def _prioritize_gap_report(
        cls,
        gaps: list[dict[str, Any]],
        focus_targets: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """Prioritize focused failures first while preserving all gap records."""
        if not gaps or not focus_targets:
            return gaps
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for idx, gap in enumerate(gaps):
            if not isinstance(gap, dict):
                continue
            scored.append((cls._gap_focus_score(gap, focus_targets), idx, gap))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [row for _, _, row in scored]

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to layer-specific implementation and emit evidence atomically."""
        from spec_manager.orchestration.evidence import ImplementationRef

        # L1 runs even without intentions (uses gaps directly).
        # L2/L3 need explicit intentions from the planner.
        if ctx.layer != "l1" and not bundle.plan.intentions:
            bundle.implementation = ImplementationRef()
            return StepResult(status="OK")

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            bundle.implementation = ImplementationRef()
            return StepResult(status="OK")

        result: StepResult
        if ctx.layer == "l1":
            result = self._implement_l1(ctx, bundle, slice_root)
        elif ctx.layer == "l2":
            result = self._implement_l2(ctx, bundle, slice_root)
        elif ctx.layer == "l3":
            result = self._implement_l3(ctx, bundle, slice_root)
        else:
            result = StepResult(status="OK")

        if result.status != "OK":
            return result

        try:
            self._emit_transactional_evidence(ctx, bundle, slice_root)
        except Exception as exc:
            logger.warning("Failed to emit transactional evidence: %s", exc, exc_info=True)
            return StepResult(
                status="RETRY",
                notes_path=result.notes_path,
                error=f"Implementation evidence emission failed: {exc}",
            )

        return result

    @staticmethod
    def _collect_slice_hashes(slice_root: Path) -> list[dict[str, Any]]:
        """Collect hash evidence for all non-hidden files in the slice."""
        files: list[dict[str, Any]] = []
        for file_path in sorted(slice_root.rglob("*")):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            try:
                raw = file_path.read_bytes()
            except OSError as exc:
                logger.debug("Skipping unreadable file for hash evidence %s: %s", file_path, exc)
                continue
            rel = _safe_rel(file_path, slice_root)
            files.append(
                {
                    "path": rel,
                    "sha256": _hash_bytes(raw),
                    "size_bytes": len(raw),
                }
            )
        return files

    @staticmethod
    def _canonical_edge_signal(signal_type: Any) -> str:
        """Map implementation-specific edge types to evidence graph contract."""
        if not isinstance(signal_type, str):
            return "REFERENCE"
        signal = signal_type.upper()
        if signal in {"CALL"}:
            return "CALL"
        if signal in {"STORE_TOUCH"}:
            return "STORE_TOUCH"
        if signal in {"EVENT_EMIT", "EVENT_HANDLE", "EVENT"}:
            return "EVENT"
        return "REFERENCE"

    @staticmethod
    def _normalize_gap(gap: dict[str, Any]) -> dict[str, Any]:
        """Ensure every gap has explicit location span metadata."""
        location = gap.get("location", {}) or {}
        span = gap.get("span", {}) or {}
        normalized_span = _location_span(
            start_line=span.get("start_line") or location.get("start_line"),
            end_line=span.get("end_line") or location.get("end_line"),
            start_col=span.get("start_col") or location.get("start_col"),
            end_col=span.get("end_col") or location.get("end_col"),
        )
        file_path = gap.get("file", "") or location.get("file", "")
        merged = dict(gap)
        merged["file"] = file_path
        merged["span"] = normalized_span
        merged["location"] = {"file": file_path, **normalized_span}
        return merged

    @staticmethod
    def _snapshot_text_files(slice_root: Path) -> dict[str, str]:
        """Capture a best-effort UTF-8 snapshot of slice files."""
        snapshot: dict[str, str] = {}
        for file_path in sorted(slice_root.rglob("*")):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            rel = _safe_rel(file_path, slice_root)
            try:
                snapshot[rel] = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        return snapshot

    @staticmethod
    def _collect_patch_targets(
        *,
        edits: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> set[str]:
        """Collect file paths likely touched by implementation."""
        targets: set[str] = set()
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            rel = str(edit.get("file", "")).strip()
            if rel:
                targets.add(rel)
        for intention in intentions:
            if not isinstance(intention, dict):
                continue
            target_file = str(intention.get("target_file", "")).strip()
            if target_file:
                targets.add(target_file)
            raw_target_files = intention.get("target_files", [])
            if isinstance(raw_target_files, list):
                for rel in raw_target_files:
                    rel_str = str(rel).strip()
                    if rel_str:
                        targets.add(rel_str)
        return targets

    @staticmethod
    def _write_patch_artifact(
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        before_snapshot: dict[str, str],
        after_snapshot: dict[str, str],
        target_paths: set[str],
    ) -> str:
        """Write a unified diff artifact and return relative artifact path."""
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)
        iteration_dir.mkdir(parents=True, exist_ok=True)

        candidate_paths = set(before_snapshot.keys()) | set(after_snapshot.keys())
        if target_paths:
            candidate_paths = {path for path in candidate_paths if path in target_paths}

        patch_chunks: list[str] = []
        for rel_path in sorted(candidate_paths):
            before_text = before_snapshot.get(rel_path)
            after_text = after_snapshot.get(rel_path)
            if before_text == after_text:
                continue
            before_lines = (before_text or "").splitlines(keepends=True)
            after_lines = (after_text or "").splitlines(keepends=True)
            diff_lines = list(
                unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                )
            )
            if diff_lines:
                patch_chunks.extend(diff_lines)

        patch_text = "".join(patch_chunks)
        patch_name = "implementation.patch.diff"
        (iteration_dir / patch_name).write_text(patch_text, encoding="utf-8")
        return patch_name

    @staticmethod
    def _gaps_from_under_spec_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Project under-spec events into gap inventory records."""
        gaps: list[dict[str, Any]] = []
        for event in events:
            span = _location_span(
                start_line=(event.get("span") or {}).get("start_line"),
                end_line=(event.get("span") or {}).get("end_line"),
                start_col=(event.get("span") or {}).get("start_col"),
                end_col=(event.get("span") or {}).get("end_col"),
            )
            file_path = event.get("file", "") or event.get("context", "")
            gaps.append(
                {
                    "kind": "ambiguity_gap",
                    "file": file_path,
                    "description": event.get("question", "Under-specification event"),
                    "severity": "BLOCKER",
                    "required_change_type": "spec_change",
                    "span": span,
                    "location": {"file": file_path, **span},
                }
            )
        return gaps

    def _emit_transactional_evidence(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        slice_root: Path,
    ) -> None:
        """Emit code+evidence artifacts as one promotion transaction."""
        from spec_manager.orchestration.evidence import GraphDeltaRef

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)
        iteration_dir.mkdir(parents=True, exist_ok=True)

        file_hashes = self._collect_slice_hashes(slice_root)
        manifest_hash_input = "\n".join(
            f"{f['path']}:{f.get('sha256', '')}"
            for f in sorted(file_hashes, key=lambda x: x["path"])
        )
        manifest_hash = _hash_text(manifest_hash_input) if file_hashes else ""

        # Update manifest/diff to prove evidence aligns with exact file text.
        bundle.manifest.files = file_hashes
        bundle.manifest.path = "manifest.json"
        bundle.diff.changed_files = [f["path"] for f in file_hashes]
        bundle.diff.content_hash = manifest_hash
        bundle.diff.head_commit = manifest_hash
        bundle.diff.path = "diff.json"
        quality_receipts_snapshot: dict[str, Any] = {}
        if _QUALITY_RECEIPTS_FILENAME in (bundle.manifest.generated_files or []):
            quality_receipts_snapshot = {"path": _QUALITY_RECEIPTS_FILENAME}
        _write_iteration_json(
            bundle,
            evidence_root,
            "manifest.json",
            {
                "files": bundle.manifest.files,
                "component_inventory": bundle.manifest.component_inventory,
                "pin_registry_summary": bundle.manifest.pin_registry_summary,
                "slice_patterns": bundle.manifest.slice_patterns,
                "generated_files": bundle.manifest.generated_files,
                "quality_receipts_snapshot": quality_receipts_snapshot,
            },
        )
        _write_iteration_json(
            bundle,
            evidence_root,
            "diff.json",
            {
                "base_commit": bundle.diff.base_commit,
                "head_commit": bundle.diff.head_commit,
                "changed_files": bundle.diff.changed_files,
                "content_hash": bundle.diff.content_hash,
            },
        )

        pin_deltas = bundle.implementation.pin_proposals or []
        edge_deltas = bundle.implementation.edge_proposals or []

        graph_deltas: list[GraphDeltaRef] = []
        if pin_deltas:
            pin_delta_path = iteration_dir / "pins.delta.json"
            pin_delta_path.write_text(json.dumps(pin_deltas, indent=2), encoding="utf-8")
            graph_deltas.append(
                GraphDeltaRef(
                    path=pin_delta_path.name,
                    delta_type="pin_proposal",
                    produced_by=self.name,
                )
            )
        if edge_deltas:
            canonical_edges = []
            for edge in edge_deltas:
                canonical_edges.append(
                    {
                        "src": edge.get("src", ""),
                        "dst": edge.get("dst", ""),
                        "signal_type": self._canonical_edge_signal(edge.get("signal_type")),
                        "weight": edge.get("weight", 0.7),
                    }
                )
            edge_delta_path = iteration_dir / "graph.delta.json"
            edge_delta_path.write_text(json.dumps(canonical_edges, indent=2), encoding="utf-8")
            graph_deltas.append(
                GraphDeltaRef(
                    path=edge_delta_path.name,
                    delta_type="edge_proposal",
                    produced_by=self.name,
                )
            )
        merge_delta_payload = {
            "operation": "merge",
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "applied_edit_count": len(bundle.implementation.applied_edits or []),
            "pin_delta_count": len(pin_deltas),
            "edge_delta_count": len(edge_deltas),
            "manifest_hash": manifest_hash,
        }
        merge_delta_path = iteration_dir / "graph.merge.delta.json"
        merge_delta_path.write_text(json.dumps(merge_delta_payload, indent=2), encoding="utf-8")
        graph_deltas.append(
            GraphDeltaRef(
                path=merge_delta_path.name,
                delta_type="merge",
                produced_by=self.name,
            )
        )
        bundle.graph_deltas = graph_deltas

        explicit_gaps = [
            self._normalize_gap(g)
            for g in (bundle.implementation.gap_inventory or [])
            if isinstance(g, dict)
        ]
        event_gaps = self._gaps_from_under_spec_events(
            bundle.implementation.under_spec_events or []
        )
        if explicit_gaps or event_gaps:
            gap_inventory = explicit_gaps + event_gaps
        else:
            gap_inventory = [self._normalize_gap(g) for g in bundle.gaps.open_gaps]
        gap_path = iteration_dir / "gaps.json"
        gap_path.write_text(json.dumps(gap_inventory, indent=2), encoding="utf-8")
        bundle.gaps.path = gap_path.name
        bundle.gaps.open_gaps = gap_inventory

        impl_result = {
            "applied_edits": bundle.implementation.applied_edits,
            "gap_inventory": bundle.implementation.gap_inventory,
            "pin_proposals": bundle.implementation.pin_proposals,
            "edge_proposals": bundle.implementation.edge_proposals,
            "under_spec_events": bundle.implementation.under_spec_events,
            "tests_added": bundle.implementation.tests_added,
            "patch_path": bundle.implementation.patch_path,
        }
        impl_result_path = iteration_dir / "impl.result.json"
        impl_result_path.write_text(json.dumps(impl_result, indent=2), encoding="utf-8")
        bundle.implementation.result_path = impl_result_path.name

        promotion_report = {
            "transaction": "code_plus_evidence",
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "file_hash": manifest_hash,
            "gap_inventory": bundle.gaps.path,
            "graph_delta_count": len(bundle.graph_deltas),
        }
        promotion_path = iteration_dir / "promotion.report.json"
        promotion_path.write_text(json.dumps(promotion_report, indent=2), encoding="utf-8")
        bundle.promotion.path = promotion_path.name

    def _implement_l1(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L1: fill function bodies via ImplementationRunner (P9)."""
        from spec_manager.orchestration.evidence import ImplementationRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        try:
            from spec_manager.orchestration.implementation.runner import (
                ImplementationRunner,
            )

            runner = ImplementationRunner(
                workspace_root=workspace,
                run_id=ctx.run_id,
            )

            evidence_root = _evidence_base_path(
                slice_root=ctx.slice_root,
                workspace_root=ctx.workspace_root,
            )
            iteration_dir = bundle.iter_dir(evidence_root)
            focus_targets = self._focus_targets(ctx)
            run_result = runner.run_for_slice(
                slice_root=slice_root,
                iteration_dir=iteration_dir,
                plan_intentions=bundle.plan.intentions,
                gap_report=self._prioritize_gap_report(bundle.gaps.open_gaps, focus_targets),
            )

            gap_inventory = self._gaps_from_under_spec_events(run_result.under_spec_events)
            if run_result.functions_skipped > 0:
                gap_inventory.append(
                    {
                        "kind": "stub_gap",
                        "file": "",
                        "description": (
                            f"{run_result.functions_skipped} function(s) were skipped during "
                            "implementation and need follow-up."
                        ),
                        "severity": "MAJOR",
                        "required_change_type": "behavior_change",
                        "span": {},
                        "location": {"file": ""},
                    }
                )
            for err in run_result.errors:
                file_path = err.get("file", "")
                gap_inventory.append(
                    {
                        "kind": "ambiguity_gap",
                        "file": file_path,
                        "description": err.get("error", "Implementation error"),
                        "severity": "BLOCKER",
                        "required_change_type": "spec_change",
                        "span": {},
                        "location": {"file": file_path},
                    }
                )

            bundle.implementation = ImplementationRef(
                patch_path=run_result.patch_path,
                applied_edits=run_result.applied_edits,
                gap_inventory=gap_inventory,
                pin_proposals=run_result.pin_proposals,
                edge_proposals=run_result.edge_proposals,
                under_spec_events=run_result.under_spec_events,
                tests_added=run_result.tests_added,
            )

            if run_result.notes_path:
                return StepResult(status="OK", notes_path=run_result.notes_path)

        except Exception as exc:
            logger.warning("L1 implementation failed: %s", exc, exc_info=True)
            bundle.implementation = ImplementationRef()
            return StepResult(status="RETRY", error=f"L1 implementation failed: {exc}")

        return StepResult(status="OK")

    def _implement_l2(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L2: architectural assembler — wiring, dispatch, lifecycle, IO boundaries."""
        import json

        from spec_manager.core.language import source_rglob
        from spec_manager.orchestration.evidence import ImplementationRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        before_snapshot = self._snapshot_text_files(slice_root)

        # Gather current code for context
        code_summaries: list[str] = []
        for py_file in source_rglob(slice_root):
            if py_file.is_file() and not any(p.startswith(".") for p in py_file.parts):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    lines = content.split("\n")[:60]
                    code_summaries.append(
                        f"### {py_file.relative_to(slice_root)}\n```\n" + "\n".join(lines) + "\n```"
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        intentions_text = json.dumps(bundle.plan.intentions, indent=2)
        focus_targets = self._focus_targets(ctx)
        focus_section = self._focus_targets_prompt_section(focus_targets)
        focus_prompt = f"## FOCUS TARGETS\n{focus_section}\n\n" if focus_section else ""

        prompt = (
            "## TASK\n"
            "You are an Architectural Assembler. Apply minimal patches to wire components:\n"
            "- Create/adjust component entrypoints\n"
            "- Connect pins in correct order\n"
            "- Add missing handlers/routes\n"
            "- Refactor wiring to satisfy boundaries\n\n"
            "CONSTRAINT: Do NOT invent business logic. If the gap requires new logic,\n"
            "return it as an under_spec_event instead of implementing it.\n\n"
            "Return JSON with keys:\n"
            '- "edits": [{"file": ..., "description": ...}]\n'
            '- "pin_proposals": [{"pin_id": ..., "fqn": ..., "file": ..., "span": {...}}]\n'
            '- "edge_proposals": [{"src": ..., "dst": ..., '
            '"signal_type": "CALL"|"STORE_TOUCH"|"EVENT"|"REFERENCE"}]\n'
            '- "gap_inventory": [{"kind": "stub_gap"|"comment_gap"|"ambiguity_gap", "file": ..., '
            '"description": ..., "span": {"start_line": N, "end_line": N}}]\n'
            '- "under_spec_events": [{"question": ..., "context": ...}]\n\n'
            f"## PLAN\n{intentions_text}\n\n"
            f"{focus_prompt}"
            "## CURRENT CODE\n\n" + "\n\n".join(code_summaries[:10])
        )

        try:
            from spec_manager.core.agent_utils import run_agent
            from spec_manager.core.json_extraction import _extract_json_payload
            from spec_manager.refinement.formats import _strip_code_fences

            output = run_agent(
                agent_name="opus-architecture-proposer",
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))

            gap_inventory = [self._normalize_gap(g) for g in data.get("gap_inventory", [])]
            gap_inventory.extend(
                self._gaps_from_under_spec_events(data.get("under_spec_events", []))
            )
            applied_edits = [edit for edit in data.get("edits", []) if isinstance(edit, dict)]
            target_paths = self._collect_patch_targets(
                edits=applied_edits,
                intentions=bundle.plan.intentions,
            )
            after_snapshot = self._snapshot_text_files(slice_root)
            patch_path = self._write_patch_artifact(
                ctx=ctx,
                bundle=bundle,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                target_paths=target_paths,
            )
            bundle.implementation = ImplementationRef(
                patch_path=patch_path,
                applied_edits=applied_edits,
                gap_inventory=gap_inventory,
                pin_proposals=data.get("pin_proposals", []),
                edge_proposals=data.get("edge_proposals", []),
                under_spec_events=data.get("under_spec_events", []),
            )

        except Exception as exc:
            logger.warning("L2 implementation failed: %s", exc)
            bundle.implementation = ImplementationRef()
            return StepResult(
                status="RETRY",
                error=f"L2 implementation parse error: {exc}",
            )

        return StepResult(status="OK")

    def _implement_l3(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L3: clean-code refactorer — targeted refactors, no behavior change."""
        import json

        from spec_manager.core.language import source_rglob
        from spec_manager.orchestration.evidence import ImplementationRef

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        intentions_text = json.dumps(bundle.plan.intentions, indent=2)
        gaps_text = json.dumps(bundle.gaps.open_gaps[:20], indent=2)
        focus_targets = self._focus_targets(ctx)
        focus_section = self._focus_targets_prompt_section(focus_targets)
        focus_prompt = f"## FOCUS TARGETS\n{focus_section}\n\n" if focus_section else ""

        # Gather code for the files being refactored — scope to slice file for L3
        code_summaries: list[str] = []
        target_files = {i.get("target_file", "") for i in bundle.plan.intentions}
        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""
        for py_file in source_rglob(slice_root):
            if target_stem and py_file.stem != target_stem:
                continue
            rel = (
                str(py_file.relative_to(slice_root))
                if slice_root in py_file.parents or py_file.parent == slice_root
                else ""
            )
            if (rel in target_files or not target_files) and py_file.is_file():
                try:
                    content = py_file.read_text(encoding="utf-8")
                    code_summaries.append(
                        f"### {py_file.relative_to(slice_root)}\n```\n{content[:3000]}\n```"
                    )
                except (OSError, UnicodeDecodeError):
                    continue

        prompt = (
            "## TASK\n"
            "You are a Clean-Code Refactorer. Apply targeted refactors to "
            "resolve quality findings.\n\n"
            "CONSTRAINT: Do NOT change behavior. All refactors must be behavior-preserving.\n"
            "If a finding requires a logic change, return it as a demotion_needed item.\n\n"
            "Return JSON with keys:\n"
            '- "edits": [{"file": ..., "description": ...}]\n'
            '- "pin_proposals": [{"pin_id": ..., "fqn": ..., "file": ..., "span": {...}}]\n'
            '- "edge_proposals": [{"src": ..., "dst": ..., '
            '"signal_type": "CALL"|"STORE_TOUCH"|"EVENT"|"REFERENCE"}]\n'
            '- "gap_inventory": [{"kind": "stub_gap"|"comment_gap"|"ambiguity_gap", "file": ..., '
            '"description": ..., "span": {"start_line": N, "end_line": N}}]\n'
            '- "demotion_needed": [{"file": ..., "reason": ..., "target_layer": "L1"|"L2"}]\n\n'
            f"## REFACTOR PLAN\n{intentions_text}\n\n"
            f"## FINDINGS TO ADDRESS\n{gaps_text}\n\n"
            f"{focus_prompt}"
            "## CURRENT CODE\n\n" + "\n\n".join(code_summaries[:10])
        )

        try:
            from spec_manager.core.agent_utils import run_agent
            from spec_manager.core.json_extraction import _extract_json_payload
            from spec_manager.refinement.formats import _strip_code_fences

            output = run_agent(
                agent_name="chatgpt-correctness-reviewer",
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))

            demotion_tickets: list[DemotionTicket] = []
            for item in data.get("demotion_needed", []):
                if not isinstance(item, dict):
                    continue
                target_raw = str(item.get("target_layer", "L1")).strip().upper()
                target = "L2" if target_raw == "L2" else "L1"
                reason = (
                    str(item.get("reason", "")).strip() or "L3 refactor requires lower-layer change"
                )
                file_path = str(item.get("file", "")).strip()
                severity = str(item.get("severity", "")).strip().upper()
                if severity not in {"BLOCKER", "MAJOR", "MINOR"}:
                    severity = "BLOCKER" if target == "L1" else "MAJOR"
                demotion_tickets.append(
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="IMPLEMENT",
                        origin_layer="L3",
                        target_layer=target,
                        severity=severity,
                        diagnosis=reason,
                        failing_files=[file_path] if file_path else [],
                    )
                )

            gap_inventory = [self._normalize_gap(g) for g in data.get("gap_inventory", [])]
            bundle.implementation = ImplementationRef(
                applied_edits=data.get("edits", []),
                gap_inventory=gap_inventory,
                pin_proposals=data.get("pin_proposals", []),
                edge_proposals=data.get("edge_proposals", []),
                under_spec_events=[],
            )
            if demotion_tickets:
                return StepResult(
                    status="RETRY",
                    emitted_tickets=demotion_tickets,
                    error=f"L3 implementation emitted {len(demotion_tickets)} demotion ticket(s)",
                )

        except Exception as exc:
            logger.warning("L3 implementation failed: %s", exc)
            bundle.implementation = ImplementationRef()
            return StepResult(
                status="RETRY",
                error=f"L3 implementation parse error: {exc}",
            )

        return StepResult(status="OK")


class CoordinateStep:
    """Resolve under-specification and coordination signals.

    Delegates all layers to UnderSpecManager so unresolved events block
    promotion until constraints are provided.
    """

    name = "UNDER_SPEC_CHECK"

    def __init__(self, planner: Any = None) -> None:
        self._planner = planner

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Resolve under-spec events for the active layer."""
        return self._resolve_under_spec(ctx, bundle)

    def _coordinate_l1(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Compatibility shim; L1 now uses the unified under-spec resolver."""
        return self._resolve_under_spec(ctx, bundle)

    def _resolve_under_spec(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L2/L3: resolve under-spec events via UnderSpecManager.

        Delegates to UnderSpecManager for constraint resolution.
        """
        raw_events = bundle.implementation.under_spec_events

        if not raw_events:
            return StepResult(status="OK")

        from spec_manager.orchestration.under_spec.manager import (
            UnderSpecEvent,
            UnderSpecManager,
        )

        events = [UnderSpecEvent.from_dict(e) for e in raw_events]
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        manager = UnderSpecManager(
            workspace_root=workspace,
            mode=ctx.mode,
            planner=self._planner,
            run_id=ctx.run_id,
        )
        outcome = manager.resolve(slice_id=ctx.slice_id, events=events, layer=ctx.layer)

        # Record decisions/blockers and under-spec artifacts in the bundle.
        bundle.under_spec.decisions = (
            list(outcome.decisions)
            if outcome.decisions
            else [{"event_id": e.event_id, "question": e.question} for e in outcome.resolved]
        )
        bundle.under_spec.blockers = []
        for event in outcome.blocked:
            payload = event.to_dict()
            if outcome.blocked_on:
                payload["blocked_on"] = list(outcome.blocked_on)
            if outcome.resume_hint:
                payload["resume_hint"] = dict(outcome.resume_hint)
            if outcome.constraint_request_path:
                payload["constraint_request_path"] = outcome.constraint_request_path
            bundle.under_spec.blockers.append(payload)

        if outcome.blockers_path:
            bundle.under_spec.path = outcome.blockers_path
        elif outcome.decisions_path:
            bundle.under_spec.path = outcome.decisions_path

        # Record new constraint refs
        if outcome.constraints:
            constraint_path = outcome.resume_hint.get("constraints_path") or str(
                workspace / "analysis" / "constraints" / f"{ctx.slice_id}.yaml"
            )
            if constraint_path not in bundle.facts.constraints_refs:
                bundle.facts.constraints_refs.append(constraint_path)

        if outcome.is_blocked:
            bundle.status = outcome.bundle_status
            return StepResult(
                status="BLOCKED",
                error=f"Under-specification: {len(outcome.blocked)} unresolvable events",
            )

        return StepResult(status="OK")


class AnalyzeStep:
    """Analyze slice after implementation — layer-aware.

    - L1: P1 + P2 (parse_file adapters + analyze_source cache)
    - L2: Build architecture graph cache (components/entrypoints/pins + wiring edges)
    - L3: Compute diff summary + structural metrics (size, duplication
      hotspots, refactor impact candidates)
    """

    name = "ANALYZE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Dispatch to layer-specific analysis."""
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            return StepResult(status="OK")

        if ctx.layer == "l1":
            return self._analyze_l1(ctx, bundle, slice_root)
        if ctx.layer == "l2":
            return self._analyze_l2(ctx, bundle, slice_root)
        if ctx.layer == "l3":
            return self._analyze_l3(ctx, bundle, slice_root)

        return StepResult(status="OK")

    def _analyze_l1(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L1: source analysis via cache (P1 + P2)."""
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        try:
            from spec_manager.comment_planning.models import parse_file
            from spec_manager.orchestration.source_analysis_cache import (
                SourceAnalysisCache,
            )

            cache = SourceAnalysisCache(
                workspace_root=workspace,
                run_id=ctx.run_id,
            )

            entries: list[dict[str, Any]] = []
            normalized_functions: dict[str, Any] = {}
            reverse_payload: list[dict[str, Any]] = []

            targets = self._analysis_targets(bundle, slice_root)
            for py_file in targets:
                if not py_file.is_file():
                    continue
                if any(part.startswith(".") for part in py_file.parts):
                    continue

                try:
                    content = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Skipping %s: %s", py_file, exc)
                    continue

                relative_path = str(py_file.relative_to(slice_root))
                analysis = cache.analyze_with_cache(content, relative_path)
                analysis_functions = [asdict(fn) for fn in analysis.functions]
                analysis_comments = [asdict(comment) for comment in analysis.comments]

                parsed_functions: list[dict[str, Any]] = []
                try:
                    parsed_file = parse_file(str(py_file))
                    for func in parsed_file.functions:
                        comment_texts = [c.text for c in func.comments if c.text]
                        parsed_functions.append(
                            {
                                "name": func.name,
                                "class_name": func.class_name,
                                "start_line": func.start_line,
                                "end_line": func.end_line,
                                "comment_count": len(comment_texts),
                            }
                        )
                        if comment_texts:
                            reverse_payload.append(
                                {
                                    "file": relative_path,
                                    "function": func.name,
                                    "class_name": func.class_name,
                                    "start_line": func.start_line,
                                    "end_line": func.end_line,
                                    "comments": comment_texts,
                                }
                            )
                except Exception as exc:
                    logger.debug("parse_file failed for %s: %s", py_file, exc)

                entries.append(
                    {
                        "path": relative_path,
                        "content_hash": _hash_text(content),
                        "analysis": {
                            "functions": analysis_functions,
                            "comments": analysis_comments,
                            "parse_file": {"functions": parsed_functions},
                        },
                    }
                )

                for fn in analysis_functions:
                    qualified_name = fn.get("qualified_name") or fn.get("name") or ""
                    if not qualified_name:
                        continue
                    normalized_functions[qualified_name] = {
                        "signature": {
                            "name": fn.get("name", ""),
                            "args": fn.get("args", []),
                            "return_annotation": fn.get("return_annotation"),
                            "is_async": fn.get("is_async", False),
                        },
                        "doc": fn.get("docstring", ""),
                        "file": relative_path,
                        "lines": [fn.get("start_line", 0), fn.get("end_line", 0)],
                    }

            bundle.source_index.entries = entries
            bundle.source_index.path = "source_analysis.index.json"
            if normalized_functions:
                bundle.facts.functions.update(normalized_functions)

            if reverse_payload:
                evidence_root = _evidence_base_path(
                    slice_root=ctx.slice_root,
                    workspace_root=ctx.workspace_root,
                )
                _write_iteration_json(
                    bundle,
                    evidence_root,
                    "reverse_pseudocode.json",
                    {"items": reverse_payload},
                )

            logger.info(
                "Analyzed %d files (cache stats: %s)",
                len(entries),
                cache.stats,
            )

        except Exception as exc:
            logger.warning("L1 analysis failed: %s", exc, exc_info=True)
            return StepResult(status="RETRY", error=f"L1 analysis failed: {exc}")

        return StepResult(status="OK")

    def _analyze_l2(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L2: build architecture graph cache for promote/verify continuity checks."""
        from types import SimpleNamespace

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        discovery: dict[str, Any] = {}
        try:
            from spec_manager.planner.layers.l2 import L2Planner

            discovery = L2Planner().discover(
                SimpleNamespace(workspace_root=str(workspace), slice_root=ctx.slice_root)
            )
        except Exception as exc:
            logger.debug("L2 analyze discovery fallback failed: %s", exc)
            discovery = {"nodes": [], "edges": [], "arch_files": [], "discovery_issues": [str(exc)]}

        topology_nodes = [n for n in discovery.get("nodes", []) if isinstance(n, dict)]
        topology_edges = [e for e in discovery.get("edges", []) if isinstance(e, dict)]
        arch_files = [
            str(path).strip()
            for path in discovery.get("arch_files", [])
            if isinstance(path, str) and str(path).strip()
        ]

        component_manifest = _load_run_component_manifest(workspace, bundle.run_id)
        pin_registry = _load_pin_registry_snapshot(slice_root)
        pin_functions = [item for item in pin_registry.get("pins", []) if isinstance(item, dict)]
        import_edges = [item for item in pin_registry.get("edges", []) if isinstance(item, dict)]

        graph_nodes: list[dict[str, Any]] = []
        graph_edges: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        seen_edges: set[str] = set()

        def add_node(
            *, node_id: str, node_type: str, file_path: str = "", metadata: Any = None
        ) -> None:
            normalized_id = node_id.strip()
            if not normalized_id:
                return
            key = f"{node_type}:{normalized_id}"
            if key in seen_nodes:
                return
            seen_nodes.add(key)
            graph_nodes.append(
                {
                    "id": normalized_id,
                    "type": node_type,
                    "file": file_path,
                    "metadata": metadata if isinstance(metadata, dict) else {},
                }
            )

        def add_edge(
            *,
            source: str,
            target: str,
            edge_type: str,
            file_path: str = "",
            metadata: Any = None,
        ) -> None:
            src = source.strip()
            dst = target.strip()
            if not src or not dst:
                return
            edge_kind = edge_type.strip().lower() or "reference"
            key = f"{src}|{edge_kind}|{dst}|{file_path}"
            if key in seen_edges:
                return
            seen_edges.add(key)
            graph_edges.append(
                {
                    "source": src,
                    "target": dst,
                    "type": edge_kind,
                    "file": file_path,
                    "metadata": metadata if isinstance(metadata, dict) else {},
                }
            )

        for node in topology_nodes:
            node_id = GapExplorationStep._topology_node_id(node)
            node_type = str(node.get("type") or node.get("kind") or "unknown").strip().lower()
            file_path = str(node.get("file") or node.get("arch_file_path") or "").strip()
            if node_type in {"component", "pin", "handler", "route", "edge"}:
                add_node(node_id=node_id, node_type=node_type, file_path=file_path, metadata=node)

        for edge in topology_edges:
            src, dst = GapExplorationStep._topology_edge_endpoints(edge)
            edge_type = str(edge.get("type") or edge.get("signal_type") or "wired_to")
            file_path = str(edge.get("file") or edge.get("arch_file_path") or "").strip()
            add_edge(
                source=src, target=dst, edge_type=edge_type, file_path=file_path, metadata=edge
            )

        for component in component_manifest:
            component_id = str(component.get("component_id", "")).strip()
            if not component_id:
                continue
            component_files = [
                str(path).strip()
                for path in component.get("files", [])
                if isinstance(path, str) and str(path).strip()
            ]
            primary_file = component_files[0] if component_files else ""
            add_node(
                node_id=component_id,
                node_type="component",
                file_path=primary_file,
                metadata={"files": component_files},
            )
            for entrypoint in component.get("owned_entrypoints", []):
                if not isinstance(entrypoint, str):
                    continue
                entrypoint_id = entrypoint.strip()
                if not entrypoint_id:
                    continue
                add_node(node_id=entrypoint_id, node_type="entrypoint", file_path=primary_file)
                add_edge(
                    source=entrypoint_id,
                    target=component_id,
                    edge_type="declared_in",
                    file_path=primary_file,
                )
            for upstream in component.get("upstream", []):
                if isinstance(upstream, str) and upstream.strip():
                    add_edge(
                        source=upstream,
                        target=component_id,
                        edge_type="dependency",
                        file_path=primary_file,
                    )
            for downstream in component.get("downstream", []):
                if isinstance(downstream, str) and downstream.strip():
                    add_edge(
                        source=component_id,
                        target=downstream,
                        edge_type="dependency",
                        file_path=primary_file,
                    )

        for pin in pin_functions:
            pin_id = str(pin.get("pin_func_id") or pin.get("pin_id") or pin.get("id") or "").strip()
            file_path = str(pin.get("file_path") or pin.get("file") or "").strip()
            add_node(node_id=pin_id, node_type="pin", file_path=file_path, metadata=pin)

        for edge in import_edges:
            src = str(edge.get("pin_func_id") or edge.get("src") or "").strip()
            dst = str(edge.get("arch_location") or edge.get("dst") or "").strip()
            file_path = str(edge.get("arch_file_path") or edge.get("file") or "").strip()
            edge_type = str(edge.get("projection_type") or edge.get("signal_type") or "wired_to")
            add_edge(
                source=src, target=dst, edge_type=edge_type, file_path=file_path, metadata=edge
            )

        if bundle.manifest.component_inventory:
            for component in bundle.manifest.component_inventory:
                if not isinstance(component, dict):
                    continue
                component_id = str(component.get("component_id", "")).strip()
                component_files = [
                    str(path).strip()
                    for path in component.get("files", [])
                    if isinstance(path, str) and str(path).strip()
                ]
                add_node(
                    node_id=component_id,
                    node_type="component",
                    file_path=component_files[0] if component_files else "",
                    metadata={"source": "manifest.component_inventory"},
                )

        node_type_counts: dict[str, int] = {}
        for node in graph_nodes:
            node_type = str(node.get("type", "unknown"))
            node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

        edge_type_counts: dict[str, int] = {}
        for edge in graph_edges:
            edge_type = str(edge.get("type", "reference"))
            edge_type_counts[edge_type] = edge_type_counts.get(edge_type, 0) + 1

        graph_payload = {
            "schema_version": "1",
            "slice_id": ctx.slice_id,
            "run_id": ctx.run_id,
            "layer": ctx.layer,
            "arch_files": sorted(set(arch_files)),
            "nodes": graph_nodes,
            "edges": graph_edges,
            "stats": {
                "node_count": len(graph_nodes),
                "edge_count": len(graph_edges),
                "node_type_counts": node_type_counts,
                "edge_type_counts": edge_type_counts,
                "component_count": len(
                    [node for node in graph_nodes if str(node.get("type")) == "component"]
                ),
                "pin_count": len([node for node in graph_nodes if str(node.get("type")) == "pin"]),
                "entrypoint_count": len(
                    [node for node in graph_nodes if str(node.get("type")) == "entrypoint"]
                ),
                "discovery_issues": [
                    issue
                    for issue in discovery.get("discovery_issues", [])
                    if isinstance(issue, str)
                ],
            },
        }

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        graph_path = _write_iteration_json(
            bundle, evidence_root, "architecture.graph.json", graph_payload
        )
        graph_payload_json = json.dumps(graph_payload, indent=2)
        bundle.source_index.entries = [
            {
                "path": graph_path,
                "content_hash": _hash_text(graph_payload_json),
                "analysis": {
                    "type": "l2_architecture_graph",
                    "graph_path": graph_path,
                    "stats": graph_payload["stats"],
                    "arch_files": graph_payload["arch_files"],
                },
            }
        ]
        bundle.source_index.path = "source_analysis.index.json"
        return StepResult(status="OK")

    @staticmethod
    def _analysis_targets(bundle: EvidenceBundle, slice_root: Path) -> list[Path]:
        """Select files to analyze, preferring the current diff working set."""
        from spec_manager.core.language import SOURCE_EXTENSIONS, source_rglob

        targets: list[Path] = []
        seen: set[str] = set()
        for changed in bundle.diff.changed_files or []:
            if not isinstance(changed, str) or not changed.strip():
                continue
            candidate = slice_root / changed
            if not candidate.is_file():
                continue
            if candidate.suffix not in SOURCE_EXTENSIONS:
                continue
            key = candidate.resolve().as_posix()
            if key in seen:
                continue
            seen.add(key)
            targets.append(candidate)

        if targets:
            return sorted(targets)

        return source_rglob(slice_root)

    def _analyze_l3(
        self, ctx: SliceContext, bundle: EvidenceBundle, slice_root: Path
    ) -> StepResult:
        """L3: diff summary + structural metrics."""
        from spec_manager.core.language import FUNCTION_KEYWORDS, source_rglob

        entries: list[dict[str, Any]] = []
        total_lines = 0
        total_functions = 0
        previous_hashes: dict[str, str] = {}
        if bundle.iteration > 1:
            evidence_root = _evidence_base_path(
                slice_root=ctx.slice_root,
                workspace_root=ctx.workspace_root,
            )
            prev_bundle_path = _bundle_json_path(
                evidence_root,
                bundle.run_id,
                bundle.slice_id,
                bundle.iteration - 1,
            )
            if prev_bundle_path.exists():
                try:
                    previous_bundle = EvidenceBundle.load(prev_bundle_path)
                    previous_hashes = {
                        str(entry.get("path", "")).strip(): str(
                            entry.get("content_hash", "")
                        ).strip()
                        for entry in (previous_bundle.source_index.entries or [])
                        if isinstance(entry, dict) and str(entry.get("path", "")).strip()
                    }
                except Exception as exc:
                    logger.debug("L3 analyze previous bundle load failed: %s", exc)

        current_hashes: dict[str, str] = {}
        duplicate_windows: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
        refactor_impact_candidates: list[dict[str, Any]] = []
        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""

        for py_file in source_rglob(slice_root):
            if not py_file.is_file():
                continue
            if any(part.startswith(".") for part in py_file.parts):
                continue
            if target_stem and py_file.stem != target_stem:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.split("\n")
                rel_path = str(py_file.relative_to(slice_root))
                content_hash = _hash_text(content)
                current_hashes[rel_path] = content_hash

                function_lines = [
                    line_number
                    for line_number, line in enumerate(lines, start=1)
                    if any(line.strip().startswith(kw) for kw in FUNCTION_KEYWORDS)
                ]
                func_count = len(function_lines)
                function_lengths: list[int] = []
                for index, start_line in enumerate(function_lines):
                    next_start = (
                        function_lines[index + 1] - 1
                        if index + 1 < len(function_lines)
                        else len(lines)
                    )
                    function_lengths.append(max(next_start - start_line + 1, 1))

                normalized_window_lines: list[tuple[int, str]] = []
                for line_number, raw_line in enumerate(lines, start=1):
                    token = raw_line.strip()
                    if not token or token.startswith("#"):
                        continue
                    normalized_window_lines.append((line_number, "".join(token.split())))
                for idx in range(0, max(len(normalized_window_lines) - 2, 0)):
                    chunk = normalized_window_lines[idx : idx + 3]
                    if len(chunk) < 3:
                        continue
                    signature = "\n".join(item[1] for item in chunk)
                    if len(signature) < 40:
                        continue
                    key = _hash_text(signature)
                    duplicate_windows[key].append((rel_path, chunk[0][0], chunk[-1][0]))

                changed_from_previous = (
                    previous_hashes.get(rel_path) != content_hash if previous_hashes else True
                )
                gap_candidates = [
                    {
                        "reason": str(gap.get("description", "")).strip()[:220],
                        "severity": str(gap.get("severity", "MINOR")).upper(),
                        "span": gap.get("span", {}),
                    }
                    for gap in (bundle.gaps.open_gaps or [])
                    if isinstance(gap, dict) and str(gap.get("file", "")).strip() == rel_path
                ]
                if changed_from_previous:
                    refactor_impact_candidates.append(
                        {
                            "file": rel_path,
                            "reason": "content_hash_changed",
                            "function_count": func_count,
                            "candidate_spans": [
                                item.get("span", {}) for item in gap_candidates[:5]
                            ],
                        }
                    )

                total_lines += len(lines)
                total_functions += func_count
                entries.append(
                    {
                        "path": rel_path,
                        "content_hash": content_hash,
                        "analysis": {
                            "type": "l3_quality_metrics",
                            "metrics": {
                                "lines": len(lines),
                                "functions": func_count,
                                "max_function_length_lines": max(function_lengths)
                                if function_lengths
                                else 0,
                                "avg_function_length_lines": (
                                    round(sum(function_lengths) / len(function_lengths), 2)
                                    if function_lengths
                                    else 0.0
                                ),
                            },
                            "diff_summary": {
                                "changed_from_previous_iteration": changed_from_previous,
                                "present_in_manifest_diff": rel_path
                                in set(bundle.diff.changed_files or []),
                            },
                            "refactor_impact_candidates": gap_candidates[:10],
                        },
                    }
                )
            except (OSError, UnicodeDecodeError):
                continue

        duplicate_hotspots = [
            {
                "occurrences": len(locations),
                "locations": [f"{path}:{start}-{end}" for path, start, end in locations[:6]],
            }
            for locations in duplicate_windows.values()
            if len(locations) > 1
        ]
        duplicate_hotspots.sort(key=lambda item: item["occurrences"], reverse=True)

        current_paths = set(current_hashes)
        previous_paths = set(previous_hashes)
        changed_files = sorted(
            path
            for path in current_paths & previous_paths
            if previous_hashes[path] != current_hashes[path]
        )
        added_files = sorted(current_paths - previous_paths)
        removed_files = sorted(previous_paths - current_paths)
        unchanged_count = len(current_paths & previous_paths) - len(changed_files)

        entries.append(
            {
                "path": "__l3_analysis_summary__",
                "content_hash": bundle.diff.content_hash,
                "analysis": {
                    "type": "l3_summary",
                    "diff_summary": {
                        "changed_files": changed_files,
                        "added_files": added_files,
                        "removed_files": removed_files,
                        "unchanged_file_count": max(unchanged_count, 0),
                        "manifest_changed_files": list(bundle.diff.changed_files or []),
                    },
                    "structural_metrics": {
                        "total_files": len(current_hashes),
                        "total_lines": total_lines,
                        "total_functions": total_functions,
                        "duplication_hotspots": duplicate_hotspots[:25],
                    },
                    "refactor_impact_candidates": refactor_impact_candidates[:40],
                },
            }
        )

        bundle.source_index.entries = entries
        bundle.source_index.path = "source_analysis.index.json"

        logger.info(
            "L3 analysis: %d files, %d lines, %d functions, %d duplicate hotspots",
            len(current_hashes),
            total_lines,
            total_functions,
            len(duplicate_hotspots),
        )

        return StepResult(status="OK")


class PromoteStep:
    """Run promotion mechanics, gates, then refinement."""

    name = "PROMOTE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Run P4/P5 mechanics, dispatch gates, then persist refinement output."""
        has_evidence = bool(
            bundle.manifest.files
            or bundle.implementation.applied_edits
            or bundle.implementation.pin_proposals
            or bundle.implementation.edge_proposals
            or bundle.gaps.open_gaps
        )
        if not has_evidence:
            return StepResult(status="OK")

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            return StepResult(status="RETRY", error="PROMOTE requires a valid slice root")

        mechanics = self._run_promotion_mechanics(ctx, bundle, slice_root)
        if mechanics.status != "OK":
            return mechanics

        if ctx.layer == "l1":
            result = self._promote_l1(ctx, bundle)
        elif ctx.layer == "l2":
            result = self._promote_l2(ctx, bundle)
        elif ctx.layer == "l3":
            result = self._promote_l3(ctx, bundle)
        else:
            result = StepResult(status="OK")

        if result.status == "OK":
            self._emit_refinement_artifact(ctx, bundle)
        return result

    @staticmethod
    def _current_layer_literal(layer: str) -> Literal["L1", "L2", "L3"]:
        normalized = str(layer).strip().upper()
        if normalized == "L2":
            return "L2"
        if normalized == "L3":
            return "L3"
        return "L1"

    @staticmethod
    def _bundle_required_evidence_refs(bundle: EvidenceBundle) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = [
            ("manifest.path", str(bundle.manifest.path or "").strip()),
            ("diff.path", str(bundle.diff.path or "").strip()),
            ("implementation.result_path", str(bundle.implementation.result_path or "").strip()),
            ("pins_snapshot.path", str(bundle.pins_snapshot.path or "").strip()),
            ("graph_snapshot.path", str(bundle.graph_snapshot.path or "").strip()),
        ]
        refs.extend(
            (
                f"manifest.generated_files[{idx}]",
                str(rel_path).strip(),
            )
            for idx, rel_path in enumerate(bundle.manifest.generated_files or [])
            if str(rel_path).strip()
        )
        return refs

    def _prior_iteration_bundle(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        evidence_root: Path,
    ) -> tuple[dict[str, Any], Path | None]:
        """Load the latest completed bundle from a prior iteration for this slice."""
        slices_root = (
            evidence_root / ".pdd_runs" / ctx.run_id / "slices" / ctx.slice_id
            if ctx.run_id and ctx.slice_id
            else None
        )
        if slices_root is None or not slices_root.exists():
            return {}, None

        candidates: list[Path] = []
        for candidate in slices_root.glob("iter_*/bundle.json"):
            try:
                iter_num = int(candidate.parent.name.split("_")[-1])
            except (TypeError, ValueError):
                continue
            if iter_num >= bundle.iteration:
                continue
            candidates.append(candidate)

        if not candidates:
            return {}, None

        latest = sorted(candidates)[-1]
        payload = _read_json_file(latest)
        return (payload if isinstance(payload, dict) else {}), latest.parent

    def _collect_dirty_clean_governance_findings(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        iteration_dir: Path,
        evidence_root: Path,
    ) -> tuple[list[str], list[str]]:
        """Return FAIL/WARN findings for dirty→clean promotion governance."""
        failures: list[str] = []
        warnings: list[str] = []

        for label, rel_path in self._bundle_required_evidence_refs(bundle):
            if not rel_path:
                failures.append(f"{label} missing")
                continue
            artifact_path = iteration_dir / rel_path
            if not artifact_path.exists():
                failures.append(f"{label} missing artifact file: {rel_path}")

        prior_bundle, prior_iter_dir = self._prior_iteration_bundle(
            ctx=ctx,
            bundle=bundle,
            evidence_root=evidence_root,
        )
        if not prior_bundle:
            warnings.append("No prior iteration bundle available for CI receipt continuity check")
        else:
            integration_ref = str((prior_bundle.get("integration") or {}).get("path", "")).strip()
            if not integration_ref or prior_iter_dir is None:
                failures.append("Prior iteration missing integration report reference")
            else:
                integration_payload = _read_json_file(prior_iter_dir / integration_ref)
                if not isinstance(integration_payload, dict):
                    failures.append("Prior iteration integration report unreadable")
                else:
                    ci_tick = integration_payload.get("ci_tick")
                    if not isinstance(ci_tick, dict):
                        failures.append(
                            "Prior iteration integration report missing ci_tick payload"
                        )
                    else:
                        if not bool(ci_tick.get("triggered", False)):
                            failures.append("Prior iteration CI tick was not triggered")
                        ci_error = str(ci_tick.get("error", "")).strip()
                        if ci_error:
                            failures.append(f"Prior iteration CI tick error: {ci_error}")
                        ci_receipt = ci_tick.get("receipt")
                        if not isinstance(ci_receipt, dict) or not ci_receipt:
                            failures.append("Prior iteration CI tick receipt missing")
                        elif bool(ci_receipt.get("failed", False)):
                            failures.append("Prior iteration CI tick receipt recorded failed=true")

            tests_ref = (prior_bundle.get("tests") or {}).get("slice_path", "")
            tests_path = str(tests_ref).strip()
            if not tests_path or prior_iter_dir is None:
                failures.append("Prior iteration missing slice test receipt reference")
            else:
                tests_payload = _read_json_file(prior_iter_dir / tests_path)
                if not isinstance(tests_payload, dict):
                    failures.append("Prior iteration slice test receipt unreadable")
                else:
                    result_payload = tests_payload.get("result")
                    if not isinstance(result_payload, dict):
                        failures.append("Prior iteration slice test receipt missing result payload")

        under_spec_events = list(bundle.implementation.under_spec_events or [])
        has_decision_activity = bool(under_spec_events or bundle.under_spec.decisions)
        if has_decision_activity:
            decision_ref = str(bundle.under_spec.path or "").strip()
            if not decision_ref:
                failures.append(
                    "Decision activity detected but under_spec.path decision log is missing"
                )
            else:
                decision_path = iteration_dir / decision_ref
                if not decision_path.exists():
                    failures.append(f"Decision log artifact missing: {decision_ref}")
                else:
                    decision_payload = _read_json_file(decision_path)
                    if not isinstance(decision_payload, dict):
                        failures.append(f"Decision log artifact unreadable: {decision_ref}")
                    elif "decisions" not in decision_payload and "blockers" not in decision_payload:
                        failures.append(
                            f"Decision log artifact missing decisions/blockers: {decision_ref}"
                        )
                    impl_ref = str(bundle.implementation.result_path or "").strip()
                    impl_path = iteration_dir / impl_ref if impl_ref else None
                    if (
                        impl_path
                        and impl_path.exists()
                        and (decision_path.stat().st_mtime < impl_path.stat().st_mtime)
                    ):
                        failures.append(
                            "Decision log is stale relative to current implementation artifact"
                        )

        return failures, warnings

    @staticmethod
    def _canonical_edge_signal(signal_type: Any) -> str:
        """Map edge/projection labels to canonical graph signal types."""
        if not isinstance(signal_type, str):
            return "REFERENCE"
        signal = signal_type.upper()
        if signal in {"CALL"}:
            return "CALL"
        if signal in {"STORE_TOUCH", "AGGREGATION"}:
            return "STORE_TOUCH"
        if signal in {"EVENT_EMIT", "EVENT_HANDLE", "EVENT", "EVENT_BRIDGE"}:
            return "EVENT"
        return "REFERENCE"

    def _normalize_pin_proposals(
        self, proposals: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        """Normalize IMPLEMENT pin proposals into pin-orchestrator shape."""
        normalized: list[dict[str, Any]] = []
        for proposal in proposals or []:
            if not isinstance(proposal, dict):
                continue
            fqn = str(
                proposal.get("fqn")
                or proposal.get("qualified_name")
                or proposal.get("function_name")
                or ""
            )
            function_name = str(proposal.get("function_name") or "").strip()
            module_path = str(proposal.get("module_path") or "").strip()
            if not function_name and fqn:
                function_name = fqn.rsplit(".", 1)[-1]
            if not module_path and "." in fqn:
                module_path = fqn.rsplit(".", 1)[0]

            file_path = str(proposal.get("file_path") or proposal.get("file") or "").strip()
            span = proposal.get("span") if isinstance(proposal.get("span"), dict) else {}
            line_start = proposal.get("line_start") or span.get("start_line") or 0
            line_end = proposal.get("line_end") or span.get("end_line") or line_start

            normalized.append(
                {
                    "pin_func_id": proposal.get("pin_func_id")
                    or proposal.get("pin_id")
                    or proposal.get("id")
                    or "",
                    "function_name": function_name,
                    "module_path": module_path,
                    "file_path": file_path,
                    "line_start": int(line_start) if isinstance(line_start, int | float) else 0,
                    "line_end": int(line_end) if isinstance(line_end, int | float) else 0,
                    "signature": proposal.get("signature", ""),
                    "docstring": proposal.get("docstring", ""),
                    "content_hash": proposal.get("content_hash", ""),
                    "is_shape": bool(
                        proposal.get("is_shape") or str(proposal.get("role", "")).upper() == "SHAPE"
                    ),
                    "store_touches": proposal.get("store_touches", []),
                    "evidence_atom_ids": proposal.get("evidence_atom_ids", []),
                }
            )
        return normalized

    def _normalize_edge_proposals(
        self, proposals: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        """Normalize IMPLEMENT edge proposals into pin-orchestrator shape."""
        normalized: list[dict[str, Any]] = []
        for proposal in proposals or []:
            if not isinstance(proposal, dict):
                continue

            arch_location = str(proposal.get("arch_location") or proposal.get("dst") or "").strip()
            arch_file_path = str(proposal.get("arch_file_path") or "").strip()
            if not arch_file_path and ":" in arch_location:
                arch_file_path = arch_location.split(":", 1)[0]
            if not arch_location and arch_file_path:
                arch_location = arch_file_path

            arch_line = proposal.get("arch_line")
            if not isinstance(arch_line, int):
                if ":" in arch_location:
                    line_candidate = arch_location.rsplit(":", 1)[-1]
                    arch_line = int(line_candidate) if line_candidate.isdigit() else 0
                else:
                    arch_line = 0

            projection_type = proposal.get("projection_type")
            if not isinstance(projection_type, str) or not projection_type.strip():
                raise ValueError("edge_proposals entries must include projection_type")
            confidence_raw = proposal.get("confidence", proposal.get("weight", 0.8))
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                raise ValueError(
                    f"edge_proposals has invalid confidence value {confidence_raw!r}"
                ) from None

            normalized.append(
                {
                    "edge_id": proposal.get("edge_id", ""),
                    "pin_func_id": proposal.get("pin_func_id") or proposal.get("src") or "",
                    "arch_location": arch_location,
                    "arch_file_path": arch_file_path,
                    "arch_line": arch_line,
                    "projection_type": str(projection_type).strip().lower(),
                    "confidence": confidence,
                    "is_direct_import": bool(proposal.get("is_direct_import", True)),
                }
            )
        return normalized

    def _run_promotion_mechanics(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        slice_root: Path,
    ) -> StepResult:
        """Execute collapse + pin/edge promotion and materialize snapshots."""
        from spec_manager.pin_functions.orchestrator import PinFunctionOrchestrator

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)
        iteration_dir.mkdir(parents=True, exist_ok=True)

        try:
            normalized_pins = self._normalize_pin_proposals(bundle.implementation.pin_proposals)
            normalized_edges = self._normalize_edge_proposals(bundle.implementation.edge_proposals)
        except ValueError as exc:
            return StepResult(status="RETRY", error=f"P5 proposal normalization failed: {exc}")

        pin_proposals_path: Path | None = None
        if normalized_pins:
            pin_proposals_path = iteration_dir / "pin_proposals.normalized.json"
            pin_proposals_path.write_text(json.dumps(normalized_pins, indent=2), encoding="utf-8")

        edge_proposals_path: Path | None = None
        if normalized_edges:
            edge_proposals_path = iteration_dir / "edge_proposals.normalized.json"
            edge_proposals_path.write_text(json.dumps(normalized_edges, indent=2), encoding="utf-8")

        orchestrator = PinFunctionOrchestrator(slice_root)
        try:
            registry = orchestrator.scan(
                mode="proposals",
                pin_proposals=normalized_pins,
                edge_proposals=normalized_edges,
                pin_proposals_path=pin_proposals_path,
                edge_proposals_path=edge_proposals_path,
                source_index_entries=bundle.source_index.entries,
                changed_files=[
                    str(path)
                    for path in (bundle.diff.changed_files or [])
                    if isinstance(path, str) and str(path).strip()
                ],
            )
            registry_path = orchestrator.save_registry(registry)
        except Exception as exc:
            logger.warning("Pin/edge promotion orchestration failed: %s", exc, exc_info=True)
            return StepResult(status="RETRY", error=f"P5 pin/edge promotion failed: {exc}")

        self._materialize_snapshots(
            ctx=ctx,
            bundle=bundle,
            evidence_root=evidence_root,
            registry=registry,
        )

        collapse_payload: dict[str, Any] = {"executed": False}
        promote_payload: dict[str, Any] = {"executed": False}
        warnings: list[str] = []
        governance_failures: list[str] = []
        governance_warnings: list[str] = []

        branch_manager = ctx.branch_manager
        if branch_manager is not None:
            collapse_fn = getattr(branch_manager, "collapse_codebase", None)
            if callable(collapse_fn):
                try:
                    collapse_result = collapse_fn(slice_root)
                    collapse_payload = {
                        "executed": True,
                        "result": collapse_result.to_dict()
                        if hasattr(collapse_result, "to_dict")
                        else {},
                    }
                except Exception as exc:
                    warnings.append(f"collapse_codebase failed: {exc}")
            else:
                warnings.append("collapse_codebase unavailable on branch_manager")

            governance_failures, governance_warnings = (
                self._collect_dirty_clean_governance_findings(
                    ctx=ctx,
                    bundle=bundle,
                    iteration_dir=iteration_dir,
                    evidence_root=evidence_root,
                )
            )
            for warning in governance_warnings:
                warnings.append(f"dirty-clean governance WARN: {warning}")

            promote_fn = getattr(branch_manager, "promote", None)
            if callable(promote_fn):
                if governance_failures:
                    promote_payload = {
                        "executed": False,
                        "success": False,
                        "error": "dirty-clean governance gate failed",
                    }
                else:
                    try:
                        promote_result = promote_fn(skip_compliance=True)
                        promote_payload = {
                            "executed": True,
                            "result": promote_result.to_dict()
                            if hasattr(promote_result, "to_dict")
                            else {},
                            "success": bool(getattr(promote_result, "success", True)),
                        }
                        if not promote_payload["success"]:
                            warnings.append("branch promotion reported unsuccessful result")
                    except Exception as exc:
                        warnings.append(f"branch promote failed: {exc}")
            else:
                warnings.append("promote unavailable on branch_manager")
        else:
            warnings.append("branch_manager not available for P4/P5 branch promotion")

        bundle.promotion.path = _write_iteration_json(
            bundle,
            evidence_root,
            "promotion.report.json",
            {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "pins_snapshot": bundle.pins_snapshot.path,
                "graph_snapshot": bundle.graph_snapshot.path,
                "pin_registry_path": str(registry_path),
                "collapse": collapse_payload,
                "promotion": promote_payload,
                "dirty_clean_governance": {
                    "passed": not governance_failures,
                    "failures": governance_failures,
                    "warnings": governance_warnings,
                },
                "warnings": warnings,
            },
        )

        if governance_failures:
            current_layer = self._current_layer_literal(ctx.layer)
            ticket = DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="GATE_FAILURE",
                category="governance",
                gate="DIRTY_TO_CLEAN_GOVERNANCE",
                origin_layer=current_layer,
                target_layer=current_layer,
                severity="BLOCKER",
                diagnosis="; ".join(governance_failures[:5]),
                evidence_refs=[bundle.promotion.path] if bundle.promotion.path else [],
            )
            return StepResult(
                status="RETRY",
                emitted_tickets=[ticket],
                error="Dirty→clean governance gate failed",
            )

        return StepResult(status="OK")

    def _materialize_snapshots(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        evidence_root: Path,
        registry: Any,
    ) -> None:
        """Persist pins/graph snapshots from the promoted registry."""
        manifest_hash = self._expected_manifest_hash(bundle) or bundle.diff.content_hash

        pins_payload = {
            "schema_version": "1",
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "file_hash": manifest_hash,
            "pins": [pin.model_dump() for pin in registry.pin_functions],
        }
        pins_payload_json = json.dumps(pins_payload, indent=2)
        bundle.pins_snapshot.path = _write_iteration_json(
            bundle,
            evidence_root,
            "pins.snapshot.json",
            pins_payload,
        )
        bundle.pins_snapshot.schema_version = pins_payload["schema_version"]
        bundle.pins_snapshot.snapshot_hash = _hash_text(pins_payload_json)

        graph_edges = []
        for edge in registry.import_edges:
            projection_type = str(edge.projection_type)
            graph_edges.append(
                {
                    "src": edge.pin_func_id,
                    "dst": edge.arch_location,
                    "arch_file_path": edge.arch_file_path,
                    "arch_line": edge.arch_line,
                    "projection_type": projection_type,
                    "signal_type": self._canonical_edge_signal(projection_type),
                    "weight": edge.confidence,
                }
            )
        graph_payload = {
            "schema_version": "1",
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "file_hash": manifest_hash,
            "edges": graph_edges,
        }
        graph_payload_json = json.dumps(graph_payload, indent=2)
        bundle.graph_snapshot.path = _write_iteration_json(
            bundle,
            evidence_root,
            "graph.snapshot.json",
            graph_payload,
        )
        bundle.graph_snapshot.schema_version = graph_payload["schema_version"]
        bundle.graph_snapshot.snapshot_hash = _hash_text(graph_payload_json)

    def _emit_refinement_artifact(self, ctx: SliceContext, bundle: EvidenceBundle) -> None:
        """Run cohesion detector over promoted graph evidence and persist output."""
        from spec_manager.analysis.adjacency.graph import (
            AdjacencyGraph,
            EdgeSignal,
            NodeInfo,
            SignalType,
        )
        from spec_manager.cohesion.detector import GroupingUnit, detect_all

        if not bundle.graph_snapshot.path:
            return

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)
        graph_path = iteration_dir / bundle.graph_snapshot.path
        if not graph_path.exists():
            return

        try:
            payload = json.loads(graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        edges = payload.get("edges", [])
        if not isinstance(edges, list):
            edges = []

        graph = AdjacencyGraph()
        units_by_file: dict[str, set[str]] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("src", "")).strip()
            dst = str(edge.get("dst", "")).strip()
            if not src or not dst:
                continue

            signal_raw = self._canonical_edge_signal(edge.get("signal_type"))
            signal_map = {
                "CALL": SignalType.CALL,
                "STORE_TOUCH": SignalType.STORE_TOUCH,
                "EVENT": SignalType.EVENT,
                "REFERENCE": SignalType.REFERENCE,
            }
            signal_type = signal_map.get(signal_raw, SignalType.REFERENCE)
            weight_raw = edge.get("weight", 1.0)
            weight = float(weight_raw) if isinstance(weight_raw, int | float) else 1.0

            graph.add_node(src, NodeInfo(node_id=src, node_type="pin"))
            graph.add_node(
                dst,
                NodeInfo(
                    node_id=dst,
                    node_type="architecture",
                    file_path=edge.get("arch_file_path"),
                ),
            )
            graph.add_edge(
                src,
                dst,
                EdgeSignal(
                    signal_type=signal_type,
                    weight=weight,
                    details={"projection_type": edge.get("projection_type", "")},
                ),
            )

            grouping_key = str(edge.get("arch_file_path") or "slice")
            units = units_by_file.setdefault(grouping_key, set())
            units.add(src)
            units.add(dst)

        grouping_units = [
            GroupingUnit(unit_id=unit_id, name=unit_id, entity_ids=entity_ids)
            for unit_id, entity_ids in sorted(units_by_file.items())
        ]
        if not grouping_units:
            grouping_units = [
                GroupingUnit(unit_id="slice", name="slice", entity_ids=set(graph.nodes()))
            ]

        issues = detect_all(graph, grouping_units)
        bundle.refinement.path = _write_iteration_json(
            bundle,
            evidence_root,
            "refinement.json",
            {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "issue_count": len(issues),
                "issues": [asdict(issue) for issue in issues],
            },
        )

    @staticmethod
    def _expected_manifest_hash(bundle: EvidenceBundle) -> str:
        """Compute stable manifest hash from manifest entries."""
        if not bundle.manifest.files:
            return ""
        material = "\n".join(
            f"{item.get('path', '')}:{item.get('sha256', '')}"
            for item in sorted(bundle.manifest.files, key=lambda x: x.get("path", ""))
        )
        return _hash_text(material) if material else ""

    def _validate_hash_consistency(self, bundle: EvidenceBundle) -> list[str]:
        """Validate that evidence references match manifest hash state."""
        failures: list[str] = []
        if not bundle.manifest.files:
            failures.append("Manifest missing files/hash entries")
            return failures

        expected = self._expected_manifest_hash(bundle)
        if not expected:
            failures.append("Manifest hash could not be computed")
            return failures

        recorded = bundle.diff.content_hash
        if recorded and recorded != expected:
            failures.append("Diff content hash does not match manifest hash")

        if not bundle.pins_snapshot.path:
            failures.append("Pin snapshot artifact missing")
        if not bundle.pins_snapshot.snapshot_hash:
            failures.append("Pin snapshot hash missing")

        if not bundle.graph_snapshot.path:
            failures.append("Graph snapshot artifact missing")
        if not bundle.graph_snapshot.snapshot_hash:
            failures.append("Graph snapshot hash missing")

        return failures

    @staticmethod
    def _validate_gap_spans(bundle: EvidenceBundle) -> list[str]:
        """Ensure each open gap carries explicit location/span metadata."""
        failures: list[str] = []
        for idx, gap in enumerate(bundle.gaps.open_gaps):
            if not isinstance(gap, dict):
                failures.append(f"Gap {idx} is not a dict record")
                continue
            span = gap.get("span", {}) or {}
            location = gap.get("location", {}) or {}
            if not isinstance(span, dict) or not isinstance(location, dict):
                failures.append(f"Gap {idx} has malformed span/location")
                continue
            if "file" not in location:
                failures.append(f"Gap {idx} missing location.file")
        return failures

    def _validate_graph_evidence(self, bundle: EvidenceBundle) -> list[str]:
        """Validate graph delta/snapshot consistency and signal taxonomy."""
        failures: list[str] = []
        allowed = {"CALL", "STORE_TOUCH", "EVENT", "REFERENCE"}

        if bundle.implementation.edge_proposals and not bundle.graph_deltas:
            failures.append("Edge proposals exist but graph delta artifacts are missing")

        for edge in bundle.implementation.edge_proposals or []:
            signal = self._canonical_edge_signal(edge.get("signal_type"))
            if signal not in allowed:
                failures.append(f"Unsupported edge signal type: {edge.get('signal_type')}")

        for delta in bundle.graph_deltas or []:
            if not delta.path:
                failures.append("Graph delta missing artifact path")
            if delta.delta_type not in {"pin_proposal", "edge_proposal", "merge"}:
                failures.append(f"Unknown graph delta type: {delta.delta_type}")

        return failures

    @staticmethod
    def _to_gate(
        gate_id: str, passed: bool, summary: str, required_change_type: str
    ) -> dict[str, Any]:
        """Build a gate entry for EvidenceBundle gates report."""
        return {
            "gate_id": gate_id,
            "passed": passed,
            "summary": summary,
            "required_change_type": required_change_type,
        }

    @staticmethod
    def _l2_gate_required_change_type(gate_id: str) -> str:
        """Classify L2 gate failure by fix authority."""
        behavior_change_gates = {
            "no_remaining_comments",
            "no_stub_functions",
            "call_graph_connected",
            "store_monogamy",
            "all_tests_pass",
        }
        return "behavior_change" if gate_id in behavior_change_gates else "wiring_only"

    @staticmethod
    def _load_l2_architecture_graph(ctx: SliceContext, bundle: EvidenceBundle) -> dict[str, Any]:
        """Load architecture graph payload emitted by L2 ANALYZE."""
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)
        for entry in bundle.source_index.entries or []:
            if not isinstance(entry, dict):
                continue
            analysis = entry.get("analysis", {}) or {}
            if not isinstance(analysis, dict):
                continue
            if analysis.get("type") != "l2_architecture_graph":
                continue
            graph_path = str(analysis.get("graph_path") or entry.get("path") or "").strip()
            if not graph_path:
                continue
            payload = _read_json_file(iteration_dir / graph_path)
            if isinstance(payload, dict):
                return payload
        return {}

    @staticmethod
    def _l2_finding_to_gap(finding: dict[str, Any]) -> dict[str, Any]:
        """Project L2 reviewer finding into gap schema for next planning pass."""
        location = finding.get("location", {}) or {}
        file_path = str(location.get("file") or finding.get("file") or "").strip()
        anchor = str(
            finding.get("anchor") or location.get("symbol") or finding.get("reviewer") or ""
        ).strip()
        description = str(finding.get("description") or finding.get("evidence") or "").strip()
        expected = str(finding.get("expected") or finding.get("suggested_fix") or "").strip()
        return _normalize_gap_record(
            {
                "kind": str(finding.get("kind") or "l2_review_finding"),
                "component_id": str(finding.get("component_id") or "").strip(),
                "file": file_path,
                "anchor": anchor,
                "description": description,
                "expected": expected,
                "severity": str(finding.get("severity") or "MAJOR").upper(),
                "required_change_type": str(
                    finding.get("required_change_type") or "wiring_only"
                ).strip(),
                "location": location if isinstance(location, dict) else {"file": file_path},
            }
        )

    def _run_l2_review_pack(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        architecture_graph: dict[str, Any],
        arch_artifacts: list[dict[str, str]],
        component_manifest: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run L2 reviewer pack during PROMOTE and return normalized findings."""
        import json

        from spec_manager.orchestration.pattern_library import PatternLibrary

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        pattern_lib = PatternLibrary(
            library_path=GapExplorationStep._pattern_library_path(workspace)
        )
        strategy_candidates_recorded = 0
        findings_out: list[dict[str, Any]] = []

        review_payload = {
            "slice_id": ctx.slice_id,
            "layer": ctx.layer,
            "graph_stats": architecture_graph.get("stats", {}),
            "graph_nodes": architecture_graph.get("nodes", [])[:150],
            "graph_edges": architecture_graph.get("edges", [])[:300],
            "pins_snapshot": {
                "path": bundle.pins_snapshot.path,
                "hash": bundle.pins_snapshot.snapshot_hash,
            },
            "graph_snapshot": {
                "path": bundle.graph_snapshot.path,
                "hash": bundle.graph_snapshot.snapshot_hash,
            },
            "component_manifest": component_manifest,
            "arch_artifacts": arch_artifacts,
        }

        for reviewer in L2_REVIEW_PACK:
            pattern_section = pattern_lib.get_review_prompt_section(reviewer.dimension)
            reviewer_prompt = (
                "## TASK\n"
                f"Review this L2 architecture slice for {reviewer.dimension}.\n"
                f"Objective: {reviewer.objective}\n"
                "You are running in PROMOTE: judge post-implementation readiness.\n"
                "Return only unresolved findings.\n\n"
                "For each finding include:\n"
                "- severity (BLOCKER/MAJOR/MINOR)\n"
                "- required_change_type (wiring_only/behavior_change)\n"
                "- description\n"
                "- expected\n"
                "- location {file, symbol?, start_line?, end_line?}\n\n"
                f"{pattern_section}\n\n"
                "## EVIDENCE\n"
                f"{json.dumps(review_payload, indent=2)}\n\n"
                'Return JSON: {"findings": [...]}.\n'
            )

            try:
                from spec_manager.core.agent_utils import run_agent
                from spec_manager.core.json_extraction import _extract_json_payload
                from spec_manager.refinement.formats import _strip_code_fences

                output = run_agent(
                    agent_name=reviewer.agent_name,
                    prompt=reviewer_prompt,
                    workspace=workspace,
                )
                cleaned = _strip_code_fences(output)
                payload = json.loads(_extract_json_payload(cleaned))
                findings = [item for item in payload.get("findings", []) if isinstance(item, dict)]
                strategy_candidates_recorded += GapExplorationStep._record_strategy_candidates(
                    pattern_lib,
                    dimension=reviewer.dimension,
                    findings=findings,
                )
                for finding in findings:
                    location = finding.get("location", {}) or {}
                    file_path = str(location.get("file") or finding.get("file") or "").strip()
                    findings_out.append(
                        {
                            "kind": f"l2_{reviewer.dimension.lower()}_finding",
                            "reviewer": reviewer.reviewer_id,
                            "agent_name": reviewer.agent_name,
                            "dimension": reviewer.dimension,
                            "component_id": str(
                                finding.get("component_id") or location.get("symbol") or ""
                            ).strip(),
                            "anchor": str(
                                location.get("symbol") or finding.get("anchor") or ""
                            ).strip(),
                            "file": file_path,
                            "location": location
                            if isinstance(location, dict)
                            else {"file": file_path},
                            "description": str(
                                finding.get("description") or finding.get("evidence") or ""
                            ).strip(),
                            "expected": str(
                                finding.get("expected") or finding.get("suggested_fix") or ""
                            ).strip(),
                            "suggested_fix": str(finding.get("suggested_fix") or "").strip(),
                            "severity": str(finding.get("severity", "MINOR")).upper(),
                            "required_change_type": str(
                                finding.get(
                                    "required_change_type", reviewer.default_required_change_type
                                )
                            ).strip(),
                        }
                    )
            except Exception as exc:
                findings_out.append(
                    {
                        "kind": "l2_reviewer_execution_failure",
                        "reviewer": reviewer.reviewer_id,
                        "agent_name": reviewer.agent_name,
                        "dimension": reviewer.dimension,
                        "component_id": "",
                        "anchor": reviewer.reviewer_id,
                        "file": "",
                        "location": {"file": ""},
                        "description": (
                            f"Reviewer execution failed for {reviewer.reviewer_id}: {exc}"
                        ),
                        "expected": (
                            "Reviewer must execute to evaluate architecture continuity readiness."
                        ),
                        "severity": "BLOCKER",
                        "required_change_type": reviewer.default_required_change_type,
                    }
                )

        if strategy_candidates_recorded:
            try:
                pattern_lib.save()
            except Exception as exc:
                logger.warning("Failed to persist strategy candidates: %s", exc, exc_info=True)

        return findings_out

    def _run_l3_quality_review_pack(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        slice_root: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Run configured L3 quality reviewers on post-implementation code."""
        import json

        from spec_manager.orchestration.pattern_library import PatternLibrary

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        pattern_lib = PatternLibrary(
            library_path=GapExplorationStep._pattern_library_path(workspace)
        )
        strategy_candidates_recorded = 0
        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""
        code_files, candidate_count = GapExplorationStep._load_review_files_from_manifest(
            slice_root,
            bundle,
            target_stem=target_stem,
        )
        reviewers = _configured_l3_review_pack(
            ctx.config if isinstance(ctx.config, dict) else None,
            include_diff_impact=False,
        )
        findings_out: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []

        if not code_files and candidate_count > 0:
            findings_out.append(
                {
                    "kind": "quality_review_input_unavailable",
                    "file": "",
                    "reviewer": "l3-review-pack",
                    "agent_name": "",
                    "dimension": "QUALITY",
                    "description": "L3 review inputs declared in manifest could not be loaded.",
                    "severity": "BLOCKER",
                    "category": "review_execution",
                    "required_change_type": "refactor_only",
                    "span": {},
                    "location": {"file": ""},
                }
            )
            return findings_out, receipts

        for file_path, code_content in code_files.items():
            file_hash = _hash_text(code_content)
            for reviewer in reviewers:
                pattern_section = pattern_lib.get_review_prompt_section(reviewer.dimension)
                reviewer_prompt = (
                    "## TASK\n"
                    "Review the following code for quality issues.\n"
                    "Execution stage: PROMOTE (post-implementation quality closure).\n"
                    f"Objective: {reviewer.objective}\n"
                    "Return only unresolved findings.\n"
                    "For each finding include: severity (BLOCKER/MAJOR/MINOR), "
                    "category (style/maintainability/logic/architecture/drift), "
                    "required_change_type (refactor_only/wiring_only/behavior_change), "
                    "description, "
                    "location {file,start_line,end_line,start_col,end_col}.\n"
                    'Return JSON: {"findings": [...]}.\n\n'
                    f"{pattern_section}\n\n"
                    f"File: {file_path}\n\n"
                    f"```\n{code_content[:4000]}\n```\n"
                )
                try:
                    from spec_manager.core.agent_utils import run_agent
                    from spec_manager.core.json_extraction import _extract_json_payload
                    from spec_manager.refinement.formats import _strip_code_fences

                    output = run_agent(
                        agent_name=reviewer.agent_name,
                        prompt=reviewer_prompt,
                        workspace=workspace,
                    )
                    cleaned = _strip_code_fences(output)
                    payload = json.loads(_extract_json_payload(cleaned))
                    findings = [
                        item for item in payload.get("findings", []) if isinstance(item, dict)
                    ]
                    strategy_candidates_recorded += GapExplorationStep._record_strategy_candidates(
                        pattern_lib,
                        dimension=reviewer.dimension,
                        findings=findings,
                    )
                    for finding in findings:
                        location = finding.get("location", {}) or {}
                        span = _location_span(
                            start_line=location.get("start_line"),
                            end_line=location.get("end_line"),
                            start_col=location.get("start_col"),
                            end_col=location.get("end_col"),
                        )
                        findings_out.append(
                            {
                                "kind": "quality_finding",
                                "file": file_path,
                                "reviewer": reviewer.reviewer_id,
                                "agent_name": reviewer.agent_name,
                                "dimension": reviewer.dimension,
                                "description": finding.get("description", ""),
                                "severity": str(finding.get("severity", "MINOR")).upper(),
                                "category": finding.get("category", reviewer.default_category),
                                "required_change_type": finding.get(
                                    "required_change_type",
                                    reviewer.default_required_change_type,
                                ),
                                "span": span,
                                "location": {"file": file_path, **span},
                            }
                        )
                    receipts.append(
                        _normalize_quality_receipt(
                            {
                                "reviewer_id": reviewer.reviewer_id,
                                "agent_name": reviewer.agent_name,
                                "dimension": reviewer.dimension,
                                "file": file_path,
                                "file_hash": file_hash,
                                "status": "FAIL" if findings else "PASS",
                                "finding_count": len(findings),
                                "findings": findings,
                                "stage": "PROMOTE",
                                "recorded_at": _now_iso(),
                            }
                        )
                    )
                except Exception as exc:
                    findings_out.append(
                        {
                            "kind": "quality_finding",
                            "file": file_path,
                            "reviewer": reviewer.reviewer_id,
                            "agent_name": reviewer.agent_name,
                            "dimension": reviewer.dimension,
                            "description": (
                                f"Reviewer execution failed for {reviewer.reviewer_id}: {exc}"
                            ),
                            "severity": "BLOCKER",
                            "category": "review_execution",
                            "required_change_type": "refactor_only",
                            "span": {},
                            "location": {"file": file_path},
                        }
                    )
                    receipts.append(
                        _normalize_quality_receipt(
                            {
                                "reviewer_id": reviewer.reviewer_id,
                                "agent_name": reviewer.agent_name,
                                "dimension": reviewer.dimension,
                                "file": file_path,
                                "file_hash": file_hash,
                                "status": "FAIL",
                                "finding_count": 1,
                                "findings": [
                                    {
                                        "description": (
                                            f"Reviewer execution failed for "
                                            f"{reviewer.reviewer_id}: {exc}"
                                        ),
                                        "severity": "BLOCKER",
                                        "category": "review_execution",
                                        "required_change_type": "refactor_only",
                                    }
                                ],
                                "stage": "PROMOTE",
                                "recorded_at": _now_iso(),
                            }
                        )
                    )

        if strategy_candidates_recorded:
            try:
                pattern_lib.save()
            except Exception as exc:
                logger.warning("Failed to persist strategy candidates: %s", exc, exc_info=True)

        return findings_out, receipts

    def _run_l3_diff_impact_classifier(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        slice_root: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Classify post-refactor diff impact for demotion routing."""
        import json

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        reviewers = _configured_l3_review_pack(
            ctx.config if isinstance(ctx.config, dict) else None,
            include_diff_impact=True,
        )
        classifier = next((r for r in reviewers if r.dimension == "DIFF_IMPACT"), None)
        if classifier is None:
            return [], []

        target_stem = ctx.slice_id.removeprefix("cq-") if ctx.slice_id.startswith("cq-") else ""
        code_files, _ = GapExplorationStep._load_review_files_from_manifest(
            slice_root,
            bundle,
            target_stem=target_stem,
        )
        changed_set = {
            str(path).strip() for path in (bundle.diff.changed_files or []) if str(path).strip()
        }
        if changed_set:
            excerpt_order = [path for path in code_files if path in changed_set]
        else:
            excerpt_order = list(code_files)
        excerpts = [
            {"file": path, "content": code_files[path][:2500]}
            for path in excerpt_order[:6]
            if path in code_files
        ]
        analysis_summary = next(
            (
                entry.get("analysis", {})
                for entry in (bundle.source_index.entries or [])
                if isinstance(entry, dict) and entry.get("path") == "__l3_analysis_summary__"
            ),
            {},
        )
        prompt = (
            "## TASK\n"
            "Act as an L3 Diff-Impact Classifier.\n"
            "Classify whether the post-refactor diff is logic-affecting or boundary-affecting.\n"
            "Only return findings that require demotion routing.\n"
            "impact_type meanings:\n"
            "- logic: observable behavior or semantic logic changed (demote L1)\n"
            "- boundary: architectural boundary/wiring changed (demote L2)\n"
            "- none: behavior-preserving refactor\n"
            'Return JSON: {"findings": [{"file": "...", "impact_type": "logic"|"boundary"|"none", '
            '"severity": "BLOCKER"|"MAJOR"|"MINOR", "description": "...", "location": {...}}]}.\n\n'
            "## EVIDENCE\n"
            f"changed_files: {json.dumps(list(changed_set), indent=2)}\n"
            f"plan_intentions: {json.dumps(bundle.plan.intentions[:20], indent=2)}\n"
            f"applied_edits: {json.dumps(bundle.implementation.applied_edits[:40], indent=2)}\n"
            f"edge_proposals: {json.dumps(bundle.implementation.edge_proposals[:40], indent=2)}\n"
            f"analysis_summary: {json.dumps(analysis_summary, indent=2)}\n"
            f"code_excerpts: {json.dumps(excerpts, indent=2)}\n"
        )

        findings_out: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        try:
            from spec_manager.core.agent_utils import run_agent
            from spec_manager.core.json_extraction import _extract_json_payload
            from spec_manager.refinement.formats import _strip_code_fences

            output = run_agent(
                agent_name=classifier.agent_name,
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            payload = json.loads(_extract_json_payload(cleaned))
            findings = [item for item in payload.get("findings", []) if isinstance(item, dict)]
            actionable_count = 0
            for item in findings:
                impact_type = str(item.get("impact_type", "none")).strip().lower()
                if impact_type not in {"logic", "boundary", "none"}:
                    impact_type = "none"
                if impact_type == "none":
                    continue
                actionable_count += 1
                file_path = str(item.get("file", "")).strip()
                location = item.get("location", {}) or {}
                span = _location_span(
                    start_line=location.get("start_line"),
                    end_line=location.get("end_line"),
                    start_col=location.get("start_col"),
                    end_col=location.get("end_col"),
                )
                findings_out.append(
                    {
                        "kind": "diff_impact_finding",
                        "file": file_path,
                        "reviewer": classifier.reviewer_id,
                        "agent_name": classifier.agent_name,
                        "dimension": classifier.dimension,
                        "impact_type": impact_type,
                        "description": str(item.get("description", "")).strip(),
                        "severity": str(item.get("severity", "MAJOR")).upper(),
                        "category": "diff-impact",
                        "required_change_type": (
                            "behavior_change" if impact_type == "logic" else "wiring_only"
                        ),
                        "span": span,
                        "location": {"file": file_path, **span},
                    }
                )
            receipts.append(
                _normalize_quality_receipt(
                    {
                        "reviewer_id": classifier.reviewer_id,
                        "agent_name": classifier.agent_name,
                        "dimension": classifier.dimension,
                        "file": "__diff__",
                        "file_hash": bundle.diff.content_hash,
                        "status": "FAIL" if actionable_count else "PASS",
                        "finding_count": actionable_count,
                        "findings": findings_out,
                        "stage": "PROMOTE",
                        "recorded_at": _now_iso(),
                    }
                )
            )
        except Exception as exc:
            findings_out.append(
                {
                    "kind": "diff_impact_finding",
                    "file": "",
                    "reviewer": classifier.reviewer_id,
                    "agent_name": classifier.agent_name,
                    "dimension": classifier.dimension,
                    "impact_type": "unknown",
                    "description": f"Diff-impact classifier execution failed: {exc}",
                    "severity": "BLOCKER",
                    "category": "review_execution",
                    "required_change_type": "refactor_only",
                    "span": {},
                    "location": {"file": ""},
                }
            )
            receipts.append(
                _normalize_quality_receipt(
                    {
                        "reviewer_id": classifier.reviewer_id,
                        "agent_name": classifier.agent_name,
                        "dimension": classifier.dimension,
                        "file": "__diff__",
                        "file_hash": bundle.diff.content_hash,
                        "status": "FAIL",
                        "finding_count": 1,
                        "findings": findings_out,
                        "stage": "PROMOTE",
                        "recorded_at": _now_iso(),
                    }
                )
            )

        return findings_out, receipts

    def _promote_l1(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L1: verify evidence transaction integrity."""
        failures = self._validate_hash_consistency(bundle)
        failures.extend(self._validate_gap_spans(bundle))
        failures.extend(self._validate_graph_evidence(bundle))

        bundle.gates.gates = [
            self._to_gate(
                "EVIDENCE_HASH_ALIGNMENT",
                not any("hash" in f.lower() or "manifest" in f.lower() for f in failures),
                "; ".join(f for f in failures if "hash" in f.lower() or "manifest" in f.lower())
                or "Manifest and snapshot hashes are aligned",
                "refactor_only",
            ),
            self._to_gate(
                "GAP_SPAN_COMPLETENESS",
                not any("gap" in f.lower() for f in failures),
                "; ".join(f for f in failures if "gap" in f.lower())
                or "Gap inventory includes location metadata",
                "behavior_change",
            ),
            self._to_gate(
                "GRAPH_EVIDENCE_COMPLETENESS",
                not any("graph" in f.lower() or "edge" in f.lower() for f in failures),
                "; ".join(f for f in failures if "graph" in f.lower() or "edge" in f.lower())
                or "Graph evidence artifacts are complete",
                "wiring_only",
            ),
        ]
        bundle.gates.path = "gates.report.json"

        if failures:
            return StepResult(
                status="RETRY",
                emitted_tickets=[
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="GATE_FAILURE",
                        gate="EVIDENCE_INTEGRITY",
                        target_layer="L1",
                        severity="BLOCKER",
                        diagnosis="; ".join(failures),
                    )
                ],
                error="L1 evidence integrity gate failed",
            )
        return StepResult(status="OK")

    def _promote_l2(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L2: run canonical promotion gates with snapshot adapters."""
        from spec_manager.compliance.promotion.config import PromotionGateConfig
        from spec_manager.compliance.promotion.orchestrator import LayerPromotionGate
        from spec_manager.schemas.pin_functions import PinFunctionRegistry

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root:
            return StepResult(status="RETRY", error="L2 PROMOTE missing slice root")

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)

        pins_snapshot: dict[str, Any] = {}
        graph_snapshot: dict[str, Any] = {}
        try:
            if bundle.pins_snapshot.path:
                pins_snapshot = json.loads(
                    (iteration_dir / bundle.pins_snapshot.path).read_text(encoding="utf-8")
                )
            if bundle.graph_snapshot.path:
                graph_snapshot = json.loads(
                    (iteration_dir / bundle.graph_snapshot.path).read_text(encoding="utf-8")
                )
        except (OSError, json.JSONDecodeError):
            pins_snapshot = {}
            graph_snapshot = {}

        registry_path = slice_root / ".spec" / "pin_registry.json"
        pin_registry: PinFunctionRegistry | None = None
        if registry_path.exists():
            try:
                pin_registry = PinFunctionRegistry.model_validate_json(
                    registry_path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                logger.debug("Failed to load pin registry for L2 gates: %s", exc)

        config = PromotionGateConfig.default()
        config.project_root = str(slice_root)

        gate = LayerPromotionGate(
            config=config,
            pin_registry=pin_registry,
            graph_snapshot=graph_snapshot,
            pins_snapshot=pins_snapshot,
        )
        report = gate.run_all_checks()

        bundle.gates.gates = [
            self._to_gate(
                gate_id=result.gate_id,
                passed=bool(result.passed),
                summary=result.summary,
                required_change_type=self._l2_gate_required_change_type(result.gate_id),
            )
            for result in report.gate_results
        ]
        bundle.gates.path = "gates.report.json"

        architecture_graph = self._load_l2_architecture_graph(ctx, bundle)
        arch_files = [
            str(path).strip()
            for path in architecture_graph.get("arch_files", [])
            if isinstance(path, str) and str(path).strip()
        ]
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        arch_artifacts = GapExplorationStep._load_arch_artifacts(workspace, arch_files)
        component_manifest = _load_run_component_manifest(workspace, bundle.run_id)
        review_findings = self._run_l2_review_pack(
            ctx=ctx,
            bundle=bundle,
            architecture_graph=architecture_graph,
            arch_artifacts=arch_artifacts,
            component_manifest=component_manifest,
        )

        findings_by_reviewer: dict[str, list[dict[str, Any]]] = {}
        for finding in review_findings:
            reviewer_id = str(finding.get("reviewer", "reviewer")).strip() or "reviewer"
            findings_by_reviewer.setdefault(reviewer_id, []).append(finding)

        for reviewer in L2_REVIEW_PACK:
            reviewer_findings = findings_by_reviewer.get(reviewer.reviewer_id, [])
            if not reviewer_findings:
                bundle.gates.gates.append(
                    self._to_gate(
                        gate_id=f"l2_review_{reviewer.dimension.lower()}",
                        passed=True,
                        summary=f"{reviewer.reviewer_id}: no unresolved findings",
                        required_change_type=reviewer.default_required_change_type,
                    )
                )
                continue

            required_change = "wiring_only"
            if any(
                str(item.get("required_change_type", "")).strip() == "behavior_change"
                for item in reviewer_findings
            ):
                required_change = "behavior_change"
            summaries = [
                str(item.get("description") or item.get("expected") or "").strip()
                for item in reviewer_findings[:3]
            ]
            bundle.gates.gates.append(
                self._to_gate(
                    gate_id=f"l2_review_{reviewer.dimension.lower()}",
                    passed=False,
                    summary="; ".join(summary for summary in summaries if summary)
                    or f"{len(reviewer_findings)} unresolved findings",
                    required_change_type=required_change,
                )
            )

        if review_findings:
            normalized_review_gaps = [self._l2_finding_to_gap(item) for item in review_findings]
            bundle.gaps.open_gaps = normalized_review_gaps

        failed_gates = [gate for gate in bundle.gates.gates if not gate.get("passed")]
        if not failed_gates:
            return StepResult(status="OK")

        current_layer = self._current_layer_literal(ctx.layer)
        behavior_change_failures = [
            gate for gate in failed_gates if gate.get("required_change_type") == "behavior_change"
        ]
        governance_failures = [
            gate
            for gate in failed_gates
            if "governance" in str(gate.get("gate_id", "")).strip().lower()
        ]
        tickets = [
            DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="GATE_FAILURE",
                category="logic",
                gate=str(gate.get("gate_id", "")),
                origin_layer=current_layer,
                target_layer="L1",
                severity="BLOCKER",
                diagnosis=str(gate.get("summary", "L2 behavior-change gate failed")),
            )
            for gate in behavior_change_failures
        ]
        for gate in governance_failures:
            tickets.append(
                DemotionTicket(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    source="GATE_FAILURE",
                    category="governance",
                    gate=str(gate.get("gate_id", "")),
                    origin_layer=current_layer,
                    target_layer=current_layer,
                    severity="BLOCKER",
                    diagnosis=str(gate.get("summary", "L2 governance gate failed")),
                )
            )

        wiring_failures = len(failed_gates) - len(behavior_change_failures)
        error_parts = []
        if wiring_failures:
            error_parts.append(f"{wiring_failures} wiring-only gate(s) require L2 retry")
        if behavior_change_failures:
            error_parts.append(
                f"{len(behavior_change_failures)} gate(s) require L1 behavior-change demotion"
            )
        if governance_failures:
            error_parts.append(
                f"{len(governance_failures)} governance gate(s) require governance remediation"
            )

        return StepResult(
            status="RETRY",
            emitted_tickets=tickets,
            error="; ".join(error_parts) if error_parts else "L2 promotion gates failed",
        )

    def _promote_l3(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L3: rerun quality reviewers and diff-impact classifier for closure."""
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            return StepResult(status="RETRY", error="L3 PROMOTE missing slice root")

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        quality_findings, quality_receipts = self._run_l3_quality_review_pack(
            ctx=ctx,
            bundle=bundle,
            slice_root=slice_root,
        )
        diff_impact_findings, diff_receipts = self._run_l3_diff_impact_classifier(
            ctx=ctx,
            bundle=bundle,
            slice_root=slice_root,
        )
        all_open_gaps = quality_findings + diff_impact_findings
        bundle.gaps.open_gaps = [_normalize_gap_record(gap) for gap in all_open_gaps]
        bundle.gaps.path = "gaps.json"

        existing_receipts = _load_iteration_quality_receipts(
            evidence_root=evidence_root,
            bundle=bundle,
        )
        latest_receipts = _latest_quality_receipts_by_key(existing_receipts)
        for receipt in quality_receipts + diff_receipts:
            normalized = _normalize_quality_receipt(receipt)
            latest_receipts[_quality_receipt_key(normalized)] = normalized
        _write_iteration_quality_receipts(
            ctx=ctx,
            bundle=bundle,
            evidence_root=evidence_root,
            stage="PROMOTE",
            receipts=list(latest_receipts.values()),
        )

        actionable_diff = [
            finding
            for finding in diff_impact_findings
            if str(finding.get("impact_type", "")).strip().lower() in {"logic", "boundary"}
        ]
        unresolved_diff = [
            finding
            for finding in diff_impact_findings
            if str(finding.get("impact_type", "")).strip().lower() not in {"logic", "boundary"}
        ]

        bundle.gates.gates = [
            self._to_gate(
                "ALL_QUALITY_REVIEWERS_PASS",
                not quality_findings,
                "All post-implementation quality reviewers reported PASS"
                if not quality_findings
                else f"{len(quality_findings)} post-implementation quality finding(s) remain open",
                "refactor_only",
            ),
            self._to_gate(
                "DIFF_IMPACT_PASS",
                not actionable_diff and not unresolved_diff,
                "Diff-impact classifier reports behavior-preserving, boundary-preserving refactor"
                if not actionable_diff and not unresolved_diff
                else (
                    f"{len(actionable_diff)} diff-impact finding(s) require demotion"
                    if actionable_diff
                    else f"{len(unresolved_diff)} diff-impact finding(s) unresolved"
                ),
                "behavior_change",
            ),
        ]
        bundle.gates.path = "gates.report.json"

        if quality_findings or actionable_diff or unresolved_diff:
            tickets: list[DemotionTicket] = []
            for finding in quality_findings:
                category = str(finding.get("category", "style")).strip().lower()
                if category in {"logic", "correctness"}:
                    tickets.append(
                        DemotionTicket(
                            run_id=ctx.run_id,
                            slice_id=ctx.slice_id,
                            source="REVIEW",
                            origin_layer="L3",
                            target_layer="L1",
                            severity=str(finding.get("severity", "MAJOR")).upper(),
                            diagnosis=str(
                                finding.get("description", "Quality finding requires logic change")
                            ),
                            failing_files=[finding["file"]] if finding.get("file") else [],
                        )
                    )
                elif category == "architecture":
                    tickets.append(
                        DemotionTicket(
                            run_id=ctx.run_id,
                            slice_id=ctx.slice_id,
                            source="REVIEW",
                            origin_layer="L3",
                            target_layer="L2",
                            severity=str(finding.get("severity", "MAJOR")).upper(),
                            diagnosis=str(
                                finding.get(
                                    "description", "Quality finding requires architecture change"
                                )
                            ),
                            failing_files=[finding["file"]] if finding.get("file") else [],
                        )
                    )
            for finding in actionable_diff:
                impact_type = str(finding.get("impact_type", "")).strip().lower()
                target = "L1" if impact_type == "logic" else "L2"
                severity = str(finding.get("severity", "BLOCKER")).upper()
                if severity not in {"BLOCKER", "MAJOR", "MINOR"}:
                    severity = "BLOCKER" if target == "L1" else "MAJOR"
                tickets.append(
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="DIFF_IMPACT",
                        origin_layer="L3",
                        target_layer=target,
                        severity=severity,
                        diagnosis=str(
                            finding.get(
                                "description",
                                "Diff-impact classifier requires lower-layer handling.",
                            )
                        ),
                        failing_files=[finding["file"]] if finding.get("file") else [],
                    )
                )

            if tickets:
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    error=(
                        f"L3 promote unresolved findings: quality={len(quality_findings)} "
                        f"diff_impact={len(actionable_diff)} demotions={len(tickets)}"
                    ),
                )
            return StepResult(
                status="RETRY",
                error=(
                    f"L3 promote unresolved findings: quality={len(quality_findings)} "
                    f"diff_impact_unresolved={len(unresolved_diff)}"
                ),
            )

        failures = self._validate_hash_consistency(bundle)
        failures.extend(self._validate_gap_spans(bundle))

        behavior_change_gaps = [
            g
            for g in bundle.implementation.gap_inventory
            if g.get("required_change_type") == "behavior_change"
        ]
        wiring_edges = [
            e
            for e in bundle.implementation.edge_proposals
            if self._canonical_edge_signal(e.get("signal_type")) != "REFERENCE"
        ]

        bundle.gates.gates.extend(
            [
                self._to_gate(
                    "NO_LOGIC_CHANGE_EVIDENCE",
                    not behavior_change_gaps,
                    "No behavior-change gaps in implementation evidence"
                    if not behavior_change_gaps
                    else f"{len(behavior_change_gaps)} behavior-change gap(s) reported",
                    "behavior_change",
                ),
                self._to_gate(
                    "NO_ARCH_BOUNDARY_VIOLATIONS_EVIDENCE",
                    not wiring_edges,
                    "No architecture wiring edges emitted in L3"
                    if not wiring_edges
                    else f"{len(wiring_edges)} architecture edge(s) emitted in L3",
                    "wiring_only",
                ),
                self._to_gate(
                    "EVIDENCE_HASH_ALIGNMENT",
                    not failures,
                    "; ".join(failures) if failures else "Evidence hashes align with current text",
                    "refactor_only",
                ),
            ]
        )

        failed = [gate for gate in bundle.gates.gates if not gate["passed"]]
        if failed:
            tickets = []
            for gate in failed:
                target = "L1" if gate["required_change_type"] == "behavior_change" else "L2"
                if gate["required_change_type"] == "refactor_only":
                    target = "L3"
                tickets.append(
                    DemotionTicket(
                        run_id=ctx.run_id,
                        slice_id=ctx.slice_id,
                        source="GATE_FAILURE",
                        origin_layer="L3",
                        target_layer=target,
                        gate=gate["gate_id"],
                        severity="BLOCKER" if target in {"L1", "L3"} else "MAJOR",
                        diagnosis=gate["summary"],
                    )
                )
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                error=f"L3 evidence gates failed: {[g['gate_id'] for g in failed]}",
            )

        return StepResult(status="OK")


class IntegrateStep:
    """Merge completed slice work into the active layer's dirty branch.

    Merge is still delegated to the lifecycle-owned CI tick. For merge
    conflicts, integrate performs a single rebase+remerge cycle and then
    emits demotion/blocking if conflicts persist.
    """

    name = "INTEGRATE"

    def __init__(self, *, investigator_budget: int = 2) -> None:
        self._investigator_budget = investigator_budget

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Merge grandchild → dirty with single rebase retry for merge conflicts."""
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        wm = ctx.worktree_manager

        def resolve_worktree_roots() -> tuple[Path | None, Path | None]:
            dirty_root = Path(ctx.dirty_parent_root) if ctx.dirty_parent_root else None
            clean_root = Path(ctx.clean_sibling_root) if ctx.clean_sibling_root else None
            if wm is not None:
                lane_map = getattr(wm, "_layer_worktrees", {}).get(ctx.layer, {})
                if dirty_root is None and lane_map.get("dirty") is not None:
                    dirty_root = Path(lane_map["dirty"])
                if clean_root is None and lane_map.get("clean") is not None:
                    clean_root = Path(lane_map["clean"])
            return dirty_root, clean_root

        def record_artifacts(
            *,
            merge: Any | None,
            emitted: list[DemotionTicket] | None = None,
            error: str = "",
            skipped: bool = False,
            merge_attempts: list[dict[str, Any]] | None = None,
            ci_tick_triggered: bool = False,
            ci_tick_error: str = "",
            ci_tick_receipt: dict[str, Any] | None = None,
            failure_evidence: dict[str, Any] | None = None,
            investigator_report_refs: list[str] | None = None,
        ) -> None:
            dirty_root, clean_root = resolve_worktree_roots()
            integration_payload: dict[str, Any] = {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "skipped": skipped,
                "merge_success": bool(getattr(merge, "success", False))
                if merge is not None
                else False,
                "merge_error": getattr(merge, "error", "") if merge is not None else "",
                "merge_sha": getattr(merge, "merge_sha", "") if merge is not None else "",
                "demotion_count": len(emitted or []),
                "error": error,
                "dirty_root": str(dirty_root) if dirty_root else "",
                "clean_root": str(clean_root) if clean_root else "",
                "merge_attempts": list(merge_attempts or []),
                "ci_tick": {
                    "triggered": ci_tick_triggered,
                    "error": ci_tick_error,
                    "delegated_to_pipeline": True,
                    "receipt": ci_tick_receipt or {},
                },
                "failure_evidence": failure_evidence or {},
                "investigator_report_refs": list(investigator_report_refs or []),
            }
            bundle.integration.path = _write_iteration_json(
                bundle,
                evidence_root,
                "integration.report.json",
                integration_payload,
            )

            tests_payload: dict[str, Any] = {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "note": "Per-slice integrate tests moved to batch pipeline tick",
            }
            bundle.tests.slice_path = _write_iteration_json(
                bundle,
                evidence_root,
                "tests.slice.json",
                tests_payload,
            )
            bundle.tests.full_path = _write_iteration_json(
                bundle,
                evidence_root,
                "tests.full.json",
                {
                    "slice_id": ctx.slice_id,
                    "layer": ctx.layer,
                    "note": "Full-suite integrate tests moved to batch pipeline tick",
                },
            )

        if wm is None:
            record_artifacts(merge=None, skipped=True)
            return StepResult(status="OK")

        integration_lock: Any | None = None
        if isinstance(ctx.config, dict):
            lock_candidate = ctx.config.get("_integration_lock")
            if hasattr(lock_candidate, "acquire") and hasattr(lock_candidate, "release"):
                integration_lock = lock_candidate

        def run_with_integration_lock(fn: Callable[[], Any]) -> Any:
            if integration_lock is None:
                return fn()
            with integration_lock:
                return fn()

        merge_attempts: list[dict[str, Any]] = []
        investigator_report_refs: list[str] = []
        failure_evidence: dict[str, Any] = {}
        dirty_root, _ = resolve_worktree_roots()

        def is_direct_dirty_slice() -> bool:
            if dirty_root is None or not ctx.slice_root:
                return False
            slice_root = Path(ctx.slice_root)
            try:
                return slice_root.resolve() == dirty_root.resolve()
            except OSError:
                return slice_root == dirty_root

        def run_merge_cycle(*, cycle: str) -> Any:
            if is_direct_dirty_slice():
                merge_result = SimpleNamespace(
                    success=True,
                    error="",
                    merge_sha=wm.vcs.get_head_sha(dirty_root),
                )
                merge_attempts.append(
                    {
                        "attempt": len(merge_attempts) + 1,
                        "cycle": cycle,
                        "strategy": "direct_dirty_no_merge",
                        "success": True,
                        "error": "",
                    }
                )
                return merge_result

            merge_result = wm.merge_slice_to_dirty(ctx.layer, ctx.slice_id, strategy="merge")
            merge_attempts.append(
                {
                    "attempt": len(merge_attempts) + 1,
                    "cycle": cycle,
                    "strategy": "merge",
                    "success": bool(merge_result.success),
                    "error": str(merge_result.error or ""),
                }
            )
            if merge_result.success:
                return merge_result

            rebase_ok = False
            rebase_error = ""
            slice_worktree = wm.get_slice_worktree(ctx.layer, ctx.slice_id)
            if slice_worktree is None:
                rebase_error = "Cannot locate slice worktree for rebase retry"
            else:
                dirty_branch = wm.layer_branch(ctx.layer, "dirty")
                rebase_ok, rebase_error = wm.vcs.rebase(slice_worktree, dirty_branch)
            merge_attempts.append(
                {
                    "attempt": len(merge_attempts) + 1,
                    "cycle": cycle,
                    "strategy": "rebase_slice_onto_dirty",
                    "success": bool(rebase_ok),
                    "error": str(rebase_error or ""),
                }
            )
            if not rebase_ok:
                return merge_result

            merge_result = wm.merge_slice_to_dirty(ctx.layer, ctx.slice_id, strategy="merge")
            merge_attempts.append(
                {
                    "attempt": len(merge_attempts) + 1,
                    "cycle": cycle,
                    "strategy": "merge_after_rebase",
                    "success": bool(merge_result.success),
                    "error": str(merge_result.error or ""),
                }
            )
            return merge_result

        def write_investigator_report(phase: str, report: dict[str, Any] | None) -> str:
            if not isinstance(report, dict) or not report:
                return ""
            name = f"investigator.{phase}.report.json"
            return _write_iteration_json(bundle, evidence_root, name, report)

        merge_result = run_with_integration_lock(lambda: run_merge_cycle(cycle="initial"))

        if not merge_result.success:
            failure_evidence = {
                "phase": "merge_failure",
                "merge_error": str(merge_result.error or ""),
                "merge_attempts": merge_attempts,
            }
            ticket_layer = cast("Literal['L1', 'L2', 'L3']", str(ctx.layer).upper())
            ticket = DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="TEST_FAILURE",
                origin_layer=ticket_layer,
                target_layer=ticket_layer,
                severity="BLOCKER",
                diagnosis=(
                    "Merge conflict after rebase retry: "
                    f"{merge_result.error or 'unknown merge error'}"
                ),
                evidence_refs=[],
                investigator_report_ref="",
            )
            record_artifacts(
                merge=merge_result,
                emitted=[ticket],
                error=merge_result.error,
                merge_attempts=merge_attempts,
                failure_evidence=failure_evidence,
                investigator_report_refs=investigator_report_refs,
            )
            return StepResult(
                status="RETRY",
                emitted_tickets=[ticket],
                error=merge_result.error,
            )

        ci_tick_triggered = False
        ci_tick_error = ""
        ci_tick_receipt: dict[str, Any] = {}
        if ctx.ci_tick_callback is not None:
            ci_callback = ctx.ci_tick_callback
            try:
                tick_result = run_with_integration_lock(lambda: ci_callback(ctx.slice_id))
                ci_tick_triggered = True
                if isinstance(tick_result, dict):
                    ci_tick_receipt = tick_result
            except Exception as exc:
                ci_tick_error = str(exc)
                logger.exception("CI tick callback failed for slice '%s'", ctx.slice_id)

        ci_failed = bool(ci_tick_error)
        if isinstance(ci_tick_receipt, dict):
            ci_failed = ci_failed or bool(ci_tick_receipt.get("failed", False))

        if ci_failed:
            refs: list[str] = []
            if isinstance(ci_tick_receipt.get("failure_refs"), list):
                refs.extend(
                    str(item).strip()
                    for item in ci_tick_receipt.get("failure_refs", [])
                    if str(item).strip()
                )
            summary = str(ci_tick_receipt.get("failure_summary", "")).strip()
            if summary:
                refs.append(summary)
            if ci_tick_error:
                refs.append(ci_tick_error)

            failure_evidence = {
                "phase": "ci_tick_failure",
                "ci_tick_error": ci_tick_error,
                "ci_tick_receipt": ci_tick_receipt,
                "merge_attempts": merge_attempts,
            }
            retry_receipt_holder: dict[str, Any] = {}

            def verify_ci_recovery(
                _: int,
                __: dict[str, Any],
            ) -> tuple[bool, dict[str, Any]]:
                if ctx.ci_tick_callback is None:
                    return True, {"note": "No CI callback available for retry verification"}
                retry_callback = ctx.ci_tick_callback
                try:
                    retry_raw = run_with_integration_lock(lambda: retry_callback(ctx.slice_id))
                except Exception as exc:
                    return False, {"error": str(exc)}
                retry_receipt = retry_raw if isinstance(retry_raw, dict) else {}
                retry_receipt_holder["receipt"] = retry_receipt
                retry_failed = bool(retry_receipt.get("failed", False))
                return (not retry_failed), {"retry_receipt": retry_receipt}

            ci_recovery_report = self._try_investigator(
                ctx,
                failure_refs=refs,
                failure_evidence=failure_evidence,
                layer_worktree=dirty_root,
                verify_callback=verify_ci_recovery,
            )
            ci_report_ref = write_investigator_report("ci", ci_recovery_report)
            if ci_report_ref:
                investigator_report_refs.append(ci_report_ref)

            if bool((ci_recovery_report or {}).get("fixed", False)):
                ci_tick_error = ""
                if isinstance(retry_receipt_holder.get("receipt"), dict):
                    ci_tick_receipt = cast("dict[str, Any]", retry_receipt_holder["receipt"])
            else:
                ticket_layer = cast("Literal['L1', 'L2', 'L3']", str(ctx.layer).upper())
                diagnosis = summary or ci_tick_error or "CI tick failed after integrate"
                ticket = DemotionTicket(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    source="TEST_FAILURE",
                    origin_layer=ticket_layer,
                    target_layer=ticket_layer,
                    severity="BLOCKER",
                    diagnosis=diagnosis,
                    evidence_refs=list(investigator_report_refs),
                    investigator_report_ref=investigator_report_refs[-1]
                    if investigator_report_refs
                    else "",
                )
                merge_attempts.append(
                    {
                        "attempt": len(merge_attempts) + 1,
                        "cycle": "ci_tick",
                        "strategy": "ci_tick_callback",
                        "success": False,
                        "error": diagnosis,
                    }
                )
                record_artifacts(
                    merge=merge_result,
                    emitted=[ticket],
                    error=diagnosis,
                    merge_attempts=merge_attempts,
                    ci_tick_triggered=ci_tick_triggered,
                    ci_tick_error=ci_tick_error,
                    ci_tick_receipt=ci_tick_receipt,
                    failure_evidence=failure_evidence,
                    investigator_report_refs=investigator_report_refs,
                )
                return StepResult(
                    status="RETRY",
                    emitted_tickets=[ticket],
                    error=diagnosis,
                )

        record_artifacts(
            merge=merge_result,
            merge_attempts=merge_attempts,
            ci_tick_triggered=ci_tick_triggered,
            ci_tick_error=ci_tick_error,
            ci_tick_receipt=ci_tick_receipt,
            investigator_report_refs=investigator_report_refs,
        )
        return StepResult(status="OK")

    def _try_investigator(
        self,
        ctx: SliceContext,
        *,
        failure_refs: list[str],
        failure_evidence: dict[str, Any] | None = None,
        layer_worktree: Path | None = None,
        verify_callback: Callable[[int, dict[str, Any]], tuple[bool, dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Invoke bounded investigator recovery in the layer worktree."""
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        candidate_worktree = layer_worktree
        if candidate_worktree is None and ctx.dirty_parent_root:
            candidate_worktree = Path(ctx.dirty_parent_root)
        if candidate_worktree is None:
            return {"fixed": False, "attempts": [], "error": "No investigator worktree"}
        return attempt_investigator_recovery(
            run_id=ctx.run_id,
            slice_id=ctx.slice_id,
            layer=ctx.layer,
            workspace_root=workspace,
            layer_worktree=candidate_worktree,
            failure_refs=failure_refs,
            failure_evidence=failure_evidence,
            investigator_budget=self._investigator_budget,
            verify_callback=verify_callback,
        )


class VerifyStep:
    """Run layer-aware post-integration verification.

    Per layer:
    - L1: cross-library connectivity (P6) + lineage (P7)
    - L2: pin consumption + topology + no inlined logic + manifest drift
    - L3: reviewer closure + no-logic-change + drift

    All layers:
    - Governance/oversight check (fail closed on FAIL)
    - Finding → DemotionTicket triage
    """

    name = "VERIFY"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Run governance checks + layer-specific verification."""
        import json
        import time

        from spec_manager.orchestration.evidence import Finding

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        verification_root = self._resolve_verification_root(ctx, workspace)
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)
        iteration_dir.mkdir(parents=True, exist_ok=True)
        findings: list[dict[str, Any]] = []
        notes: dict[str, Any] = {
            "layer": ctx.layer,
            "slice_id": ctx.slice_id,
            "verification_root": str(verification_root),
            "timestamp": time.time(),
            "findings": [],
        }

        def emit_finding(**kw: Any) -> None:
            f = Finding(
                dimension=kw.get("dimension", "VERIFY"),
                category=kw.get("category", "drift"),
                severity=kw.get("severity", "MINOR"),
                required_change_type=kw.get("required_change_type", "refactor_only"),
                location=kw.get("location", {}),
                evidence=kw.get("evidence", ""),
                suggested_fix=kw.get("suggested_fix", ""),
                confidence=kw.get("confidence", 0.7),
                tags=kw.get("tags", []),
            )
            findings.append(f.to_dict())

        def triage_to_ticket(f: dict[str, Any]) -> DemotionTicket | None:
            required = f.get("required_change_type", "refactor_only")
            cat = str(f.get("category", "style")).strip().lower() or "style"
            sev = f.get("severity", "MINOR")

            if cat == "governance":
                target = ctx.layer.upper()
            elif required == "behavior_change":
                target = "L1"
            elif cat == "architecture" or required == "wiring_only":
                target = "L2"
            else:
                return None

            loc = f.get("location") or {}
            failing_files = [loc["file"]] if loc.get("file") else []

            return DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="VERIFY",
                category=cat,
                origin_layer=ctx.layer.upper(),
                target_layer=target,
                severity=sev if sev in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                diagnosis=f.get("evidence", "")[:500] or f.get("dimension", "Verification finding"),
                failing_files=failing_files,
            )

        def run_agent_json(agent_name: str, prompt: str) -> dict[str, Any]:
            try:
                from spec_manager.core.agent_utils import run_agent
                from spec_manager.core.json_extraction import (
                    _extract_json_payload,
                )
                from spec_manager.refinement.formats import _strip_code_fences

                out = run_agent(
                    agent_name=agent_name,
                    prompt=prompt,
                    workspace=verification_root,
                )
                cleaned = _strip_code_fences(out)
                return json.loads(_extract_json_payload(cleaned))
            except Exception:
                # C03: Surface errors — LLM agent failure needs diagnosis
                logger.warning(
                    "Agent %s failed for verify step — returning empty",
                    agent_name,
                    exc_info=True,
                )
                return {}

        # 0) Governance / oversight
        oversight_prompt = (
            "## TASK\n"
            "Act as Pipeline Oversight Enforcer for this slice.\n"
            "Check: missing receipts, undocumented deviations, decision injection patterns.\n"
            "Return JSON: "
            '{"status": "PASS"|"WARN"|"FAIL", "findings": [{"severity": ..., "evidence": ..., '
            '"location": {}, "required_change_type": ...}]}\n\n'
            f"Slice: {ctx.slice_id}\nLayer: {ctx.layer}\nVerification root: {verification_root}\n"
        )
        oversight = run_agent_json("pipeline-oversight-enforcer", oversight_prompt)
        oversight_findings = oversight.get("findings", []) if isinstance(oversight, dict) else []
        for of in oversight_findings or []:
            emit_finding(
                dimension="GOVERNANCE",
                category="governance",
                severity=of.get("severity", "MAJOR"),
                required_change_type=of.get("required_change_type", "refactor_only"),
                location=of.get("location", {}),
                evidence=of.get("evidence", "Oversight finding"),
                confidence=0.8,
            )

        oversight_status = (
            str(oversight.get("status", "")).strip().upper() if isinstance(oversight, dict) else ""
        )
        if oversight_status not in {"PASS", "WARN", "FAIL"}:
            emit_finding(
                dimension="GOVERNANCE",
                category="governance",
                severity="BLOCKER",
                required_change_type="refactor_only",
                evidence=(
                    "Pipeline oversight verifier produced no valid PASS/WARN/FAIL status; "
                    "failing closed."
                ),
                confidence=1.0,
            )
            oversight_status = "FAIL"

        if oversight_status == "FAIL":
            tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]
            notes["findings"] = findings
            notes_path = iteration_dir / "verify.notes.json"
            notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
            bundle.verification.path = notes_path.name
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                notes_path=str(notes_path),
                error="VERIFY: governance FAIL",
            )

        # 1) Layer-specific verification
        if ctx.layer == "l1":
            l1_evidence = self._build_l1_verification_payload(
                ctx,
                bundle,
                verification_root=verification_root,
                workspace=workspace,
            )
            prompt = (
                "## TASK\n"
                "Verify L1 post-integration correctness:\n"
                "1) Cross-library connectivity (P6): promoted interfaces connect; no orphan "
                "dependencies.\n"
                "2) Lineage (P7): architecture-facing surfaces trace back to spec/atoms; flag "
                "orphans.\n"
                "Use only the evidence payload below. If evidence is missing for a required check, "
                "emit a finding that identifies the missing artifact.\n\n"
                "## EVIDENCE_PAYLOAD\n"
                f"{json.dumps(l1_evidence, indent=2)}\n\n"
                'Return JSON: {"findings": [...]} with required_change_type in {'
                "refactor_only, wiring_only, behavior_change}.\n\n"
                "Provide file locations when possible.\n"
            )
            data = run_agent_json("pdd-l1-verifier", prompt)
            for f in data.get("findings", []) or []:
                emit_finding(**f)

        elif ctx.layer == "l2":
            l2_evidence = self._build_l2_verification_payload(
                ctx,
                bundle,
                verification_root=verification_root,
                workspace=workspace,
            )
            prompt = (
                "## TASK\n"
                "Verify L2 architecture post-integration:\n"
                "- Pin consumption coverage (no unaccounted promoted pins)\n"
                "- Topology connectivity (no orphan components)\n"
                "- No inlined business logic in architecture\n"
                "- Conformance to component manifest / intended topology\n"
                "- Governance receipts are complete and traceable for promoted wiring changes\n\n"
                "Use only the evidence payload below. If evidence is missing for a required check, "
                "emit a finding that identifies the missing artifact.\n\n"
                "## EVIDENCE_PAYLOAD\n"
                f"{json.dumps(l2_evidence, indent=2)}\n\n"
                'Return JSON: {"findings": [...]}.\n'
            )
            data = run_agent_json("pdd-l2-verifier", prompt)
            for f in data.get("findings", []) or []:
                emit_finding(**f)

        elif ctx.layer == "l3":
            slice_test_payload = (
                _read_json_file(iteration_dir / bundle.tests.slice_path)
                if bundle.tests.slice_path
                else None
            )
            full_test_payload = (
                _read_json_file(iteration_dir / bundle.tests.full_path)
                if bundle.tests.full_path
                else None
            )
            slice_test_result = (
                slice_test_payload.get("result", {}) if isinstance(slice_test_payload, dict) else {}
            )
            full_test_result = (
                full_test_payload.get("result", {}) if isinstance(full_test_payload, dict) else {}
            )
            if not isinstance(slice_test_result, dict) or not slice_test_result:
                emit_finding(
                    dimension="CORRECTNESS",
                    category="logic",
                    severity="BLOCKER",
                    required_change_type="behavior_change",
                    evidence="L3 verify missing SLICE test result receipt.",
                    location={"file": ""},
                    confidence=1.0,
                )
                slice_test_result = {}
            elif not bool(slice_test_result.get("passed", False)):
                emit_finding(
                    dimension="CORRECTNESS",
                    category="logic",
                    severity="BLOCKER",
                    required_change_type="behavior_change",
                    evidence="L3 verify detected failing SLICE tests after integration.",
                    location={"file": ""},
                    confidence=1.0,
                )

            if (
                isinstance(full_test_result, dict)
                and full_test_result
                and not bool(full_test_result.get("passed", False))
            ):
                emit_finding(
                    dimension="CORRECTNESS",
                    category="logic",
                    severity="BLOCKER",
                    required_change_type="behavior_change",
                    evidence="L3 verify detected failing FULL tests after integration.",
                    location={"file": ""},
                    confidence=1.0,
                )

            reviewers = _configured_l3_review_pack(
                ctx.config if isinstance(ctx.config, dict) else None,
                include_diff_impact=False,
            )
            receipt_rows = _load_iteration_quality_receipts(
                evidence_root=evidence_root,
                bundle=bundle,
            )
            receipt_index = _latest_quality_receipts_by_key(receipt_rows)
            pass_receipts = [
                receipt
                for receipt in receipt_index.values()
                if _normalize_receipt_status(receipt.get("status")) == "PASS"
            ]
            manifest_hashes = {
                str(item.get("path", "")).strip(): str(item.get("sha256", "")).strip()
                for item in (bundle.manifest.files or [])
                if isinstance(item, dict) and str(item.get("path", "")).strip()
            }
            receipt_hash_mismatches: list[str] = []
            for receipt in pass_receipts:
                file_path = str(receipt.get("file", "")).strip()
                file_hash = str(receipt.get("file_hash", "")).strip()
                if not file_path or not file_hash:
                    continue
                candidate = verification_root / file_path
                if not candidate.exists() or not candidate.is_file():
                    receipt_hash_mismatches.append(f"{file_path}:missing")
                    continue
                try:
                    current_hash = _hash_text(candidate.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    receipt_hash_mismatches.append(f"{file_path}:unreadable")
                    continue
                if current_hash != file_hash:
                    receipt_hash_mismatches.append(file_path)

            if receipt_hash_mismatches:
                emit_finding(
                    dimension="DRIFT",
                    category="drift",
                    severity="MAJOR",
                    required_change_type="refactor_only",
                    evidence=(
                        "L3 verify found PASS quality receipts that do not match merged content "
                        f"hashes for {len(receipt_hash_mismatches)} file(s)."
                    ),
                    location={"file": receipt_hash_mismatches[0].split(":", 1)[0]},
                    confidence=1.0,
                )

            target_files = list(bundle.diff.changed_files or []) or list(manifest_hashes)
            missing_pass_receipts: list[str] = []
            for file_path in target_files:
                expected_hash = manifest_hashes.get(file_path, "")
                if not expected_hash:
                    continue
                for reviewer in reviewers:
                    key = "::".join((reviewer.reviewer_id, file_path, expected_hash))
                    receipt = receipt_index.get(key)
                    if (
                        receipt is None
                        or _normalize_receipt_status(receipt.get("status")) != "PASS"
                    ):
                        missing_pass_receipts.append(f"{reviewer.reviewer_id}:{file_path}")

            if missing_pass_receipts:
                emit_finding(
                    dimension="CLARITY",
                    category="maintainability",
                    severity="MAJOR",
                    required_change_type="refactor_only",
                    evidence=(
                        "L3 verify missing PASS quality receipts for merged content "
                        f"({len(missing_pass_receipts)} reviewer/file pair(s))."
                    ),
                    location={"file": target_files[0] if target_files else ""},
                    confidence=0.9,
                )

            l3_evidence = {
                "slice": {
                    "run_id": bundle.run_id,
                    "slice_id": bundle.slice_id,
                    "iteration": bundle.iteration,
                },
                "tests": {
                    "slice": slice_test_result,
                    "full": full_test_result,
                },
                "quality_receipts": {
                    "total_receipts": len(receipt_rows),
                    "latest_receipts": len(receipt_index),
                    "pass_receipts": len(pass_receipts),
                    "missing_pass_pairs": missing_pass_receipts[:80],
                    "hash_mismatches": receipt_hash_mismatches[:80],
                },
                "promotion": {
                    "gates": list(bundle.gates.gates or []),
                    "open_gaps": list(bundle.gaps.open_gaps or []),
                },
            }
            notes["l3_evidence"] = l3_evidence
            prompt = (
                "## TASK\n"
                "Verify L3 clean-code post-integration from concrete evidence:\n"
                "- Tests pass after merge\n"
                "- PASS quality receipts correspond to merged content hashes\n"
                "- Reviewer closure holds (no unresolved quality findings)\n"
                "- Governance/drift checks pass\n\n"
                "Use only the evidence payload below. If a required check lacks evidence, emit a "
                "finding for missing evidence.\n\n"
                "## EVIDENCE_PAYLOAD\n"
                f"{json.dumps(l3_evidence, indent=2)}\n\n"
                'Return JSON: {"findings": [...]}.\n'
            )
            data = run_agent_json("pdd-l3-verifier", prompt)
            for f in data.get("findings", []) or []:
                emit_finding(**f)

        # 2) Convert to demotion tickets
        tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]

        # Persist verify notes
        notes["findings"] = findings
        notes_path = iteration_dir / "verify.notes.json"
        notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
        bundle.verification.path = notes_path.name

        # Decide pass/fail
        has_blocker = any(f.get("severity") == "BLOCKER" for f in findings)
        has_major = any(f.get("severity") == "MAJOR" for f in findings)

        if has_blocker or has_major:
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                notes_path=str(notes_path),
                error=f"VERIFY: {len(findings)} findings ({len(tickets)} demotions)",
            )

        return StepResult(status="OK", notes_path=str(notes_path))

    @staticmethod
    def _resolve_verification_root(ctx: SliceContext, workspace: Path) -> Path:
        """Prefer clean sibling for verification; fallback to dirty parent/workspace."""
        candidates = [ctx.clean_sibling_root, ctx.dirty_parent_root, str(workspace)]
        for candidate in candidates:
            if not candidate:
                continue
            root = Path(candidate)
            if root.exists():
                return root
        return workspace

    def _build_l1_verification_payload(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        *,
        verification_root: Path,
        workspace: Path,
    ) -> dict[str, Any]:
        """Build concrete P6/P7 evidence for L1 verification."""
        p6_payload: dict[str, Any]
        try:
            from spec_manager.analysis.adjacency.runner import (
                AdjacencyAnalysisConfig,
                run_adjacency_analysis,
            )

            adjacency_report = run_adjacency_analysis(
                AdjacencyAnalysisConfig(
                    source_dirs=[verification_root],
                    spec_dirs=[verification_root],
                )
            )
            p6_payload = {
                "status": "OK",
                "total_nodes": adjacency_report.total_nodes,
                "total_edges": adjacency_report.total_edges,
                "num_components": adjacency_report.num_components,
                "disconnected_warnings": list(adjacency_report.disconnected_warnings),
                "signal_type_counts": dict(adjacency_report.signal_type_counts),
            }
        except Exception as exc:
            logger.warning("P6 adjacency verification payload failed: %s", exc, exc_info=True)
            p6_payload = {
                "status": "ERROR",
                "error": str(exc),
            }

        p7_payload: dict[str, Any]
        try:
            from spec_manager.projection.lineage.builder import (
                AtomDefinition,
                LineageBuilder,
                import_records_from_pin_registry,
                scan_imports_from_directory,
            )
            from spec_manager.schemas.pin_functions import PinFunctionRegistry

            registry_path = verification_root / ".spec" / "pin_registry.json"
            import_records = []
            record_source = "pin_registry"
            if registry_path.exists():
                try:
                    pin_registry = PinFunctionRegistry.model_validate_json(
                        registry_path.read_text(encoding="utf-8")
                    )
                    import_records = import_records_from_pin_registry(pin_registry)
                except Exception as exc:
                    logger.warning(
                        "Failed to load pin registry for P7 verification payload: %s",
                        exc,
                        exc_info=True,
                    )
            if not import_records:
                record_source = "scan_fallback"
                import_records = scan_imports_from_directory(verification_root)

            atom_defs: list[AtomDefinition] = []
            branch_manager = ctx.branch_manager
            if branch_manager is not None:
                list_atoms = getattr(branch_manager, "list_atoms", None)
                if callable(list_atoms):
                    for atom in list_atoms():
                        atom_defs.append(
                            AtomDefinition(
                                atom_id=getattr(atom, "atom_id", ""),
                                function_name=getattr(atom, "function_name", ""),
                                file_path=getattr(atom, "file_path", ""),
                                module_path="",
                                signature_hash=(
                                    getattr(atom, "signature_hash", "")
                                    or getattr(atom, "content_hash", "")
                                ),
                            )
                        )

            if atom_defs:
                lineage_builder = LineageBuilder(import_records=import_records, atoms=atom_defs)
                lineage_table = lineage_builder.build_lineage()
                known_atom_ids = {a.atom_id for a in atom_defs}
                orphan_atoms = lineage_table.find_orphan_atoms(known_atom_ids)
                p7_payload = {
                    "status": "OK",
                    "import_edges": len(import_records),
                    "lineage_edges": len(lineage_table.edges),
                    "known_atoms": len(known_atom_ids),
                    "orphan_atoms": len(orphan_atoms),
                    "orphan_atom_ids": sorted(orphan_atoms)[:50],
                    "edge_source": record_source,
                }
            else:
                p7_payload = {
                    "status": "MISSING_ATOMS",
                    "import_edges": len(import_records),
                    "lineage_edges": 0,
                    "known_atoms": 0,
                    "orphan_atoms": 0,
                    "note": "No branch-manager atoms available for lineage tracing",
                    "edge_source": record_source,
                }
        except Exception as exc:
            logger.warning("P7 lineage verification payload failed: %s", exc, exc_info=True)
            p7_payload = {
                "status": "ERROR",
                "error": str(exc),
            }

        return {
            "slice": {
                "run_id": bundle.run_id,
                "slice_id": bundle.slice_id,
                "iteration": bundle.iteration,
                "layer": ctx.layer,
            },
            "roots": {
                "verification_root": str(verification_root),
                "workspace_root": str(workspace),
                "clean_sibling_root": ctx.clean_sibling_root,
                "dirty_parent_root": ctx.dirty_parent_root,
            },
            "p6_cross_library": p6_payload,
            "p7_lineage": p7_payload,
            "integration": {
                "integration_report_path": bundle.integration.path,
                "tests_slice_path": bundle.tests.slice_path,
                "tests_full_path": bundle.tests.full_path,
            },
        }

    @staticmethod
    def _is_l2_architecture_artifact(rel_path: str) -> bool:
        """Return True when a manifest path is likely an L2 architecture artifact."""
        lowered = rel_path.lower()
        tokens = (
            "manifest",
            "topology",
            "wiring",
            "entrypoint",
            "pins",
            "architecture",
            "graph",
        )
        return any(token in lowered for token in tokens)

    def _build_l2_verification_payload(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        *,
        verification_root: Path,
        workspace: Path,
    ) -> dict[str, Any]:
        """Build concrete L2 verification evidence from the current bundle."""
        manifest_entries = [m for m in bundle.manifest.files if isinstance(m, dict)]
        arch_manifest_paths = [
            str(entry.get("path", "")).strip()
            for entry in manifest_entries
            if isinstance(entry.get("path"), str)
            and self._is_l2_architecture_artifact(str(entry.get("path", "")).strip())
        ]

        search_roots: list[Path] = [verification_root]
        if workspace != verification_root:
            search_roots.append(workspace)

        architecture_artifacts: list[dict[str, str]] = []
        for rel_path in arch_manifest_paths[:12]:
            artifact_path: Path | None = None
            for root in search_roots:
                candidate = root / rel_path
                if candidate.exists() and candidate.is_file():
                    artifact_path = candidate
                    break
            if artifact_path is None:
                continue
            try:
                content = artifact_path.read_text(encoding="utf-8")
            except OSError:
                continue
            architecture_artifacts.append(
                {
                    "path": rel_path,
                    "content": content[:4000],
                }
            )

        analyzed_components: list[dict[str, Any]] = []
        architecture_graph_cache: dict[str, Any] = {}
        for entry in bundle.source_index.entries:
            if not isinstance(entry, dict):
                continue
            analysis = entry.get("analysis")
            if isinstance(analysis, dict):
                analyzed_components.append(analysis)
                if analysis.get("type") == "l2_architecture_graph":
                    graph_path = str(analysis.get("graph_path") or entry.get("path") or "").strip()
                    if graph_path:
                        evidence_root = _evidence_base_path(
                            slice_root=ctx.slice_root,
                            workspace_root=ctx.workspace_root,
                        )
                        graph_payload = _read_json_file(bundle.iter_dir(evidence_root) / graph_path)
                        if isinstance(graph_payload, dict):
                            architecture_graph_cache = graph_payload

        return {
            "slice": {
                "run_id": bundle.run_id,
                "slice_id": bundle.slice_id,
                "iteration": bundle.iteration,
                "layer": ctx.layer,
            },
            "manifest": {
                "files": manifest_entries,
                "slice_patterns": list(bundle.manifest.slice_patterns or []),
                "generated_files": list(bundle.manifest.generated_files or []),
                "architecture_paths": arch_manifest_paths,
            },
            "diff": {
                "changed_files": list(bundle.diff.changed_files or []),
                "content_hash": bundle.diff.content_hash,
                "head_commit": bundle.diff.head_commit,
            },
            "analysis": {
                "source_index_entries": len(bundle.source_index.entries or []),
                "components": analyzed_components[:150],
                "architecture_graph_cache": architecture_graph_cache,
            },
            "implementation_receipts": {
                "applied_edits": list(bundle.implementation.applied_edits or []),
                "pin_proposals": list(bundle.implementation.pin_proposals or []),
                "edge_proposals": list(bundle.implementation.edge_proposals or []),
                "under_spec_events": list(bundle.implementation.under_spec_events or []),
            },
            "graph_artifacts": {
                "pins_snapshot": asdict(bundle.pins_snapshot),
                "graph_snapshot": asdict(bundle.graph_snapshot),
                "graph_deltas": [asdict(delta) for delta in bundle.graph_deltas],
            },
            "promotion": {
                "promotion_report_path": bundle.promotion.path,
                "gates": list(bundle.gates.gates or []),
                "demotions": asdict(bundle.demotions),
            },
            "integration": {
                "integration_report_path": bundle.integration.path,
                "tests_slice_path": bundle.tests.slice_path,
                "tests_full_path": bundle.tests.full_path,
                "verification_path": bundle.verification.path,
            },
            "architecture_artifacts": architecture_artifacts,
        }


class AlignStep:
    """POWER alignment check: detect drift and reward hacking.

    Compares the current implementation against the original spec
    (charter/constraints) to ensure the system hasn't drifted from
    its intended purpose or started optimizing for proxy metrics.

    Runs after VERIFY, before termination check.  High-severity
    findings emit DemotionTickets.
    """

    name = "ALIGN"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Run POWER alignment on the slice."""
        from spec_manager.core.language import source_rglob

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            return StepResult(status="OK")

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        # Gather charter/constraints and current code for alignment comparison
        charter_files: list[str] = []
        code_summaries: list[str] = []

        # Look for charter in library structure
        libraries_dir = workspace / "libraries"
        if libraries_dir.exists():
            for lib_dir in sorted(libraries_dir.iterdir()):
                if not lib_dir.is_dir():
                    continue
                charter_path = lib_dir / "charter.md"
                if charter_path.exists():
                    charter_files.append(
                        f"## {lib_dir.name}\n\n" + charter_path.read_text(encoding="utf-8")
                    )
                constraints_path = lib_dir / "constraints.md"
                if constraints_path.exists():
                    charter_files.append(
                        f"## {lib_dir.name} constraints\n\n"
                        + constraints_path.read_text(encoding="utf-8")
                    )

        # Gather current code from slice
        for py_file in source_rglob(slice_root):
            if not py_file.is_file():
                continue
            if any(part.startswith(".") for part in py_file.parts):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                # Include first 100 lines as summary
                lines = content.split("\n")[:100]
                code_summaries.append(
                    f"### {py_file.relative_to(slice_root)}\n```python\n"
                    + "\n".join(lines)
                    + "\n```"
                )
            except (OSError, UnicodeDecodeError):
                continue

        if not charter_files or not code_summaries:
            # No charter to check against — skip
            return StepResult(status="OK")

        try:
            import json

            from spec_manager.core.agent_utils import run_agent
            from spec_manager.refinement.formats import (
                _extract_json_payload,
                _strip_code_fences,
            )

            prompt = (
                "## TASK\n\n"
                "Check the implementation against the original charter/constraints.\n"
                "Detect requirement drift and reward hacking.\n"
                "Return JSON with keys: drift_findings, reward_hacking_findings.\n"
                "Each finding should have: severity (HIGH/MEDIUM/LOW), description, file.\n\n"
                "## CHARTER/CONSTRAINTS\n\n"
                + "\n\n---\n\n".join(charter_files)
                + "\n\n## CURRENT CODE\n\n"
                + "\n\n".join(code_summaries[:20])  # limit context
            )

            output = run_agent(
                agent_name="opus-alignment-checker",
                prompt=prompt,
                workspace=workspace,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))

            drift = data.get("drift_findings", [])
            reward = data.get("reward_hacking_findings", [])

            # Emit DemotionTickets for high-severity findings
            tickets: list[DemotionTicket] = []
            for finding in drift + reward:
                severity = finding.get("severity", "LOW")
                if severity == "HIGH":
                    tickets.append(
                        DemotionTicket(
                            run_id=ctx.run_id,
                            slice_id=ctx.slice_id,
                            source="REVIEW",
                            target_layer="L1",
                            origin_layer=ctx.layer.upper(),
                            severity="BLOCKER",
                            diagnosis=finding.get("description", "POWER alignment drift"),
                            failing_files=[finding.get("file", "")],
                        )
                    )

            if tickets:
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    error=f"POWER alignment: {len(tickets)} high-severity findings",
                )

        except Exception as exc:
            logger.warning("POWER alignment check failed: %s", exc, exc_info=True)
            return StepResult(status="RETRY", error=f"POWER alignment check failed: {exc}")

        return StepResult(status="OK")


# ------------------------------------------------------------------
# Default step sequence
# ------------------------------------------------------------------

DEFAULT_BUILD_STEPS: tuple[type, ...] = (
    CollectBaselineStep,
    GapExplorationStep,
    PlanStep,
    ImplementStep,
    CoordinateStep,
    AnalyzeStep,
    PromoteStep,
    IntegrateStep,
    VerifyStep,
    AlignStep,
)
ARCHITECTURE_MODE_STEPS: tuple[type, ...] = (
    CollectBaselineStep,
    GapExplorationStep,
    PlanStep,
    ImplementStep,
    CoordinateStep,
    AnalyzeStep,
    PromoteStep,
    IntegrateStep,
    VerifyStep,
    AlignStep,
)
CODE_QUALITY_MODE_STEPS: tuple[type, ...] = DEFAULT_BUILD_STEPS

RUN_MODE_STEP_DISPATCH: dict[LifecycleRunMode, dict[Layer, tuple[type, ...]]] = {
    "build": {
        "l1": DEFAULT_BUILD_STEPS,
        "l2": DEFAULT_BUILD_STEPS,
        "l3": DEFAULT_BUILD_STEPS,
    },
    "qa": {
        "l1": (CollectBaselineStep, IntegrateStep, VerifyStep),
        "l2": (CollectBaselineStep, IntegrateStep, VerifyStep),
        "l3": (CollectBaselineStep, IntegrateStep, VerifyStep),
    },
    "architecture": {
        "l1": ARCHITECTURE_MODE_STEPS,
        "l2": ARCHITECTURE_MODE_STEPS,
        "l3": ARCHITECTURE_MODE_STEPS,
    },
    "code_quality": {
        "l1": CODE_QUALITY_MODE_STEPS,
        "l2": CODE_QUALITY_MODE_STEPS,
        "l3": CODE_QUALITY_MODE_STEPS,
    },
}


# ------------------------------------------------------------------
# PromotionLoop
# ------------------------------------------------------------------


class PromotionLoop:
    """Per-slice iterative promotion loop.

    Replaces the sequential P0-P10 pipeline with a convergence loop
    that runs until all gaps are closed and all atoms promoted.

    Args:
        worktree_manager: Multi-layer worktree manager.
        workspace_manager: Workspace manager reference for steps that need workspace state.
        branch_manager: Branch manager reference for steps that need branch metadata.
        workspace_root: Root of the repository.
        demotion_manager: Handles applying demotion tickets.
        steps: Custom step sequence (defaults to all steps).
    """

    def __init__(
        self,
        worktree_manager: Any = None,
        workspace_manager: Any = None,
        branch_manager: Any = None,
        workspace_root: Path = Path("."),
        demotion_manager: DemotionManager | None = None,
        steps: list[Any] | None = None,
        planner: Any = None,
    ) -> None:
        self._wm = worktree_manager
        self._workspace_manager = workspace_manager
        self._branch_manager = branch_manager
        self._workspace_root = workspace_root
        self._dm = demotion_manager or DemotionManager(workspace_root)
        self._planner = planner
        from spec_manager.core.gap_queue import GapQueue

        self._gap_queue = GapQueue()
        self._steps_override = steps
        self._step_cache: dict[tuple[LifecycleRunMode, Layer], list[Any]] = {}

    @staticmethod
    def _normalize_lifecycle_mode(value: str) -> LifecycleRunMode:
        normalized = str(value).strip().lower()
        if normalized in {"build", "qa", "architecture", "code_quality"}:
            return cast("LifecycleRunMode", normalized)
        return "build"

    def _instantiate_steps(self, step_types: tuple[type, ...]) -> list[Any]:
        instances: list[Any] = []
        for step_cls in step_types:
            if step_cls is IntegrateStep:
                instances.append(step_cls())
            elif step_cls is GapExplorationStep:
                instances.append(step_cls(planner=self._planner, gap_queue=self._gap_queue))
            elif step_cls in (PlanStep, CoordinateStep):
                instances.append(step_cls(planner=self._planner))
            else:
                instances.append(step_cls())
        return instances

    def _steps_for_run(self, *, lifecycle_mode: LifecycleRunMode, layer: Layer) -> list[Any]:
        if self._steps_override is not None:
            return self._steps_override

        key = (lifecycle_mode, layer)
        cached = self._step_cache.get(key)
        if cached is not None:
            return cached

        mode_dispatch = RUN_MODE_STEP_DISPATCH.get(lifecycle_mode, RUN_MODE_STEP_DISPATCH["build"])
        step_types = mode_dispatch.get(layer, mode_dispatch["l1"])
        instances = self._instantiate_steps(step_types)
        self._step_cache[key] = instances
        return instances

    def _record_provenance(
        self,
        bundle: EvidenceBundle,
        step_name: str,
        result: StepResult,
        ctx: SliceContext,
    ) -> None:
        """Append per-step provenance metadata."""
        entry: dict[str, Any] = {
            "step": step_name,
            "status": result.status,
            "timestamp": _now_iso(),
            "layer": ctx.layer,
            "slice_id": ctx.slice_id,
            "mode": ctx.mode,
            "lifecycle_mode": ctx.lifecycle_mode,
        }
        if result.error:
            entry["error"] = result.error[:500]
        if result.notes_path:
            entry["notes_path"] = result.notes_path
        model_ids = ctx.config.get("model_ids") if isinstance(ctx.config, dict) else None
        if isinstance(model_ids, dict) and model_ids:
            entry["model_ids"] = model_ids
        bundle.provenance.entries.append(entry)
        bundle.provenance.path = "provenance.json"

    @staticmethod
    def _refresh_facts(bundle: EvidenceBundle) -> None:
        """Refresh normalized facts using current source index + implementation outputs."""
        functions = dict(bundle.facts.functions or {})
        stores = dict(bundle.facts.stores or {})
        atoms = dict(bundle.facts.atoms or {})
        llm_claims = list(bundle.facts.llm_claims or [])

        for entry in bundle.source_index.entries or []:
            if not isinstance(entry, dict):
                continue
            analysis = entry.get("analysis") or {}
            if not isinstance(analysis, dict):
                continue
            file_path = entry.get("path", "")
            for fn in analysis.get("functions", []) or []:
                if not isinstance(fn, dict):
                    continue
                qualified_name = fn.get("qualified_name") or fn.get("name") or ""
                if not qualified_name:
                    continue
                functions[qualified_name] = {
                    "signature": {
                        "name": fn.get("name", ""),
                        "args": fn.get("args", []),
                        "return_annotation": fn.get("return_annotation"),
                        "is_async": fn.get("is_async", False),
                    },
                    "doc": fn.get("docstring", ""),
                    "file": file_path,
                    "lines": [fn.get("start_line", 0), fn.get("end_line", 0)],
                }

        for pin in bundle.implementation.pin_proposals or []:
            pin_id = pin.get("pin_id") or pin.get("id") or pin.get("fqn") or ""
            if not pin_id:
                continue
            atoms[pin_id] = {
                "file": pin.get("file", ""),
                "boundaries": pin.get("span", {}),
                "responsibilities": pin.get("responsibilities", []),
            }

        for edge in bundle.implementation.edge_proposals or []:
            if edge.get("signal_type") != "STORE_TOUCH":
                continue
            store_id = edge.get("dst") or edge.get("store_id") or ""
            if not store_id:
                continue
            owner = edge.get("src", "")
            owner_atoms = [owner] if owner else []
            existing = stores.get(store_id, {})
            previous = existing.get("owner_atoms", [])
            stores[store_id] = {
                "owner_atoms": sorted(set(previous + owner_atoms)),
                "schema": existing.get("schema", {}),
            }

        seen_claims: set[str] = set()
        for claim in llm_claims:
            if isinstance(claim, dict):
                fingerprint = json.dumps(claim, sort_keys=True)
                seen_claims.add(fingerprint)
        for gap in bundle.gaps.open_gaps or []:
            if not isinstance(gap, dict):
                continue
            if not gap.get("reviewer") and not gap.get("dimension"):
                continue
            claim = {
                "claim": gap.get("description", ""),
                "evidence_refs": [bundle.gaps.path] if bundle.gaps.path else [],
                "confidence": 0.7,
                "produced_by_step": "GAP_EXPLORATION",
            }
            fingerprint = json.dumps(claim, sort_keys=True)
            if fingerprint not in seen_claims:
                seen_claims.add(fingerprint)
                llm_claims.append(claim)

        bundle.facts.functions = functions
        bundle.facts.stores = stores
        bundle.facts.atoms = atoms
        bundle.facts.llm_claims = llm_claims
        if (
            bundle.facts.functions
            or bundle.facts.stores
            or bundle.facts.atoms
            or bundle.facts.llm_claims
            or bundle.facts.constraints_refs
        ):
            bundle.facts.path = "facts.json"

    @staticmethod
    def _persist_iteration_artifacts(ctx: SliceContext, bundle: EvidenceBundle) -> None:
        """Persist step artifacts and keep bundle refs pointing to them."""
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )

        if bundle.manifest.files:
            quality_receipts_snapshot: dict[str, Any] = {}
            if _QUALITY_RECEIPTS_FILENAME in (bundle.manifest.generated_files or []):
                quality_receipts_snapshot = {"path": _QUALITY_RECEIPTS_FILENAME}
            bundle.manifest.path = _write_iteration_json(
                bundle,
                evidence_root,
                "manifest.json",
                {
                    "files": bundle.manifest.files,
                    "component_inventory": bundle.manifest.component_inventory,
                    "pin_registry_summary": bundle.manifest.pin_registry_summary,
                    "slice_patterns": bundle.manifest.slice_patterns,
                    "generated_files": bundle.manifest.generated_files,
                    "quality_receipts_snapshot": quality_receipts_snapshot,
                },
            )

        if (
            bundle.diff.base_commit
            or bundle.diff.head_commit
            or bundle.diff.changed_files
            or bundle.diff.content_hash
        ):
            bundle.diff.path = _write_iteration_json(
                bundle,
                evidence_root,
                "diff.json",
                {
                    "base_commit": bundle.diff.base_commit,
                    "head_commit": bundle.diff.head_commit,
                    "changed_files": bundle.diff.changed_files,
                    "content_hash": bundle.diff.content_hash,
                },
            )

        if bundle.provenance.path or bundle.provenance.entries:
            bundle.provenance.path = _write_iteration_json(
                bundle,
                evidence_root,
                "provenance.json",
                {"entries": bundle.provenance.entries},
            )

        if bundle.source_index.path or bundle.source_index.entries:
            bundle.source_index.path = _write_iteration_json(
                bundle,
                evidence_root,
                "source_analysis.index.json",
                {"entries": bundle.source_index.entries},
            )

        if bundle.facts.path or (
            bundle.facts.functions
            or bundle.facts.stores
            or bundle.facts.atoms
            or bundle.facts.constraints_refs
            or bundle.facts.llm_claims
        ):
            bundle.facts.path = _write_iteration_json(
                bundle,
                evidence_root,
                "facts.json",
                {
                    "functions": bundle.facts.functions,
                    "stores": bundle.facts.stores,
                    "atoms": bundle.facts.atoms,
                    "constraints_refs": bundle.facts.constraints_refs,
                    "llm_claims": bundle.facts.llm_claims,
                },
            )

        if bundle.gaps.path or bundle.gaps.open_gaps or bundle.gaps.stagnation:
            bundle.gaps.path = _write_iteration_json(
                bundle,
                evidence_root,
                "gaps.json",
                {
                    "open_gaps": bundle.gaps.open_gaps,
                    "stagnation": bundle.gaps.stagnation,
                },
            )

        if (
            bundle.plan.path
            or bundle.plan.intentions
            or bundle.plan.edit_targets
            or bundle.plan.test_plan
            or bundle.plan.risks
        ):
            bundle.plan.path = _write_iteration_json(
                bundle,
                evidence_root,
                "plan.json",
                {
                    "intentions": bundle.plan.intentions,
                    "edit_targets": bundle.plan.edit_targets,
                    "test_plan": bundle.plan.test_plan,
                    "risks": bundle.plan.risks,
                },
            )

        if (
            bundle.implementation.result_path
            or bundle.implementation.applied_edits
            or bundle.implementation.gap_inventory
            or bundle.implementation.pin_proposals
            or bundle.implementation.edge_proposals
            or bundle.implementation.under_spec_events
            or bundle.implementation.tests_added
            or bundle.implementation.patch_path
        ):
            bundle.implementation.result_path = _write_iteration_json(
                bundle,
                evidence_root,
                "impl.result.json",
                {
                    "patch_path": bundle.implementation.patch_path,
                    "applied_edits": bundle.implementation.applied_edits,
                    "gap_inventory": bundle.implementation.gap_inventory,
                    "pin_proposals": bundle.implementation.pin_proposals,
                    "edge_proposals": bundle.implementation.edge_proposals,
                    "under_spec_events": bundle.implementation.under_spec_events,
                    "tests_added": bundle.implementation.tests_added,
                },
            )

        if bundle.under_spec.path or bundle.under_spec.decisions or bundle.under_spec.blockers:
            bundle.under_spec.path = _write_iteration_json(
                bundle,
                evidence_root,
                "blockers.json",
                {
                    "decisions": bundle.under_spec.decisions,
                    "blockers": bundle.under_spec.blockers,
                },
            )

        if bundle.gates.path or bundle.gates.gates:
            bundle.gates.path = _write_iteration_json(
                bundle,
                evidence_root,
                "gates.report.json",
                {"gates": bundle.gates.gates},
            )

        if bundle.promotion.path or bundle.gates.gates:
            promotion_name = bundle.promotion.path or "promotion.report.json"
            promotion_path = bundle.iter_dir(evidence_root) / promotion_name
            if promotion_path.exists():
                bundle.promotion.path = promotion_name
            else:
                bundle.promotion.path = _write_iteration_json(
                    bundle,
                    evidence_root,
                    "promotion.report.json",
                    {
                        "slice_id": bundle.slice_id,
                        "iteration": bundle.iteration,
                        "status": bundle.status,
                        "gates_ref": bundle.gates.path,
                        "graph_snapshot": bundle.graph_snapshot.path,
                        "pins_snapshot": bundle.pins_snapshot.path,
                    },
                )

        if bundle.refinement.path:
            refinement_path = bundle.iter_dir(evidence_root) / bundle.refinement.path
            if refinement_path.exists():
                bundle.refinement.path = refinement_path.name

        if (
            bundle.demotions.path
            or bundle.demotions.emitted
            or bundle.demotions.applied
            or bundle.demotions.pending
        ):
            bundle.demotions.path = _write_iteration_json(
                bundle,
                evidence_root,
                "demotions.json",
                {
                    "emitted": bundle.demotions.emitted,
                    "applied": bundle.demotions.applied,
                    "pending": bundle.demotions.pending,
                },
            )

    @staticmethod
    def _register_gap_queue_stagnation_under_spec(
        ctx: SliceContext,
        bundle: EvidenceBundle,
    ) -> str | None:
        """Convert GapQueue stagnation into an under-spec event."""
        stagnation = bundle.gaps.stagnation
        if not isinstance(stagnation, dict) or not bool(stagnation.get("is_stagnant")):
            return None

        open_gap_count = len(bundle.gaps.open_gaps or [])
        stagnation_count_raw = stagnation.get("stagnation_count", 0)
        try:
            stagnation_count = int(stagnation_count_raw)
        except (TypeError, ValueError):
            stagnation_count = 0

        question = (
            f"Cannot progress on slice '{ctx.slice_id}': GapQueue stagnated "
            f"for {stagnation_count} consecutive updates with {open_gap_count} open gaps. "
            "Additional constraints or clarifications are required."
        )
        event = {
            "kind": "MISSING_CONSTRAINT",
            "file": "",
            "question": question,
            "context": bundle.gaps.path or "gaps.json",
            "stagnation_count": stagnation_count,
            "open_gaps": open_gap_count,
        }

        existing_events = [
            e for e in (bundle.implementation.under_spec_events or []) if isinstance(e, dict)
        ]
        if not any(str(e.get("question", "")) == question for e in existing_events):
            existing_events.append(event)
        bundle.implementation.under_spec_events = existing_events
        return question

    @staticmethod
    def _refinement_issue_threshold(ctx: SliceContext) -> int:
        """Resolve per-slice refinement issue threshold from run config."""
        threshold = 0
        if isinstance(ctx.config, dict):
            raw_threshold = ctx.config.get("refinement_max_issues", 0)
            try:
                threshold = int(raw_threshold)
            except (TypeError, ValueError):
                threshold = 0
        return max(threshold, 0)

    @staticmethod
    def _refinement_issue_count(ctx: SliceContext, bundle: EvidenceBundle) -> int:
        """Load issue_count from the current iteration refinement artifact."""
        if not bundle.refinement.path:
            return 0

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        refinement_path = bundle.iter_dir(evidence_root) / bundle.refinement.path
        if not refinement_path.exists():
            return 0

        try:
            payload = json.loads(refinement_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Unreadable refinement artifact at %s", refinement_path)
            return 1

        issue_count_raw = payload.get("issue_count")
        if isinstance(issue_count_raw, int):
            return max(issue_count_raw, 0)

        issues = payload.get("issues", [])
        return len(issues) if isinstance(issues, list) else 0

    def run_slice(
        self,
        slice_ref: SliceRef,
        run_context: RunContext,
        seed_gap_set: SeedGapSet | None = None,
    ) -> SliceResult:
        """Run the promotion loop on a single slice until convergence.

        Args:
            slice_ref: The slice to process.
            run_context: Run-scoped configuration.
            seed_gap_set: Optional scheduler-provided initial open gaps.

        Returns:
            SliceResult with final status.
        """
        slice_config = dict(run_context.config) if isinstance(run_context.config, dict) else {}
        raw_focus_targets = {}
        slice_focus_targets = slice_config.pop("slice_focus_targets", None)
        if isinstance(slice_focus_targets, dict):
            raw_focus_targets = slice_focus_targets.get(slice_ref.slice_id, {})
        elif isinstance(slice_config.get("focus_targets"), dict):
            raw_focus_targets = slice_config.get("focus_targets", {})
        focus_targets = _normalize_focus_targets(raw_focus_targets)
        if focus_targets:
            slice_config["focus_targets"] = focus_targets

        ctx = SliceContext(
            slice_id=slice_ref.slice_id,
            slice_root=slice_ref.worktree_path,
            layer=slice_ref.layer,
            run_id=run_context.run_id,
            mode=run_context.mode,
            lifecycle_mode=self._normalize_lifecycle_mode(run_context.lifecycle_mode),
            workspace_root=run_context.workspace_root,
            config=slice_config,
            ci_tick_callback=run_context.ci_tick_callback,
            ci_periodic_tick_callback=run_context.ci_periodic_tick_callback,
            ci_periodic_tick_interval_sec=run_context.ci_periodic_tick_interval_sec,
            worktree_manager=self._wm,
            workspace_manager=self._workspace_manager,
            branch_manager=self._branch_manager,
        )
        self._dm.run_id = run_context.run_id
        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )

        # Set dirty/clean parent paths if worktree manager available
        if ctx.worktree_manager:
            dirty = ctx.worktree_manager._layer_worktrees.get(ctx.layer, {}).get("dirty")
            clean = ctx.worktree_manager._layer_worktrees.get(ctx.layer, {}).get("clean")
            if dirty:
                ctx.dirty_parent_root = str(dirty)
            if clean:
                ctx.clean_sibling_root = str(clean)

        # Layer-specific iteration limit
        max_iters = run_context.max_iterations_by_layer.get(
            slice_ref.layer, run_context.max_iterations
        )
        active_steps = self._steps_for_run(
            lifecycle_mode=ctx.lifecycle_mode,
            layer=ctx.layer,
        )

        all_tickets: list[DemotionTicket] = []
        iteration = 0
        waiting_iterations = 0

        # Per-ticket retry budget: track (failing_files_key, gate) → count
        retry_tracker: dict[tuple[str, str], int] = {}
        retry_budget = 3

        bundle: EvidenceBundle | None = None
        periodic_tick_due_at: float | None = None
        if ctx.ci_periodic_tick_callback is not None:
            interval = max(float(ctx.ci_periodic_tick_interval_sec), 1.0)
            periodic_tick_due_at = monotonic() + interval

        def maybe_emit_periodic_ci_tick() -> None:
            nonlocal periodic_tick_due_at
            if ctx.ci_periodic_tick_callback is None or periodic_tick_due_at is None:
                return
            if monotonic() < periodic_tick_due_at:
                return
            try:
                ctx.ci_periodic_tick_callback()
            except Exception:
                logger.exception(
                    "Periodic CI tick callback failed for slice '%s'",
                    ctx.slice_id,
                )
            interval = max(float(ctx.ci_periodic_tick_interval_sec), 1.0)
            periodic_tick_due_at = monotonic() + interval

        while iteration < max_iters:
            iteration += 1
            logger.info("=== Slice '%s' iteration %d/%d ===", ctx.slice_id, iteration, max_iters)
            maybe_emit_periodic_ci_tick()

            bundle = EvidenceBundle(
                run_id=run_context.run_id,
                slice_id=slice_ref.slice_id,
                iteration=iteration,
                created_at=_now_iso(),
                mode=run_context.mode,
                workspace_root=run_context.workspace_root,
                slice_root=slice_ref.worktree_path,
            )
            if iteration == 1 and seed_gap_set and seed_gap_set.open_gaps:
                bundle.gaps.open_gaps = [
                    _normalize_gap_record(gap)
                    for gap in seed_gap_set.open_gaps
                    if isinstance(gap, dict)
                ]
                bundle.gaps.path = "gaps.json"

            retry = False
            waiting = False
            step_statuses: dict[str, str] = {}

            for step in active_steps:
                maybe_emit_periodic_ci_tick()
                logger.debug("Running step: %s", step.name)
                result = step.run(ctx, bundle)
                if step.name == "GAP_EXPLORATION" and result.status == "OK":
                    question = self._register_gap_queue_stagnation_under_spec(ctx, bundle)
                    if question:
                        logger.warning(
                            "Slice '%s': GapQueue stagnation detected; terminating as STAGNATED",
                            ctx.slice_id,
                        )
                        stagnation_result = StepResult(status="FAIL", error=question)
                        self._record_provenance(bundle, step.name, stagnation_result, ctx)
                        self._refresh_facts(bundle)
                        bundle.status = "FAILED"
                        self._persist_iteration_artifacts(ctx, bundle)
                        bundle.save(evidence_root)
                        return SliceResult(
                            slice_id=ctx.slice_id,
                            status="STAGNATED",
                            iterations=iteration,
                            remaining_gaps=len(bundle.gaps.open_gaps),
                            demotion_tickets=all_tickets,
                            error=question,
                        )

                if result.emitted_tickets:
                    all_tickets.extend(result.emitted_tickets)
                    # Apply demotion tickets + track retries per unique failure pattern
                    seen_keys: set[tuple[str, str]] = set()
                    for ticket in result.emitted_tickets:
                        apply_result = self._dm.apply(ticket, Path(ctx.slice_root))
                        bundle.demotions.emitted.append(ticket.ticket_id)
                        if apply_result.get("applied", False):
                            bundle.demotions.applied.append(ticket.ticket_id)
                        else:
                            bundle.demotions.pending.append(ticket.ticket_id)
                        files_key = (
                            ",".join(sorted(ticket.failing_files)) if ticket.failing_files else ""
                        )
                        gate_key = ticket.gate or ticket.source or ""
                        tracker_key = (files_key, gate_key)
                        seen_keys.add(tracker_key)

                    # Increment once per unique pattern per iteration (not per ticket)
                    for tracker_key in seen_keys:
                        retry_tracker[tracker_key] = retry_tracker.get(tracker_key, 0) + 1
                        if retry_tracker[tracker_key] > retry_budget:
                            logger.warning(
                                "Slice '%s': per-ticket retry budget exceeded "
                                "for (%s, %s) — escalating",
                                ctx.slice_id,
                                tracker_key[0],
                                tracker_key[1],
                            )
                            bundle.status = "FAILED"
                            self._persist_iteration_artifacts(ctx, bundle)
                            bundle.save(evidence_root)
                            return SliceResult(
                                slice_id=ctx.slice_id,
                                status="STAGNATED",
                                iterations=iteration,
                                remaining_gaps=len(bundle.gaps.open_gaps),
                                demotion_tickets=all_tickets,
                                error=f"Per-ticket retry budget exceeded for gate={tracker_key[1]}",
                            )

                self._record_provenance(bundle, step.name, result, ctx)
                self._refresh_facts(bundle)
                self._persist_iteration_artifacts(ctx, bundle)
                saved_bundle_path = bundle.save(evidence_root)
                if not result.bundle_path:
                    result.bundle_path = str(saved_bundle_path)
                step_statuses[step.name] = result.status

                if result.status == "OK":
                    next_bundle_path = Path(result.bundle_path)
                    if not next_bundle_path.is_absolute():
                        next_bundle_path = saved_bundle_path.parent / next_bundle_path
                    try:
                        bundle = EvidenceBundle.load(next_bundle_path)
                    except Exception as exc:
                        logger.exception(
                            "Failed loading bundle handoff for step %s at %s",
                            step.name,
                            next_bundle_path,
                        )
                        return SliceResult(
                            slice_id=ctx.slice_id,
                            status="FAILED",
                            iterations=iteration,
                            demotion_tickets=all_tickets,
                            error=f"Bundle handoff failed after {step.name}: {exc}",
                        )

                if result.status == "WAITING":
                    # Slice needs coordination — save bundle and return WAITING
                    waiting = True
                    break

                if result.status == "BLOCKED":
                    # Slice is blocked — return with blocked status
                    bundle.status = "BLOCKED"
                    self._persist_iteration_artifacts(ctx, bundle)
                    bundle.save(evidence_root)
                    questions = []
                    for event in bundle.implementation.under_spec_events:
                        if q := event.get("question"):
                            questions.append(q)
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="BLOCKED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        blocked_questions=questions,
                    )

                if result.status == "RETRY":
                    # A gate/test/merge failed — restart iteration
                    retry = True
                    break

                if result.status == "FAIL":
                    bundle.status = "FAILED"
                    self._persist_iteration_artifacts(ctx, bundle)
                    bundle.save(evidence_root)
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="FAILED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        error=result.error,
                    )

            # Handle WAITING: save bundle and return to scheduler
            if waiting:
                waiting_iterations += 1
                # Collect pending signal info from bundle
                pending = [
                    {"question": e.get("question", ""), "kind": e.get("kind", "")}
                    for e in (bundle.implementation.under_spec_events or [])
                ]
                return SliceResult(
                    slice_id=ctx.slice_id,
                    status="WAITING",
                    iterations=iteration,
                    remaining_gaps=len(bundle.gaps.open_gaps),
                    demotion_tickets=all_tickets,
                    pending_signals=pending,
                    wake_count=waiting_iterations,
                )

            if retry:
                continue

            # Check termination
            remaining = len(bundle.gaps.open_gaps)
            unresolved_slice_demotions = len(bundle.demotions.pending)
            refinement_issue_count = self._refinement_issue_count(ctx, bundle)
            refinement_issue_threshold = self._refinement_issue_threshold(ctx)
            configured_steps = {step.name for step in active_steps}
            required_steps = tuple(
                step_name
                for step_name in ("PROMOTE", "INTEGRATE", "VERIFY", "ALIGN")
                if step_name in configured_steps
            )
            required_steps_ok = all(
                step_statuses.get(step_name) == "OK" for step_name in required_steps
            )
            if remaining == 0:
                completion_failures: list[str] = []
                if unresolved_slice_demotions > 0:
                    completion_failures.append(
                        f"unresolved_demotion_tickets={unresolved_slice_demotions}"
                    )
                if refinement_issue_count > refinement_issue_threshold:
                    completion_failures.append(
                        "refinement_threshold_failed"
                        f"({refinement_issue_count}>{refinement_issue_threshold})"
                    )
                if not required_steps_ok:
                    completion_failures.append("required_gates_not_all_ok")

                if completion_failures:
                    bundle.status = "FAILED"
                    self._persist_iteration_artifacts(ctx, bundle)
                    bundle.save(evidence_root)
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="STAGNATED",
                        iterations=iteration,
                        remaining_gaps=0,
                        demotion_tickets=all_tickets,
                        error="; ".join(completion_failures),
                    )

                bundle.status = "COMPLETE"
                self._persist_iteration_artifacts(ctx, bundle)
                bundle.save(evidence_root)
                return SliceResult(
                    slice_id=ctx.slice_id,
                    status="COMPLETE",
                    iterations=iteration,
                    remaining_gaps=0,
                    demotion_tickets=all_tickets,
                )

            # Still gaps — loop
            logger.info(
                "Slice '%s': %d gaps remaining (unresolved_demotions=%d), continuing",
                ctx.slice_id,
                remaining,
                unresolved_slice_demotions,
            )

        # Max iterations reached
        if bundle:
            bundle.status = "FAILED"
            self._persist_iteration_artifacts(ctx, bundle)
            bundle.save(evidence_root)
        return SliceResult(
            slice_id=ctx.slice_id,
            status="MAX_ITERATIONS",
            iterations=iteration,
            remaining_gaps=len(bundle.gaps.open_gaps) if bundle else 0,
            demotion_tickets=all_tickets,
        )

    def run_slices(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
    ) -> list[SliceResult]:
        """Run the promotion loop on multiple slices sequentially.

        For parallel execution, use ReactivePromotionScheduler instead.

        Args:
            slice_refs: Slices to process.
            run_context: Run-scoped configuration.

        Returns:
            List of SliceResults.
        """
        results = []
        for ref in slice_refs:
            result = self.run_slice(ref, run_context)
            results.append(result)

            if result.status == "FAILED":
                logger.error("Slice '%s' failed: %s", ref.slice_id, result.error)
                # Continue with other slices rather than aborting

        return results

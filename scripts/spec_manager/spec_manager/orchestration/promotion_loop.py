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
    PLAN               (P8, planner-authoritative for all layers)
      ↓
    IMPLEMENT          (P9) ← emits patch + pin/edge proposals + evidence
      ↓
    COORDINATE         (reactive triage / monitor registration)
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
import re
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

from spec_manager.core.layer_types import Layer
from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
from spec_manager.orchestration.downward_flow.engine import DownwardFlowEngine, FailureEvidence
from spec_manager.orchestration.evidence import EvidenceBundle
from spec_manager.schemas.lineage import RelationshipFacts

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


def _gate_source_for_layer(layer: str) -> Literal["ALGORITHMIC_GATE", "ARCH_GATE"]:
    normalized = str(layer).strip().upper()
    if normalized == "L1":
        return "ALGORITHMIC_GATE"
    return "ARCH_GATE"


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


def _max_persisted_iteration(base: Path, run_id: str, slice_id: str) -> int:
    """Return the highest persisted iteration index for a slice."""
    if not run_id or not slice_id:
        return 0
    slices_root = base / ".pdd_runs" / run_id / "slices" / slice_id
    if not slices_root.exists():
        return 0

    latest = 0
    for candidate in slices_root.glob("iter_*"):
        if not candidate.is_dir():
            continue
        try:
            iter_num = int(candidate.name.split("_")[-1])
        except (TypeError, ValueError):
            continue
        latest = max(latest, iter_num)
    return latest


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
        logger.debug("JSON artifact missing or not a file: %s", path)
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Failed to read JSON artifact %s: %s", path, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON artifact %s: %s", path, exc)
        return None
    if isinstance(loaded, dict | list):
        return loaded
    logger.warning(
        "JSON artifact %s has unsupported top-level type: %s",
        path,
        type(loaded).__name__,
    )
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


def _canonical_signal(value: Any) -> str:
    """Normalize relationship signal labels into canonical categories."""
    if not isinstance(value, str):
        return "REFERENCE"
    signal = value.strip().upper()
    if signal in {"CALL", "CALLS"}:
        return "CALL"
    if signal in {"STORE_TOUCH", "AGGREGATION"}:
        return "STORE_TOUCH"
    if signal in {"EVENT", "EVENT_EMIT", "EVENT_HANDLE"}:
        return "EVENT"
    return "REFERENCE"


def _append_unique_record(records: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    """Append candidate record when no structurally-equal record exists."""
    fingerprint = json.dumps(candidate, sort_keys=True)
    for existing in records:
        if json.dumps(existing, sort_keys=True) == fingerprint:
            return
    records.append(candidate)


def _build_l1_source_entry(
    *,
    relative_path: str,
    content_hash: str,
    source_analysis: Any,
    file_facts_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build source-index entry from canonical file facts."""
    analysis_functions = [asdict(fn) for fn in getattr(source_analysis, "functions", [])]
    analysis_comments = [asdict(comment) for comment in getattr(source_analysis, "comments", [])]
    analysis_facets = getattr(source_analysis, "facets", {})
    return {
        "path": relative_path,
        "content_hash": content_hash,
        "analysis": {
            "functions": analysis_functions,
            "comments": analysis_comments,
            "facets": analysis_facets if isinstance(analysis_facets, dict) else {},
            "file_facts": file_facts_payload,
        },
    }


def _extract_file_facts_payload(entry: dict[str, Any]) -> dict[str, Any]:
    """Load canonical file-facts payload from a source-index entry."""
    analysis = entry.get("analysis")
    if not isinstance(analysis, dict):
        return {}
    payload = analysis.get("file_facts")
    return payload if isinstance(payload, dict) else {}


def _merge_file_facts_payload(bundle: EvidenceBundle, payload: dict[str, Any]) -> None:
    """Merge canonical file-facts projection into bundle-level facts."""
    functions = payload.get("functions", {})
    if isinstance(functions, dict) and functions:
        bundle.facts.functions.update(functions)

    for key in ("stub_nodes", "remaining_gap_pins", "call_graph_edges"):
        records = payload.get(key, [])
        if not isinstance(records, list):
            continue
        target = getattr(bundle.facts, key)
        for record in records:
            if isinstance(record, dict):
                _append_unique_record(target, record)

    call_graph_nodes = payload.get("call_graph_nodes", [])
    if isinstance(call_graph_nodes, list):
        merged_nodes = {
            str(node).strip() for node in bundle.facts.call_graph_nodes if str(node).strip()
        }
        merged_nodes.update(str(node).strip() for node in call_graph_nodes if str(node).strip())
        bundle.facts.call_graph_nodes = sorted(merged_nodes)

    stores = payload.get("stores", {})
    if isinstance(stores, dict):
        for store_id, store_data in stores.items():
            store_key = str(store_id).strip()
            if not store_key:
                continue
            existing = bundle.facts.stores.get(store_key, {})
            if not isinstance(existing, dict):
                existing = {}
            incoming = store_data if isinstance(store_data, dict) else {}
            owners = sorted(set(existing.get("owner_atoms", []) + incoming.get("owner_atoms", [])))
            bundle.facts.stores[store_key] = {
                "owner_atoms": owners,
                "schema": incoming.get("schema", existing.get("schema", {})),
            }

    store_owners = payload.get("store_owners", {})
    if isinstance(store_owners, dict):
        for store_id, owners in store_owners.items():
            store_key = str(store_id).strip()
            if not store_key or not isinstance(owners, list):
                continue
            merged = set(bundle.facts.store_owners.get(store_key, []))
            merged.update(str(owner).strip() for owner in owners if str(owner).strip())
            if merged:
                bundle.facts.store_owners[store_key] = sorted(merged)

    test_hints = payload.get("test_identity_hints", [])
    if isinstance(test_hints, list):
        for hint in test_hints:
            if isinstance(hint, dict):
                claim = {
                    "claim": f"test_identity_hint:{hint.get('kind', 'hint')}",
                    "evidence_refs": [hint.get("file", "")] if hint.get("file") else [],
                    "confidence": 0.8,
                    "produced_by_step": "ANALYZE",
                    "details": hint,
                }
                _append_unique_record(bundle.facts.llm_claims, claim)

    if (
        bundle.facts.functions
        or bundle.facts.stores
        or bundle.facts.remaining_gap_pins
        or bundle.facts.stub_nodes
        or bundle.facts.call_graph_nodes
        or bundle.facts.call_graph_edges
        or bundle.facts.store_owners
        or bundle.facts.llm_claims
    ):
        bundle.facts.path = "facts.json"


def _reverse_pseudocode_payload_from_analysis(
    *,
    relative_path: str,
    functions: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project comment-to-function groupings without invoking parse_file adapters."""
    by_qualified: dict[str, dict[str, Any]] = {}
    by_simple: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fn in functions:
        if not isinstance(fn, dict):
            continue
        qn = str(fn.get("qualified_name") or fn.get("name") or "").strip()
        if not qn:
            continue
        by_qualified[qn] = fn
        by_simple[str(fn.get("name") or "").strip()].append(fn)

    grouped_comments: dict[str, list[str]] = defaultdict(list)
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        text = str(comment.get("text", "")).strip()
        if not text:
            continue
        enclosing = str(comment.get("enclosing_function") or "").strip()
        if not enclosing:
            continue
        grouped_comments[enclosing].append(text)

    payload: list[dict[str, Any]] = []
    for enclosing, comment_texts in grouped_comments.items():
        fn = by_qualified.get(enclosing)
        if fn is None:
            candidates = by_simple.get(enclosing, [])
            fn = candidates[0] if candidates else None
        if fn is None:
            continue
        qualified = str(fn.get("qualified_name") or fn.get("name") or "").strip()
        class_name = ""
        if "." in qualified:
            class_name = ".".join(qualified.split(".")[:-1]).strip()
        payload.append(
            {
                "file": relative_path,
                "function": str(fn.get("name", "")),
                "class_name": class_name,
                "start_line": fn.get("start_line"),
                "end_line": fn.get("end_line"),
                "comments": comment_texts,
            }
        )
    return payload


def _gaps_from_file_facts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Project canonical gap pins to L1 gap-exploration records."""
    gaps: list[dict[str, Any]] = []
    for pin in payload.get("remaining_gap_pins", []):
        if not isinstance(pin, dict):
            continue
        span = _location_span(
            start_line=(pin.get("span") or {}).get("start_line"),
            end_line=(pin.get("span") or {}).get("end_line"),
            start_col=(pin.get("span") or {}).get("start_col"),
            end_col=(pin.get("span") or {}).get("end_col"),
        )
        file_path = str(pin.get("file", "")).strip()
        gaps.append(
            {
                "file": file_path,
                "description": str(pin.get("description", "")).strip(),
                "kind": str(pin.get("kind", "gap")).strip() or "gap",
                "span": span,
                "location": {"file": file_path, **span},
            }
        )
    return gaps


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
    last_signal_id: str = ""
    wake_payload: dict[str, Any] = field(default_factory=dict)
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
        result: StepResult
        if ctx.layer == "l1":
            result = self._explore_l1(ctx, bundle)
        elif ctx.layer == "l2":
            result = self._explore_l2(ctx, bundle)
        elif ctx.layer == "l3":
            result = self._explore_l3(ctx, bundle)
        else:
            result = StepResult(status="OK")

        if result.status == "OK":
            self._run_gap_planner_pass(ctx, bundle)
        return result

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

    def _run_gap_planner_pass(self, ctx: SliceContext, bundle: EvidenceBundle) -> None:
        """Run planner GAP post-processing over collected raw gaps."""
        if self._planner is None:
            return

        raw_gaps = [dict(gap) for gap in (bundle.gaps.open_gaps or []) if isinstance(gap, dict)]
        bundle.gaps.open_gaps = raw_gaps
        bundle.gaps.analysis = dict(bundle.gaps.analysis or {})

        try:
            from spec_manager.planner.api import PlanningContext, PlanningRequest

            planning_ctx = PlanningContext(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                iteration=bundle.iteration,
                layer=ctx.layer,
                mode=ctx.mode,
                workspace_root=ctx.workspace_root,
                slice_root=ctx.slice_root,
                bundle_ref=bundle,
                metadata={
                    "changed_files": list(bundle.diff.changed_files or []),
                },
            )
            result = self._planner.plan(
                PlanningRequest(
                    capability="GAP",
                    context=planning_ctx,
                    inputs={"raw_gaps": raw_gaps},
                )
            )
            outputs = getattr(result, "outputs", {})
            safe_outputs = outputs if isinstance(outputs, dict) else {}
            bundle.gaps.planner_outputs = safe_outputs

            curated_raw = (
                safe_outputs.get("gaps")
                or safe_outputs.get("prioritized_gaps")
                or safe_outputs.get("clustered_gaps")
                or []
            )
            if isinstance(curated_raw, list):
                curated = [self._normalize_gap(gap) for gap in curated_raw if isinstance(gap, dict)]
                if curated:
                    bundle.gaps.open_gaps = curated

            decision_requirements_raw = safe_outputs.get("decision_requirements", [])
            decision_requirements = (
                [item for item in decision_requirements_raw if isinstance(item, dict)]
                if isinstance(decision_requirements_raw, list)
                else []
            )
            integration_notes = safe_outputs.get("integration_notes", [])
            if not isinstance(integration_notes, list):
                integration_notes = []

            bundle.gaps.analysis.update(
                {
                    "planner_status": str(getattr(result, "status", "OK")),
                    "planner_trace_id": str(getattr(result, "trace_id", "")),
                    "raw_gap_count": len(raw_gaps),
                    "curated_gap_count": len(bundle.gaps.open_gaps or []),
                    "decision_requirements": decision_requirements,
                    "integration_notes": integration_notes,
                }
            )
        except Exception as exc:
            logger.debug("Planner GAP post-processing failed: %s", exc, exc_info=True)

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
        """Resolve L2 topology via planner GAP discovery only."""
        if self._planner is None:
            return {
                "nodes": [],
                "edges": [],
                "arch_files": [],
                "discovery_status": "incomplete",
                "discovery_issues": ["L2 topology discovery requires planner wiring."],
            }

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
            return {
                "nodes": [],
                "edges": [],
                "arch_files": [],
                "discovery_status": "incomplete",
                "discovery_issues": ["Planner GAP response did not include a discovery payload."],
            }
        except Exception as exc:
            logger.warning("Planner L2 discovery failed: %s", exc, exc_info=True)
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

    def _infer_promoted_evidence(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        slice_root: Path,
        arch_artifacts: list[dict[str, str]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Infer promoted pin/edge evidence via LLM code signals when stored evidence is missing."""
        from spec_manager.core.code_analysis import infer_code_signals
        from spec_manager.core.language import source_rglob

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else slice_root
        candidate_files: list[tuple[str, str]] = []

        for artifact in arch_artifacts:
            rel_path = str(artifact.get("path", "")).strip()
            if not rel_path:
                continue
            content = str(artifact.get("content", ""))
            if not content:
                candidate = slice_root / rel_path
                if candidate.exists() and candidate.is_file():
                    try:
                        content = candidate.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        content = ""
            if content:
                candidate_files.append((rel_path, content))

        if not candidate_files:
            for candidate in source_rglob(slice_root):
                try:
                    rel_path = str(candidate.relative_to(slice_root))
                    content = candidate.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                candidate_files.append((rel_path, content))

        inferred_edges: list[dict[str, Any]] = []
        seen_edges: set[str] = set()
        pin_ids: set[str] = set()
        for rel_path, content in candidate_files:
            try:
                signals = infer_code_signals(
                    file_path=rel_path,
                    source_text=content,
                    spans=[],
                    requested={"import_edges", "relationship_edges"},
                    workspace=workspace,
                    run_id=ctx.run_id or bundle.run_id,
                )
            except Exception as exc:
                logger.debug("L2 promoted-evidence inference failed for %s: %s", rel_path, exc)
                continue

            raw_edges = []
            for key in ("import_edges", "relationship_edges", "edges"):
                value = signals.get(key)
                if isinstance(value, list):
                    raw_edges.extend(item for item in value if isinstance(item, dict))

            for edge in raw_edges:
                src = str(
                    edge.get("pin_func_id")
                    or edge.get("src")
                    or edge.get("src_id")
                    or edge.get("imported_name")
                    or ""
                ).strip()
                dst = str(
                    edge.get("arch_location")
                    or edge.get("dst")
                    or edge.get("dst_id")
                    or edge.get("importer_location")
                    or ""
                ).strip()
                if not src or not dst:
                    continue
                signal = _canonical_signal(edge.get("signal_type"))
                projection_type = str(edge.get("projection_type") or "").strip().lower()
                if not projection_type:
                    if signal == "EVENT":
                        projection_type = "event_bridge"
                    elif signal == "STORE_TOUCH":
                        projection_type = "aggregation"
                    else:
                        projection_type = "pass_through"
                arch_file_path = str(edge.get("arch_file_path") or rel_path).strip()
                edge_fingerprint = f"{src}|{dst}|{projection_type}|{arch_file_path}"
                if edge_fingerprint in seen_edges:
                    continue
                seen_edges.add(edge_fingerprint)
                line_raw = edge.get("line_no") or edge.get("line") or 0
                try:
                    arch_line = int(line_raw)
                except (TypeError, ValueError):
                    arch_line = 0
                confidence_raw = edge.get("confidence", 0.6)
                try:
                    confidence = float(confidence_raw)
                except (TypeError, ValueError):
                    confidence = 0.6
                inferred_edges.append(
                    {
                        "pin_func_id": src,
                        "src": src,
                        "arch_location": dst,
                        "dst": dst,
                        "arch_file_path": arch_file_path,
                        "arch_line": arch_line,
                        "projection_type": projection_type,
                        "signal_type": signal,
                        "confidence": confidence,
                        "is_direct_import": bool(edge.get("is_direct_import", False)),
                    }
                )
                pin_ids.add(src)

        inferred_pins = [
            {
                "pin_func_id": pin_id,
                "function_name": pin_id.rsplit(".", 1)[-1],
                "module_path": pin_id.rsplit(".", 1)[0] if "." in pin_id else "",
                "file_path": "",
                "line_start": 0,
                "line_end": 0,
                "signature": "",
                "docstring": "",
                "content_hash": "",
                "is_shape": False,
                "store_touches": [],
                "evidence_atom_ids": [],
            }
            for pin_id in sorted(pin_ids)
        ]
        return {"pins": inferred_pins, "edges": inferred_edges}

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

        try:
            gaps: list[dict[str, Any]] = []

            for entry in bundle.source_index.entries or []:
                if not isinstance(entry, dict):
                    continue
                payload = _extract_file_facts_payload(entry)
                if not payload:
                    continue
                _merge_file_facts_payload(bundle, payload)
                for gap in _gaps_from_file_facts(payload):
                    _append_unique_record(gaps, gap)

            for gap in bundle.facts.remaining_gap_pins or []:
                if isinstance(gap, dict):
                    _append_unique_record(gaps, gap)

            normalized = [self._normalize_gap(g) for g in gaps]
            if bundle.source_index.entries:
                bundle.source_index.path = "source_analysis.index.json"
            bundle.gaps = GapReportRef(path="gaps.json", open_gaps=normalized)
            self._merge_gap_queue(self._report_from_gap_records(normalized), bundle)
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
            inferred = self._infer_promoted_evidence(
                ctx=ctx,
                bundle=bundle,
                slice_root=slice_root,
                arch_artifacts=arch_artifacts,
            )
            promoted_pins = [item for item in inferred.get("pins", []) if isinstance(item, dict)]
            promoted_edges = [item for item in inferred.get("edges", []) if isinstance(item, dict)]
            if promoted_pins or promoted_edges:
                claims = [
                    item for item in (bundle.facts.llm_claims or []) if isinstance(item, dict)
                ]
                claims.append(
                    {
                        "claim": "Inferred promoted pin/edge evidence via code-analysis signals.",
                        "evidence_refs": [bundle.gaps.path] if bundle.gaps.path else [],
                        "confidence": 0.6,
                        "produced_by_step": "GAP_EXPLORATION",
                    }
                )
                bundle.facts.llm_claims = claims
            else:
                gaps.append(
                    self._l2_gap(
                        kind="l2_promoted_evidence_inference_failed",
                        component_id="",
                        file_path=str(slice_root / ".spec" / "pin_registry.json"),
                        anchor="promoted_pin_edge_evidence",
                        description=(
                            "Promoted pin/edge evidence was missing and inference returned "
                            "no usable relationship edges."
                        ),
                        expected=(
                            "Inference fallback should produce promotable adjacency evidence "
                            "when stored pin/edge artifacts are missing."
                        ),
                        severity="MAJOR",
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

    - L1: Planner emits direct-implementation intentions from spec-comment authority.
    - L2: Convert architecture gaps into a wiring plan (which component
      to adjust, how to connect pins, handlers/routes to add)
    - L3: Convert quality findings into a refactor plan (group by
      function/span, sequence smallest safe refactors first, define
      "no behavior change" acceptance criteria)

    After generating intentions, checks decision requirements against
    the constraints store.  Uncovered decisions become under-spec events
    that block the slice before implementation begins.

    PLAN is planner-authoritative for all layers. Legacy static planning
    fallbacks are intentionally removed.
    """

    name = "PLAN"

    def __init__(self, planner: Any = None, resolver: Any = None) -> None:
        self._planner = planner
        self._resolver = resolver

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

    @staticmethod
    def _constraints_context_for_planner(
        ctx: SliceContext,
        bundle: EvidenceBundle,
    ) -> dict[str, Any]:
        """Build constraints context so PLAN can reason over existing decisions."""
        constraints_refs: list[str] = []
        for ref in bundle.facts.constraints_refs or []:
            cleaned = str(ref).strip()
            if cleaned and cleaned not in constraints_refs:
                constraints_refs.append(cleaned)

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else None
        if workspace is None:
            return {"constraints_refs": constraints_refs}

        try:
            from spec_manager.planner.constraints.store import ConstraintsStore

            store = ConstraintsStore(workspace)
            merged_constraints = store.load_merged(ctx.slice_id)
            active_constraints = [
                constraint
                for constraint in merged_constraints
                if str(constraint.status or "ACTIVE").strip().upper() == "ACTIVE"
            ]
            constraints_summary = [
                {
                    "constraint_id": str(constraint.constraint_id).strip(),
                    "question": str(constraint.question).strip(),
                    "answer": str(constraint.answer).strip(),
                    "dimension": str(constraint.dimension).strip(),
                    "authority_required": str(constraint.authority_required).strip(),
                    "decision_type": str(constraint.decision_type).strip(),
                    "scope": str(constraint.scope).strip(),
                    "applies_to_layers": [
                        str(layer).strip() for layer in constraint.applies_to_layers
                    ],
                }
                for constraint in active_constraints
            ]
            for derived_path in (
                workspace / "analysis" / "constraints" / "__system__.json",
                workspace / "analysis" / "constraints" / f"{ctx.slice_id}.json",
            ):
                path_str = str(derived_path)
                if path_str not in constraints_refs:
                    constraints_refs.append(path_str)
            return {
                "constraints_refs": constraints_refs,
                "constraints_summary": constraints_summary,
                "constraints_snapshot_hash": store.snapshot_hash(ctx.slice_id),
            }
        except Exception as exc:
            logger.warning(
                "Failed to load constraints context for PLAN slice %s: %s",
                ctx.slice_id,
                exc,
                exc_info=True,
            )
            return {
                "constraints_refs": constraints_refs,
                "load_error": str(exc),
            }

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Generate layer-appropriate implementation plan from gaps."""
        from spec_manager.orchestration.evidence import PlanRef

        if not bundle.gaps.open_gaps:
            bundle.plan = PlanRef(path="plan.json", intentions=[], plan_artifacts={})
            return StepResult(status="OK")

        if self._planner is None:
            return StepResult(
                status="FAIL",
                error="Planner is required for PLAN step execution.",
            )

        plan_outputs = self._plan_via_planner(ctx, bundle)
        intentions = plan_outputs.get("intentions", [])
        if not isinstance(intentions, list):
            intentions = []

        focus_targets = self._focus_targets(ctx)
        intentions = self._apply_focus_targets(intentions, focus_targets)
        plan_outputs["intentions"] = intentions
        plan_artifacts_raw = plan_outputs.get("plan_artifacts", {})
        plan_artifacts = plan_artifacts_raw if isinstance(plan_artifacts_raw, dict) else {}
        bundle.plan = PlanRef(
            path="plan.json",
            intentions=intentions,
            plan_artifacts=plan_artifacts,
            under_spec_events=[],
            under_spec_events_path="",
            constraints_snapshot_hash="",
        )

        # Run planning gate: check decision requirements against constraints
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else None
        if workspace is None:
            return StepResult(
                status="BLOCKED",
                error=(
                    "Planning gate unavailable: workspace_root is required to "
                    "validate decision requirements against constraints."
                ),
            )

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
                plan_outputs=plan_outputs,
            )
            bundle.plan.constraints_snapshot_hash = str(
                gate_result.constraints_snapshot_hash
            ).strip()
            bundle.plan.under_spec_events = list(gate_result.under_spec_events)

            if not gate_result.all_covered:
                coordinate_step = CoordinateStep(
                    planner=self._planner,
                    resolver=self._resolver,
                )
                return coordinate_step._resolve_under_spec(
                    ctx,
                    bundle,
                    raw_events=bundle.plan.under_spec_events,
                    source="plan",
                )
        except Exception as exc:
            logger.warning(
                "Planning gate failed for slice %s: %s", ctx.slice_id, exc, exc_info=True
            )
            return StepResult(
                status="BLOCKED",
                error=f"Planning gate failed: {exc}",
            )

        return StepResult(status="OK")

    def _plan_via_planner(self, ctx: SliceContext, bundle: EvidenceBundle) -> dict[str, Any]:
        """Route plan generation through the planner module.

        Returns the full planner output payload with normalized intentions.
        """
        from spec_manager.planner.api import PlanningContext, PlanningRequest

        constraints_context = self._constraints_context_for_planner(ctx, bundle)

        planning_ctx = PlanningContext(
            run_id=ctx.run_id,
            slice_id=ctx.slice_id,
            iteration=bundle.iteration,
            layer=ctx.layer,
            mode=ctx.mode,
            workspace_root=ctx.workspace_root,
            slice_root=ctx.slice_root,
            bundle_ref=bundle,
            metadata={
                "focus_targets": self._focus_targets(ctx),
                "constraints_context": constraints_context,
            },
        )
        gap_analysis: dict[str, Any] = {}
        if isinstance(bundle.gaps.analysis, dict):
            gap_analysis.update(bundle.gaps.analysis)
        if isinstance(bundle.gaps.planner_outputs, dict) and bundle.gaps.planner_outputs:
            gap_analysis["gap_planner_outputs"] = dict(bundle.gaps.planner_outputs)
        if isinstance(bundle.gaps.stagnation, dict) and bundle.gaps.stagnation:
            gap_analysis["gap_queue_stagnation"] = dict(bundle.gaps.stagnation)

        prior_artifacts: dict[str, Any] = {
            "source_index_entries": list(bundle.source_index.entries or []),
            "facts": {
                "functions": dict(bundle.facts.functions or {}),
                "stores": dict(bundle.facts.stores or {}),
                "atoms": dict(bundle.facts.atoms or {}),
                "remaining_gap_pins": list(bundle.facts.remaining_gap_pins or []),
            },
            "previous_plan_artifacts": dict(bundle.plan.plan_artifacts or {}),
            "under_spec_decisions": list(bundle.under_spec.decisions or []),
            "constraints_context": constraints_context,
        }

        result = self._planner.plan(
            PlanningRequest(
                capability="PLAN",
                context=planning_ctx,
                inputs={
                    "gaps": bundle.gaps.open_gaps,
                    "gap_analysis": gap_analysis,
                    "prior_artifacts": prior_artifacts,
                    "constraints_context": constraints_context,
                },
            )
        )
        plan_outputs = result.outputs if hasattr(result, "outputs") else {}
        if not isinstance(plan_outputs, dict):
            return {"intentions": [], "plan_artifacts": {}}

        intentions_raw = plan_outputs.get("intentions", [])
        if not isinstance(intentions_raw, list):
            intentions_raw = []
        normalized_outputs = dict(plan_outputs)
        normalized_outputs["intentions"] = [row for row in intentions_raw if isinstance(row, dict)]
        artifacts_raw = normalized_outputs.get("plan_artifacts")
        if isinstance(artifacts_raw, dict):
            normalized_outputs["plan_artifacts"] = dict(artifacts_raw)
        else:
            normalized_outputs["plan_artifacts"] = {
                key: value for key, value in normalized_outputs.items() if key != "intentions"
            }
        return normalized_outputs


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
            "pin_proposals_path": bundle.implementation.pin_proposals_path,
            "edge_proposals_path": bundle.implementation.edge_proposals_path,
            "under_spec_events_path": bundle.implementation.under_spec_events_path,
            "tests_added_path": bundle.implementation.tests_added_path,
            "notes_path": bundle.implementation.notes_path,
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
        import json

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
            iteration_dir.mkdir(parents=True, exist_ok=True)
            focus_targets = self._focus_targets(ctx)
            prioritized_gap_report = self._prioritize_gap_report(
                bundle.gaps.open_gaps, focus_targets
            )

            plan_path = iteration_dir / (bundle.plan.path or "plan.json")
            if not plan_path.exists():
                plan_path.write_text(
                    json.dumps(
                        {
                            "intentions": bundle.plan.intentions,
                            "plan_artifacts": bundle.plan.plan_artifacts,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            gaps_path = iteration_dir / (bundle.gaps.path or "gaps.json")
            if not gaps_path.exists():
                gaps_path.write_text(
                    json.dumps({"open_gaps": prioritized_gap_report}, indent=2),
                    encoding="utf-8",
                )

            constraints_paths: list[Path] = []
            for ref in bundle.facts.constraints_refs or []:
                cleaned = str(ref).strip()
                if not cleaned:
                    continue
                candidate = Path(cleaned)
                if not candidate.is_absolute():
                    candidate = workspace / candidate
                constraints_paths.append(candidate)

            run_result = runner.run_for_slice(
                slice_root=slice_root,
                slice_id=ctx.slice_id,
                iteration=bundle.iteration,
                iteration_dir=iteration_dir,
                plan_path=plan_path,
                gaps_path=gaps_path,
                constraints_paths=constraints_paths,
            )

            pin_proposals = (
                _read_json_file(iteration_dir / run_result.pin_proposals_path)
                if run_result.pin_proposals_path
                else []
            )
            if not isinstance(pin_proposals, list):
                pin_proposals = run_result.pin_proposals

            edge_proposals = (
                _read_json_file(iteration_dir / run_result.edge_proposals_path)
                if run_result.edge_proposals_path
                else []
            )
            if not isinstance(edge_proposals, list):
                edge_proposals = run_result.edge_proposals

            under_spec_events = (
                _read_json_file(iteration_dir / run_result.under_spec_events_path)
                if run_result.under_spec_events_path
                else []
            )
            if not isinstance(under_spec_events, list):
                under_spec_events = run_result.under_spec_events

            prioritized_gaps = self._prioritize_gap_report(bundle.gaps.open_gaps, focus_targets)
            gap_inventory = self._gaps_from_under_spec_events(under_spec_events)
            if not gap_inventory and prioritized_gaps:
                gap_inventory.extend(prioritized_gaps)
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
                pin_proposals_path=run_result.pin_proposals_path,
                edge_proposals_path=run_result.edge_proposals_path,
                under_spec_events_path=run_result.under_spec_events_path,
                tests_added_path=run_result.tests_added_path,
                notes_path=run_result.notes_path,
                applied_edits=run_result.applied_edits,
                gap_inventory=gap_inventory,
                pin_proposals=pin_proposals,
                edge_proposals=edge_proposals,
                under_spec_events=under_spec_events,
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
                        source="ALGORITHMIC_GATE" if target == "L1" else "ARCH_GATE",
                        origin_layer="L3",
                        hop_trace=["L3", target],
                        target_layer=target,
                        severity=severity,
                        diagnosis=reason,
                        failing_files=[file_path] if file_path else [],
                        symbol_span_anchors=[{"file": file_path}] if file_path else [],
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

    - L1: triage under-spec events as coordination signals and park slice in
      WAITING while monitors watch for dependencies to resolve.
    - L2/L3: resolve under-spec events through UnderSpecManager (resolve/wait/block).
    """

    name = "COORDINATE"

    def __init__(self, planner: Any = None, resolver: Any = None) -> None:
        self._planner = planner
        self._resolver = resolver

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Resolve under-spec events for the active layer."""
        if ctx.layer == "l1":
            return self._coordinate_l1(ctx, bundle)
        return self._resolve_under_spec(ctx, bundle)

    def _coordinate_l1(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Triage L1 under-spec events into monitors and return WAITING."""
        raw_events = [
            e for e in (bundle.implementation.under_spec_events or []) if isinstance(e, dict)
        ]
        if not raw_events:
            return StepResult(status="OK")

        signals = self._load_l1_signals(ctx, bundle, raw_events)
        triage_decisions: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        resolved_questions: set[str] = set()
        wait_required = False

        for signal in signals:
            triage = self._triage_l1_signal(ctx, bundle, signal)
            action = str(triage.get("action", "NOOP")).strip().upper()
            monitors_raw = triage.get("monitors", [])
            monitors = monitors_raw if isinstance(monitors_raw, list) else []
            routing_raw = triage.get("routing", [])
            routing = routing_raw if isinstance(routing_raw, list) else []
            signal_id = str(signal.get("signal_id", "")).strip()
            summary = str((signal.get("need") or {}).get("summary", "")).strip()

            routed_count = self._register_routing_work_items(ctx, routing)
            registered_monitors = self._register_l1_monitors(
                ctx,
                signal_id=signal_id,
                monitors=monitors,
            )
            if (
                not registered_monitors
                and self._is_needs_decision_signal(signal)
                and action != "WAKE_IMMEDIATELY"
            ):
                fallback_monitor = self._build_constraint_present_monitor(
                    ctx=ctx,
                    signal=signal,
                    signal_id=signal_id,
                )
                registered_monitors = self._register_l1_monitors(
                    ctx,
                    signal_id=signal_id,
                    monitors=[fallback_monitor],
                )

            triage_decisions.append(
                {
                    "signal_id": signal_id,
                    "action": action or "NOOP",
                    "summary": summary,
                    "routing_count": routed_count,
                    "monitor_count": len(registered_monitors),
                }
            )

            if action == "WAKE_IMMEDIATELY":
                if summary:
                    resolved_questions.add(summary)
                continue

            if action == "NOOP" and not registered_monitors:
                # No concrete resolution was provided; keep waiting by default.
                wait_required = True
            elif action != "NOOP" or registered_monitors:
                wait_required = True

            if summary:
                blockers.append(
                    {
                        "signal_id": signal_id,
                        "question": summary,
                        "action": action or "NOOP",
                    }
                )

        if resolved_questions:
            bundle.implementation.under_spec_events = [
                event
                for event in raw_events
                if str(event.get("question", "")).strip() not in resolved_questions
            ]
        else:
            bundle.implementation.under_spec_events = raw_events

        bundle.under_spec.decisions = triage_decisions
        if wait_required and bundle.implementation.under_spec_events:
            bundle.under_spec.blockers = blockers
            return StepResult(status="WAITING")

        bundle.under_spec.blockers = []
        return StepResult(status="OK")

    def _load_l1_signals(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        raw_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Load persisted coordination signals, or synthesize from under-spec events."""
        from spec_manager.orchestration.coordination.signals import CoordinationSignal

        evidence_root = _evidence_base_path(
            slice_root=ctx.slice_root,
            workspace_root=ctx.workspace_root,
        )
        iteration_dir = bundle.iter_dir(evidence_root)
        try:
            loaded = CoordinationSignal.load_from(iteration_dir)
        except Exception as exc:
            logger.debug("Failed loading coordination signals for %s: %s", ctx.slice_id, exc)
            loaded = []

        signals: list[dict[str, Any]] = []
        for signal in loaded:
            payload = signal.to_dict()
            payload["run_id"] = str(payload.get("run_id") or ctx.run_id)
            payload["layer"] = str(payload.get("layer") or ctx.layer)
            payload["slice_id"] = str(payload.get("slice_id") or ctx.slice_id)
            payload["iteration"] = int(payload.get("iteration") or bundle.iteration or 0)
            payload = self._enrich_interface_mismatch_signal(
                ctx=ctx,
                bundle=bundle,
                signal_payload=payload,
            )
            signals.append(payload)
        if signals:
            return signals

        synthesized = [
            self._enrich_interface_mismatch_signal(
                ctx=ctx,
                bundle=bundle,
                signal_payload=self._signal_from_under_spec_event(
                    ctx=ctx,
                    bundle=bundle,
                    event=event,
                    event_index=idx,
                ),
            )
            for idx, event in enumerate(raw_events)
        ]
        try:
            iteration_dir.mkdir(parents=True, exist_ok=True)
            signals_path = iteration_dir / "signals.jsonl"
            signals_path.unlink(missing_ok=True)
            for payload in synthesized:
                CoordinationSignal.from_dict(payload).write_to(iteration_dir)
        except OSError:
            logger.debug(
                "Failed to persist synthesized signals for %s",
                ctx.slice_id,
                exc_info=True,
            )
        except (TypeError, ValueError):
            logger.warning(
                "Failed to persist synthesized signals for %s due to invalid payload",
                ctx.slice_id,
                exc_info=True,
            )
        return synthesized

    @staticmethod
    def _signal_from_under_spec_event(
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        event: dict[str, Any],
        event_index: int,
    ) -> dict[str, Any]:
        """Project an L1 under-spec event into a CoordinationSignal-compatible dict."""
        classification_map = {
            "MISSING_CONSTRAINT": "AMBIGUOUS_SPEC",
            "CONFLICTING_CONSTRAINTS": "CONFLICTING_REQUIREMENTS",
            "EXTERNAL_DEP_UNKNOWN": "MISSING_INTERFACE",
            "EXTERNAL_DEPENDENCY_UNKNOWN": "MISSING_INTERFACE",
            "NEEDS_PRODUCT_DECISION": "AMBIGUOUS_SPEC",
            "NEEDS_API_DECISION": "MISSING_INTERFACE",
            "MERGE_CONFLICT": "MERGE_CONFLICT",
        }
        question = str(event.get("question", "")).strip() or "Under-specification detected"
        raw_event_id = str(event.get("event_id", "")).strip()
        event_id = raw_event_id or hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]
        classification = classification_map.get(
            str(event.get("kind", "")).strip(),
            "AMBIGUOUS_SPEC",
        )
        source_line_raw = event.get("source_line", 0)
        try:
            source_line = int(source_line_raw or 0)
        except (TypeError, ValueError):
            source_line = 0

        context_payload = event.get("context", {})
        context_needed_for = ""
        if isinstance(context_payload, dict):
            context_needed_for = str(
                context_payload.get("needed_for")
                or context_payload.get("artifact_key")
                or context_payload.get("context")
                or ""
            ).strip()
        elif isinstance(context_payload, str):
            context_needed_for = context_payload.strip()
        artifact_key = str(event.get("needed_for") or context_needed_for or "").strip()
        if not artifact_key:
            artifact_key = str(event.get("source_file", "")).strip()
        interface_mismatch = {}
        if classification == "MISSING_INTERFACE":
            interface_mismatch = CoordinateStep._interface_mismatch_evidence(
                bundle=bundle,
                slice_root=ctx.slice_root,
                artifact_key=artifact_key,
            )
            if interface_mismatch:
                classification = "INTERFACE_MISMATCH"
        signal_id = f"{ctx.slice_id}:{bundle.iteration}:{event_id}:{event_index}"
        signal_payload: dict[str, Any] = {"under_spec_event": event}
        expected_shape: dict[str, Any] = {}
        if interface_mismatch:
            signal_payload["interface_mismatch"] = interface_mismatch
            expected_shape = {
                "kind": "callable",
                "signature_hint": str(
                    interface_mismatch.get("expected_signature_hint", "")
                ).strip(),
            }
        return {
            "signal_version": 1,
            "signal_id": signal_id,
            "run_id": ctx.run_id,
            "layer": ctx.layer,
            "slice_id": ctx.slice_id,
            "iteration": bundle.iteration,
            "status": "HALT",
            "classification": classification,
            "need": {
                "summary": question,
                "artifact_key": artifact_key,
                "expected_shape": expected_shape,
            },
            "spec_refs": [
                {
                    "spec_text": question,
                    "source_file": str(event.get("source_file", event.get("file", ""))).strip(),
                    "source_symbol": "",
                    "source_line_hint": source_line,
                }
            ],
            "search_hints": {
                "keywords": [token for token in re.split(r"[^a-zA-Z0-9]+", artifact_key) if token],
                "possible_owner_slices": [],
            },
            "payload": signal_payload,
        }

    @staticmethod
    def _enrich_interface_mismatch_signal(
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        signal_payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(signal_payload)
        classification = str(payload.get("classification", "")).strip().upper()
        if classification != "MISSING_INTERFACE":
            return payload

        need_payload = payload.get("need")
        need = dict(need_payload) if isinstance(need_payload, dict) else {}
        artifact_key = str(need.get("artifact_key", "")).strip()
        interface_mismatch = CoordinateStep._interface_mismatch_evidence(
            bundle=bundle,
            slice_root=ctx.slice_root,
            artifact_key=artifact_key,
        )
        if not interface_mismatch:
            return payload

        payload["classification"] = "INTERFACE_MISMATCH"
        expected_shape_raw = need.get("expected_shape")
        expected_shape = dict(expected_shape_raw) if isinstance(expected_shape_raw, dict) else {}
        expected_shape["signature_hint"] = str(
            interface_mismatch.get("expected_signature_hint", "")
        ).strip()
        if "kind" not in expected_shape:
            expected_shape["kind"] = "callable"
        need["expected_shape"] = expected_shape
        payload["need"] = need

        inner_payload_raw = payload.get("payload")
        inner_payload = dict(inner_payload_raw) if isinstance(inner_payload_raw, dict) else {}
        inner_payload["interface_mismatch"] = interface_mismatch
        payload["payload"] = inner_payload
        return payload

    @staticmethod
    def _interface_mismatch_evidence(
        *,
        bundle: EvidenceBundle,
        slice_root: str,
        artifact_key: str,
    ) -> dict[str, Any]:
        wake_payload = CoordinateStep._latest_symbol_wake_payload(bundle)
        expected_signature_hint = str(wake_payload.get("expected_signature_hint", "")).strip()
        if not expected_signature_hint:
            return {}
        symbol_fqn = str(wake_payload.get("symbol_fqn", "")).strip() or artifact_key
        observed_signature_snippet = CoordinateStep._extract_symbol_signature_snippet(
            slice_root=slice_root,
            symbol_fqn=symbol_fqn,
        )
        if not observed_signature_snippet:
            return {}
        if CoordinateStep._signature_hint_matches(
            expected_hint=expected_signature_hint,
            observed_snippet=observed_signature_snippet,
        ):
            return {}
        return {
            "expected_signature_hint": expected_signature_hint,
            "observed_signature_snippet": observed_signature_snippet,
            "symbol_fqn": symbol_fqn,
            "artifact_key": artifact_key,
        }

    @staticmethod
    def _latest_symbol_wake_payload(bundle: EvidenceBundle) -> dict[str, Any]:
        decisions = bundle.under_spec.decisions or []
        for item in reversed(decisions):
            if not isinstance(item, dict):
                continue
            if str(item.get("source", "")).strip().upper() != "WAKE_EVENT":
                continue
            wake_payload = item.get("wake_payload")
            if not isinstance(wake_payload, dict):
                continue
            if str(wake_payload.get("kind", "")).strip().lower() != "symbol_available":
                continue
            return dict(wake_payload)
        return {}

    @staticmethod
    def _extract_symbol_signature_snippet(*, slice_root: str, symbol_fqn: str) -> str:
        root_text = str(slice_root).strip()
        if not root_text:
            return ""
        root = Path(root_text)
        if not root.exists():
            return ""
        symbol_leaf = str(symbol_fqn).strip()
        if "." in symbol_leaf:
            symbol_leaf = symbol_leaf.split(".")[-1]
        if "::" in symbol_leaf:
            symbol_leaf = symbol_leaf.split("::")[-1]
        symbol_leaf = symbol_leaf.strip()
        if not symbol_leaf:
            return ""

        for path in root.rglob("*.py"):
            if ".git" in path.parts:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                if f"def {symbol_leaf}(" in stripped or f"class {symbol_leaf}" in stripped:
                    rel = path.relative_to(root)
                    return f"{rel}:{line_no}:{stripped[:240]}"
        return ""

    @staticmethod
    def _signature_hint_matches(*, expected_hint: str, observed_snippet: str) -> bool:
        expected = str(expected_hint).strip().lower()
        observed = str(observed_snippet).strip().lower()
        if not expected or not observed:
            return False
        if expected in observed:
            return True
        tokens = [token for token in re.split(r"[^a-zA-Z0-9_]+", expected) if token]
        if not tokens:
            return False
        significant_tokens = [token for token in tokens if len(token) >= 3]
        required_tokens = significant_tokens if significant_tokens else tokens
        return all(token in observed for token in required_tokens)

    @staticmethod
    def _is_needs_decision_signal(signal: dict[str, Any]) -> bool:
        """True when a signal represents unresolved decision-level ambiguity."""
        classification = str(signal.get("classification", "")).strip().upper()
        if classification in {
            "AMBIGUOUS_SPEC",
            "CONFLICTING_REQUIREMENTS",
            "MISSING_INTERFACE",
            "INTERFACE_MISMATCH",
        }:
            return True

        payload = signal.get("payload")
        if not isinstance(payload, dict):
            return False

        origin_kind = str(payload.get("origin_event_kind", "")).strip().upper()
        if origin_kind.startswith("NEEDS_") or origin_kind in {
            "MISSING_CONSTRAINT",
            "CONFLICTING_CONSTRAINTS",
            "EXTERNAL_DEP_UNKNOWN",
        }:
            return True

        under_spec_event = payload.get("under_spec_event")
        if not isinstance(under_spec_event, dict):
            return False
        event_kind = str(under_spec_event.get("kind", "")).strip().upper()
        return event_kind.startswith("NEEDS_") or event_kind in {
            "MISSING_CONSTRAINT",
            "CONFLICTING_CONSTRAINTS",
            "EXTERNAL_DEP_UNKNOWN",
        }

    @staticmethod
    def _build_constraint_present_monitor(
        *,
        ctx: SliceContext,
        signal: dict[str, Any],
        signal_id: str,
    ) -> dict[str, Any]:
        """Build a constraint-present fallback monitor for unresolved decisions."""
        need = signal.get("need")
        need_payload = need if isinstance(need, dict) else {}
        constraint_key = str(need_payload.get("artifact_key", "")).strip() or ctx.slice_id

        constraint_id = ""
        payload = signal.get("payload")
        if isinstance(payload, dict):
            constraint_id = str(payload.get("constraint_id", "")).strip()
            if not constraint_id:
                under_spec_event = payload.get("under_spec_event")
                if isinstance(under_spec_event, dict):
                    constraint_id = str(under_spec_event.get("event_id", "")).strip()

        return {
            "signal_id": signal_id,
            "kind": "constraint_present",
            "type": "constraint_present",
            "constraint_key": constraint_key,
            "constraint_dir": "analysis/constraints",
            "constraint_id": constraint_id,
            "slice_id": ctx.slice_id,
            "mode": "hybrid",
            "event_triggers": ["SLICE_MERGED", "GIT_DIRTY_ADVANCED"],
            "poll_interval_sec": 20,
            "timeout_seconds": 3600,
        }

    def _triage_l1_signal(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        signal: dict[str, Any],
    ) -> dict[str, Any]:
        """Call planner TRIAGE_SIGNAL when available."""
        if self._planner is None or not hasattr(self._planner, "triage_signal"):
            return {"action": "WAIT_ON_WORK_ITEM", "monitors": []}

        try:
            from spec_manager.planner.api import PlanningContext

            planning_ctx = PlanningContext(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                iteration=bundle.iteration,
                layer=ctx.layer,
                mode=ctx.mode,
                workspace_root=ctx.workspace_root,
                slice_root=ctx.slice_root,
                bundle_ref=bundle,
                signal_ref=signal,
                metadata={"source": "COORDINATE"},
            )
            triage_result = self._planner.triage_signal(planning_ctx, signal)
            if isinstance(triage_result, dict):
                return triage_result
            outputs = getattr(triage_result, "outputs", None)
            if isinstance(outputs, dict):
                return outputs
        except Exception as exc:
            logger.warning("L1 signal triage failed for %s: %s", ctx.slice_id, exc, exc_info=True)

        return {"action": "WAIT_ON_WORK_ITEM", "monitors": []}

    @staticmethod
    def _register_routing_work_items(ctx: SliceContext, routing: list[dict[str, Any]]) -> int:
        """Persist triage-routed work items for monitor tracking."""
        if not routing:
            return 0

        from spec_manager.orchestration.coordination.work_items import WorkItem, WorkItemStore

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        coordination_dir = workspace / ".pdd_runs" / ctx.run_id / "coordination"
        store = WorkItemStore(coordination_dir)
        added = 0
        for payload in routing:
            if not isinstance(payload, dict):
                continue
            try:
                work_item = WorkItem.from_dict(payload)
            except ValueError as exc:
                logger.warning(
                    "Skipping invalid routed work item payload for %s: %s",
                    ctx.slice_id,
                    exc,
                )
                continue
            if not work_item.work_item_id:
                continue
            if not work_item.owner_slice_id:
                work_item.owner_slice_id = ctx.slice_id
            if not work_item.status:
                work_item_kind = str(work_item.kind).strip().upper()
                work_item.status = "OPEN" if work_item_kind == "ARCH_DECISION" else "NEW"
            if store.get(work_item.work_item_id) is not None:
                continue
            store.add(work_item)
            added += 1
        return added

    @staticmethod
    def _normalize_monitor_condition(
        monitor_payload: dict[str, Any],
        *,
        slice_id: str,
    ) -> dict[str, Any]:
        """Normalize planner monitor payload into a ConditionChecker-compatible dict."""
        condition = dict(monitor_payload)
        raw_type = str(condition.get("type", "")).strip()
        if not raw_type:
            kind = str(condition.get("kind", "")).strip().lower()
            if kind == "work_item_status":
                raw_type = "work_item_done"
            elif kind == "symbol_available":
                raw_type = "git_symbol_exists"
            elif kind in {"constraint_present", "constraint_available"}:
                raw_type = "constraint_present"
        if raw_type == "work_item_done":
            work_item_id = str(condition.get("work_item_id", "")).strip()
            if not work_item_id:
                return {}
            condition_kind = str(condition.get("kind", "")).strip().lower()
            default_status = "DECIDED" if condition_kind == "arch_decision" else "MERGED"
            required_status = (
                str(condition.get("required_status", default_status)).strip().upper()
                or default_status
            )
            return {
                "type": "work_item_done",
                "work_item_id": work_item_id,
                "required_status": required_status,
            }
        if raw_type == "git_symbol_exists":
            symbol = str(condition.get("symbol_fqn") or condition.get("artifact_key") or "").strip()
            if not symbol:
                return {}
            ref = str(condition.get("ref", "")).strip() or "HEAD"
            file_glob = str(condition.get("file_glob", "")).strip() or "**/*.py"
            signature_regex = str(condition.get("signature_regex", "")).strip()
            if not signature_regex:
                signature_regex = rf"\b{re.escape(symbol.split('.')[-1] or symbol)}\b"
            return {
                "type": "git_symbol_exists",
                "ref": ref,
                "file_glob": file_glob,
                "symbol_fqn": symbol,
                "signature_regex": signature_regex,
            }
        if raw_type == "constraint_present":
            constraint_key = str(condition.get("constraint_key", "")).strip() or slice_id
            return {
                "type": "constraint_present",
                "constraint_key": constraint_key,
                "constraint_dir": str(
                    condition.get("constraint_dir", "analysis/constraints")
                ).strip(),
                "constraint_id": str(condition.get("constraint_id", "")).strip(),
                "slice_id": str(condition.get("slice_id", "")).strip() or slice_id,
            }
        return {}

    @staticmethod
    def _monitor_fingerprint(*, signal_id: str, condition: dict[str, Any]) -> str:
        """Stable identity for deduplicating monitor registrations."""
        payload = {"signal_id": signal_id, "condition": condition}
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _register_l1_monitors(
        self,
        ctx: SliceContext,
        *,
        signal_id: str,
        monitors: list[dict[str, Any]],
    ) -> list[str]:
        """Register planner-provided monitors for L1 WAITING coordination."""
        if not monitors:
            return []

        from spec_manager.orchestration.coordination.monitors import (
            MonitorExecution,
            MonitorRegistry,
            MonitorSpec,
            MonitorTimeout,
            MonitorWake,
            SliceInfo,
        )

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        coordination_dir = workspace / ".pdd_runs" / ctx.run_id / "coordination"
        coordination_dir.mkdir(parents=True, exist_ok=True)
        registry = MonitorRegistry(coordination_dir)
        existing_active = [
            s for s in registry.get_active() if s.waiting_slice.slice_id == ctx.slice_id
        ]

        fingerprints = {
            self._monitor_fingerprint(signal_id=s.signal_id, condition=s.condition)
            for s in existing_active
        }
        registered: list[str] = []
        for payload in monitors:
            if not isinstance(payload, dict):
                continue
            normalized_signal_id = str(payload.get("signal_id", "")).strip() or signal_id
            condition = self._normalize_monitor_condition(payload, slice_id=ctx.slice_id)
            if not condition:
                continue

            fingerprint = self._monitor_fingerprint(
                signal_id=normalized_signal_id,
                condition=condition,
            )
            if fingerprint in fingerprints:
                continue

            timeout_raw = payload.get("timeout_seconds", payload.get("timeout_sec", 3600))
            try:
                timeout_sec = max(int(timeout_raw), 1)
            except (TypeError, ValueError):
                timeout_sec = 3600

            poll_interval_raw = payload.get("poll_interval_sec", 20)
            try:
                poll_interval_sec = max(int(poll_interval_raw), 1)
            except (TypeError, ValueError):
                poll_interval_sec = 20

            mode = str(payload.get("mode", "hybrid")).strip().lower()
            if mode not in {"hybrid", "poll", "event"}:
                mode = "hybrid"
            event_triggers_raw = payload.get("event_triggers", [])
            event_triggers = (
                [str(item) for item in event_triggers_raw if str(item).strip()]
                if isinstance(event_triggers_raw, list)
                else []
            )
            monitor_id = str(payload.get("monitor_id", "")).strip()
            spec = MonitorSpec(
                monitor_id=monitor_id,
                run_id=ctx.run_id,
                waiting_slice=SliceInfo(layer=ctx.layer, slice_id=ctx.slice_id),
                signal_id=normalized_signal_id,
                condition=condition,
                execution=MonitorExecution(
                    mode=cast("Literal['hybrid', 'poll', 'event']", mode),
                    poll_interval_sec=poll_interval_sec,
                    event_triggers=event_triggers,
                ),
                timeout=MonitorTimeout(
                    timeout_sec=timeout_sec,
                    on_timeout="ESCALATE",
                ),
                wake=MonitorWake(
                    action="WAKE_SLICE",
                    payload={
                        "slice_id": ctx.slice_id,
                        "layer": ctx.layer,
                        "signal_id": normalized_signal_id,
                        "kind": str(payload.get("kind", "")).strip(),
                        "artifact_key": str(payload.get("artifact_key", "")).strip(),
                        "symbol_fqn": str(payload.get("symbol_fqn", "")).strip(),
                        "expected_signature_hint": str(
                            payload.get("expected_signature_hint", "")
                        ).strip(),
                    },
                ),
            )
            registry.register(spec)
            fingerprints.add(fingerprint)
            registered.append(spec.monitor_id)
        return registered

    def _resolve_under_spec(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        *,
        raw_events: list[dict[str, Any]] | None = None,
        source: Literal["implementation", "plan"] = "implementation",
    ) -> StepResult:
        """L2/L3: resolve under-spec events via UnderSpecManager.

        Delegates to UnderSpecManager for constraint resolution.
        """
        if source == "plan":
            selected_events = (
                raw_events if raw_events is not None else bundle.plan.under_spec_events
            )
            normalized_events = [
                event for event in (selected_events or []) if isinstance(event, dict)
            ]
            bundle.plan.under_spec_events = normalized_events
        else:
            selected_events = (
                raw_events if raw_events is not None else bundle.implementation.under_spec_events
            )
            normalized_events = [
                event for event in (selected_events or []) if isinstance(event, dict)
            ]
            bundle.implementation.under_spec_events = normalized_events

        if not normalized_events:
            return StepResult(status="OK")

        from spec_manager.orchestration.under_spec.manager import (
            UnderSpecEvent,
            UnderSpecManager,
        )

        events = [UnderSpecEvent.from_dict(e) for e in normalized_events]
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        manager = UnderSpecManager(
            workspace_root=workspace,
            mode=ctx.mode,
            planner=self._planner,
            run_id=ctx.run_id,
        )
        outcome = manager.resolve(slice_id=ctx.slice_id, events=events, layer=ctx.layer)

        resolved_ids = {event.event_id for event in outcome.resolved if event.event_id}
        if resolved_ids:
            if source == "plan":
                bundle.plan.under_spec_events = [
                    event
                    for event in (bundle.plan.under_spec_events or [])
                    if str(event.get("event_id", "")).strip() not in resolved_ids
                ]
            else:
                bundle.implementation.under_spec_events = [
                    event
                    for event in (bundle.implementation.under_spec_events or [])
                    if str(event.get("event_id", "")).strip() not in resolved_ids
                ]

        # Record decisions/blockers and under-spec artifacts in the bundle.
        bundle.under_spec.decisions = list(outcome.decisions)
        bundle.under_spec.blockers = []
        for event in outcome.blocked:
            payload = event.to_dict()
            if outcome.blocked_on:
                payload["blocked_on"] = list(outcome.blocked_on)
            if outcome.resume_hint:
                payload["resume_hint"] = dict(outcome.resume_hint)
            bundle.under_spec.blockers.append(payload)

        if outcome.blockers_path:
            bundle.under_spec.path = outcome.blockers_path
        elif outcome.decisions_path:
            bundle.under_spec.path = outcome.decisions_path
        elif outcome.expansion_path:
            bundle.under_spec.path = outcome.expansion_path

        # Record new constraint refs
        if outcome.constraints:
            constraint_path = outcome.resume_hint.get("constraints_path") or str(
                workspace / "analysis" / "constraints" / f"{ctx.slice_id}.json"
            )
            if constraint_path not in bundle.facts.constraints_refs:
                bundle.facts.constraints_refs.append(constraint_path)

        if outcome.is_waiting:
            monitor_payloads = list(outcome.monitors)
            if not monitor_payloads:
                for event in outcome.blocked:
                    canonical_key = (
                        str((event.context or {}).get("canonical_key", "")).strip()
                        if isinstance(event.context, dict)
                        else ""
                    )
                    if not canonical_key:
                        canonical_key = f"underspec.{event.event_id}".strip(".")
                    monitor_payloads.append(
                        {
                            "signal_id": f"underspec:{ctx.slice_id}:{event.event_id}",
                            "kind": "constraint_present",
                            "type": "constraint_present",
                            "constraint_key": canonical_key,
                            "constraint_dir": "analysis/constraints",
                            "constraint_id": event.event_id,
                            "slice_id": ctx.slice_id,
                            "mode": "hybrid",
                            "event_triggers": ["SLICE_MERGED", "GIT_DIRTY_ADVANCED"],
                            "poll_interval_sec": 20,
                            "timeout_seconds": 3600,
                        }
                    )

            registered_monitor_ids = self._register_l1_monitors(
                ctx,
                signal_id=f"underspec:{ctx.slice_id}",
                monitors=monitor_payloads,
            )
            if registered_monitor_ids:
                bundle.under_spec.decisions.append(
                    {
                        "action": "WAITING_FOR_CONSTRAINTS",
                        "monitor_count": len(registered_monitor_ids),
                    }
                )
            bundle.status = outcome.bundle_status
            return StepResult(
                status="WAITING",
                error=f"Under-specification waiting on {len(outcome.blocked)} user questions",
            )

        if outcome.is_blocked:
            bundle.status = outcome.bundle_status
            return StepResult(
                status="BLOCKED",
                error=f"Under-specification: {len(outcome.blocked)} unresolvable events",
            )

        bundle.under_spec.blockers = []
        return StepResult(status="OK")


class AnalyzeStep:
    """Analyze slice after implementation — layer-aware.

    - L1: P1 + P2 via canonical file facts projection
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
            from spec_manager.core.code_analysis import analyze_file_facts

            existing_entries: dict[str, dict[str, Any]] = {
                str(entry.get("path", "")).strip(): entry
                for entry in (bundle.source_index.entries or [])
                if isinstance(entry, dict) and str(entry.get("path", "")).strip()
            }
            entries: list[dict[str, Any]] = []
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
                content_hash = _hash_text(content)
                cached_entry = existing_entries.get(relative_path)
                cached_payload = (
                    _extract_file_facts_payload(cached_entry)
                    if isinstance(cached_entry, dict)
                    else {}
                )
                cached_analysis = (
                    cached_entry.get("analysis")
                    if isinstance(cached_entry, dict)
                    and isinstance(cached_entry.get("analysis"), dict)
                    else {}
                )
                analysis_functions = (
                    cached_analysis.get("functions")
                    if isinstance(cached_analysis.get("functions"), list)
                    else []
                )
                analysis_comments = (
                    cached_analysis.get("comments")
                    if isinstance(cached_analysis.get("comments"), list)
                    else []
                )

                if (
                    isinstance(cached_entry, dict)
                    and cached_entry.get("content_hash") == content_hash
                    and cached_payload
                    and isinstance(cached_analysis.get("functions"), list)
                    and isinstance(cached_analysis.get("comments"), list)
                ):
                    source_entry = cached_entry
                    payload = cached_payload
                else:
                    file_facts = analyze_file_facts(
                        content,
                        relative_path,
                        requested_relationship_facets={"CALL", "REFERENCE", "STORE_TOUCH", "EVENT"},
                        workspace=workspace,
                        run_id=ctx.run_id,
                    )
                    payload = {
                        "structure_hints": dict(file_facts.structure_hints),
                        "remaining_gap_pins": list(file_facts.gap_pins),
                        "relationship_edges": list(file_facts.relationship_edges),
                        "test_identity_hints": list(file_facts.test_identity_hints),
                        "functions": dict(file_facts.functions),
                        "stub_nodes": list(file_facts.stub_nodes),
                        "call_graph_nodes": list(file_facts.call_graph_nodes),
                        "call_graph_edges": list(file_facts.call_graph_edges),
                        "stores": dict(file_facts.stores),
                        "store_owners": dict(file_facts.store_owners),
                    }
                    source_entry = _build_l1_source_entry(
                        relative_path=relative_path,
                        content_hash=content_hash,
                        source_analysis=file_facts.source_analysis,
                        file_facts_payload=payload,
                    )
                    analysis_functions = source_entry.get("analysis", {}).get("functions", [])
                    analysis_comments = source_entry.get("analysis", {}).get("comments", [])

                entries.append(source_entry)
                _merge_file_facts_payload(bundle, payload)
                reverse_payload.extend(
                    _reverse_pseudocode_payload_from_analysis(
                        relative_path=relative_path,
                        functions=[fn for fn in analysis_functions if isinstance(fn, dict)],
                        comments=[
                            comment for comment in analysis_comments if isinstance(comment, dict)
                        ],
                    )
                )

            bundle.source_index.entries = entries
            bundle.source_index.path = "source_analysis.index.json"

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
                "Analyzed %d files with canonical file facts",
                len(entries),
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

        under_spec_events = [
            *list(bundle.implementation.under_spec_events or []),
            *list(bundle.plan.under_spec_events or []),
        ]
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
                if ":" in fqn:
                    function_name = fqn.rsplit(":", 1)[-1]
                elif "." in fqn:
                    function_name = fqn.rsplit(".", 1)[-1]
                else:
                    function_name = fqn
            if not module_path and fqn:
                if ":" in fqn:
                    module_path = fqn.rsplit(":", 1)[0]
                elif "." in fqn:
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

        def _projection_from_signal(signal_type: str) -> str:
            signal = signal_type.strip().upper()
            if signal in {"CALL"}:
                return "pass_through"
            if signal in {"STORE_TOUCH"}:
                return "aggregation"
            if signal in {"EVENT", "EVENT_EMIT", "EVENT_HANDLE"}:
                return "event_bridge"
            if signal in {"IMPORT", "REFERENCE"}:
                return "slice"
            return "pass_through"

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
                projection_type = _projection_from_signal(str(proposal.get("signal_type", "CALL")))
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

        raw_pin_proposals: list[dict[str, Any]] = list(bundle.implementation.pin_proposals or [])
        if bundle.implementation.pin_proposals_path:
            loaded = _read_json_file(iteration_dir / bundle.implementation.pin_proposals_path)
            if isinstance(loaded, list):
                raw_pin_proposals = [row for row in loaded if isinstance(row, dict)]

        raw_edge_proposals: list[dict[str, Any]] = list(bundle.implementation.edge_proposals or [])
        if bundle.implementation.edge_proposals_path:
            loaded = _read_json_file(iteration_dir / bundle.implementation.edge_proposals_path)
            if isinstance(loaded, list):
                raw_edge_proposals = [row for row in loaded if isinstance(row, dict)]

        try:
            normalized_pins = self._normalize_pin_proposals(raw_pin_proposals)
            normalized_edges = self._normalize_edge_proposals(raw_edge_proposals)
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
                pin_proposals=normalized_pins,
                edge_proposals=normalized_edges,
                pin_proposals_path=pin_proposals_path,
                edge_proposals_path=edge_proposals_path,
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
                source=_gate_source_for_layer(current_layer),
                category="governance",
                gate="DIRTY_TO_CLEAN_GOVERNANCE",
                origin_layer=current_layer,
                hop_trace=[current_layer, current_layer],
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

        dropped_entities: list = []
        issues = detect_all(
            graph,
            grouping_units,
            dropped_entities=dropped_entities,
        )
        bundle.refinement.path = _write_iteration_json(
            bundle,
            evidence_root,
            "refinement.json",
            {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "issue_count": len(issues),
                "issues": [asdict(issue) for issue in issues],
                "dropped_entity_count": len(dropped_entities),
                "dropped_entities": [asdict(item) for item in dropped_entities],
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
                        source="ALGORITHMIC_GATE",
                        gate="EVIDENCE_INTEGRITY",
                        origin_layer="L1",
                        hop_trace=["L1", "L1"],
                        target_layer="L1",
                        severity="BLOCKER",
                        diagnosis="; ".join(failures),
                    )
                ],
                error="L1 evidence integrity gate failed",
            )
        return StepResult(status="OK")

    def _promote_l2(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """L2: run canonical promotion gates as EvidenceBundle queries."""
        from spec_manager.compliance.promotion.config import PromotionGateConfig
        from spec_manager.compliance.promotion.orchestrator import LayerPromotionGate
        from spec_manager.schemas.pin_functions import PinFunctionRegistry

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root:
            return StepResult(status="RETRY", error="L2 PROMOTE missing slice root")

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
            evidence_bundle=bundle,
            pin_registry=pin_registry,
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
        gap_records = [gap for gap in bundle.gaps.open_gaps if isinstance(gap, dict)]
        failing_files = sorted(
            {
                str(gap.get("file") or (gap.get("location") or {}).get("file") or "").strip()
                for gap in gap_records
            }
            - {""}
        )
        failing_pins = sorted({str(gap.get("pin_id") or "").strip() for gap in gap_records} - {""})
        failing_atoms = sorted(
            {str(gap.get("atom_id") or "").strip() for gap in gap_records} - {""}
        )
        symbol_span_anchors = []
        for gap in gap_records:
            file_path = str(
                gap.get("file") or (gap.get("location") or {}).get("file") or ""
            ).strip()
            if not file_path:
                continue
            span = gap.get("span") if isinstance(gap.get("span"), dict) else {}
            symbol_span_anchors.append(
                {
                    "file": file_path,
                    "symbol": str(
                        gap.get("anchor") or gap.get("pin_id") or gap.get("atom_id") or ""
                    ).strip()
                    or None,
                    "start_line": span.get("start_line"),
                    "end_line": span.get("end_line"),
                }
            )
        evidence_refs = [ref for ref in (bundle.gates.path, bundle.gaps.path) if str(ref).strip()]
        component_id = next(
            (
                str(gap.get("component_id")).strip()
                for gap in gap_records
                if str(gap.get("component_id") or "").strip()
            ),
            None,
        )
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
                source="ARCH_GATE",
                category="logic",
                gate=str(gate.get("gate_id", "")),
                origin_layer=current_layer,
                hop_trace=[current_layer, "L1"],
                target_layer="L1",
                severity="BLOCKER",
                diagnosis=str(gate.get("summary", "L2 behavior-change gate failed")),
                failing_files=failing_files,
                failing_pins=failing_pins,
                failing_atoms=failing_atoms,
                component_id=component_id,
                symbol_span_anchors=symbol_span_anchors,
                evidence_refs=evidence_refs,
            )
            for gate in behavior_change_failures
        ]
        for gate in governance_failures:
            tickets.append(
                DemotionTicket(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    source="ARCH_GATE",
                    category="governance",
                    gate=str(gate.get("gate_id", "")),
                    origin_layer=current_layer,
                    hop_trace=[current_layer, current_layer],
                    target_layer=current_layer,
                    severity="BLOCKER",
                    diagnosis=str(gate.get("summary", "L2 governance gate failed")),
                    failing_files=failing_files,
                    failing_pins=failing_pins,
                    failing_atoms=failing_atoms,
                    component_id=component_id,
                    symbol_span_anchors=symbol_span_anchors,
                    evidence_refs=evidence_refs,
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
                            hop_trace=["L3", "L1"],
                            target_layer="L1",
                            severity=str(finding.get("severity", "MAJOR")).upper(),
                            diagnosis=str(
                                finding.get("description", "Quality finding requires logic change")
                            ),
                            failing_files=[finding["file"]] if finding.get("file") else [],
                            symbol_span_anchors=(
                                [
                                    {
                                        "file": finding.get("file", ""),
                                        **(finding.get("span", {}) or {}),
                                    }
                                ]
                                if finding.get("file")
                                else []
                            ),
                        )
                    )
                elif category == "architecture":
                    tickets.append(
                        DemotionTicket(
                            run_id=ctx.run_id,
                            slice_id=ctx.slice_id,
                            source="REVIEW",
                            origin_layer="L3",
                            hop_trace=["L3", "L2"],
                            target_layer="L2",
                            severity=str(finding.get("severity", "MAJOR")).upper(),
                            diagnosis=str(
                                finding.get(
                                    "description", "Quality finding requires architecture change"
                                )
                            ),
                            failing_files=[finding["file"]] if finding.get("file") else [],
                            symbol_span_anchors=(
                                [
                                    {
                                        "file": finding.get("file", ""),
                                        **(finding.get("span", {}) or {}),
                                    }
                                ]
                                if finding.get("file")
                                else []
                            ),
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
                        source="REVIEW",
                        origin_layer="L3",
                        hop_trace=["L3", target],
                        target_layer=target,
                        severity=severity,
                        diagnosis=str(
                            finding.get(
                                "description",
                                "Diff-impact classifier requires lower-layer handling.",
                            )
                        ),
                        failing_files=[finding["file"]] if finding.get("file") else [],
                        symbol_span_anchors=(
                            [{"file": finding.get("file", ""), **(finding.get("span", {}) or {})}]
                            if finding.get("file")
                            else []
                        ),
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
                        source=(
                            "ALGORITHMIC_GATE"
                            if gate["required_change_type"] == "behavior_change"
                            else (
                                "ARCH_GATE"
                                if gate["required_change_type"] == "wiring_only"
                                else "REVIEW"
                            )
                        ),
                        origin_layer="L3",
                        hop_trace=["L3", target],
                        target_layer=target,
                        gate=gate["gate_id"],
                        severity="BLOCKER" if target in {"L1", "L3"} else "MAJOR",
                        diagnosis=gate["summary"],
                        evidence_refs=[ref for ref in (bundle.gates.path, bundle.gaps.path) if ref],
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

    Integrate merges slice work into dirty, then directly runs pipeline CI
    propagation via ``worktree_manager.tick_pipeline()``. For merge conflicts,
    integrate performs a single rebase+remerge cycle and emits demotion/retry
    if conflicts persist.
    """

    name = "INTEGRATE"
    _FAILURE_FILE_RE = re.compile(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)(?::(\d+))?")

    def __init__(self, *, investigator_budget: int = 2) -> None:
        self._investigator_budget = investigator_budget

    @staticmethod
    def _extract_failure_files(
        *,
        refs: list[str],
        summary: str,
        changed_files: list[str],
    ) -> list[str]:
        """Extract likely failing files from failure refs/summary with changed-file fallback."""
        candidates: list[str] = []
        haystacks = [*refs, summary]
        for text in haystacks:
            for match in IntegrateStep._FAILURE_FILE_RE.findall(str(text)):
                path = str(match[0]).strip().replace("\\", "/").lstrip("./")
                if path:
                    candidates.append(path)
        if not candidates:
            candidates.extend(str(path).strip() for path in changed_files if str(path).strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for path in candidates:
            if path not in seen:
                seen.add(path)
                deduped.append(path)
        return deduped[:25]

    @staticmethod
    def _build_pin_registry_adapter(slice_root: Path) -> Any | None:
        """Build a lightweight adapter for DownwardFlowEngine pin/atom queries."""
        registry_path = slice_root / ".spec" / "pin_registry.json"
        payload = _read_json_file(registry_path)
        if not isinstance(payload, dict):
            return None
        pin_functions = [
            item for item in payload.get("pin_functions", []) if isinstance(item, dict)
        ]
        import_edges = [item for item in payload.get("import_edges", []) if isinstance(item, dict)]
        if not pin_functions and not import_edges:
            return None

        by_pin: dict[str, dict[str, Any]] = {
            str(item.get("pin_func_id", "")).strip(): item
            for item in pin_functions
            if str(item.get("pin_func_id", "")).strip()
        }
        by_file: dict[str, list[str]] = defaultdict(list)
        for edge in import_edges:
            pin_id = str(edge.get("pin_func_id", "")).strip()
            file_path = str(edge.get("arch_file_path", "")).strip().replace("\\", "/")
            if not pin_id or not file_path:
                continue
            by_file[file_path].append(pin_id)

        class _TraceAdapter:
            def query_pin_functions_for_file(self, file_path: str) -> list[Any]:
                normalized = str(file_path).strip().replace("\\", "/")
                matches: list[str] = []
                for edge_file, pins in by_file.items():
                    if (
                        normalized == edge_file
                        or normalized.endswith(edge_file)
                        or edge_file.endswith(normalized)
                    ):
                        matches.extend(pins)
                return [SimpleNamespace(pin_id=pin_id) for pin_id in dict.fromkeys(matches)]

            def query_importers(self, pin_id: str) -> list[Any]:
                pin = by_pin.get(str(pin_id).strip(), {})
                atoms = [
                    str(atom_id).strip()
                    for atom_id in (pin.get("evidence_atom_ids") or [])
                    if str(atom_id).strip()
                ]
                return [
                    SimpleNamespace(pin_id=f"PIN-ATOM-{atom_id}")
                    for atom_id in dict.fromkeys(atoms)
                ]

        return _TraceAdapter()

    @staticmethod
    def _anchors_from_refs(*, failing_files: list[str], refs: list[str]) -> list[dict[str, Any]]:
        anchors: list[dict[str, Any]] = []
        for file_path in failing_files:
            anchors.append({"file": file_path})
        for ref in refs:
            for path, line in IntegrateStep._FAILURE_FILE_RE.findall(str(ref)):
                cleaned = str(path).strip().replace("\\", "/").lstrip("./")
                if not cleaned:
                    continue
                anchor: dict[str, Any] = {"file": cleaned}
                if line:
                    try:
                        line_num = int(line)
                        if line_num > 0:
                            anchor["start_line"] = line_num
                            anchor["end_line"] = line_num
                    except ValueError:
                        pass
                anchors.append(anchor)
        unique: list[dict[str, Any]] = []
        seen = set()
        for anchor in anchors:
            key = (
                str(anchor.get("file", "")).strip(),
                int(anchor.get("start_line") or 0),
                int(anchor.get("end_line") or 0),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            unique.append(anchor)
        return unique[:40]

    @staticmethod
    def _serialize_test_failure(failure: Any) -> dict[str, Any]:
        """Normalize a TestFailure-like object into dict form."""
        return {
            "test_id": str(getattr(failure, "test_id", "") or "").strip() or None,
            "file": str(getattr(failure, "file", "") or "").strip() or None,
            "message": str(getattr(failure, "message", "") or "").strip(),
            "raw_excerpt_path": str(getattr(failure, "raw_excerpt_path", "") or "").strip(),
        }

    @classmethod
    def _serialize_test_run_result(cls, run_result: Any) -> dict[str, Any]:
        """Normalize a TestRunResult-like object into receipt-safe JSON."""
        failures = [
            cls._serialize_test_failure(failure)
            for failure in list(getattr(run_result, "failures", []) or [])
        ]
        return {
            "passed": bool(getattr(run_result, "passed", False)),
            "scope": str(getattr(run_result, "scope", "SLICE") or "SLICE").upper(),
            "runner_id": str(getattr(run_result, "runner_id", "") or "").strip(),
            "command": [str(item) for item in list(getattr(run_result, "command", []) or [])],
            "stdout_path": str(getattr(run_result, "stdout_path", "") or "").strip(),
            "stderr_path": str(getattr(run_result, "stderr_path", "") or "").strip(),
            "total_tests": int(getattr(run_result, "total_tests", 0) or 0),
            "passed_tests": int(getattr(run_result, "passed_tests", 0) or 0),
            "failed_tests": int(getattr(run_result, "failed_tests", 0) or 0),
            "duration_ms": float(getattr(run_result, "duration_ms", 0.0) or 0.0),
            "failures": failures,
        }

    @staticmethod
    def _not_run_test_payload(*, slice_id: str, layer: str, reason: str) -> dict[str, Any]:
        """Build a structured receipt for skipped test execution."""
        return {
            "slice_id": slice_id,
            "layer": layer,
            "status": "not_run",
            "reason": reason,
            "result": {
                "passed": False,
                "scope": "SLICE",
                "runner_id": "not_run",
                "command": [],
                "stdout_path": "",
                "stderr_path": "",
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
                "duration_ms": 0.0,
                "failures": [
                    {
                        "test_id": None,
                        "file": None,
                        "message": reason,
                        "raw_excerpt_path": "",
                    }
                ],
            },
        }

    @staticmethod
    def _run_slice_tests(*, test_root: Path, timeout_seconds: int = 300) -> Any:
        """Run slice tests through the swappable TestRunnerRegistry."""
        from spec_manager.core.testing.registry import TestRunnerRegistry
        from spec_manager.core.testing.runner import TestFailure, TestRunResult

        try:
            registry = TestRunnerRegistry()
            runner = registry.pick(root=test_root, timeout_seconds=timeout_seconds)
            return runner.run(root=test_root, scope="SLICE", targets=None)
        except Exception as exc:
            return TestRunResult(
                passed=False,
                scope="SLICE",
                runner_id="runner_error",
                command=[],
                failures=[
                    TestFailure(
                        message=f"Test runner invocation failed: {exc}",
                        raw_excerpt_path="",
                    )
                ],
            )

    def _build_test_failure_tickets(
        self,
        *,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        refs: list[str],
        summary: str,
        evidence_refs: list[str],
        test_result: Any | None = None,
    ) -> list[DemotionTicket]:
        """Create traced TEST_FAILURE demotion tickets using DownwardFlowEngine."""
        active_layer = cast("Literal['L1', 'L2', 'L3']", str(ctx.layer).upper())
        changed_files = [
            str(path) for path in (bundle.diff.changed_files or []) if str(path).strip()
        ]
        failing_files = self._extract_failure_files(
            refs=refs, summary=summary, changed_files=changed_files
        )
        serialized_failures = [
            self._serialize_test_failure(failure)
            for failure in list(getattr(test_result, "failures", []) or [])
        ]
        structured_files = sorted(
            {
                str(failure.get("file", "")).strip()
                for failure in serialized_failures
                if str(failure.get("file", "")).strip()
            }
        )
        if structured_files:
            failing_files = structured_files

        merged_evidence_refs = [str(ref).strip() for ref in evidence_refs if str(ref).strip()]
        for path_candidate in (
            str(getattr(test_result, "stdout_path", "") or "").strip(),
            str(getattr(test_result, "stderr_path", "") or "").strip(),
        ):
            if path_candidate and path_candidate not in merged_evidence_refs:
                merged_evidence_refs.append(path_candidate)
        for failure in serialized_failures:
            excerpt_path = str(failure.get("raw_excerpt_path", "")).strip()
            if excerpt_path and excerpt_path not in merged_evidence_refs:
                merged_evidence_refs.append(excerpt_path)

        slice_root = Path(ctx.slice_root) if ctx.slice_root else Path(".")
        trace_adapter = (
            self._build_pin_registry_adapter(slice_root) if slice_root.exists() else None
        )
        engine = DownwardFlowEngine(
            run_id=ctx.run_id,
            active_layer=active_layer,
            pin_registry=trace_adapter,
        )
        batch = engine.trace_and_route(
            FailureEvidence(
                source="TEST_FAILURE",
                failing_files=failing_files,
                evidence_paths=merged_evidence_refs,
                stack_trace=summary,
            )
        )

        tickets = list(batch.tickets)
        if not tickets:
            tickets = [
                DemotionTicket(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    source="TEST_FAILURE",
                    origin_layer=active_layer,
                    hop_trace=[active_layer, "L1"],
                    target_layer="L1",
                    severity="BLOCKER",
                    diagnosis=summary or "Integration test/merge failure",
                    failing_files=failing_files,
                    evidence_refs=merged_evidence_refs,
                )
            ]

        anchors = self._anchors_from_refs(failing_files=failing_files, refs=refs)
        for failure in serialized_failures:
            file_path = str(failure.get("file", "") or "").strip()
            test_id = str(failure.get("test_id", "") or "").strip()
            if file_path:
                anchors.append(
                    {
                        "file": file_path,
                        "symbol": test_id or None,
                    }
                )

        normalized_anchors: list[dict[str, Any]] = []
        seen_anchors: set[tuple[str, int, int, str]] = set()
        for anchor in anchors:
            key = (
                str(anchor.get("file", "")).strip(),
                int(anchor.get("start_line") or 0),
                int(anchor.get("end_line") or 0),
                str(anchor.get("symbol", "")).strip(),
            )
            if not key[0] or key in seen_anchors:
                continue
            seen_anchors.add(key)
            normalized_anchors.append(anchor)
        anchors = normalized_anchors[:40]

        structured_summary = ""
        if test_result is not None:
            runner_id = str(getattr(test_result, "runner_id", "") or "").strip()
            scope = str(getattr(test_result, "scope", "") or "").strip()
            failed_count = int(getattr(test_result, "failed_tests", 0) or 0)
            details = [part for part in (f"runner={runner_id}" if runner_id else "", scope) if part]
            if failed_count > 0:
                details.append(f"failed_tests={failed_count}")
            snippets = []
            for failure in serialized_failures[:5]:
                test_id = str(failure.get("test_id", "") or "").strip()
                message = str(failure.get("message", "") or "").strip()
                if test_id and message:
                    snippets.append(f"{test_id}: {message}")
                elif test_id:
                    snippets.append(test_id)
                elif message:
                    snippets.append(message)
            if snippets:
                details.append("; ".join(snippets))
            structured_summary = " | ".join(details).strip()

        for ticket in tickets:
            ticket.slice_id = ctx.slice_id
            ticket.source = "TEST_FAILURE"
            ticket.origin_layer = active_layer
            if not ticket.hop_trace:
                ticket.hop_trace = [active_layer, ticket.target_layer]
            ticket.severity = "BLOCKER"
            if summary and summary not in ticket.diagnosis:
                ticket.diagnosis = f"{ticket.diagnosis}; {summary}".strip("; ")
            if structured_summary and structured_summary not in ticket.diagnosis:
                ticket.diagnosis = f"{ticket.diagnosis}; {structured_summary}".strip("; ")
            ticket.evidence_refs = list(
                dict.fromkeys([*ticket.evidence_refs, *merged_evidence_refs])
            )
            ticket.failing_atoms = [
                str(atom).removeprefix("PIN-ATOM-")
                for atom in ticket.failing_atoms
                if str(atom).strip()
            ]
            if failing_files and not ticket.failing_files:
                ticket.failing_files = list(failing_files)
            if anchors:
                ticket.symbol_span_anchors = anchors
            if ticket.failing_files and not ticket.component_id:
                ticket.component_id = ticket.failing_files[0].split("/")[0]
        return tickets

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
                get_layer_worktree = getattr(wm, "get_layer_worktree", None)
                if callable(get_layer_worktree):
                    dirty_candidate = get_layer_worktree(ctx.layer, "dirty")
                    clean_candidate = get_layer_worktree(ctx.layer, "clean")
                    if dirty_root is None and dirty_candidate is not None:
                        dirty_root = Path(dirty_candidate)
                    if clean_root is None and clean_candidate is not None:
                        clean_root = Path(clean_candidate)
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
            slice_test_payload: dict[str, Any] | None = None,
            full_test_payload: dict[str, Any] | None = None,
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

            if not isinstance(slice_test_payload, dict):
                reason = str(error).strip() or "Slice tests were not executed"
                slice_test_payload = self._not_run_test_payload(
                    slice_id=ctx.slice_id,
                    layer=ctx.layer,
                    reason=reason,
                )
            bundle.tests.slice_path = _write_iteration_json(
                bundle,
                evidence_root,
                "tests.slice.json",
                slice_test_payload,
            )
            if isinstance(full_test_payload, dict) and full_test_payload:
                bundle.tests.full_path = _write_iteration_json(
                    bundle,
                    evidence_root,
                    "tests.full.json",
                    full_test_payload,
                )
            else:
                bundle.tests.full_path = ""

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

        run_gates: bool | dict[str, Any] = True
        run_tests: bool | dict[str, Any] = True
        max_pending_batches = 1
        if isinstance(ctx.config, dict):
            pipeline_ci = ctx.config.get("pipeline_ci")
            if isinstance(pipeline_ci, dict):
                run_gates = cast("bool | dict[str, Any]", pipeline_ci.get("run_gates", True))
                run_tests = cast("bool | dict[str, Any]", pipeline_ci.get("run_tests", True))
                raw_max_pending = pipeline_ci.get("max_pending_batches", 1)
                try:
                    max_pending_batches = max(0, int(raw_max_pending))
                except (TypeError, ValueError):
                    max_pending_batches = 1

        def build_ci_tick_receipt(tick: Any) -> dict[str, Any]:
            layer_batch: Any | None = None
            layer_results = getattr(tick, "layer_results", None)
            if isinstance(layer_results, dict):
                layer_batch = layer_results.get(ctx.layer)

            candidate_sha = getattr(layer_batch, "candidate_sha", None)
            base_clean_sha = getattr(layer_batch, "base_clean_sha", None)
            batch_success = bool(getattr(layer_batch, "success", True)) if layer_batch else True
            batch_error = str(getattr(layer_batch, "error", "") or "")
            batch_demotion_tickets = (
                [str(item) for item in (getattr(layer_batch, "demotion_tickets", []) or [])]
                if layer_batch is not None
                else []
            )
            gates_passed = bool(getattr(layer_batch, "gates_passed", True)) if layer_batch else True
            tests_passed = bool(getattr(layer_batch, "tests_passed", True)) if layer_batch else True

            propagation_failures: list[dict[str, Any]] = []
            for prop in getattr(tick, "propagation_results", []) or []:
                if str(getattr(prop, "from_layer", "")) != str(ctx.layer):
                    continue
                if bool(getattr(prop, "success", True)):
                    continue
                propagation_failures.append(
                    {
                        "from_layer": getattr(prop, "from_layer", ""),
                        "to_layer": getattr(prop, "to_layer", ""),
                        "error": str(getattr(prop, "error", "") or ""),
                        "conflict_files": list(getattr(prop, "conflict_files", []) or []),
                    }
                )

            failed = (not batch_success) or bool(propagation_failures)
            failure_refs: list[str] = []
            if batch_error:
                failure_refs.append(f"batch_error:{batch_error}")
            for ticket_ref in batch_demotion_tickets:
                if ticket_ref:
                    failure_refs.append(f"batch_ticket:{ticket_ref}")
            for prop_failure in propagation_failures:
                prop_error = str(prop_failure.get("error", "")).strip()
                hop = f"{prop_failure.get('from_layer')}->{prop_failure.get('to_layer')}"
                if prop_error:
                    failure_refs.append(f"propagation:{hop}:{prop_error}")
                for path in prop_failure.get("conflict_files", []) or []:
                    failure_refs.append(f"propagation_conflict_file:{path}")

            failure_summary = ""
            if failed:
                segments: list[str] = []
                if batch_error:
                    segments.append(batch_error)
                if propagation_failures and not batch_error:
                    segments.append("cross-layer propagation failed")
                failure_summary = "; ".join(segments) if segments else "CI tick failed"

            return {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "main_updated": bool(getattr(tick, "main_updated", False)),
                "main_sha": getattr(tick, "main_sha", None),
                "demotions": len(getattr(tick, "demotion_tickets", []) or []),
                "candidate_sha": candidate_sha,
                "base_clean_sha": base_clean_sha,
                "failed": failed,
                "failure_summary": failure_summary,
                "failure_refs": failure_refs[:24],
                "failure_evidence": {
                    "batch_success": batch_success,
                    "batch_error": batch_error,
                    "batch_demotion_tickets": batch_demotion_tickets,
                    "gates_passed": gates_passed,
                    "tests_passed": tests_passed,
                    "propagation_failures": propagation_failures,
                },
            }

        def run_pipeline_tick() -> tuple[dict[str, Any], str]:
            try:
                tick = run_with_integration_lock(
                    lambda: wm.tick_pipeline(
                        active_layer=ctx.layer,
                        max_pending_batches=max_pending_batches,
                        run_gates=run_gates,
                        run_tests=run_tests,
                    )
                )
            except Exception as exc:
                error = str(exc)
                logger.exception("tick_pipeline failed for slice '%s'", ctx.slice_id)
                return (
                    {
                        "slice_id": ctx.slice_id,
                        "layer": ctx.layer,
                        "failed": True,
                        "failure_summary": error,
                        "failure_refs": [f"ci_tick_exception:{error}"],
                        "failure_evidence": {"exception": error},
                    },
                    error,
                )
            return build_ci_tick_receipt(tick), ""

        merge_attempts: list[dict[str, Any]] = []
        investigator_report_refs: list[str] = []
        failure_evidence: dict[str, Any] = {}
        slice_test_payload: dict[str, Any] | None = None
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
            summary = (
                f"Merge conflict after rebase retry: {merge_result.error or 'unknown merge error'}"
            )
            refs = [summary]
            refs.extend(
                str(item.get("error", "")).strip()
                for item in merge_attempts
                if str(item.get("error", "")).strip()
            )
            dirty_branch = (
                wm.layer_branch(ctx.layer, "dirty")
                if wm is not None and hasattr(wm, "layer_branch")
                else f"pdd/{ctx.run_id}/{ctx.layer}/dirty"
            )
            merge_conflict_payload: dict[str, Any] = {
                "merge_error": str(merge_result.error or "").strip(),
                "merge_attempts": list(merge_attempts),
                "dirty_branch": dirty_branch,
                "slice_root": ctx.slice_root,
                "refs": refs,
            }

            signal_id = ""
            try:
                from spec_manager.orchestration.coordination.signals import (
                    CoordinationSignal,
                    SignalNeed,
                )

                signal = CoordinationSignal(
                    run_id=ctx.run_id,
                    layer=ctx.layer,
                    slice_id=ctx.slice_id,
                    iteration=bundle.iteration,
                    classification="MERGE_CONFLICT",
                    need=SignalNeed(
                        summary=summary,
                        artifact_type="git_branch",
                        artifact_key=dirty_branch,
                        expected_shape={"resolution": "conflict_resolution_commit"},
                        confidence=1.0,
                    ),
                    payload=merge_conflict_payload,
                )
                signal.write_to(bundle.iter_dir(evidence_root))
                signal_id = signal.signal_id
            except Exception:
                logger.warning(
                    "Failed to emit MERGE_CONFLICT coordination signal for %s",
                    ctx.slice_id,
                    exc_info=True,
                )

            merge_event = {
                "event_id": signal_id or hashlib.sha256(summary.encode("utf-8")).hexdigest()[:12],
                "kind": "MERGE_CONFLICT",
                "question": summary,
                "context": merge_conflict_payload,
                "source": "INTEGRATE",
            }
            existing_events = [
                event
                for event in (bundle.implementation.under_spec_events or [])
                if isinstance(event, dict)
            ]
            _append_unique_record(existing_events, merge_event)
            bundle.implementation.under_spec_events = existing_events
            if signal_id:
                _append_unique_record(
                    bundle.under_spec.decisions,
                    {
                        "signal_id": signal_id,
                        "action": "MERGE_CONFLICT",
                        "summary": summary,
                        "source": "INTEGRATE",
                    },
                )

            record_artifacts(
                merge=merge_result,
                error=merge_result.error,
                merge_attempts=merge_attempts,
                failure_evidence=failure_evidence,
                investigator_report_refs=investigator_report_refs,
            )
            return StepResult(status="RETRY", error=summary)

        ci_tick_triggered = False
        ci_tick_error = ""
        ci_tick_receipt: dict[str, Any] = {}
        ci_tick_triggered = True
        if ctx.ci_tick_callback is not None:
            try:
                callback_receipt = run_with_integration_lock(
                    lambda: ctx.ci_tick_callback(ctx.slice_id)
                )
            except Exception as exc:
                ci_tick_error = str(exc)
                logger.exception("Post-merge CI callback failed for slice '%s'", ctx.slice_id)
            else:
                ci_tick_receipt = callback_receipt if isinstance(callback_receipt, dict) else {}
        else:
            ci_tick_receipt, ci_tick_error = run_pipeline_tick()

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
                retry_receipt, retry_error = run_pipeline_tick()
                if retry_error:
                    return False, {"error": retry_error}
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
                diagnosis = summary or ci_tick_error or "CI tick failed after integrate"
                tickets = self._build_test_failure_tickets(
                    ctx=ctx,
                    bundle=bundle,
                    refs=refs,
                    summary=diagnosis,
                    evidence_refs=list(investigator_report_refs),
                )
                if investigator_report_refs:
                    for ticket in tickets:
                        ticket.investigator_report_ref = investigator_report_refs[-1]
                merge_attempts.append(
                    {
                        "attempt": len(merge_attempts) + 1,
                        "cycle": "ci_tick",
                        "strategy": "tick_pipeline",
                        "success": False,
                        "error": diagnosis,
                    }
                )
                record_artifacts(
                    merge=merge_result,
                    emitted=tickets,
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
                    emitted_tickets=tickets,
                    error=diagnosis,
                )

        if dirty_root is None or not dirty_root.exists():
            slice_test_payload = self._not_run_test_payload(
                slice_id=ctx.slice_id,
                layer=ctx.layer,
                reason="Cannot run slice tests: dirty worktree is unavailable",
            )
        else:
            timeout_seconds = 300
            if isinstance(ctx.config, dict):
                timeout_seconds = int(ctx.config.get("test_timeout_seconds", 300) or 300)
            slice_test_result = self._run_slice_tests(
                test_root=dirty_root,
                timeout_seconds=timeout_seconds,
            )
            serialized_result = self._serialize_test_run_result(slice_test_result)
            slice_test_payload = {
                "slice_id": ctx.slice_id,
                "layer": ctx.layer,
                "result": serialized_result,
            }
            if not bool(serialized_result.get("passed", False)):
                failure_rows = [
                    row for row in serialized_result.get("failures", []) if isinstance(row, dict)
                ]
                refs: list[str] = []
                for row in failure_rows:
                    test_id = str(row.get("test_id", "") or "").strip()
                    file_path = str(row.get("file", "") or "").strip()
                    message = str(row.get("message", "") or "").strip()
                    if test_id:
                        refs.append(test_id)
                    if file_path and message:
                        refs.append(f"{file_path}: {message}")
                    elif file_path:
                        refs.append(file_path)
                    elif message:
                        refs.append(message)

                runner_id = str(serialized_result.get("runner_id", "") or "").strip() or "runner"
                failed_tests = int(serialized_result.get("failed_tests", 0) or 0)
                diagnosis = (
                    f"Slice tests failed after integrate via {runner_id}"
                    f" (failed_tests={failed_tests})"
                )
                if not refs:
                    refs.append(diagnosis)

                evidence_refs = ["tests.slice.json"]
                for path_candidate in (
                    str(serialized_result.get("stdout_path", "")).strip(),
                    str(serialized_result.get("stderr_path", "")).strip(),
                ):
                    if path_candidate:
                        evidence_refs.append(path_candidate)
                for row in failure_rows:
                    excerpt_path = str(row.get("raw_excerpt_path", "") or "").strip()
                    if excerpt_path:
                        evidence_refs.append(excerpt_path)
                evidence_refs = list(dict.fromkeys(evidence_refs))

                failure_evidence = {
                    "phase": "slice_test_failure",
                    "test_result": serialized_result,
                    "merge_attempts": merge_attempts,
                    "ci_tick_receipt": ci_tick_receipt,
                }
                tickets = self._build_test_failure_tickets(
                    ctx=ctx,
                    bundle=bundle,
                    refs=refs,
                    summary=diagnosis,
                    evidence_refs=evidence_refs,
                    test_result=slice_test_result,
                )
                record_artifacts(
                    merge=merge_result,
                    emitted=tickets,
                    error=diagnosis,
                    merge_attempts=merge_attempts,
                    ci_tick_triggered=ci_tick_triggered,
                    ci_tick_error=ci_tick_error,
                    ci_tick_receipt=ci_tick_receipt,
                    failure_evidence=failure_evidence,
                    investigator_report_refs=investigator_report_refs,
                    slice_test_payload=slice_test_payload,
                )
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    error=diagnosis,
                )

        record_artifacts(
            merge=merge_result,
            merge_attempts=merge_attempts,
            ci_tick_triggered=ci_tick_triggered,
            ci_tick_error=ci_tick_error,
            ci_tick_receipt=ci_tick_receipt,
            investigator_report_refs=investigator_report_refs,
            slice_test_payload=slice_test_payload,
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
                source="LINEAGE",
                category=cat,
                origin_layer=ctx.layer.upper(),
                hop_trace=[ctx.layer.upper(), target],
                target_layer=target,
                severity=sev if sev in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                diagnosis=f.get("evidence", "")[:500] or f.get("dimension", "Verification finding"),
                failing_files=failing_files,
                symbol_span_anchors=[
                    {
                        "file": loc.get("file", ""),
                        "symbol": loc.get("symbol"),
                        "start_line": loc.get("start_line"),
                        "end_line": loc.get("end_line"),
                    }
                ]
                if loc.get("file")
                else [],
                evidence_refs=[bundle.verification.path] if bundle.verification.path else [],
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
            governance_question = (
                "VERIFY governance failed; pipeline requires explicit remediation."
            )
            bundle.implementation.under_spec_events = [
                *[
                    e
                    for e in (bundle.implementation.under_spec_events or [])
                    if isinstance(e, dict)
                ],
                {
                    "kind": "GOVERNANCE_BLOCK",
                    "question": governance_question,
                    "context": "verify.notes.json",
                    "source": "VERIFY",
                },
            ]
            notes["findings"] = findings
            notes_path = iteration_dir / "verify.notes.json"
            notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
            bundle.verification.path = notes_path.name
            return StepResult(
                status="BLOCKED",
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
        """Resolve authoritative verification root (clean sibling only)."""
        clean_root = str(ctx.clean_sibling_root or "").strip()
        if not clean_root:
            raise RuntimeError(
                f"Verification requires clean sibling root for slice '{ctx.slice_id}'"
            )
        root = Path(clean_root)
        if not root.exists():
            raise RuntimeError(f"Verification clean sibling path missing: {root}")
        return root

    def _build_l1_verification_payload(
        self,
        ctx: SliceContext,
        bundle: EvidenceBundle,
        *,
        verification_root: Path,
        workspace: Path,
    ) -> dict[str, Any]:
        """Build concrete P6/P7 evidence for L1 verification."""
        relationship_edge_records: list[dict[str, Any]] = []
        for entry in bundle.source_index.entries or []:
            if not isinstance(entry, dict):
                continue
            payload = _extract_file_facts_payload(entry)
            raw_edges = payload.get("relationship_edges", [])
            if not isinstance(raw_edges, list):
                continue
            for edge in raw_edges:
                if isinstance(edge, dict):
                    relationship_edge_records.append(edge)

        if not relationship_edge_records:
            for edge in bundle.facts.call_graph_edges or []:
                if not isinstance(edge, dict):
                    continue
                relationship_edge_records.append(
                    {
                        "signal_type": "CALL",
                        "src_id": str(edge.get("src", "")),
                        "dst_id": str(edge.get("dst", "")),
                        "confidence": edge.get("confidence", 1.0),
                    }
                )

        relationship_facts = RelationshipFacts.from_edge_records(relationship_edge_records)
        relationship_edges = relationship_facts.to_edge_records()

        signal_type_counts: dict[str, int] = {}
        relation_nodes: set[str] = set()
        adjacency_edges: list[tuple[str, str, str]] = []
        for edge in relationship_edges:
            signal = _canonical_signal(edge.get("signal_type"))
            src = str(edge.get("src_id") or edge.get("src") or "").strip()
            dst = str(edge.get("dst_id") or edge.get("dst") or "").strip()
            if not src or not dst:
                continue
            signal_type_counts[signal] = signal_type_counts.get(signal, 0) + 1
            relation_nodes.update({src, dst})
            adjacency_edges.append((src, dst, signal))

        atoms = {
            str(atom_id).strip() for atom_id in (bundle.facts.atoms or {}) if str(atom_id).strip()
        }
        relation_nodes.update(atoms)
        relation_nodes.update(
            str(node).strip() for node in (bundle.facts.call_graph_nodes or []) if str(node).strip()
        )
        relation_nodes.update(
            str(fn_name).strip()
            for fn_name in (bundle.facts.functions or {})
            if str(fn_name).strip()
        )

        inbound: dict[str, int] = defaultdict(int)
        outbound: dict[str, int] = defaultdict(int)
        for src, dst, _ in adjacency_edges:
            outbound[src] += 1
            inbound[dst] += 1

        disconnected_nodes = sorted(
            node
            for node in relation_nodes
            if inbound.get(node, 0) == 0 and outbound.get(node, 0) == 0
        )
        p6_payload = {
            "status": "OK" if adjacency_edges or relation_nodes else "MISSING_EVIDENCE",
            "total_nodes": len(relation_nodes),
            "total_edges": len(adjacency_edges),
            "num_components": len(relation_nodes),
            "disconnected_warnings": disconnected_nodes[:50],
            "signal_type_counts": signal_type_counts,
            "edge_source": "bundle_facts",
        }

        known_atom_ids = sorted(atoms)
        lineage_edges = [edge for edge in adjacency_edges if edge[0] in atoms or edge[1] in atoms]
        referenced_atoms = {edge[0] for edge in lineage_edges if edge[0] in atoms}
        referenced_atoms.update(edge[1] for edge in lineage_edges if edge[1] in atoms)
        orphan_atoms = sorted(atom for atom in atoms if atom not in referenced_atoms)
        p7_payload = {
            "status": "OK" if known_atom_ids else "MISSING_ATOMS",
            "import_edges": len([edge for edge in adjacency_edges if edge[2] == "REFERENCE"]),
            "lineage_edges": len(lineage_edges),
            "known_atoms": len(known_atom_ids),
            "orphan_atoms": len(orphan_atoms),
            "orphan_atom_ids": orphan_atoms[:50],
            "edge_source": "bundle_facts",
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
            "facts_summary": {
                "functions": len(bundle.facts.functions or {}),
                "atoms": len(bundle.facts.atoms or {}),
                "remaining_gap_pins": len(bundle.facts.remaining_gap_pins or []),
                "stub_nodes": len(bundle.facts.stub_nodes or []),
            },
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
    AnalyzeStep,
    GapExplorationStep,
    PlanStep,
    ImplementStep,
    CoordinateStep,
    PromoteStep,
    IntegrateStep,
    VerifyStep,
    AlignStep,
)
L1_REACTIVE_BUILD_STEPS: tuple[type, ...] = (
    CollectBaselineStep,
    AnalyzeStep,
    GapExplorationStep,
    PlanStep,
    ImplementStep,
    CoordinateStep,
    PromoteStep,
    IntegrateStep,
    VerifyStep,
    AlignStep,
)
ARCHITECTURE_MODE_STEPS: tuple[type, ...] = (
    CollectBaselineStep,
    AnalyzeStep,
    GapExplorationStep,
    PlanStep,
    ImplementStep,
    CoordinateStep,
    PromoteStep,
    IntegrateStep,
    VerifyStep,
    AlignStep,
)
CODE_QUALITY_MODE_STEPS: tuple[type, ...] = DEFAULT_BUILD_STEPS

RUN_MODE_STEP_DISPATCH: dict[LifecycleRunMode, dict[Layer, tuple[type, ...]]] = {
    "build": {
        "l1": L1_REACTIVE_BUILD_STEPS,
        "l2": DEFAULT_BUILD_STEPS,
        "l3": DEFAULT_BUILD_STEPS,
    },
    "qa": {
        "l1": (CollectBaselineStep, IntegrateStep, VerifyStep),
        "l2": (CollectBaselineStep, IntegrateStep, VerifyStep),
        "l3": (CollectBaselineStep, IntegrateStep, VerifyStep),
    },
    "architecture": {
        "l1": L1_REACTIVE_BUILD_STEPS,
        "l2": ARCHITECTURE_MODE_STEPS,
        "l3": ARCHITECTURE_MODE_STEPS,
    },
    "code_quality": {
        "l1": L1_REACTIVE_BUILD_STEPS,
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
        under_spec_resolver: Any = None,
    ) -> None:
        self._wm = worktree_manager
        self._workspace_manager = workspace_manager
        self._branch_manager = branch_manager
        self._workspace_root = workspace_root
        self._dm = demotion_manager or DemotionManager(workspace_root)
        self._planner = planner
        self._under_spec_resolver = under_spec_resolver
        from spec_manager.core.gap_queue import GapQueue

        self._gap_queue = GapQueue()
        self._steps_override = steps
        self._step_cache: dict[tuple[LifecycleRunMode, Layer], list[Any]] = {}
        self._phase0_quality_gate_cache: dict[tuple[str, str], tuple[bool, str]] = {}

    @staticmethod
    def _normalize_lifecycle_mode(value: str) -> LifecycleRunMode:
        normalized = str(value).strip().lower()
        if normalized in {"build", "qa", "architecture", "code_quality"}:
            return cast("LifecycleRunMode", normalized)
        return "build"

    @property
    def worktree_manager(self) -> Any:
        """Public accessor used by external scheduler integrations."""
        return self._wm

    def _instantiate_steps(self, step_types: tuple[type, ...]) -> list[Any]:
        instances: list[Any] = []
        for step_cls in step_types:
            if step_cls is IntegrateStep:
                instances.append(step_cls())
            elif step_cls is GapExplorationStep:
                instances.append(step_cls(planner=self._planner, gap_queue=self._gap_queue))
            elif step_cls in (PlanStep, CoordinateStep):
                instances.append(
                    step_cls(
                        planner=self._planner,
                        resolver=self._under_spec_resolver,
                    )
                )
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

    def _resolve_phase0_quality_gate(self, run_context: RunContext) -> tuple[bool, str]:
        """Resolve and cache pre-loop Phase 0 library-quality gate status."""
        run_id = str(run_context.run_id or "").strip()
        workspace_token = str(run_context.workspace_root or "").strip()
        cache_key = (run_id, workspace_token)
        cached = self._phase0_quality_gate_cache.get(cache_key)
        if cached is not None:
            return cached

        config = run_context.config if isinstance(run_context.config, dict) else {}
        configured_gate = config.get("phase0_library_quality")
        if isinstance(configured_gate, dict):
            configured_passed = configured_gate.get("gate_passed")
            if isinstance(configured_passed, bool):
                if configured_passed:
                    resolved = (True, "")
                else:
                    failed_dims = configured_gate.get("failed_gate_dimensions", [])
                    failed = (
                        ", ".join(str(dim).strip() for dim in failed_dims if str(dim).strip())
                        if isinstance(failed_dims, list)
                        else ""
                    )
                    detail = f" Failed dimensions: {failed}." if failed else ""
                    resolved = (
                        False,
                        "Phase 0 library quality gate failed before PromotionLoop start." + detail,
                    )
                self._phase0_quality_gate_cache[cache_key] = resolved
                return resolved

        workspace_root = (
            Path(run_context.workspace_root)
            if str(run_context.workspace_root or "").strip()
            else self._workspace_root
        )
        phase0_output_dir = workspace_root / "phase0_output"
        if not phase0_output_dir.exists():
            resolved = (True, "")
            self._phase0_quality_gate_cache[cache_key] = resolved
            return resolved

        report_path = phase0_output_dir / "library_quality.report.json"
        report_payload = _read_json_file(report_path)
        if isinstance(report_payload, dict):
            gate_passed = report_payload.get("gate_passed")
            if isinstance(gate_passed, bool):
                if gate_passed:
                    resolved = (True, "")
                else:
                    failed_dims = report_payload.get("failed_gate_dimensions", [])
                    failed = (
                        ", ".join(str(dim).strip() for dim in failed_dims if str(dim).strip())
                        if isinstance(failed_dims, list)
                        else ""
                    )
                    detail = f" Failed dimensions: {failed}." if failed else ""
                    resolved = (
                        False,
                        "Phase 0 library quality gate failed before PromotionLoop start." + detail,
                    )
                self._phase0_quality_gate_cache[cache_key] = resolved
                return resolved

        try:
            from spec_manager.intake.quality.library_quality_validator import validate_libraries

            report = validate_libraries(workspace_root, phase0_output_dir=phase0_output_dir)
            if report.gate_passed:
                resolved = (True, "")
            else:
                failed = ", ".join(report.failed_gate_dimensions)
                detail = f" Failed dimensions: {failed}." if failed else ""
                resolved = (
                    False,
                    "Phase 0 library quality gate failed before PromotionLoop start." + detail,
                )
        except Exception as exc:
            resolved = (
                False,
                f"Phase 0 library quality validation failed before PromotionLoop start: {exc}",
            )
        self._phase0_quality_gate_cache[cache_key] = resolved
        return resolved

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
        """Merge iteration deltas into canonical facts already produced upstream."""
        functions = dict(bundle.facts.functions or {})
        stores = dict(bundle.facts.stores or {})
        atoms = dict(bundle.facts.atoms or {})
        remaining_gap_pins = list(bundle.facts.remaining_gap_pins or [])
        stub_nodes = list(bundle.facts.stub_nodes or [])
        call_graph_nodes = {
            str(node).strip() for node in (bundle.facts.call_graph_nodes or []) if str(node).strip()
        }
        call_graph_edges = list(bundle.facts.call_graph_edges or [])
        store_owners = {
            str(store_id).strip(): [
                str(owner).strip()
                for owner in owners
                if isinstance(owner, str) and str(owner).strip()
            ]
            for store_id, owners in (bundle.facts.store_owners or {}).items()
            if str(store_id).strip() and isinstance(owners, list)
        }
        llm_claims = list(bundle.facts.llm_claims or [])

        for pin in bundle.implementation.pin_proposals or []:
            pin_id = pin.get("pin_id") or pin.get("id") or pin.get("fqn") or ""
            if not pin_id:
                continue
            atoms[pin_id] = {
                "file": pin.get("file", ""),
                "boundaries": pin.get("span", {}),
                "responsibilities": pin.get("responsibilities", []),
            }
            call_graph_nodes.add(str(pin_id).strip())

        for edge in bundle.implementation.edge_proposals or []:
            signal_type = _canonical_signal(
                edge.get("signal_type") or edge.get("type") or edge.get("projection_type")
            )
            src = str(
                edge.get("src") or edge.get("src_id") or edge.get("pin_func_id") or ""
            ).strip()
            dst = str(
                edge.get("dst")
                or edge.get("dst_id")
                or edge.get("arch_location")
                or edge.get("store_id")
                or ""
            ).strip()

            if signal_type == "CALL" and src and dst:
                call_graph_nodes.update({src, dst})
                _append_unique_record(
                    call_graph_edges,
                    {
                        "src": src,
                        "dst": dst,
                        "signal_type": "CALL",
                        "confidence": edge.get("confidence", 1.0),
                    },
                )

            if signal_type != "STORE_TOUCH":
                continue
            store_id = dst
            if not store_id:
                continue
            owner = src
            owner_atoms = [owner] if owner else []
            existing = stores.get(store_id, {})
            if not isinstance(existing, dict):
                existing = {}
            previous = existing.get("owner_atoms", [])
            stores[store_id] = {
                "owner_atoms": sorted(set(previous + owner_atoms)),
                "schema": existing.get("schema", {}),
            }
            current_store_owners = set(store_owners.get(store_id, []))
            current_store_owners.update(owner_atoms)
            store_owners[store_id] = sorted(owner for owner in current_store_owners if owner)

        gap_inputs: list[dict[str, Any]] = []
        for gap in bundle.gaps.open_gaps or []:
            if isinstance(gap, dict):
                gap_inputs.append(gap)
        for gap in bundle.implementation.gap_inventory or []:
            if isinstance(gap, dict):
                gap_inputs.append(gap)

        comment_gap_kinds = {"spec_comment_unimplemented", "executable_comment", "comment_gap"}
        for gap in gap_inputs:
            raw_kind = gap.get("kind") or gap.get("gap_type") or gap.get("type") or ""
            kind = str(raw_kind).strip()
            kind_lower = kind.lower()
            if "stub" in kind_lower:
                node_id = (
                    str(gap.get("pin_id") or gap.get("atom_id") or gap.get("anchor") or "").strip()
                    or str(gap.get("file") or "").strip()
                )
                _append_unique_record(
                    stub_nodes,
                    {
                        "node_id": node_id,
                        "file_path": gap.get("file")
                        or (gap.get("location") or {}).get("file")
                        or "",
                        "line": (gap.get("span") or {}).get("start_line"),
                        "stub_type": kind or "stub_gap",
                    },
                )
            if "comment" not in kind_lower and kind_lower not in comment_gap_kinds:
                continue
            _append_unique_record(
                remaining_gap_pins,
                {
                    "pin_id": str(
                        gap.get("pin_id") or gap.get("atom_id") or gap.get("anchor") or ""
                    ).strip(),
                    "kind": kind,
                    "file": gap.get("file") or (gap.get("location") or {}).get("file"),
                    "description": gap.get("description", ""),
                    "span": gap.get("span", {}),
                },
            )

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
        bundle.facts.remaining_gap_pins = remaining_gap_pins
        bundle.facts.stub_nodes = stub_nodes
        bundle.facts.call_graph_nodes = sorted(node for node in call_graph_nodes if node)
        bundle.facts.call_graph_edges = call_graph_edges
        bundle.facts.store_owners = {
            store_id: sorted(set(owners))
            for store_id, owners in store_owners.items()
            if store_id and owners
        }
        bundle.facts.llm_claims = llm_claims
        if (
            bundle.facts.functions
            or bundle.facts.stores
            or bundle.facts.atoms
            or bundle.facts.remaining_gap_pins
            or bundle.facts.stub_nodes
            or bundle.facts.call_graph_nodes
            or bundle.facts.call_graph_edges
            or bundle.facts.store_owners
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
            or bundle.facts.remaining_gap_pins
            or bundle.facts.stub_nodes
            or bundle.facts.call_graph_nodes
            or bundle.facts.call_graph_edges
            or bundle.facts.store_owners
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
                    "remaining_gap_pins": bundle.facts.remaining_gap_pins,
                    "stub_nodes": bundle.facts.stub_nodes,
                    "call_graph_nodes": bundle.facts.call_graph_nodes,
                    "call_graph_edges": bundle.facts.call_graph_edges,
                    "store_owners": bundle.facts.store_owners,
                    "constraints_refs": bundle.facts.constraints_refs,
                    "llm_claims": bundle.facts.llm_claims,
                },
            )

        if (
            bundle.gaps.path
            or bundle.gaps.open_gaps
            or bundle.gaps.stagnation
            or bundle.gaps.analysis
            or bundle.gaps.planner_outputs
        ):
            bundle.gaps.path = _write_iteration_json(
                bundle,
                evidence_root,
                "gaps.json",
                {
                    "open_gaps": bundle.gaps.open_gaps,
                    "stagnation": bundle.gaps.stagnation,
                    "analysis": bundle.gaps.analysis,
                    "planner_outputs": bundle.gaps.planner_outputs,
                },
            )

        if bundle.plan.under_spec_events:
            bundle.plan.under_spec_events_path = _write_iteration_json(
                bundle,
                evidence_root,
                "plan.under_spec.events.json",
                bundle.plan.under_spec_events,
            )
        else:
            bundle.plan.under_spec_events_path = ""
        if (
            bundle.plan.path
            or bundle.plan.intentions
            or bundle.plan.plan_artifacts
            or bundle.plan.under_spec_events
            or bundle.plan.under_spec_events_path
            or bundle.plan.constraints_snapshot_hash
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
                    "plan_artifacts": bundle.plan.plan_artifacts,
                    "under_spec_events_path": bundle.plan.under_spec_events_path,
                    "constraints_snapshot_hash": bundle.plan.constraints_snapshot_hash,
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
            or bundle.implementation.pin_proposals_path
            or bundle.implementation.edge_proposals_path
            or bundle.implementation.under_spec_events_path
            or bundle.implementation.tests_added_path
            or bundle.implementation.notes_path
        ):
            bundle.implementation.result_path = _write_iteration_json(
                bundle,
                evidence_root,
                "impl.result.json",
                {
                    "patch_path": bundle.implementation.patch_path,
                    "pin_proposals_path": bundle.implementation.pin_proposals_path,
                    "edge_proposals_path": bundle.implementation.edge_proposals_path,
                    "under_spec_events_path": bundle.implementation.under_spec_events_path,
                    "tests_added_path": bundle.implementation.tests_added_path,
                    "notes_path": bundle.implementation.notes_path,
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
            or bundle.demotions.records
        ):
            bundle.demotions.path = _write_iteration_json(
                bundle,
                evidence_root,
                "demotions.json",
                {
                    "emitted": bundle.demotions.emitted,
                    "applied": bundle.demotions.applied,
                    "pending": bundle.demotions.pending,
                    "records": bundle.demotions.records,
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

    @staticmethod
    def _ticket_target_layer_key(target_layer: str) -> Layer:
        """Map demotion ticket layer labels (L1/L2/L3) to layer keys."""
        normalized = str(target_layer).strip().upper()
        if normalized == "L2":
            return "l2"
        if normalized == "L3":
            return "l3"
        return "l1"

    def _resolve_demotion_apply_root(
        self,
        *,
        ctx: SliceContext,
        ticket: DemotionTicket,
    ) -> tuple[Path | None, str]:
        """Resolve the concrete worktree root where a demotion should apply."""
        wm = ctx.worktree_manager
        if wm is None:
            if ctx.slice_root:
                return Path(ctx.slice_root), ""
            return None, "No slice root available for demotion apply"

        target_layer = self._ticket_target_layer_key(ticket.target_layer)
        get_layer_worktree = getattr(wm, "get_layer_worktree", None)
        dirty_root = (
            get_layer_worktree(target_layer, "dirty") if callable(get_layer_worktree) else None
        )
        if dirty_root is None:
            return (
                None,
                f"No dirty worktree for demotion target layer {ticket.target_layer}",
            )
        return Path(dirty_root), ""

    @staticmethod
    def _commit_demotion_reopen(
        *,
        ctx: SliceContext,
        ticket: DemotionTicket,
        apply_root: Path,
        apply_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Commit demotion changes so dirty/clean divergence is explicit."""
        if not bool(apply_result.get("applied", False)):
            return apply_result

        wm = ctx.worktree_manager
        vcs = getattr(wm, "vcs", None) if wm is not None else None
        if vcs is None or not hasattr(vcs, "commit_all"):
            return apply_result

        commit_message = (
            f"demotion({str(ticket.target_layer).lower()}): reopen for ticket {ticket.ticket_id}"
        )
        committed, commit_error = vcs.commit_all(apply_root, commit_message)
        apply_result["layer_dirty_commit"] = {
            "layer": ticket.target_layer,
            "root": str(apply_root),
            "committed": bool(committed),
            "error": str(commit_error or ""),
        }
        if committed:
            return apply_result

        errors = apply_result.setdefault("errors", [])
        if isinstance(errors, list):
            errors.append(
                f"Failed to commit demotion into {ticket.target_layer} dirty branch: "
                f"{commit_error or 'unknown commit error'}"
            )
        apply_result["applied"] = False
        return apply_result

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
        raw_metadata = slice_ref.metadata if isinstance(slice_ref.metadata, dict) else {}
        metadata = dict(raw_metadata)

        wake_count_seed = 0
        try:
            wake_count_seed = int(metadata.get("wake_count", 0) or 0)
        except (TypeError, ValueError):
            wake_count_seed = 0

        wake_events_raw = metadata.get("wake_events", [])
        wake_events: list[dict[str, Any]] = []
        if isinstance(wake_events_raw, list):
            for item in wake_events_raw:
                if isinstance(item, dict):
                    wake_events.append(dict(item))
        wake_requires_triage = bool(metadata.get("wake_requires_triage", False))

        last_signal_id = str(metadata.get("last_signal_id", "")).strip()
        wake_payload_raw = metadata.get("wake_payload", {})
        wake_payload = dict(wake_payload_raw) if isinstance(wake_payload_raw, dict) else {}
        if wake_events:
            for event in wake_events:
                event_signal = str(event.get("signal_id", "")).strip()
                if event_signal:
                    last_signal_id = event_signal
                event_payload = event.get("wake_payload")
                if isinstance(event_payload, dict):
                    wake_payload = dict(event_payload)
        elif last_signal_id or wake_payload:
            wake_events = [
                {
                    "signal_id": last_signal_id,
                    "slice_id": slice_ref.slice_id,
                    "layer": str(slice_ref.layer),
                    "reason": str(metadata.get("wake_reason", "")).strip(),
                    "artifact_key": str(metadata.get("wake_artifact_key", "")).strip(),
                    "wake_payload": dict(wake_payload),
                }
            ]

        def build_slice_result(**kwargs: Any) -> SliceResult:
            kwargs.setdefault("last_signal_id", last_signal_id)
            kwargs.setdefault("wake_payload", dict(wake_payload))
            return SliceResult(**kwargs)

        gate_passed, gate_error = self._resolve_phase0_quality_gate(run_context)
        if not gate_passed:
            logger.warning(
                "Slice '%s' blocked before iteration start: %s",
                slice_ref.slice_id,
                gate_error,
            )
            return build_slice_result(
                slice_id=slice_ref.slice_id,
                status="FAILED",
                iterations=0,
                remaining_gaps=0,
                demotion_tickets=[],
                error=gate_error,
            )

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
            get_layer_worktree = getattr(ctx.worktree_manager, "get_layer_worktree", None)
            dirty = get_layer_worktree(ctx.layer, "dirty") if callable(get_layer_worktree) else None
            clean = get_layer_worktree(ctx.layer, "clean") if callable(get_layer_worktree) else None
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
        resume_iteration_seed = _max_persisted_iteration(
            evidence_root,
            run_context.run_id,
            slice_ref.slice_id,
        )
        iteration = max(resume_iteration_seed, 0)
        waiting_iterations = max(wake_count_seed, 0)

        # Per-ticket retry budget: track (failing_files_key, gate) → count
        retry_tracker: dict[tuple[str, str], int] = {}
        retry_budget = 3

        bundle = EvidenceBundle(
            run_id=run_context.run_id,
            slice_id=slice_ref.slice_id,
            iteration=iteration,
            created_at=_now_iso(),
            mode=run_context.mode,
            workspace_root=run_context.workspace_root,
            slice_root=slice_ref.worktree_path,
        )
        if seed_gap_set and seed_gap_set.open_gaps and iteration == 0:
            bundle.gaps.open_gaps = [
                _normalize_gap_record(gap)
                for gap in seed_gap_set.open_gaps
                if isinstance(gap, dict)
            ]
            bundle.gaps.path = "gaps.json"
        if wake_events:
            for idx, event in enumerate(wake_events, start=1):
                event_signal = str(event.get("signal_id", "")).strip()
                wake_event_payload = (
                    dict(event.get("wake_payload", {}))
                    if isinstance(event.get("wake_payload"), dict)
                    else {}
                )
                _append_unique_record(
                    bundle.under_spec.decisions,
                    {
                        "source": "WAKE_EVENT",
                        "sequence": idx,
                        "signal_id": event_signal,
                        "reason": str(event.get("reason", "")).strip(),
                        "artifact_key": str(event.get("artifact_key", "")).strip(),
                        "wake_payload": wake_event_payload,
                    },
                )
        if wake_requires_triage:
            merge_summary = str(wake_payload.get("wake_sync_error", "")).strip() or (
                "Wake sync reported merge conflict and requires triage"
            )
            conflict_event = {
                "event_id": last_signal_id
                or hashlib.sha256(merge_summary.encode("utf-8")).hexdigest()[:12],
                "kind": "MERGE_CONFLICT",
                "question": f"Resolve wake-sync merge conflict: {merge_summary}",
                "context": dict(wake_payload),
                "source": "WAKE_SYNC",
            }
            existing_events = [
                event
                for event in (bundle.implementation.under_spec_events or [])
                if isinstance(event, dict)
            ]
            _append_unique_record(existing_events, conflict_event)
            bundle.implementation.under_spec_events = existing_events

        if iteration >= max_iters:
            return build_slice_result(
                slice_id=ctx.slice_id,
                status="MAX_ITERATIONS",
                iterations=iteration,
                remaining_gaps=0,
                demotion_tickets=all_tickets,
            )

        prioritize_coordinate = wake_requires_triage

        def has_merge_conflict_under_spec() -> bool:
            return any(
                str(event.get("kind", "")).strip().upper() == "MERGE_CONFLICT"
                for event in (bundle.implementation.under_spec_events or [])
                if isinstance(event, dict)
            )

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
            bundle.iteration = iteration
            bundle.demotions.emitted = []
            bundle.demotions.applied = []
            bundle.demotions.pending = []

            retry = False
            waiting = False
            step_statuses: dict[str, str] = {}

            iteration_steps = active_steps
            if prioritize_coordinate:
                coordinate_steps = [
                    step for step in active_steps if getattr(step, "name", "") == "COORDINATE"
                ]
                if coordinate_steps:
                    non_coordinate_steps = [
                        step for step in active_steps if getattr(step, "name", "") != "COORDINATE"
                    ]
                    iteration_steps = [*coordinate_steps, *non_coordinate_steps]
                prioritize_coordinate = False

            for step in iteration_steps:
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
                        return build_slice_result(
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
                        apply_root, apply_root_error = self._resolve_demotion_apply_root(
                            ctx=ctx,
                            ticket=ticket,
                        )
                        if apply_root is None:
                            apply_result: dict[str, Any] = {
                                "ticket_id": ticket.ticket_id,
                                "applied": False,
                                "patches": [],
                                "gap_evidence_added": 0,
                                "registry_updates": [],
                                "routing_patches": [],
                                "errors": [apply_root_error],
                            }
                        else:
                            apply_result = self._dm.apply(
                                ticket,
                                apply_root,
                                gap_queue=self._gap_queue,
                                branch_manager=ctx.branch_manager,
                            )
                            apply_result = self._commit_demotion_reopen(
                                ctx=ctx,
                                ticket=ticket,
                                apply_root=apply_root,
                                apply_result=apply_result,
                            )
                        bundle.demotions.emitted.append(ticket.ticket_id)
                        if apply_result.get("applied", False):
                            bundle.demotions.applied.append(ticket.ticket_id)
                        else:
                            bundle.demotions.pending.append(ticket.ticket_id)
                        bundle.demotions.records.append(
                            {
                                "ticket": ticket.to_dict(),
                                "apply_result": apply_result,
                                "evidence_refs": list(ticket.evidence_refs),
                            }
                        )
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
                            return build_slice_result(
                                slice_id=ctx.slice_id,
                                status="STAGNATED",
                                iterations=iteration,
                                remaining_gaps=len(bundle.gaps.open_gaps),
                                demotion_tickets=all_tickets,
                                error=f"Per-ticket retry budget exceeded for gate={tracker_key[1]}",
                            )

                    # Ticket questions without available constraints force BLOCKED.
                    unresolved_ticket_questions = [
                        str(question).strip()
                        for ticket in result.emitted_tickets
                        for question in (ticket.questions or [])
                        if str(question).strip()
                    ]
                    if unresolved_ticket_questions and not (bundle.facts.constraints_refs or []):
                        existing_events = [
                            event
                            for event in (bundle.implementation.under_spec_events or [])
                            if isinstance(event, dict)
                        ]
                        for question in unresolved_ticket_questions:
                            existing_events.append(
                                {
                                    "kind": "DEMOTION_UNDER_SPEC",
                                    "question": question,
                                    "context": "demotions.json",
                                    "source": "DEMOTION_TICKET",
                                }
                            )
                        bundle.implementation.under_spec_events = existing_events
                        result.status = "BLOCKED"
                        if not result.error:
                            result.error = "Demotion ticket raised unresolved under-spec questions"

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
                        return build_slice_result(
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
                    combined_under_spec_events = [
                        *list(bundle.implementation.under_spec_events or []),
                        *list(bundle.plan.under_spec_events or []),
                    ]
                    for event in combined_under_spec_events:
                        if not isinstance(event, dict):
                            continue
                        if q := event.get("question"):
                            questions.append(q)
                    for ticket in all_tickets:
                        for q in ticket.questions or []:
                            cleaned = str(q).strip()
                            if cleaned:
                                questions.append(cleaned)
                    questions = list(dict.fromkeys(questions))
                    return build_slice_result(
                        slice_id=ctx.slice_id,
                        status="BLOCKED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        blocked_questions=questions,
                    )

                if result.status == "RETRY":
                    # A gate/test/merge failed — restart iteration
                    if step.name == "INTEGRATE" and has_merge_conflict_under_spec():
                        prioritize_coordinate = True
                    retry = True
                    break

                if result.status == "FAIL":
                    bundle.status = "FAILED"
                    self._persist_iteration_artifacts(ctx, bundle)
                    bundle.save(evidence_root)
                    return build_slice_result(
                        slice_id=ctx.slice_id,
                        status="FAILED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        error=result.error,
                    )

            # Handle WAITING: save bundle and return to scheduler
            if waiting:
                waiting_iterations += 1
                # WAITING is not stagnation; reset counters so parked slices do not
                # amplify into false stagnation failures.
                self._gap_queue.mark_progress()
                self._gap_queue.last_content_hash = ""
                # Collect pending signal info from bundle
                combined_under_spec_events = [
                    *list(bundle.implementation.under_spec_events or []),
                    *list(bundle.plan.under_spec_events or []),
                ]
                pending = [
                    {"question": e.get("question", ""), "kind": e.get("kind", "")}
                    for e in combined_under_spec_events
                    if isinstance(e, dict)
                ]
                if waiting_iterations >= run_context.max_wait_cycles:
                    bundle.status = "BLOCKED"
                    self._persist_iteration_artifacts(ctx, bundle)
                    bundle.save(evidence_root)
                    blocked_questions = [
                        str(item.get("question", "")).strip()
                        for item in pending
                        if str(item.get("question", "")).strip()
                    ]
                    return build_slice_result(
                        slice_id=ctx.slice_id,
                        status="BLOCKED",
                        iterations=iteration,
                        remaining_gaps=len(bundle.gaps.open_gaps),
                        demotion_tickets=all_tickets,
                        blocked_questions=blocked_questions,
                        pending_signals=pending,
                        wake_count=waiting_iterations,
                        error=f"Exceeded max_wait_cycles ({run_context.max_wait_cycles})",
                    )
                return build_slice_result(
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
                    return build_slice_result(
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
                return build_slice_result(
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
        bundle.status = "FAILED"
        self._persist_iteration_artifacts(ctx, bundle)
        bundle.save(evidence_root)
        return build_slice_result(
            slice_id=ctx.slice_id,
            status="MAX_ITERATIONS",
            iterations=iteration,
            remaining_gaps=len(bundle.gaps.open_gaps),
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

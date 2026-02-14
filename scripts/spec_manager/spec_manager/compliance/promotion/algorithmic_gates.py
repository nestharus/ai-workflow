"""Algorithmic layer gate checks for promotion gating."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.branches.gap_detection import scan_stubs
from spec_manager.compliance.promotion.call_graph import (
    CallGraphEdge,
    StrategyRegistry,
    build_call_graph,
)
from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.code_analysis import infer_adjacency_signals

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile


def check_no_remaining_comments(
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
    gap_inventory: list[dict[str, Any]] | None = None,
) -> GateCheckResult:
    """Gate: no unresolved spec comments in the authoritative gap inventory."""
    del algorithmic_files, analyzed  # Legacy inputs; gate now uses gap inventory evidence only.

    start = time.monotonic()
    inventory = gap_inventory
    if inventory is None:
        raw_inventory = gate_spec.params.get("gap_inventory")
        if isinstance(raw_inventory, list):
            inventory = [item for item in raw_inventory if isinstance(item, dict)]

    if inventory is None:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.NO_REMAINING_COMMENTS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[
                {
                    "reason": "gap_inventory_missing",
                    "message": "NO_REMAINING_COMMENTS requires gap inventory evidence",
                }
            ],
            summary="Gap inventory not provided for NO_REMAINING_COMMENTS",
            duration_ms=duration,
        )

    expected_kinds = {
        str(item).strip()
        for item in gate_spec.params.get(
            "comment_gap_kinds",
            ["SPEC_COMMENT_UNIMPLEMENTED", "executable_comment"],
        )
        if str(item).strip()
    }

    findings: list[dict[str, Any]] = []
    for gap in inventory:
        raw_kind = gap.get("kind") or gap.get("gap_type") or gap.get("type")
        kind = str(raw_kind).strip() if raw_kind is not None else ""
        if kind not in expected_kinds:
            continue
        findings.append(
            {
                "kind": kind,
                "file": gap.get("file") or (gap.get("location") or {}).get("file"),
                "description": gap.get("description", ""),
                "span": gap.get("span", {}),
            }
        )

    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.NO_REMAINING_COMMENTS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=(
            "Gap inventory contains no unresolved spec-comment gaps"
            if passed
            else f"Gap inventory contains {len(findings)} unresolved spec-comment gap(s)"
        ),
        duration_ms=duration,
    )


def check_no_stub_functions(
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: No stub functions in algorithmic code."""
    start = time.monotonic()
    all_findings: list[dict[str, Any]] = []

    if analyzed is not None:
        for af in analyzed:
            for func in af.analysis.functions:
                if func.is_stub:
                    all_findings.append(
                        {
                            "file_path": af.path,
                            "line": func.start_line,
                            "name": func.name,
                            "stub_type": func.stub_reason or "unknown",
                        }
                    )
    else:
        for file_path in algorithmic_files:
            stubs = scan_stubs(file_path)
            for stub in stubs:
                all_findings.append(
                    {
                        "file_path": stub.file_path,
                        "line": stub.line,
                        "name": stub.name,
                        "stub_type": stub.stub_type,
                    }
                )

    passed = len(all_findings) == 0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.NO_STUB_FUNCTIONS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=all_findings,
        summary=(
            "No stub functions found in algorithmic code"
            if passed
            else f"Found {len(all_findings)} stub function(s) in algorithmic code"
        ),
        duration_ms=duration,
    )


def check_all_tests_pass(
    test_command: list[str],
    project_root: Path,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: all algorithmic tests pass."""
    start = time.monotonic()
    timeout_seconds = gate_spec.params.get("timeout_seconds", 300)

    try:
        result = subprocess.run(
            test_command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        passed = result.returncode == 0
        output = result.stdout + result.stderr
        findings: list[dict[str, Any]] = []
        if not passed:
            findings.append(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout[:2000],
                    "stderr": result.stderr[:2000],
                }
            )
    except subprocess.TimeoutExpired:
        passed = False
        output = f"Test command timed out after {timeout_seconds}s"
        findings = [{"error": output}]
    except FileNotFoundError:
        passed = False
        output = f"Test command not found: {test_command}"
        findings = [{"error": output}]

    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.ALL_TESTS_PASS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=(
            "All algorithmic tests passed" if passed else f"Test command failed: {output[:200]}"
        ),
        duration_ms=duration,
    )


def _resolve_entrypoints(nodes: set[str], raw_entrypoints: list[str]) -> set[str]:
    """Resolve configured entrypoint names to graph node ids."""
    resolved: set[str] = set()
    if not nodes:
        return resolved

    for entry in raw_entrypoints:
        candidate = entry.strip()
        if not candidate:
            continue
        if candidate in nodes:
            resolved.add(candidate)
            continue

        short = candidate.rsplit(".", 1)[-1]
        matches = {node for node in nodes if node.rsplit(".", 1)[-1] == short}
        if len(matches) == 1:
            resolved.update(matches)
            continue

        if candidate.endswith(".*"):
            prefix = candidate[:-2]
            resolved.update(node for node in nodes if node.startswith(prefix))

    return resolved


def _forward_reachable(entrypoints: set[str], edges: list[CallGraphEdge]) -> set[str]:
    """Compute directed reachability from entrypoints."""
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.caller, set()).add(edge.callee)

    reachable = set(entrypoints)
    frontier = set(entrypoints)
    while frontier:
        current = frontier.pop()
        for nxt in adjacency.get(current, set()):
            if nxt in reachable:
                continue
            reachable.add(nxt)
            frontier.add(nxt)
    return reachable


def check_call_graph_connected(
    algorithmic_files: list[Path],
    project_root: Path,
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
    registry: StrategyRegistry | None = None,
) -> GateCheckResult:
    """Gate: every target node is reachable from declared entrypoints."""
    start = time.monotonic()
    entry_points = [
        str(item)
        for item in gate_spec.params.get("entry_points", [])
        if isinstance(item, str) and item.strip()
    ]
    target_nodes_raw = [
        str(item)
        for item in gate_spec.params.get("pin_function_nodes", [])
        if isinstance(item, str) and item.strip()
    ]
    min_confidence = float(gate_spec.params.get("min_confidence", 0.6))

    graph_result = build_call_graph(
        algorithmic_files=algorithmic_files,
        project_root=project_root,
        analyzed=analyzed,
        registry=registry,
    )

    if not graph_result.nodes:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "empty_call_graph"}],
            summary="Call graph evidence unavailable",
            duration_ms=duration,
        )

    resolved_entrypoints = _resolve_entrypoints(graph_result.nodes, entry_points)
    if not resolved_entrypoints:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            mode=gate_spec.mode.value,
            status=GateStatus.AMBIGUOUS,
            score=0.0,
            findings=[
                {
                    "reason": "entrypoints_missing_or_unresolved",
                    "configured_entry_points": entry_points,
                }
            ],
            summary="Entry points are required to assess call reachability",
            duration_ms=duration,
        )

    high_conf_edges = [edge for edge in graph_result.edges if edge.confidence >= min_confidence]
    low_conf_edges = [edge for edge in graph_result.edges if edge.confidence < min_confidence]

    reachable = _forward_reachable(resolved_entrypoints, high_conf_edges)

    if target_nodes_raw:
        resolved_targets = _resolve_entrypoints(graph_result.nodes, target_nodes_raw)
    else:
        resolved_targets = set(graph_result.nodes)

    if not resolved_targets:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            mode=gate_spec.mode.value,
            status=GateStatus.AMBIGUOUS,
            score=0.0,
            findings=[{"reason": "target_nodes_unresolved", "targets": target_nodes_raw}],
            summary="Target nodes are unresolved for reachability assessment",
            duration_ms=duration,
        )

    missing = sorted(node for node in resolved_targets if node not in reachable)
    if not missing:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            passed=True,
            mode=gate_spec.mode.value,
            status=GateStatus.PASSED,
            score=1.0,
            findings=[],
            summary="All target nodes are reachable from configured entrypoints",
            duration_ms=duration,
        )

    ambiguous_edges = [
        {
            "caller": edge.caller,
            "callee": edge.callee,
            "confidence": edge.confidence,
        }
        for edge in low_conf_edges
        if edge.caller in reachable and edge.callee in missing
    ]
    status = GateStatus.AMBIGUOUS if ambiguous_edges else GateStatus.FAILED

    findings: list[dict[str, Any]] = [
        {
            "missing_targets": missing,
            "resolved_entrypoints": sorted(resolved_entrypoints),
            "reachable_count": len(reachable),
            "target_count": len(resolved_targets),
            "min_confidence": min_confidence,
        }
    ]
    if ambiguous_edges:
        findings.append({"low_confidence_edges": ambiguous_edges})

    coverage = len(resolved_targets) - len(missing)
    score = coverage / len(resolved_targets) if resolved_targets else 0.0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.CALL_GRAPH_CONNECTED.value,
        mode=gate_spec.mode.value,
        status=status,
        score=score,
        findings=findings,
        summary=(
            "Some targets may be reachable only via low-confidence edges"
            if status == GateStatus.AMBIGUOUS
            else f"{len(missing)} target node(s) are unreachable from entrypoints"
        ),
        duration_ms=duration,
    )


def _slice_owner_for_edge(
    *,
    src_id: str,
    file_path: Path,
    project_root: Path,
    vertical_depth: int,
) -> str:
    """Derive a slice owner key for a STORE_TOUCH edge."""
    if src_id:
        segments = [seg for seg in src_id.split(".") if seg]
        if segments:
            return ".".join(segments[: max(1, vertical_depth)])

    try:
        rel = file_path.relative_to(project_root)
    except ValueError:
        rel = file_path

    parts = [part for part in rel.parts if part]
    if not parts:
        return str(rel)
    return "/".join(parts[: max(1, vertical_depth)])


def check_store_monogamy(
    algorithmic_files: list[Path],
    project_root: Path,
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: each store node should be touched by only one slice owner."""
    start = time.monotonic()
    vertical_depth = int(gate_spec.params.get("vertical_depth", 2))

    analyzed_by_path: dict[str, AnalyzedFile] = {}
    if analyzed is not None:
        analyzed_by_path = {Path(item.path).resolve().as_posix(): item for item in analyzed}

    store_owners: dict[str, set[str]] = {}
    store_evidence: dict[str, list[dict[str, Any]]] = {}

    for file_path in algorithmic_files:
        resolved = file_path.resolve().as_posix()
        preloaded = analyzed_by_path.get(resolved)

        if preloaded is not None:
            source = preloaded.content
            analysis = preloaded.analysis
        else:
            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            analysis = None

        spans: list[dict[str, Any]] = []
        if analysis is not None:
            for func in analysis.functions:
                spans.append(
                    {
                        "id": func.qualified_name or func.name,
                        "line_start": func.start_line,
                        "line_end": func.end_line,
                        "kind": "function",
                    }
                )

        inferred = infer_adjacency_signals(
            file_path=str(file_path),
            source_text=source,
            spans=spans,
            requested={"STORE_TOUCH"},
            workspace=project_root,
        )
        raw_edges = inferred.get("edges") if isinstance(inferred, dict) else []
        if not isinstance(raw_edges, list):
            continue

        for edge in raw_edges:
            if not isinstance(edge, dict):
                continue
            signal_type = str(edge.get("signal_type", "")).upper()
            if signal_type != "STORE_TOUCH":
                continue

            src_id = str(edge.get("src_id", "")).strip()
            store_id = str(edge.get("dst_id", "")).strip()
            if not store_id:
                continue

            owner = _slice_owner_for_edge(
                src_id=src_id,
                file_path=file_path,
                project_root=project_root,
                vertical_depth=vertical_depth,
            )
            store_owners.setdefault(store_id, set()).add(owner)
            store_evidence.setdefault(store_id, []).append(
                {
                    "owner": owner,
                    "src_id": src_id,
                    "file_path": str(file_path),
                    "confidence": float(edge.get("confidence", 1.0) or 0.0),
                }
            )

    if not store_owners:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.STORE_MONOGAMY.value,
            passed=True,
            mode=gate_spec.mode.value,
            status=GateStatus.PASSED,
            score=1.0,
            findings=[],
            summary="No STORE_TOUCH edges found",
            duration_ms=duration,
        )

    findings: list[dict[str, Any]] = []
    for store_id, owners in sorted(store_owners.items()):
        if len(owners) <= 1:
            continue
        findings.append(
            {
                "store_id": store_id,
                "owners": sorted(owners),
                "owner_count": len(owners),
                "evidence": store_evidence.get(store_id, []),
            }
        )

    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.STORE_MONOGAMY.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else max(0.0, 1.0 - (len(findings) / max(1, len(store_owners)))),
        findings=findings,
        summary=(
            "Each store is touched by exactly one slice owner"
            if passed
            else f"Found {len(findings)} store(s) touched by multiple slice owners"
        ),
        duration_ms=duration,
    )

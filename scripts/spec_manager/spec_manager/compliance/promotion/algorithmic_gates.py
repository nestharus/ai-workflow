"""Algorithmic layer gate checks for promotion gating."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.testing.registry import TestRunnerRegistry
from spec_manager.orchestration.evidence import EvidenceBundle


def check_no_remaining_comments(bundle: EvidenceBundle, gate_spec: GateSpec) -> GateCheckResult:
    """Gate: no unresolved comment-gap pins remain in facts evidence."""
    start = time.monotonic()
    raw_findings = bundle.facts.remaining_gap_pins
    if not isinstance(raw_findings, list):
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.NO_REMAINING_COMMENTS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "missing_facts.remaining_gap_pins"}],
            summary="Missing facts.remaining_gap_pins evidence",
            duration_ms=duration,
        )

    expected_kinds = {
        str(item).strip()
        for item in gate_spec.params.get(
            "comment_gap_kinds",
            ["SPEC_COMMENT_UNIMPLEMENTED", "executable_comment", "comment_gap"],
        )
        if isinstance(item, str) and item.strip()
    }

    findings: list[dict[str, Any]] = []
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        kind = str(finding.get("kind", "")).strip()
        if expected_kinds and kind and kind not in expected_kinds:
            continue
        findings.append(finding)

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
            "No unresolved comment-gap pins remain"
            if passed
            else f"Found {len(findings)} unresolved comment-gap pin(s)"
        ),
        duration_ms=duration,
    )


def check_no_stub_functions(bundle: EvidenceBundle, gate_spec: GateSpec) -> GateCheckResult:
    """Gate: no stub nodes remain in facts evidence."""
    start = time.monotonic()
    raw_findings = bundle.facts.stub_nodes
    if not isinstance(raw_findings, list):
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.NO_STUB_FUNCTIONS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "missing_facts.stub_nodes"}],
            summary="Missing facts.stub_nodes evidence",
            duration_ms=duration,
        )

    findings = [item for item in raw_findings if isinstance(item, dict)]
    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000
    return GateCheckResult(
        gate_id=GateId.NO_STUB_FUNCTIONS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary="No stub nodes found" if passed else f"Found {len(findings)} stub node(s)",
        duration_ms=duration,
    )


def _infer_targets_from_command(test_command: list[str]) -> list[str] | None:
    """Extract explicit test targets from a legacy command list."""
    if not test_command:
        return None

    skip_next = False
    targets: list[str] = []
    flags_with_value = {
        "-k",
        "-m",
        "-p",
        "-c",
        "--maxfail",
        "--rootdir",
        "--confcutdir",
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "--basetemp",
        "--override-ini",
    }

    for arg in [str(item).strip() for item in test_command if str(item).strip()]:
        if skip_next:
            skip_next = False
            continue
        if arg in {"python", "python3", "uv", "run", "pytest"}:
            continue
        if arg in flags_with_value:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        if arg == "pytest":
            continue
        targets.append(arg)

    return targets or None


def _is_pytest_command(test_command: list[str]) -> bool:
    """Return True when command clearly invokes pytest."""
    normalized = [str(item).strip().lower() for item in test_command if str(item).strip()]
    if any(token == "pytest" for token in normalized):
        return True
    for idx, token in enumerate(normalized):
        if token != "-m":
            continue
        if idx + 1 < len(normalized) and normalized[idx + 1] in {"pytest", "pytest.__main__"}:
            return True
    return False


def check_all_tests_pass(
    test_command: list[str],
    project_root: Path,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: all algorithmic tests pass."""
    start = time.monotonic()
    timeout_seconds = int(gate_spec.params.get("timeout_seconds", 300) or 300)
    requested_scope = str(gate_spec.params.get("scope", "FULL")).strip().upper()
    scope: Literal["SLICE", "FULL"] = "SLICE" if requested_scope == "SLICE" else "FULL"
    requested_targets = gate_spec.params.get("targets")
    targets = (
        [str(item).strip() for item in requested_targets if str(item).strip()]
        if isinstance(requested_targets, list)
        else _infer_targets_from_command(test_command)
    )

    findings: list[dict[str, Any]]
    try:
        if test_command and not _is_pytest_command(test_command):
            command_result = subprocess.run(
                test_command,
                cwd=str(project_root),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            passed = command_result.returncode == 0
            findings = [
                {
                    "runner_id": "external_command",
                    "scope": scope,
                    "command": list(test_command),
                    "returncode": command_result.returncode,
                    "stdout": command_result.stdout,
                    "stderr": command_result.stderr,
                }
            ]
            summary = (
                "All algorithmic tests passed"
                if passed
                else f"External test command failed: {command_result.stderr[:200]}"
            )
            duration = (time.monotonic() - start) * 1000
            return GateCheckResult(
                gate_id=GateId.ALL_TESTS_PASS.value,
                passed=passed,
                mode=gate_spec.mode.value,
                status=GateStatus.PASSED if passed else GateStatus.FAILED,
                score=1.0 if passed else 0.0,
                findings=findings,
                summary=summary,
                duration_ms=duration,
            )

        registry = TestRunnerRegistry()
        runner = registry.pick(root=project_root, timeout_seconds=timeout_seconds)
        run_result = runner.run(
            root=project_root,
            scope=scope,
            targets=targets,
        )
        failures = [
            {
                "test_id": failure.test_id,
                "file": failure.file,
                "message": failure.message,
                "raw_excerpt_path": failure.raw_excerpt_path,
            }
            for failure in run_result.failures
        ]
        findings = [
            {
                "runner_id": run_result.runner_id,
                "scope": run_result.scope,
                "command": run_result.command,
                "stdout_path": run_result.stdout_path,
                "stderr_path": run_result.stderr_path,
                "total_tests": run_result.total_tests,
                "passed_tests": run_result.passed_tests,
                "failed_tests": run_result.failed_tests,
                "duration_ms": run_result.duration_ms,
                "failures": failures,
            }
        ]
        passed = bool(run_result.passed)
        if passed:
            summary = "All algorithmic tests passed"
        elif failures:
            first_failure = failures[0]
            first_id = str(first_failure.get("test_id") or first_failure.get("file") or "").strip()
            suffix = f"; first={first_id}" if first_id else ""
            summary = f"{len(failures)} test failure(s) detected{suffix}"
        else:
            summary = "Test runner reported failure without structured failure rows"
    except Exception as exc:
        passed = False
        findings = [
            {
                "error": str(exc),
                "requested_command": list(test_command),
                "scope": scope,
            }
        ]
        summary = f"Test runner execution failed: {exc}"

    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.ALL_TESTS_PASS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=summary,
        duration_ms=duration,
    )


def _resolve_nodes(nodes: set[str], configured: list[str]) -> set[str]:
    """Resolve configured identifiers to known node ids."""
    resolved: set[str] = set()
    if not nodes:
        return resolved
    for raw in configured:
        candidate = raw.strip()
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


def check_call_graph_connected(bundle: EvidenceBundle, gate_spec: GateSpec) -> GateCheckResult:
    """Gate: target atom nodes form a connected CALL graph in bundle facts."""
    start = time.monotonic()
    raw_nodes = bundle.facts.call_graph_nodes
    raw_edges = bundle.facts.call_graph_edges
    atom_ids = {
        str(atom_id).strip() for atom_id in (bundle.facts.atoms or {}) if str(atom_id).strip()
    }

    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "missing_facts.call_graph_nodes_or_edges"}],
            summary="Missing call graph facts evidence",
            duration_ms=duration,
        )

    nodes = {str(node).strip() for node in raw_nodes if isinstance(node, str) and str(node).strip()}
    configured_targets = [
        str(item).strip()
        for item in gate_spec.params.get("pin_function_nodes", [])
        if isinstance(item, str) and str(item).strip()
    ]
    if configured_targets:
        targets = _resolve_nodes(nodes | atom_ids, configured_targets)
    else:
        targets = atom_ids or nodes

    if not targets:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "empty_target_nodes"}],
            summary="No target nodes available for connectivity gate",
            duration_ms=duration,
        )

    min_confidence = float(gate_spec.params.get("min_confidence", 0.6))
    adjacency: dict[str, set[str]] = {node: set() for node in targets}
    low_conf_edges: list[tuple[str, str]] = []
    malformed_confidence_edges: list[dict[str, Any]] = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        signal_type = str(edge.get("signal_type", "")).strip().upper()
        if signal_type != "CALL":
            continue
        src = str(edge.get("src") or edge.get("caller") or "").strip()
        dst = str(edge.get("dst") or edge.get("callee") or "").strip()
        if not src or not dst:
            continue
        raw_confidence = edge.get("confidence", 1.0)
        try:
            confidence = float(raw_confidence or 0.0)
        except (TypeError, ValueError):
            malformed_confidence_edges.append(
                {
                    "reason": "malformed_edge_confidence",
                    "src": src,
                    "dst": dst,
                    "confidence": repr(raw_confidence),
                }
            )
            continue
        if confidence < min_confidence:
            low_conf_edges.append((src, dst))
            continue
        if src in targets and dst in targets:
            adjacency.setdefault(src, set()).add(dst)
            adjacency.setdefault(dst, set()).add(src)

    if len(targets) <= 1:
        duration = (time.monotonic() - start) * 1000
        if malformed_confidence_edges:
            return GateCheckResult(
                gate_id=GateId.CALL_GRAPH_CONNECTED.value,
                mode=gate_spec.mode.value,
                status=GateStatus.AMBIGUOUS,
                score=0.5,
                findings=malformed_confidence_edges,
                summary=(
                    "Connectivity is trivially satisfied, but call-edge confidence "
                    "evidence is malformed"
                ),
                duration_ms=duration,
            )
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            passed=True,
            mode=gate_spec.mode.value,
            status=GateStatus.PASSED,
            score=1.0,
            findings=[],
            summary="Call graph target set is trivially connected",
            duration_ms=duration,
        )

    seed = next(iter(targets))
    reachable: set[str] = set()
    frontier = {seed}
    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        reachable.add(current)
        frontier.update(adjacency.get(current, set()) - reachable)

    missing = sorted(node for node in targets if node not in reachable)
    if not missing and not malformed_confidence_edges:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.CALL_GRAPH_CONNECTED.value,
            passed=True,
            mode=gate_spec.mode.value,
            status=GateStatus.PASSED,
            score=1.0,
            findings=[],
            summary="All target nodes are connected in the evidence call graph",
            duration_ms=duration,
        )

    ambiguous = bool(malformed_confidence_edges) or any(
        (src in reachable and dst in missing) or (dst in reachable and src in missing)
        for src, dst in low_conf_edges
    )
    status = GateStatus.AMBIGUOUS if ambiguous else GateStatus.FAILED
    score = (len(targets) - len(missing)) / len(targets) if missing else 0.5
    duration = (time.monotonic() - start) * 1000

    findings: list[dict[str, Any]] = [
        {
            "disconnected_nodes": missing,
            "reachable_nodes": sorted(reachable),
            "target_count": len(targets),
            "min_confidence": min_confidence,
        }
    ]
    if ambiguous:
        findings.append(
            {
                "reason": "low_confidence_bridges",
                "candidate_edges": [{"src": src, "dst": dst} for src, dst in low_conf_edges],
            }
        )
    if malformed_confidence_edges:
        findings.append(
            {
                "reason": "malformed_call_edge_confidence",
                "edges": malformed_confidence_edges,
            }
        )

    return GateCheckResult(
        gate_id=GateId.CALL_GRAPH_CONNECTED.value,
        mode=gate_spec.mode.value,
        status=status,
        score=score,
        findings=findings,
        summary=(
            "Call-edge confidence evidence is malformed for one or more edges"
            if malformed_confidence_edges and not missing
            else (
                "Some disconnected nodes may be bridged by low-confidence CALL edges"
                if ambiguous
                else f"{len(missing)} node(s) are disconnected in the evidence call graph"
            )
        ),
        duration_ms=duration,
    )


def check_store_monogamy(bundle: EvidenceBundle, gate_spec: GateSpec) -> GateCheckResult:
    """Gate: each store has exactly one owner in bundle facts."""
    start = time.monotonic()

    owners_map: dict[str, list[str]] = {}
    has_owner_evidence = False
    if isinstance(bundle.facts.store_owners, dict):
        for store_id, owners in bundle.facts.store_owners.items():
            if not isinstance(store_id, str) or not store_id.strip():
                continue
            if not isinstance(owners, list):
                continue
            has_owner_evidence = True
            owners_map[store_id] = [
                str(owner).strip()
                for owner in owners
                if isinstance(owner, str) and str(owner).strip()
            ]

    if not owners_map:
        for store_id, store_data in (bundle.facts.stores or {}).items():
            if (
                not isinstance(store_id, str)
                or not store_id.strip()
                or not isinstance(store_data, dict)
            ):
                continue
            raw_owners = store_data.get("owner_atoms", [])
            if not isinstance(raw_owners, list):
                continue
            has_owner_evidence = True
            owners_map[store_id] = [
                str(owner).strip()
                for owner in raw_owners
                if isinstance(owner, str) and str(owner).strip()
            ]

    if not has_owner_evidence:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.STORE_MONOGAMY.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "missing_store_owner_evidence"}],
            summary="Missing store ownership evidence in bundle facts",
            duration_ms=duration,
        )

    findings: list[dict[str, Any]] = []
    for store_id, owners in sorted(owners_map.items()):
        normalized_owners = sorted(set(owners))
        if len(normalized_owners) <= 1:
            continue
        findings.append(
            {
                "store_id": store_id,
                "owners": normalized_owners,
                "owner_count": len(normalized_owners),
            }
        )

    passed = len(findings) == 0
    score = 1.0 if passed else max(0.0, 1.0 - (len(findings) / max(1, len(owners_map))))
    duration = (time.monotonic() - start) * 1000
    return GateCheckResult(
        gate_id=GateId.STORE_MONOGAMY.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=score,
        findings=findings,
        summary=(
            "Each store has exactly one owner atom"
            if passed
            else f"Found {len(findings)} store(s) with multiple owner atoms"
        ),
        duration_ms=duration,
    )

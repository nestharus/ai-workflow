# TODO(single-layer): RESTRUCTURE — These become "Behavior gates" (Section 10.1 group A).
#   KEEP: check_all_tests_pass (primary authority), check_no_remaining_comments (adapted:
#     Section 8.1 replaces comment markers with external work items — this gate must be
#     scoped to non-routing comments only, e.g. leftover FIXMEs/HACKs, NOT spec TODOs)
#   CONVERT to soft signal: check_call_graph_connected, check_no_stub_functions
#   KEEP: check_store_monogamy — becomes deterministic boundary verifier if possible,
#     otherwise convert to contract-test requirement (Section 10.2 fallback path)
#   The gate check functions themselves are good — just reclassify from "algorithmic layer"
#   to "behavior aspect" and remove layer-specific evidence assumptions.
# ALGORITHM(single-layer):
#   References: response3 Sections 10.1(A), 10.2.
#   Data structures:
#     - Keep GateCheckResult/GateStatus payload contract.
#     - BehaviorGateContext: {bundle: EvidenceBundle, test_command: list[str], project_root: Path, shape_verifier_summary: dict[ShapeId, VerifierRunSummary]|None}.
#   Interface contracts:
#     - def check_all_tests_pass(...) -> GateCheckResult  # hard by default.
#     - def check_no_remaining_comments(...) -> GateCheckResult  # only non-routing debt comments.
#     - def check_no_stub_functions(...) -> GateCheckResult  # soft signal default.
#     - def check_call_graph_connected(...) -> GateCheckResult  # soft signal.
#     - def check_store_monogamy(...) -> GateCheckResult  # deterministic if adapter exists else advisory + verifier-required finding.
#   Control flow:
#     1. These gates run in the Libraries phase (phase='libraries') — not a separate "Build" phase.
#     2. Three phases (Libraries -> Architecture -> Quality), forward-only; no cycling back.
#     3. The Libraries phase edits code via its own PromotionLoop with IMPLEMENT step.
#     4. Keep existing deterministic test execution path as primary authority.
#     5. Re-scope comment scan to debt markers (FIXME/HACK/etc.) and ignore spec/routing TODO policy artifacts.
#     6. Emit advisory results for call-graph connectivity and stub detection unless config overrides.
#     7. When store-monogamy cannot be evaluated deterministically, return advisory finding that requests contract verifier test creation.
#     8. Phase-local remediation if within Libraries authority; block if outside authority (no backtracking).
#   Error handling:
#     - Missing facts payload returns STALE_EVIDENCE, not pass.
#     - External test command failure returns failed hard gate with captured stderr path.
#   Integration points:
#     - Called by aspect gate orchestrator behavior group during Libraries phase.
#     - Libraries phase gates: library verifiers (hard) + LLM gap scans (soft).
#   Test requirements:
#     - Hard fail on test failure.
#     - TODO/spec comments do not trigger no_remaining_comments failure.
#     - Soft gates remain non-blocking under default mode.

"""Algorithmic layer gate checks for promotion gating."""

from __future__ import annotations

import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from spec_manager.compliance.promotion.config import GateId, GateSpec, PhaseId
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.testing.registry import TestRunnerRegistry
from spec_manager.orchestration.evidence import EvidenceBundle

# IMPL(single-layer): These checks are consumed as Libraries-phase behavior gates via
# aspect orchestration; blocking vs advisory semantics are driven by GateSpec mode.

_DEBT_COMMENT_KINDS: set[str] = {"comment_gap", "executable_comment"}
_DEBT_COMMENT_MARKER_PATTERN = re.compile(
    r"\b(FIXME|HACK|XXX|TODO|TBD|UNIMPLEMENTED|WORKAROUND)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BehaviorGateContext:
    bundle: EvidenceBundle
    test_command: list[str]
    project_root: Path
    phase: PhaseId
    shape_verifier_summary: dict[str, Any] | None = None


def _normalize_comment_kind(raw_kind: Any) -> str:
    return str(raw_kind).strip().lower()


def _looks_like_spec_or_routing_comment(finding: dict[str, Any]) -> bool:
    kind = _normalize_comment_kind(finding.get("kind", ""))
    if kind.startswith("spec_") or kind.startswith("routing_"):
        return True

    file_path = str(finding.get("file", "")).lower()
    if "/spec/" in file_path or "/specs/" in file_path or "/routing/" in file_path:
        return True

    return False


def _is_debt_comment_finding(finding: dict[str, Any]) -> bool:
    if _looks_like_spec_or_routing_comment(finding):
        return False

    marker_source = " ".join(
        part.strip()
        for part in [
            str(finding.get("description", "")),
            str(finding.get("kind", "")),
            str(finding.get("pin_id", "")),
        ]
        if part
    )
    return bool(_DEBT_COMMENT_MARKER_PATTERN.search(marker_source))


def _persist_text_artifact(root: Path, label: str, content: str) -> str:
    if not isinstance(content, str) or not content:
        return ""

    for base_dir in (root, Path.cwd(), Path(tempfile.gettempdir())):
        try:
            if not base_dir.exists():
                continue
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f"pdd-{label}-",
                suffix=".log",
                dir=str(base_dir),
                delete=False,
            ) as handle:
                handle.write(content)
                return str(handle.name)
        except OSError:
            continue
    return ""


def _build_external_test_findings(
    *,
    project_root: Path,
    runner_id: str,
    scope: Literal["SLICE", "FULL"],
    command: list[str],
    returncode: int | None = None,
    raw_stdout: str | None = None,
    raw_stderr: str | None = None,
) -> dict[str, Any]:
    findings: dict[str, Any] = {"runner_id": runner_id, "scope": scope, "command": list(command)}
    if returncode is not None:
        findings["returncode"] = returncode
    if raw_stdout is not None:
        findings["stdout"] = raw_stdout
        findings["stdout_path"] = _persist_text_artifact(project_root, "test-stdout", raw_stdout)
    if raw_stderr is not None:
        findings["stderr"] = raw_stderr
        findings["stderr_path"] = _persist_text_artifact(project_root, "test-stderr", raw_stderr)
    return findings


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

    # IMPL(single-layer): Section 8.1 replaces routing/spec TODO markers with external
    # work items; configure `comment_gap_kinds` to debt-comment kinds only.
    expected_kinds = {
        str(item).strip().lower()
        for item in gate_spec.params.get(
            "comment_gap_kinds",
            ["comment_gap", "executable_comment"],
        )
        if isinstance(item, str) and item.strip()
    }

    findings: list[dict[str, Any]] = []
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        kind = _normalize_comment_kind(finding.get("kind", "comment_gap"))
        if expected_kinds and kind not in expected_kinds:
            continue
        if kind in _DEBT_COMMENT_KINDS and not _is_debt_comment_finding(finding):
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
    # IMPL(single-layer): Section 10.2 treats stub detection as advisory by default
    # unless the project defines a deterministic blocking policy.
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
    # IMPL(single-layer): ALL_TESTS_PASS remains the primary deterministic authority;
    # use this gate as hard-required across phases unless config explicitly relaxes it.
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
            stdout_text = command_result.stdout if command_result.stdout is not None else ""
            stderr_text = command_result.stderr if command_result.stderr is not None else ""
            findings = [
                _build_external_test_findings(
                    project_root=project_root,
                    runner_id="external_command",
                    scope=scope,
                    command=test_command,
                    returncode=command_result.returncode,
                    raw_stdout=stdout_text,
                    raw_stderr=stderr_text,
                )
            ]
            summary = (
                "All algorithmic tests passed"
                if passed
                else (
                    f"External test command failed: {stderr_text[:200]}"
                    if stderr_text
                    else "External test command failed"
                )
            )
            if not passed:
                stderr_path = findings[0].get("stderr_path")
                if stderr_path:
                    summary += f" (stderr_path={stderr_path})"
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
        error_message = str(exc)
        error_trace_path = _persist_text_artifact(project_root, "test-runner-error", error_message)
        findings = [
            {
                "error": error_message,
                "requested_command": list(test_command),
                "scope": scope,
                "error_trace_path": error_trace_path,
            }
        ]
        summary = f"Test runner execution failed: {error_message}"

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
    # IMPL(single-layer): Section 10.2 keeps call-graph connectivity as a soft routing
    # signal; FAILED/AMBIGUOUS outcomes are non-blocking unless GateSpec overrides mode.
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
    # IMPL(single-layer): Keep this deterministic only when ownership evidence is
    # authoritative; otherwise emit advisory findings and require contract verifiers.
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
            findings=[
                {"reason": "missing_store_owner_evidence"},
                {
                    "reason": "contract_verifier_required",
                    "message": "Create contract verifier coverage for store ownership boundaries.",
                },
            ],
            summary="Missing store ownership evidence in bundle facts; add contract verifier coverage.",
            duration_ms=duration,
        )

    findings: list[dict[str, Any]] = []
    violation_count = 0
    for store_id, owners in sorted(owners_map.items()):
        normalized_owners = sorted(set(owners))
        if len(normalized_owners) <= 1:
            continue
        violation_count += 1
        findings.append(
            {
                "store_id": store_id,
                "owners": normalized_owners,
                "owner_count": len(normalized_owners),
            }
        )
    if findings and not gate_spec.params.get("skip_contract_verifier_fallback"):
        findings.append(
            {
                "reason": "contract_verifier_required",
                "message": "Create contract verifier coverage for violating store boundaries.",
            }
        )

    passed = violation_count == 0
    score = 1.0 if passed else max(0.0, 1.0 - (violation_count / max(1, len(owners_map))))
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
            else f"Found {violation_count} store(s) with multiple owner atoms"
        ),
        duration_ms=duration,
    )

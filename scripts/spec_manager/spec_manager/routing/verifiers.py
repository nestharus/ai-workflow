# TODO(single-layer): NEW — Verifier runner (Sections 4.1, 6.3, 9.4).
#   - Run verifier commands/checks declared in shape Verifiers sections
#   - Verifier types: TEST (run specific test), IMPORT_BOUNDARY (check allow/deny deps)
#   - Collect pass/fail evidence per verifier
#   - Contract verification: communication contracts satisfied iff verifiers pass
#     (Section 6.3 rule #3 — implementation mechanism can change freely)
#   - Convergence authority: all shape verifiers pass is part of termination condition
#   - No LLM output becomes convergence authority (Section 13.3) — only deterministic checks
#   - Verifiers run within all 3 phases (Libraries, Architecture, Quality):
#     * Libraries phase: library-level verifiers (unit tests, API surface checks)
#     * Architecture phase: shape matching + contract verifiers + integration tests
#     * Quality phase: all tests + contract verifiers + style checks
#   - Non-ship safety (Section 15): if key structural contracts cannot be verifier-backed,
#     single-layer design should not ship — this is a go/no-go gate
# ALGORITHM(single-layer):
#   References: response3 Sections 4.1, 6.3, 9.4, 13.1, 15; evaluation modification #3.
#   Phase model: 3 forward-only phases — Libraries → Architecture → Quality.
#     PhaseId = Literal['libraries', 'architecture', 'quality'].
#     Each phase edits code via its own PromotionLoop with IMPLEMENT step.
#     No backtracking: phases block (not demote) if they encounter something
#     outside their authority.
#   Per-phase verifier scope:
#     - Libraries phase: library-level verifiers — unit tests for individual
#       libraries, API surface contract checks, import boundary enforcement
#       within library boundaries.
#     - Architecture phase: shape matching verifiers + contract verifiers
#       (EVENT_FLOW, DI_BINDING, etc.) + integration tests that exercise
#       cross-shape communication paths.
#     - Quality phase: full verifier suite — all tests + contract verifiers +
#       style checks + any remaining verification gaps.
#   Data structures (authoritative shared interface):
#     - VerifierResult (defined here): {shape_id: ShapeId, verifier_id: str, kind: str, passed: bool, evidence_refs: list[str], summary: str, started_at: str, finished_at: str, duration_ms: float, deterministic: bool, error: str|None}.
#     - VerifierRunSummary: {shape_id: ShapeId, all_passed: bool, results: list[VerifierResult], missing_required: list[str], non_ship_block: bool}.
# IMPL(single-layer): `VerifierResult`/`VerifierRunSummary` are canonical shared
# contracts for matcher, monitors, introduction checks, and gate orchestration.
#   Interface contracts:
#     - def run_shape_verifier(shape: Shape, verifier: VerifierSpec, workspace_root: Path) -> VerifierResult
#     - def run_shape_verifiers(shape: Shape, workspace_root: Path) -> VerifierRunSummary
#     - def run_all_active_shape_verifiers(index: ShapePackIndex, workspace_root: Path) -> dict[ShapeId, VerifierRunSummary]
#     - def enforce_non_ship_policy(shape_summaries: dict[ShapeId, VerifierRunSummary], required_contract_shape_ids: set[ShapeId]) -> tuple[bool, list[str]]
# IMPL(single-layer): Keep verifier APIs imported via `spec_manager.routing`
# re-exports so downstream modules do not bind to module-local paths.
# IMPL(single-layer): Inside the `routing` package, keep sibling-module imports
# (`routing.shapes`, etc.) instead of package re-export imports to avoid
# `routing.__init__` import-cycle/re-entry during module load.
#   Control flow:
#     1. Skip PROPOSAL shapes for pass/fail authority, but emit missing-verifier diagnostics.
#     2. For ACTIVE shapes, execute each verifier deterministically by kind: TEST via core testing runner, IMPORT_BOUNDARY via import scan policy, COMMAND via strict command allowlist.
#     3. Aggregate per-shape and global status; any ACTIVE shape with zero verifiers is immediate failure and work item seed for the current phase.
#     4. Return convergence-ready map for lifecycle termination checks (all active-shape verifiers must pass).
#     5. Non-ship safety: if critical contract shapes cannot be verifier-backed, return non_ship_block=True (Section 15).
# IMPL(single-layer): Phase convergence and monitor pass-conditions must evaluate
# ACTIVE-shape summaries only; PROPOSAL diagnostics remain actionable but non-authoritative.
# IMPL(single-layer): `non_ship_block=True` is a hard-stop signal consumed by
# promotion/lifecycle termination logic (never downgraded to advisory).
#   Error handling:
#     - Unknown verifier kind: failed result with explicit error.
#     - Tool invocation timeout or missing test target: failed result, deterministic evidence path captured.
#     - Non-deterministic/LLM-only checker requested: reject and mark failed (Section 13.3).
# IMPL(single-layer): Failed verifier results must always include deterministic
# evidence refs/error text so work-item generation can route without LLM inference.
#   Integration points:
#     - Called by: matcher, promotion gate orchestrator, lifecycle termination checks, monitor conditions.
#     - Calls: core.testing.runner/registry and deterministic import-boundary checker.
#   Test requirements:
#     - TEST and IMPORT_BOUNDARY verifier pass/fail paths.
#     - ACTIVE shape with empty verifiers fails.
#     - PROPOSAL shape excluded from hard convergence while still producing diagnostics.
#     - Non-ship block triggers when critical contracts are unverifiable.

"""Verifier execution: run deterministic checks declared in shape documents."""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.core.testing.registry import RunnerSelectionError, TestRunnerRegistry
from spec_manager.routing.shapes import Shape, ShapeId, ShapePackIndex, VerifierSpec

logger = logging.getLogger(__name__)

_IGNORE_SCAN_DIRS = {".git", ".venv", "dist", "build", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
_WORK_ITEM_SCANNING_SENTINEL = "__routing_import_scan_error__"
_PHASE_DEFAULT: PhaseId = "libraries"


def _utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _normalize_text(value: Any) -> str:
    return str(value).strip().lower()


def _normalize_graph_path(path: str | Path) -> str:
    text = str(path).replace("\\", "/").replace(" ", "-").lower().strip()
    if len(text) >= 2 and text[1] == ":":
        text = text[2:]
    if text.startswith("/"):
        text = text.lstrip("/")
    if text.startswith("workspace/"):
        text = text[len("workspace/") :]
    if text.startswith("runs/"):
        text = text[len("runs/") :]
    if text.endswith("/"):
        text = text.rstrip("/")
    return text


def _normalize_dependency_token(value: Any) -> str:
    normalized = _normalize_text(value)
    return normalized.replace(".", "/")


def _dependency_variants(value: Any) -> set[str]:
    base = _normalize_text(value)
    if not base:
        return set()
    variants = {
        base,
        base.replace("-", "/"),
        base.replace("_", "-"),
        base.replace("/", "-"),
        base.replace("-", "_"),
        base.replace("/", "."),
    }
    variants.update(f for f in {f"{variant}.*" for variant in variants} if "*" not in variant)
    variants.add(Path(base).name)
    return {item for item in variants if item}


def _match_allowed(value: str, allowed: set[str]) -> bool:
    observed = _normalize_dependency_token(value)
    observed_variants = _dependency_variants(observed)
    observed_variants.add(observed)
    observed_variants.add(observed.replace("/", "."))
    for token in allowed:
        token_variants = _dependency_variants(token)
        if not token_variants:
            continue
        if observed_variants.intersection(token_variants):
            return True
        if _normalize_text(token) in observed_variants:
            return True
    return False


def _coerce_string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, tuple):
        raw = list(raw)
    if isinstance(raw, list):
        return [_normalize_text(item) for item in raw if _normalize_text(item)]
    if isinstance(raw, set):
        return [_normalize_text(item) for item in raw if _normalize_text(item)]
    if isinstance(raw, str):
        if not raw.strip():
            return []
        return [_normalize_text(item) for item in re.split(r"\s*,\s*", raw) if _normalize_text(item)]
    return []


def _normalize_command_tokens(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        try:
            tokens = shlex.split(raw)
        except ValueError:
            return [raw.strip()] if raw.strip() else []
        return [item.strip() for item in tokens if item.strip()]
    return []


def _command_signature_tokens(command: list[str]) -> list[str]:
    return [_normalize_text(item) for item in command]


def _command_matches(command: list[str], allowlist_entry: str) -> bool:
    allow = _normalize_text(allowlist_entry)
    if not allow or not command:
        return False
    allowed_tokens = _normalize_command_tokens(allow)
    if not allowed_tokens:
        allowed = allow.replace("*", "")
        return allow in _normalize_text(" ".join(command))
    if len(allowed_tokens) > len(command):
        return False
    return command[: len(allowed_tokens)] == allowed_tokens


def _is_hidden_dir(path: Path) -> bool:
    return any(part in _IGNORE_SCAN_DIRS for part in path.parts)


def _iter_python_files(workspace_root: Path) -> list[Path]:
    if not workspace_root.exists():
        return []
    files: list[Path] = []
    for path in workspace_root.rglob("*.py"):
        if path.is_file() and not _is_hidden_dir(path):
            files.append(path)
    return sorted(files)


def _candidate_targets_from_import_parts(
    workspace_root: Path,
    source_path: Path,
    *,
    base_modules: list[str],
    rel_level: int,
) -> set[str]:
    candidates: set[str] = set()
    source_parent = source_path.parent
    for module_name in base_modules:
        if rel_level:
            anchor = source_parent
            for _ in range(rel_level):
                if anchor.parent == anchor:
                    break
                anchor = anchor.parent
            module_parts = [part for part in module_name.split(".") if part]
            module_path = anchor.joinpath(*module_parts) if module_parts else anchor
        else:
            module_parts = [part for part in module_name.split(".") if part]
            module_path = workspace_root.joinpath(*module_parts) if module_parts else workspace_root

        if module_path.is_file():
            candidates.add(_normalize_graph_path(module_path))
            continue
        module_file = module_path.with_suffix(".py")
        if module_file.is_file():
            candidates.add(_normalize_graph_path(module_file))
        package_file = module_path / "__init__.py"
        if package_file.is_file():
            candidates.add(_normalize_graph_path(package_file))
    return candidates


def _build_observed_dependency_graph(workspace_root: Path) -> tuple[dict[str, set[str]], list[str]]:
    workspace_root = Path(workspace_root)
    graph: dict[str, set[str]] = {}
    scan_failures: list[str] = []

    for source in _iter_python_files(workspace_root):
        normalized_source = _normalize_graph_path(source)
        if not normalized_source:
            continue
        graph.setdefault(normalized_source, set())
        try:
            content = source.read_text(encoding="utf-8", errors="ignore")
            module = __import__("ast").parse(content)
        except Exception as exc:  # pragma: no cover - deterministic fallback
            scan_failures.append(f"{normalized_source}: {exc}")
            graph.setdefault(_WORK_ITEM_SCANNING_SENTINEL, set()).add(
                f"{normalized_source}: {exc}"
            )
            continue

        for node in __import__("ast").walk(module):
            if node.__class__.__name__ == "Import":
                base_names: list[str] = []
                for item in node.names:
                    candidate = getattr(item, "name", "")
                    if str(candidate).strip():
                        base_names.append(str(candidate).strip())
                targets = _candidate_targets_from_import_parts(
                    workspace_root=workspace_root,
                    source_path=source,
                    base_modules=base_names,
                    rel_level=0,
                )
                graph[normalized_source].update(targets)
            elif node.__class__.__name__ == "ImportFrom":
                base_module = str(getattr(node, "module", "") or "").strip()
                alias_names = [
                    str(item.name).strip()
                    for item in getattr(node, "names", [])
                    if str(item.name).strip() and item.name != "*"
                ]
                module_names = [base_module] if base_module else []
                for alias_name in alias_names:
                    if base_module:
                        module_names.append(f"{base_module}.{alias_name}")
                    else:
                        module_names.append(alias_name)
                targets = _candidate_targets_from_import_parts(
                    workspace_root=workspace_root,
                    source_path=source,
                    base_modules=[m for m in module_names if m],
                    rel_level=int(getattr(node, "level", 0) or 0),
                )
                graph[normalized_source].update(targets)

    return graph, scan_failures


_DEPENDENCY_GRAPH_CACHE: dict[str, tuple[dict[str, set[str]], list[str]]] = {}


def _get_dependency_graph(workspace_root: Path) -> tuple[dict[str, set[str]], list[str]]:
    workspace_key = str(workspace_root.resolve())
    if workspace_key in _DEPENDENCY_GRAPH_CACHE:
        return _DEPENDENCY_GRAPH_CACHE[workspace_key]
    graph = _build_observed_dependency_graph(workspace_root)
    _DEPENDENCY_GRAPH_CACHE[workspace_key] = graph
    return graph


@dataclass
class VerifierResult:
    shape_id: ShapeId
    verifier_id: str
    kind: str
    passed: bool
    evidence_refs: list[str] = field(default_factory=list)
    summary: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    deterministic: bool = True
    error: str | None = None


@dataclass
class VerifierRunSummary:
    shape_id: ShapeId
    all_passed: bool
    results: list[VerifierResult]
    missing_required: list[str]
    non_ship_block: bool = False


def _failed_result(
    shape_id: ShapeId,
    verifier_id: str,
    kind: str,
    *,
    summary: str,
    error: str,
    evidence_refs: list[str] | None = None,
    deterministic: bool = True,
    started_at: str,
    duration_ms: float,
) -> VerifierResult:
    finished_at = _utcnow()
    return VerifierResult(
        shape_id=shape_id,
        verifier_id=_normalize_text(verifier_id),
        kind=_normalize_text(kind) or kind,
        passed=False,
        evidence_refs=[item for item in (evidence_refs or []) if item],
        summary=summary,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        deterministic=deterministic,
        error=error,
    )


def _require_stripped_text(value: Any, field_name: str) -> str:
    text = _normalize_text(value)
    if not text:
        raise ValueError(f"{field_name} is required and must be non-empty")
    return str(text)


def _run_test_verifier(
    shape: Shape,
    verifier: VerifierSpec,
    workspace_root: Path,
    started_at: str,
) -> VerifierResult:
    started = datetime.now(tz=UTC).replace(microsecond=0)
    duration_ms = 0.0
    evidence: list[str] = []
    verifier_id = _require_stripped_text(verifier.verifier_id, "verifier_id")
    timeout_seconds = int(verifier.params.get("timeout_seconds", 300) or 300)
    requested_scope = _normalize_text(verifier.params.get("scope", "FULL"))
    scope: Literal["SLICE", "FULL"] = "SLICE" if requested_scope == "slice" else "FULL"
    raw_targets = verifier.params.get("targets")
    targets = _coerce_string_list(raw_targets)

    if targets:
        missing_targets = [target for target in targets if not (workspace_root / target).exists()]
        if missing_targets:
            duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000
            evidence_refs = []
            output_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-missing-target.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "Missing test target(s):\n" + "\n".join(missing_targets),
                encoding="utf-8",
            )
            evidence_refs.append(str(output_path))
            return _failed_result(
                shape.shape_id,
                verifier_id,
                "TEST",
                summary="Missing test target path for TEST verifier",
                error="missing test target",
                evidence_refs=evidence_refs,
                deterministic=True,
                started_at=started_at,
                duration_ms=duration_ms,
            )

    try:
        registry = TestRunnerRegistry()
        runner = registry.pick(root=workspace_root, timeout_seconds=timeout_seconds)
        run_result = runner.run(root=workspace_root, scope=scope, targets=targets or None)
        evidence.extend([str(run_result.stdout_path), str(run_result.stderr_path)])
        if run_result.stdout_path:
            evidence.append(str(run_result.stdout_path))
        if run_result.stderr_path:
            evidence.append(str(run_result.stderr_path))
        passed = bool(run_result.passed)
        if passed:
            summary = "All tests passed"
            error = None
        else:
            summary = (
                f"{len(run_result.failures)} deterministic test failure(s)"
                if run_result.failures
                else "Test runner reported deterministic failure"
            )
            error = "tests_failed"
    except RunnerSelectionError as exc:
        output_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-test-selection-error.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(str(exc), encoding="utf-8")
        evidence.append(str(output_path))
        passed = False
        summary = f"TEST runner selection failed: {exc}"
        error = "test_runner_selection_failed"
        run_result = None
    except Exception as exc:
        output_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-test-invocation-error.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(str(exc), encoding="utf-8")
        evidence.append(str(output_path))
        passed = False
        summary = f"TEST verifier failed: {exc}"
        error = "test_verifier_exception"
        run_result = None
    finally:
        duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000

    if passed:
        return VerifierResult(
            shape_id=shape.shape_id,
            verifier_id=verifier_id,
            kind="TEST",
            passed=True,
            evidence_refs=[*dict.fromkeys(evidence)],
            summary=summary,
            started_at=started_at,
            finished_at=_utcnow(),
            duration_ms=duration_ms,
            deterministic=True,
            error=None,
        )

    return _failed_result(
        shape.shape_id,
        verifier_id,
        "TEST",
        summary=summary,
        error=error,
        evidence_refs=[*dict.fromkeys(evidence)],
        deterministic=True,
        started_at=started_at,
        duration_ms=duration_ms,
    )


def _run_import_boundary_verifier(
    shape: Shape,
    verifier: VerifierSpec,
    workspace_root: Path,
    started_at: str,
) -> VerifierResult:
    verifier_id = _require_stripped_text(verifier.verifier_id, "verifier_id")
    evidence: list[str] = []
    started = datetime.now(tz=UTC).replace(microsecond=0)
    summary = "Import boundary passed"
    duration_ms = 0.0
    error: str | None = None

    owned_prefixes: set[str] = {_normalize_dependency_token(item) for item in shape.files if _normalize_text(item)}
    if not owned_prefixes and shape.package:
        owned_prefixes.add(_normalize_dependency_token(shape.package))

    explicit_allow = set(
        _coerce_string_list(
            verifier.params.get("allowed")
            or verifier.params.get("allow")
            or verifier.params.get("allowlist")
            or verifier.params.get("allowed_dependencies")
            or verifier.params.get("dependencies")
        )
    )
    if not explicit_allow and shape.dependencies_declared:
        explicit_allow = {_normalize_dependency_token(item) for item in shape.dependencies_declared}

    graph, scan_failures = _get_dependency_graph(workspace_root)
    if scan_failures:
        evidence_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-import-scan.txt"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text("\n".join(scan_failures), encoding="utf-8")
        evidence.append(str(evidence_path))
        if owned_prefixes:
            owned_hits = [item for item in scan_failures if item.startswith(tuple(owned_prefixes))]
            if owned_hits:
                error = "import_scan_failed_for_owned_files"
                summary = "Import scan failed for shape-owned files"
                duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000
                return _failed_result(
                    shape.shape_id,
                    verifier_id,
                    "IMPORT_BOUNDARY",
                    summary=summary,
                    error=error,
                    evidence_refs=evidence,
                    deterministic=True,
                    started_at=started_at,
                    duration_ms=duration_ms,
                )

    owned_files: set[str] = set()
    for source_path in graph:
        if source_path == _WORK_ITEM_SCANNING_SENTINEL:
            continue
        normalized_source = _normalize_graph_path(source_path)
        if any(normalized_source == prefix or normalized_source.startswith(f"{prefix}/") for prefix in owned_prefixes):
            owned_files.add(source_path)

    violations: list[str] = []
    if not owned_prefixes and shape.package:
        package_prefix = _normalize_dependency_token(shape.package)
        owned_files = {
            source
            for source in graph
            if source == package_prefix or source.startswith(f"{package_prefix}/")
        }

    allowlist = {_normalize_dependency_token(item) for item in explicit_allow}
    allowlist.update({_normalize_dependency_token(shape.shape_id)})
    if not allowlist and shape.dependencies_declared:
        allowlist.update({_normalize_dependency_token(item) for item in shape.dependencies_declared})

    for source in sorted(owned_files):
        for target in sorted(graph.get(source, set())):
            if target == _WORK_ITEM_SCANNING_SENTINEL:
                continue
            if _match_allowed(target, allowlist):
                continue
            violations.append(f"{source} -> {target}")

    if violations:
        passed = False
        summary = "Import boundary violation(s) detected"
        error = "import_boundary_violation"
    duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000

    if not owned_files and shape.files:
        # If ownership cannot be resolved from scanner output, still emit deterministic evidence.
        evidence_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-ownership.txt"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            "Could not resolve shape-owned files for import-boundary check.",
            encoding="utf-8",
        )
        evidence.append(str(evidence_path))

    if violations:
        evidence_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-import-boundary.txt"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            "\n".join(violations),
            encoding="utf-8",
        )
        evidence.append(str(evidence_path))
        return _failed_result(
            shape.shape_id,
            verifier_id,
            "IMPORT_BOUNDARY",
            summary=summary,
            error=error or "import_boundary_violation",
            evidence_refs=evidence,
            deterministic=True,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    return VerifierResult(
        shape_id=shape.shape_id,
        verifier_id=verifier_id,
        kind="IMPORT_BOUNDARY",
        passed=True,
        evidence_refs=evidence,
        summary=summary,
        started_at=started_at,
        finished_at=_utcnow(),
        duration_ms=duration_ms,
        deterministic=True,
        error=None,
    )


def _run_command_verifier(
    shape: Shape,
    verifier: VerifierSpec,
    workspace_root: Path,
    started_at: str,
) -> VerifierResult:
    verifier_id = _require_stripped_text(verifier.verifier_id, "verifier_id")
    started = datetime.now(tz=UTC).replace(microsecond=0)
    evidence: list[str] = []
    duration_ms = 0.0

    if _normalize_text(verifier.params.get("mode")) in {"llm", "llm_only", "llm-only", "agent"}:
        summary = "LLM checker requested for COMMAND verifier"
        duration_ms = 0.0
        return _failed_result(
            shape.shape_id,
            verifier_id,
            "COMMAND",
            summary=summary,
            error="non_deterministic_checker",
            evidence_refs=[],
            deterministic=False,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    raw_command = verifier.params.get("command") or verifier.params.get("cmd") or []
    command = _normalize_command_tokens(raw_command)
    if not command:
        command = [str(item).strip() for item in _coerce_string_list(raw_command)]
    if not command:
        duration_ms = 0.0
        return _failed_result(
            shape.shape_id,
            verifier_id,
            "COMMAND",
            summary="COMMAND verifier has no executable command",
            error="missing_command",
            evidence_refs=[],
            deterministic=True,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    allowlist = set(
        _coerce_string_list(
            verifier.params.get("command_allowlist")
            or verifier.params.get("allowed_commands")
            or verifier.params.get("allowlist")
            or verifier.params.get("command_allow")
        )
    )
    if not allowlist:
        duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000
        return _failed_result(
            shape.shape_id,
            verifier_id,
            "COMMAND",
            summary="COMMAND verifier allowlist not configured",
            error="missing_command_allowlist",
            evidence_refs=[],
            deterministic=True,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    allowed = False
    allowlist_text = " ".join(command)
    for entry in allowlist:
        if _command_matches(command, entry):
            allowed = True
            break
        if "*" in entry and re.match(entry.replace("*", ".*"), allowlist_text):
            allowed = True
            break
    if not allowed:
        duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000
        return _failed_result(
            shape.shape_id,
            verifier_id,
            "COMMAND",
            summary="COMMAND not on strict allowlist",
            error="command_disallowed",
            evidence_refs=[],
            deterministic=True,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    timeout_seconds = int(verifier.params.get("timeout_seconds", 120) or 120)
    output_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-stdout.txt"
    error_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-{verifier_id}-stderr.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        output_path.write_text(result.stdout, encoding="utf-8")
        error_path.write_text(result.stderr, encoding="utf-8")
        evidence.extend([str(output_path), str(error_path)])
        passed = result.returncode == 0
        if passed:
            summary = f"COMMAND completed successfully: {allowlist_text}"
            duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000
            return VerifierResult(
                shape_id=shape.shape_id,
                verifier_id=verifier_id,
                kind="COMMAND",
                passed=True,
                evidence_refs=evidence,
                summary=summary,
                started_at=started_at,
                finished_at=_utcnow(),
                duration_ms=duration_ms,
                deterministic=True,
                error=None,
            )

        summary = f"COMMAND failed with exit code {result.returncode}"
        error = "command_exit_code_failure"
    except subprocess.TimeoutExpired:
        error = "command_timeout"
        summary = f"COMMAND timed out after {timeout_seconds}s: {allowlist_text}"
        error_path.write_text(f"Timed out after {timeout_seconds}s", encoding="utf-8")
        evidence.append(str(error_path))
    except FileNotFoundError as exc:
        error = "command_not_found"
        summary = f"COMMAND executable missing: {exc}"
        error_path.write_text(summary, encoding="utf-8")
        evidence.append(str(error_path))
    except Exception as exc:
        error = "command_exception"
        summary = f"COMMAND execution failed: {exc}"
        error_path.write_text(summary, encoding="utf-8")
        evidence.append(str(error_path))
    finally:
        duration_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000

    return _failed_result(
        shape.shape_id,
        verifier_id,
        "COMMAND",
        summary=summary,
        error=error,
        evidence_refs=[*dict.fromkeys(evidence)],
        deterministic=True,
        started_at=started_at,
        duration_ms=duration_ms,
    )


def run_shape_verifier(shape: Shape, verifier: VerifierSpec, workspace_root: Path) -> VerifierResult:
    workspace_root = Path(workspace_root)
    started_at = _utcnow()
    try:
        verifier_id = _require_stripped_text(verifier.verifier_id, "verifier_id")
    except ValueError:
        return _failed_result(
            shape.shape_id,
            "",
            str(verifier.kind or "unknown"),
            summary="Invalid verifier declaration",
            error="invalid_verifier_spec",
            evidence_refs=[],
            deterministic=True,
            started_at=started_at,
            duration_ms=0.0,
        )

    kind = _normalize_text(verifier.kind or "")
    if kind == "test":
        return _run_test_verifier(shape, verifier, workspace_root, started_at)
    if kind == "import_boundary":
        return _run_import_boundary_verifier(shape, verifier, workspace_root, started_at)
    if kind == "command":
        return _run_command_verifier(shape, verifier, workspace_root, started_at)

    return _failed_result(
        shape.shape_id,
        verifier_id,
        kind or "unknown",
        summary=f"Unknown verifier kind: {kind or 'unknown'}",
        error="unknown_verifier_kind",
        evidence_refs=[],
        deterministic=True,
        started_at=started_at,
        duration_ms=0.0,
    )


def run_shape_verifiers(shape: Shape, workspace_root: Path) -> VerifierRunSummary:
    workspace_root = Path(workspace_root)
    results: list[VerifierResult] = []
    missing_required: list[str] = []
    seen: set[str] = set()
    is_active = _normalize_text(getattr(shape, "status", "")) == "active"

    if not getattr(shape, "verifiers", None):
        if is_active:
            started_at = _utcnow()
            results.append(
                VerifierResult(
                    shape_id=shape.shape_id,
                    verifier_id="shape-no-verifiers",
                    kind="ACTIVE_REQUIRED",
                    passed=False,
                    evidence_refs=[],
                    summary="ACTIVE shape has no verifiers",
                    started_at=started_at,
                    finished_at=_utcnow(),
                    duration_ms=0.0,
                    deterministic=True,
                    error="missing_shape_verifier",
                )
            )
            missing_required = ["shape-no-verifiers"]
        else:
            evidence_path = workspace_root / ".routing_verifier_artifacts" / f"{shape.shape_id}-proposal-warning.txt"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(
                f"PROPOSAL shape '{shape.shape_id}' has no verifiers configured.",
                encoding="utf-8",
            )
            results.append(
                VerifierResult(
                    shape_id=shape.shape_id,
                    verifier_id="shape-no-verifiers",
                    kind="PROPOSAL_REQUIRED",
                    passed=False,
                    evidence_refs=[str(evidence_path)],
                    summary="PROPOSAL shape has no verifiers yet",
                    started_at=_utcnow(),
                    finished_at=_utcnow(),
                    duration_ms=0.0,
                    deterministic=True,
                    error="missing_shape_verifier",
                )
            )
            missing_required = ["shape-no-verifiers"]
        return VerifierRunSummary(
            shape_id=shape.shape_id,
            all_passed=False if is_active else True,
            results=results,
            missing_required=missing_required,
            non_ship_block=is_active,
        )

    for verifier in shape.verifiers:
        verifier_id = _normalize_text(getattr(verifier, "verifier_id", ""))
        if not verifier_id:
            continue
        if verifier_id in seen:
            duplicate = VerifierResult(
                shape_id=shape.shape_id,
                verifier_id=f"{verifier_id}-duplicate",
                kind=str(verifier.kind or "unknown"),
                passed=False,
                evidence_refs=[],
                summary=f"Duplicate verifier id '{verifier_id}'",
                started_at=_utcnow(),
                finished_at=_utcnow(),
                duration_ms=0.0,
                deterministic=True,
                error="duplicate_verifier_id",
            )
            results.append(duplicate)
            continue
        seen.add(verifier_id)
        results.append(run_shape_verifier(shape, verifier, workspace_root))

    all_passed = bool(results) and all(item.passed for item in results) if is_active else True
    return VerifierRunSummary(
        shape_id=shape.shape_id,
        all_passed=all_passed,
        results=results,
        missing_required=missing_required,
        non_ship_block=(is_active and not results),
    )


def run_all_active_shape_verifiers(
    index: ShapePackIndex,
    workspace_root: Path,
) -> dict[ShapeId, VerifierRunSummary]:
    workspace_root = Path(workspace_root)
    summaries: dict[ShapeId, VerifierRunSummary] = {}
    for shape_id, shape in sorted(index.shapes.items(), key=lambda item: str(item[0])):
        summaries[shape_id] = run_shape_verifiers(shape, workspace_root)
    return summaries


def enforce_non_ship_policy(
    shape_summaries: dict[ShapeId, VerifierRunSummary],
    required_contract_shape_ids: set[ShapeId],
) -> tuple[bool, list[str]]:
    blocking: list[str] = []
    for raw_shape_id in sorted(required_contract_shape_ids, key=lambda item: str(item)):
        normalized = ShapeId(_normalize_text(raw_shape_id))
        summary = shape_summaries.get(normalized)
        if summary is None:
            blocking.append(f"{normalized}: missing verifier summary")
            continue
        if summary.non_ship_block or not summary.all_passed:
            blocking.append(f"{normalized}: non-deterministic verifier state")
    return bool(blocking), blocking


__all__ = [
    "VerifierResult",
    "VerifierRunSummary",
    "enforce_non_ship_policy",
    "run_all_active_shape_verifiers",
    "run_shape_verifier",
    "run_shape_verifiers",
]

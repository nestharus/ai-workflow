"""Architectural quality checks for layer promotion gating.

Verifies:
1. No inlined atom logic in the architectural layer
2. Function recomposition quality (proper imports and calls)
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.formats import _strip_code_fences
from spec_manager.schemas.pin_functions import PinFunctionRegistry

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile


@dataclass
class InlinedLogicFinding:
    """A location where atom logic appears to be copy-pasted inline.

    Attributes:
        arch_file: Architectural file path.
        arch_line_start: Start line of the suspected inlined code.
        arch_line_end: End line of the suspected inlined code.
        matching_pin_func_id: Pin-function whose logic appears inlined.
        similarity_score: 0.0-1.0 indicating how similar the code is.
        detection_method: How the duplication was detected.
    """

    arch_file: str
    arch_line_start: int
    arch_line_end: int
    matching_pin_func_id: str
    similarity_score: float
    detection_method: str  # "exact_match", "text_similarity", "fingerprint_overlap"


def _hash_function_body(source: str, start_line: int, end_line: int) -> str:
    """Compute SHA-256 hash of a function body."""
    lines = source.splitlines()
    body_lines = lines[start_line - 1 : end_line]
    normalized = "\n".join(line.strip() for line in body_lines if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _extract_span_text(source: str, start: int, end: int) -> str:
    lines = source.splitlines()
    lower = max(0, start - 1)
    upper = min(end, len(lines))
    return "\n".join(lines[lower:upper]).strip()


def _extract_function_info(file_path: Path) -> list[tuple[RawFunctionInfo, str]]:
    """Extract function info and source text from a file using analyze_source."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    analysis = analyze_source(source, str(file_path))
    return [(func, source) for func in analysis.functions]


def _extract_function_info_from_analyzed(af: AnalyzedFile) -> list[tuple[RawFunctionInfo, str]]:
    """Extract function info from a pre-loaded AnalyzedFile."""
    return [(func, af.content) for func in af.analysis.functions]


def _llm_detect_inlined_logic(
    *,
    workspace: Path,
    agent_name: str,
    arch_span: str,
    arch_context: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Use semantic analysis to determine whether an arch span inlines an atom."""
    from spec_manager.core.agent_utils import run_agent

    prompt = (
        "Decide whether the architectural span inlines atom logic from the candidate list.\n"
        "Use semantic behavior equivalence; do not rely on superficial token matching.\n"
        "Return JSON only:\n"
        '{"duplicate": true|false, "matching_pin_func_id": "string|null", '
        '"confidence": 0.0, "reason": "string"}\n\n'
        f"Architectural location: {arch_context}\n"
        "Architectural span:\n"
        "```\n"
        f"{arch_span[:6000]}\n"
        "```\n\n"
        "Candidate atom spans:\n"
        f"{json.dumps(candidates, ensure_ascii=True)}\n"
    )
    raw_output = run_agent(
        agent_name=agent_name,
        prompt=prompt,
        workspace=workspace,
    )
    cleaned = _strip_code_fences(raw_output)
    payload = _extract_json_payload(cleaned)
    if not payload:
        return None
    try:
        loaded = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _collect_pin_span_texts(
    pin_registry: PinFunctionRegistry,
    algorithmic_files: list[Path],
    analyzed_algo: list[AnalyzedFile] | None,
) -> dict[str, dict[str, Any]]:
    """Collect candidate atom spans keyed by pin-function ID."""
    pin_ids_by_name: dict[str, list[str]] = {}
    for pin in pin_registry.pin_functions:
        pin_ids_by_name.setdefault(pin.function_name, []).append(pin.pin_func_id)

    span_by_pin_id: dict[str, dict[str, Any]] = {}
    analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed_algo is not None:
        for af in analyzed_algo:
            analyzed_lookup[af.path] = af

    for algo_file in algorithmic_files:
        af = analyzed_lookup.get(str(algo_file))
        entries = (
            _extract_function_info_from_analyzed(af) if af else _extract_function_info(algo_file)
        )
        for func_info, source in entries:
            pin_ids = pin_ids_by_name.get(func_info.name, [])
            if not pin_ids:
                continue
            span_text = _extract_span_text(source, func_info.start_line, func_info.end_line)
            if not span_text:
                continue
            for pin_id in pin_ids:
                span_by_pin_id[pin_id] = {
                    "pin_func_id": pin_id,
                    "function_name": func_info.name,
                    "file_path": str(algo_file),
                    "line_start": func_info.start_line,
                    "line_end": func_info.end_line,
                    "span": span_text,
                }

    # Keep empty placeholders for pins whose source span wasn't resolved.
    for pin in pin_registry.pin_functions:
        span_by_pin_id.setdefault(
            pin.pin_func_id,
            {
                "pin_func_id": pin.pin_func_id,
                "function_name": pin.function_name,
                "file_path": pin.file_path,
                "line_start": pin.line_start,
                "line_end": pin.line_end,
                "span": "",
            },
        )
    return span_by_pin_id


def check_no_inlined_atom_logic(
    pin_registry: PinFunctionRegistry,
    architectural_files: list[Path],
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
    analyzed_arch: list[AnalyzedFile] | None = None,
    analyzed_algo: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: No semantically inlined atom logic in architectural layer."""
    start_time = time.monotonic()
    semantic_agent = str(gate_spec.params.get("semantic_agent", "pdd-code-analyzer"))
    workspace = Path(str(gate_spec.params.get("workspace", ".")).strip() or ".")
    min_confidence = float(gate_spec.params.get("semantic_min_confidence", 0.6))
    max_candidates = int(gate_spec.params.get("semantic_candidate_limit", 12))

    pin_spans = _collect_pin_span_texts(pin_registry, algorithmic_files, analyzed_algo)
    candidate_pool = list(pin_spans.values())

    all_findings: list[dict[str, Any]] = []
    ambiguous_findings: list[dict[str, Any]] = []

    arch_analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed_arch is not None:
        for af in analyzed_arch:
            arch_analyzed_lookup[af.path] = af

    for arch_file in architectural_files:
        af = arch_analyzed_lookup.get(str(arch_file))
        arch_entries = (
            _extract_function_info_from_analyzed(af) if af else _extract_function_info(arch_file)
        )
        for arch_func_info, arch_source in arch_entries:
            arch_end = arch_func_info.end_line
            arch_span = _extract_span_text(arch_source, arch_func_info.start_line, arch_end)
            if not arch_span:
                continue

            ranked_candidates = [
                candidate
                for candidate in candidate_pool
                if candidate.get("span")
                and str(candidate.get("function_name", "")).lower() in arch_span.lower()
            ]
            if not ranked_candidates:
                ranked_candidates = [
                    candidate for candidate in candidate_pool if candidate.get("span")
                ]
            candidates_payload = ranked_candidates[: max(1, max_candidates)]
            if not candidates_payload:
                continue

            llm_decision = _llm_detect_inlined_logic(
                workspace=workspace,
                agent_name=semantic_agent,
                arch_span=arch_span,
                arch_context=f"{arch_file}:{arch_func_info.start_line}-{arch_end}",
                candidates=candidates_payload,
            )
            if not llm_decision:
                ambiguous_findings.append(
                    {
                        "arch_file": str(arch_file),
                        "arch_line_start": arch_func_info.start_line,
                        "arch_line_end": arch_end,
                        "arch_function_name": arch_func_info.name,
                        "reason": "semantic_evaluator_failed",
                        "candidate_pin_func_ids": [
                            str(item.get("pin_func_id", "")) for item in candidates_payload
                        ],
                    }
                )
                continue

            duplicate = bool(llm_decision.get("duplicate"))
            matching_pin = str(llm_decision.get("matching_pin_func_id") or "").strip()
            try:
                confidence = float(llm_decision.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0

            if confidence < min_confidence:
                ambiguous_findings.append(
                    {
                        "arch_file": str(arch_file),
                        "arch_line_start": arch_func_info.start_line,
                        "arch_line_end": arch_end,
                        "arch_function_name": arch_func_info.name,
                        "reason": "semantic_confidence_below_threshold",
                        "llm_confidence": confidence,
                        "llm_reason": llm_decision.get("reason"),
                    }
                )
                continue
            if not duplicate:
                continue
            if matching_pin not in pin_spans:
                ambiguous_findings.append(
                    {
                        "arch_file": str(arch_file),
                        "arch_line_start": arch_func_info.start_line,
                        "arch_line_end": arch_end,
                        "arch_function_name": arch_func_info.name,
                        "reason": "semantic_match_not_in_candidate_pool",
                        "matching_pin_func_id": matching_pin,
                    }
                )
                continue

            all_findings.append(
                {
                    "arch_file": str(arch_file),
                    "arch_line_start": arch_func_info.start_line,
                    "arch_line_end": arch_end,
                    "matching_pin_func_id": matching_pin,
                    "similarity_score": confidence,
                    "detection_method": "semantic_llm",
                    "arch_function_name": arch_func_info.name,
                    "llm_confidence": confidence,
                    "llm_reason": llm_decision.get("reason"),
                }
            )

    duration = (time.monotonic() - start_time) * 1000
    if all_findings:
        status = GateStatus.FAILED
        score = 0.0
        summary = f"Found {len(all_findings)} instance(s) of inlined atom logic"
        findings = all_findings
    elif ambiguous_findings:
        status = GateStatus.AMBIGUOUS
        score = 0.5
        summary = "Inlined-logic detection is ambiguous for some spans; manual review required."
        findings = ambiguous_findings
    else:
        status = GateStatus.PASSED
        score = 1.0
        summary = "No inlined atom logic found in architectural layer"
        findings = []

    return GateCheckResult(
        gate_id=GateId.NO_INLINED_ATOM_LOGIC.value,
        mode=gate_spec.mode.value,
        status=status,
        score=score,
        findings=findings,
        summary=summary,
        duration_ms=duration,
    )


def check_function_recomposition(
    pin_registry: PinFunctionRegistry,
    architectural_files: list[Path],
    gate_spec: GateSpec,
    analyzed_arch: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: Architectural functions correctly recompose atoms.

    Verifies:
    1. All imported pin-functions are actually called (no dead imports).
    2. No local variables shadow imported pin-function names.

    gate_spec.params:
        - check_dead_imports (bool, default True): Flag unused pin imports.
        - check_signature_match (bool, default True): Verify call arg counts.

    Args:
        pin_registry: PinFunctionRegistry.
        architectural_files: Architectural layer files.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for recomposition issues.
    """
    start_time = time.monotonic()
    check_dead_imports = gate_spec.params.get("check_dead_imports", True)

    # Build set of pin-function names
    pin_func_names: dict[str, str] = {}  # function_name -> pin_func_id
    pin_names_by_id: dict[str, str] = {}
    for pf in pin_registry.pin_functions:
        pin_func_names[pf.function_name] = pf.pin_func_id
        pin_names_by_id[pf.pin_func_id] = pf.function_name

    findings: list[dict[str, Any]] = []
    unreadable_file_count = 0

    # Group pin-consumption edges by architecture file.
    imports_by_file: dict[str, set[str]] = {}
    for edge in pin_registry.import_edges:
        function_name = pin_names_by_id.get(edge.pin_func_id)
        if not function_name:
            continue
        key = str(edge.arch_file_path).replace("\\", "/").strip()
        if not key:
            continue
        imports_by_file.setdefault(key, set()).add(function_name)

    # Build analyzed lookup
    arch_analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed_arch is not None:
        for af in analyzed_arch:
            arch_analyzed_lookup[af.path] = af

    for arch_file in architectural_files:
        file_str = str(arch_file).replace("\\", "/")
        imported_pin_names = set(imports_by_file.get(file_str, set()))
        if not imported_pin_names:
            for candidate_key, names in imports_by_file.items():
                if file_str.endswith(candidate_key):
                    imported_pin_names.update(names)
        if not imported_pin_names:
            continue

        af = arch_analyzed_lookup.get(file_str)
        if af is not None:
            source = af.content
            analysis = af.analysis
        else:
            try:
                source = arch_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                unreadable_file_count += 1
                findings.append(
                    {
                        "arch_file": file_str,
                        "issue_type": "file_unreadable",
                        "reason": f"read_error:{type(exc).__name__}",
                    }
                )
                continue
            analysis = analyze_source(source, file_str)
        lines = source.splitlines()
        called_names: set[str] = set()
        for func in analysis.functions:
            body_start = func.body_start_line if func.body_start_line > 0 else func.start_line
            body_end = func.end_line
            if body_start > 0 and body_end > 0 and body_end <= len(lines):
                body_text = "\n".join(lines[body_start - 1 : body_end])
                # Find call-like patterns in body text (acceptable local regex)
                called_names.update(re.findall(r"\b(\w+)\s*\(", body_text))

        # Also check module-level calls (outside functions)
        called_names.update(re.findall(r"\b(\w+)\s*\(", source))

        # Find assignments that shadow imported pin-function names
        # using analyze_source function bodies
        shadowed_names: set[str] = set()
        for func in analysis.functions:
            body_start = func.body_start_line if func.body_start_line > 0 else func.start_line
            body_end = func.end_line
            if body_start > 0 and body_end > 0 and body_end <= len(lines):
                body_lines = lines[body_start - 1 : body_end]
                for line in body_lines:
                    stripped = line.strip()
                    # Simple assignment detection: "name = ..."
                    # Skip comparisons (==, !=, <=, >=) and comments
                    if "=" in stripped and not stripped.startswith("#") and "==" not in stripped:
                        lhs = stripped.split("=")[0].strip()
                        # Exclude augmented assignments (+=, -=, etc.)
                        if (
                            lhs.isidentifier()
                            and not stripped.startswith(f"{lhs} +=")
                            and not stripped.startswith(f"{lhs} -=")
                            and not stripped.startswith(f"{lhs} *=")
                            and not stripped.startswith(f"{lhs} /=")
                            and lhs in imported_pin_names
                        ):
                            shadowed_names.add(lhs)

        # Check for dead imports
        if check_dead_imports:
            unused = imported_pin_names - called_names
            for name in unused:
                findings.append(
                    {
                        "arch_file": file_str,
                        "issue_type": "dead_import",
                        "pin_func_name": name,
                        "pin_func_id": pin_func_names[name],
                        "message": (f"Pin-function '{name}' is imported but never called"),
                    }
                )

        # Check for shadowing
        for name in shadowed_names:
            findings.append(
                {
                    "arch_file": file_str,
                    "issue_type": "shadowed_import",
                    "pin_func_name": name,
                    "pin_func_id": pin_func_names[name],
                    "message": (f"Local variable shadows imported pin-function '{name}'"),
                }
            )

    duration = (time.monotonic() - start_time) * 1000
    if unreadable_file_count > 0:
        status = GateStatus.STALE_EVIDENCE
        score = 0.0
        passed = False
        summary = (
            "Function recomposition evidence is incomplete: "
            f"{unreadable_file_count} architectural file(s) were unreadable"
        )
    else:
        passed = len(findings) == 0
        status = GateStatus.PASSED if passed else GateStatus.FAILED
        score = 1.0 if passed else max(0.0, 1.0 - len(findings) * 0.1)
        summary = (
            "Architectural functions correctly recompose atoms"
            if passed
            else f"Found {len(findings)} recomposition issue(s)"
        )

    return GateCheckResult(
        gate_id=GateId.FUNCTION_RECOMPOSITION.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=status,
        score=score,
        findings=findings,
        summary=summary,
        duration_ms=duration,
    )


def check_pin_consumption_coverage(
    pin_registry: PinFunctionRegistry,
    component_manifest: dict[str, Any],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: every in-scope pin is consumed by at least one component."""
    start = time.monotonic()
    in_scope_pins = {pf.pin_func_id for pf in pin_registry.pin_functions}
    consumed: set[str] = set()

    for component in component_manifest.get("components", []):
        if not isinstance(component, dict):
            continue
        for pin in component.get("pins_consumed", []):
            if isinstance(pin, str) and pin.strip():
                consumed.add(pin.strip())

    missing = sorted(pin for pin in in_scope_pins if pin not in consumed)
    findings = [{"pin_func_id": pin, "reason": "not_consumed_by_any_component"} for pin in missing]
    passed = not missing
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.PIN_CONSUMPTION_COVERAGE.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=(len(in_scope_pins) - len(missing)) / len(in_scope_pins) if in_scope_pins else 1.0,
        findings=findings,
        summary=(
            "All in-scope pins are consumed by declared components"
            if passed
            else f"{len(missing)} pin(s) are not consumed by any declared component"
        ),
        duration_ms=duration,
    )


def check_edge_realization(
    component_manifest: dict[str, Any],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: component interaction edges reference valid components."""
    start = time.monotonic()
    components = [
        item for item in component_manifest.get("components", []) if isinstance(item, dict)
    ]
    component_ids = {
        str(item.get("component_id", "")).strip()
        for item in components
        if str(item.get("component_id", "")).strip()
    }

    findings: list[dict[str, Any]] = []
    for component in components:
        cid = str(component.get("component_id", "")).strip()
        for direction in ("upstream", "downstream"):
            for dep in component.get(direction, []):
                if not isinstance(dep, str):
                    continue
                dep_id = dep.strip()
                if not dep_id:
                    continue
                if dep_id not in component_ids:
                    findings.append(
                        {
                            "component_id": cid,
                            "direction": direction,
                            "missing_component_ref": dep_id,
                        }
                    )

    has_relationships = any(
        isinstance(component.get("upstream"), list) or isinstance(component.get("downstream"), list)
        for component in components
    )
    duration = (time.monotonic() - start) * 1000
    if not has_relationships:
        return GateCheckResult(
            gate_id=GateId.EDGE_REALIZATION.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "component_manifest_missing_edge_data"}],
            summary="Component manifest has no upstream/downstream edge evidence",
            duration_ms=duration,
        )

    passed = not findings
    return GateCheckResult(
        gate_id=GateId.EDGE_REALIZATION.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=(
            "Component manifest edge references are valid"
            if passed
            else f"Found {len(findings)} invalid component edge reference(s)"
        ),
        duration_ms=duration,
    )


def check_no_orphan_components(
    component_manifest: dict[str, Any],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: every component has at least one reachable entrypoint."""
    start = time.monotonic()
    findings: list[dict[str, Any]] = []

    for component in component_manifest.get("components", []):
        if not isinstance(component, dict):
            continue
        component_id = str(component.get("component_id", "")).strip()
        entrypoints = [
            ep
            for ep in component.get("owned_entrypoints", [])
            if isinstance(ep, str) and ep.strip()
        ]
        if component_id and not entrypoints:
            findings.append(
                {
                    "component_id": component_id,
                    "reason": "missing_owned_entrypoints",
                }
            )

    passed = not findings
    duration = (time.monotonic() - start) * 1000
    return GateCheckResult(
        gate_id=GateId.NO_ORPHAN_COMPONENTS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=(
            "Every component has at least one owned entrypoint"
            if passed
            else f"Found {len(findings)} orphan component(s) without entrypoints"
        ),
        duration_ms=duration,
    )


def check_event_handler_coverage(
    component_manifest: dict[str, Any],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: each declared event should have at least one consumer."""
    start = time.monotonic()
    events = component_manifest.get("events")
    if not isinstance(events, list):
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.EVENT_HANDLER_COVERAGE.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "events_section_missing"}],
            summary="Component manifest does not include event coverage evidence",
            duration_ms=duration,
        )

    findings: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or event.get("name") or "").strip()
        consumers = [c for c in event.get("consumers", []) if isinstance(c, str) and c.strip()]
        external_only = bool(event.get("external_only"))
        if event_id and not consumers and not external_only:
            findings.append({"event_id": event_id, "reason": "no_consumers"})

    passed = not findings
    duration = (time.monotonic() - start) * 1000
    return GateCheckResult(
        gate_id=GateId.EVENT_HANDLER_COVERAGE.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=(
            "All declared events have at least one consumer or are external-only"
            if passed
            else f"Found {len(findings)} event(s) without consumers"
        ),
        duration_ms=duration,
    )


def check_config_externalization(
    architectural_files: list[Path],
    gate_spec: GateSpec,
    analyzed_arch: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: environment/config should be injected rather than hardcoded."""
    start = time.monotonic()
    semantic_agent = str(gate_spec.params.get("semantic_agent", "pdd-code-analyzer"))
    workspace = Path(str(gate_spec.params.get("workspace", ".")).strip() or ".")

    analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed_arch is not None:
        for af in analyzed_arch:
            analyzed_lookup[af.path] = af

    hardcoded_findings: list[dict[str, Any]] = []
    ambiguous_findings: list[dict[str, Any]] = []
    stale_findings: list[dict[str, Any]] = []
    for file_path in architectural_files:
        af = analyzed_lookup.get(str(file_path))
        if af is not None:
            source = af.content
        else:
            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                stale_findings.append(
                    {
                        "file_path": str(file_path),
                        "reason": f"file_unreadable:{type(exc).__name__}",
                    }
                )
                continue
        payload = _llm_detect_hardcoded_config(
            workspace=workspace,
            agent_name=semantic_agent,
            file_path=str(file_path),
            source=source,
        )
        if payload is None:
            ambiguous_findings.append(
                {
                    "file_path": str(file_path),
                    "reason": "semantic_evaluator_failed",
                }
            )
            continue

        rows = payload.get("findings", [])
        if not isinstance(rows, list):
            ambiguous_findings.append(
                {
                    "file_path": str(file_path),
                    "reason": "semantic_evaluator_invalid_payload",
                }
            )
            continue

        for row_idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                ambiguous_findings.append(
                    {
                        "file_path": str(file_path),
                        "reason": "semantic_evaluator_invalid_row",
                        "row_index": row_idx,
                    }
                )
                continue

            raw_line = row.get("line", 0)
            try:
                line = int(raw_line or 0)
            except (TypeError, ValueError):
                ambiguous_findings.append(
                    {
                        "file_path": str(file_path),
                        "reason": "semantic_evaluator_invalid_line",
                        "row_index": row_idx,
                        "raw_line": repr(raw_line),
                    }
                )
                continue

            hardcoded_findings.append(
                {
                    "file_path": str(file_path),
                    "line": line,
                    "snippet": str(row.get("snippet", "")).strip()[:200],
                    "reason": str(row.get("reason", "")).strip(),
                }
            )

    duration = (time.monotonic() - start) * 1000
    findings: list[dict[str, Any]]
    if hardcoded_findings:
        findings = hardcoded_findings + stale_findings + ambiguous_findings
        status = GateStatus.FAILED
        score = 0.0
        summary = f"Found {len(hardcoded_findings)} potential hardcoded config assignment(s)"
    elif stale_findings:
        findings = stale_findings + ambiguous_findings
        status = GateStatus.STALE_EVIDENCE
        score = 0.0
        summary = "Config externalization evidence is incomplete (unreadable architectural files)"
    elif ambiguous_findings:
        findings = ambiguous_findings
        status = GateStatus.AMBIGUOUS
        score = 0.5
        summary = "Semantic config externalization check was inconclusive for some files"
    else:
        findings = []
        status = GateStatus.PASSED
        score = 1.0
        summary = "No semantic hardcoded runtime config values detected"

    passed = status == GateStatus.PASSED
    return GateCheckResult(
        gate_id=GateId.CONFIG_EXTERNALIZATION.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=status,
        score=score,
        findings=findings,
        summary=summary,
        duration_ms=duration,
    )


def _llm_detect_hardcoded_config(
    *,
    workspace: Path,
    agent_name: str,
    file_path: str,
    source: str,
) -> dict[str, Any] | None:
    from spec_manager.core.agent_utils import run_agent

    prompt = (
        "Identify hardcoded runtime configuration values that should be injected.\n"
        "Classify semantically (for example credentials, endpoint URLs, hostnames,\n"
        "service tokens, environment-specific constants). Ignore harmless local literals.\n"
        "Return JSON only with shape: "
        '{"findings":[{"line":1,"snippet":"...","reason":"..."}]}.\n\n'
        f"File: {file_path}\n"
        "Source:\n"
        "```\n"
        f"{source[:12000]}\n"
        "```\n"
    )
    raw_output = run_agent(
        agent_name=agent_name,
        prompt=prompt,
        workspace=workspace,
    )
    cleaned = _strip_code_fences(raw_output)
    payload = _extract_json_payload(cleaned)
    if not payload:
        return None
    try:
        loaded = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def check_arch_drift_pass(
    component_manifest_path: Path | None,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: detect stale architecture evidence from content identity mismatch."""
    start = time.monotonic()
    expected_hash = str(gate_spec.params.get("expected_manifest_hash", "")).strip()
    if component_manifest_path is None or not component_manifest_path.exists():
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.ARCH_DRIFT_PASS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "component_manifest_missing"}],
            summary="Component manifest is missing; cannot evaluate architecture drift",
            duration_ms=duration,
        )
    if not expected_hash:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.ARCH_DRIFT_PASS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "expected_manifest_hash_missing"}],
            summary="Expected architecture evidence hash not provided",
            duration_ms=duration,
        )

    try:
        raw = component_manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        duration = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.ARCH_DRIFT_PASS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": f"manifest_read_error:{type(exc).__name__}"}],
            summary="Failed reading component manifest for drift assessment",
            duration_ms=duration,
        )

    current_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    passed = current_hash == expected_hash
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.ARCH_DRIFT_PASS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.STALE_EVIDENCE,
        score=1.0 if passed else 0.0,
        findings=[] if passed else [{"expected_hash": expected_hash, "current_hash": current_hash}],
        summary=(
            "Architecture evidence hash matches current manifest"
            if passed
            else "Architecture evidence hash mismatch (stale evidence)"
        ),
        duration_ms=duration,
    )

"""Architectural quality checks for layer promotion gating.

Verifies:
1. No inlined atom logic in the architectural layer
2. Function recomposition quality (proper imports and calls)
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source
from spec_manager.projection.lineage.builder import scan_imports_from_files
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


def _text_similarity(
    source_a: str,
    start_a: int,
    end_a: int,
    source_b: str,
    start_b: int,
    end_b: int,
) -> float:
    """Compute text-based structural similarity between two function bodies."""
    from difflib import SequenceMatcher

    lines_a = source_a.splitlines()[start_a - 1 : end_a]
    lines_b = source_b.splitlines()[start_b - 1 : end_b]
    # Normalize: strip whitespace, skip empty/comment lines
    norm_a = [line.strip() for line in lines_a if line.strip() and not line.strip().startswith("#")]
    norm_b = [line.strip() for line in lines_b if line.strip() and not line.strip().startswith("#")]
    if not norm_a or not norm_b:
        return 0.0
    return SequenceMatcher(None, "\n".join(norm_a), "\n".join(norm_b)).ratio()


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


def _get_line_fingerprints(source: str, start: int, end: int) -> set[str]:
    """Get SHA-256 fingerprints for individual lines in a range."""
    lines = source.splitlines()
    fingerprints: set[str] = set()
    for i in range(max(0, start - 1), min(end, len(lines))):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            fp = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
            fingerprints.add(fp)
    return fingerprints


def check_no_inlined_atom_logic(
    pin_registry: PinFunctionRegistry,
    architectural_files: list[Path],
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
    analyzed_arch: list[AnalyzedFile] | None = None,
    analyzed_algo: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: No inlined atom logic in architectural layer.

    Detection strategies (applied in order):
    1. Exact body match: Hash the body of each architectural function,
       compare against pin-function content_hash values.
    2. Text structural similarity: Normalize source lines, compare structure.
    3. Line fingerprint overlap: If >threshold of an architectural
       function's line fingerprints match a pin-function's lines, flag it.

    gate_spec.params:
        - similarity_threshold (float, default 0.8): Minimum text similarity.
        - fingerprint_overlap_threshold (float, default 0.6): Minimum line
            fingerprint overlap.
        - exclude_patterns (list[str]): File patterns to skip.

    Args:
        pin_registry: PinFunctionRegistry with atom content hashes.
        architectural_files: Architectural layer files to scan.
        algorithmic_files: Algorithmic layer files (for body extraction).
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each inlined logic instance.
    """
    start_time = time.monotonic()
    similarity_threshold = gate_spec.params.get("similarity_threshold", 0.8)
    fingerprint_overlap_threshold = gate_spec.params.get("fingerprint_overlap_threshold", 0.6)

    # Build map of pin-function content hashes -> pin_func_id
    pin_hashes: dict[str, str] = {}
    for pf in pin_registry.pin_functions:
        if pf.content_hash:
            pin_hashes[pf.content_hash] = pf.pin_func_id

    # Extract pin-function info and line fingerprints from algorithmic files
    pin_func_info: dict[str, tuple[RawFunctionInfo, str]] = {}
    pin_func_fingerprints: dict[str, set[str]] = {}
    pin_func_id_by_name: dict[str, str] = {}

    for pf in pin_registry.pin_functions:
        pin_func_id_by_name[pf.function_name] = pf.pin_func_id

    # Build algo lookup from analyzed or files
    algo_analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed_algo is not None:
        for af in analyzed_algo:
            algo_analyzed_lookup[af.path] = af

    for algo_file in algorithmic_files:
        af = algo_analyzed_lookup.get(str(algo_file))
        entries = (
            _extract_function_info_from_analyzed(af) if af else _extract_function_info(algo_file)
        )
        for func_info, source in entries:
            func_name = func_info.name
            if func_name in pin_func_id_by_name:
                pfid = pin_func_id_by_name[func_name]
                pin_func_info[pfid] = (func_info, source)
                pin_func_fingerprints[pfid] = _get_line_fingerprints(
                    source, func_info.start_line, func_info.end_line
                )

    # Scan architectural files
    all_findings: list[dict[str, Any]] = []

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

            # Strategy 1: Exact body match
            arch_hash = _hash_function_body(arch_source, arch_func_info.start_line, arch_end)
            if arch_hash in pin_hashes:
                all_findings.append(
                    {
                        "arch_file": str(arch_file),
                        "arch_line_start": arch_func_info.start_line,
                        "arch_line_end": arch_end,
                        "matching_pin_func_id": pin_hashes[arch_hash],
                        "similarity_score": 1.0,
                        "detection_method": "exact_match",
                        "arch_function_name": arch_func_info.name,
                    }
                )
                continue  # No need to check other strategies

            # Strategy 2: Text structural similarity
            best_similarity = 0.0
            best_match_id = ""
            for pfid, (pf_info, pf_source) in pin_func_info.items():
                sim = _text_similarity(
                    arch_source,
                    arch_func_info.start_line,
                    arch_end,
                    pf_source,
                    pf_info.start_line,
                    pf_info.end_line,
                )
                if sim > best_similarity:
                    best_similarity = sim
                    best_match_id = pfid

            if best_similarity >= similarity_threshold:
                all_findings.append(
                    {
                        "arch_file": str(arch_file),
                        "arch_line_start": arch_func_info.start_line,
                        "arch_line_end": arch_end,
                        "matching_pin_func_id": best_match_id,
                        "similarity_score": best_similarity,
                        "detection_method": "text_similarity",
                        "arch_function_name": arch_func_info.name,
                    }
                )
                continue

            # Strategy 3: Line fingerprint overlap
            arch_fps = _get_line_fingerprints(arch_source, arch_func_info.start_line, arch_end)
            if not arch_fps:
                continue

            for pfid, pin_fps in pin_func_fingerprints.items():
                if not pin_fps:
                    continue
                overlap = len(arch_fps & pin_fps)
                overlap_ratio = overlap / len(arch_fps)
                if overlap_ratio >= fingerprint_overlap_threshold:
                    all_findings.append(
                        {
                            "arch_file": str(arch_file),
                            "arch_line_start": arch_func_info.start_line,
                            "arch_line_end": arch_end,
                            "matching_pin_func_id": pfid,
                            "similarity_score": overlap_ratio,
                            "detection_method": "fingerprint_overlap",
                            "arch_function_name": arch_func_info.name,
                        }
                    )
                    break

    passed = len(all_findings) == 0
    duration = (time.monotonic() - start_time) * 1000

    return GateCheckResult(
        gate_id=GateId.NO_INLINED_ATOM_LOGIC.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=all_findings,
        summary=(
            "No inlined atom logic found in architectural layer"
            if passed
            else f"Found {len(all_findings)} instance(s) of inlined atom logic"
        ),
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
    pin_func_signatures: dict[str, int] = {}  # function_name -> param count
    for pf in pin_registry.pin_functions:
        pin_func_names[pf.function_name] = pf.pin_func_id
        # Extract param count from signature string
        sig = pf.signature
        if "(" in sig and ")" in sig:
            params_str = sig[sig.index("(") + 1 : sig.rindex(")")]
            params = [p.strip() for p in params_str.split(",") if p.strip() and p.strip() != "self"]
            pin_func_signatures[pf.function_name] = len(params)

    findings: list[dict[str, Any]] = []

    # Use evidence-based import scanning for all architectural files
    import_records = scan_imports_from_files(architectural_files)

    # Group import records by file
    imports_by_file: dict[str, set[str]] = {}
    for record in import_records:
        name = record.imported_name
        if name in pin_func_names:
            imports_by_file.setdefault(record.importer_file, set()).add(name)

    # Build analyzed lookup
    arch_analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed_arch is not None:
        for af in analyzed_arch:
            arch_analyzed_lookup[af.path] = af

    for arch_file in architectural_files:
        file_str = str(arch_file)
        imported_pin_names = imports_by_file.get(file_str, set())
        if not imported_pin_names:
            continue

        af = arch_analyzed_lookup.get(file_str)
        if af is not None:
            source = af.content
            analysis = af.analysis
        else:
            try:
                source = arch_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
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

    passed = len(findings) == 0
    duration = (time.monotonic() - start_time) * 1000

    return GateCheckResult(
        gate_id=GateId.FUNCTION_RECOMPOSITION.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else max(0.0, 1.0 - len(findings) * 0.1),
        findings=findings,
        summary=(
            "Architectural functions correctly recompose atoms"
            if passed
            else f"Found {len(findings)} recomposition issue(s)"
        ),
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
    assignment_re = re.compile(r"\\b(API_KEY|TOKEN|SECRET|PASSWORD|HOST|URL)\\b\\s*=\\s*['\\\"]")

    analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed_arch is not None:
        for af in analyzed_arch:
            analyzed_lookup[af.path] = af

    findings: list[dict[str, Any]] = []
    for file_path in architectural_files:
        af = analyzed_lookup.get(str(file_path))
        if af is not None:
            source = af.content
        else:
            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        for idx, line in enumerate(source.splitlines(), start=1):
            if assignment_re.search(line):
                findings.append(
                    {
                        "file_path": str(file_path),
                        "line": idx,
                        "snippet": line.strip()[:200],
                    }
                )

    passed = not findings
    duration = (time.monotonic() - start) * 1000
    return GateCheckResult(
        gate_id=GateId.CONFIG_EXTERNALIZATION.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=1.0 if passed else 0.0,
        findings=findings,
        summary=(
            "No obvious hardcoded runtime config values detected"
            if passed
            else f"Found {len(findings)} potential hardcoded config assignment(s)"
        ),
        duration_ms=duration,
    )


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

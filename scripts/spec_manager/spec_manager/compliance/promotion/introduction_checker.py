# TODO(single-layer): RESTRUCTURE — "Introduced algorithm" concept changes. In multi-layer,
#   INTRODUCTION was a ProjectionType for arch-only code with no L1 atom origin. In
#   single-layer, all code is in one place — there's no "introduced without atom origin."
#   This check may survive as "does new code have a shape contract?" (NOT comment markers —
#   Section 8.1 replaces marker-based enforcement with external work items + shape verifiers).
#   Authority must come from shape ownership + verifier presence, not comment scanning.
#   The pin-coverage dependency (PinCoverageReport import) must be removed.
# IMPL(single-layer): Shape ownership resolution should reuse
# `routing.shapes.resolve_shape_for_file` to stay consistent with matcher/router routing.
# IMPL(single-layer): `Shape.status` is verifier-driven (`ACTIVE` iff verifiers exist);
# introduced behavior mapped to PROPOSAL shapes should emit actionable findings until
# verifier linkage is present.
# ALGORITHM(single-layer):
#   References: response3 Sections 8.1, 10.2, 13.3.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] — three-phase forward-only pipeline.
#     - IntroducedChange: {file_path: str, line_start: int, line_end: int, shape_id: ShapeId|None, has_contract: bool, has_verifier: bool, evidence_ref: str, rationale: str}.
#   Interface contracts:
#     - def find_uncontracted_introductions(changed_files: list[Path], shape_index: ShapePackIndex, verifier_summary: dict[ShapeId, VerifierRunSummary]) -> list[IntroducedChange]
#     - def check_introduced_algorithm_specs(...) -> GateCheckResult
#   Control flow:
#     1. Determine newly introduced code spans from deterministic diff metadata.
#     2. Resolve each changed file to owning shape.
#     3. Mark compliant only when owning shape has matching contract section and at least one relevant verifier.
#     4. Emit findings as work-item-ready diagnostics; do not scan for comment markers.
#     5. This check runs across Libraries and Architecture phases (both do work via PromotionLoop).
#     6. Three phases (Libraries -> Architecture -> Quality), forward-only; no cycling back.
#     7. Phase-local remediation if within authority; block if outside authority (no backtracking).
#   Error handling:
#     - Unknown owner shape or missing verifier summary => fail with actionable finding.
#     - LLM semantic classifier may assist categorization but never decides pass/fail.
#   Integration points:
#     - Called by behavior/architecture gate orchestration during Libraries and Architecture phases.
#     - Consumes routing.shapes and routing.verifiers outputs.
#   Test requirements:
#     - New code without shape contract fails.
#     - New code with contract + passing verifier passes.
#     - Comment marker presence/absence does not affect result.

"""Introduced algorithm spec checker for layer promotion gating."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.pin_coverage import PinCoverageReport
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.agent_utils import run_agent
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.formats import _strip_code_fences

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile


@dataclass
class IntroducedAlgorithm:
    """Semantic classification of one introduced changed span."""

    function_name: str
    file_path: str
    line_start: int
    line_end: int
    category: str = "unknown"
    requires_spec: bool = True
    has_spec: bool = False
    introduction_confidence: float = 0.0
    rationale: str = ""


def find_introduced_algorithms(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
    analyzed: list[AnalyzedFile] | None = None,
    *,
    semantic_agent: str = "pdd-code-analyzer",
    workspace: Path | None = None,
) -> list[IntroducedAlgorithm]:
    """Semantically classify introduced spans from pin coverage evidence."""
    introductions = [item for item in pin_coverage.items if item.is_introduction]
    if not introductions:
        return []

    analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed is not None:
        for af in analyzed:
            analyzed_lookup[_normalize_path(af.path)] = af

    arch_lookup = {_normalize_path(path): path for path in architectural_files}
    ws = workspace or Path.cwd()

    results: list[IntroducedAlgorithm] = []
    for item in introductions:
        file_key = _normalize_path(item.arch_file_path)
        source_text = _extract_span_text(
            file_key=file_key,
            line_start=item.arch_line,
            line_end=item.arch_line_end,
            analyzed_lookup=analyzed_lookup,
            arch_lookup=arch_lookup,
        )
        if not source_text:
            results.append(
                IntroducedAlgorithm(
                    function_name=item.arch_location,
                    file_path=file_key,
                    line_start=item.arch_line,
                    line_end=item.arch_line_end,
                    introduction_confidence=0.0,
                    rationale="Unable to read source span for semantic classification",
                )
            )
            continue

        payload = _semantic_introduction_assessment(
            agent_name=semantic_agent,
            workspace=ws,
            file_path=file_key,
            line_start=item.arch_line,
            line_end=item.arch_line_end,
            span_text=source_text,
        )

        if payload is None:
            results.append(
                IntroducedAlgorithm(
                    function_name=item.arch_location,
                    file_path=file_key,
                    line_start=item.arch_line,
                    line_end=item.arch_line_end,
                    introduction_confidence=0.0,
                    rationale="Semantic classifier returned invalid output",
                )
            )
            continue

        results.append(
            IntroducedAlgorithm(
                function_name=str(payload.get("function_name") or item.arch_location).strip(),
                file_path=file_key,
                line_start=item.arch_line,
                line_end=item.arch_line_end,
                category=str(payload.get("category") or "unknown").strip() or "unknown",
                requires_spec=bool(payload.get("requires_spec", True)),
                has_spec=bool(payload.get("has_spec", False)),
                introduction_confidence=_coerce_confidence(payload.get("confidence", 0.0)),
                rationale=str(payload.get("rationale") or "").strip(),
            )
        )

    return results


def check_introduced_algorithm_specs(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: introduced algorithm spans require semantic spec coverage."""
    start = time.monotonic()
    confidence_threshold = float(gate_spec.params.get("introduction_confidence_threshold", 0.75))
    semantic_agent = str(gate_spec.params.get("semantic_agent", "pdd-code-analyzer"))
    workspace = Path(str(gate_spec.params.get("workspace", ".")).strip() or ".")

    introduced = find_introduced_algorithms(
        pin_coverage,
        architectural_files,
        analyzed=analyzed,
        semantic_agent=semantic_agent,
        workspace=workspace,
    )

    strict_findings: list[dict[str, Any]] = []
    uncertain_findings: list[dict[str, Any]] = []

    for algo in introduced:
        payload = {
            "function_name": algo.function_name,
            "file_path": algo.file_path,
            "line_start": algo.line_start,
            "line_end": algo.line_end,
            "category": algo.category,
            "requires_spec": algo.requires_spec,
            "has_spec": algo.has_spec,
            "introduction_confidence": algo.introduction_confidence,
            "rationale": algo.rationale,
        }

        if algo.introduction_confidence < confidence_threshold:
            uncertain_findings.append(payload)
            continue

        if algo.requires_spec and not algo.has_spec:
            strict_findings.append(payload)

    if strict_findings:
        status = GateStatus.FAILED
    elif uncertain_findings:
        status = GateStatus.AMBIGUOUS
    else:
        status = GateStatus.PASSED

    findings: list[dict[str, Any]] = []
    if strict_findings:
        findings.append({"violations": strict_findings})
    if uncertain_findings:
        findings.append({"uncertain_introductions": uncertain_findings})

    confident_required = [
        algo
        for algo in introduced
        if algo.introduction_confidence >= confidence_threshold and algo.requires_spec
    ]
    confident_compliant = [algo for algo in confident_required if algo.has_spec]
    score = len(confident_compliant) / len(confident_required) if confident_required else 1.0

    duration = (time.monotonic() - start) * 1000

    if status == GateStatus.PASSED:
        summary = (
            f"All {len(confident_required)} confidently classified introduced span(s) have specs"
        )
    elif status == GateStatus.AMBIGUOUS:
        summary = (
            "Introduction classification is uncertain for some changed spans; "
            "manual review required before strict enforcement"
        )
    else:
        summary = f"{len(strict_findings)} introduced span(s) are missing semantic spec coverage"

    return GateCheckResult(
        gate_id=GateId.INTRODUCED_ALGORITHM_SPECS.value,
        mode=gate_spec.mode.value,
        status=status,
        score=score,
        findings=findings,
        summary=summary,
        duration_ms=duration,
    )


def _semantic_introduction_assessment(
    *,
    agent_name: str,
    workspace: Path,
    file_path: str,
    line_start: int,
    line_end: int,
    span_text: str,
) -> dict[str, Any] | None:
    prompt = (
        "Classify whether this changed span introduces algorithm/spec-level behavior and "
        "whether local spec documentation is present. Return JSON only with keys: "
        "function_name, category, requires_spec, has_spec, confidence, rationale.\n\n"
        f"Location: {file_path}:{line_start}-{line_end}\n"
        "Changed span:\n"
        "```\n"
        f"{span_text[:7000]}\n"
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


def _extract_span_text(
    *,
    file_key: str,
    line_start: int,
    line_end: int,
    analyzed_lookup: dict[str, AnalyzedFile],
    arch_lookup: dict[str, Path],
) -> str:
    analyzed = analyzed_lookup.get(file_key)
    if analyzed is not None:
        lines = analyzed.content.splitlines()
        return _slice_lines(lines, line_start, line_end)

    path = arch_lookup.get(file_key, Path(file_key))
    if not path.exists() or not path.is_file():
        return ""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""

    return _slice_lines(lines, line_start, line_end)


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    if start_line <= 0:
        return ""
    effective_end = max(start_line, end_line)
    lower = max(0, start_line - 1)
    upper = min(len(lines), effective_end)
    return "\n".join(lines[lower:upper]).strip()


def _normalize_path(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))

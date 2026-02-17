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
from typing import Any

from spec_manager.compliance.promotion.config import GateId, GateSpec, PhaseId
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus

# IMPL(single-layer): Section 13.3 keeps LLM outputs diagnostic-only in this module.
# Any `run_agent` output may assist routing hints but must not determine hard pass/fail.
from spec_manager.core.agent_utils import run_agent
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.formats import _strip_code_fences

# IMPL(single-layer): Section 10.2 retires PIN_* authority; migrate this module from
# pin-coverage span sourcing to deterministic diff spans + shape/verifier context.
from spec_manager.routing.shapes import ShapeId, ShapePackIndex, resolve_shape_for_file
from spec_manager.routing.verifiers import VerifierRunSummary


# IMPL(single-layer): Converge this payload with ALGORITHM `IntroducedChange`
# (`shape_id`, `has_contract`, `has_verifier`, `evidence_ref`) so findings map directly
# to external work-item routing fields from Section 8.1.
@dataclass
class IntroducedChange:
    """Deterministic introduced-span record used for shape-verifier routing."""

    file_path: str
    line_start: int
    line_end: int
    shape_id: ShapeId | None
    has_contract: bool
    has_verifier: bool
    evidence_ref: str
    rationale: str


_ALLOWED_PHASES: tuple[PhaseId, PhaseId] = ("libraries", "architecture")


# IMPL(single-layer): Replace this pin-centric helper with
# `find_uncontracted_introductions(changed_files, shape_index, verifier_summary)`.
# Ownership must resolve via `routing.shapes.resolve_shape_for_file`; introduction spans
# should come from deterministic diff metadata, not projection/pin evidence.
def find_uncontracted_introductions(
    changed_files: list[Path],
    shape_index: ShapePackIndex,
    verifier_summary: dict[ShapeId, VerifierRunSummary],
) -> list[IntroducedChange]:
    """Detect changed spans and map them to shape contract/verifier authority state."""
    introductions: list[IntroducedChange] = []
    for raw_file in changed_files:
        file_path = str(raw_file)
        lookup_path = _normalize_path(raw_file)
        if not lookup_path:
            continue

        spans = _resolve_changed_spans(raw_file)
        if not spans:
            spans = [(0, 0)]

        shape_id = _resolve_shape_for_changed_file(lookup_path, shape_index)
        if shape_id is None:
            for line_start, line_end in spans:
                introductions.append(
                    IntroducedChange(
                        file_path=file_path,
                        line_start=line_start,
                        line_end=line_end,
                        shape_id=None,
                        has_contract=False,
                        has_verifier=False,
                        evidence_ref=f"unowned-shape:{file_path}:{line_start}-{line_end}",
                        rationale=f"No owning shape found for changed file '{file_path}'.",
                    )
                )
            continue

        shape = shape_index.shapes.get(shape_id)
        has_contract, has_verifier, rationale, evidence_ref = _assess_shape_compliance(
            shape_id=shape_id,
            shape=shape,
            verifier_summary=verifier_summary,
        )
        for line_start, line_end in spans:
            span_rationale = rationale
            if not has_contract:
                span_rationale = (
                    f"{rationale} Missing contract ownership on shape '{shape_id}'."
                    if rationale
                    else f"Shape '{shape_id}' is missing contract ownership."
                )
            introductions.append(
                IntroducedChange(
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_end,
                    shape_id=shape_id,
                    has_contract=has_contract,
                    has_verifier=has_verifier,
                    evidence_ref=evidence_ref,
                    rationale=span_rationale,
                )
            )

    return introductions


def check_introduced_algorithm_specs(
    changed_files: list[Path],
    shape_index: ShapePackIndex,
    verifier_summary: dict[ShapeId, VerifierRunSummary],
    gate_spec: GateSpec,
    *,
    workspace: Path | None = None,
    semantic_agent: str = "pdd-code-analyzer",
    active_phase: PhaseId | None = None,
) -> GateCheckResult:
    """Gate: introduced code must be backed by shape contract and verifier linkage."""
    start = time.monotonic()

    # IMPL(single-layer): Keep PhaseId imported for routing table alignment and
    # phase-local authority checks in phase-local promotion steps.
    if active_phase is not None and active_phase not in _ALLOWED_PHASES:
        duration_ms = (time.monotonic() - start) * 1000
        return GateCheckResult(
            gate_id=GateId.INTRODUCED_ALGORITHM_SPECS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.FAILED,
            score=0.0,
            findings=[
                {
                    "shape_id": None,
                    "required_change_type": "phase_scope",
                    "rationale": (
                        f"INTRODUCED_ALGORITHM_SPECS is not authoritative in phase '{active_phase}'."
                    ),
                    "evidence_ref": f"phase:{active_phase}",
                }
            ],
            summary=(
                f"Introduction check is phase-local and does not execute in phase '{active_phase}'."
            ),
            duration_ms=duration_ms,
            evidence_refs=[f"phase:{active_phase}"],
        )

    introduced = find_uncontracted_introductions(changed_files, shape_index, verifier_summary)

    findings: list[dict[str, Any]] = []
    ws = workspace or Path.cwd()
    for change in introduced:
        if change.has_contract and change.has_verifier:
            continue

        finding: dict[str, Any] = {
            "file_path": change.file_path,
            "line_start": change.line_start,
            "line_end": change.line_end,
            "shape_id": str(change.shape_id) if change.shape_id else None,
            "has_contract": change.has_contract,
            "has_verifier": change.has_verifier,
            "evidence_ref": change.evidence_ref,
            "rationale": change.rationale,
            "required_change_type": "spec_change",
        }
        if change.line_start > 0 and change.line_end >= change.line_start:
            snippet = _extract_span_text(
                file_path=change.file_path,
                line_start=change.line_start,
                line_end=change.line_end,
            )
            payload = _semantic_introduction_assessment(
                agent_name=semantic_agent,
                workspace=ws,
                file_path=change.file_path,
                line_start=change.line_start,
                line_end=change.line_end,
                span_text=snippet,
            )
            if isinstance(payload, dict):
                if rationale := payload.get("rationale"):
                    finding["llm_rationale"] = str(rationale)
                if category := payload.get("category"):
                    finding["likely_category"] = str(category)
        findings.append(finding)

    duration_ms = (time.monotonic() - start) * 1000
    if not findings:
        return GateCheckResult(
            gate_id=GateId.INTRODUCED_ALGORITHM_SPECS.value,
            mode=gate_spec.mode.value,
            status=GateStatus.PASSED,
            score=1.0,
            findings=[],
            summary=(
                f"No uncontracted introduced spans found in {len(introduced)} "
                "deterministic change span(s)."
            ),
            duration_ms=duration_ms,
            evidence_refs=[f"introduced-change-count:{len(introduced)}"],
        )

    return GateCheckResult(
        gate_id=GateId.INTRODUCED_ALGORITHM_SPECS.value,
        mode=gate_spec.mode.value,
        status=GateStatus.FAILED,
        score=0.0,
        findings=findings,
        summary=f"{len(findings)} introduced span(s) require contract + verifier action",
        duration_ms=duration_ms,
        evidence_refs=[f"introduced-change-count:{len(introduced)}"],
    )


def _assess_shape_compliance(
    shape_id: ShapeId,
    shape: Any,
    verifier_summary: dict[ShapeId, VerifierRunSummary],
) -> tuple[bool, bool, str, str]:
    if shape is None:
        return False, False, f"Resolved shape '{shape_id}' is missing from shape pack.", ""

    has_contract = bool(getattr(shape, "contracts", None))
    source_ref = _shape_source_ref(shape)
    status = str(getattr(shape, "status", "")).strip().lower()
    if status != "active":
        return (
            has_contract,
            False,
            f"Shape '{shape_id}' is not ACTIVE for verifier-backed authority.",
            source_ref,
        )

    summary = verifier_summary.get(shape_id)
    if summary is None:
        return (
            has_contract,
            False,
            f"No verifier summary available for ACTIVE shape '{shape_id}'.",
            source_ref,
        )

    evidence_ref = _first_evidence_ref(shape, summary)
    if summary.non_ship_block:
        reasons = ", ".join(sorted(set(summary.missing_required)))
        reasons = reasons or "non_ship_block"
        return (
            has_contract,
            False,
            f"ACTIVE shape '{shape_id}' is blocked by verifier policy: {reasons!s}.",
            evidence_ref,
        )
    if summary.missing_required:
        reason = ", ".join(sorted(set(summary.missing_required)))
        return (
            has_contract,
            False,
            f"ACTIVE shape '{shape_id}' is missing required verifiers: {reason}.",
            evidence_ref,
        )
    if not summary.all_passed:
        return (
            has_contract,
            False,
            f"ACTIVE shape '{shape_id}' has failing verifier results.",
            evidence_ref,
        )
    if not any(result.passed for result in summary.results):
        return (
            has_contract,
            False,
            f"ACTIVE shape '{shape_id}' has no passing verifier results.",
            evidence_ref,
        )

    return has_contract, True, "", evidence_ref


def _shape_source_ref(shape: Any) -> str:
    if shape is None:
        return ""
    return str(getattr(shape, "source_path", "")).strip() or str(
        getattr(shape, "shape_id", "")
    ).strip()


def _first_evidence_ref(shape: Any, summary: VerifierRunSummary) -> str:
    refs: list[str] = []
    for result in summary.results:
        refs.extend(str(item) for item in (result.evidence_refs or []) if str(item).strip())
    if not refs:
        for item in summary.missing_required:
            item_text = str(item).strip()
            if item_text:
                refs.append(item_text)
    if shape is not None:
        source_ref = str(getattr(shape, "source_path", "")).strip()
        if source_ref:
            refs.append(source_ref)
    return refs[0] if refs else ""


def _resolve_shape_for_changed_file(file_path: str, shape_index: ShapePackIndex) -> ShapeId | None:
    for candidate in _shape_path_candidates(file_path):
        shape_id = resolve_shape_for_file(candidate, shape_index)
        if shape_id is not None:
            return shape_id
    return None


def _shape_path_candidates(file_path: str) -> list[str]:
    candidate = _normalize_path(file_path)
    if not candidate:
        return []
    parts = [part for part in candidate.split("/") if part]
    candidates: list[str] = [candidate]
    for idx in range(1, len(parts)):
        suffix = "/".join(parts[idx:])
        if suffix and suffix not in candidates:
            candidates.append(suffix)
    return candidates


def _resolve_changed_spans(raw_file: Path) -> list[tuple[int, int]]:
    path = Path(raw_file)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    if not lines:
        return []
    return [(1, len(lines))]


def _semantic_introduction_assessment(
    *,
    agent_name: str,
    workspace: Path,
    file_path: str,
    line_start: int,
    line_end: int,
    span_text: str,
) -> dict[str, Any] | None:
    # IMPL(single-layer): Keep semantic classification optional; outputs from this helper
    # may annotate rationale/category but must never be the deciding authority for gate status.
    prompt = (
        "Classify whether this changed span appears to require spec-level remediation and "
        "whether existing shape contracts likely cover it. Return JSON only with keys: "
        "category, rationale, requires_spec, confidence.\n\n"
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
    file_path: str,
    line_start: int,
    line_end: int,
) -> str:
    path = Path(file_path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    return _slice_lines(lines, line_start, line_end)


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    if start_line <= 0:
        return ""
    effective_start = max(1, start_line)
    effective_end = max(effective_start, end_line)
    lower = effective_start - 1
    upper = min(len(lines), effective_end)
    return "\n".join(lines[lower:upper]).strip()


def _normalize_path(path: str | Path) -> str:
    normalized = str(path).replace("\\", "/").lower().strip()
    if not normalized:
        return ""
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[2:]
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/"):
        normalized = normalized.lstrip("/")
    if normalized.startswith("workspace/"):
        normalized = normalized[len("workspace/") :]
    if normalized.startswith("runs/"):
        normalized = normalized[len("runs/") :]
    if normalized.startswith("routing/"):
        normalized = normalized[len("routing/") :]
    return normalized.rstrip("/")

"""Decision point detection from gaps, discovery, and evidence.

Uses an LLM call (via injectable ``run_agent``) to examine gaps, architecture
files, and evidence for a slice, then filters out points already covered by
existing authoritative constraints.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spec_manager.planner.constraints.types import ConstraintFact, ImpactClassification

from .types import DecisionPoint

logger = logging.getLogger(__name__)

_ALLOWED_IMPACT = {"LOW", "MEDIUM", "HIGH"}
_ALLOWED_BLAST_RADIUS = {"LOCAL", "SLICE", "CROSS_SLICE", "SYSTEM"}


class DetectionOutputError(ValueError):
    """Raised when decision-detection output cannot be trusted."""


class DecisionPointDetector:
    """Detects architecture decision points from slice context.

    Parameters
    ----------
    workspace_root:
        Root directory of the workspace.
    run_agent:
        Optional callable for LLM calls.  Signature:
        ``(prompt: str) -> str``.  When *None* the detector falls back
        to a heuristic-only mode.
    """

    def __init__(
        self,
        workspace_root: Path,
        run_agent: Callable[..., str] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._run_agent = run_agent

    def detect(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
        evidence_refs: list[str] | None = None,
        authoritative_constraints: list[ConstraintFact] | None = None,
    ) -> list[DecisionPoint]:
        """Detect decision points for a slice.

        Parameters
        ----------
        slice_id:
            Identifier of the slice being analysed.
        gaps:
            Gap analysis results for the slice.
        discovery:
            Discovery graph (nodes + edges) for the slice.
        evidence_refs:
            Optional evidence references to consider.
        authoritative_constraints:
            Existing constraints that may cover decisions.

        Returns
        -------
        list[DecisionPoint]
            Decision points that are NOT already covered.
        """
        if authoritative_constraints is None:
            authoritative_constraints = []
        if evidence_refs is None:
            evidence_refs = []

        raw_points = self._detect_raw(
            slice_id=slice_id,
            gaps=gaps,
            discovery=discovery,
            evidence_refs=evidence_refs,
        )

        return self._filter_decided(raw_points, authoritative_constraints)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _detect_raw(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
        evidence_refs: list[str],
    ) -> list[DecisionPoint]:
        """Produce raw (unfiltered) decision points."""
        if self._run_agent is not None:
            return self._detect_via_llm(
                slice_id=slice_id,
                gaps=gaps,
                discovery=discovery,
                evidence_refs=evidence_refs,
            )
        return self._detect_heuristic(
            slice_id=slice_id,
            gaps=gaps,
            discovery=discovery,
        )

    def _detect_via_llm(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
        evidence_refs: list[str],
    ) -> list[DecisionPoint]:
        """Use the LLM to identify decision points."""
        prompt = _build_detection_prompt(
            slice_id=slice_id,
            gaps=gaps,
            discovery=discovery,
            evidence_refs=evidence_refs,
        )

        assert self._run_agent is not None
        raw_output = self._run_agent(prompt)
        return _parse_detection_output(raw_output, slice_id)

    def _detect_heuristic(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> list[DecisionPoint]:
        """Fallback heuristic when no LLM is available.

        Creates one decision point per gap that mentions architecture
        keywords.
        """
        arch_keywords = {
            "architecture",
            "pattern",
            "design",
            "topology",
            "interface",
            "coupling",
            "dependency",
            "layer",
            "module",
            "component",
            "wiring",
            "wire",
            "pin",
            "event",
            "boundary",
        }
        points: list[DecisionPoint] = []

        for gap in gaps:
            description = str(gap.get("description", "")).strip()
            target = str(gap.get("target", "")).strip()
            desc = f"{description} {target}".strip()
            if any(kw in desc.lower() for kw in arch_keywords):
                scope = _derive_gap_scope(gap, default_library=slice_id)
                if not scope:
                    logger.debug("Skipping architecture gap with unresolved scope: %s", gap)
                    continue
                trigger_evidence = _coerce_trigger_evidence(gap.get("trigger_evidence"))
                if not trigger_evidence and target:
                    trigger_evidence = [target]
                point = DecisionPoint(
                    decision_id=f"DEC-{uuid.uuid4().hex[:8]}",
                    scope=scope,
                    description=description or target,
                    trigger_evidence=trigger_evidence,
                    impact=ImpactClassification(
                        impact="MEDIUM",
                        blast_radius="SLICE",
                    ),
                    owner_slice_id=slice_id,
                    status="OPEN",
                )
                points.append(point)

        return points

    def _filter_decided(
        self,
        points: list[DecisionPoint],
        authoritative_constraints: list[ConstraintFact],
    ) -> list[DecisionPoint]:
        """Remove points already covered by authoritative constraints."""
        if not authoritative_constraints:
            return list(points)

        decided_scopes: set[str] = set()
        decided_questions: set[str] = set()
        for c in authoritative_constraints:
            if c.status == "ACTIVE" and c.validated:
                decided_scopes.add(c.scope)
                decided_questions.add(c.question.lower())

        filtered: list[DecisionPoint] = []
        for point in points:
            if point.scope in decided_scopes and point.description.lower() in decided_questions:
                logger.debug(
                    "Filtering out decided point %s (covered by constraint)",
                    point.decision_id,
                )
                continue
            filtered.append(point)

        return filtered


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _build_detection_prompt(
    *,
    slice_id: str,
    gaps: list[dict[str, Any]],
    discovery: dict[str, Any],
    evidence_refs: list[str],
) -> str:
    """Build the LLM prompt for decision detection."""
    nodes_summary = []
    for node in discovery.get("nodes", []):
        nodes_summary.append(
            f"  - {node.get('kind', '?')}: {node.get('name', node.get('id', '?'))}"
        )
    nodes_text = "\n".join(nodes_summary) if nodes_summary else "  (none)"

    gaps_summary = []
    for gap in gaps:
        gaps_summary.append(f"  - {gap.get('target', '?')}: {gap.get('description', '')}")
    gaps_text = "\n".join(gaps_summary) if gaps_summary else "  (none)"

    evidence_text = (
        "\n".join(f"  - {ref}" for ref in evidence_refs) if evidence_refs else "  (none)"
    )

    return f"""Analyze the following slice for architecture decision points.

Slice ID: {slice_id}

Discovery nodes:
{nodes_text}

Gaps:
{gaps_text}

Evidence references:
{evidence_text}

Identify architecture decisions that need to be made. For each, provide:
- scope: the scope of the decision, using only:
  - intra:<LIB>
  - intra:<LIB>:<refinement>
  - inter:<LIB_A>-><LIB_B>:<interaction_handle>
  Inter scopes must include an evidence-backed interaction handle.
- description: what needs to be decided
- trigger_evidence: which evidence triggered this
- impact: LOW/MEDIUM/HIGH
- blast_radius: LOCAL/SLICE/CROSS_SLICE/SYSTEM

Return a JSON array of objects with keys: scope, description,
trigger_evidence (list), impact, blast_radius.
Return [] if no architecture decisions are needed.
"""


def _parse_detection_output(raw: str, slice_id: str) -> list[DecisionPoint]:
    """Parse LLM output into DecisionPoint instances.

    Raises
    ------
    DetectionOutputError
        If the response cannot be parsed into valid decision points.
    """
    try:
        text = raw.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            raise DetectionOutputError("LLM output did not contain a JSON array")
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise DetectionOutputError("Failed to parse decision detection JSON output") from exc

    points: list[DecisionPoint] = []
    if not isinstance(parsed, list):
        raise DetectionOutputError("Decision detection output must be a JSON array")

    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise DetectionOutputError(f"Decision item at index {index} is not an object")

        scope = _normalize_scope(item.get("scope"))
        if scope is None:
            raw_scope = str(item.get("scope", "")).strip()
            if not raw_scope:
                raise DetectionOutputError(f"Decision item at index {index} is missing scope")
            scope = f"unresolved:{raw_scope}"

        description = str(item.get("description", "")).strip()
        if not description:
            raise DetectionOutputError(f"Decision item at index {index} is missing description")

        impact = str(item.get("impact", "")).strip().upper()
        if impact not in _ALLOWED_IMPACT:
            raise DetectionOutputError(
                f"Decision item at index {index} has invalid impact: {item.get('impact')!r}"
            )
        blast_radius = str(item.get("blast_radius", "")).strip().upper()
        if blast_radius not in _ALLOWED_BLAST_RADIUS:
            raise DetectionOutputError(
                "Decision item at index "
                f"{index} has invalid blast_radius: {item.get('blast_radius')!r}"
            )

        point = DecisionPoint(
            decision_id=f"DEC-{uuid.uuid4().hex[:8]}",
            scope=scope,
            description=description,
            trigger_evidence=_coerce_trigger_evidence(item.get("trigger_evidence")),
            impact=ImpactClassification(
                impact=impact,
                blast_radius=blast_radius,
            ),
            owner_slice_id=slice_id,
            status="OPEN",
        )
        points.append(point)

    return points


def _derive_gap_scope(gap: dict[str, Any], *, default_library: str) -> str | None:
    del default_library  # Scope defaults are intentionally not inferred from slice IDs.

    raw_scope = str(gap.get("scope", "")).strip()
    if raw_scope:
        explicit_scope = _normalize_scope(raw_scope)
        if explicit_scope is not None:
            return explicit_scope
        return f"unresolved:{raw_scope}"

    inter_scope = _extract_inter_scope_from_gap(gap)
    if inter_scope is not None:
        return inter_scope

    library = ""
    for key in (
        "owner_slice_id",
        "slice_id",
        "library",
        "library_id",
        "lib_id",
        "lib",
        "component_id",
    ):
        library = _normalize_library(gap.get(key))
        if library:
            break
    if not library:
        target = str(gap.get("target", "")).strip()
        return f"unresolved:{target}" if target else None
    return f"intra:{library}"


def _extract_inter_scope_from_gap(gap: dict[str, Any]) -> str | None:
    lib_pairs = (
        ("source_library", "target_library"),
        ("producer_library", "consumer_library"),
        ("provider_library", "consumer_library"),
        ("from_library", "to_library"),
        ("source_lib", "target_lib"),
    )
    for source_key, target_key in lib_pairs:
        source_lib = _normalize_library(gap.get(source_key))
        target_lib = _normalize_library(gap.get(target_key))
        if not source_lib or not target_lib or source_lib == target_lib:
            continue
        handle = _extract_interaction_handle(gap)
        if handle:
            return f"inter:{source_lib}->{target_lib}:{handle}"
    return None


def _extract_interaction_handle(gap: dict[str, Any]) -> str:
    for key in (
        "interaction_handle",
        "event_name",
        "contract_name",
        "pin_mismatch",
        "pin_id",
        "pin_ref",
        "import_path",
        "import_symbol",
        "call_symbol",
        "call_name",
        "event",
        "contract",
    ):
        handle = _normalize_handle(gap.get(key))
        if handle:
            return handle
    return ""


def _coerce_trigger_evidence(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        refs = [str(item).strip() for item in value if str(item).strip()]
        # Preserve order, remove duplicates.
        deduped: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            deduped.append(ref)
        return deduped
    return []


def _normalize_scope(scope: Any) -> str | None:
    raw = str(scope or "").strip()
    if not raw:
        return None

    if raw.lower() == "system":
        return "system"

    lowered = raw.lower()

    if lowered.startswith("intra:"):
        intra_body = raw.split(":", 1)[1]
        return _normalize_intra_scope(intra_body)

    if lowered.startswith("inter:"):
        inter_body = raw.split(":", 1)[1]
        return _normalize_inter_scope(inter_body)

    return None


def _normalize_intra_scope(scope_body: str) -> str | None:
    body = str(scope_body).strip()
    if not body:
        return None
    segments = [segment.strip() for segment in body.split(":")]
    library = _normalize_library(segments[0] if segments else "")
    if not library:
        return None
    refinement = ":".join(segment for segment in segments[1:] if segment.strip())
    if not refinement:
        return f"intra:{library}"
    return f"intra:{library}:{refinement}"


def _normalize_inter_scope(scope_body: str) -> str | None:
    body = str(scope_body).strip()
    if "->" not in body:
        return None
    left, right = body.split("->", 1)
    source_lib = _normalize_library(left)
    if ":" not in right:
        return None
    right_lib, handle_value = right.split(":", 1)
    target_lib = _normalize_library(right_lib)
    handle = _normalize_handle(handle_value)
    if not source_lib or not target_lib or not handle:
        return None
    if source_lib == target_lib:
        return None
    return f"inter:{source_lib}->{target_lib}:{handle}"


def _normalize_library(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    token = text.replace("\\", "/")
    if token.lower().startswith("libraries/"):
        parts = [part for part in token.split("/") if part]
        if len(parts) >= 2:
            token = parts[1]
    elif "/" in token:
        token = token.rsplit("/", 1)[-1]
    token = token.strip()
    if not token:
        return ""
    lowered = token.lower()
    if lowered in {"lib", "library", "libraries", "unknown", "tbd"}:
        return ""
    return token


def _normalize_handle(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"interaction", "handle", "unknown", "tbd", "todo"}:
        return ""
    compact = re.sub(r"\s+", "_", text)
    compact = re.sub(r"[^A-Za-z0-9._:/#-]+", "_", compact)
    compact = compact.strip("._:/#-")
    return compact

"""Scorer for INTEGRATION_ANALYSIS decisions.

Evaluates whether the planner correctly identified integration risks
and dependency topology by comparing discovered risks/edges against
ground-truth must-include and must-not-include lists.
"""

from __future__ import annotations

from typing import Any

from spec_manager.refinement.evals.planner.scorers.base import Verdict


class IntegrationAnalysisScorer:
    """Scores INTEGRATION_ANALYSIS planner decisions.

    Ground-truth cases are expected to contain::

        expected:
          must_include_risks:
            - description: "circular dependency between module A and B"
            - description: "missing error handling on timeout"
          must_not_include_risks:
            - description: "deprecated API usage"
          must_include_edges:
            - source: "component_a"
              target: "component_b"
              kind: "depends_on"
          must_not_include_edges:
            - source: "component_a"
              target: "component_x"
          thresholds:
            risk_recall: 0.75
            risk_precision: 0.75
            edge_recall: 0.75
            edge_precision: 0.75
    """

    def score(self, trace: Any, gt_case: Any) -> Verdict:
        """Score a single INTEGRATION_ANALYSIS trace against ground truth.

        Args:
            trace: A LoadedTrace-like object with ``.artifacts`` and
                ``.decision`` dicts.
            gt_case: A GroundTruthCase-like object with an ``.expected`` dict.

        Returns:
            Verdict with score = min(overall_recall, overall_precision).
        """
        expected = getattr(gt_case, "expected", None)
        if expected is None:
            expected = {}
        if not isinstance(expected, dict):
            expected = {}
        thresholds = expected.get("thresholds", {})
        if not isinstance(thresholds, dict):
            thresholds = {}

        must_include_risks: list[dict[str, Any]] = expected.get("must_include_risks", [])
        must_not_include_risks: list[dict[str, Any]] = expected.get("must_not_include_risks", [])
        must_include_edges: list[dict[str, Any]] = expected.get("must_include_edges", [])
        must_not_include_edges: list[dict[str, Any]] = expected.get("must_not_include_edges", [])

        if (
            not must_include_risks
            and not must_not_include_risks
            and not must_include_edges
            and not must_not_include_edges
        ):
            return Verdict(
                capability="integration_analysis",
                passed=True,
                score=1.0,
                detail="No risk/edge expectations in ground truth; neutral verdict.",
            )

        # Extract discovery from trace.
        artifacts = getattr(trace, "artifacts", {}) or {}
        outputs = artifacts.get("outputs", {}) or {}
        discovery: dict[str, Any] = outputs.get("discovery", {}) or {}

        # Build flat lists for risk and dependency-edge matching.
        discovered_descriptions = _extract_risk_descriptions(discovery)
        discovered_edges = _extract_dependency_edges(discovery)

        hard_gate_failures: list[str] = []
        soft_signal_warnings: list[str] = []

        # ---- risk recall/precision ----
        must_include_matched = 0
        must_include_total = len(must_include_risks)
        for risk in must_include_risks:
            risk_desc = risk.get("description", "")
            if _risk_present(risk_desc, discovered_descriptions):
                must_include_matched += 1

        risk_recall = must_include_matched / must_include_total if must_include_total else 1.0

        must_not_violations = 0
        must_not_total = len(must_not_include_risks)
        for risk in must_not_include_risks:
            risk_desc = risk.get("description", "")
            if _risk_present(risk_desc, discovered_descriptions):
                must_not_violations += 1

        risk_precision = 1.0 - (must_not_violations / must_not_total) if must_not_total else 1.0

        # ---- edge recall/precision ----
        must_include_edges_matched = 0
        must_include_edges_total = len(must_include_edges)
        for edge in must_include_edges:
            if _edge_present(edge, discovered_edges):
                must_include_edges_matched += 1

        edge_recall = (
            must_include_edges_matched / must_include_edges_total
            if must_include_edges_total
            else 1.0
        )

        must_not_edge_violations = 0
        must_not_edges_total = len(must_not_include_edges)
        for edge in must_not_include_edges:
            if _edge_present(edge, discovered_edges):
                must_not_edge_violations += 1

        edge_precision = (
            1.0 - (must_not_edge_violations / must_not_edges_total) if must_not_edges_total else 1.0
        )

        overall_recall = _mean([risk_recall, edge_recall])
        overall_precision = _mean([risk_precision, edge_precision])

        # ---- threshold gates ----
        risk_recall_threshold = _resolve_threshold(
            gt_case,
            thresholds=thresholds,
            expected_keys=("risk_recall", "recall"),
            rubric_keys=("risk_recall", "must_include_recall", "recall"),
            default=0.75,
        )
        risk_precision_threshold = _resolve_threshold(
            gt_case,
            thresholds=thresholds,
            expected_keys=("risk_precision", "precision"),
            rubric_keys=("risk_precision", "must_not_include_precision", "precision"),
            default=0.75,
        )
        edge_recall_threshold = _resolve_threshold(
            gt_case,
            thresholds=thresholds,
            expected_keys=("edge_recall", "dependency_edge_recall", "recall"),
            rubric_keys=("edge_recall", "dependency_edge_recall", "recall"),
            default=0.75,
        )
        edge_precision_threshold = _resolve_threshold(
            gt_case,
            thresholds=thresholds,
            expected_keys=("edge_precision", "dependency_edge_precision", "precision"),
            rubric_keys=("edge_precision", "dependency_edge_precision", "precision"),
            default=0.75,
        )

        if risk_recall < risk_recall_threshold:
            hard_gate_failures.append(
                f"risk_recall_below_threshold({risk_recall:.2f}<{risk_recall_threshold})"
            )
        if risk_precision < risk_precision_threshold:
            hard_gate_failures.append(
                f"risk_precision_below_threshold({risk_precision:.2f}<{risk_precision_threshold})"
            )
        if edge_recall < edge_recall_threshold:
            hard_gate_failures.append(
                f"edge_recall_below_threshold({edge_recall:.2f}<{edge_recall_threshold})"
            )
        if edge_precision < edge_precision_threshold:
            hard_gate_failures.append(
                f"edge_precision_below_threshold({edge_precision:.2f}<{edge_precision_threshold})"
            )

        score = min(overall_recall, overall_precision)
        passed = len(hard_gate_failures) == 0

        detail = (
            f"risk_recall={risk_recall:.2f} ({must_include_matched}/{must_include_total}), "
            f"risk_precision={risk_precision:.2f} "
            f"({must_not_total - must_not_violations}/{max(1, must_not_total)} clean), "
            f"edge_recall={edge_recall:.2f} "
            f"({must_include_edges_matched}/{must_include_edges_total}), "
            f"edge_precision={edge_precision:.2f} "
            f"({must_not_edges_total - must_not_edge_violations}/"
            f"{max(1, must_not_edges_total)} clean), "
            f"overall_recall={overall_recall:.2f}, "
            f"overall_precision={overall_precision:.2f}, "
            f"discovered_risks={len(discovered_descriptions)}, "
            f"discovered_edges={len(discovered_edges)}"
        )

        return Verdict(
            capability="integration_analysis",
            passed=passed,
            score=score,
            detail=detail,
            hard_gate_failures=hard_gate_failures,
            soft_signal_warnings=soft_signal_warnings,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _extract_risk_descriptions(discovery: dict[str, Any]) -> list[str]:
    """Extract a flat list of risk description strings from a discovery dict.

    The discovery dict may have various shapes. We look for:
    - ``discovery["risks"]`` as a list of dicts with "description"
    - ``discovery["risks"]`` as a list of strings
    - ``discovery`` values that are themselves lists of risk dicts
    - Flat string values in discovery

    Returns:
        List of lowercase description strings for matching.
    """
    descriptions: list[str] = []

    # Direct "risks" key.
    risks = discovery.get("risks", [])
    if isinstance(risks, list):
        for item in risks:
            if isinstance(item, dict):
                desc = item.get("description", "")
                if desc:
                    descriptions.append(str(desc).lower())
            elif isinstance(item, str):
                descriptions.append(item.lower())

    # Also scan all top-level values that are lists of dicts.
    for key, value in discovery.items():
        if key == "risks":
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    desc = item.get("description", "")
                    if desc:
                        descriptions.append(str(desc).lower())
        elif isinstance(value, str) and value:
            descriptions.append(value.lower())

    return descriptions


def _risk_present(risk_description: str, discovered_descriptions: list[str]) -> bool:
    """Check if a risk description is present in discovered descriptions.

    Uses case-insensitive substring matching: the risk is considered
    present if its description appears as a substring in any discovered
    description, or vice versa.

    Args:
        risk_description: Ground-truth risk description.
        discovered_descriptions: List of lowercase discovered descriptions.

    Returns:
        True if the risk is found.
    """
    if not risk_description:
        return False

    needle = risk_description.lower()

    return any(needle in desc or desc in needle for desc in discovered_descriptions)


def _extract_dependency_edges(discovery: dict[str, Any]) -> list[dict[str, str]]:
    """Extract normalized dependency-edge descriptors from discovery."""
    edges: list[dict[str, str]] = []

    def _append_edge(item: Any) -> None:
        if isinstance(item, str) and item.strip():
            edges.append(
                {"source": "", "target": "", "kind": "", "description": item.strip().lower()}
            )
            return
        if not isinstance(item, dict):
            return

        source = (
            str(item.get("source") or item.get("from") or item.get("src") or "").strip().lower()
        )
        target = str(item.get("target") or item.get("to") or item.get("dst") or "").strip().lower()
        kind = (
            str(item.get("kind") or item.get("type") or item.get("relation") or "").strip().lower()
        )
        description = str(item.get("description") or item.get("summary") or "").strip().lower()
        if source or target or kind or description:
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "kind": kind,
                    "description": description,
                }
            )

    def _consume(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                _append_edge(item)
            return
        if isinstance(value, dict):
            # Dict may itself be an edge object or may contain edge collections.
            _append_edge(value)
            for nested_key in ("edges", "dependency_edges", "dependencies"):
                nested_value = value.get(nested_key)
                if nested_value is not None:
                    _consume(nested_value)

    for key in ("edges", "dependency_edges", "dependencies"):
        _consume(discovery.get(key))
    for value in discovery.values():
        _consume(value)

    return edges


def _edge_present(edge_spec: dict[str, Any], discovered_edges: list[dict[str, str]]) -> bool:
    """Check whether an expected dependency edge is present in discovered topology."""
    if not edge_spec:
        return False

    spec_source = str(edge_spec.get("source") or edge_spec.get("from") or "").strip().lower()
    spec_target = str(edge_spec.get("target") or edge_spec.get("to") or "").strip().lower()
    spec_kind = str(edge_spec.get("kind") or edge_spec.get("type") or "").strip().lower()
    spec_description = str(edge_spec.get("description") or "").strip().lower()

    for edge in discovered_edges:
        edge_text = _edge_text(edge)
        if spec_description and not (
            spec_description in edge_text or edge_text in spec_description
        ):
            continue
        if spec_source and spec_source != edge.get("source", ""):
            continue
        if spec_target and spec_target != edge.get("target", ""):
            continue
        if spec_kind and spec_kind != edge.get("kind", ""):
            continue
        if spec_source or spec_target or spec_kind or spec_description:
            return True
    return False


def _edge_text(edge: dict[str, str]) -> str:
    """Build a comparable text form of an edge."""
    return " ".join(
        part
        for part in (
            edge.get("source", ""),
            edge.get("target", ""),
            edge.get("kind", ""),
            edge.get("description", ""),
        )
        if part
    )


def _resolve_threshold(
    gt_case: Any,
    *,
    thresholds: dict[str, Any],
    expected_keys: tuple[str, ...],
    rubric_keys: tuple[str, ...],
    default: float,
) -> float:
    """Resolve threshold from expected thresholds, rubric hard gates, or default."""
    for key in expected_keys:
        if key in thresholds:
            return _coerce_float(thresholds.get(key), default)

    rubric = getattr(gt_case, "rubric", None)
    hard_gates = getattr(rubric, "hard_gates", []) if rubric is not None else []
    normalized_keys = {k.lower() for k in rubric_keys}
    for gate in hard_gates:
        metric = str(getattr(gate, "metric", "") or "").lower()
        if metric in normalized_keys:
            return _coerce_float(getattr(gate, "threshold", default), default)
    return default


def _coerce_float(value: Any, default: float) -> float:
    """Best-effort float conversion with default fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: list[float]) -> float:
    """Return the arithmetic mean for non-empty *values*."""
    return sum(values) / len(values) if values else 0.0

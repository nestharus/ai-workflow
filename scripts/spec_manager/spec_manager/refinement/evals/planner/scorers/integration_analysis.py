"""Scorer for INTEGRATION_ANALYSIS decisions.

Evaluates whether the planner correctly identified integration risks
by comparing discovered risks against ground-truth must-include and
must-not-include risk lists using substring matching.
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
    """

    def score(self, trace: Any, gt_case: Any) -> Verdict:
        """Score a single INTEGRATION_ANALYSIS trace against ground truth.

        Args:
            trace: A LoadedTrace-like object with ``.artifacts`` and
                ``.decision`` dicts.
            gt_case: A GroundTruthCase-like object with an ``.expected`` dict.

        Returns:
            Verdict with score = min(recall, precision).
        """
        expected = getattr(gt_case, "expected", None)
        if expected is None:
            expected = {}
        if not isinstance(expected, dict):
            expected = {}

        must_include_risks: list[dict[str, Any]] = expected.get("must_include_risks", [])
        must_not_include_risks: list[dict[str, Any]] = expected.get("must_not_include_risks", [])

        if not must_include_risks and not must_not_include_risks:
            return Verdict(
                capability="integration_analysis",
                passed=True,
                score=1.0,
                detail="No risk expectations in ground truth; neutral verdict.",
            )

        # Extract discovery from trace.
        artifacts = getattr(trace, "artifacts", {}) or {}
        outputs = artifacts.get("outputs", {}) or {}
        discovery: dict[str, Any] = outputs.get("discovery", {}) or {}

        # Build a flat list of discovered risk descriptions for matching.
        discovered_descriptions = _extract_risk_descriptions(discovery)

        hard_gate_failures: list[str] = []
        soft_signal_warnings: list[str] = []

        # ---- must_include recall ----
        must_include_matched = 0
        must_include_total = len(must_include_risks)
        for risk in must_include_risks:
            risk_desc = risk.get("description", "")
            if _risk_present(risk_desc, discovered_descriptions):
                must_include_matched += 1

        recall = (
            must_include_matched / must_include_total
            if must_include_total
            else 1.0
        )

        # ---- must_not_include precision ----
        must_not_violations = 0
        must_not_total = len(must_not_include_risks)
        for risk in must_not_include_risks:
            risk_desc = risk.get("description", "")
            if _risk_present(risk_desc, discovered_descriptions):
                must_not_violations += 1

        precision = (
            1.0 - (must_not_violations / must_not_total)
            if must_not_total
            else 1.0
        )

        score = min(recall, precision)
        passed = len(hard_gate_failures) == 0

        detail = (
            f"recall={recall:.2f} ({must_include_matched}/{must_include_total}), "
            f"precision={precision:.2f} "
            f"({must_not_total - must_not_violations}/{max(1, must_not_total)} clean), "
            f"discovered_risks={len(discovered_descriptions)}"
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

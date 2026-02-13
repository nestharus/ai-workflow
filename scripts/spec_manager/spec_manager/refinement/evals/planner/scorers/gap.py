"""Scorer for GAP decisions.

Evaluates whether the planner correctly identified specification and code
gaps by comparing discovered gaps against ground-truth ``must_find`` and
``must_not_find`` atom lists.  Ground truth is constraint-based (gap atoms
+ optional clustering constraints), NOT a full clustering tree.

Correct means: high recall on ``must_find``, low false positives on
``must_not_find``.
"""

from __future__ import annotations

from typing import Any

from spec_manager.refinement.evals.planner.scorers.base import Verdict, _matches_atom


class GapScorer:
    """Scores GAP planner decisions.

    Ground-truth cases are expected to contain::

        expected:
          must_find:
            - id: "gap_001"
              match: {description_contains: "missing validation", ...}
            - id: "gap_002"
              match: {function_name_any_of: [...], ...}
          must_not_find:
            - id: "fp_001"
              match: {description_contains: "deprecated API", ...}
          thresholds:
            recall: 0.75
    """

    capability = "GAP"

    def score(self, trace: Any, gt_case: Any) -> Verdict:
        """Score a single GAP trace against ground truth.

        Args:
            trace: A LoadedTrace-like object with ``.artifacts`` and
                ``.decision`` dicts.
            gt_case: A GroundTruthCase-like object with an ``.expected`` dict.

        Returns:
            Verdict with score = F1(recall, precision), hard-gate failures
            when recall is below threshold or must_not_find atoms are matched.
        """
        expected = getattr(gt_case, "expected", None)
        if expected is None:
            expected = {}
        if not isinstance(expected, dict):
            expected = {}

        must_find: list[dict[str, Any]] = expected.get("must_find", [])
        must_not_find: list[dict[str, Any]] = expected.get("must_not_find", [])
        thresholds: dict[str, float] = expected.get("thresholds", {})

        if not must_find and not must_not_find:
            return Verdict(
                capability="gap",
                passed=True,
                score=1.0,
                detail="No gap expectations in ground truth; neutral verdict.",
            )

        # Extract gaps from the trace outputs.
        artifacts = getattr(trace, "artifacts", {}) or {}
        outputs = artifacts.get("outputs", {}) or {}
        gaps = _extract_gaps(outputs)

        hard_gate_failures: list[str] = []
        soft_signal_warnings: list[str] = []

        # ---- must_find recall ----
        must_find_matched = 0
        must_find_total = len(must_find)
        for atom in must_find:
            match_spec = atom.get("match", {})
            if any(_matches_gap(gap, match_spec) for gap in gaps):
                must_find_matched += 1

        recall = must_find_matched / must_find_total if must_find_total else 1.0

        # ---- must_not_find precision ----
        must_not_violations = 0
        violation_ids: list[str] = []
        for atom in must_not_find:
            match_spec = atom.get("match", {})
            if any(_matches_gap(gap, match_spec) for gap in gaps):
                must_not_violations += 1
                violation_ids.append(atom.get("id", "?"))

        # Precision: proportion of found gaps that are NOT false positives.
        # If no gaps found, precision is 1.0 (no false positives possible).
        total_gaps_found = len(gaps)
        precision = 1.0 - (must_not_violations / total_gaps_found) if total_gaps_found > 0 else 1.0

        # Clamp precision to [0.0, 1.0] in case must_not_violations > total_gaps_found
        precision = max(0.0, min(1.0, precision))

        # ---- F1 ----
        f1 = 2.0 * (recall * precision) / (recall + precision) if recall + precision > 0 else 0.0

        # ---- threshold gates ----
        recall_threshold = thresholds.get("recall", 0.75)
        if recall < recall_threshold:
            hard_gate_failures.append(f"recall_below_threshold({recall:.2f}<{recall_threshold})")

        if must_not_violations > 0:
            hard_gate_failures.append(
                f"must_not_find_matched({must_not_violations}: {', '.join(violation_ids)})"
            )

        passed = len(hard_gate_failures) == 0
        score = f1

        detail_parts: list[str] = [
            f"recall={recall:.2f} ({must_find_matched}/{must_find_total})",
            f"precision={precision:.2f}",
            f"f1={f1:.2f}",
            f"gaps_found={total_gaps_found}",
        ]
        if must_not_violations:
            detail_parts.append(f"must_not_find_violations={must_not_violations}")
        if hard_gate_failures:
            detail_parts.append(f"hard_gate_failures={hard_gate_failures}")
        if soft_signal_warnings:
            detail_parts.append(f"warnings={soft_signal_warnings}")

        return Verdict(
            capability="gap",
            passed=passed,
            score=score,
            detail="; ".join(detail_parts),
            hard_gate_failures=hard_gate_failures,
            soft_signal_warnings=soft_signal_warnings,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _extract_gaps(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a flat list of gap dicts from planner outputs.

    The outputs dict may have various shapes:
    - ``outputs["gaps"]`` as a list of dicts
    - ``outputs["discovery"]`` containing gap sub-keys
    - ``outputs["discovery"]["gaps"]`` as a list
    - Gap dicts nested under ``outputs["discovery"]`` values

    Returns:
        List of gap dictionaries suitable for matching.
    """
    gaps: list[dict[str, Any]] = []

    # Direct "gaps" key.
    raw_gaps = outputs.get("gaps", [])
    if isinstance(raw_gaps, list):
        for item in raw_gaps:
            if isinstance(item, dict):
                gaps.append(item)
            elif isinstance(item, str):
                gaps.append({"description": item})

    # Discovery sub-dict.
    discovery = outputs.get("discovery", {})
    if isinstance(discovery, dict):
        # discovery["gaps"]
        disc_gaps = discovery.get("gaps", [])
        if isinstance(disc_gaps, list):
            for item in disc_gaps:
                if isinstance(item, dict):
                    gaps.append(item)
                elif isinstance(item, str):
                    gaps.append({"description": item})

        # Scan all discovery values for lists of gap-like dicts.
        for key, value in discovery.items():
            if key == "gaps":
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and (
                        "description" in item or "target" in item or "summary" in item
                    ):
                        gaps.append(item)
            elif isinstance(value, dict) and (
                "description" in value or "target" in value or "summary" in value
            ):
                gaps.append(value)

    return gaps


def _matches_gap(gap: dict[str, Any], match_spec: dict[str, Any]) -> bool:
    """Check whether a gap dict matches the match specification.

    Delegates to ``_matches_atom`` for standard atom matching fields, and
    also supports gap-specific matching via ``description_contains``
    applied to the gap's ``summary``, ``description``, or ``target`` fields.

    Args:
        gap: Dict representing a single discovered gap.
        match_spec: Dict of match criteria.

    Returns:
        True if the gap satisfies all criteria in the match spec.
    """
    if not match_spec:
        return False

    # Try standard atom matching first (function_name, file, etc.).
    if _matches_atom(gap, match_spec):
        return True

    # Gap-specific: description_contains can match against summary/target/description.
    desc_contains = match_spec.get("description_contains", "")
    if desc_contains:
        needle = desc_contains.lower()
        for field_name in ("description", "summary", "target"):
            value = gap.get(field_name, "")
            if value and needle in str(value).lower():
                return True

    # Gap-specific: id matching.
    id_any_of = match_spec.get("id_any_of", [])
    if id_any_of:
        gap_id = gap.get("id", "")
        if gap_id and gap_id in id_any_of:
            return True

    # target matching.
    target_any_of = match_spec.get("target_any_of", [])
    if target_any_of:
        gap_target = gap.get("target", "")
        if gap_target and gap_target in target_any_of:
            return True

    return False

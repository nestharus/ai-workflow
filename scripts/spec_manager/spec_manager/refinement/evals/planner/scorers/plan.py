"""Scorer for PLAN decisions.

Evaluates whether planner-produced intentions match ground-truth
``must_include`` and ``must_not_include`` atoms, and checks invariants
such as deduplication and scope constraints.
"""

from __future__ import annotations

from typing import Any

from spec_manager.refinement.evals.planner.scorers.base import Verdict, _matches_atom


class PlanScorer:
    """Scores PLAN planner decisions.

    Ground-truth cases are expected to contain::

        expected:
          must_include:
            - match: {function_name_any_of: [...], ...}
            - match: {file_any_of: [...], ...}
          must_not_include:
            - match: {function_name_regex: "...", ...}
          invariants:
            - type: dedupe
              key_fields: [function_name, file]
              max_duplicates: 0
            - type: scope
              root: "src/"
          thresholds:
            recall: 0.8
            precision: 0.8
            actionability_warn: 1.0
            actionability_fail: 0.8
    """

    def score(self, trace: Any, gt_case: Any) -> Verdict:
        """Score a single PLAN trace against ground truth.

        Args:
            trace: A LoadedTrace-like object with ``.artifacts`` and
                ``.decision`` dicts.
            gt_case: A GroundTruthCase-like object with an ``.expected`` dict.

        Returns:
            Verdict with score = min(recall, precision) and hard-gate
            failures when thresholds are breached.
        """
        expected = getattr(gt_case, "expected", None)
        if expected is None:
            expected = {}
        if not isinstance(expected, dict):
            expected = {}

        # Extract intentions from the trace.
        artifacts = getattr(trace, "artifacts", {}) or {}
        outputs = artifacts.get("outputs", {}) or {}
        intentions: list[dict[str, Any]] = outputs.get("intentions", [])

        if not isinstance(intentions, list):
            intentions = []

        must_include: list[dict[str, Any]] = expected.get("must_include", [])
        must_not_include: list[dict[str, Any]] = expected.get("must_not_include", [])
        invariants: list[dict[str, Any]] = expected.get("invariants", [])
        thresholds: dict[str, float] = expected.get("thresholds", {})
        layer = str(getattr(gt_case, "layer", "") or "").lower()

        hard_gate_failures: list[str] = []
        soft_signal_warnings: list[str] = []

        # ---- must_include recall ----
        must_include_matched = 0
        must_include_total = len(must_include)
        actionable_matched = 0
        non_actionable_matches = 0
        missing_required_field_instances = 0
        required_fields = _required_fields_for_layer(layer)

        for atom in must_include:
            match_spec = atom.get("match", {})
            matched_intentions = [
                intent for intent in intentions if _matches_atom(intent, match_spec)
            ]
            if matched_intentions:
                must_include_matched += 1
                if not required_fields:
                    actionable_matched += 1
                    continue

                best_missing: list[str] | None = None
                is_actionable = False
                for matched_intent in matched_intentions:
                    missing = _missing_required_fields(matched_intent, required_fields)
                    if best_missing is None or len(missing) < len(best_missing):
                        best_missing = missing
                    if not missing:
                        is_actionable = True
                        break

                if is_actionable:
                    actionable_matched += 1
                else:
                    non_actionable_matches += 1
                    missing_fields = best_missing or []
                    missing_required_field_instances += len(missing_fields)
                    soft_signal_warnings.append(
                        f"non_actionable_intention(missing={','.join(missing_fields) or 'unknown'})"
                    )

        recall = must_include_matched / max(1, must_include_total) if must_include_total else 1.0
        actionability_rate = actionable_matched / max(1, must_include_matched)

        # ---- must_not_include precision ----
        must_not_violations = 0
        must_not_total = len(must_not_include)
        for atom in must_not_include:
            match_spec = atom.get("match", {})
            if any(_matches_atom(intent, match_spec) for intent in intentions):
                must_not_violations += 1

        precision = 1.0 - (must_not_violations / must_not_total) if must_not_total else 1.0

        # ---- invariants ----
        for inv in invariants:
            inv_type = inv.get("type", "")
            if inv_type == "dedupe":
                _check_dedupe(inv, intentions, hard_gate_failures, soft_signal_warnings)
            elif inv_type == "scope":
                _check_scope(inv, intentions, hard_gate_failures, soft_signal_warnings)

        # ---- threshold gates ----
        recall_threshold = thresholds.get("recall", 0.0)
        precision_threshold = thresholds.get("precision", 0.0)

        if recall_threshold and recall < recall_threshold:
            hard_gate_failures.append(f"recall_below_threshold({recall:.2f}<{recall_threshold})")
        if precision_threshold and precision < precision_threshold:
            hard_gate_failures.append(
                f"precision_below_threshold({precision:.2f}<{precision_threshold})"
            )

        actionability_warn = _coerce_float(thresholds.get("actionability_warn"), 1.0)
        actionability_fail = _coerce_float(thresholds.get("actionability_fail"), 0.8)
        missing_fields_fail_threshold = int(
            _coerce_float(thresholds.get("actionability_missing_fields_fail"), 3.0)
        )

        if must_include_matched and actionability_rate < actionability_fail:
            hard_gate_failures.append(
                f"actionability_below_threshold({actionability_rate:.2f}<{actionability_fail})"
            )
        elif must_include_matched and actionability_rate < actionability_warn:
            soft_signal_warnings.append(
                f"actionability_warn({actionability_rate:.2f}<{actionability_warn})"
            )

        if (
            must_include_matched
            and missing_required_field_instances >= missing_fields_fail_threshold
            and non_actionable_matches > 0
        ):
            hard_gate_failures.append(
                "actionability_missing_fields("
                f"{missing_required_field_instances}>={missing_fields_fail_threshold})"
            )

        score = min(recall, precision)
        passed = len(hard_gate_failures) == 0

        detail_parts: list[str] = [
            f"recall={recall:.2f} ({must_include_matched}/{must_include_total})",
            f"precision={precision:.2f} "
            f"({must_not_total - must_not_violations}/{max(1, must_not_total)} clean), ",
            f"actionability={actionability_rate:.2f} "
            f"({actionable_matched}/{max(1, must_include_matched)})",
            f"intentions_count={len(intentions)}",
        ]
        if non_actionable_matches:
            detail_parts.append(
                "non_actionable_matches="
                f"{non_actionable_matches} missing_fields={missing_required_field_instances}"
            )
        if hard_gate_failures:
            detail_parts.append(f"hard_gate_failures={hard_gate_failures}")
        if soft_signal_warnings:
            detail_parts.append(f"warnings={soft_signal_warnings}")

        return Verdict(
            capability="plan",
            passed=passed,
            score=score,
            detail="; ".join(detail_parts),
            hard_gate_failures=hard_gate_failures,
            soft_signal_warnings=soft_signal_warnings,
        )


# ------------------------------------------------------------------
# Invariant checkers
# ------------------------------------------------------------------


def _check_dedupe(
    inv: dict[str, Any],
    intentions: list[dict[str, Any]],
    hard_gate_failures: list[str],
    soft_signal_warnings: list[str],
) -> None:
    """Check the dedupe invariant: no duplicate intentions by key_fields."""
    key_fields: list[str] = inv.get("key_fields", [])
    max_duplicates: int = inv.get("max_duplicates", 0)

    if not key_fields:
        soft_signal_warnings.append("dedupe invariant has no key_fields; skipped.")
        return

    seen: dict[tuple[str, ...], int] = {}
    for intent in intentions:
        key = tuple(str(intent.get(f, "")) for f in key_fields)
        seen[key] = seen.get(key, 0) + 1

    duplicate_count = sum(count - 1 for count in seen.values() if count > 1)
    if duplicate_count > max_duplicates:
        hard_gate_failures.append(
            f"dedupe_violation({duplicate_count} duplicates, max={max_duplicates})"
        )


def _check_scope(
    inv: dict[str, Any],
    intentions: list[dict[str, Any]],
    hard_gate_failures: list[str],
    soft_signal_warnings: list[str],
) -> None:
    """Check the scope invariant: all file paths start with the expected root."""
    root: str = inv.get("root", "")
    if not root:
        soft_signal_warnings.append("scope invariant has no root; skipped.")
        return

    out_of_scope: list[str] = []
    for intent in intentions:
        file_path = intent.get("file", "")
        if file_path and not file_path.startswith(root):
            out_of_scope.append(file_path)

    if out_of_scope:
        hard_gate_failures.append(f"scope_violation({len(out_of_scope)} files outside '{root}')")


def _required_fields_for_layer(layer: str) -> tuple[str, ...]:
    """Return required actionability fields for a PLAN layer."""
    if layer == "l1":
        return ("function_name", "file")
    if layer == "l2":
        return ("component_id", "target_files", "pin_refs")
    if layer == "l3":
        return ("file", "function_span", "smell_type", "behavior_preservation_check")
    return ()


def _missing_required_fields(intent: dict[str, Any], required_fields: tuple[str, ...]) -> list[str]:
    """Return required fields that are absent or empty in an intention."""
    missing: list[str] = []
    for field_name in required_fields:
        if not _is_populated(intent.get(field_name)):
            missing.append(field_name)
    return missing


def _is_populated(value: Any) -> bool:
    """Return True when value is present and non-empty."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _coerce_float(value: Any, default: float) -> float:
    """Best-effort float parsing with default fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

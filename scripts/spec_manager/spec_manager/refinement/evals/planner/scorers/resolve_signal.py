"""Scorer for RESOLVE_SIGNAL decisions.

Checks whether the planner correctly resolved or rejected a signal
by comparing the decision output against ground-truth expectations.
"""

from __future__ import annotations

from typing import Any

from spec_manager.refinement.evals.planner.scorers.base import Verdict


class ResolveSignalScorer:
    """Scores RESOLVE_SIGNAL planner decisions.

    Ground-truth cases are expected to contain::

        expected:
          should_resolve: bool
          answers_any_of: list[str]   # only when should_resolve=true
          must_cite: list[str]        # optional evidence ref IDs
    """

    def score(self, trace: Any, gt_case: Any) -> Verdict:
        """Score a single RESOLVE_SIGNAL trace against ground truth.

        Args:
            trace: A LoadedTrace-like object with ``.artifacts`` and
                ``.decision`` dicts.
            gt_case: A GroundTruthCase-like object with an ``.expected`` dict.

        Returns:
            Verdict with pass/fail and detail.
        """
        expected = getattr(gt_case, "expected", None)
        if expected is None:
            expected = {}
        if not isinstance(expected, dict):
            expected = {}

        should_resolve = expected.get("should_resolve")
        if should_resolve is None:
            return Verdict(
                capability="resolve_signal",
                passed=True,
                score=1.0,
                detail="No should_resolve in ground truth; neutral verdict.",
            )

        # Extract the planner's answer from the trace.
        artifacts = getattr(trace, "artifacts", {}) or {}
        decision = getattr(trace, "decision", {}) or {}

        outputs = artifacts.get("outputs", {}) or {}
        response = outputs.get("response", "")
        decision_text = decision.get("decision_text", "")
        answer = response or decision_text

        hard_gate_failures: list[str] = []
        soft_signal_warnings: list[str] = []

        if not should_resolve:
            # GT says the planner should NOT resolve (NOOP / empty).
            answer_is_empty = _is_empty_answer(answer)
            if answer_is_empty:
                return Verdict(
                    capability="resolve_signal",
                    passed=True,
                    score=1.0,
                    detail="Correctly returned NOOP/empty for should_resolve=false.",
                )
            else:
                hard_gate_failures.append("false_resolve")
                return Verdict(
                    capability="resolve_signal",
                    passed=False,
                    score=0.0,
                    detail=(
                        "Planner returned a non-empty answer when "
                        "should_resolve=false. "
                        f"Answer snippet: {_truncate(answer, 120)}"
                    ),
                    hard_gate_failures=hard_gate_failures,
                )

        # should_resolve=true: check answer matches one of answers_any_of.
        answers_any_of: list[str] = expected.get("answers_any_of", [])
        matched_answer = False
        if answers_any_of:
            answer_lower = answer.lower()
            for acceptable in answers_any_of:
                if acceptable.lower() in answer_lower:
                    matched_answer = True
                    break
            if not matched_answer:
                hard_gate_failures.append("wrong_answer")
        else:
            # No expected answers listed; as long as the answer is non-empty
            # we consider it acceptable.
            if _is_empty_answer(answer):
                hard_gate_failures.append("missing_answer")
            else:
                matched_answer = True

        # Check must_cite evidence references.
        must_cite: list[str] = expected.get("must_cite", [])
        evidence_refs = _extract_evidence_refs(artifacts, decision)
        missing_citations: list[str] = []
        for cite_id in must_cite:
            if cite_id not in evidence_refs:
                missing_citations.append(cite_id)
        if missing_citations:
            soft_signal_warnings.append(
                f"missing_citations: {', '.join(missing_citations)}"
            )

        passed = len(hard_gate_failures) == 0
        score = 1.0 if passed else 0.0

        detail_parts: list[str] = []
        if matched_answer:
            detail_parts.append("Answer matches expected.")
        elif "wrong_answer" in hard_gate_failures:
            detail_parts.append(
                f"Answer does not match any of {answers_any_of}. "
                f"Got: {_truncate(answer, 120)}"
            )
        elif "missing_answer" in hard_gate_failures:
            detail_parts.append("Planner returned empty answer for should_resolve=true.")
        if missing_citations:
            detail_parts.append(f"Missing citations: {missing_citations}")

        return Verdict(
            capability="resolve_signal",
            passed=passed,
            score=score,
            detail=" ".join(detail_parts) if detail_parts else "OK",
            hard_gate_failures=hard_gate_failures,
            soft_signal_warnings=soft_signal_warnings,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _is_empty_answer(answer: str) -> bool:
    """Return True if the answer is effectively empty or NOOP."""
    if not answer:
        return True
    stripped = answer.strip().lower()
    return stripped in ("", "noop", "none", "null", "n/a")


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _extract_evidence_refs(
    artifacts: dict[str, Any],
    decision: dict[str, Any],
) -> set[str]:
    """Collect all evidence ref IDs from artifacts and decision dicts."""
    refs: set[str] = set()

    # Look in decision.evidence_refs
    for ref_id in decision.get("evidence_refs", []):
        if isinstance(ref_id, str):
            refs.add(ref_id)

    # Look in artifacts.outputs.evidence_refs
    outputs = artifacts.get("outputs", {}) or {}
    for ref_id in outputs.get("evidence_refs", []):
        if isinstance(ref_id, str):
            refs.add(ref_id)

    return refs

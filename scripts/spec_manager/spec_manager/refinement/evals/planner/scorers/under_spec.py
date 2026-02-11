"""Scorer for UNDER_SPEC decisions.

Evaluates whether the planner correctly blocked or resolved under-specified
events, with special emphasis on safety: a false unblock (planner resolves
when it should have blocked) is a hard-gate failure.
"""

from __future__ import annotations

from typing import Any

from spec_manager.refinement.evals.planner.scorers.base import Verdict


class UnderSpecScorer:
    """Scores UNDER_SPEC planner decisions.

    Ground-truth cases are expected to contain::

        expected:
          events:
            - event_id: "evt_001"
              should_block: true
            - event_id: "evt_002"
              should_block: false
    """

    def score(self, trace: Any, gt_case: Any) -> Verdict:
        """Score a single UNDER_SPEC trace against ground truth.

        Args:
            trace: A LoadedTrace-like object with ``.artifacts`` and
                ``.decision`` dicts.
            gt_case: A GroundTruthCase-like object with an ``.expected`` dict.

        Returns:
            Verdict with hard-gate failure if any false unblocks occur.
        """
        expected = getattr(gt_case, "expected", None)
        if expected is None:
            expected = {}
        if not isinstance(expected, dict):
            expected = {}

        events: list[dict[str, Any]] = expected.get("events", [])
        if not events:
            return Verdict(
                capability="under_spec",
                passed=True,
                score=1.0,
                detail="No events in ground truth; neutral verdict.",
            )

        # Extract planner outputs.
        artifacts = getattr(trace, "artifacts", {}) or {}
        outputs = artifacts.get("outputs", {}) or {}

        blocked: bool = bool(outputs.get("blocked", False))
        constraints: dict[str, Any] = outputs.get("constraints", {}) or {}
        questions: list[Any] = outputs.get("questions", []) or []

        # Build a set of resolved event IDs: events for which the planner
        # provided a constraint or explicitly resolved.
        resolved_event_ids: set[str] = set()
        for key in constraints:
            resolved_event_ids.add(str(key))

        # Walk through GT events and classify outcomes.
        false_unblock_count = 0
        correct_block_count = 0
        correct_resolve_count = 0
        total_should_block = 0
        total_should_resolve = 0

        hard_gate_failures: list[str] = []
        soft_signal_warnings: list[str] = []

        for event in events:
            event_id = str(event.get("event_id", ""))
            should_block = event.get("should_block", False)

            if should_block:
                total_should_block += 1
                # The planner should have blocked this event. A false unblock
                # happens when the planner did NOT block AND provided a
                # constraint for this event (i.e., it resolved something it
                # should not have).
                if not blocked and event_id in resolved_event_ids:
                    false_unblock_count += 1
                else:
                    correct_block_count += 1
            else:
                total_should_resolve += 1
                # The planner should have resolved this event (not blocked, or
                # at least provided a constraint).
                if event_id in resolved_event_ids or not blocked:
                    correct_resolve_count += 1

        # Hard gate: any false unblock is critical.
        if false_unblock_count > 0:
            hard_gate_failures.append(
                f"false_unblock({false_unblock_count})"
            )

        # Compute rates.
        false_unblock_rate = (
            false_unblock_count / max(1, total_should_block)
            if total_should_block
            else 0.0
        )
        correct_block_rate = (
            correct_block_count / max(1, total_should_block)
            if total_should_block
            else 1.0
        )
        correct_resolve_rate = (
            correct_resolve_count / max(1, total_should_resolve)
            if total_should_resolve
            else 1.0
        )

        # Score: average of correct rates, but floor to 0 if any false unblocks.
        if false_unblock_count > 0:
            score = 0.0
        else:
            score = (correct_block_rate + correct_resolve_rate) / 2.0

        passed = len(hard_gate_failures) == 0

        detail = (
            f"false_unblock_rate={false_unblock_rate:.2f}, "
            f"correct_block_rate={correct_block_rate:.2f} "
            f"({correct_block_count}/{total_should_block}), "
            f"correct_resolve_rate={correct_resolve_rate:.2f} "
            f"({correct_resolve_count}/{total_should_resolve}), "
            f"blocked={blocked}, constraints={len(constraints)}, "
            f"questions={len(questions)}"
        )

        return Verdict(
            capability="under_spec",
            passed=passed,
            score=score,
            detail=detail,
            hard_gate_failures=hard_gate_failures,
            soft_signal_warnings=soft_signal_warnings,
        )

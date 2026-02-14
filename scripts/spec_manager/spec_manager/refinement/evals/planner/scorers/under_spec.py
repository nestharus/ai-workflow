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
              required_question_patterns: ["which component", "owner"]
            - event_id: "evt_002"
              should_block: false
              required_constraint_keys: ["decision", "owner"]
              answer_type: "constraint"
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
        constraints_raw = outputs.get("constraints", {}) or {}
        constraints: dict[str, Any] = constraints_raw if isinstance(constraints_raw, dict) else {}
        questions: list[Any] = outputs.get("questions", []) or []
        question_texts = _normalize_question_texts(questions)

        # Build a set of resolved event IDs: events for which the planner
        # provided a constraint or explicitly resolved.
        resolved_event_ids = _collect_resolved_event_ids(outputs, constraints)

        # Walk through GT events and classify outcomes.
        false_unblock_count = 0
        false_block_count = 0
        missing_question_pattern_count = 0
        missing_constraint_key_count = 0
        answer_type_mismatch_count = 0
        correct_block_count = 0
        correct_resolve_count = 0
        total_should_block = 0
        total_should_resolve = 0
        fully_correct_events = 0

        hard_gate_failures: list[str] = []
        soft_signal_warnings: list[str] = []
        false_unblock_ids: list[str] = []
        false_block_ids: list[str] = []
        missing_question_pattern_ids: list[str] = []
        missing_constraint_key_ids: list[str] = []
        answer_type_mismatch_ids: list[str] = []

        for event in events:
            event_id = _event_identifier(event)
            should_block = bool(event.get("should_block", False))
            event_failures = 0

            if should_block:
                total_should_block += 1
                # Safety-critical: if GT says should block and planner did not
                # block, this is a false unblock regardless of constraints.
                if not blocked:
                    false_unblock_count += 1
                    false_unblock_ids.append(event_id)
                    event_failures += 1
                required_question_patterns = event.get("required_question_patterns", []) or []
                if blocked and required_question_patterns:
                    missing_patterns = _missing_question_patterns(
                        required_question_patterns, question_texts
                    )
                    if missing_patterns:
                        missing_question_pattern_count += 1
                        missing_question_pattern_ids.append(event_id)
                        event_failures += 1
                if blocked and event_id in resolved_event_ids:
                    soft_signal_warnings.append(f"blocked_event_has_resolution({event_id})")
                if event_failures == 0:
                    correct_block_count += 1
            else:
                total_should_resolve += 1
                constraint_payload = _constraint_for_event(event, constraints)
                event_resolved = event_id in resolved_event_ids or constraint_payload is not None

                # False block: event should resolve, but planner left it blocked
                # and did not provide event-specific resolution.
                if blocked and not event_resolved:
                    false_block_count += 1
                    false_block_ids.append(event_id)
                    event_failures += 1

                required_constraint_keys = event.get("required_constraint_keys", []) or []
                if required_constraint_keys:
                    missing_keys = _missing_constraint_keys(
                        constraint_payload, required_constraint_keys
                    )
                    if missing_keys:
                        missing_constraint_key_count += 1
                        missing_constraint_key_ids.append(event_id)
                        event_failures += 1

                expected_answer_type = str(event.get("answer_type", "") or "").strip()
                if expected_answer_type and not _matches_answer_type(
                    constraint_payload, expected_answer_type
                ):
                    answer_type_mismatch_count += 1
                    answer_type_mismatch_ids.append(event_id)
                    event_failures += 1

                if event_failures == 0 and (event_resolved or not blocked):
                    correct_resolve_count += 1

            if event_failures == 0:
                fully_correct_events += 1

        # Hard gates
        if false_unblock_count > 0:
            hard_gate_failures.append(
                f"false_unblock({false_unblock_count}:{','.join(false_unblock_ids[:5])})"
            )
        if false_block_count > 0:
            hard_gate_failures.append(
                f"false_block({false_block_count}:{','.join(false_block_ids[:5])})"
            )
        if missing_question_pattern_count > 0:
            hard_gate_failures.append(
                "missing_question_patterns("
                f"{missing_question_pattern_count}:{','.join(missing_question_pattern_ids[:5])})"
            )
        if missing_constraint_key_count > 0:
            hard_gate_failures.append(
                "missing_constraint_keys("
                f"{missing_constraint_key_count}:{','.join(missing_constraint_key_ids[:5])})"
            )
        if answer_type_mismatch_count > 0:
            hard_gate_failures.append(
                "answer_type_mismatch("
                f"{answer_type_mismatch_count}:{','.join(answer_type_mismatch_ids[:5])})"
            )

        # Compute rates.
        false_unblock_rate = (
            false_unblock_count / max(1, total_should_block) if total_should_block else 0.0
        )
        correct_block_rate = (
            correct_block_count / max(1, total_should_block) if total_should_block else 1.0
        )
        correct_resolve_rate = (
            correct_resolve_count / max(1, total_should_resolve) if total_should_resolve else 1.0
        )
        event_accuracy = fully_correct_events / max(1, len(events))

        # Score is event-level accuracy; floor to 0 on safety-critical false unblocks.
        score = 0.0 if false_unblock_count > 0 else event_accuracy

        passed = len(hard_gate_failures) == 0

        detail = (
            f"false_unblock_rate={false_unblock_rate:.2f}, "
            f"false_block_count={false_block_count}, "
            f"correct_block_rate={correct_block_rate:.2f} "
            f"({correct_block_count}/{total_should_block}), "
            f"correct_resolve_rate={correct_resolve_rate:.2f} "
            f"({correct_resolve_count}/{total_should_resolve}), "
            f"event_accuracy={event_accuracy:.2f} "
            f"({fully_correct_events}/{len(events)}), "
            f"blocked={blocked}, constraints={len(constraints)}, "
            f"questions={len(question_texts)}"
        )

        return Verdict(
            capability="under_spec",
            passed=passed,
            score=score,
            detail=detail,
            hard_gate_failures=hard_gate_failures,
            soft_signal_warnings=soft_signal_warnings,
        )


def _event_identifier(event: dict[str, Any]) -> str:
    """Return a stable event identifier string for diagnostics."""
    for key in ("event_id", "id", "question"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown_event"


def _normalize_question_texts(raw_questions: list[Any]) -> list[str]:
    """Normalize question payloads into plain text strings."""
    texts: list[str] = []
    for question in raw_questions:
        if isinstance(question, str) and question.strip():
            texts.append(question.strip())
            continue
        if isinstance(question, dict):
            for key in ("question", "text", "prompt"):
                value = question.get(key)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
                    break
    return texts


def _collect_resolved_event_ids(outputs: dict[str, Any], constraints: dict[str, Any]) -> set[str]:
    """Collect resolved event identifiers from constraints and explicit resolved entries."""
    resolved_event_ids = {str(key) for key in constraints}
    resolved = outputs.get("resolved", []) or []
    if isinstance(resolved, list):
        for item in resolved:
            if not isinstance(item, dict):
                continue
            for key in ("event_id", "id", "question"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    resolved_event_ids.add(value.strip())
            event_payload = item.get("event")
            if isinstance(event_payload, dict):
                for key in ("event_id", "id", "question"):
                    value = event_payload.get(key)
                    if isinstance(value, str) and value.strip():
                        resolved_event_ids.add(value.strip())
    return resolved_event_ids


def _constraint_for_event(event: dict[str, Any], constraints: dict[str, Any]) -> Any | None:
    """Return the constraint payload associated with an event when present."""
    for key in ("event_id", "id", "question"):
        event_key = event.get(key)
        if not isinstance(event_key, str) or not event_key.strip():
            continue
        if event_key in constraints:
            return constraints[event_key]
    return None


def _missing_constraint_keys(payload: Any, required_keys: list[Any]) -> list[str]:
    """Return missing required keys from a constraint payload."""
    required = [str(key).strip() for key in required_keys if str(key).strip()]
    if not required:
        return []
    if not isinstance(payload, dict):
        return required
    missing: list[str] = []
    for key in required:
        if not _is_populated(payload.get(key)):
            missing.append(key)
    return missing


def _matches_answer_type(payload: Any, expected_answer_type: str) -> bool:
    """Check whether payload exposes the expected answer_type."""
    expected = expected_answer_type.strip().lower()
    if not expected:
        return True
    if isinstance(payload, dict):
        for key in ("answer_type", "type", "kind"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip().lower() == expected:
                return True
    if isinstance(payload, str):
        return expected in {"string", "str", "text"}
    if isinstance(payload, bool):
        return expected in {"bool", "boolean"}
    if isinstance(payload, (int, float)):
        return expected in {"number", "int", "float"}
    if isinstance(payload, list):
        return expected in {"list", "array"}
    if isinstance(payload, dict):
        return expected in {"dict", "object"}
    return False


def _missing_question_patterns(patterns: list[Any], question_texts: list[str]) -> list[str]:
    """Return required question patterns that were not asked."""
    lowered_questions = [text.lower() for text in question_texts]
    missing: list[str] = []
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        needle = pattern.strip().lower()
        if not any(needle in question_text for question_text in lowered_questions):
            missing.append(pattern.strip())
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

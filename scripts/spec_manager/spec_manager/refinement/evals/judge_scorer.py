"""LLM judge scorer for semantic detail-capture evaluation.

Uses an LLM judge agent to evaluate whether actual extracted items
semantically match expected ground-truth items, replacing fuzzy
string matching with semantic equivalence checking.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from spec_manager.core.agent_utils import run_agent
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.evals.metrics import DetailScore
from spec_manager.refinement.formats import _strip_code_fences
from spec_manager.schemas.eval_judge import EvalJudgeOutput

logger = logging.getLogger(__name__)

JUDGE_AGENT_NAME = "chatgpt-eval-detail-judge"


def _build_judge_prompt(
    expected: list[str],
    actual: list[str],
    phase: str = "",
) -> str:
    """Build the prompt for the judge agent.

    Follows OUTPUT CONTRACT -> INPUT DATA -> OUTPUT FORMAT ordering
    per Cerebras best practices.

    Args:
        expected: List of expected ground-truth items.
        actual: List of actual system-extracted items.
        phase: Optional phase name for context.

    Returns:
        Formatted prompt string.
    """
    lines: list[str] = []

    # OUTPUT CONTRACT
    lines.append("## OUTPUT CONTRACT")
    lines.append("")
    lines.append(
        "Return a JSON object with `matches` (one entry per expected item), "
        "`unmatched_actual` (indices of actual items not matched), and `summary`."
    )
    lines.append("Every expected item must appear exactly once in matches.")
    lines.append("One-to-one matching: each actual item matches at most one expected item.")
    lines.append("")

    # INPUT DATA
    lines.append("## INPUT DATA")
    lines.append("")
    if phase:
        lines.append(f"Phase: {phase}")
        lines.append("")

    lines.append(f"### Expected Items ({len(expected)})")
    lines.append("")
    for i, item in enumerate(expected):
        lines.append(f"{i}. {item}")
    lines.append("")

    lines.append(f"### Actual Items ({len(actual)})")
    lines.append("")
    for i, item in enumerate(actual):
        lines.append(f"{i}. {item}")
    lines.append("")

    # OUTPUT FORMAT
    lines.append("## OUTPUT FORMAT")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append('  "matches": [')
    lines.append("    {")
    lines.append('      "expected_index": 0,')
    lines.append('      "actual_index": 0,')
    lines.append('      "matched": true,')
    lines.append('      "rationale": "..."')
    lines.append("    }")
    lines.append("  ],")
    lines.append('  "unmatched_actual": [],')
    lines.append('  "summary": "..."')
    lines.append("}")
    lines.append("```")

    return "\n".join(lines)


def _parse_judge_output(raw: str) -> EvalJudgeOutput:
    """Parse raw judge agent output into structured data.

    Handles code-fenced responses and preamble text.

    Args:
        raw: Raw string output from the judge agent.

    Returns:
        Validated EvalJudgeOutput.

    Raises:
        ValueError: If the output cannot be parsed.
    """
    cleaned = _strip_code_fences(raw)

    # Try direct Pydantic parse
    try:
        return EvalJudgeOutput.model_validate_json(cleaned)
    except Exception:
        pass

    # Fallback: extract JSON payload
    extracted = _extract_json_payload(cleaned)
    try:
        return EvalJudgeOutput.model_validate_json(extracted)
    except Exception:
        pass

    # Final fallback: parse as dict then validate
    data = json.loads(extracted)
    return EvalJudgeOutput.model_validate(data)


def _to_detail_score(
    judge_data: EvalJudgeOutput,
    expected_count: int,
    actual_count: int,
) -> DetailScore:
    """Convert judge match decisions to a DetailScore.

    Args:
        judge_data: Parsed judge output.
        expected_count: Total expected items.
        actual_count: Total actual items.

    Returns:
        DetailScore with precision and recall.
    """
    matched_count = sum(1 for m in judge_data.matches if m.matched)

    recall = matched_count / max(1, expected_count)
    precision = matched_count / max(1, actual_count)

    return DetailScore(
        matched_count=matched_count,
        expected_count=expected_count,
        actual_count=actual_count,
        recall=recall,
        precision=precision,
    )


def score_detail_capture_with_judge(
    expected: list[str],
    actual: list[str],
    *,
    workspace: Path,
    phase: str = "",
) -> DetailScore:
    """Score detail capture using an LLM judge for semantic matching.

    Drop-in replacement for ``score_detail_capture()`` that uses an LLM
    judge agent instead of fuzzy string matching.

    Args:
        expected: List of expected ground-truth items.
        actual: List of actual extracted items.
        workspace: Workspace directory for the agent.
        phase: Optional phase name for context.

    Returns:
        DetailScore with precision and recall from semantic matching.
    """
    # Edge cases: handle locally without LLM call
    if not expected and not actual:
        return DetailScore(
            matched_count=0,
            expected_count=0,
            actual_count=0,
            recall=1.0,
            precision=1.0,
        )

    if not expected:
        return DetailScore(
            matched_count=0,
            expected_count=0,
            actual_count=len(actual),
            recall=1.0,
            precision=0.0,
        )

    if not actual:
        return DetailScore(
            matched_count=0,
            expected_count=len(expected),
            actual_count=0,
            recall=0.0,
            precision=1.0,
        )

    # Build prompt and call judge agent
    prompt = _build_judge_prompt(expected, actual, phase=phase)
    raw_output = run_agent(
        agent_name=JUDGE_AGENT_NAME,
        prompt=prompt,
        workspace=workspace,
    )

    # Parse and convert
    judge_data = _parse_judge_output(raw_output)
    return _to_detail_score(judge_data, len(expected), len(actual))

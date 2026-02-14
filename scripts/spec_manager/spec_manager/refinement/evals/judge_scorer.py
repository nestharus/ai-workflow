"""LLM judge scorer for semantic detail-capture evaluation.

Uses an LLM judge agent to evaluate whether actual extracted items
semantically match expected ground-truth items, replacing fuzzy
string matching with semantic equivalence checking.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

from spec_manager.core.agent_utils import run_agent as _unused_run_agent
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey
from spec_manager.refinement.evals.judges.client import JudgeClient
from spec_manager.refinement.evals.metrics import DetailScore
from spec_manager.refinement.formats import _strip_code_fences
from spec_manager.schemas.eval_judge import EvalJudgeOutput

logger = logging.getLogger(__name__)

JUDGE_AGENT_NAME = "chatgpt-eval-detail-judge"
PROMPT_VERSION = "v1"
_ = _unused_run_agent


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


def _parse_judge_output(raw: str) -> EvalJudgeOutput:
    """Parse raw judge output into a validated EvalJudgeOutput."""
    cleaned = _strip_code_fences(raw)

    try:
        return EvalJudgeOutput.model_validate_json(cleaned)
    except Exception:
        logger.debug("Direct Pydantic parse failed for judge output", exc_info=True)

    extracted = _extract_json_payload(cleaned)
    try:
        return EvalJudgeOutput.model_validate_json(extracted)
    except Exception:
        logger.debug("Pydantic parse of extracted JSON failed for judge output", exc_info=True)

    return EvalJudgeOutput.model_validate(json.loads(extracted))


def _cache_key(
    expected: list[str],
    actual: list[str],
    phase: str,
    model_id: str,
    prompt_version: str,
) -> JudgeCacheKey:
    payload = json.dumps(
        {
            "expected": expected,
            "actual": actual,
            "phase": phase,
        },
        sort_keys=True,
    )
    return JudgeCacheKey(
        judge_type="detail_match",
        model_id=model_id,
        prompt_version=prompt_version,
        input_hash=JudgeCache.compute_hash(payload),
    )


def score_detail_capture_with_judge(
    expected: list[str],
    actual: list[str],
    *,
    workspace: Path,
    phase: str = "",
    model_id: str = "",
    producer_model_id: str = "",
    allow_self_judge: bool = False,
    cache: JudgeCache | None = None,
    prompt_version: str = PROMPT_VERSION,
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

    # Build prompt and call shared judge runtime
    prompt = _build_judge_prompt(expected, actual, phase=phase)
    judge_client = JudgeClient(
        agent_name=JUDGE_AGENT_NAME,
        workspace=workspace,
        schema_cls=EvalJudgeOutput,
        model_id=model_id,
        producer_model_id=producer_model_id,
        allow_self_judge=allow_self_judge,
    )
    cache_obj = cache if cache is not None else JudgeCache(workspace / "analysis" / "judge_cache")
    judge_key = _cache_key(
        expected=expected,
        actual=actual,
        phase=phase,
        model_id=model_id,
        prompt_version=prompt_version,
    )
    judge_data = cast(
        "EvalJudgeOutput",
        judge_client.judge(
            prompt=prompt,
            cache=cache_obj,
            cache_key=judge_key,
        ),
    )

    return _to_detail_score(judge_data, len(expected), len(actual))

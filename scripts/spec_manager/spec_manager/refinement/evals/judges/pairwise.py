"""Pairwise comparison judge modules."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey
from spec_manager.refinement.evals.judges.client import JudgeClient
from spec_manager.schemas.eval_pairwise_judge import PairwiseOutput

logger = logging.getLogger(__name__)

AGENT_NAME = "judge-pairwise"
PROMPT_VERSION = "v1"

_IDENTITY_KEYS = {
    "run_id",
    "model",
    "pipeline",
    "profile_name",
    "comparison_id",
    "timestamp",
    "created_at",
    "updated_at",
    "producer_model_id",
    "judge_model_id",
    "notes",
}


def _blind_digest(value: Any) -> Any:
    """Remove run/model metadata so pairwise prompts stay candidate-blind."""
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if lowered in _IDENTITY_KEYS:
                continue
            if lowered.endswith("_path"):
                continue
            projected[key] = _blind_digest(item)
        return projected
    if isinstance(value, list):
        return [_blind_digest(item) for item in value]
    return value


class PairwiseArchJudge:
    """Blinded A/B comparison of architecture quality between two runs."""

    def __init__(
        self,
        workspace: Path,
        cache: JudgeCache | None = None,
        model_id: str = "",
        producer_model_id: str = "",
        allow_self_judge: bool = False,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.workspace = workspace
        self.cache = cache
        self.model_id = model_id
        self.prompt_version = prompt_version
        self._client = JudgeClient(
            agent_name=AGENT_NAME,
            workspace=workspace,
            schema_cls=PairwiseOutput,
            model_id=model_id,
            producer_model_id=producer_model_id,
            allow_self_judge=allow_self_judge,
        )

    def compare(
        self,
        digest_a: dict[str, Any],
        digest_b: dict[str, Any],
    ) -> PairwiseOutput:
        """Compare two architecture digests.

        Args:
            digest_a: First run's architecture digest.
            digest_b: Second run's architecture digest.

        Returns:
            Validated PairwiseOutput with winner and per-dimension scores.
        """
        blinded_a = _blind_digest(digest_a)
        blinded_b = _blind_digest(digest_b)
        prompt = self._build_prompt(blinded_a, blinded_b, focus="architecture")

        cache_key = None
        if self.cache is not None:
            combined = json.dumps({"a": blinded_a, "b": blinded_b}, sort_keys=True)
            input_hash = JudgeCache.compute_hash(combined)
            cache_key = JudgeCacheKey(
                judge_type="pairwise_arch",
                model_id=self.model_id,
                prompt_version=self.prompt_version,
                input_hash=input_hash,
            )

        result = self._client.judge(
            prompt=prompt,
            cache=self.cache,
            cache_key=cache_key,
        )
        return result  # type: ignore[return-value]

    def _build_prompt(
        self,
        digest_a: dict[str, Any],
        digest_b: dict[str, Any],
        focus: str,
    ) -> str:
        lines = [
            "## OUTPUT CONTRACT",
            "",
            f"Compare candidate A and candidate B on {focus} quality and return a JSON object"
            " with:",
            "- `winner`: `A`, `B`, or `TIE`",
            "- `scores`: dimension-by-dimension integer scores for A and B",
            "- `key_differences`: concise differences that drove the decision",
            "- `risks`: notable risks with severity and evidence",
            "Valid alternatives are acceptable; do not enforce one prescriptive style.",
            "Cite component/file identifiers from the digest in differences and risks.",
            "",
            "## INPUT DATA",
            "",
            "### Output A (Candidate A, blinded)",
            "```json",
            json.dumps(digest_a, indent=2, sort_keys=True),
            "```",
            "",
            "### Output B (Candidate B, blinded)",
            "```json",
            json.dumps(digest_b, indent=2, sort_keys=True),
            "```",
            "",
            "## OUTPUT FORMAT",
            "",
            "Return strict JSON only (no prose, no markdown):",
            "```json",
            "{",
            '  "winner": "A",',
            '  "scores": {',
            '    "A": {"overall": 1},',
            '    "B": {"overall": 1}',
            "  },",
            '  "key_differences": ["..."],',
            '  "risks": [{"severity": "MAJOR", "evidence": "component_or_file_id"}]',
            "}",
            "```",
        ]
        return "\n".join(lines)


class PairwiseCodeJudge:
    """Blinded A/B comparison of code quality between two runs."""

    def __init__(
        self,
        workspace: Path,
        cache: JudgeCache | None = None,
        model_id: str = "",
        producer_model_id: str = "",
        allow_self_judge: bool = False,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.workspace = workspace
        self.cache = cache
        self.model_id = model_id
        self.prompt_version = prompt_version
        self._client = JudgeClient(
            agent_name=AGENT_NAME,
            workspace=workspace,
            schema_cls=PairwiseOutput,
            model_id=model_id,
            producer_model_id=producer_model_id,
            allow_self_judge=allow_self_judge,
        )

    def compare(
        self,
        digest_a: dict[str, Any],
        digest_b: dict[str, Any],
    ) -> PairwiseOutput:
        """Compare two code digests.

        Args:
            digest_a: First run's code digest.
            digest_b: Second run's code digest.

        Returns:
            Validated PairwiseOutput with winner and per-dimension scores.
        """
        blinded_a = _blind_digest(digest_a)
        blinded_b = _blind_digest(digest_b)
        prompt = self._build_prompt(blinded_a, blinded_b)

        cache_key = None
        if self.cache is not None:
            combined = json.dumps({"a": blinded_a, "b": blinded_b}, sort_keys=True)
            input_hash = JudgeCache.compute_hash(combined)
            cache_key = JudgeCacheKey(
                judge_type="pairwise_code",
                model_id=self.model_id,
                prompt_version=self.prompt_version,
                input_hash=input_hash,
            )

        result = self._client.judge(
            prompt=prompt,
            cache=self.cache,
            cache_key=cache_key,
        )
        return result  # type: ignore[return-value]

    def _build_prompt(
        self,
        digest_a: dict[str, Any],
        digest_b: dict[str, Any],
    ) -> str:
        lines = [
            "## OUTPUT CONTRACT",
            "",
            "Compare candidate A and candidate B on code quality and return one JSON object with:",
            "- `winner`: `A`, `B`, or `TIE`",
            "- `scores`: dimension-by-dimension integer scores for A and B",
            "- `key_differences`: concise differences that drove the decision",
            "- `risks`: notable risks with severity and evidence",
            "Valid alternatives are acceptable; do not enforce one prescriptive style.",
            "Cite file identifiers from the digest in differences and risks.",
            "",
            "## INPUT DATA",
            "",
            "### Output A (Candidate A, blinded)",
            "```json",
            json.dumps(digest_a, indent=2, sort_keys=True),
            "```",
            "",
            "### Output B (Candidate B, blinded)",
            "```json",
            json.dumps(digest_b, indent=2, sort_keys=True),
            "```",
            "",
            "## OUTPUT FORMAT",
            "",
            "Return strict JSON only (no prose, no markdown):",
            "```json",
            "{",
            '  "winner": "A",',
            '  "scores": {',
            '    "A": {"overall": 1},',
            '    "B": {"overall": 1}',
            "  },",
            '  "key_differences": ["..."],',
            '  "risks": [{"severity": "MAJOR", "evidence": "path/to/file.py"}]',
            "}",
            "```",
        ]
        return "\n".join(lines)

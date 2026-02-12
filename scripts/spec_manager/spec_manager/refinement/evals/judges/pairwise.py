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


class PairwiseArchJudge:
    """Blinded A/B comparison of architecture quality between two runs."""

    def __init__(
        self,
        workspace: Path,
        cache: JudgeCache | None = None,
        model_id: str = "",
    ) -> None:
        self.workspace = workspace
        self.cache = cache
        self.model_id = model_id
        self._client = JudgeClient(
            agent_name=AGENT_NAME,
            workspace=workspace,
            schema_cls=PairwiseOutput,
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
        prompt = self._build_prompt(digest_a, digest_b, focus="architecture")

        cache_key = None
        if self.cache is not None:
            combined = json.dumps({"a": digest_a, "b": digest_b}, sort_keys=True)
            input_hash = JudgeCache.compute_hash(combined)
            cache_key = JudgeCacheKey(
                judge_type="pairwise_arch",
                model_id=self.model_id,
                prompt_version="v1",
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
        sections = [
            f"# Pairwise {focus.title()} Comparison",
            "",
            "Compare the following two outputs (A and B). This is a blinded comparison.",
            "",
            "## Output A",
            "",
            json.dumps(digest_a, indent=2),
            "",
            "## Output B",
            "",
            json.dumps(digest_b, indent=2),
            "",
            "Compare and return your assessment as JSON.",
        ]
        return "\n".join(sections)


class PairwiseCodeJudge:
    """Blinded A/B comparison of code quality between two runs."""

    def __init__(
        self,
        workspace: Path,
        cache: JudgeCache | None = None,
        model_id: str = "",
    ) -> None:
        self.workspace = workspace
        self.cache = cache
        self.model_id = model_id
        self._client = JudgeClient(
            agent_name=AGENT_NAME,
            workspace=workspace,
            schema_cls=PairwiseOutput,
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
        prompt = self._build_prompt(digest_a, digest_b)

        cache_key = None
        if self.cache is not None:
            combined = json.dumps({"a": digest_a, "b": digest_b}, sort_keys=True)
            input_hash = JudgeCache.compute_hash(combined)
            cache_key = JudgeCacheKey(
                judge_type="pairwise_code",
                model_id=self.model_id,
                prompt_version="v1",
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
        sections = [
            "# Pairwise Code Quality Comparison",
            "",
            "Compare the following two outputs (A and B). This is a blinded comparison.",
            "",
            "## Output A",
            "",
            json.dumps(digest_a, indent=2),
            "",
            "## Output B",
            "",
            json.dumps(digest_b, indent=2),
            "",
            "Compare and return your assessment as JSON.",
        ]
        return "\n".join(sections)

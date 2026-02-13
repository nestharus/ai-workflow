"""Spec fidelity judge module."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey
from spec_manager.refinement.evals.judges.client import JudgeClient
from spec_manager.schemas.eval_spec_fidelity_judge import SpecFidelityOutput

logger = logging.getLogger(__name__)

AGENT_NAME = "judge-spec-fidelity"


class SpecFidelityJudge:
    """Evaluates spec coverage and detects hallucinated features."""

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
            schema_cls=SpecFidelityOutput,
        )

    def evaluate(
        self,
        spec_summary: dict[str, Any],
        code_digest: dict[str, Any],
    ) -> SpecFidelityOutput:
        """Evaluate spec fidelity.

        Args:
            spec_summary: Spec summary with requirements.
            code_digest: Code digest with file list.

        Returns:
            Validated SpecFidelityOutput.
        """
        prompt = self._build_prompt(spec_summary, code_digest)

        cache_key = None
        if self.cache is not None:
            combined = json.dumps({"spec": spec_summary, "code": code_digest}, sort_keys=True)
            input_hash = JudgeCache.compute_hash(combined)
            cache_key = JudgeCacheKey(
                judge_type="spec_fidelity",
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
        spec_summary: dict[str, Any],
        code_digest: dict[str, Any],
    ) -> str:
        """Build the judge prompt."""
        requirements = spec_summary.get("requirements", [])
        files = code_digest.get("codebase", {}).get("files", [])

        sections = [
            "# Spec Fidelity Evaluation",
            "",
            f"## Requirements ({len(requirements)})",
            "",
        ]

        for i, req in enumerate(requirements, 1):
            if isinstance(req, str):
                sections.append(f"{i}. {req}")
            elif isinstance(req, dict):
                sections.append(f"{i}. {req.get('text', req.get('requirement', str(req)))}")

        sections.extend(
            [
                "",
                f"## Produced Files ({len(files)})",
                "",
            ]
        )

        for f in files[:20]:  # Cap to avoid prompt explosion
            sections.append(f"- {f.get('path', '?')} ({f.get('loc', 0)} LOC)")

        sections.extend(
            [
                "",
                "Evaluate spec fidelity and return your assessment as JSON.",
            ]
        )

        return "\n".join(sections)

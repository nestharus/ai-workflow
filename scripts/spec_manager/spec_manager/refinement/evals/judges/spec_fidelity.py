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
PROMPT_VERSION = "v1"


class SpecFidelityJudge:
    """Evaluates spec coverage and detects hallucinated features."""

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
            schema_cls=SpecFidelityOutput,
            model_id=model_id,
            producer_model_id=producer_model_id,
            allow_self_judge=allow_self_judge,
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
        spec_summary: dict[str, Any],
        code_digest: dict[str, Any],
    ) -> str:
        """Build the judge prompt."""
        requirements = spec_summary.get("requirements", [])
        files = code_digest.get("codebase", {}).get("files", [])
        requirement_texts: list[str] = []
        for req in requirements:
            if isinstance(req, str):
                requirement_texts.append(req)
            elif isinstance(req, dict):
                requirement_texts.append(str(req.get("text", req.get("requirement", str(req)))))

        judge_input = {
            "requirements": requirement_texts,
            "produced_files": [
                {"path": f.get("path", "?"), "loc": f.get("loc", 0)} for f in files[:40]
            ],
        }

        lines = [
            "## OUTPUT CONTRACT",
            "",
            "Assess whether produced code reflects the specification and return a JSON object"
            " with:",
            "- `coverage_estimate`: float 0.0-1.0",
            "- `requirements`: list of requirement coverage objects (`requirement`, `status`,"
            " `evidence`)",
            "- `missing`: list of requirements not implemented",
            "- `hallucinated`: list of implemented behavior not grounded in spec requirements",
            "Valid alternatives are acceptable; do not enforce one prescriptive implementation"
            " pattern."
            "",
            "## INPUT DATA",
            "",
            "```json",
            json.dumps(judge_input, indent=2, sort_keys=True),
            "```",
            "",
            "## OUTPUT FORMAT",
            "",
            "Return strict JSON only (no prose, no markdown):",
            "```json",
            "{",
            '  "coverage_estimate": 0.0,',
            '  "requirements": [',
            '    {"requirement": "...", "status": "implemented", "evidence": "path/to/file.py"}',
            "  ],",
            '  "missing": ["..."],',
            '  "hallucinated": ["..."]',
            "}",
            "```",
        ]
        return "\n".join(lines)

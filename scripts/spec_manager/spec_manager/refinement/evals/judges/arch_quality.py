"""Architecture quality judge module."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey
from spec_manager.refinement.evals.judges.client import JudgeClient
from spec_manager.schemas.eval_arch_judge import ArchJudgeOutput

logger = logging.getLogger(__name__)

AGENT_NAME = "judge-arch-quality"
PROMPT_VERSION = "v1"


class ArchitectureQualityJudge:
    """Evaluates architecture quality using an LLM judge."""

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
            schema_cls=ArchJudgeOutput,
            model_id=model_id,
            producer_model_id=producer_model_id,
            allow_self_judge=allow_self_judge,
        )

    def evaluate(self, digest: dict[str, Any]) -> ArchJudgeOutput:
        """Run architecture quality evaluation on a digest.

        Args:
            digest: Architecture digest dict.

        Returns:
            Validated ArchJudgeOutput.
        """
        prompt = self._build_prompt(digest)

        cache_key = None
        if self.cache is not None:
            input_hash = JudgeCache.compute_hash(json.dumps(digest, sort_keys=True))
            cache_key = JudgeCacheKey(
                judge_type="arch_quality",
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

    def _build_prompt(self, digest: dict[str, Any]) -> str:
        """Build the judge prompt from a digest."""
        topology = digest.get("topology", {})
        components = topology.get("components", [])
        edges = topology.get("edges", [])
        coverage = digest.get("coverage", {})
        l2_findings = digest.get("l2_review", {}).get("final_findings", {})
        judge_input = {
            "topology_summary": {
                "components": len(components),
                "edges": len(edges),
            },
            "components": [
                {
                    "id": comp.get("id", "unknown"),
                    "type": comp.get("type", "unknown"),
                    "summary": comp.get("summary", ""),
                    "depends_on": comp.get("depends_on", []),
                    "public_contracts": comp.get("public_contracts", []),
                }
                for comp in components
            ],
            "coverage": {
                "requirements_total": coverage.get("requirements_total", 0),
                "requirements_mapped": coverage.get("requirements_mapped", 0),
            },
            "l2_review_findings": {
                "BLOCKER": l2_findings.get("BLOCKER", 0),
                "MAJOR": l2_findings.get("MAJOR", 0),
                "MINOR": l2_findings.get("MINOR", 0),
            },
        }
        lines = [
            "## OUTPUT CONTRACT",
            "",
            "Evaluate Architecture Quality and return one JSON object with:",
            "- `scores`: integer 1-5 for cohesion, coupling, completeness, consistency, clarity,"
            " extensibility",
            "- `overall`: integer 1-5",
            "- `strengths`: list of concise strengths",
            "- `risks`: list of objects with `severity`, `component_id`, and `evidence`",
            "- `tradeoffs_noted`: list of tradeoffs",
            "Valid alternatives are acceptable; do not prescribe one fixed design style.",
            "Every risk must cite component or file identifiers from the digest as evidence.",
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
            '  "scores": {',
            '    "cohesion": 1,',
            '    "coupling": 1,',
            '    "completeness": 1,',
            '    "consistency": 1,',
            '    "clarity": 1,',
            '    "extensibility": 1',
            "  },",
            '  "overall": 1,',
            '  "strengths": ["..."],',
            '  "risks": [',
            '    {"severity": "MAJOR", "component_id": "component.id", "evidence": "component.id"}',
            "  ],",
            '  "tradeoffs_noted": ["..."]',
            "}",
            "```",
        ]
        return "\n".join(lines)

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


class ArchitectureQualityJudge:
    """Evaluates architecture quality using an LLM judge."""

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
            schema_cls=ArchJudgeOutput,
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
                prompt_version="v1",
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

        sections = [
            "# Architecture Quality Evaluation",
            "",
            "## Topology Summary",
            f"- Components: {len(components)}",
            f"- Edges: {len(edges)}",
            "",
        ]

        if components:
            sections.append("## Components")
            for comp in components:
                comp_id = comp.get("id", "unknown")
                comp_type = comp.get("type", "unknown")
                summary = comp.get("summary", "")
                deps = comp.get("depends_on", [])
                sections.append(f"### {comp_id} ({comp_type})")
                if summary:
                    sections.append(f"{summary}")
                if deps:
                    sections.append(f"Depends on: {', '.join(deps)}")
                sections.append("")

        sections.extend(
            [
                "## Coverage",
                f"- Requirements total: {coverage.get('requirements_total', 0)}",
                f"- Requirements mapped: {coverage.get('requirements_mapped', 0)}",
                "",
                "## L2 Review Findings",
                f"- BLOCKER: {l2_findings.get('BLOCKER', 0)}",
                f"- MAJOR: {l2_findings.get('MAJOR', 0)}",
                f"- MINOR: {l2_findings.get('MINOR', 0)}",
                "",
                "Evaluate this architecture and return your assessment as JSON.",
            ]
        )

        return "\n".join(sections)

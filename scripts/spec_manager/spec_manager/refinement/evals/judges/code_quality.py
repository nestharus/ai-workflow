"""Code quality judge module."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey
from spec_manager.refinement.evals.judges.client import JudgeClient
from spec_manager.schemas.eval_code_judge import CodeJudgeOutput

logger = logging.getLogger(__name__)

AGENT_NAME = "judge-code-quality"


class CodeQualityJudge:
    """Evaluates code quality using an LLM judge on sampled files."""

    def __init__(
        self,
        workspace: Path,
        cache: JudgeCache | None = None,
        model_id: str = "",
        sample_budget: int = 8,
    ) -> None:
        self.workspace = workspace
        self.cache = cache
        self.model_id = model_id
        self.sample_budget = sample_budget
        self._client = JudgeClient(
            agent_name=AGENT_NAME,
            workspace=workspace,
            schema_cls=CodeJudgeOutput,
        )

    def evaluate(
        self,
        digest: dict[str, Any],
        snapshot_dir: Path | None = None,
    ) -> CodeJudgeOutput:
        """Run code quality evaluation.

        Args:
            digest: Code digest dict.
            snapshot_dir: Optional path to snapshot files for reading content.

        Returns:
            Validated CodeJudgeOutput.
        """
        sampled = self._sample_files(digest)
        file_contents = self._read_files(sampled, snapshot_dir) if snapshot_dir else {}

        prompt = self._build_prompt(digest, sampled, file_contents)

        cache_key = None
        if self.cache is not None:
            input_hash = JudgeCache.compute_hash(json.dumps(digest, sort_keys=True))
            cache_key = JudgeCacheKey(
                judge_type="code_quality",
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

    def _sample_files(self, digest: dict[str, Any]) -> list[dict]:
        """Deterministically sample files for review.

        Strategy:
        1. Top K by LOC (K=3)
        2. Top K by findings (K=3)
        3. Fill remaining budget with other files
        """
        files = digest.get("codebase", {}).get("files", [])
        if not files:
            return []

        selected: dict[str, dict] = {}

        # Top by LOC
        by_loc = sorted(files, key=lambda f: f.get("loc", 0), reverse=True)
        for f in by_loc[:3]:
            selected[f["path"]] = f

        # Top by findings from l3_review
        top_finding_files = digest.get("l3_review", {}).get("top_files", [])
        for f in top_finding_files[:3]:
            path = f.get("path", "")
            if path and path not in selected:
                # Find matching file info
                match = next((x for x in files if x["path"] == path), None)
                if match:
                    selected[path] = match

        # Fill remaining
        remaining = self.sample_budget - len(selected)
        if remaining > 0:
            for f in files:
                if f["path"] not in selected:
                    selected[f["path"]] = f
                    remaining -= 1
                    if remaining <= 0:
                        break

        return list(selected.values())

    def _read_files(
        self, sampled: list[dict], snapshot_dir: Path
    ) -> dict[str, str]:
        """Read file contents from snapshot."""
        contents: dict[str, str] = {}
        for f in sampled:
            path = snapshot_dir / f["path"]
            if path.exists():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    # Truncate very large files
                    if len(text) > 5000:
                        text = text[:5000] + "\n... (truncated)"
                    contents[f["path"]] = text
                except OSError:
                    pass
        return contents

    def _build_prompt(
        self,
        digest: dict[str, Any],
        sampled: list[dict],
        file_contents: dict[str, str],
    ) -> str:
        """Build the judge prompt."""
        totals = digest.get("codebase", {}).get("totals", {})
        l3_findings = digest.get("l3_review", {}).get("final_findings", {})

        sections = [
            "# Code Quality Evaluation",
            "",
            f"Total files: {totals.get('files', 0)}, Total LOC: {totals.get('loc', 0)}",
            f"L3 findings: BLOCKER={l3_findings.get('BLOCKER', 0)}, MAJOR={l3_findings.get('MAJOR', 0)}, MINOR={l3_findings.get('MINOR', 0)}",
            "",
            f"## Sampled Files ({len(sampled)})",
            "",
        ]

        for f in sampled:
            path = f["path"]
            loc = f.get("loc", 0)
            sections.append(f"### {path} ({loc} LOC)")
            if path in file_contents:
                sections.append(f"```\n{file_contents[path]}\n```")
            sections.append("")

        sections.append("Evaluate the code quality and return your assessment as JSON.")
        return "\n".join(sections)

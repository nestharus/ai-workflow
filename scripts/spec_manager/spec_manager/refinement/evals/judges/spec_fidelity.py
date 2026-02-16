"""Spec fidelity judge module."""

from __future__ import annotations

import json
import logging
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey
from spec_manager.refinement.evals.judges.client import JudgeClient
from spec_manager.schemas.eval_spec_fidelity_judge import SpecFidelityOutput

logger = logging.getLogger(__name__)

AGENT_NAME = "judge-spec-fidelity"
PROMPT_VERSION = "v2"


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
        snapshot_dir: Path | None = None,
    ) -> SpecFidelityOutput:
        """Evaluate spec fidelity.

        Args:
            spec_summary: Spec summary with requirements.
            code_digest: Code digest with file list.
            snapshot_dir: Optional path to immutable run snapshot files.

        Returns:
            Validated SpecFidelityOutput.
        """
        sampled = self._sample_files(code_digest)
        file_excerpts = self._read_file_excerpts(sampled, snapshot_dir) if snapshot_dir else {}
        prompt = self._build_prompt(spec_summary, code_digest, sampled, file_excerpts)

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
        sampled_files: list[dict[str, Any]],
        file_excerpts: dict[str, str],
    ) -> str:
        """Build the judge prompt."""
        requirements = spec_summary.get("requirements", [])
        requirement_texts: list[str] = []
        for req in requirements:
            if isinstance(req, str):
                requirement_texts.append(req)
            elif isinstance(req, dict):
                requirement_texts.append(str(req.get("text", req.get("requirement", str(req)))))

        sampled_payload = []
        for file_data in sampled_files:
            path = str(file_data.get("path", ""))
            sampled_payload.append(
                {
                    "path": path,
                    "loc": int(file_data.get("loc", 0) or 0),
                    "sha256": str(file_data.get("sha256", "")),
                    "excerpt": file_excerpts.get(path, ""),
                }
            )

        judge_input = {
            "requirements": requirement_texts,
            "codebase_totals": code_digest.get("codebase", {}).get("totals", {}),
            "sampled_files": sampled_payload,
        }

        lines = [
            "## OUTPUT CONTRACT",
            "",
            (
                "Assess whether produced code reflects the specification and return"
                " a JSON object with:"
            ),
            "- `coverage_estimate`: float 0.0-1.0",
            (
                "- `requirements`: list of requirement coverage objects (`requirement`,"
                " `status`, `evidence`)"
            ),
            (
                "- `missing_requirements`: list of requirements not implemented or"
                " only weakly evidenced"
            ),
            "- `hallucinated_features`: list of implemented behavior not grounded in requirements",
            "",
            "For each requirement entry:",
            "- `status` must be one of: implemented, partial, missing",
            "- `evidence` must cite concrete file paths and symbols/snippets from sampled excerpts",
            "",
            "Reasoning expectations:",
            "- Identify requirements that appear fully implemented (with evidence pointers).",
            "- Identify missing/partial requirements and explain the gap concisely.",
            "- Identify invented behaviors not stated by requirements (hallucinated features).",
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
            '  "missing_requirements": ["..."],',
            '  "hallucinated_features": ["..."]',
            "}",
            "```",
        ]
        return "\n".join(lines)

    def _sample_files(
        self, code_digest: dict[str, Any], *, budget: int = 8
    ) -> list[dict[str, Any]]:
        """Sample files for spec-fidelity evidence gathering."""
        files = code_digest.get("codebase", {}).get("files", [])
        if not isinstance(files, list) or not files:
            return []

        selected: dict[str, dict[str, Any]] = {}

        by_loc = sorted(files, key=lambda f: int(f.get("loc", 0) or 0), reverse=True)
        for file_data in by_loc[:3]:
            path = str(file_data.get("path", ""))
            if path:
                selected[path] = file_data

        top_finding_files = code_digest.get("l3_review", {}).get("top_files", [])
        if isinstance(top_finding_files, list):
            for file_data in top_finding_files[:3]:
                path = str(file_data.get("path", ""))
                if not path or path in selected:
                    continue
                match = next(
                    (candidate for candidate in files if str(candidate.get("path", "")) == path),
                    None,
                )
                if isinstance(match, dict):
                    selected[path] = match

        remaining_pool = [
            file_data
            for file_data in files
            if str(file_data.get("path", "")) and str(file_data.get("path", "")) not in selected
        ]
        random_slots = min(2, budget - len(selected), len(remaining_pool))
        if random_slots > 0:
            run_id = str(code_digest.get("run_id", ""))
            pool = sorted(
                remaining_pool,
                key=lambda file_data: sha256(
                    f"{run_id}:{file_data.get('path', '')}".encode()
                ).hexdigest(),
            )
            for file_data in pool[:random_slots]:
                selected[str(file_data.get("path", ""))] = file_data

        return list(selected.values())

    def _read_file_excerpts(
        self,
        sampled_files: list[dict[str, Any]],
        snapshot_dir: Path,
    ) -> dict[str, str]:
        """Read and condense sampled source files into evidence excerpts."""
        excerpts: dict[str, str] = {}
        for file_data in sampled_files:
            rel_path = str(file_data.get("path", ""))
            if not rel_path:
                continue
            file_path = snapshot_dir / rel_path
            if not file_path.exists():
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                logger.warning(
                    "Failed to read %s for spec fidelity judge", file_path, exc_info=True
                )
                continue
            excerpts[rel_path] = self._extract_excerpt(text)
        return excerpts

    def _extract_excerpt(self, text: str, *, max_chars: int = 3000) -> str:
        """Extract comment/docstring/signature-heavy snippets for judging."""
        lines_text = text.splitlines()
        pattern = re.compile(
            r"^\s*(class\s+\w+|def\s+\w+|async\s+def\s+\w+|#|//|/\*|\*|\"\"\"|'''|function\s+\w+|export\s+)"
        )
        selected = [line for line in lines_text if pattern.match(line)]
        if not selected:
            selected = lines_text[:120]
        excerpt = "\n".join(selected)
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars] + "\n... (truncated)"
        return excerpt

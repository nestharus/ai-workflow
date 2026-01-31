"""Agent execution utilities for spec refinement workflows."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_FILE_OUTPUT_RE = re.compile(r"see `([^`]+)` for details\\.?$", re.IGNORECASE)

logger = logging.getLogger(__name__)


def _maybe_read_file_output(stdout: str) -> str | None:
    """Some model runners write long output to a file and print a short pointer.

    Example: "Architecture mapping complete. See `ARCHITECTURE-MAPPING.md` for details."
    """
    match = _FILE_OUTPUT_RE.search(stdout.strip())
    if not match:
        return None
    rel_path = match.group(1).strip()
    if not rel_path:
        return None

    path = (PROJECT_ROOT / rel_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None

    if not path.exists() or not path.is_file():
        return None

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    # Cleanup the known temporary artifact to avoid polluting the repo root.
    if path.name.upper() == "ARCHITECTURE-MAPPING.MD":
        with contextlib.suppress(OSError):
            path.unlink()

    return content


def _analyze_prompt_structure(prompt: str) -> dict[str, Any]:
    """Analyze prompt structure for Cerebras best practices compliance."""
    lines = prompt.splitlines()
    contract_section_start = None
    content_section_start = None
    output_format_start = None

    for idx, line in enumerate(lines):
        upper = line.upper()
        if ("OUTPUT CONTRACT" in upper or "REQUIRED" in upper) and contract_section_start is None:
            contract_section_start = idx
        elif ("INPUT DATA" in upper or "CONTENT" in upper) and content_section_start is None:
            content_section_start = idx
        elif "OUTPUT FORMAT" in upper and output_format_start is None:
            output_format_start = idx

    return {
        "total_lines": len(lines),
        "contract_starts_at_line": contract_section_start,
        "content_starts_at_line": content_section_start,
        "output_format_starts_at_line": output_format_start,
        "contract_first": contract_section_start is not None and contract_section_start < 10,
    }


def run_agent(
    *,
    agent_name: str,
    prompt: str,
    workspace: Path,
    max_retries: int = 2,
    structured_schema: type[BaseModel] | None = None,
    extra_env: dict[str, str] | None = None,
) -> BaseModel | str:
    """Run an agent via `uv run agents`.

    Uses a prompt file to avoid command-line length limits.
    """
    if structured_schema is not None:
        if extra_env:
            raise ValueError("extra_env is not supported for structured agents.")
        return run_structured_agent(
            agent_name=agent_name,
            prompt=prompt,
            schema=structured_schema,
            workspace=workspace,
        )
    prompts_dir = workspace / "agent_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompts_dir / f"{agent_name}_{int(time.time() * 1000)}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    if agent_name.startswith("glm-"):
        structure_metrics = _analyze_prompt_structure(prompt)
        if not structure_metrics["contract_first"]:
            logger.warning(
                "GLM prompt does not front-load contract rules "
                "(agent=%s, contract_starts_at_line=%s)",
                agent_name,
                structure_metrics["contract_starts_at_line"],
            )

    cmd = [
        "uv",
        "run",
        "agents",
        agent_name,
        "--file",
        str(prompt_file),
        "--project",
        str(PROJECT_ROOT),
    ]

    last_error: RuntimeError | None = None
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}

    for attempt in range(max_retries):
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            last_error = RuntimeError(
                f"Agent failed (agent={agent_name}, exit={result.returncode}). "
                f"stderr={result.stderr.strip()}"
            )
            time.sleep(2**attempt)
            continue

        output = (result.stdout or "").strip()
        if output:
            file_output = _maybe_read_file_output(output)
            return file_output if file_output is not None else output

        last_error = RuntimeError(f"Agent returned empty output (agent={agent_name}).")
        time.sleep(2**attempt)

    raise last_error or RuntimeError(f"Agent failed (agent={agent_name}).")


def run_structured_agent(
    agent_name: str,
    prompt: str,
    schema: type[BaseModel],
    workspace: Path,
) -> BaseModel:
    """Run agent with structured output support."""
    from scripts.agents.structured_output import run_structured_agent as _run

    return _run(agent_name, prompt, schema, workspace)

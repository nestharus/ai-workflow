"""Agent execution utilities for spec refinement workflows."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
    """Run an agent via `uv run agents`.

    Uses a prompt file to avoid command-line length limits.
    """
    prompts_dir = workspace / "agent_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompts_dir / f"{agent_name}_{int(time.time() * 1000)}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

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
    for attempt in range(max_retries):
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
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
            return output

        last_error = RuntimeError(f"Agent returned empty output (agent={agent_name}).")
        time.sleep(2**attempt)

    raise last_error or RuntimeError(f"Agent failed (agent={agent_name}).")

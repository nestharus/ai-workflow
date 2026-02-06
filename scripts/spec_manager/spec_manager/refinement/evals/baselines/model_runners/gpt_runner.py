"""GPT model runner using the agent runner infrastructure.

Uses: uv run agents gpt-labyrinth-implementer --file <prompt>
Model config: gpt-5.3-codex-xhigh (codex exec with xhigh reasoning)
Prompt includes the dense spec and full labyrinth source code.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from spec_manager.refinement.evals.baselines.model_runners.base import ModelOutput
from spec_manager.refinement.evals.baselines.prompt_builder import build_prompt


class GPTRunner:
    """Runs GPT via the agent runner infrastructure."""

    def invoke(
        self, spec_text: str, codebase_path: Path, workspace: Path
    ) -> ModelOutput:
        """Invoke GPT with the spec text.

        Builds a comprehensive prompt with full codebase context,
        then runs via the agents CLI. After execution, writes the
        agent output as labyrinth_setup.py in the codebase directory.
        """
        from spec_manager.refinement.agent_utils import run_agent

        prompt = build_prompt(spec_text, codebase_path)

        # Write prompt to file for debugging/audit
        prompt_file = workspace / "gpt_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        start = time.perf_counter()
        try:
            output = run_agent(
                agent_name="gpt-labyrinth-implementer",
                prompt=prompt,
                workspace=workspace,
            )
            duration = (time.perf_counter() - start) * 1000

            # GPT returns the setup code as text output.
            # Write it to labyrinth_setup.py in the codebase.
            setup_code = _extract_python_code(output)
            if setup_code:
                setup_file = codebase_path / "labyrinth_setup.py"
                setup_file.write_text(setup_code, encoding="utf-8")

            # Capture all changes via git
            diff = self._capture_all_changes(codebase_path)

            return ModelOutput(
                model_name="gpt",
                diff=diff,
                stdout=output,
                duration_ms=duration,
                success=True,
            )
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            return ModelOutput(
                model_name="gpt",
                stderr=str(exc),
                returncode=1,
                duration_ms=duration,
                success=False,
            )

    def _capture_all_changes(self, codebase_path: Path) -> str:
        """Stage all changes and get diff against HEAD."""
        subprocess.run(
            ["git", "add", "-A"],
            cwd=codebase_path,
            capture_output=True,
            check=False,
        )
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=codebase_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout


def _extract_python_code(output: str) -> str:
    """Extract Python code from model output.

    If the output contains a ```python code fence, extract its contents.
    Otherwise, return the full output if it looks like Python code.
    """
    import re

    pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
    match = pattern.search(output)
    if match:
        return match.group(1).strip()

    # If the output starts with typical Python imports/defs, use as-is
    stripped = output.strip()
    if stripped.startswith(("from ", "import ", "def ", '"""', "# ")):
        return stripped

    return ""

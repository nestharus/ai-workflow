"""Opus model runner using Claude Code in agentic tool-use mode.

Opus runs with `-p --dangerously-skip-permissions` which gives it full
tool access (Read, Write, Glob, Grep, Task sub-agents). Instead of
inlining all source code in the prompt (which blows the context window
at L3+), we copy the labyrinth source into the codebase directory and
give Opus a short prompt telling it to explore files with tools.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from spec_manager.refinement.evals.baselines.model_runners.base import ModelOutput

# Labyrinth package source (engine, core, integration, services)
# opus_runner.py is at .../spec_manager/refinement/evals/baselines/model_runners/
# parents[4] = .../spec_manager/ (the inner package dir)
_LABYRINTH_PKG = Path(__file__).resolve().parents[4] / "labyrinth"

_PROMPT = """\
# Task: Implement Labyrinth Integration

You are working in a brownfield Python codebase. Your job is to create \
`labyrinth_setup.py` that sets up a processing pipeline.

## Steps

1. **Read the spec**: Open and read `dense_spec.md` in the current directory. \
It contains the full specification of rules, integration points, and side-effect chains.
2. **Study the framework source**: The labyrinth framework source is in `labyrinth_src/`. \
Read the key files to understand the API:
   - `labyrinth_src/engine/conditions.py` — Condition, ConditionGroup, ConditionOperator, LogicOperator
   - `labyrinth_src/engine/rule.py` — Rule, CompositeRule, CompositionMode
   - `labyrinth_src/core/record.py` — InputRecord
   - `labyrinth_src/integration/integration_points.py` — IntegrationPoint
   - `labyrinth_src/integration/wiring.py` — SideEffectChain
   - `labyrinth_src/integration/pipeline.py` — Pipeline object structure
3. **Write the implementation**: Create `labyrinth_setup.py` that defines \
`setup_labyrinth(pipeline)`.

## Key Imports for labyrinth_setup.py

```python
from spec_manager.labyrinth.engine.conditions import (
    Condition, ConditionGroup, ConditionOperator, LogicOperator,
)
from spec_manager.labyrinth.engine.rule import Rule, CompositeRule, CompositionMode
from spec_manager.labyrinth.core.record import InputRecord
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.wiring import SideEffectChain
```

## Implementation Strategy

For large specs with many rules, split the work into multiple helper files \
to stay organized:
- `labyrinth_setup.py` — main entry point, imports helpers, calls setup_labyrinth
- `rules_group_N.py` — helper modules that define batches of rules

Use the Task tool to delegate work on different rule groups to sub-agents \
in parallel. Each sub-agent should read the relevant section of the spec \
and write its helper file.

## Requirements

- Match ALL conditions EXACTLY (field names, operators, values)
- Match ALL transforms EXACTLY (output field names and values)
- Register rules in dependency order
- Wire ALL side-effect chains
- Create ALL integration points and register their required rules
"""


class OpusRunner:
    """Runs Opus with full tool access so it can explore files and use sub-agents."""

    def invoke(self, spec_text: str, codebase_path: Path, workspace: Path) -> ModelOutput:
        """Invoke Opus with a short prompt pointing to spec + source files.

        Instead of inlining everything in the prompt, copies the labyrinth
        framework source into the codebase dir and lets Opus read files
        with its tools. Opus writes labyrinth_setup.py directly.
        """
        # Copy labyrinth framework source so Opus can read it with tools
        self._copy_labyrinth_source(codebase_path)

        # Ensure spec is written (harness already does this, but be safe)
        spec_file = codebase_path / "dense_spec.md"
        spec_file.write_text(spec_text, encoding="utf-8")

        # Commit the source files so the final diff only shows Opus's work
        self._commit_baseline(codebase_path, "Add labyrinth source for reference")

        # Save prompt for audit
        prompt_file = workspace / "opus_prompt.txt"
        prompt_file.write_text(_PROMPT, encoding="utf-8")

        start = time.perf_counter()
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", "opus", "--dangerously-skip-permissions"],
                input=_PROMPT,
                capture_output=True,
                text=True,
                cwd=codebase_path,
            )
            duration = (time.perf_counter() - start) * 1000

            output = (result.stdout or "").strip()

            # Opus writes labyrinth_setup.py directly via its Write tool.
            # Fallback: if it output code as text instead, extract and write it.
            setup_file = codebase_path / "labyrinth_setup.py"
            if not setup_file.exists() and output:
                code = _extract_python_code(output)
                if code:
                    setup_file.write_text(code, encoding="utf-8")

            diff = self._capture_all_changes(codebase_path)

            return ModelOutput(
                model_name="opus",
                diff=diff,
                stdout=output,
                stderr=(result.stderr or "").strip(),
                returncode=result.returncode,
                duration_ms=duration,
                success=result.returncode == 0,
            )
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            return ModelOutput(
                model_name="opus",
                stderr=str(exc),
                returncode=1,
                duration_ms=duration,
                success=False,
            )

    def _commit_baseline(self, codebase_path: Path, message: str) -> None:
        """Stage and commit all current files."""
        subprocess.run(
            ["git", "add", "-A"],
            cwd=codebase_path,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "commit", "-m", message, "--no-gpg-sign"],
            cwd=codebase_path,
            capture_output=True,
            check=False,
        )

    def _copy_labyrinth_source(self, codebase_path: Path) -> None:
        """Copy labyrinth framework source into codebase for Opus to read."""
        dest = codebase_path / "labyrinth_src"
        if dest.exists():
            shutil.rmtree(dest)

        if not _LABYRINTH_PKG.exists():
            return

        for subdir in ("core", "engine", "integration", "services"):
            src = _LABYRINTH_PKG / subdir
            if src.exists():
                shutil.copytree(
                    src,
                    dest / subdir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    dirs_exist_ok=True,
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
    """Extract Python code from model output (fallback if Opus didn't write the file)."""
    pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
    match = pattern.search(output)
    if match:
        return match.group(1).strip()

    stripped = output.strip()
    if stripped.startswith(("from ", "import ", "def ", '"""', "# ")):
        return stripped

    return ""

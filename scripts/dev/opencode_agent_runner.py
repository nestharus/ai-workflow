#!/usr/bin/env python3
"""Run an OpenCode sub-agent via `opencode run --agent <name> "<prompt>"`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for OpenCode agent runner."""
    parser = argparse.ArgumentParser(description="Run an OpenCode sub-agent")
    parser.add_argument("--agent", required=True, type=str, help="Agent name")
    parser.add_argument("--prompt", required=True, type=str, help="Prompt to pass to the agent")
    return parser.parse_args()


def run_agent(agent: str, prompt: str, *, stream_output: bool = True) -> tuple[int, str]:
    """Run an OpenCode agent and return exit code and captured output.

    Args:
        agent: Name of the agent to run.
        prompt: Prompt to pass to the agent.
        stream_output: If True, also write stdout to sys.stdout (for CLI usage).

    Returns:
        Tuple of (exit_code, stdout_output).
    """
    command = [str(PROJECT_ROOT / "opencode"), "run", "--agent", agent, prompt]
    result = subprocess.run(command, capture_output=True, text=True, cwd=PROJECT_ROOT)

    if stream_output and result.stdout:
        sys.stdout.write(result.stdout)
    if result.returncode != 0 and result.stderr:
        sys.stderr.write(result.stderr)

    return result.returncode, result.stdout or ""


def main() -> int:
    """Main entry point for OpenCode agent runner."""
    try:
        args = parse_args()
        exit_code, _ = run_agent(args.agent, args.prompt)
    except Exception as exc:  # pragma: no cover - defensive catch-all
        sys.stderr.write(f"{exc}\n")
        return 1
    else:
        return exit_code


if __name__ == "__main__":
    sys.exit(main())

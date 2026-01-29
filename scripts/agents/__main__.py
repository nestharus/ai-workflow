"""Execute agents or models via CLI.

Usage:
    uv run agents <agent_name> <prompt>
    uv run agents --model <model_name> <prompt>
    uv run agents <agent_name> --file <prompt_file>
    echo "prompt" | uv run agents <agent_name>

Examples:
    uv run agents implementor task_001.md
    uv run agents --model claude-sonnet "Write a haiku"
    echo "Help me" | uv run agents my-agent
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.agents.config import load_agents, load_models


def main() -> int:
    """Execute an agent or model."""
    parser = argparse.ArgumentParser(
        description="Execute an agent or model",
        prog="uv run agents",
    )
    parser.add_argument("agent", nargs="?", help="Agent name (without .md extension)")
    parser.add_argument("--model", "-m", help="Execute model directly instead of agent")
    parser.add_argument("--file", "-f", type=Path, help="Read prompt from file instead of argument")
    parser.add_argument(
        "--project",
        "-p",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )

    # Use parse_known_args to capture everything after agent name as prompt
    # This allows passing flags like --loop --tasks-file without quoting
    args, remaining = parser.parse_known_args()

    # When using --model, the prompt is the first positional (captured as agent)
    # When using agent mode, remaining args form the prompt (supports flags like --loop)
    prompt_arg = args.agent if args.model else " ".join(remaining) if remaining else None

    # Get prompt from argument, file, or stdin
    if args.file:
        prompt = args.file.read_text()
    elif prompt_arg:
        prompt = prompt_arg
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read()
    else:
        parser.error("Prompt required: provide as argument, --file, or via stdin")

    project_root = args.project.resolve()

    # Load configurations
    models = load_models(project_root / ".agents/models")

    # Direct model execution
    if args.model:
        model = models.get(args.model)
        if not model:
            print(f"Error: Model not found: {args.model}", file=sys.stderr)
            return 1

        if model.prompt_mode == "arg":
            result = subprocess.run(
                [model.command, *model.args, prompt],
                capture_output=False,
                text=True,
                cwd=project_root,
            )
        else:
            result = subprocess.run(
                [model.command, *model.args],
                input=prompt,
                capture_output=False,
                text=True,
                cwd=project_root,
            )
        return result.returncode

    # Agent execution
    if not args.agent:
        parser.error("Either agent name or --model required")

    agents = load_agents(project_root / ".agents/agents")

    agent = agents.get(args.agent)

    if not agent:
        print(f"Error: Agent not found: {args.agent}", file=sys.stderr)
        return 1
    if not agent.model:
        print(f"Error: Agent missing model: {args.agent}", file=sys.stderr)
        return 1

    model = models.get(agent.model)
    if not model:
        print(f"Error: Model not found: {agent.model}", file=sys.stderr)
        return 1

    # Build full prompt with agent instructions
    full_prompt = f"{agent.instructions}\n\n{prompt}"

    print(
        f"[agent-exec] model={agent.model} cmd={model.command} args={model.args} "
        f"mode={model.prompt_mode} prompt_len={len(full_prompt)}",
        file=sys.stderr,
    )

    # Execute based on prompt_mode
    if model.prompt_mode == "arg":
        print(
            f"[agent-exec] launching: {model.command} {' '.join(model.args)} <prompt>",
            file=sys.stderr,
        )
        result = subprocess.run(
            [model.command, *model.args, full_prompt],
            capture_output=False,
            text=True,
            cwd=project_root,
        )
    else:
        result = subprocess.run(
            [model.command, *model.args],
            input=full_prompt,
            capture_output=False,
            text=True,
            cwd=project_root,
        )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

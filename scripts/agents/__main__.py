"""Execute agents or models via CLI.

Usage:
    uv run python -m scripts.agents <agent_name> <prompt>
    uv run python -m scripts.agents --model <model_name> <prompt>
    uv run python -m scripts.agents <agent_name> --file <prompt_file>
    echo "prompt" | uv run python -m scripts.agents <agent_name>

Examples:
    uv run python -m scripts.agents router "Is this ambiguous?"
    uv run python -m scripts.agents implementor task_001.md
    uv run python -m scripts.agents --model claude-sonnet "Write a haiku"
    echo "Help me" | uv run python -m scripts.agents my-agent
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.agents.router import load_agents, load_models, route_prompt


def main() -> int:
    """Execute an agent or model."""
    parser = argparse.ArgumentParser(
        description="Execute an agent or model",
        prog="uv run python -m scripts.agents",
    )
    parser.add_argument("agent", nargs="?", help="Agent name (without .md extension)")
    parser.add_argument("prompt", nargs="?", help="Prompt to send")
    parser.add_argument(
        "--model", "-m", help="Execute model directly instead of agent"
    )
    parser.add_argument(
        "--file", "-f", type=Path, help="Read prompt from file instead of argument"
    )
    parser.add_argument(
        "--project",
        "-p",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )

    args = parser.parse_args()

    # When using --model, the prompt is the first positional (captured as agent)
    # When using agent mode, both agent and prompt are positional
    if args.model:
        # In model mode: first positional is the prompt
        prompt_arg = args.agent
    else:
        prompt_arg = args.prompt

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

    # Agent execution with routing
    if not args.agent:
        parser.error("Either agent name or --model required")

    agents = load_agents(project_root / ".agents/agents")

    agent = agents.get(args.agent)
    router = agents.get("router")

    if not agent:
        print(f"Error: Agent not found: {args.agent}", file=sys.stderr)
        return 1

    if not router:
        print("Error: Router agent not found (.agents/agents/router.md)", file=sys.stderr)
        return 1

    # Route to find best model
    rule = route_prompt(agent, router, models, prompt)
    if not rule:
        print("Error: No routing rule matched the prompt", file=sys.stderr)
        return 1

    model = models.get(rule.model)
    if not model:
        print(f"Error: Model not found: {rule.model}", file=sys.stderr)
        return 1

    # Build full prompt with agent instructions
    full_prompt = f"{agent.instructions}\n\n{prompt}"

    # Execute based on prompt_mode
    if model.prompt_mode == "arg":
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

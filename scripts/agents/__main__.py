"""Execute agents or models via CLI.

Usage:
    uv run agents <agent_name> <prompt>
    uv run agents --model <model_name> <prompt>
    uv run agents --agent-file <path.md> <prompt>
    uv run agents <agent_name> --file <prompt_file>
    echo "prompt" | uv run agents <agent_name>

Examples:
    uv run agents implementor task_001.md
    uv run agents --model claude-sonnet "Write a haiku"
    uv run agents --agent-file .claude/agents/workflow/exception-handler.md --file prompt.md
    echo "Help me" | uv run agents my-agent
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from scripts.agents.config import (
    AgentConfig,
    ModelConfig,
    load_agent_file,
    load_agents,
    load_models,
)


def _build_cmd(model: ModelConfig) -> list[str]:
    """Build command list from model config, splitting command string on spaces."""
    return [*shlex.split(model.command), *model.args]


def _execute_model(
    model: ModelConfig, prompt: str, project_root: Path
) -> subprocess.CompletedProcess[str]:
    """Execute a model with the given prompt. Returns the subprocess result."""
    cmd = _build_cmd(model)

    if model.prompt_mode == "arg":
        if len(prompt) > 100_000:
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, dir=project_root
            ) as tmp:
                tmp.write(prompt)
                prompt_path = tmp.name
            print(
                f"[agent-exec] launching: {' '.join(cmd)} (prompt via file: {prompt_path})",
                file=sys.stderr,
            )
            try:
                result = subprocess.run(
                    [*cmd, f"Follow the instructions in {prompt_path}"],
                    capture_output=False,
                    text=True,
                    cwd=project_root,
                )
            finally:
                Path(prompt_path).unlink(missing_ok=True)
        else:
            print(
                f"[agent-exec] launching: {' '.join(cmd)} <prompt>",
                file=sys.stderr,
            )
            result = subprocess.run(
                [*cmd, prompt],
                capture_output=False,
                text=True,
                cwd=project_root,
            )
    else:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=False,
            text=True,
            cwd=project_root,
        )
    return result


def _resolve_agent(args: argparse.Namespace, project_root: Path) -> AgentConfig | None:
    """Resolve agent from --agent-file path or agent name. Returns AgentConfig or None."""
    if args.agent_file:
        agent_path = Path(args.agent_file)
        if not agent_path.is_absolute():
            agent_path = project_root / agent_path
        if not agent_path.exists():
            print(f"Error: Agent file not found: {agent_path}", file=sys.stderr)
            return None
        return load_agent_file(agent_path)

    if not args.agent:
        return None

    agents = load_agents(project_root / ".agents/agents")
    return agents.get(args.agent)


def main() -> int:
    """Execute an agent or model."""
    parser = argparse.ArgumentParser(
        description="Execute an agent or model",
        prog="uv run agents",
    )
    parser.add_argument("agent", nargs="?", help="Agent name (without .md extension)")
    parser.add_argument("--model", "-m", help="Execute model directly instead of agent")
    parser.add_argument(
        "--agent-file", "-a", type=str, help="Path to agent .md file (any location)"
    )
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

    # When using --model or --agent-file, the prompt is the first positional (captured as agent)
    # When using agent mode, remaining args form the prompt (supports flags like --loop)
    if args.model or args.agent_file:
        prompt_arg = args.agent if args.agent else (" ".join(remaining) if remaining else None)
    else:
        prompt_arg = " ".join(remaining) if remaining else None

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

    # Direct model execution (no agent instructions)
    if args.model and not args.agent_file:
        model = models.get(args.model)
        if not model:
            print(f"Error: Model not found: {args.model}", file=sys.stderr)
            return 1
        return _execute_model(model, prompt, project_root).returncode

    # Agent execution (from name or file path)
    agent = _resolve_agent(args, project_root)

    if not agent:
        if args.agent_file:
            return 1  # error already printed
        if args.agent:
            print(f"Error: Agent not found: {args.agent}", file=sys.stderr)
            return 1
        parser.error("Either agent name, --agent-file, or --model required")

    if not agent.model:
        print(f"Error: Agent missing model: {agent.name}", file=sys.stderr)
        return 1

    model = models.get(agent.model)
    if not model:
        print(f"Error: Model not found: {agent.model}", file=sys.stderr)
        return 1

    # Build full prompt with agent instructions
    full_prompt = f"{agent.instructions}\n\n{prompt}"

    print(
        f"[agent-exec] agent={agent.name} model={agent.model} cmd={model.command} "
        f"args={model.args} mode={model.prompt_mode} prompt_len={len(full_prompt)}",
        file=sys.stderr,
    )

    return _execute_model(model, full_prompt, project_root).returncode


if __name__ == "__main__":
    sys.exit(main())

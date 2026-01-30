"""CLI to run Claude sub-agents defined in .claude/agents.

Parses YAML frontmatter from an agent markdown file and invokes the local
`./claude` wrapper with the appropriate flags.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for Claude agent runner."""
    parser = argparse.ArgumentParser(description="Run a Claude sub-agent defined in .claude/agents")
    parser.add_argument(
        "--agent",
        required=True,
        type=str,
        help="Name of the Claude agent to run",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        type=str,
        help="Prompt to pass to the agent",
    )
    return parser.parse_args()


def load_agent(agent_name: str) -> tuple[dict[str, Any], str]:
    """Load and parse a Claude agent definition from markdown file.

    Args:
        agent_name: Name of the agent to load.

    Returns:
        Tuple of (frontmatter_dict, system_prompt_string).
    """
    project_root = Path(__file__).resolve().parents[2]
    agent_path = project_root / "claude" / "agents" / f"{agent_name}.md"

    try:
        content = agent_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - path error case
        raise FileNotFoundError(f"Agent '{agent_name}' not found in .claude/agents/") from exc

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Invalid frontmatter in agent file")

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise ValueError("Invalid YAML frontmatter") from exc

    if not isinstance(frontmatter, dict):
        raise TypeError("Invalid frontmatter in agent file")

    for key in ("tools", "model"):
        if key not in frontmatter:
            raise KeyError(f"Missing required frontmatter field: {key}")

    system_prompt = parts[2].strip()
    return frontmatter, system_prompt


def build_command(frontmatter: dict[str, Any], system_prompt: str) -> list[str]:
    """Build command line arguments for Claude CLI invocation.

    Args:
        frontmatter: Agent configuration dict.
        system_prompt: System prompt for the agent.

    Returns:
        List of command line arguments. Prompt should be passed via stdin.
    """
    tools_field = frontmatter.get("tools", "")

    # Handle None, string format ("Read, Write"), list format, and dict format ({write: true})
    if tools_field is None:
        tools_list = []
    elif isinstance(tools_field, dict):
        tools_list = [tool for tool, enabled in tools_field.items() if enabled]
    elif isinstance(tools_field, list):
        tools_list = [str(tool).strip() for tool in tools_field if str(tool).strip()]
    else:
        tools_list = [tool.strip() for tool in str(tools_field).split(",") if tool.strip()]

    disallowed_field = frontmatter.get("disallowedTools", "")

    # Handle None, string format, list format, and dict format for disallowed tools
    if disallowed_field is None:
        disallowed_tools_list = []
    elif isinstance(disallowed_field, dict):
        disallowed_tools_list = [tool for tool, disabled in disallowed_field.items() if disabled]
    elif isinstance(disallowed_field, list):
        disallowed_tools_list = [
            str(tool).strip() for tool in disallowed_field if str(tool).strip()
        ]
    else:
        disallowed_tools_list = [
            tool.strip() for tool in str(disallowed_field).split(",") if tool.strip()
        ]

    command = [
        "claude",
        "-p",
        "--model",
        str(frontmatter["model"]),
        "--system-prompt",
        system_prompt,
    ]

    if tools_list:
        command.extend(["--allowedTools", ",".join(tools_list)])

    if disallowed_tools_list:
        command.extend(["--disallowedTools", ",".join(disallowed_tools_list)])

    # Prompt is passed via stdin, not as positional argument
    return command


def run_command(
    command: list[str], *, stream_output: bool = True, stdin_input: str | None = None
) -> tuple[int, str]:
    """Run a command and return exit code and captured output.

    Args:
        command: Command to execute as list of strings.
        stream_output: If True, also write stdout to sys.stdout (for CLI usage).
        stdin_input: Optional string to pass to the command via stdin.

    Returns:
        Tuple of (exit_code, stdout_output).
    """
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=project_root,
        check=False,
        input=stdin_input,
    )

    if stream_output and result.stdout:
        sys.stdout.write(result.stdout)

    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.returncode, result.stdout or ""

    return 0, result.stdout or ""


def main() -> int:
    """Main entry point for Claude agent runner."""
    try:
        args = parse_args()
        frontmatter, system_prompt = load_agent(args.agent)
        command = build_command(frontmatter, system_prompt)
        exit_code, _ = run_command(command, stdin_input=args.prompt)
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except KeyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        return exc.returncode or 1
    except Exception as exc:  # pragma: no cover - defensive catch-all
        sys.stderr.write(f"{exc}\n")
        return 1
    else:
        return exit_code


if __name__ == "__main__":
    sys.exit(main())

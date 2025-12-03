"""CLI to run Claude sub-agents defined in .claude/agents.

Parses YAML frontmatter from an agent markdown file and invokes the local
`./claude` wrapper with the appropriate flags.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


def parse_args() -> argparse.Namespace:
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


def load_agent(agent_name: str) -> tuple[dict, str]:
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
        raise ValueError("Invalid frontmatter in agent file")

    for key in ("tools", "model"):
        if key not in frontmatter:
            raise KeyError(f"Missing required frontmatter field: {key}")

    system_prompt = parts[2].strip()
    return frontmatter, system_prompt


def build_command(frontmatter: dict, system_prompt: str, prompt: str) -> list[str]:
    tools_field = frontmatter.get("tools", "")
    tools_list = [tool.strip() for tool in str(tools_field).split(",") if tool.strip()]

    disallowed_field = frontmatter.get("disallowedTools", "")
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
        "--allowedTools",
        *tools_list,
    ]

    if disallowed_tools_list:
        command.extend(["--disallowedTools", *disallowed_tools_list])

    command.extend(["--prompt", prompt])
    return command


def run_command(command: list[str]) -> int:
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=project_root,
        check=False,
    )

    if result.stdout:
        sys.stdout.write(result.stdout)

    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.returncode

    return 0


def main() -> int:
    try:
        args = parse_args()
        frontmatter, system_prompt = load_agent(args.agent)
        command = build_command(frontmatter, system_prompt, args.prompt)
        return run_command(command)
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


if __name__ == "__main__":
    sys.exit(main())

"""CLI runner for .tasks system agents with routing threshold support.

This module provides a CLI for running agents from the .tasks system. Each agent
defines its own `routing_thresholds` in its frontmatter to specify which
runner/model combination to use for different prompt character counts.

Routing Logic:
    When `--prompt-chars` is provided, the agent's `routing_thresholds` from its
    frontmatter are consulted. The routing thresholds are iterated in order, and
    the first threshold where `prompt_chars <= max_chars` (or `max_chars is None`)
    determines the model and provider to use.

Fallback Behavior:
    If `--prompt-chars` is omitted, or if the agent has no routing_thresholds,
    the agent's default model and provider from its frontmatter are used.

Example usage:
    uv run agent.tasks --agent implementor --prompt 'task' --prompt-chars 5000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.dev.agent_runner import AgentRunner

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the tasks agent runner.

    Returns:
        Parsed arguments namespace with agent, prompt, and optional prompt_chars.
    """
    parser = argparse.ArgumentParser(
        description="Run a .tasks system agent with routing threshold support"
    )
    parser.add_argument(
        "--agent",
        required=True,
        type=str,
        help="Name of the agent to run (without .md extension)",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        type=str,
        help="Prompt to pass to the agent",
    )
    parser.add_argument(
        "--prompt-chars",
        type=int,
        default=None,
        help="Number of characters in the prompt for routing logic",
    )
    return parser.parse_args()


def _get_agent_runner() -> type[AgentRunner]:
    """Import AgentRunner class lazily to avoid circular imports."""
    from scripts.dev.agent_runner import AgentRunner

    return AgentRunner


def main() -> int:
    """Run a .tasks system agent with optional routing based on prompt character count.

    When `--prompt-chars` is provided, the agent's `routing_thresholds` from its
    frontmatter are automatically consulted to select the appropriate model and
    provider. When omitted, the agent's default model and provider are used.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    try:
        args = parse_args()

        config_path = PROJECT_ROOT / ".tasks.yaml"

        AgentRunner = _get_agent_runner()

        # Log routing status if prompt_chars was provided
        if args.prompt_chars is not None:
            sys.stderr.write(f"Routing enabled with {args.prompt_chars} characters\n")

        # Create runner with prompt_chars for automatic routing
        runner = AgentRunner.from_agent_name(
            args.agent, config_path, prompt_chars=args.prompt_chars
        )

        # Execute the agent
        output = runner.run(args.prompt)
        if output:
            sys.stdout.write(output)

    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except KeyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except Exception as exc:  # pragma: no cover - defensive catch-all
        sys.stderr.write(f"{exc}\n")
        return 1
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""Code generation state machine CLI.

Usage:
    uv run codegen init <workspace>
    uv run codegen next <workspace>
    uv run codegen process <workspace>
    uv run codegen status <workspace>

Workspace should contain state.yaml from planner.
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Validation errors: user/input issues that can be fixed by correcting input
# Includes FileNotFoundError as missing files (e.g., state.yaml) are user-fixable validation issues
VALIDATION_ERRORS = (ValueError, KeyError, TypeError, FileNotFoundError)


def _build_error_response(e: Exception) -> dict[str, Any]:
    """Build a standardized error response JSON for exception handling.

    Args:
        e: The exception that was raised

    Returns:
        Dictionary with error details including type, message, and category
    """
    error_type = e.__class__.__name__
    error_category = "validation" if isinstance(e, VALIDATION_ERRORS) else "system"

    return {
        "ok": False,
        "error": str(e),
        "error_type": error_type,
        "error_category": error_category,
    }


def handle_command_errors(
    command_name: str,
) -> Callable[[Callable[[Path], int]], Callable[[Path], int]]:
    """Decorator to handle command errors uniformly.

    Catches VALIDATION_ERRORS and logs them with logger.error, catches general
    Exception and logs with logger.exception. Both cases print JSON error response
    and return 1.

    Args:
        command_name: Name of the command for logging purposes

    Returns:
        Decorator function that wraps command functions
    """

    def _handle_error(e: Exception, workspace: Path) -> int:
        """Handle error by logging, printing JSON response, and returning exit code."""
        if isinstance(e, VALIDATION_ERRORS):
            logger.error("%s failed for workspace %s: %s", command_name, workspace, e)
        else:
            logger.exception("%s failed for workspace %s", command_name, workspace)
        print(json.dumps(_build_error_response(e)))
        return 1

    def decorator(func: Callable[[Path], int]) -> Callable[[Path], int]:
        @functools.wraps(func)
        def wrapper(workspace: Path) -> int:
            try:
                return func(workspace)
            except Exception as e:
                return _handle_error(e, workspace)

        return wrapper

    return decorator


@handle_command_errors("init_command")
def init_command(workspace: Path) -> int:
    """Initialize codegen from existing design state.

    Args:
        workspace: Path to workspace with state.yaml

    Returns:
        0 on success, 1 on failure
    """
    from scripts.planner.state import DesignState

    state = DesignState.load(workspace)

    # Switch to execute-plan workflow
    state.workflow = "execute-plan"
    state.phase = "init"
    state.save()

    print(
        json.dumps(
            {
                "ok": True,
                "workspace": str(workspace),
                "ticket_id": state.ticket_id,
            }
        )
    )
    return 0


@handle_command_errors("next_command")
def next_command(workspace: Path) -> int:
    """Get next action for orchestrator.

    Args:
        workspace: Path to workspace with state.yaml

    Returns:
        0 on success, 1 on failure
    """
    from scripts.codegen.execute_plan import ExecutePlanStateMachine
    from scripts.planner.state import DesignState

    state = DesignState.load(workspace)
    machine = ExecutePlanStateMachine(state)
    machine.next_action()

    next_action = state.read_next_action()
    print(
        json.dumps(
            {
                **next_action,
                "ok": True,
            }
        )
    )
    return 0


@handle_command_errors("process_command")
def process_command(workspace: Path) -> int:
    """Process agent output.

    Args:
        workspace: Path to workspace with state.yaml

    Returns:
        0 on success, 1 on failure
    """
    from scripts.codegen.execute_plan import ExecutePlanStateMachine
    from scripts.planner.state import DesignState

    state = DesignState.load(workspace)
    machine = ExecutePlanStateMachine(state)
    machine.process_agent_output()

    next_action = state.read_next_action()
    print(
        json.dumps(
            {
                **next_action,
                "ok": True,
            }
        )
    )
    return 0


@handle_command_errors("status_command")
def status_command(workspace: Path) -> int:
    """Get execution status.

    Args:
        workspace: Path to workspace with state.yaml

    Returns:
        0 on success, 1 on failure
    """
    from scripts.planner.state import DesignState

    state = DesignState.load(workspace)

    total_units = len(state.units)
    completed = sum(
        len(layer.get("units_completed", [])) for layer in state.layer_execution.values()
    )
    failed = len(state.failures)

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": state.ticket_id,
                "phase": state.phase,
                "current_layer": state.current_layer,
                "total_units": total_units,
                "completed_units": completed,
                "failed_units": failed,
                "worktree_path": state.worktree_path,
                "pr_url": state.pr_url,
            }
        )
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Command line arguments (None for sys.argv)

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Code generation state machine CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize codegen")
    init_parser.add_argument("workspace", type=Path, help="Workspace path")

    # next command
    next_parser = subparsers.add_parser("next", help="Get next action")
    next_parser.add_argument("workspace", type=Path, help="Workspace path")

    # process command
    process_parser = subparsers.add_parser("process", help="Process agent output")
    process_parser.add_argument("workspace", type=Path, help="Workspace path")

    # status command
    status_parser = subparsers.add_parser("status", help="Get status")
    status_parser.add_argument("workspace", type=Path, help="Workspace path")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command line arguments (None for sys.argv)

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    args = parse_args(argv)

    if args.command == "init":
        return init_command(args.workspace)
    if args.command == "next":
        return next_command(args.workspace)
    if args.command == "process":
        return process_command(args.workspace)
    if args.command == "status":
        return status_command(args.workspace)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

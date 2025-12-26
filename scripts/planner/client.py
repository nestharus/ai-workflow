"""Planning state machine CLI.

Usage:
    uv run planner init <ticket-id> [--workflow <create-plan|update-plan|refactor-plan|analyze>]
    uv run planner next <workspace>
    uv run planner process <workspace>
    uv run planner status <workspace>

All communication happens through files in the workspace directory:
    .tmp/design/<ticket>/
    ├── state.yaml          # Main state
    ├── next_action.yaml    # What orchestrator should do
    ├── agent_input.yaml    # Input for agent
    └── agent_output.yaml   # Output from agent
"""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from scripts.planner.analyze import AnalyzeStateMachine
    from scripts.planner.create_plan import CreatePlanStateMachine
    from scripts.planner.refactor_plan import RefactorPlanStateMachine
    from scripts.planner.state import DesignState
    from scripts.planner.update_plan import UpdatePlanStateMachine

    StateMachineType = (
        CreatePlanStateMachine
        | UpdatePlanStateMachine
        | AnalyzeStateMachine
        | RefactorPlanStateMachine
    )


def _get_state_machine(state: DesignState) -> StateMachineType:
    """Map workflow string to the corresponding StateMachine instance.

    Args:
        state: The DesignState containing the workflow type.

    Returns:
        An instantiated state machine for the given workflow.

    Raises:
        ValueError: If the workflow type is unknown.
    """
    from scripts.planner.analyze import AnalyzeStateMachine
    from scripts.planner.create_plan import CreatePlanStateMachine
    from scripts.planner.refactor_plan import RefactorPlanStateMachine
    from scripts.planner.update_plan import UpdatePlanStateMachine

    workflow_to_machine: dict[str, type[StateMachineType]] = {
        "create-plan": CreatePlanStateMachine,
        "update-plan": UpdatePlanStateMachine,
        "analyze": AnalyzeStateMachine,
        "refactor-plan": RefactorPlanStateMachine,
    }

    machine_class = workflow_to_machine.get(state.workflow)
    if machine_class is None:
        raise ValueError(f"Unknown workflow: {state.workflow}")

    return machine_class(state)


def init_command(
    ticket_id: str,
    workflow: Literal["create-plan", "update-plan", "refactor-plan", "analyze"] = "create-plan",
    paths: list[str] | None = None,
    update_prompt: str | None = None,
) -> int:
    """Initialize state for a new ticket.

    Creates workspace directory and initial state.yaml.
    Fetches ticket info from Linear.

    Args:
        ticket_id: Linear ticket ID (e.g., NES-123)
        workflow: Workflow type (create-plan or update-plan)
        paths: Paths to analyze (for refactor-plan/analyze workflow)
        update_prompt: Update prompt text (for update-plan workflow)

    Returns:
        0 on success, 1 on failure
    """
    from scripts.clients.linear_client import LinearClient
    from scripts.planner.state import DesignState, Unit

    normalized_paths: list[str] = []
    if isinstance(paths, str):
        normalized_paths = shlex.split(paths)
    elif paths:
        if len(paths) == 1 and isinstance(paths[0], str) and " " in paths[0]:
            normalized_paths = shlex.split(paths[0])
        else:
            normalized_paths = list(paths)

    # Create workspace
    workspace = Path(f".tmp/design/{ticket_id}")
    workspace.mkdir(parents=True, exist_ok=True)

    # Fetch ticket
    client = LinearClient()
    issue = client.get_issue(ticket_id)

    # Create initial state
    state = DesignState(
        workspace=workspace,
        ticket_id=ticket_id,
        title=issue.get("title", ""),
        url=issue.get("url", ""),
        workflow=workflow,
        phase="init",
        paths=normalized_paths,
    )
    if workflow == "update-plan":
        if update_prompt:
            state.update_source = "inline_prompt"
            state.update_prompt_text = update_prompt
        else:
            state.update_source = "pr_comments"

    # Create root unit
    state.units["root"] = Unit(
        id="root",
        description=issue.get("description", ""),
        operation="CREATE",
        status="pending",
    )
    state.branches["main"].layers[0] = ["root"]

    state.add_history("init", {"ticket_id": ticket_id, "workflow": workflow})
    state.save()

    # Output result
    print(
        json.dumps(
            {
                "ok": True,
                "workspace": str(workspace),
                "ticket_id": ticket_id,
                "workflow": workflow,
            }
        )
    )
    return 0


def next_command(workspace: Path) -> int:
    """Get the next action for the orchestrator.

    Reads state.yaml, determines next action, writes:
    - next_action.yaml (for orchestrator)
    - agent_input.yaml (for agent, if applicable)

    Args:
        workspace: Path to workspace directory

    Returns:
        0 on success, 1 on failure
    """
    from scripts.planner.state import DesignState

    state = DesignState.load(workspace)

    try:
        machine = _get_state_machine(state)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1

    machine.next_action()

    # Read what was written and output
    next_action = state.read_next_action()
    print(json.dumps({"ok": True, **next_action}))
    return 0


def process_command(workspace: Path) -> int:
    """Process agent output and determine next action.

    Reads agent_output.yaml, updates state, writes next_action.yaml.

    Args:
        workspace: Path to workspace directory

    Returns:
        0 on success, 1 on failure
    """
    from scripts.planner.state import DesignState

    state = DesignState.load(workspace)

    try:
        machine = _get_state_machine(state)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1

    machine.process_agent_output()

    next_action = state.read_next_action()
    print(json.dumps({"ok": True, **next_action}))
    return 0


def status_command(workspace: Path) -> int:
    """Get current state status.

    Args:
        workspace: Path to workspace directory

    Returns:
        0 on success, 1 on failure
    """
    from scripts.planner.state import DesignState

    state = DesignState.load(workspace)

    total_units = len(state.units)
    atomic_units = sum(1 for u in state.units.values() if u.status == "atomic")
    pending_units = sum(1 for u in state.units.values() if u.status == "pending")
    decomposed_units = sum(1 for u in state.units.values() if u.status == "decomposed")

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": state.ticket_id,
                "workflow": state.workflow,
                "phase": state.phase,
                "current_layer": state.current_layer,
                "total_units": total_units,
                "atomic_units": atomic_units,
                "pending_units": pending_units,
                "decomposed_units": decomposed_units,
                "max_layer": (
                    max(state.branches["main"].layers.keys())
                    if state.branches["main"].layers
                    else 0
                ),
            }
        )
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Planning state machine CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize state for a ticket",
    )
    init_parser.add_argument(
        "ticket_id",
        help="Linear ticket ID (e.g., NES-123)",
    )
    init_parser.add_argument(
        "--workflow",
        default="create-plan",
        choices=["create-plan", "update-plan", "refactor-plan", "analyze"],
        help="Workflow type",
    )
    init_parser.add_argument(
        "--paths",
        nargs="+",
        help="Paths to analyze (for refactor-plan/analyze workflow)",
    )
    init_parser.add_argument(
        "--update-prompt",
        help="Update prompt text (for update-plan workflow)",
    )

    # next command
    next_parser = subparsers.add_parser(
        "next",
        help="Get next action (writes next_action.yaml)",
    )
    next_parser.add_argument(
        "workspace",
        type=Path,
        help="Path to workspace directory",
    )

    # process command
    process_parser = subparsers.add_parser(
        "process",
        help="Process agent output (reads agent_output.yaml)",
    )
    process_parser.add_argument(
        "workspace",
        type=Path,
        help="Path to workspace directory",
    )

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Get current state status",
    )
    status_parser.add_argument(
        "workspace",
        type=Path,
        help="Path to workspace directory",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the planner CLI."""
    args = parse_args(argv)

    if args.command == "init":
        return init_command(
            args.ticket_id,
            args.workflow,
            args.paths,
            args.update_prompt,
        )
    if args.command == "next":
        return next_command(args.workspace)
    if args.command == "process":
        return process_command(args.workspace)
    if args.command == "status":
        return status_command(args.workspace)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

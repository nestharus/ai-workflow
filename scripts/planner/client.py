"""Planning state machine CLI.

Usage:
    uv run planner init <ticket-id> [--workflow <create-plan|update-plan>]
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
from pathlib import Path


def init_command(ticket_id: str, workflow: str = "create-plan") -> int:
    """Initialize state for a new ticket.

    Creates workspace directory and initial state.yaml.
    Fetches ticket info from Linear.

    Args:
        ticket_id: Linear ticket ID (e.g., NES-123)
        workflow: Workflow type (create-plan or update-plan)

    Returns:
        0 on success, 1 on failure
    """
    from scripts.clients.linear_client import LinearClient
    from scripts.planner.state import DesignState, Unit

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
    )

    # Create root unit
    state.units["root"] = Unit(
        id="root",
        description=issue.get("description", ""),
        operation="CREATE",
        status="pending",
    )
    state.layers[0] = ["root"]

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
    from scripts.planner.create_plan import CreatePlanStateMachine
    from scripts.planner.state import DesignState
    from scripts.planner.update_plan import UpdatePlanStateMachine

    state = DesignState.load(workspace)

    if state.workflow == "create-plan":
        machine = CreatePlanStateMachine(state)
    elif state.workflow == "update-plan":
        machine = UpdatePlanStateMachine(state)
    else:
        print(json.dumps({"ok": False, "error": f"Unknown workflow: {state.workflow}"}))
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
    from scripts.planner.create_plan import CreatePlanStateMachine
    from scripts.planner.state import DesignState
    from scripts.planner.update_plan import UpdatePlanStateMachine

    state = DesignState.load(workspace)

    if state.workflow == "create-plan":
        machine = CreatePlanStateMachine(state)
    elif state.workflow == "update-plan":
        machine = UpdatePlanStateMachine(state)
    else:
        print(json.dumps({"ok": False, "error": f"Unknown workflow: {state.workflow}"}))
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
                "max_layer": max(state.layers.keys()) if state.layers else 0,
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
        choices=["create-plan", "update-plan"],
        help="Workflow type",
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
        return init_command(args.ticket_id, args.workflow)
    if args.command == "next":
        return next_command(args.workspace)
    if args.command == "process":
        return process_command(args.workspace)
    if args.command == "status":
        return status_command(args.workspace)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

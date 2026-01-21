"""CLI interface for workflow state machine.

Provides commands for orchestrating the article writer workflow:
- init: Start a new workflow
- next: Get the next action to take
- respond: Provide user input response
- status: Check workflow status
- list: List all workflows
- resume: Resume a paused workflow

All commands output JSON for machine parsing by the orchestrator (Claude Code).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .database import get_database
from .models import Workflow
from .state_machine import (
    Status,
    create_workflow,
    load_workflow,
)


def output_json(data: dict[str, Any]) -> None:
    """Output JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a new workflow."""
    db = get_database(args.db)
    db.init()

    config = {
        "input_path": str(Path(args.input).resolve()),
        "output_path": str(Path(args.output).resolve()),
        "llm_cmd": args.llm_cmd,
        "no_research": args.no_research,
        "max_loops": args.max_loops,
    }

    if args.brief:
        config["brief_path"] = str(Path(args.brief).resolve())

    if args.style:
        config["style_path"] = str(Path(args.style).resolve())

    if args.workspace:
        config["workspace"] = str(Path(args.workspace).resolve())

    sm = create_workflow(db, "article-writer", config)

    output_json(
        {
            "workflow_id": sm.workflow_id,
            "status": sm.current_status.value,
            "phase": sm.current_phase.value,
            "config": config,
        }
    )

    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Get the next action for a workflow."""
    db = get_database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)
        action = sm.get_next_action()
        output_json(action.to_dict())
        return 0
    except ValueError as e:
        output_json({"error": str(e)})
        return 1


def cmd_respond(args: argparse.Namespace) -> int:
    """Provide response to an input request."""
    db = get_database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)
        sm.provide_input(args.request_id, args.response)

        output_json(
            {
                "status": sm.current_status.value,
                "phase": sm.current_phase.value,
                "message": "Input received, workflow continuing",
            }
        )
        return 0
    except ValueError as e:
        output_json({"error": str(e)})
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Get workflow status."""
    db = get_database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)
        workflow = sm.workflow

        # Get artifact summary
        artifacts = sm.get_artifacts()
        artifact_summary = {}
        for a in artifacts:
            if a.artifact_type not in artifact_summary:
                artifact_summary[a.artifact_type] = []
            artifact_summary[a.artifact_type].append(a.name)

        output_json(
            {
                "workflow_id": workflow.id,
                "type": workflow.type,
                "phase": workflow.phase,
                "status": workflow.status,
                "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
                "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
                "config": workflow.config,
                "artifacts": artifact_summary,
            }
        )
        return 0
    except ValueError as e:
        output_json({"error": str(e)})
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """List all workflows."""
    db = get_database(args.db)

    with db.session() as session:
        workflows = session.query(Workflow).order_by(Workflow.created_at.desc()).all()

        result = []
        for w in workflows:
            result.append(
                {
                    "workflow_id": w.id,
                    "type": w.type,
                    "phase": w.phase,
                    "status": w.status,
                    "created_at": w.created_at.isoformat() if w.created_at else None,
                }
            )

    output_json({"workflows": result})
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume a paused workflow."""
    db = get_database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)

        if sm.current_status != Status.PAUSED:
            output_json(
                {
                    "error": f"Workflow is not paused (status: {sm.current_status.value})",
                    "status": sm.current_status.value,
                }
            )
            return 1

        resume_context = sm.resume()

        output_json(
            {
                "status": sm.current_status.value,
                "phase": sm.current_phase.value,
                "resume_context": resume_context,
                "message": "Workflow resumed",
            }
        )
        return 0
    except ValueError as e:
        output_json({"error": str(e)})
        return 1


def cmd_pause(args: argparse.Namespace) -> int:
    """Pause a running workflow."""
    db = get_database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)

        if sm.current_status != Status.RUNNING:
            output_json(
                {
                    "error": f"Workflow is not running (status: {sm.current_status.value})",
                    "status": sm.current_status.value,
                }
            )
            return 1

        sm.pause(args.reason)

        output_json(
            {
                "status": sm.current_status.value,
                "phase": sm.current_phase.value,
                "message": "Workflow paused",
            }
        )
        return 0
    except ValueError as e:
        output_json({"error": str(e)})
        return 1


def cmd_process(args: argparse.Namespace) -> int:
    """Process result from an agent/tool and advance state."""
    db = get_database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)

        # Parse result from stdin or argument
        if args.result == "-":
            result_str = sys.stdin.read()
        else:
            result_str = args.result

        result = json.loads(result_str)
        sm.process_result(result)

        output_json(
            {
                "status": sm.current_status.value,
                "phase": sm.current_phase.value,
                "message": "Result processed",
            }
        )
        return 0
    except (ValueError, json.JSONDecodeError) as e:
        output_json({"error": str(e)})
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="workflow",
        description="Workflow state machine CLI for article writer",
    )
    parser.add_argument(
        "--db",
        default="workflow.db",
        help="Path to SQLite database (default: workflow.db)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new workflow")
    init_parser.add_argument("--input", required=True, help="Path to input notes/draft")
    init_parser.add_argument("--output", required=True, help="Path for final output")
    init_parser.add_argument("--brief", help="Optional brief JSON file")
    init_parser.add_argument("--style", help="Optional style JSON file")
    init_parser.add_argument("--workspace", help="Workspace directory")
    init_parser.add_argument("--llm-cmd", required=True, help="LLM command")
    init_parser.add_argument("--no-research", action="store_true", help="Skip research phase")
    init_parser.add_argument("--max-loops", type=int, default=2, help="Max finalizer loops")
    init_parser.set_defaults(func=cmd_init)

    # next command
    next_parser = subparsers.add_parser("next", help="Get next action")
    next_parser.add_argument("workflow_id", help="Workflow ID")
    next_parser.set_defaults(func=cmd_next)

    # respond command
    respond_parser = subparsers.add_parser("respond", help="Respond to input request")
    respond_parser.add_argument("workflow_id", help="Workflow ID")
    respond_parser.add_argument("request_id", help="Request ID")
    respond_parser.add_argument("response", help="User response")
    respond_parser.set_defaults(func=cmd_respond)

    # status command
    status_parser = subparsers.add_parser("status", help="Get workflow status")
    status_parser.add_argument("workflow_id", help="Workflow ID")
    status_parser.set_defaults(func=cmd_status)

    # list command
    list_parser = subparsers.add_parser("list", help="List all workflows")
    list_parser.set_defaults(func=cmd_list)

    # resume command
    resume_parser = subparsers.add_parser("resume", help="Resume paused workflow")
    resume_parser.add_argument("workflow_id", help="Workflow ID")
    resume_parser.set_defaults(func=cmd_resume)

    # pause command
    pause_parser = subparsers.add_parser("pause", help="Pause running workflow")
    pause_parser.add_argument("workflow_id", help="Workflow ID")
    pause_parser.add_argument("--reason", help="Reason for pausing")
    pause_parser.set_defaults(func=cmd_pause)

    # process command
    process_parser = subparsers.add_parser("process", help="Process agent/tool result")
    process_parser.add_argument("workflow_id", help="Workflow ID")
    process_parser.add_argument(
        "result",
        nargs="?",
        default="-",
        help="Result JSON (or - for stdin)",
    )
    process_parser.set_defaults(func=cmd_process)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

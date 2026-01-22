#!/usr/bin/env python3
"""CLI entry point for Article Writer workflow.

Usage (from scripts/article_writer directory):
    python -m article_writer init --input notes.md --output final.md --brief brief.json
    python -m article_writer resume <workflow_id> [--response "A,B"]
    python -m article_writer feedback <workflow_id> "Make the opening stronger"
    python -m article_writer status [workflow_id]
    python -m article_writer list
    python -m article_writer run --input notes.md --output final.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# The outer package root (where tools/ lives) is the parent of this module's parent
# article_writer/article_writer/__main__.py -> article_writer/ (PACKAGE_ROOT)
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGE_ROOT))

# Import from sibling tools directory
from tools.workflow.database import Database
from tools.workflow.state_machine import (
    Phase,
    Status,
    create_workflow,
    load_workflow,
)


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a new article workflow."""
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output).expanduser().resolve()

    # Initialize database
    db = Database(args.db)
    db.init()

    # Build config
    config = {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "llm_cmd": args.llm_cmd or "claude --print",
        "no_research": args.no_research,
        "max_loops": args.max_loops,
        "package_root": str(PACKAGE_ROOT),
    }

    if args.brief:
        brief_path = Path(args.brief).expanduser().resolve()
        if not brief_path.exists():
            print(f"Error: Brief file not found: {brief_path}", file=sys.stderr)
            return 1
        config["brief_path"] = str(brief_path)

    if args.workspace:
        config["workspace"] = str(Path(args.workspace).expanduser().resolve())

    # Create workflow
    sm = create_workflow(db, "article-writer", config)

    print(
        json.dumps(
            {
                "workflow_id": sm.workflow_id,
                "status": "created",
                "phase": sm.current_phase.value,
                "config": config,
            },
            indent=2,
        )
    )

    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume a paused workflow."""
    db = Database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    status = sm.current_status

    if status == Status.COMPLETED:
        print(
            json.dumps(
                {
                    "workflow_id": args.workflow_id,
                    "status": "completed",
                    "message": "Workflow already completed",
                },
                indent=2,
            )
        )
        return 0

    if status == Status.ERROR:
        config = sm.workflow.config or {}
        print(
            json.dumps(
                {
                    "workflow_id": args.workflow_id,
                    "status": "error",
                    "error": config.get("error", "Unknown error"),
                },
                indent=2,
            )
        )
        return 1

    # Handle pending input request
    if status == Status.WAITING_INPUT:
        pending = sm._get_pending_input_request()
        if pending:
            if args.response:
                # Provide the response
                from tools.run_workflow import _parse_cut_selection

                selected_cuts = _parse_cut_selection(args.response)
                sm.provide_input(pending.id, args.response)

                # Store selected cuts
                config = sm.workflow.config or {}
                config["selected_cuts"] = selected_cuts
                sm._update_workflow(config=config)

                print(
                    json.dumps(
                        {
                            "workflow_id": args.workflow_id,
                            "status": "running",
                            "phase": sm.current_phase.value,
                            "action": "input_provided",
                            "selected_cuts": selected_cuts,
                        },
                        indent=2,
                    )
                )
            else:
                # Return the pending request
                print(
                    json.dumps(
                        {
                            "workflow_id": args.workflow_id,
                            "status": "waiting_input",
                            "phase": sm.current_phase.value,
                            "request": {
                                "id": pending.id,
                                "prompt": pending.prompt,
                                "options": pending.options,
                            },
                        },
                        indent=2,
                    )
                )
            return 0

    # Resume from paused
    if status == Status.PAUSED:
        resume_context = sm.resume()
        print(
            json.dumps(
                {
                    "workflow_id": args.workflow_id,
                    "status": "running",
                    "phase": sm.current_phase.value,
                    "has_resume_context": bool(resume_context),
                },
                indent=2,
            )
        )
        return 0

    # Already running
    print(
        json.dumps(
            {
                "workflow_id": args.workflow_id,
                "status": status.value,
                "phase": sm.current_phase.value,
            },
            indent=2,
        )
    )
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    """Provide feedback on an existing draft to trigger revision."""
    db = Database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Store feedback in workflow config
    config = sm.workflow.config or {}
    feedback_list = config.get("user_feedback", [])
    feedback_list.append(
        {
            "feedback": args.feedback,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    config["user_feedback"] = feedback_list

    # Set flag to trigger feedback revision
    config["has_pending_feedback"] = True

    # If workflow is complete or paused, move to feedback revision phase
    if sm.current_status in (Status.COMPLETED, Status.PAUSED):
        sm._update_workflow(
            phase=Phase.REVISE.value,
            status=Status.RUNNING.value,
            config=config,
        )
        print(
            json.dumps(
                {
                    "workflow_id": args.workflow_id,
                    "status": "running",
                    "phase": "revise",
                    "action": "feedback_queued",
                    "feedback": args.feedback,
                    "message": "Workflow will incorporate feedback in revision",
                },
                indent=2,
            )
        )
    else:
        # Workflow is running - just queue feedback
        sm._update_workflow(config=config)
        print(
            json.dumps(
                {
                    "workflow_id": args.workflow_id,
                    "status": sm.current_status.value,
                    "phase": sm.current_phase.value,
                    "action": "feedback_queued",
                    "feedback": args.feedback,
                    "message": "Feedback queued for next revision cycle",
                },
                indent=2,
            )
        )

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Check workflow status."""
    db = Database(args.db)
    db.init()

    if args.workflow_id:
        try:
            sm = load_workflow(db, args.workflow_id)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        config = sm.workflow.config or {}
        result = {
            "workflow_id": args.workflow_id,
            "status": sm.current_status.value,
            "phase": sm.current_phase.value,
            "created_at": sm.workflow.created_at.isoformat() if sm.workflow.created_at else None,
            "updated_at": sm.workflow.updated_at.isoformat() if sm.workflow.updated_at else None,
        }

        if sm.current_status == Status.WAITING_INPUT:
            pending = sm._get_pending_input_request()
            if pending:
                result["pending_input"] = {
                    "prompt": pending.prompt,
                    "options": pending.options,
                }

        feedback = config.get("user_feedback", [])
        if feedback:
            result["feedback_count"] = len(feedback)
            result["has_pending_feedback"] = config.get("has_pending_feedback", False)

        if sm.current_status == Status.ERROR:
            result["error"] = config.get("error")

        print(json.dumps(result, indent=2))
    else:
        return cmd_list(args)

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List all workflows."""
    db = Database(args.db)
    db.init()

    from tools.workflow.models import Workflow

    with db.session() as session:
        workflows = session.query(Workflow).order_by(Workflow.created_at.desc()).all()
        results = []
        for w in workflows:
            results.append(
                {
                    "workflow_id": w.id,
                    "type": w.type,
                    "status": w.status,
                    "phase": w.phase,
                    "created_at": w.created_at.isoformat() if w.created_at else None,
                }
            )

    print(json.dumps({"workflows": results}, indent=2))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Get the next action for a workflow."""
    db = Database(args.db)

    try:
        sm = load_workflow(db, args.workflow_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    action = sm.get_next_action()
    print(json.dumps(action.to_dict(), indent=2))
    return 0


def cmd_continue(args: argparse.Namespace) -> int:
    """Continue executing an existing workflow (after feedback or resume).

    This actually runs the workflow through the state machine, unlike 'resume'
    which only updates status. Use this after 'feedback' to apply changes.
    """
    from tools.run_workflow import main as run_main

    # Build sys.argv for the runner with --resume
    sys.argv = ["run_workflow", "--resume", args.workflow_id]
    if args.db:
        sys.argv.extend(["--db", args.db])
    if args.response:
        sys.argv.extend(["--response", args.response])

    return run_main()


def cmd_run(args: argparse.Namespace) -> int:
    """Run the full workflow (for CLI use, not Claude Code)."""
    from tools.run_workflow import main as run_main

    # Build sys.argv for the runner
    sys.argv = ["run_workflow"]
    if args.input:
        sys.argv.extend(["--input", args.input])
    if args.output:
        sys.argv.extend(["--output", args.output])
    if args.brief:
        sys.argv.extend(["--brief", args.brief])
    if args.llm_cmd:
        sys.argv.extend(["--llm-cmd", args.llm_cmd])
    if args.workspace:
        sys.argv.extend(["--workspace", args.workspace])
    if args.db:
        sys.argv.extend(["--db", args.db])
    sys.argv.append("--use-state-machine")

    return run_main()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="article_writer",
        description="Multi-agent article writing workflow",
    )
    parser.add_argument(
        "--db",
        default="workflow.db",
        help="SQLite database path",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    init_p = subparsers.add_parser("init", help="Start a new article workflow")
    init_p.add_argument("--input", "-i", required=True, help="Input notes/draft file")
    init_p.add_argument("--output", "-o", required=True, help="Output file path")
    init_p.add_argument("--brief", "-b", help="Brief JSON file")
    init_p.add_argument("--llm-cmd", help="LLM command (default: claude --print)")
    init_p.add_argument("--workspace", "-w", help="Workspace directory")
    init_p.add_argument("--no-research", action="store_true", help="Skip research phase")
    init_p.add_argument("--max-loops", type=int, default=2, help="Max revision loops")

    # resume
    resume_p = subparsers.add_parser("resume", help="Resume a paused workflow")
    resume_p.add_argument("workflow_id", help="Workflow ID to resume")
    resume_p.add_argument("--response", "-r", help="Response to pending input")

    # feedback
    feedback_p = subparsers.add_parser("feedback", help="Provide feedback on draft")
    feedback_p.add_argument("workflow_id", help="Workflow ID")
    feedback_p.add_argument("feedback", help="Feedback text")

    # status
    status_p = subparsers.add_parser("status", help="Check workflow status")
    status_p.add_argument("workflow_id", nargs="?", help="Workflow ID (optional)")

    # list
    subparsers.add_parser("list", help="List all workflows")

    # next
    next_p = subparsers.add_parser("next", help="Get next action for workflow")
    next_p.add_argument("workflow_id", help="Workflow ID")

    # continue (execute workflow after feedback)
    continue_p = subparsers.add_parser("continue", help="Execute workflow (use after feedback)")
    continue_p.add_argument("workflow_id", help="Workflow ID to continue")
    continue_p.add_argument(
        "--response", "-r", help="Response to pending input (e.g., cut selection)"
    )

    # run (full workflow, for CLI use)
    run_p = subparsers.add_parser("run", help="Run full workflow (CLI mode)")
    run_p.add_argument("--input", "-i", required=True, help="Input notes/draft file")
    run_p.add_argument("--output", "-o", required=True, help="Output file path")
    run_p.add_argument("--brief", "-b", help="Brief JSON file")
    run_p.add_argument("--llm-cmd", help="LLM command")
    run_p.add_argument("--workspace", "-w", help="Workspace directory")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "resume": cmd_resume,
        "feedback": cmd_feedback,
        "status": cmd_status,
        "list": cmd_list,
        "next": cmd_next,
        "continue": cmd_continue,
        "run": cmd_run,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

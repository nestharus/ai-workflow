#!/usr/bin/env python3
"""CLI entry point for Article Writer workflow.

Usage (from repo root):
    python -m scripts.article_writer init --input notes.md --output final.md
    python -m scripts.article_writer run --input notes.md --output final.md

Usage (from scripts/article_writer directory):
    python -m article_writer init --input notes.md --output final.md
    python -m article_writer run --input notes.md --output final.md

The inner article_writer module provides the same CLI when cd'd into the package.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Add the article_writer package to path for imports
PACKAGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE_ROOT))

# Try to delegate to inner module
try:
    from article_writer.__main__ import main
except ImportError:
    # Inner module not available - define main here
    import argparse
    import json

    try:
        from tools.workflow.database import Database
        from tools.workflow.state_machine import (
            Phase,
            Status,
            create_workflow,
            load_workflow,
        )
    except ImportError:
        sys.path.insert(0, str(PACKAGE_ROOT.parent.parent))
        from scripts.article_writer.tools.workflow.database import Database
        from scripts.article_writer.tools.workflow.state_machine import (
            Phase,
            Status,
            create_workflow,
            load_workflow,
        )

    def cmd_init(args: argparse.Namespace) -> int:
        input_path = Path(args.input).expanduser().resolve()
        if not input_path.exists():
            print(f"Error: Input file not found: {input_path}", file=sys.stderr)
            return 1
        output_path = Path(args.output).expanduser().resolve()
        db = Database(args.db)
        db.init()
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
        sm = create_workflow(db, "article-writer", config)
        print(
            json.dumps(
                {
                    "workflow_id": sm.workflow_id,
                    "status": "created",
                    "phase": sm.current_phase.value,
                },
                indent=2,
            )
        )
        return 0

    def cmd_resume(args: argparse.Namespace) -> int:
        db = Database(args.db)
        try:
            sm = load_workflow(db, args.workflow_id)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "workflow_id": args.workflow_id,
                    "status": sm.current_status.value,
                    "phase": sm.current_phase.value,
                },
                indent=2,
            )
        )
        return 0

    def cmd_feedback(args: argparse.Namespace) -> int:
        db = Database(args.db)
        try:
            sm = load_workflow(db, args.workflow_id)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        config = sm.workflow.config or {}
        feedback_list = config.get("user_feedback", [])
        feedback_list.append(
            {
                "feedback": args.feedback,
                "timestamp": datetime.now().isoformat(),
            }
        )
        config["user_feedback"] = feedback_list
        config["has_pending_feedback"] = True
        if sm.current_status in (Status.COMPLETED, Status.PAUSED):
            sm._update_workflow(
                phase=Phase.REVISE.value, status=Status.RUNNING.value, config=config
            )
        else:
            sm._update_workflow(config=config)
        print(json.dumps({"workflow_id": args.workflow_id, "action": "feedback_queued"}, indent=2))
        return 0

    def cmd_status(args: argparse.Namespace) -> int:
        db = Database(args.db)
        db.init()
        if args.workflow_id:
            try:
                sm = load_workflow(db, args.workflow_id)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            print(
                json.dumps(
                    {
                        "workflow_id": args.workflow_id,
                        "status": sm.current_status.value,
                        "phase": sm.current_phase.value,
                    },
                    indent=2,
                )
            )
        else:
            return cmd_list(args)
        return 0

    def cmd_list(args: argparse.Namespace) -> int:
        db = Database(args.db)
        db.init()
        try:
            from tools.workflow.models import Workflow
        except ImportError:
            from scripts.article_writer.tools.workflow.models import Workflow
        with db.session() as session:
            workflows = session.query(Workflow).order_by(Workflow.created_at.desc()).all()
            results = [
                {"workflow_id": w.id, "type": w.type, "status": w.status, "phase": w.phase}
                for w in workflows
            ]
        print(json.dumps({"workflows": results}, indent=2))
        return 0

    def cmd_next(args: argparse.Namespace) -> int:
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
        """Continue executing workflow after feedback."""
        try:
            from tools.run_workflow import main as run_main
        except ImportError:
            from scripts.article_writer.tools.run_workflow import main as run_main
        sys.argv = ["run_workflow", "--resume", args.workflow_id]
        if args.db:
            sys.argv.extend(["--db", args.db])
        if args.response:
            sys.argv.extend(["--response", args.response])
        return run_main()

    def cmd_run(args: argparse.Namespace) -> int:
        try:
            from tools.run_workflow import main as run_main
        except ImportError:
            from scripts.article_writer.tools.run_workflow import main as run_main
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
            prog="article-writer", description="Multi-agent article writing workflow"
        )
        parser.add_argument("--db", default="workflow.db", help="SQLite database path")
        subparsers = parser.add_subparsers(dest="command", required=True)

        init_p = subparsers.add_parser("init", help="Start a new article workflow")
        init_p.add_argument("--input", "-i", required=True)
        init_p.add_argument("--output", "-o", required=True)
        init_p.add_argument("--brief", "-b")
        init_p.add_argument("--llm-cmd")
        init_p.add_argument("--workspace", "-w")
        init_p.add_argument("--no-research", action="store_true")
        init_p.add_argument("--max-loops", type=int, default=2)

        resume_p = subparsers.add_parser("resume")
        resume_p.add_argument("workflow_id")
        resume_p.add_argument("--response", "-r")

        feedback_p = subparsers.add_parser("feedback")
        feedback_p.add_argument("workflow_id")
        feedback_p.add_argument("feedback")

        status_p = subparsers.add_parser("status")
        status_p.add_argument("workflow_id", nargs="?")

        subparsers.add_parser("list")

        next_p = subparsers.add_parser("next")
        next_p.add_argument("workflow_id")

        continue_p = subparsers.add_parser("continue", help="Execute workflow after feedback")
        continue_p.add_argument("workflow_id")
        continue_p.add_argument("--response", "-r")

        run_p = subparsers.add_parser("run")
        run_p.add_argument("--input", "-i", required=True)
        run_p.add_argument("--output", "-o", required=True)
        run_p.add_argument("--brief", "-b")
        run_p.add_argument("--llm-cmd")
        run_p.add_argument("--workspace", "-w")

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

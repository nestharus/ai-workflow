"""Command-line interface for spec refinement."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.spec_refinement.workspace import WorkspaceManager


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize run-scoped workspace."""
    run_id = args.run_id
    input_folder = Path(args.input_folder)

    if not input_folder.exists():
        print(f"Input folder does not exist: {input_folder}")
        return 1

    manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)

    issues = manager.initialize(force=args.force)
    if issues:
        print("Validation issues:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print(f"Workspace initialized: {manager.workspace_path}")
    print(f"Files found: {len(manager.state.file_manifest)}")
    for file_id, file_path in manager.get_all_files().items():
        sections = manager.get_section_labels(file_id)
        print(f"  - {file_id}: {Path(file_path).name} ({len(sections)} sections)")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show workspace status."""
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    print(f"Run ID: {run_id}")
    print(f"Workspace: {manager.workspace_path}")
    print(f"Complete: {manager.is_complete}")
    print()
    print("Phases:")

    from scripts.spec_refinement.workspace.state import Phase, PhaseStatus

    for phase in Phase:
        result = manager.state.phases[phase.value]
        status_icon = {
            PhaseStatus.COMPLETED: "✅",
            PhaseStatus.FAILED: "❌",
            PhaseStatus.IN_PROGRESS: "🔄",
            PhaseStatus.SKIPPED: "⏭️",
            PhaseStatus.NOT_STARTED: "⏸️",
        }.get(result.status, "❓")
        print(f"  {status_icon} {phase.value}: {result.status.value}")

    return 0


def main() -> int:
    """Main entry point for spec refinement CLI."""
    parser = argparse.ArgumentParser(
        description="Spec Refinement - Refine and execute large specs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init", help="Initialize run-scoped workspace")
    p_init.add_argument("run_id", help="Unique run identifier")
    p_init.add_argument("input_folder", help="Path to folder containing spec files")
    p_init.add_argument("--force", action="store_true", help="Clear existing workspace")

    p_status = subparsers.add_parser("status", help="Show workspace status")
    p_status.add_argument("run_id", help="Run identifier")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

"""Command-line interface for spec refinement."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from scripts.spec_refinement.core.gap import Gap, format_gap_table
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

    print()
    print("Gap Audit:")
    has_gap_audit = False
    for phase in Phase:
        audit = manager.get_gap_audit_status(phase)
        if audit["iterations"] > 0:
            has_gap_audit = True
            print(
                f"  {phase.value}: iterations={audit['iterations']}, "
                f"converged={audit['converged']}, open_gaps={audit['open_gaps_count']}"
            )
    if not has_gap_audit:
        print("  No gap audits recorded.")

    all_gaps = manager.get_all_gaps(run_id)
    total_open = sum(1 for gaps in all_gaps.values() for gap in gaps if gap.status == "open")
    print(f"Total open gaps: {total_open}")

    return 0


def cmd_gaps_list(args: argparse.Namespace) -> int:
    """List gaps across libraries and tasks."""
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    all_gaps = manager.get_all_gaps(run_id)
    filtered: list[Gap] = []

    for artifact_id, gaps in all_gaps.items():
        if args.artifact and artifact_id != args.artifact:
            continue
        for gap in gaps:
            if args.status and gap.status != args.status:
                continue
            if args.severity and gap.severity.value != args.severity:
                continue
            if args.type and gap.gap_type.value != args.type:
                continue
            filtered.append(
                Gap(
                    id=gap.id,
                    gap_type=gap.gap_type,
                    severity=gap.severity,
                    source=gap.source,
                    derived_artifact_target=artifact_id,
                    description=gap.description,
                    evidence=gap.evidence,
                    status=gap.status,
                    resolution_pointer=gap.resolution_pointer,
                    created_at=gap.created_at,
                    resolved_at=gap.resolved_at,
                    resolution_notes=gap.resolution_notes,
                )
            )

    if not filtered:
        print("No gaps found.")
        return 0

    print(format_gap_table(filtered))
    return 0


def _find_gap(manager: WorkspaceManager, gap_id: str) -> tuple[str, str, Gap] | None:
    if manager.structure.libraries_dir.exists():
        for lib_dir in sorted(manager.structure.libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            gaps = manager.read_library_gaps(lib_dir.name)
            for gap in gaps:
                if gap.id == gap_id:
                    return ("library", lib_dir.name, gap)
    if manager.structure.tasks_dir.exists():
        for task_dir in sorted(manager.structure.tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            gaps = manager.read_task_gaps(task_dir.name)
            for gap in gaps:
                if gap.id == gap_id:
                    return ("task", task_dir.name, gap)
    return None


def _extract_sections(content: str) -> dict[str, str]:
    import re

    sections: dict[str, str] = {}
    current_label: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_label, current_lines
        if current_label is not None:
            sections[current_label] = "\n".join(current_lines).strip()
        current_label = None
        current_lines = []

    for line in content.splitlines():
        stripped = line.strip()
        label = None
        match = re.search(r"\[([A-Z_]+)\]", stripped)
        if match:
            label = match.group(1).strip()
        elif stripped.startswith("## "):
            heading = stripped[3:].strip()
            if heading:
                label = heading.upper().replace(" ", "_")
        if label:
            _flush()
            current_label = label
            current_lines = [line]
            continue
        if current_label is not None:
            current_lines.append(line)

    _flush()
    return sections


def _read_source_section(manager: WorkspaceManager, pointer: str) -> str:
    if "::" not in pointer:
        return f"### {pointer}\n\nSource pointer missing section."
    file_id, section_id = pointer.split("::", 1)
    file_path = manager.get_file_path(file_id) or Path(file_id)
    if not file_path.exists():
        return f"### {pointer}\n\nSource file not found."
    content = file_path.read_text(encoding="utf-8")
    sections = _extract_sections(content)
    section_content = sections.get(section_id)
    if section_content is None:
        section_content = "Section not found."
    return f"### {pointer}\n\n{section_content}"


def cmd_gap_investigate(args: argparse.Namespace) -> int:
    """Investigate a gap and stitch context."""
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    result = _find_gap(manager, args.gap_id)
    if result is None:
        print(f"Gap not found: {args.gap_id}")
        return 1

    _, _, gap = result
    source_sections = []
    for pointer in gap.source:
        source_sections.append(_read_source_section(manager, pointer))

    target_path = Path(gap.derived_artifact_target)
    if not target_path.exists():
        candidate = manager.structure.root / gap.derived_artifact_target
        if candidate.exists():
            target_path = candidate
    target_content = (
        target_path.read_text(encoding="utf-8")
        if target_path.exists()
        else "Target artifact not found."
    )

    evidence_lines = []
    for item in gap.evidence:
        evidence_lines.append(
            f"- {item.invariant_family}: {item.description} (confidence={item.confidence})"
        )
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "- None"

    stitched = "\n".join(
        [
            "## Source Evidence",
            "",
            "\n\n".join(source_sections) if source_sections else "No source pointers.",
            "",
            "## Target Artifact",
            "",
            target_content,
            "",
            "## Gap Details",
            "",
            gap.description,
            "",
            evidence_block,
            "",
        ]
    )

    audits_dir = manager.structure.audits_dir
    audits_dir.mkdir(parents=True, exist_ok=True)
    context_path = audits_dir / f"gap_{gap.id}_context.md"
    context_path.write_text(stitched, encoding="utf-8")
    print(f"Context written to: {context_path}")

    if args.propose_resolution:
        from scripts.dev.agent_runner import AgentRunner

        prompt = (
            "Analyze this gap and propose a resolution. Specify whether to: "
            "(1) integrate (update artifact), (2) defer (record decision), "
            "(3) reject (mark irrelevant with evidence).\n\n"
            f"{stitched}"
        )
        runner = AgentRunner.from_agent_name(
            "implementor",
            Path(".tasks.yaml"),
            model="factory/gpt-5.1-codex-max-xhigh",
            provider="opencode",
        )
        proposal = runner.run(prompt)
        proposal_path = audits_dir / f"gap_{gap.id}_proposal.md"
        proposal_path.write_text(proposal, encoding="utf-8")
        print(f"Proposal written to: {proposal_path}")

    return 0


def cmd_gap_resolve(args: argparse.Namespace) -> int:
    """Resolve a gap with a given resolution type."""
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    result = _find_gap(manager, args.gap_id)
    if result is None:
        print(f"Gap not found: {args.gap_id}")
        return 1

    artifact_kind, artifact_id, gap = result
    resolution_type = args.resolution_type
    if resolution_type not in {"integrate", "defer", "reject"}:
        print(f"Invalid resolution type: {resolution_type}")
        return 1

    if resolution_type == "integrate" and not args.pointer:
        print("Resolution pointer is required for integrate.")
        return 1

    status_mapping = {
        "integrate": "integrated",
        "defer": "deferred",
        "reject": "rejected",
    }
    gap.status = status_mapping[resolution_type]
    gap.resolved_at = datetime.now().isoformat()
    gap.resolution_notes = args.notes
    if resolution_type == "integrate":
        gap.resolution_pointer = args.pointer

    if artifact_kind == "library":
        gaps = manager.read_library_gaps(artifact_id)
        gaps = [gap if item.id == gap.id else item for item in gaps]
        manager.write_library_gaps(artifact_id, gaps)
    else:
        gaps = manager.read_task_gaps(artifact_id)
        gaps = [gap if item.id == gap.id else item for item in gaps]
        manager.write_task_gaps(artifact_id, gaps)

    print(f"Gap {gap.id} resolved as {resolution_type}")
    return 0


def main() -> int:
    """Main entry point for spec refinement CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Spec Refinement - Refine and execute large specs\n\n"
            "Planned commands:\n"
            "  spec.summarize_all (agent: glm-file-what-summarizer)\n"
            "  library.synthesize (agent: opus-library-synthesizer)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init", help="Initialize run-scoped workspace")
    p_init.add_argument("run_id", help="Unique run identifier")
    p_init.add_argument("input_folder", help="Path to folder containing spec files")
    p_init.add_argument("--force", action="store_true", help="Clear existing workspace")
    p_init.set_defaults(func=cmd_init)

    p_status = subparsers.add_parser("status", help="Show workspace status")
    p_status.add_argument("run_id", help="Run identifier")
    p_status.set_defaults(func=cmd_status)

    p_gaps = subparsers.add_parser("gaps", help="Gap-related commands")
    gaps_subparsers = p_gaps.add_subparsers(dest="gaps_command", required=True)

    p_gaps_list = gaps_subparsers.add_parser("list", help="List gaps")
    p_gaps_list.add_argument("run_id", help="Run identifier")
    p_gaps_list.add_argument("--status", help="Filter by status")
    p_gaps_list.add_argument("--severity", help="Filter by severity")
    p_gaps_list.add_argument("--type", help="Filter by gap type")
    p_gaps_list.add_argument("--artifact", help="Filter by artifact ID")
    p_gaps_list.set_defaults(func=cmd_gaps_list)

    p_gap = subparsers.add_parser("gap", help="Single-gap commands")
    gap_subparsers = p_gap.add_subparsers(dest="gap_command", required=True)

    p_gap_investigate = gap_subparsers.add_parser("investigate", help="Investigate a gap")
    p_gap_investigate.add_argument("run_id", help="Run identifier")
    p_gap_investigate.add_argument("gap_id", help="Gap identifier")
    p_gap_investigate.add_argument(
        "--propose-resolution", action="store_true", help="Generate resolution proposal"
    )
    p_gap_investigate.set_defaults(func=cmd_gap_investigate)

    p_gap_resolve = gap_subparsers.add_parser("resolve", help="Resolve a gap")
    p_gap_resolve.add_argument("run_id", help="Run identifier")
    p_gap_resolve.add_argument("gap_id", help="Gap identifier")
    p_gap_resolve.add_argument(
        "resolution_type", choices=["integrate", "defer", "reject"], help="Resolution type"
    )
    p_gap_resolve.add_argument("--notes", help="Resolution notes")
    p_gap_resolve.add_argument("--pointer", help="Resolution pointer (required for integrate)")
    p_gap_resolve.set_defaults(func=cmd_gap_resolve)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

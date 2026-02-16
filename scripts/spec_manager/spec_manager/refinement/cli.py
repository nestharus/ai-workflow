"""Command-line interface for spec refinement.

Workflow examples:

# Phase 1: Summarize all files
uv run spec spec summarize my_run_001

# Phase 2: Synthesize libraries
uv run spec spec synthesize my_run_001

# Phase 3: Expand evidence
uv run spec spec expand-evidence my_run_001

# Phase 4: Build specs
uv run spec spec build-specs my_run_001
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from spec_manager.core.agent_utils import run_agent
from spec_manager.core.gap import Gap, format_gap_table
from spec_manager.core.project_root import resolve_from_root
from spec_manager.refinement.qa.contract_lint import run_contract_lint
from spec_manager.refinement.trace import (
    format_atom_trace,
    format_element_trace,
    format_section_trace,
    format_task_trace,
    load_trace_indexes,
)
from spec_manager.refinement.workflows import summarize_all, synthesize_libraries
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager


def _phase_completed(manager: WorkspaceManager, phase: Phase) -> bool:
    return manager.state.phases[phase.value].status == PhaseStatus.COMPLETED


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value!r}")


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize run-scoped workspace."""
    run_id = args.run_id
    input_folder = Path(args.input_folder)
    if not input_folder.is_absolute():
        input_folder = resolve_from_root(args.input_folder)

    if not input_folder.exists():
        print(f"Input folder does not exist: {input_folder}")
        return 1

    manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)

    issues = manager.initialize(force=args.force)
    if issues:
        if any("Manifest conflict" in issue for issue in issues):
            print("⚠️  RESUME CONFLICT DETECTED")
            print("The workspace already exists with different inputs.")
            print("Use --force to recreate the workspace from scratch.")
            print()
        print("Validation issues:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print(f"Workspace initialized: {manager.workspace_path}")
    print(f"Mode: {manager.state.mode}")
    print(f"Files found: {len(manager.state.file_manifest)}")
    for file_id, file_path in manager.get_all_files().items():
        sections = manager.get_section_labels(file_id)
        print(f"  - {file_id}: {Path(file_path).name} ({len(sections)} sections)")

    return 0


def cmd_spec_sectionize(args: argparse.Namespace) -> int:
    """Run Phase 1 sectionization for all files."""
    run_id = args.run_id

    from spec_manager.refinement.workflows import sectionize_all

    try:
        result = sectionize_all(run_id, parallel=not args.sequential)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Files processed: {result['files_processed']}")
    print(f"Sections written: {result['sections_written']}")
    print(f"Atoms written: {result['atoms_written']}")
    print(f"Terms written: {result['terms_written']}")

    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error.get('file_id')}: {error.get('error')}")

    if result.get("issues"):
        print(f"Validation issues: {len(result['issues'])}")

    if not result.get("success", True):
        print("Sectionization failed.")
        return 1

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.SECTIONIZATION):
        return 1

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

    from spec_manager.refinement.workspace.state import Phase, PhaseStatus

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
        prompt = (
            "Analyze this gap and propose a resolution. Specify whether to: "
            "(1) integrate (update artifact), (2) defer (record decision), "
            "(3) reject (mark irrelevant with evidence).\n\n"
            f"{stitched}"
        )
        proposal = run_agent(
            agent_name="implementor",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
        proposal_path = audits_dir / f"gap_{gap.id}_proposal.md"
        proposal_path.write_text(str(proposal), encoding="utf-8")
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

    status_mapping: dict[str, Literal["integrated", "deferred", "rejected"]] = {
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
        manager.write_library_gaps(artifact_id, gaps, update_queue=True)
    else:
        gaps = manager.read_task_gaps(artifact_id)
        gaps = [gap if item.id == gap.id else item for item in gaps]
        manager.write_task_gaps(artifact_id, gaps)

    print(f"Gap {gap.id} resolved as {resolution_type}")
    return 0


def _extract_intent_from_charter(content: str) -> str:
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().lower() == "## intent":
            for follow in lines[idx + 1 :]:
                if follow.startswith("## "):
                    break
                if follow.strip():
                    return follow.strip()
    return ""


def cmd_spec_summarize(args: argparse.Namespace) -> int:
    """Summarize all files in the workspace."""
    run_id = args.run_id

    try:
        result = summarize_all(run_id, parallel=not args.sequential)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Summaries written: {result['summaries_written']} / {result['files_processed']}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error.get('file_id')}: {error.get('error')}")
    if result.get("issues"):
        print("Issues:")
        for issue in result["issues"]:
            file_id = issue.get("file_id", "unknown")
            message = issue.get("message", issue.get("type", "issue"))
            print(f"  - {file_id}: {message}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.SUMMARIZATION):
        return 1
    return 0


def cmd_spec_synthesize(args: argparse.Namespace) -> int:
    """Synthesize libraries from the summary outputs."""
    run_id = args.run_id

    try:
        result = synthesize_libraries(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    if result.get("error"):
        print(f"Synthesis failed: {result['error']}")
        return 1

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    index_path = result.get("library_index")
    if index_path and Path(index_path).exists():
        print("Library Index:")
        print(Path(index_path).read_text(encoding="utf-8"))

    libraries_dir = manager.structure.libraries_dir
    if libraries_dir.exists():
        print("Library Charters:")
        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            charter_path = lib_dir / "charter.md"
            intent = ""
            if charter_path.exists():
                intent = _extract_intent_from_charter(charter_path.read_text(encoding="utf-8"))
            evidence_path = lib_dir / "evidence.json"
            evidence_count = 0
            if evidence_path.exists():
                import json

                payload = json.loads(evidence_path.read_text(encoding="utf-8"))
                sources = payload.get("sources", [])
                evidence_count = sum(len(source.get("sections", [])) for source in sources)
            intent_display = f" - {intent}" if intent else ""
            print(f"  - {lib_dir.name}{intent_display} (evidence: {evidence_count})")

    if result.get("issues"):
        print("Issues:")
        for issue in result["issues"]:
            lib_id = issue.get("lib_id", "unknown")
            message = issue.get("message", issue.get("type", "issue"))
            print(f"  - {lib_id}: {message}")
    if not result.get("success", True):
        return 1
    if not _phase_completed(manager, Phase.LIBRARY_SYNTHESIS):
        return 1

    return 0


def cmd_spec_expand_evidence(args: argparse.Namespace) -> int:
    """Expand evidence sources for Phase 3."""
    run_id = args.run_id

    from spec_manager.refinement.workflows import expand_evidence

    try:
        result = expand_evidence(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Evidence expanded: {result['libraries_expanded']} libraries")
    print(f"Evidence sources added: {result['evidence_sources_added']}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            lib_id = error.get("lib_id", "unknown")
            message = error.get("error", "error")
            print(f"  - {lib_id}: {message}")
    if result.get("issues"):
        print("Issues:")
        for issue in result["issues"]:
            lib_id = issue.get("lib_id", "unknown")
            message = issue.get("message", issue.get("type", "issue"))
            print(f"  - {lib_id}: {message}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.EVIDENCE_EXPANSION):
        return 1
    return 0


def cmd_spec_spotcheck_evidence(args: argparse.Namespace) -> int:
    """Spot-check evidence coverage for Phase 3."""
    run_id = args.run_id
    lib_ids = args.lib_ids

    from spec_manager.refinement.workflows import spotcheck_evidence

    try:
        result = spotcheck_evidence(run_id, lib_ids)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries spot-checked: {result['libraries_checked']}")
    print(f"Missing sections found: {result['missing_sections_added']}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            lib_id = error.get("lib_id", "unknown")
            message = error.get("error", "error")
            print(f"  - {lib_id}: {message}")
    if result.get("issues"):
        print("Issues:")
        for issue in result["issues"]:
            lib_id = issue.get("lib_id", "unknown")
            message = issue.get("message", issue.get("type", "issue"))
            print(f"  - {lib_id}: {message}")
    if not result.get("success", True) or result.get("errors") or result.get("issues"):
        return 1
    return 0


def cmd_spec_build_specs(args: argparse.Namespace) -> int:
    """Build library specs for Phase 4."""
    run_id = args.run_id

    from spec_manager.refinement.workflows import build_specs

    try:
        result = build_specs(run_id, max_iterations=args.max_iterations)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries built: {result['libraries_built']}")
    print(f"Converged: {result['converged_count']}/{result['libraries_built']}")
    print(f"Total iterations: {result['total_iterations']}")
    coverage_metrics = result.get("coverage_metrics", {})
    if coverage_metrics:
        print("Coverage metrics:")
        for lib_id, metrics in sorted(coverage_metrics.items()):
            ratio = metrics.get("convergence_ratio", 1.0)
            total = metrics.get("total_gaps", 0)
            closed = metrics.get("closed_gaps", 0)
            low_flag = " ⚠️" if ratio < 0.8 else ""
            print(f"  - {lib_id}: {ratio:.2%} ({closed}/{total} closed){low_flag}")
        total_ratio = result.get("total_coverage_ratio")
        if isinstance(total_ratio, (int, float)):
            print(f"Total coverage ratio: {total_ratio:.2%}")
    if result.get("issues"):
        print(f"Issues: {len(result['issues'])}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            lib_id = error.get("lib_id", "unknown")
            message = error.get("error", "error")
            print(f"  - {lib_id}: {message}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.SPEC_BUILDING):
        return 1
    return 0


def cmd_spec_stabilize_specs(args: argparse.Namespace) -> int:
    """Stabilize element IDs and indexes for Phase 4 outputs."""
    run_id = args.run_id
    lib_ids = None
    if args.libs:
        lib_ids = [lib_id.strip() for lib_id in args.libs.split(",") if lib_id.strip()]
        if not lib_ids:
            lib_ids = None

    from spec_manager.refinement.workflows import stabilize_specs

    try:
        result = stabilize_specs(
            run_id,
            lib_ids=lib_ids,
            write_run_index=args.write_run_index,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries processed: {result['libraries_processed']}")
    print(f"Elements assigned: {result['elements_assigned']}")
    print(f"Decisions assigned: {result['decisions_assigned']}")
    if result.get("issues"):
        print(f"Validation issues: {len(result['issues'])}")
        for issue in result["issues"]:
            lib_id = issue.get("lib_id", "unknown")
            message = issue.get("message", issue.get("type", "issue"))
            print(f"  - {lib_id}: {message}")
    else:
        print("Validation status: ok")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            lib_id = error.get("lib_id", "unknown")
            message = error.get("error", "error")
            print(f"  - {lib_id}: {message}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.SPEC_BUILDING):
        return 1
    return 0


def cmd_check_alignment(args: argparse.Namespace) -> int:
    """Check alignment of specs against original requirements."""
    run_id = args.run_id

    from spec_manager.refinement.workflows.alignment_check import check_alignment

    try:
        result = check_alignment(run_id, max_iterations=args.max_iterations)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries checked: {result['libraries_checked']}")
    print(f"Drift findings: {result['drift_findings']}")
    print(f"Reward hacking findings: {result['reward_hacking_findings']}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error.get('lib_id', 'unknown')}: {error.get('error', '')}")
    return 0 if result.get("success") else 1


def cmd_generate_overview(args: argparse.Namespace) -> int:
    """Generate human-readable overview document."""
    run_id = args.run_id

    from spec_manager.refinement.workflows.overview_generation import generate_overview

    try:
        result = generate_overview(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries processed: {result['libraries_processed']}")
    print(f"Overview: {result['outputs'].get('overview_path', 'N/A')}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error.get('lib_id', 'unknown')}: {error.get('error', '')}")
    return 0 if result.get("success") else 1


def cmd_approve_overview(args: argparse.Namespace) -> int:
    """Approve the generated overview for QA evaluation."""
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        print("Workspace not initialized.")
        return 1

    reports_dir = manager.structure.root / "reports"
    overview_path = reports_dir / "overview.md"
    if not overview_path.exists():
        print("No overview found. Run 'generate-overview' first.")
        return 1

    marker_path = reports_dir / "overview_approved.marker"
    comment = args.comment or ""
    marker_content = json.dumps(
        {
            "approved_at": datetime.now().isoformat(),
            "comment": comment,
        },
        indent=2,
    )
    marker_path.write_text(marker_content, encoding="utf-8")
    print("Overview approved.")
    if comment:
        print(f"Comment: {comment}")
    return 0


def cmd_qa_evaluate(args: argparse.Namespace) -> int:
    """Run QA evaluation against approved overview."""
    run_id = args.run_id

    from spec_manager.refinement.workflows.qa_evaluation import evaluate_qa

    try:
        result = evaluate_qa(run_id, max_iterations=args.max_iterations)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries evaluated: {result['libraries_evaluated']}")
    print(f"Total findings: {result['total_findings']}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error.get('lib_id', 'unknown')}: {error.get('error', '')}")
    return 0 if result.get("success") else 1


def cmd_quality_gates(args: argparse.Namespace) -> int:
    """Run multi-dimensional quality review."""
    run_id = args.run_id

    from spec_manager.refinement.workflows.quality_gates import run_quality_gates

    try:
        result = run_quality_gates(run_id, threshold=args.threshold)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries reviewed: {result['libraries_reviewed']}")
    print(f"Average score: {result['average_score']:.4f}")
    print(f"Threshold: {args.threshold}")
    print(f"Status: {'PASSED' if result['passed'] else 'FAILED'}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error.get('lib_id', 'unknown')}: {error.get('error', '')}")
    return 0 if result.get("passed") else 1


def cmd_spec_detect_sublibraries(args: argparse.Namespace) -> int:
    """Detect sub-libraries for Phase 5."""
    run_id = args.run_id

    from spec_manager.refinement.workflows import detect_sublibraries

    try:
        result = detect_sublibraries(run_id, max_depth=args.max_depth)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Sub-libraries created: {result['sublibraries_created']}")
    if result.get("issues"):
        print(f"Issues: {len(result['issues'])}")
    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            lib_id = error.get("lib_id", "unknown")
            message = error.get("error", "error")
            print(f"  - {lib_id}: {message}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.SUBLIBRARY_DETECTION):
        return 1
    return 0


def cmd_arch_propose(args: argparse.Namespace) -> int:
    """Propose architecture candidates for Phase 6."""
    run_id = args.run_id

    from spec_manager.refinement.workflows import propose_architectures

    try:
        result = propose_architectures(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Architecture candidates created: {result['candidates_created']}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.ARCHITECTURE_PROPOSAL):
        return 1
    return 0


def cmd_arch_select(args: argparse.Namespace) -> int:
    """Select best architecture for Phase 6."""
    run_id = args.run_id

    from spec_manager.refinement.workflows import select_architecture

    try:
        result = select_architecture(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Selected architecture: {result['selected_arch_id']}")
    print(f"Rejected candidates: {result['rejected_count']}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.ARCHITECTURE_SELECTION):
        return 1
    return 0


def cmd_arch_map(args: argparse.Namespace) -> int:
    """Map libraries to architecture components for Phase 6."""
    run_id = args.run_id

    from spec_manager.refinement.workflows import map_libraries_to_architecture

    try:
        result = map_libraries_to_architecture(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Libraries mapped: {result['libraries_mapped']}")
    if result.get("unmapped_libraries"):
        print(f"Unmapped libraries: {result['unmapped_libraries']}")
    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.ARCHITECTURE_MAPPING):
        return 1
    return 0


def cmd_spec_review_structure(args: argparse.Namespace) -> int:
    """Review library structure for Phase 7."""
    run_id = args.run_id
    apply_splits = args.apply_splits
    apply_moves = args.apply_moves

    if apply_splits:
        manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
        if not manager.is_initialized:
            print("Workspace not initialized. Run 'init' first.")
            return 1
        if not _phase_completed(manager, Phase.SPEC_STABILIZATION):
            print("Spec stabilization must be completed before applying splits.")
            return 1

    from spec_manager.refinement.workflows import review_library_structure

    try:
        result = review_library_structure(
            run_id, apply_splits=apply_splits, apply_moves=apply_moves
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Overlap candidates: {result['overlap_candidates_count']}")
    print(f"Split candidates: {result['split_candidates_count']}")

    report_paths = result.get("report_paths", {})
    if report_paths.get("json"):
        print(f"Report (json): {report_paths['json']}")
    if report_paths.get("markdown"):
        print(f"Report (markdown): {report_paths['markdown']}")

    split_application = result.get("split_application")
    if split_application:
        print(f"Applied splits: {split_application.get('applied_count', 0)}")
        if split_application.get("new_library_ids"):
            new_libs = ", ".join(split_application["new_library_ids"])
            print(f"New libraries: {new_libs}")
        if split_application.get("rejected_count"):
            print(f"Rejected splits: {split_application['rejected_count']}")
        if split_application.get("validation_issues"):
            print("Split validation warnings:")
            for issue in split_application["validation_issues"]:
                message = issue.get("message", "validation issue")
                lib_id = issue.get("lib_id", "unknown")
                print(f"  - {lib_id}: {message}")

    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            error_type = error.get("type", "error")
            message = error.get("error", "error")
            print(f"  - {error_type}: {message}")

    if not result.get("success", True):
        return 1
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.LIBRARY_STRUCTURE_REVIEW):
        return 1
    return 0


def cmd_spec_build_interfaces(args: argparse.Namespace) -> int:
    """Build interface graph and contracts for Phase 8."""
    run_id = args.run_id

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1
    if not _phase_completed(manager, Phase.LIBRARY_STRUCTURE_REVIEW):
        print("Library structure review must be completed before building interfaces.")
        return 1
    if not _phase_completed(manager, Phase.ARCHITECTURE_MAPPING):
        print("Architecture mapping must be completed before building interfaces.")
        return 1

    from spec_manager.refinement.workflows.interfaces import build_interface_graph

    try:
        result = build_interface_graph(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Edges extracted: {result['edges_count']}")
    print(f"Contracts generated: {result['contracts_count']}")
    print(f"Validation errors: {len(result.get('validation_errors', []))}")

    if result.get("edge_list_path"):
        print(f"Edge list: {result['edge_list_path']}")
    if result.get("interface_index_path"):
        print(f"Interface index: {result['interface_index_path']}")

    if not result.get("success", True):
        return 1

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.INTERFACES):
        return 1
    return 0


def cmd_spec_plan_tasks(args: argparse.Namespace) -> int:
    """Plan tasks for Phase 9."""
    run_id = args.run_id

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1
    if not _phase_completed(manager, Phase.INTERFACES):
        print("Interfaces must be completed before planning tasks.")
        return 1
    if not _phase_completed(manager, Phase.ARCHITECTURE_MAPPING):
        print("Architecture mapping must be completed before planning tasks.")
        return 1

    required_artifacts = {
        manager.structure.architecture_dir / "mapping.md": "architecture/mapping.md",
        manager.structure.architecture_dir / "selected.md": "architecture/selected.md",
        manager.structure.indexes_dir / "edge_list.json": "indexes/edge_list.json",
        manager.structure.indexes_dir / "interface_index.json": "indexes/interface_index.json",
    }
    missing = [label for path, label in required_artifacts.items() if not path.exists()]
    if missing:
        print("Missing prerequisite artifacts for task planning:")
        for label in missing:
            print(f"  - {label}")
        return 1

    manager.start_phase(Phase.TASKS)

    from spec_manager.refinement.workflows.tasks import plan_tasks

    try:
        result = plan_tasks(run_id)
    except RuntimeError as exc:
        print(str(exc))
        manager.fail_phase(Phase.TASKS, str(exc))
        return 1

    tasks_count = result.get("tasks_count", 0)
    validation_errors = result.get("validation_errors", [])
    validation_stats = result.get("validation_stats", {})
    task_index_path = result.get("task_index_path")
    patch_graph_path = result.get("patch_graph_path")

    print(f"Tasks planned: {tasks_count}")
    print(f"Validation errors: {len(validation_errors)}")

    coverage = validation_stats.get("coverage", {})
    if coverage:
        print("Coverage metrics:")
        coverage_targets = coverage.get("coverage_targets")
        if coverage_targets is not None:
            print(f"  - Coverage targets: {coverage_targets}")
        edges_required = coverage.get("edges_required")
        if edges_required is not None:
            print(f"  - Edges required: {edges_required}")
        open_gaps_required = coverage.get("open_gaps_required")
        if open_gaps_required is not None:
            print(f"  - Open gaps required: {open_gaps_required}")
        open_decisions_required = coverage.get("open_decisions_required")
        if open_decisions_required is not None:
            print(f"  - Open decisions required: {open_decisions_required}")
        error_types = coverage.get("error_types") or {}
        if error_types:
            print("  - Error types:")
            for error_type, count in sorted(error_types.items()):
                print(f"    - {error_type}: {count}")

    if task_index_path:
        print(f"Task index: {task_index_path}")
    if patch_graph_path:
        print(f"Patch graph: {patch_graph_path}")

    if not result.get("success", True) or result.get("validation_errors"):
        manager.fail_phase(Phase.TASKS, "Task planning failed")
        return 1

    manager.complete_phase(Phase.TASKS, outputs=result)

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not _phase_completed(manager, Phase.TASKS):
        return 1
    return 0


def cmd_spec_implement(args: argparse.Namespace) -> int:
    """Execute tasks for Phase 10."""
    run_id = args.run_id
    repo_root = args.repo_root or Path(".")
    task_filter = None
    if args.tasks:
        task_filter = [task_id.strip() for task_id in args.tasks.split(",") if task_id.strip()]
        if not task_filter:
            task_filter = None
    manager = WorkspaceManager(run_id=run_id, input_folder=repo_root)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1
    if not _phase_completed(manager, Phase.TASKS):
        print("Tasks must be planned before implementation.")
        return 1

    from spec_manager.refinement.workflows.implementation import (
        ImplementationConfig,
        run_implementation_phase,
    )

    config = ImplementationConfig(
        run_tests=args.run_tests,
        test_command=args.test_command,
        run_lint=args.run_lint,
        lint_command=args.lint_command,
        allow_test_repair=args.allow_test_repair,
    )

    try:
        result = run_implementation_phase(
            run_root=manager.workspace_path,
            repo_root=manager.input_folder,
            task_filter=task_filter,
            max_iterations=args.max_iterations,
            config=config,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"Tasks executed: {result.get('tasks_executed', 0)}")
    print(f"Tasks done: {result.get('tasks_done', 0)}")
    print(f"Tasks failed: {result.get('tasks_failed', 0)}")
    if result.get("tasks_blocked"):
        print(f"Tasks blocked: {result.get('tasks_blocked', 0)}")

    task_summaries = result.get("task_summaries", [])
    total_patches_applied = sum(s.get("applied_files", 0) for s in task_summaries)
    tests_passed = 0
    tests_failed = 0
    for summary in task_summaries:
        tests = summary.get("tests")
        if tests and tests.get("ran"):
            if tests.get("exit_code", -1) == 0:
                tests_passed += 1
            else:
                tests_failed += 1

    print(f"Total patches applied: {total_patches_applied}")
    print(f"Tasks with tests passed: {tests_passed}")
    print(f"Tasks with tests failed: {tests_failed}")

    if result.get("tasks_failed", 0) > 0 or tests_failed > 0:
        return 1
    return 0


def cmd_spec_run_tasks(args: argparse.Namespace) -> int:
    """Execute tasks for Phase 10 (alias for implement)."""
    return cmd_spec_implement(args)


def cmd_finalize_run(args: argparse.Namespace) -> int:
    """Finalize run with trace indexes and reports for Phase 11."""
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    from spec_manager.refinement.workflows.finalize import finalize_run

    try:
        result = finalize_run(run_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print("Trace indexes built:")
    trace_stats = result.get("trace_stats", {})
    print(f"  - Atoms indexed: {trace_stats.get('atoms', 0)}")
    print(f"  - Sections indexed: {trace_stats.get('sections', 0)}")
    print(f"  - Elements indexed: {trace_stats.get('elements', 0)}")
    print(f"  - Tasks indexed: {trace_stats.get('tasks', 0)}")

    validation_errors = result.get("validation_errors", [])
    if validation_errors:
        print(f"Validation warnings: {len(validation_errors)}")

    print(f"Reports generated: {result.get('reports_generated', 0)}")
    print("Run finalization complete.")

    if result.get("success") is False:
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Run STRUCTURE phase validation (CMD-validate).

    Validates atoms and sections exist and checks coverage report.
    Emits gaps_report if validation issues are found.
    """
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    # Check required artifacts exist
    manifest_dir = manager.structure.manifest_dir
    sections_dir = manifest_dir / "sections"
    atoms_dir = manifest_dir / "atoms"

    issues: list[str] = []

    if not sections_dir.exists() or not any(sections_dir.glob("*.sections.json")):
        issues.append("Missing sections manifest (manifest/sections/*.sections.json)")

    if not atoms_dir.exists() or not any(atoms_dir.glob("*.atoms.jsonl")):
        issues.append("Missing atoms manifest (manifest/atoms/*.atoms.jsonl)")

    # Check for spec_index files if we're past Phase 4
    libraries_dir = manager.structure.libraries_dir
    if libraries_dir.exists():
        lib_dirs = [d for d in libraries_dir.iterdir() if d.is_dir()]
        if lib_dirs:
            specs_missing = [d.name for d in lib_dirs if not (d / "spec_index.json").exists()]
            if specs_missing:
                issues.append(f"Missing spec_index.json for libraries: {', '.join(specs_missing)}")

    if issues:
        print("Validation issues found:")
        for issue in issues:
            print(f"  - {issue}")

        # Write gaps report
        gaps_report = {
            "run_id": run_id,
            "phase": "STRUCTURE",
            "issues": [{"type": "validation_error", "message": issue} for issue in issues],
        }
        reports_dir = manager.structure.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        gaps_path = reports_dir / "gaps_report.json"
        gaps_path.write_text(json.dumps(gaps_report, indent=2), encoding="utf-8")
        print(f"\nGaps report written: {gaps_path}")
        return 1

    print("Validation passed:")
    print("  - Sections manifest: OK")
    print("  - Atoms manifest: OK")
    if libraries_dir.exists():
        lib_count = len([d for d in libraries_dir.iterdir() if d.is_dir()])
        print(f"  - Libraries: {lib_count}")

    return 0


def cmd_project(args: argparse.Namespace) -> int:
    """Generate plan.md projection with pins (CMD-project).

    Uses generate_plan_from_libraries from projection module.
    Runs drift detection and outputs plan_md, drift_report, gaps_report.
    """
    run_id = args.run_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    # Check libraries exist
    libraries_dir = manager.structure.libraries_dir
    if not libraries_dir.exists():
        print("No libraries found. Run synthesis phase first.")
        return 1

    from spec_manager.projection.generator import (
        generate_plan_from_libraries,
        save_projection,
    )
    from spec_manager.schemas.spec_index_v2 import Library, SpecIndexV2

    # Load libraries and elements from spec indexes
    libraries: list[Library] = []
    from spec_manager.schemas.derived_elements import DerivedElement

    elements: list[DerivedElement] = []
    provenance_errors: list[dict[str, str]] = []

    for lib_dir in sorted(libraries_dir.iterdir()):
        if not lib_dir.is_dir():
            continue

        # Read library info from charter or spec_index
        lib_id = lib_dir.name
        charter_path = lib_dir / "charter.md"
        name = lib_id
        description = ""

        if charter_path.exists():
            charter_content = charter_path.read_text(encoding="utf-8")
            # Extract name from first heading
            for line in charter_content.splitlines():
                if line.startswith("# "):
                    name = line[2:].strip()
                    break
                if line.startswith("## Intent"):
                    # Next non-empty line is description
                    idx = charter_content.find("## Intent")
                    rest = charter_content[idx + len("## Intent") :].strip()
                    for desc_line in rest.splitlines():
                        if desc_line.strip() and not desc_line.startswith("#"):
                            description = desc_line.strip()
                            break
                    break

        library = Library(lib_id=lib_id, name=name, description=description)
        libraries.append(library)

        # Load elements from spec_index
        spec_index_path = lib_dir / "spec_index.json"
        if spec_index_path.exists():
            spec_data = json.loads(spec_index_path.read_text(encoding="utf-8"))
            for elem_data in spec_data.get("elements", []):
                atom_ids = elem_data.get("evidence_atom_ids")
                element_id = str(elem_data.get("element_id", "")).strip() or "?"
                if not isinstance(atom_ids, list) or not atom_ids:
                    provenance_errors.append(
                        {
                            "lib_id": lib_id,
                            "element_id": element_id,
                            "message": "missing evidence_atom_ids",
                        }
                    )
                    continue
                cleaned_atom_ids = [
                    atom_id.strip()
                    for atom_id in atom_ids
                    if isinstance(atom_id, str) and atom_id.strip()
                ]
                if len(cleaned_atom_ids) != len(atom_ids):
                    provenance_errors.append(
                        {
                            "lib_id": lib_id,
                            "element_id": element_id,
                            "message": "contains invalid evidence_atom_ids entries",
                        }
                    )
                    continue
                elem = DerivedElement(
                    elem_id=elem_data.get("element_id", ""),
                    kind=elem_data.get("kind", "REQ"),
                    lib_id=lib_id,
                    title=elem_data.get("title", ""),
                    body=elem_data.get("text", ""),
                    evidence_atom_ids=cleaned_atom_ids,
                )
                elements.append(elem)

    if provenance_errors:
        print("Projection blocked: missing or invalid evidence provenance detected.")
        for error in provenance_errors:
            print(f"  - {error['lib_id']}/{error['element_id']}: {error['message']}")
        return 1

    if not libraries:
        print("No library directories found.")
        return 1

    print(f"Generating projection from {len(libraries)} libraries, {len(elements)} elements...")

    # Generate projection
    artifact = generate_plan_from_libraries(libraries, elements)

    # Save projection
    projections_dir = manager.workspace_path / "projections"
    projections_dir.mkdir(parents=True, exist_ok=True)
    plan_path = projections_dir / "plan.md"
    pins_path = projections_dir / "plan_pins.json"

    save_projection(artifact, plan_path, pins_path)

    print("Projection generated:")
    print(f"  - Plan: {plan_path}")
    print(f"  - Pins: {pins_path} ({len(artifact.pins)} pins)")

    # Run drift detection if previous projection exists
    existing_plan = manager.structure.root / "plan.md"
    if existing_plan.exists():
        from spec_manager.projection.drift import AtomAwareDriftComparator

        comparator = AtomAwareDriftComparator()
        spec_index = SpecIndexV2(libraries=libraries)

        report = comparator.compare(artifact, spec_index)

        reports_dir = manager.structure.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        drift_path = reports_dir / "projection_drift.json"

        drift_data = {
            "projection_id": artifact.projection_id,
            "similarity": report.similarity,
            "total_pins": report.total_pins,
            "valid_pins": report.valid_pins,
            "missing_targets": report.missing_targets,
            "drift_items": [
                {
                    "drift_type": item.drift_type,
                    "pin_id": item.pin_id,
                    "target_id": item.target_id,
                    "projection_excerpt": item.projection_excerpt,
                }
                for item in report.drift_items
            ],
        }
        drift_path.write_text(json.dumps(drift_data, indent=2), encoding="utf-8")
        print(f"  - Drift report: {drift_path}")
        print(f"    - Similarity: {report.similarity:.2%}")
        print(f"    - Valid pins: {report.valid_pins}/{report.total_pins}")

        if report.has_significant_drift():
            print("  - WARNING: Significant drift detected")

    return 0


def cmd_trace_atom(args: argparse.Namespace) -> int:
    """Trace an atom through the provenance chain."""
    run_id = args.run_id
    atom_id = args.atom_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    try:
        indexes = load_trace_indexes(manager)
    except FileNotFoundError:
        print("Trace indexes not found. Run 'spec finalize-run' first.")
        return 1
    except json.JSONDecodeError:
        print("Trace indexes are malformed.")
        return 1

    try:
        report = format_atom_trace(atom_id, indexes, manager)
    except ValueError as exc:
        print(f"Trace index integrity error: {exc}")
        return 1
    if report is None:
        print(f"Atom not found: {atom_id}")
        return 2

    print(report)
    return 0


def cmd_trace_section(args: argparse.Namespace) -> int:
    """Trace a section through the provenance chain."""
    run_id = args.run_id
    section_id = args.section_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    try:
        indexes = load_trace_indexes(manager)
    except FileNotFoundError:
        print("Trace indexes not found. Run 'spec finalize-run' first.")
        return 1
    except json.JSONDecodeError:
        print("Trace indexes are malformed.")
        return 1

    try:
        report = format_section_trace(section_id, indexes, manager)
    except ValueError as exc:
        print(f"Trace index integrity error: {exc}")
        return 1
    if report is None:
        print(f"Section not found: {section_id}")
        return 2

    print(report)
    return 0


def cmd_trace_element(args: argparse.Namespace) -> int:
    """Trace a spec element through the provenance chain."""
    run_id = args.run_id
    element_id = args.element_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    try:
        indexes = load_trace_indexes(manager)
    except FileNotFoundError:
        print("Trace indexes not found. Run 'spec finalize-run' first.")
        return 1
    except json.JSONDecodeError:
        print("Trace indexes are malformed.")
        return 1

    try:
        report = format_element_trace(element_id, indexes, manager)
    except ValueError as exc:
        print(f"Trace index integrity error: {exc}")
        return 1
    if report is None:
        print(f"Element not found: {element_id}")
        return 2

    print(report)
    return 0


def cmd_trace_task(args: argparse.Namespace) -> int:
    """Trace a task back to source sections and elements."""
    run_id = args.run_id
    task_id = args.task_id
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    try:
        indexes = load_trace_indexes(manager)
    except FileNotFoundError:
        print("Trace indexes not found. Run 'spec finalize-run' first.")
        return 1
    except json.JSONDecodeError:
        print("Trace indexes are malformed.")
        return 1

    try:
        report = format_task_trace(task_id, indexes, manager)
    except ValueError as exc:
        print(f"Trace index integrity error: {exc}")
        return 1
    if report is None:
        print(f"Task not found: {task_id}")
        return 2

    print(report)
    return 0


def cmd_qa_list(_: argparse.Namespace) -> int:
    """List available manual QA cases."""
    from spec_manager.refinement.qa import QA_CASES

    print("Available QA cases:")
    for case_id, case in sorted(QA_CASES.items()):
        print(f"  - {case_id}: {case.description}")
    return 0


def cmd_qa_run(args: argparse.Namespace) -> int:
    """Run a single manual QA case (one agent step + judge)."""
    from spec_manager.refinement.qa import run_qa_case

    try:
        result = run_qa_case(
            run_id=args.run_id,
            case_id=args.case_id,
            force_init=args.force,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    status = "PASS" if result.get("passed") else "FAIL"
    print(f"{args.case_id}: {status} (score={result.get('score')})")
    if result.get("session_id"):
        print(f"Session: {result['session_id']}")
    print(f"Report: {result.get('report_path')}")
    return 0 if result.get("passed") else 1


def cmd_qa_run_all(args: argparse.Namespace) -> int:
    """Run all manual QA cases (one agent step each + judge)."""
    from spec_manager.refinement.qa import run_qa_suite

    case_ids = args.case_ids or None
    try:
        result = run_qa_suite(
            run_id=args.run_id,
            case_ids=case_ids,
            force_init=args.force,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(
        f"QA suite complete: {result['cases_passed']}/{result['cases_total']} passed "
        f"(session={result['session_id']})"
    )
    if result["cases_passed"] != result["cases_total"]:
        return 1
    return 0


def cmd_qa_lint_contracts(args: argparse.Namespace) -> int:
    """Lint agent prompts and workflow contracts."""
    output_dir = (
        resolve_from_root("runs", args.run_id, "reports")
        if args.run_id is not None
        else resolve_from_root(".tmp")
    )
    issues, exit_code = run_contract_lint(
        agents_dir=resolve_from_root(".agents", "agents"),
        workflows_dir=resolve_from_root(
            "scripts", "spec_manager", "spec_manager", "refinement", "workflows"
        ),
        output_dir=output_dir,
    )

    summary = {"total": len(issues), "error": 0, "warning": 0, "info": 0}
    for issue in issues:
        if issue.severity in summary:
            summary[issue.severity] += 1

    print(f"Total issues: {summary['total']}")
    print(
        "Errors: {error} | Warnings: {warning} | Info: {info}".format(
            error=summary["error"],
            warning=summary["warning"],
            info=summary["info"],
        )
    )
    print(f"Report (markdown): {output_dir / 'contract_lint.md'}")
    print(f"Report (json): {output_dir / 'contract_lint.json'}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Main entry point for spec refinement CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Spec Refinement - Refine and execute large specs\n\n"
            "Commands:\n"
            "  init\n"
            "  status\n"
            "  gaps\n"
            "  gap\n"
            "  spec sectionize (Phase 1: LLM sectionization, atom emission, term extraction)\n"
            "  spec summarize (Phase 2: agent: glm-file-what-summarizer)\n"
            "  spec synthesize (Phase 3: agent: opus-library-synthesizer)\n"
            "  spec expand-evidence (agent: glm-library-evidence-mapper)\n"
            "  spec spotcheck-evidence (agent: chatgpt-evidence-gap-judge)\n"
            "  spec build-specs (agent: glm-library-spec-integrator)\n"
            "  spec stabilize-specs (stable element IDs and indexes)\n"
            "  spec propose-architectures (agent: opus-architecture-proposer)\n"
            "  spec select-architecture (agent: chatgpt-architecture-tradeoff-judge)\n"
            "  spec map-libraries (agent: glm-architecture-mapper)\n"
            "  spec review-structure (Phase 7: library boundary review)\n"
            "  spec build-interfaces (Phase 8: interface graph and contracts)\n"
            "  spec plan-tasks (Phase 9: task planning from specs and interfaces)\n"
            "  spec implement (Phase 10: execute tasks with\n"
            "    --repo-root, --tasks, --run-tests, --max-iterations)\n"
            "  spec run-tasks (Phase 10: alias for implement)\n"
            "  spec finalize-run (Phase 11: reports and traceability)\n"
            "  trace atom <run_id> <atom_id>\n"
            "  trace section <run_id> <section_id>\n"
            "  trace element <run_id> <element_id>\n"
            "  trace task <run_id> <task_id>\n"
            "  qa list\n"
            "  qa run\n"
            "  qa run-all\n"
            "  qa lint-contracts"
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

    p_qa = subparsers.add_parser(
        "qa",
        help="Manual QA cases for agent steps (runs external LLMs; not part of pytest)",
    )
    qa_subparsers = p_qa.add_subparsers(dest="qa_command", required=True)

    p_qa_list = qa_subparsers.add_parser("list", help="List available QA cases")
    p_qa_list.set_defaults(func=cmd_qa_list)

    p_qa_run = qa_subparsers.add_parser("run", help="Run a single QA case")
    p_qa_run.add_argument(
        "run_id", help="Run identifier used for storing QA artifacts under runs/<run_id>/"
    )
    p_qa_run.add_argument("case_id", help="QA case identifier (see: qa list)")
    p_qa_run.add_argument("--force", action="store_true", help="Recreate workspace before running")
    p_qa_run.set_defaults(func=cmd_qa_run)

    p_qa_run_all = qa_subparsers.add_parser("run-all", help="Run all QA cases")
    p_qa_run_all.add_argument(
        "run_id", help="Run identifier used for storing QA artifacts under runs/<run_id>/"
    )
    p_qa_run_all.add_argument(
        "--case-ids",
        nargs="+",
        default=None,
        help="Optional subset of QA case IDs to run",
    )
    p_qa_run_all.add_argument(
        "--force", action="store_true", help="Recreate workspace before running"
    )
    p_qa_run_all.set_defaults(func=cmd_qa_run_all)

    p_qa_lint_contracts = qa_subparsers.add_parser(
        "lint-contracts",
        help="Lint agent prompts and workflow contracts",
    )
    p_qa_lint_contracts.add_argument(
        "--run-id",
        help="Optional run identifier for storing reports under runs/<run_id>/reports/",
    )
    p_qa_lint_contracts.set_defaults(func=cmd_qa_lint_contracts)

    p_trace = subparsers.add_parser(
        "trace",
        help="Trace provenance from atoms to patches",
    )
    trace_subparsers = p_trace.add_subparsers(dest="trace_command", required=True)

    p_trace_atom = trace_subparsers.add_parser(
        "atom",
        help="Trace an atom through the provenance chain",
    )
    p_trace_atom.add_argument("run_id", help="Run identifier")
    p_trace_atom.add_argument("atom_id", help="Atom ID (e.g., ATOM-F0001-L0042)")
    p_trace_atom.set_defaults(func=cmd_trace_atom)

    p_trace_section = trace_subparsers.add_parser(
        "section",
        help="Trace a section through the provenance chain",
    )
    p_trace_section.add_argument("run_id", help="Run identifier")
    p_trace_section.add_argument("section_id", help="Section ID (e.g., SEC-F0001-0001)")
    p_trace_section.set_defaults(func=cmd_trace_section)

    p_trace_element = trace_subparsers.add_parser(
        "element",
        help="Trace a spec element through the provenance chain",
    )
    p_trace_element.add_argument(
        "run_id",
        help="Run identifier",
    )
    p_trace_element.add_argument(
        "element_id",
        help="Element ID (e.g., REQ-LIB-0001-0001)",
    )
    p_trace_element.set_defaults(func=cmd_trace_element)

    p_trace_task = trace_subparsers.add_parser(
        "task",
        help="Trace a task back to source sections and elements",
    )
    p_trace_task.add_argument("run_id", help="Run identifier")
    p_trace_task.add_argument("task_id", help="Task ID (e.g., TASK-0001)")
    p_trace_task.set_defaults(func=cmd_trace_task)

    p_spec = subparsers.add_parser(
        "spec",
        help="Workflow commands for summarization and synthesis",
    )
    spec_subparsers = p_spec.add_subparsers(dest="spec_command", required=True)

    p_spec_sectionize = spec_subparsers.add_parser(
        "sectionize",
        help="Run Phase 1 sectionization (LLM-based section detection)",
        description=(
            "Run Phase 1 sectionization using LLM agents to detect sections, "
            "emit line-atoms, and extract terms.\n"
            "Inputs: initialized workspace with spec_snapshot.\n"
            "Outputs: manifest/sections/*.sections.json, manifest/atoms/*.atoms.jsonl, "
            "manifest/terms/*.terms.json, workspace/intermediates/pass_01/evidence.jsonl, "
            "workspace/intermediates/pass_01/gaps.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_sectionize.add_argument("run_id", help="Run identifier")
    p_spec_sectionize.add_argument(
        "--sequential", action="store_true", help="Disable parallel execution"
    )
    p_spec_sectionize.set_defaults(func=cmd_spec_sectionize)

    p_spec_summarize = spec_subparsers.add_parser(
        "summarize",
        help="Summarize all files for Phase 1",
        description=(
            "Run Phase 1 summarization using the glm-file-what-summarizer agent.\n"
            "Inputs: initialized workspace.\n"
            "Outputs: summaries/*.what.md and phase state updates."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_summarize.add_argument("run_id", help="Run identifier")
    p_spec_summarize.add_argument(
        "--sequential", action="store_true", help="Disable parallel execution"
    )
    p_spec_summarize.set_defaults(func=cmd_spec_summarize)

    p_spec_synthesize = spec_subparsers.add_parser(
        "synthesize",
        help="Synthesize libraries for Phase 2",
        description=(
            "Run Phase 2 library synthesis using the opus-library-synthesizer agent.\n"
            "Requires Phase 1 summarization to be completed.\n"
            "Outputs: libraries/ with library_index.md and charter artifacts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_synthesize.add_argument("run_id", help="Run identifier")
    p_spec_synthesize.set_defaults(func=cmd_spec_synthesize)

    p_spec_expand = spec_subparsers.add_parser(
        "expand-evidence",
        help="Expand evidence sources for Phase 3",
        description=(
            "Run Phase 3 evidence expansion using glm-library-evidence-mapper.\n"
            "Requires Phase 2 library synthesis to be completed.\n"
            "Outputs: libraries/*/evidence.json updates and phase state updates."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_expand.add_argument("run_id", help="Run identifier")
    p_spec_expand.set_defaults(func=cmd_spec_expand_evidence)

    p_spec_spotcheck = spec_subparsers.add_parser(
        "spotcheck-evidence",
        help="Spot-check evidence coverage for Phase 3",
        description=(
            "Optional Phase 3 spot-check using chatgpt-evidence-gap-judge.\n"
            "Reads libraries/*/evidence.json and proposes missing sections."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_spotcheck.add_argument("run_id", help="Run identifier")
    p_spec_spotcheck.add_argument(
        "--lib-ids",
        nargs="+",
        default=None,
        help="Library IDs to spot-check (default: all)",
    )
    p_spec_spotcheck.set_defaults(func=cmd_spec_spotcheck_evidence)

    p_spec_build = spec_subparsers.add_parser(
        "build-specs",
        help="Build library specs for Phase 4",
        description=(
            "Run Phase 4 spec building using glm-library-spec-integrator and "
            "chatgpt-library-spec-gap-judge.\n"
            "Requires Phase 3 evidence expansion to be completed.\n"
            "Outputs: libraries/*/spec.md, gaps.md, decisions.md updates."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_build.add_argument("run_id", help="Run identifier")
    p_spec_build.add_argument(
        "--max-iterations", type=int, default=5, help="Max gap closure iterations"
    )
    p_spec_build.set_defaults(func=cmd_spec_build_specs)

    p_spec_stabilize = spec_subparsers.add_parser(
        "stabilize-specs",
        help="Stabilize element IDs for Phase 4 outputs",
        description=(
            "Stabilize element IDs in library specs and decisions, persist per-library "
            "ID counters, and build spec indexes.\n"
            "Requires Phase 4 spec building to be completed.\n"
            "Outputs: libraries/*/id_counters.json, spec_index.json, decisions_index.json, "
            "workspace/indexes/library_spec_index.json (optional)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_stabilize.add_argument("run_id", help="Run identifier")
    p_spec_stabilize.add_argument(
        "--libs",
        help="Comma-separated library IDs to stabilize (default: all)",
    )
    p_spec_stabilize.add_argument(
        "--write-run-index",
        action="store_true",
        help="Write aggregate run-level spec index",
    )
    p_spec_stabilize.set_defaults(func=cmd_spec_stabilize_specs)

    # PDD: Alignment check
    p_check_alignment = spec_subparsers.add_parser(
        "check-alignment",
        help="Check spec alignment against original requirements",
        description=(
            "Run alignment check to detect requirement drift and reward hacking.\n"
            "Requires spec stabilization to be completed.\n"
            "Outputs: reports/alignment_report.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_check_alignment.add_argument("run_id", help="Run identifier")
    p_check_alignment.add_argument(
        "--max-iterations", type=int, default=3, help="Max alignment correction iterations"
    )
    p_check_alignment.set_defaults(func=cmd_check_alignment)

    # PDD: Overview generation
    p_gen_overview = spec_subparsers.add_parser(
        "generate-overview",
        help="Generate human-readable overview document",
        description=(
            "Generate consolidated overview from library specs.\n"
            "Requires alignment check to be completed.\n"
            "Outputs: reports/overview.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_gen_overview.add_argument("run_id", help="Run identifier")
    p_gen_overview.set_defaults(func=cmd_generate_overview)

    # PDD: Approve overview
    p_approve_overview = spec_subparsers.add_parser(
        "approve-overview",
        help="Approve the generated overview for QA evaluation",
        description=(
            "Mark the generated overview as approved.\n"
            "Creates overview_approved.marker for QA evaluation prerequisite."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_approve_overview.add_argument("run_id", help="Run identifier")
    p_approve_overview.add_argument("--comment", default="", help="Approval comment")
    p_approve_overview.set_defaults(func=cmd_approve_overview)

    # PDD: QA evaluation
    p_qa_eval = spec_subparsers.add_parser(
        "qa-evaluate",
        help="Run QA evaluation against approved overview",
        description=(
            "Evaluate specs against the approved overview.\n"
            "Requires overview approval.\n"
            "Outputs: reports/qa_evaluation.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_qa_eval.add_argument("run_id", help="Run identifier")
    p_qa_eval.add_argument(
        "--max-iterations", type=int, default=3, help="Max QA evaluation iterations"
    )
    p_qa_eval.set_defaults(func=cmd_qa_evaluate)

    p_spec_detect = spec_subparsers.add_parser(
        "detect-sublibraries",
        help="Detect sub-libraries for Phase 5",
        description=(
            "Run Phase 5 sub-library detection using opus-sublibrary-planner.\n"
            "Requires Phase 4 spec building to be completed.\n"
            "Outputs: libraries/*/sublibraries/ with nested library structures."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_detect.add_argument("run_id", help="Run identifier")
    p_spec_detect.add_argument("--max-depth", type=int, default=3, help="Max recursion depth")
    p_spec_detect.set_defaults(func=cmd_spec_detect_sublibraries)

    p_arch_propose = spec_subparsers.add_parser(
        "propose-architectures",
        help="Propose architecture candidates for Phase 6",
        description=(
            "Run Phase 6a architecture proposal using opus-architecture-proposer.\n"
            "Requires Phase 5 sublibrary detection to be completed.\n"
            "Outputs: architecture/candidates/arch_*.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_arch_propose.add_argument("run_id", help="Run identifier")
    p_arch_propose.set_defaults(func=cmd_arch_propose)

    p_arch_select = spec_subparsers.add_parser(
        "select-architecture",
        help="Select best architecture for Phase 6",
        description=(
            "Run Phase 6b architecture selection using chatgpt-architecture-tradeoff-judge.\n"
            "Requires architecture proposal to be completed.\n"
            "Outputs: architecture/selected.md, architecture/rejected.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_arch_select.add_argument("run_id", help="Run identifier")
    p_arch_select.set_defaults(func=cmd_arch_select)

    p_arch_map = spec_subparsers.add_parser(
        "map-libraries",
        help="Map libraries to architecture for Phase 6",
        description=(
            "Run Phase 6c library mapping using glm-architecture-mapper.\n"
            "Requires architecture selection to be completed.\n"
            "Outputs: architecture/mapping.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_arch_map.add_argument("run_id", help="Run identifier")
    p_arch_map.set_defaults(func=cmd_arch_map)

    p_spec_review = spec_subparsers.add_parser(
        "review-structure",
        help="Review library structure for Phase 7",
        description=(
            "Run Phase 7 library structure review to detect splits, merges, and boundary issues.\n"
            "Requires Phase 6 spec stabilization to be completed.\n"
            "Outputs: reports/review_actions.json, reports/review_actions.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_review.add_argument("run_id", help="Run identifier")
    p_spec_review.add_argument(
        "--apply-splits",
        action="store_true",
        help="Apply split actions after generating review actions report",
    )
    p_spec_review.add_argument(
        "--apply-moves",
        action="store_true",
        help="Apply move actions (not yet implemented)",
    )
    p_spec_review.set_defaults(func=cmd_spec_review_structure)

    p_spec_build_interfaces = spec_subparsers.add_parser(
        "build-interfaces",
        help="Build interface graph and contracts for Phase 8",
        description=(
            "Run Phase 8 interface graph building to extract edges, draft contracts, "
            "and validate cross-library dependencies.\n"
            "Requires Phase 6 architecture mapping and Phase 7 structure review to be completed.\n"
            "Outputs: workspace/indexes/edge_list.json, workspace/indexes/interface_index.json, "
            "libraries/*/interfaces/EDGE-*.md, libraries/*/interfaces/EDGE-*.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_build_interfaces.add_argument("run_id", help="Run identifier")
    p_spec_build_interfaces.set_defaults(func=cmd_spec_build_interfaces)

    # PDD: Quality gates
    p_quality_gates = spec_subparsers.add_parser(
        "quality-gates",
        help="Run multi-dimensional quality review",
        description=(
            "Run completeness, consistency, clarity, and correctness reviews.\n"
            "Requires interfaces to be completed.\n"
            "Outputs: reports/quality_gates.md, reports/quality_gates.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_quality_gates.add_argument("run_id", help="Run identifier")
    p_quality_gates.add_argument(
        "--threshold", type=float, default=0.8, help="Minimum score threshold (default: 0.8)"
    )
    p_quality_gates.set_defaults(func=cmd_quality_gates)

    p_spec_plan_tasks = spec_subparsers.add_parser(
        "plan-tasks",
        help="Plan tasks for Phase 9",
        description=(
            "Run Phase 9 task planning to convert stabilized specs, interface contracts, and "
            "architecture mapping into an executable task plan.\n"
            "Requires Phase 8 interfaces and Phase 6 architecture mapping to be completed.\n"
            "Outputs: tasks/task_index.json, tasks/task_index.md, tasks/TASK-####/task.json, "
            "tasks/TASK-####/task.md, workspace/indexes/patch_graph.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_plan_tasks.add_argument("run_id", help="Run identifier")
    p_spec_plan_tasks.set_defaults(func=cmd_spec_plan_tasks)

    p_spec_implement = spec_subparsers.add_parser(
        "implement",
        help="Execute implementation tasks for Phase 10",
        description=(
            "Run Phase 10 implementation to apply task patches, run tests, and audit results.\n"
            "Requires Phase 9 task planning to be completed.\n"
            "Outputs: tasks/TASK-####/patch.diff, apply_log.json, test_output.txt, audit.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_implement.add_argument("run_id", help="Run identifier")
    p_spec_implement.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory (default: current directory)",
    )
    p_spec_implement.add_argument(
        "--tasks",
        help=(
            "Comma-separated task IDs to execute (e.g., TASK-0001,TASK-0002). "
            "If omitted, all tasks are executed in dependency order."
        ),
    )
    p_spec_implement.add_argument(
        "--max-iterations", type=int, default=5, help="Max repair iterations"
    )
    tests_group = p_spec_implement.add_mutually_exclusive_group()
    tests_group.add_argument(
        "--run-tests",
        dest="run_tests",
        action="store_true",
        default=True,
        help="Run tests after applying patches (default)",
    )
    tests_group.add_argument(
        "--no-tests",
        dest="run_tests",
        action="store_false",
        help="Skip test execution",
    )
    p_spec_implement.add_argument(
        "--test-command",
        help="Override test command (default: from pyproject or 'uv run pytest')",
    )
    p_spec_implement.add_argument(
        "--run-lint",
        action="store_true",
        help="Run lint after tests (non-blocking)",
    )
    p_spec_implement.add_argument(
        "--lint-command",
        help="Override lint command (default: 'uv run lint')",
    )
    p_spec_implement.add_argument(
        "--allow-test-repair",
        type=_parse_bool,
        default=True,
        help="Allow patch repair iterations on test failures (default: true)",
    )
    p_spec_implement.set_defaults(func=cmd_spec_implement)

    p_spec_run_tasks = spec_subparsers.add_parser(
        "run-tasks",
        help="Execute implementation tasks for Phase 10 (alias for implement)",
        description=(
            "Run Phase 10 implementation to apply task patches, run tests, and audit results.\n"
            "This is an alias for 'spec implement'.\n"
            "Requires Phase 9 task planning to be completed.\n"
            "Outputs: tasks/TASK-####/patch.diff, apply_log.json, test_output.txt, audit.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_run_tasks.add_argument("run_id", help="Run identifier")
    p_spec_run_tasks.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory (default: current directory)",
    )
    p_spec_run_tasks.add_argument(
        "--tasks",
        help=(
            "Comma-separated task IDs to execute (e.g., TASK-0001,TASK-0002). "
            "If omitted, all tasks are executed in dependency order."
        ),
    )
    p_spec_run_tasks.add_argument(
        "--max-iterations", type=int, default=5, help="Max repair iterations"
    )
    run_tasks_tests_group = p_spec_run_tasks.add_mutually_exclusive_group()
    run_tasks_tests_group.add_argument(
        "--run-tests",
        dest="run_tests",
        action="store_true",
        default=True,
        help="Run tests after applying patches (default)",
    )
    run_tasks_tests_group.add_argument(
        "--no-tests",
        dest="run_tests",
        action="store_false",
        help="Skip test execution",
    )
    p_spec_run_tasks.add_argument(
        "--test-command",
        help="Override test command (default: from pyproject or 'uv run pytest')",
    )
    p_spec_run_tasks.add_argument(
        "--run-lint",
        action="store_true",
        help="Run lint after tests (non-blocking)",
    )
    p_spec_run_tasks.add_argument(
        "--lint-command",
        help="Override lint command (default: 'uv run lint')",
    )
    p_spec_run_tasks.add_argument(
        "--allow-test-repair",
        type=_parse_bool,
        default=True,
        help="Allow patch repair iterations on test failures (default: true)",
    )
    p_spec_run_tasks.set_defaults(func=cmd_spec_run_tasks)

    p_spec_finalize = spec_subparsers.add_parser(
        "finalize-run",
        help="Finalize run with reports and traceability for Phase 11",
        description=(
            "Run Phase 11 finalization to build trace indexes and generate reports.\n"
            "Requires Phase 10 implementation to be completed (recommended).\n"
            "Outputs: workspace/indexes/trace_index.json, reports/coverage.md, "
            "reports/compliance.md, reports/drift.md, audits/run_audit.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_finalize.add_argument("run_id", help="Run identifier")
    p_spec_finalize.set_defaults(func=cmd_finalize_run)

    # CMD-validate: Structure phase validation
    p_spec_validate = spec_subparsers.add_parser(
        "validate",
        help="Run STRUCTURE phase validation (CMD-validate)",
        description=(
            "Validate atoms and sections exist, check coverage report.\n"
            "Emits gaps_report if validation issues are found.\n"
            "Outputs: reports/gaps_report.json (on failure)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_validate.add_argument("run_id", help="Run identifier")
    p_spec_validate.set_defaults(func=cmd_validate)

    # CMD-project: Generate projection with pins
    p_spec_project = spec_subparsers.add_parser(
        "project",
        help="Generate plan.md projection with pins (CMD-project)",
        description=(
            "Generate plan.md as a projection from libraries with inline pins.\n"
            "Uses ALG-PROJ-0001 to generate plan from libraries.\n"
            "Runs drift detection using ALG-PROJ-0002.\n"
            "Outputs: workspace/projections/plan.md, plan_pins.json, "
            "reports/projection_drift.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_spec_project.add_argument("run_id", help="Run identifier")
    p_spec_project.set_defaults(func=cmd_project)

    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)

    result = args.func(args)
    # All handlers return int
    return int(result)


if __name__ == "__main__":
    sys.exit(main())

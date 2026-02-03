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
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.core.gap import Gap, format_gap_table
from spec_manager.refinement.qa.contract_lint import run_contract_lint
from spec_manager.refinement.workflows import summarize_all, synthesize_libraries
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager


def _phase_completed(manager: WorkspaceManager, phase: Phase) -> bool:
    return manager.state.phases[phase.value].status == PhaseStatus.COMPLETED


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
    return 0


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
    return 0


def cmd_qa_lint_contracts(args: argparse.Namespace) -> int:
    """Lint agent prompts and workflow contracts."""
    output_dir = Path("runs") / args.run_id / "reports" if args.run_id is not None else Path(".tmp")
    issues, exit_code = run_contract_lint(
        agents_dir=Path(".agents/agents"),
        workflows_dir=Path("scripts/spec_manager/spec_manager/refinement/workflows"),
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

    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)

    result = args.func(args)
    # All handlers return int
    return int(result)


if __name__ == "__main__":
    sys.exit(main())

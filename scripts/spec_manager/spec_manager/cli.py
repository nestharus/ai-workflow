"""Command-line interface for spec manager.

Usage:
    uv run python -m scripts.spec_manager <command> <spec_folder> [options]

Commands:
    init        Initialize workspace in a spec folder
    status      Show workspace and phase status
    stage       Run cleaning phase (validate inputs)
    plan        Run discovery phase (decompose changes)
    merge       Run review phase (apply changes)
    verify      Run finalization phase (confirm correctness)
    analyze     Run analysis (divergence/convergence detection)
    run         Run all phases
    cleanup     Clean up workspace
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spec_manager.analysis import run_analysis
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.provenance import ProvenanceTracker
from spec_manager.discovery import discover_libraries_sync
from spec_manager.merging import run_merging
from spec_manager.planning import run_planning
from spec_manager.staging.pipeline import StagingPipeline
from spec_manager.verification import run_verification
from spec_manager.workspace import PhaseStatus, WorkspaceManager
from spec_manager.workspace.state import Phase


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize workspace."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    issues = manager.initialize(force=args.force)
    if issues:
        print("Validation issues:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print(f"Workspace initialized: {manager.workspace_path}")
    print(f"Inputs found: {len(manager.state.inputs)}")
    for inp in manager.state.inputs:
        print(f"  - {Path(inp).name}")

    # Check for ambiguous ordering
    if manager.has_ambiguous_ordering():
        ambiguous = manager.get_ambiguous_inputs()
        print(f"\n⚠️  AMBIGUOUS ORDERING: {len(ambiguous)} files have no sequence number")
        print("Cannot determine processing order for:")
        for amb in ambiguous:
            print(f"  - {Path(amb).name}")
        print("\nPlease specify order using:")
        print(f"  uv run python -m spec_manager set-order {spec_folder} file1.md file2.md ...")
        print("\nOr rename files with sequence numbers (e.g., 1-feature.md, 2-other.md)")
        return 2  # Special return code for ambiguous ordering

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show workspace status."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    print(f"Spec Folder: {spec_folder}")
    print(f"Workspace: {manager.workspace_path}")
    print(f"Complete: {manager.is_complete}")
    print()
    print("Phases:")

    for phase in Phase:
        result = manager.state.phases[phase.value]
        status_icon = {
            PhaseStatus.COMPLETED: "✅",
            PhaseStatus.FAILED: "❌",
            PhaseStatus.IN_PROGRESS: "🔄",
            PhaseStatus.SKIPPED: "⏭️",
            PhaseStatus.NOT_STARTED: "⏸️",
        }.get(result.status, "❓")

        issues_count = len(result.issues)
        issues_str = f" ({issues_count} issues)" if issues_count else ""
        print(f"  {status_icon} {phase.value}: {result.status.value}{issues_str}")

    if args.json:
        print()
        print("JSON:")
        print(json.dumps(manager.state.to_dict(), indent=2))

    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    """Run staging phase using strategy pipeline."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    manager.start_phase(Phase.CLEANING)

    # Get patch paths (IMMUTABLE - never modified)
    patch_paths = [Path(p) for p in manager.state.inputs if Path(p).exists()]

    if not patch_paths:
        manager.fail_phase(Phase.CLEANING, "No input files found")
        print("Cleaning failed: No input files found")
        return 1

    print(f"Processing {len(patch_paths)} input file(s):")
    for path in patch_paths:
        print(f"  - {path.name}")

    # Run strategy-based pipeline
    pipeline = StagingPipeline(
        workspace_path=manager.workspace_path,
        max_passes=args.max_passes if hasattr(args, "max_passes") else 10,
    )

    result = pipeline.run(patch_paths)

    # Record issues from gaps
    for gap in result.gaps_detected:
        manager.state.add_issue(
            Phase.CLEANING,
            {
                "category": "strategy_gap",
                "message": f"Strategy gap: {gap['failure_mode']} ({gap['stuck_units']} units)",
                "severity": "warning",
            },
        )

    # Check for convergence
    if not result.converged and result.gaps_detected:
        manager.fail_phase(
            Phase.CLEANING, f"Pipeline did not converge: {len(result.gaps_detected)} strategy gaps"
        )
        print(f"\nCleaning incomplete: {len(result.gaps_detected)} strategy gaps detected")
        for gap in result.gaps_detected:
            print(f"  - {gap['failure_mode']}: {gap['stuck_units']} stuck units")
        return 1

    # Complete phase with metrics
    manager.complete_phase(
        Phase.CLEANING,
        {
            "total_passes": len(result.passes),
            "input_units": result.total_input_units,
            "output_units": result.total_output_units,
            "strategies_used": result.strategies_used,
            "converged": result.converged,
            "evolution_triggers": result.evolution_triggers,
        },
    )

    print("\nCleaning complete:")
    print(f"  Passes: {len(result.passes)}")
    print(f"  Units: {result.total_input_units} -> {result.total_output_units}")
    print(
        f"  Strategies: {', '.join(result.strategies_used) if result.strategies_used else 'none'}"
    )
    print(f"  Converged: {result.converged}")

    if result.evolution_triggers:
        print(f"  Evolution triggers: {result.evolution_triggers}")

    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Run planning phase."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    manager.start_phase(Phase.DISCOVERY)

    # Load registry
    # Build registry by scanning library files
    registry = LibsRegistry.from_libraries(manager.structure.libraries_dir)

    # Get combined content from plan.md + patches (in order)
    combined_content = manager.get_combined_content()
    if not combined_content.strip():
        manager.fail_phase(Phase.PLANNING, "No input content found (no plan.md or patches)")
        return 1

    # Show what's being processed
    inputs = manager.state.inputs
    print(f"Processing {len(inputs)} input file(s):")
    for inp in inputs:
        print(f"  - {Path(inp).name}")

    # Run planning on combined content
    result = run_planning(combined_content, registry, manager.structure.libraries_dir)

    if result.has_blocking_issues:
        manager.fail_phase(Phase.DISCOVERY, f"{len(result.conflicts)} conflicts found")
        print("Discovery failed due to conflicts:")
        for conflict in result.conflicts[:5]:
            print(f"  - {conflict}")
        return 1

    # Report new IDs that will be added to libraries
    if result.missing_in_registry:
        print(f"\nNew IDs found ({len(result.missing_in_registry)}):")
        for id_val in result.missing_in_registry[:10]:
            print(f"  - {id_val}")
        if len(result.missing_in_registry) > 10:
            print(f"  ... and {len(result.missing_in_registry) - 10} more")

    manager.complete_phase(Phase.DISCOVERY, result.to_dict())
    print("\nDiscovery complete:")
    print(f"  Batches: {len(result.batches)}")
    print(f"  Missing in registry: {len(result.missing_in_registry)}")
    print(f"  Missing in libraries: {len(result.missing_in_libraries)}")
    print(f"  Sequence issues: {len(result.sequence_issues)}")

    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Run merging phase."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    manager.start_phase(Phase.REVIEW)

    # Build registry by scanning library files
    registry = LibsRegistry.from_libraries(manager.structure.libraries_dir)
    combined_content = manager.get_combined_content()

    # Run merging
    result = run_merging(
        combined_content,
        registry,
        manager.structure.libraries_dir,
        apply=args.apply,
    )

    if result.errors:
        manager.fail_phase(Phase.REVIEW, "; ".join(result.errors))
        return 1

    manager.complete_phase(Phase.REVIEW, result.to_dict())

    mode = "Applied" if args.apply else "Planned (dry-run)"
    print(f"Review {mode}:")
    print(f"  Actions: {len(result.actions_planned)}")

    if not args.apply:
        print("  Run with --apply to write changes")

    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Run verification phase."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    manager.start_phase(Phase.FINALIZATION)

    # Build registry by scanning library files
    registry = LibsRegistry.from_libraries(manager.structure.libraries_dir)
    combined_content = manager.get_combined_content()

    # Run verification
    result = run_verification(
        combined_content,
        registry,
        manager.structure.libraries_dir,
    )

    if not result.is_valid:
        manager.fail_phase(Phase.FINALIZATION, f"{result.total_issues} issues found")
        print("Finalization failed:")
        print(f"  Duplicates: {len(result.duplicates)}")
        print(f"  Assignment issues: {len(result.assignment_issues)}")
        return 1

    manager.complete_phase(Phase.FINALIZATION, result.to_dict())
    print("Finalization passed:")
    print(f"  Content mismatches: {len(result.content_mismatches)}")
    print(f"  Empty stubs: {len(result.empty_stubs)}")

    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Run analysis."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    # Build registry by scanning library files
    registry = LibsRegistry.from_libraries(manager.structure.libraries_dir)

    # Run analysis
    result = run_analysis(registry, manager.structure.libraries_dir)

    print("Analysis Results:")
    print(f"  Divergence candidates: {len(result.divergence_candidates)}")
    print(f"  Convergence candidates: {len(result.convergence_candidates)}")
    print(f"  Reference patterns: {len(result.reference_patterns)}")
    print(f"  Suggestions: {len(result.suggestions)}")

    if result.suggestions:
        print("\nTop Suggestions:")
        for s in result.suggestions[:5]:
            print(f"  [{s.action}] {s.description} (confidence: {s.confidence:.0%})")

    if args.json:
        print("\nJSON:")
        print(json.dumps(result.to_dict(), indent=2))

    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    """Resolve restructuring suggestions to achieve consistent state."""
    from spec_manager.analysis.resolver import resolve_suggestions

    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    # Build registry by scanning library files
    registry = LibsRegistry.from_libraries(manager.structure.libraries_dir)

    # Run analysis to get suggestions
    analysis_result = run_analysis(registry, manager.structure.libraries_dir)

    if not analysis_result.suggestions:
        print("No restructuring suggestions found.")
        return 0

    # Filter by confidence
    min_confidence = args.min_confidence
    high_conf = [s for s in analysis_result.suggestions if s.confidence >= min_confidence]

    if not high_conf:
        print(f"No suggestions with confidence >= {min_confidence:.0%}")
        print(f"  Total suggestions: {len(analysis_result.suggestions)}")
        print("\nUse --min-confidence to lower threshold, or review with 'analyze' command.")
        return 0

    print(f"Found {len(high_conf)} suggestions with confidence >= {min_confidence:.0%}:")
    for s in high_conf:
        print(f"  [{s.action}] {s.description} ({s.confidence:.0%})")

    if args.dry_run:
        print("\n[DRY RUN] No changes will be made.")
        result = resolve_suggestions(
            high_conf,
            manager.structure.libraries_dir,
            registry,
            min_confidence=min_confidence,
            dry_run=True,
        )
    else:
        print("\nApplying resolutions...")
        result = resolve_suggestions(
            high_conf,
            manager.structure.libraries_dir,
            registry,
            min_confidence=min_confidence,
            dry_run=False,
        )
        # No need to save - registry is derived from library files

    print("\nResolution complete:")
    print(f"  Applied: {result.total_applied}")
    print(f"  Failed: {result.total_failed}")

    for action in result.actions:
        status = "✓" if action.success else "✗"
        print(f"  {status} {action.description}")
        if action.error:
            print(f"      Error: {action.error}")

    return 0 if result.total_failed == 0 else 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run all phases."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    # Initialize if needed
    if not manager.is_initialized:
        issues = manager.initialize()
        if issues:
            print("Cannot initialize workspace:")
            for issue in issues:
                print(f"  - {issue}")
            return 1

    # Run each phase - discovery ALWAYS runs first
    phases = [
        ("discover", lambda: cmd_discover(args)),
        ("stage", lambda: cmd_stage(args)),
        ("plan", lambda: cmd_plan(args)),
        ("merge", lambda: cmd_merge(args)),
        ("verify", lambda: cmd_verify(args)),
    ]

    for name, cmd in phases:
        print(f"\n{'=' * 60}")
        print(f"Phase: {name.upper()}")
        print("=" * 60)

        result = cmd()
        if result != 0:
            print(f"\nFailed at phase: {name}")
            return result

    print(f"\n{'=' * 60}")
    print("All phases completed successfully!")
    print("=" * 60)

    # Generate report
    report_path = manager.generate_summary_report()
    print(f"\nReport: {report_path}")

    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    """Clean up workspace."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized.")
        return 0

    manager.cleanup(keep_reports=not args.all)
    print("Workspace cleaned up.")

    return 0


def cmd_set_order(args: argparse.Namespace) -> int:
    """Set the processing order for ambiguous input files."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    # Get current inputs (sequential ones)
    current_inputs = manager.state.inputs
    ambiguous = manager.get_ambiguous_inputs()

    if not ambiguous:
        print("No ambiguous files to order.")
        return 0

    # Validate provided order
    provided_files = args.files
    ambiguous_names = {Path(a).name for a in ambiguous}
    provided_names = set(provided_files)

    missing = ambiguous_names - provided_names
    extra = provided_names - ambiguous_names

    if missing:
        print(f"Missing files in order: {', '.join(missing)}")
        return 1
    if extra:
        print(f"Unknown files specified: {', '.join(extra)}")
        return 1

    # Build full ordered list: current sequential + user-ordered ambiguous
    ambiguous_map = {Path(a).name: a for a in ambiguous}
    ordered_ambiguous = [ambiguous_map[name] for name in provided_files]

    full_order = current_inputs + ordered_ambiguous
    manager.set_input_order(full_order)

    print("Input order set:")
    for i, inp in enumerate(full_order, 1):
        print(f"  {i}. {Path(inp).name}")

    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Run library discovery phase."""
    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized. Run 'init' first.")
        return 1

    # Ensure libraries directory exists
    manager.structure.libraries_dir.mkdir(exist_ok=True)

    # Extract units from all input files
    tracker = ProvenanceTracker()
    all_units = []

    combined_content = manager.get_combined_content()
    if not combined_content.strip():
        print("No input content found")
        return 1

    # Process each input file separately for proper provenance
    for input_path in manager.state.inputs:
        path = Path(input_path)
        if not path.exists():
            continue

        content = path.read_text(encoding="utf-8")

        # Determine patch_id from filename (e.g., p1.md -> "p1")
        patch_id = None
        name = path.stem
        if (name.startswith("p") and name[1:].isdigit()) or path.parent.name == "patches":
            patch_id = name

        units = tracker.extract_units_from_file(content, str(path), patch_id)
        all_units.extend(units)

    print(f"Extracted {len(all_units)} units from {len(manager.state.inputs)} input files")

    if not all_units:
        print("No units extracted - check input format")
        return 1

    # Run library discovery with keyword config if available
    print("Running library discovery...")
    config_path = spec_folder / "library_keywords.yaml"
    if not config_path.exists():
        config_path = None

    labels = discover_libraries_sync(all_units, config_path=config_path)

    print(f"Discovered labels for {len(labels)} elements")

    # Generate libs.md from labels
    libs_content = _generate_libs_md(all_units, labels)
    libs_md_path = spec_folder / "libs.md"
    libs_md_path.write_text(libs_content, encoding="utf-8")
    print(f"Generated: {libs_md_path}")

    # Generate library files
    library_contents = _generate_library_files(all_units, labels)
    for lib_name, content in library_contents.items():
        lib_path = manager.structure.libraries_dir / f"{lib_name}.md"
        lib_path.write_text(content, encoding="utf-8")
        print(f"Generated: {lib_path}")

    # Generate plan.md as projection
    plan_content = _generate_plan_md(all_units, labels)
    plan_path = spec_folder / "plan.md"
    plan_path.write_text(plan_content, encoding="utf-8")
    print(f"Generated: {plan_path}")

    print("\nDiscovery complete:")
    print(f"  Libraries: {len(library_contents)}")
    print(f"  Units assigned: {len(labels)}")

    return 0


def _generate_libs_md(units: list, labels: dict) -> str:
    """Generate libs.md content from discovery labels."""
    lines = []

    # Group units by their primary library
    by_library: dict[str, list] = {}
    for unit in units:
        if unit.id in labels:
            label_info = labels[unit.id]
            primary = label_info.primary or "other"
            relations = label_info.relations or []
            relations = [r for r in relations if r != primary]  # Remove self-refs
        else:
            primary = "other"
            relations = []

        if unit.declarations:
            decl = unit.declarations[0]
            if primary not in by_library:
                by_library[primary] = []
            by_library[primary].append((decl, list(set(relations))))

    # Sort and format
    for lib_name in sorted(by_library.keys()):
        for decl, relations in sorted(by_library[lib_name], key=lambda x: x[0]):
            lines.append(f"- ([={decl}])")
            lines.append(f"  - primary: {lib_name}")
            rel_str = ", ".join(sorted(set(relations))) if relations else ""
            lines.append(f"  - related: {rel_str}")

    return "\n".join(lines) + "\n" if lines else "# No libraries discovered\n"


def _generate_library_files(units: list, labels: dict) -> dict[str, str]:
    """Generate library file contents from discovery labels."""
    libraries: dict[str, list[str]] = {}

    for unit in units:
        if unit.id in labels:
            label_info = labels[unit.id]
            primary = label_info.primary or "other"
        else:
            primary = "other"

        if primary not in libraries:
            libraries[primary] = []
        libraries[primary].append(unit.content)

    # Format each library
    result = {}
    for lib_name, contents in libraries.items():
        header = f"# {lib_name.title()} Library\n\n"
        body = "\n\n".join(contents)
        result[lib_name] = header + body

    return result


def _generate_plan_md(units: list, labels: dict) -> str:
    """Generate plan.md as projection of all units."""
    lines = ["# Plan\n"]

    # Group by patch/source
    by_source: dict[str, list] = {}
    for unit in units:
        source = unit.introduced_by or "unknown"
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(unit)

    # Output in order
    for source in sorted(by_source.keys()):
        if source != "unknown":
            lines.append(f"\n## From {source}\n")
        for unit in by_source[source]:
            lines.append(unit.content)
            lines.append("")

    return "\n".join(lines)


def cmd_gaps(args: argparse.Namespace) -> int:
    """Show or update gaps.md with detected gaps."""
    from spec_manager.core.gaps import detect_gaps, format_gaps_md

    spec_folder = Path(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    # Get library content - this is where the actual spec lives
    library_content = manager.get_library_content()

    # Build registry by scanning library files
    registry = LibsRegistry.from_libraries(manager.structure.libraries_dir)

    # Detect gaps in library content
    gaps = detect_gaps(library_content, registry, manager.structure.libraries_dir)

    print(f"Gaps detected: {len(gaps)}")
    for gap in gaps[:10]:
        print(f"  [{gap['type']}] {gap['description']}")
    if len(gaps) > 10:
        print(f"  ... and {len(gaps) - 10} more")

    if args.update:
        gaps_content = format_gaps_md(gaps)
        manager.structure.gaps_md.write_text(gaps_content, encoding="utf-8")
        print(f"\nUpdated: {manager.structure.gaps_md}")

    return 0


def main() -> int:
    """Main entry point for the spec manager CLI.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    parser = argparse.ArgumentParser(
        description="Spec Manager - Manage specification libraries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize workspace")
    p_init.add_argument("spec_folder", help="Path to spec folder")
    p_init.add_argument("--force", action="store_true", help="Clear existing workspace")

    # status
    p_status = subparsers.add_parser("status", help="Show workspace status")
    p_status.add_argument("spec_folder", help="Path to spec folder")
    p_status.add_argument("--json", action="store_true", help="Output JSON")

    # stage
    p_stage = subparsers.add_parser("stage", help="Run cleaning phase")
    p_stage.add_argument("spec_folder", help="Path to spec folder")
    p_stage.add_argument(
        "--max-passes", type=int, default=10, help="Maximum strategy passes (default: 10)"
    )

    # plan
    p_plan = subparsers.add_parser("plan", help="Run discovery phase")
    p_plan.add_argument("spec_folder", help="Path to spec folder")

    # merge
    p_merge = subparsers.add_parser("merge", help="Run review phase")
    p_merge.add_argument("spec_folder", help="Path to spec folder")
    p_merge.add_argument("--apply", action="store_true", help="Apply changes (not dry-run)")

    # verify
    p_verify = subparsers.add_parser("verify", help="Run finalization phase")
    p_verify.add_argument("spec_folder", help="Path to spec folder")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Run analysis")
    p_analyze.add_argument("spec_folder", help="Path to spec folder")
    p_analyze.add_argument("--json", action="store_true", help="Output JSON")

    # resolve
    p_resolve = subparsers.add_parser("resolve", help="Apply restructuring suggestions")
    p_resolve.add_argument("spec_folder", help="Path to spec folder")
    p_resolve.add_argument("--dry-run", action="store_true", help="Show what would be done")
    p_resolve.add_argument(
        "--min-confidence",
        type=float,
        default=0.7,
        help="Minimum confidence to auto-apply (default: 0.7)",
    )

    # run
    p_run = subparsers.add_parser("run", help="Run all phases")
    p_run.add_argument("spec_folder", help="Path to spec folder")
    p_run.add_argument("--apply", action="store_true", help="Apply changes (not dry-run)")
    p_run.add_argument(
        "--max-passes", type=int, default=10, help="Maximum strategy passes (default: 10)"
    )

    # cleanup
    p_cleanup = subparsers.add_parser("cleanup", help="Clean up workspace")
    p_cleanup.add_argument("spec_folder", help="Path to spec folder")
    p_cleanup.add_argument("--all", action="store_true", help="Remove reports too")

    # set-order
    p_set_order = subparsers.add_parser("set-order", help="Set order for ambiguous inputs")
    p_set_order.add_argument("spec_folder", help="Path to spec folder")
    p_set_order.add_argument("files", nargs="+", help="Files in desired order")

    # gaps
    p_gaps = subparsers.add_parser("gaps", help="Detect and show gaps")
    p_gaps.add_argument("spec_folder", help="Path to spec folder")
    p_gaps.add_argument("--update", action="store_true", help="Update gaps.md")

    # discover
    p_discover = subparsers.add_parser("discover", help="Run library discovery")
    p_discover.add_argument("spec_folder", help="Path to spec folder")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "stage": cmd_stage,
        "plan": cmd_plan,
        "merge": cmd_merge,
        "verify": cmd_verify,
        "analyze": cmd_analyze,
        "resolve": cmd_resolve,
        "run": cmd_run,
        "cleanup": cmd_cleanup,
        "set-order": cmd_set_order,
        "gaps": cmd_gaps,
        "discover": cmd_discover,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

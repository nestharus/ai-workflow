"""Command-line interface for spec manager.

Usage:
    uv run spec-manager <command> <spec_folder> [options]

Commands:
    init        Initialize workspace in a spec folder
    status      Show workspace and phase status
    stage       Run CLEANING phase (validate inputs)
    plan        Run DISCOVERY phase (decompose changes)
    merge       Run REVIEW phase (apply changes)
    verify      Run FINALIZATION phase (confirm correctness)
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
from spec_manager.core.project_root import resolve_from_root
from spec_manager.core.provenance import ProvenanceTracker
from spec_manager.discovery import discover_libraries_sync
from spec_manager.merging import run_merging
from spec_manager.planning import run_planning
from spec_manager.staging.pipeline import StagingPipeline
from spec_manager.verification import run_verification
from spec_manager.workspace import PhaseStatus, WorkspaceManager
from spec_manager.workspace.state import Phase


def _resolve_spec_folder(raw_path: str) -> Path:
    """Resolve a spec folder path relative to the project root when not absolute."""
    p = Path(raw_path)
    if p.is_absolute():
        return p
    return resolve_from_root(raw_path)


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize workspace."""
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
        print(f"  uv run spec-manager set-order {spec_folder} file1.md file2.md ...")
        print("\nOr rename files with sequence numbers (e.g., 1-feature.md, 2-other.md)")
        return 2  # Special return code for ambiguous ordering

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show workspace status."""
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
    """Run CLEANING phase (staging) using strategy pipeline."""
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
    """Run DISCOVERY phase (planning)."""
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
        manager.fail_phase(Phase.DISCOVERY, "No input content found (no plan.md or patches)")
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
    """Run REVIEW phase (merging)."""
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
    """Run FINALIZATION phase (verification)."""
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
    spec_folder = _resolve_spec_folder(args.spec_folder)
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

    spec_folder = _resolve_spec_folder(args.spec_folder)
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
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
    spec_folder = _resolve_spec_folder(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    if not manager.is_initialized:
        print("Workspace not initialized.")
        return 0

    manager.cleanup(keep_reports=not args.all)
    print("Workspace cleaned up.")

    return 0


def cmd_set_order(args: argparse.Namespace) -> int:
    """Set the processing order for ambiguous input files."""
    spec_folder = _resolve_spec_folder(args.spec_folder)
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
    spec_folder = _resolve_spec_folder(args.spec_folder)
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

    spec_folder = _resolve_spec_folder(args.spec_folder)
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


def cmd_refine(args: argparse.Namespace) -> int:
    """Run spec refinement (interactive or auto mode)."""
    from spec_manager.refinement.interactive.signal_resolver import create_resolver
    from spec_manager.refinement.interactive.workflow import InteractiveWorkflow

    workspace = Path(args.workspace) if args.workspace else Path.cwd() / "runs" / args.run_id
    if not workspace.exists():
        print(f"Workspace not found: {workspace}")
        return 1

    spec_path = workspace / "spec.md"
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}")
        return 1

    spec_text = spec_path.read_text(encoding="utf-8")

    steering_path = Path(args.steering) if args.steering else None
    file_signals = getattr(args, "file_signals", False)

    # Determine resolver mode
    if file_signals:
        mode_str = "file"
    elif args.auto:
        mode_str = "auto"
    else:
        mode_str = "interactive"

    print(f"Running {mode_str} refinement: run_id={args.run_id}")
    print(f"  Workspace: {workspace}")
    if args.auto or file_signals:
        print(f"  Steering: {steering_path or 'none'}")
        print(f"  Research: {args.research}")
        print(f"  Evidence store: {args.evidence_store}")
    print(f"  Max iterations: {args.max_iterations}")

    resolver = create_resolver(
        mode=mode_str,
        workspace=workspace,
        steering_path=steering_path,
        use_research=args.research,
        use_evidence_store=args.evidence_store,
    )

    workflow = InteractiveWorkflow(
        workspace=workspace,
        max_iterations=args.max_iterations,
        signal_resolver=resolver,
    )

    refined = workflow.run(spec_text)

    output_path = workspace / "refined_spec.md"
    output_path.write_text(refined, encoding="utf-8")
    print(f"Refined spec saved: {output_path}")
    return 0


def cmd_ambiguities_list(args: argparse.Namespace) -> int:
    """List detected ambiguities in a spec."""
    from spec_manager.refinement.interactive.ambiguity_detector import AmbiguityDetector

    workspace = Path(args.workspace) if args.workspace else Path.cwd() / "runs" / args.run_id
    if not workspace.exists():
        print(f"Workspace not found: {workspace}")
        return 1

    spec_path = workspace / "spec.md"
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}")
        return 1

    spec_text = spec_path.read_text(encoding="utf-8")

    print(f"Detecting ambiguities: run_id={args.run_id}")
    print(f"  Workspace: {workspace}")

    detector = AmbiguityDetector()
    ambiguities = detector.detect(spec_text, workspace)

    if not ambiguities:
        print("\nNo ambiguities detected.")
        return 0

    print(f"\nFound {len(ambiguities)} ambiguities:\n")
    for amb in ambiguities:
        print(f"  [{amb.ambiguity_id}] ({amb.ambiguity_type}, confidence={amb.confidence:.0%})")
        print(f"    Location: {amb.source_location}")
        print(f"    Text: {amb.source_text[:120]}{'...' if len(amb.source_text) > 120 else ''}")
        print(f"    Question: {amb.suggested_question}")
        print()

    return 0


def cmd_evidence_store(args: argparse.Namespace) -> int:
    """Handle evidence-store subcommands."""
    evidence_store_commands = {
        "hollow": cmd_evidence_store_hollow,
        "rebuild-index": cmd_evidence_store_rebuild_index,
        "search": cmd_evidence_store_search,
        "status": cmd_evidence_store_status,
    }
    return evidence_store_commands[args.evidence_store_command](args)


def cmd_evidence_store_hollow(args: argparse.Namespace) -> int:
    """Manually trigger hollow-out for one or all libraries."""
    from spec_manager.refinement.hollowed_spec.hooks import on_spec_completed
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)

    if not manager.structure.libraries_dir.exists():
        print(f"Libraries directory not found: {manager.structure.libraries_dir}")
        return 1

    if args.lib_id:
        lib_ids = [args.lib_id]
    else:
        lib_ids = [d.name for d in sorted(manager.structure.libraries_dir.iterdir()) if d.is_dir()]

    if not lib_ids:
        print("No libraries found.")
        return 0

    hollowed_count = 0
    for lib_id in lib_ids:
        spec_path = manager.structure.libraries_dir / lib_id / "spec.md"
        if not spec_path.exists():
            print(f"  Skipping {lib_id}: no spec.md")
            continue
        print(f"  Hollowing {lib_id}...")
        on_spec_completed(lib_id, manager)
        hollowed_count += 1

    print(f"Hollowed {hollowed_count} library specs.")
    return 0


def cmd_evidence_store_rebuild_index(args: argparse.Namespace) -> int:
    """Rebuild the evidence index from scratch."""
    from spec_manager.refinement.hollowed_spec.hooks import rebuild_evidence_index
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)
    count = rebuild_evidence_index(manager)
    print(f"Rebuilt evidence index: {count} specs indexed.")
    return 0


def cmd_evidence_store_search(args: argparse.Namespace) -> int:
    """Interactive search for testing/debugging."""
    from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
    from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)
    index_path = manager.structure.evidence_index_path

    if not index_path.exists():
        print(f"Evidence index not found: {index_path}")
        print("Run 'evidence-store rebuild-index' first.")
        return 1

    index = EvidenceIndex.load(index_path)
    searcher = EvidenceSearcher(index)
    results = searcher.search(query=args.query, max_results=args.max_results)

    if not results:
        print("No results found.")
        return 0

    print(f"Found {len(results)} results:\n")
    for i, result in enumerate(results, 1):
        print(f"  {i}. [{result.lib_id}] {result.section_path} (score={result.score:.2f})")
        text_preview = result.paragraph.text[:200]
        if len(result.paragraph.text) > 200:
            text_preview += "..."
        print(f"     {text_preview}")
        if result.matched_keywords:
            print(f"     Keywords: {', '.join(result.matched_keywords)}")
        if result.matched_entities:
            print(f"     Entities: {', '.join(result.matched_entities)}")
        print()

    return 0


def cmd_evidence_store_status(args: argparse.Namespace) -> int:
    """Show index stats."""
    from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)
    index_path = manager.structure.evidence_index_path

    if not index_path.exists():
        print(f"Evidence index not found: {index_path}")
        print("Run 'evidence-store rebuild-index' first.")
        return 1

    index = EvidenceIndex.load(index_path)

    print("Evidence Store Status:")
    print(f"  Indexed specs: {len(index.specs)}")
    print(f"  Total paragraphs: {index.total_paragraphs}")
    print(f"  Keyword count: {index.total_keywords}")
    print(f"  Entity count: {index.total_entities}")
    print()

    if index.specs:
        print("  Libraries:")
        for lib_id, spec in sorted(index.specs.items()):
            print(f"    {lib_id}: {len(spec.sections)} sections, {len(spec.paragraphs)} paragraphs")

    return 0


def cmd_adjacency(args: argparse.Namespace) -> int:
    """Run adjacency analysis on source and spec files."""
    from spec_manager.analysis.adjacency.runner import (
        AdjacencyAnalysisConfig,
        run_adjacency_analysis,
        save_report,
    )

    source_dirs = [Path(d) for d in args.source_dir] if args.source_dir else []
    spec_dirs = [Path(d) for d in args.spec_dir] if args.spec_dir else []

    if not source_dirs and not spec_dirs:
        print("At least one --source-dir or --spec-dir is required.")
        return 1

    config = AdjacencyAnalysisConfig(
        source_dirs=source_dirs,
        spec_dirs=spec_dirs,
        include_call_graph=not args.no_call_graph,
        include_event_graph=not args.no_event_graph,
        include_store_graph=not args.no_store_graph,
        include_cooccurrence=not args.no_cooccurrence,
        output_format=args.format,
        output_path=Path(args.output) if args.output else None,
    )

    print("Running adjacency analysis...")
    if source_dirs:
        print(f"  Source dirs: {', '.join(str(d) for d in source_dirs)}")
    if spec_dirs:
        print(f"  Spec dirs: {', '.join(str(d) for d in spec_dirs)}")

    report = run_adjacency_analysis(config)

    print("\nAdjacency Analysis Results:")
    print(f"  Total nodes: {report.total_nodes}")
    print(f"  Total edges: {report.total_edges}")
    print(f"  Connected components: {report.num_components}")

    if report.signal_type_counts:
        print("\n  Signal types:")
        for sig_type, count in sorted(report.signal_type_counts.items()):
            weight = report.signal_type_weights.get(sig_type, 0.0)
            print(f"    {sig_type}: {count} edges (weight: {weight:.2f})")

    if report.disconnected_warnings:
        print(f"\n  Warnings ({len(report.disconnected_warnings)}):")
        for warning in report.disconnected_warnings:
            print(f"    - {warning}")

    if args.output:
        output_path = save_report(report, config)
        print(f"\n  Report saved: {output_path}")
    elif args.json:
        print("\nJSON:")
        print(json.dumps(report.to_dict(), indent=2))

    return 0


def cmd_phase_02(args: argparse.Namespace) -> int:
    """Run Phase 2 clean/compose/compliance workflow."""
    run_id = args.run_id

    from spec_manager.refinement.workflows.phase_02_clean import run_phase_02_clean

    result = run_phase_02_clean(run_id)
    if result.get("success"):
        print(f"Phase 2 completed successfully for run {run_id}")
        return 0

    print(f"Phase 2 failed: {result.get('error')}", file=sys.stderr)
    return 1


def cmd_generate_analysis(args: argparse.Namespace) -> int:
    """Generate the analysis file (computed artifact)."""
    from spec_manager.analysis.generator import (
        generate_analysis_file,
        write_analysis_json,
    )
    from spec_manager.analysis.report_renderer import render_analysis_markdown

    spec_folder = _resolve_spec_folder(args.spec_folder)
    manager = WorkspaceManager(spec_folder)

    # Determine algorithmic and architectural directories.
    # The convention is that algorithmic atoms live under the spec folder
    # itself, and architecture lives in the workspace architecture dir.
    algorithmic_dir = spec_folder
    architectural_dir = manager.structure.libraries_dir

    print(f"Generating analysis file for: {spec_folder}")
    print(f"  Algorithmic dir: {algorithmic_dir}")
    print(f"  Architectural dir: {architectural_dir}")

    analysis = generate_analysis_file(
        algorithmic_dir=algorithmic_dir,
        architectural_dir=architectural_dir,
        run_id=getattr(manager, "run_id", ""),
    )

    output_format = args.format if hasattr(args, "format") else "both"

    if output_format in ("json", "both"):
        json_dir = spec_folder / "analysis"
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / "analysis.json"
        write_analysis_json(analysis, json_path)
        print(f"  JSON: {json_path}")

    if output_format in ("markdown", "both"):
        reports_dir = spec_folder / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        md_path = reports_dir / "analysis.md"
        md_content = render_analysis_markdown(analysis)
        md_path.write_text(md_content, encoding="utf-8")
        print(f"  Markdown: {md_path}")

    if hasattr(args, "json") and args.json:
        print()
        print(json.dumps(analysis.model_dump(), indent=2, sort_keys=True))

    summary = analysis.summary
    print("\nAnalysis Summary:")
    print(f"  Total atoms: {summary.get('total_atoms', 0)}")
    print(f"  Implemented: {summary.get('implemented_atoms', 0)}")
    print(f"  Unimplemented: {summary.get('unimplemented_atoms', 0)}")
    print(f"  Orphaned architecture: {summary.get('orphaned_architecture', 0)}")
    print(f"  Lineage edges: {summary.get('total_lineage_edges', 0)}")

    return 0


def cmd_scan_source(args: argparse.Namespace) -> int:
    """Run edit-in-place source analysis on a Python file or directory.

    Produces a gap report showing all spec comments (gaps) and stub functions.
    """
    from spec_manager.core.edit_in_place import (
        ProjectTranslationState,
        analyze_file,
        analyze_project,
        format_gap_report,
    )

    target = Path(args.path)
    if not target.exists():
        print(f"Path not found: {target}")
        return 1

    exclude_patterns = args.exclude if args.exclude else None

    if target.is_file():
        try:
            file_state = analyze_file(str(target))
        except SyntaxError as e:
            print(f"Syntax error in {target}: {e}")
            return 1
        # Wrap in ProjectTranslationState for uniform handling
        project_state = ProjectTranslationState(files={str(target): file_state})
    else:
        project_state = analyze_project(str(target), exclude=exclude_patterns)

    output_format = args.format if hasattr(args, "format") and args.format else "text"

    if output_format == "json":
        import dataclasses

        def _to_dict(obj: object) -> object:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, dict):
                return {k: _to_dict(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_to_dict(i) for i in obj]
            if hasattr(obj, "value"):
                return obj.value  # type: ignore[union-attr]
            return obj

        result_dict = {
            "files": {path: _to_dict(state) for path, state in project_state.files.items()},
            "total_gaps": project_state.total_gaps,
            "total_functions": project_state.total_functions,
            "is_complete": project_state.is_complete,
        }
        output_text = json.dumps(result_dict, indent=2)
    else:
        output_text = format_gap_report(project_state)

    if hasattr(args, "output") and args.output:
        output_path = Path(args.output)
        output_path.write_text(output_text)
        print(f"Report written to: {output_path}")
    else:
        print(output_text)

    return 0


def cmd_branches(args: argparse.Namespace) -> int:
    """Handle branches subcommands."""
    branches_commands = {
        "init": cmd_branches_init,
        "gaps": cmd_branches_gaps,
        "promote": cmd_branches_promote,
        "analyze": cmd_branches_analyze,
        "status": cmd_branches_status,
        "run": cmd_branches_run,
    }
    return branches_commands[args.branches_command](args)


def cmd_branches_init(args: argparse.Namespace) -> int:
    """Initialize branch layout and optionally collapse codebase."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_init

    source_dir = Path(args.source_dir) if args.source_dir else None
    if args.from_scan:
        return cmd_branches_init_from_scan(args)

    result = run_branch_init(args.run_id, source_dir=source_dir)
    if not result.get("success"):
        print(f"Branch init failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Branch layout initialized for run {args.run_id}")
    print(f"  Atoms registered: {outputs.get('atom_count', 0)}")
    if outputs.get("atom_count_by_kind"):
        for kind, count in outputs["atom_count_by_kind"].items():
            print(f"    {kind}: {count}")
    if outputs.get("collapse_warnings"):
        print(f"  Warnings: {len(outputs['collapse_warnings'])}")
    return 0


def cmd_branches_init_from_scan(args: argparse.Namespace) -> int:
    """Initialize branches using edit-in-place scan."""
    from spec_manager.refinement.workflows.branch_lifecycle import (
        run_branch_init_from_edit_in_place,
    )

    source_dir = Path(args.from_scan)
    if not source_dir.exists():
        print(f"Source directory not found: {source_dir}", file=sys.stderr)
        return 1

    result = run_branch_init_from_edit_in_place(args.run_id, source_dir=source_dir)
    if not result.get("success"):
        print(f"Branch init from scan failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Branch layout initialized from scan for run {args.run_id}")
    print(f"  Atoms registered: {outputs.get('atom_count', 0)}")
    print(f"  EIP lineage mappings: {outputs.get('eip_lineage_count', 0)}")
    print(f"  EIP gaps found: {outputs.get('eip_gap_count', 0)}")
    return 0


def cmd_branches_gaps(args: argparse.Namespace) -> int:
    """Scan algorithmic branch for gaps."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_gaps

    result = run_branch_gaps(args.run_id)
    if not result.get("success"):
        print(f"Branch gaps scan failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Gap scan complete for run {args.run_id}")
    print(f"  Total gaps: {outputs.get('total_gaps', 0)}")
    if outputs.get("gaps_by_type"):
        for gap_type, count in outputs["gaps_by_type"].items():
            print(f"    {gap_type}: {count}")
    return 0


def cmd_branches_promote(args: argparse.Namespace) -> int:
    """Promote atoms to architectural branch."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_promote

    atom_ids = args.atom_ids if hasattr(args, "atom_ids") and args.atom_ids else None
    result = run_branch_promote(
        args.run_id,
        skip_compliance=args.skip_compliance,
        atom_ids=atom_ids,
    )
    if not result.get("success"):
        print(f"Branch promote failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Promotion complete for run {args.run_id}")
    print(f"  Promoted: {outputs.get('promoted_count', 0)}")
    print(f"  Skipped: {outputs.get('skipped_count', 0)}")
    print(f"  New pins: {len(outputs.get('new_pin_ids', []))}")
    compliance = outputs.get("compliance_passed")
    if compliance is not None:
        print(f"  Compliance passed: {compliance}")
    return 0


def cmd_branches_analyze(args: argparse.Namespace) -> int:
    """Regenerate analysis branch."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_analyze

    result = run_branch_analyze(args.run_id)
    if not result.get("success"):
        print(f"Branch analyze failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Analysis complete for run {args.run_id}")
    print(f"  Atoms analyzed: {outputs.get('atom_count', 0)}")
    print(f"  Orphaned: {outputs.get('orphaned_count', 0)}")
    print(f"  Subgraphs: {outputs.get('subgraph_count', 0)}")
    return 0


def cmd_branches_status(args: argparse.Namespace) -> int:
    """Show branch system status."""
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager
    from spec_manager.refinement.workspace.state import Phase

    input_folder = Path(".")
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)

    if not manager.is_initialized:
        print("Workspace not initialized.")
        return 0

    branch_initialized = manager.branches.is_initialized()
    print(f"Branch status for run {args.run_id}:")
    print(f"  Initialized: {branch_initialized}")

    if branch_initialized:
        import contextlib

        with contextlib.suppress(Exception):
            manager.branches.load()
        atoms = manager.branches.list_atoms()
        pins = manager.branches.pin_registry.list_all()
        slices = list(manager.branches.slice_navigator._slices.values())
        print(f"  Atoms: {len(atoms)}")
        print(f"  Pins: {len(pins)}")
        print(f"  Slices: {len(slices)}")

    # Show branch phase statuses
    branch_phases = [
        Phase.BRANCH_INIT,
        Phase.BRANCH_GAPS,
        Phase.BRANCH_PROMOTE,
        Phase.BRANCH_ANALYZE,
    ]
    print("  Phase status:")
    for phase in branch_phases:
        result = manager.state.phases[phase.value]
        print(f"    {phase.value}: {result.status.value}")

    return 0


def cmd_branches_run(args: argparse.Namespace) -> int:
    """Run all branch lifecycle phases in sequence."""
    from spec_manager.refinement.workflows.branch_lifecycle import (
        run_branch_analyze,
        run_branch_gaps,
        run_branch_init,
        run_branch_promote,
    )

    source_dir = Path(args.source_dir) if args.source_dir else None

    steps = [
        ("init", lambda: run_branch_init(args.run_id, source_dir=source_dir)),
        ("gaps", lambda: run_branch_gaps(args.run_id)),
        (
            "promote",
            lambda: run_branch_promote(args.run_id, skip_compliance=args.skip_compliance),
        ),
        ("analyze", lambda: run_branch_analyze(args.run_id)),
    ]

    for name, step_fn in steps:
        print(f"Running branch {name}...")
        result = step_fn()
        if not result.get("success"):
            print(f"Branch {name} failed: {result.get('error')}", file=sys.stderr)
            return 1
        print(f"  Branch {name} completed.")

    print(f"All branch phases completed for run {args.run_id}.")
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
    p_stage = subparsers.add_parser("stage", help="Run CLEANING phase")
    p_stage.add_argument("spec_folder", help="Path to spec folder")
    p_stage.add_argument(
        "--max-passes", type=int, default=10, help="Maximum strategy passes (default: 10)"
    )

    # plan
    p_plan = subparsers.add_parser("plan", help="Run DISCOVERY phase")
    p_plan.add_argument("spec_folder", help="Path to spec folder")

    # merge
    p_merge = subparsers.add_parser("merge", help="Run REVIEW phase")
    p_merge.add_argument("spec_folder", help="Path to spec folder")
    p_merge.add_argument("--apply", action="store_true", help="Apply changes (not dry-run)")

    # verify
    p_verify = subparsers.add_parser("verify", help="Run FINALIZATION phase")
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

    # phase-02
    p_phase_02 = subparsers.add_parser(
        "phase-02",
        help="Run Phase 2 clean/compose/compliance workflow",
    )
    p_phase_02.add_argument("run_id", help="Run identifier")

    # discover
    p_discover = subparsers.add_parser("discover", help="Run library discovery")
    p_discover.add_argument("spec_folder", help="Path to spec folder")

    # refine (unified command)
    p_refine = subparsers.add_parser("refine", help="Run spec refinement")
    p_refine.add_argument("run_id", help="Run identifier")
    p_refine.add_argument("--workspace", help="Workspace directory")
    p_refine.add_argument(
        "--auto", action="store_true", help="Use automated mode (default: interactive)"
    )
    p_refine.add_argument("--steering", help="Path to steering script JSON (auto mode)")
    p_refine.add_argument(
        "--research", action="store_true", help="Use research-based resolution (auto mode)"
    )
    p_refine.add_argument(
        "--evidence-store", action="store_true", help="Use evidence store search (auto mode)"
    )
    p_refine.add_argument(
        "--max-iterations", type=int, default=5, help="Max iterations (default: 5)"
    )
    p_refine.add_argument(
        "--file-signals",
        action="store_true",
        help="Use file-based signal exchange (write signals to disk, read responses)",
    )

    # ambiguities (sub-group with "list" subcommand)
    p_ambiguities = subparsers.add_parser("ambiguities", help="Ambiguity detection commands")
    ambiguities_sub = p_ambiguities.add_subparsers(dest="ambiguities_command", required=True)
    p_amb_list = ambiguities_sub.add_parser("list", help="List detected ambiguities")
    p_amb_list.add_argument("run_id", help="Run identifier")
    p_amb_list.add_argument("--workspace", help="Workspace directory")

    # evidence-store
    p_evidence_store = subparsers.add_parser(
        "evidence-store", help="Evidence store management commands"
    )
    evidence_store_sub = p_evidence_store.add_subparsers(
        dest="evidence_store_command", required=True
    )

    p_es_hollow = evidence_store_sub.add_parser("hollow", help="Hollow out specs for a run")
    p_es_hollow.add_argument("run_id", help="Run identifier")
    p_es_hollow.add_argument("--lib-id", help="Specific library ID to hollow (default: all)")
    p_es_hollow.add_argument("--input-folder", help="Input folder path", default=".")

    p_es_rebuild = evidence_store_sub.add_parser("rebuild-index", help="Rebuild evidence index")
    p_es_rebuild.add_argument("run_id", help="Run identifier")
    p_es_rebuild.add_argument("--input-folder", help="Input folder path", default=".")

    p_es_search = evidence_store_sub.add_parser("search", help="Search evidence store")
    p_es_search.add_argument("run_id", help="Run identifier")
    p_es_search.add_argument("--query", required=True, help="Search query text")
    p_es_search.add_argument(
        "--max-results", type=int, default=5, help="Maximum results (default: 5)"
    )
    p_es_search.add_argument("--input-folder", help="Input folder path", default=".")

    p_es_status = evidence_store_sub.add_parser("status", help="Show evidence store status")
    p_es_status.add_argument("run_id", help="Run identifier")
    p_es_status.add_argument("--input-folder", help="Input folder path", default=".")

    # generate-analysis
    p_gen_analysis = subparsers.add_parser(
        "generate-analysis",
        help="Generate analysis file (algorithmic-to-architectural mapping)",
    )
    p_gen_analysis.add_argument("spec_folder", help="Path to spec folder")
    p_gen_analysis.add_argument(
        "--format",
        choices=["markdown", "json", "both"],
        default="both",
        help="Output format (default: both)",
    )
    p_gen_analysis.add_argument("--json", action="store_true", help="Print JSON to stdout")

    # adjacency
    p_adjacency = subparsers.add_parser("adjacency", help="Run adjacency detection analysis")
    p_adjacency.add_argument(
        "--source-dir",
        action="append",
        help="Python source directory to analyze (repeatable)",
    )
    p_adjacency.add_argument(
        "--spec-dir",
        action="append",
        help="Spec markdown directory to analyze (repeatable)",
    )
    p_adjacency.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json)",
    )
    p_adjacency.add_argument(
        "--output",
        help="Output file path",
    )
    p_adjacency.add_argument("--json", action="store_true", help="Print JSON to stdout")
    p_adjacency.add_argument(
        "--no-call-graph",
        action="store_true",
        help="Disable call graph extraction",
    )
    p_adjacency.add_argument(
        "--no-event-graph",
        action="store_true",
        help="Disable event graph extraction",
    )
    p_adjacency.add_argument(
        "--no-store-graph",
        action="store_true",
        help="Disable store touch graph extraction",
    )
    p_adjacency.add_argument(
        "--no-cooccurrence",
        action="store_true",
        help="Disable co-occurrence extraction",
    )

    # scan-source (edit-in-place engine)
    p_scan_source = subparsers.add_parser(
        "scan-source",
        help="Scan Python source for spec comments and stubs (edit-in-place engine)",
    )
    p_scan_source.add_argument("path", help="Path to a Python file or directory")
    p_scan_source.add_argument(
        "--exclude",
        nargs="*",
        help="Glob patterns to exclude (default: test_*, __pycache__)",
    )
    p_scan_source.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    p_scan_source.add_argument(
        "--output",
        help="Write output to file instead of stdout",
    )

    # branches - branch lifecycle management commands
    p_branches = subparsers.add_parser("branches", help="Branch lifecycle management commands")
    branches_sub = p_branches.add_subparsers(dest="branches_command", required=True)

    p_br_init = branches_sub.add_parser("init", help="Initialize branch layout")
    p_br_init.add_argument("run_id", help="Run identifier")
    p_br_init.add_argument("--source-dir", help="Source directory to collapse")
    p_br_init.add_argument("--from-scan", help="Run edit-in-place scan on this directory first")
    p_br_init.add_argument("--force", action="store_true", help="Force re-initialization")

    p_br_gaps = branches_sub.add_parser("gaps", help="Scan algorithmic branch for gaps")
    p_br_gaps.add_argument("run_id", help="Run identifier")

    p_br_promote = branches_sub.add_parser("promote", help="Promote atoms to architectural branch")
    p_br_promote.add_argument("run_id", help="Run identifier")
    p_br_promote.add_argument("--skip-compliance", action="store_true", help="Skip compliance gate")
    p_br_promote.add_argument("--atom-ids", nargs="+", help="Specific atom IDs to promote")

    p_br_analyze = branches_sub.add_parser("analyze", help="Regenerate analysis branch")
    p_br_analyze.add_argument("run_id", help="Run identifier")

    p_br_status = branches_sub.add_parser("status", help="Show branch system status")
    p_br_status.add_argument("run_id", help="Run identifier")

    p_br_run = branches_sub.add_parser("run", help="Run all branch lifecycle phases")
    p_br_run.add_argument("run_id", help="Run identifier")
    p_br_run.add_argument("--source-dir", help="Source directory to collapse")
    p_br_run.add_argument("--skip-compliance", action="store_true", help="Skip compliance gate")

    # pin - pin-function management commands
    from spec_manager.pin_functions.cli import setup_pin_parser

    setup_pin_parser(subparsers)

    # eval - add subcommand group for evaluation
    from spec_manager.refinement.evals.cli import setup_eval_parser

    setup_eval_parser(subparsers)

    # plan-v2 - algorithmic planning subcommand group
    from spec_manager.planning.algo_cli import setup_plan_v2_parser

    setup_plan_v2_parser(subparsers)

    # coverage - entity coverage gap analysis
    from spec_manager.compliance.coverage.cli import setup_coverage_parser

    setup_coverage_parser(subparsers)

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
        "phase-02": cmd_phase_02,
        "discover": cmd_discover,
        "refine": cmd_refine,
        "adjacency": cmd_adjacency,
        "generate-analysis": cmd_generate_analysis,
        "scan-source": cmd_scan_source,
    }

    # Handle eval command separately
    if args.command == "eval":
        from spec_manager.refinement.evals.cli import handle_eval_command

        return handle_eval_command(args)

    # Handle pin sub-group
    if args.command == "pin":
        from spec_manager.pin_functions.cli import handle_pin_command

        return handle_pin_command(args)

    # Handle evidence-store sub-group
    if args.command == "evidence-store":
        return cmd_evidence_store(args)

    # Handle plan-v2 sub-group
    if args.command == "plan-v2":
        from spec_manager.planning.algo_cli import handle_plan_v2_command

        return handle_plan_v2_command(args)

    # Handle coverage sub-group
    if args.command == "coverage":
        from spec_manager.compliance.coverage.cli import handle_coverage_command

        return handle_coverage_command(args)

    # Handle branches sub-group
    if args.command == "branches":
        return cmd_branches(args)

    # Handle ambiguities sub-group
    if args.command == "ambiguities":
        ambiguities_commands = {
            "list": cmd_ambiguities_list,
        }
        return ambiguities_commands[args.ambiguities_command](args)

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

"""Command-line interface for spec manager.

Usage:
    uv run spec <command> [options]

PDD orchestration (primary):
    run                 Run the full PDD pipeline (phases 0-10)
    phase               Run a specific PDD design phase (0-10)
    extract             Phase 0: extract input to PDD format

Module CLIs (standalone PDD modules):
    scan-source         Scan Python source for spec comments/stubs
    branches *          Branch lifecycle management
    pin *               Pin-function management
    plan-v2 *           Algorithmic planning operations
    generate-analysis   Generate analysis file
    adjacency           Run adjacency detection analysis
    coverage *          Entity coverage gap analysis
    eval *              Evaluation framework

Legacy:
    refine              Run spec refinement (interactive or auto mode)
    ambiguities list    List detected ambiguities
    evidence-store *    Evidence store management
    phase-02            Run Phase 2 clean/compose/compliance workflow
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spec_manager.core.project_root import resolve_from_root


def _resolve_spec_folder(raw_path: str) -> Path:
    """Resolve a spec folder path relative to the project root when not absolute."""
    p = Path(raw_path)
    if p.is_absolute():
        return p
    return resolve_from_root(raw_path)


def cmd_run(args: argparse.Namespace) -> int:
    """Run the full PDD pipeline (phases 0-10)."""
    from spec_manager.orchestration.pdd_orchestrator import PDD_PHASE_ORDER, PddOrchestrator
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    run_id = args.run_id
    input_folder = Path(args.input) if args.input else Path.cwd()

    print(f"PDD pipeline: run_id={run_id}")
    print(f"  Input: {input_folder}")

    manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)
    if not manager.is_initialized:
        manager.initialize()

    orchestrator = PddOrchestrator(manager)
    summary = orchestrator.run()

    completed = summary.get("completed", [])
    failed = summary.get("failed", [])
    skipped = summary.get("skipped", [])

    print(f"\nPDD pipeline finished for run {run_id}:")
    if completed:
        print(f"  Completed: {', '.join(completed)}")
    if skipped:
        print(f"  Skipped (already done): {', '.join(skipped)}")
    if failed:
        print(f"  Failed: {', '.join(failed)}")
        return 1

    total = len(PDD_PHASE_ORDER)
    done = len(completed) + len(skipped)
    print(f"  Progress: {done}/{total} phases")
    return 0


def cmd_phase(args: argparse.Namespace) -> int:
    """Run a specific PDD design phase (0-10)."""
    from spec_manager.orchestration.pdd_orchestrator import PDD_PHASE_ORDER, PddOrchestrator
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    phase_number = args.phase_number
    if phase_number < 0 or phase_number > 10:
        print(f"Invalid phase number: {phase_number}. Must be 0-10.", file=sys.stderr)
        return 1

    phase = PDD_PHASE_ORDER[phase_number]
    run_id = args.run_id
    input_folder = Path(args.input) if args.input else Path.cwd()

    print(f"PDD phase {phase_number} ({phase.value}): run_id={run_id}")
    print(f"  Input: {input_folder}")

    manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)
    if not manager.is_initialized:
        manager.initialize()

    orchestrator = PddOrchestrator(manager)
    try:
        outputs = orchestrator.run_phase(phase)
        print(f"\nPhase {phase_number} ({phase.value}) completed.")
        if outputs:
            for key, value in outputs.items():
                print(f"  {key}: {value}")
        return 0
    except NotImplementedError as exc:
        print(f"\nPhase {phase_number} ({phase.value}) not yet implemented: {exc}")
        return 1
    except Exception as exc:
        print(f"\nPhase {phase_number} ({phase.value}) failed: {exc}", file=sys.stderr)
        return 1


def cmd_extract(args: argparse.Namespace) -> int:
    """Phase 0: extract input to PDD format.

    This is an alias for ``phase 0``.  Phase 0 is designed but not yet
    implemented -- the command reports this clearly.
    """
    from spec_manager.orchestration.pdd_orchestrator import PDD_PHASE_ORDER, PddOrchestrator
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    input_path = Path(args.path) if args.path else Path.cwd()
    run_id = args.run_id

    print(f"PDD extraction (phase 0): run_id={run_id}")
    print(f"  Input: {input_path}")

    manager = WorkspaceManager(run_id=run_id, input_folder=input_path)
    if not manager.is_initialized:
        manager.initialize()

    orchestrator = PddOrchestrator(manager)
    phase = PDD_PHASE_ORDER[0]  # Phase.EXTRACTION
    try:
        outputs = orchestrator.run_phase(phase)
        print("\nExtraction completed.")
        if outputs:
            for key, value in outputs.items():
                print(f"  {key}: {value}")
        return 0
    except NotImplementedError as exc:
        print(f"\nExtraction not yet implemented: {exc}")
        return 1
    except Exception as exc:
        print(f"\nExtraction failed: {exc}", file=sys.stderr)
        return 1


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
    libraries_dir = spec_folder / "libraries"

    print(f"Generating analysis file for: {spec_folder}")
    print(f"  Algorithmic dir: {spec_folder}")
    print(f"  Architectural dir: {libraries_dir}")

    analysis = generate_analysis_file(
        algorithmic_dir=spec_folder,
        architectural_dir=libraries_dir,
        run_id="",
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

    # ── PDD orchestration commands ──────────────────────────────────

    # run - full PDD pipeline
    p_run = subparsers.add_parser(
        "run",
        help="Run the full PDD pipeline (phases 0-10)",
    )
    p_run.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="Run identifier (auto-generated if omitted)",
    )
    p_run.add_argument(
        "--input",
        help="Path to input spec folder",
    )

    # phase - run a specific PDD phase
    p_phase = subparsers.add_parser(
        "phase",
        help="Run a specific PDD design phase (0-10)",
    )
    p_phase.add_argument(
        "phase_number",
        type=int,
        help="Phase number (0-10)",
    )
    p_phase.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="Run identifier (auto-generated if omitted)",
    )
    p_phase.add_argument(
        "--input",
        help="Path to input spec folder",
    )

    # extract - alias for phase 0
    p_extract = subparsers.add_parser(
        "extract",
        help="Phase 0: extract input to PDD format",
    )
    p_extract.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to input spec (default: current directory)",
    )
    p_extract.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="Run identifier (auto-generated if omitted)",
    )

    # ── Legacy / module commands ────────────────────────────────────

    # phase-02
    p_phase_02 = subparsers.add_parser(
        "phase-02",
        help="Run Phase 2 clean/compose/compliance workflow",
    )
    p_phase_02.add_argument("run_id", help="Run identifier")

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

    # Auto-generate run_id for PDD commands when not provided
    if args.command in ("run", "phase", "extract"):
        if getattr(args, "run_id", None) is None:
            from datetime import datetime

            args.run_id = datetime.now().strftime("pdd-%Y%m%d-%H%M%S")

    commands = {
        "run": cmd_run,
        "phase": cmd_phase,
        "extract": cmd_extract,
        "phase-02": cmd_phase_02,
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

"""CLI commands for evaluation framework.

Commands:
    eval run                        Run evaluation on specs
    eval resume                     Resume an interrupted evaluation
    eval report                     Generate report from a completed run
    eval list                       List available spec fixtures
    eval orchestration <cmd>        Orchestration-level QA (PromotionLoop / PddLifecycle)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spec_manager.core.project_root import resolve_from_root
from spec_manager.refinement.evals.inputs.sequence_spec import (
    load_sequence_specs_from_dir,
)
from spec_manager.refinement.evals.report import (
    generate_markdown_report,
    load_report,
)
from spec_manager.refinement.evals.runner import EvalConfig, EvalRunner


def _default_fixtures_dir() -> Path:
    return resolve_from_root(
        "scripts", "spec_manager", "spec_manager", "refinement", "evals", "inputs", "fixtures"
    )


def _default_output_dir() -> Path:
    return resolve_from_root("runs", "evals", "reports")


def _default_checkpoint_dir() -> Path:
    return resolve_from_root("runs", "evals", "checkpoints")


def cmd_eval_run(args: argparse.Namespace) -> int:
    """Run evaluation on specs.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    # Build config from args
    # Default to PDD; --refinement flag switches to legacy refinement pipeline
    use_pdd = not getattr(args, "refinement", False)

    config = EvalConfig(
        spec_ids=args.spec_ids if args.spec_ids else None,
        checkpoint_dir=Path(args.checkpoint_dir)
        if args.checkpoint_dir
        else _default_checkpoint_dir(),
        output_dir=Path(args.output_dir) if args.output_dir else _default_output_dir(),
        max_iterations_per_phase=args.max_iterations,
        stagnation_threshold=args.stagnation_threshold,
        convergence_threshold=args.convergence_threshold,
        fuzzy_match_threshold=args.fuzzy_threshold,
        parallel=args.parallel,
        use_real_workflows=getattr(args, "use_real_workflows", False),
        sparse=getattr(args, "sparse", False),
        resolve_ambiguities=getattr(args, "resolve_ambiguities", False),
        use_judge=getattr(args, "judge", False),
        use_pdd=use_pdd,
    )

    fixtures_dir = Path(args.fixtures_dir) if args.fixtures_dir else _default_fixtures_dir()

    # Build signal resolver if --mode specified
    signal_resolver = None
    eval_mode = getattr(args, "mode", None)
    if eval_mode is not None:
        from spec_manager.refinement.interactive.signal_resolver import create_resolver

        signal_resolver = create_resolver(mode=eval_mode)

    pipeline_label = "PDD orchestrator" if config.use_pdd else "refinement pipeline (legacy)"
    print("Running evaluation with config:")
    print(f"  Pipeline: {pipeline_label}")
    print(f"  Fixtures: {fixtures_dir}")
    print(f"  Output: {config.output_dir}")
    print(f"  Checkpoint: {config.checkpoint_dir}")

    if config.spec_ids:
        print(f"  Specs: {', '.join(config.spec_ids)}")
    else:
        print("  Specs: all available")

    if eval_mode:
        print(f"  Mode: {eval_mode}")
    if config.resolve_ambiguities:
        print("  Resolve ambiguities: enabled")
    if config.use_judge:
        print("  Scoring: LLM judge (semantic)")

    # Create and run
    runner = EvalRunner(config, fixtures_dir=fixtures_dir, signal_resolver=signal_resolver)
    report = runner.run()

    # Display summary
    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)
    print(f"Run ID: {report.run_id}")
    print(f"Specs evaluated: {report.specs_evaluated}")
    print(f"Passed: {report.specs_passed}")
    print(f"Failed: {report.specs_failed}")

    if report.aggregate_metrics:
        recall = report.aggregate_metrics.get("overall_recall", 0)
        precision = report.aggregate_metrics.get("overall_precision", 0)
        print("\nAggregate metrics:")
        print(f"  Recall: {recall:.1%}")
        print(f"  Precision: {precision:.1%}")

    if report.common_bottlenecks:
        print("\nCommon bottlenecks:")
        for bn in report.common_bottlenecks[:3]:
            print(f"  - {bn}")

    if report.recommendations:
        print("\nRecommendations:")
        for rec in report.recommendations[:3]:
            print(f"  - {rec}")

    # Show report paths
    json_path = config.output_dir / f"eval_report_{report.run_id}.json"
    md_path = config.output_dir / f"eval_report_{report.run_id}.md"
    print("\nReports saved:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")

    return 0 if report.specs_failed == 0 else 1


def cmd_eval_resume(args: argparse.Namespace) -> int:
    """Resume an interrupted evaluation.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    run_id = args.run_id
    checkpoint_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else _default_checkpoint_dir()
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()
    fixtures_dir = Path(args.fixtures_dir) if args.fixtures_dir else _default_fixtures_dir()

    print(f"Resuming evaluation: {run_id}")

    config = EvalConfig(
        checkpoint_dir=checkpoint_dir,
        output_dir=output_dir,
    )

    runner = EvalRunner(config, fixtures_dir=fixtures_dir)
    report = runner.resume(run_id)

    if report is None:
        print(f"Could not find checkpoint for run: {run_id}")
        print(f"Searched in: {checkpoint_dir}")
        return 1

    # Display summary
    print("\n" + "=" * 60)
    print("RESUMED EVALUATION COMPLETE")
    print("=" * 60)
    print(f"Run ID: {report.run_id}")
    print(f"Specs evaluated: {report.specs_evaluated}")
    print(f"Passed: {report.specs_passed}")
    print(f"Failed: {report.specs_failed}")

    return 0 if report.specs_failed == 0 else 1


def cmd_eval_report(args: argparse.Namespace) -> int:
    """Generate or display report from a completed run.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    run_id = args.run_id
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()
    output_format = args.format

    # Find report file
    json_path = output_dir / f"eval_report_{run_id}.json"

    if not json_path.exists():
        # Try without prefix
        json_path = output_dir / f"{run_id}.json"

    if not json_path.exists():
        print(f"Report not found: {json_path}")
        print(f"Available reports in {output_dir}:")
        if output_dir.exists():
            for f in output_dir.glob("*.json"):
                print(f"  - {f.stem}")
        return 1

    try:
        report = load_report(json_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading report: {e}")
        return 1

    if output_format == "json":
        import json

        print(json.dumps(report.to_dict(), indent=2))
    elif output_format == "markdown":
        print(generate_markdown_report(report))
    else:
        # Summary format
        print(f"Run ID: {report.run_id}")
        print(f"Generated: {report.generated_at}")
        print(
            f"Specs: {report.specs_evaluated} "
            f"({report.specs_passed} passed, {report.specs_failed} failed)"
        )

        if report.aggregate_metrics:
            recall = report.aggregate_metrics.get("overall_recall", 0)
            precision = report.aggregate_metrics.get("overall_precision", 0)
            print(f"Recall: {recall:.1%}, Precision: {precision:.1%}")

        if report.common_bottlenecks:
            print(f"Bottlenecks: {', '.join(report.common_bottlenecks[:3])}")

    return 0


def cmd_eval_list(args: argparse.Namespace) -> int:
    """List available spec fixtures.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    fixtures_dir = Path(args.fixtures_dir) if args.fixtures_dir else _default_fixtures_dir()

    if not fixtures_dir.exists():
        print(f"Fixtures directory not found: {fixtures_dir}")
        return 1

    specs = load_sequence_specs_from_dir(fixtures_dir)

    if not specs:
        print("No spec fixtures found.")
        return 0

    print(f"Available spec fixtures ({len(specs)}):\n")

    for spec in sorted(specs, key=lambda s: s.complexity_score):
        print(f"  {spec.spec_id}")
        print(f"    Title: {spec.title}")
        print(f"    Complexity: {spec.complexity_score}/10")
        print(f"    Rules: {len(spec.rules)}")
        tags = ", ".join(spec.tags) if spec.tags else "none"
        print(f"    Tags: {tags}")
        print()

    return 0


def setup_eval_parser(subparsers: argparse._SubParsersAction) -> None:
    """Set up eval subcommand parser.

    Args:
        subparsers: Subparsers to add eval commands to.
    """
    # eval command group
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run spec refinement evaluation",
        description="Evaluate spec refinement system against test fixtures",
    )

    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)

    # eval run
    p_run = eval_subparsers.add_parser("run", help="Run evaluation on specs")
    p_run.add_argument(
        "--spec-ids",
        nargs="+",
        help="Specific spec IDs to evaluate (default: all)",
    )
    p_run.add_argument(
        "--fixtures-dir",
        help="Directory containing spec fixtures (default: <project>/.../fixtures)",
    )
    p_run.add_argument(
        "--output-dir",
        help="Directory for reports (default: <project>/runs/evals/reports)",
    )
    p_run.add_argument(
        "--checkpoint-dir",
        help="Directory for checkpoints (default: <project>/runs/evals/checkpoints)",
    )
    p_run.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Max iterations per phase (default: 10)",
    )
    p_run.add_argument(
        "--stagnation-threshold",
        type=int,
        default=3,
        help="Stagnation detection threshold (default: 3)",
    )
    p_run.add_argument(
        "--convergence-threshold",
        type=float,
        default=0.95,
        help="Convergence ratio threshold (default: 0.95)",
    )
    p_run.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.6,
        help="Fuzzy match threshold (default: 0.6)",
    )
    p_run.add_argument(
        "--parallel",
        action="store_true",
        help="Run specs in parallel",
    )
    p_run.add_argument(
        "--use-real-workflows",
        action="store_true",
        help="Use real workflow extraction instead of simulation",
    )
    p_run.add_argument(
        "--sparse",
        action="store_true",
        help="Run sparse-to-dense steering evaluation mode",
    )
    p_run.add_argument(
        "--mode",
        choices=["auto", "interactive", "steering-only"],
        default=None,
        help="Signal resolution mode for sparse-to-dense evals",
    )
    p_run.add_argument(
        "--resolve-ambiguities",
        action="store_true",
        help="Enable post-phase ambiguity resolution during evaluation",
    )
    p_run.add_argument(
        "--judge",
        action="store_true",
        help="Use LLM judge for semantic scoring instead of fuzzy matching",
    )
    p_run.add_argument(
        "--refinement",
        action="store_true",
        help="Use legacy refinement pipeline instead of PDD orchestrator (default: PDD)",
    )

    # eval resume
    p_resume = eval_subparsers.add_parser("resume", help="Resume interrupted evaluation")
    p_resume.add_argument("run_id", help="Run ID to resume")
    p_resume.add_argument(
        "--fixtures-dir",
        help="Directory containing spec fixtures (default: <project>/.../fixtures)",
    )
    p_resume.add_argument(
        "--output-dir",
        help="Directory for reports (default: <project>/runs/evals/reports)",
    )
    p_resume.add_argument(
        "--checkpoint-dir",
        help="Directory for checkpoints (default: <project>/runs/evals/checkpoints)",
    )

    # eval report
    p_report = eval_subparsers.add_parser("report", help="Generate or display report")
    p_report.add_argument("run_id", help="Run ID to generate report for")
    p_report.add_argument(
        "--format",
        choices=["summary", "json", "markdown"],
        default="summary",
        help="Output format (default: summary)",
    )
    p_report.add_argument(
        "--output-dir",
        help="Directory containing reports (default: <project>/runs/evals/reports)",
    )

    # eval list
    p_list = eval_subparsers.add_parser("list", help="List available spec fixtures")
    p_list.add_argument(
        "--fixtures-dir",
        help="Directory containing spec fixtures (default: <project>/.../fixtures)",
    )

    # --- Planner commands ---

    p_planner = eval_subparsers.add_parser(
        "planner",
        help="Planner eval harness and trace analysis",
        description=(
            "Primary harness entry point: eval planner --fixture <name> --gt <path> --mode <mode>. "
            "Trace utility subcommands remain available."
        ),
    )
    p_planner.add_argument(
        "--fixture",
        default="",
        help="Fixture name (without _pdd suffix), e.g. chaotic_treasury_expanded",
    )
    p_planner.add_argument(
        "--fixture-root",
        default="",
        help="Fixture root directory (defaults to repository eval fixtures dir)",
    )
    p_planner.add_argument("--gt", default="", help="Path to planner ground truth YAML")
    p_planner.add_argument(
        "--mode",
        choices=["e2e", "slice", "replay", "counterfactual", "shadow"],
        default="e2e",
        help="Harness mode (default: e2e)",
    )
    p_planner.add_argument("--run-id", default="", help="Run ID override")
    p_planner.add_argument("--workspace", default=".", help="Workspace root for traces/replay")
    p_planner.add_argument("--slice-id", default="", help="Slice ID for mode=slice")
    p_planner.add_argument("--layer", default="", help="Layer for mode=slice (l1|l2|l3)")
    p_planner.add_argument(
        "--trace-id", default="", help="Trace ID for mode=replay or mode=counterfactual"
    )
    p_planner.add_argument(
        "--override",
        default="",
        help="Override YAML/JSON for mode=replay or mode=counterfactual",
    )
    p_planner.add_argument("--model-config", default="", help="Candidate model ID override")
    p_planner.add_argument(
        "--shadow-model",
        default="",
        help="Oracle model ID for mode=shadow",
    )

    planner_sub = p_planner.add_subparsers(dest="planner_command", required=False)

    # eval planner score
    p_pl_score = planner_sub.add_parser("score", help="Score planner traces against ground truth")
    p_pl_score.add_argument("--run-id", default="", help="Run ID to score (empty = all traces)")
    p_pl_score.add_argument("--gt", required=True, help="Path to planner ground truth YAML")
    p_pl_score.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # eval planner trace list
    p_pl_list = planner_sub.add_parser("list", help="List planner traces")
    p_pl_list.add_argument("--run-id", default="", help="Filter by run ID")
    p_pl_list.add_argument("--slice", default="", help="Filter by slice ID")
    p_pl_list.add_argument("--capability", default="", help="Filter by capability")
    p_pl_list.add_argument("--layer", default="", help="Filter by layer")
    p_pl_list.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # eval planner trace show
    p_pl_show = planner_sub.add_parser("show", help="Show a specific trace")
    p_pl_show.add_argument("trace_id", help="Trace ID to show")
    p_pl_show.add_argument("--calls", action="store_true", help="Include model/tool calls")
    p_pl_show.add_argument("--artifacts", action="store_true", help="Include artifacts")
    p_pl_show.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # eval planner trace replay
    p_pl_replay = planner_sub.add_parser("replay", help="Replay a planner decision")
    p_pl_replay.add_argument("trace_id", help="Trace ID to replay")
    p_pl_replay.add_argument(
        "--model-config",
        default="",
        help="Model configuration override for replayed planner call",
    )
    p_pl_replay.add_argument(
        "--override",
        help="Path to override YAML/JSON (mapping with optional inputs/outputs keys)",
    )
    p_pl_replay.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # eval planner trace diff
    p_pl_diff = planner_sub.add_parser("diff", help="Diff two traces")
    p_pl_diff.add_argument("trace_a", help="First trace ID")
    p_pl_diff.add_argument("trace_b", help="Second trace ID")
    p_pl_diff.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # eval planner trace summarize-run
    p_pl_summary = planner_sub.add_parser("summarize-run", help="Summarize traces for a run")
    p_pl_summary.add_argument("--run-id", required=True, help="Run ID to summarize")
    p_pl_summary.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # eval planner trace timeline
    p_pl_timeline = planner_sub.add_parser("timeline", help="Generate planner timeline HTML")
    p_pl_timeline.add_argument("--run-id", required=True, help="Run ID to visualize")
    p_pl_timeline.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # eval planner export-gt
    p_pl_export = planner_sub.add_parser("export-gt", help="Export GT template from traces")
    p_pl_export.add_argument("--run-id", required=True, help="Run ID to export from")
    p_pl_export.add_argument("--out", required=True, help="Output YAML path")
    p_pl_export.add_argument("--spec-id", default="chaotic_treasury_expanded", help="Spec ID")
    p_pl_export.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # --- Orchestration commands ---

    # eval orchestration (sub-subcommand group)
    p_orch = eval_subparsers.add_parser(
        "orchestration",
        help="Orchestration-level evaluation",
        description="Step-by-step QA for PromotionLoop and PddLifecycle",
    )
    orch_sub = p_orch.add_subparsers(dest="orchestration_command", required=True)

    # eval orchestration setup
    p_orch_setup = orch_sub.add_parser("setup", help="Set up eval workspace")
    p_orch_setup.add_argument("--run-id", default="orchestration-qa", help="Run ID")

    # eval orchestration slices
    p_orch_slices = orch_sub.add_parser("slices", help="List available slices")
    p_orch_slices.add_argument("--layer", required=True, choices=["l1", "l2", "l3"])
    p_orch_slices.add_argument("--run-id", default="orchestration-qa")

    # eval orchestration loop
    p_orch_loop = orch_sub.add_parser("loop", help="Run PromotionLoop on a single slice")
    p_orch_loop.add_argument("--layer", required=True, choices=["l1", "l2", "l3"])
    p_orch_loop.add_argument("--slice", required=True, help="Slice ID")
    p_orch_loop.add_argument("--run-id", default="orchestration-qa")

    # eval orchestration layer
    p_orch_layer = orch_sub.add_parser("layer", help="Run full layer via PddLifecycle")
    p_orch_layer.add_argument("--layer", required=True, choices=["l1", "l2", "l3"])
    p_orch_layer.add_argument("--run-id", default="orchestration-qa")

    # eval orchestration transition
    p_orch_transition = orch_sub.add_parser("transition", help="Run layer transition")
    p_orch_transition.add_argument(
        "--from-layer", required=True, choices=["l1", "l2"], dest="from_layer"
    )
    p_orch_transition.add_argument(
        "--to-layer", required=True, choices=["l2", "l3"], dest="to_layer"
    )
    p_orch_transition.add_argument("--run-id", default="orchestration-qa")

    # eval orchestration scoring
    p_orch_scoring = orch_sub.add_parser("scoring", help="Run scoring on results")
    p_orch_scoring.add_argument("--run-id", default="orchestration-qa")

    # eval orchestration report
    p_orch_report = orch_sub.add_parser("report", help="Generate final report")
    p_orch_report.add_argument("--results-file", required=True, help="Path to results JSON file")
    p_orch_report.add_argument("--run-id", default="orchestration-qa")

    # eval orchestration full
    p_orch_full = orch_sub.add_parser("full", help="Run full PddLifecycle.run() pipeline")
    p_orch_full.add_argument("--run-id", default="orchestration-qa")

    # eval quality - quality scoring subcommand
    p_quality = eval_subparsers.add_parser(
        "quality",
        help="Compute quality scorecard for a run",
    )
    p_quality.add_argument("run_id", help="Run identifier")
    p_quality.add_argument(
        "--judges",
        action="store_true",
        help="Run LLM judges",
    )
    p_quality.add_argument(
        "--judge-model",
        default="",
        help="Model ID for quality judges",
    )
    p_quality.add_argument(
        "--allow-self-judge",
        action="store_true",
        help="Allow judge model to equal producer model",
    )

    # eval multi-model - multi-model comparison subcommand
    p_eval_multi_model = eval_subparsers.add_parser(
        "multi-model",
        help="Run multi-model comparison",
    )
    p_eval_multi_model.add_argument(
        "--spec",
        required=True,
        help="Path to input spec folder",
    )
    p_eval_multi_model.add_argument(
        "--models",
        required=True,
        help="Comma-separated model profiles (format: name[:model_id])",
    )
    p_eval_multi_model.add_argument(
        "--runs-per-model",
        type=int,
        default=1,
        help="Number of replicates to run per model profile",
    )
    p_eval_multi_model.add_argument(
        "--comparison-id",
        help="Comparison identifier",
    )
    p_eval_multi_model.add_argument(
        "--judge-model",
        default="",
        help="Model ID for judges",
    )
    p_eval_multi_model.add_argument(
        "--quality",
        action="store_true",
        help="Compute quality scorecards for each run",
    )


# --- Planner command handlers ---


def cmd_planner_run(args: argparse.Namespace) -> int:
    """Run planner eval harness via mode-based entry point."""
    import json

    from spec_manager.refinement.evals.planner.harness import EvalConfig, PlannerEvalHarness

    workspace = Path(args.workspace)
    gt_path = Path(args.gt) if args.gt else None
    fixture_root = Path(args.fixture_root) if args.fixture_root else None
    override_path = Path(args.override) if args.override else None

    config = EvalConfig(
        workspace_root=workspace,
        gt_path=gt_path,
        run_id=args.run_id,
        mode=args.mode,
        fixture=args.fixture,
        fixture_root=fixture_root,
        model_config=args.model_config,
        shadow_model_config=args.shadow_model,
        slice_id=args.slice_id,
        layer=args.layer,
        replay_trace_id=args.trace_id,
        override_path=override_path,
    )
    harness = PlannerEvalHarness(workspace, gt_path=gt_path)
    result = harness.run_and_score(config)

    print(f"Mode: {args.mode}")
    if result.run_id:
        print(f"Run ID: {result.run_id}")
    print(f"Traces evaluated: {result.traces_evaluated}")

    if args.mode == "replay":
        if result.verdicts:
            verdict = result.verdicts[0]
            print(f"Replay: {'SAME' if verdict.passed else 'DIFFERENT'}")
            print(f"Replay detail: {verdict.detail}")
        if result.diagnostics:
            print("\nDiagnostics:")
            print(json.dumps(result.diagnostics, indent=2, default=str))
        if result.errors:
            print("\nErrors:")
            for err in result.errors:
                print(f"  - {err}")
        mode_ok = bool(result.verdicts and result.verdicts[0].passed)
        return 0 if mode_ok and not result.errors else 1

    if args.mode == "counterfactual":
        if result.scorecard:
            print(f"Overall: {'PASS' if result.scorecard.overall_pass else 'FAIL'}")
            hard_pass = sum(1 for g in result.scorecard.hard_gates if g.status == "PASS")
            print(f"Hard gates: {hard_pass}/{len(result.scorecard.hard_gates)}")
        if result.diagnostics:
            print("\nDiagnostics:")
            print(json.dumps(result.diagnostics, indent=2, default=str))
        if result.errors:
            print("\nErrors:")
            for err in result.errors:
                print(f"  - {err}")
        mode_ok = bool(result.scorecard and result.scorecard.overall_pass and not result.errors)
        return 0 if mode_ok else 1

    if result.scorecard:
        scorecard = result.scorecard
        print(f"Overall: {'PASS' if scorecard.overall_pass else 'FAIL'}")
        hard_pass = sum(1 for g in scorecard.hard_gates if g.status == "PASS")
        print(f"Hard gates: {hard_pass}/{len(scorecard.hard_gates)}")
        soft_pass = sum(1 for s in scorecard.soft_signals if s.status == "PASS")
        print(f"Soft signals: {soft_pass}/{len(scorecard.soft_signals)}")

    if result.errors:
        print("\nErrors:")
        for err in result.errors:
            print(f"  - {err}")
    if result.diagnostics:
        print("\nDiagnostics:")
        print(json.dumps(result.diagnostics, indent=2, default=str))
    if result.diagnostic_scorecard:
        print("\nIdeal-upstream diagnostic:")
        print(f"Run ID: {result.diagnostic_run_id}")
        print(f"Overall: {'PASS' if result.diagnostic_scorecard.overall_pass else 'FAIL'}")

    if result.scorecard is None:
        return 1 if result.errors else 0
    return 0 if (result.scorecard.overall_pass and not result.errors) else 1


def cmd_planner_score(args: argparse.Namespace) -> int:
    """Score planner traces against ground truth."""
    from spec_manager.refinement.evals.planner.harness import PlannerEvalHarness

    workspace = Path(args.workspace)
    gt_path = Path(args.gt)
    harness = PlannerEvalHarness(workspace, gt_path=gt_path)
    result = harness.score_existing_traces(args.run_id)

    print(f"Traces evaluated: {result.traces_evaluated}")
    print(f"GT cases matched: {result.gt_cases_matched}")
    print(f"GT cases unmatched: {result.gt_cases_unmatched}")

    if result.scorecard:
        sc = result.scorecard
        print(f"\nOverall: {'PASS' if sc.overall_pass else 'FAIL'}")
        hard_gates_pass = sum(1 for g in sc.hard_gates if g.status == "PASS")
        print(f"Hard gates: {hard_gates_pass}/{len(sc.hard_gates)}")
        for g in sc.hard_gates:
            print(f"  {g.name}: {g.status} (raw={g.raw:.2f})")
        soft_signals_pass = sum(1 for s in sc.soft_signals if s.status == "PASS")
        print(f"Soft signals: {soft_signals_pass}/{len(sc.soft_signals)}")
        for s in sc.soft_signals:
            print(f"  {s.name}: {s.status} (raw={s.raw:.2f})")

    if result.errors:
        print(f"\nErrors: {len(result.errors)}")
        for e in result.errors:
            print(f"  - {e}")

    return 0 if (result.scorecard and result.scorecard.overall_pass) else 1


def cmd_planner_list(args: argparse.Namespace) -> int:
    """List planner traces."""
    from spec_manager.refinement.evals.planner.trace_loader import filter_traces, load_index

    workspace = Path(args.workspace)
    entries = load_index(workspace)

    kwargs = {}
    if args.run_id:
        kwargs["run_id"] = args.run_id
    if args.slice:
        kwargs["slice_id"] = args.slice
    if args.capability:
        kwargs["capability"] = args.capability
    if args.layer:
        kwargs["layer"] = args.layer

    filtered = filter_traces(entries, **kwargs) if kwargs else entries

    print(f"Traces: {len(filtered)}")
    print(f"{'TRACE_ID':<14} {'LAYER':<5} {'CAPABILITY':<22} {'SLICE':<12} {'STATUS':<8}")
    print("-" * 65)
    for e in filtered:
        print(f"{e.trace_id:<14} {e.layer:<5} {e.capability:<22} {e.slice_id:<12} {e.status:<8}")

    return 0


def cmd_planner_show(args: argparse.Namespace) -> int:
    """Show a specific planner trace."""
    import json

    from spec_manager.refinement.evals.planner.trace_loader import load_trace

    workspace = Path(args.workspace)
    trace = load_trace(workspace, args.trace_id)

    print(f"Trace: {trace.trace_id}")
    print(f"Decision Key: {trace.decision_key}")
    print(f"Status: {trace.status}")
    print(f"Overridden: {trace.overridden}")
    print(f"\nRequest: {json.dumps(trace.request, indent=2)}")
    print(f"\nDecision: {json.dumps(trace.decision, indent=2)}")

    if args.calls:
        print(f"\nModel calls ({len(trace.model_calls)}):")
        for mc in trace.model_calls:
            print(f"  {json.dumps(mc)}")
        print(f"\nTool calls ({len(trace.tool_calls)}):")
        for tc in trace.tool_calls:
            print(f"  {json.dumps(tc)}")

    if args.artifacts:
        print(f"\nArtifacts ({len(trace.artifacts)}):")
        for name, data in trace.artifacts.items():
            print(f"  {name}: {json.dumps(data, indent=2)[:500]}")

    return 0


def cmd_planner_replay(args: argparse.Namespace) -> int:
    """Replay a planner decision."""
    from spec_manager.refinement.evals.planner.harness import EvalConfig, PlannerEvalHarness

    workspace = Path(args.workspace)
    config = EvalConfig(
        workspace_root=workspace,
        mode="replay",
        replay_trace_id=args.trace_id,
        model_config=args.model_config,
        override_path=Path(args.override) if args.override else None,
    )
    harness = PlannerEvalHarness(workspace)
    result = harness.run_and_score(config)

    if result.verdicts:
        v = result.verdicts[0]
        print(f"Replay result: {'SAME' if v.passed else 'DIFFERENT'}")
        print(f"Detail: {v.detail}")
    if result.errors:
        for e in result.errors:
            print(f"Error: {e}")

    return 0


def _planner_trace_parts(trace: object) -> tuple[str, str, str, int]:
    decision_key = str(getattr(trace, "decision_key", "") or "")
    parts = decision_key.split(":") if decision_key else []
    layer = parts[0] if len(parts) > 0 else "unknown"
    capability = parts[1] if len(parts) > 1 else "unknown"
    slice_id = parts[2] if len(parts) > 2 else "unknown"
    iteration = 0
    if len(parts) > 3:
        try:
            iteration = int(parts[3])
        except (TypeError, ValueError):
            iteration = 0
    return layer, capability, slice_id, iteration


def _planner_trace_outputs(trace: object) -> dict[str, object]:
    artifacts = getattr(trace, "artifacts", {}) or {}
    outputs = artifacts.get("outputs")
    if isinstance(outputs, dict):
        return outputs
    override_outputs = artifacts.get("override_outputs")
    if isinstance(override_outputs, dict):
        return override_outputs
    return {}


def _planner_trace_decision_field(trace: object, field: str) -> object:
    decision = getattr(trace, "decision", {}) or {}
    if not isinstance(decision, dict):
        return None
    return decision.get(field)


def _planner_trace_tokens_latency(trace: object) -> tuple[int, float]:
    def _safe_int(value: object) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _safe_float(value: object) -> float:
        try:
            return max(float(value or 0.0), 0.0)
        except (TypeError, ValueError):
            return 0.0

    model_calls = getattr(trace, "model_calls", []) or []
    tool_calls = getattr(trace, "tool_calls", []) or []

    tokens_total = 0
    model_latency_ms = 0.0
    tool_latency_ms = 0.0

    for call in model_calls:
        if not isinstance(call, dict):
            continue
        tokens_total += _safe_int(call.get("tokens_in")) + _safe_int(call.get("tokens_out"))
        model_latency_ms += _safe_float(call.get("duration_ms"))

    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tokens_total += _safe_int(call.get("tokens_in")) + _safe_int(call.get("tokens_out"))
        tool_latency_ms += _safe_float(call.get("duration_ms"))

    latency_ms = model_latency_ms if model_calls else tool_latency_ms
    if latency_ms <= 0.0 and tool_latency_ms > 0.0:
        latency_ms = tool_latency_ms
    return tokens_total, latency_ms


def _planner_call_sequence(
    calls: list[dict[str, object]],
    *,
    fields: tuple[str, ...],
) -> list[dict[str, object]]:
    sequence: list[dict[str, object]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        sequence.append({field: call.get(field) for field in fields})
    return sequence


def _first_sequence_mismatch(
    left: list[dict[str, object]],
    right: list[dict[str, object]],
) -> int:
    max_len = max(len(left), len(right))
    for idx in range(max_len):
        if idx >= len(left) or idx >= len(right):
            return idx
        if left[idx] != right[idx]:
            return idx
    return -1


def _planner_diff_payload(trace_a: object, trace_b: object) -> dict[str, object]:
    import json

    outputs_a = _planner_trace_outputs(trace_a)
    outputs_b = _planner_trace_outputs(trace_b)
    output_keys = sorted(set(outputs_a) | set(outputs_b))

    output_changes = []
    changed_keys: list[str] = []
    for key in output_keys:
        left = outputs_a.get(key)
        right = outputs_b.get(key)
        changed = json.dumps(left, sort_keys=True, default=str) != json.dumps(
            right, sort_keys=True, default=str
        )
        if changed:
            changed_keys.append(key)
        output_changes.append(
            {
                "key": key,
                "changed": changed,
                "a": left,
                "b": right,
            }
        )

    assumptions_a = _planner_trace_decision_field(trace_a, "assumptions")
    assumptions_b = _planner_trace_decision_field(trace_b, "assumptions")
    assumptions_list_a = assumptions_a if isinstance(assumptions_a, list) else []
    assumptions_list_b = assumptions_b if isinstance(assumptions_b, list) else []
    assumptions_set_a = {str(item) for item in assumptions_list_a}
    assumptions_set_b = {str(item) for item in assumptions_list_b}

    confidence_a = _planner_trace_decision_field(trace_a, "confidence")
    confidence_b = _planner_trace_decision_field(trace_b, "confidence")
    confidence_a_num = float(confidence_a) if isinstance(confidence_a, (int, float)) else None
    confidence_b_num = float(confidence_b) if isinstance(confidence_b, (int, float)) else None
    confidence_delta = None
    if confidence_a_num is not None and confidence_b_num is not None:
        confidence_delta = confidence_b_num - confidence_a_num

    model_sequence_a = _planner_call_sequence(
        getattr(trace_a, "model_calls", []) or [],
        fields=(
            "agent_name",
            "model",
            "prompt_hash",
            "output_hash",
            "duration_ms",
            "tokens_in",
            "tokens_out",
        ),
    )
    model_sequence_b = _planner_call_sequence(
        getattr(trace_b, "model_calls", []) or [],
        fields=(
            "agent_name",
            "model",
            "prompt_hash",
            "output_hash",
            "duration_ms",
            "tokens_in",
            "tokens_out",
        ),
    )
    tool_sequence_a = _planner_call_sequence(
        getattr(trace_a, "tool_calls", []) or [],
        fields=("tool_name", "inputs_hash", "output_summary", "duration_ms"),
    )
    tool_sequence_b = _planner_call_sequence(
        getattr(trace_b, "tool_calls", []) or [],
        fields=("tool_name", "inputs_hash", "output_summary", "duration_ms"),
    )

    model_mismatch = _first_sequence_mismatch(model_sequence_a, model_sequence_b)
    tool_mismatch = _first_sequence_mismatch(tool_sequence_a, tool_sequence_b)

    return {
        "trace_a": {
            "trace_id": getattr(trace_a, "trace_id", ""),
            "decision_key": getattr(trace_a, "decision_key", ""),
            "status": getattr(trace_a, "status", ""),
        },
        "trace_b": {
            "trace_id": getattr(trace_b, "trace_id", ""),
            "decision_key": getattr(trace_b, "decision_key", ""),
            "status": getattr(trace_b, "status", ""),
        },
        "status": {
            "match": str(getattr(trace_a, "status", "")) == str(getattr(trace_b, "status", "")),
            "a": getattr(trace_a, "status", ""),
            "b": getattr(trace_b, "status", ""),
        },
        "decision_outputs": {
            "changed_keys": changed_keys,
            "change_count": len(changed_keys),
            "entries": output_changes,
        },
        "confidence": {
            "a": confidence_a_num,
            "b": confidence_b_num,
            "delta": confidence_delta,
            "match": confidence_a_num == confidence_b_num,
        },
        "assumptions": {
            "a": assumptions_list_a,
            "b": assumptions_list_b,
            "only_in_a": sorted(assumptions_set_a - assumptions_set_b),
            "only_in_b": sorted(assumptions_set_b - assumptions_set_a),
            "match": assumptions_list_a == assumptions_list_b,
        },
        "model_call_sequence": {
            "match": model_mismatch < 0,
            "first_mismatch_index": model_mismatch,
            "count_a": len(model_sequence_a),
            "count_b": len(model_sequence_b),
            "a": model_sequence_a,
            "b": model_sequence_b,
        },
        "tool_call_sequence": {
            "match": tool_mismatch < 0,
            "first_mismatch_index": tool_mismatch,
            "count_a": len(tool_sequence_a),
            "count_b": len(tool_sequence_b),
            "a": tool_sequence_a,
            "b": tool_sequence_b,
        },
    }


def _planner_diff_markdown(payload: dict[str, object]) -> str:
    trace_a = payload.get("trace_a", {})
    trace_b = payload.get("trace_b", {})
    status = payload.get("status", {})
    outputs = payload.get("decision_outputs", {})
    confidence = payload.get("confidence", {})
    assumptions = payload.get("assumptions", {})
    model_sequence = payload.get("model_call_sequence", {})
    tool_sequence = payload.get("tool_call_sequence", {})

    changed_keys = outputs.get("changed_keys", [])
    if not isinstance(changed_keys, list):
        changed_keys = []

    lines = [
        "# Planner Trace Diff",
        "",
        f"- Trace A: `{trace_a.get('trace_id', '')}`",
        f"- Trace B: `{trace_b.get('trace_id', '')}`",
        "",
        "## Decision Outputs",
        "",
        f"- Changed keys: {len(changed_keys)}",
        f"- Keys: {', '.join(str(key) for key in changed_keys) if changed_keys else '(none)'}",
        "",
        "## Status",
        "",
        f"- Match: {status.get('match', False)}",
        f"- A: `{status.get('a', '')}`",
        f"- B: `{status.get('b', '')}`",
        "",
        "## Confidence",
        "",
        f"- Match: {confidence.get('match', False)}",
        f"- A: {confidence.get('a', None)}",
        f"- B: {confidence.get('b', None)}",
        f"- Delta (B-A): {confidence.get('delta', None)}",
        "",
        "## Assumptions",
        "",
        f"- Match: {assumptions.get('match', False)}",
        f"- Only in A: {', '.join(assumptions.get('only_in_a', [])) or '(none)'}",
        f"- Only in B: {', '.join(assumptions.get('only_in_b', [])) or '(none)'}",
        "",
        "## Model Call Sequence",
        "",
        f"- Match: {model_sequence.get('match', False)}",
        f"- Count A: {model_sequence.get('count_a', 0)}",
        f"- Count B: {model_sequence.get('count_b', 0)}",
        f"- First mismatch index: {model_sequence.get('first_mismatch_index', -1)}",
        "",
        "## Tool Call Sequence",
        "",
        f"- Match: {tool_sequence.get('match', False)}",
        f"- Count A: {tool_sequence.get('count_a', 0)}",
        f"- Count B: {tool_sequence.get('count_b', 0)}",
        f"- First mismatch index: {tool_sequence.get('first_mismatch_index', -1)}",
        "",
    ]
    return "\n".join(lines)


def cmd_planner_diff(args: argparse.Namespace) -> int:
    """Diff two planner traces."""
    import json

    from spec_manager.refinement.evals.planner.trace_loader import load_trace

    workspace = Path(args.workspace)
    trace_a = load_trace(workspace, args.trace_a)
    trace_b = load_trace(workspace, args.trace_b)

    payload = _planner_diff_payload(trace_a, trace_b)
    run_a = str((trace_a.request or {}).get("run_id", "") or "")
    run_b = str((trace_b.request or {}).get("run_id", "") or "")
    run_id = run_a if run_a and run_a == run_b else (run_a or run_b or "cross-run")
    out_dir = (
        workspace / "reports" / "pdd" / run_id / "planner_diffs" / f"{args.trace_a}__{args.trace_b}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "diff.json"
    md_path = out_dir / "diff.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_planner_diff_markdown(payload), encoding="utf-8")

    changed = ((payload.get("decision_outputs") or {}).get("change_count")) or 0
    status_match = ((payload.get("status") or {}).get("match")) or False
    print(f"Trace A: {trace_a.trace_id}")
    print(f"Trace B: {trace_b.trace_id}")
    print(f"Status match: {status_match}")
    print(f"Decision output changed keys: {changed}")
    print(f"Diff markdown: {md_path}")
    print(f"Diff JSON: {json_path}")

    return 0


def cmd_planner_summarize_run(args: argparse.Namespace) -> int:
    """Summarize planner traces for a run and write markdown report."""
    from spec_manager.refinement.evals.planner.trace_loader import load_traces_for_run

    workspace = Path(args.workspace)
    traces = load_traces_for_run(workspace, args.run_id)

    reports_dir = workspace / "reports" / "pdd" / args.run_id
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / "planner_traces_summary.md"

    calls_by_capability: dict[str, dict[str, float]] = {}
    failure_clusters: dict[str, dict[str, object]] = {}
    expensive: list[dict[str, object]] = []

    for trace in traces:
        _layer, capability, slice_id, iteration = _planner_trace_parts(trace)
        capability_key = capability or "unknown"
        agg = calls_by_capability.setdefault(
            capability_key,
            {
                "decisions": 0.0,
                "model_calls": 0.0,
                "tool_calls": 0.0,
                "tokens": 0.0,
                "latency_ms": 0.0,
            },
        )

        model_calls = len(getattr(trace, "model_calls", []) or [])
        tool_calls = len(getattr(trace, "tool_calls", []) or [])
        tokens, latency_ms = _planner_trace_tokens_latency(trace)
        agg["decisions"] += 1.0
        agg["model_calls"] += float(model_calls)
        agg["tool_calls"] += float(tool_calls)
        agg["tokens"] += float(tokens)
        agg["latency_ms"] += latency_ms

        status = str(getattr(trace, "status", "") or "")
        if status.upper() != "OK":
            cluster_key = f"{capability_key}:{status or 'UNKNOWN'}"
            cluster = failure_clusters.setdefault(
                cluster_key,
                {"count": 0, "sample_trace_ids": []},
            )
            cluster["count"] = int(cluster["count"]) + 1
            sample = cluster["sample_trace_ids"]
            if isinstance(sample, list) and len(sample) < 5:
                sample.append(str(getattr(trace, "trace_id", "")))

        expensive.append(
            {
                "trace_id": str(getattr(trace, "trace_id", "")),
                "decision_key": str(getattr(trace, "decision_key", "")),
                "capability": capability_key,
                "slice_id": slice_id,
                "iteration": iteration,
                "model_calls": model_calls,
                "tool_calls": tool_calls,
                "tokens": tokens,
                "latency_ms": latency_ms,
            }
        )

    expensive.sort(
        key=lambda row: (
            float(row.get("tokens", 0)),
            float(row.get("latency_ms", 0.0)),
            int(row.get("model_calls", 0)) + int(row.get("tool_calls", 0)),
        ),
        reverse=True,
    )
    top_expensive = expensive[:20]

    lines = [
        f"# Planner Trace Summary -- Run {args.run_id}",
        "",
        f"Total traces: {len(traces)}",
        "",
        "## Calls Per Capability",
        "",
        (
            "| Capability | Decisions | Model Calls | Tool Calls | "
            "Avg Tokens/Decision | Avg Latency (ms) |"
        ),
        "|------------|-----------|-------------|------------|---------------------|------------------|",
    ]

    for capability, agg in sorted(calls_by_capability.items()):
        decisions = int(agg["decisions"])
        avg_tokens = (agg["tokens"] / decisions) if decisions else 0.0
        avg_latency = (agg["latency_ms"] / decisions) if decisions else 0.0
        lines.append(
            f"| {capability} | {decisions} | {int(agg['model_calls'])} | "
            f"{int(agg['tool_calls'])} | {avg_tokens:.1f} | {avg_latency:.1f} |"
        )

    lines.extend(
        [
            "",
            "## Failure Clusters",
            "",
            "| Cluster | Count | Sample Trace IDs |",
            "|---------|-------|------------------|",
        ]
    )
    if failure_clusters:
        for cluster_name, cluster in sorted(
            failure_clusters.items(),
            key=lambda item: int(item[1]["count"]),
            reverse=True,
        ):
            samples = cluster.get("sample_trace_ids", [])
            sample_text = (
                ", ".join(str(sample) for sample in samples) if isinstance(samples, list) else ""
            )
            lines.append(f"| {cluster_name} | {cluster['count']} | {sample_text or '(none)'} |")
    else:
        lines.append("| (none) | 0 | |")

    lines.extend(
        [
            "",
            "## Top Expensive Decisions",
            "",
            (
                "| Trace ID | Capability | Slice | Iteration | "
                "Model Calls | Tool Calls | Tokens | Latency (ms) |"
            ),
            "|----------|------------|-------|-----------|-------------|------------|--------|--------------|",
        ]
    )
    for row in top_expensive:
        lines.append(
            f"| {row['trace_id']} | {row['capability']} | {row['slice_id']} | {row['iteration']} | "
            f"{row['model_calls']} | {row['tool_calls']} | {row['tokens']} | "
            f"{row['latency_ms']:.1f} |"
        )

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Summary report written: {summary_path}")
    print(f"Traces summarized: {len(traces)}")

    return 0


def cmd_planner_timeline(args: argparse.Namespace) -> int:
    """Generate planner timeline HTML for a run."""
    import json

    from spec_manager.refinement.evals.planner.trace_loader import load_traces_for_run

    workspace = Path(args.workspace)
    traces = load_traces_for_run(workspace, args.run_id)
    reports_dir = workspace / "reports" / "pdd" / args.run_id
    reports_dir.mkdir(parents=True, exist_ok=True)
    timeline_path = reports_dir / "planner_timeline.html"

    rows = []
    for trace in traces:
        layer, capability, slice_id, iteration = _planner_trace_parts(trace)
        rows.append(
            {
                "trace_id": str(getattr(trace, "trace_id", "")),
                "layer": layer,
                "capability": capability,
                "slice_id": slice_id,
                "iteration": iteration,
                "status": str(getattr(trace, "status", "") or ""),
                "model_calls": len(getattr(trace, "model_calls", []) or []),
                "tool_calls": len(getattr(trace, "tool_calls", []) or []),
                "trace_path": f"../../../analysis/planner_traces/{getattr(trace, 'trace_id', '')}/",
            }
        )

    rows_json = json.dumps(rows, sort_keys=True)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Planner Timeline - {args.run_id}</title>
  <style>
    :root {{
      --bg: #f7f8fb;
      --panel: #ffffff;
      --line: #d8dde8;
      --text: #1d2a3d;
      --muted: #5b6880;
      --accent: #0f6ecf;
    }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: radial-gradient(circle at 0% 0%, #e9f3ff 0, var(--bg) 45%);
      color: var(--text);
    }}
    main {{
      max-width: 1100px;
      margin: 24px auto;
      padding: 0 12px 24px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: 0 6px 24px rgba(33, 42, 62, 0.08);
      overflow: hidden;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }}
    .header h1 {{
      margin: 0;
      font-size: 20px;
    }}
    .controls {{
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 13px;
      color: var(--muted);
    }}
    select {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 4px 8px;
      background: #fff;
      color: var(--text);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    thead th {{
      text-align: left;
      padding: 10px 12px;
      background: #f0f4fa;
      border-bottom: 1px solid var(--line);
      color: #24344d;
    }}
    tbody td {{
      border-bottom: 1px solid #edf1f7;
      padding: 9px 12px;
      vertical-align: middle;
    }}
    tbody tr {{
      cursor: pointer;
    }}
    tbody tr:hover {{
      background: #f6fbff;
    }}
    .heat {{
      text-align: center;
      font-weight: 600;
      border-radius: 6px;
    }}
    .status {{
      font-weight: 700;
      letter-spacing: 0.2px;
    }}
    .status.ok {{ color: #1a8f43; }}
    .status.error {{ color: #d03f2b; }}
    .hint {{
      padding: 8px 16px 12px;
      color: var(--muted);
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <div class="header">
        <h1>Planner Timeline: {args.run_id}</h1>
        <div class="controls">
          <label for="sortKey">Sort</label>
          <select id="sortKey">
            <option value="slice_id">slice</option>
            <option value="capability">capability</option>
            <option value="layer">layer</option>
            <option value="model_calls">model calls</option>
            <option value="tool_calls">tool calls</option>
          </select>
          <select id="sortDir">
            <option value="asc">asc</option>
            <option value="desc">desc</option>
          </select>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Trace</th>
            <th>Layer</th>
            <th>Capability</th>
            <th>Slice</th>
            <th>Iter</th>
            <th>Status</th>
            <th>Model Calls</th>
            <th>Tool Calls</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      <div class="hint">Click a row to open the trace directory.</div>
    </div>
  </main>
  <script>
    const rows = {rows_json};
    const rowsNode = document.getElementById("rows");
    const sortKey = document.getElementById("sortKey");
    const sortDir = document.getElementById("sortDir");
    const maxModel = Math.max(1, ...rows.map((r) => Number(r.model_calls || 0)));
    const maxTool = Math.max(1, ...rows.map((r) => Number(r.tool_calls || 0)));

    function heat(value, max, hue) {{
      const ratio = Math.max(0, Math.min(1, Number(value || 0) / max));
      const alpha = 0.12 + ratio * 0.6;
      return `hsla(${{hue}}, 75%, 45%, ${{alpha}})`;
    }}

    function compare(a, b, key, dir) {{
      const left = a[key];
      const right = b[key];
      if (typeof left === "number" && typeof right === "number") {{
        return dir === "asc" ? left - right : right - left;
      }}
      const l = String(left ?? "");
      const r = String(right ?? "");
      return dir === "asc" ? l.localeCompare(r) : r.localeCompare(l);
    }}

    function render() {{
      const key = sortKey.value;
      const dir = sortDir.value;
      const sorted = [...rows].sort((a, b) => compare(a, b, key, dir));
      rowsNode.innerHTML = "";
      for (const row of sorted) {{
        const tr = document.createElement("tr");
        tr.onclick = () => {{
          window.location.href = row.trace_path;
        }};
        const statusClass = String(row.status || "").toLowerCase() === "ok" ? "ok" : "error";
        tr.innerHTML = `
          <td><code>${{row.trace_id}}</code></td>
          <td>${{row.layer}}</td>
          <td>${{row.capability}}</td>
          <td>${{row.slice_id}}</td>
          <td>${{row.iteration}}</td>
          <td class="status ${{statusClass}}">${{row.status || "(none)"}}</td>
          <td
            class="heat"
            style="background:${{heat(row.model_calls, maxModel, 210)}}"
          >${{row.model_calls}}</td>
          <td
            class="heat"
            style="background:${{heat(row.tool_calls, maxTool, 25)}}"
          >${{row.tool_calls}}</td>
        `;
        rowsNode.appendChild(tr);
      }}
    }}
    sortKey.addEventListener("change", render);
    sortDir.addEventListener("change", render);
    render();
  </script>
</body>
</html>
"""
    timeline_path.write_text(html, encoding="utf-8")
    print(f"Timeline report written: {timeline_path}")
    print(f"Traces visualized: {len(rows)}")
    return 0


def cmd_planner_export_gt(args: argparse.Namespace) -> int:
    """Export ground truth template from planner traces."""
    from spec_manager.refinement.evals.planner.export_gt import GroundTruthExporter

    workspace = Path(args.workspace)
    exporter = GroundTruthExporter(workspace)
    out_path = exporter.export(
        run_id=args.run_id,
        out_path=Path(args.out),
        spec_id=args.spec_id,
    )
    print(f"Ground truth template exported: {out_path}")
    return 0


# --- Orchestration command handlers ---


def cmd_orchestration_setup(args: argparse.Namespace) -> int:
    """Set up orchestration eval workspace."""
    from spec_manager.refinement.evals.phase_evals.orchestration import (
        setup_orchestration_workspace,
    )

    manager, workspace_path = setup_orchestration_workspace(run_id=args.run_id)
    print(f"Workspace created: {workspace_path}")
    print(f"Run ID: {manager.run_id}")
    return 0


def cmd_orchestration_slices(args: argparse.Namespace) -> int:
    """List available slices for a layer."""
    from spec_manager.refinement.evals.phase_evals.orchestration import (
        discover_eval_slices,
        setup_orchestration_workspace,
    )

    manager, _ws = setup_orchestration_workspace(run_id=args.run_id)
    slices = discover_eval_slices(manager=manager, layer=args.layer)
    print(f"Layer {args.layer} slices ({len(slices)}):")
    for s in slices:
        print(f"  - {s['slice_id']} (worktree: {s['worktree_path']})")
    return 0


def cmd_orchestration_loop(args: argparse.Namespace) -> int:
    """Run PromotionLoop on a single slice."""
    import json

    from spec_manager.refinement.evals.phase_evals.orchestration import (
        run_promotion_loop_slice,
        setup_orchestration_workspace,
    )

    manager, workspace_path = setup_orchestration_workspace(run_id=args.run_id)
    result = run_promotion_loop_slice(
        manager=manager,
        layer=args.layer,
        slice_id=args.slice,
    )
    print(f"Slice: {result['slice_id']}")
    print(f"Status: {result['status']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Remaining gaps: {result['remaining_gaps']}")
    print(f"Demotion tickets: {result['demotion_count']}")
    print(f"Duration: {result['duration_ms']:.0f}ms")
    if result["error"]:
        print(f"Error: {result['error']}")

    result_path = workspace_path / f"eval_loop_{args.layer}_{args.slice}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Result saved: {result_path}")
    return 0


def cmd_orchestration_layer(args: argparse.Namespace) -> int:
    """Run full layer evaluation via PddLifecycle._run_layer()."""
    import json

    from spec_manager.refinement.evals.phase_evals.orchestration import (
        run_lifecycle_layer,
        setup_orchestration_workspace,
    )

    manager, workspace_path = setup_orchestration_workspace(run_id=args.run_id)
    result = run_lifecycle_layer(manager=manager, layer=args.layer)

    slices = result.get("slices", {}).get("slices", [])
    print(f"Layer {args.layer} results ({len(slices)} slices):")
    for s in slices:
        line = f"  {s['slice_id']}: {s['status']}"
        if s.get("iterations"):
            line += f" ({s['iterations']} iterations)"
        print(line)
    print(f"Duration: {result.get('duration_ms', 0):.0f}ms")

    results_path = workspace_path / f"eval_layer_{args.layer}.json"
    results_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Results saved: {results_path}")
    return 0


def cmd_orchestration_transition(args: argparse.Namespace) -> int:
    """Run layer transition evaluation."""
    import json

    from spec_manager.refinement.evals.phase_evals.orchestration import (
        run_lifecycle_transition,
        setup_orchestration_workspace,
    )

    manager, workspace_path = setup_orchestration_workspace(run_id=args.run_id)
    result = run_lifecycle_transition(
        manager=manager,
        from_layer=args.from_layer,
        to_layer=args.to_layer,
    )
    stuck = result.get("transition_stuck", False)
    rounds = len(result.get("rework_rounds", []))
    print(f"Transition {args.from_layer} -> {args.to_layer}:")
    print(f"  Stuck: {stuck}")
    print(f"  Rework rounds: {rounds}")
    print(f"  Duration: {result.get('duration_ms', 0):.0f}ms")
    if result.get("error"):
        print(f"  Error: {result['error']}")

    result_path = workspace_path / f"eval_transition_{args.from_layer}_{args.to_layer}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Result saved: {result_path}")
    return 0


def cmd_orchestration_scoring(args: argparse.Namespace) -> int:
    """Run scoring on orchestration results."""
    from spec_manager.refinement.evals.phase_evals.orchestration import (
        run_scoring,
        setup_orchestration_workspace,
    )

    manager, _ws = setup_orchestration_workspace(run_id=args.run_id)
    scorecard = run_scoring(manager=manager)
    print("Scorecard:")
    print(f"  Hard gates passed: {scorecard['hard_gates_passed']}/{scorecard['hard_gates_total']}")
    print(f"  Overall: {'PASS' if scorecard['overall_pass'] else 'FAIL'}")
    print(f"  Summary: {scorecard['summary']}")
    print(f"  Scores: {scorecard['scores_path']}")
    print(f"  Final report: {scorecard['final_report_path']}")
    return 0


def cmd_orchestration_report(args: argparse.Namespace) -> int:
    """Generate final orchestration report."""
    import json

    from spec_manager.refinement.evals.phase_evals.orchestration import (
        run_final_report,
        setup_orchestration_workspace,
    )

    manager, _ws = setup_orchestration_workspace(run_id=args.run_id)
    results_data = json.loads(Path(args.results_file).read_text(encoding="utf-8"))
    report_paths = run_final_report(manager=manager, run_results=results_data)
    print("Reports generated:")
    for label, path in report_paths.items():
        print(f"  {label}: {path}")
    return 0


def cmd_orchestration_full(args: argparse.Namespace) -> int:
    """Run full orchestration eval pipeline via PddLifecycle.run()."""
    import json

    from spec_manager.refinement.evals.phase_evals.orchestration import (
        run_full_pipeline,
        setup_orchestration_workspace,
    )

    print("=" * 60)
    print("ORCHESTRATION EVAL: FULL PIPELINE")
    print("=" * 60)

    manager, workspace_path = setup_orchestration_workspace(run_id=args.run_id)
    print(f"Workspace: {workspace_path}")
    print(f"Run ID: {manager.run_id}")

    result = run_full_pipeline(manager=manager)

    # Display per-layer results
    for layer_key in ("l1", "l2", "l3"):
        layer_data = result.get(layer_key, {})
        slices = layer_data.get("slices", {}).get("slices", [])
        print(f"\n--- {layer_key.upper()} ({len(slices)} slices) ---")
        for s in slices:
            print(f"  {s['slice_id']}: {s['status']}")

    # Display scorecard
    scorecard = result.get("scorecard", {})
    print("\n--- Scorecard ---")
    print(f"  Overall: {'PASS' if scorecard.get('overall_pass') else 'FAIL'}")
    print(f"  Summary: {scorecard.get('summary', '')}")

    # Save results
    results_path = workspace_path / "eval_full_results.json"
    results_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nResults saved: {results_path}")
    print(f"Duration: {result.get('duration_ms', 0):.0f}ms")

    return 0 if scorecard.get("overall_pass") else 1


def cmd_eval_quality(args: argparse.Namespace) -> int:
    """Compute quality scorecard via eval framework."""
    from spec_manager.evaluation.digests import (
        build_architecture_digest,
        build_code_digest,
    )
    from spec_manager.evaluation.quality import QualityReporter

    workspace = Path.cwd()
    run_id = args.run_id
    run_dir = workspace / ".pdd_runs" / run_id
    snapshot_dir = run_dir / "snapshot" / "files" / "spec_snapshot"

    arch_digest = build_architecture_digest(
        workspace,
        run_id,
        git_sha="",
        producer_model_id="",
    )
    code_digest = build_code_digest(
        workspace,
        run_id,
        git_sha="",
        producer_model_id="",
    )

    arch_judge = None
    code_judge = None
    spec_judge = None

    if args.judges:
        from spec_manager.refinement.evals.judges.arch_quality import ArchitectureQualityJudge
        from spec_manager.refinement.evals.judges.code_quality import CodeQualityJudge
        from spec_manager.refinement.evals.judges.spec_fidelity import SpecFidelityJudge

        producer_model_id = (
            (arch_digest.get("model") or {}).get("producer_model_id")
            or (code_digest.get("model") or {}).get("producer_model_id")
            or ""
        )

        arch_judge = (
            ArchitectureQualityJudge(
                workspace=workspace,
                model_id=args.judge_model,
                producer_model_id=producer_model_id,
                allow_self_judge=getattr(args, "allow_self_judge", False),
            )
            .evaluate(arch_digest)
            .model_dump()
        )

        code_judge = (
            CodeQualityJudge(
                workspace=workspace,
                model_id=args.judge_model,
                producer_model_id=producer_model_id,
                allow_self_judge=getattr(args, "allow_self_judge", False),
            )
            .evaluate(
                code_digest,
                snapshot_dir=snapshot_dir if snapshot_dir.exists() else None,
            )
            .model_dump()
        )

        spec_summary_path = run_dir / "spec_summary.json"
        if spec_summary_path.exists():
            import json as _json

            spec_summary = _json.loads(spec_summary_path.read_text(encoding="utf-8"))
            spec_judge = (
                SpecFidelityJudge(
                    workspace=workspace,
                    model_id=args.judge_model,
                    producer_model_id=producer_model_id,
                    allow_self_judge=getattr(args, "allow_self_judge", False),
                )
                .evaluate(
                    spec_summary=spec_summary,
                    code_digest=code_digest,
                    snapshot_dir=snapshot_dir if snapshot_dir.exists() else None,
                )
                .model_dump()
            )

    reporter = QualityReporter(workspace, run_id)
    scorecard = reporter.compute(
        arch_digest,
        code_digest,
        arch_judge_output=arch_judge,
        code_judge_output=code_judge,
        spec_judge_output=spec_judge,
    )
    json_path, _md_path = reporter.write(scorecard)

    print(f"Quality scorecard: {json_path}")
    print(f"Status: {scorecard.overall_status}")
    return 0


def cmd_eval_multi_model(args: argparse.Namespace) -> int:
    """Run multi-model comparison via eval framework."""
    from spec_manager.evaluation.model_profile import ModelProfile
    from spec_manager.evaluation.multi_model import MultiModelRunner

    raw_models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not raw_models:
        print("No models provided. Use --models name[:model_id],...", file=sys.stderr)
        return 2
    profiles = []
    for profile_str in raw_models:
        parts = profile_str.split(":", 1)
        name = parts[0].strip()
        model_id = parts[1].strip() if len(parts) > 1 and parts[1].strip() else name
        profiles.append(ModelProfile(name=name, producer_model_id=model_id))

    input_folder = Path(args.spec)

    runner = MultiModelRunner(
        workspace_root=input_folder,
        input_folder=input_folder,
    )
    manifest = runner.run(
        profiles=profiles,
        comparison_id=args.comparison_id or "",
        judge_model=args.judge_model,
        compute_quality=args.quality,
        runs_per_model=args.runs_per_model,
    )

    print(f"Comparison complete: {manifest['comparison_id']}")
    return 0


def handle_eval_command(args: argparse.Namespace) -> int:
    """Handle eval subcommand dispatch.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    commands = {
        "run": cmd_eval_run,
        "resume": cmd_eval_resume,
        "report": cmd_eval_report,
        "list": cmd_eval_list,
    }

    if args.eval_command == "planner":
        if not getattr(args, "planner_command", None):
            return cmd_planner_run(args)
        planner_commands = {
            "score": cmd_planner_score,
            "list": cmd_planner_list,
            "show": cmd_planner_show,
            "replay": cmd_planner_replay,
            "diff": cmd_planner_diff,
            "summarize-run": cmd_planner_summarize_run,
            "timeline": cmd_planner_timeline,
            "export-gt": cmd_planner_export_gt,
        }
        return planner_commands[args.planner_command](args)

    if args.eval_command == "orchestration":
        orchestration_commands = {
            "setup": cmd_orchestration_setup,
            "slices": cmd_orchestration_slices,
            "loop": cmd_orchestration_loop,
            "layer": cmd_orchestration_layer,
            "transition": cmd_orchestration_transition,
            "scoring": cmd_orchestration_scoring,
            "report": cmd_orchestration_report,
            "full": cmd_orchestration_full,
        }
        return orchestration_commands[args.orchestration_command](args)

    if args.eval_command == "quality":
        return cmd_eval_quality(args)

    if args.eval_command == "multi-model":
        return cmd_eval_multi_model(args)

    return commands[args.eval_command](args)


def main() -> int:
    """Standalone entry point for eval CLI.

    Returns:
        Exit code.
    """
    parser = argparse.ArgumentParser(
        description="Spec Refinement Evaluation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Set up eval commands directly at top level for standalone use
    # eval run
    p_run = subparsers.add_parser("run", help="Run evaluation on specs")
    p_run.add_argument(
        "--spec-ids",
        nargs="+",
        help="Specific spec IDs to evaluate (default: all)",
    )
    p_run.add_argument(
        "--fixtures-dir",
        help="Directory containing spec fixtures (default: <project>/.../fixtures)",
    )
    p_run.add_argument(
        "--output-dir",
        help="Directory for reports (default: <project>/runs/evals/reports)",
    )
    p_run.add_argument(
        "--checkpoint-dir",
        help="Directory for checkpoints (default: <project>/runs/evals/checkpoints)",
    )
    p_run.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Max iterations per phase (default: 10)",
    )
    p_run.add_argument(
        "--stagnation-threshold",
        type=int,
        default=3,
        help="Stagnation detection threshold (default: 3)",
    )
    p_run.add_argument(
        "--convergence-threshold",
        type=float,
        default=0.95,
        help="Convergence ratio threshold (default: 0.95)",
    )
    p_run.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.6,
        help="Fuzzy match threshold (default: 0.6)",
    )
    p_run.add_argument(
        "--parallel",
        action="store_true",
        help="Run specs in parallel",
    )
    p_run.add_argument(
        "--use-real-workflows",
        action="store_true",
        help="Use real workflow extraction instead of simulation",
    )
    p_run.add_argument(
        "--sparse",
        action="store_true",
        help="Run sparse-to-dense steering evaluation mode",
    )
    p_run.add_argument(
        "--mode",
        choices=["auto", "interactive", "steering-only"],
        default=None,
        help="Signal resolution mode for sparse-to-dense evals",
    )
    p_run.add_argument(
        "--resolve-ambiguities",
        action="store_true",
        help="Enable post-phase ambiguity resolution during evaluation",
    )
    p_run.add_argument(
        "--judge",
        action="store_true",
        help="Use LLM judge for semantic scoring instead of fuzzy matching",
    )
    p_run.add_argument(
        "--refinement",
        action="store_true",
        help="Use legacy refinement pipeline instead of PDD orchestrator (default: PDD)",
    )

    # eval resume
    p_resume = subparsers.add_parser("resume", help="Resume interrupted evaluation")
    p_resume.add_argument("run_id", help="Run ID to resume")
    p_resume.add_argument(
        "--fixtures-dir",
        help="Directory containing spec fixtures (default: <project>/.../fixtures)",
    )
    p_resume.add_argument(
        "--output-dir",
        help="Directory for reports (default: <project>/runs/evals/reports)",
    )
    p_resume.add_argument(
        "--checkpoint-dir",
        help="Directory for checkpoints (default: <project>/runs/evals/checkpoints)",
    )

    # eval report
    p_report = subparsers.add_parser("report", help="Generate or display report")
    p_report.add_argument("run_id", help="Run ID to generate report for")
    p_report.add_argument(
        "--format",
        choices=["summary", "json", "markdown"],
        default="summary",
        help="Output format (default: summary)",
    )
    p_report.add_argument(
        "--output-dir",
        help="Directory containing reports (default: <project>/runs/evals/reports)",
    )

    # eval list
    p_list = subparsers.add_parser("list", help="List available spec fixtures")
    p_list.add_argument(
        "--fixtures-dir",
        help="Directory containing spec fixtures (default: <project>/.../fixtures)",
    )

    args = parser.parse_args()

    commands = {
        "run": cmd_eval_run,
        "resume": cmd_eval_resume,
        "report": cmd_eval_report,
        "list": cmd_eval_list,
    }

    # Map to eval_command for consistency
    args.eval_command = args.command

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

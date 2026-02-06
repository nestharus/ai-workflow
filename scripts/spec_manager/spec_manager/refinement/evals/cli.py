"""CLI commands for evaluation framework.

Commands:
    eval run     Run evaluation on specs
    eval resume  Resume an interrupted evaluation
    eval report  Generate report from a completed run
    eval list    List available spec fixtures
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
    )

    fixtures_dir = Path(args.fixtures_dir) if args.fixtures_dir else _default_fixtures_dir()

    print("Running evaluation with config:")
    print(f"  Fixtures: {fixtures_dir}")
    print(f"  Output: {config.output_dir}")
    print(f"  Checkpoint: {config.checkpoint_dir}")

    if config.spec_ids:
        print(f"  Specs: {', '.join(config.spec_ids)}")
    else:
        print("  Specs: all available")

    # Create and run
    runner = EvalRunner(config, fixtures_dir=fixtures_dir)
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

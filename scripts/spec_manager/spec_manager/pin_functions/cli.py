"""CLI commands for the pin-function system.

Provides subcommands for scanning, diffing, querying, and analyzing
pin-functions via the spec-manager CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spec_manager.pin_functions.orchestrator import (
    PinFunctionConfig,
    PinFunctionOrchestrator,
)
from spec_manager.projection.pin_propagation import convert_propagation_to_drift


def setup_pin_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'pin' subcommand group in the CLI parser.

    Args:
        subparsers: The parent subparsers action to register into.
    """
    p_pin = subparsers.add_parser("pin", help="Pin-function management commands")
    pin_sub = p_pin.add_subparsers(dest="pin_command", required=True)

    # pin scan
    p_scan = pin_sub.add_parser("scan", help="Scan project and build pin-function registry")
    p_scan.add_argument("--project-root", default=".", help="Project root directory")
    p_scan.add_argument("--format", choices=["json", "text"], default="text", help="Output format")

    # pin diff
    p_diff = pin_sub.add_parser("diff", help="Compare current scan against previous registry")
    p_diff.add_argument("--project-root", default=".", help="Project root directory")
    p_diff.add_argument("--old-registry", help="Path to previous registry JSON")
    p_diff.add_argument("--format", choices=["json", "text"], default="text", help="Output format")

    # pin query
    p_query = pin_sub.add_parser("query", help="Query pin-function relationships")
    p_query.add_argument("--project-root", default=".", help="Project root directory")
    p_query.add_argument("--function", help="Query importers of a function")
    p_query.add_argument("--arch-file", help="Query pin-functions used by an arch file")

    # pin analysis
    p_analysis = pin_sub.add_parser("analysis", help="Generate pin-function analysis report")
    p_analysis.add_argument("--project-root", default=".", help="Project root directory")

    # pin test-check
    p_test_check = pin_sub.add_parser(
        "test-check",
        help="Check test-pin alignment (test signatures as stable anchors)",
    )
    p_test_check.add_argument("--project-root", default=".", help="Project root directory")
    p_test_check.add_argument(
        "--test-root", action="append", default=None,
        help="Test directory to scan (repeatable, default: tests/)",
    )
    p_test_check.add_argument(
        "--update-baseline", action="store_true",
        help="Update the baseline after checking",
    )
    p_test_check.add_argument(
        "--format", choices=["json", "text"], default="text",
        help="Output format",
    )


def handle_pin_command(args: argparse.Namespace) -> int:
    """Dispatch pin subcommands.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    handlers = {
        "scan": _cmd_pin_scan,
        "diff": _cmd_pin_diff,
        "query": _cmd_pin_query,
        "analysis": _cmd_pin_analysis,
        "test-check": _cmd_pin_test_check,
    }

    handler = handlers.get(args.pin_command)
    if handler is None:
        print(f"Unknown pin command: {args.pin_command}", file=sys.stderr)
        return 1

    return handler(args)


def _cmd_pin_scan(args: argparse.Namespace) -> int:
    """Execute the pin scan command."""
    project_root = Path(args.project_root).resolve()
    orchestrator = PinFunctionOrchestrator(project_root)

    registry = orchestrator.scan()

    # Save registry
    save_path = orchestrator.save_registry(registry)

    if getattr(args, "format", "text") == "json":
        print(registry.model_dump_json(indent=2))
    else:
        print(f"Pin-function scan complete:")
        print(f"  Pin-functions found: {len(registry.pin_functions)}")
        print(f"  Import edges found: {len(registry.import_edges)}")
        print(f"  Registry saved: {save_path}")

        if registry.pin_functions:
            print("\n  Pin-functions:")
            for pf in registry.pin_functions:
                shape = " [SHAPE]" if pf.is_shape else ""
                print(f"    - {pf.function_name}{shape} ({pf.file_path}:{pf.line_start})")

    return 0


def _cmd_pin_diff(args: argparse.Namespace) -> int:
    """Execute the pin diff command."""
    project_root = Path(args.project_root).resolve()
    orchestrator = PinFunctionOrchestrator(project_root)

    # Determine old registry path
    old_path = Path(args.old_registry) if args.old_registry else orchestrator.registry_path
    if not old_path.exists():
        print(f"No previous registry found at: {old_path}", file=sys.stderr)
        print("Run 'pin scan' first to create a baseline registry.")
        return 1

    report = orchestrator.diff(old_path)

    if getattr(args, "format", "text") == "json":
        output = {
            "changes": [
                {
                    "pin_func_id": c.pin_func_id,
                    "function_name": c.function_name,
                    "change_type": c.change_type,
                    "diff_summary": c.diff_summary,
                }
                for c in report.changes
            ],
            "propagation_items": [
                {
                    "arch_location": item.import_edge.arch_location,
                    "urgency": item.review_urgency,
                    "reason": item.reason,
                }
                for item in report.propagation_items
            ],
            "auto_propagated": report.auto_propagated_count,
            "review_required": report.review_required_count,
            "breaking_changes": report.breaking_change_count,
        }
        print(json.dumps(output, indent=2))
    else:
        if not report.changes:
            print("No changes detected.")
            return 0

        print(f"Changes detected: {len(report.changes)}")
        for change in report.changes:
            print(f"  [{change.change_type}] {change.function_name}: {change.diff_summary}")

        if report.propagation_items:
            print(f"\nAffected locations: {len(report.propagation_items)}")
            print(f"  Auto-propagated: {report.auto_propagated_count}")
            print(f"  Review required: {report.review_required_count}")
            print(f"  Breaking changes: {report.breaking_change_count}")

            for item in report.propagation_items:
                urgency_icon = {
                    "auto_propagated": "->",
                    "review_required": "??",
                    "breaking_change": "!!",
                }.get(item.review_urgency, "  ")
                print(f"  {urgency_icon} {item.import_edge.arch_location}: {item.reason}")

    return 0


def _cmd_pin_query(args: argparse.Namespace) -> int:
    """Execute the pin query command."""
    project_root = Path(args.project_root).resolve()
    orchestrator = PinFunctionOrchestrator(project_root)

    if args.function:
        edges = orchestrator.query_importers(args.function)
        if not edges:
            print(f"No importers found for function: {args.function}")
            return 0

        print(f"Importers of '{args.function}' ({len(edges)}):")
        for edge in edges:
            print(
                f"  - {edge.arch_location} ({edge.projection_type}, "
                f"line {edge.arch_line})"
            )
        return 0

    if args.arch_file:
        pin_funcs = orchestrator.query_pin_functions_for(args.arch_file)
        if not pin_funcs:
            print(f"No pin-functions found for: {args.arch_file}")
            return 0

        print(f"Pin-functions used by '{args.arch_file}' ({len(pin_funcs)}):")
        for pf in pin_funcs:
            shape = " [SHAPE]" if pf.is_shape else ""
            print(f"  - {pf.function_name}{shape} ({pf.module_path})")
        return 0

    print("Specify --function or --arch-file", file=sys.stderr)
    return 1


def _cmd_pin_analysis(args: argparse.Namespace) -> int:
    """Execute the pin analysis command."""
    project_root = Path(args.project_root).resolve()
    orchestrator = PinFunctionOrchestrator(project_root)

    report = orchestrator.generate_analysis_file()
    print(report)
    return 0


def _cmd_pin_test_check(args: argparse.Namespace) -> int:
    """Execute the pin test-check command.

    Runs the test-pin validation pipeline and reports drift.
    """
    from spec_manager.projection.lineage.test_pin_checker import (
        check_test_pin_alignment,
    )

    project_root = Path(args.project_root).resolve()

    # Resolve test roots
    test_root_args = getattr(args, "test_root", None)
    if test_root_args:
        test_roots = [project_root / r for r in test_root_args]
    else:
        test_roots = [project_root / "tests"]

    # Load or scan the PinFunctionRegistry
    orchestrator = PinFunctionOrchestrator(project_root)
    registry_path = orchestrator.registry_path
    if registry_path.exists():
        registry_data = json.loads(registry_path.read_text(encoding="utf-8"))
        from spec_manager.schemas.pin_functions import PinFunctionRegistry

        registry = PinFunctionRegistry(**registry_data)
    else:
        # Scan to build registry
        registry = orchestrator.scan()
        orchestrator.save_registry(registry)

    # Resolve baseline path
    baseline_path = project_root / ".spec" / "test_pin_baselines.json"

    # Run the check
    update_bl = getattr(args, "update_baseline", False)
    result = check_test_pin_alignment(
        registry=registry,
        test_roots=test_roots,
        baseline_path=baseline_path,
        update_baseline_flag=update_bl,
    )

    # Output results
    output_format = getattr(args, "format", "text")
    if output_format == "json":
        output = {
            "drift_items": [
                {
                    "drift_kind": d.drift_kind.value,
                    "pin_func_id": d.edge.from_unit,
                    "expected": d.expected,
                    "actual": d.actual,
                    "severity": d.severity,
                }
                for d in result.drift_items
            ],
            "total_pin_functions": result.total_pin_functions,
            "pin_functions_with_tests": result.pin_functions_with_tests,
            "pin_functions_without_tests": result.pin_functions_without_tests,
            "test_coverage_ratio": result.test_coverage_ratio,
            "associations_found": result.associations_found,
            "baseline_updated": result.baseline_updated,
        }
        print(json.dumps(output, indent=2))
    else:
        print("Test-Pin Alignment Check")
        print(f"  Pin-functions: {result.total_pin_functions}")
        print(f"  With tests: {result.pin_functions_with_tests}")
        print(f"  Without tests: {result.pin_functions_without_tests}")
        print(f"  Coverage: {result.test_coverage_ratio:.1%}")
        print(f"  Associations: {result.associations_found}")

        if result.drift_items:
            print(f"\n  Drift detected ({len(result.drift_items)} items):")
            for d in result.drift_items:
                print(f"    [{d.drift_kind.value}] {d.edge.from_unit}")
                print(f"      Expected: {d.expected}")
                print(f"      Actual:   {d.actual}")
        else:
            print("\n  No drift detected.")

        if result.baseline_updated:
            print(f"\n  Baseline updated: {baseline_path}")

    # Exit code: 0 if no drift, 1 if drift detected
    return 1 if result.drift_items else 0


__all__ = [
    "handle_pin_command",
    "setup_pin_parser",
]

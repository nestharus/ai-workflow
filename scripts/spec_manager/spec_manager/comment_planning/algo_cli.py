"""CLI commands for algorithmic planning operations.

Provides subcommands for:
- insert: Insert pseudocode comments from an intention
- reverse: Reverse-translate code to pseudocode comments
- scan: Scan for gaps (unimplemented comments + stubs)
- adjacency: Discover adjacent details
- decompose: Decompose an intention into micro-units
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def setup_plan_v2_parser(subparsers: Any) -> None:
    """Set up the plan-v2 subcommand group.

    Args:
        subparsers: Parent argparse subparsers object.
    """
    p_plan_v2 = subparsers.add_parser("plan-v2", help="Algorithmic planning v2 commands")
    plan_v2_sub = p_plan_v2.add_subparsers(dest="plan_v2_command", required=True)

    # insert
    p_insert = plan_v2_sub.add_parser("insert", help="Insert pseudocode comments from an intention")
    p_insert.add_argument("--file", required=True, help="Path to Python file")
    p_insert.add_argument("--function", required=True, help="Target function name")
    p_insert.add_argument("--intention", required=True, help="High-level intention text")
    p_insert.add_argument("--evidence-dir", help="Path to spec evidence directory")
    p_insert.add_argument("--apply", action="store_true", help="Write changes to disk")

    # reverse
    p_reverse = plan_v2_sub.add_parser(
        "reverse", help="Reverse-translate code to pseudocode comments"
    )
    p_reverse.add_argument("--file", required=True, help="Path to Python file")
    p_reverse.add_argument("--function", required=True, help="Target function name")
    p_reverse.add_argument("--start-line", type=int, help="Start line (1-based)")
    p_reverse.add_argument("--end-line", type=int, help="End line (1-based)")
    p_reverse.add_argument("--apply", action="store_true", help="Write changes to disk")

    # scan
    p_scan = plan_v2_sub.add_parser("scan", help="Scan for gaps (unimplemented comments + stubs)")
    p_scan.add_argument("--directory", required=True, help="Directory to scan")
    p_scan.add_argument("--json", action="store_true", help="Output as JSON")

    # adjacency
    p_adj = plan_v2_sub.add_parser("adjacency", help="Discover adjacent details for a function")
    p_adj.add_argument("--file", required=True, help="Path to Python file")
    p_adj.add_argument("--function", required=True, help="Target function name")
    p_adj.add_argument("--directory", required=True, help="Directory to build call graph from")

    # decompose
    p_decompose = plan_v2_sub.add_parser(
        "decompose", help="Decompose an intention into micro-units"
    )
    p_decompose.add_argument("--intention", required=True, help="High-level intention text")
    p_decompose.add_argument("--file", required=True, help="Path to Python file")
    p_decompose.add_argument("--function", required=True, help="Target function name")


def handle_plan_v2_command(args: argparse.Namespace) -> int:
    """Route plan-v2 subcommands to their handlers.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (0 for success).
    """
    handlers = {
        "insert": cmd_insert,
        "reverse": cmd_reverse,
        "scan": cmd_scan,
        "adjacency": cmd_adjacency,
        "decompose": cmd_decompose,
    }

    handler = handlers.get(args.plan_v2_command)
    if handler is None:
        print(f"Unknown plan-v2 command: {args.plan_v2_command}", file=sys.stderr)
        return 1

    return handler(args)


def cmd_insert(args: argparse.Namespace) -> int:
    """Handle plan-v2 insert command.

    Args:
        args: Parsed arguments with --file, --function, --intention.

    Returns:
        Exit code.
    """
    from spec_manager.comment_planning.evidence_store import EvidenceStore
    from spec_manager.comment_planning.inserter import (
        apply_insertion_plan,
        plan_insertions,
    )
    from spec_manager.comment_planning.models import parse_file

    file_path = str(Path(args.file).resolve())

    try:
        code_file = parse_file(file_path)
    except FileNotFoundError:
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1
    except SyntaxError as e:
        print(f"Syntax error in {file_path}: {e}", file=sys.stderr)
        return 1

    evidence_store = None
    if args.evidence_dir:
        evidence_dir = Path(args.evidence_dir).resolve()
        evidence_store = EvidenceStore(
            spec_snapshot_dir=evidence_dir / "spec_snapshot",
            libraries_dir=evidence_dir / "libraries",
        )

    try:
        plan = plan_insertions(
            intention=args.intention,
            code_file=code_file,
            function_name=args.function,
            evidence_store=evidence_store,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Insertion plan for {args.function} in {file_path}:")
    print(f"  Intention: {args.intention}")
    print(f"  Comments to insert: {len(plan.insertions)}")

    for point, text in plan.insertions:
        print(f"    Line {point.line_no}: # {text}")

    if args.apply:
        modified = apply_insertion_plan(plan)
        Path(file_path).write_text(modified, encoding="utf-8")
        print(f"\nChanges written to {file_path}")
    else:
        print("\nDry run. Use --apply to write changes.")

    return 0


def cmd_reverse(args: argparse.Namespace) -> int:
    """Handle plan-v2 reverse command.

    Args:
        args: Parsed arguments with --file, --function.

    Returns:
        Exit code.
    """
    from spec_manager.comment_planning.models import parse_file
    from spec_manager.comment_planning.reverser import (
        apply_reverse_plan,
        reverse_translate,
    )

    file_path = str(Path(args.file).resolve())

    try:
        code_file = parse_file(file_path)
    except FileNotFoundError:
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1
    except SyntaxError as e:
        print(f"Syntax error in {file_path}: {e}", file=sys.stderr)
        return 1

    try:
        plan = reverse_translate(
            code_file=code_file,
            function_name=args.function,
            start_line=getattr(args, "start_line", None),
            end_line=getattr(args, "end_line", None),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Reverse translation for {args.function} in {file_path}:")
    print(f"  Range: lines {plan.start_line}-{plan.end_line}")
    print(f"  Generated comments: {len(plan.generated_comments)}")

    for comment in plan.generated_comments:
        print(f"    # {comment.text}")

    if args.apply:
        modified = apply_reverse_plan(plan)
        Path(file_path).write_text(modified, encoding="utf-8")
        print(f"\nChanges written to {file_path}")
    else:
        print("\nDry run. Use --apply to write changes.")

    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Handle plan-v2 scan command.

    Args:
        args: Parsed arguments with --directory.

    Returns:
        Exit code.
    """
    from spec_manager.comment_planning.gap_bridge import scan_for_gaps
    from spec_manager.comment_planning.models import parse_file

    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        print(f"Not a directory: {directory}", file=sys.stderr)
        return 1

    code_files = []
    for py_file in sorted(directory.rglob("*.py")):
        try:
            code_files.append(parse_file(str(py_file)))
        except (SyntaxError, OSError):
            continue

    gaps = scan_for_gaps(code_files)

    if hasattr(args, "json") and args.json:
        print(json.dumps([g.to_dict() for g in gaps], indent=2))
    else:
        print(f"Scanned {len(code_files)} files, found {len(gaps)} gaps:")
        for gap in gaps:
            severity = gap.severity.value.upper()
            print(f"  [{severity}] {gap.id}: {gap.description}")

    return 0


def cmd_adjacency(args: argparse.Namespace) -> int:
    """Handle plan-v2 adjacency command.

    Args:
        args: Parsed arguments with --file, --function, --directory.

    Returns:
        Exit code.
    """
    from spec_manager.comment_planning.adjacency import (
        build_call_graph,
        discover_adjacent_details,
        find_store_touches,
    )
    from spec_manager.comment_planning.models import parse_file

    file_path = str(Path(args.file).resolve())
    directory = Path(args.directory).resolve()

    if not directory.is_dir():
        print(f"Not a directory: {directory}", file=sys.stderr)
        return 1

    # Parse all files for call graph
    code_files = []
    for py_file in sorted(directory.rglob("*.py")):
        try:
            code_files.append(parse_file(str(py_file)))
        except (SyntaxError, OSError):
            continue

    # Build call graph and store touches
    call_graph = build_call_graph(code_files)
    store_touches = find_store_touches(code_files)

    # Find the qualified function name
    target_code_file = None
    for cf in code_files:
        if cf.file_path == file_path:
            target_code_file = cf
            break

    if target_code_file is None:
        print(f"File not found in scanned directory: {file_path}", file=sys.stderr)
        return 1

    # Build qualified name
    from spec_manager.comment_planning.adjacency import _module_name_from_path

    module = _module_name_from_path(file_path)
    qualified = f"{module}.{args.function}"

    # Check if function exists in file
    func_found = any(f.name == args.function for f in target_code_file.functions)
    if not func_found:
        print(
            f"Function '{args.function}' not found in {file_path}",
            file=sys.stderr,
        )
        return 1

    adjacencies = discover_adjacent_details(qualified, call_graph, store_touches)

    print(f"Adjacent details for {args.function}:")
    if not adjacencies:
        print("  No adjacent details found.")
    else:
        for adj in adjacencies:
            store_info = f" via {adj.store_or_event}" if adj.store_or_event else ""
            coverage = "tested" if adj.has_test_coverage else "UNTESTED"
            needs = " [NEEDS PLAN]" if adj.needs_plan else ""
            print(f"  {adj.relationship}: {adj.related_function}{store_info} ({coverage}){needs}")

    return 0


def cmd_decompose(args: argparse.Namespace) -> int:
    """Handle plan-v2 decompose command.

    Args:
        args: Parsed arguments with --intention, --file, --function.

    Returns:
        Exit code.
    """
    from spec_manager.comment_planning.inserter import decompose_intention
    from spec_manager.comment_planning.models import parse_file

    file_path = str(Path(args.file).resolve())

    try:
        code_file = parse_file(file_path)
    except FileNotFoundError:
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1
    except SyntaxError as e:
        print(f"Syntax error in {file_path}: {e}", file=sys.stderr)
        return 1

    # Find the target function
    func = None
    for f in code_file.functions:
        if f.name == args.function:
            func = f
            break

    if func is None:
        print(
            f"Function '{args.function}' not found in {file_path}",
            file=sys.stderr,
        )
        return 1

    micro_units = decompose_intention(args.intention, func)

    print(f"Decomposition of: {args.intention}")
    print(f"  Target: {args.function} in {file_path}")
    print(f"  Micro-units ({len(micro_units)}):")
    for i, unit in enumerate(micro_units, 1):
        print(f"    {i}. # {unit}")

    return 0

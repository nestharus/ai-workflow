"""CLI commands for algorithmic planning operations.

Provides subcommands for:
- insert: Insert pseudocode comments from an intention
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
    print(f"  Decomposition strategy: {plan.decomposition_strategy}")
    if plan.decomposition_failure_kind:
        print(f"  Decomposition failure kind: {plan.decomposition_failure_kind}")
    if plan.decomposition_failure_reason:
        print(f"  Decomposition failure: {plan.decomposition_failure_reason}")

    for point, text in plan.insertions:
        print(f"    Line {point.line_no}: # {text}")

    if plan.ambiguity_gaps:
        print("  Unresolved ambiguity gaps:")
        for gap in plan.ambiguity_gaps:
            print(f"    - {gap}")

    if args.apply:
        modified = apply_insertion_plan(plan)
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

    from spec_manager.core.language import source_rglob

    code_files = []
    scan_errors: list[dict[str, str]] = []
    for py_file in source_rglob(directory):
        py_path = str(py_file)
        try:
            code_files.append(parse_file(py_path))
        except (SyntaxError, OSError, ValueError, TypeError) as exc:
            scan_errors.append({"file": py_path, "error": f"{type(exc).__name__}: {exc}"})
            continue

    gaps = scan_for_gaps(code_files)

    if hasattr(args, "json") and args.json:
        payload = {
            "files_scanned": len(code_files),
            "scan_errors": scan_errors,
            "gaps": [g.to_dict() for g in gaps],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"Scanned {len(code_files)} files, found {len(gaps)} gaps:")
        if scan_errors:
            print(f"  Skipped {len(scan_errors)} files due to parse/read failures:")
            for row in scan_errors:
                print(f"    - {row['file']}: {row['error']}")
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
        discover_adjacent_details_from_relationship_edges,
        module_name_from_path,
    )
    from spec_manager.core.code_analysis import analyze_file_facts

    file_path = str(Path(args.file).resolve())
    directory = Path(args.directory).resolve()

    if not directory.is_dir():
        print(f"Not a directory: {directory}", file=sys.stderr)
        return 1

    from spec_manager.core.language import source_rglob

    relationship_edges: list[dict[str, object]] = []
    scan_errors: list[dict[str, str]] = []
    target_functions: list[Any] = []

    for py_file in source_rglob(directory):
        py_path = py_file.resolve()
        py_path_str = str(py_path)
        try:
            source = py_path.read_text(encoding="utf-8")
            facts = analyze_file_facts(source, py_path_str, workspace=directory)
            relationship_edges.extend(
                edge for edge in facts.relationship_edges if isinstance(edge, dict)
            )
            if py_path_str == file_path:
                target_functions = list(facts.source_analysis.functions)
        except (SyntaxError, OSError, ValueError, TypeError) as exc:
            scan_errors.append({"file": py_path_str, "error": f"{type(exc).__name__}: {exc}"})
            continue

    if not target_functions:
        print(f"File not found in scanned directory: {file_path}", file=sys.stderr)
        if scan_errors:
            print("Scan failures:", file=sys.stderr)
            for row in scan_errors:
                print(f"  - {row['file']}: {row['error']}", file=sys.stderr)
        return 1

    target_raw = _resolve_target_raw_function(target_functions, args.function)
    if target_raw is None:
        print(
            f"Function '{args.function}' not found in {file_path}",
            file=sys.stderr,
        )
        return 1
    if isinstance(target_raw, list):
        options = ", ".join(
            f"{fn.qualified_name or fn.name}@{fn.start_line}-{fn.end_line}" for fn in target_raw
        )
        print(
            f"Function selector '{args.function}' is ambiguous in {file_path}: {options}",
            file=sys.stderr,
        )
        return 1

    module = module_name_from_path(file_path)
    try:
        qualified = _resolve_relationship_function_id(target_raw, module, relationship_edges)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    adjacencies = discover_adjacent_details_from_relationship_edges(qualified, relationship_edges)

    print(f"Adjacent details for {args.function} ({qualified}):")
    if scan_errors:
        print(f"  Note: skipped {len(scan_errors)} files due to parse/read failures.")
    if not adjacencies:
        print("  No adjacent details found.")
    else:
        for adj in adjacencies:
            store_info = f" via {adj.store_or_event}" if adj.store_or_event else ""
            coverage = (
                "tested"
                if adj.has_test_coverage is True
                else "UNTESTED"
                if adj.has_test_coverage is False
                else "UNKNOWN"
            )
            needs = " [NEEDS PLAN]" if adj.needs_plan else ""
            print(f"  {adj.relationship}: {adj.related_function}{store_info} ({coverage}){needs}")

    return 0


def _resolve_target_raw_function(
    functions: list[Any],
    selector: str,
) -> Any | list[Any] | None:
    """Resolve CLI function selector against raw analysis functions."""
    target = selector.strip()
    if not target:
        return None

    exact: list[Any] = []
    fallback: list[Any] = []
    for func in functions:
        name = str(getattr(func, "name", "") or "").strip()
        qualified = str(getattr(func, "qualified_name", "") or name).strip()
        if target == qualified:
            exact.append(func)
        if name == target or qualified.endswith("." + target):
            fallback.append(func)

    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact
    if len(fallback) == 1:
        return fallback[0]
    if len(fallback) > 1:
        return fallback
    return None


def _resolve_relationship_function_id(
    raw_func: Any,
    module_name: str,
    relationship_edges: list[dict[str, object]],
) -> str:
    """Resolve function identifier as it appears in relationship edges."""
    qualified = str(
        getattr(raw_func, "qualified_name", "") or getattr(raw_func, "name", "")
    ).strip()
    name = str(getattr(raw_func, "name", "")).strip()
    preferred = [qualified, f"{module_name}.{qualified}", name, f"{module_name}.{name}"]

    endpoints: set[str] = set()
    for edge in relationship_edges:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("src") or edge.get("src_id") or "").strip()
        dst = str(edge.get("dst") or edge.get("dst_id") or "").strip()
        if src:
            endpoints.add(src)
        if dst:
            endpoints.add(dst)

    for candidate in preferred:
        if candidate and candidate in endpoints:
            return candidate

    suffixes = [f".{qualified}", f".{name}"]
    matched = sorted(
        endpoint
        for endpoint in endpoints
        if endpoint and any(endpoint.endswith(suffix) for suffix in suffixes)
    )
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        raise ValueError(
            f"Ambiguous relationship identifier for {qualified or name}: {', '.join(matched)}"
        )

    if qualified:
        return f"{module_name}.{qualified}"
    return f"{module_name}.{name}"


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

    matches = []
    selector = str(args.function).strip()
    for f in code_file.functions:
        if f.name == selector:
            matches.append(f)
            continue
        if f.class_name and f"{f.class_name}.{f.name}" == selector:
            matches.append(f)

    if not matches:
        print(
            f"Function '{args.function}' not found in {file_path}",
            file=sys.stderr,
        )
        return 1
    if len(matches) > 1:
        options = ", ".join(
            f"{f.class_name + '.' if f.class_name else ''}{f.name}@{f.start_line}-{f.end_line}"
            for f in matches
        )
        print(
            f"Function selector '{args.function}' is ambiguous in {file_path}: {options}",
            file=sys.stderr,
        )
        return 1

    func = matches[0]

    micro_units = decompose_intention(args.intention, func)

    print(f"Decomposition of: {args.intention}")
    print(f"  Target: {args.function} in {file_path}")
    print(f"  Micro-units ({len(micro_units)}):")
    for i, unit in enumerate(micro_units, 1):
        print(f"    {i}. # {unit}")

    return 0

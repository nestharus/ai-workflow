"""Workflow integration for planning with the workspace/phase system.

Provides the run_planning_v2_phase function that integrates with
WorkspaceManager and Phase.PLANNING_V2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spec_manager.comment_planning.adjacency import (
    build_call_graph,
    discover_adjacent_details,
    find_store_touches,
)
from spec_manager.comment_planning.evidence_store import EvidenceStore
from spec_manager.comment_planning.gap_bridge import adjacencies_to_gaps, scan_for_gaps
from spec_manager.comment_planning.inserter import plan_insertions
from spec_manager.comment_planning.models import CodeFile, InsertionPlan, parse_file


def run_planning_v2_phase(
    run_id: str,
    target_files: list[str],
    intentions: list[str],
    evidence_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the algorithmic planning phase within the refinement workflow.

    Steps:
    1. Parse target files
    2. For each intention, decompose into micro-units
    3. Determine insertion points
    4. Resolve ambiguities via evidence store
    5. Generate InsertionPlans
    6. Discover adjacent details
    7. Convert unresolved items to gaps
    8. Write artifacts (plans, gaps, adjacency report)

    Args:
        run_id: Unique run identifier.
        target_files: List of Python file paths to plan against.
        intentions: List of high-level intention strings.
        evidence_dir: Optional path to spec evidence directory.
        output_dir: Optional output directory for artifacts.

    Returns:
        Dict with results including plans, gaps, and adjacency info.
    """
    # Step 1: Parse target files
    code_files: list[CodeFile] = []
    parse_errors: list[str] = []
    for file_path in target_files:
        try:
            code_files.append(parse_file(file_path))
        except (FileNotFoundError, SyntaxError) as e:
            parse_errors.append(f"{file_path}: {e}")

    if not code_files:
        return {
            "success": False,
            "run_id": run_id,
            "error": "No files could be parsed",
            "parse_errors": parse_errors,
            "plans": [],
            "gaps": [],
            "adjacencies": [],
        }

    # Step 2-5: Generate insertion plans
    evidence_store = None
    if evidence_dir and evidence_dir.is_dir():
        evidence_store = EvidenceStore(
            spec_snapshot_dir=evidence_dir / "spec_snapshot",
            libraries_dir=evidence_dir / "libraries",
        )

    plans: list[InsertionPlan] = []
    plan_errors: list[str] = []
    for intention in intentions:
        for code_file in code_files:
            for func in code_file.functions:
                try:
                    plan = plan_insertions(
                        intention=intention,
                        code_file=code_file,
                        function_name=func.name,
                        evidence_store=evidence_store,
                    )
                    if plan.insertions:
                        plans.append(plan)
                except (ValueError, RuntimeError) as e:
                    plan_errors.append(f"{func.name}: {e}")

    # Step 6: Discover adjacent details
    call_graph = build_call_graph(code_files)
    store_touches = find_store_touches(code_files)

    all_adjacencies = []
    for code_file in code_files:
        from spec_manager.comment_planning.adjacency import _module_name_from_path

        module = _module_name_from_path(code_file.file_path)
        for func in code_file.functions:
            qualified = f"{module}.{func.name}"
            adjacencies = discover_adjacent_details(qualified, call_graph, store_touches)
            all_adjacencies.extend(adjacencies)

    # Step 7: Convert to gaps
    code_gaps = scan_for_gaps(code_files)
    adjacency_gaps = adjacencies_to_gaps(all_adjacencies)
    all_gaps = code_gaps + adjacency_gaps

    # Step 8: Write artifacts
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_artifacts(output_dir, run_id, plans, all_gaps, all_adjacencies)

    return {
        "success": True,
        "run_id": run_id,
        "files_parsed": len(code_files),
        "parse_errors": parse_errors,
        "plans_generated": len(plans),
        "plan_errors": plan_errors,
        "total_insertions": sum(len(p.insertions) for p in plans),
        "gaps_detected": len(all_gaps),
        "adjacencies_found": len(all_adjacencies),
        "plans": [
            {
                "file": p.file_path,
                "intention": p.source_intention,
                "insertions": len(p.insertions),
                "evidence_refs": p.evidence_refs,
            }
            for p in plans
        ],
        "gaps": [g.to_dict() for g in all_gaps],
        "adjacencies": [
            {
                "source": a.source_function,
                "related": a.related_function,
                "relationship": a.relationship,
                "store_or_event": a.store_or_event,
                "has_tests": a.has_test_coverage,
                "needs_plan": a.needs_plan,
            }
            for a in all_adjacencies
        ],
    }


def _write_artifacts(
    output_dir: Path,
    run_id: str,
    plans: list[InsertionPlan],
    gaps: list,
    adjacencies: list,
) -> None:
    """Write workflow artifacts to disk.

    Args:
        output_dir: Output directory.
        run_id: Run identifier.
        plans: Generated insertion plans.
        gaps: Detected gaps.
        adjacencies: Discovered adjacencies.
    """
    # Plans
    plans_data = []
    for plan in plans:
        plans_data.append(
            {
                "file": plan.file_path,
                "intention": plan.source_intention,
                "insertions": [
                    {
                        "line_no": point.line_no,
                        "indent": point.indent_level,
                        "comment": text,
                        "rationale": point.rationale,
                    }
                    for point, text in plan.insertions
                ],
                "evidence_refs": plan.evidence_refs,
            }
        )

    plans_path = output_dir / f"{run_id}_plans.json"
    plans_path.write_text(json.dumps(plans_data, indent=2), encoding="utf-8")

    # Gaps
    from spec_manager.core.gap import Gap

    gaps_data = [g.to_dict() if isinstance(g, Gap) else g for g in gaps]
    gaps_path = output_dir / f"{run_id}_gaps.json"
    gaps_path.write_text(json.dumps(gaps_data, indent=2), encoding="utf-8")

    # Adjacencies
    adj_data = []
    for a in adjacencies:
        if hasattr(a, "source_function"):
            adj_data.append(
                {
                    "source": a.source_function,
                    "related": a.related_function,
                    "relationship": a.relationship,
                    "store_or_event": a.store_or_event,
                    "has_tests": a.has_test_coverage,
                    "needs_plan": a.needs_plan,
                }
            )
        else:
            adj_data.append(a)

    adj_path = output_dir / f"{run_id}_adjacencies.json"
    adj_path.write_text(json.dumps(adj_data, indent=2), encoding="utf-8")

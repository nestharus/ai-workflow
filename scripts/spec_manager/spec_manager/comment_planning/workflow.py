"""Workflow integration for planning with the workspace/phase system.

Provides the run_planning_v2_phase function that integrates with
WorkspaceManager and Phase.PLANNING_V2.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from spec_manager.comment_planning.adjacency import (
    discover_adjacent_details_from_relationship_edges,
)
from spec_manager.comment_planning.evidence_store import EvidenceStore
from spec_manager.comment_planning.gap_bridge import adjacencies_to_gaps
from spec_manager.comment_planning.inserter import plan_insertions
from spec_manager.comment_planning.models import (
    CodeFile,
    InsertionPlan,
    parse_source_index_entry,
)
from spec_manager.core.code_analysis import analyze_file_facts
from spec_manager.orchestration.evidence import EvidenceBundle


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
    bundle = _load_latest_bundle(evidence_dir)
    bootstrap_errors: list[str] = []
    if bundle is None:
        bundle, bootstrap_errors = _bootstrap_bundle_from_targets(
            run_id=run_id,
            target_files=target_files,
            evidence_dir=evidence_dir,
        )
    if bundle is None:
        return {
            "success": False,
            "run_id": run_id,
            "error": "Unable to build canonical planning evidence from target files",
            "parse_errors": bootstrap_errors or ["missing_bundle"],
            "plans": [],
            "gaps": [],
            "adjacencies": [],
        }

    source_root = _resolve_source_root(bundle, evidence_dir)
    code_files, parse_errors = _load_code_files_from_source_index(
        bundle=bundle,
        source_root=source_root,
        target_files=target_files,
    )
    parse_errors = bootstrap_errors + parse_errors

    if not code_files:
        return {
            "success": False,
            "run_id": run_id,
            "error": "No canonical source-index entries matched target files",
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

    # Step 6: Discover adjacent details from canonical relationship edges
    relationship_edges = _collect_relationship_edges(bundle)

    all_adjacencies = []
    for code_file in code_files:
        from spec_manager.comment_planning.adjacency import _module_name_from_path

        module = _module_name_from_path(code_file.file_path)
        for func in code_file.functions:
            qualified = f"{module}.{func.name}"
            adjacencies = discover_adjacent_details_from_relationship_edges(
                qualified,
                relationship_edges,
            )
            all_adjacencies.extend(adjacencies)

    # Step 7: Convert to gaps
    code_gaps = _canonical_gap_records(bundle)
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
        "gaps": [
            g.to_dict() if hasattr(g, "to_dict") else dict(g)
            for g in all_gaps
            if hasattr(g, "to_dict") or isinstance(g, dict)
        ],
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


def _load_latest_bundle(evidence_dir: Path | None) -> EvidenceBundle | None:
    """Load the latest available canonical evidence bundle."""
    if evidence_dir is None:
        return None
    root = evidence_dir.resolve()
    candidates: list[Path] = []
    direct = root / "bundle.json"
    if direct.exists():
        candidates.append(direct)
    candidates.extend(root.glob(".pdd_runs/*/slices/*/iter_*/bundle.json"))
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    try:
        return EvidenceBundle.load(latest)
    except Exception:
        return None


def _resolve_source_root(bundle: EvidenceBundle, evidence_dir: Path | None) -> Path:
    """Resolve source root used for source-index path hydration."""
    bundle_slice_root = str(bundle.slice_root or "").strip()
    if bundle_slice_root:
        candidate = Path(bundle_slice_root)
        if candidate.exists():
            return candidate
    if evidence_dir is not None:
        return evidence_dir.resolve()
    return Path(".")


def _path_matches_target(
    *,
    candidate: Path,
    rel_path: str,
    target_files: list[str],
) -> bool:
    if not target_files:
        return True
    candidate_norm = candidate.as_posix()
    rel_norm = rel_path.replace("\\", "/")
    target_norm = [str(Path(path)).replace("\\", "/") for path in target_files]
    for target in target_norm:
        if not target:
            continue
        if target in (rel_norm, candidate_norm):
            return True
        if candidate_norm.endswith("/" + target) or rel_norm.endswith("/" + target):
            return True
    return False


def _load_code_files_from_source_index(
    *,
    bundle: EvidenceBundle,
    source_root: Path,
    target_files: list[str],
) -> tuple[list[CodeFile], list[str]]:
    """Hydrate CodeFile views from canonical source-index entries."""
    code_files: list[CodeFile] = []
    errors: list[str] = []
    for entry in bundle.source_index.entries or []:
        if not isinstance(entry, dict):
            continue
        rel_path = str(entry.get("path", "")).strip()
        if not rel_path:
            continue
        candidate = source_root / rel_path
        if not _path_matches_target(
            candidate=candidate,
            rel_path=rel_path,
            target_files=target_files,
        ):
            continue
        try:
            code_files.append(parse_source_index_entry(entry, source_root))
        except Exception as exc:
            errors.append(f"{rel_path}: {exc}")
    return code_files, errors


def _collect_relationship_edges(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    """Collect canonical relationship edges from facts and source-index payloads."""
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in bundle.facts.call_graph_edges or []:
        if not isinstance(edge, dict):
            continue
        fingerprint = json.dumps(edge, sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        edges.append(edge)

    for entry in bundle.source_index.entries or []:
        if not isinstance(entry, dict):
            continue
        analysis = entry.get("analysis")
        if not isinstance(analysis, dict):
            continue
        file_facts = analysis.get("file_facts")
        if not isinstance(file_facts, dict):
            continue
        for edge in file_facts.get("relationship_edges", []):
            if not isinstance(edge, dict):
                continue
            fingerprint = json.dumps(edge, sort_keys=True)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            edges.append(edge)
    return edges


def _canonical_gap_records(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    """Return open gap records from canonical bundle evidence."""
    gaps = [gap for gap in bundle.gaps.open_gaps if isinstance(gap, dict)]
    if gaps:
        return [dict(gap) for gap in gaps]
    return [dict(gap) for gap in bundle.facts.remaining_gap_pins if isinstance(gap, dict)]


def _bootstrap_bundle_from_targets(
    *,
    run_id: str,
    target_files: list[str],
    evidence_dir: Path | None,
) -> tuple[EvidenceBundle | None, list[str]]:
    """Build canonical evidence bundle from target files when no bundle exists yet."""
    source_root = evidence_dir.resolve() if evidence_dir is not None else Path.cwd()
    bundle = EvidenceBundle(
        run_id=run_id,
        slice_id="planning-bootstrap",
        iteration=0,
        workspace_root=str(source_root),
        slice_root=str(source_root),
    )
    errors: list[str] = []
    for raw_path in target_files:
        target = Path(raw_path)
        if not target.exists() or not target.is_file():
            errors.append(f"{raw_path}: file not found")
            continue
        try:
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{raw_path}: {exc}")
            continue

        try:
            rel_path = str(target.resolve().relative_to(source_root.resolve()))
        except ValueError:
            rel_path = target.as_posix()

        try:
            facts = analyze_file_facts(
                source,
                rel_path,
                workspace=source_root,
                run_id=run_id,
            )
        except Exception as exc:  # pragma: no cover - defensive integration boundary
            errors.append(f"{raw_path}: analyze_file_facts failed: {exc}")
            continue

        file_facts_payload = {
            "structure_hints": dict(facts.structure_hints),
            "remaining_gap_pins": list(facts.gap_pins),
            "relationship_edges": list(facts.relationship_edges),
            "test_identity_hints": list(facts.test_identity_hints),
            "functions": dict(facts.functions),
            "stub_nodes": list(facts.stub_nodes),
            "call_graph_nodes": list(facts.call_graph_nodes),
            "call_graph_edges": list(facts.call_graph_edges),
            "stores": dict(facts.stores),
            "store_owners": dict(facts.store_owners),
        }
        bundle.source_index.entries.append(
            {
                "path": rel_path,
                "content_hash": facts.content_hash,
                "analysis": {
                    "functions": [asdict(fn) for fn in facts.source_analysis.functions],
                    "comments": [asdict(comment) for comment in facts.source_analysis.comments],
                    "facets": (
                        dict(facts.source_analysis.facets)
                        if isinstance(facts.source_analysis.facets, dict)
                        else {}
                    ),
                    "file_facts": file_facts_payload,
                },
            }
        )
        _merge_bundle_facts(bundle, file_facts_payload)

    if not bundle.source_index.entries:
        return None, errors

    bundle.source_index.path = "source_analysis.index.json"
    bundle.facts.path = "facts.json"
    bundle.gaps.open_gaps = _canonical_gap_records(bundle)
    bundle.gaps.path = "gaps.json"
    return bundle, errors


def _merge_bundle_facts(bundle: EvidenceBundle, payload: dict[str, Any]) -> None:
    """Merge one file-facts payload into bundle-level facts."""
    functions = payload.get("functions", {})
    if isinstance(functions, dict):
        bundle.facts.functions.update(functions)

    stores = payload.get("stores", {})
    if isinstance(stores, dict):
        for store_id, details in stores.items():
            if not isinstance(details, dict):
                continue
            existing = bundle.facts.stores.get(store_id, {})
            if not isinstance(existing, dict):
                existing = {}
            merged_owners = sorted(
                set(existing.get("owner_atoms", []) + details.get("owner_atoms", []))
            )
            bundle.facts.stores[store_id] = {
                "owner_atoms": merged_owners,
                "schema": details.get("schema", existing.get("schema", {})),
            }

    for row in payload.get("remaining_gap_pins", []):
        if isinstance(row, dict):
            bundle.facts.remaining_gap_pins.append(dict(row))
    for row in payload.get("stub_nodes", []):
        if isinstance(row, dict):
            bundle.facts.stub_nodes.append(dict(row))
    for row in payload.get("call_graph_edges", []):
        if isinstance(row, dict):
            bundle.facts.call_graph_edges.append(dict(row))

    nodes = [str(node).strip() for node in payload.get("call_graph_nodes", []) if str(node).strip()]
    if nodes:
        bundle.facts.call_graph_nodes = sorted(set(bundle.facts.call_graph_nodes + nodes))


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

"""Report generators for refinement workflows."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.formats import parse_evidence_pointer
from spec_manager.refinement.qa.bad_signatures import scan_known_bad_signatures
from spec_manager.refinement.qa.runner import run_qa_suite
from spec_manager.refinement.validation_utils import (
    SECTION_ID_RE,
    build_file_id_lookup,
    build_section_alias_map,
    resolve_section_reference,
)
from spec_manager.refinement.workflows.trace_indexes import (
    build_atom_to_section_index,
    build_section_to_spec_elements_index,
    build_spec_element_to_tasks_index,
    build_task_to_patches_index,
)
from spec_manager.refinement.workspace import WorkspaceManager
from spec_manager.schemas.edge_list import EdgeListSchema, EdgeSchema, read_edge_list_json
from spec_manager.schemas.spec_indexes import DecisionsIndex, SpecIndex
from spec_manager.schemas.task_status import read_task_implementation_status_json
from spec_manager.schemas.tasks import read_task_index_json, read_task_json

logger = logging.getLogger(__name__)

_TRACE_INDEX_BUILDERS: dict[str, Any] = {
    "atom_to_section": build_atom_to_section_index,
    "section_to_spec_elements": build_section_to_spec_elements_index,
    "spec_element_to_tasks": build_spec_element_to_tasks_index,
    "task_to_patches": build_task_to_patches_index,
}


def generate_coverage_report(manager: WorkspaceManager) -> str:
    """Generate coverage report markdown and write to reports/coverage.md."""
    atom_to_section = _load_trace_index(manager, "atom_to_section")
    section_to_spec_elements = _load_trace_index(manager, "section_to_spec_elements")
    _load_trace_index(manager, "spec_element_to_tasks")

    total_sections = _count_total_sections(manager)
    referenced_sections = (
        len({str(section_id) for section_id in section_to_spec_elements})
        if isinstance(section_to_spec_elements, dict)
        else 0
    )

    def format_ratio(numerator: int, denominator: int) -> str:
        if denominator <= 0:
            return "n/a"
        return f"{numerator / denominator:.2%}"

    library_rows: list[list[Any]] = []
    libraries_dir = manager.structure.libraries_dir
    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest,
        manager.structure.spec_snapshot_dir,
    )
    alias_map = build_section_alias_map(manager.state.section_manifest)
    sections_cache: dict[str, dict[str, Any] | None] = {}

    if libraries_dir.exists():
        for lib_dir in sorted(libraries_dir.iterdir(), key=lambda path: path.name):
            if not lib_dir.is_dir():
                continue
            spec_index_path = lib_dir / "spec_index.json"
            if not spec_index_path.exists():
                logger.warning("Missing spec index for library: %s", spec_index_path)
                continue
            try:
                payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read spec index %s: %s", spec_index_path, exc)
                continue
            try:
                spec_index = SpecIndex.model_validate(payload)
            except Exception as exc:
                logger.warning("Spec index validation failed for %s: %s", spec_index_path, exc)
                continue

            sections_cited: set[str] = set()
            for element in spec_index.elements:
                for citation in element.citations:
                    parsed = parse_evidence_pointer(citation)
                    if not parsed:
                        logger.warning(
                            "Unable to parse citation %r for %s", citation, element.element_id
                        )
                        continue
                    file_ref = parsed.get("file_ref", "")
                    section_ref = parsed.get("section_ref", "")
                    if not section_ref:
                        continue
                    section_id = section_ref
                    if not SECTION_ID_RE.fullmatch(section_ref):
                        file_id = file_id_lookup.get(file_ref)
                        if not file_id:
                            logger.warning(
                                "Unresolved file reference %r for citation %r", file_ref, citation
                            )
                            continue
                        if file_id not in sections_cache:
                            sections_cache[file_id] = manager.read_file_sections(file_id)
                        resolved = resolve_section_reference(
                            section_ref,
                            file_id,
                            alias_map,
                            sections_cache[file_id],
                        )
                        if not resolved:
                            logger.warning(
                                "Unresolved section reference %r for %s",
                                section_ref,
                                element.element_id,
                            )
                            continue
                        section_id = resolved
                    sections_cited.add(section_id)

            library_rows.append(
                [
                    spec_index.lib_id,
                    len(spec_index.elements),
                    len(sections_cited),
                    format_ratio(len(sections_cited), len(spec_index.elements)),
                ]
            )
    else:
        logger.warning("Libraries directory missing: %s", libraries_dir)

    total_atoms = len(atom_to_section) if isinstance(atom_to_section, dict) else 0
    referenced_section_ids = (
        set(section_to_spec_elements.keys())
        if isinstance(section_to_spec_elements, dict)
        else set()
    )
    referenced_atoms = 0
    if isinstance(atom_to_section, dict):
        for payload in atom_to_section.values():
            if not isinstance(payload, dict):
                continue
            section_id = payload.get("section_id")
            if isinstance(section_id, str) and section_id in referenced_section_ids:
                referenced_atoms += 1

    timestamp = _format_timestamp()
    lines = [
        "# Coverage Report",
        "",
        f"- run_id: {manager.run_id}",
        f"- generated_at: {timestamp}",
        "",
        "## Section Coverage",
        _format_coverage_table(
            ["Total Sections", "Referenced Sections", "Coverage Ratio"],
            [
                [
                    total_sections,
                    referenced_sections,
                    format_ratio(referenced_sections, total_sections),
                ]
            ],
        ),
        "",
        "## Library Coverage",
        _format_coverage_table(
            ["Library", "Elements", "Sections Cited", "Coverage Ratio"],
            library_rows,
        ),
        "",
        "## Atom Coverage (Approximate)",
        _format_coverage_table(
            ["Total Atoms", "Referenced Atoms", "Coverage Ratio"],
            [[total_atoms, referenced_atoms, format_ratio(referenced_atoms, total_atoms)]],
        ),
        "",
        "## Trace Indexes",
        "- workspace/indexes/atom_to_section.json",
        "- workspace/indexes/section_to_spec_elements.json",
        "- workspace/indexes/spec_element_to_tasks.json",
        "",
    ]

    content = "\n".join(lines)
    reports_dir = manager.structure.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "coverage.md"
    report_path.write_text(content, encoding="utf-8")
    logger.info("Wrote coverage report to %s", report_path)
    return content


def generate_compliance_report(manager: WorkspaceManager, *, run_qa: bool = True) -> str:
    """Generate compliance report markdown and write to reports/compliance.md."""
    qa_results: dict[str, Any] | None = None
    qa_error: str | None = None
    if run_qa:
        try:
            qa_results = run_qa_suite(manager.run_id, force_init=False)
        except Exception as exc:
            logger.warning("QA suite failed: %s", exc)
            qa_error = str(exc)
    else:
        qa_results = _load_latest_qa_summary(manager.structure.audits_dir)

    cases_total = qa_results.get("cases_total") if isinstance(qa_results, dict) else None
    cases_passed = qa_results.get("cases_passed") if isinstance(qa_results, dict) else None
    cases_failed = qa_results.get("cases_failed") if isinstance(qa_results, dict) else None
    results = qa_results.get("results", []) if isinstance(qa_results, dict) else []

    libraries_dir = manager.structure.libraries_dir
    signature_counts: dict[str, dict[str, Any]] = {}
    total_bad_signatures = 0
    libraries_scanned = 0

    if libraries_dir.exists():
        for lib_dir in sorted(libraries_dir.iterdir(), key=lambda path: path.name):
            if not lib_dir.is_dir():
                continue
            libraries_scanned += 1
            combined_texts: list[str] = []

            spec_index_path = lib_dir / "spec_index.json"
            if spec_index_path.exists():
                try:
                    payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning("Failed to read spec index %s: %s", spec_index_path, exc)
                    payload = None
                if payload is not None:
                    try:
                        spec_index = SpecIndex.model_validate(payload)
                    except Exception as exc:
                        logger.warning(
                            "Spec index validation failed for %s: %s", spec_index_path, exc
                        )
                    else:
                        combined_texts.extend(
                            element.text for element in spec_index.elements if element.text
                        )
            else:
                logger.warning("Missing spec index for library: %s", spec_index_path)

            decisions_index_path = lib_dir / "decisions_index.json"
            if decisions_index_path.exists():
                try:
                    payload = json.loads(decisions_index_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "Failed to read decisions index %s: %s", decisions_index_path, exc
                    )
                    payload = None
                if payload is not None:
                    try:
                        decisions_index = DecisionsIndex.model_validate(payload)
                    except Exception as exc:
                        logger.warning(
                            "Decisions index validation failed for %s: %s",
                            decisions_index_path,
                            exc,
                        )
                    else:
                        for decision in decisions_index.decisions:
                            if decision.question:
                                combined_texts.append(decision.question)
                            if decision.context:
                                combined_texts.append(decision.context)
                            if decision.options:
                                combined_texts.extend(decision.options)
                            if decision.default:
                                combined_texts.append(decision.default)

            combined_text = "\n".join(text for text in combined_texts if text).strip()
            issues = scan_known_bad_signatures(combined_text)
            if not issues:
                continue
            for issue in issues:
                signature = str(issue.get("signature", "unknown"))
                message = str(issue.get("message", ""))
                entry = signature_counts.setdefault(
                    signature,
                    {"count": 0, "description": message},
                )
                entry["count"] += 1
                if not entry.get("description") and message:
                    entry["description"] = message
                total_bad_signatures += 1
    else:
        logger.warning("Libraries directory missing: %s", libraries_dir)

    def format_ratio(numerator: int | None, denominator: int | None) -> str:
        if numerator is None or denominator is None or denominator <= 0:
            return "n/a"
        return f"{numerator / denominator:.2%}"

    qa_pass_rate = (
        cases_passed / cases_total if isinstance(cases_passed, int) and cases_total else None
    )
    bad_signature_density = total_bad_signatures / libraries_scanned if libraries_scanned else None

    sorted_signatures = sorted(
        signature_counts.items(),
        key=lambda item: (-int(item[1].get("count", 0)), item[0]),
    )
    top_three = sorted_signatures[:3]

    lines = [
        "# Compliance Report",
        "",
        f"- run_id: {manager.run_id}",
        f"- generated_at: {_format_timestamp()}",
        "",
    ]

    if qa_error is not None:
        lines.extend(
            [
                "## QA Validation Results",
                "",
                f"**QA suite failed:** {qa_error}",
                "",
            ]
        )
    elif qa_results is not None:
        lines.extend(
            [
                "## QA Validation Results",
                _format_coverage_table(
                    ["Total Cases", "Passed", "Failed", "Pass Rate"],
                    [
                        [
                            cases_total or 0,
                            cases_passed or 0,
                            cases_failed or 0,
                            format_ratio(cases_passed, cases_total),
                        ]
                    ],
                ),
                "",
            ]
        )

        failed_cases = [item for item in results if item.get("passed") is False]
        if failed_cases:
            lines.append("### Failed Cases")
            for item in failed_cases:
                case_id = item.get("case_id", "unknown")
                summary = _extract_case_summary(item)
                lines.append(f"- {case_id}: {summary}")
            lines.append("")
        else:
            lines.extend(["### Failed Cases", "- None", ""])

    lines.append("## Bad Signature Detection")
    if signature_counts:
        signature_rows = [
            [signature, data.get("count", 0), data.get("description", "")]
            for signature, data in sorted_signatures
        ]
        lines.append(
            _format_coverage_table(
                ["Signature", "Count", "Description"],
                signature_rows,
            )
        )
    else:
        lines.append(
            _format_coverage_table(
                ["Signature", "Count", "Description"],
                [["(none)", 0, "No known bad signatures detected."]],
            )
        )

    if top_three:
        top_text = ", ".join(
            f"{signature} ({data.get('count', 0)})" for signature, data in top_three
        )
        lines.append("")
        lines.append(f"Top failures: {top_text}")

    lines.append("")
    lines.append("## Compliance Summary")

    status = "NEEDS ATTENTION"
    if qa_pass_rate is not None and qa_pass_rate > 0.8 and total_bad_signatures < 5:
        status = "PASS"

    lines.append(f"- overall_status: {status}")
    if qa_pass_rate is not None:
        lines.append(f"- qa_pass_rate: {qa_pass_rate:.2%}")
    else:
        lines.append("- qa_pass_rate: n/a")
    lines.append(f"- bad_signature_total: {total_bad_signatures}")
    if bad_signature_density is not None:
        lines.append(f"- bad_signature_density: {bad_signature_density:.2f}")
    else:
        lines.append("- bad_signature_density: n/a")
    lines.append("")
    lines.append("### Recommendations")

    if status == "PASS":
        lines.append("- No immediate remediation required.")
    else:
        if qa_error is not None:
            lines.append("- Investigate and fix the QA suite failure before assessing compliance.")
        elif qa_results is None:
            lines.append("- Run the QA suite to establish a compliance baseline.")
        elif cases_failed:
            lines.append("- Review failed QA case reports and address their findings.")
        if total_bad_signatures:
            lines.append("- Remove known bad signature patterns from library specs and decisions.")
        if not total_bad_signatures and (
            qa_error is not None or qa_results is None or cases_failed
        ):
            lines.append("- Re-run QA after updates to confirm improvements.")

    lines.append("")

    content = "\n".join(lines)
    reports_dir = manager.structure.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "compliance.md"
    report_path.write_text(content, encoding="utf-8")
    logger.info("Wrote compliance report to %s", report_path)
    return content


def _aggregate_task_status(tasks_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {
        "planned": 0,
        "in_progress": 0,
        "done": 0,
        "blocked": 0,
        "failed": 0,
    }
    if not tasks_dir.exists():
        logger.warning("Tasks directory missing: %s", tasks_dir)
        return counts

    for task_dir in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
        if not task_dir.is_dir():
            continue
        status_path = task_dir / "status.json"
        if not status_path.exists():
            counts["planned"] += 1
            continue
        try:
            status = read_task_implementation_status_json(status_path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read task status %s: %s", status_path, exc)
            counts["planned"] += 1
            continue
        except Exception as exc:
            logger.warning("Task status validation failed for %s: %s", status_path, exc)
            counts["planned"] += 1
            continue
        counts[status.status] = counts.get(status.status, 0) + 1

    return counts


def _find_uncovered_edges(
    edge_list: EdgeListSchema,
    element_to_tasks: dict[str, list[str]],
) -> list[EdgeSchema]:
    covered_elements = set(element_to_tasks.keys())
    uncovered: list[EdgeSchema] = []
    for edge in edge_list.edges:
        elements = [*edge.consumer_elements, *edge.provider_elements]
        if any(element_id in covered_elements for element_id in elements):
            continue
        uncovered.append(edge)
    return uncovered


def generate_drift_report(manager: WorkspaceManager) -> str:
    """Generate drift report markdown and write to reports/drift.md."""
    element_to_tasks = _load_trace_index(manager, "spec_element_to_tasks")
    task_to_patches = _load_trace_index(manager, "task_to_patches")

    if not isinstance(element_to_tasks, dict):
        logger.warning("Spec element-to-tasks index has unexpected payload.")
        element_to_tasks = {}
    if not isinstance(task_to_patches, dict):
        logger.warning("Task-to-patches index has unexpected payload.")
        task_to_patches = {}

    libraries_dir = manager.structure.libraries_dir
    spec_elements: list[dict[str, str]] = []
    if libraries_dir.exists():
        for lib_dir in sorted(libraries_dir.iterdir(), key=lambda path: path.name):
            if not lib_dir.is_dir():
                continue
            spec_index_path = lib_dir / "spec_index.json"
            if not spec_index_path.exists():
                logger.warning("Missing spec index for library: %s", spec_index_path)
                continue
            try:
                payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read spec index %s: %s", spec_index_path, exc)
                continue
            try:
                spec_index = SpecIndex.model_validate(payload)
            except Exception as exc:
                logger.warning("Spec index validation failed for %s: %s", spec_index_path, exc)
                continue
            for element in spec_index.elements:
                spec_elements.append(
                    {
                        "element_id": element.element_id,
                        "lib_id": spec_index.lib_id,
                        "kind": element.kind,
                    }
                )
    else:
        logger.warning("Libraries directory missing: %s", libraries_dir)

    tasks_dir = manager.structure.tasks_dir
    covered_elements = set(element_to_tasks.keys())
    if tasks_dir.exists():
        for task_dir in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
            if not task_dir.is_dir():
                continue
            task_path = task_dir / "task.json"
            if not task_path.exists():
                continue
            try:
                task_detail = read_task_json(task_path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read task file %s: %s", task_path, exc)
                continue
            except Exception as exc:
                logger.warning("Task schema validation failed for %s: %s", task_path, exc)
                continue
            for element_id in task_detail.covers.elements:
                covered_elements.add(element_id)
                if isinstance(element_to_tasks, dict):
                    element_to_tasks.setdefault(element_id, [])
                    if task_detail.task_id not in element_to_tasks[element_id]:
                        element_to_tasks[element_id].append(task_detail.task_id)
    else:
        logger.warning("Tasks directory missing: %s", tasks_dir)

    uncovered_elements = [
        element for element in spec_elements if element["element_id"] not in covered_elements
    ]
    uncovered_rows = [
        [element["element_id"], element["lib_id"], element["kind"]]
        for element in sorted(
            uncovered_elements,
            key=lambda item: (item["lib_id"], item["element_id"], item["kind"]),
        )
    ]
    if not uncovered_rows:
        uncovered_rows = [["(none)", "-", "-"]]

    task_status_counts = _aggregate_task_status(tasks_dir)
    status_order = ["planned", "in_progress", "done", "blocked", "failed"]
    task_status_rows = [[status, task_status_counts.get(status, 0)] for status in status_order]

    failed_rows: list[list[str]] = []
    if tasks_dir.exists():
        for task_dir in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
            if not task_dir.is_dir():
                continue
            status_path = task_dir / "status.json"
            if not status_path.exists():
                continue
            try:
                raw_payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read task status payload %s: %s", status_path, exc)
                continue
            try:
                status = read_task_implementation_status_json(status_path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read task status %s: %s", status_path, exc)
                continue
            except Exception as exc:
                logger.warning("Task status validation failed for %s: %s", status_path, exc)
                continue
            if status.status not in {"failed", "blocked"}:
                continue

            detail = ""
            if isinstance(raw_payload, dict):
                for key in ("error", "notes", "message", "reason"):
                    value = raw_payload.get(key)
                    if isinstance(value, str) and value.strip():
                        detail = value.strip()
                        break
            if not detail and status.tests is not None:
                detail = f"tests exit_code={status.tests.exit_code}"
            if not detail and status.audit is not None:
                detail = f"audit {status.audit.verdict} (issues={status.audit.issues})"
            if not detail:
                detail = "No details available."

            failed_rows.append([status.task_id, status.status, detail])
    if not failed_rows:
        failed_rows = [["(none)", "-", "No failed or blocked tasks found."]]

    edge_list_path = manager.structure.indexes_dir / "edge_list.json"
    edge_list: EdgeListSchema | None = None
    if edge_list_path.exists():
        try:
            edge_list = read_edge_list_json(edge_list_path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read edge list %s: %s", edge_list_path, exc)
        except Exception as exc:
            logger.warning("Edge list validation failed for %s: %s", edge_list_path, exc)
    else:
        logger.warning("Edge list missing: %s", edge_list_path)

    uncovered_edge_rows: list[list[str]] = []
    uncovered_edges: list[EdgeSchema] = []
    if edge_list is not None:
        uncovered_edges = _find_uncovered_edges(edge_list, element_to_tasks)
        uncovered_edge_rows = [
            [
                edge.edge_id,
                edge.consumer_lib,
                edge.provider_lib,
                edge.kind,
            ]
            for edge in uncovered_edges
        ]
        if not uncovered_edge_rows:
            uncovered_edge_rows = [["(none)", "-", "-", "-"]]

    failed_or_blocked_count = sum(1 for row in failed_rows if row[0] != "(none)")
    uncovered_edge_count = len(uncovered_edges) if edge_list is not None else 0
    uncovered_element_count = sum(1 for row in uncovered_rows if row[0] != "(none)")

    overall_status = "NEEDS ATTENTION"
    if not uncovered_element_count and not failed_or_blocked_count and not uncovered_edge_count:
        overall_status = "OK"

    lines = [
        "# Drift Report",
        "",
        f"- run_id: {manager.run_id}",
        f"- generated_at: {_format_timestamp()}",
        "",
        "## Uncovered Spec Elements",
        _format_coverage_table(["Element ID", "Library", "Kind"], uncovered_rows),
        "",
        "## Task Status Summary",
        _format_coverage_table(["Status", "Count"], task_status_rows),
        "",
        "## Failed/Blocked Tasks",
        _format_coverage_table(["Task ID", "Status", "Details"], failed_rows),
        "",
    ]

    if edge_list is not None:
        lines.extend(
            [
                "## Uncovered Interface Edges",
                _format_coverage_table(
                    ["Edge ID", "Consumer Library", "Provider Library", "Kind"],
                    uncovered_edge_rows,
                ),
                "",
            ]
        )

    artifacts: list[str] = [
        "../reports/coverage.md",
        "../reports/compliance.md",
        "../workspace/indexes/trace_index.json",
    ]

    if edge_list_path.exists():
        artifacts.append("../workspace/indexes/edge_list.json")

    task_index_path = tasks_dir / "task_index.json"
    if task_index_path.exists():
        artifacts.append("../tasks/task_index.json")

    lines.append("## Artifacts")
    for artifact in artifacts:
        lines.append(f"- {artifact}")
    lines.append("")

    lines.extend(
        [
            "## Drift Summary",
            f"- overall_status: {overall_status}",
            f"- uncovered_elements: {uncovered_element_count}",
            f"- failed_or_blocked_tasks: {failed_or_blocked_count}",
            f"- uncovered_edges: {uncovered_edge_count if edge_list is not None else 'n/a'}",
            f"- tasks_with_patches: {len(task_to_patches)}",
            "",
            "### Recommendations",
        ]
    )

    if overall_status == "OK":
        lines.append("- No immediate remediation required.")
    else:
        if uncovered_element_count:
            lines.append("- Create tasks to cover uncovered spec elements.")
        if failed_or_blocked_count:
            lines.append("- Resolve failed or blocked tasks and re-run implementation checks.")
        if edge_list is not None and uncovered_edge_count:
            lines.append("- Define tasks that cover uncovered interface edges.")
        if not (uncovered_element_count or failed_or_blocked_count or uncovered_edge_count):
            lines.append("- Review drift inputs and rerun reporting.")

    lines.append("")

    content = "\n".join(lines)
    reports_dir = manager.structure.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "drift.md"
    report_path.write_text(content, encoding="utf-8")
    logger.info("Wrote drift report to %s", report_path)
    return content


def generate_run_audit(manager: WorkspaceManager) -> str:
    """Generate run audit markdown and write to audits/run_audit.md."""
    phase_rows: list[list[str]] = []

    def format_duration(started_at: str | None, completed_at: str | None) -> str:
        if not started_at or not completed_at:
            return "n/a"
        try:
            started = datetime.fromisoformat(started_at)
            completed = datetime.fromisoformat(completed_at)
        except ValueError:
            return "n/a"
        duration = (completed - started).total_seconds()
        if duration < 0:
            return "n/a"
        if duration >= 3600:
            hours = duration / 3600
            return f"{hours:.2f}h"
        if duration >= 60:
            minutes = duration / 60
            return f"{minutes:.2f}m"
        return f"{duration:.0f}s"

    for phase_name, result in manager.state.phases.items():
        status = result.status.value if hasattr(result.status, "value") else str(result.status)
        started_at = result.started_at or "n/a"
        completed_at = result.completed_at or "n/a"
        duration = format_duration(result.started_at, result.completed_at)
        phase_rows.append([phase_name, status, started_at, completed_at, duration])

    libraries_dir = manager.structure.libraries_dir
    library_rows: list[list[Any]] = []
    if libraries_dir.exists():
        for lib_dir in sorted(libraries_dir.iterdir(), key=lambda path: path.name):
            if not lib_dir.is_dir():
                continue
            spec_index_path = lib_dir / "spec_index.json"
            decisions_index_path = lib_dir / "decisions_index.json"

            lib_id = lib_dir.name
            element_count = 0
            open_decisions = 0

            if spec_index_path.exists():
                try:
                    payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning("Failed to read spec index %s: %s", spec_index_path, exc)
                    payload = None
                if payload is not None:
                    try:
                        spec_index = SpecIndex.model_validate(payload)
                    except Exception as exc:
                        logger.warning(
                            "Spec index validation failed for %s: %s", spec_index_path, exc
                        )
                    else:
                        lib_id = spec_index.lib_id
                        element_count = len(spec_index.elements)
            else:
                logger.warning("Missing spec index for library: %s", spec_index_path)

            if decisions_index_path.exists():
                try:
                    payload = json.loads(decisions_index_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "Failed to read decisions index %s: %s", decisions_index_path, exc
                    )
                    payload = None
                if payload is not None:
                    try:
                        decisions_index = DecisionsIndex.model_validate(payload)
                    except Exception as exc:
                        logger.warning(
                            "Decisions index validation failed for %s: %s",
                            decisions_index_path,
                            exc,
                        )
                    else:
                        open_decisions = sum(
                            1
                            for decision in decisions_index.decisions
                            if decision.status == "open" or not decision.default
                        )

            library_rows.append([lib_id, element_count, open_decisions])
    else:
        logger.warning("Libraries directory missing: %s", libraries_dir)

    task_status_counts = {
        "planned": 0,
        "in_progress": 0,
        "done": 0,
        "blocked": 0,
        "failed": 0,
    }
    task_index_path = manager.structure.tasks_dir / "task_index.json"
    task_ids: list[str] = []
    if task_index_path.exists():
        try:
            task_index = read_task_index_json(task_index_path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read task index %s: %s", task_index_path, exc)
        except Exception as exc:
            logger.warning("Task index validation failed for %s: %s", task_index_path, exc)
        else:
            task_ids = [entry.task_id for entry in task_index.tasks]
    else:
        logger.warning("Task index missing: %s", task_index_path)

    if task_ids:
        for task_id in task_ids:
            status_path = manager.structure.tasks_dir / task_id / "status.json"
            if not status_path.exists():
                task_status_counts["planned"] += 1
                continue
            try:
                status = read_task_implementation_status_json(status_path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read task status %s: %s", status_path, exc)
                task_status_counts["planned"] += 1
                continue
            except Exception as exc:
                logger.warning("Task status validation failed for %s: %s", status_path, exc)
                task_status_counts["planned"] += 1
                continue
            task_status_counts[status.status] = task_status_counts.get(status.status, 0) + 1
    else:
        task_status_counts = _aggregate_task_status(manager.structure.tasks_dir)

    task_status_rows = [
        [status, task_status_counts.get(status, 0)]
        for status in ["planned", "in_progress", "done", "blocked", "failed"]
    ]

    current_phase = (
        manager.state.current_phase.value
        if hasattr(manager.state.current_phase, "value")
        else str(manager.state.current_phase)
    )

    lines = [
        "# Run Audit",
        "",
        f"- run_id: {manager.run_id}",
        f"- generated_at: {_format_timestamp()}",
        f"- current_phase: {current_phase}",
        f"- mode: {manager.state.mode}",
        "",
        "## Phase Status",
        _format_coverage_table(
            ["Phase", "Status", "Started At", "Completed At", "Duration"],
            phase_rows,
        ),
        "",
        "## Library Summary",
        _format_coverage_table(
            ["Library", "Elements", "Open Decisions"],
            library_rows if library_rows else [["(none)", 0, 0]],
        ),
        "",
        "## Task Summary",
        _format_coverage_table(["Status", "Count"], task_status_rows),
        "",
        "## Artifacts",
    ]

    artifacts: list[str] = [
        "../reports/coverage.md",
        "../reports/compliance.md",
        "../reports/drift.md",
        "../workspace/indexes/trace_index.json",
    ]

    edge_list_path = manager.structure.indexes_dir / "edge_list.json"
    if edge_list_path.exists():
        artifacts.append("../workspace/indexes/edge_list.json")

    interface_index_path = manager.structure.indexes_dir / "interface_index.json"
    if interface_index_path.exists():
        artifacts.append("../workspace/indexes/interface_index.json")

    if task_index_path.exists():
        artifacts.append("../tasks/task_index.json")

    for artifact in artifacts:
        lines.append(f"- {artifact}")

    lines.append("")

    content = "\n".join(lines)
    audits_dir = manager.structure.audits_dir
    audits_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audits_dir / "run_audit.md"
    audit_path.write_text(content, encoding="utf-8")
    logger.info("Wrote run audit to %s", audit_path)
    return content


def _load_trace_index(manager: WorkspaceManager, index_name: str) -> dict[str, Any]:
    path = manager.structure.indexes_dir / f"{index_name}.json"
    if not path.exists():
        logger.warning("Trace index missing: %s", path)
        builder = _TRACE_INDEX_BUILDERS.get(index_name)
        if builder is None:
            return {}
        try:
            return builder(manager)
        except Exception as exc:
            logger.warning("Failed to build trace index %s: %s", index_name, exc)
            return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read trace index %s: %s", path, exc)
        return {}
    if not isinstance(payload, dict):
        logger.warning("Trace index %s has unexpected payload", path)
        return {}
    return payload


def _count_total_sections(manager: WorkspaceManager) -> int:
    section_ids = {
        section_id
        for sections in manager.state.section_manifest.values()
        for section_id in sections
        if isinstance(section_id, str)
    }
    return len(section_ids)


def _format_coverage_table(headers: list[str], rows: list[list[Any]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    row_lines = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header_line, separator, *row_lines])


def _format_timestamp() -> str:
    return datetime.now().isoformat()


def _load_latest_qa_summary(audits_dir: Path) -> dict[str, Any] | None:
    qa_dir = audits_dir / "qa"
    if not qa_dir.exists():
        logger.warning("QA audits directory missing: %s", qa_dir)
        return None

    summary_paths: list[Path] = []
    for session_dir in qa_dir.iterdir():
        if not session_dir.is_dir():
            continue
        summary_path = session_dir / "suite_summary.json"
        if summary_path.exists():
            summary_paths.append(summary_path)

    if not summary_paths:
        logger.warning("No QA suite summaries found under: %s", qa_dir)
        return None

    summary_paths.sort(key=lambda path: path.parent.name)
    latest = summary_paths[-1]
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read QA summary %s: %s", latest, exc)
        return None


def _extract_case_summary(result: dict[str, Any]) -> str:
    summary = str(result.get("summary", "")).strip()
    if summary:
        return summary

    report_path = result.get("report_path")
    if not isinstance(report_path, str) or not report_path:
        return "No summary available"

    path = Path(report_path)
    if not path.exists():
        return f"Report not found: {report_path}"

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read QA report %s: %s", path, exc)
        return "No summary available"

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- judge_summary:"):
            return stripped.split(":", 1)[1].strip() or "No summary available"

    return f"See report: {report_path}"


def generate_analysis_report(manager: WorkspaceManager) -> str:
    """Generate analysis file report from algorithmic/architectural layers.

    Reads the pre-generated analysis JSON artifact and renders it as
    a Markdown report with sections for:
    - Per-atom forward traces with projection types
    - Adjacency graph summary
    - Unimplemented atoms
    - Orphaned architecture
    - Data flow summaries
    - Aggregate statistics

    If no pre-generated analysis JSON exists, generates one on the fly
    using the workspace's spec snapshot and libraries directories.

    Args:
        manager: WorkspaceManager providing access to run artifacts.

    Returns:
        Markdown content string. Also writes to reports/analysis.md.
    """
    from spec_manager.analysis.generator import (
        generate_analysis_file,
        read_analysis_json,
        write_analysis_json,
    )
    from spec_manager.analysis.report_renderer import render_analysis_markdown

    analysis_json_path = manager.structure.analysis_dir / "analysis.json"

    if analysis_json_path.exists():
        try:
            analysis = read_analysis_json(analysis_json_path)
        except Exception as exc:
            logger.warning("Failed to read analysis JSON %s: %s", analysis_json_path, exc)
            analysis = None
    else:
        analysis = None

    if analysis is None:
        # Generate on the fly.
        algorithmic_dir = manager.structure.spec_snapshot_dir
        architectural_dir = manager.structure.libraries_dir
        analysis = generate_analysis_file(
            algorithmic_dir=algorithmic_dir,
            architectural_dir=architectural_dir,
            run_id=manager.run_id,
        )
        manager.structure.analysis_dir.mkdir(parents=True, exist_ok=True)
        write_analysis_json(analysis, analysis_json_path)
        logger.info("Generated analysis JSON: %s", analysis_json_path)

    content = render_analysis_markdown(analysis)

    reports_dir = manager.structure.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "analysis.md"
    report_path.write_text(content, encoding="utf-8")
    logger.info("Wrote analysis report to %s", report_path)

    return content


__all__ = [
    "generate_analysis_report",
    "generate_compliance_report",
    "generate_coverage_report",
    "generate_drift_report",
    "generate_run_audit",
]

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
from spec_manager.refinement.workspace import WorkspaceManager
from spec_manager.refinement.workflows.trace_indexes import (
    build_atom_to_section_index,
    build_section_to_spec_elements_index,
    build_spec_element_to_tasks_index,
)
from spec_manager.schemas.spec_indexes import DecisionsIndex, SpecIndex

logger = logging.getLogger(__name__)

_TRACE_INDEX_BUILDERS: dict[str, Any] = {
    "atom_to_section": build_atom_to_section_index,
    "section_to_spec_elements": build_section_to_spec_elements_index,
    "spec_element_to_tasks": build_spec_element_to_tasks_index,
}


def generate_coverage_report(manager: WorkspaceManager) -> str:
    """Generate coverage report markdown and write to reports/coverage.md."""
    atom_to_section = _load_trace_index(manager, "atom_to_section")
    section_to_spec_elements = _load_trace_index(manager, "section_to_spec_elements")
    _load_trace_index(manager, "spec_element_to_tasks")

    total_sections = _count_total_sections(manager)
    referenced_sections = (
        len({str(section_id) for section_id in section_to_spec_elements.keys()})
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
                                "Unresolved section reference %r for %s", section_ref, element.element_id
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
        set(section_to_spec_elements.keys()) if isinstance(section_to_spec_elements, dict) else set()
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
            [[total_sections, referenced_sections, format_ratio(referenced_sections, total_sections)]],
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
    bad_signature_density = (
        total_bad_signatures / libraries_scanned if libraries_scanned else None
    )

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
            lines.append(
                "- Remove known bad signature patterns from library specs and decisions."
            )
        if not total_bad_signatures and (qa_error is not None or qa_results is None or cases_failed):
            lines.append("- Re-run QA after updates to confirm improvements.")

    lines.append("")

    content = "\n".join(lines)
    reports_dir = manager.structure.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "compliance.md"
    report_path.write_text(content, encoding="utf-8")
    logger.info("Wrote compliance report to %s", report_path)
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


__all__ = [
    "generate_coverage_report",
    "generate_compliance_report",
]

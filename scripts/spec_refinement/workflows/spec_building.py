"""Spec building workflow for Phase 4 spec refinement."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.dev.agent_runner import AgentRunner
from scripts.spec_refinement.core.gap import Gap, GapEvidence, GapSynthesizer, format_gap_table
from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .formats import EVIDENCE_POINTER_RE, parse_gap_judge_output
from .progress import ProgressTracker

MAX_ITERATIONS_DEFAULT = 5
VALID_GAP_SEVERITIES = {"must", "should", "nice-to-have"}
SEVERITY_MAP = {"must": "error", "should": "warning", "nice-to-have": "info"}


def _extract_sections(content: str, level: int) -> dict[str, str]:
    pattern = re.compile(rf"^{'#' * level}\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections[title] = content[start:end].strip()
    return sections


def _extract_list_items(section_text: str) -> list[str]:
    items = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            items.append(stripped.lstrip("-* ").strip())
    return items


def _parse_charter(content: str) -> dict[str, Any]:
    sections = _extract_sections(content, level=2)
    return {
        "intent": sections.get("Intent", "").strip(),
        "boundaries": sections.get("Boundaries", "").strip(),
        "responsibilities": _extract_list_items(sections.get("Responsibilities", "")),
    }


def _build_spec_template(lib_id: str, charter: dict[str, Any]) -> str:
    lines = [
        f"# Library Spec: {lib_id}",
        "",
        "## Intent",
        charter.get("intent", ""),
        "",
        "## Boundaries",
        charter.get("boundaries", ""),
        "",
        "## Requirements",
        "<!-- Requirements will be added during integration -->",
        "",
        "## Constraints",
        "<!-- Constraints will be added during integration -->",
        "",
        "## Dependencies",
        "<!-- Dependencies will be added during integration -->",
        "",
        "## Decisions Needed",
        "<!-- Ambiguities/contradictions will be recorded here -->",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _initialize_spec(lib_dir: Path, charter_content: str, lib_id: str) -> Path:
    spec_path = lib_dir / "spec.md"
    if spec_path.exists() and spec_path.read_text(encoding="utf-8").strip():
        return spec_path
    charter = _parse_charter(charter_content)
    spec_path.write_text(_build_spec_template(lib_id, charter), encoding="utf-8")
    return spec_path


def _build_integration_prompt(
    lib_id: str,
    charter_content: str,
    spec_content: str,
    file_id: str,
    file_content: str,
    evidence_sections: list[str],
    gaps: list[Gap] | None = None,
) -> str:
    section_list = ", ".join(evidence_sections) if evidence_sections else "None"
    lines = [
        "Integrate the source file into the library spec.",
        "Preserve existing content; add missing details with citations [FILE_ID::SECTION].",
        "",
        f"Library ID: {lib_id}",
        "",
        "Library Charter:",
        charter_content.strip(),
        "",
        f"Evidence Sections: {section_list}",
        "",
        "Current Spec:",
        spec_content.strip(),
        "",
    ]
    if gaps:
        lines.extend(
            [
                "Focus on closing the following gaps:",
                format_gap_table(gaps),
                "",
            ]
        )
    lines.extend(
        [
            "Source File:",
            f"File ID: {file_id}",
            file_content.strip(),
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _build_gap_prompt(spec_content: str, file_id: str, file_content: str) -> str:
    lines = [
        "Review the spec against the source file and report gaps.",
        "Return JSON with keys: gaps, total_gaps, file_id.",
        "",
        "Spec:",
        spec_content.strip(),
        "",
        "Source File:",
        f"File ID: {file_id}",
        file_content.strip(),
    ]
    return "\n".join(lines).strip() + "\n"


def _validate_spec_citations(
    content: str, manager: WorkspaceManager, lib_id: str
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    pointer_matches = list(EVIDENCE_POINTER_RE.finditer(content))
    if not pointer_matches:
        issues.append(
            {
                "type": "missing_evidence_pointers",
                "lib_id": lib_id,
                "message": "No evidence pointers found.",
            }
        )
        return issues

    file_id_lookup: dict[str, str] = {}
    for file_id, path_str in manager.state.file_manifest.items():
        file_id_lookup[file_id] = file_id
        file_id_lookup[path_str] = file_id
        try:
            file_id_lookup[str(Path(path_str).resolve())] = file_id
        except OSError:
            continue

    for match in pointer_matches:
        file_ref = match.group(1).strip()
        section_ref = match.group(2).strip()
        resolved_file_id = file_id_lookup.get(file_ref)
        if resolved_file_id is None:
            issues.append(
                {
                    "type": "unknown_file_reference",
                    "lib_id": lib_id,
                    "pointer": match.group(0),
                    "message": f"Unknown file reference: {file_ref}",
                }
            )
            continue
        valid_sections = manager.state.section_manifest.get(resolved_file_id, [])
        if section_ref not in valid_sections:
            issues.append(
                {
                    "type": "unknown_section_reference",
                    "lib_id": lib_id,
                    "pointer": match.group(0),
                    "message": f"Unknown section reference: {section_ref}",
                }
            )

    sections = _extract_sections(content, level=2)
    for section_name in ("Requirements", "Constraints", "Dependencies"):
        section_text = sections.get(section_name, "")
        for line in section_text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("-", "*")):
                continue
            if not EVIDENCE_POINTER_RE.search(stripped):
                issues.append(
                    {
                        "type": "missing_citation",
                        "lib_id": lib_id,
                        "section": section_name,
                        "line": stripped,
                        "message": "Bullet missing evidence pointer.",
                    }
                )

    return issues


def _read_evidence_sources(lib_dir: Path) -> list[dict[str, Any]]:
    evidence_path = lib_dir / "evidence.json"
    if not evidence_path.exists():
        return []
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    sources = payload.get("sources", [])
    return sources if isinstance(sources, list) else []


def _normalize_evidence_sources(
    sources: list[dict[str, Any]],
) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = {}
    for source in sources:
        file_id = source.get("file_id")
        if not isinstance(file_id, str):
            continue
        sections = source.get("sections", [])
        if not isinstance(sections, list):
            sections = []
        merged.setdefault(file_id, set()).update(section for section in sections if section)
    return {file_id: sorted(sections) for file_id, sections in merged.items()}


def _update_decisions(lib_dir: Path, spec_content: str) -> None:
    sections = _extract_sections(spec_content, level=2)
    decisions_text = sections.get("Decisions Needed", "").strip()
    decisions_path = lib_dir / "decisions.md"
    if decisions_text:
        decisions_path.write_text(f"## Decisions Needed\n\n{decisions_text}\n", encoding="utf-8")
    else:
        decisions_path.write_text("", encoding="utf-8")


def _gap_signature(gaps: list[Gap]) -> tuple[str, ...]:
    return tuple(sorted(gap.id for gap in gaps if gap.status == "open"))


def _build_gaps_from_judge(
    lib_id: str,
    file_id: str,
    raw_gaps: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> list[GapEvidence]:
    evidence_list: list[GapEvidence] = []
    for gap_finding in raw_gaps:
        if not isinstance(gap_finding, dict):
            continue
        severity_raw = str(gap_finding.get("severity", "")).strip().lower()
        if severity_raw not in VALID_GAP_SEVERITIES:
            issues.append(
                {
                    "type": "invalid_gap_severity",
                    "lib_id": lib_id,
                    "file_id": file_id,
                    "severity": severity_raw,
                    "message": "Gap severity must be must/should/nice-to-have.",
                }
            )
            severity_raw = "nice-to-have"
        mapped_severity = SEVERITY_MAP[severity_raw]
        evidence_list.append(
            GapEvidence(
                invariant_family="content",
                description=gap_finding.get("missing_content", ""),
                details={
                    "source": gap_finding.get("source", file_id),
                    "derived_artifact_target": f"libraries/{lib_id}/spec.md",
                    "where_in_spec": gap_finding.get("where_in_spec", ""),
                    "severity": mapped_severity,
                    "reported_severity": severity_raw,
                    "gap_type": "missing_detail",
                },
                confidence=1.0,
                location=gap_finding.get("source", file_id),
                detector="chatgpt-library-spec-gap-judge",
            )
        )
    return evidence_list


def _build_library_spec(
    manager: WorkspaceManager,
    lib_dir: Path,
    config_path: Path,
    max_iterations: int,
) -> dict[str, Any]:
    lib_id = lib_dir.name
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    iterations = 0
    converged = False

    charter_path = lib_dir / "charter.md"
    if not charter_path.exists():
        return {
            "lib_id": lib_id,
            "errors": [{"lib_id": lib_id, "error": "Missing charter.md for library."}],
            "issues": [],
            "iterations": 0,
            "converged": False,
            "failed": True,
        }

    charter_content = charter_path.read_text(encoding="utf-8")
    spec_path = _initialize_spec(lib_dir, charter_content, lib_id)

    sources = _read_evidence_sources(lib_dir)
    evidence_map = _normalize_evidence_sources(sources)
    if not evidence_map:
        return {
            "lib_id": lib_id,
            "errors": [{"lib_id": lib_id, "error": "No evidence sources available for library."}],
            "issues": [],
            "iterations": 0,
            "converged": False,
            "failed": True,
        }

    existing_gaps = manager.read_library_gaps(lib_id)
    gap_history: list[tuple[str, ...]] = []

    for iteration in range(max_iterations):
        iterations += 1
        gap_focus = existing_gaps if iteration > 0 else None

        for file_id, sections in evidence_map.items():
            file_path = manager.get_file_path(file_id)
            if file_path is None or not file_path.exists():
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": "Source file not found.",
                    }
                )
                continue

            file_content = file_path.read_text(encoding="utf-8")
            current_spec = spec_path.read_text(encoding="utf-8")
            prompt = _build_integration_prompt(
                lib_id,
                charter_content,
                current_spec,
                file_id,
                file_content,
                sections,
                gaps=gap_focus,
            )
            runner = AgentRunner.from_agent_name(
                "glm-library-spec-integrator", config_path, prompt_chars=len(prompt)
            )

            try:
                output = runner.run(prompt)
            except RuntimeError as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Agent execution failed: {exc}",
                    }
                )
                continue

            if current_spec.strip() and current_spec.strip() not in output:
                issues.append(
                    {
                        "type": "non_monotonic_integration",
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "message": "Integrator output removed existing spec content.",
                    }
                )
                output = current_spec

            spec_path.write_text(output, encoding="utf-8")
            issues.extend(_validate_spec_citations(output, manager, lib_id))
            _update_decisions(lib_dir, output)

        spec_content = spec_path.read_text(encoding="utf-8")
        evidence_list: list[GapEvidence] = []

        for file_id in evidence_map:
            file_path = manager.get_file_path(file_id)
            if file_path is None or not file_path.exists():
                continue
            file_content = file_path.read_text(encoding="utf-8")
            prompt = _build_gap_prompt(spec_content, file_id, file_content)
            runner = AgentRunner.from_agent_name(
                "chatgpt-library-spec-gap-judge", config_path, prompt_chars=len(prompt)
            )
            try:
                output = runner.run(prompt)
            except RuntimeError as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Gap judge failed: {exc}",
                    }
                )
                continue

            try:
                data = parse_gap_judge_output(output)
            except Exception as exc:  # pragma: no cover - defensive logging
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Failed to parse gap output: {exc}",
                    }
                )
                continue

            raw_gaps = data.get("gaps", [])
            evidence_list.extend(_build_gaps_from_judge(lib_id, file_id, raw_gaps, issues))

        synthesizer = GapSynthesizer()
        new_gaps = synthesizer.cluster_evidence(evidence_list) if evidence_list else []
        existing_gaps = synthesizer.merge_gaps(existing_gaps, new_gaps)

        manager.write_library_gaps(lib_id, existing_gaps)

        if not new_gaps:
            existing_gaps = []
            manager.write_library_gaps(lib_id, existing_gaps)
            manager.record_gap_audit(Phase.SPEC_BUILDING, gaps=existing_gaps, converged=True)
            converged = True
            break

        manager.record_gap_audit(Phase.SPEC_BUILDING, gaps=existing_gaps, converged=False)

        signature = _gap_signature(existing_gaps)
        gap_history.append(signature)

    return {
        "lib_id": lib_id,
        "errors": errors,
        "issues": issues,
        "iterations": iterations,
        "converged": converged,
        "failed": not converged and existing_gaps,
    }


def build_specs(
    run_id: str, config_path: Path, max_iterations: int = MAX_ITERATIONS_DEFAULT
) -> dict[str, Any]:
    """Build library specs with audit-driven gap closure (Phase 4)."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before spec building.")

    expansion_status = manager.state.phases[Phase.EVIDENCE_EXPANSION.value].status
    if expansion_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Evidence expansion must be completed before spec building.")

    manager.start_phase(Phase.SPEC_BUILDING)

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [lib_dir for lib_dir in sorted(libraries_dir.iterdir()) if lib_dir.is_dir()]

    tracker = ProgressTracker(
        total=len(lib_dirs),
        description="Building library specs",
        manager=manager,
    )

    libraries_built = 0
    total_iterations = 0
    converged_count = 0
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    failed_libraries = 0

    for lib_dir in lib_dirs:
        result = _build_library_spec(manager, lib_dir, config_path, max_iterations)
        total_iterations += result.get("iterations", 0)
        errors.extend(result.get("errors", []))
        issues.extend(result.get("issues", []))
        if result.get("failed"):
            failed_libraries += 1
        else:
            libraries_built += 1
            if result.get("converged"):
                converged_count += 1
        tracker.update(status=lib_dir.name)

    tracker.finish()

    phase_result = manager.state.phases[Phase.SPEC_BUILDING.value]
    phase_result.issues = errors + issues

    total_libs = len(lib_dirs)
    failure_ratio = (failed_libraries / total_libs) if total_libs else 0
    outputs = {
        "libraries_built": libraries_built,
        "total_iterations": total_iterations,
        "converged_count": converged_count,
    }

    if total_libs > 0 and failure_ratio > 0.5:
        manager.fail_phase(Phase.SPEC_BUILDING, error="Too many library failures")
    else:
        manager.complete_phase(Phase.SPEC_BUILDING, outputs=outputs)

    return {
        "libraries_built": libraries_built,
        "total_iterations": total_iterations,
        "converged_count": converged_count,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }

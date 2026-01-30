"""Architecture workflow for Phase 6 spec refinement."""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .agent_utils import run_agent
from .formats import (
    normalize_compound_pointers,
    parse_architecture_mapping,
    parse_architecture_proposal,
    parse_architecture_selection,
)
from .progress import ProgressTracker

# Only treat bracketed text containing a `::` segment separator as a citation.
ARCH_CITATION_RE = re.compile(r"\[([^\[\]]*?::[^\[\]]*?)\]")


def propose_architectures(run_id: str) -> dict[str, Any]:
    """Propose architecture candidates for Phase 6."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    sublibrary_status = manager.state.phases[Phase.SUBLIBRARY_DETECTION.value].status
    if sublibrary_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Sub-library detection must be completed before architecture proposal.")

    manager.start_phase(Phase.ARCHITECTURE_PROPOSAL)

    libraries = manager.get_all_libraries_recursive()
    if not libraries:
        manager.fail_phase(Phase.ARCHITECTURE_PROPOSAL, error="No libraries found for proposal.")
        return {"candidates_created": 0, "issues": [{"type": "no_libraries"}]}

    lib_charters: dict[str, str] = {}
    lib_specs: dict[str, str] = {}
    for lib_id, lib_dir in libraries.items():
        charter_path = lib_dir / "charter.md"
        spec_path = lib_dir / "spec.md"
        if charter_path.exists():
            lib_charters[lib_id] = charter_path.read_text(encoding="utf-8")
        if spec_path.exists():
            lib_specs[lib_id] = spec_path.read_text(encoding="utf-8")

    constraints = _extract_constraints_from_specs(lib_specs)
    prompt = _build_architecture_proposal_prompt(lib_charters, lib_specs, constraints)

    try:
        output = run_agent(
            agent_name="opus-architecture-proposer",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        manager.fail_phase(Phase.ARCHITECTURE_PROPOSAL, error=f"Agent execution failed: {exc}")
        return {"candidates_created": 0, "issues": [{"type": "agent_error", "error": str(exc)}]}

    try:
        candidates = _parse_architecture_candidates(output)
    except Exception as exc:
        manager.fail_phase(Phase.ARCHITECTURE_PROPOSAL, error=f"Failed to parse output: {exc}")
        return {"candidates_created": 0, "issues": [{"type": "parse_error", "error": str(exc)}]}

    if not candidates:
        manager.fail_phase(
            Phase.ARCHITECTURE_PROPOSAL, error="No architecture candidates returned."
        )
        return {"candidates_created": 0, "issues": [{"type": "no_candidates"}]}

    candidates_dir = manager.structure.architecture_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    tracker = ProgressTracker(
        total=len(candidates),
        description="Writing architecture candidates",
        manager=manager,
    )

    for candidate in candidates:
        arch_id = str(candidate.get("arch_id", "unknown"))
        candidate_path = candidates_dir / _candidate_filename(arch_id)
        candidate_path.write_text(_format_architecture_candidate(candidate), encoding="utf-8")
        tracker.update(status=arch_id)

    tracker.finish()

    phase_result = manager.state.phases[Phase.ARCHITECTURE_PROPOSAL.value]
    phase_result.issues = []

    outputs = {"candidates_count": len(candidates)}
    manager.complete_phase(Phase.ARCHITECTURE_PROPOSAL, outputs=outputs)

    return {"candidates_created": len(candidates), "issues": []}


def select_architecture(run_id: str) -> dict[str, Any]:
    """Select the best architecture candidate for Phase 6."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    proposal_status = manager.state.phases[Phase.ARCHITECTURE_PROPOSAL.value].status
    if proposal_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Architecture proposal must be completed before selection.")

    manager.start_phase(Phase.ARCHITECTURE_SELECTION)

    candidates_dir = manager.structure.architecture_dir / "candidates"
    if not candidates_dir.exists():
        manager.fail_phase(Phase.ARCHITECTURE_SELECTION, error="No candidates directory found.")
        return {"selected_arch_id": None, "rejected_count": 0}

    candidate_files = sorted(candidates_dir.glob("arch_*.md"))
    if not candidate_files:
        manager.fail_phase(Phase.ARCHITECTURE_SELECTION, error="No candidate files found.")
        return {"selected_arch_id": None, "rejected_count": 0}

    candidates: dict[str, str] = {}
    for candidate_path in candidate_files:
        candidates[candidate_path.stem] = candidate_path.read_text(encoding="utf-8")

    libraries = manager.get_all_libraries_recursive()
    lib_specs: dict[str, str] = {}
    for lib_id, lib_dir in libraries.items():
        spec_path = lib_dir / "spec.md"
        if spec_path.exists():
            lib_specs[lib_id] = spec_path.read_text(encoding="utf-8")

    prompt = _build_architecture_selection_prompt(candidates, lib_specs)
    try:
        output = run_agent(
            agent_name="chatgpt-architecture-tradeoff-judge",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        manager.fail_phase(Phase.ARCHITECTURE_SELECTION, error=f"Agent execution failed: {exc}")
        return {"selected_arch_id": None, "rejected_count": 0}

    try:
        selection = _parse_architecture_selection(output)
    except Exception as exc:
        manager.fail_phase(Phase.ARCHITECTURE_SELECTION, error=f"Failed to parse output: {exc}")
        return {"selected_arch_id": None, "rejected_count": 0}

    selected_arch_id = selection.get("selected_arch_id")
    if selected_arch_id is None:
        manager.fail_phase(Phase.ARCHITECTURE_SELECTION, error="No architecture selected.")
        return {"selected_arch_id": None, "rejected_count": 0}

    if selected_arch_id not in candidates:
        manager.fail_phase(
            Phase.ARCHITECTURE_SELECTION,
            error=f"Selected architecture {selected_arch_id} not found in candidates.",
        )
        return {"selected_arch_id": None, "rejected_count": 0}

    rationale = str(selection.get("rationale", "")).strip()
    issues = _validate_architecture_citations(rationale, manager)

    phase_result = manager.state.phases[Phase.ARCHITECTURE_SELECTION.value]
    phase_result.issues = issues

    if issues:
        # Do not leave behind non-compliant artifacts from a failed validation.
        selected_path = manager.structure.architecture_dir / "selected.md"
        rejected_path = manager.structure.architecture_dir / "rejected.md"
        with contextlib.suppress(OSError):
            selected_path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            rejected_path.unlink(missing_ok=True)

        manager.fail_phase(
            Phase.ARCHITECTURE_SELECTION,
            error=f"Architecture selection citation validation failed ({len(issues)} issue(s)).",
        )
        rejected = selection.get("rejected_architectures", [])
        return {"selected_arch_id": selected_arch_id, "rejected_count": len(rejected)}

    selected_path = manager.structure.architecture_dir / "selected.md"
    selected_path.write_text(
        _format_architecture_selection(selected_arch_id, selection, candidates[selected_arch_id]),
        encoding="utf-8",
    )

    rejected_path = manager.structure.architecture_dir / "rejected.md"
    rejected_path.write_text(_format_architecture_rejections(selection), encoding="utf-8")

    outputs = {"selected_arch_id": selected_arch_id}
    manager.complete_phase(Phase.ARCHITECTURE_SELECTION, outputs=outputs)

    rejected = selection.get("rejected_architectures", [])
    return {"selected_arch_id": selected_arch_id, "rejected_count": len(rejected)}


def map_libraries_to_architecture(run_id: str) -> dict[str, Any]:
    """Map libraries to the selected architecture components."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    selection_status = manager.state.phases[Phase.ARCHITECTURE_SELECTION.value].status
    if selection_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Architecture selection must be completed before mapping.")

    manager.start_phase(Phase.ARCHITECTURE_MAPPING)

    selected_path = manager.structure.architecture_dir / "selected.md"
    if not selected_path.exists():
        manager.fail_phase(Phase.ARCHITECTURE_MAPPING, error="Selected architecture not found.")
        return {"libraries_mapped": 0, "unmapped_libraries": [], "issues": []}

    selected_content = selected_path.read_text(encoding="utf-8")

    libraries = manager.get_all_libraries_recursive()
    lib_specs: dict[str, str] = {}
    lib_charters: dict[str, str] = {}
    for lib_id, lib_dir in libraries.items():
        spec_path = lib_dir / "spec.md"
        charter_path = lib_dir / "charter.md"
        if spec_path.exists():
            lib_specs[lib_id] = spec_path.read_text(encoding="utf-8")
        if charter_path.exists():
            lib_charters[lib_id] = charter_path.read_text(encoding="utf-8")

    prompt = _build_architecture_mapping_prompt(selected_content, lib_charters, lib_specs)
    try:
        output = run_agent(
            agent_name="glm-architecture-mapper",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        manager.fail_phase(Phase.ARCHITECTURE_MAPPING, error=f"Agent execution failed: {exc}")
        return {"libraries_mapped": 0, "unmapped_libraries": [], "issues": []}

    output = normalize_compound_pointers(output)

    try:
        mapping = parse_architecture_mapping(output)
    except Exception as exc:
        manager.fail_phase(Phase.ARCHITECTURE_MAPPING, error=f"Failed to parse output: {exc}")
        return {"libraries_mapped": 0, "unmapped_libraries": [], "issues": []}

    component_mappings: dict[str, list[str]] = mapping.get("component_mappings", {})
    component_lines: dict[str, list[str]] = mapping.get("component_lines", {})

    all_lib_ids = set(libraries.keys())
    mapped_libs: set[str] = set()
    for libs in component_mappings.values():
        mapped_libs.update(libs)
    unmapped = sorted(all_lib_ids - mapped_libs)

    issues: list[dict[str, Any]] = []

    if unmapped:
        issues.append(
            {
                "type": "unmapped_libraries",
                "libraries": unmapped,
                "message": "Some libraries were not mapped to any component.",
            }
        )

    missing_citations = _find_missing_mapping_citations(component_lines)
    if missing_citations:
        issues.extend(missing_citations)

    dependencies = mapping.get("dependencies", [])
    if not dependencies:
        issues.append(
            {
                "type": "missing_cross_component_dependencies",
                "message": "No cross-component dependencies documented.",
            }
        )

    citation_issues = _validate_architecture_citations(output, manager)
    issues.extend(citation_issues)

    phase_result = manager.state.phases[Phase.ARCHITECTURE_MAPPING.value]
    phase_result.issues = issues

    if issues:
        # Do not leave behind non-compliant artifacts from a failed validation.
        mapping_path = manager.structure.architecture_dir / "mapping.md"
        with contextlib.suppress(OSError):
            mapping_path.unlink(missing_ok=True)

        manager.fail_phase(
            Phase.ARCHITECTURE_MAPPING,
            error=f"Architecture mapping validation failed ({len(issues)} issue(s)).",
        )
        return {
            "libraries_mapped": len(mapped_libs),
            "unmapped_libraries": unmapped,
            "issues": issues,
        }

    mapping_path = manager.structure.architecture_dir / "mapping.md"
    mapping_path.write_text(output.strip() + "\n", encoding="utf-8")

    outputs = {
        "libraries_mapped": len(mapped_libs),
        "components_count": len(component_mappings),
    }
    manager.complete_phase(Phase.ARCHITECTURE_MAPPING, outputs=outputs)

    return {
        "libraries_mapped": len(mapped_libs),
        "unmapped_libraries": unmapped,
        "issues": issues,
    }


def _extract_constraints_from_specs(lib_specs: dict[str, str]) -> list[str]:
    """Extract constraint-related sections from library specs."""
    keywords = (
        "constraint",
        "requirement",
        "performance",
        "latency",
        "throughput",
        "security",
        "compliance",
        "availability",
        "scalability",
    )
    constraints: list[str] = []
    for lib_id, content in lib_specs.items():
        sections = _extract_markdown_sections(content)
        for title, body in sections.items():
            title_lower = title.lower()
            if any(key in title_lower for key in keywords):
                snippet = _collapse_whitespace(body)
                if snippet:
                    constraints.append(f"{lib_id}::{title}: {snippet[:500]}")
    return constraints


def _parse_architecture_candidates(output: str) -> list[dict[str, Any]]:
    payload = _extract_json_payload(output)
    candidates = parse_architecture_proposal(payload)
    return [asdict(candidate) for candidate in candidates]


def _parse_architecture_selection(output: str) -> dict[str, Any]:
    payload = _extract_json_payload(output)
    return parse_architecture_selection(payload)


def _validate_architecture_citations(
    content: str, manager: WorkspaceManager
) -> list[dict[str, Any]]:
    """Validate architecture citations like [lib_id::spec.md::SECTION]."""
    issues: list[dict[str, Any]] = []
    libraries = manager.get_all_libraries_recursive()
    lib_lookup = {lib_id: lib_dir for lib_id, lib_dir in libraries.items()}
    matches = list(ARCH_CITATION_RE.finditer(content))
    if not matches:
        issues.append(
            {
                "type": "missing_citations",
                "message": "No architecture citations found.",
            }
        )
        return issues

    for match in matches:
        raw = match.group(1).strip()
        parts = [part.strip() for part in raw.split("::") if part.strip()]
        if len(parts) < 2:
            issues.append(
                {
                    "type": "invalid_citation",
                    "pointer": match.group(0),
                    "message": "Citation does not include lib_id and file.",
                }
            )
            continue

        lib_id, file_name = parts[0], parts[1]
        section = parts[2] if len(parts) > 2 else None

        lib_dir = lib_lookup.get(lib_id)
        if lib_dir is None:
            issues.append(
                {
                    "type": "unknown_library",
                    "pointer": match.group(0),
                    "message": f"Unknown library reference: {lib_id}",
                }
            )
            continue

        file_path = lib_dir / file_name
        if not file_path.exists():
            issues.append(
                {
                    "type": "missing_library_file",
                    "pointer": match.group(0),
                    "message": f"Missing library file: {file_name}",
                }
            )
            continue

        if section:
            labels = _extract_section_labels(file_path.read_text(encoding="utf-8"))
            if section not in labels:
                issues.append(
                    {
                        "type": "unknown_section_reference",
                        "pointer": match.group(0),
                        "message": f"Unknown section reference: {section}",
                    }
                )

    return issues


def _format_architecture_candidate(candidate: dict[str, Any]) -> str:
    lines = [f"# Architecture Candidate: {candidate.get('arch_id', 'unknown')}", ""]
    lines.extend(["## Pattern", str(candidate.get("pattern", "")).strip(), ""])
    lines.extend(["## Description", str(candidate.get("description", "")).strip(), ""])

    lines.append("## Components")
    components = candidate.get("components", [])
    if components:
        for component in components:
            if isinstance(component, dict):
                name = component.get("name") or component.get("component") or "Unnamed"
                responsibilities = component.get("responsibilities") or component.get(
                    "responsibility"
                )
                if isinstance(responsibilities, list):
                    resp_text = "; ".join(str(item) for item in responsibilities if item)
                elif responsibilities:
                    resp_text = str(responsibilities)
                else:
                    resp_text = ""
                if resp_text:
                    lines.append(f"- {name}: {resp_text}")
                else:
                    lines.append(f"- {name}")
            else:
                lines.append(f"- {component}")
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Communication", str(candidate.get("communication", "")).strip(), ""])
    lines.extend(["## Deployment", str(candidate.get("deployment", "")).strip(), ""])

    lines.append("## Tradeoffs")
    tradeoffs = candidate.get("tradeoffs", {})
    advantages = tradeoffs.get("advantages", []) if isinstance(tradeoffs, dict) else []
    disadvantages = tradeoffs.get("disadvantages", []) if isinstance(tradeoffs, dict) else []
    lines.append("### Advantages")
    if advantages:
        for item in advantages:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("### Disadvantages")
    if disadvantages:
        for item in disadvantages:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Citations")
    citations = candidate.get("citations", [])
    if citations:
        for citation in citations:
            lines.append(f"- {citation}")
    else:
        lines.append("- None")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_architecture_proposal_prompt(
    lib_charters: dict[str, str], lib_specs: dict[str, str], constraints: list[str]
) -> str:
    lines = [
        "Generate 3-5 architecture candidates for Phase 6.",
        "Return a JSON array of objects.",
        (
            "Each object must include: arch_id, pattern, description, components, "
            "communication, deployment, citations, tradeoffs."
        ),
        "Components should be a list of objects with name and responsibilities.",
        "Citations MUST use library pointers only:",
        "- [lib_###::charter.md]",
        (
            "- [lib_###::spec.md::SECTION] where SECTION is taken from the "
            "allow-list below (exact match)."
        ),
        (
            "Do NOT cite source files like [file_001::REQS] in the output "
            "(even if you see them inside specs)."
        ),
        "Tradeoffs must be concrete and measurable.",
        "",
        f"Libraries provided: {len(lib_charters)}",
        "",
        "## Library Intents",
    ]

    for lib_id, charter in lib_charters.items():
        intent = _extract_charter_intent(charter)
        lines.append(f"- {lib_id}: {intent}")

    if constraints:
        lines.append("")
        lines.append("## Key Constraints")
        for constraint in constraints:
            lines.append(f"- {constraint}")

    if lib_specs:
        lines.append("")
        lines.append("## Valid Spec Section Labels (for citations)")
        for lib_id in sorted(lib_specs):
            sections = _section_allowlist_from_content(lib_specs[lib_id])
            if sections:
                lines.append(f"- {lib_id} spec.md: {', '.join(sections)}")
            else:
                lines.append(f"- {lib_id} spec.md: (no sections detected)")

    return "\n".join(lines).strip() + "\n"


def _build_architecture_selection_prompt(
    candidates: dict[str, str], lib_specs: dict[str, str]
) -> str:
    lines = [
        "Select the best architecture candidate.",
        (
            "Return JSON with selected_arch_id, rationale, rejected_architectures, "
            "implementation_risks, evolution_notes."
        ),
        "Citations MUST use library pointers only:",
        "- [lib_###::charter.md]",
        (
            "- [lib_###::spec.md::SECTION] where SECTION is taken from the "
            "allow-list below (exact match)."
        ),
        (
            "Do NOT cite source files like [file_001::REQS] in the output "
            "(even if you see them inside specs)."
        ),
        "Use citations from library specs/charters in the rationale (not file-level citations).",
        "",
        "## Candidates",
    ]

    for arch_id, content in candidates.items():
        lines.append(f"### {arch_id}")
        lines.append(content.strip())
        lines.append("")

    if lib_specs:
        lines.append("## Library Specs")
        for lib_id, spec in lib_specs.items():
            lines.append(f"### {lib_id}")
            lines.append(_summarize_spec_for_prompt(spec))
            lines.append("")
        lines.append("## Valid Spec Section Labels (for citations)")
        for lib_id in sorted(lib_specs):
            sections = _section_allowlist_from_content(lib_specs[lib_id])
            if sections:
                lines.append(f"- {lib_id} spec.md: {', '.join(sections)}")
            else:
                lines.append(f"- {lib_id} spec.md: (no sections detected)")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _build_architecture_mapping_prompt(
    selected_architecture: str,
    lib_charters: dict[str, str],
    lib_specs: dict[str, str],
) -> str:
    lines = [
        "Map libraries to architecture components.",
        "Follow the output format exactly.",
        "Every library must be mapped with citations.",
        "Citations MUST use library pointers only:",
        "- [lib_###::charter.md]",
        (
            "- [lib_###::spec.md::SECTION] where SECTION is taken from the "
            "allow-list below (exact match)."
        ),
        (
            "Do NOT cite source files like [file_001::REQS] in the output "
            "(even if you see them inside specs)."
        ),
        "",
        "## Selected Architecture",
        selected_architecture.strip(),
        "",
        "## Library Charters",
    ]

    for lib_id, charter in lib_charters.items():
        lines.append(f"### {lib_id}")
        lines.append(_summarize_charter_for_prompt(charter))
        lines.append("")

    if lib_specs:
        lines.append("## Library Specs")
        for lib_id, spec in lib_specs.items():
            lines.append(f"### {lib_id}")
            lines.append(_summarize_spec_for_prompt(spec))
            lines.append("")
        lines.append("## Valid Spec Section Labels (for citations)")
        for lib_id in sorted(lib_specs):
            sections = _section_allowlist_from_content(lib_specs[lib_id])
            if sections:
                lines.append(f"- {lib_id} spec.md: {', '.join(sections)}")
            else:
                lines.append(f"- {lib_id} spec.md: (no sections detected)")
        lines.append("")

    lines.append("## Mapping Format")
    lines.append(
        """# Architecture Mapping

## Architecture: {arch_id}

{architecture description}

## Component Mappings

### Component: {component_name}

**Responsibilities**: {component responsibilities}

**Libraries**:
- lib_001: {intent} [lib_001::charter.md]
- lib_002: {intent} [lib_002::spec.md::REQUIREMENTS]

### Component: {component_name}

...

## Cross-Component Dependencies

- {component_A} -> {component_B}: {reason} [lib_003::spec.md::DEPENDENCIES]

## Unmapped Libraries

- None (or list with reasons)
"""
    )

    return "\n".join(lines).strip() + "\n"


def _summarize_spec_for_prompt(spec: str) -> str:
    sections = _extract_markdown_sections(spec)
    if not sections:
        return _strip_file_citations(spec.strip())[:1500]

    wanted = [
        "intent",
        "requirements",
        "constraints",
        "dependencies",
        "performance",
        "security",
        "availability",
    ]
    lines: list[str] = []
    for title, body in sections.items():
        if any(key in title.lower() for key in wanted):
            lines.append(f"## {title}")
            lines.append(_strip_file_citations(body.strip()))
            lines.append("")

    if lines:
        return "\n".join(lines).strip()[:2000]

    return _strip_file_citations(spec.strip())[:2000]


def _summarize_charter_for_prompt(charter: str) -> str:
    sections = _extract_markdown_sections(charter)
    if not sections:
        return charter.strip()[:800]
    wanted = ["intent", "boundaries", "responsibilities"]
    lines: list[str] = []
    for title, body in sections.items():
        if any(key in title.lower() for key in wanted):
            lines.append(f"## {title}")
            lines.append(body.strip())
            lines.append("")
    if lines:
        return "\n".join(lines).strip()[:1200]
    return charter.strip()[:1200]


def _extract_charter_intent(charter: str) -> str:
    sections = _extract_markdown_sections(charter)
    for title, body in sections.items():
        if title.lower() == "intent":
            return _collapse_whitespace(body)[:160]
    return _collapse_whitespace(charter)[:160]


def _extract_markdown_sections(content: str) -> dict[str, str]:
    pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections[title] = content[start:end].strip()
    return sections


def _extract_section_labels(content: str) -> set[str]:
    labels: set[str] = set()
    for match in re.finditer(r"\[([A-Z_]+)\]", content):
        labels.add(match.group(1))
    for match in re.finditer(r"^#{2,3}\s+(.+)$", content, re.MULTILINE):
        heading = match.group(1).strip()
        if heading:
            labels.add(heading)
            labels.add(heading.upper().replace(" ", "_"))
    return labels


def _section_allowlist_from_content(content: str) -> list[str]:
    """Return a stable citation allow-list derived from section headings/labels."""
    labels = _extract_section_labels(content)
    (
        # Prefer the machine-stable labels (UPPER_SNAKE_CASE) to avoid duplicates like
        # "Intent"/"INTENT".
        stable
    ) = {label for label in labels if re.fullmatch(r"[A-Z0-9_]+", label)}
    return sorted(stable)


def _strip_file_citations(text: str) -> str:
    """Remove `[file_###::SECTION]` citations to reduce chance of file-level citation drift."""
    return re.sub(r"\[file_\d+::[^\]]+?\]", "", text)


def _extract_json_payload(output: str) -> str:
    """Extract the first valid JSON object/array from an agent output string.

    Tolerant of fenced code blocks and trailing commentary containing brackets.
    """
    text = output.strip()
    if not text:
        return text

    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            fence_end = text.find("```", first_newline + 1)
            if fence_end != -1:
                text = text[first_newline + 1 : fence_end].strip()

    decoder = json.JSONDecoder()

    first_obj = text.find("{")
    first_list = text.find("[")
    starts = [idx for idx in (first_obj, first_list) if idx != -1]
    if not starts:
        return text

    for start in sorted(starts):
        idx = start
        while idx < len(text):
            if text[idx] not in "{[":
                idx += 1
                continue
            try:
                _, end = decoder.raw_decode(text[idx:])
            except json.JSONDecodeError:
                idx += 1
                continue
            return text[idx : idx + end]

    return text[min(starts) :]


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _candidate_filename(arch_id: str) -> str:
    if arch_id.startswith("arch_"):
        suffix = arch_id[len("arch_") :]
        return f"arch_{suffix}.md"
    return f"arch_{arch_id}.md"


def _find_missing_mapping_citations(component_lines: dict[str, list[str]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for component, lines in component_lines.items():
        for line in lines:
            if "[" not in line or "]" not in line:
                issues.append(
                    {
                        "type": "missing_mapping_citation",
                        "component": component,
                        "line": line.strip(),
                        "message": "Library mapping missing citation.",
                    }
                )
    return issues


def _format_architecture_selection(
    arch_id: str, selection: dict[str, Any], candidate_content: str
) -> str:
    lines = [f"# Selected Architecture: {arch_id}", ""]
    lines.append("## Rationale")
    lines.append(str(selection.get("rationale", "")).strip())
    lines.append("")

    lines.append("## Implementation Risks")
    risks = selection.get("implementation_risks", [])
    if isinstance(risks, list) and risks:
        for risk in risks:
            lines.append(f"- {risk}")
    elif risks:
        lines.append(str(risks))
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Evolution Notes")
    evolution = selection.get("evolution_notes", [])
    if isinstance(evolution, list) and evolution:
        for note in evolution:
            lines.append(f"- {note}")
    elif evolution:
        lines.append(str(evolution))
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Selected Candidate")
    lines.append(candidate_content.strip())
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _format_architecture_rejections(selection: dict[str, Any]) -> str:
    lines = ["# Rejected Architectures", ""]
    rejected = selection.get("rejected_architectures", [])
    if not rejected:
        lines.append("- None")
        lines.append("")
        return "\n".join(lines)

    for item in rejected:
        arch_id = item.get("arch_id") if isinstance(item, dict) else "unknown"
        reason = item.get("reason") if isinstance(item, dict) else str(item)
        lines.append(f"- {arch_id}: {reason}")

    lines.append("")
    return "\n".join(lines)

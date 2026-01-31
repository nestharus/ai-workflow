"""Architecture workflow for Phase 6 spec refinement."""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from scripts.spec_refinement.schemas import (
    ArchitectureBrief,
    ArchitectureProposal,
    ArchitectureSelection,
)
from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from .agent_utils import run_agent
from .formats import (
    normalize_compound_pointers,
    parse_architecture_brief_output,
    parse_architecture_proposal,
    parse_architecture_selection,
)
from .progress import ProgressTracker
from .validation_utils import strip_invalid_file_pointers

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

    briefs = _extract_architecture_briefs(libraries, manager)
    prompt = _build_architecture_proposal_prompt(lib_charters, lib_specs, briefs)

    try:
        output = run_agent(
            agent_name="opus-architecture-proposer",
            prompt=prompt,
            workspace=manager.workspace_path,
            structured_schema=ArchitectureProposal,
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
            structured_schema=ArchitectureSelection,
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
    rationale = strip_invalid_file_pointers(
        rationale,
        manager.state.file_manifest,
        allow_multi_hop=True,
    )
    selection["rationale"] = rationale
    issues = _validate_architecture_citations(rationale, manager)
    if issues:
        from .repair import ArtifactType, repair_artifact

        libraries = manager.get_all_libraries_recursive()
        try:
            repaired_rationale = repair_artifact(
                output=rationale,
                errors=issues,
                allowlists={
                    "library_ids": list(libraries.keys()),
                    "file_names": ["charter.md", "spec.md"],
                },
                artifact_type=ArtifactType.ARCHITECTURE_SELECTION,
                manager=manager,
            )
            repaired_issues = _validate_architecture_citations(repaired_rationale, manager)
            if not repaired_issues:
                rationale = repaired_rationale
                selection["rationale"] = rationale
                issues = []
        except Exception as exc:
            issues.append(
                {
                    "type": "repair_failed",
                    "message": f"Architecture selection repair failed: {exc}",
                }
            )

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
    mapping_fragments = _map_libraries_distributed(selected_content, libraries, manager)
    mapping = _aggregate_mapping_fragments(mapping_fragments, libraries)

    component_mappings: dict[str, list[str]] = mapping.get("component_mappings", {})
    component_lines: dict[str, list[str]] = mapping.get("component_lines", {})
    dependencies: list[str] = mapping.get("dependencies", [])
    unmapped: list[str] = mapping.get("unmapped_libraries", [])

    mapped_libs: set[str] = set()
    for libs in component_mappings.values():
        mapped_libs.update(libs)

    issues: list[dict[str, Any]] = []

    if unmapped:
        issues.append(
            {
                "type": "unmapped_libraries",
                "libraries": unmapped,
                "message": "Some libraries were not mapped to any component.",
            }
        )

    missing_citations = _find_missing_mapping_citations(component_lines, dependencies)
    if missing_citations:
        issues.extend(missing_citations)

    if not dependencies:
        issues.append(
            {
                "type": "missing_cross_component_dependencies",
                "message": "No cross-component dependencies documented.",
            }
        )

    formatted_output = _format_architecture_mapping(mapping, selected_content)
    formatted_output = normalize_compound_pointers(formatted_output)
    formatted_output = strip_invalid_file_pointers(
        formatted_output,
        manager.state.file_manifest,
        allow_multi_hop=True,
    )

    citation_issues = _validate_architecture_citations(formatted_output, manager)
    issues.extend(citation_issues)
    if citation_issues:
        from .repair import ArtifactType, repair_artifact

        libraries = manager.get_all_libraries_recursive()
        try:
            repaired_output = repair_artifact(
                output=formatted_output,
                errors=citation_issues,
                allowlists={
                    "library_ids": list(libraries.keys()),
                    "file_names": ["charter.md", "spec.md"],
                },
                artifact_type=ArtifactType.ARCHITECTURE_MAPPING,
                manager=manager,
            )
            repaired_citation_issues = _validate_architecture_citations(repaired_output, manager)
            if not repaired_citation_issues:
                formatted_output = repaired_output
                issues = [i for i in issues if i not in citation_issues]
        except Exception as exc:
            issues.append(
                {
                    "type": "repair_failed",
                    "message": f"Architecture mapping repair failed: {exc}",
                }
            )

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
    mapping_path.write_text(formatted_output.strip() + "\n", encoding="utf-8")

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


def _extract_architecture_briefs(
    libraries: dict[str, Path], manager: WorkspaceManager
) -> dict[str, dict[str, Any]]:
    """Extract architecture briefs from all libraries in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    briefs: dict[str, dict[str, Any]] = {}
    tracker = ProgressTracker(
        total=len(libraries),
        description="Extracting architecture briefs",
        manager=manager,
    )

    def _extract_brief(lib_id: str, lib_dir: Path) -> tuple[str, dict[str, Any]]:
        charter_path = lib_dir / "charter.md"
        spec_path = lib_dir / "spec.md"
        charter = charter_path.read_text(encoding="utf-8") if charter_path.exists() else ""
        spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""

        prompt = _build_brief_extraction_prompt(lib_id, charter, spec)
        output = run_agent(
            agent_name="glm-architecture-brief-extractor",
            prompt=prompt,
            workspace=manager.workspace_path,
            structured_schema=ArchitectureBrief,
        )
        if isinstance(output, BaseModel):
            brief = output.model_dump()
        else:
            brief = parse_architecture_brief_output(output)
        _validate_architecture_brief(brief, lib_id)
        return lib_id, brief

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_extract_brief, lib_id, lib_dir): lib_id
            for lib_id, lib_dir in libraries.items()
        }
        for future in as_completed(futures):
            lib_id = futures[future]
            try:
                lib_id, brief = future.result()
                briefs[lib_id] = brief
                tracker.update(status=lib_id)
            except Exception:
                tracker.update(status=f"{lib_id} (failed)")
                # Continue with other libraries

    tracker.finish()
    return briefs


def _build_brief_extraction_prompt(lib_id: str, charter: str, spec: str) -> str:
    lines = [
        f"Extract architecture brief for library: {lib_id}",
        "Return JSON with: lib_id, intent, boundaries, dependencies, constraints, interfaces",
        "All constraints and interfaces MUST include citations to spec sections.",
        "",
        "## Charter",
        charter.strip(),
        "",
        "## Spec",
        spec.strip(),
    ]
    return "\n".join(lines)


def _validate_architecture_brief(brief: dict[str, Any], lib_id: str) -> None:
    if not isinstance(brief, dict):
        raise TypeError("Architecture brief must be a JSON object.")

    brief_lib_id = brief.get("lib_id")
    if not isinstance(brief_lib_id, str) or brief_lib_id != lib_id:
        raise TypeError("Architecture brief lib_id mismatch.")

    required_str = ("intent", "boundaries")
    for key in required_str:
        if not isinstance(brief.get(key), str):
            raise TypeError(f"Architecture brief missing string field: {key}")

    dependencies = brief.get("dependencies")
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise TypeError("Architecture brief dependencies must be a list of strings.")

    constraints = brief.get("constraints")
    if not isinstance(constraints, list) or not all(isinstance(item, str) for item in constraints):
        raise TypeError("Architecture brief constraints must be a list of strings.")

    interfaces = brief.get("interfaces")
    if not isinstance(interfaces, list) or not all(isinstance(item, str) for item in interfaces):
        raise TypeError("Architecture brief interfaces must be a list of strings.")


def _parse_architecture_candidates(output: BaseModel | str) -> list[dict[str, Any]]:
    if isinstance(output, BaseModel):
        payload = output.model_dump_json()
    else:
        payload = _extract_json_payload(output)
    candidates = parse_architecture_proposal(payload)
    return [asdict(candidate) for candidate in candidates]


def _parse_architecture_selection(output: BaseModel | str) -> dict[str, Any]:
    if isinstance(output, BaseModel):
        payload = output.model_dump_json()
    else:
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
    lib_charters: dict[str, str],
    lib_specs: dict[str, str],
    briefs: dict[str, dict[str, Any]],
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

    lines.append("")
    lines.append("## Library Architecture Briefs")
    if briefs:
        for lib_id in sorted(briefs.keys()):
            brief = briefs[lib_id]
            intent = _collapse_whitespace(str(brief.get("intent", ""))).strip() or "None"
            boundaries = _collapse_whitespace(str(brief.get("boundaries", ""))).strip() or "None"
            dependencies = brief.get("dependencies", [])
            constraints = brief.get("constraints", [])
            interfaces = brief.get("interfaces", [])

            lines.append(f"### {lib_id}")
            lines.append(f"Intent: {intent}")
            lines.append(f"Boundaries: {boundaries}")
            lines.append("Dependencies:")
            if isinstance(dependencies, list) and dependencies:
                for dep in dependencies:
                    dep_text = _collapse_whitespace(str(dep)).strip()
                    if dep_text:
                        lines.append(f"- {dep_text}")
            else:
                lines.append("- None")

            lines.append("Constraints:")
            if isinstance(constraints, list) and constraints:
                for item in constraints:
                    item_text = _collapse_whitespace(str(item)).strip()
                    if item_text:
                        lines.append(f"- {item_text}")
            else:
                lines.append("- None")

            lines.append("Interfaces:")
            if isinstance(interfaces, list) and interfaces:
                for item in interfaces:
                    item_text = _collapse_whitespace(str(item)).strip()
                    if item_text:
                        lines.append(f"- {item_text}")
            else:
                lines.append("- None")
            lines.append("")
    else:
        lines.append("- None")

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


def _map_libraries_distributed(
    selected_architecture: str,
    libraries: dict[str, Path],
    manager: WorkspaceManager,
) -> list[dict[str, Any]]:
    """Map each library to architecture components in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    fragments: list[dict[str, Any]] = []
    tracker = ProgressTracker(
        total=len(libraries),
        description="Mapping libraries to architecture",
        manager=manager,
    )

    def _map_library(lib_id: str, lib_dir: Path) -> dict[str, Any]:
        charter_path = lib_dir / "charter.md"
        spec_path = lib_dir / "spec.md"
        charter = charter_path.read_text(encoding="utf-8") if charter_path.exists() else ""
        spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""

        prompt = _build_library_mapping_prompt(lib_id, selected_architecture, charter, spec)
        output = run_agent(
            agent_name="glm-architecture-library-mapper",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
        if isinstance(output, BaseModel):
            output = output.model_dump_json()
        fragment = json.loads(_extract_json_payload(output))
        _validate_mapping_fragment(fragment, lib_id)
        return cast("dict[str, Any]", fragment)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_map_library, lib_id, lib_dir): lib_id
            for lib_id, lib_dir in libraries.items()
        }
        for future in as_completed(futures):
            lib_id = futures[future]
            try:
                fragment = future.result()
                fragments.append(fragment)
                tracker.update(status=lib_id)
            except Exception:
                tracker.update(status=f"{lib_id} (failed)")
                # Continue with other libraries

    tracker.finish()
    return fragments


def _validate_mapping_fragment(fragment: dict[str, Any], lib_id: str) -> None:
    if not isinstance(fragment, dict):
        raise TypeError("Architecture mapping fragment must be a JSON object.")

    fragment_lib_id = fragment.get("lib_id")
    if not isinstance(fragment_lib_id, str) or fragment_lib_id != lib_id:
        raise TypeError("Architecture mapping fragment lib_id mismatch.")

    for key in ("component", "rationale"):
        if not isinstance(fragment.get(key), str):
            raise TypeError(f"Architecture mapping fragment missing field: {key}")

    citations = fragment.get("citations")
    if not isinstance(citations, list) or not all(isinstance(item, str) for item in citations):
        raise TypeError("Architecture mapping fragment citations must be a list of strings.")

    dependencies = fragment.get("cross_component_dependencies")
    if not isinstance(dependencies, list):
        raise TypeError("Architecture mapping fragment dependencies must be a list.")
    for item in dependencies:
        if not isinstance(item, dict):
            raise TypeError("Architecture mapping dependency entries must be objects.")
        for key in ("target_component", "reason", "citation"):
            if not isinstance(item.get(key), str):
                raise TypeError(f"Architecture mapping dependency missing field: {key}")


def _aggregate_mapping_fragments(
    fragments: list[dict[str, Any]],
    libraries: dict[str, Path],
) -> dict[str, Any]:
    """Aggregate per-library mapping fragments into final mapping structure."""
    component_mappings: dict[str, list[str]] = {}
    component_lines: dict[str, list[str]] = {}
    dependencies: list[str] = []

    for fragment in fragments:
        lib_id = fragment.get("lib_id", "unknown")
        component = fragment.get("component", "Unknown")
        rationale = fragment.get("rationale", "")
        citations = fragment.get("citations", [])

        component_mappings.setdefault(component, []).append(lib_id)

        citation_str = " ".join(citations) if citations else ""
        line = f"- {lib_id}: {rationale}".strip()
        if citation_str:
            line = f"{line} {citation_str}".strip()
        component_lines.setdefault(component, []).append(line)

        for dep in fragment.get("cross_component_dependencies", []):
            target = dep.get("target_component", "")
            reason = dep.get("reason", "")
            citation = dep.get("citation", "")
            if target and reason:
                if citation:
                    dependencies.append(f"{component} -> {target}: {reason} {citation}")
                else:
                    dependencies.append(f"{component} -> {target}: {reason}")

    all_lib_ids = set(libraries.keys())
    mapped_libs: set[str] = set()
    for libs in component_mappings.values():
        mapped_libs.update(libs)
    unmapped = sorted(all_lib_ids - mapped_libs)

    return {
        "component_mappings": component_mappings,
        "component_lines": component_lines,
        "dependencies": dependencies,
        "unmapped_libraries": unmapped,
    }


def _build_library_mapping_prompt(
    lib_id: str,
    selected_architecture: str,
    charter: str,
    spec: str,
) -> str:
    lines = [
        f"Map library {lib_id} to the appropriate architecture component.",
        "Return JSON with: lib_id, component, rationale, citations, cross_component_dependencies",
        "Citations MUST use library pointers only: [lib_###::charter.md] or "
        "[lib_###::spec.md::SECTION]",
        "Do NOT cite source files like [file_001::REQS]",
        "",
        "## Selected Architecture",
        selected_architecture.strip(),
        "",
        f"## Library {lib_id} Charter",
        charter.strip(),
        "",
        f"## Library {lib_id} Spec",
        _summarize_spec_for_prompt(spec),
    ]
    return "\n".join(lines)


def _format_architecture_mapping(
    mapping: dict[str, Any],
    selected_architecture: str,
) -> str:
    """Format aggregated mapping fragments into final mapping.md."""
    lines = [
        "# Architecture Mapping",
        "",
        "## Architecture",
        selected_architecture.strip(),
        "",
        "## Component Mappings",
        "",
    ]

    component_mappings = mapping.get("component_mappings", {})
    component_lines = mapping.get("component_lines", {})

    for component in sorted(component_mappings.keys()):
        lines.append(f"### Component: {component}")
        lines.append("")
        lines.append("**Libraries**:")
        for line in component_lines.get(component, []):
            lines.append(line)
        lines.append("")

    lines.append("## Cross-Component Dependencies")
    lines.append("")
    dependencies = mapping.get("dependencies", [])
    if dependencies:
        for dep in dependencies:
            lines.append(f"- {dep}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Unmapped Libraries")
    lines.append("")
    unmapped = mapping.get("unmapped_libraries", [])
    if unmapped:
        for lib_id in unmapped:
            lines.append(f"- {lib_id}")
    else:
        lines.append("- None")
    lines.append("")

    return "\n".join(lines)


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


def _find_missing_mapping_citations(
    component_lines: dict[str, list[str]],
    dependencies: list[str],
) -> list[dict[str, Any]]:
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
    for dependency in dependencies:
        dep_text = str(dependency).strip()
        if not dep_text:
            continue
        if not ARCH_CITATION_RE.search(dep_text):
            issues.append(
                {
                    "type": "missing_dependency_citation",
                    "dependency": dep_text,
                    "message": "Cross-component dependency missing citation.",
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

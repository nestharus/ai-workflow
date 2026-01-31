"""Deterministic validators for manual QA agent-step cases."""

from __future__ import annotations

import json
import re
from typing import Any

from scripts.spec_refinement.workflows.architecture import _validate_architecture_citations
from scripts.spec_refinement.workflows.formats import (
    parse_architecture_proposal,
    parse_architecture_selection,
    parse_spec_patch_output,
)
from scripts.spec_refinement.workflows.spec_patches import (
    SpecDocument,
    apply_patch,
    parse_patch_json,
    render_spec,
    validate_patch_citations,
    validate_patch_operation,
)
from scripts.spec_refinement.workflows.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
)
from scripts.spec_refinement.workspace import WorkspaceManager

FORBIDDEN_DERIVED_POINTER_RE = re.compile(
    r"\[(?:charter|charter\\.md|(?:libraries|runs)[\\/][^\\]]+?)::[^\\]]+?\\]",
    re.IGNORECASE,
)


def _issue(issue_type: str, message: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"type": issue_type, "message": message}
    out.update(extra)
    return out


def _extract_json(output: str) -> Any:
    """Best-effort JSON extraction tolerant of leading/trailing noise."""
    text = output.strip()
    if not text:
        raise ValueError("Empty output.")
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            fence_end = text.find("```", first_newline + 1)
            if fence_end != -1:
                text = text[first_newline + 1 : fence_end].strip()
    decoder = json.JSONDecoder()
    for start in (text.find("{"), text.find("[")):
        if start == -1:
            continue
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        return obj
    return json.loads(text)


def validate_evidence_mapper_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        data = _extract_json(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse JSON: {exc}")]
    if not isinstance(data, dict):
        return [_issue("invalid_format", "Expected JSON object.")]

    file_id = data.get("file_id")
    if allowlists.get("file_id") and file_id != allowlists["file_id"]:
        issues.append(_issue("wrong_file_id", f"file_id must be {allowlists['file_id']}", got=file_id))

    relevant = data.get("relevant_sections")
    if not isinstance(relevant, list):
        issues.append(_issue("relevant_sections_not_list", "relevant_sections must be a list."))
        return issues

    valid_sections = allowlists.get("valid_sections") or manager.get_section_labels(str(file_id))
    if isinstance(valid_sections, list):
        for section in relevant:
            if not isinstance(section, str):
                issues.append(_issue("invalid_section_type", "Section entries must be strings.", got=section))
                continue
            if section not in valid_sections:
                issues.append(
                    _issue(
                        "section_not_in_allowlist",
                        "relevant_sections must use exact allow-list section labels.",
                        section=section,
                    )
                )

    for forbidden in ("Components", "Workflows", "Algorithms"):
        if any(isinstance(item, str) and item.strip() == forbidden for item in relevant):
            issues.append(
                _issue(
                    "used_summary_heading_as_section",
                    f"relevant_sections contains summary heading '{forbidden}'.",
                )
            )

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        issues.append(_issue("confidence_not_number", "confidence must be a number."))
    elif confidence < 0.0 or confidence > 1.0:
        issues.append(_issue("confidence_out_of_range", "confidence must be within [0.0, 1.0].", got=confidence))

    return issues


def _extract_sections(content: str) -> dict[str, str]:
    pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(content) else len(content)
        sections[title] = content[start:end].strip()
    return sections


def _section_bullets(section_text: str) -> list[str]:
    bullets: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            bullets.append(stripped)
    return bullets


def validate_spec_integrator_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        payload = parse_spec_patch_output(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse SpecPatchOutput: {exc}")]

    lib_id = str(payload.get("lib_id", ""))
    file_id = str(payload.get("file_id", ""))
    if allowlists.get("lib_id") and lib_id != allowlists["lib_id"]:
        issues.append(_issue("wrong_lib_id", "lib_id mismatch.", expected=allowlists["lib_id"], got=lib_id))
    if allowlists.get("file_id") and file_id != allowlists["file_id"]:
        issues.append(_issue("wrong_file_id", "file_id mismatch.", expected=allowlists["file_id"], got=file_id))

    patches = payload.get("patches", [])
    patch_json = json.dumps({"operations": patches, "lib_id": lib_id, "file_id": file_id})
    try:
        patch_set = parse_patch_json(patch_json)
    except Exception as exc:
        issues.append(_issue("invalid_patch_json", f"Patch JSON did not parse: {exc}"))
        return issues

    # Validate each operation structure.
    for operation in patch_set.operations:
        op_errors = validate_patch_operation(operation, valid_sections=patch_set_operations_valid_sections())
        if op_errors:
            issues.append(
                _issue(
                    "invalid_patch_operation",
                    "; ".join(op_errors),
                    op=operation.op,
                    section=operation.section,
                    bullet_index=operation.bullet_index,
                    source_section=operation.source_section,
                )
            )

    file_id_lookup = build_file_id_lookup(manager.state.file_manifest)
    section_alias_map = build_section_alias_map(manager.state.section_manifest)
    citation_issues = validate_patch_citations(
        patch_set.operations,
        file_id_lookup,
        section_alias_map,
        lib_id=lib_id or (allowlists.get("lib_id") or "unknown"),
    )
    issues.extend(citation_issues)

    # Apply patch to current spec and validate reclassification outcome.
    current_spec = allowlists.get("current_spec") or ""
    if not isinstance(current_spec, str) or not current_spec.strip():
        issues.append(_issue("missing_current_spec", "Test case did not provide current_spec for application."))
        return issues

    try:
        spec_doc = SpecDocument(current_spec)
        for operation in patch_set.operations:
            apply_patch(spec_doc, operation)
        rendered = render_spec(spec_doc, lib_id=allowlists.get("lib_id", lib_id) or lib_id)
    except Exception as exc:
        issues.append(_issue("patch_apply_failed", f"Failed to apply patch operations: {exc}"))
        return issues

    if FORBIDDEN_DERIVED_POINTER_RE.search(rendered):
        issues.append(
            _issue(
                "derived_pointer_present",
                "Derived pointers like [charter::...] must not appear in rendered spec.",
            )
        )

    sections = _extract_sections(rendered)
    boundaries = sections.get("Boundaries", "")
    if "throughput management" in boundaries.lower():
        issues.append(
            _issue(
                "unsupported_assertion_still_asserted",
                "Unsupported 'throughput management' claim must not remain asserted in Boundaries after applying patches.",
            )
        )
    decisions = sections.get("Decisions Needed", "")
    if "throughput management" not in decisions.lower():
        issues.append(
            _issue(
                "missing_decision_needed",
                "Unsupported 'throughput management' claim should appear in Decisions Needed after applying patches.",
            )
        )

    return issues


def patch_set_operations_valid_sections() -> list[str]:
    # Keep this local to avoid importing VALID_SPEC_SECTIONS at module import time.
    return ["Intent", "Boundaries", "Requirements", "Constraints", "Dependencies", "Decisions Needed"]


def validate_architecture_proposal_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        candidates = parse_architecture_proposal(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse architecture proposal JSON: {exc}")]

    if not (3 <= len(candidates) <= 5):
        issues.append(
            _issue("wrong_candidate_count", "Expected 3-5 architecture candidates.", count=len(candidates))
        )

    # Validate citations are in library-pointer space and exist.
    as_text = output if isinstance(output, str) else json.dumps(output)
    issues.extend(_validate_architecture_citations(as_text, manager))

    # Forbid file-level pointers in Phase 6 artifacts.
    if re.search(r"\\[file_\\d+::", as_text):
        issues.append(_issue("file_pointer_in_arch_output", "Architecture proposal must not cite [file_###::...]."))

    return issues


def validate_architecture_selection_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        data = parse_architecture_selection(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse selection JSON: {exc}")]

    selected = data.get("selected_arch_id")
    candidate_ids = allowlists.get("candidate_ids")
    if isinstance(candidate_ids, list) and selected not in candidate_ids and selected is not None:
        issues.append(_issue("selected_not_in_candidates", "selected_arch_id not in candidate set.", selected=selected))

    rationale = str(data.get("rationale", ""))
    issues.extend(_validate_architecture_citations(rationale, manager))
    if re.search(r"\\[file_\\d+::", rationale):
        issues.append(_issue("file_pointer_in_rationale", "Selection rationale must not cite [file_###::...]."))

    return issues


def validate_architecture_library_mapping_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        data = _extract_json(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse mapping JSON: {exc}")]

    if not isinstance(data, dict):
        return [_issue("invalid_format", "Expected JSON object for mapping fragment.")]

    lib_id = data.get("lib_id")
    expected_lib_id = allowlists.get("lib_id")
    if isinstance(expected_lib_id, str) and lib_id != expected_lib_id:
        issues.append(
            _issue(
                "lib_id_mismatch",
                "Mapping fragment lib_id mismatch.",
                expected=expected_lib_id,
                got=lib_id,
            )
        )

    component = data.get("component")
    if not isinstance(component, str) or not component.strip():
        issues.append(_issue("missing_component", "Mapping fragment must include a non-empty component."))
    else:
        allowed_components = allowlists.get("components") or []
        if isinstance(allowed_components, list) and allowed_components and component not in allowed_components:
            issues.append(
                _issue(
                    "component_not_in_architecture",
                    "component must match a component name from the selected architecture.",
                    component=component,
                )
            )

    citations = data.get("citations")
    if not isinstance(citations, list) or not all(isinstance(item, str) for item in citations):
        issues.append(_issue("invalid_citations", "citations must be a list of strings."))

    # Validate citations exist and are in library-pointer space.
    issues.extend(_validate_architecture_citations(json.dumps(data), manager))
    if re.search(r"\\[file_\\d+::", json.dumps(data)):
        issues.append(_issue("file_pointer_in_mapping", "Architecture mapping must not cite [file_###::...]."))

    dependencies = data.get("cross_component_dependencies", [])
    if not isinstance(dependencies, list):
        issues.append(_issue("invalid_dependencies", "cross_component_dependencies must be a list."))
    else:
        for dep in dependencies:
            if not isinstance(dep, dict):
                issues.append(_issue("invalid_dependency_entry", "Dependency entries must be objects."))
                continue
            citation = dep.get("citation", "")
            if isinstance(citation, str) and "[file_" in citation:
                issues.append(
                    _issue(
                        "file_pointer_in_dependency",
                        "Dependency citation must not cite [file_###::...].",
                    )
                )

    return issues

"""Deterministic validators for manual QA agent-step cases."""

from __future__ import annotations

import json
import re
from typing import Any

from spec_manager.refinement.formats import (
    parse_architecture_proposal,
    parse_architecture_selection,
    parse_spec_patch_output,
)

from scripts.spec_refinement.workflows.architecture import _validate_architecture_citations
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
from scripts.spec_refinement.workspace import WorkspaceManager, WorkspaceState

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
            obj, _end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        return obj
    return json.loads(text)


def validate_evidence_mapper_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate evidence mapper output against allowlists."""
    issues: list[dict[str, Any]] = []
    try:
        data = _extract_json(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse JSON: {exc}")]
    if not isinstance(data, dict):
        return [_issue("invalid_format", "Expected JSON object.")]

    file_id = data.get("file_id")
    if allowlists.get("file_id") and file_id != allowlists["file_id"]:
        issues.append(
            _issue("wrong_file_id", f"file_id must be {allowlists['file_id']}", got=file_id)
        )

    relevant = data.get("relevant_sections")
    if not isinstance(relevant, list):
        issues.append(_issue("relevant_sections_not_list", "relevant_sections must be a list."))
        return issues

    valid_sections = allowlists.get("valid_sections") or manager.get_section_labels(str(file_id))
    if isinstance(valid_sections, list):
        for section in relevant:
            if not isinstance(section, str):
                issues.append(
                    _issue("invalid_section_type", "Section entries must be strings.", got=section)
                )
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
        issues.append(
            _issue(
                "confidence_out_of_range", "confidence must be within [0.0, 1.0].", got=confidence
            )
        )

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
    """Validate spec integrator output."""
    issues: list[dict[str, Any]] = []
    try:
        payload = parse_spec_patch_output(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse SpecPatchOutput: {exc}")]

    lib_id = str(payload.get("lib_id", ""))
    file_id = str(payload.get("file_id", ""))
    if allowlists.get("lib_id") and lib_id != allowlists["lib_id"]:
        issues.append(
            _issue("wrong_lib_id", "lib_id mismatch.", expected=allowlists["lib_id"], got=lib_id)
        )
    if allowlists.get("file_id") and file_id != allowlists["file_id"]:
        issues.append(
            _issue(
                "wrong_file_id", "file_id mismatch.", expected=allowlists["file_id"], got=file_id
            )
        )

    patches = payload.get("patches", [])
    patch_json = json.dumps({"operations": patches, "lib_id": lib_id, "file_id": file_id})
    try:
        patch_set = parse_patch_json(patch_json)
    except Exception as exc:
        issues.append(_issue("invalid_patch_json", f"Patch JSON did not parse: {exc}"))
        return issues

    # Validate each operation structure.
    for operation in patch_set.operations:
        op_errors = validate_patch_operation(
            operation, valid_sections=patch_set_operations_valid_sections()
        )
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

    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
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
        issues.append(
            _issue(
                "missing_current_spec", "Test case did not provide current_spec for application."
            )
        )
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
                "Unsupported 'throughput management' claim must not remain asserted in Boundaries "
                "after applying patches.",
            )
        )
    decisions = sections.get("Decisions Needed", "")
    if "throughput management" not in decisions.lower():
        issues.append(
            _issue(
                "missing_decision_needed",
                "Unsupported 'throughput management' claim should appear in Decisions Needed "
                "after applying patches.",
            )
        )

    return issues


def patch_set_operations_valid_sections() -> list[str]:
    """Return valid sections for patch set operations."""
    # Keep this local to avoid importing VALID_SPEC_SECTIONS at module import time.
    return [
        "Intent",
        "Boundaries",
        "Requirements",
        "Constraints",
        "Dependencies",
        "Decisions Needed",
    ]


def validate_architecture_proposal_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate architecture proposal output."""
    issues: list[dict[str, Any]] = []
    try:
        candidates = parse_architecture_proposal(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse architecture proposal JSON: {exc}")]

    if not (3 <= len(candidates) <= 5):
        issues.append(
            _issue(
                "wrong_candidate_count",
                "Expected 3-5 architecture candidates.",
                count=len(candidates),
            )
        )

    # Validate citations are in library-pointer space and exist.
    as_text = output if isinstance(output, str) else json.dumps(output)
    issues.extend(_validate_architecture_citations(as_text, manager))

    # Forbid file-level pointers in Phase 6 artifacts.
    if re.search(r"\[F\d{4}::", as_text):
        issues.append(
            _issue(
                "file_pointer_in_arch_output",
                "Architecture proposal must not cite [F####::...].",
            )
        )

    return issues


def validate_architecture_selection_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate architecture selection output."""
    issues: list[dict[str, Any]] = []
    try:
        data = parse_architecture_selection(output)
    except Exception as exc:
        return [_issue("parse_error", f"Failed to parse selection JSON: {exc}")]

    selected = data.get("selected_arch_id")
    candidate_ids = allowlists.get("candidate_ids")
    if isinstance(candidate_ids, list) and selected not in candidate_ids and selected is not None:
        issues.append(
            _issue(
                "selected_not_in_candidates",
                "selected_arch_id not in candidate set.",
                selected=selected,
            )
        )

    rationale = str(data.get("rationale", ""))
    issues.extend(_validate_architecture_citations(rationale, manager))
    if re.search(r"\[F\d{4}::", rationale):
        issues.append(
            _issue("file_pointer_in_rationale", "Selection rationale must not cite [F####::...].")
        )

    return issues


def validate_architecture_library_mapping_output(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate architecture library mapping output."""
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
        issues.append(
            _issue("missing_component", "Mapping fragment must include a non-empty component.")
        )
    else:
        allowed_components = allowlists.get("components") or []
        if (
            isinstance(allowed_components, list)
            and allowed_components
            and component not in allowed_components
        ):
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
    if re.search(r"\[F\d{4}::", json.dumps(data)):
        issues.append(
            _issue("file_pointer_in_mapping", "Architecture mapping must not cite [F####::...].")
        )

    dependencies = data.get("cross_component_dependencies", [])
    if not isinstance(dependencies, list):
        issues.append(
            _issue("invalid_dependencies", "cross_component_dependencies must be a list.")
        )
    else:
        for dep in dependencies:
            if not isinstance(dep, dict):
                issues.append(
                    _issue("invalid_dependency_entry", "Dependency entries must be objects.")
                )
                continue
            citation = dep.get("citation", "")
            if isinstance(citation, str) and re.search(r"\[F\d{4}::", citation):
                issues.append(
                    _issue(
                        "file_pointer_in_dependency",
                        "Dependency citation must not cite [F####::...].",
                    )
                )

    return issues


def validate_phase0_determinism(
    *,
    first_manifest: dict[str, dict[str, str]],
    second_manifest: dict[str, dict[str, str]],
    first_state: WorkspaceState,
    second_state: WorkspaceState,
    allowlists: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate Phase 0 determinism and safety invariants."""
    issues: list[dict[str, Any]] = []

    def _expected_ids(manifest: dict[str, dict[str, str]]) -> list[str]:
        return [f"F{index:04d}" for index in range(1, len(manifest) + 1)]

    def _check_manifest_sequence(label: str, manifest: dict[str, dict[str, str]]) -> None:
        expected = _expected_ids(manifest)
        actual = list(manifest.keys())
        if actual != expected:
            issues.append(
                _issue(
                    "file_id_sequence",
                    f"{label} manifest file IDs must be sequential and ordered.",
                    expected=expected[:5],
                    got=actual[:5],
                )
            )

    _check_manifest_sequence("first", first_manifest)
    _check_manifest_sequence("second", second_manifest)

    if list(first_manifest.items()) != list(second_manifest.items()):
        issues.append(
            _issue(
                "manifest_mismatch",
                "Manifest entries differ across runs (file IDs, paths, hashes, or ordering).",
            )
        )

    manifest_raw = allowlists.get("manifest_raw")
    if isinstance(manifest_raw, dict):
        first_raw = manifest_raw.get("first")
        second_raw = manifest_raw.get("second")
        if isinstance(first_raw, str) and isinstance(second_raw, str) and first_raw != second_raw:
            issues.append(
                _issue(
                    "manifest_raw_mismatch",
                    "Manifest files.json contents are not byte-identical across runs.",
                )
            )

    if first_state.mode != second_state.mode:
        issues.append(
            _issue(
                "mode_mismatch",
                "Detected modes differ across runs.",
                first=first_state.mode,
                second=second_state.mode,
            )
        )

    expected_mode = allowlists.get("expected_mode")
    if isinstance(expected_mode, str) and first_state.mode != expected_mode:
        issues.append(
            _issue(
                "mode_unexpected",
                "Detected mode does not match expected value.",
                expected=expected_mode,
                got=first_state.mode,
            )
        )

    if first_state.spec_snapshot_baseline != second_state.spec_snapshot_baseline:
        issues.append(
            _issue(
                "spec_snapshot_baseline_mismatch",
                "Spec snapshot baseline differs across runs.",
            )
        )
    if first_state.spec_snapshot_baseline is None:
        issues.append(
            _issue(
                "spec_snapshot_baseline_missing",
                "Spec snapshot baseline is missing from the first run.",
            )
        )
    if second_state.spec_snapshot_baseline is None:
        issues.append(
            _issue(
                "spec_snapshot_baseline_missing",
                "Spec snapshot baseline is missing from the second run.",
            )
        )

    init_issues = allowlists.get("init_issues")
    if isinstance(init_issues, dict):
        for label in ("first", "second"):
            issue_list = init_issues.get(label)
            if isinstance(issue_list, list) and issue_list:
                issues.append(
                    _issue(
                        "init_issues",
                        f"{label} initialization returned issues: {issue_list}",
                    )
                )

    resume_payload = allowlists.get("resume")
    if isinstance(resume_payload, dict):
        resume_init_issues = resume_payload.get("init_issues")
        if isinstance(resume_init_issues, list) and resume_init_issues:
            issues.append(
                _issue(
                    "resume_init_issues",
                    f"Resume setup initialization returned issues: {resume_init_issues}",
                )
            )
        resume_issues = resume_payload.get("issues")
        if not isinstance(resume_issues, list) or not resume_issues:
            issues.append(
                _issue(
                    "resume_safety_missing",
                    "Resume safety test did not produce a manifest conflict error.",
                )
            )
        else:
            resume_text = " ".join(str(item) for item in resume_issues)
            if "Manifest conflict detected" not in resume_text:
                issues.append(
                    _issue(
                        "resume_safety_message",
                        "Resume safety error did not mention manifest conflict.",
                    )
                )
            if "--force" not in resume_text:
                issues.append(
                    _issue(
                        "resume_safety_force_hint_missing",
                        "Resume safety error did not mention --force.",
                    )
                )

        baseline_issues = resume_payload.get("baseline_issues")
        if isinstance(baseline_issues, list) and baseline_issues:
            issues.append(
                _issue(
                    "resume_baseline_issues",
                    f"Resume baseline update returned issues: {baseline_issues}",
                )
            )

    immutability_payload = allowlists.get("immutability")
    if isinstance(immutability_payload, dict):
        immut_init_issues = immutability_payload.get("init_issues")
        if isinstance(immut_init_issues, list) and immut_init_issues:
            issues.append(
                _issue(
                    "immutability_init_issues",
                    f"Immutability setup initialization returned issues: {immut_init_issues}",
                )
            )
        immutability_issues = immutability_payload.get("issues")
        if not isinstance(immutability_issues, list) or not immutability_issues:
            issues.append(
                _issue(
                    "immutability_missing",
                    "Spec snapshot immutability test did not detect modifications.",
                )
            )
        else:
            immut_text = " ".join(str(item) for item in immutability_issues)
            if "Spec snapshot has changed since creation" not in immut_text:
                issues.append(
                    _issue(
                        "immutability_message",
                        "Spec snapshot immutability error did not mention drift.",
                    )
                )
            if "--force" not in immut_text:
                issues.append(
                    _issue(
                        "immutability_force_hint_missing",
                        "Spec snapshot immutability error did not mention --force.",
                    )
                )

    return issues

"""Spec stabilization workflow for Phase 4 outputs.

This module normalizes evidence pointers from legacy `[F####::SECTION]`
format to canonical `[spec_snapshot/relpath::SEC-F####-####]` format while
preserving multi-hop pointers, assigns stable element IDs, persists
per-library counters, and builds indexes to support downstream phases.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from spec_manager.refinement.formats import (
    EVIDENCE_POINTER_RE,
    migrate_pointers_to_new_format,
    parse_evidence_pointer,
)
from spec_manager.refinement.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    resolve_section_reference,
)
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager
from spec_manager.schemas.spec_indexes import Decision, DecisionsIndex, SpecElement, SpecIndex

DEFAULT_COUNTERS: dict[str, int] = {"REQ": 0, "FLOW": 0, "INV": 0, "DEC": 0}
COUNTER_LIMITS: dict[str, int] = {"REQ": 9999, "FLOW": 99, "INV": 9999, "DEC": 9999}
ELEMENT_ID_RE = re.compile(r"^\s*-\s*((?:REQ|FLOW|INV|DEC)-LIB-\d{4}-\d+):\s*")
VALID_ELEMENT_ID_RE = re.compile(
    r"^(?:REQ-LIB-\d{4}-\d{4}|FLOW-LIB-\d{4}-\d{2}|INV-LIB-\d{4}-\d{4}|DEC-LIB-\d{4}-\d{4})$"
)
_DECISION_FIELD_RE = re.compile(r"\*\*\[(\w+)\]\*\*:\s*")
_DECISION_FIELD_NAMES = frozenset({"status", "context", "options", "default"})
logger = logging.getLogger(__name__)
_POINTER_MIGRATION_ERRORS: list[dict[str, str]] = []
_INDEX_BUILD_ERRORS: list[dict[str, str]] = []


def _default_counters() -> dict[str, int]:
    return dict(DEFAULT_COUNTERS)


def _load_id_counters_with_issues(
    lib_dir: Path,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Load ID counters and return any parse issues."""
    counters_path = lib_dir / "id_counters.json"
    if not counters_path.exists():
        return _default_counters(), []

    try:
        raw = json.loads(counters_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _default_counters(), [{"error": f"Failed to load id_counters.json: {exc}"}]

    if not isinstance(raw, dict):
        return _default_counters(), [{"error": "id_counters.json must contain an object"}]

    counters = _default_counters()
    errors: list[dict[str, Any]] = []
    for key in counters:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append({"error": f"Invalid counter value for {key}: {value!r}"})
            continue
        counters[key] = value

    return counters, errors


def load_id_counters(lib_dir: Path) -> dict[str, int]:
    """Load element ID counters for a library.

    Args:
        lib_dir: Library directory path.

    Returns:
        Counter map for REQ/FLOW/INV/DEC with defaults if missing.
    """
    counters, _ = _load_id_counters_with_issues(lib_dir)
    return counters


def save_id_counters(lib_dir: Path, counters: dict[str, int]) -> None:
    """Persist ID counters for a library.

    Args:
        lib_dir: Library directory path.
        counters: Counter map for REQ/FLOW/INV/DEC.

    Raises:
        OSError: If the counters file cannot be written.
    """
    counters_path = lib_dir / "id_counters.json"
    lib_dir.mkdir(parents=True, exist_ok=True)
    # Persist counters as JSON for stable ID allocation across runs.
    counters_path.write_text(json.dumps(counters, indent=2), encoding="utf-8")


def allocate_element_id(lib_id: str, element_type: str, counters: dict[str, int]) -> str:
    """Allocate the next stable element ID for a library.

    Args:
        lib_id: Library identifier (e.g., "LIB-0001").
        element_type: Element type prefix (REQ/FLOW/INV/DEC).
        counters: Mutable counters map for element types.

    Returns:
        Newly allocated element ID string.

    Raises:
        ValueError: If the element type is invalid or the counter exceeds limits.
    """
    if element_type not in counters:
        raise ValueError(f"Invalid element type: {element_type}")

    current = counters[element_type]
    limit = COUNTER_LIMITS.get(element_type)
    if limit is not None and current + 1 > limit:
        raise ValueError(f"Counter limit exceeded for {element_type}: {current + 1}")

    counters[element_type] = current + 1

    # ID format is type-prefixed and zero-padded for stable sorting.
    if element_type == "REQ":
        return f"REQ-{lib_id}-{counters[element_type]:04d}"
    if element_type == "FLOW":
        return f"FLOW-{lib_id}-{counters[element_type]:02d}"
    if element_type == "INV":
        return f"INV-{lib_id}-{counters[element_type]:04d}"
    if element_type == "DEC":
        return f"DEC-{lib_id}-{counters[element_type]:04d}"

    raise ValueError(f"Invalid element type: {element_type}")


def has_element_id(line: str, expected_prefix: str) -> bool:
    """Check if a bullet line starts with an element ID.

    Args:
        line: Line to check.
        expected_prefix: Expected prefix (REQ/FLOW/INV/DEC).

    Returns:
        True if the line begins with an element ID, False otherwise.
    """
    pattern = rf"^\s*-\s*({re.escape(expected_prefix)}-LIB-\d{{4}}-\d+):\s*"
    return bool(re.search(pattern, line))


def extract_existing_id(line: str) -> str | None:
    """Extract an existing element ID from a bullet line.

    Args:
        line: Line to parse.

    Returns:
        The extracted element ID string, or None if not found.
    """
    match = ELEMENT_ID_RE.search(line)
    return match.group(1) if match else None


def _extract_citations(line: str) -> list[str]:
    citations: list[str] = []
    for match in EVIDENCE_POINTER_RE.findall(line):
        if isinstance(match, tuple):
            file_ref, section_ref = match
            citations.append(f"[{file_ref}::{section_ref}]")
        else:
            citations.append(f"[{match}]")
    return citations


def _extract_library_mentions(line: str, lib_id: str) -> list[str]:
    text = _remove_element_id_prefix(line)
    mentions = re.findall(r"LIB-\d{4}", text)
    return sorted(set(mentions) - {lib_id})


def _remove_element_id_prefix(line: str) -> str:
    return re.sub(r"^\s*[-*]\s*((?:REQ|FLOW|INV|DEC)-LIB-\d{4}-\d+):\s*", "", line)


def _extract_sections_with_positions(content: str, level: int) -> list[tuple[str, int, int]]:
    pattern = re.compile(rf"^{'#' * level}\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return []

    sections: list[tuple[str, int, int]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections.append((title, start, end))
    return sections


def _get_section_element_type(section_title: str) -> str | None:
    mapping = {
        "Requirements": "REQ",
        "Flows": "FLOW",
        "Constraints": "INV",
        "Dependencies": "INV",
    }
    return mapping.get(section_title)


def _process_bullet_line(
    line: str, lib_id: str, element_type: str, counters: dict[str, int]
) -> tuple[str, bool]:
    bullet_match = re.match(r"^([ \t]*)([-*])\s+(.*)$", line)
    if not bullet_match:
        return line, False

    indent = bullet_match.group(1)
    indent_width = len(indent.expandtabs(4))
    if indent_width > 3:
        return line, False

    if has_element_id(line, element_type):
        existing_id = extract_existing_id(line)
        if existing_id and not existing_id.startswith(f"{element_type}-{lib_id}-"):
            logger.warning(
                "Element ID %s does not match library %s in %s section.",
                existing_id,
                lib_id,
                element_type,
            )
        return line, False

    rest_of_line = bullet_match.group(3)
    try:
        element_id = allocate_element_id(lib_id, element_type, counters)
    except ValueError:
        logger.exception(
            "Failed to allocate %s ID for %s spec",
            element_type,
            lib_id,
        )
        return line, False

    updated_line = f"{indent}- {element_id}: {rest_of_line}"
    return updated_line, True


def _process_id_managed_section(
    section_content: str, lib_id: str, element_type: str, counters: dict[str, int]
) -> tuple[str, int]:
    if not section_content:
        return section_content, 0

    lines = section_content.splitlines(keepends=True)
    updated_lines: list[str] = []
    ids_assigned = 0
    for line in lines:
        line_text = line.rstrip("\r\n")
        line_ending = line[len(line_text) :]
        updated_line, assigned = _process_bullet_line(line_text, lib_id, element_type, counters)
        if assigned:
            ids_assigned += 1
        updated_lines.append(updated_line + line_ending)
    return "".join(updated_lines), ids_assigned


def _ensure_flows_section(content: str) -> str:
    sections = _extract_sections_with_positions(content, level=2)
    if any(title == "Flows" for title, _, _ in sections):
        return content

    for title, _, end in sections:
        if title == "Requirements":
            insert_text = "\n## Flows\n\n"
            return f"{content[:end]}{insert_text}{content[end:]}"

    return content + "\n## Flows\n\n"


def _extract_decisions_from_spec(spec_content: str) -> str:
    if not spec_content:
        return ""
    sections = _extract_sections_with_positions(spec_content, level=2)
    for title, start, end in sections:
        if title == "Decisions Needed":
            return spec_content[start:end]
    return ""


def _ensure_decisions_header(decisions_content: str) -> str:
    if not decisions_content:
        return decisions_content
    stripped = decisions_content.lstrip()
    if stripped.startswith("# ") or stripped.startswith("## "):
        return decisions_content
    return f"# Decisions\n\n{decisions_content}"


def format_validation_error(
    error: dict[str, Any],
    lib_id: str,
    *,
    issue_type: str = "schema_error",
) -> dict[str, Any]:
    """Format a Pydantic validation error into a standardized issue dict.

    Args:
        error: Pydantic validation error dict.
        lib_id: Library identifier for the error.
        issue_type: Type string for the formatted error.

    Returns:
        Dict with type, lib_id, field, message, and error_type keys.
    """
    field_path = ".".join(str(part) for part in error.get("loc", ()) or ())
    return {
        "type": issue_type,
        "lib_id": lib_id,
        "field": field_path,
        "message": error.get("msg", "Schema validation error"),
        "error_type": error.get("type", "value_error"),
    }


def collect_validation_metrics(issues: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate validation issues by type into count metrics.

    Args:
        issues: List of validation issue dicts.

    Returns:
        Dict mapping issue category to count.
    """
    metrics = {
        "duplicate_ids": 0,
        "missing_ids": 0,
        "invalid_id_formats": 0,
        "invalid_pointers": 0,
        "schema_errors": 0,
        "other": 0,
    }
    for issue in issues:
        issue_type = issue.get("type")
        if issue_type == "duplicate_id":
            metrics["duplicate_ids"] += 1
        elif issue_type == "missing_id":
            metrics["missing_ids"] += 1
        elif issue_type in {"invalid_id_format", "mismatched_id"}:
            metrics["invalid_id_formats"] += 1
        elif issue_type in {"unresolved_pointer", "unresolved_section", "invalid_pointer"}:
            metrics["invalid_pointers"] += 1
        elif issue_type == "schema_error":
            metrics["schema_errors"] += 1
        else:
            metrics["other"] += 1
    return metrics


def _extract_element_identifier(
    element: SpecElement | Decision | dict[str, Any],
) -> str | None:
    if isinstance(element, dict):
        value = element.get("element_id") or element.get("decision_id")
        return value if isinstance(value, str) else None
    if isinstance(element, SpecElement):
        return element.element_id
    if isinstance(element, Decision):
        return element.decision_id
    return None


def _is_valid_element_id(element_id: str, *, expected_prefix: str | None = None) -> bool:
    return bool(
        VALID_ELEMENT_ID_RE.fullmatch(element_id)
        and (not expected_prefix or element_id.startswith(f"{expected_prefix}-"))
    )


def validate_id_uniqueness(
    elements: list[SpecElement | Decision | dict[str, Any]],
    lib_id: str,
) -> list[dict[str, Any]]:
    """Validate that element IDs are unique within a library.

    Args:
        elements: List of element metadata dicts or schema objects.
        lib_id: Library identifier.

    Returns:
        List of validation issues.
    """
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in elements:
        element_id = _extract_element_identifier(element)
        if not element_id:
            continue
        if not _is_valid_element_id(element_id):
            issues.append(
                {
                    "type": "invalid_id_format",
                    "element_id": element_id,
                    "lib_id": lib_id,
                    "message": f"Invalid element ID format: {element_id}",
                }
            )
            continue
        if element_id in seen:
            issues.append(
                {
                    "type": "duplicate_id",
                    "element_id": element_id,
                    "lib_id": lib_id,
                    "message": f"Duplicate element ID detected: {element_id}",
                }
            )
        else:
            seen.add(element_id)
    return issues


def validate_all_bullets_have_ids(spec_content: str, lib_id: str) -> list[dict[str, Any]]:
    """Validate that ID-managed bullet lines have stable IDs.

    Args:
        spec_content: Spec content to inspect.
        lib_id: Library identifier.

    Returns:
        List of validation issues for bullets missing IDs.
    """
    if not spec_content:
        return []
    issues: list[dict[str, Any]] = []
    sections = _extract_sections_with_positions(spec_content, level=2)
    if not sections:
        return issues

    bullet_pattern = re.compile(r"^([ \t]*)([-*])\s+(.+)$")
    for section_title, start, end in sections:
        element_type = _get_section_element_type(section_title)
        if not element_type:
            continue
        section_content = spec_content[start:end]
        for line in section_content.splitlines():
            match = bullet_pattern.match(line)
            if not match:
                continue
            indent = match.group(1)
            indent_width = len(indent.expandtabs(4))
            if indent_width > 3:
                continue
            element_id = extract_existing_id(line)
            if not element_id:
                issues.append(
                    {
                        "type": "missing_id",
                        "lib_id": lib_id,
                        "section": section_title,
                        "message": f"Missing {element_type} ID for bullet: {line.strip()}",
                    }
                )
                continue
            if not _is_valid_element_id(element_id, expected_prefix=element_type):
                issues.append(
                    {
                        "type": "mismatched_id",
                        "lib_id": lib_id,
                        "element_id": element_id,
                        "section": section_title,
                        "message": (
                            f"Invalid {element_type} ID for bullet in {section_title}: {element_id}"
                        ),
                    }
                )
    return issues


def validate_spec_index_schema(
    index_payload: dict[str, Any],
    lib_id: str,
) -> list[dict[str, Any]]:
    """Validate spec index payload against the Pydantic schema."""
    issues: list[dict[str, Any]] = []
    try:
        SpecIndex.model_validate(index_payload)
    except ValidationError as exc:
        for error in exc.errors():
            issues.append(format_validation_error(error, lib_id, issue_type="schema_error"))
    return issues


def validate_decisions_index_schema(
    index_payload: dict[str, Any],
    lib_id: str,
) -> list[dict[str, Any]]:
    """Validate decisions index payload against the Pydantic schema."""
    issues: list[dict[str, Any]] = []
    try:
        DecisionsIndex.model_validate(index_payload)
    except ValidationError as exc:
        for error in exc.errors():
            issues.append(format_validation_error(error, lib_id, issue_type="schema_error"))
    return issues


def _record_pointer_migration_error(context: str, error: str) -> None:
    """Record a pointer migration error for later issue reporting."""
    _POINTER_MIGRATION_ERRORS.append({"context": context, "error": error})


def _consume_pointer_migration_errors() -> list[dict[str, str]]:
    """Return and clear any recorded pointer migration errors."""
    if not _POINTER_MIGRATION_ERRORS:
        return []
    errors = list(_POINTER_MIGRATION_ERRORS)
    _POINTER_MIGRATION_ERRORS.clear()
    return errors


def _record_index_build_error(context: str, lib_id: str, error: str) -> None:
    """Record an index build error for later issue reporting."""
    _INDEX_BUILD_ERRORS.append({"context": context, "lib_id": lib_id, "error": error})


def _consume_index_build_errors() -> list[dict[str, str]]:
    """Return and clear any recorded index build errors."""
    if not _INDEX_BUILD_ERRORS:
        return []
    errors = list(_INDEX_BUILD_ERRORS)
    _INDEX_BUILD_ERRORS.clear()
    return errors


def _normalize_pointers(
    content: str,
    manager: WorkspaceManager,
    *,
    context: str,
    section_alias_map: dict[str, dict[str, str]] | None = None,
) -> str:
    """Normalize legacy evidence pointers using the migration infrastructure.

    Converts legacy `[F####::SECTION]` pointers to canonical
    `[spec_snapshot/relpath::SEC-F####-####]` format while preserving
    multi-hop pointers such as `[LIB-0001::spec.md::REQ-LIB-0001-0001]`.
    Delegates conversion to `migrate_pointers_to_new_format`, ensuring
    consistency with other refinement workflows.

    Args:
        content: Raw markdown content to normalize.
        manager: Workspace manager providing manifest and snapshot context.
        context: Label used for logging (e.g., "spec.md").
        section_alias_map: Optional section alias map for resolving legacy
            section labels to canonical IDs.

    Returns:
        Content with legacy evidence pointers migrated to canonical format.
    """
    if not content:
        return content
    try:
        return migrate_pointers_to_new_format(content, manager, section_alias_map=section_alias_map)
    except Exception as exc:
        logger.warning("Pointer normalization failed for %s: %s", context, exc)
        _record_pointer_migration_error(context, str(exc))
        return content


def normalize_spec_pointers(
    spec_content: str,
    manager: WorkspaceManager,
    section_alias_map: dict[str, dict[str, str]] | None = None,
) -> str:
    """Normalize evidence pointers in spec.md content.

    Legacy `[F####::SECTION]` pointers are converted to
    `[spec_snapshot/relpath::SEC-F####-####]` using the shared migration
    logic from `migrate_pointers_to_new_format`, while multi-hop pointers like
    `[LIB-0001::spec.md::REQ-LIB-0001-0001]` remain unchanged.

    Args:
        spec_content: Raw spec content.
        manager: Workspace manager providing manifest and snapshot context.
        section_alias_map: Optional section alias map for resolving legacy
            section labels to canonical IDs.

    Returns:
        Spec content with normalized evidence pointers.
    """
    return _normalize_pointers(
        spec_content, manager, context="spec.md", section_alias_map=section_alias_map
    )


def normalize_decisions_pointers(
    decisions_content: str,
    manager: WorkspaceManager,
    section_alias_map: dict[str, dict[str, str]] | None = None,
) -> str:
    """Normalize evidence pointers in decisions.md content.

    Converts legacy `[F####::SECTION]` pointers to
    `[spec_snapshot/relpath::SEC-F####-####]` using the shared migration
    logic from `migrate_pointers_to_new_format`, while preserving multi-hop pointers such as
    `[LIB-0001::spec.md::REQ-LIB-0001-0001]`.

    Args:
        decisions_content: Raw decisions content.
        manager: Workspace manager providing manifest and snapshot context.
        section_alias_map: Optional section alias map for resolving legacy
            section labels to canonical IDs.

    Returns:
        Decisions content with normalized evidence pointers.
    """
    return _normalize_pointers(
        decisions_content, manager, context="decisions.md", section_alias_map=section_alias_map
    )


def insert_element_ids(
    spec_content: str, lib_id: str, id_counters: dict[str, int]
) -> tuple[str, int]:
    """Insert stable element IDs. Implementation in Phase 3.

    Args:
        spec_content: Spec content to modify.
        lib_id: Library identifier.
        id_counters: Mutable counters used for ID allocation.

    Returns:
        Tuple of updated spec content and number of IDs assigned.
    """
    updated_content = _ensure_flows_section(spec_content)
    if updated_content != spec_content:
        logger.info("Created missing ## Flows section for %s", lib_id)

    sections = _extract_sections_with_positions(updated_content, level=2)
    if not sections:
        logger.info("Assigned 0 element IDs to %s spec", lib_id)
        return updated_content, 0

    ids_assigned = 0
    rebuilt_parts: list[str] = []
    cursor = 0
    for title, start, end in sections:
        rebuilt_parts.append(updated_content[cursor:start])
        element_type = _get_section_element_type(title)
        if element_type:
            logger.debug("Processing section '%s' with element type %s", title, element_type)
            section_content = updated_content[start:end]
            updated_section, section_ids = _process_id_managed_section(
                section_content, lib_id, element_type, id_counters
            )
            ids_assigned += section_ids
            rebuilt_parts.append(updated_section)
        else:
            rebuilt_parts.append(updated_content[start:end])
        cursor = end

    rebuilt_parts.append(updated_content[cursor:])
    final_content = "".join(rebuilt_parts)
    logger.info("Assigned %s element IDs to %s spec", ids_assigned, lib_id)
    return final_content, ids_assigned


def insert_decision_ids(
    decisions_content: str,
    spec_content: str,
    lib_id: str,
    id_counters: dict[str, int],
) -> tuple[str, int]:
    """Insert stable decision IDs into decisions.md content.

    If decisions_content is empty, extracts decision bullets from the
    spec.md "## Decisions Needed" section. Assigns DEC-LIB-####-#### IDs
    to decision bullets that don't already have stable IDs. Preserves
    existing decision IDs across re-runs.

    Args:
        decisions_content: Current decisions.md content (may be empty).
        spec_content: Spec.md content for decision extraction.
        lib_id: Library identifier (e.g., "LIB-0001").
        id_counters: Mutable counters map for element types.

    Returns:
        Tuple of (updated_decisions_content, number_of_ids_assigned).
    """
    if not decisions_content.strip():
        decisions_content = _extract_decisions_from_spec(spec_content)
        if not decisions_content.strip():
            logger.debug("No decisions found in spec.md for %s", lib_id)
            return "", 0
        decisions_content = _ensure_decisions_header(decisions_content)
        logger.info("Extracted decisions from spec.md for %s", lib_id)

    lines = decisions_content.splitlines(keepends=True)
    updated_lines: list[str] = []
    ids_assigned = 0
    for line in lines:
        line_text = line.rstrip("\r\n")
        line_ending = line[len(line_text) :]
        updated_line, assigned = _process_bullet_line(line_text, lib_id, "DEC", id_counters)
        if assigned:
            ids_assigned += 1
        updated_lines.append(updated_line + line_ending)

    # Future: Structured decision parsing
    # After ID insertion, optionally invoke LLM-based normalization
    # to extract: question, options, default, impact, status
    # This would populate the decisions_index.json with structured fields
    # Agent: glm-decision-normalizer (to be implemented in later phase)

    final_content = "".join(updated_lines)
    logger.info("Assigned %s decision IDs to %s", ids_assigned, lib_id)
    return final_content, ids_assigned


def build_spec_index(spec_content: str, lib_id: str) -> dict[str, Any]:
    """Build spec index. Implementation in Phase 5.

    Args:
        spec_content: Spec content to index.
        lib_id: Library identifier.

    Returns:
        Index payload with minimal schema.
    """
    index = {
        "lib_id": lib_id,
        "generated_at": datetime.now().isoformat(),
        "spec_path": f"libraries/{lib_id}/spec.md",
        "elements": [],
    }

    if not spec_content:
        logger.info("Built spec index for %s with 0 elements", lib_id)
        return index

    try:
        sections = _extract_sections_with_positions(spec_content, level=2)
    except Exception as exc:
        logger.warning("Failed to parse sections for %s spec index: %s", lib_id, exc)
        _record_index_build_error("spec_index", lib_id, str(exc))
        return index

    if not sections:
        logger.info("Built spec index for %s with 0 elements", lib_id)
        return index

    kind_map = {
        "Requirements": "requirement",
        "Flows": "flow",
        "Constraints": "invariant",
        "Dependencies": "invariant",
    }
    bullet_pattern = re.compile(r"^\s*[-*]\s+(.+)$")
    elements: list[dict[str, Any]] = []

    for section_title, start, end in sections:
        element_type = _get_section_element_type(section_title)
        if not element_type:
            continue
        try:
            section_content = spec_content[start:end]
            section_count = 0
            for line in section_content.splitlines():
                if not bullet_pattern.match(line):
                    continue
                element_id = extract_existing_id(line)
                if not element_id:
                    continue
                element = {
                    "element_id": element_id,
                    "kind": kind_map.get(section_title, element_type.lower()),
                    "section": section_title,
                    "text": _remove_element_id_prefix(line).strip(),
                    "raw_line": line,
                    "citations": _extract_citations(line),
                    "mentions_libs": _extract_library_mentions(line, lib_id),
                }
                elements.append(element)
                section_count += 1
            logger.info(
                "Extracted %d elements from %s section for %s",
                section_count,
                section_title,
                lib_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to parse %s section for %s spec index: %s",
                section_title,
                lib_id,
                exc,
            )
            _record_index_build_error(f"spec_index:{section_title}", lib_id, str(exc))
            continue

    index["elements"] = elements
    logger.info("Built spec index for %s with %d elements", lib_id, len(elements))
    return index


def _parse_decision_fields(main_text: str, sub_lines: list[str]) -> dict[str, str]:
    """Parse structured decision fields from decision text.

    Recognizes ``**[FieldName]**: value`` patterns in the main bullet text
    and in sub-bullet lines.  Also recognizes plain ``FieldName: value``
    sub-bullets for known fields (status, context, options, default).

    Args:
        main_text: Text of the main decision bullet (after ID prefix removal).
        sub_lines: Subsequent indented or continuation lines belonging to the
            same decision block.

    Returns:
        Dict mapping lowercase field name to raw string value for recognised
        fields.
    """
    fields: dict[str, str] = {}
    for line in [main_text, *sub_lines]:
        matches = list(_DECISION_FIELD_RE.finditer(line))
        for i, match in enumerate(matches):
            name = match.group(1).lower()
            if name not in _DECISION_FIELD_NAMES:
                continue
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            value = line[start:end].strip()
            if value:
                fields.setdefault(name, value)
        plain = re.match(r"^\s+[-*]\s+(\w+):\s*(.+)$", line)
        if plain:
            name = plain.group(1).lower()
            value = plain.group(2).strip()
            if name in _DECISION_FIELD_NAMES and value:
                fields.setdefault(name, value)
    return fields


def _parse_options_list(raw: str) -> list[str]:
    """Split a comma-separated options string into a list."""
    if not raw:
        return []
    return [opt.strip() for opt in raw.split(",") if opt.strip()]


def _clean_question_text(raw_question: str) -> str:
    """Remove trailing known-field markers from a question string.

    Strips ``**[Status]**:``, ``**[Context]**:``, ``**[Options]**:``, and
    ``**[Default]**:`` suffixes (and their values) so that the question
    contains only the decision question text.
    """
    match = re.search(
        r"\*\*\[(?:Status|Context|Options|Default)\]\*\*:",
        raw_question,
        re.IGNORECASE,
    )
    if match:
        cleaned = raw_question[: match.start()].strip()
        if cleaned:
            return cleaned
    return raw_question


def build_decisions_index(decisions_content: str, lib_id: str) -> dict[str, Any]:
    """Build decisions index with structured field extraction.

    Parses decision bullets and their sub-lines to extract structured
    fields (status, context, options, default) when present.  Recognised
    field patterns are ``**[FieldName]**: value`` on the bullet line or
    sub-bullets, and plain ``FieldName: value`` sub-bullets for the known
    field set.  Fields that are absent fall back to their defaults
    (status ``"open"``, context ``""``, options ``[]``, default ``None``).

    Args:
        decisions_content: Decisions content to index.
        lib_id: Library identifier.

    Returns:
        Index payload with minimal schema.
    """
    index: dict[str, Any] = {
        "lib_id": lib_id,
        "generated_at": datetime.now().isoformat(),
        "decisions_path": f"libraries/{lib_id}/decisions.md",
        "decisions": [],
    }

    if not decisions_content:
        logger.info("Built decisions index for %s with 0 decisions", lib_id)
        return index

    bullet_pattern = re.compile(r"^\s*[-*]\s+(.+)$")
    decisions: list[dict[str, Any]] = []
    try:
        lines = decisions_content.splitlines()

        # Group lines into decision blocks.  Each top-level bullet that
        # carries a decision ID starts a new block; subsequent lines
        # (sub-bullets, continuations) belong to the preceding block.
        blocks: list[tuple[str, list[str]]] = []
        for line in lines:
            is_bullet = bullet_pattern.match(line)
            decision_id = extract_existing_id(line) if is_bullet else None
            if decision_id:
                blocks.append((line, []))
            elif blocks:
                blocks[-1][1].append(line)

        for main_line, sub_lines in blocks:
            decision_id = extract_existing_id(main_line)
            if not decision_id:
                continue

            text = _remove_element_id_prefix(main_line).strip()
            title_match = re.match(r"^\*\*\[Title\]\*\*:\s*(.+)", text)
            question = title_match.group(1).strip() if title_match else text
            question = _clean_question_text(question)

            fields = _parse_decision_fields(text, sub_lines)

            decisions.append(
                {
                    "decision_id": decision_id,
                    "status": fields.get("status", "open"),
                    "question": question,
                    "context": fields.get("context", ""),
                    "options": _parse_options_list(fields.get("options", "")),
                    "default": fields.get("default"),
                    "citations": _extract_citations(main_line),
                }
            )
    except Exception as exc:
        logger.warning("Failed to parse decisions for %s index: %s", lib_id, exc)
        _record_index_build_error("decisions_index", lib_id, str(exc))
        return index

    index["decisions"] = decisions
    logger.info("Built decisions index for %s with %d decisions", lib_id, len(decisions))
    return index


def _collect_ids_from_content(content: str) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for line in content.splitlines():
        element_id = extract_existing_id(line)
        if element_id:
            elements.append({"element_id": element_id})
    return elements


def _validate_counter_values(counters: dict[str, int], lib_id: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for key, value in counters.items():
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(
                {
                    "type": "invalid_counter",
                    "lib_id": lib_id,
                    "counter": key,
                    "error": f"Counter {key} is not an integer.",
                }
            )
            counters[key] = 0
            continue
        if value < 0:
            issues.append(
                {
                    "type": "invalid_counter",
                    "lib_id": lib_id,
                    "counter": key,
                    "error": f"Counter {key} must be non-negative.",
                }
            )
            counters[key] = 0
            continue
        limit = COUNTER_LIMITS.get(key)
        if limit is not None and value > limit:
            issues.append(
                {
                    "type": "counter_overflow",
                    "lib_id": lib_id,
                    "counter": key,
                    "error": f"Counter {key} exceeds limit {limit}.",
                }
            )
    return issues


def _write_json_file(path: Path, payload: dict[str, Any]) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        return str(exc)
    return None


def _count_legacy_pointers(content: str) -> int:
    """Count legacy evidence pointers not using the spec_snapshot prefix.

    Legacy pointers are any `[FILE_REF::SECTION]` pointers whose file
    reference does not begin with `spec_snapshot/`, including multi-hop
    pointers that should remain unchanged.
    """
    if not content:
        return 0
    count = 0
    for match in EVIDENCE_POINTER_RE.finditer(content):
        file_ref = match.group(1).strip()
        if not file_ref.startswith("spec_snapshot/"):
            count += 1
    return count


def _validate_pointers(
    content: str,
    file_manifest: dict[str, dict[str, str]],
    lib_id: str,
    section_alias_map: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Validate evidence pointers resolve to known files and sections.

    Unresolved file references and unresolved section references are
    reported.  Multi-hop pointers (e.g. ``[LIB-0001::spec.md::REQ-...]``)
    are excluded from validation.  When *section_alias_map* is provided,
    section references are resolved through the alias map so that legacy
    labels present only as aliases are not falsely flagged.

    Args:
        content: Markdown content containing evidence pointers.
        file_manifest: Manifest mapping file IDs to relpaths.
        lib_id: Library identifier used for issue reporting.
        section_alias_map: Optional section alias map for resolving legacy
            section labels to canonical section IDs.

    Returns:
        List of issues for pointers with unresolved references.
    """
    if not content:
        return []
    issues: list[dict[str, Any]] = []
    file_id_lookup = build_file_id_lookup(file_manifest)
    for match in EVIDENCE_POINTER_RE.finditer(content):
        pointer = match.group(0)
        parsed = parse_evidence_pointer(pointer, allow_multi_hop=True)
        if not parsed:
            continue
        if "intermediate" in parsed:
            if not parsed.get("intermediate") or not parsed.get("section_ref"):
                issues.append(
                    {
                        "type": "invalid_pointer",
                        "lib_id": lib_id,
                        "pointer": pointer,
                        "message": f"Invalid multi-hop pointer syntax: {pointer}",
                    }
                )
            continue
        file_ref = parsed["file_ref"]
        resolved_file_id = file_id_lookup.get(file_ref)
        if not resolved_file_id:
            issues.append(
                {
                    "type": "unresolved_pointer",
                    "lib_id": lib_id,
                    "pointer": pointer,
                    "file_ref": file_ref,
                    "message": f"Unresolved file reference for pointer: {pointer}",
                }
            )
            continue
        if section_alias_map:
            section_ref = parsed["section_ref"]
            resolved = resolve_section_reference(section_ref, resolved_file_id, section_alias_map)
            if resolved is None:
                issues.append(
                    {
                        "type": "unresolved_section",
                        "lib_id": lib_id,
                        "pointer": pointer,
                        "file_ref": file_ref,
                        "section_ref": section_ref,
                        "message": (f"Unresolved section reference for pointer: {pointer}"),
                    }
                )
    return issues


def validate_library_stabilization(
    spec_content: str,
    decisions_content: str,
    spec_index: dict[str, Any],
    decisions_index: dict[str, Any],
    file_manifest: dict[str, dict[str, str]],
    lib_id: str,
    section_alias_map: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run all stabilization validations and return a combined report."""
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    issues.extend(validate_spec_index_schema(spec_index, lib_id))
    issues.extend(validate_decisions_index_schema(decisions_index, lib_id))
    issues.extend(validate_all_bullets_have_ids(spec_content, lib_id))

    elements: list[SpecElement | Decision | dict[str, Any]] = []
    elements.extend(spec_index.get("elements", []) or [])
    elements.extend(decisions_index.get("decisions", []) or [])
    issues.extend(validate_id_uniqueness(elements, lib_id))

    content_elements: list[dict[str, Any]] = []
    content_elements.extend(_collect_ids_from_content(spec_content))
    content_elements.extend(_collect_ids_from_content(decisions_content))
    issues.extend(validate_id_uniqueness(content_elements, lib_id))

    issues.extend(_validate_pointers(spec_content, file_manifest, lib_id, section_alias_map))
    issues.extend(_validate_pointers(decisions_content, file_manifest, lib_id, section_alias_map))

    return {
        "valid": not issues,
        "issues": issues,
        "warnings": warnings,
    }


def stabilize_specs(
    run_id: str, lib_ids: list[str] | None = None, write_run_index: bool = False
) -> dict[str, Any]:
    """Stabilize spec and decision IDs for all libraries.

    Normalizes legacy evidence pointers to the canonical spec snapshot
    format (preserving multi-hop pointers), validates unresolved file
    references, allocates stable IDs, and emits per-library indexes.

    Args:
        run_id: Run identifier.
        lib_ids: Optional list of library IDs to process.
        write_run_index: Whether to write the aggregate run-level index.

    Returns:
        Result payload with counts, issues, errors, and phase outputs.

    Raises:
        RuntimeError: If the workspace is not initialized or prerequisites are incomplete.
    """
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before spec stabilization.")

    build_status = manager.state.phases[Phase.SPEC_BUILDING.value].status
    if build_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Spec building must be completed before stabilization.")

    libraries_dir = manager.structure.libraries_dir
    if not libraries_dir.exists():
        raise RuntimeError(f"Libraries directory missing: {libraries_dir}")

    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    processed_libs: list[str] = []
    elements_assigned = 0
    decisions_assigned = 0
    elements_indexed = 0
    decisions_indexed = 0
    pointers_migrated_total = 0
    legacy_pointers_remaining_total = 0
    spec_indexes: list[dict[str, Any]] = []

    target_libs: list[Path] = []
    if lib_ids:
        for lib_id in lib_ids:
            if not lib_id:
                continue
            lib_dir = libraries_dir / lib_id
            if not lib_dir.exists() or not lib_dir.is_dir():
                errors.append({"lib_id": lib_id, "error": "Library directory not found."})
                continue
            target_libs.append(lib_dir)
    else:
        target_libs = [lib_dir for lib_dir in sorted(libraries_dir.iterdir()) if lib_dir.is_dir()]

    if not target_libs:
        issues.append({"type": "no_libraries", "message": "No libraries found to stabilize."})

    section_alias_map = build_section_alias_map(manager.state.section_manifest)

    for lib_dir in target_libs:
        lib_id = lib_dir.name
        processed_libs.append(lib_id)

        counters, counter_errors = _load_id_counters_with_issues(lib_dir)
        for error in counter_errors:
            errors.append({"lib_id": lib_id, "error": error.get("error", "id counter error")})

        counter_issues = _validate_counter_values(counters, lib_id)
        if counter_issues:
            errors.extend(counter_issues)

        spec_path = lib_dir / "spec.md"
        spec_content = ""
        spec_exists = spec_path.exists()
        spec_read_failed = False
        if not spec_exists:
            issues.append(
                {
                    "type": "missing_spec",
                    "lib_id": lib_id,
                    "message": "spec.md missing for library.",
                }
            )
        else:
            try:
                spec_content = spec_path.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append({"lib_id": lib_id, "error": f"Failed to read spec.md: {exc}"})
                spec_read_failed = True

        decisions_path = lib_dir / "decisions.md"
        decisions_content = ""
        decisions_read_failed = False
        if decisions_path.exists():
            try:
                decisions_content = decisions_path.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append({"lib_id": lib_id, "error": f"Failed to read decisions.md: {exc}"})
                decisions_read_failed = True
        else:
            try:
                decisions_path.write_text("", encoding="utf-8")
                issues.append(
                    {
                        "type": "decisions_created",
                        "lib_id": lib_id,
                        "message": "decisions.md missing; created empty file.",
                    }
                )
            except OSError as exc:
                errors.append({"lib_id": lib_id, "error": f"Failed to create decisions.md: {exc}"})

        legacy_before_spec = _count_legacy_pointers(spec_content)
        legacy_before_decisions = _count_legacy_pointers(decisions_content)

        normalized_spec = normalize_spec_pointers(spec_content, manager, section_alias_map)
        normalized_decisions = normalize_decisions_pointers(
            decisions_content, manager, section_alias_map
        )

        for error in _consume_pointer_migration_errors():
            issues.append(
                {
                    "type": "pointer_migration_failed",
                    "lib_id": lib_id,
                    "context": error["context"],
                    "message": (
                        f"Pointer migration failed for {error['context']}: {error['error']}"
                    ),
                }
            )

        legacy_after_spec = _count_legacy_pointers(normalized_spec)
        legacy_after_decisions = _count_legacy_pointers(normalized_decisions)
        migrated_count = (legacy_before_spec + legacy_before_decisions) - (
            legacy_after_spec + legacy_after_decisions
        )
        pointers_migrated_total += migrated_count
        legacy_pointers_remaining_total += legacy_after_spec + legacy_after_decisions
        logger.info("Migrated %s pointers in %s", migrated_count, lib_id)

        normalized_spec, assigned_elements = insert_element_ids(normalized_spec, lib_id, counters)
        normalized_decisions, assigned_decisions = insert_decision_ids(
            normalized_decisions, normalized_spec, lib_id, counters
        )

        elements_assigned += assigned_elements
        decisions_assigned += assigned_decisions

        if spec_exists and not spec_read_failed:
            try:
                spec_path.write_text(normalized_spec, encoding="utf-8")
            except OSError as exc:
                errors.append({"lib_id": lib_id, "error": f"Failed to write spec.md: {exc}"})

        if not decisions_read_failed:
            try:
                decisions_path.write_text(normalized_decisions, encoding="utf-8")
            except OSError as exc:
                errors.append({"lib_id": lib_id, "error": f"Failed to write decisions.md: {exc}"})

        try:
            save_id_counters(lib_dir, counters)
        except OSError as exc:
            errors.append({"lib_id": lib_id, "error": f"Failed to save id_counters.json: {exc}"})

        try:
            spec_index = build_spec_index(normalized_spec, lib_id)
        except Exception as exc:
            issues.append(
                {
                    "type": "spec_index_failed",
                    "lib_id": lib_id,
                    "message": f"Spec index build failed: {exc}",
                }
            )
            spec_index = {
                "lib_id": lib_id,
                "generated_at": datetime.now().isoformat(),
                "spec_path": f"libraries/{lib_id}/spec.md",
                "elements": [],
            }

        try:
            decisions_index = build_decisions_index(normalized_decisions, lib_id)
        except Exception as exc:
            issues.append(
                {
                    "type": "decisions_index_failed",
                    "lib_id": lib_id,
                    "message": f"Decisions index build failed: {exc}",
                }
            )
            decisions_index = {
                "lib_id": lib_id,
                "generated_at": datetime.now().isoformat(),
                "decisions_path": f"libraries/{lib_id}/decisions.md",
                "decisions": [],
            }

        for error in _consume_index_build_errors():
            issues.append(
                {
                    "type": "index_build_failed",
                    "lib_id": error["lib_id"],
                    "context": error["context"],
                    "message": f"Index build failed for {error['context']}: {error['error']}",
                }
            )

        validation_report = validate_library_stabilization(
            normalized_spec,
            normalized_decisions,
            spec_index,
            decisions_index,
            manager.state.file_manifest,
            lib_id,
            section_alias_map,
        )
        issues.extend(validation_report["issues"])
        issues.extend(validation_report["warnings"])

        spec_indexes.append(spec_index)

        spec_index_path = lib_dir / "spec_index.json"
        decisions_index_path = lib_dir / "decisions_index.json"
        spec_error = _write_json_file(spec_index_path, spec_index)
        if spec_error:
            errors.append(
                {
                    "lib_id": lib_id,
                    "error": f"Failed to write spec_index.json: {spec_error}",
                }
            )
        decisions_error = _write_json_file(decisions_index_path, decisions_index)
        if decisions_error:
            errors.append(
                {
                    "lib_id": lib_id,
                    "error": f"Failed to write decisions_index.json: {decisions_error}",
                }
            )

        elements_indexed += len(spec_index.get("elements", []))
        decisions_indexed += len(decisions_index.get("decisions", []))

    if write_run_index:
        logger.info("Writing run-level spec index for %s", run_id)
        run_index = {
            "generated_at": datetime.now().isoformat(),
            "libraries": spec_indexes,
        }
        run_index_path = manager.structure.indexes_dir / "library_spec_index.json"
        run_index_error = _write_json_file(run_index_path, run_index)
        if run_index_error:
            errors.append(
                {
                    "error": f"Failed to write run-level spec index: {run_index_error}",
                }
            )
        else:
            logger.info("Wrote run-level spec index for %s", run_id)

    phase_result = manager.state.phases[Phase.SPEC_BUILDING.value]
    phase_result.issues.extend(errors + issues)

    stabilized = not errors and bool(processed_libs)
    validation_metrics = collect_validation_metrics(issues)
    validation_issues_count = sum(validation_metrics.values())
    outputs = {
        "specs_stabilized": stabilized,
        "libraries_processed": len(processed_libs),
        "elements_assigned": elements_assigned,
        "decisions_assigned": decisions_assigned,
        "elements_indexed": elements_indexed,
        "decisions_indexed": decisions_indexed,
        "pointers_migrated": pointers_migrated_total,
        "legacy_pointers_remaining": legacy_pointers_remaining_total,
        "validation_issues_count": validation_issues_count,
        "spec_index": "workspace/indexes/library_spec_index.json" if write_run_index else None,
    }
    if stabilized:
        manager.complete_phase(Phase.SPEC_BUILDING, outputs=outputs)

    return {
        "success": not errors,
        "libraries_processed": len(processed_libs),
        "elements_assigned": elements_assigned,
        "decisions_assigned": decisions_assigned,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }

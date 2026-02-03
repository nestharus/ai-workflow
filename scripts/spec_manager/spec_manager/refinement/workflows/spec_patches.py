"""Patch operation parsing, validation, and application for spec building.

Supports stable element ID preservation when specs have been stabilized.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from spec_manager.refinement.formats import (
    EVIDENCE_POINTER_RE,
    _extract_json_payload,
    _record_json_extraction_evidence,
)
from spec_manager.refinement.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    resolve_section_reference,
)

from .spec_stabilization import extract_existing_id

VALID_SPEC_SECTIONS = [
    "Intent",
    "Boundaries",
    "Requirements",
    "Constraints",
    "Dependencies",
    "Decisions Needed",
]

CITATION_REQUIRED_SECTIONS = {"Boundaries", "Requirements", "Constraints", "Dependencies"}


@dataclass
class PatchOperation:
    """A single patch operation for modifying a spec document."""

    op: Literal["add", "move", "edit"]
    section: str
    bullet_index: int | None
    content: str
    citations: list[str]
    source_section: str | None = None


@dataclass
class SpecPatchSet:
    """A set of patch operations for a library specification."""

    lib_id: str
    file_id: str
    operations: list[PatchOperation]


class SpecDocument:
    """Parsed spec document sections with bullet-aware helpers."""

    def __init__(self, content: str) -> None:
        """Initialize a parsed spec document.

        Args:
            content: The full spec document content as markdown.
        """
        from . import spec_building

        sections = spec_building._extract_sections(content, level=2)
        self.section_order = list(sections.keys())
        self.section_lines = {name: self._split_lines(text) for name, text in sections.items()}

    def get_lines(self, section: str) -> list[str]:
        """Return all lines for a given section, or empty list if section doesn't exist."""
        if section in self.section_lines:
            return self.section_lines[section]
        return []

    def count_bullets(self, section: str) -> int:
        """Count the number of bullet lines in a section."""
        return sum(1 for line in self.get_lines(section) if _is_bullet_line(line))

    def bullet_line_indices(self, section: str) -> list[int]:
        """Return the list indices of all bullet lines in a section."""
        return [
            index for index, line in enumerate(self.get_lines(section)) if _is_bullet_line(line)
        ]

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        if not text:
            return []
        return [line.rstrip() for line in text.splitlines()]


def validate_patch_operation(op: PatchOperation, valid_sections: list[str]) -> list[str]:
    """Validate a patch operation.

    Args:
        op: The patch operation to validate.
        valid_sections: List of valid section names.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors: list[str] = []
    if op.op not in {"add", "move", "edit"}:
        errors.append(f"Invalid op '{op.op}'.")
    if op.section not in valid_sections:
        errors.append(f"Invalid section '{op.section}'.")
    if op.bullet_index is not None and op.bullet_index < 0:
        errors.append("bullet_index must be non-negative when provided.")
    if op.op == "edit" and op.bullet_index is None:
        errors.append("edit operations require bullet_index.")
    if op.op == "move":
        if op.source_section is None:
            errors.append("move operations require source_section.")
        if op.bullet_index is None:
            errors.append("move operations require bullet_index.")
        if op.source_section is not None and op.source_section not in valid_sections:
            errors.append(f"Invalid source_section '{op.source_section}'.")
    content_stripped = op.content.strip()
    if op.op in {"add", "edit"} and not content_stripped:
        errors.append("content must be non-empty for add/edit operations.")
    if op.op == "move" and op.content != "" and not content_stripped:
        errors.append("content must be non-empty when provided for move operations.")
    for citation in op.citations:
        if not EVIDENCE_POINTER_RE.fullmatch(citation.strip()):
            errors.append(f"Invalid citation '{citation}'.")
    return errors


def parse_patch_json(json_str: str, evidence: list[dict[str, Any]] | None = None) -> SpecPatchSet:
    """Parse patch JSON into a structured SpecPatchSet.

    Args:
        json_str: JSON string containing patch operations.
        evidence: Optional list to record extraction evidence.

    Returns:
        Parsed SpecPatchSet with lib_id, file_id, and operations.
    """
    extracted = _extract_json_payload(json_str)
    _record_json_extraction_evidence(json_str, extracted, evidence, location="parse_patch_json")
    data = json.loads(extracted)
    if isinstance(data, dict):
        operations_data = data.get("operations")
        if operations_data is None:
            raise ValueError("Missing 'operations' in patch JSON.")
        lib_id_value = data.get("lib_id")
        lib_id = lib_id_value if isinstance(lib_id_value, str) else "unknown"
        file_id_value = data.get("file_id")
        file_id = file_id_value if isinstance(file_id_value, str) else "unknown"
    elif isinstance(data, list):
        operations_data = data
        lib_id = "unknown"
        file_id = "unknown"
    else:
        raise TypeError("Expected JSON array or object for patch output.")

    if not isinstance(operations_data, list):
        raise TypeError("Patch operations must be a JSON array.")

    operations: list[PatchOperation] = []
    for item in operations_data:
        if not isinstance(item, dict):
            raise TypeError("Patch operation entries must be JSON objects.")
        op_value = item.get("op", "")
        op = op_value.strip().lower() if isinstance(op_value, str) else ""
        section = item.get("section", "")
        if not isinstance(section, str):
            section = ""
        bullet_index_raw = item.get("bullet_index")
        bullet_index = _coerce_bullet_index(bullet_index_raw)
        content = item.get("content", "")
        if not isinstance(content, str):
            content = ""
        citations = item.get("citations", [])
        citations = _coerce_citations(citations)
        source_section = item.get("source_section")
        if source_section is not None and not isinstance(source_section, str):
            source_section = None
        operations.append(
            PatchOperation(
                op=op,  # type: ignore[arg-type]
                section=section,
                bullet_index=bullet_index,
                content=content,
                citations=citations,
                source_section=source_section,
            )
        )

    return SpecPatchSet(lib_id=lib_id, file_id=file_id, operations=operations)


def apply_patch(spec_doc: SpecDocument, operation: PatchOperation) -> None:
    """Apply a patch operation to a spec document.

    Preserves existing element IDs (REQ-/FLOW-/INV-/DEC-) when editing or moving bullets.

    Args:
        spec_doc: The spec document to modify.
        operation: The patch operation to apply.

    Raises:
        ValueError: If the operation is invalid or requires missing fields.
    """
    if operation.op == "add":
        lines = list(spec_doc.get_lines(operation.section))
        _append_bullet_line(lines, _compose_bullet_line(operation, original_line=None))
        spec_doc.section_lines[operation.section] = lines
        if operation.section not in spec_doc.section_order:
            spec_doc.section_order.append(operation.section)
        return

    if operation.op == "edit":
        lines = list(spec_doc.get_lines(operation.section))
        line_index = _resolve_bullet_line_index(lines, operation.bullet_index)
        original_line = lines[line_index]
        lines[line_index] = _compose_bullet_line(operation, original_line=original_line)
        spec_doc.section_lines[operation.section] = lines
        if operation.section not in spec_doc.section_order:
            spec_doc.section_order.append(operation.section)
        return

    if operation.op == "move":
        if operation.source_section is None:
            raise ValueError("move operations require source_section.")
        source_lines = list(spec_doc.get_lines(operation.source_section))
        dest_lines = list(spec_doc.get_lines(operation.section))
        line_index = _resolve_bullet_line_index(source_lines, operation.bullet_index)
        moved_line = source_lines.pop(line_index)
        if operation.content.strip():
            bullet_line = _compose_bullet_line(operation, original_line=moved_line)
        else:
            bullet_line = moved_line
        _append_bullet_line(dest_lines, bullet_line)
        spec_doc.section_lines[operation.source_section] = source_lines
        spec_doc.section_lines[operation.section] = dest_lines
        if operation.section not in spec_doc.section_order:
            spec_doc.section_order.append(operation.section)
        if operation.source_section not in spec_doc.section_order:
            spec_doc.section_order.append(operation.source_section)
        return

    raise ValueError(f"Unsupported patch op: {operation.op}")


def render_spec(spec_doc: SpecDocument, lib_id: str) -> str:
    """Render a spec document to markdown.

    Args:
        spec_doc: The spec document to render.
        lib_id: The library ID for the header.

    Returns:
        Markdown representation of the spec document.
    """
    lines = [f"# Library Spec: {lib_id}", ""]
    remaining_sections = set(spec_doc.section_lines.keys())
    for section in VALID_SPEC_SECTIONS:
        lines.append(f"## {section}")
        content_lines = spec_doc.get_lines(section)
        if content_lines:
            lines.extend(content_lines)
        lines.append("")
        remaining_sections.discard(section)

    for section in spec_doc.section_order:
        if section not in remaining_sections:
            continue
        lines.append(f"## {section}")
        content_lines = spec_doc.get_lines(section)
        if content_lines:
            lines.extend(content_lines)
        lines.append("")
        remaining_sections.discard(section)

    return "\n".join(lines).rstrip() + "\n"


def validate_patch_citations(
    operations: list[PatchOperation],
    file_id_lookup: dict[str, str],
    section_alias_map: dict[str, dict[str, str]],
    *,
    lib_id: str,
) -> list[dict[str, Any]]:
    """Validate evidence pointers in patch operations.

    Args:
        operations: List of patch operations to validate.
        file_id_lookup: Mapping from file references to canonical file IDs.
        section_alias_map: Mapping from file IDs to section alias dictionaries.
        lib_id: Library ID for error reporting.

    Returns:
        List of validation issues (empty if valid).
    """
    file_id_lookup = _ensure_file_id_lookup(file_id_lookup)
    section_alias_map = _ensure_section_alias_map(section_alias_map)
    issues: list[dict[str, Any]] = []
    pointer_seen = False
    requires_evidence_pointers = False

    for operation in operations:
        if (
            operation.op in {"add", "edit", "move"}
            and operation.section in CITATION_REQUIRED_SECTIONS
            and not (operation.op == "move" and not operation.content.strip())
        ):
            requires_evidence_pointers = True
        if (
            operation.op in {"add", "edit", "move"}
            and operation.section in CITATION_REQUIRED_SECTIONS
            and not operation.citations
        ):
            issues.append(
                {
                    "type": "missing_citation",
                    "lib_id": lib_id,
                    "section": operation.section,
                    "line": operation.content.strip(),
                    "message": "Bullet missing evidence pointer.",
                }
            )

        for citation in operation.citations:
            match = EVIDENCE_POINTER_RE.fullmatch(citation.strip())
            if not match:
                issues.append(
                    {
                        "type": "invalid_evidence_pointer",
                        "lib_id": lib_id,
                        "pointer": citation,
                        "message": "Citation is not a valid evidence pointer.",
                    }
                )
                continue

            pointer_seen = True
            file_ref = match.group(1).strip()
            section_ref = match.group(2).strip()
            resolved_file_id = file_id_lookup.get(file_ref)
            if resolved_file_id is None:
                issues.append(
                    {
                        "type": "unknown_file_reference",
                        "lib_id": lib_id,
                        "pointer": citation,
                        "message": f"Unknown file reference: {file_ref}",
                    }
                )
                continue

            canonical_section = resolve_section_reference(
                section_ref,
                resolved_file_id,
                section_alias_map,
            )
            if canonical_section is None:
                issues.append(
                    {
                        "type": "unknown_section_reference",
                        "lib_id": lib_id,
                        "pointer": citation,
                        "message": (
                            f"Unknown section reference: {section_ref} (file: {resolved_file_id})"
                        ),
                    }
                )

    if not pointer_seen and requires_evidence_pointers:
        issues.append(
            {
                "type": "missing_evidence_pointers",
                "lib_id": lib_id,
                "message": "No evidence pointers found.",
            }
        )

    return issues


def _coerce_bullet_index(value: int | str | None) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _ensure_file_id_lookup(
    file_id_lookup: dict[str, str] | dict[str, dict[str, str]],
) -> dict[str, str]:
    if not file_id_lookup:
        return {}
    values = list(file_id_lookup.values())
    if values and all(isinstance(value, dict) for value in values):
        return build_file_id_lookup(file_id_lookup)  # type: ignore[arg-type]
    if values and all(
        isinstance(value, str) and value.startswith("F") and value[1:].isdigit() for value in values
    ):
        return file_id_lookup  # type: ignore[return-value]
    legacy_manifest: dict[str, dict[str, str]] = {}
    for file_id, value in file_id_lookup.items():
        if isinstance(value, str):
            relpath = value
            sha256 = ""
        elif isinstance(value, dict):
            relpath = value.get("relpath", "")
            sha256 = value.get("sha256", "")
        else:
            continue
        if not isinstance(relpath, str) or not relpath:
            continue
        legacy_manifest[file_id] = {
            "relpath": relpath,
            "sha256": sha256 if isinstance(sha256, str) else "",
        }
    return build_file_id_lookup(legacy_manifest)


def _ensure_section_alias_map(
    section_alias_map: dict[str, dict[str, str]] | dict[str, list[str]],
) -> dict[str, dict[str, str]]:
    if not section_alias_map:
        return {}
    first_value = next(iter(section_alias_map.values()))
    if isinstance(first_value, list):
        return build_section_alias_map(section_alias_map)  # type: ignore[arg-type]
    return section_alias_map  # type: ignore[return-value]


def _coerce_citations(value: str | list[str] | list[object] | None) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _is_bullet_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("-") or stripped.startswith("*")


def _extract_id_prefix(line: str) -> str | None:
    """Extract element ID prefix from a bullet line if present.

    Args:
        line: Bullet line to check.

    Returns:
        Element ID string (e.g., "REQ-LIB-0001-0001") or None.
    """
    existing_id = extract_existing_id(line)
    return existing_id


def _is_stabilization_enabled(spec_doc: SpecDocument) -> bool:
    """Check if spec stabilization has been run (IDs should be preserved).

    This is a heuristic check - if any bullet in Requirements/Constraints/Dependencies
    sections has an element ID, we assume stabilization has run.

    Args:
        spec_doc: The spec document to check.

    Returns:
        True if stabilization appears to have run, False otherwise.
    """
    id_managed_sections = ["Requirements", "Constraints", "Dependencies", "Flows"]
    for section in id_managed_sections:
        lines = spec_doc.get_lines(section)
        for line in lines:
            if _is_bullet_line(line) and extract_existing_id(line):
                return True
    return False


def _resolve_bullet_line_index(lines: list[str], bullet_index: int | None) -> int:
    if bullet_index is None:
        raise ValueError("bullet_index is required for this operation.")
    bullet_lines = [index for index, line in enumerate(lines) if _is_bullet_line(line)]
    if bullet_index < 0 or bullet_index >= len(bullet_lines):
        raise ValueError("bullet_index is out of range.")
    return bullet_lines[bullet_index]


def _compose_bullet_line(operation: PatchOperation, original_line: str | None = None) -> str:
    """Compose a bullet line from patch operation, preserving existing IDs.

    Args:
        operation: The patch operation containing new content.
        original_line: The original bullet line (for edit/move ops) to extract ID from.

    Returns:
        Formatted bullet line with ID preserved if present.
    """
    content = operation.content.strip()

    # Extract existing ID from original line if provided
    existing_id = None
    if original_line:
        existing_id = _extract_id_prefix(original_line)

    # Add citations that aren't already in content
    citations = [citation.strip() for citation in operation.citations if citation.strip()]
    for citation in citations:
        if citation not in content:
            content = f"{content} {citation}" if content else citation

    if not content:
        raise ValueError("Bullet content cannot be empty.")

    # Prepend existing ID if found
    if existing_id:
        # Remove ID from content if agent accidentally included it
        content_without_id = content
        if content.startswith(f"{existing_id}:"):
            content_without_id = content[len(existing_id) + 1 :].strip()
        return f"- {existing_id}: {content_without_id}".rstrip()

    return f"- {content}".rstrip()


def _append_bullet_line(lines: list[str], bullet_line: str) -> None:
    if lines:
        last = lines[-1].strip()
        if last and not _is_bullet_line(lines[-1]):
            lines.append("")
    lines.append(bullet_line)

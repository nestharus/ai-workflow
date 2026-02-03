"""Spec stabilization workflow for Phase 4 outputs.

This module normalizes spec pointers, assigns stable element IDs, persists
per-library counters, and builds indexes to support downstream phases.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager

DEFAULT_COUNTERS: dict[str, int] = {"REQ": 0, "FLOW": 0, "INV": 0, "DEC": 0}
COUNTER_LIMITS: dict[str, int] = {"REQ": 9999, "FLOW": 99, "INV": 9999, "DEC": 9999}
ELEMENT_ID_RE = re.compile(r"^\s*-\s*((?:REQ|FLOW|INV|DEC)-LIB-\d{4}-\d+):\s*")


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


def validate_id_uniqueness(elements: list[dict[str, Any]], lib_id: str) -> list[dict[str, Any]]:
    """Validate that element IDs are unique within a library.

    Args:
        elements: List of element metadata dicts.
        lib_id: Library identifier.

    Returns:
        List of validation issues.
    """
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in elements:
        element_id = element.get("element_id") or element.get("id")
        if not isinstance(element_id, str) or not element_id:
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


def normalize_spec_pointers(
    spec_content: str, file_manifest: dict[str, Any], section_manifest: dict[str, Any]
) -> str:
    """Normalize pointers in spec.md. Implementation in Phase 2.

    Args:
        spec_content: Raw spec content.
        file_manifest: File manifest for pointer resolution.
        section_manifest: Section manifest for pointer resolution.

    Returns:
        Spec content with normalized pointers.
    """
    return spec_content


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
    return spec_content, 0


def insert_decision_ids(
    decisions_content: str, lib_id: str, id_counters: dict[str, int]
) -> tuple[str, int]:
    """Insert decision IDs. Implementation in Phase 4.

    Args:
        decisions_content: Decisions content to modify.
        lib_id: Library identifier.
        id_counters: Mutable counters used for ID allocation.

    Returns:
        Tuple of updated decisions content and number of IDs assigned.
    """
    return decisions_content, 0


def build_spec_index(spec_content: str, lib_id: str) -> dict[str, Any]:
    """Build spec index. Implementation in Phase 5.

    Args:
        spec_content: Spec content to index.
        lib_id: Library identifier.

    Returns:
        Index payload with minimal schema.
    """
    return {
        "lib_id": lib_id,
        "generated_at": datetime.now().isoformat(),
        "elements": [],
    }


def build_decisions_index(decisions_content: str, lib_id: str) -> dict[str, Any]:
    """Build decisions index. Implementation in Phase 5.

    Args:
        decisions_content: Decisions content to index.
        lib_id: Library identifier.

    Returns:
        Index payload with minimal schema.
    """
    return {
        "lib_id": lib_id,
        "generated_at": datetime.now().isoformat(),
        "decisions": [],
    }


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


def stabilize_specs(
    run_id: str, lib_ids: list[str] | None = None, write_run_index: bool = False
) -> dict[str, Any]:
    """Stabilize spec and decision IDs for all libraries.

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
                errors.append(
                    {"lib_id": lib_id, "error": f"Failed to create decisions.md: {exc}"}
                )

        normalized_spec = normalize_spec_pointers(
            spec_content,
            manager.state.file_manifest,
            manager.state.section_manifest,
        )
        normalized_spec, assigned_elements = insert_element_ids(
            normalized_spec, lib_id, counters
        )
        normalized_decisions, assigned_decisions = insert_decision_ids(
            decisions_content, lib_id, counters
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
                errors.append(
                    {"lib_id": lib_id, "error": f"Failed to write decisions.md: {exc}"}
                )

        try:
            save_id_counters(lib_dir, counters)
        except OSError as exc:
            errors.append({"lib_id": lib_id, "error": f"Failed to save id_counters.json: {exc}"})

        spec_index = build_spec_index(normalized_spec, lib_id)
        decisions_index = build_decisions_index(normalized_decisions, lib_id)
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

        elements = _collect_ids_from_content(normalized_spec)
        elements.extend(_collect_ids_from_content(normalized_decisions))
        issues.extend(validate_id_uniqueness(elements, lib_id))

    if write_run_index:
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

    phase_result = manager.state.phases[Phase.SPEC_BUILDING.value]
    phase_result.issues.extend(errors + issues)

    stabilized = not errors and bool(processed_libs)
    outputs = {
        "specs_stabilized": stabilized,
        "libraries_processed": len(processed_libs),
        "elements_assigned": elements_assigned,
        "decisions_assigned": decisions_assigned,
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

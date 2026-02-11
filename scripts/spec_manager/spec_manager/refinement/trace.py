"""Helpers for loading trace indexes and formatting trace reports."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.workflows.trace_indexes import (
    ATOM_ID_RE,
    ELEMENT_ID_RE,
    SECTION_ID_RE,
    TASK_ID_RE,
)
from spec_manager.refinement.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> Any:
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(f"Missing trace index: {path}") from exc
    return json.loads(payload)


def _resolve_index_path(raw_path: str, manager: WorkspaceManager) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = manager.structure.root / path
    return path


def _normalize_patch_path(patch_path: str | None, manager: WorkspaceManager) -> str:
    if not isinstance(patch_path, str) or not patch_path:
        return "(patch missing)"
    path = Path(patch_path)
    if path.is_absolute():
        try:
            return path.relative_to(manager.structure.root).as_posix()
        except ValueError:
            return path.as_posix()
    return patch_path


def _format_patch_line(
    task_id: str,
    patch_info: dict[str, Any] | None,
    manager: WorkspaceManager,
    indent: str,
    include_task_id: bool,
) -> str:
    if not isinstance(patch_info, dict):
        logger.warning("Patch info missing for task %s", task_id)
        label = f"{task_id}: (patch missing)" if include_task_id else "Patch: (patch missing)"
        return f"{indent}- {label}"
    patch_path = _normalize_patch_path(patch_info.get("patch_path"), manager)
    if patch_path == "(patch missing)":
        logger.warning("Patch path missing for task %s", task_id)
    status = patch_info.get("status")
    status_text = f" (status: {status})" if isinstance(status, str) and status.strip() else ""
    label = f"{task_id}: {patch_path}" if include_task_id else f"Patch: {patch_path}"
    return f"{indent}- {label}{status_text}"


def _collect_element_sources(
    element_id: str,
    section_to_elements: dict[str, Any],
) -> tuple[list[tuple[str, str, str]], tuple[str, str] | None]:
    sources: list[tuple[str, str, str]] = []
    element_meta: tuple[str, str] | None = None
    for section_id, entries in section_to_elements.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("element_id") != element_id:
                continue
            lib_id = entry.get("lib_id") if isinstance(entry.get("lib_id"), str) else "unknown"
            kind = entry.get("kind") if isinstance(entry.get("kind"), str) else "unknown"
            sources.append((section_id, lib_id, kind))
            if element_meta is None:
                element_meta = (lib_id, kind)
    return sources, element_meta


def load_trace_indexes(manager: WorkspaceManager) -> dict[str, Any]:
    """Load trace indexes referenced by the workspace trace index."""
    trace_index_path = manager.structure.indexes_dir / "trace_index.json"
    trace_index = _read_json(trace_index_path)
    indexes = trace_index.get("indexes") if isinstance(trace_index, dict) else None
    if not isinstance(indexes, dict):
        raise json.JSONDecodeError("Trace index missing 'indexes' key", json.dumps(trace_index), 0)

    index_paths = {
        "atom_to_section": indexes.get("atom_to_section"),
        "section_to_spec_elements": indexes.get("section_to_spec_elements"),
        "spec_element_to_tasks": indexes.get("spec_element_to_tasks"),
        "task_to_patches": indexes.get("task_to_patches"),
    }

    loaded: dict[str, Any] = {}
    for key, raw_path in index_paths.items():
        if not isinstance(raw_path, str) or not raw_path:
            raise FileNotFoundError(f"Trace index missing path for {key}")
        path = _resolve_index_path(raw_path, manager)
        loaded[key] = _read_json(path)

    return {
        "atom_to_section": loaded["atom_to_section"],
        "section_to_elements": loaded["section_to_spec_elements"],
        "element_to_tasks": loaded["spec_element_to_tasks"],
        "task_to_patches": loaded["task_to_patches"],
    }


def format_atom_trace(
    atom_id: str, indexes: dict[str, Any], manager: WorkspaceManager
) -> str | None:
    if not ATOM_ID_RE.fullmatch(atom_id):
        return None
    atom_to_section = indexes.get("atom_to_section")
    if not isinstance(atom_to_section, dict):
        return None
    atom_entry = atom_to_section.get(atom_id)
    if not isinstance(atom_entry, dict):
        return None

    file_id = atom_entry.get("file_id") if isinstance(atom_entry.get("file_id"), str) else "unknown"
    section_id = (
        atom_entry.get("section_id") if isinstance(atom_entry.get("section_id"), str) else "unknown"
    )
    sha256 = atom_entry.get("sha256") if isinstance(atom_entry.get("sha256"), str) else "unknown"

    section_to_elements = indexes.get("section_to_elements")
    elements = section_to_elements.get(section_id) if isinstance(section_to_elements, dict) else []
    if not isinstance(elements, list):
        elements = []

    element_to_tasks = indexes.get("element_to_tasks")
    task_to_patches = indexes.get("task_to_patches")
    if not isinstance(element_to_tasks, dict):
        element_to_tasks = {}
    if not isinstance(task_to_patches, dict):
        task_to_patches = {}

    lines = [
        f"# Trace: {atom_id}",
        "",
        f"**Atom**: {atom_id}",
        f"- File: {file_id}",
        f"- Section: {section_id}",
        f"- SHA256: {sha256}",
        "",
        f"**Spec Elements** ({len(elements)}):",
    ]

    for entry in elements:
        if not isinstance(entry, dict):
            continue
        lib_id = entry.get("lib_id") if isinstance(entry.get("lib_id"), str) else "unknown"
        element_id = entry.get("element_id") if isinstance(entry.get("element_id"), str) else ""
        kind = entry.get("kind") if isinstance(entry.get("kind"), str) else "unknown"
        if not element_id:
            continue
        lines.append(f"- {lib_id}/{element_id} ({kind})")
        tasks = element_to_tasks.get(element_id, [])
        if not isinstance(tasks, list):
            tasks = []
        task_ids = sorted({task for task in tasks if isinstance(task, str)})
        task_list = ", ".join(task_ids) if task_ids else "none"
        lines.append(f"  - Tasks: {task_list}")
        for task_id in task_ids:
            patch_info = task_to_patches.get(task_id)
            lines.append(
                _format_patch_line(
                    task_id, patch_info, manager, indent="    ", include_task_id=True
                )
            )

    return "\n".join(lines)


def format_section_trace(
    section_id: str, indexes: dict[str, Any], manager: WorkspaceManager
) -> str | None:
    if not SECTION_ID_RE.fullmatch(section_id):
        return None
    section_to_elements = indexes.get("section_to_elements")
    if not isinstance(section_to_elements, dict):
        return None
    elements = section_to_elements.get(section_id)
    if not isinstance(elements, list):
        return None

    element_to_tasks = indexes.get("element_to_tasks")
    task_to_patches = indexes.get("task_to_patches")
    if not isinstance(element_to_tasks, dict):
        element_to_tasks = {}
    if not isinstance(task_to_patches, dict):
        task_to_patches = {}

    lines = [
        f"# Trace: {section_id}",
        "",
        f"**Section**: {section_id}",
        "",
        f"**Spec Elements** ({len(elements)}):",
    ]

    for entry in elements:
        if not isinstance(entry, dict):
            continue
        lib_id = entry.get("lib_id") if isinstance(entry.get("lib_id"), str) else "unknown"
        element_id = entry.get("element_id") if isinstance(entry.get("element_id"), str) else ""
        kind = entry.get("kind") if isinstance(entry.get("kind"), str) else "unknown"
        if not element_id:
            continue
        lines.append(f"- {lib_id}/{element_id} ({kind})")
        tasks = element_to_tasks.get(element_id, [])
        if not isinstance(tasks, list):
            tasks = []
        task_ids = sorted({task for task in tasks if isinstance(task, str)})
        task_list = ", ".join(task_ids) if task_ids else "none"
        lines.append(f"  - Tasks: {task_list}")
        for task_id in task_ids:
            patch_info = task_to_patches.get(task_id)
            lines.append(
                _format_patch_line(
                    task_id, patch_info, manager, indent="    ", include_task_id=True
                )
            )

    return "\n".join(lines)


def format_element_trace(
    element_id: str, indexes: dict[str, Any], manager: WorkspaceManager
) -> str | None:
    if not ELEMENT_ID_RE.fullmatch(element_id):
        return None

    section_to_elements = indexes.get("section_to_elements")
    if not isinstance(section_to_elements, dict):
        section_to_elements = {}

    sources, _ = _collect_element_sources(element_id, section_to_elements)
    sources = sorted(set(sources), key=lambda item: (item[0], item[1], item[2]))

    element_to_tasks = indexes.get("element_to_tasks")
    if not isinstance(element_to_tasks, dict):
        element_to_tasks = {}
    tasks = element_to_tasks.get(element_id, [])
    if not isinstance(tasks, list):
        tasks = []
    task_ids = sorted({task for task in tasks if isinstance(task, str)})

    if not sources and not task_ids:
        return None

    task_to_patches = indexes.get("task_to_patches")
    if not isinstance(task_to_patches, dict):
        task_to_patches = {}

    lines = [
        f"# Trace: {element_id}",
        "",
        f"**Element**: {element_id}",
        "",
        f"**Source Sections** ({len(sources)}):",
    ]

    for section_id, lib_id, _kind in sources:
        lines.append(f"- {section_id} (from {lib_id})")

    lines.extend(
        [
            "",
            f"**Tasks** ({len(task_ids)}):",
        ]
    )

    for task_id in task_ids:
        lines.append(f"- {task_id}")
        patch_info = task_to_patches.get(task_id)
        lines.append(
            _format_patch_line(task_id, patch_info, manager, indent="  ", include_task_id=False)
        )

    return "\n".join(lines)


def format_task_trace(
    task_id: str, indexes: dict[str, Any], manager: WorkspaceManager
) -> str | None:
    if not TASK_ID_RE.fullmatch(task_id):
        return None
    task_to_patches = indexes.get("task_to_patches")
    if not isinstance(task_to_patches, dict):
        task_to_patches = {}
    patch_info = task_to_patches.get(task_id)

    element_to_tasks = indexes.get("element_to_tasks")
    section_to_elements = indexes.get("section_to_elements")
    if not isinstance(element_to_tasks, dict):
        element_to_tasks = {}
    if not isinstance(section_to_elements, dict):
        section_to_elements = {}

    covered_elements = sorted(
        [
            element_id
            for element_id, tasks in element_to_tasks.items()
            if isinstance(element_id, str) and isinstance(tasks, list) and task_id in tasks
        ]
    )

    if not isinstance(patch_info, dict) and not covered_elements:
        return None

    if isinstance(patch_info, dict):
        patch_path = _normalize_patch_path(patch_info.get("patch_path"), manager)
        patch_sha256 = (
            patch_info.get("patch_sha256")
            if isinstance(patch_info.get("patch_sha256"), str)
            else "unknown"
        )
        status = patch_info.get("status") if isinstance(patch_info.get("status"), str) else None
    else:
        logger.warning("Patch info missing for task %s", task_id)
        patch_path = "(patch missing)"
        patch_sha256 = "unknown"
        status = None

    lines = [
        f"# Trace: {task_id}",
        "",
        f"**Task**: {task_id}",
        f"- Patch: {patch_path}",
        f"- SHA256: {patch_sha256}",
    ]
    if status:
        lines.append(f"- Status: {status}")

    lines.extend(["", f"**Covers Elements** ({len(covered_elements)}):"])

    for element_id in covered_elements:
        sources, element_meta = _collect_element_sources(element_id, section_to_elements)
        sources_sorted = sorted({entry[0] for entry in sources})
        lib_id = element_meta[0] if element_meta else "unknown"
        kind = element_meta[1] if element_meta else "unknown"
        lines.append(f"- {element_id} ({kind}, from {lib_id})")
        if sources_sorted:
            lines.append(f"  - Source sections: {', '.join(sources_sorted)}")
        else:
            lines.append("  - Source sections: (none)")

    return "\n".join(lines)

"""Trace index builders for spec refinement workflows."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.formats import parse_evidence_pointer
from spec_manager.refinement.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    resolve_section_reference,
)
from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.schemas.spec_indexes import SpecIndex
from spec_manager.schemas.tasks import TaskIndexSchema, read_task_index_json, read_task_json

logger = logging.getLogger(__name__)

ATOM_ID_RE = re.compile(r"^ATOM-[A-Za-z0-9_.-]+-L\d{4}$")
SECTION_ID_RE = re.compile(r"^SEC-F\d{4}-\d{4}$")
ELEMENT_ID_RE = re.compile(
    r"^(?:REQ-LIB-\d{4}-\d{4}|FLOW-LIB-\d{4}-\d{2}|INV-LIB-\d{4}-\d{4})$"
)
TASK_ID_RE = re.compile(r"^TASK-\d{4}$")


def build_atom_to_section_index(manager: WorkspaceManager) -> dict[str, dict[str, str]]:
    atom_to_section: dict[str, dict[str, str]] = {}
    issues: list[str] = []
    atoms_dir = manager.structure.manifest_atoms_dir
    if not atoms_dir.exists():
        logger.warning("Atoms directory missing: %s", atoms_dir)
        return atom_to_section

    for atoms_file in sorted(atoms_dir.glob("*.atoms.jsonl")):
        filename = atoms_file.name
        file_id = filename[:-len(".atoms.jsonl")] if filename.endswith(".atoms.jsonl") else filename
        try:
            with atoms_file.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        atom = json.loads(line)
                    except json.JSONDecodeError as exc:
                        issue = f"Invalid JSON in {atoms_file} line {line_no}: {exc}"
                        issues.append(issue)
                        logger.warning(issue)
                        continue
                    atom_id = atom.get("atom_id")
                    section_id = atom.get("section_id")
                    sha256 = atom.get("sha256")
                    if not isinstance(atom_id, str) or not isinstance(section_id, str):
                        issue = f"Missing atom_id/section_id in {atoms_file} line {line_no}"
                        issues.append(issue)
                        logger.warning(issue)
                        continue
                    if not isinstance(sha256, str):
                        issue = f"Missing sha256 in {atoms_file} line {line_no}"
                        issues.append(issue)
                        logger.warning(issue)
                        continue
                    if atom_id in atom_to_section:
                        issue = f"Duplicate atom_id {atom_id} in {atoms_file} line {line_no}"
                        issues.append(issue)
                        logger.warning(issue)
                        continue
                    atom_to_section[atom_id] = {
                        "file_id": file_id,
                        "section_id": section_id,
                        "sha256": sha256,
                    }
        except OSError as exc:
            issue = f"Failed to read atoms file {atoms_file}: {exc}"
            issues.append(issue)
            logger.warning(issue)

    sorted_atom_to_section = {atom_id: atom_to_section[atom_id] for atom_id in sorted(atom_to_section)}
    if issues:
        logger.info("Collected %s atom index issues", len(issues))
    return sorted_atom_to_section


def build_section_to_spec_elements_index(
    manager: WorkspaceManager,
) -> dict[str, list[dict[str, str]]]:
    section_to_elements: dict[str, list[dict[str, str]]] = defaultdict(list)
    issues: list[str] = []
    libraries_dir = manager.structure.libraries_dir
    if not libraries_dir.exists():
        logger.warning("Libraries directory missing: %s", libraries_dir)
        return {}

    file_id_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )
    alias_map = build_section_alias_map(manager.state.section_manifest)
    sections_cache: dict[str, dict[str, Any] | None] = {}

    for lib_dir in sorted(libraries_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        spec_index_path = lib_dir / "spec_index.json"
        if not spec_index_path.exists():
            continue
        try:
            payload = json.loads(spec_index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issue = f"Failed to read spec index {spec_index_path}: {exc}"
            issues.append(issue)
            logger.warning(issue)
            continue
        try:
            spec_index = SpecIndex.model_validate(payload)
        except Exception as exc:
            issue = f"Spec index validation failed for {spec_index_path}: {exc}"
            issues.append(issue)
            logger.warning(issue)
            continue

        lib_id = spec_index.lib_id
        for element in spec_index.elements:
            element_id = element.element_id
            kind = element.kind
            for citation in element.citations:
                parsed = parse_evidence_pointer(citation)
                if not parsed:
                    issue = (
                        f"Unable to parse citation {citation!r} for {element_id} in {lib_id}"
                    )
                    issues.append(issue)
                    logger.warning(issue)
                    continue
                file_ref = parsed.get("file_ref", "")
                section_ref = parsed.get("section_ref", "")
                section_id = section_ref
                if not SECTION_ID_RE.fullmatch(section_ref):
                    file_id = file_id_lookup.get(file_ref)
                    if not file_id:
                        issue = (
                            f"Unresolved file reference {file_ref!r} for citation {citation!r}"
                        )
                        issues.append(issue)
                        logger.warning(issue)
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
                        issue = (
                            f"Unresolved section reference {section_ref!r} for {element_id} "
                            f"in {lib_id}"
                        )
                        issues.append(issue)
                        logger.warning(issue)
                        continue
                    section_id = resolved
                if not section_id:
                    continue
                section_to_elements[section_id].append(
                    {"lib_id": lib_id, "element_id": element_id, "kind": kind}
                )

    normalized: dict[str, list[dict[str, str]]] = {}
    for section_id in sorted(section_to_elements):
        entries = sorted(
            section_to_elements[section_id],
            key=lambda item: (item["lib_id"], item["element_id"], item["kind"]),
        )
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for entry in entries:
            key = (entry["lib_id"], entry["element_id"], entry["kind"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        normalized[section_id] = deduped

    if issues:
        logger.info("Collected %s section-to-elements issues", len(issues))
    return normalized


def build_spec_element_to_tasks_index(manager: WorkspaceManager) -> dict[str, list[str]]:
    element_to_tasks: dict[str, list[str]] = defaultdict(list)
    issues: list[str] = []
    task_index_path = manager.structure.tasks_dir / "task_index.json"
    if not task_index_path.exists():
        logger.warning("Task index missing: %s", task_index_path)
        return {}

    try:
        task_index: TaskIndexSchema = read_task_index_json(task_index_path)
    except (OSError, json.JSONDecodeError) as exc:
        issue = f"Failed to read task index {task_index_path}: {exc}"
        issues.append(issue)
        logger.warning(issue)
        return {}
    except Exception as exc:
        issue = f"Task index validation failed for {task_index_path}: {exc}"
        issues.append(issue)
        logger.warning(issue)
        return {}

    for task in sorted(task_index.tasks, key=lambda entry: entry.task_id):
        task_id = task.task_id
        task_path = manager.structure.tasks_dir / task_id / "task.json"
        try:
            task_detail = read_task_json(task_path)
        except (OSError, json.JSONDecodeError) as exc:
            issue = f"Failed to read task file {task_path}: {exc}"
            issues.append(issue)
            logger.warning(issue)
            continue
        except Exception as exc:
            issue = f"Task schema validation failed for {task_path}: {exc}"
            issues.append(issue)
            logger.warning(issue)
            continue
        for element_id in task_detail.covers.elements:
            element_to_tasks[element_id].append(task_id)

    normalized: dict[str, list[str]] = {}
    for element_id in sorted(element_to_tasks):
        normalized[element_id] = sorted(set(element_to_tasks[element_id]))

    if issues:
        logger.info("Collected %s element-to-task issues", len(issues))
    return normalized


def build_task_to_patches_index(manager: WorkspaceManager) -> dict[str, dict[str, Any]]:
    task_to_patches: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    task_index_path = manager.structure.tasks_dir / "task_index.json"
    if not task_index_path.exists():
        logger.warning("Task index missing: %s", task_index_path)
        return {}

    try:
        task_index: TaskIndexSchema = read_task_index_json(task_index_path)
    except (OSError, json.JSONDecodeError) as exc:
        issue = f"Failed to read task index {task_index_path}: {exc}"
        issues.append(issue)
        logger.warning(issue)
        return {}
    except Exception as exc:
        issue = f"Task index validation failed for {task_index_path}: {exc}"
        issues.append(issue)
        logger.warning(issue)
        return {}

    for task in sorted(task_index.tasks, key=lambda entry: entry.task_id):
        task_id = task.task_id
        task_dir = manager.structure.tasks_dir / task_id
        patch_path = task_dir / "patch.diff"
        if not patch_path.exists():
            continue
        try:
            patch_bytes = patch_path.read_bytes()
        except OSError as exc:
            issue = f"Failed to read patch {patch_path}: {exc}"
            issues.append(issue)
            logger.warning(issue)
            continue
        patch_hash = hashlib.sha256(patch_bytes).hexdigest()
        try:
            relative_patch = patch_path.relative_to(manager.structure.root).as_posix()
        except ValueError:
            relative_patch = patch_path.as_posix()

        patch_info: dict[str, Any] = {
            "patch_path": relative_patch,
            "patch_sha256": patch_hash,
        }

        status_path = task_dir / "status.json"
        if status_path.exists():
            try:
                status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issue = f"Failed to read status {status_path}: {exc}"
                issues.append(issue)
                logger.warning(issue)
            else:
                status = status_payload.get("status")
                task_hash = status_payload.get("task_hash")
                if isinstance(status, str) and status:
                    patch_info["status"] = status
                if isinstance(task_hash, str) and task_hash:
                    patch_info["task_hash"] = task_hash

        task_to_patches[task_id] = patch_info

    normalized = {task_id: task_to_patches[task_id] for task_id in sorted(task_to_patches)}
    if issues:
        logger.info("Collected %s task-to-patch issues", len(issues))
    return normalized


def build_trace_indexes(run_id: str) -> dict[str, Any]:
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))

    atom_to_section = build_atom_to_section_index(manager)
    section_to_elements = build_section_to_spec_elements_index(manager)
    element_to_tasks = build_spec_element_to_tasks_index(manager)
    task_to_patches = build_task_to_patches_index(manager)

    indexes_dir = manager.structure.indexes_dir
    indexes_dir.mkdir(parents=True, exist_ok=True)

    index_payloads = {
        "atom_to_section.json": atom_to_section,
        "section_to_spec_elements.json": section_to_elements,
        "spec_element_to_tasks.json": element_to_tasks,
        "task_to_patches.json": task_to_patches,
    }

    for filename, payload in index_payloads.items():
        path = indexes_dir / filename
        try:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write index %s: %s", path, exc)

    trace_index = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(),
        "indexes": {
            "atom_to_section": "workspace/indexes/atom_to_section.json",
            "section_to_spec_elements": "workspace/indexes/section_to_spec_elements.json",
            "spec_element_to_tasks": "workspace/indexes/spec_element_to_tasks.json",
            "task_to_patches": "workspace/indexes/task_to_patches.json",
        },
    }

    trace_index_path = indexes_dir / "trace_index.json"
    try:
        trace_index_path.write_text(
            json.dumps(trace_index, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to write trace index %s: %s", trace_index_path, exc)

    root_trace_index_path = manager.structure.root / "trace_index.json"
    try:
        root_trace_index_path.write_text(
            json.dumps(trace_index, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to write root trace index %s: %s", root_trace_index_path, exc)

    return {
        "atoms": len(atom_to_section),
        "sections": len(section_to_elements),
        "elements": len(element_to_tasks),
        "tasks": len(task_to_patches),
    }


def validate_trace_indexes(manager: WorkspaceManager) -> list[str]:
    errors: list[str] = []
    indexes_dir = manager.structure.indexes_dir
    trace_paths = {
        "atom_to_section": indexes_dir / "atom_to_section.json",
        "section_to_spec_elements": indexes_dir / "section_to_spec_elements.json",
        "spec_element_to_tasks": indexes_dir / "spec_element_to_tasks.json",
        "task_to_patches": indexes_dir / "task_to_patches.json",
    }

    loaded: dict[str, Any] = {}
    for name, path in trace_paths.items():
        if not path.exists():
            errors.append(f"Missing trace index: {path}")
            continue
        try:
            loaded[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Failed to read trace index {path}: {exc}")

    section_ids = {
        section_id
        for sections in manager.state.section_manifest.values()
        for section_id in sections
        if isinstance(section_id, str)
    }

    atom_to_section = loaded.get("atom_to_section")
    if isinstance(atom_to_section, dict):
        for atom_id, payload in atom_to_section.items():
            if not ATOM_ID_RE.fullmatch(str(atom_id)):
                errors.append(f"Invalid atom ID: {atom_id}")
            if not isinstance(payload, dict):
                errors.append(f"Invalid atom payload for {atom_id}")
                continue
            section_id = payload.get("section_id")
            if not isinstance(section_id, str) or not SECTION_ID_RE.fullmatch(section_id):
                errors.append(f"Invalid section ID for {atom_id}: {section_id}")
            elif section_id not in section_ids:
                errors.append(f"Section ID not found in manifest: {section_id}")

    section_to_elements = loaded.get("section_to_spec_elements")
    if isinstance(section_to_elements, dict):
        for section_id, entries in section_to_elements.items():
            if not SECTION_ID_RE.fullmatch(str(section_id)):
                errors.append(f"Invalid section ID: {section_id}")
            elif section_id not in section_ids:
                errors.append(f"Section ID not found in manifest: {section_id}")
            if not isinstance(entries, list):
                errors.append(f"Invalid section entries for {section_id}")
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    errors.append(f"Invalid element mapping for {section_id}")
                    continue
                element_id = entry.get("element_id")
                if not isinstance(element_id, str) or not ELEMENT_ID_RE.fullmatch(element_id):
                    errors.append(f"Invalid element ID in section {section_id}: {element_id}")

    element_to_tasks = loaded.get("spec_element_to_tasks")
    if isinstance(element_to_tasks, dict):
        for element_id, tasks in element_to_tasks.items():
            if not ELEMENT_ID_RE.fullmatch(str(element_id)):
                errors.append(f"Invalid element ID: {element_id}")
            if not isinstance(tasks, list):
                errors.append(f"Invalid tasks list for {element_id}")
                continue
            for task_id in tasks:
                if not TASK_ID_RE.fullmatch(str(task_id)):
                    errors.append(f"Invalid task ID for {element_id}: {task_id}")

    task_to_patches = loaded.get("task_to_patches")
    if isinstance(task_to_patches, dict):
        for task_id, payload in task_to_patches.items():
            if not TASK_ID_RE.fullmatch(str(task_id)):
                errors.append(f"Invalid task ID: {task_id}")
            if not isinstance(payload, dict):
                errors.append(f"Invalid patch payload for {task_id}")
                continue
            patch_path = payload.get("patch_path")
            if isinstance(patch_path, str) and patch_path:
                patch_abs = manager.structure.root / patch_path
                if not patch_abs.exists():
                    errors.append(f"Patch path not found for {task_id}: {patch_path}")

    return errors


__all__ = [
    "build_atom_to_section_index",
    "build_section_to_spec_elements_index",
    "build_spec_element_to_tasks_index",
    "build_task_to_patches_index",
    "build_trace_indexes",
    "validate_trace_indexes",
]

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

import pytest
from spec_manager.refinement.workflows import trace_indexes as trace_indexes_module
from spec_manager.refinement.workflows.trace_indexes import (
    build_atom_to_section_index,
    build_section_to_spec_elements_index,
    build_spec_element_to_tasks_index,
    build_task_to_patches_index,
    build_trace_indexes,
    validate_trace_indexes,
)
from spec_manager.refinement.workspace import WorkspaceManager
from spec_manager.schemas.spec_indexes import SpecIndex
from spec_manager.schemas.tasks import (
    TaskCoversSchema,
    TaskIndexEntrySchema,
    TaskIndexSchema,
    TaskSchema,
    write_task_index_json,
    write_task_json,
)

from tests.spec_refinement.fixtures.test_corpus import (
    create_interface_test_libraries,
    create_task_planning_prerequisites,
)
from tests.spec_refinement.utils import (
    _count_markdown_sections,
    _extract_table_rows,
    _validate_json_index,
    _validate_markdown_table,
)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_sections(manager: WorkspaceManager, file_id: str) -> list[str]:
    sections = [
        {
            "section_id": f"SEC-{file_id}-0001",
            "start_line": 1,
            "end_line": 2,
            "label": "INTRO",
        },
        {
            "section_id": f"SEC-{file_id}-0002",
            "start_line": 3,
            "end_line": 4,
            "label": "DETAILS",
        },
    ]
    manager.write_file_sections(
        file_id,
        {
            "file_id": file_id,
            "sections": sections,
            "total_lines": 4,
        },
    )
    manager.save_state()
    return [section["section_id"] for section in sections]


def _create_minimal_atoms(
    manager: WorkspaceManager,
    file_id: str,
    entries: list[tuple[str, str]],
    *,
    rev_id: str = "R0001",
) -> list[dict[str, str]]:
    atoms: list[dict[str, str]] = []
    for line_no, (section_id, text) in enumerate(entries, start=1):
        atom_id = f"ATOM-{file_id}-{rev_id}-L{line_no:04d}"
        # atom_fingerprint is a hash of content + context for cross-revision matching
        atom_fingerprint = _hash_text(f"{text}:{line_no}")
        atoms.append(
            {
                "atom_id": atom_id,
                "atom_fingerprint": atom_fingerprint,
                "file_uid": file_id,
                "rev_id": rev_id,
                "line_no": line_no,
                "sequence_index": line_no - 1,
                "section_id": section_id,
                "sha256": _hash_text(text),
                "text": text,
            }
        )
    manager.write_file_atoms(file_id, atoms)
    return atoms


def _create_minimal_spec_index(
    manager: WorkspaceManager,
    lib_id: str,
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "lib_id": lib_id,
        "generated_at": "2024-01-01T00:00:00",
        "spec_path": f"libraries/{lib_id}/spec.md",
        "elements": [],
    }
    for element in elements:
        element_id = element["element_id"]
        text = element.get("text", "Test element")
        payload["elements"].append(
            {
                "element_id": element_id,
                "kind": element.get("kind", "requirement"),
                "section": element.get("section", "Requirements"),
                "text": text,
                "raw_line": element.get("raw_line", f"- {element_id}: {text}"),
                "citations": element.get("citations", []),
                "mentions_libs": element.get("mentions_libs", []),
            }
        )
    SpecIndex.model_validate(payload)
    (lib_dir / "spec_index.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _create_minimal_task_index(
    manager: WorkspaceManager,
    task_defs: list[dict[str, Any]],
) -> list[TaskSchema]:
    tasks_dir = manager.structure.tasks_dir
    tasks_dir.mkdir(parents=True, exist_ok=True)
    entries: list[TaskIndexEntrySchema] = []
    tasks: list[TaskSchema] = []

    for spec in task_defs:
        task_id = spec["task_id"]
        element_ids = spec.get("elements", [])
        status = spec.get("status", "planned")
        libraries = spec.get("libraries", ["LIB-0001"])
        task = TaskSchema(
            task_id=task_id,
            title=spec.get("title", f"Task {task_id}"),
            description=spec.get("description", "Trace index task."),
            priority=spec.get("priority", "p1"),
            component=spec.get("component", "API Layer"),
            libraries=libraries,
            covers=TaskCoversSchema(
                elements=element_ids,
                edges=spec.get("edges", []),
                decisions=spec.get("decisions", []),
                gaps=spec.get("gaps", []),
            ),
            acceptance_criteria=spec.get("acceptance_criteria", ["Checks pass."]),
            suggested_files=spec.get("suggested_files", []),
            risk_notes=spec.get("risk_notes", ""),
            validation_notes=spec.get("validation_notes", ""),
            citations=spec.get(
                "citations",
                ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            ),
            depends_on=spec.get("depends_on", []),
        )
        write_task_json(task, tasks_dir / task_id / "task.json")
        entries.append(
            TaskIndexEntrySchema(
                task_id=task_id,
                title=task.title,
                status=status,
                priority=task.priority,
                component=task.component,
                libraries=task.libraries,
                covers=task.covers,
                depends_on=task.depends_on,
            )
        )
        tasks.append(task)

    index = TaskIndexSchema(
        run_id=manager.run_id,
        generated_at="2024-01-01T00:00:00",
        tasks=entries,
    )
    write_task_index_json(index, tasks_dir / "task_index.json")
    return tasks


def _create_minimal_patches(
    manager: WorkspaceManager,
    task_ids: list[str],
    *,
    status_payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    patch_hashes: dict[str, str] = {}
    for task_id in task_ids:
        task_dir = manager.structure.tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        patch_path = task_dir / "patch.diff"
        patch_content = f"diff --git a/{task_id}.txt b/{task_id}.txt\n"
        patch_path.write_text(patch_content, encoding="utf-8")
        patch_hashes[task_id] = hashlib.sha256(patch_content.encode("utf-8")).hexdigest()

        if status_payloads and task_id in status_payloads:
            (task_dir / "status.json").write_text(
                json.dumps(status_payloads[task_id], indent=2),
                encoding="utf-8",
            )
    return patch_hashes


class TestAtomToSectionIndex:
    def test_build_atom_to_section_index_basic(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_atoms_basic")
        atoms_file_id = "F0001"
        entries = [
            ("SEC-F0001-0001", "First line"),
            ("SEC-F0001-0002", "Second line"),
        ]
        _create_minimal_atoms(manager, atoms_file_id, entries)

        atoms_file_id_two = "F0002"
        entries_two = [("SEC-F0002-0001", "Third line")]
        _create_minimal_atoms(manager, atoms_file_id_two, entries_two)

        index = build_atom_to_section_index(manager)

        # Atom IDs now include revision ID: ATOM-{file_uid}-{rev_id}-L{line_no:04d}
        assert index["ATOM-F0001-R0001-L0001"]["section_id"] == "SEC-F0001-0001"
        assert index["ATOM-F0001-R0001-L0001"]["sha256"] == _hash_text("First line")
        assert index["ATOM-F0002-R0001-L0001"]["section_id"] == "SEC-F0002-0001"
        assert index["ATOM-F0002-R0001-L0001"]["file_id"] == "F0002"

    def test_build_atom_to_section_index_empty_directory(
        self, interface_workspace, fs, caplog
    ) -> None:
        manager, _ = interface_workspace(run_id="run_atoms_empty")
        atoms_dir = manager.structure.manifest_atoms_dir
        if atoms_dir.exists():
            fs.remove_object(atoms_dir)

        caplog.set_level(logging.WARNING)
        index = build_atom_to_section_index(manager)

        assert index == {}
        assert any("Atoms directory missing" in record.message for record in caplog.records)

    def test_build_atom_to_section_index_invalid_json(self, interface_workspace, caplog) -> None:
        manager, _ = interface_workspace(run_id="run_atoms_invalid")
        atoms_dir = manager.structure.manifest_atoms_dir
        atoms_dir.mkdir(parents=True, exist_ok=True)
        atoms_path = atoms_dir / "F0001.atoms.jsonl"
        atoms_path.write_text("{invalid-json}\n", encoding="utf-8")

        caplog.set_level(logging.WARNING)
        index = build_atom_to_section_index(manager)

        assert index == {}
        assert any("Invalid JSON" in record.message for record in caplog.records)

    def test_build_atom_to_section_index_duplicate_atoms(self, interface_workspace, caplog) -> None:
        manager, _ = interface_workspace(run_id="run_atoms_duplicate")
        atoms_dir = manager.structure.manifest_atoms_dir
        atoms_dir.mkdir(parents=True, exist_ok=True)
        atoms_path = atoms_dir / "F0001.atoms.jsonl"
        atom_payload = {
            "atom_id": "ATOM-F0001-L0001",
            "line_no": 1,
            "section_id": "SEC-F0001-0001",
            "sha256": _hash_text("dup"),
            "text": "dup",
        }
        atoms_path.write_text(
            "\n".join([json.dumps(atom_payload), json.dumps(atom_payload)]) + "\n",
            encoding="utf-8",
        )

        caplog.set_level(logging.WARNING)
        index = build_atom_to_section_index(manager)

        assert list(index.keys()) == ["ATOM-F0001-L0001"]
        assert any("Duplicate atom_id" in record.message for record in caplog.records)

    def test_build_atom_to_section_index_deterministic(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_atoms_deterministic")
        entries = [
            ("SEC-F0001-0001", "Alpha"),
            ("SEC-F0001-0001", "Beta"),
        ]
        _create_minimal_atoms(manager, "F0001", entries)

        first = build_atom_to_section_index(manager)
        second = build_atom_to_section_index(manager)

        assert first == second
        assert list(first.keys()) == sorted(first.keys())


class TestSectionToElementsIndex:
    def test_build_section_to_spec_elements_index_basic(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_sections_basic")
        file_id = sorted(manager.state.file_manifest.keys())[0]
        section_ids = _write_sections(manager, file_id)
        citation_one = f"[spec_snapshot/input.md::{section_ids[0]}]"
        citation_two = f"[spec_snapshot/input.md::{section_ids[1]}]"

        _create_minimal_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "citations": [citation_one],
                },
                {
                    "element_id": "REQ-LIB-0001-0002",
                    "citations": [citation_two],
                },
            ],
        )

        index = build_section_to_spec_elements_index(manager)

        assert section_ids[0] in index
        assert section_ids[1] in index
        assert index[section_ids[0]][0]["element_id"] == "REQ-LIB-0001-0001"

    def test_build_section_to_spec_elements_index_legacy_pointers(
        self, interface_workspace
    ) -> None:
        manager, _ = interface_workspace(run_id="run_sections_legacy")
        _create_minimal_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "citations": ["[F0001::Intro]"],
                }
            ],
        )

        index = build_section_to_spec_elements_index(manager)

        assert "INTRO" in index
        assert index["INTRO"][0]["lib_id"] == "LIB-0001"

    def test_build_section_to_spec_elements_index_multiple_libraries(
        self, interface_workspace
    ) -> None:
        manager, _ = interface_workspace(run_id="run_sections_multi")
        file_id = sorted(manager.state.file_manifest.keys())[0]
        section_ids = _write_sections(manager, file_id)
        citation = f"[spec_snapshot/input.md::{section_ids[0]}]"
        for lib_id in ["LIB-0001", "LIB-0002", "LIB-0003"]:
            _create_minimal_spec_index(
                manager,
                lib_id,
                [
                    {
                        "element_id": f"REQ-{lib_id}-0001",
                        "citations": [citation],
                    }
                ],
            )

        index = build_section_to_spec_elements_index(manager)

        entries = index[section_ids[0]]
        assert {entry["lib_id"] for entry in entries} == {"LIB-0001", "LIB-0002", "LIB-0003"}

    def test_build_section_to_spec_elements_index_deduplication(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_sections_dedupe")
        file_id = sorted(manager.state.file_manifest.keys())[0]
        section_ids = _write_sections(manager, file_id)
        citation = f"[spec_snapshot/input.md::{section_ids[0]}]"
        _create_minimal_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "citations": [citation, citation],
                }
            ],
        )

        index = build_section_to_spec_elements_index(manager)

        assert len(index[section_ids[0]]) == 1

    def test_build_section_to_spec_elements_index_invalid_citations(
        self, interface_workspace, caplog
    ) -> None:
        manager, _ = interface_workspace(run_id="run_sections_invalid")
        _create_minimal_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "citations": ["not-a-pointer"],
                }
            ],
        )

        caplog.set_level(logging.WARNING)
        index = build_section_to_spec_elements_index(manager)

        assert index == {}
        assert any("Unable to parse citation" in record.message for record in caplog.records)


class TestElementToTasksIndex:
    def test_build_spec_element_to_tasks_index_basic(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_elements_basic")
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                },
                {
                    "task_id": "TASK-0002",
                    "elements": ["FLOW-LIB-0001-01"],
                },
            ],
        )

        index = build_spec_element_to_tasks_index(manager)

        assert index["REQ-LIB-0001-0001"] == ["TASK-0001"]
        assert index["FLOW-LIB-0001-01"] == ["TASK-0002"]

    def test_build_spec_element_to_tasks_index_multiple_tasks(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_elements_multi")
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                },
                {
                    "task_id": "TASK-0002",
                    "elements": ["REQ-LIB-0001-0001"],
                },
                {
                    "task_id": "TASK-0003",
                    "elements": ["REQ-LIB-0001-0001"],
                },
            ],
        )

        index = build_spec_element_to_tasks_index(manager)

        assert index["REQ-LIB-0001-0001"] == ["TASK-0001", "TASK-0002", "TASK-0003"]

    def test_build_spec_element_to_tasks_index_missing_task_index(
        self, interface_workspace, fs, caplog
    ) -> None:
        manager, _ = interface_workspace(run_id="run_elements_missing")
        tasks_dir = manager.structure.tasks_dir
        if tasks_dir.exists():
            fs.remove_object(tasks_dir)

        caplog.set_level(logging.WARNING)
        index = build_spec_element_to_tasks_index(manager)

        assert index == {}
        assert any("Task index missing" in record.message for record in caplog.records)

    def test_build_spec_element_to_tasks_index_invalid_task_file(
        self, interface_workspace, caplog
    ) -> None:
        manager, _ = interface_workspace(run_id="run_elements_invalid_task")
        tasks_dir = manager.structure.tasks_dir
        tasks_dir.mkdir(parents=True, exist_ok=True)
        index = TaskIndexSchema(
            run_id=manager.run_id,
            generated_at="2024-01-01T00:00:00",
            tasks=[
                TaskIndexEntrySchema(
                    task_id="TASK-0001",
                    title="Invalid task",
                    status="planned",
                    priority="p1",
                    component="API Layer",
                    libraries=["LIB-0001"],
                    covers=TaskCoversSchema(elements=["REQ-LIB-0001-0001"]),
                )
            ],
        )
        write_task_index_json(index, tasks_dir / "task_index.json")
        task_dir = tasks_dir / "TASK-0001"
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "task.json").write_text("{bad-json", encoding="utf-8")

        caplog.set_level(logging.WARNING)
        result = build_spec_element_to_tasks_index(manager)

        assert result == {}
        assert any("Failed to read task file" in record.message for record in caplog.records)


class TestTaskToPatchesIndex:
    def test_build_task_to_patches_index_basic(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_patches_basic")
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                }
            ],
        )
        patch_hashes = _create_minimal_patches(manager, ["TASK-0001"])

        index = build_task_to_patches_index(manager)

        assert index["TASK-0001"]["patch_sha256"] == patch_hashes["TASK-0001"]

    def test_build_task_to_patches_index_with_status(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_patches_status")
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                }
            ],
        )
        _create_minimal_patches(
            manager,
            ["TASK-0001"],
            status_payloads={
                "TASK-0001": {"status": "done", "task_hash": "hash-0001"},
            },
        )

        index = build_task_to_patches_index(manager)

        assert index["TASK-0001"]["status"] == "done"
        assert index["TASK-0001"]["task_hash"] == "hash-0001"

    def test_build_task_to_patches_index_missing_patches(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_patches_missing")
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                }
            ],
        )

        index = build_task_to_patches_index(manager)

        assert index == {}

    def test_build_task_to_patches_index_relative_paths(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_patches_relative")
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                }
            ],
        )
        _create_minimal_patches(manager, ["TASK-0001"])

        index = build_task_to_patches_index(manager)

        assert index["TASK-0001"]["patch_path"] == "tasks/TASK-0001/patch.diff"


class TestTraceIndexesIntegration:
    @pytest.mark.integration
    def test_build_trace_indexes_full(self, interface_workspace, fs) -> None:
        manager, manifest = interface_workspace(run_id="run_trace_full")
        create_interface_test_libraries(fs, run_id=manager.run_id)
        create_task_planning_prerequisites(fs, manager.run_id, manifest)

        file_id = sorted(manager.state.file_manifest.keys())[0]
        section_ids = _write_sections(manager, file_id)
        _create_minimal_atoms(
            manager,
            file_id,
            [
                (section_ids[0], "Alpha"),
                (section_ids[1], "Beta"),
            ],
        )
        _create_minimal_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "citations": [f"[spec_snapshot/input.md::{section_ids[0]}]"],
                }
            ],
        )
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                }
            ],
        )
        _create_minimal_patches(manager, ["TASK-0001"])

        build_trace_indexes(manager.run_id)

        indexes_dir = manager.structure.indexes_dir
        assert (indexes_dir / "atom_to_section.json").exists()
        assert (indexes_dir / "section_to_spec_elements.json").exists()
        assert (indexes_dir / "spec_element_to_tasks.json").exists()
        assert (indexes_dir / "task_to_patches.json").exists()
        assert (indexes_dir / "trace_index.json").exists()
        assert (manager.structure.root / "trace_index.json").exists()
        assert _validate_json_index(
            indexes_dir / "trace_index.json", {"run_id", "generated_at", "indexes"}
        )

    @pytest.mark.integration
    def test_validate_trace_indexes_success(self, interface_workspace, fs) -> None:
        manager, manifest = interface_workspace(run_id="run_trace_validate")
        create_task_planning_prerequisites(fs, manager.run_id, manifest)
        file_id = sorted(manager.state.file_manifest.keys())[0]
        section_ids = _write_sections(manager, file_id)
        _create_minimal_atoms(
            manager,
            file_id,
            [
                (section_ids[0], "Alpha"),
            ],
        )
        _create_minimal_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "citations": [f"[spec_snapshot/input.md::{section_ids[0]}]"],
                }
            ],
        )
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                }
            ],
        )
        _create_minimal_patches(manager, ["TASK-0001"])

        build_trace_indexes(manager.run_id)

        errors = validate_trace_indexes(manager)

        assert errors == []

    @pytest.mark.integration
    def test_validate_trace_indexes_missing_files(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_trace_missing_files")
        build_trace_indexes(manager.run_id)
        missing_path = manager.structure.indexes_dir / "task_to_patches.json"
        if missing_path.exists():
            missing_path.unlink()

        errors = validate_trace_indexes(manager)

        assert any("Missing trace index" in error for error in errors)

    @pytest.mark.integration
    def test_validate_trace_indexes_invalid_ids(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_trace_invalid_ids")
        file_id = sorted(manager.state.file_manifest.keys())[0]
        _write_sections(manager, file_id)

        indexes_dir = manager.structure.indexes_dir
        indexes_dir.mkdir(parents=True, exist_ok=True)
        (indexes_dir / "atom_to_section.json").write_text(
            json.dumps(
                {
                    "ATOM-BAD": {
                        "file_id": file_id,
                        "section_id": f"SEC-{file_id}-0001",
                        "sha256": _hash_text("bad"),
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (indexes_dir / "section_to_spec_elements.json").write_text(
            json.dumps(
                {
                    f"SEC-{file_id}-0001": [
                        {"lib_id": "LIB-0001", "element_id": "BAD-ELEM", "kind": "requirement"}
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (indexes_dir / "spec_element_to_tasks.json").write_text(
            json.dumps(
                {"BAD-ELEM": ["BAD-TASK"]},
                indent=2,
            ),
            encoding="utf-8",
        )
        patch_path = manager.structure.tasks_dir / "TASK-0001" / "patch.diff"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text("diff --git a/a b/a\n", encoding="utf-8")
        (indexes_dir / "task_to_patches.json").write_text(
            json.dumps(
                {
                    "TASK-BAD": {
                        "patch_path": patch_path.relative_to(manager.structure.root).as_posix(),
                        "patch_sha256": _hash_text("patch"),
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        errors = validate_trace_indexes(manager)

        assert any("Invalid atom ID" in error for error in errors)
        assert any("Invalid element ID" in error for error in errors)
        assert any("Invalid task ID" in error for error in errors)

    @pytest.mark.integration
    def test_validate_trace_indexes_missing_references(self, interface_workspace) -> None:
        manager, _ = interface_workspace(run_id="run_trace_missing_refs")
        file_id = sorted(manager.state.file_manifest.keys())[0]
        _write_sections(manager, file_id)

        indexes_dir = manager.structure.indexes_dir
        indexes_dir.mkdir(parents=True, exist_ok=True)
        (indexes_dir / "atom_to_section.json").write_text(
            json.dumps(
                {
                    "ATOM-F0001-L0001": {
                        "file_id": file_id,
                        "section_id": f"SEC-{file_id}-9999",
                        "sha256": _hash_text("orphan"),
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (indexes_dir / "section_to_spec_elements.json").write_text("{}", encoding="utf-8")
        (indexes_dir / "spec_element_to_tasks.json").write_text("{}", encoding="utf-8")
        (indexes_dir / "task_to_patches.json").write_text("{}", encoding="utf-8")

        errors = validate_trace_indexes(manager)

        assert any("Section ID not found in manifest" in error for error in errors)

    @pytest.mark.integration
    def test_trace_indexes_deterministic_output(self, interface_workspace, fs, monkeypatch) -> None:
        """Ensure repeated builds produce identical JSON payloads with a fixed timestamp."""
        manager, manifest = interface_workspace(run_id="run_trace_deterministic")
        create_task_planning_prerequisites(fs, manager.run_id, manifest)
        file_id = sorted(manager.state.file_manifest.keys())[0]
        section_ids = _write_sections(manager, file_id)
        _create_minimal_atoms(
            manager,
            file_id,
            [
                (section_ids[0], "Alpha"),
            ],
        )
        _create_minimal_spec_index(
            manager,
            "LIB-0001",
            [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "citations": [f"[spec_snapshot/input.md::{section_ids[0]}]"],
                }
            ],
        )
        _create_minimal_task_index(
            manager,
            [
                {
                    "task_id": "TASK-0001",
                    "elements": ["REQ-LIB-0001-0001"],
                }
            ],
        )
        _create_minimal_patches(manager, ["TASK-0001"])

        fixed = datetime(2024, 1, 1, 0, 0, 0)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                if tz is None:
                    return fixed
                return fixed.replace(tzinfo=tz)

        monkeypatch.setattr(trace_indexes_module, "datetime", FixedDateTime)

        build_trace_indexes(manager.run_id)
        first_payloads = {
            path.name: path.read_text(encoding="utf-8")
            for path in manager.structure.indexes_dir.glob("*.json")
        }

        build_trace_indexes(manager.run_id)
        second_payloads = {
            path.name: path.read_text(encoding="utf-8")
            for path in manager.structure.indexes_dir.glob("*.json")
        }

        assert first_payloads == second_payloads

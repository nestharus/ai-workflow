from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.refinement.cli import main
from spec_manager.refinement.workspace import WorkspaceManager
from spec_manager.refinement.workflows.trace_indexes import build_trace_indexes

from tests.spec_refinement.test_trace_indexes import (
    _create_minimal_atoms,
    _create_minimal_patches,
    _create_minimal_spec_index,
    _create_minimal_task_index,
    _hash_text,
    _write_sections,
)


@pytest.fixture
def trace_workspace(
    interface_workspace,
) -> tuple[WorkspaceManager, dict[str, object]]:
    manager, _ = interface_workspace(run_id="run_trace_cli")
    file_id = sorted(manager.state.file_manifest.keys())[0]
    section_ids = _write_sections(manager, file_id)
    atoms = _create_minimal_atoms(
        manager,
        file_id,
        [
            (section_ids[0], "First line"),
            (section_ids[1], "Second line"),
        ],
    )
    citation_one = f"[spec_snapshot/input.md::{section_ids[0]}]"
    citation_two = f"[spec_snapshot/input.md::{section_ids[1]}]"
    element_ids = ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002"]
    _create_minimal_spec_index(
        manager,
        "LIB-0001",
        [
            {"element_id": element_ids[0], "citations": [citation_one]},
            {"element_id": element_ids[1], "citations": [citation_two]},
        ],
    )
    _create_minimal_task_index(
        manager,
        [
            {"task_id": "TASK-0001", "elements": [element_ids[0]]},
            {"task_id": "TASK-0002", "elements": [element_ids[1]]},
        ],
    )
    patch_hashes = _create_minimal_patches(
        manager,
        ["TASK-0001", "TASK-0002"],
        status_payloads={"TASK-0001": {"status": "done", "task_hash": "taskhash"}},
    )
    build_trace_indexes(manager.run_id)

    patch_path = Path("tasks") / "TASK-0001" / "patch.diff"
    known_ids = {
        "run_id": manager.run_id,
        "file_id": file_id,
        "section_id": section_ids[0],
        "section_ids": section_ids,
        "atom_id": atoms[0]["atom_id"],
        "atom_sha256": atoms[0]["sha256"],
        "element_id": element_ids[0],
        "element_ids": element_ids,
        "task_id": "TASK-0001",
        "task_ids": ["TASK-0001", "TASK-0002"],
        "patch_hash": patch_hashes["TASK-0001"],
        "patch_path": patch_path.as_posix(),
    }

    return manager, known_ids


class TestTraceAtomCommand:
    def test_trace_atom_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"**Atom**: {known_ids['atom_id']}" in output
        assert f"- File: {known_ids['file_id']}" in output
        assert f"- Section: {known_ids['section_id']}" in output
        assert f"- SHA256: {known_ids['atom_sha256']}" in output

    def test_trace_atom_not_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace
        missing_atom = "ATOM-F0001-L9999"

        exit_code = main(["trace", "atom", known_ids["run_id"], missing_atom])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert f"Atom not found: {missing_atom}" in output

    def test_trace_atom_invalid_format(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "atom", known_ids["run_id"], "ATOM-BAD"])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert "Atom not found: ATOM-BAD" in output

    def test_trace_atom_workspace_not_initialized(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "atom", "missing_run", known_ids["atom_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Workspace not initialized" in output

    def test_trace_atom_indexes_missing(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        trace_index_path = manager.structure.indexes_dir / "trace_index.json"
        trace_index_path.unlink()

        exit_code = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_atom_indexes_malformed(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        trace_index_path = manager.structure.indexes_dir / "trace_index.json"
        trace_index_path.write_text("{malformed", encoding="utf-8")

        exit_code = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes are malformed" in output


class TestTraceSectionCommand:
    def test_trace_section_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "section", known_ids["run_id"], known_ids["section_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"**Section**: {known_ids['section_id']}" in output

    def test_trace_section_not_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace
        missing_section = f"SEC-{known_ids['file_id']}-9999"

        exit_code = main(["trace", "section", known_ids["run_id"], missing_section])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert f"Section not found: {missing_section}" in output

    def test_trace_section_invalid_format(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "section", known_ids["run_id"], "SEC-BAD"])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert "Section not found: SEC-BAD" in output

    def test_trace_section_workspace_not_initialized(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "section", "missing_run", known_ids["section_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Workspace not initialized" in output

    def test_trace_section_indexes_missing(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        trace_index_path = manager.structure.indexes_dir / "trace_index.json"
        trace_index_path.unlink()

        exit_code = main(["trace", "section", known_ids["run_id"], known_ids["section_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_section_output_format(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "section", known_ids["run_id"], known_ids["section_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"**Section**: {known_ids['section_id']}" in output
        assert "**Spec Elements**" in output
        assert f"Tasks: {known_ids['task_id']}" in output


class TestTraceElementCommand:
    def test_trace_element_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "element", known_ids["run_id"], known_ids["element_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"**Element**: {known_ids['element_id']}" in output

    def test_trace_element_not_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace
        missing_element = "REQ-LIB-9999-0001"

        exit_code = main(["trace", "element", known_ids["run_id"], missing_element])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert f"Element not found: {missing_element}" in output

    def test_trace_element_invalid_format(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "element", known_ids["run_id"], "REQ-INVALID"])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert "Element not found: REQ-INVALID" in output

    def test_trace_element_workspace_not_initialized(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "element", "missing_run", known_ids["element_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Workspace not initialized" in output

    def test_trace_element_indexes_missing(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        trace_index_path = manager.structure.indexes_dir / "trace_index.json"
        trace_index_path.unlink()

        exit_code = main(["trace", "element", known_ids["run_id"], known_ids["element_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_element_output_format(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "element", known_ids["run_id"], known_ids["element_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"**Element**: {known_ids['element_id']}" in output
        assert f"- {known_ids['section_id']} (from LIB-0001)" in output
        assert f"- {known_ids['task_id']}" in output
        assert f"Patch: {known_ids['patch_path']}" in output


class TestTraceTaskCommand:
    def test_trace_task_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "task", known_ids["run_id"], known_ids["task_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"**Task**: {known_ids['task_id']}" in output

    def test_trace_task_not_found(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace
        missing_task = "TASK-9999"

        exit_code = main(["trace", "task", known_ids["run_id"], missing_task])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert f"Task not found: {missing_task}" in output

    def test_trace_task_invalid_format(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "task", known_ids["run_id"], "TASK-BAD"])
        output = capsys.readouterr().out

        assert exit_code == 2
        assert "Task not found: TASK-BAD" in output

    def test_trace_task_workspace_not_initialized(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "task", "missing_run", known_ids["task_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Workspace not initialized" in output

    def test_trace_task_indexes_missing(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        trace_index_path = manager.structure.indexes_dir / "trace_index.json"
        trace_index_path.unlink()

        exit_code = main(["trace", "task", known_ids["run_id"], known_ids["task_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_task_output_format(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "task", known_ids["run_id"], known_ids["task_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"**Task**: {known_ids['task_id']}" in output
        assert f"- Patch: {known_ids['patch_path']}" in output
        assert f"- SHA256: {known_ids['patch_hash']}" in output
        assert "- Status: done" in output
        assert f"- {known_ids['element_id']} (requirement, from LIB-0001)" in output
        assert f"Source sections: {known_ids['section_id']}" in output


class TestTraceCommandErrors:
    def test_trace_atom_missing_index_file(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        (manager.structure.indexes_dir / "atom_to_section.json").unlink()

        exit_code = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_section_missing_index_file(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        (manager.structure.indexes_dir / "section_to_spec_elements.json").unlink()

        exit_code = main(["trace", "section", known_ids["run_id"], known_ids["section_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_element_missing_index_file(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        (manager.structure.indexes_dir / "spec_element_to_tasks.json").unlink()

        exit_code = main(["trace", "element", known_ids["run_id"], known_ids["element_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_task_missing_index_file(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        (manager.structure.indexes_dir / "task_to_patches.json").unlink()

        exit_code = main(["trace", "task", known_ids["run_id"], known_ids["task_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output

    def test_trace_indexes_malformed_json(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        bad_index = manager.structure.indexes_dir / "section_to_spec_elements.json"
        bad_index.write_text("{bad", encoding="utf-8")

        exit_code = main(["trace", "element", known_ids["run_id"], known_ids["element_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes are malformed" in output

    def test_trace_indexes_missing_keys(self, trace_workspace, capsys) -> None:
        manager, known_ids = trace_workspace
        trace_index_path = manager.structure.indexes_dir / "trace_index.json"
        trace_index_path.write_text(json.dumps({"indexes": {}}), encoding="utf-8")

        exit_code = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output = capsys.readouterr().out

        assert exit_code == 1
        assert "Trace indexes not found" in output


class TestTraceOutputContent:
    def test_atom_trace_shows_full_chain(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace
        expected_sha = _hash_text("First line")

        exit_code = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"- File: {known_ids['file_id']}" in output
        assert f"- Section: {known_ids['section_id']}" in output
        assert f"- SHA256: {expected_sha}" in output
        assert f"{known_ids['element_id']}" in output
        assert f"{known_ids['task_id']}" in output
        assert f"{known_ids['patch_path']}" in output

    def test_section_trace_shows_elements_and_tasks(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "section", known_ids["run_id"], known_ids["section_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"{known_ids['element_id']}" in output
        assert f"{known_ids['task_id']}" in output

    def test_element_trace_shows_bidirectional_links(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "element", known_ids["run_id"], known_ids["element_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"{known_ids['section_id']}" in output
        assert f"{known_ids['task_id']}" in output

    def test_task_trace_shows_coverage(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code = main(["trace", "task", known_ids["run_id"], known_ids["task_id"]])
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"{known_ids['element_id']}" in output
        assert f"{known_ids['section_id']}" in output

    def test_trace_output_deterministic(self, trace_workspace, capsys) -> None:
        _, known_ids = trace_workspace

        exit_code_first = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output_first = capsys.readouterr().out

        exit_code_second = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
        output_second = capsys.readouterr().out

        assert exit_code_first == 0
        assert exit_code_second == 0
        assert output_first == output_second


@pytest.mark.integration
def test_trace_full_provenance_chain(trace_workspace, capsys) -> None:
    _, known_ids = trace_workspace

    atom_exit = main(["trace", "atom", known_ids["run_id"], known_ids["atom_id"]])
    atom_output = capsys.readouterr().out

    assert atom_exit == 0
    assert f"{known_ids['element_id']}" in atom_output
    assert f"Tasks: {known_ids['task_id']}" in atom_output

    task_exit = main(["trace", "task", known_ids["run_id"], known_ids["task_id"]])
    task_output = capsys.readouterr().out

    assert task_exit == 0
    assert f"{known_ids['section_id']}" in task_output
    assert f"{known_ids['element_id']}" in task_output

    assert f"{known_ids['task_id']}" in atom_output
    assert f"{known_ids['element_id']}" in task_output


class TestTraceCommandArguments:
    def test_trace_missing_run_id(self) -> None:
        with pytest.raises(SystemExit):
            main(["trace", "atom"])

    def test_trace_missing_entity_id(self) -> None:
        with pytest.raises(SystemExit):
            main(["trace", "atom", "run1"])

    def test_trace_invalid_command(self) -> None:
        with pytest.raises(SystemExit):
            main(["trace", "invalid", "run1", "ID"])

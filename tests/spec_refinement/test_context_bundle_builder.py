from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.refinement.workflows.implementation import (
    build_context_bundle,
    write_context_bundle,
)
from spec_manager.schemas.tasks import TaskCoversSchema, TaskSchema, write_task_json

from tests.spec_refinement.fixtures.test_corpus import create_task_planning_prerequisites

pytestmark = [pytest.mark.implementation]


def _write_task(run_root: Path, task: TaskSchema) -> None:
    task_dir = run_root / "tasks" / task.task_id
    write_task_json(task, task_dir / "task.json")


def _seed_spec_snapshot(
    fs,
    run_root: Path,
    manifest: dict[str, object],
    *,
    include_interfaces: bool = False,
) -> None:
    snapshot_root = run_root / "spec_snapshot" / "libraries"
    fs.create_dir(snapshot_root)
    library_ids = manifest.get("library_ids", [])
    for lib_id in library_ids:
        src_dir = run_root / "libraries" / lib_id
        dest_dir = snapshot_root / lib_id
        fs.create_dir(dest_dir)
        for filename in ["spec.md", "spec_index.json", "decisions_index.json"]:
            src = src_dir / filename
            if src.exists():
                (dest_dir / filename).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        if include_interfaces:
            src_interfaces = src_dir / "interfaces"
            if src_interfaces.exists():
                dest_interfaces = dest_dir / "interfaces"
                fs.create_dir(dest_interfaces)
                for interface_file in src_interfaces.iterdir():
                    (dest_interfaces / interface_file.name).write_text(
                        interface_file.read_text(encoding="utf-8"), encoding="utf-8"
                    )


def test_build_context_bundle_includes_task_requirements(interface_workspace, fs) -> None:
    manager, _manifest = interface_workspace(run_id="run_context_requirements")
    repo_root = manager.input_folder
    fs.create_dir(repo_root / "app")
    (repo_root / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    task = TaskSchema(
        task_id="TASK-0001",
        title="Update handler",
        description="Update the handler logic.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(elements=["REQ-LIB-0001-0001"], edges=[], decisions=[], gaps=[]),
        acceptance_criteria=["Behavior updated.", "Tests added."],
        suggested_files=["app/main.py"],
        risk_notes="Low risk.",
        validation_notes="Run tests.",
        citations=["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        depends_on=[],
    )
    _write_task(manager.run_root, task)

    content = build_context_bundle(manager.run_root, "TASK-0001", repo_root)

    assert "# Task Requirements" in content
    assert "TASK-0001" in content
    assert "Update the handler logic." in content
    assert "Behavior updated." in content
    assert "Tests added." in content


def test_build_context_bundle_includes_spec_snippets(interface_workspace, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_context_specs")
    repo_root = manager.input_folder
    fs.create_dir(repo_root / "app")
    (repo_root / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    _seed_spec_snapshot(fs, manager.run_root, manifest)

    task = TaskSchema(
        task_id="TASK-0001",
        title="Update handler",
        description="Update the handler logic.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(elements=["REQ-LIB-0001-0001"], edges=[], decisions=[], gaps=[]),
        acceptance_criteria=["Behavior updated."],
        suggested_files=["app/main.py"],
        risk_notes="",
        validation_notes="",
        citations=[],
        depends_on=[],
    )
    _write_task(manager.run_root, task)

    content = build_context_bundle(manager.run_root, "TASK-0001", repo_root)

    assert "Relevant Specs / Interfaces" in content
    assert "REQ-LIB-0001-0001" in content
    assert "[LIB-0001::spec.md::REQ-LIB-0001-0001]" in content


def test_build_context_bundle_includes_interface_contracts(interface_workspace, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_context_interfaces")
    repo_root = manager.input_folder
    fs.create_dir(repo_root / "app")
    (repo_root / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    create_task_planning_prerequisites(fs, manager.run_id, manifest)
    _seed_spec_snapshot(fs, manager.run_root, manifest, include_interfaces=True)

    task = TaskSchema(
        task_id="TASK-0001",
        title="Update handler",
        description="Update the handler logic.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(
            elements=[],
            edges=["EDGE-LIB-0001-LIB-0002"],
            decisions=[],
            gaps=[],
        ),
        acceptance_criteria=["Behavior updated."],
        suggested_files=["app/main.py"],
        risk_notes="",
        validation_notes="",
        citations=[],
        depends_on=[],
    )
    _write_task(manager.run_root, task)

    content = build_context_bundle(manager.run_root, "TASK-0001", repo_root)

    assert "EDGE-LIB-0001-LIB-0002" in content
    assert "Interface Contract" in content


def test_build_context_bundle_includes_suggested_files(interface_workspace, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_context_files")
    _ = manifest
    repo_root = manager.input_folder
    fs.create_dir(repo_root / "app")
    (repo_root / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    task = TaskSchema(
        task_id="TASK-0001",
        title="Update handler",
        description="Update the handler logic.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(elements=[], edges=[], decisions=[], gaps=[]),
        acceptance_criteria=["Behavior updated."],
        suggested_files=["app/main.py"],
        risk_notes="",
        validation_notes="",
        citations=[],
        depends_on=[],
    )
    _write_task(manager.run_root, task)

    content = build_context_bundle(manager.run_root, "TASK-0001", repo_root)

    assert "# Relevant Code Context" in content
    assert "print('hello')" in content


def test_build_context_bundle_truncates_large_files(interface_workspace, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_context_truncate")
    _ = manifest
    repo_root = manager.input_folder
    fs.create_dir(repo_root / "app")
    large_path = repo_root / "app" / "large.py"
    large_path.write_text("line\n" * 3000, encoding="utf-8")

    task = TaskSchema(
        task_id="TASK-0001",
        title="Update handler",
        description="Update the handler logic.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(elements=[], edges=[], decisions=[], gaps=[]),
        acceptance_criteria=["Behavior updated."],
        suggested_files=["app/large.py"],
        risk_notes="",
        validation_notes="",
        citations=[],
        depends_on=[],
    )
    _write_task(manager.run_root, task)

    content = build_context_bundle(manager.run_root, "TASK-0001", repo_root)

    assert "truncated" in content


def test_build_context_bundle_respects_token_limits(interface_workspace, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_context_token_limits")
    _ = manifest
    repo_root = manager.input_folder
    fs.create_dir(repo_root / "app")

    suggested_files: list[str] = []
    for idx in range(12):
        rel_path = f"app/large_{idx}.py"
        suggested_files.append(rel_path)
        (repo_root / rel_path).write_text("line\n" * 2000, encoding="utf-8")

    task = TaskSchema(
        task_id="TASK-0001",
        title="Update handler",
        description="Update the handler logic.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(elements=[], edges=[], decisions=[], gaps=[]),
        acceptance_criteria=["Behavior updated."],
        suggested_files=suggested_files,
        risk_notes="",
        validation_notes="",
        citations=[],
        depends_on=[],
    )
    _write_task(manager.run_root, task)

    content = build_context_bundle(manager.run_root, "TASK-0001", repo_root)

    assert len(content) < 50500
    assert "truncated" in content


def test_write_context_bundle_creates_file(interface_workspace, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_context_write")
    _ = manifest
    repo_root = manager.input_folder
    fs.create_dir(repo_root / "app")
    (repo_root / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    task = TaskSchema(
        task_id="TASK-0001",
        title="Update handler",
        description="Update the handler logic.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema(elements=[], edges=[], decisions=[], gaps=[]),
        acceptance_criteria=["Behavior updated."],
        suggested_files=["app/main.py"],
        risk_notes="",
        validation_notes="",
        citations=[],
        depends_on=[],
    )
    _write_task(manager.run_root, task)

    content = build_context_bundle(manager.run_root, "TASK-0001", repo_root)
    output_path = write_context_bundle(manager.run_root, "TASK-0001", content)

    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").startswith("# Task Requirements")

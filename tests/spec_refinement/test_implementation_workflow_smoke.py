from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from spec_manager.refinement.workflows.implementation import (
    ImplementationConfig,
    _filter_tasks_with_prerequisites,
    _topological_sort_tasks,
    execute_task,
    run_implementation_phase,
)
from spec_manager.refinement.workflows.patch_utils import (
    IMMUTABLE_PATH_PATTERNS,
    validate_patch,
)
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager
from spec_manager.schemas.task_status import (
    TaskImplementationStatusSchema,
    TestResultSchema,
    read_task_implementation_status_json,
    write_task_implementation_status_json,
)
from spec_manager.schemas.tasks import (
    PatchGraphSchema,
    TaskCoversSchema,
    TaskIndexEntrySchema,
    TaskIndexSchema,
    TaskSchema,
    TaskStatusSchema,
    write_patch_graph_json,
    write_task_index_json,
    write_task_json,
    write_task_markdown,
    write_task_status_json,
)

from tests.spec_refinement.fixtures.agent_mocks import MockAgentController

pytestmark = [pytest.mark.implementation, pytest.mark.workflow_smoke]


def _now_iso() -> str:
    return datetime.now().isoformat()


def _make_task(
    task_id: str,
    *,
    suggested_files: list[str],
    depends_on: list[str] | None = None,
    covers: TaskCoversSchema | None = None,
) -> TaskSchema:
    return TaskSchema(
        task_id=task_id,
        title=f"Implement {task_id}",
        description=f"Implement workflow for {task_id}.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=covers
        or TaskCoversSchema(
            elements=["DTL-LIB-0001-0001"],
            edges=[],
            decisions=[],
            gaps=[],
        ),
        acceptance_criteria=["Behavior updated.", "Tests cover changes."],
        suggested_files=suggested_files,
        risk_notes="Low risk.",
        validation_notes="Run tests.",
        citations=["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
        depends_on=depends_on or [],
    )


def _create_task_planning_output(run_root: Path, tasks: list[TaskSchema]) -> None:
    tasks_dir = run_root / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    created_at = _now_iso()
    entries: list[TaskIndexEntrySchema] = []
    for task in tasks:
        task_dir = tasks_dir / task.task_id
        write_task_json(task, task_dir / "task.json")
        write_task_markdown(task, task_dir / "task.md")
        status = TaskStatusSchema(
            task_id=task.task_id,
            status="planned",
            created_at=created_at,
            updated_at=created_at,
            task_hash="",
            notes="",
        )
        write_task_status_json(status, task_dir / "status.json")
        entries.append(
            TaskIndexEntrySchema(
                task_id=task.task_id,
                title=task.title,
                status="planned",
                priority=task.priority,
                component=task.component,
                libraries=task.libraries,
                covers=task.covers,
                depends_on=task.depends_on,
            )
        )

    index = TaskIndexSchema(
        run_id=run_root.name,
        generated_at=created_at,
        tasks=entries,
    )
    write_task_index_json(index, tasks_dir / "task_index.json")

    edges: list[tuple[str, str]] = []
    for task in tasks:
        for dep in task.depends_on:
            edges.append((dep, task.task_id))
    graph = PatchGraphSchema(
        run_id=run_root.name,
        generated_at=created_at,
        nodes=[task.task_id for task in tasks],
        edges=edges,
    )
    write_patch_graph_json(graph, tasks_dir / "patch_graph.json")


def _complete_task_planning_prerequisites(manager: WorkspaceManager, task_count: int) -> None:
    manager.start_phase(Phase.INTERFACES)
    manager.complete_phase(
        Phase.INTERFACES,
        outputs={
            "edge_list_path": "edge_list.json",
            "interface_index_path": "interface_index.json",
        },
    )
    manager.start_phase(Phase.ARCHITECTURE_MAPPING)
    manager.complete_phase(Phase.ARCHITECTURE_MAPPING, outputs={"mapped": 1})
    manager.start_phase(Phase.TASKS)
    manager.complete_phase(
        Phase.TASKS,
        outputs={
            "task_index_path": "tasks/task_index.json",
            "patch_graph_path": "tasks/patch_graph.json",
            "task_count": task_count,
        },
    )


def _create_toy_repo_files(fs, repo_root: Path, files: list[str] | None = None) -> list[str]:
    file_paths = files or ["app/main.py", "app/utils.py", "lib/worker.py"]
    for rel_path in file_paths:
        full_path = repo_root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text("def handler():\n    return True\n", encoding="utf-8")
    return file_paths


def _assert_implementation_artifacts_exist(run_root: Path, task_id: str) -> None:
    task_dir = run_root / "tasks" / task_id
    assert (task_dir / "context_bundle.md").exists()
    assert (task_dir / "patch.diff").exists()
    assert (task_dir / "backup").exists()
    assert (task_dir / "apply_log.json").exists()
    assert (task_dir / "audit.md").exists()
    assert (task_dir / "status.json").exists()


@pytest.fixture
def mock_implementation_agents(monkeypatch):
    def _apply(
        manifest: dict[str, dict[str, object]],
        *,
        implementation_violation_mode: str | None = None,
        patch_audit_violation_mode: str | None = None,
        patch_repair_violation_mode: str | None = None,
        overrides: dict[str, float] | None = None,
    ) -> MockAgentController:
        controller = MockAgentController(manifest=manifest, violation_rate=0.0)
        controller.implementation_violation_mode = implementation_violation_mode
        controller.patch_audit_violation_mode = patch_audit_violation_mode
        controller.patch_repair_violation_mode = patch_repair_violation_mode
        if overrides:
            controller.violation_overrides.update(overrides)

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "spec_manager.refinement.repair.run_agent",
            controller.dispatch,
        )
        return controller

    return _apply


class TestExecuteTaskSmoke:
    def test_execute_task_creates_artifacts(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_artifacts")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest)

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=2,
            manager=manager,
            config=config,
        )

        _assert_implementation_artifacts_exist(manager.run_root, "TASK-0001")

    def test_execute_task_applies_patch(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_apply")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest)

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=2,
            manager=manager,
            config=config,
        )

        updated = (repo_root / "app/main.py").read_text(encoding="utf-8")
        assert "# updated" in updated

        backup_log = manager.run_root / "tasks" / "TASK-0001" / "backup" / "apply_log.json"
        assert backup_log.exists()
        payload = json.loads(backup_log.read_text(encoding="utf-8"))
        backup_records = payload.get("backup_records", [])
        assert backup_records
        assert Path(backup_records[0]["backup_path"]).exists()

    def test_execute_task_runs_tests_when_enabled(
        self, interface_workspace, mock_implementation_agents, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_tests")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest)

        def _fake_run_tests(task_dir, repo_root, test_command=None, run_tests_flag=True):
            if not run_tests_flag:
                return None
            output_path = task_dir / "test_output.txt"
            output_path.write_text("ok", encoding="utf-8")
            now = _now_iso()
            return TestResultSchema(
                ran=True,
                command=test_command or "pytest",
                exit_code=0,
                started_at=now,
                finished_at=now,
                duration_s=0.01,
            )

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.run_tests", _fake_run_tests
        )

        config = ImplementationConfig(run_tests=True, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=1,
            manager=manager,
            config=config,
        )

        task_dir = manager.run_root / "tasks" / "TASK-0001"
        assert (task_dir / "test_output.txt").exists()
        status = read_task_implementation_status_json(task_dir / "status.json")
        assert status.tests is not None
        assert status.tests.exit_code == 0

    def test_execute_task_writes_audit_report(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_audit")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest)

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=1,
            manager=manager,
            config=config,
        )

        audit_content = (manager.run_root / "tasks" / "TASK-0001" / "audit.md").read_text(
            encoding="utf-8"
        )
        assert "## Verdict" in audit_content
        assert "## Acceptance Criteria Assessment" in audit_content
        assert "## Issues" in audit_content

    def test_execute_task_updates_status_json(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_status")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest)

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=1,
            manager=manager,
            config=config,
        )

        status = read_task_implementation_status_json(
            manager.run_root / "tasks" / "TASK-0001" / "status.json"
        )
        assert status.status == "done"
        assert status.patch_sha256
        assert status.applied_files == ["app/main.py"]

    def test_run_implementation_phase_executes_multiple_tasks(
        self, interface_workspace, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_phase")
        _ = manifest
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py", "app/utils.py", "lib/worker.py"])

        tasks = [
            _make_task("TASK-0001", suggested_files=["app/main.py"]),
            _make_task("TASK-0002", suggested_files=["app/utils.py"], depends_on=["TASK-0001"]),
            _make_task("TASK-0003", suggested_files=["lib/worker.py"], depends_on=["TASK-0002"]),
        ]
        _create_task_planning_output(manager.run_root, tasks)
        _complete_task_planning_prerequisites(manager, len(tasks))

        calls: list[str] = []

        def _fake_execute_task(run_root, task_id, repo_root, max_iterations, manager, config):
            _ = run_root, repo_root, max_iterations, manager, config
            calls.append(task_id)
            return {
                "task_id": task_id,
                "status": "done",
                "applied_files": 1,
                "tests": None,
            }

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.execute_task", _fake_execute_task
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        run_implementation_phase(
            run_root=manager.run_root,
            repo_root=repo_root,
            task_filter=None,
            max_iterations=1,
            config=config,
        )

        assert calls == ["TASK-0001", "TASK-0002", "TASK-0003"]
        refreshed = WorkspaceManager(run_id=manager.run_id, input_folder=repo_root)
        phase_result = refreshed.state.phases[Phase.IMPLEMENTATION.value]
        assert phase_result.status == PhaseStatus.COMPLETED

    def test_run_implementation_phase_respects_task_filter(
        self, interface_workspace, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_filter")
        _ = manifest
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py", "app/utils.py", "lib/worker.py"])

        tasks = [
            _make_task("TASK-0001", suggested_files=["app/main.py"]),
            _make_task("TASK-0002", suggested_files=["app/utils.py"], depends_on=["TASK-0001"]),
            _make_task("TASK-0003", suggested_files=["lib/worker.py"]),
            _make_task("TASK-0004", suggested_files=["app/main.py"], depends_on=["TASK-0002"]),
            _make_task("TASK-0005", suggested_files=["app/utils.py"]),
        ]
        _create_task_planning_output(manager.run_root, tasks)
        _complete_task_planning_prerequisites(manager, len(tasks))

        calls: list[str] = []

        def _fake_execute_task(run_root, task_id, repo_root, max_iterations, manager, config):
            _ = run_root, repo_root, max_iterations, manager, config
            calls.append(task_id)
            return {
                "task_id": task_id,
                "status": "done",
                "applied_files": 1,
                "tests": None,
            }

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.execute_task", _fake_execute_task
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        run_implementation_phase(
            run_root=manager.run_root,
            repo_root=repo_root,
            task_filter=["TASK-0002", "TASK-0004"],
            max_iterations=1,
            config=config,
        )

        assert calls == ["TASK-0001", "TASK-0002", "TASK-0004"]


class TestRepairLoops:
    def test_patch_generation_repair_loop_succeeds(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_repair_patch")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        controller = mock_implementation_agents(
            manifest, implementation_violation_mode="invalid_patch"
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=2,
            manager=manager,
            config=config,
        )

        repair_calls = [
            call for call in controller.call_log if call["agent_name"] == "chatgpt-patch-repairer"
        ]
        assert len(repair_calls) == 1

    def test_patch_generation_repair_loop_fails_after_max_iterations(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_repair_fail")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        controller = mock_implementation_agents(
            manifest,
            implementation_violation_mode="invalid_patch",
            patch_repair_violation_mode="persistent_failure",
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        result = execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=3,
            manager=manager,
            config=config,
        )

        assert result["status"] == "failed"
        assert "validation failed" in result.get("error", "")
        repair_calls = [
            call for call in controller.call_log if call["agent_name"] == "chatgpt-patch-repairer"
        ]
        assert len(repair_calls) == 3

    def test_audit_repair_loop_succeeds(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_audit_repair")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        controller = mock_implementation_agents(
            manifest,
            patch_audit_violation_mode="fail_audit_once",
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=2,
            manager=manager,
            config=config,
        )

        audit_calls = [
            call
            for call in controller.call_log
            if call["agent_name"] == "chatgpt-patch-audit-judge"
        ]
        repair_calls = [
            call for call in controller.call_log if call["agent_name"] == "chatgpt-patch-repairer"
        ]
        assert len(audit_calls) >= 2
        assert repair_calls

    def test_audit_repair_loop_fails_after_max_iterations(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_audit_fail")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        controller = mock_implementation_agents(
            manifest,
            patch_audit_violation_mode="fail_audit",
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        result = execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=2,
            manager=manager,
            config=config,
        )

        assert result["status"] == "failed"
        repair_calls = [
            call for call in controller.call_log if call["agent_name"] == "chatgpt-patch-repairer"
        ]
        assert len(repair_calls) == 2

    def test_test_failure_repair_loop_succeeds(
        self, interface_workspace, mock_implementation_agents, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_test_repair")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        controller = mock_implementation_agents(manifest)

        call_count = {"tests": 0}

        def _fake_run_tests(task_dir, repo_root, test_command=None, run_tests_flag=True):
            if not run_tests_flag:
                return None
            call_count["tests"] += 1
            output_path = task_dir / "test_output.txt"
            output_path.write_text("output", encoding="utf-8")
            now = _now_iso()
            exit_code = 1 if call_count["tests"] == 1 else 0
            return TestResultSchema(
                ran=True,
                command=test_command or "pytest",
                exit_code=exit_code,
                started_at=now,
                finished_at=now,
                duration_s=0.01,
            )

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.run_tests", _fake_run_tests
        )

        config = ImplementationConfig(run_tests=True, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=2,
            manager=manager,
            config=config,
        )

        repair_calls = [
            call for call in controller.call_log if call["agent_name"] == "chatgpt-patch-repairer"
        ]
        assert repair_calls
        status = read_task_implementation_status_json(
            manager.run_root / "tasks" / "TASK-0001" / "status.json"
        )
        assert status.tests is not None
        assert status.tests.exit_code == 0

    def test_test_failure_repair_loop_respects_max_iterations(
        self, interface_workspace, mock_implementation_agents, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_test_fail")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        controller = mock_implementation_agents(manifest)

        def _fake_run_tests(task_dir, repo_root, test_command=None, run_tests_flag=True):
            if not run_tests_flag:
                return None
            output_path = task_dir / "test_output.txt"
            output_path.write_text("output", encoding="utf-8")
            now = _now_iso()
            return TestResultSchema(
                ran=True,
                command=test_command or "pytest",
                exit_code=1,
                started_at=now,
                finished_at=now,
                duration_s=0.01,
            )

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.run_tests", _fake_run_tests
        )

        config = ImplementationConfig(run_tests=True, run_lint=False, allow_test_repair=True)
        result = execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=1,
            manager=manager,
            config=config,
        )

        assert result["status"] == "failed"
        repair_calls = [
            call for call in controller.call_log if call["agent_name"] == "chatgpt-patch-repairer"
        ]
        assert len(repair_calls) == 1


class TestImmutablePaths:
    def test_patch_validation_rejects_spec_snapshot_modification(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_immutable_spec")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest, implementation_violation_mode="immutable_path")

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        result = execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=0,
            manager=manager,
            config=config,
        )

        assert result["status"] == "failed"
        assert "immutable_path" in result.get("error", "")
        assert not (manager.run_root / "tasks" / "TASK-0001" / "patch.diff").exists()

    def test_patch_validation_rejects_manifest_modification(
        self, interface_workspace, mock_implementation_agents, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_immutable_manifest")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        controller = mock_implementation_agents(manifest)

        def _immutable_manifest(prompt: str, *, violation_mode: str | None = None) -> str:
            _ = violation_mode
            patch_text = (
                "diff --git a/runs/run_001/manifest/manifest.json "
                "b/runs/run_001/manifest/manifest.json\n"
                "--- a/runs/run_001/manifest/manifest.json\n"
                "+++ b/runs/run_001/manifest/manifest.json\n"
                "@@ -1,1 +1,1 @@\n"
                "-old\n"
                "+new\n"
            )
            return json.dumps({"patch": patch_text})

        monkeypatch.setattr(
            "tests.spec_refinement.fixtures.agent_mocks.mock_task_implementer_agent",
            _immutable_manifest,
        )
        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.run_agent",
            controller.dispatch,
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        result = execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=0,
            manager=manager,
            config=config,
        )

        assert result["status"] == "failed"
        assert "immutable_path" in result.get("error", "")

    def test_patch_repair_corrects_immutable_path_violation(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_immutable_repair")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest, implementation_violation_mode="immutable_path")

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        result = execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=2,
            manager=manager,
            config=config,
        )

        assert result["status"] == "done"
        status = read_task_implementation_status_json(
            manager.run_root / "tasks" / "TASK-0001" / "status.json"
        )
        assert status.patch_sha256

    @pytest.mark.parametrize(
        "pattern,path",
        [
            ("runs/*/spec_snapshot/**", "runs/run_001/spec_snapshot/libraries/LIB-0001/spec.md"),
            ("runs/*/manifest/**", "runs/run_001/manifest/manifest.json"),
        ],
    )
    def test_immutable_path_patterns_comprehensive(self, fs, pattern: str, path: str) -> None:
        _ = pattern
        repo_root = Path("/repo")
        fs.create_dir(repo_root)
        patch_text = (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        valid, errors = validate_patch(patch_text, repo_root, IMMUTABLE_PATH_PATTERNS)
        assert valid is False
        assert any(error["type"] == "immutable_path" for error in errors)


class TestTaskOrdering:
    def test_topological_sort_respects_dependencies(self) -> None:
        graph = PatchGraphSchema(
            run_id="run_001",
            generated_at=_now_iso(),
            nodes=["TASK-0001", "TASK-0002", "TASK-0003"],
            edges=[("TASK-0001", "TASK-0002"), ("TASK-0002", "TASK-0003")],
        )
        order = _topological_sort_tasks(graph)
        assert order == ["TASK-0001", "TASK-0002", "TASK-0003"]

    def test_topological_sort_handles_parallel_tasks(self) -> None:
        graph = PatchGraphSchema(
            run_id="run_001",
            generated_at=_now_iso(),
            nodes=["TASK-0001", "TASK-0002", "TASK-0003", "TASK-0004"],
            edges=[
                ("TASK-0001", "TASK-0002"),
                ("TASK-0001", "TASK-0003"),
                ("TASK-0002", "TASK-0004"),
                ("TASK-0003", "TASK-0004"),
            ],
        )
        order = _topological_sort_tasks(graph)
        assert order[0] == "TASK-0001"
        assert order[-1] == "TASK-0004"
        assert set(order[1:3]) == {"TASK-0002", "TASK-0003"}

    def test_topological_sort_detects_cycles(self) -> None:
        graph = SimpleNamespace(
            nodes=["TASK-0001", "TASK-0002"],
            edges=[("TASK-0001", "TASK-0002"), ("TASK-0002", "TASK-0001")],
        )
        with pytest.raises(RuntimeError, match="cycle"):
            _topological_sort_tasks(graph)

    def test_filter_tasks_with_prerequisites_includes_dependencies(self) -> None:
        graph = PatchGraphSchema(
            run_id="run_001",
            generated_at=_now_iso(),
            nodes=["TASK-0001", "TASK-0002", "TASK-0003"],
            edges=[("TASK-0001", "TASK-0002"), ("TASK-0002", "TASK-0003")],
        )
        filtered = _filter_tasks_with_prerequisites(["TASK-0003"], graph)
        assert filtered == ["TASK-0001", "TASK-0002", "TASK-0003"]

    def test_filter_tasks_with_prerequisites_excludes_unrelated(self) -> None:
        graph = PatchGraphSchema(
            run_id="run_001",
            generated_at=_now_iso(),
            nodes=["TASK-0001", "TASK-0002", "TASK-0003"],
            edges=[("TASK-0001", "TASK-0002")],
        )
        filtered = _filter_tasks_with_prerequisites(["TASK-0002"], graph)
        assert filtered == ["TASK-0001", "TASK-0002"]

    def test_run_implementation_phase_executes_in_dependency_order(
        self, interface_workspace, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_order")
        _ = manifest
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py", "app/utils.py", "lib/worker.py"])

        tasks = [
            _make_task("TASK-0001", suggested_files=["app/main.py"]),
            _make_task("TASK-0002", suggested_files=["app/utils.py"], depends_on=["TASK-0001"]),
            _make_task("TASK-0003", suggested_files=["lib/worker.py"], depends_on=["TASK-0002"]),
        ]
        _create_task_planning_output(manager.run_root, tasks)
        _complete_task_planning_prerequisites(manager, len(tasks))

        execution_order: list[str] = []

        def _fake_execute_task(run_root, task_id, repo_root, max_iterations, manager, config):
            _ = run_root, repo_root, max_iterations, manager, config
            execution_order.append(task_id)
            return {
                "task_id": task_id,
                "status": "done",
                "applied_files": 1,
                "tests": None,
            }

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.execute_task", _fake_execute_task
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        run_implementation_phase(
            run_root=manager.run_root,
            repo_root=repo_root,
            task_filter=None,
            max_iterations=1,
            config=config,
        )

        assert execution_order == ["TASK-0001", "TASK-0002", "TASK-0003"]


class TestPhaseTracking:
    def test_run_implementation_phase_updates_phase_state(
        self, interface_workspace, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_phase_state")
        _ = manifest
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])

        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)

        def _fake_execute_task(run_root, task_id, repo_root, max_iterations, manager, config):
            _ = run_root, repo_root, max_iterations, manager, config
            return {
                "task_id": task_id,
                "status": "done",
                "applied_files": 1,
                "tests": None,
            }

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.execute_task", _fake_execute_task
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        run_implementation_phase(
            run_root=manager.run_root,
            repo_root=repo_root,
            task_filter=None,
            max_iterations=1,
            config=config,
        )

        refreshed = WorkspaceManager(run_id=manager.run_id, input_folder=repo_root)
        phase_result = refreshed.state.phases[Phase.IMPLEMENTATION.value]
        assert phase_result.status == PhaseStatus.COMPLETED
        assert phase_result.started_at is not None
        assert phase_result.completed_at is not None

    def test_run_implementation_phase_records_outputs(
        self, interface_workspace, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_phase_outputs")
        _ = manifest
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py", "app/utils.py"])

        tasks = [
            _make_task("TASK-0001", suggested_files=["app/main.py"]),
            _make_task("TASK-0002", suggested_files=["app/utils.py"]),
        ]
        _create_task_planning_output(manager.run_root, tasks)
        _complete_task_planning_prerequisites(manager, len(tasks))

        def _fake_execute_task(run_root, task_id, repo_root, max_iterations, manager, config):
            _ = run_root, repo_root, max_iterations, manager, config
            tests = {
                "ran": True,
                "command": "pytest",
                "exit_code": 0 if task_id == "TASK-0001" else 1,
            }
            return {
                "task_id": task_id,
                "status": "done" if task_id == "TASK-0001" else "failed",
                "applied_files": 1,
                "tests": tests,
            }

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.execute_task", _fake_execute_task
        )

        config = ImplementationConfig(run_tests=True, run_lint=False, allow_test_repair=True)
        run_implementation_phase(
            run_root=manager.run_root,
            repo_root=repo_root,
            task_filter=None,
            max_iterations=1,
            config=config,
        )

        refreshed = WorkspaceManager(run_id=manager.run_id, input_folder=repo_root)
        phase_result = refreshed.state.phases[Phase.IMPLEMENTATION.value]
        outputs = phase_result.outputs
        assert outputs["tasks_executed"] == 2
        assert outputs["patches_applied"] == 2
        assert outputs["tests_passed"] == 1
        assert outputs["tests_failed"] == 1

    def test_task_status_transitions_correctly(
        self, interface_workspace, mock_implementation_agents, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_status_transition")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest)

        status_path = manager.run_root / "tasks" / "TASK-0001" / "status.json"
        planned = TaskImplementationStatusSchema(
            task_id="TASK-0001",
            status="planned",
            repo_root=str(repo_root),
        )
        write_task_implementation_status_json(planned, status_path)
        before = read_task_implementation_status_json(status_path)
        assert before.status == "planned"

        records: list[str] = []
        original_write = write_task_implementation_status_json

        def _record(status, output_path):
            records.append(status.status)
            return original_write(status, output_path)

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.write_task_implementation_status_json",
            _record,
        )

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=1,
            manager=manager,
            config=config,
        )

        assert "in_progress" in records
        assert records[-1] == "done"
        after = read_task_implementation_status_json(status_path)
        assert after.started_at is not None
        assert after.finished_at is not None

    def test_task_status_transitions_to_failed_on_error(
        self, interface_workspace, mock_implementation_agents, fs
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_status_failed")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py"])
        task = _make_task("TASK-0001", suggested_files=["app/main.py"])
        _create_task_planning_output(manager.run_root, [task])
        _complete_task_planning_prerequisites(manager, 1)
        mock_implementation_agents(manifest, implementation_violation_mode="raise_error")

        config = ImplementationConfig(run_tests=False, run_lint=False, allow_test_repair=True)
        execute_task(
            manager.run_root,
            "TASK-0001",
            repo_root,
            max_iterations=1,
            manager=manager,
            config=config,
        )

        status = read_task_implementation_status_json(
            manager.run_root / "tasks" / "TASK-0001" / "status.json"
        )
        assert status.status == "failed"
        assert status.finished_at is not None


@pytest.mark.slow
class TestFullWorkflow:
    def test_full_implementation_workflow_end_to_end(
        self, interface_workspace, mock_implementation_agents, fs, monkeypatch
    ) -> None:
        manager, manifest = interface_workspace(run_id="run_impl_end_to_end")
        repo_root = manager.input_folder
        _create_toy_repo_files(fs, repo_root, ["app/main.py", "app/utils.py", "lib/worker.py"])

        tasks = [
            _make_task("TASK-0001", suggested_files=["app/main.py"]),
            _make_task("TASK-0002", suggested_files=["app/utils.py"], depends_on=["TASK-0001"]),
            _make_task("TASK-0003", suggested_files=["lib/worker.py"], depends_on=["TASK-0002"]),
        ]
        _create_task_planning_output(manager.run_root, tasks)
        _complete_task_planning_prerequisites(manager, len(tasks))
        mock_implementation_agents(manifest)

        def _fake_run_tests(task_dir, repo_root, test_command=None, run_tests_flag=True):
            if not run_tests_flag:
                return None
            output_path = task_dir / "test_output.txt"
            output_path.write_text("ok", encoding="utf-8")
            now = _now_iso()
            return TestResultSchema(
                ran=True,
                command=test_command or "pytest",
                exit_code=0,
                started_at=now,
                finished_at=now,
                duration_s=0.01,
            )

        monkeypatch.setattr(
            "spec_manager.refinement.workflows.implementation.run_tests", _fake_run_tests
        )

        config = ImplementationConfig(run_tests=True, run_lint=False, allow_test_repair=True)
        result = run_implementation_phase(
            run_root=manager.run_root,
            repo_root=repo_root,
            task_filter=None,
            max_iterations=2,
            config=config,
        )

        executed = [summary["task_id"] for summary in result["task_summaries"]]
        assert executed == ["TASK-0001", "TASK-0002", "TASK-0003"]

        for task_id in executed:
            task_dir = manager.run_root / "tasks" / task_id
            assert (task_dir / "patch.diff").exists()
            assert (task_dir / "backup" / "apply_log.json").exists()
            assert (task_dir / "audit.md").exists()
            status = read_task_implementation_status_json(task_dir / "status.json")
            assert status.status == "done"
            assert status.tests is not None
            assert status.tests.exit_code == 0

        refreshed = WorkspaceManager(run_id=manager.run_id, input_folder=repo_root)
        phase_result = refreshed.state.phases[Phase.IMPLEMENTATION.value]
        assert phase_result.status == PhaseStatus.COMPLETED
        assert phase_result.outputs["tasks_executed"] == 3

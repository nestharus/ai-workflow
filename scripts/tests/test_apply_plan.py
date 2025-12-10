"""Integration tests for scripts.apply_plan orchestrator."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import yaml

from scripts.tasks.commands import clipboard_to_plan as clipboard_to_plan_module
from scripts.tasks.workflows import apply_plan, implementation, testing
from scripts.tasks.workflows.apply_plan import ApplyPlanError
from scripts.tasks.workflows.implementation import ImplementationResult
from scripts.tasks.workflows.testing import TestingResult

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


@pytest.fixture(autouse=True)
def patch_project_root(fake_repo_root: Path) -> Iterator[None]:
    """Ensure PROJECT_ROOT points to the fake repository."""
    with (
        patch.object(apply_plan, "PROJECT_ROOT", fake_repo_root),
        patch.object(implementation, "PROJECT_ROOT", fake_repo_root),
        patch.object(testing, "PROJECT_ROOT", fake_repo_root),
    ):
        yield


class TestComputePlanHash:
    """Tests for _compute_plan_hash."""

    def test_returns_sha256_hex(self) -> None:
        """Should compute deterministic SHA256 hex digest."""
        content = "example plan content"
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()

        assert apply_plan._compute_plan_hash(content) == expected


class TestParseTaskHeader:
    """Tests for _parse_task_header."""

    def test_extracts_header_line(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return the filepath from the first heading line."""
        task_path = fake_repo_root / "scripts" / "task_001.md"
        fs.create_file(str(task_path), contents="# app/main.py\nDetails here")

        assert apply_plan._parse_task_header(task_path) == "app/main.py"

    def test_returns_empty_when_no_lines(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return an empty string when the task file is empty."""
        task_path = fake_repo_root / "scripts" / "task_002.md"
        fs.create_file(str(task_path), contents="")

        assert apply_plan._parse_task_header(task_path) == ""


class TestCollectTasks:
    """Tests for _collect_tasks."""

    def test_collects_and_sorts_tasks(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should find task files and sort them by name."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))
        fs.create_file(str(task_dir / "task_002.md"), contents="# b\nbody")
        fs.create_file(str(task_dir / "task_001.md"), contents="# a\nbody")

        tasks = apply_plan._collect_tasks(task_dir)

        assert [t.name for t in tasks] == ["task_001.md", "task_002.md"]


class TestInitStatus:
    """Tests for _init_status."""

    def test_initializes_status_structure(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should create task entries with pending status."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))
        fs.create_file(str(task_dir / "task_001.md"), contents="# file_a\nDetails")
        fs.create_file(str(task_dir / "task_002.md"), contents="# file_b\nMore")

        status = apply_plan._init_status(task_dir, "hash123")

        assert status["plan_hash"] == "hash123"
        assert len(status["tasks"]) == 2
        assert status["tasks"][0]["task_file"] == "task_001.md"
        assert status["tasks"][0]["file"] == "file_a"
        assert status["tasks"][0]["status"] == "pending"


class TestUpdateStatus:
    """Tests for _update_status."""

    def test_updates_status_and_writes_yaml(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should update matching task and persist to YAML."""
        status_path = fake_repo_root / "scripts" / "status.yml"
        fs.create_file(str(status_path), contents="")
        status_data: dict[str, Any] = {
            "plan_hash": "hash",
            "tasks": [
                {"task_file": "task_001.md", "status": "pending", "file": "a.py"},
                {"task_file": "task_002.md", "status": "pending", "file": "b.py"},
            ],
        }

        apply_plan._update_status(status_path, status_data, "task_001.md", status="completed")

        updated = yaml.safe_load(status_path.read_text())
        assert any(task["status"] == "completed" for task in updated["tasks"])


class TestRunClipboardToPlan:
    """Tests for _run_clipboard_to_plan."""

    def test_returns_path_from_stdout(self) -> None:
        """Should convert subprocess stdout to Path."""
        completed = subprocess.CompletedProcess(
            args=[sys.executable], returncode=0, stdout="/fake/tasks/123\n", stderr=""
        )
        with patch("subprocess.run", return_value=completed):
            result = apply_plan._run_clipboard_to_plan()

        assert result == Path("/fake/tasks/123")

    def test_raises_on_failure(self) -> None:
        """Should raise ApplyPlanError when subprocess fails."""
        completed = subprocess.CompletedProcess(
            args=[sys.executable], returncode=1, stdout="", stderr="err"
        )
        with patch("subprocess.run", return_value=completed), pytest.raises(ApplyPlanError):
            apply_plan._run_clipboard_to_plan()

    def test_raises_on_empty_output(self) -> None:
        """Should raise ApplyPlanError when subprocess returns no output."""
        completed = subprocess.CompletedProcess(
            args=[sys.executable], returncode=0, stdout="", stderr=""
        )
        with patch("subprocess.run", return_value=completed), pytest.raises(ApplyPlanError):
            apply_plan._run_clipboard_to_plan()


class TestRunOpencodeAgent:
    """Tests for _run_opencode_agent."""

    def test_invokes_runner_with_agent(self) -> None:
        """Should call _run with implementor arguments."""
        mock_completed: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            [], 0, "", ""
        )
        with patch.object(apply_plan, "_run", return_value=mock_completed) as mock_run:
            result = apply_plan._run_opencode_agent("implementor", "prompt path")

        assert result is mock_completed
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        assert "opencode_agent_runner.py" in args[1]
        # Command: [python, runner, "--agent", agent, "--prompt", prompt]
        assert args[2:4] == ["--agent", "implementor"]
        assert args[-2:] == ["--prompt", "prompt path"]


class TestCreateChangesFiles:
    """Tests for _create_changes_files."""

    def test_creates_change_files_from_git_diff(
        self, fs: FakeFilesystem, fake_repo_root: Path
    ) -> None:
        """Should write .changes files for each modified path."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))

        def fake_run(
            cmd: list[str], *, capture_output: bool, text: bool, cwd: Path
        ) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["git", "diff", "--name-only"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="a.txt\nb/c.txt\n", stderr="")
            if cmd[:2] == ["git", "diff"]:
                target = cmd[-1]
                return subprocess.CompletedProcess(cmd, 0, stdout=f"diff for {target}", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            files = apply_plan._create_changes_files(task_dir)

        expected_files = {
            str(task_dir / "a.txt.changes"),
            str(task_dir / "b__c.txt.changes"),
        }
        assert set(files) == expected_files
        for path in expected_files:
            expected_content = (
                f"diff for {Path(path).name.replace('.changes', '').replace('__', '/')}"
            )
            assert Path(path).read_text() == expected_content

    def test_returns_empty_on_git_error(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return empty list when git diff fails."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))

        def fake_run(
            cmd: list[str], *, capture_output: bool, text: bool, cwd: Path
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="err")

        with patch("subprocess.run", side_effect=fake_run):
            assert apply_plan._create_changes_files(task_dir) == []


class TestDetectConclusion:
    """Tests for _detect_conclusion."""

    def test_returns_first_conclusion_file(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return sorted first .conclusion file when present."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))
        fs.create_file(str(task_dir / "b.conclusion"), contents="")
        fs.create_file(str(task_dir / "a.conclusion"), contents="")

        result = apply_plan._detect_conclusion(task_dir)

        assert result == task_dir / "a.conclusion"

    def test_returns_none_when_absent(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return None when no conclusion file exists."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))

        assert apply_plan._detect_conclusion(task_dir) is None


class TestPatchIncompleteTasks:
    """Tests for _patch_incomplete_tasks."""

    def test_invokes_task_patcher_for_incomplete_tasks(
        self, fs: FakeFilesystem, fake_repo_root: Path
    ) -> None:
        """Should call tasks agent for non-completed tasks and keep status."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))
        task_file = task_dir / "task_001.md"
        fs.create_file(str(task_file), contents="# file_a\nDetails")
        status_path = task_dir / "status.yml"
        status_data: dict[str, Any] = {
            "plan_hash": "old",
            "tasks": [
                {"task_file": "task_001.md", "status": "pending"},
                {"task_file": "task_002.md", "status": "completed"},
            ],
        }
        fs.create_file(str(status_path), contents=yaml.safe_dump(status_data))
        calls: list[str] = []

        def fake_run_tasks(agent: str, prompt: str) -> subprocess.CompletedProcess[str]:
            calls.append(agent)
            return subprocess.CompletedProcess([], 0)

        with patch.object(apply_plan, "_run_tasks_agent", side_effect=fake_run_tasks):
            apply_plan._patch_incomplete_tasks(task_dir, status_path, status_data, "new plan text")

        assert calls == ["task-patcher"]
        written = yaml.safe_load(status_path.read_text())
        assert written["tasks"][0]["status"] == "pending"


class TestProcessTask:
    """Tests for _process_task."""

    def _setup_task(
        self, fs: FakeFilesystem, fake_repo_root: Path
    ) -> tuple[Path, Path, dict[str, Any]]:
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))
        task_path = task_dir / "task_001.md"
        fs.create_file(str(task_path), contents="# file_a\nDo things")
        status_path = task_dir / "status.yml"
        status_data = {
            "plan_hash": "hash",
            "tasks": [{"task_file": "task_001.md", "status": "pending"}],
        }
        fs.create_file(str(status_path), contents=yaml.safe_dump(status_data))
        return task_dir, status_path, status_data

    def test_process_successful_task(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should mark task completed and run reviewer."""
        task_dir, status_path, status_data = self._setup_task(fs, fake_repo_root)

        with (
            patch.object(
                apply_plan,
                "_run_tasks_agent",
                return_value=subprocess.CompletedProcess([], 0, stdout="SUCCESS", stderr=""),
            ) as mock_tasks_agent,
            patch.object(
                apply_plan,
                "_run_opencode_agent",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ) as mock_opencode,
        ):
            result = apply_plan._process_task(
                task_dir, status_data["tasks"][0], status_path, status_data
            )

        assert result == "completed"
        assert status_data["tasks"][0]["status"] == "completed"
        mock_tasks_agent.assert_called_once()
        mock_opencode.assert_called_once()

    def test_process_task_with_failing_tests(
        self, fs: FakeFilesystem, fake_repo_root: Path
    ) -> None:
        """Should invoke run_testing_workflow and reset status to pending."""
        task_dir, status_path, status_data = self._setup_task(fs, fake_repo_root)

        with (
            patch.object(
                apply_plan,
                "_run_tasks_agent",
                return_value=subprocess.CompletedProcess(
                    [], 0, stdout="TESTS: [tests/unit/test_one.py::test_ok]", stderr=""
                ),
            ),
            patch.object(
                apply_plan,
                "run_testing_workflow",
                return_value=TestingResult(status="fixed", message="All tests pass"),
            ) as mock_testing,
        ):
            result = apply_plan._process_task(
                task_dir, status_data["tasks"][0], status_path, status_data
            )

        assert result == "tests"
        assert status_data["tasks"][0]["status"] == "pending"
        mock_testing.assert_called_once()

    def test_process_task_with_conclusion(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should mark pending with conclusion when detected."""
        task_dir, status_path, status_data = self._setup_task(fs, fake_repo_root)
        changes_file = task_dir / "change.changes"
        fs.create_file(str(changes_file), contents="diff content")

        tasks_agent_calls: list[str] = []

        def track_tasks_agent_calls(
            agent: str, *args: Any, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            tasks_agent_calls.append(agent)
            if agent == "implementor":
                return subprocess.CompletedProcess([], 0, stdout="FAIL: blocking issue", stderr="")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with (
            patch.object(
                apply_plan,
                "_run_tasks_agent",
                side_effect=track_tasks_agent_calls,
            ),
            patch.object(apply_plan, "_create_changes_files", return_value=[str(changes_file)]),
            patch.object(
                apply_plan, "_detect_conclusion", return_value=task_dir / "design.conclusion"
            ),
        ):
            result = apply_plan._process_task(
                task_dir, status_data["tasks"][0], status_path, status_data
            )

        assert result == "conclusion"
        assert status_data["tasks"][0]["status"] == "pending"
        assert status_data["tasks"][0]["conclusion_file"] == str(task_dir / "design.conclusion")
        assert "implementor" in tasks_agent_calls
        assert "implementation-analyzer" in tasks_agent_calls

    def test_process_task_with_failure_no_conclusion(
        self, fs: FakeFilesystem, fake_repo_root: Path
    ) -> None:
        """Should mark pending with changes when no conclusion is created."""
        task_dir, status_path, status_data = self._setup_task(fs, fake_repo_root)
        changes_file = task_dir / "change.changes"
        fs.create_file(str(changes_file), contents="diff content")

        tasks_agent_calls: list[str] = []

        def track_tasks_agent_calls(
            agent: str, *args: Any, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            tasks_agent_calls.append(agent)
            if agent == "implementor":
                return subprocess.CompletedProcess([], 0, stdout="FAIL: needs work", stderr="")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with (
            patch.object(
                apply_plan,
                "_run_tasks_agent",
                side_effect=track_tasks_agent_calls,
            ),
            patch.object(apply_plan, "_create_changes_files", return_value=[str(changes_file)]),
            patch.object(apply_plan, "_detect_conclusion", return_value=None),
        ):
            result = apply_plan._process_task(
                task_dir, status_data["tasks"][0], status_path, status_data
            )

        assert result == "fail"
        assert status_data["tasks"][0]["status"] == "pending"
        assert status_data["tasks"][0]["changes_file"] == [str(changes_file)]
        assert "implementor" in tasks_agent_calls
        assert "implementation-analyzer" in tasks_agent_calls


class TestMain:
    """Tests for main orchestrator flow."""

    def test_resume_from_existing_tasks_dir(
        self, fs: FakeFilesystem, fake_repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should reuse provided tasks dir and skip completed tasks."""
        task_dir = fake_repo_root / ".tasks" / "store" / "resume"
        fs.create_dir(str(task_dir))
        status_data = {
            "plan_hash": apply_plan._compute_plan_hash("plan"),
            "tasks": [{"task_file": "task_001.md", "status": "completed"}],
        }
        fs.create_file(str(task_dir / "status.yml"), contents=yaml.safe_dump(status_data))

        monkeypatch.setattr(clipboard_to_plan_module, "get_clipboard_content", lambda: "plan")

        with patch.object(sys, "argv", ["apply-plan", "--tasks-dir", str(task_dir)]):
            result = apply_plan.main()

        assert result == 0

    def test_plan_hash_change_triggers_patching(
        self, fs: FakeFilesystem, fake_repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should invoke task patcher when plan hash differs."""
        task_dir = fake_repo_root / ".tasks" / "store" / "hash"
        fs.create_dir(str(task_dir))
        fs.create_file(str(task_dir / "task_001.md"), contents="# file\n")
        status_data = {
            "plan_hash": "old",
            "tasks": [{"task_file": "task_001.md", "status": "pending"}],
        }
        status_path = task_dir / "status.yml"
        fs.create_file(str(status_path), contents=yaml.safe_dump(status_data))

        monkeypatch.setattr(clipboard_to_plan_module, "get_clipboard_content", lambda: "new plan")
        monkeypatch.setattr(apply_plan, "_run_clipboard_to_plan", lambda: task_dir)
        patch_calls: list[Path] = []

        def fake_patch(
            task_dir_path: Path,
            status_path_path: Path,
            status_data_dict: dict[str, Any],
            plan_text: str,
        ) -> None:
            patch_calls.append(task_dir_path)

        def fake_process(
            task_dir_path: Path,
            task: dict[str, Any],
            status_path_path: Path,
            status_data_dict: dict[str, Any],
        ) -> str:
            task["status"] = "completed"
            return "completed"

        with (
            patch.object(apply_plan, "_patch_incomplete_tasks", side_effect=fake_patch),
            patch.object(apply_plan, "_process_task", side_effect=fake_process),
            patch.object(sys, "argv", ["apply-plan"]),
        ):
            result = apply_plan.main()

        assert patch_calls == [task_dir]
        assert result == 0

    def test_conclusion_detection_returns_two(
        self, fs: FakeFilesystem, fake_repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return code 2 when conclusion is detected."""
        task_dir = fake_repo_root / ".tasks" / "store" / "conclusion"
        fs.create_dir(str(task_dir))
        fs.create_file(str(task_dir / "task_001.md"), contents="# file\n")
        # Use matching hash to avoid triggering _patch_incomplete_tasks
        status_data = {
            "plan_hash": apply_plan._compute_plan_hash("plan"),
            "tasks": [{"task_file": "task_001.md", "status": "pending"}],
        }
        fs.create_file(str(task_dir / "status.yml"), contents=yaml.safe_dump(status_data))

        monkeypatch.setattr(clipboard_to_plan_module, "get_clipboard_content", lambda: "plan")
        monkeypatch.setattr(apply_plan, "_run_clipboard_to_plan", lambda: task_dir)

        with (
            patch.object(apply_plan, "_process_task", return_value="conclusion"),
            patch.object(sys, "argv", ["apply-plan"]),
        ):
            result = apply_plan.main()

        assert result == 2

    def test_incomplete_tasks_return_one(
        self, fs: FakeFilesystem, fake_repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return code 1 when tasks remain incomplete."""
        task_dir = fake_repo_root / ".tasks" / "store" / "incomplete"
        fs.create_dir(str(task_dir))
        fs.create_file(str(task_dir / "task_001.md"), contents="# file\n")
        # Use matching hash to avoid triggering _patch_incomplete_tasks
        status_data = {
            "plan_hash": apply_plan._compute_plan_hash("plan"),
            "tasks": [{"task_file": "task_001.md", "status": "pending"}],
        }
        fs.create_file(str(task_dir / "status.yml"), contents=yaml.safe_dump(status_data))

        monkeypatch.setattr(clipboard_to_plan_module, "get_clipboard_content", lambda: "plan")
        monkeypatch.setattr(apply_plan, "_run_clipboard_to_plan", lambda: task_dir)

        with (
            patch.object(apply_plan, "_process_task", return_value="tests"),
            patch.object(sys, "argv", ["apply-plan"]),
        ):
            result = apply_plan.main()

        assert result == 1

    def test_apply_plan_error_is_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should propagate ApplyPlanError raised during execution."""
        monkeypatch.setattr(clipboard_to_plan_module, "get_clipboard_content", lambda: "plan")

        def raise_error() -> Path:
            raise ApplyPlanError("failure")

        monkeypatch.setattr(apply_plan, "_run_clipboard_to_plan", raise_error)

        with patch.object(sys, "argv", ["apply-plan"]), pytest.raises(ApplyPlanError):
            apply_plan.main()

    def test_clipboard_to_plan_integration_generates_tasks(
        self, fs: FakeFilesystem, fake_repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should exercise real clipboard_to_plan logic to generate task files."""
        sample_plan = """## Implementation Plan

### Observations
- Existing modules need enhancement.

### Approach
- Add new functions to existing files.

## Proposed File Changes

### app/main.py
- Add new function `process_data`
- Update imports

### app/utils.py
- Add helper function `format_output`
"""
        # Patch clipboard content
        monkeypatch.setattr(clipboard_to_plan_module, "get_clipboard_content", lambda: sample_plan)

        # Track created task directory
        created_task_dir: list[Path] = []

        def intercepted_subprocess_run(
            cmd: list[str],
            *,
            capture_output: bool = False,
            text: bool = False,
            cwd: Any = None,
        ) -> subprocess.CompletedProcess[str]:
            """Intercept subprocess.run to execute clipboard_to_plan in fake fs."""
            cmd_str = " ".join(str(c) for c in cmd)
            if "clipboard_to_plan.py" in cmd_str:
                # Execute clipboard_to_plan logic directly in pyfakefs context
                from datetime import datetime

                store_root = fake_repo_root / ".tasks" / "store"
                store_root.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                timestamp_dir = store_root / timestamp
                timestamp_dir.mkdir(parents=True, exist_ok=True)

                content = clipboard_to_plan_module.get_clipboard_content()
                sections = clipboard_to_plan_module.parse_plan_sections(content)
                file_changes_body = sections.get("file_changes", "")
                file_changes = clipboard_to_plan_module.extract_file_changes(file_changes_body)

                outline = clipboard_to_plan_module.generate_outline(sections, file_changes)
                (timestamp_dir / "outline.md").write_text(outline)

                if file_changes:
                    intro = sections.get("intro", "")
                    clipboard_to_plan_module.write_task_files(timestamp_dir, file_changes, intro)

                created_task_dir.append(timestamp_dir)
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=str(timestamp_dir) + "\n", stderr=""
                )

            # Default mock for other subprocess calls
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        def fake_process_task(
            task_dir_path: Path,
            task: dict[str, Any],
            status_path: Path,
            status_data: dict[str, Any],
        ) -> str:
            task["status"] = "completed"
            return "completed"

        with (
            patch("subprocess.run", side_effect=intercepted_subprocess_run),
            patch.object(apply_plan, "_process_task", side_effect=fake_process_task),
            patch.object(sys, "argv", ["apply-plan"]),
        ):
            result = apply_plan.main()

        # Verify execution completed successfully
        assert result == 0
        assert len(created_task_dir) == 1

        task_dir = created_task_dir[0]

        # Verify task directory structure was created
        assert task_dir.exists()
        assert (task_dir / "outline.md").exists()
        assert (task_dir / "status.yml").exists()

        # Verify task files were generated (one per file change)
        task_files = sorted(task_dir.glob("task_*.md"))
        assert len(task_files) == 2  # app/main.py and app/utils.py

        # Verify status.yml references the generated task files
        status_content = yaml.safe_load((task_dir / "status.yml").read_text())
        assert "tasks" in status_content
        task_file_names = {t["task_file"] for t in status_content["tasks"]}
        assert task_file_names == {"task_001.md", "task_002.md"}

        # Verify task files contain expected headers
        task_001_content = (task_dir / "task_001.md").read_text()
        assert "# app/main.py" in task_001_content

        task_002_content = (task_dir / "task_002.md").read_text()
        assert "# app/utils.py" in task_002_content


class TestImplementationParseImplementorOutput:
    """Tests for implementation._parse_implementor_output."""

    def test_detects_success(self) -> None:
        """Should detect SUCCESS token."""
        assert implementation._parse_implementor_output("random SUCCESS text") == (
            "success",
            None,
            None,
        )

    def test_extracts_tests(self) -> None:
        """Should parse test list from output."""
        output = "TESTS: [tests/unit/a.py::test_one, tests/unit/b.py::test_two]"
        assert implementation._parse_implementor_output(output) == (
            "tests",
            ["tests/unit/a.py::test_one", "tests/unit/b.py::test_two"],
            None,
        )

    def test_extracts_fail_detail(self) -> None:
        """Should parse fail message."""
        output = "FAIL: missing environment"
        assert implementation._parse_implementor_output(output) == (
            "fail",
            None,
            "missing environment",
        )

    def test_defaults_to_fail_when_unrecognized(self) -> None:
        """Should return fail when output does not match known patterns."""
        output = "No markers present"
        assert implementation._parse_implementor_output(output) == (
            "fail",
            None,
            "Unrecognized implementor response",
        )


class TestImplementationCountTaskChars:
    """Tests for implementation._count_task_chars."""

    def test_counts_characters_in_file(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return character count of file content."""
        task_path = fake_repo_root / "task_001.md"
        content = "# file_a\nDo things here"
        fs.create_file(str(task_path), contents=content)

        assert implementation._count_task_chars(task_path) == len(content)

    def test_counts_empty_file(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return zero for empty file."""
        task_path = fake_repo_root / "task_empty.md"
        fs.create_file(str(task_path), contents="")

        assert implementation._count_task_chars(task_path) == 0

    def test_counts_large_file(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should count characters in large files."""
        task_path = fake_repo_root / "task_large.md"
        content = "x" * 10000
        fs.create_file(str(task_path), contents=content)

        assert implementation._count_task_chars(task_path) == 10000


class TestImplementationRunTasksAgent:
    """Tests for implementation._run_tasks_agent."""

    def test_invokes_runner_with_agent_and_prompt(self) -> None:
        """Should call _run with tasks_agent_runner arguments."""
        mock_completed = subprocess.CompletedProcess([], 0, stdout="SUCCESS", stderr="")
        with patch.object(implementation, "_run", return_value=mock_completed) as mock_run:
            result = implementation._run_tasks_agent("implementor", "task_path")

        assert result is mock_completed
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        assert "tasks_agent_runner.py" in args[1]
        assert args[2:4] == ["--agent", "implementor"]
        assert args[-2:] == ["--prompt", "task_path"]

    def test_includes_prompt_chars_when_provided(self) -> None:
        """Should include --prompt-chars when char count provided."""
        mock_completed = subprocess.CompletedProcess([], 0, stdout="SUCCESS", stderr="")
        with patch.object(implementation, "_run", return_value=mock_completed) as mock_run:
            result = implementation._run_tasks_agent("implementor", "task_path", prompt_chars=5000)

        assert result is mock_completed
        args = mock_run.call_args.args[0]
        assert "--prompt-chars" in args
        chars_idx = args.index("--prompt-chars")
        assert args[chars_idx + 1] == "5000"

    def test_omits_prompt_chars_when_none(self) -> None:
        """Should not include --prompt-chars when not provided."""
        mock_completed = subprocess.CompletedProcess([], 0, stdout="SUCCESS", stderr="")
        with patch.object(implementation, "_run", return_value=mock_completed) as mock_run:
            implementation._run_tasks_agent("implementor", "task_path", prompt_chars=None)

        args = mock_run.call_args.args[0]
        assert "--prompt-chars" not in args


class TestRunImplementationWorkflow:
    """Tests for implementation.run_implementation_workflow."""

    def _setup_task(self, fs: FakeFilesystem, fake_repo_root: Path) -> tuple[Path, Path]:
        """Create a task file and directory for testing."""
        task_dir = fake_repo_root / "scripts" / "tasks"
        fs.create_dir(str(task_dir))
        task_path = task_dir / "task_001.md"
        fs.create_file(str(task_path), contents="# file_a\nDo things")
        return task_path, task_dir

    def test_returns_success_result(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return ImplementationResult with success status."""
        task_path, task_dir = self._setup_task(fs, fake_repo_root)

        with patch.object(
            implementation,
            "_run_tasks_agent",
            return_value=subprocess.CompletedProcess([], 0, stdout="SUCCESS", stderr=""),
        ):
            result = implementation.run_implementation_workflow(task_path, task_dir)

        assert isinstance(result, ImplementationResult)
        assert result.status == "success"
        assert result.failing_tests is None
        assert result.failure_detail is None

    def test_returns_tests_result(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return ImplementationResult with tests status and failing test list."""
        task_path, task_dir = self._setup_task(fs, fake_repo_root)

        with patch.object(
            implementation,
            "_run_tasks_agent",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout="TESTS: [test_one, test_two]", stderr=""
            ),
        ):
            result = implementation.run_implementation_workflow(task_path, task_dir)

        assert result.status == "tests"
        assert result.failing_tests == ["test_one", "test_two"]
        assert result.failure_detail is None

    def test_returns_fail_result(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should return ImplementationResult with fail status and detail."""
        task_path, task_dir = self._setup_task(fs, fake_repo_root)

        with patch.object(
            implementation,
            "_run_tasks_agent",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout="FAIL: blocking issue", stderr=""
            ),
        ):
            result = implementation.run_implementation_workflow(task_path, task_dir)

        assert result.status == "fail"
        assert result.failing_tests is None
        assert result.failure_detail == "blocking issue"

    def test_passes_character_count_for_routing(
        self, fs: FakeFilesystem, fake_repo_root: Path
    ) -> None:
        """Should pass character count to _run_tasks_agent for routing."""
        task_path, task_dir = self._setup_task(fs, fake_repo_root)
        task_content = task_path.read_text()

        with patch.object(
            implementation,
            "_run_tasks_agent",
            return_value=subprocess.CompletedProcess([], 0, stdout="SUCCESS", stderr=""),
        ) as mock_agent:
            implementation.run_implementation_workflow(task_path, task_dir)

        mock_agent.assert_called_once()
        call_args = mock_agent.call_args
        assert call_args.args[0] == "implementor"
        assert call_args.args[1] == str(task_path)
        assert call_args.args[2] == len(task_content)

    def test_handles_empty_stdout(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should handle empty stdout gracefully."""
        task_path, task_dir = self._setup_task(fs, fake_repo_root)

        with patch.object(
            implementation,
            "_run_tasks_agent",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ):
            result = implementation.run_implementation_workflow(task_path, task_dir)

        assert result.status == "fail"
        assert result.failure_detail == "Unrecognized implementor response"

    def test_handles_none_stdout(self, fs: FakeFilesystem, fake_repo_root: Path) -> None:
        """Should handle None stdout gracefully."""
        task_path, task_dir = self._setup_task(fs, fake_repo_root)

        with patch.object(
            implementation,
            "_run_tasks_agent",
            return_value=subprocess.CompletedProcess([], 0, stdout=None, stderr=""),
        ):
            result = implementation.run_implementation_workflow(task_path, task_dir)

        assert result.status == "fail"
        assert result.failure_detail == "Unrecognized implementor response"


class TestTestingParseTestDebuggerOutput:
    """Tests for testing._parse_test_debugger_output."""

    def test_detects_fixed(self) -> None:
        """Should detect FIXED token and extract message."""
        output = "Some output\nFIXED: All tests now pass\nMore output"
        status, message = testing._parse_test_debugger_output(output)

        assert status == "fixed"
        assert message == "All tests now pass"

    def test_detects_partial(self) -> None:
        """Should detect PARTIAL token and extract message."""
        output = "PARTIAL: 2 tests still failing"
        status, message = testing._parse_test_debugger_output(output)

        assert status == "partial"
        assert message == "2 tests still failing"

    def test_detects_blocked(self) -> None:
        """Should detect BLOCKED token and extract message."""
        output = "BLOCKED: needs design decision for auth flow"
        status, message = testing._parse_test_debugger_output(output)

        assert status == "blocked"
        assert message == "needs design decision for auth flow"

    def test_defaults_to_blocked_when_unrecognized(self) -> None:
        """Should return blocked status when output does not match known patterns."""
        output = "No markers present in output"
        status, message = testing._parse_test_debugger_output(output)

        assert status == "blocked"
        assert message == "Unrecognized test-debugger response"

    def test_case_insensitive_matching(self) -> None:
        """Should match tokens case-insensitively."""
        output = "fixed: all tests pass"
        status, message = testing._parse_test_debugger_output(output)

        assert status == "fixed"
        assert message == "all tests pass"


class TestRunTestingWorkflow:
    """Tests for testing.run_testing_workflow."""

    def test_returns_fixed_result(self) -> None:
        """Should return TestingResult with fixed status."""
        mock_completed = subprocess.CompletedProcess(
            [], 0, stdout="FIXED: All tests now pass", stderr=""
        )
        with patch.object(testing, "_run_tasks_agent", return_value=mock_completed):
            result = testing.run_testing_workflow("task content", ["test_one", "test_two"])

        assert isinstance(result, TestingResult)
        assert result.status == "fixed"
        assert result.message == "All tests now pass"

    def test_returns_partial_result(self) -> None:
        """Should return TestingResult with partial status and message extraction."""
        mock_completed = subprocess.CompletedProcess(
            [], 0, stdout="PARTIAL: test_two still failing", stderr=""
        )
        with patch.object(testing, "_run_tasks_agent", return_value=mock_completed):
            result = testing.run_testing_workflow("task content", ["test_one", "test_two"])

        assert result.status == "partial"
        assert result.message == "test_two still failing"

    def test_returns_blocked_result(self) -> None:
        """Should return TestingResult with blocked status and message extraction."""
        mock_completed = subprocess.CompletedProcess(
            [], 0, stdout="BLOCKED: needs database schema change", stderr=""
        )
        with patch.object(testing, "_run_tasks_agent", return_value=mock_completed):
            result = testing.run_testing_workflow("task content", ["test_one"])

        assert result.status == "blocked"
        assert result.message == "needs database schema change"

    def test_formats_prompt_correctly(self) -> None:
        """Should format prompt with task content, failing tests, and instructions."""
        mock_completed = subprocess.CompletedProcess([], 0, stdout="FIXED: done", stderr="")
        with patch.object(testing, "_run_tasks_agent", return_value=mock_completed) as mock_agent:
            testing.run_testing_workflow(
                "# Task\nDo something", ["tests/unit/test_a.py", "tests/unit/test_b.py"]
            )

        mock_agent.assert_called_once()
        call_args = mock_agent.call_args
        prompt = call_args.args[1]

        assert "Task: # Task\nDo something" in prompt
        assert "Failing Tests: [tests/unit/test_a.py, tests/unit/test_b.py]" in prompt
        assert "Instructions: Debug and fix the failing tests" in prompt

    def test_handles_empty_failing_tests(self) -> None:
        """Should handle empty failing_tests list."""
        mock_completed = subprocess.CompletedProcess([], 0, stdout="FIXED: done", stderr="")
        with patch.object(testing, "_run_tasks_agent", return_value=mock_completed) as mock_agent:
            result = testing.run_testing_workflow("task content", [])

        assert result.status == "fixed"
        call_args = mock_agent.call_args
        prompt = call_args.args[1]
        assert "Failing Tests: []" in prompt

    def test_handles_empty_stdout(self) -> None:
        """Should handle empty stdout gracefully."""
        mock_completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(testing, "_run_tasks_agent", return_value=mock_completed):
            result = testing.run_testing_workflow("task content", ["test_one"])

        assert result.status == "blocked"
        assert result.message == "Unrecognized test-debugger response"

    def test_handles_none_stdout(self) -> None:
        """Should handle None stdout gracefully."""
        mock_completed = subprocess.CompletedProcess([], 0, stdout=None, stderr="")
        with patch.object(testing, "_run_tasks_agent", return_value=mock_completed):
            result = testing.run_testing_workflow("task content", ["test_one"])

        assert result.status == "blocked"
        assert result.message == "Unrecognized test-debugger response"


class TestTestingRunTasksAgent:
    """Tests for testing._run_tasks_agent."""

    def test_invokes_runner_with_agent(self) -> None:
        """Should call _run with tasks_agent_runner arguments."""
        mock_completed: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            [], 0, "", ""
        )
        with patch.object(testing, "_run", return_value=mock_completed) as mock_run:
            result = testing._run_tasks_agent("test-debugger", "prompt text")

        assert result is mock_completed
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        assert "tasks_agent_runner.py" in args[1]
        assert args[2:4] == ["--agent", "test-debugger"]
        assert args[-2:] == ["--prompt", "prompt text"]

    def test_invokes_runner_with_empty_prompt(self) -> None:
        """Should handle empty prompt correctly."""
        mock_completed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess([], 0)
        with patch.object(testing, "_run", return_value=mock_completed) as mock_run:
            testing._run_tasks_agent("test-debugger", "")

        args = mock_run.call_args.args[0]
        assert args[-2:] == ["--prompt", ""]

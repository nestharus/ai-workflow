import hashlib
import subprocess
from unittest.mock import patch

from scripts.tasks.workflows import apply_plan, implementation, testing
from scripts.tasks.workflows.testing import TestingResult


class TestComputePlanHash:
    def test_returns_sha256_hex(self) -> None:
        """Should compute deterministic SHA256 hex digest."""
        content = "example plan content"
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()

        assert apply_plan._compute_plan_hash(content) == expected


class TestRunOpencodeAgent:
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


class TestImplementationParseImplementorOutput:
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


class TestImplementationRunTasksAgent:
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


class TestTestingParseTestDebuggerOutput:
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

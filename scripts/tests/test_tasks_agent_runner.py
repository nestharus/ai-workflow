"""Tests for scripts.dev.tasks_agent_runner module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.tasks_agent_runner import main, parse_args


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_agent(self) -> None:
        """Should require --agent argument."""
        with (
            patch.object(sys, "argv", ["script", "--prompt", "test prompt"]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_requires_prompt(self) -> None:
        """Should require --prompt argument."""
        with (
            patch.object(sys, "argv", ["script", "--agent", "test-agent"]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_parses_agent_and_prompt(self) -> None:
        """Should parse --agent and --prompt arguments."""
        with patch.object(
            sys, "argv", ["script", "--agent", "implementor", "--prompt", "Write code"]
        ):
            args = parse_args()
        assert args.agent == "implementor"
        assert args.prompt == "Write code"

    def test_prompt_chars_is_optional(self) -> None:
        """Should allow --prompt-chars to be optional (None by default)."""
        with patch.object(sys, "argv", ["script", "--agent", "test", "--prompt", "test"]):
            args = parse_args()
        assert args.prompt_chars is None

    def test_parses_prompt_chars(self) -> None:
        """Should parse --prompt-chars as integer."""
        with patch.object(
            sys,
            "argv",
            ["script", "--agent", "test", "--prompt", "test", "--prompt-chars", "5000"],
        ):
            args = parse_args()
        assert args.prompt_chars == 5000
        assert isinstance(args.prompt_chars, int)

    def test_all_arguments_together(self) -> None:
        """Should parse all arguments correctly."""
        with patch.object(
            sys,
            "argv",
            [
                "script",
                "--agent",
                "evaluator",
                "--prompt",
                "Evaluate this code",
                "--prompt-chars",
                "12000",
            ],
        ):
            args = parse_args()
        assert args.agent == "evaluator"
        assert args.prompt == "Evaluate this code"
        assert args.prompt_chars == 12000


class TestMain:
    """Tests for main function."""

    def test_main_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Should return 0 on successful execution."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = "Agent output"

        mock_agent_runner_class = MagicMock(return_value=mock_runner)
        mock_agent_runner_class.from_agent_name = MagicMock(return_value=mock_runner)

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(sys, "argv", ["script", "--agent", "test", "--prompt", "test"]),
        ):
            result = main()
            assert result == 0

    def test_main_writes_output_to_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should write agent output to stdout."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = "Agent completed task"

        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(return_value=mock_runner)

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(sys, "argv", ["script", "--agent", "test", "--prompt", "test"]),
        ):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        assert "Agent completed task" in captured.out

    def test_main_logs_routing_when_prompt_chars_provided(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should log routing status when --prompt-chars is provided."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = "Output"

        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(return_value=mock_runner)

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(
                sys,
                "argv",
                ["script", "--agent", "test", "--prompt", "test", "--prompt-chars", "5000"],
            ),
        ):
            main()

        captured = capsys.readouterr()
        assert "Routing enabled with 5000 characters" in captured.err

    def test_main_handles_file_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when FileNotFoundError is raised."""
        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(
            side_effect=FileNotFoundError("Config not found")
        )

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(sys, "argv", ["script", "--agent", "missing", "--prompt", "test"]),
        ):
            result = main()
            assert result == 1

        captured = capsys.readouterr()
        assert "Config not found" in captured.err

    def test_main_handles_value_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when ValueError is raised."""
        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(
            side_effect=ValueError("Invalid configuration")
        )

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(sys, "argv", ["script", "--agent", "bad", "--prompt", "test"]),
        ):
            result = main()
            assert result == 1

        captured = capsys.readouterr()
        assert "Invalid configuration" in captured.err

    def test_main_handles_key_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when KeyError is raised."""
        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(side_effect=KeyError("missing_key"))

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(sys, "argv", ["script", "--agent", "test", "--prompt", "test"]),
        ):
            result = main()
            assert result == 1

    def test_main_handles_runtime_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when RuntimeError is raised."""
        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(
            side_effect=RuntimeError("Execution failed")
        )

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(sys, "argv", ["script", "--agent", "test", "--prompt", "test"]),
        ):
            result = main()
            assert result == 1

        captured = capsys.readouterr()
        assert "Execution failed" in captured.err

    def test_main_handles_empty_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should not write anything when output is empty or None."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = None

        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(return_value=mock_runner)

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(sys, "argv", ["script", "--agent", "test", "--prompt", "test"]),
        ):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        # Nothing written to stdout when output is None
        assert captured.out == ""

    def test_main_passes_prompt_chars_to_from_agent_name(self) -> None:
        """Should pass prompt_chars to from_agent_name when provided."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = "Output"

        mock_agent_runner_class = MagicMock()
        mock_agent_runner_class.from_agent_name = MagicMock(return_value=mock_runner)

        with (
            patch(
                "scripts.dev.tasks_agent_runner._get_agent_runner",
                return_value=mock_agent_runner_class,
            ),
            patch.object(
                sys,
                "argv",
                ["script", "--agent", "myagent", "--prompt", "task", "--prompt-chars", "7500"],
            ),
        ):
            main()

        # Verify from_agent_name was called with prompt_chars=7500
        mock_agent_runner_class.from_agent_name.assert_called_once()
        call_kwargs = mock_agent_runner_class.from_agent_name.call_args
        assert call_kwargs[1]["prompt_chars"] == 7500

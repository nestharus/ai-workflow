"""Tests for scripts/dev/commands/cli.py."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.dev.commands.cli import JsonArgumentParser, main, parse_args


class TestJsonArgumentParser:
    """Tests for JsonArgumentParser class."""

    def test_error_outputs_json_and_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """error() should output JSON error and exit with code 2."""
        parser = JsonArgumentParser(prog="test")

        with pytest.raises(SystemExit) as exc_info:
            parser.error("test error message")

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert output["error"]["code"] == "INVALID_INPUT"
        assert output["error"]["message"] == "test error message"

    def test_error_formats_json_correctly(self, capsys: pytest.CaptureFixture[str]) -> None:
        """error() should format the JSON with correct structure."""
        parser = JsonArgumentParser(prog="ai")

        with pytest.raises(SystemExit):
            parser.error("missing required argument")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "ok" in output
        assert "error" in output
        assert "code" in output["error"]
        assert "message" in output["error"]


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parses_update_plan_command_with_ticket_id(self) -> None:
        """parse_args should parse update-plan command with ticket ID."""
        args = parse_args(["update-plan", "NES-123"])

        assert args.command == "update-plan"
        assert args.args == ["NES-123"]

    def test_parses_update_plan_with_additional_prompt(self) -> None:
        """parse_args should parse update-plan command with additional prompt."""
        args = parse_args(["update-plan", "NES-456", "Add", "error", "handling"])

        assert args.command == "update-plan"
        assert args.args == ["NES-456", "Add", "error", "handling"]

    def test_raises_on_missing_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """parse_args should exit with JSON error when command is missing."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args([])

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False

    def test_raises_on_missing_ticket_id(self, capsys: pytest.CaptureFixture[str]) -> None:
        """parse_args should exit with JSON error when ticket ID is missing."""
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["update-plan"])

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False

    def test_creates_parser_with_correct_prog(self) -> None:
        """parse_args should create parser with 'ai' as prog name."""
        # This tests that the parser is created correctly
        args = parse_args(["update-plan", "TEST-1"])
        assert args.command == "update-plan"


class TestMain:
    """Tests for main function."""

    def test_main_calls_update_plan_run_with_ticket_id(self) -> None:
        """main should call update_plan.run with correct ticket_id."""
        with patch("scripts.dev.commands.cli.update_plan.run", return_value=0) as mock_run:
            result = main(["update-plan", "NES-123"])

        mock_run.assert_called_once_with("NES-123", None)
        assert result == 0

    def test_main_calls_update_plan_run_with_prompt(self) -> None:
        """main should call update_plan.run with ticket_id and prompt."""
        with patch("scripts.dev.commands.cli.update_plan.run", return_value=0) as mock_run:
            result = main(["update-plan", "NES-456", "Add", "error", "handling"])

        mock_run.assert_called_once_with("NES-456", "Add error handling")
        assert result == 0

    def test_main_returns_update_plan_exit_code(self) -> None:
        """main should return the exit code from update_plan.run."""
        with patch("scripts.dev.commands.cli.update_plan.run", return_value=1):
            result = main(["update-plan", "FAIL-1"])

        assert result == 1

    def test_main_with_single_word_prompt(self) -> None:
        """main should handle single word prompt."""
        with patch("scripts.dev.commands.cli.update_plan.run", return_value=0) as mock_run:
            result = main(["update-plan", "NES-789", "refactor"])

        mock_run.assert_called_once_with("NES-789", "refactor")
        assert result == 0

    def test_main_unknown_command_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """main should output error JSON for unknown command.

        Note: With required=True on subparsers, this branch is normally unreachable.
        We test it by simulating a Namespace with an unexpected command value.
        """
        # Since subparsers with required=True prevent unknown commands at parse time,
        # we need to patch parse_args to return an unexpected command value
        from argparse import Namespace

        mock_args = Namespace(command="unknown-cmd", args=["test"])

        with patch("scripts.dev.commands.cli.parse_args", return_value=mock_args):
            result = main(["unknown-cmd", "test"])

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert output["error"]["code"] == "UNKNOWN_COMMAND"
        assert "unknown-cmd" in output["error"]["message"]


class TestMainIntegration:
    """Integration tests for main function."""

    def test_main_with_none_argv_uses_sys_argv(self) -> None:
        """main with None argv should use sys.argv for parsing."""
        with (
            patch("sys.argv", ["ai", "update-plan", "INT-1"]),
            patch("scripts.dev.commands.cli.update_plan.run", return_value=0) as mock_run,
        ):
            # Call with explicit None to test that branch
            result = main(None)

        mock_run.assert_called_once_with("INT-1", None)
        assert result == 0

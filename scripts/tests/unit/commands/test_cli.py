import json
from unittest.mock import patch

import pytest

from scripts.dev.commands.cli import JsonArgumentParser, main, parse_args


class TestMain:
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

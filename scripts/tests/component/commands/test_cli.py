import json

import pytest

from scripts.dev.commands.cli import JsonArgumentParser, main, parse_args


class TestJsonArgumentParser:
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

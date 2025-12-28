import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.tasks_agent_runner import main, parse_args


class TestParseArgs:
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

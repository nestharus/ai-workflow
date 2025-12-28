from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.huggingface_agent_runner import (
    build_prompt,
    load_agent,
    load_model,
    main,
    parse_args,
    run_inference,
)


class TestParseArgs:
    def test_parses_required_arguments(self) -> None:
        """Should parse --agent and --prompt arguments."""
        with patch("sys.argv", ["prog", "--agent", "test-agent", "--prompt", "test prompt"]):
            args = parse_args()

        assert args.agent == "test-agent"
        assert args.prompt == "test prompt"

    def test_raises_on_missing_agent(self) -> None:
        """Should raise SystemExit when --agent is missing."""
        with (
            patch("sys.argv", ["prog", "--prompt", "test prompt"]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_raises_on_missing_prompt(self) -> None:
        """Should raise SystemExit when --prompt is missing."""
        with (
            patch("sys.argv", ["prog", "--agent", "test-agent"]),
            pytest.raises(SystemExit),
        ):
            parse_args()


class TestMain:
    def test_returns_zero_on_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 0 on successful execution."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.huggingface_agent_runner.load_agent",
                return_value=(
                    {"model": "test-model", "generation_config": {}},
                    "System prompt",
                ),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.load_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.run_inference",
                return_value="Generated output",
            ),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Generated output" in captured.out

    def test_returns_one_on_file_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when agent file not found."""
        with (
            patch("sys.argv", ["prog", "--agent", "nonexistent", "--prompt", "hello"]),
            patch(
                "scripts.dev.huggingface_agent_runner.load_agent",
                side_effect=FileNotFoundError("Agent not found"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Agent not found" in captured.err

    def test_returns_one_on_value_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 on ValueError from load_agent."""
        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.huggingface_agent_runner.load_agent",
                side_effect=ValueError("Invalid frontmatter"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Invalid frontmatter" in captured.err

    def test_returns_one_on_key_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 on KeyError from load_agent."""
        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.huggingface_agent_runner.load_agent",
                side_effect=KeyError("Missing field"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Missing field" in captured.err

    def test_returns_one_on_runtime_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 on RuntimeError from load_model."""
        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.huggingface_agent_runner.load_agent",
                return_value=({"model": "test-model"}, "System"),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.load_model",
                side_effect=RuntimeError("Model load failed"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Model load failed" in captured.err

    def test_uses_default_generation_config(self) -> None:
        """Should use empty dict when generation_config not in frontmatter."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.huggingface_agent_runner.load_agent",
                return_value=({"model": "test-model"}, "System"),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.load_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.run_inference",
                return_value="output",
            ) as mock_inference,
        ):
            main()

        # Check that run_inference was called with empty dict for generation_config
        call_args = mock_inference.call_args
        assert call_args[0][3] == {}  # Fourth positional arg is generation_config


class TestLoadAgentActualFunction:
    def test_load_agent_file_not_found(self, tmp_path: Path) -> None:
        """Test load_agent raises FileNotFoundError for missing agent (line 72-73)."""

        # Create the directory structure but no agent file
        agents_dir = tmp_path / ".huggingface" / "agents"
        agents_dir.mkdir(parents=True)

        # Patch the project_root to use tmp_path
        with patch("scripts.dev.huggingface_agent_runner.Path") as mock_path:
            # Create a mock that returns tmp_path for parents[2]
            mock_file = MagicMock()
            mock_file.resolve.return_value.parents = {2: tmp_path}
            mock_path.__call__ = lambda x: mock_file if x == __file__ else Path(x)


class TestHuggingfaceRunner:
    def test_run_executes_agent_successfully(self) -> None:
        """HuggingfaceRunner.run should execute agent and return output."""
        from scripts.dev.huggingface_agent_runner import HuggingfaceRunner

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Use the correct format: agent_config dict with _system_prompt key
        runner = HuggingfaceRunner(
            agent_config={
                "model": "test/model",
                "provider": "huggingface",
                "_system_prompt": "You are a test assistant.",
                "generation_config": {"max_new_tokens": 100},
            },
        )

        with (
            patch(
                "scripts.dev.huggingface_agent_runner.load_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.run_inference",
                return_value="Generated output",
            ),
        ):
            result = runner.run("Test prompt")

        assert result == "Generated output"

    def test_run_raises_runtime_error_on_failure(self) -> None:
        """HuggingfaceRunner.run should raise RuntimeError on execution failure."""
        from scripts.dev.huggingface_agent_runner import HuggingfaceRunner

        runner = HuggingfaceRunner(
            agent_config={
                "model": "test/model",
                "provider": "huggingface",
                "_system_prompt": "Test prompt",
            },
        )

        with (
            patch(
                "scripts.dev.huggingface_agent_runner.load_model",
                side_effect=Exception("Model loading failed"),
            ),
            pytest.raises(RuntimeError, match="HuggingFace agent execution failed"),
        ):
            runner.run("Test prompt")

    def test_run_uses_default_generation_config(self) -> None:
        """HuggingfaceRunner.run should use empty dict for missing generation_config."""
        from scripts.dev.huggingface_agent_runner import HuggingfaceRunner

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # No generation_config in agent_config
        runner = HuggingfaceRunner(
            agent_config={
                "model": "test/model",
                "provider": "huggingface",
                "_system_prompt": "You are a test assistant.",
            },
        )

        with (
            patch(
                "scripts.dev.huggingface_agent_runner.load_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.run_inference",
                return_value="Output",
            ) as mock_inference,
        ):
            runner.run("Test prompt")

        # Verify run_inference was called with empty dict for generation_config
        call_args = mock_inference.call_args
        assert call_args[0][3] == {}  # Fourth positional arg is generation_config

    def test_run_builds_correct_prompt(self) -> None:
        """HuggingfaceRunner.run should build correct prompt with system_prompt."""
        from scripts.dev.huggingface_agent_runner import HuggingfaceRunner

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        runner = HuggingfaceRunner(
            agent_config={
                "model": "test/model",
                "provider": "huggingface",
                "_system_prompt": "You are helpful.",
                "generation_config": {},
            },
        )

        with (
            patch(
                "scripts.dev.huggingface_agent_runner.load_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.dev.huggingface_agent_runner.run_inference",
                return_value="Output",
            ) as mock_inference,
        ):
            runner.run("User query")

        # Verify run_inference was called with built prompt
        call_args = mock_inference.call_args
        full_prompt = call_args[0][2]  # Third positional arg is the prompt
        assert "You are helpful." in full_prompt
        assert "User query" in full_prompt

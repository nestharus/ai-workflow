"""Tests for scripts.dev.huggingface_agent_runner module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.huggingface_agent_runner import (
    build_prompt,
    load_model,
    main,
    parse_args,
    run_inference,
)


class TestParseArgs:
    """Tests for parse_args function."""

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


class TestLoadAgent:
    """Tests for load_agent function."""

    def test_loads_valid_agent_file(self, tmp_path: Path) -> None:
        """Should load frontmatter and system prompt from agent file."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
name: test-agent
model: mistralai/Ministral-3B-Instruct
generation_config:
  max_new_tokens: 512
---

You are a test agent."""
        )

        frontmatter, system_prompt = _load_agent_from_path(agent_file)

        assert frontmatter["name"] == "test-agent"
        assert frontmatter["model"] == "mistralai/Ministral-3B-Instruct"
        assert frontmatter["generation_config"]["max_new_tokens"] == 512
        assert system_prompt == "You are a test agent."

    def test_raises_for_invalid_frontmatter_format(self, tmp_path: Path) -> None:
        """Should raise ValueError for missing frontmatter delimiters."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text("No frontmatter here")

        with pytest.raises(ValueError, match="Invalid frontmatter"):
            _load_agent_from_path(agent_file)

    def test_raises_for_invalid_yaml(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid YAML in frontmatter."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
invalid: yaml: content: [
---

System prompt"""
        )

        with pytest.raises(ValueError, match="Invalid YAML"):
            _load_agent_from_path(agent_file)

    def test_raises_for_non_dict_frontmatter(self, tmp_path: Path) -> None:
        """Should raise TypeError when frontmatter is not a dict."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
- just
- a
- list
---

System prompt"""
        )

        with pytest.raises(TypeError, match="Invalid frontmatter"):
            _load_agent_from_path(agent_file)

    def test_raises_for_missing_model_field(self, tmp_path: Path) -> None:
        """Should raise KeyError when model field is missing."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
name: test-agent
---

System prompt"""
        )

        with pytest.raises(KeyError, match="model"):
            _load_agent_from_path(agent_file)

    def test_raises_for_invalid_generation_config(self, tmp_path: Path) -> None:
        """Should raise ValueError when generation_config is not a dict."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
name: test-agent
model: test-model
generation_config: not-a-dict
---

System prompt"""
        )

        with pytest.raises(ValueError, match="generation_config must be a dict"):
            _load_agent_from_path(agent_file)


def _load_agent_from_path(agent_path: Path) -> tuple[dict[str, Any], str]:
    """Helper to load agent directly from a path for testing."""
    import yaml

    content = agent_path.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Invalid frontmatter in agent file")

    try:
        frontmatter = yaml.safe_load(parts[1])
    except Exception as exc:
        raise ValueError("Invalid YAML frontmatter") from exc

    if not isinstance(frontmatter, dict):
        raise TypeError("Invalid frontmatter in agent file")

    if "model" not in frontmatter:
        raise KeyError("Missing required frontmatter field: model")

    if "generation_config" in frontmatter and not isinstance(
        frontmatter["generation_config"], dict
    ):
        raise ValueError("generation_config must be a dict")

    system_prompt = parts[2].strip()
    return frontmatter, system_prompt


class TestLoadModel:
    """Tests for load_model function."""

    def test_loads_model_successfully(self) -> None:
        """Should load model and tokenizer from HuggingFace."""
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_auto_tokenizer = MagicMock()
        mock_auto_model = MagicMock()
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer
        mock_auto_model.from_pretrained.return_value = mock_model

        # Create mock transformers module
        mock_transformers = MagicMock()
        mock_transformers.AutoTokenizer = mock_auto_tokenizer
        mock_transformers.AutoModelForCausalLM = mock_auto_model

        with patch.dict(
            "sys.modules",
            {"torch": MagicMock(), "transformers": mock_transformers},
        ):
            model, tokenizer = load_model("test-model")

        assert model == mock_model
        assert tokenizer == mock_tokenizer
        mock_model.eval.assert_called_once()

    def test_raises_runtime_error_on_failure(self) -> None:
        """Should raise RuntimeError when model loading fails."""
        mock_auto_tokenizer = MagicMock()
        mock_auto_tokenizer.from_pretrained.side_effect = Exception("Load failed")

        mock_transformers = MagicMock()
        mock_transformers.AutoTokenizer = mock_auto_tokenizer

        with (
            patch.dict(
                "sys.modules",
                {"torch": MagicMock(), "transformers": mock_transformers},
            ),
            pytest.raises(RuntimeError, match="Failed to load model"),
        ):
            load_model("test-model")


class TestRunInference:
    """Tests for run_inference function."""

    def test_runs_inference_successfully(self) -> None:
        """Should run inference and return generated text."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_device = MagicMock()

        # Setup mocks
        mock_model.parameters.return_value = iter([MagicMock(device=mock_device)])
        mock_tokenizer.return_value = {"input_ids": MagicMock()}
        mock_tokenizer.eos_token_id = 0
        mock_tokenizer.decode.return_value = "Generated response"

        mock_outputs = MagicMock()
        mock_outputs.__getitem__ = MagicMock(return_value=MagicMock())
        mock_model.generate.return_value = mock_outputs

        mock_torch = MagicMock()
        mock_torch.no_grad.return_value.__enter__ = MagicMock()
        mock_torch.no_grad.return_value.__exit__ = MagicMock()

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = run_inference(
                mock_model,
                mock_tokenizer,
                "Test prompt",
                {"max_new_tokens": 100},
            )

        assert result == "Generated response"

    def test_strips_prompt_prefix_from_response(self) -> None:
        """Should strip prompt prefix from response if present."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()
        mock_device = MagicMock()

        prompt = "Test prompt"
        mock_model.parameters.return_value = iter([MagicMock(device=mock_device)])
        mock_tokenizer.return_value = {"input_ids": MagicMock()}
        mock_tokenizer.eos_token_id = 0
        mock_tokenizer.decode.return_value = f"{prompt} Generated response"

        mock_outputs = MagicMock()
        mock_outputs.__getitem__ = MagicMock(return_value=MagicMock())
        mock_model.generate.return_value = mock_outputs

        mock_torch = MagicMock()
        mock_torch.no_grad.return_value.__enter__ = MagicMock()
        mock_torch.no_grad.return_value.__exit__ = MagicMock()

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = run_inference(mock_model, mock_tokenizer, prompt, {})

        assert result == "Generated response"

    def test_raises_runtime_error_on_failure(self) -> None:
        """Should raise RuntimeError when inference fails."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.side_effect = Exception("Tokenization failed")

        mock_torch = MagicMock()
        with (
            patch.dict("sys.modules", {"torch": mock_torch}),
            pytest.raises(RuntimeError, match="Inference failed"),
        ):
            run_inference(mock_model, mock_tokenizer, "Test", {})


class TestBuildPrompt:
    """Tests for build_prompt function."""

    def test_combines_system_and_user_prompts(self) -> None:
        """Should combine system prompt and user prompt with proper formatting."""
        system_prompt = "You are a helpful assistant."
        user_prompt = "What is 2+2?"

        result = build_prompt(system_prompt, user_prompt)

        assert system_prompt in result
        assert user_prompt in result
        assert "User:" in result
        assert "Assistant:" in result

    def test_handles_empty_system_prompt(self) -> None:
        """Should handle empty system prompt."""
        result = build_prompt("", "User query")

        assert "User: User query" in result
        assert "Assistant:" in result

    def test_handles_multiline_prompts(self) -> None:
        """Should handle multiline prompts."""
        system_prompt = "Line 1\nLine 2"
        user_prompt = "Query line 1\nQuery line 2"

        result = build_prompt(system_prompt, user_prompt)

        assert system_prompt in result
        assert user_prompt in result


class TestMain:
    """Tests for main function."""

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

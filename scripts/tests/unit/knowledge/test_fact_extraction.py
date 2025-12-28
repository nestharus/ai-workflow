import argparse
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.knowledge.fact_extraction import (
    CSV_COLUMNS,
    FactExtractorError,
    FactRecord,
    append_fact_batch,
    compute_pairwise_similarity,
    ensure_csv_exists,
    extract_facts_inline,
    extract_facts_main,
    get_existing_facts,
    invoke_fact_extractor,
    main,
    parse_args,
    validate_fact_extraction,
)


class TestInvokeFactExtractor:
    def test_raises_error_when_claude_not_found(self) -> None:
        """Should raise FactExtractorError when claude CLI is not found."""
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(FactExtractorError, match="Claude CLI not found"),
        ):
            invoke_fact_extractor("Test sentence.", "entity")

    def test_raises_error_on_timeout(self) -> None:
        """Should raise FactExtractorError on subprocess timeout."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120)
            ),
            pytest.raises(FactExtractorError, match="timed out"),
        ):
            invoke_fact_extractor("Test sentence.", "entity")

    def test_raises_error_on_non_zero_exit(self) -> None:
        """Should raise FactExtractorError on non-zero exit code."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "Error message"
            with (
                patch("subprocess.run", return_value=mock_result),
                pytest.raises(FactExtractorError, match="non-zero exit code"),
            ):
                invoke_fact_extractor("Test sentence.", "entity")

    def test_raises_error_on_empty_output(self) -> None:
        """Should raise FactExtractorError on empty stdout."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            with (
                patch("subprocess.run", return_value=mock_result),
                pytest.raises(FactExtractorError, match="empty output"),
            ):
                invoke_fact_extractor("Test sentence.", "entity")

    def test_raises_error_on_no_json_in_output(self) -> None:
        """Should raise FactExtractorError when no JSON found in output."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "No JSON here, just plain text."
            with (
                patch("subprocess.run", return_value=mock_result),
                pytest.raises(FactExtractorError, match="No JSON found"),
            ):
                invoke_fact_extractor("Test sentence.", "entity")

    def test_raises_error_on_invalid_json(self) -> None:
        """Should raise FactExtractorError on invalid JSON."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "{invalid json}"
            with (
                patch("subprocess.run", return_value=mock_result),
                pytest.raises(FactExtractorError, match="Invalid JSON"),
            ):
                invoke_fact_extractor("Test sentence.", "entity")

    def test_raises_error_on_missing_required_fields(self) -> None:
        """Should raise FactExtractorError when required fields are missing."""
        import json

        with patch("shutil.which", return_value="/usr/bin/claude"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            # Missing required fields
            mock_result.stdout = json.dumps({"entity": "test"})
            with (
                patch("subprocess.run", return_value=mock_result),
                pytest.raises(FactExtractorError, match="Missing required fields"),
            ):
                invoke_fact_extractor("Test sentence.", "entity")

    def test_returns_parsed_output_on_success(self) -> None:
        """Should return parsed JSON on successful invocation."""
        import json

        with patch("shutil.which", return_value="/usr/bin/claude"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(
                {
                    "entity": "test_entity",
                    "original_sentence": "Test sentence.",
                    "facts": [{"fact": "Test fact", "confidence": 0.9}],
                    "residual_sentence": "Residual.",
                    "validation": {"semantic_similarity": 0.95},
                }
            )
            with patch("subprocess.run", return_value=mock_result):
                result = invoke_fact_extractor("Test sentence.", "test_entity")

                assert result["entity"] == "test_entity"
                assert len(result["facts"]) == 1

    def test_raises_error_on_subprocess_error(self) -> None:
        """Should raise FactExtractorError on SubprocessError."""
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("subprocess.run", side_effect=subprocess.SubprocessError("Subprocess failed")),
            pytest.raises(FactExtractorError, match="invocation failed"),
        ):
            invoke_fact_extractor("Test sentence.", "entity")


class TestExtractFactsMain:
    def test_returns_zero_on_no_facts_extracted(self, tmp_path: Path) -> None:
        """Should return 0 when no facts could be extracted."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="This sentence has nothing about the entity.",
            entity="nonexistent_entity",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.side_effect = FactExtractorError("Sub-agent unavailable")
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                result = extract_facts_main(args)

                assert result == 0

    def test_returns_one_on_model_load_error(self, tmp_path: Path) -> None:
        """Should return 1 when model fails to load."""
        args = argparse.Namespace(
            sentence="Test sentence about entity.",
            entity="entity",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.side_effect = FactExtractorError("Sub-agent unavailable")
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.side_effect = Exception("Model load failed")

                result = extract_facts_main(args)

                assert result == 1

    def test_uses_inline_extraction_on_subagent_failure(self, tmp_path: Path) -> None:
        """Should use inline extraction when sub-agent fails."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="Use create_app in app/core/factory.py.",
            entity="create_app",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.side_effect = FactExtractorError("Sub-agent unavailable")
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                result = extract_facts_main(args)

                # Should use inline extraction and return success (0) or incomplete (2)
                assert result in [0, 2]

    def test_uses_subagent_when_available(self, tmp_path: Path) -> None:
        """Should use sub-agent results when available and validate with Qwen."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="Test sentence about entity.",
            entity="entity",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        subagent_result = {
            "entity": "entity",
            "original_sentence": "Test sentence about entity.",
            "facts": [
                {
                    "fact": "entity does something",
                    "confidence": 0.95,
                    "rewritten_sentence": "Test sentence.",
                }
            ],
            "residual_sentence": "Test sentence.",
            "validation": {
                "semantic_similarity": 0.98,
                "entity_absent": True,
                "information_preserved": True,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.return_value = subagent_result
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                result = extract_facts_main(args)

                assert result in [0, 2]  # Success or incomplete
                mock_invoke.assert_called_once()

    def test_stores_facts_when_not_dry_run(self, tmp_path: Path) -> None:
        """Should store facts to CSV when not in dry run mode."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        knowledge_path = tmp_path / ".knowledge"
        csv_path = knowledge_path / "facts" / "extractions.csv"

        args = argparse.Namespace(
            sentence="Use create_app in app/core/factory.py.",
            entity="create_app",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        subagent_result = {
            "entity": "create_app",
            "original_sentence": "Use create_app in app/core/factory.py.",
            "facts": [
                {
                    "fact": "create_app is in app/core/factory.py",
                    "confidence": 0.95,
                    "rewritten_sentence": "Use.",
                }
            ],
            "residual_sentence": "Use.",
            "validation": {
                "semantic_similarity": 0.98,
                "entity_absent": True,
                "information_preserved": True,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.return_value = subagent_result
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                result = extract_facts_main(args)

                assert result == 0
                assert csv_path.exists()
                content = csv_path.read_text()
                assert "create_app" in content

    def test_handles_absolute_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle absolute knowledge path."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir(parents=True, exist_ok=True)

        args = argparse.Namespace(
            sentence="Test sentence.",
            entity="nonexistent",
            knowledge_path=knowledge_path,  # Absolute path
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.side_effect = FactExtractorError("Sub-agent unavailable")
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                result = extract_facts_main(args)

                assert result == 0


class TestMain:
    def test_calls_parse_args_and_extract_facts_main(self) -> None:
        """Should call parse_args and extract_facts_main."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_args = argparse.Namespace(
            sentence="Test sentence.",
            entity="entity",
            knowledge_path=Path(".knowledge"),
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        with patch("scripts.knowledge.fact_extraction.parse_args") as mock_parse:
            mock_parse.return_value = mock_args
            with patch("scripts.knowledge.fact_extraction.extract_facts_main") as mock_main:
                mock_main.return_value = 0

                result = main()

                mock_parse.assert_called_once()
                mock_main.assert_called_once_with(mock_args)
                assert result == 0

    def test_returns_exit_code_from_extract_facts_main(self) -> None:
        """Should return exit code from extract_facts_main."""
        mock_args = argparse.Namespace(
            sentence="Test.",
            entity="test",
            knowledge_path=Path(".knowledge"),
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        with patch("scripts.knowledge.fact_extraction.parse_args") as mock_parse:
            mock_parse.return_value = mock_args
            with patch("scripts.knowledge.fact_extraction.extract_facts_main") as mock_main:
                mock_main.return_value = 2  # Incomplete extraction

                result = main()

                assert result == 2


class TestExtractFactsMainEdgeCases:
    def test_displays_facts_with_rewritten_sentence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should display facts with rewritten sentences and confidence."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="Use create_app in app/core/factory.py.",
            entity="create_app",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        subagent_result = {
            "entity": "create_app",
            "original_sentence": "Use create_app in app/core/factory.py.",
            "facts": [
                {
                    "fact": "create_app is located in app/core/factory.py",
                    "confidence": 0.95,
                    "rewritten_sentence": "Use.",
                },
            ],
            "residual_sentence": "Use.",
            "validation": {
                "semantic_similarity": 0.98,
                "entity_absent": True,
                "information_preserved": True,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.return_value = subagent_result
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                extract_facts_main(args)

                captured = capsys.readouterr()
                assert "Iteration 1:" in captured.out
                assert "Fact:" in captured.out
                assert "Confidence:" in captured.out
                assert "Rewritten:" in captured.out

    def test_displays_facts_without_rewritten_sentence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should display facts when rewritten_sentence is empty."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="Entity does something.",
            entity="Entity",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # No rewritten_sentence in fact
        subagent_result = {
            "entity": "Entity",
            "original_sentence": "Entity does something.",
            "facts": [
                {"fact": "Entity does something", "confidence": 0.90, "rewritten_sentence": ""},
            ],
            "residual_sentence": "Does something.",
            "validation": {
                "semantic_similarity": 0.92,
                "entity_absent": True,
                "information_preserved": False,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.return_value = subagent_result
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                extract_facts_main(args)

                captured = capsys.readouterr()
                assert "Iteration 1:" in captured.out
                assert "Fact:" in captured.out

    def test_warns_on_low_semantic_similarity(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print warning when information_preserved is False."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="Entity does something important.",
            entity="Entity",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # Use inline extraction (which respects our validation mock) instead of subagent
        # Mock extract_facts_inline to return low similarity result
        inline_result = {
            "entity": "Entity",
            "original_sentence": "Entity does something important.",
            "facts": [{"fact": "Entity does something", "confidence": 0.7}],
            "residual_sentence": "Does.",
            "extraction_complete": True,
            "total_iterations": 1,
            "validation": {
                "semantic_similarity": 0.80,
                "entity_absent": True,
                "information_preserved": False,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.side_effect = FactExtractorError("Sub-agent unavailable")
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)
                with patch("scripts.knowledge.fact_extraction.extract_facts_inline") as mock_inline:
                    mock_inline.return_value = inline_result

                    extract_facts_main(args)

                    captured = capsys.readouterr()
                    assert "WARNING" in captured.err
                    assert (
                        "similarity" in captured.err.lower()
                        or "information" in captured.err.lower()
                    )

    def test_warns_on_incomplete_extraction(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print warning when entity is still present in residual."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="Entity does something with Entity.",
            entity="Entity",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # Mock inline extraction to return incomplete result
        inline_result = {
            "entity": "Entity",
            "original_sentence": "Entity does something with Entity.",
            "facts": [{"fact": "Entity does something", "confidence": 0.9}],
            "residual_sentence": "Does something with Entity.",  # Entity still present
            "total_iterations": 1,
            "extraction_complete": False,
            "validation": {
                "semantic_similarity": 0.95,
                "entity_absent": False,
                "information_preserved": True,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.side_effect = FactExtractorError("Sub-agent unavailable")
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)
                with patch("scripts.knowledge.fact_extraction.extract_facts_inline") as mock_inline:
                    mock_inline.return_value = inline_result

                    result = extract_facts_main(args)

                    assert result == 2  # Incomplete extraction
                    captured = capsys.readouterr()
                    assert "WARNING" in captured.err
                    assert "present" in captured.err.lower() or "Entity" in captured.err

    def test_returns_two_on_incomplete_extraction_dry_run(self, tmp_path: Path) -> None:
        """Should return 2 for incomplete extraction even in dry run mode."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            sentence="Entity does something.",
            entity="Entity",
            knowledge_path=tmp_path / ".knowledge",
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # Mock inline extraction to return incomplete result
        inline_result = {
            "entity": "Entity",
            "original_sentence": "Entity does something.",
            "facts": [{"fact": "Entity does", "confidence": 0.9}],
            "residual_sentence": "Does something with Entity.",  # Entity still present
            "total_iterations": 1,
            "extraction_complete": False,
            "validation": {
                "semantic_similarity": 0.95,
                "entity_absent": False,
                "information_preserved": True,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.side_effect = FactExtractorError("Sub-agent unavailable")
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)
                with patch("scripts.knowledge.fact_extraction.extract_facts_inline") as mock_inline:
                    mock_inline.return_value = inline_result

                    result = extract_facts_main(args)

                    assert result == 2

    def test_falls_back_to_residual_for_last_fact_without_rewritten(self, tmp_path: Path) -> None:
        """Should use residual as rewritten_sentence for last fact if not provided."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        knowledge_path = tmp_path / ".knowledge"
        csv_path = knowledge_path / "facts" / "extractions.csv"

        args = argparse.Namespace(
            sentence="Use create_app in app/core/factory.py.",
            entity="create_app",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
        )

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # Last fact has no rewritten_sentence
        subagent_result = {
            "entity": "create_app",
            "original_sentence": "Use create_app in app/core/factory.py.",
            "facts": [
                {
                    "fact": "create_app is in app/core/factory.py",
                    "confidence": 0.95,
                },  # No rewritten_sentence
            ],
            "residual_sentence": "Use in.",
            "validation": {
                "semantic_similarity": 0.98,
                "entity_absent": True,
                "information_preserved": True,
            },
        }

        with patch("scripts.knowledge.fact_extraction.invoke_fact_extractor") as mock_invoke:
            mock_invoke.return_value = subagent_result
            with patch("scripts.knowledge.fact_extraction.load_qwen_embedding_model") as mock_load:
                mock_load.return_value = (mock_model, mock_tokenizer)

                result = extract_facts_main(args)

                assert result == 0
                assert csv_path.exists()
                # Check that the residual was used as rewritten_sentence
                content = csv_path.read_text()
                assert "Use in." in content

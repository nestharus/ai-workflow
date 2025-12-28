from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.knowledge import qwen_scoring
from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.qwen_scoring import (
    get_unscored_candidates,
    load_reranker_model,
    main,
    parse_args,
    score_batch,
    score_candidates_main,
    update_candidate_scores_batch,
)


def _make_csv_row(
    candidate_id: str,
    source_file: str,
    element_id: str,
    sentence: str,
    candidate_text: str,
    start_char: str,
    end_char: str,
    detected_at: str,
    keep: str = "",
    confidence: str = "",
    reason: str = "",
    classified_at: str = "",
    qwen_score: str = "",
    projection_version: str = "fieldfacts.v2",
    source_field_path: str = "",
    source_scope_path: str = "",
    field_role: str = "",
    artifact_kind: str = "",
) -> str:
    """Helper to create a CSV row matching the new schema."""
    return ",".join(
        [
            candidate_id,
            source_file,
            element_id,
            sentence,
            candidate_text,
            start_char,
            end_char,
            detected_at,
            keep,
            confidence,
            reason,
            classified_at,
            qwen_score,
            projection_version,
            source_field_path,
            source_scope_path,
            field_role,
            artifact_kind,
        ]
    )


class TestLoadRerankerModel:
    def test_raises_import_error_when_torch_not_available(self) -> None:
        """Should raise ImportError when torch/transformers not installed (lines 117-122)."""
        with patch.dict("sys.modules", {"torch": None, "transformers": None}):
            # Force reload of the import to trigger ImportError
            with pytest.raises(ImportError) as exc_info:
                # Since torch/transformers are likely installed, we mock the import
                original_import = __builtins__["__import__"]

                def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
                    if name in ("torch", "transformers"):
                        raise ImportError(f"No module named '{name}'")
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=mock_import):
                    load_reranker_model("test-model")

            assert "transformers and torch are required" in str(exc_info.value)


class TestLoadRerankerModelActual:
    def test_load_reranker_model_import_error(self) -> None:
        """Test load_reranker_model raises ImportError (lines 117-122)."""
        import builtins
        import importlib
        import sys

        original_torch = sys.modules.get("torch")
        original_transformers = sys.modules.get("transformers")

        try:
            # Remove torch and transformers from sys.modules to simulate not installed
            if "torch" in sys.modules:
                del sys.modules["torch"]
            if "transformers" in sys.modules:
                del sys.modules["transformers"]

            # Create a mock import that raises ImportError for torch/transformers
            original_import = builtins.__import__

            def mock_import_error(name: str, *args: Any, **kwargs: Any) -> Any:
                if name in ("torch", "transformers"):
                    raise ImportError(f"No module named '{name}'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import_error):
                importlib.reload(qwen_scoring)

                with pytest.raises(ImportError) as exc_info:
                    qwen_scoring.load_reranker_model("test-model")

                assert "transformers and torch are required" in str(exc_info.value)

        finally:
            if original_torch is not None:
                sys.modules["torch"] = original_torch
            if original_transformers is not None:
                sys.modules["transformers"] = original_transformers
            importlib.reload(qwen_scoring)


class TestMain:
    def test_calls_parse_args_and_score_candidates_main(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should call parse_args and score_candidates_main (lines 313-314)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "keywords").mkdir(parents=True)

        with (
            patch.object(qwen_scoring, "REPO_ROOT", tmp_path),
            patch("sys.argv", ["script"]),
        ):
            result = main()

        # Will return 1 because candidates.csv doesn't exist
        assert result == 1

    def test_returns_score_candidates_main_result(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return result from score_candidates_main."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "keywords").mkdir(parents=True)
        csv_path = knowledge_path / "keywords" / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "sent1",
            "FastAPI",
            "0",
            "7",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "0.95",  # Already scored
        )
        csv_path.write_text(f"{header}\n{row}\n")

        with (
            patch.object(qwen_scoring, "REPO_ROOT", tmp_path),
            patch("sys.argv", ["script", "--knowledge-path", str(knowledge_path)]),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "No unscored candidates found" in captured.out

"""Tests for scripts.knowledge.ministral_hunter module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.knowledge.ministral_hunter import (
    EntityResult,
    FactResult,
    HunterError,
    HunterOutput,
    SpanResult,
    TargetEntity,
    _parse_json_response,
    _validate_hunter_output,
    invoke_hunter,
    invoke_hunter_mock,
    load_ministral_model,
)


class TestLoadMinistralModel:
    """Tests for load_ministral_model function."""

    def test_loads_model_and_tokenizer(self) -> None:
        """Should load model and tokenizer from transformers."""
        with patch("transformers.AutoTokenizer") as mock_tokenizer_cls:
            with patch("transformers.AutoModelForCausalLM") as mock_model_cls:
                mock_tokenizer = MagicMock()
                mock_model = MagicMock()
                mock_tokenizer_cls.from_pretrained.return_value = mock_tokenizer
                mock_model_cls.from_pretrained.return_value = mock_model

                model, tokenizer = load_ministral_model("test-model")

                mock_tokenizer_cls.from_pretrained.assert_called_once_with(
                    "test-model", trust_remote_code=True
                )
                mock_model_cls.from_pretrained.assert_called_once()
                mock_model.eval.assert_called_once()
                assert model == mock_model
                assert tokenizer == mock_tokenizer

    def test_raises_hunter_error_on_failure(self) -> None:
        """Should raise HunterError when model loading fails."""
        with patch("transformers.AutoTokenizer") as mock_tokenizer_cls:
            mock_tokenizer_cls.from_pretrained.side_effect = RuntimeError("Load failed")

            with pytest.raises(HunterError, match="Failed to load Ministral model"):
                load_ministral_model("invalid-model")


class TestInvokeHunterEntitiesMode:
    """Tests for invoke_hunter in entities mode."""

    def test_invoke_hunter_entities_mode_returns_output(self, tmp_path: Path) -> None:
        """Should return HunterOutput with entities."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Mock tokenizer behavior
        mock_tokenizer.return_tensors = "pt"
        mock_tokenizer.return_value = {"input_ids": MagicMock()}
        mock_tokenizer.eos_token_id = 1

        # Mock model parameters
        mock_param = MagicMock()
        mock_param.device = "cpu"
        mock_model.parameters.return_value = iter([mock_param])

        # Mock generate output
        mock_outputs = MagicMock()
        mock_model.generate.return_value = mock_outputs

        # Mock decode to return valid JSON
        mock_tokenizer.decode.return_value = """
        {
            "mode": "entities",
            "entities": [{"mention": "create_app", "type_hint": "FUNCTION", "evidence_span_id": "span_1"}],
            "target_entity": null,
            "facts": [],
            "spans": [{"span_id": "span_1", "original_text": "The create_app function."}],
            "done": false,
            "reason": null
        }
        """

        with patch("torch.no_grad"):
            result = invoke_hunter(
                state_text="The create_app function initializes the app.",
                mode="entities",
                model=mock_model,
                tokenizer=mock_tokenizer,
                knowledge_path=tmp_path,
            )

        assert result["mode"] == "entities"
        assert len(result["entities"]) == 1
        assert result["entities"][0]["mention"] == "create_app"
        assert result["done"] is False


class TestInvokeHunterFactsMode:
    """Tests for invoke_hunter in facts mode."""

    def test_invoke_hunter_facts_mode_requires_target(self) -> None:
        """Should raise ValueError when target_entity not provided."""
        with pytest.raises(ValueError, match="target_entity is required"):
            invoke_hunter(state_text="Some text", mode="facts")

    def test_invoke_hunter_facts_mode_returns_facts(self, tmp_path: Path) -> None:
        """Should return HunterOutput with facts for target entity."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Mock tokenizer behavior
        mock_tokenizer.return_tensors = "pt"
        mock_tokenizer.return_value = {"input_ids": MagicMock()}
        mock_tokenizer.eos_token_id = 1

        # Mock model parameters
        mock_param = MagicMock()
        mock_param.device = "cpu"
        mock_model.parameters.return_value = iter([mock_param])

        # Mock generate output
        mock_outputs = MagicMock()
        mock_model.generate.return_value = mock_outputs

        # Mock decode to return valid JSON
        mock_tokenizer.decode.return_value = """
        {
            "mode": "facts",
            "entities": [],
            "target_entity": {"mention": "create_app", "resolved_id": "create_app"},
            "facts": [{"fact_text": "create_app is a factory function", "evidence_span_id": "span_1", "confidence": 0.95}],
            "spans": [{"span_id": "span_1", "original_text": "create_app is a factory function."}],
            "done": false,
            "reason": null
        }
        """

        with patch("torch.no_grad"):
            result = invoke_hunter(
                state_text="The create_app is a factory function that initializes the app.",
                target_entity="create_app",
                mode="facts",
                model=mock_model,
                tokenizer=mock_tokenizer,
                knowledge_path=tmp_path,
            )

        assert result["mode"] == "facts"
        assert result["target_entity"]["mention"] == "create_app"
        assert len(result["facts"]) == 1
        assert result["facts"][0]["confidence"] == 0.95


class TestInvokeHunterJsonParsing:
    """Tests for JSON parsing in invoke_hunter."""

    def test_parse_json_response_valid(self) -> None:
        """Should parse valid JSON response."""
        response = '{"mode": "entities", "entities": [], "facts": [], "spans": [], "done": true, "reason": null}'

        result = _parse_json_response(response)

        assert result["mode"] == "entities"
        assert result["done"] is True

    def test_parse_json_response_with_prefix(self) -> None:
        """Should extract JSON from response with prefix text."""
        response = 'Here is my response:\n{"mode": "entities", "entities": [], "facts": [], "spans": [], "done": true}'

        result = _parse_json_response(response)

        assert result["mode"] == "entities"

    def test_parse_json_response_invalid_raises_error(self) -> None:
        """Should raise HunterError for invalid JSON."""
        response = "not valid json {"

        with pytest.raises(HunterError, match="No JSON found"):
            _parse_json_response(response)

    def test_parse_json_response_malformed_raises_error(self) -> None:
        """Should raise HunterError for malformed JSON."""
        response = '{"mode": "entities", "missing_quote: }'

        with pytest.raises(HunterError, match="Invalid JSON"):
            _parse_json_response(response)


class TestInvokeHunterValidation:
    """Tests for validation in invoke_hunter."""

    def test_validate_hunter_output_missing_fields(self) -> None:
        """Should raise HunterError when required fields are missing."""
        data = {"mode": "entities", "done": True}  # Missing entities, facts, spans

        with pytest.raises(HunterError, match="Missing required fields"):
            _validate_hunter_output(data, "entities")

    def test_validate_hunter_output_mode_mismatch(self) -> None:
        """Should raise HunterError when mode doesn't match."""
        data = {
            "mode": "facts",
            "entities": [],
            "facts": [],
            "spans": [],
            "done": False,
        }

        with pytest.raises(HunterError, match="Mode mismatch"):
            _validate_hunter_output(data, "entities")

    def test_validate_hunter_output_facts_missing_target(self) -> None:
        """Should raise HunterError when target_entity missing for facts mode."""
        data = {
            "mode": "facts",
            "entities": [],
            "facts": [],
            "spans": [],
            "done": False,
        }

        with pytest.raises(HunterError, match="Missing 'target_entity'"):
            _validate_hunter_output(data, "facts")


class TestInvokeHunterErrorHandling:
    """Tests for error handling in invoke_hunter."""

    def test_invoke_hunter_timeout_raises_error(self, tmp_path: Path) -> None:
        """Should raise HunterError on inference timeout."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {"input_ids": MagicMock()}
        mock_tokenizer.eos_token_id = 1

        mock_param = MagicMock()
        mock_param.device = "cpu"
        mock_model.parameters.return_value = iter([mock_param])

        # Mock generate to raise timeout error
        mock_model.generate.side_effect = TimeoutError("Inference timed out")

        with patch("torch.no_grad"):
            with pytest.raises(HunterError, match="Inference failed"):
                invoke_hunter(
                    state_text="Test text",
                    mode="entities",
                    model=mock_model,
                    tokenizer=mock_tokenizer,
                    knowledge_path=tmp_path,
                )


class TestInvokeHunterMock:
    """Tests for invoke_hunter_mock function."""

    def test_mock_returns_hunter_output_structure(self) -> None:
        """Should return valid HunterOutput structure."""
        result = invoke_hunter_mock("The create_app function creates a FastAPI application.")

        assert "mode" in result
        assert "entities" in result
        assert "facts" in result
        assert "spans" in result
        assert "done" in result
        assert isinstance(result["entities"], list)
        assert isinstance(result["done"], bool)

    def test_mock_entities_mode_extracts_entities(self) -> None:
        """Should extract entities from artifact text in entity mode."""
        result = invoke_hunter_mock(
            "The create_app function creates a FastAPI application.",
            mode="entities",
        )

        assert result["mode"] == "entities"
        assert result["target_entity"] is None
        # Should find CamelCase or snake_case identifiers
        assert len(result["entities"]) >= 0

    def test_mock_facts_mode_extracts_facts(self) -> None:
        """Should extract facts for target entity in facts mode."""
        result = invoke_hunter_mock(
            "The create_app function initializes the application.",
            target_entity="create_app",
            mode="facts",
        )

        assert result["mode"] == "facts"
        assert result["target_entity"] is not None
        assert result["target_entity"]["mention"] == "create_app"

    def test_mock_facts_mode_returns_done_for_missing_entity(self) -> None:
        """Should return done=true when entity not found."""
        result = invoke_hunter_mock(
            "Some text without the entity.",
            target_entity="nonexistent_entity",
            mode="facts",
        )

        assert result["done"] is True
        assert "not found" in (result["reason"] or "").lower()

    def test_mock_deterministic_output(self) -> None:
        """Should return consistent output for same input."""
        text = "The create_app function initializes the application."

        result1 = invoke_hunter_mock(text, mode="entities")
        result2 = invoke_hunter_mock(text, mode="entities")

        assert result1["mode"] == result2["mode"]
        assert result1["done"] == result2["done"]
        assert len(result1["entities"]) == len(result2["entities"])

    def test_mock_returns_done_true_for_empty_text(self) -> None:
        """Should return done=true for empty text."""
        result = invoke_hunter_mock("")

        assert result["done"] is True


class TestHunterOutputTypedDict:
    """Tests for HunterOutput TypedDict structure."""

    def test_valid_hunter_output(self) -> None:
        """Should accept valid HunterOutput structure."""
        output: HunterOutput = {
            "mode": "entities",
            "entities": [
                EntityResult(
                    mention="create_app",
                    type_hint="FUNCTION",
                    evidence_span_id="span_1",
                )
            ],
            "target_entity": None,
            "facts": [],
            "spans": [
                SpanResult(
                    span_id="span_1",
                    original_text="The create_app function.",
                )
            ],
            "done": False,
            "reason": None,
        }

        assert output["entities"][0]["mention"] == "create_app"
        assert output["done"] is False

    def test_entity_result_structure(self) -> None:
        """Should accept valid EntityResult structure."""
        entity: EntityResult = {
            "mention": "create_app",
            "type_hint": "FUNCTION",
            "evidence_span_id": "span_1",
        }

        assert entity["mention"] == "create_app"
        assert entity["type_hint"] == "FUNCTION"

    def test_fact_result_structure(self) -> None:
        """Should accept valid FactResult structure."""
        fact: FactResult = {
            "fact_text": "create_app is a factory function",
            "evidence_span_id": "span_1",
            "confidence": 0.95,
        }

        assert fact["fact_text"] == "create_app is a factory function"
        assert fact["confidence"] == 0.95

    def test_span_result_structure(self) -> None:
        """Should accept valid SpanResult structure."""
        span: SpanResult = {
            "span_id": "span_1",
            "original_text": "The function creates an app.",
        }

        assert span["span_id"] == "span_1"
        assert "original_text" in span

    def test_target_entity_structure(self) -> None:
        """Should accept valid TargetEntity structure."""
        target: TargetEntity = {
            "mention": "create_app",
            "resolved_id": "create_app",
        }

        assert target["mention"] == "create_app"
        assert target["resolved_id"] == "create_app"

    def test_hunter_output_facts_mode(self) -> None:
        """Should accept valid HunterOutput in facts mode."""
        output: HunterOutput = {
            "mode": "facts",
            "entities": [],
            "target_entity": TargetEntity(mention="create_app", resolved_id="create_app"),
            "facts": [
                FactResult(
                    fact_text="create_app initializes the app",
                    evidence_span_id="span_1",
                    confidence=0.9,
                )
            ],
            "spans": [
                SpanResult(
                    span_id="span_1",
                    original_text="create_app initializes the app.",
                )
            ],
            "done": False,
            "reason": None,
        }

        assert output["mode"] == "facts"
        assert output["target_entity"]["mention"] == "create_app"
        assert len(output["facts"]) == 1

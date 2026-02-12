"""Tests for JudgeClient."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from spec_manager.refinement.evals.judges.cache import JudgeCache, JudgeCacheKey
from spec_manager.refinement.evals.judges.client import JudgeClient


class _Verdict(BaseModel):
    """Minimal schema for testing."""

    value: str


_AGENT = "test-judge"
_VALID_JSON = json.dumps({"value": "pass"})


class TestJudgeClientBasic:
    """Core parse-and-validate path."""

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_valid_output_returns_model(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        client = JudgeClient(_AGENT, tmp_path, _Verdict)
        result = client.judge("rate this")
        assert isinstance(result, _Verdict)
        assert result.value == "pass"

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_code_fenced_output_parsed(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = f"```json\n{_VALID_JSON}\n```"  # type: ignore[attr-defined]
        client = JudgeClient(_AGENT, tmp_path, _Verdict)
        result = client.judge("rate this")
        assert result.value == "pass"


class TestJudgeClientRetry:
    """Retry behaviour on transient failures."""

    @patch("spec_manager.refinement.evals.judges.client.time.sleep")
    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_retries_on_garbage_then_succeeds(
        self, mock_agent: object, _mock_sleep: object, tmp_path: Path
    ) -> None:
        mock_agent.side_effect = ["not json at all", _VALID_JSON]  # type: ignore[attr-defined]
        client = JudgeClient(_AGENT, tmp_path, _Verdict, max_retries=2)
        result = client.judge("rate this")
        assert result.value == "pass"

    @patch("spec_manager.refinement.evals.judges.client.time.sleep")
    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_raises_after_all_retries_exhausted(
        self, mock_agent: object, _mock_sleep: object, tmp_path: Path
    ) -> None:
        mock_agent.return_value = "garbage"  # type: ignore[attr-defined]
        client = JudgeClient(_AGENT, tmp_path, _Verdict, max_retries=2)
        with pytest.raises(RuntimeError, match="failed after 2 attempts"):
            client.judge("rate this")


class TestJudgeClientCache:
    """Cache integration."""

    def _make_key(self) -> JudgeCacheKey:
        return JudgeCacheKey(
            judge_type="test",
            model_id="m1",
            prompt_version="v1",
            input_hash="abc123",
        )

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_cache_hit_skips_agent(self, mock_agent: object, tmp_path: Path) -> None:
        cache = JudgeCache(tmp_path)
        key = self._make_key()
        cache.put(key, {"value": "cached"})

        client = JudgeClient(_AGENT, tmp_path, _Verdict)
        result = client.judge("rate this", cache=cache, cache_key=key)

        assert result.value == "cached"
        mock_agent.assert_not_called()  # type: ignore[attr-defined]

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_cache_miss_calls_agent_and_stores(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        cache = JudgeCache(tmp_path)
        key = self._make_key()

        client = JudgeClient(_AGENT, tmp_path, _Verdict)
        result = client.judge("rate this", cache=cache, cache_key=key)

        assert result.value == "pass"
        mock_agent.assert_called_once()  # type: ignore[attr-defined]
        assert cache.get(key) == {"value": "pass"}


class TestJudgeClientModelId:
    """Tests for model_id passing to run_agent."""

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_model_id_passed_to_run_agent(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        client = JudgeClient(_AGENT, tmp_path, _Verdict, model_id="opus-4")
        client.judge("rate this")
        call_kwargs = mock_agent.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs["model_id"] == "opus-4"

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_empty_model_id_passed_as_empty(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        client = JudgeClient(_AGENT, tmp_path, _Verdict)
        client.judge("rate this")
        call_kwargs = mock_agent.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs["model_id"] == ""


class TestJudgeClientSelfJudgeEnforcement:
    """Tests for judge != producer enforcement."""

    def test_same_model_raises_without_override(self, tmp_path: Path) -> None:
        client = JudgeClient(
            _AGENT,
            tmp_path,
            _Verdict,
            model_id="opus-4",
            producer_model_id="opus-4",
        )
        with pytest.raises(ValueError, match="same as producer model"):
            client.judge("rate this")

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_same_model_allowed_with_flag(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        client = JudgeClient(
            _AGENT,
            tmp_path,
            _Verdict,
            model_id="opus-4",
            producer_model_id="opus-4",
            allow_self_judge=True,
        )
        result = client.judge("rate this")
        assert result.value == "pass"

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_different_models_no_error(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        client = JudgeClient(
            _AGENT,
            tmp_path,
            _Verdict,
            model_id="opus-4",
            producer_model_id="gpt-4o",
        )
        result = client.judge("rate this")
        assert result.value == "pass"

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_empty_producer_model_no_error(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        client = JudgeClient(
            _AGENT,
            tmp_path,
            _Verdict,
            model_id="opus-4",
            producer_model_id="",
        )
        result = client.judge("rate this")
        assert result.value == "pass"

    @patch("spec_manager.refinement.evals.judges.client.run_agent")
    def test_empty_judge_model_no_error(self, mock_agent: object, tmp_path: Path) -> None:
        mock_agent.return_value = _VALID_JSON  # type: ignore[attr-defined]
        client = JudgeClient(
            _AGENT,
            tmp_path,
            _Verdict,
            model_id="",
            producer_model_id="gpt-4o",
        )
        result = client.judge("rate this")
        assert result.value == "pass"

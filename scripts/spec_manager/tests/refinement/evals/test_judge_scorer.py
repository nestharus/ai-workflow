"""Tests for LLM judge scorer module."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from spec_manager.refinement.evals.judge_scorer import (
    _build_judge_prompt,
    _parse_judge_output,
    _to_detail_score,
    score_detail_capture_with_judge,
)
from spec_manager.schemas.eval_judge import EvalJudgeOutput, ItemMatch


class TestBuildJudgePrompt:
    """Tests for _build_judge_prompt."""

    def test_includes_expected_items(self) -> None:
        prompt = _build_judge_prompt(["item A", "item B"], ["actual X"])
        assert "item A" in prompt
        assert "item B" in prompt

    def test_includes_actual_items(self) -> None:
        prompt = _build_judge_prompt(["item A"], ["actual X", "actual Y"])
        assert "actual X" in prompt
        assert "actual Y" in prompt

    def test_includes_phase_context(self) -> None:
        prompt = _build_judge_prompt(["a"], ["b"], phase="sectionization")
        assert "sectionization" in prompt

    def test_no_phase_context_when_empty(self) -> None:
        prompt = _build_judge_prompt(["a"], ["b"], phase="")
        assert "Phase:" not in prompt

    def test_has_all_sections(self) -> None:
        prompt = _build_judge_prompt(["a"], ["b"])
        assert "OUTPUT CONTRACT" in prompt
        assert "INPUT DATA" in prompt
        assert "OUTPUT FORMAT" in prompt

    def test_counts_in_headers(self) -> None:
        prompt = _build_judge_prompt(["a", "b", "c"], ["x"])
        assert "Expected Items (3)" in prompt
        assert "Actual Items (1)" in prompt


class TestParseJudgeOutput:
    """Tests for _parse_judge_output."""

    def test_valid_json(self) -> None:
        data = {
            "matches": [
                {
                    "expected_index": 0,
                    "actual_index": 1,
                    "matched": True,
                    "rationale": "Equivalent meaning.",
                }
            ],
            "unmatched_actual": [0],
            "summary": "1/1 matched",
        }
        result = _parse_judge_output(json.dumps(data))
        assert len(result.matches) == 1
        assert result.matches[0].matched is True
        assert result.unmatched_actual == [0]

    def test_code_fenced_json(self) -> None:
        data = {
            "matches": [
                {
                    "expected_index": 0,
                    "actual_index": 0,
                    "matched": True,
                    "rationale": "Same.",
                }
            ],
            "unmatched_actual": [],
            "summary": "All matched",
        }
        raw = f"```json\n{json.dumps(data)}\n```"
        result = _parse_judge_output(raw)
        assert len(result.matches) == 1
        assert result.matches[0].matched is True

    def test_json_with_preamble(self) -> None:
        data = {
            "matches": [
                {
                    "expected_index": 0,
                    "actual_index": None,
                    "matched": False,
                    "rationale": "No match found.",
                }
            ],
            "unmatched_actual": [0],
            "summary": "0/1 matched",
        }
        raw = f"Here is my analysis:\n{json.dumps(data)}"
        result = _parse_judge_output(raw)
        assert len(result.matches) == 1
        assert result.matches[0].matched is False

    def test_missing_matches_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_judge_output('{"summary": "no matches field"}')


class TestToDetailScore:
    """Tests for _to_detail_score."""

    def test_perfect_match(self) -> None:
        judge = EvalJudgeOutput(
            matches=[
                ItemMatch(expected_index=0, actual_index=0, matched=True, rationale="ok"),
                ItemMatch(expected_index=1, actual_index=1, matched=True, rationale="ok"),
            ],
            unmatched_actual=[],
            summary="All matched",
        )
        score = _to_detail_score(judge, expected_count=2, actual_count=2)
        assert score.matched_count == 2
        assert score.recall == 1.0
        assert score.precision == 1.0

    def test_partial_match(self) -> None:
        judge = EvalJudgeOutput(
            matches=[
                ItemMatch(expected_index=0, actual_index=0, matched=True, rationale="ok"),
                ItemMatch(expected_index=1, actual_index=None, matched=False, rationale="no"),
            ],
            unmatched_actual=[1, 2],
            summary="1/2 matched",
        )
        score = _to_detail_score(judge, expected_count=2, actual_count=3)
        assert score.matched_count == 1
        assert score.recall == pytest.approx(0.5)
        assert score.precision == pytest.approx(1.0 / 3.0)

    def test_no_matches(self) -> None:
        judge = EvalJudgeOutput(
            matches=[
                ItemMatch(expected_index=0, actual_index=None, matched=False, rationale="no"),
            ],
            unmatched_actual=[0, 1],
            summary="0/1 matched",
        )
        score = _to_detail_score(judge, expected_count=1, actual_count=2)
        assert score.matched_count == 0
        assert score.recall == 0.0
        assert score.precision == 0.0


class TestScoreDetailCaptureWithJudge:
    """Tests for score_detail_capture_with_judge."""

    def test_both_empty(self, tmp_path) -> None:
        score = score_detail_capture_with_judge([], [], workspace=tmp_path)
        assert score.recall == 1.0
        assert score.precision == 1.0
        assert score.matched_count == 0

    def test_empty_expected(self, tmp_path) -> None:
        score = score_detail_capture_with_judge(
            [], ["actual item"], workspace=tmp_path
        )
        assert score.recall == 1.0
        assert score.precision == 0.0

    def test_empty_actual(self, tmp_path) -> None:
        score = score_detail_capture_with_judge(
            ["expected item"], [], workspace=tmp_path
        )
        assert score.recall == 0.0
        assert score.precision == 1.0

    @patch("spec_manager.refinement.evals.judge_scorer.run_agent")
    def test_calls_correct_agent(self, mock_run_agent, tmp_path) -> None:
        mock_run_agent.return_value = json.dumps(
            {
                "matches": [
                    {
                        "expected_index": 0,
                        "actual_index": 0,
                        "matched": True,
                        "rationale": "Same.",
                    }
                ],
                "unmatched_actual": [],
                "summary": "ok",
            }
        )
        score_detail_capture_with_judge(
            ["expected"], ["actual"], workspace=tmp_path
        )
        mock_run_agent.assert_called_once()
        call_kwargs = mock_run_agent.call_args[1]
        assert call_kwargs["agent_name"] == "chatgpt-eval-detail-judge"

    @patch("spec_manager.refinement.evals.judge_scorer.run_agent")
    def test_prompt_contains_items(self, mock_run_agent, tmp_path) -> None:
        mock_run_agent.return_value = json.dumps(
            {
                "matches": [
                    {
                        "expected_index": 0,
                        "actual_index": 0,
                        "matched": True,
                        "rationale": "ok",
                    }
                ],
                "unmatched_actual": [],
                "summary": "ok",
            }
        )
        score_detail_capture_with_judge(
            ["Fibonacci recurrence"], ["Fibonacci formula"],
            workspace=tmp_path,
            phase="spec_building",
        )
        call_kwargs = mock_run_agent.call_args[1]
        assert "Fibonacci recurrence" in call_kwargs["prompt"]
        assert "Fibonacci formula" in call_kwargs["prompt"]
        assert "spec_building" in call_kwargs["prompt"]

    @patch("spec_manager.refinement.evals.judge_scorer.run_agent")
    def test_score_conversion(self, mock_run_agent, tmp_path) -> None:
        mock_run_agent.return_value = json.dumps(
            {
                "matches": [
                    {
                        "expected_index": 0,
                        "actual_index": 0,
                        "matched": True,
                        "rationale": "ok",
                    },
                    {
                        "expected_index": 1,
                        "actual_index": None,
                        "matched": False,
                        "rationale": "no match",
                    },
                ],
                "unmatched_actual": [1],
                "summary": "1/2",
            }
        )
        score = score_detail_capture_with_judge(
            ["a", "b"], ["x", "y"], workspace=tmp_path
        )
        assert score.matched_count == 1
        assert score.expected_count == 2
        assert score.actual_count == 2
        assert score.recall == pytest.approx(0.5)
        assert score.precision == pytest.approx(0.5)

    @patch("spec_manager.refinement.evals.judge_scorer.run_agent")
    def test_code_fenced_response(self, mock_run_agent, tmp_path) -> None:
        data = {
            "matches": [
                {
                    "expected_index": 0,
                    "actual_index": 0,
                    "matched": True,
                    "rationale": "ok",
                }
            ],
            "unmatched_actual": [],
            "summary": "ok",
        }
        mock_run_agent.return_value = f"```json\n{json.dumps(data)}\n```"
        score = score_detail_capture_with_judge(
            ["a"], ["b"], workspace=tmp_path
        )
        assert score.matched_count == 1
        assert score.recall == 1.0

    @patch("spec_manager.refinement.evals.judge_scorer.run_agent")
    def test_agent_error_propagation(self, mock_run_agent, tmp_path) -> None:
        mock_run_agent.side_effect = RuntimeError("Agent failed")
        with pytest.raises(RuntimeError, match="Agent failed"):
            score_detail_capture_with_judge(
                ["a"], ["b"], workspace=tmp_path
            )

"""Tests for scripts.knowledge.surgeon_orchestrator module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from scripts.knowledge.surgeon_orchestrator import (
    GroupResult,
    OrganizerOutput,
    PlannerOutput,
    ReviewerOutput,
    RewriteResult,
    RewriterOutput,
    SpanInput,
    SurgeonError,
    SurgeonResult,
    ValidationResult,
    compute_score_drop,
    invoke_sub_agent,
    orchestrate_surgeon_pipeline,
    orchestrate_surgeon_pipeline_mock,
    validate_removal_qwen3,
    validate_removal_with_anchors,
)


class TestInvokeSubAgent:
    """Tests for invoke_sub_agent function."""

    def test_invoke_sub_agent_success(self, tmp_path: Path) -> None:
        """Should invoke sub-agent and return parsed JSON."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"result": "success", "data": [1, 2, 3]}'
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = invoke_sub_agent(
                "fact-surgeon-organizer",
                {"input": "test"},
                knowledge_path=tmp_path,
            )

            assert result["result"] == "success"
            assert result["data"] == [1, 2, 3]
            mock_run.assert_called_once()

    def test_invoke_sub_agent_extracts_json_from_text(self, tmp_path: Path) -> None:
        """Should extract JSON from response with surrounding text."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = 'Here is my response:\n{"groups": []}\nDone!'
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = invoke_sub_agent(
                "fact-surgeon-organizer",
                {"spans": []},
                knowledge_path=tmp_path,
            )

            assert result["groups"] == []

    def test_invoke_sub_agent_timeout_raises_error(self, tmp_path: Path) -> None:
        """Should raise SurgeonError on timeout."""
        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)),
            pytest.raises(SurgeonError, match="timed out"),
        ):
            invoke_sub_agent(
                "fact-surgeon-organizer",
                {"input": "test"},
                timeout=120,
                knowledge_path=tmp_path,
            )

    def test_invoke_sub_agent_not_found_raises_error(self, tmp_path: Path) -> None:
        """Should raise SurgeonError when Claude CLI not found."""
        with (
            patch("subprocess.run", side_effect=FileNotFoundError("claude")),
            pytest.raises(SurgeonError, match="Claude CLI not found"),
        ):
            invoke_sub_agent(
                "fact-surgeon-organizer",
                {"input": "test"},
                knowledge_path=tmp_path,
            )

    def test_invoke_sub_agent_non_zero_exit_raises_error(self, tmp_path: Path) -> None:
        """Should raise SurgeonError on non-zero exit code."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: Agent failed"

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(SurgeonError, match="non-zero exit code"),
        ):
            invoke_sub_agent(
                "fact-surgeon-organizer",
                {"input": "test"},
                knowledge_path=tmp_path,
            )

    def test_invoke_sub_agent_empty_output_raises_error(self, tmp_path: Path) -> None:
        """Should raise SurgeonError on empty output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(SurgeonError, match="empty output"),
        ):
            invoke_sub_agent(
                "fact-surgeon-organizer",
                {"input": "test"},
                knowledge_path=tmp_path,
            )

    def test_invoke_sub_agent_invalid_json_raises_error(self, tmp_path: Path) -> None:
        """Should raise SurgeonError on invalid JSON output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"
        mock_result.stderr = ""

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(SurgeonError, match="No JSON found"),
        ):
            invoke_sub_agent(
                "fact-surgeon-organizer",
                {"input": "test"},
                knowledge_path=tmp_path,
            )


class TestValidateRemovalQwen3:
    """Tests for validate_removal_qwen3 function."""

    def test_score_drop_calculation(self) -> None:
        """Should compute score drop correctly."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with patch("scripts.knowledge.surgeon_orchestrator.embed_keywords") as mock_embed:
            mock_embed.return_value = np.array(
                [
                    [1.0, 0.0, 0.0],  # fact
                    [0.9, 0.1, 0.0],  # original (similar to fact)
                    [0.1, 0.9, 0.0],  # rewritten (dissimilar to fact)
                ]
            )

            with patch(
                "scripts.knowledge.surgeon_orchestrator.compute_cosine_similarity"
            ) as mock_sim:
                mock_sim.return_value = np.array(
                    [
                        [1.0, 0.9, 0.1],  # fact similarities
                        [0.9, 1.0, 0.2],  # original similarities
                        [0.1, 0.2, 1.0],  # rewritten similarities
                    ]
                )

                score_drop, passed = validate_removal_qwen3(
                    "create_app is a function",
                    "The create_app function initializes the app.",
                    "The function initializes the app.",
                    mock_model,
                    mock_tokenizer,
                )

                # score_drop = sim(fact, original) - sim(fact, rewritten) = 0.9 - 0.1 = 0.8
                assert score_drop == pytest.approx(0.8, rel=0.01)
                assert passed is True  # 0.8 >= 0.2 threshold

    def test_handles_empty_new_span(self) -> None:
        """Should return score_drop 1.0 for empty new span."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        score_drop, passed = validate_removal_qwen3(
            "fact text",
            "original text",
            "",  # Empty span = full deletion
            mock_model,
            mock_tokenizer,
        )

        assert score_drop == 1.0
        assert passed is True

    def test_threshold_comparison(self) -> None:
        """Should correctly compare against threshold."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with patch("scripts.knowledge.surgeon_orchestrator.embed_keywords") as mock_embed:
            mock_embed.return_value = np.array([[1.0, 0.0], [0.8, 0.2], [0.7, 0.3]])

            with patch(
                "scripts.knowledge.surgeon_orchestrator.compute_cosine_similarity"
            ) as mock_sim:
                # Low score drop (0.1)
                mock_sim.return_value = np.array(
                    [[1.0, 0.5, 0.4], [0.5, 1.0, 0.9], [0.4, 0.9, 1.0]]
                )

                score_drop, passed = validate_removal_qwen3(
                    "fact",
                    "original",
                    "rewritten",
                    mock_model,
                    mock_tokenizer,
                    threshold=0.2,
                )

                # score_drop = 0.5 - 0.4 = 0.1, below threshold
                assert score_drop == pytest.approx(0.1, rel=0.01)
                assert passed is False


class TestValidateRemovalWithAnchors:
    """Tests for validate_removal_with_anchors function."""

    def test_returns_validation_result(self) -> None:
        """Should return ValidationResult structure."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with patch("scripts.knowledge.surgeon_orchestrator.embed_keywords") as mock_embed:
            mock_embed.return_value = np.array([[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.8, 0.1, 0.1]])

            with patch(
                "scripts.knowledge.surgeon_orchestrator.compute_cosine_similarity"
            ) as mock_sim:
                mock_sim.return_value = np.array(
                    [
                        [1.0, 0.9, 0.5],  # fact similarities
                        [0.9, 1.0, 0.8],  # original similarities
                        [0.5, 0.8, 1.0],  # new similarities
                    ]
                )

                result = validate_removal_with_anchors(
                    "create_app is a function",
                    "The create_app function initializes the app.",
                    "The function initializes the app.",
                    mock_model,
                    mock_tokenizer,
                )

                assert "score_drop" in result
                assert "target_passed" in result
                assert "anchor_similarity" in result
                assert "anchor_passed" in result
                assert "over_removal_detected" in result
                assert "needs_review" in result

    def test_detects_over_removal(self) -> None:
        """Should detect over-removal when anchor similarity drops."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with patch("scripts.knowledge.surgeon_orchestrator.embed_keywords") as mock_embed:
            mock_embed.return_value = np.array([[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.2, 0.7, 0.1]])

            with patch(
                "scripts.knowledge.surgeon_orchestrator.compute_cosine_similarity"
            ) as mock_sim:
                # High target removal but low anchor preservation
                mock_sim.return_value = np.array(
                    [
                        [1.0, 0.9, 0.2],  # fact: high drop
                        [0.9, 1.0, 0.3],  # original -> new: low similarity
                        [0.2, 0.3, 1.0],  # new
                    ]
                )

                result = validate_removal_with_anchors(
                    "create_app is a function",
                    "The create_app function initializes the app.",
                    "Something completely different.",
                    mock_model,
                    mock_tokenizer,
                )

                assert result["target_passed"] is True
                assert result["anchor_passed"] is False
                assert result["over_removal_detected"] is True
                assert result["needs_review"] is True

    def test_handles_empty_new_span(self) -> None:
        """Should handle empty new span as deletion case."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        result = validate_removal_with_anchors(
            "create_app is a function",
            "The create_app function initializes the app.",
            "",
            mock_model,
            mock_tokenizer,
        )

        assert result["score_drop"] == 1.0
        assert result["target_passed"] is True
        assert result["over_removal_detected"] is True
        assert result["needs_review"] is True

    def test_anchor_preservation_check(self) -> None:
        """Should check anchor text preservation."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with patch("scripts.knowledge.surgeon_orchestrator.embed_keywords") as mock_embed:
            # Mock for main embeddings, then for anchor embeddings
            mock_embed.side_effect = [
                np.array([[1.0, 0.0], [0.9, 0.1], [0.7, 0.3]]),  # Main
                np.array([[0.8, 0.2], [0.7, 0.3]]),  # Anchor + new
            ]

            with patch(
                "scripts.knowledge.surgeon_orchestrator.compute_cosine_similarity"
            ) as mock_sim:
                # Good target removal, good anchor preservation
                mock_sim.side_effect = [
                    np.array([[1.0, 0.9, 0.4], [0.9, 1.0, 0.8], [0.4, 0.8, 1.0]]),  # Main
                    np.array([[1.0, 0.85], [0.85, 1.0]]),  # Anchor
                ]

                result = validate_removal_with_anchors(
                    "target fact",
                    "original text",
                    "new text",
                    mock_model,
                    mock_tokenizer,
                    anchor_texts=["anchor fact"],
                )

                assert result["target_passed"] is True
                assert result["anchor_passed"] is True


class TestOrchestateSurgeonPipeline:
    """Tests for orchestrate_surgeon_pipeline function."""

    def test_success_flow(self, tmp_path: Path) -> None:
        """Should complete full pipeline successfully."""
        mock_qwen_model = MagicMock()
        mock_qwen_tokenizer = MagicMock()

        spans = [
            SpanInput(
                span_id="span_1",
                original_text="The create_app function initializes the app.",
                target_facts=["create_app is a function"],
                anchor_facts=[],
            )
        ]

        with patch("scripts.knowledge.surgeon_orchestrator.invoke_sub_agent") as mock_invoke:
            # Mock responses for each stage
            mock_invoke.side_effect = [
                # Organizer
                {
                    "groups": [
                        {
                            "group_id": "group_1",
                            "span_ids": ["span_1"],
                            "anchors_to_keep": [],
                            "targets_to_remove": ["create_app is a function"],
                        }
                    ]
                },
                # Planner
                {"plan": {"strategy": "selective_removal"}},
                # Rewriter
                {
                    "rewrites": [
                        {
                            "span_id": "span_1",
                            "replacement_text": "The function initializes the app.",
                        }
                    ],
                    "self_check": {"target_inferable": False},
                },
            ]

            with patch(
                "scripts.knowledge.surgeon_orchestrator.validate_removal_with_anchors"
            ) as mock_validate:
                mock_validate.return_value = ValidationResult(
                    score_drop=0.5,
                    target_passed=True,
                    anchor_similarity=0.9,
                    anchor_passed=True,
                    over_removal_detected=False,
                    needs_review=False,
                )

                results = orchestrate_surgeon_pipeline(
                    spans=spans,
                    target_facts=["create_app is a function"],
                    anchor_facts=[],
                    artifact_id="test_artifact",
                    qwen_model=mock_qwen_model,
                    qwen_tokenizer=mock_qwen_tokenizer,
                    knowledge_path=tmp_path,
                )

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["span_id"] == "span_1"

    def test_needs_review_flow(self, tmp_path: Path) -> None:
        """Should invoke reviewer when validation fails."""
        mock_qwen_model = MagicMock()
        mock_qwen_tokenizer = MagicMock()

        spans = [
            SpanInput(
                span_id="span_1",
                original_text="The create_app function initializes the app.",
                target_facts=["create_app is a function"],
                anchor_facts=[],
            )
        ]

        with patch("scripts.knowledge.surgeon_orchestrator.invoke_sub_agent") as mock_invoke:
            mock_invoke.side_effect = [
                # Organizer
                {
                    "groups": [
                        {
                            "group_id": "group_1",
                            "span_ids": ["span_1"],
                            "anchors_to_keep": [],
                            "targets_to_remove": ["create_app is a function"],
                        }
                    ]
                },
                # Planner
                {"plan": {"strategy": "selective_removal"}},
                # Rewriter
                {
                    "rewrites": [
                        {
                            "span_id": "span_1",
                            "replacement_text": "The function initializes the app.",
                        }
                    ],
                    "self_check": {},
                },
                # Reviewer (called because needs_review=True)
                {"decision": "approve", "reason": "Looks good"},
            ]

            with patch(
                "scripts.knowledge.surgeon_orchestrator.validate_removal_with_anchors"
            ) as mock_validate:
                mock_validate.return_value = ValidationResult(
                    score_drop=0.1,
                    target_passed=False,  # Failed target removal
                    anchor_similarity=0.9,
                    anchor_passed=True,
                    over_removal_detected=False,
                    needs_review=True,
                )

                results = orchestrate_surgeon_pipeline(
                    spans=spans,
                    target_facts=["create_app is a function"],
                    anchor_facts=[],
                    artifact_id="test_artifact",
                    qwen_model=mock_qwen_model,
                    qwen_tokenizer=mock_qwen_tokenizer,
                    knowledge_path=tmp_path,
                )

        assert len(results) == 1
        assert results[0]["review"] is not None
        assert results[0]["review"]["decision"] == "approve"
        assert results[0]["success"] is True

    def test_reject_reverts_original(self, tmp_path: Path) -> None:
        """Should revert to original span on reviewer reject."""
        mock_qwen_model = MagicMock()
        mock_qwen_tokenizer = MagicMock()

        original_text = "The create_app function initializes the app."
        spans = [
            SpanInput(
                span_id="span_1",
                original_text=original_text,
                target_facts=["create_app is a function"],
                anchor_facts=[],
            )
        ]

        with patch("scripts.knowledge.surgeon_orchestrator.invoke_sub_agent") as mock_invoke:
            mock_invoke.side_effect = [
                # Organizer
                {"groups": [{"group_id": "g1", "span_ids": ["span_1"]}]},
                # Planner
                {"plan": {}},
                # Rewriter
                {
                    "rewrites": [{"span_id": "span_1", "replacement_text": "Bad rewrite"}],
                    "self_check": {},
                },
                # Reviewer rejects
                {"decision": "reject", "reason": "Over-removal"},
            ]

            with patch(
                "scripts.knowledge.surgeon_orchestrator.validate_removal_with_anchors"
            ) as mock_validate:
                mock_validate.return_value = ValidationResult(
                    score_drop=0.8,
                    target_passed=True,
                    anchor_similarity=0.3,
                    anchor_passed=False,
                    over_removal_detected=True,
                    needs_review=True,
                )

                results = orchestrate_surgeon_pipeline(
                    spans=spans,
                    target_facts=[],
                    anchor_facts=[],
                    artifact_id="test",
                    qwen_model=mock_qwen_model,
                    qwen_tokenizer=mock_qwen_tokenizer,
                    knowledge_path=tmp_path,
                )

        assert results[0]["success"] is False
        assert results[0]["replacement_text"] == original_text  # Reverted

    def test_fallback_on_sub_agent_failure(self, tmp_path: Path) -> None:
        """Should retain original spans when sub-agent fails."""
        mock_qwen_model = MagicMock()
        mock_qwen_tokenizer = MagicMock()

        original_text = "The create_app function initializes the app."
        spans = [
            SpanInput(
                span_id="span_1",
                original_text=original_text,
                target_facts=[],
                anchor_facts=[],
            )
        ]

        with patch("scripts.knowledge.surgeon_orchestrator.invoke_sub_agent") as mock_invoke:
            # Organizer fails
            mock_invoke.side_effect = SurgeonError("Organizer failed")

            results = orchestrate_surgeon_pipeline(
                spans=spans,
                target_facts=[],
                anchor_facts=[],
                artifact_id="test",
                qwen_model=mock_qwen_model,
                qwen_tokenizer=mock_qwen_tokenizer,
                knowledge_path=tmp_path,
            )

        assert len(results) == 1
        assert results[0]["success"] is False
        assert results[0]["replacement_text"] == original_text

    def test_no_groups_returns_unchanged(self, tmp_path: Path) -> None:
        """Should return unchanged spans when no groups formed."""
        mock_qwen_model = MagicMock()
        mock_qwen_tokenizer = MagicMock()

        spans = [
            SpanInput(
                span_id="span_1",
                original_text="Original text",
                target_facts=[],
                anchor_facts=[],
            )
        ]

        with patch("scripts.knowledge.surgeon_orchestrator.invoke_sub_agent") as mock_invoke:
            mock_invoke.return_value = {"groups": []}

            results = orchestrate_surgeon_pipeline(
                spans=spans,
                target_facts=[],
                anchor_facts=[],
                artifact_id="test",
                qwen_model=mock_qwen_model,
                qwen_tokenizer=mock_qwen_tokenizer,
                knowledge_path=tmp_path,
            )

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["replacement_text"] == "Original text"


class TestOrchestateSurgeonPipelineMock:
    """Tests for orchestrate_surgeon_pipeline_mock function."""

    def test_mock_performs_simple_removal(self) -> None:
        """Should remove sentences containing target keywords."""
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="The create_app function initializes the app. It is fast.",
                target_facts=["create_app initializes the app"],
                anchor_facts=[],
            )
        ]

        results = orchestrate_surgeon_pipeline_mock(
            spans=spans,
            target_facts=["create_app initializes the app"],
            anchor_facts=[],
            artifact_id="test",
        )

        assert len(results) == 1
        assert results[0]["success"] is True
        # Should have removed the sentence about create_app

    def test_mock_returns_rewrite_result(self) -> None:
        """Should return RewriteResult structure."""
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="Test text.",
                target_facts=[],
                anchor_facts=[],
            )
        ]

        results = orchestrate_surgeon_pipeline_mock(
            spans=spans,
            target_facts=[],
            anchor_facts=[],
            artifact_id="test",
        )

        assert "span_id" in results[0]
        assert "replacement_text" in results[0]
        assert "validation" in results[0]
        assert "success" in results[0]


class TestComputeScoreDrop:
    """Tests for compute_score_drop function."""

    def test_returns_score_drop(self) -> None:
        """Should return score drop value."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with patch("scripts.knowledge.surgeon_orchestrator.embed_keywords") as mock_embed:
            mock_embed.return_value = np.array([[1.0, 0.0], [0.8, 0.2], [0.2, 0.8]])

            with patch(
                "scripts.knowledge.surgeon_orchestrator.compute_cosine_similarity"
            ) as mock_sim:
                mock_sim.return_value = np.array(
                    [[1.0, 0.8, 0.2], [0.8, 1.0, 0.4], [0.2, 0.4, 1.0]]
                )

                result = compute_score_drop(
                    "fact",
                    "original",
                    "rewritten",
                    mock_model,
                    mock_tokenizer,
                )

                # score_drop = 0.8 - 0.2 = 0.6
                assert result == pytest.approx(0.6, rel=0.01)

    def test_handles_empty_rewritten_text(self) -> None:
        """Should return 1.0 for empty rewritten text."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        result = compute_score_drop(
            "fact",
            "original",
            "",
            mock_model,
            mock_tokenizer,
        )

        assert result == 1.0


class TestTypedDictStructures:
    """Tests for TypedDict structures."""

    def test_rewrite_result_structure(self) -> None:
        """Should accept valid RewriteResult structure."""
        result: RewriteResult = {
            "span_id": "span_1",
            "replacement_text": "New text",
            "validation": {"score_drop": 0.5},
            "review": None,
            "success": True,
        }

        assert result["span_id"] == "span_1"
        assert result["success"] is True

    def test_rewrite_result_with_failure(self) -> None:
        """Should accept RewriteResult with failure."""
        result: RewriteResult = {
            "span_id": "span_1",
            "replacement_text": "Original text",
            "validation": {"error": "Validation failed"},
            "review": None,
            "success": False,
        }

        assert result["success"] is False

    def test_group_result_structure(self) -> None:
        """Should accept valid GroupResult structure."""
        group: GroupResult = {
            "group_id": "group_1",
            "span_ids": ["span_1", "span_2"],
            "anchors_to_keep": ["anchor fact"],
            "targets_to_remove": ["target fact"],
        }

        assert group["group_id"] == "group_1"
        assert len(group["span_ids"]) == 2

    def test_validation_result_structure(self) -> None:
        """Should accept valid ValidationResult structure."""
        result: ValidationResult = {
            "score_drop": 0.75,
            "target_passed": True,
            "anchor_similarity": 0.85,
            "anchor_passed": True,
            "over_removal_detected": False,
            "needs_review": False,
        }

        assert result["score_drop"] == 0.75
        assert result["target_passed"] is True

    def test_surgeon_result_structure(self) -> None:
        """Should accept valid SurgeonResult structure."""
        result: SurgeonResult = {
            "span_id": "span_1",
            "original_text": "Original span text",
            "rewritten_text": "Rewritten span text",
            "facts_removed": ["fact1", "fact2"],
            "score_drop": 0.75,
            "status": "success",
            "failure_reason": "",
        }

        assert result["span_id"] == "span_1"
        assert result["status"] == "success"

    def test_organizer_output_structure(self) -> None:
        """Should accept valid OrganizerOutput structure."""
        output: OrganizerOutput = {
            "groups": [
                {
                    "group_id": "group_1",
                    "span_ids": ["span_1"],
                    "anchors_to_keep": [],
                    "targets_to_remove": [],
                }
            ]
        }

        assert len(output["groups"]) == 1

    def test_planner_output_structure(self) -> None:
        """Should accept valid PlannerOutput structure."""
        output: PlannerOutput = {
            "plans": [{"group_id": "group_1", "strategy": "selective_removal"}]
        }

        assert len(output["plans"]) == 1

    def test_rewriter_output_structure(self) -> None:
        """Should accept valid RewriterOutput structure."""
        output: RewriterOutput = {
            "rewritten_text": "Modified text",
            "self_check": {"target_inferable": False},
            "confidence": 0.9,
        }

        assert output["rewritten_text"] == "Modified text"

    def test_reviewer_output_structure(self) -> None:
        """Should accept valid ReviewerOutput structure."""
        output: ReviewerOutput = {
            "decision": "approve",
            "reason": "Looks good",
            "suggested_fix": None,
        }

        assert output["decision"] == "approve"

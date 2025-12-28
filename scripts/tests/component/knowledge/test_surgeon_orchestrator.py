from unittest.mock import MagicMock, patch

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
    organize_spans,
    plan_rewrites,
    review_rewrite,
    rewrite_span,
    validate_removal_qwen3,
    validate_removal_with_anchors,
)


class TestValidateRemovalQwen3:
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


class TestValidateRemovalWithAnchors:
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


class TestOrchestateSurgeonPipelineMock:
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

    def test_mock_adds_period_when_missing(self) -> None:
        """Should add period to replacement that doesn't end with one."""
        # Create a span where keyword removal leaves text without trailing period
        spans = [
            SpanInput(
                span_id="span_1",
                # After removing sentence with "create_app", remaining text won't end with .
                original_text="The create_app function is here. Another statement",
                target_facts=["create_app function"],
                anchor_facts=[],
            )
        ]

        results = orchestrate_surgeon_pipeline_mock(
            spans=spans,
            target_facts=["create_app function"],
            anchor_facts=[],
            artifact_id="test",
        )

        assert len(results) == 1
        # The mock should add a period at the end
        replacement = results[0]["replacement_text"]
        if replacement:  # If not empty
            assert replacement.endswith(".") or replacement == ""

    def test_mock_handles_empty_after_removal(self) -> None:
        """Should handle case where all content is removed."""
        # Create a span where removing keywords leaves empty content
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="The create_app is the only content.",
                target_facts=["create_app is the only content"],
                anchor_facts=[],
            )
        ]

        results = orchestrate_surgeon_pipeline_mock(
            spans=spans,
            target_facts=["create_app is the only content"],
            anchor_facts=[],
            artifact_id="test",
        )

        assert len(results) == 1
        # The result should be empty string when only period remains
        assert results[0]["replacement_text"] == "" or results[0]["replacement_text"] == "."

    def test_mock_single_period_becomes_empty(self) -> None:
        """Should convert single period to empty string."""
        # Create a span that results in just a period after processing
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="create_app.",  # Single sentence with keyword
                target_facts=["create_app"],
                anchor_facts=[],
            )
        ]

        results = orchestrate_surgeon_pipeline_mock(
            spans=spans,
            target_facts=["create_app"],
            anchor_facts=[],
            artifact_id="test",
        )

        assert len(results) == 1
        # After cleanup, should be empty string if it was just "."
        assert results[0]["replacement_text"] == ""


class TestComputeScoreDrop:
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

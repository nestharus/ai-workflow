"""Tests for scripts.tasks.workflows.review_loop module.

This test module covers:
1. Loop termination on APPROVED after 1 iteration
2. Loop termination on max_iterations (timeout)
3. Loop termination on BLOCKED (reviewer or reviser)
4. Loop termination on planner UNCHANGED (stalemate)
5. Issues tracked across iterations
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.tasks.workflows.review_loop import (
    ReviewIteration,
    ReviewLoopResult,
    run_strategy_planner_review_loop,
)


class TestReviewLoopApproval:
    """Tests for review loop terminating on APPROVED."""

    @pytest.mark.asyncio
    async def test_terminates_on_approved_after_one_iteration(self) -> None:
        """Should terminate with approved status after one iteration when reviewer approves."""
        # Mock strategy-reviewer returning APPROVED
        mock_result = MagicMock()
        mock_result.stdout = """REVIEW:
status: APPROVED
issues: []
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            return_value=mock_result,
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "approved"
        assert result.iterations == 1
        assert result.final_plan_path == "/tmp/plan.md"
        assert len(result.history) == 1
        assert result.history[0].review_status == "APPROVED"
        assert result.history[0].review_issues == []
        assert result.history[0].revision_status is None

    @pytest.mark.asyncio
    async def test_terminates_on_approved_after_multiple_iterations(self) -> None:
        """Should terminate on APPROVED after feedback and revision cycles."""
        # First iteration: FEEDBACK
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_requirement
    description: Missing integration tests
    location: Plan 1
    severity: high
    suggestion: Add integration test step
"""

        # Revision result: REVISED
        revised_result = MagicMock()
        revised_result.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
revision_summary: Added integration tests
"""

        # Second iteration: APPROVED
        approved_result = MagicMock()
        approved_result.stdout = """REVIEW:
status: APPROVED
issues: []
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, revised_result, approved_result],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "approved"
        assert result.iterations == 2
        assert len(result.history) == 2

        # First iteration - feedback and revision
        assert result.history[0].review_status == "FEEDBACK"
        assert result.history[0].review_issues == ["SR-1-001"]
        assert result.history[0].revision_status == "REVISED"
        assert result.history[0].addressed_issues == ["SR-1-001"]

        # Second iteration - approved
        assert result.history[1].review_status == "APPROVED"
        assert result.history[1].review_issues == []


class TestReviewLoopTimeout:
    """Tests for review loop terminating on max_iterations."""

    @pytest.mark.asyncio
    async def test_terminates_on_max_iterations(self) -> None:
        """Should terminate with timeout status when max iterations reached."""
        # All iterations return FEEDBACK
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_requirement
    description: Missing integration tests
    location: Plan 1
    severity: high
    suggestion: Add integration test step
"""

        revised_result = MagicMock()
        revised_result.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
revision_summary: Added tests
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, revised_result] * 5,  # 5 iterations
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "timeout"
        assert result.iterations == 5
        assert len(result.history) == 5
        # All iterations should have feedback and revision
        for iteration in result.history:
            assert iteration.review_status == "FEEDBACK"
            assert iteration.revision_status == "REVISED"

    @pytest.mark.asyncio
    async def test_terminates_on_max_iterations_with_low_limit(self) -> None:
        """Should terminate on timeout with small max_iterations value."""
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: approach_mismatch
    description: Issue
    location: Plan 1
    severity: low
    suggestion: Fix the approach
"""

        revised_result = MagicMock()
        revised_result.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
revision_summary: Made changes
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, revised_result] * 2,  # 2 iterations
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=2,
            )

        assert result.status == "timeout"
        assert result.iterations == 2


class TestReviewLoopBlocked:
    """Tests for review loop terminating on BLOCKED."""

    @pytest.mark.asyncio
    async def test_terminates_on_reviewer_blocked(self) -> None:
        """Should terminate with blocked status when reviewer returns BLOCKED."""
        mock_result = MagicMock()
        mock_result.stdout = """REVIEW:
status: BLOCKED
reason: Cannot review - strategy document is malformed
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            return_value=mock_result,
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "blocked"
        assert result.iterations == 1
        assert len(result.history) == 1
        assert result.history[0].review_status == "BLOCKED"
        assert result.history[0].revision_status is None

    @pytest.mark.asyncio
    async def test_terminates_on_reviser_blocked(self) -> None:
        """Should terminate with blocked status when reviser returns BLOCKED."""
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: feasibility_concern
    description: Requirements conflict
    location: Plan 1
    severity: high
    suggestion: Resolve the conflict
"""

        blocked_result = MagicMock()
        blocked_result.stdout = """REVISION:
status: BLOCKED
reason: Cannot proceed due to conflicting requirements
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, blocked_result],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "blocked"
        assert result.iterations == 1
        assert len(result.history) == 1
        assert result.history[0].review_status == "FEEDBACK"
        assert result.history[0].revision_status == "BLOCKED"

    @pytest.mark.asyncio
    async def test_terminates_on_blocked_after_iterations(self) -> None:
        """Should terminate on blocked after multiple successful iterations."""
        # First iteration: successful feedback/revision
        feedback1 = MagicMock()
        feedback1.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_detail
    description: Issue 1
    location: Plan 1
    severity: medium
    suggestion: Add more detail
"""

        revised1 = MagicMock()
        revised1.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
revision_summary: Fixed issue 1
"""

        # Second iteration: reviewer blocked
        blocked = MagicMock()
        blocked.stdout = """REVIEW:
status: BLOCKED
reason: Unrecoverable error detected
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback1, revised1, blocked],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "blocked"
        assert result.iterations == 2
        assert len(result.history) == 2
        assert result.history[0].review_status == "FEEDBACK"
        assert result.history[1].review_status == "BLOCKED"


class TestReviewLoopStalemate:
    """Tests for review loop terminating on UNCHANGED (stalemate)."""

    @pytest.mark.asyncio
    async def test_terminates_on_unchanged_first_iteration(self) -> None:
        """Should terminate with stalemate when reviser returns UNCHANGED on first iteration."""
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: approach_mismatch
    description: Strategy requests X but plan uses Y
    location: Plan 1
    severity: high
    suggestion: Use approach X instead of Y
"""

        unchanged_result = MagicMock()
        unchanged_result.stdout = """REVISION:
status: UNCHANGED
reason: The feedback conflicts with existing constraints
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, unchanged_result],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "stalemate"
        assert result.iterations == 1
        assert len(result.history) == 1
        assert result.history[0].review_status == "FEEDBACK"
        assert result.history[0].revision_status == "UNCHANGED"

    @pytest.mark.asyncio
    async def test_terminates_on_unchanged_after_iterations(self) -> None:
        """Should terminate on stalemate after multiple successful iterations."""
        # First iteration: successful
        feedback1 = MagicMock()
        feedback1.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_detail
    description: Issue 1
    location: Plan 1
    severity: medium
    suggestion: Add more detail
"""

        revised1 = MagicMock()
        revised1.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
revision_summary: Fixed issue 1
"""

        # Second iteration: stalemate
        feedback2 = MagicMock()
        feedback2.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-2-001
    category: approach_mismatch
    description: Disagree with this requirement
    location: Plan 2
    severity: low
    suggestion: Use different approach
"""

        unchanged = MagicMock()
        unchanged.stdout = """REVISION:
status: UNCHANGED
reason: The feedback conflicts with design decisions
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback1, revised1, feedback2, unchanged],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "stalemate"
        assert result.iterations == 2
        assert len(result.history) == 2
        assert result.history[0].revision_status == "REVISED"
        assert result.history[1].revision_status == "UNCHANGED"


class TestReviewLoopIssueTracking:
    """Tests for issue tracking across iterations."""

    @pytest.mark.asyncio
    async def test_tracks_issues_across_single_iteration(self) -> None:
        """Should track issue IDs from feedback in iteration history."""
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_requirement
    description: Missing unit tests
    location: Plan 1
    severity: high
    suggestion: Add unit tests
  - id: SR-1-002
    category: missing_detail
    description: No null checks
    location: Plan 1
    severity: medium
    suggestion: Add null checks
"""

        revised_result = MagicMock()
        revised_result.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
  - SR-1-002
revision_summary: Added unit tests and null checks
"""

        approved_result = MagicMock()
        approved_result.stdout = """REVIEW:
status: APPROVED
issues: []
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, revised_result, approved_result],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "approved"
        assert len(result.history) == 2

        # First iteration has both issues
        assert result.history[0].review_issues == ["SR-1-001", "SR-1-002"]
        assert result.history[0].addressed_issues == ["SR-1-001", "SR-1-002"]

    @pytest.mark.asyncio
    async def test_tracks_issues_across_multiple_iterations(self) -> None:
        """Should track issues across multiple feedback cycles."""
        # First iteration: 2 issues, 1 addressed
        feedback1 = MagicMock()
        feedback1.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_requirement
    description: Issue 1
    location: Plan 1
    severity: high
    suggestion: Fix issue 1
  - id: SR-1-002
    category: missing_detail
    description: Issue 2
    location: Plan 1
    severity: medium
    suggestion: Fix issue 2
"""

        revised1 = MagicMock()
        revised1.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
revision_summary: Addressed issue 1
"""

        # Second iteration: 1 new issue + 1 carried over
        feedback2 = MagicMock()
        feedback2.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-2-001
    category: approach_mismatch
    description: Issue 2 still present
    location: Plan 2
    severity: medium
    suggestion: Fix approach
  - id: SR-2-002
    category: missing_requirement
    description: New issue 3
    location: Plan 2
    severity: low
    suggestion: Add requirement
"""

        revised2 = MagicMock()
        revised2.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-2-001
  - SR-2-002
revision_summary: Addressed remaining issues
"""

        # Third iteration: approved
        approved = MagicMock()
        approved.stdout = """REVIEW:
status: APPROVED
issues: []
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback1, revised1, feedback2, revised2, approved],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "approved"
        assert result.iterations == 3
        assert len(result.history) == 3

        # First iteration
        assert result.history[0].review_issues == ["SR-1-001", "SR-1-002"]
        assert result.history[0].addressed_issues == ["SR-1-001"]

        # Second iteration
        assert result.history[1].review_issues == ["SR-2-001", "SR-2-002"]
        assert result.history[1].addressed_issues == ["SR-2-001", "SR-2-002"]

        # Third iteration
        assert result.history[2].review_issues == []
        assert result.history[2].addressed_issues == []

    @pytest.mark.asyncio
    async def test_tracks_partial_issue_resolution(self) -> None:
        """Should track when reviser only addresses some issues."""
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_requirement
    description: Issue 1
    location: Plan 1
    severity: high
    suggestion: Fix issue 1
  - id: SR-1-002
    category: missing_detail
    description: Issue 2
    location: Plan 1
    severity: medium
    suggestion: Fix issue 2
  - id: SR-1-003
    category: approach_mismatch
    description: Issue 3
    location: Plan 1
    severity: low
    suggestion: Fix issue 3
"""

        revised_result = MagicMock()
        revised_result.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
  - SR-1-003
revision_summary: Partially addressed feedback
"""

        # Next iteration gets more feedback
        feedback2 = MagicMock()
        feedback2.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-2-001
    category: missing_detail
    description: Issue 2 still missing
    location: Plan 2
    severity: high
    suggestion: Address missing detail
"""

        unchanged = MagicMock()
        unchanged.stdout = """REVISION:
status: UNCHANGED
reason: Cannot address this issue due to constraints
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, revised_result, feedback2, unchanged],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "stalemate"
        assert len(result.history) == 2

        # First iteration: 3 issues identified, 2 addressed
        assert len(result.history[0].review_issues) == 3
        assert result.history[0].addressed_issues == ["SR-1-001", "SR-1-003"]

        # Second iteration: 1 issue remains
        assert result.history[1].review_issues == ["SR-2-001"]
        assert result.history[1].addressed_issues == []

    @pytest.mark.asyncio
    async def test_tracks_empty_addressed_issues(self) -> None:
        """Should handle empty addressed_issues list correctly."""
        feedback_result = MagicMock()
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_requirement
    description: Issue 1
    location: Plan 1
    severity: high
    suggestion: Fix issue 1
"""

        # Reviser doesn't address any issues but returns REVISED
        revised_result = MagicMock()
        revised_result.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-999
revision_summary: Made unrelated changes
"""

        # Next review still has issues
        feedback2 = MagicMock()
        feedback2.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-2-001
    category: missing_requirement
    description: Issue still present
    location: Plan 2
    severity: high
    suggestion: Fix the issue
"""

        unchanged = MagicMock()
        unchanged.stdout = """REVISION:
status: UNCHANGED
reason: Cannot make further changes
"""

        with patch(
            "scripts.tasks.workflows.review_loop._run_tasks_agent",
            side_effect=[feedback_result, revised_result, feedback2, unchanged],
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        assert result.status == "stalemate"
        assert len(result.history) == 2

        # First iteration: issue identified but different issue addressed
        assert result.history[0].review_issues == ["SR-1-001"]
        assert result.history[0].addressed_issues == ["SR-1-999"]

        # Second iteration: new issue appears
        assert result.history[1].review_issues == ["SR-2-001"]
        assert result.history[1].addressed_issues == []


class TestReviewLoopFeedbackYamlFallback:
    """Tests for feedback YAML fallback when re-parsing fails."""

    @pytest.mark.asyncio
    async def test_uses_raw_output_when_yaml_extraction_fails(self) -> None:
        """Should use raw stdout when YAML re-extraction fails for feedback.

        This tests the fallback in lines 354-356 where if _parse_yaml_after_marker
        fails when extracting review YAML for the plan-reviser, the raw stdout is used.
        """
        # Create review output that will parse as FEEDBACK the first time
        # but fail the second time (simulated via mock)
        feedback_result = MagicMock()
        # Output that parses to FEEDBACK but contains corrupt YAML
        # This scenario is simulated via patching _parse_yaml_after_marker
        feedback_result.stdout = """REVIEW:
status: FEEDBACK
issues:
  - id: SR-1-001
    category: missing_detail
    description: Issue
    location: Plan 1
    severity: high
    suggestion: Fix it
"""

        # Revision result: REVISED
        revised_result = MagicMock()
        revised_result.stdout = """REVISION:
status: REVISED
addressed_issues:
  - SR-1-001
revision_summary: Fixed issue
"""

        # Approved after revision
        approved_result = MagicMock()
        approved_result.stdout = """REVIEW:
status: APPROVED
issues: []
"""

        call_count = [0]
        _original_parse = None

        def patched_parse_yaml_after_marker(output: str, marker: str) -> dict:
            """Raise ValueError on second call with REVIEW marker (simulating failure)."""
            nonlocal call_count
            call_count[0] += 1
            # First call is in _parse_review_output - let it succeed
            # Second call is in the feedback extraction block - make it fail
            if marker == "REVIEW:" and call_count[0] == 2:
                raise ValueError("Simulated YAML parse failure")
            # For all other calls, use normal import
            import yaml

            marker_index = output.find(marker)
            if marker_index == -1:
                raise ValueError(f"Marker '{marker}' not found in agent output")
            yaml_text = output[marker_index + len(marker) :].strip()
            return yaml.safe_load(yaml_text)

        with (
            patch(
                "scripts.tasks.workflows.review_loop._run_tasks_agent",
                side_effect=[feedback_result, revised_result, approved_result],
            ),
            patch(
                "scripts.tasks.workflows.review_loop._parse_yaml_after_marker",
                side_effect=patched_parse_yaml_after_marker,
            ),
        ):
            result = await run_strategy_planner_review_loop(
                strategy_path="/tmp/strategy.md",
                plan_path="/tmp/plan.md",
                max_iterations=5,
            )

        # Should still complete successfully
        assert result.status == "approved"
        assert result.iterations == 2


class TestReviewIterationDataclass:
    """Tests for ReviewIteration dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """Should create ReviewIteration with required fields."""
        iteration = ReviewIteration(
            iteration_number=1,
            review_status="FEEDBACK",
        )
        assert iteration.iteration_number == 1
        assert iteration.review_status == "FEEDBACK"
        assert iteration.review_issues == []
        assert iteration.revision_status is None
        assert iteration.addressed_issues == []
        assert iteration.revision_summary is None

    def test_creates_with_all_fields(self) -> None:
        """Should create ReviewIteration with all fields populated."""
        iteration = ReviewIteration(
            iteration_number=2,
            review_status="FEEDBACK",
            review_issues=["SR-2-001", "SR-2-002"],
            revision_status="REVISED",
            addressed_issues=["SR-2-001"],
            revision_summary="Fixed one issue",
        )
        assert iteration.iteration_number == 2
        assert iteration.review_status == "FEEDBACK"
        assert iteration.review_issues == ["SR-2-001", "SR-2-002"]
        assert iteration.revision_status == "REVISED"
        assert iteration.addressed_issues == ["SR-2-001"]
        assert iteration.revision_summary == "Fixed one issue"

    def test_creates_approved_iteration(self) -> None:
        """Should create ReviewIteration for approved status."""
        iteration = ReviewIteration(
            iteration_number=3,
            review_status="APPROVED",
            review_issues=[],
        )
        assert iteration.review_status == "APPROVED"
        assert iteration.review_issues == []
        assert iteration.revision_status is None


class TestReviewLoopResultDataclass:
    """Tests for ReviewLoopResult dataclass."""

    def test_creates_approved_result(self) -> None:
        """Should create ReviewLoopResult for approved status."""
        result = ReviewLoopResult(
            status="approved",
            iterations=1,
            final_plan_path="/tmp/plan.md",
            history=[
                ReviewIteration(
                    iteration_number=1,
                    review_status="APPROVED",
                )
            ],
        )
        assert result.status == "approved"
        assert result.iterations == 1
        assert result.final_plan_path == "/tmp/plan.md"
        assert len(result.history) == 1

    def test_creates_timeout_result(self) -> None:
        """Should create ReviewLoopResult for timeout status."""
        result = ReviewLoopResult(
            status="timeout",
            iterations=5,
            final_plan_path="/tmp/plan.md",
            history=[
                ReviewIteration(iteration_number=i, review_status="FEEDBACK") for i in range(1, 6)
            ],
        )
        assert result.status == "timeout"
        assert result.iterations == 5
        assert len(result.history) == 5

    def test_creates_blocked_result(self) -> None:
        """Should create ReviewLoopResult for blocked status."""
        result = ReviewLoopResult(
            status="blocked",
            iterations=1,
            final_plan_path="/tmp/plan.md",
            history=[
                ReviewIteration(
                    iteration_number=1,
                    review_status="BLOCKED",
                )
            ],
        )
        assert result.status == "blocked"
        assert result.iterations == 1

    def test_creates_stalemate_result(self) -> None:
        """Should create ReviewLoopResult for stalemate status."""
        result = ReviewLoopResult(
            status="stalemate",
            iterations=2,
            final_plan_path="/tmp/plan.md",
            history=[
                ReviewIteration(
                    iteration_number=1,
                    review_status="FEEDBACK",
                    revision_status="REVISED",
                ),
                ReviewIteration(
                    iteration_number=2,
                    review_status="FEEDBACK",
                    revision_status="UNCHANGED",
                ),
            ],
        )
        assert result.status == "stalemate"
        assert result.iterations == 2
        assert len(result.history) == 2

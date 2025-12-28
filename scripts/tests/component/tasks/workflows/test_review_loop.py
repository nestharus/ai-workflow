from scripts.tasks.workflows.review_loop import (
    ReviewIteration,
    ReviewLoopResult,
    run_strategy_planner_review_loop,
)


class TestReviewIterationDataclass:
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

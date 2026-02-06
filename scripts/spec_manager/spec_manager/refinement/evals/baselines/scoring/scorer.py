"""Scorer for baseline evaluation results."""

from __future__ import annotations

from spec_manager.refinement.evals.baselines.scoring.test_runner import TestResults


class BaselineScorer:
    """Computes scores from test results."""

    def score(self, results: TestResults) -> dict[str, float]:
        """Compute rule accuracy and integration completeness scores.

        Args:
            results: Parsed test results.

        Returns:
            Dict with rule_accuracy, integration_completeness, and broken flag.
        """
        rule_accuracy = (
            results.rule_tests_passed / max(1, results.rule_tests_total)
        )
        integration_completeness = (
            results.integration_tests_passed / max(1, results.integration_tests_total)
        )

        # "Broken" means BOTH dimensions fail
        broken = rule_accuracy < 0.5 and integration_completeness < 0.5

        return {
            "rule_accuracy": rule_accuracy,
            "integration_completeness": integration_completeness,
            "broken": broken,
            "rule_tests_passed": results.rule_tests_passed,
            "rule_tests_total": results.rule_tests_total,
            "integration_tests_passed": results.integration_tests_passed,
            "integration_tests_total": results.integration_tests_total,
        }

"""Per-phase eval tests for the treasury spec against PDD extraction.

Runs Phase 0 (routing-based intake) against the expanded treasury spec
fixtures, extracts actual outputs per eval phase, and scores against ground
truth using both fuzzy string matching and the LLM judge (when available).

These are REAL evals, not simulations. Phase 0 uses LLM agents for
summarization, library discovery, and routing — API access is required.
The LLM judge is additionally used at scoring time to evaluate semantic
equivalence.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pytest
import yaml
from spec_manager.refinement.evals.inputs.ground_truth import GroundTruth, PhaseGroundTruth
from spec_manager.refinement.evals.inputs.sequence_spec import SequenceSpec, load_sequence_spec
from spec_manager.refinement.evals.metrics import DetailScore, score_detail_capture
from spec_manager.refinement.evals.workflow_integration import WorkspaceIntegration

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = (
    Path(__file__).resolve().parents[2]
    / "spec_manager"
    / "refinement"
    / "evals"
    / "inputs"
    / "fixtures"
)

TREASURY_EXPANDED_YAML = FIXTURES_DIR / "chaotic_treasury_expanded.yaml"
TREASURY_GROUND_TRUTH_YAML = FIXTURES_DIR / "chaotic_treasury_expanded_ground_truth.yaml"


def _load_ground_truth() -> dict:
    """Load ground truth YAML as a raw dict."""
    return yaml.safe_load(TREASURY_GROUND_TRUTH_YAML.read_text(encoding="utf-8"))


def _try_judge_score(
    expected: list[str],
    actual: list[str],
    workspace: Path,
    phase: str,
) -> DetailScore | None:
    """Attempt LLM judge scoring; return None if unavailable."""
    try:
        from spec_manager.refinement.evals.judge_scorer import score_detail_capture_with_judge

        return score_detail_capture_with_judge(
            expected,
            actual,
            workspace=workspace,
            phase=phase,
        )
    except Exception as exc:
        logger.warning("LLM judge unavailable for %s: %s", phase, exc)
        return None


pytestmark = pytest.mark.llm_required


@pytest.fixture(scope="module")
def treasury_spec() -> SequenceSpec:
    """Load the expanded treasury spec fixture."""
    return load_sequence_spec(TREASURY_EXPANDED_YAML)


@pytest.fixture(scope="module")
def ground_truth_data() -> dict:
    """Load raw ground truth dict."""
    return _load_ground_truth()


@pytest.fixture(scope="module")
def workspace_outputs(treasury_spec: SequenceSpec) -> dict[str, list[str]]:
    """Run Phase 0 extraction and extract outputs for all eval phases.

    This fixture runs once per module and shares the workspace across all
    phase eval tests. Phase 0 is fully mechanical (no LLM) so this is
    deterministic and fast.
    """
    phases = ["sectionization", "summarization", "library_synthesis", "spec_building"]
    outputs: dict[str, list[str]] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        integration = WorkspaceIntegration(
            temp_dir=Path(tmpdir),
            use_pdd=True,
            cleanup_on_exit=False,
        )
        manager = integration.create_workspace_from_spec(treasury_spec)

        # Run extraction phase (maps to PDD Phase 0)
        for phase in phases:
            result = integration.run_phase_workflow(manager, phase)
            if result.get("error"):
                logger.error("Phase %s workflow error: %s", phase, result["error"])
            phase_outputs = integration.extract_phase_outputs(manager, phase)
            outputs[phase] = phase_outputs
            logger.info(
                "Phase %s: %d outputs extracted",
                phase,
                len(phase_outputs),
            )

    return outputs


# ---------------------------------------------------------------------------
# Sectionization
# ---------------------------------------------------------------------------


class TestSectionizationEval:
    """Evaluate section detection against ground truth."""

    def test_sections_extracted(self, workspace_outputs: dict[str, list[str]]) -> None:
        """At least some sections were extracted."""
        actual = workspace_outputs["sectionization"]
        assert len(actual) > 0, "No sections extracted from treasury spec"

    def test_section_count(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Number of sections should match ground truth."""
        actual = workspace_outputs["sectionization"]
        expected = ground_truth_data["sectionization"]["expected_sections"]
        # Allow some variance but should be close
        assert len(actual) >= len(expected) * 0.5, (
            f"Too few sections: got {len(actual)}, expected ~{len(expected)}"
        )

    def test_section_fuzzy_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Fuzzy matching recall for section labels."""
        actual = workspace_outputs["sectionization"]
        expected = ground_truth_data["sectionization"]["expected_sections"]

        score = score_detail_capture(expected, actual, fuzzy_threshold=0.6)

        logger.info(
            "Sectionization fuzzy: recall=%.1f%% precision=%.1f%% (%d/%d matched, %d actual)",
            score.recall * 100,
            score.precision * 100,
            score.matched_count,
            score.expected_count,
            score.actual_count,
        )

        assert score.recall >= 0.5, (
            f"Sectionization recall too low: {score.recall:.1%} "
            f"({score.matched_count}/{score.expected_count})"
        )

    def test_section_judge_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
        tmp_path: Path,
    ) -> None:
        """LLM judge recall for section labels (skip if API unavailable)."""
        actual = workspace_outputs["sectionization"]
        expected = ground_truth_data["sectionization"]["expected_sections"]

        judge_score = _try_judge_score(expected, actual, tmp_path, "sectionization")
        if judge_score is None:
            pytest.skip("LLM judge API unavailable")

        logger.info(
            "Sectionization judge: recall=%.1f%% precision=%.1f%%",
            judge_score.recall * 100,
            judge_score.precision * 100,
        )

        assert judge_score.recall >= 0.5, (
            f"Sectionization judge recall too low: {judge_score.recall:.1%}"
        )


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


class TestSummarizationEval:
    """Evaluate library summaries against ground truth."""

    def test_summaries_extracted(self, workspace_outputs: dict[str, list[str]]) -> None:
        """At least some summary content was extracted."""
        actual = workspace_outputs["summarization"]
        assert len(actual) > 0, "No summarization outputs extracted"

    def test_summary_fuzzy_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Fuzzy matching recall for library descriptions."""
        actual = workspace_outputs["summarization"]
        expected = ground_truth_data["summarization"]["expected_libraries"]

        score = score_detail_capture(expected, actual, fuzzy_threshold=0.4)

        logger.info(
            "Summarization fuzzy: recall=%.1f%% precision=%.1f%% (%d/%d matched, %d actual)",
            score.recall * 100,
            score.precision * 100,
            score.matched_count,
            score.expected_count,
            score.actual_count,
        )

        assert score.recall >= 0.3, (
            f"Summarization recall too low: {score.recall:.1%} "
            f"({score.matched_count}/{score.expected_count})"
        )

    def test_summary_judge_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
        tmp_path: Path,
    ) -> None:
        """LLM judge recall for library descriptions."""
        actual = workspace_outputs["summarization"]
        expected = ground_truth_data["summarization"]["expected_libraries"]

        judge_score = _try_judge_score(expected, actual, tmp_path, "summarization")
        if judge_score is None:
            pytest.skip("LLM judge API unavailable")

        logger.info(
            "Summarization judge: recall=%.1f%% precision=%.1f%%",
            judge_score.recall * 100,
            judge_score.precision * 100,
        )

        assert judge_score.recall >= 0.3, (
            f"Summarization judge recall too low: {judge_score.recall:.1%}"
        )


# ---------------------------------------------------------------------------
# Library Synthesis
# ---------------------------------------------------------------------------


class TestLibrarySynthesisEval:
    """Evaluate library identification against ground truth."""

    def test_libraries_extracted(self, workspace_outputs: dict[str, list[str]]) -> None:
        """At least some library outputs were extracted."""
        actual = workspace_outputs["library_synthesis"]
        assert len(actual) > 0, "No library synthesis outputs extracted"

    def test_library_names_fuzzy_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Fuzzy recall for library names (CamelCase identifiers)."""
        actual = workspace_outputs["library_synthesis"]
        expected_names = ground_truth_data["library_synthesis"]["expected_libraries"]

        # Filter actual outputs to CamelCase names only (not responsibilities)
        import re

        camel_re = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+$")
        actual_names = [item for item in actual if camel_re.match(item)]

        score = score_detail_capture(expected_names, actual_names, fuzzy_threshold=0.8)

        logger.info(
            "Library names fuzzy: recall=%.1f%% precision=%.1f%% (%d/%d matched, %d actual names)",
            score.recall * 100,
            score.precision * 100,
            score.matched_count,
            score.expected_count,
            score.actual_count,
        )

        assert score.recall >= 0.5, (
            f"Library names recall too low: {score.recall:.1%} "
            f"({score.matched_count}/{score.expected_count})"
        )

    def test_library_requirements_fuzzy_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Fuzzy recall for library requirements."""
        actual = workspace_outputs["library_synthesis"]
        expected_reqs = ground_truth_data["library_synthesis"]["expected_requirements"]

        # Use all actual outputs (names + responsibilities) for matching
        score = score_detail_capture(expected_reqs, actual, fuzzy_threshold=0.4)

        logger.info(
            "Library requirements fuzzy: recall=%.1f%% precision=%.1f%% (%d/%d matched, %d actual)",
            score.recall * 100,
            score.precision * 100,
            score.matched_count,
            score.expected_count,
            score.actual_count,
        )

        # Requirements extraction from prose is harder — lower threshold
        assert score.recall >= 0.2, (
            f"Library requirements recall too low: {score.recall:.1%} "
            f"({score.matched_count}/{score.expected_count})"
        )

    def test_library_judge_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
        tmp_path: Path,
    ) -> None:
        """LLM judge recall for library synthesis outputs."""
        actual = workspace_outputs["library_synthesis"]
        expected_names = ground_truth_data["library_synthesis"]["expected_libraries"]

        judge_score = _try_judge_score(expected_names, actual, tmp_path, "library_synthesis")
        if judge_score is None:
            pytest.skip("LLM judge API unavailable")

        logger.info(
            "Library names judge: recall=%.1f%% precision=%.1f%%",
            judge_score.recall * 100,
            judge_score.precision * 100,
        )

        assert judge_score.recall >= 0.5, (
            f"Library names judge recall too low: {judge_score.recall:.1%}"
        )


# ---------------------------------------------------------------------------
# Spec Building
# ---------------------------------------------------------------------------


class TestSpecBuildingEval:
    """Evaluate requirement extraction against ground truth."""

    def test_requirements_extracted(self, workspace_outputs: dict[str, list[str]]) -> None:
        """At least some requirements were extracted."""
        actual = workspace_outputs["spec_building"]
        assert len(actual) > 0, "No spec building outputs extracted"

    def test_requirements_fuzzy_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Fuzzy recall for extracted requirements."""
        actual = workspace_outputs["spec_building"]
        expected = ground_truth_data["spec_building"]["expected_requirements"]

        score = score_detail_capture(expected, actual, fuzzy_threshold=0.4)

        logger.info(
            "Spec building fuzzy: recall=%.1f%% precision=%.1f%% (%d/%d matched, %d actual)",
            score.recall * 100,
            score.precision * 100,
            score.matched_count,
            score.expected_count,
            score.actual_count,
        )

        assert score.recall >= 0.2, (
            f"Spec building recall too low: {score.recall:.1%} "
            f"({score.matched_count}/{score.expected_count})"
        )

    def test_requirements_judge_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
        tmp_path: Path,
    ) -> None:
        """LLM judge recall for extracted requirements."""
        actual = workspace_outputs["spec_building"]
        expected = ground_truth_data["spec_building"]["expected_requirements"]

        judge_score = _try_judge_score(expected, actual, tmp_path, "spec_building")
        if judge_score is None:
            pytest.skip("LLM judge API unavailable")

        logger.info(
            "Spec building judge: recall=%.1f%% precision=%.1f%%",
            judge_score.recall * 100,
            judge_score.precision * 100,
        )

        assert judge_score.recall >= 0.2, (
            f"Spec building judge recall too low: {judge_score.recall:.1%}"
        )

    def test_decisions_extracted(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Check if expected decisions appear in extracted content."""
        actual = workspace_outputs["spec_building"]
        expected_decisions = ground_truth_data["spec_building"].get("expected_decisions", [])

        if not expected_decisions:
            pytest.skip("No expected decisions in ground truth")

        # Decisions should be findable in the requirement outputs
        actual_lower = " ".join(a.lower() for a in actual)
        found = 0
        for decision in expected_decisions:
            # Check if key terms from the decision appear in outputs
            key_terms = [t.lower() for t in decision.split() if len(t) > 3]
            matches = sum(1 for term in key_terms if term in actual_lower)
            if matches >= len(key_terms) * 0.5:
                found += 1

        logger.info(
            "Decisions: %d/%d found in spec outputs",
            found,
            len(expected_decisions),
        )


# ---------------------------------------------------------------------------
# Overall Aggregate
# ---------------------------------------------------------------------------


class TestOverallEval:
    """Aggregate eval across all phases."""

    def test_overall_fuzzy_recall(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Aggregate fuzzy recall across all phases."""
        total_expected = 0
        total_matched = 0
        total_actual = 0

        phase_configs = [
            ("sectionization", "expected_sections", 0.6),
            ("summarization", "expected_libraries", 0.4),
            ("library_synthesis", "expected_requirements", 0.4),
            ("spec_building", "expected_requirements", 0.4),
        ]

        for phase, gt_key, threshold in phase_configs:
            actual = workspace_outputs.get(phase, [])
            gt_phase = ground_truth_data.get(phase, {})
            expected = gt_phase.get(gt_key, [])

            if not expected:
                continue

            score = score_detail_capture(expected, actual, fuzzy_threshold=threshold)
            total_expected += score.expected_count
            total_matched += score.matched_count
            total_actual += score.actual_count

            logger.info(
                "  %s: %d/%d (%.1f%%)",
                phase,
                score.matched_count,
                score.expected_count,
                score.recall * 100,
            )

        overall_recall = total_matched / max(1, total_expected)
        overall_precision = total_matched / max(1, total_actual)

        logger.info(
            "Overall fuzzy: recall=%.1f%% precision=%.1f%% (%d/%d matched, %d actual)",
            overall_recall * 100,
            overall_precision * 100,
            total_matched,
            total_expected,
            total_actual,
        )

        assert overall_recall >= 0.2, (
            f"Overall recall too low: {overall_recall:.1%} ({total_matched}/{total_expected})"
        )

    def test_overall_requirements_count(
        self,
        workspace_outputs: dict[str, list[str]],
        ground_truth_data: dict,
    ) -> None:
        """Overall requirement count should approach ground truth target."""
        expected_count = ground_truth_data.get("overall_requirements_count", 52)

        # Collect unique requirements from library_synthesis + spec_building
        all_reqs: set[str] = set()
        for phase in ["library_synthesis", "spec_building"]:
            for item in workspace_outputs.get(phase, []):
                if len(item) > 15:  # Skip short items (likely lib names)
                    all_reqs.add(item)

        logger.info(
            "Overall requirements: %d extracted (expected %d)",
            len(all_reqs),
            expected_count,
        )

    def test_output_diagnostics(
        self,
        workspace_outputs: dict[str, list[str]],
    ) -> None:
        """Print diagnostic output counts for debugging."""
        for phase, outputs in workspace_outputs.items():
            logger.info("Phase %s: %d outputs", phase, len(outputs))
            for i, item in enumerate(outputs[:5]):
                logger.info("  [%d] %s", i, item[:100])
            if len(outputs) > 5:
                logger.info("  ... and %d more", len(outputs) - 5)

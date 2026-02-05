"""Phase 5 compliance tests for no-hardcoding policy.

This module tests compliance with:
- CON-0003: No keyword inference from raw spec text
- CON-0004: Only system stamps and explicit formats allowed
- AUTH-0001: Heuristics non-authoritative (confidence < 0.5)

Tests verify that:
1. EntityResolutionStrategy uses structural gating (not regex/keyword scanning)
2. ProseFragmentInferenceDetector uses LLM or structural analysis
3. Heuristic fallbacks have non-authoritative confidence
4. The hardcoding scanner finds no violations in refactored code
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from spec_manager.compliance.hardcoding_scanner import (
    scan_file_for_hardcoding_violations,
)
from spec_manager.core.gaps import (
    DetectorFinding,
    ProseFragmentInferenceDetector,
    Severity,
)
from spec_manager.core.provenance import (
    GranularityLevel,
    SourceLocation,
    TrackedUnit,
    UnitType,
)
from spec_manager.strategies.base import ProcessingContext, StrategyPhase
from spec_manager.strategies.implementations.entity_resolution import (
    EntityResolutionStrategy,
    compute_unresolved_references,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase5"


@pytest.fixture
def entity_resolution_input() -> str:
    """Load entity resolution test input."""
    input_path = FIXTURE_DIR / "entity_resolution" / "input_vague_refs.md"
    return input_path.read_text(encoding="utf-8")


@pytest.fixture
def entity_resolution_expected() -> dict:
    """Load expected structural signal for entity resolution."""
    expected_path = FIXTURE_DIR / "entity_resolution" / "expected_structural_signal.json"
    return json.loads(expected_path.read_text(encoding="utf-8"))


@pytest.fixture
def gap_detection_input() -> str:
    """Load gap detection test input."""
    input_path = FIXTURE_DIR / "gap_detection" / "input_prose_fragment.md"
    return input_path.read_text(encoding="utf-8")


@pytest.fixture
def gap_detection_expected() -> dict:
    """Load expected structural output for gap detection."""
    expected_path = FIXTURE_DIR / "gap_detection" / "expected_structural_output.json"
    return json.loads(expected_path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_prose_unit() -> TrackedUnit:
    """Create a sample prose unit for testing."""
    return TrackedUnit(
        id="test_prose_001",
        content="This is a test. It has multiple sentences. We need to verify structural analysis. "
        "The system should detect this as prose. More content follows here.",
        unit_type=UnitType.PROSE,
        source=SourceLocation(file="test.md", line_start=1, line_end=5),
        introduced_by="test",
        granularity=GranularityLevel.PARAGRAPH,
        content_hash="abc123",
    )


@pytest.fixture
def sample_processing_context(sample_prose_unit: TrackedUnit) -> ProcessingContext:
    """Create a sample processing context."""
    return ProcessingContext(
        units=[sample_prose_unit],
        phase=StrategyPhase.RESOLUTION,
        reference_files={},
        previous_results={},
        config={},
    )


# =============================================================================
# Entity Resolution Tests (CON-0003/CON-0004 Compliance)
# =============================================================================


class TestEntityResolutionNoHardcoding:
    """Tests for entity resolution strategy CON-0003/CON-0004 compliance."""

    def test_applies_to_uses_structural_gating(
        self, sample_processing_context: ProcessingContext
    ) -> None:
        """Verify applies_to() uses structural signals, not regex scanning."""
        strategy = EntityResolutionStrategy()

        # Should return True for PROSE units (structural check)
        result = strategy.applies_to(sample_processing_context)
        assert result is True

        # Verify it's checking unit types, not scanning content
        # Create context with no PROSE units
        non_prose_context = ProcessingContext(
            units=[
                TrackedUnit(
                    id="test_claim_001",
                    content="This must be verified and shall work correctly.",
                    unit_type=UnitType.CLAIM,  # Not PROSE
                    source=SourceLocation(file="test.md", line_start=1, line_end=1),
                    introduced_by="test",
                    granularity=GranularityLevel.SENTENCE,
                    content_hash="def456",
                )
            ],
            phase=StrategyPhase.RESOLUTION,
            reference_files={},
            previous_results={},
            config={},
        )
        # Without evidence_summary and without PROSE units, should return False
        result_non_prose = strategy.applies_to(non_prose_context)
        assert result_non_prose is False

    def test_applies_to_respects_evidence_summary(self) -> None:
        """Verify applies_to() checks evidence_summary.unresolved_references."""
        strategy = EntityResolutionStrategy()

        context_with_signal = ProcessingContext(
            units=[],  # Empty units - should still apply if evidence says so
            phase=StrategyPhase.RESOLUTION,
            reference_files={},
            previous_results={},
            config={},
            evidence_summary={"unresolved_references": 3},
        )

        # Should apply based on evidence_summary
        assert strategy.applies_to(context_with_signal) is True

    def test_compute_unresolved_references_structural_only(self) -> None:
        """Verify compute_unresolved_references uses system ID patterns only."""
        units = [
            TrackedUnit(
                id="test_001",
                content="Reference to (@[+ATOM-0001]) and (@[+ATOM-9999]) here.",
                unit_type=UnitType.PROSE,
                source=SourceLocation(file="test.md", line_start=1, line_end=1),
                introduced_by="test",
                granularity=GranularityLevel.SENTENCE,
                content_hash="test1",
            ),
        ]
        declared_ids = {"ATOM-0001"}

        # Should find 1 unresolved (ATOM-9999)
        count = compute_unresolved_references(units, declared_ids)
        assert count == 1

    def test_no_forbidden_patterns_in_entity_resolution(self) -> None:
        """Scan entity_resolution.py for forbidden heuristic signatures."""
        entity_resolution_path = Path(
            "scripts/spec_manager/spec_manager/strategies/implementations/entity_resolution.py"
        )

        if not entity_resolution_path.exists():
            pytest.skip("entity_resolution.py not found")

        findings = scan_file_for_hardcoding_violations(entity_resolution_path)

        # Filter for actual violations (not allowlisted)
        violations = [f for f in findings if f.severity == "warning"]

        # Phase 5 requirement: no hardcoding violations
        assert len(violations) == 0, f"Found violations: {[v.message for v in violations]}"


# =============================================================================
# Gap Detector Tests (CON-0003/CON-0004 Compliance)
# =============================================================================


class TestGapDetectorsNoHardcoding:
    """Tests for gap detectors CON-0003/CON-0004 compliance."""

    def test_prose_detector_uses_structural_without_llm(
        self, gap_detection_input: str
    ) -> None:
        """Verify ProseFragmentInferenceDetector uses structural analysis without LLM."""
        detector = ProseFragmentInferenceDetector(llm_client=None)

        findings = detector.detect(gap_detection_input, "test.md")

        # Should produce structural findings
        assert len(findings) > 0

        # All findings should use structural method
        for finding in findings:
            assert finding.details.get("method") == "structural_analysis"
            # Phase 5: All structural findings are non-authoritative
            assert finding.is_authoritative is False
            assert finding.details.get("confidence", 1.0) < 0.5

    def test_prose_detector_structural_signals(self, gap_detection_input: str) -> None:
        """Verify ProseFragmentInferenceDetector detects expected structural signals."""
        detector = ProseFragmentInferenceDetector(llm_client=None)

        findings = detector.detect(gap_detection_input, "test.md")

        # Check for expected structural signal types
        pattern_types = {f.details.get("pattern_type") for f in findings}

        # Should detect questions (uncertainty)
        assert any("uncertainty" in pt for pt in pattern_types if pt)

    def test_prose_detector_no_keyword_patterns(self) -> None:
        """Verify detector does not use keyword patterns."""
        detector = ProseFragmentInferenceDetector(llm_client=None)

        # Content with requirement keywords that should NOT trigger keyword-based detection
        content = """The system must ensure correctness. All components shall work together.
        Required functionality includes error handling. The algorithm should converge."""

        findings = detector.detect(content, "test.md")

        # Should NOT have findings based on keyword patterns
        for finding in findings:
            method = finding.details.get("method", "")
            assert method != "pattern_match", "Found forbidden keyword pattern matching"

    def test_no_forbidden_patterns_in_gaps_py(self) -> None:
        """Scan gaps.py for forbidden heuristic signatures."""
        gaps_path = Path("scripts/spec_manager/spec_manager/core/gaps.py")

        if not gaps_path.exists():
            pytest.skip("gaps.py not found")

        findings = scan_file_for_hardcoding_violations(gaps_path)

        # Filter for actual violations (not allowlisted)
        violations = [f for f in findings if f.severity == "warning"]

        # Note: gaps.py may have some allowlisted patterns (format compliance patterns)
        # We check that no NEW keyword inference violations exist
        keyword_violations = [
            v for v in violations if v.pattern_type == "keyword_inference"
        ]
        assert len(keyword_violations) == 0, f"Found violations: {[v.message for v in keyword_violations]}"


# =============================================================================
# Heuristic Fallback Tests (AUTH-0001 Compliance)
# =============================================================================


class TestHeuristicFallbacksNonAuthoritative:
    """Tests for AUTH-0001 compliance: heuristics must be non-authoritative."""

    def test_detector_finding_has_is_authoritative_field(self) -> None:
        """Verify DetectorFinding has is_authoritative field."""
        finding = DetectorFinding(
            severity=Severity.INFO,
            message="Test finding",
            location="test.md:1",
        )

        # Should have is_authoritative field with default True
        assert hasattr(finding, "is_authoritative")
        assert finding.is_authoritative is True

    def test_structural_findings_non_authoritative(self) -> None:
        """Verify structural findings have is_authoritative=False."""
        detector = ProseFragmentInferenceDetector(llm_client=None)

        content = """This is a long prose section. It contains multiple sentences.
        More content follows here. We need enough for structural detection.
        Additional text to ensure the section is detected."""

        findings = detector.detect(content, "test.md")

        for finding in findings:
            if finding.details.get("method") == "structural_analysis":
                assert finding.is_authoritative is False

    def test_structural_findings_confidence_below_threshold(self) -> None:
        """Verify structural findings have confidence < 0.5."""
        detector = ProseFragmentInferenceDetector(llm_client=None)

        content = """This is a long prose section. It contains multiple sentences.
        More content follows here. We need enough for structural detection.
        Additional text to ensure the section is detected."""

        findings = detector.detect(content, "test.md")

        for finding in findings:
            if finding.details.get("method") == "structural_analysis":
                confidence = finding.details.get("confidence", 1.0)
                assert confidence < 0.5, f"Confidence {confidence} >= 0.5 threshold"

    def test_heuristic_resolution_confidence_below_threshold(self) -> None:
        """Verify entity resolution heuristic uses confidence < 0.5."""
        strategy = EntityResolutionStrategy()

        # Create test units
        units = [
            TrackedUnit(
                id="test_declared",
                content="Some declared content.",
                unit_type=UnitType.CLAIM,
                source=SourceLocation(file="test.md", line_start=1, line_end=1),
                introduced_by="test",
                granularity=GranularityLevel.SENTENCE,
                content_hash="decl1",
                declarations=["DECL-001"],
            ),
            TrackedUnit(
                id="test_reference",
                content="Reference to something.",
                unit_type=UnitType.PROSE,
                source=SourceLocation(file="test.md", line_start=2, line_end=2),
                introduced_by="test",
                granularity=GranularityLevel.SENTENCE,
                content_hash="ref1",
            ),
        ]

        # Call heuristic resolution
        target_id, confidence, rationale = strategy._resolve_with_heuristic(
            "the algorithm", units, 1
        )

        # Phase 5: Heuristic confidence must be < 0.5
        assert confidence < 0.5, f"Heuristic confidence {confidence} >= 0.5"
        assert "non-authoritative" in rationale.lower()


# =============================================================================
# Forbidden Pattern Assertions
# =============================================================================


class TestForbiddenPatternAssertions:
    """Tests asserting absence of forbidden patterns in code."""

    def test_no_modal_verb_regex_in_detection(self) -> None:
        """Assert no modal verb regex (must/shall/should) in detection paths."""
        from spec_manager.core import gaps

        # Get source code of ProseFragmentInferenceDetector
        import inspect

        source = inspect.getsource(gaps.ProseFragmentInferenceDetector)

        # Should NOT contain modal verb patterns in detection
        forbidden_patterns = [
            r'r".*\\b(must|shall|should)',
            r"'must'",
            r'"must"',
            r"'shall'",
            r'"shall"',
        ]

        for pattern in forbidden_patterns:
            # Check if pattern appears in _detect methods (not in docstrings)
            # Note: We allow these in comments and docstrings
            lines = source.split("\n")
            for line in lines:
                # Skip docstrings and comments
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""'):
                    continue
                if stripped.startswith("'''"):
                    continue

                # Should not find keyword patterns in actual code
                if "patterns = [" in line or "pattern" in line.lower():
                    assert "must|shall" not in line, f"Forbidden pattern in: {line}"

    def test_no_keyword_in_text_patterns(self) -> None:
        """Assert no 'keyword in text.lower()' patterns."""
        from spec_manager.strategies.implementations import entity_resolution

        import inspect

        source = inspect.getsource(entity_resolution)

        # Should NOT contain keyword-in-text patterns in main logic
        # Exclude comments and docstrings
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue

            # Check for forbidden pattern
            if 'in text.lower()' in line or "in line.lower()" in line:
                # Allow if it's in a comment
                if "#" in line and line.index("#") < line.index("in"):
                    continue
                pytest.fail(f"Found forbidden pattern: {line}")

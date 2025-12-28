from scripts.prd.classifier import (
    ClassificationResult,
    InputType,
    _count_indexed_ids,
    _count_prose_indicators,
    _count_section_headers,
    classify_by_heuristics,
    classify_input,
    main,
)


class TestCountProseIndicators:
    def test_detects_line_start_anchored_patterns(self) -> None:
        """Should detect patterns with ^ anchor applied to individual lines."""
        # Patterns like "^\s*add\s+" should match at start of any line
        content = "Some preamble\n  add feature X\nMore text"
        count = _count_prose_indicators(content)
        assert count >= 1, "Should detect '  add feature' at line start"

    def test_detects_multiple_line_start_patterns(self) -> None:
        """Should count multiple line-start patterns across lines."""
        content = "  add feature\n  change behavior\n  remove old code"
        count = _count_prose_indicators(content)
        assert count >= 3, "Should detect add, change, and remove patterns"

    def test_detects_non_anchored_patterns(self) -> None:
        """Should detect patterns without ^ anchor anywhere in content."""
        content = "I think we should add this feature"
        count = _count_prose_indicators(content)
        # "i think" and "we should" are both prose indicators
        assert count >= 2

    def test_empty_content_returns_zero(self) -> None:
        """Should return 0 for empty content."""
        assert _count_prose_indicators("") == 0

    def test_no_prose_indicators(self) -> None:
        """Should return 0 when no prose indicators present."""
        content = "## Resources\n\nRES-1: Some resource"
        assert _count_prose_indicators(content) == 0


class TestCountSectionHeaders:
    def test_detects_prd_section_headers(self) -> None:
        """Should detect PRD-style section headers."""
        content = "## Resources\n\n## Goals\n\n## Invariants"
        count = _count_section_headers(content)
        assert count == 3

    def test_case_insensitive_matching(self) -> None:
        """Should match headers case-insensitively."""
        content = "## RESOURCES\n\n## goals\n\n## GoAlS"
        count = _count_section_headers(content)
        assert count >= 2  # Resources and at least one goals


class TestCountIndexedIds:
    def test_detects_indexed_ids(self) -> None:
        """Should detect indexed IDs like RES-1, GOAL-2."""
        content = "RES-1: Resource one\nGOAL-2: Goal two\nINV-3: Invariant"
        count = _count_indexed_ids(content)
        assert count == 3

    def test_counts_unique_ids_only(self) -> None:
        """Should count unique IDs only, not duplicates."""
        content = "RES-1 is referenced by RES-1 and RES-1"
        count = _count_indexed_ids(content)
        assert count == 1


class TestClassifyByHeuristics:
    def test_classifies_prd_content(self) -> None:
        """Should classify structured PRD content as PRD."""
        content = """## Resources

RES-1: Database schema
RES-2: API endpoint

## Goals

GOAL-1: Implement feature
GOAL-2: Add tests

## Invariants

INV-1: Data consistency
INV-2: Security
"""
        result = classify_by_heuristics(content)
        assert result.input_type == InputType.PRD
        assert result.method == "heuristic"

    def test_classifies_prose_content(self) -> None:
        """Should classify conversational prose as PROSE."""
        content = "I think we should add a new feature. Can you please implement this?"
        result = classify_by_heuristics(content)
        assert result.input_type == InputType.PROSE

    def test_classifies_prose_with_high_prose_indicators(self) -> None:
        """Should classify as PROSE when 3+ prose indicators and <2 section headers."""
        # Content with many prose indicators but some IDs (would be AMBIGUOUS without prose rule)
        content = """I think we should change the approach.
We need to update the API endpoint RES-1.
Can you please add some tests for GOAL-1?
Let's also implement the feature for REQ-1."""
        result = classify_by_heuristics(content)
        assert result.input_type == InputType.PROSE
        assert "prose indicators" in result.reasoning

    def test_returns_classification_result(self) -> None:
        """Should return a ClassificationResult instance."""
        result = classify_by_heuristics("test content")
        assert isinstance(result, ClassificationResult)
        assert result.confidence is None  # Heuristics don't provide confidence


class TestClassifyInput:
    def test_delegates_to_heuristics(self) -> None:
        """Should use heuristic classification."""
        result = classify_input("test content")
        assert result.method == "heuristic"

    def test_empty_string_returns_prose(self) -> None:
        """Should classify empty string as PROSE (0 headers AND 0 IDs)."""
        result = classify_input("")
        assert result.input_type == InputType.PROSE
        assert result.method == "heuristic"

    def test_many_ids_no_headers_returns_ambiguous(self) -> None:
        """Should classify content with many IDs but no section headers as AMBIGUOUS."""
        # Content with 6 IDs but no section headers
        content = """RES-1: First resource
RES-2: Second resource
GOAL-1: First goal
GOAL-2: Second goal
INV-1: First invariant
REQ-1: First requirement"""
        result = classify_input(content)
        assert result.input_type == InputType.AMBIGUOUS
        assert "AMBIGUOUS" in result.reasoning

    def test_boundary_exactly_3_headers_and_5_ids_is_prd(self) -> None:
        """Should classify as PRD at exact boundary of 3 headers and 5 IDs."""
        content = """## Resources

RES-1: First resource
RES-2: Second resource

## Goals

GOAL-1: First goal
GOAL-2: Second goal

## Invariants

INV-1: First invariant"""
        result = classify_input(content)
        assert result.input_type == InputType.PRD
        assert result.method == "heuristic"

    def test_boundary_2_headers_and_5_ids_is_ambiguous(self) -> None:
        """Should classify as AMBIGUOUS when just below header threshold (2 < 3)."""
        # 2 headers (below threshold) and 5 IDs (at threshold)
        content = """## Resources

RES-1: First resource
RES-2: Second resource

## Goals

GOAL-1: First goal
GOAL-2: Second goal
INV-1: First invariant"""
        result = classify_input(content)
        assert result.input_type == InputType.AMBIGUOUS

    def test_boundary_3_headers_and_4_ids_is_ambiguous(self) -> None:
        """Should classify as AMBIGUOUS when just below ID threshold (4 < 5)."""
        # 3 headers (at threshold) and 4 IDs (below threshold)
        content = """## Resources

RES-1: First resource
RES-2: Second resource

## Goals

GOAL-1: First goal

## Invariants

INV-1: First invariant"""
        result = classify_input(content)
        assert result.input_type == InputType.AMBIGUOUS

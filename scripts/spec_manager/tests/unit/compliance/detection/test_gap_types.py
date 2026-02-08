"""Tests for new GapType variants and _infer_gap_type mapping."""

from __future__ import annotations

from spec_manager.core.gap import (
    Gap,
    GapEvidence,
    GapType,
    _infer_gap_type,
)
from spec_manager.core.gaps import Severity


class TestNewGapTypeMembers:
    """Verify new GapType members exist and serialize correctly."""

    def test_unimplemented_comment_exists(self) -> None:
        assert GapType.unimplemented_comment.value == "unimplemented_comment"

    def test_stub_function_exists(self) -> None:
        assert GapType.stub_function.value == "stub_function"

    def test_runtime_not_implemented_exists(self) -> None:
        assert GapType.runtime_not_implemented.value == "runtime_not_implemented"

    def test_disconnected_subgraph_exists(self) -> None:
        assert GapType.disconnected_subgraph.value == "disconnected_subgraph"

    def test_uncovered_path_exists(self) -> None:
        assert GapType.uncovered_path.value == "uncovered_path"

    def test_gap_type_round_trip(self) -> None:
        for gap_type in [
            GapType.unimplemented_comment,
            GapType.stub_function,
            GapType.runtime_not_implemented,
            GapType.disconnected_subgraph,
            GapType.uncovered_path,
        ]:
            serialized = gap_type.value
            deserialized = GapType(serialized)
            assert deserialized == gap_type

    def test_gap_to_dict_with_new_types(self) -> None:
        evidence = GapEvidence(
            invariant_family="executable_comment",
            description="Test comment gap",
        )
        gap = Gap(
            id="GAP-test",
            gap_type=GapType.unimplemented_comment,
            severity=Severity.WARNING,
            source=["test.py"],
            derived_artifact_target="test",
            description="Test",
            evidence=[evidence],
        )
        d = gap.to_dict()
        assert d["gap_type"] == "unimplemented_comment"
        restored = Gap.from_dict(d)
        assert restored.gap_type == GapType.unimplemented_comment

    def test_gap_from_dict_all_new_types(self) -> None:
        for gap_type in [
            GapType.unimplemented_comment,
            GapType.stub_function,
            GapType.runtime_not_implemented,
            GapType.disconnected_subgraph,
            GapType.uncovered_path,
        ]:
            data = {
                "id": "GAP-test",
                "gap_type": gap_type.value,
                "severity": "warning",
                "source": [],
                "derived_artifact_target": "",
                "description": "test",
                "evidence": [],
            }
            gap = Gap.from_dict(data)
            assert gap.gap_type == gap_type


class TestInferGapType:
    """Verify _infer_gap_type returns new types for matching invariant families."""

    def test_executable_comment_mapping(self) -> None:
        evidence = [GapEvidence(invariant_family="executable_comment", description="test")]
        result = _infer_gap_type(evidence)
        assert result == GapType.unimplemented_comment

    def test_executable_stub_mapping(self) -> None:
        evidence = [GapEvidence(invariant_family="executable_stub", description="test")]
        result = _infer_gap_type(evidence)
        assert result == GapType.stub_function

    def test_executable_runtime_mapping(self) -> None:
        evidence = [GapEvidence(invariant_family="executable_runtime", description="test")]
        result = _infer_gap_type(evidence)
        assert result == GapType.runtime_not_implemented

    def test_executable_adjacency_mapping(self) -> None:
        evidence = [GapEvidence(invariant_family="executable_adjacency", description="test")]
        result = _infer_gap_type(evidence)
        assert result == GapType.disconnected_subgraph

    def test_executable_coverage_mapping(self) -> None:
        evidence = [GapEvidence(invariant_family="executable_coverage", description="test")]
        result = _infer_gap_type(evidence)
        assert result == GapType.uncovered_path

    def test_existing_mappings_preserved(self) -> None:
        evidence = [GapEvidence(invariant_family="coverage", description="test")]
        result = _infer_gap_type(evidence)
        assert result == GapType.coverage_failure

        evidence = [GapEvidence(invariant_family="contradiction", description="test")]
        result = _infer_gap_type(evidence)
        assert result == GapType.contradiction

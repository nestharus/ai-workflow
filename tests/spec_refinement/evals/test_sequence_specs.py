"""Tests for sequence spec loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.refinement.evals.inputs.ground_truth import GroundTruth, PhaseGroundTruth
from spec_manager.refinement.evals.inputs.sequence_spec import (
    SequenceRule,
    SequenceSpec,
    load_sequence_spec,
    load_sequence_specs_from_dir,
)

FIXTURES_DIR = Path("scripts/spec_manager/spec_manager/refinement/evals/inputs/fixtures")


class TestSequenceRule:
    """Tests for SequenceRule dataclass."""

    def test_create_base_rule(self) -> None:
        """Test creating a base case rule."""
        rule = SequenceRule(
            rule_id="RULE-001",
            rule_type="base",
            description="Base case for n=0",
            formal_expression="f(0) = 0",
        )

        assert rule.rule_id == "RULE-001"
        assert rule.rule_type == "base"
        assert rule.dependencies == []
        assert rule.examples == []

    def test_create_recurrence_rule_with_deps(self) -> None:
        """Test creating a recurrence rule with dependencies."""
        rule = SequenceRule(
            rule_id="RULE-003",
            rule_type="recurrence",
            description="Recurrence relation",
            formal_expression="f(n) = f(n-1) + f(n-2)",
            dependencies=["RULE-001", "RULE-002"],
            examples=[(5, 5), (10, 55)],
        )

        assert rule.rule_type == "recurrence"
        assert len(rule.dependencies) == 2
        assert rule.examples == [(5, 5), (10, 55)]


class TestPhaseGroundTruth:
    """Tests for PhaseGroundTruth dataclass."""

    def test_create_empty_ground_truth(self) -> None:
        """Test creating empty ground truth."""
        gt = PhaseGroundTruth()

        assert gt.expected_sections == []
        assert gt.expected_libraries == []
        assert gt.expected_requirements == []

    def test_create_populated_ground_truth(self) -> None:
        """Test creating populated ground truth."""
        gt = PhaseGroundTruth(
            expected_sections=["Overview", "Base Cases"],
            expected_libraries=["fibonacci_lib"],
            expected_requirements=["Must compute F(n) in O(n) time"],
        )

        assert len(gt.expected_sections) == 2
        assert "fibonacci_lib" in gt.expected_libraries


class TestGroundTruth:
    """Tests for GroundTruth dataclass."""

    def test_get_phase_ground_truth(self) -> None:
        """Test getting phase-specific ground truth."""
        gt = GroundTruth(
            sectionization=PhaseGroundTruth(
                expected_sections=["Section A"],
            ),
            library_synthesis=PhaseGroundTruth(
                expected_libraries=["lib_a"],
            ),
        )

        section_gt = gt.get_phase_ground_truth("sectionization")
        assert section_gt is not None
        assert section_gt.expected_sections == ["Section A"]

        synth_gt = gt.get_phase_ground_truth("library_synthesis")
        assert synth_gt is not None
        assert synth_gt.expected_libraries == ["lib_a"]

    def test_get_nonexistent_phase(self) -> None:
        """Test getting ground truth for nonexistent phase."""
        gt = GroundTruth()
        result = gt.get_phase_ground_truth("nonexistent")
        assert result is None


class TestSequenceSpec:
    """Tests for SequenceSpec dataclass."""

    def test_create_minimal_spec(self) -> None:
        """Test creating a minimal sequence spec."""
        from spec_manager.refinement.evals.inputs.sequence_spec import SequenceSpec as SeqSpec

        spec = SeqSpec(
            spec_id="test_spec",
            title="Test Spec",
            description="A test specification",
            sections={"intro": "Introduction text"},
            rules=[
                SequenceRule(
                    rule_id="R1",
                    rule_type="base",
                    description="Base",
                    formal_expression="f(0) = 0",
                )
            ],
            ground_truth=GroundTruth(),
        )

        assert spec.spec_id == "test_spec"
        assert len(spec.rules) == 1
        assert spec.complexity_score == 5  # Default

    def test_create_complex_spec(self) -> None:
        """Test creating a complex sequence spec."""
        from spec_manager.refinement.evals.inputs.sequence_spec import SequenceSpec as SeqSpec

        rules = [
            SequenceRule(
                rule_id=f"R{i}",
                rule_type="recurrence",
                description=f"Rule {i}",
                formal_expression=f"f(n) = f(n-{i})",
            )
            for i in range(1, 6)
        ]

        spec = SeqSpec(
            spec_id="complex",
            title="Complex Spec",
            description="Complex specification",
            sections={"a": "A", "b": "B"},
            rules=rules,
            ground_truth=GroundTruth(),
            complexity_score=8,
            tags=["complex", "multi-rule"],
        )

        assert spec.complexity_score == 8
        assert len(spec.tags) == 2


class TestLoadSequenceSpec:
    """Tests for loading sequence specs from files."""

    def test_load_fibonacci_spec(self) -> None:
        """Test loading fibonacci spec fixture."""
        path = FIXTURES_DIR / "fibonacci_modular.yaml"
        if not path.exists():
            pytest.skip("Fixture file not found")

        spec = load_sequence_spec(path)

        assert spec.spec_id == "fibonacci_modular"
        assert "fibonacci" in spec.title.lower()
        assert len(spec.rules) >= 3
        assert spec.complexity_score > 0

    def test_load_collatz_spec(self) -> None:
        """Test loading collatz spec fixture."""
        path = FIXTURES_DIR / "collatz_extended.yaml"
        if not path.exists():
            pytest.skip("Fixture file not found")

        spec = load_sequence_spec(path)

        assert spec.spec_id == "collatz_extended"
        assert len(spec.rules) >= 5

    def test_load_nonexistent_file(self) -> None:
        """Test loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_sequence_spec(Path("nonexistent.yaml"))


class TestLoadSequenceSpecsFromDir:
    """Tests for loading multiple specs from directory."""

    def test_load_all_fixtures(self) -> None:
        """Test loading all fixture specs."""
        if not FIXTURES_DIR.exists():
            pytest.skip("Fixtures directory not found")

        specs = load_sequence_specs_from_dir(FIXTURES_DIR)

        assert len(specs) >= 1
        assert all(isinstance(s, SequenceSpec) for s in specs)

    def test_load_from_empty_dir(self, tmp_path: Path) -> None:
        """Test loading from empty directory."""
        specs = load_sequence_specs_from_dir(tmp_path)
        assert specs == []

    def test_specs_have_unique_ids(self) -> None:
        """Test that all loaded specs have unique IDs."""
        if not FIXTURES_DIR.exists():
            pytest.skip("Fixtures directory not found")

        specs = load_sequence_specs_from_dir(FIXTURES_DIR)
        ids = [s.spec_id for s in specs]

        assert len(ids) == len(set(ids)), "Duplicate spec IDs found"

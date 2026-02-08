"""Tests for labyrinth generator."""

from pathlib import Path

import pytest
from spec_manager.labyrinth.generator.labyrinth_builder import LabyrinthBuilder
from spec_manager.labyrinth.generator.level_config import get_level_config


class TestLevelConfig:
    """Tests for level configuration."""

    def test_valid_levels(self) -> None:
        """Verify all valid level configurations can be retrieved."""
        for level in range(1, 5):
            config = get_level_config(level)
            assert config.level == level
            assert config.num_rules > 0

    def test_invalid_level(self) -> None:
        """Verify invalid levels raise ValueError."""
        with pytest.raises(ValueError):
            get_level_config(0)
        with pytest.raises(ValueError):
            get_level_config(-1)

    def test_4x_scaling(self) -> None:
        """Verify each level scales by 4x from the previous level."""
        c1 = get_level_config(1)
        c2 = get_level_config(2)
        assert c2.num_rules == c1.num_rules * 4
        assert c2.num_integration_points == c1.num_integration_points * 4
        assert c2.num_side_effect_chains == c1.num_side_effect_chains * 4


class TestLabyrinthBuilder:
    """Tests for labyrinth builder."""

    def test_build_level_1(self) -> None:
        """Verify level 1 labyrinth builds correctly with expected attributes."""
        builder = LabyrinthBuilder()
        instance = builder.build(level=1, seed=42)

        assert instance.level == 1
        assert instance.seed == 42
        assert len(instance.rules) == 16
        assert len(instance.integration_points) == 4
        assert len(instance.chains) == 2
        assert instance.dense_spec != ""
        assert instance.sparse_spec != ""
        assert instance.test_source != ""
        assert len(instance.steering_script.get("ambiguities", [])) > 0

    def test_reproducibility(self) -> None:
        """Verify building with same seed produces identical results."""
        builder = LabyrinthBuilder()
        i1 = builder.build(level=1, seed=42)
        i2 = builder.build(level=1, seed=42)

        assert i1.dense_spec == i2.dense_spec
        assert i1.sparse_spec == i2.sparse_spec
        assert len(i1.rules) == len(i2.rules)
        for r1, r2 in zip(i1.rules, i2.rules, strict=True):
            assert r1.rule_id == r2.rule_id
            assert r1.name == r2.name

    def test_different_seeds(self) -> None:
        """Verify different seeds produce different rule sets."""
        builder = LabyrinthBuilder()
        i1 = builder.build(level=1, seed=42)
        i2 = builder.build(level=1, seed=99)

        # Different seeds should produce different rules
        names1 = {r.name for r in i1.rules}
        names2 = {r.name for r in i2.rules}
        assert names1 != names2

    def test_build_and_save(self, tmp_path: Path) -> None:
        """Verify labyrinth saves all required artifacts to disk."""
        builder = LabyrinthBuilder()
        instance = builder.build_and_save(level=1, seed=42, output_dir=tmp_path / "labyrinth")

        assert instance.output_dir is not None
        assert (instance.output_dir / "dense_spec.md").exists()
        assert (instance.output_dir / "sparse_spec.md").exists()
        assert (instance.output_dir / "steering.json").exists()
        assert (instance.output_dir / "ground_truth.json").exists()
        assert (instance.output_dir / "rule_manifest.json").exists()
        assert (instance.output_dir / "tests" / "conftest.py").exists()

    def test_ground_truth_has_test_cases(self) -> None:
        """Verify ground truth contains rule and chain test cases."""
        builder = LabyrinthBuilder()
        instance = builder.build(level=1, seed=42)

        gt = instance.ground_truth
        assert "rule_tests" in gt
        assert "chain_tests" in gt
        assert len(gt["rule_tests"]) > 0

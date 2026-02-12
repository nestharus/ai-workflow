"""Tests for planner.constraints.impact — deterministic impact classification."""

from __future__ import annotations

import pytest

from spec_manager.planner.constraints.impact import classify_impact
from spec_manager.planner.constraints.types import ImpactClassification


class TestClassifyImpactLow:
    def test_all_defaults(self):
        result = classify_impact(layer="L1")
        assert result.impact == "LOW"
        assert result.blast_radius == "LOCAL"
        assert result.reversibility == "EASY"
        assert "default_low" in result.triggers

    def test_l1_no_flags(self):
        result = classify_impact(layer="L1", gap_kinds=[], touched_files_count=1)
        assert result.impact == "LOW"

    def test_l3_few_files(self):
        result = classify_impact(layer="L3", touched_files_count=2)
        assert result.impact == "LOW"

    def test_low_blast_radius_is_local(self):
        result = classify_impact(layer="L1")
        assert result.blast_radius == "LOCAL"

    def test_low_reversibility_is_easy(self):
        result = classify_impact(layer="L1")
        assert result.reversibility == "EASY"


class TestClassifyImpactMedium:
    def test_layer_l2(self):
        result = classify_impact(layer="L2")
        assert result.impact == "MEDIUM"
        assert "layer_L2" in result.triggers

    def test_many_touched_files(self):
        result = classify_impact(layer="L1", touched_files_count=5)
        assert result.impact == "MEDIUM"
        assert any("touched_files" in t for t in result.triggers)

    def test_gap_topology(self):
        result = classify_impact(layer="L1", gap_kinds=["topology"])
        assert result.impact == "MEDIUM"
        assert "gap_topology" in result.triggers

    def test_gap_boundary(self):
        result = classify_impact(layer="L1", gap_kinds=["boundary"])
        assert result.impact == "MEDIUM"
        assert "gap_boundary" in result.triggers

    def test_medium_blast_radius_is_slice(self):
        result = classify_impact(layer="L2")
        assert result.blast_radius == "SLICE"

    def test_medium_reversibility_is_medium(self):
        result = classify_impact(layer="L2")
        assert result.reversibility == "MEDIUM"

    def test_case_insensitive_gap_kinds(self):
        result = classify_impact(layer="L1", gap_kinds=["Topology"])
        assert result.impact == "MEDIUM"

    def test_touched_files_exactly_3_is_low(self):
        result = classify_impact(layer="L1", touched_files_count=3)
        assert result.impact == "LOW"

    def test_touched_files_4_is_medium(self):
        result = classify_impact(layer="L1", touched_files_count=4)
        assert result.impact == "MEDIUM"


class TestClassifyImpactHigh:
    def test_cross_library_contract(self):
        result = classify_impact(layer="L1", cross_library_contract=True)
        assert result.impact == "HIGH"
        assert "cross_library_contract" in result.triggers

    def test_introduces_infra(self):
        result = classify_impact(layer="L1", introduces_infra=True)
        assert result.impact == "HIGH"
        assert "introduces_infra" in result.triggers

    def test_introduces_external_dep(self):
        result = classify_impact(layer="L1", introduces_external_dep=True)
        assert result.impact == "HIGH"
        assert "introduces_external_dep" in result.triggers

    def test_high_overrides_medium_signals(self):
        result = classify_impact(
            layer="L2",
            touched_files_count=10,
            cross_library_contract=True,
        )
        assert result.impact == "HIGH"

    def test_cross_library_blast_radius_is_system(self):
        result = classify_impact(layer="L1", cross_library_contract=True)
        assert result.blast_radius == "SYSTEM"

    def test_infra_blast_radius_is_cross_slice(self):
        result = classify_impact(layer="L1", introduces_infra=True)
        assert result.blast_radius == "CROSS_SLICE"

    def test_infra_reversibility_is_hard(self):
        result = classify_impact(layer="L1", introduces_infra=True)
        assert result.reversibility == "HARD"

    def test_external_dep_reversibility_is_hard(self):
        result = classify_impact(layer="L1", introduces_external_dep=True)
        assert result.reversibility == "HARD"

    def test_cross_library_reversibility_is_medium(self):
        result = classify_impact(layer="L1", cross_library_contract=True)
        # cross_library alone (without infra/ext dep) is MEDIUM reversibility
        assert result.reversibility == "MEDIUM"

    def test_multiple_high_triggers(self):
        result = classify_impact(
            layer="L1",
            introduces_infra=True,
            introduces_external_dep=True,
            cross_library_contract=True,
        )
        assert result.impact == "HIGH"
        assert len(result.triggers) >= 3


class TestClassifyImpactReturnType:
    def test_returns_impact_classification(self):
        result = classify_impact(layer="L1")
        assert isinstance(result, ImpactClassification)

    def test_result_has_triggers(self):
        result = classify_impact(layer="L1")
        assert isinstance(result.triggers, list)
        assert len(result.triggers) > 0

    def test_deterministic(self):
        kwargs = dict(
            layer="L2",
            gap_kinds=["topology"],
            touched_files_count=5,
            introduces_external_dep=False,
        )
        r1 = classify_impact(**kwargs)
        r2 = classify_impact(**kwargs)
        assert r1 == r2

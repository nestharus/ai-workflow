"""Tests for planner.constraints.authority — decision authority policy."""

from __future__ import annotations

import pytest
from spec_manager.planner.constraints.authority import (
    build_question_pack,
    check_authority,
)
from spec_manager.planner.constraints.types import (
    DecisionRequirement,
    ImpactClassification,
)

# ===================================================================
# check_authority
# ===================================================================


class TestCheckAuthority:
    def _low_impact(self) -> ImpactClassification:
        return ImpactClassification(impact="LOW", blast_radius="LOCAL", reversibility="EASY")

    def _medium_impact(self) -> ImpactClassification:
        return ImpactClassification(impact="MEDIUM", blast_radius="SLICE", reversibility="MEDIUM")

    def _high_impact(self) -> ImpactClassification:
        return ImpactClassification(impact="HIGH", blast_radius="SYSTEM", reversibility="HARD")

    def test_low_impact_software_planner_ok(self):
        result = check_authority(impact=self._low_impact(), dimension="software")
        assert result == "planner_ok"

    def test_high_impact_requires_human(self):
        result = check_authority(impact=self._high_impact(), dimension="software")
        assert result == "human_required"

    def test_legal_dimension_requires_human(self):
        result = check_authority(impact=self._low_impact(), dimension="legal")
        assert result == "human_required"

    def test_economic_dimension_requires_human(self):
        result = check_authority(impact=self._low_impact(), dimension="economic")
        assert result == "human_required"

    def test_too_many_constraints_requires_human(self):
        result = check_authority(
            impact=self._low_impact(),
            constraints_introduced=4,
            dimension="software",
        )
        assert result == "human_required"

    def test_three_constraints_is_ok(self):
        result = check_authority(
            impact=self._low_impact(),
            constraints_introduced=3,
            dimension="software",
        )
        assert result == "planner_ok"

    def test_uncovered_dimension_requires_human(self):
        result = check_authority(
            impact=self._low_impact(),
            dimension="operational",
            existing_policies=["software", "organizational"],
        )
        assert result == "human_required"

    def test_covered_dimension_is_ok(self):
        result = check_authority(
            impact=self._low_impact(),
            dimension="software",
            existing_policies=["software", "organizational"],
        )
        assert result == "planner_ok"

    def test_empty_policies_no_check(self):
        result = check_authority(
            impact=self._low_impact(),
            dimension="operational",
            existing_policies=[],
        )
        assert result == "planner_ok"

    def test_medium_impact_software_planner_ok(self):
        result = check_authority(impact=self._medium_impact(), dimension="software")
        assert result == "planner_ok"


# ===================================================================
# build_question_pack
# ===================================================================


class TestBuildQuestionPack:
    def test_empty_list(self):
        result = build_question_pack(decision_requirements=[])
        assert result == []

    def test_single_requirement(self):
        dr = DecisionRequirement(
            decision_id="D1",
            question="SQL or NoSQL?",
            kind="technology_choice",
            dimension="software",
            scope="system",
            options=["PostgreSQL", "MongoDB"],
            needed_for=["DataStore"],
        )
        result = build_question_pack(decision_requirements=[dr])
        assert len(result) == 1
        q = result[0]
        assert q["question"] == "SQL or NoSQL?"
        assert q["kind"] == "technology_choice"
        assert q["dimension"] == "software"
        assert q["scope"] == "system"
        assert "PostgreSQL" in q["options"]
        assert "DataStore" in q["needed_for"]

    def test_multiple_requirements(self):
        drs = [
            DecisionRequirement(decision_id="D1", question="Q1"),
            DecisionRequirement(decision_id="D2", question="Q2"),
            DecisionRequirement(decision_id="D3", question="Q3"),
        ]
        result = build_question_pack(decision_requirements=drs)
        assert len(result) == 3

    def test_empty_options(self):
        dr = DecisionRequirement(decision_id="D1", question="Q", options=[])
        result = build_question_pack(decision_requirements=[dr])
        assert result[0]["options"] == ""

    def test_empty_needed_for(self):
        dr = DecisionRequirement(decision_id="D1", question="Q", needed_for=[])
        result = build_question_pack(decision_requirements=[dr])
        assert result[0]["needed_for"] == ""

    def test_return_type_is_list_of_dicts(self):
        dr = DecisionRequirement(decision_id="D1", question="Q")
        result = build_question_pack(decision_requirements=[dr])
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_all_keys_present(self):
        dr = DecisionRequirement(decision_id="D1", question="Q")
        result = build_question_pack(decision_requirements=[dr])
        expected_keys = {"question", "kind", "dimension", "scope", "options", "needed_for"}
        assert set(result[0].keys()) == expected_keys

    def test_options_joined_with_comma(self):
        dr = DecisionRequirement(
            decision_id="D1",
            question="Q",
            options=["a", "b", "c"],
        )
        result = build_question_pack(decision_requirements=[dr])
        assert result[0]["options"] == "a, b, c"

    def test_needed_for_joined_with_comma(self):
        dr = DecisionRequirement(
            decision_id="D1",
            question="Q",
            needed_for=["X", "Y"],
        )
        result = build_question_pack(decision_requirements=[dr])
        assert result[0]["needed_for"] == "X, Y"

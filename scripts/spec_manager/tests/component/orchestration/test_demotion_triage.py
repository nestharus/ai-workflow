"""Component tests for orchestration.demotion.triage module."""

from __future__ import annotations

from spec_manager.orchestration.demotion.triage import (
    DemotionContext,
    DemotionRouting,
    _constrain_to_active,
    triage,
)


class TestDemotionContextDefaults:

    def test_defaults(self) -> None:
        ctx = DemotionContext()
        assert ctx.active_layer == "L1"
        assert ctx.source_layer == "L1"
        assert ctx.source == ""
        assert ctx.gate is None
        assert ctx.category == ""
        assert ctx.failing_files == []
        assert ctx.failing_pins == []
        assert ctx.evidence_paths == []


class TestDemotionRoutingDefaults:

    def test_defaults(self) -> None:
        r = DemotionRouting()
        assert r.target_layer == "L1"
        assert r.reason == ""
        assert r.confidence == 1.0


class TestTriageCategoryRouting:

    def test_style_routes_to_l3(self) -> None:
        ctx = DemotionContext(active_layer="L3", category="STYLE")
        r = triage(ctx)
        assert r.target_layer == "L3"
        assert r.confidence == 0.9

    def test_logic_routes_to_l1(self) -> None:
        ctx = DemotionContext(active_layer="L1", category="LOGIC")
        r = triage(ctx)
        assert r.target_layer == "L1"
        assert r.confidence == 0.9

    def test_arch_routes_to_l2(self) -> None:
        ctx = DemotionContext(active_layer="L2", category="ARCH")
        r = triage(ctx)
        assert r.target_layer == "L2"
        assert r.confidence == 0.9


class TestTriageGateRouting:

    def test_gate_routes_when_no_category(self) -> None:
        ctx = DemotionContext(
            active_layer="L1", gate="NO_REMAINING_COMMENTS",
        )
        r = triage(ctx)
        assert r.target_layer == "L1"
        assert r.confidence == 0.85


class TestTriageSourceRouting:

    def test_source_routes_when_no_category_or_gate(self) -> None:
        ctx = DemotionContext(active_layer="L3", source="REVIEW")
        r = triage(ctx)
        assert r.target_layer == "L3"
        assert r.confidence == 0.7


class TestTriageDefaultRouting:

    def test_defaults_to_l1_when_nothing_matches(self) -> None:
        ctx = DemotionContext(active_layer="L1")
        r = triage(ctx)
        assert r.target_layer == "L1"
        assert r.confidence == 0.5
        assert r.reason == "Default routing to L1"


class TestConstrainToActive:

    def test_constrains_l3_target_to_l1(self) -> None:
        routing = DemotionRouting(target_layer="L3", reason="test", confidence=0.9)
        result = _constrain_to_active(routing, "L1")
        assert result.target_layer == "L1"
        assert result.confidence < 0.9
        assert "constrained" in result.reason

    def test_no_change_when_target_within_active(self) -> None:
        routing = DemotionRouting(target_layer="L1", reason="test", confidence=0.9)
        result = _constrain_to_active(routing, "L2")
        assert result.target_layer == "L1"
        assert result.confidence == 0.9


class TestTriageConfidenceVariation:

    def test_category_confidence_is_0_9(self) -> None:
        ctx = DemotionContext(active_layer="L1", category="SPEC")
        assert triage(ctx).confidence == 0.9

    def test_gate_confidence_is_0_85(self) -> None:
        ctx = DemotionContext(active_layer="L1", gate="ALL_TESTS_PASS")
        assert triage(ctx).confidence == 0.85

    def test_source_confidence_is_0_7(self) -> None:
        ctx = DemotionContext(active_layer="L1", source="TEST_FAILURE")
        assert triage(ctx).confidence == 0.7

    def test_default_confidence_is_0_5(self) -> None:
        ctx = DemotionContext(active_layer="L1")
        assert triage(ctx).confidence == 0.5

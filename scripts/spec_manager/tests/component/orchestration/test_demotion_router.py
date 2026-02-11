"""Component tests for orchestration.demotion.router module."""

from __future__ import annotations

from spec_manager.orchestration.demotion.router import DemotionRouter, RoutingBatch
from spec_manager.orchestration.demotion.triage import DemotionContext


class TestRoutingBatchDefaults:
    def test_defaults(self) -> None:
        batch = RoutingBatch()
        assert batch.tickets == []
        assert batch.routings == []


class TestDemotionRouterRoute:
    def test_route_produces_ticket_and_routing(self) -> None:
        router = DemotionRouter(run_id="r1", active_layer="L1")
        ctx = DemotionContext(
            active_layer="L1",
            source="TEST_FAILURE",
            failing_files=["foo.py"],
        )
        ticket, routing = router.route(ctx)
        assert ticket.source == "TEST_FAILURE"
        assert ticket.run_id == "r1"
        assert ticket.failing_files == ["foo.py"]
        assert routing.target_layer == "L1"

    def test_route_severity_blocker_for_high_confidence(self) -> None:
        router = DemotionRouter(run_id="r1", active_layer="L1")
        ctx = DemotionContext(active_layer="L1", category="LOGIC")
        ticket, routing = router.route(ctx)
        assert routing.confidence >= 0.8
        assert ticket.severity == "BLOCKER"

    def test_route_severity_major_for_low_confidence(self) -> None:
        router = DemotionRouter(run_id="r1", active_layer="L1")
        ctx = DemotionContext(active_layer="L1", source="TEST_FAILURE")
        ticket, routing = router.route(ctx)
        assert routing.confidence == 0.7
        assert ticket.severity == "MAJOR"


class TestDemotionRouterRouteGateFailures:
    def test_skips_passed_gates(self) -> None:
        router = DemotionRouter(run_id="r1")
        batch = router.route_gate_failures(
            slice_id="s1",
            gate_results=[
                {"gate_id": "G1", "passed": True},
                {"gate_id": "G2", "passed": False, "findings": [{"file_path": "x.py"}]},
            ],
        )
        assert len(batch.tickets) == 1
        assert batch.tickets[0].slice_id == "s1"

    def test_extracts_failing_files_from_findings(self) -> None:
        router = DemotionRouter(run_id="r1")
        batch = router.route_gate_failures(
            slice_id="s1",
            gate_results=[
                {
                    "gate_id": "G1",
                    "passed": False,
                    "findings": [
                        {"file_path": "a.py"},
                        {"file_path": "b.py"},
                    ],
                },
            ],
        )
        assert len(batch.tickets) == 1
        assert set(batch.tickets[0].failing_files) == {"a.py", "b.py"}

    def test_extracts_failing_pins_from_findings(self) -> None:
        router = DemotionRouter(run_id="r1")
        batch = router.route_gate_failures(
            slice_id="s1",
            gate_results=[
                {
                    "gate_id": "G1",
                    "passed": False,
                    "findings": [{"pin_func_id": "PIN-001"}],
                },
            ],
        )
        assert "PIN-001" in batch.tickets[0].failing_pins

    def test_empty_when_all_pass(self) -> None:
        router = DemotionRouter(run_id="r1")
        batch = router.route_gate_failures(
            slice_id="s1",
            gate_results=[
                {"gate_id": "G1", "passed": True},
                {"gate_id": "G2", "passed": True},
            ],
        )
        assert batch.tickets == []
        assert batch.routings == []


class TestDemotionRouterRouteTestFailures:
    def test_produces_tickets_from_test_failures(self) -> None:
        router = DemotionRouter(run_id="r1", active_layer="L1")
        batch = router.route_test_failures(
            slice_id="s1",
            test_failures=[
                {"file": "test_foo.py", "message": "assert failed"},
                {"file": "test_bar.py", "message": "timeout"},
            ],
        )
        assert len(batch.tickets) == 2
        assert batch.tickets[0].source == "TEST_FAILURE"
        assert batch.tickets[0].slice_id == "s1"
        assert batch.tickets[0].diagnosis == "assert failed"
        assert batch.tickets[1].diagnosis == "timeout"


class TestDemotionRouterRouteReviewFindings:
    def test_routes_by_category(self) -> None:
        router = DemotionRouter(run_id="r1", active_layer="L3")
        batch = router.route_review_findings(
            slice_id="s1",
            findings=[
                {
                    "category": "STYLE",
                    "description": "Bad formatting",
                    "files": ["fmt.py"],
                },
            ],
        )
        assert len(batch.tickets) == 1
        assert batch.tickets[0].diagnosis == "Bad formatting"
        assert batch.tickets[0].source == "REVIEW"

    def test_sets_slice_id(self) -> None:
        router = DemotionRouter(run_id="r1", active_layer="L1")
        batch = router.route_review_findings(
            slice_id="auth-slice",
            findings=[{"category": "LOGIC", "description": "Bug"}],
        )
        assert batch.tickets[0].slice_id == "auth-slice"

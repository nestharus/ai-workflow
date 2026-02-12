"""Tests for spec_manager.planner.layers — L1Planner, L2Planner, L3Planner."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from spec_manager.planner.layers.l1 import L1Planner
from spec_manager.planner.layers.l2 import L2Planner
from spec_manager.planner.layers.l3 import L3Planner
from spec_manager.planner.router import LayerPlanner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(**kwargs: Any) -> Any:
    """Create a simple context namespace for testing."""

    class _Ctx:
        pass

    ctx = _Ctx()
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_l1_planner_protocol_conformance(self) -> None:
        assert isinstance(L1Planner(), LayerPlanner)

    def test_l2_planner_protocol_conformance(self) -> None:
        assert isinstance(L2Planner(), LayerPlanner)

    def test_l3_planner_protocol_conformance(self) -> None:
        assert isinstance(L3Planner(), LayerPlanner)


# ---------------------------------------------------------------------------
# L1Planner
# ---------------------------------------------------------------------------


class TestL1Planner:
    def test_l1_discover_with_files(self, tmp_path: Path) -> None:
        """L1 discover should find functions and classes from Python skeletons."""
        skeleton = tmp_path / "treasury.py"
        skeleton.write_text(
            "# Spec: Handle treasury netting\n"
            "def calculate_net_position():\n"
            "    pass\n"
            "\n"
            "class SettlementProcessor:\n"
            "    pass\n",
            encoding="utf-8",
        )

        planner = L1Planner()
        ctx = _make_ctx(slice_root=str(tmp_path))
        result = planner.discover(ctx)

        assert "nodes" in result
        assert "edges" in result
        assert "file_index" in result

        # Check that we found the spec-comment block, function, and class
        kinds = [n["kind"] for n in result["nodes"]]
        assert "spec_comment_block" in kinds
        assert "function" in kinds
        assert "class" in kinds

        # Check specific names
        names = [n.get("name", "") for n in result["nodes"] if n.get("name")]
        assert "calculate_net_position" in names
        assert "SettlementProcessor" in names

        # Check file_index maps the relative path to node ids
        assert "treasury.py" in result["file_index"]
        assert len(result["file_index"]["treasury.py"]) >= 2

    def test_l1_discover_empty_slice(self, tmp_path: Path) -> None:
        """No files in slice_root should return an empty graph."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        planner = L1Planner()
        ctx = _make_ctx(slice_root=str(empty_dir))
        result = planner.discover(ctx)

        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["file_index"] == {}

    def test_l1_discover_no_slice_root(self) -> None:
        """Missing slice_root should return an empty graph."""
        planner = L1Planner()
        ctx = _make_ctx(slice_root="")
        result = planner.discover(ctx)
        assert result["nodes"] == []

    def test_l1_build_plan_from_gaps(self, tmp_path: Path) -> None:
        """build_plan should create intentions from gaps."""
        skeleton = tmp_path / "calc.py"
        skeleton.write_text(
            "# Spec: Compute net\ndef compute_net():\n    pass\n",
            encoding="utf-8",
        )

        planner = L1Planner()
        ctx = _make_ctx(slice_root=str(tmp_path))
        discovery = planner.discover(ctx)

        gaps = [{"target": "compute_net", "description": "implement netting logic"}]
        plan = planner.build_plan(ctx, gaps, discovery)

        assert "intentions" in plan
        assert len(plan["intentions"]) == 1
        intention = plan["intentions"][0]
        assert intention["function_name"] == "compute_net"
        assert intention["approach"] == "implement netting logic"

    def test_l1_build_plan_no_gaps_creates_from_nodes(self, tmp_path: Path) -> None:
        """When no gaps are given, build_plan generates one intention per function node."""
        skeleton = tmp_path / "funcs.py"
        skeleton.write_text(
            "def alpha():\n    pass\n\ndef beta():\n    pass\n",
            encoding="utf-8",
        )

        planner = L1Planner()
        ctx = _make_ctx(slice_root=str(tmp_path))
        discovery = planner.discover(ctx)

        plan = planner.build_plan(ctx, [], discovery)
        assert len(plan["intentions"]) == 2
        names = {i["function_name"] for i in plan["intentions"]}
        assert names == {"alpha", "beta"}

    def test_l1_resolve_signal_no_evidence(self) -> None:
        """Without an evidence tool, resolve_signal returns None."""
        planner = L1Planner()
        ctx = _make_ctx(slice_root="")
        result = planner.resolve_signal(ctx, {"target": "x"})
        assert result is None

    def test_l1_resolve_signal_with_evidence(self) -> None:
        """With an evidence tool that returns data, resolve_signal returns a dict."""
        evidence_fn = MagicMock(return_value={"found": True})
        planner = L1Planner(evidence_tool=evidence_fn)
        ctx = _make_ctx(slice_root="")
        result = planner.resolve_signal(ctx, {"target": "netting"})
        assert result is not None
        assert result["resolution"] == "evidence_tool"
        assert result["target"] == "netting"

    def test_l1_resolve_signal_none_signal(self) -> None:
        """None signal always returns None."""
        planner = L1Planner()
        ctx = _make_ctx(slice_root="")
        assert planner.resolve_signal(ctx, None) is None


# ---------------------------------------------------------------------------
# L2Planner
# ---------------------------------------------------------------------------


class TestL2Planner:
    def test_l2_discover_empty(self, tmp_path: Path) -> None:
        """No arch files should return an empty topology."""
        planner = L2Planner()
        ctx = _make_ctx(workspace_root=str(tmp_path))
        result = planner.discover(ctx)
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["arch_files"] == []

    def test_l2_discover_with_arch_files(self, tmp_path: Path) -> None:
        """L2 should discover architecture files."""
        (tmp_path / "component_manifest.yaml").write_text("name: comp1\n")
        planner = L2Planner()
        ctx = _make_ctx(workspace_root=str(tmp_path))
        result = planner.discover(ctx)
        assert "component_manifest.yaml" in result["arch_files"]

    def test_l2_build_plan_from_gaps(self) -> None:
        """build_plan should create wiring intentions from gaps."""
        planner = L2Planner()
        ctx = _make_ctx(workspace_root="", metadata={})
        discovery = {"nodes": [], "edges": [], "arch_files": []}

        gaps = [
            {
                "component_id": "payment-gateway",
                "target_files": ["gateway.py"],
                "description": "wire payment processor pin",
                "pin_refs": ["pin-001"],
                "dependencies": ["auth-service"],
            }
        ]
        plan = planner.build_plan(ctx, gaps, discovery)

        assert "intentions" in plan
        assert len(plan["intentions"]) == 1
        intention = plan["intentions"][0]
        assert intention["component_id"] == "payment-gateway"
        assert intention["approach"] == "wire payment processor pin"
        assert intention["pin_refs"] == ["pin-001"]

    def test_l2_resolve_signal_no_evidence(self) -> None:
        """Without an evidence tool, resolve_signal returns None."""
        planner = L2Planner()
        ctx = _make_ctx(workspace_root="", metadata={})
        result = planner.resolve_signal(ctx, "some ambiguity")
        assert result is None

    def test_l2_resolve_signal_with_evidence(self) -> None:
        """With an evidence tool, resolve_signal delegates."""
        evidence_fn = MagicMock(return_value={"answer": "yes"})
        planner = L2Planner(evidence_tool=evidence_fn)
        ctx = _make_ctx(workspace_root="", metadata={})
        result = planner.resolve_signal(ctx, "some ambiguity")
        assert result is not None
        assert result["resolved"] is True
        assert result["source"] == "evidence"


# ---------------------------------------------------------------------------
# L3Planner
# ---------------------------------------------------------------------------


class TestL3Planner:
    def test_l3_discover_with_metadata(self) -> None:
        """L3 discover uses metadata quality receipts to build a graph."""
        planner = L3Planner()
        ctx = _make_ctx(
            metadata={
                "changed_files": ["a.py", "b.py"],
                "quality_receipts": [
                    {
                        "id": "smell-1",
                        "smell_type": "long_method",
                        "file": "a.py",
                        "function_span": "do_stuff",
                        "severity": "warning",
                    }
                ],
                "diffs": [],
            }
        )
        result = planner.discover(ctx)

        assert result["changed_file_count"] == 2
        assert result["smell_count"] == 1

        graph = result["quality_graph"]
        # Should have 2 file nodes + 1 smell node
        assert len(graph["nodes"]) == 3

        file_nodes = [n for n in graph["nodes"] if n["type"] == "file"]
        assert len(file_nodes) == 2

        smell_nodes = [n for n in graph["nodes"] if n["type"] == "smell"]
        assert len(smell_nodes) == 1
        assert smell_nodes[0]["smell_type"] == "long_method"

        # Edge from file -> smell
        assert len(graph["edges"]) == 1
        assert graph["edges"][0]["type"] == "contains"

    def test_l3_discover_empty_metadata(self) -> None:
        """No metadata returns empty quality graph."""
        planner = L3Planner()
        ctx = _make_ctx(metadata={})
        result = planner.discover(ctx)
        assert result["changed_file_count"] == 0
        assert result["smell_count"] == 0
        assert result["quality_graph"]["nodes"] == []

    def test_l3_build_plan_from_gaps(self) -> None:
        """build_plan should create refactor intentions with behavior preservation."""
        planner = L3Planner()
        ctx = _make_ctx(metadata={})
        discovery = {
            "quality_graph": {
                "nodes": [
                    {
                        "id": "smell-1",
                        "type": "smell",
                        "smell_type": "long_method",
                        "file": "a.py",
                        "function_span": "do_stuff",
                        "severity": "warning",
                    }
                ],
                "edges": [],
            },
            "evidence_summary": {},
        }
        gaps = [
            {
                "file": "a.py",
                "function_span": "do_stuff",
                "smell_type": "long_method",
            }
        ]

        plan = planner.build_plan(ctx, gaps, discovery)

        assert "intentions" in plan
        assert len(plan["intentions"]) == 1
        intention = plan["intentions"][0]
        assert intention["file"] == "a.py"
        assert intention["function_span"] == "do_stuff"
        assert intention["smell_type"] == "long_method"
        assert "behavior_preservation_check" in intention
        assert "No observable behavior change" in intention["behavior_preservation_check"]
        assert intention["severity"] == "warning"

    def test_l3_resolve_signal_always_none(self) -> None:
        """L3 resolve_signal always returns None (quality signals need human judgment)."""
        planner = L3Planner()
        ctx = _make_ctx(metadata={})
        assert planner.resolve_signal(ctx, None) is None
        assert planner.resolve_signal(ctx, "some signal") is None
        assert planner.resolve_signal(ctx, {"target": "x"}) is None

    def test_l3_resolve_under_spec_with_matching_smell(self) -> None:
        """When a smell node matches, under-spec resolves locally."""
        planner = L3Planner()
        ctx = _make_ctx(metadata={})
        discovery = {
            "quality_graph": {
                "nodes": [
                    {
                        "id": "smell-1",
                        "type": "smell",
                        "smell_type": "long_method",
                        "file": "a.py",
                        "function_span": "do_stuff",
                        "severity": "warning",
                    }
                ],
                "edges": [],
            },
        }
        events = [{"file": "a.py", "function_span": "do_stuff"}]
        result = planner.resolve_under_spec(ctx, events, discovery)
        assert result["blocked"] is False
        assert len(result["constraints"]) == 1

    def test_l3_resolve_under_spec_blocked(self) -> None:
        """When no smell matches, under-spec is blocked with questions."""
        planner = L3Planner()
        ctx = _make_ctx(metadata={})
        discovery = {"quality_graph": {"nodes": [], "edges": []}}
        events = [{"file": "b.py", "function_span": "unknown"}]
        result = planner.resolve_under_spec(ctx, events, discovery)
        assert result["blocked"] is True
        assert len(result["questions"]) == 1

    def test_l3_triage_signal_returns_noop(self) -> None:
        """L3 triage_signal always returns NOOP."""
        planner = L3Planner()
        ctx = _make_ctx(metadata={})
        result = planner.triage_signal(ctx, {"need": {"artifact_key": "foo"}})
        assert result["action"] == "NOOP"
        assert result["monitors"] == []


# ---------------------------------------------------------------------------
# L2 triage_signal
# ---------------------------------------------------------------------------


class TestL2TriageSignal:
    def test_l2_triage_signal_returns_noop(self) -> None:
        """L2 triage_signal always returns NOOP."""
        planner = L2Planner()
        ctx = _make_ctx(workspace_root="", metadata={})
        result = planner.triage_signal(ctx, {"need": {"artifact_key": "bar"}})
        assert result["action"] == "NOOP"
        assert result["monitors"] == []


# ---------------------------------------------------------------------------
# L1 triage_signal
# ---------------------------------------------------------------------------


class TestL1TriageSignal:
    def test_triage_signal_no_workspace_returns_noop(self) -> None:
        """When workspace_root is empty, triage_signal returns NOOP."""
        planner = L1Planner()
        ctx = _make_ctx(workspace_root="", run_id="run-1", slice_id="s1")
        signal = {
            "need": {"artifact_key": "Calculator"},
            "spec_refs": [{"spec_text": "compute net position"}],
        }
        result = planner.triage_signal(ctx, signal)
        assert result["action"] == "NOOP"
        assert result["monitors"] == []

    def test_triage_signal_matching_in_progress_work_item(self, tmp_path: Path) -> None:
        """When a matching IN_PROGRESS work item exists, return WAIT_ON_WORK_ITEM."""
        from spec_manager.orchestration.coordination.work_items import (
            WorkItem,
            WorkItemLocation,
            WorkItemStore,
        )

        # Set up coordination directory and store a work item
        coord_dir = tmp_path / ".pdd_runs" / "run-1" / "coordination"
        coord_dir.mkdir(parents=True)
        store = WorkItemStore(coord_dir)
        store.add(
            WorkItem(
                work_item_id="wi-1",
                spec_text="compute net position for treasury",
                owner_slice_id="s-other",
                status="IN_PROGRESS",
                location=WorkItemLocation(file="treasury.py", symbol="compute_net"),
            )
        )

        planner = L1Planner()
        ctx = _make_ctx(
            workspace_root=str(tmp_path),
            run_id="run-1",
            slice_id="s1",
        )
        signal = {
            "signal_id": "sig-1",
            "need": {"artifact_key": "compute_net"},
            "spec_refs": [{"spec_text": "compute net position for treasury"}],
            "search_hints": {"keywords": ["treasury"]},
        }
        result = planner.triage_signal(ctx, signal)
        assert result["action"] == "WAIT_ON_WORK_ITEM"
        assert len(result["monitors"]) == 1
        assert result["monitors"][0]["kind"] == "work_item_status"
        assert "matched_work_item" in result

    def test_triage_signal_done_work_item_wakes_immediately(self, tmp_path: Path) -> None:
        """When a matching DONE work item exists, return WAKE_IMMEDIATELY."""
        from spec_manager.orchestration.coordination.work_items import (
            WorkItem,
            WorkItemLocation,
            WorkItemStore,
        )

        coord_dir = tmp_path / ".pdd_runs" / "run-1" / "coordination"
        coord_dir.mkdir(parents=True)
        store = WorkItemStore(coord_dir)
        store.add(
            WorkItem(
                work_item_id="wi-2",
                spec_text="validate settlement amounts",
                owner_slice_id="s-other",
                status="DONE",
                location=WorkItemLocation(file="settlement.py", symbol="validate"),
            )
        )

        planner = L1Planner()
        ctx = _make_ctx(
            workspace_root=str(tmp_path),
            run_id="run-1",
            slice_id="s1",
        )
        signal = {
            "signal_id": "sig-2",
            "need": {"artifact_key": "validate"},
            "spec_refs": [{"spec_text": "validate settlement amounts"}],
            "search_hints": {},
        }
        result = planner.triage_signal(ctx, signal)
        assert result["action"] == "WAKE_IMMEDIATELY"
        assert result["monitors"] == []
        assert "matched_work_item" in result

    def test_triage_signal_no_match_falls_to_expand_spec(self, tmp_path: Path) -> None:
        """When no work item or spec catalog match is found, return EXPAND_SPEC."""
        # Empty coordination dir, no matching files
        coord_dir = tmp_path / ".pdd_runs" / "run-1" / "coordination"
        coord_dir.mkdir(parents=True)

        planner = L1Planner()
        ctx = _make_ctx(
            workspace_root=str(tmp_path),
            run_id="run-1",
            slice_id="s1",
        )
        signal = {
            "signal_id": "sig-3",
            "need": {"artifact_key": "NonExistentThing", "reason": "not found"},
            "spec_refs": [],
            "search_hints": {},
        }
        result = planner.triage_signal(ctx, signal)
        assert result["action"] == "EXPAND_SPEC"
        assert len(result["monitors"]) == 1
        assert result["monitors"][0]["kind"] == "spec_expanded"
        assert "expansion" in result
        assert result["expansion"]["artifact_key"] == "NonExistentThing"

    def test_triage_signal_spec_catalog_match_routes_and_waits(self, tmp_path: Path) -> None:
        """When no work item exists but spec catalog has a match, return ROUTE_AND_WAIT."""
        # Empty coordination store
        coord_dir = tmp_path / ".pdd_runs" / "run-1" / "coordination"
        coord_dir.mkdir(parents=True)

        # Create a spec file that mentions the artifact
        spec_file = tmp_path / "slices" / "treasury.py"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text(
            "# Spec: Implement FxConverter for currency conversion\n"
            "def convert_currency():\n"
            "    pass\n",
            encoding="utf-8",
        )

        planner = L1Planner()
        ctx = _make_ctx(
            workspace_root=str(tmp_path),
            run_id="run-1",
            slice_id="s1",
        )
        signal = {
            "signal_id": "sig-4",
            "need": {"artifact_key": "FxConverter"},
            "spec_refs": [],
            "search_hints": {},
        }
        result = planner.triage_signal(ctx, signal)
        assert result["action"] == "ROUTE_AND_WAIT"
        assert len(result["monitors"]) == 1
        assert result["monitors"][0]["kind"] == "symbol_available"
        assert "routing" in result
        assert len(result["routing"]) == 1

"""Component tests for layer-aware PromotionLoop step changes.

Covers:
- Finding dataclass (construction, round-trip)
- Triage updates (required_change_type routing, new categories, new gates, triage_finding)
- GapExplorationStep layer dispatch (L1/L2/L3)
- PlanStep layer dispatch (L1/L2/L3 intention shapes)
- AnalyzeStep layer dispatch (L3 file metrics)
- VerifyStep layer dispatch (L1/L2/L3 agent calls, governance FAIL, findings)
- PromoteStep layer dispatch (L2 gate pass/fail, L3 quality gaps and diff-impact)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spec_manager.orchestration.demotion import DemotionTicket
from spec_manager.orchestration.demotion.triage import (
    DemotionContext,
    DemotionRouting,
    triage,
    triage_finding,
)
from spec_manager.orchestration.evidence import (
    EvidenceBundle,
    Finding,
    GapReportRef,
    GatesReportRef,
    ImplementationRef,
    PlanRef,
)
from spec_manager.orchestration.promotion_loop import (
    AnalyzeStep,
    GapExplorationStep,
    ImplementStep,
    PlanStep,
    PromoteStep,
    SliceContext,
    StepResult,
    VerifyStep,
)


# ======================================================================
# Helpers
# ======================================================================


def _make_ctx(
    layer: str = "l1",
    slice_root: str = "",
    workspace_root: str = "",
    slice_id: str = "test-slice",
    run_id: str = "run-1",
) -> SliceContext:
    """Build a SliceContext with sensible defaults."""
    return SliceContext(
        slice_id=slice_id,
        slice_root=slice_root,
        layer=layer,
        run_id=run_id,
        workspace_root=workspace_root,
    )


def _make_bundle(**overrides: Any) -> EvidenceBundle:
    """Build an EvidenceBundle with optional overrides."""
    defaults = {
        "run_id": "run-1",
        "slice_id": "test-slice",
        "iteration": 1,
    }
    defaults.update(overrides)
    return EvidenceBundle(**defaults)


def _write_py_file(directory: Path, name: str, content: str) -> Path:
    """Write a Python file into *directory* and return its path."""
    p = directory / name
    p.write_text(content, encoding="utf-8")
    return p


# ======================================================================
# Finding dataclass
# ======================================================================


class TestFinding:
    """Tests for the Finding dataclass in evidence.py."""

    def test_construction_with_defaults(self) -> None:
        """Finding() can be constructed with all defaults."""
        f = Finding()
        assert f.dimension == ""
        assert f.category == "style"
        assert f.severity == "MINOR"
        assert f.location == {}
        assert f.evidence == ""
        assert f.required_change_type == "refactor_only"
        assert f.suggested_fix == ""
        assert f.confidence == pytest.approx(0.7)
        assert f.tags == []

    def test_construction_with_values(self) -> None:
        """Finding() can be constructed with explicit values."""
        f = Finding(
            dimension="ARCH_BOUNDARY",
            category="architecture",
            severity="BLOCKER",
            location={"file": "api.py", "start_line": 10},
            evidence="Cross-boundary call detected",
            required_change_type="wiring_only",
            suggested_fix="Move call through dispatch layer",
            confidence=0.9,
            tags=["cross-boundary"],
        )
        assert f.dimension == "ARCH_BOUNDARY"
        assert f.severity == "BLOCKER"
        assert f.location["file"] == "api.py"
        assert f.tags == ["cross-boundary"]

    def test_to_dict(self) -> None:
        """to_dict() returns a plain dict with all fields."""
        f = Finding(dimension="DRIFT", evidence="drift detected")
        d = f.to_dict()
        assert isinstance(d, dict)
        assert d["dimension"] == "DRIFT"
        assert d["evidence"] == "drift detected"
        assert d["category"] == "style"
        assert "tags" in d

    def test_from_dict(self) -> None:
        """from_dict() reconstructs a Finding from a dict."""
        data = {
            "dimension": "GOVERNANCE",
            "category": "governance",
            "severity": "MAJOR",
            "location": {"file": "x.py"},
            "evidence": "missing receipt",
            "required_change_type": "refactor_only",
            "suggested_fix": "add receipt",
            "confidence": 0.8,
            "tags": ["gov"],
        }
        f = Finding.from_dict(data)
        assert f.dimension == "GOVERNANCE"
        assert f.category == "governance"
        assert f.severity == "MAJOR"
        assert f.location == {"file": "x.py"}
        assert f.confidence == pytest.approx(0.8)
        assert f.tags == ["gov"]

    def test_round_trip(self) -> None:
        """to_dict() -> from_dict() round-trip preserves all fields."""
        original = Finding(
            dimension="CORRECTNESS",
            category="logic",
            severity="BLOCKER",
            location={"file": "calc.py", "start_line": 42},
            evidence="Off-by-one in loop",
            required_change_type="behavior_change",
            suggested_fix="Fix loop bound",
            confidence=0.95,
            tags=["logic", "off-by-one"],
        )
        reconstructed = Finding.from_dict(original.to_dict())
        assert reconstructed.dimension == original.dimension
        assert reconstructed.category == original.category
        assert reconstructed.severity == original.severity
        assert reconstructed.location == original.location
        assert reconstructed.evidence == original.evidence
        assert reconstructed.required_change_type == original.required_change_type
        assert reconstructed.suggested_fix == original.suggested_fix
        assert reconstructed.confidence == pytest.approx(original.confidence)
        assert reconstructed.tags == original.tags

    def test_from_dict_with_missing_keys_uses_defaults(self) -> None:
        """from_dict() fills defaults when keys are missing."""
        f = Finding.from_dict({"dimension": "X"})
        assert f.dimension == "X"
        assert f.category == "style"
        assert f.severity == "MINOR"
        assert f.confidence == pytest.approx(0.7)


# ======================================================================
# Triage updates
# ======================================================================


class TestTriageRequiredChangeType:
    """Tests for required_change_type routing in triage()."""

    def test_behavior_change_routes_to_l1(self) -> None:
        """required_change_type=behavior_change always routes to L1."""
        ctx = DemotionContext(
            active_layer="L3",
            required_change_type="behavior_change",
        )
        result = triage(ctx)
        assert result.target_layer == "L1"
        assert result.confidence == pytest.approx(0.95)

    def test_wiring_only_routes_to_l2(self) -> None:
        """required_change_type=wiring_only routes to L2."""
        ctx = DemotionContext(
            active_layer="L3",
            required_change_type="wiring_only",
        )
        result = triage(ctx)
        assert result.target_layer == "L2"

    def test_refactor_only_fixes_in_layer(self) -> None:
        """required_change_type=refactor_only returns active layer (fix-in-layer)."""
        ctx = DemotionContext(
            active_layer="L3",
            required_change_type="refactor_only",
        )
        result = triage(ctx)
        assert result.target_layer == "L3"
        assert "fixes in current layer" in result.reason

    def test_spec_change_routes_to_l1(self) -> None:
        """required_change_type=spec_change routes to L1."""
        ctx = DemotionContext(
            active_layer="L2",
            required_change_type="spec_change",
        )
        result = triage(ctx)
        assert result.target_layer == "L1"

    def test_wiring_only_constrained_to_active_l1(self) -> None:
        """wiring_only targets L2 but active=L1 constrains down to L1."""
        ctx = DemotionContext(
            active_layer="L1",
            required_change_type="wiring_only",
        )
        result = triage(ctx)
        assert result.target_layer == "L1"
        assert "constrained" in result.reason


class TestTriageNewCategories:
    """Tests for new category routing in triage()."""

    def test_governance_fixes_in_current_layer(self) -> None:
        """GOVERNANCE category blocks in current layer, no demotion."""
        ctx = DemotionContext(active_layer="L2", category="GOVERNANCE")
        result = triage(ctx)
        assert result.target_layer == "L2"
        assert "fixes in current layer" in result.reason

    def test_inline_logic_at_arch_routes_to_l1(self) -> None:
        """INLINE_LOGIC_AT_ARCH routes to L1."""
        ctx = DemotionContext(active_layer="L2", category="INLINE_LOGIC_AT_ARCH")
        result = triage(ctx)
        assert result.target_layer == "L1"

    def test_architecture_routes_to_l2(self) -> None:
        """ARCHITECTURE category routes to L2."""
        ctx = DemotionContext(active_layer="L3", category="ARCHITECTURE")
        result = triage(ctx)
        assert result.target_layer == "L2"

    def test_maintainability_routes_to_l3(self) -> None:
        """MAINTAINABILITY category routes to L3."""
        ctx = DemotionContext(active_layer="L3", category="MAINTAINABILITY")
        result = triage(ctx)
        assert result.target_layer == "L3"

    def test_correctness_routes_to_l1(self) -> None:
        """CORRECTNESS category routes to L1."""
        ctx = DemotionContext(active_layer="L3", category="CORRECTNESS")
        result = triage(ctx)
        assert result.target_layer == "L1"

    def test_logic_bug_routes_to_l1(self) -> None:
        """LOGIC_BUG category routes to L1."""
        ctx = DemotionContext(active_layer="L2", category="LOGIC_BUG")
        result = triage(ctx)
        assert result.target_layer == "L1"

    def test_drift_routes_to_l1(self) -> None:
        """DRIFT category defaults to L1."""
        ctx = DemotionContext(active_layer="L3", category="DRIFT")
        result = triage(ctx)
        assert result.target_layer == "L1"


class TestTriageL2Gates:
    """Tests for new L2 gate routing in triage()."""

    @pytest.mark.parametrize(
        "gate,expected_layer",
        [
            ("PIN_CONSUMPTION_COVERAGE", "L2"),
            ("EDGE_REALIZATION", "L2"),
            ("NO_ORPHAN_COMPONENTS", "L2"),
            ("EVENT_HANDLER_COVERAGE", "L2"),
            ("CONFIG_EXTERNALIZATION", "L2"),
            ("ARCH_DRIFT_PASS", "L2"),
            ("NO_INLINED_ATOM_LOGIC", "L1"),
            ("FUNCTION_RECOMPOSITION", "L2"),
        ],
    )
    def test_l2_gates_route_correctly(self, gate: str, expected_layer: str) -> None:
        """L2 gates route to the correct target layer."""
        ctx = DemotionContext(active_layer="L3", gate=gate)
        result = triage(ctx)
        assert result.target_layer == expected_layer


class TestTriageL3Gates:
    """Tests for new L3 gate routing in triage()."""

    @pytest.mark.parametrize(
        "gate,expected_layer",
        [
            ("ALL_QUALITY_REVIEWERS_PASS", "L3"),
            ("NO_LOGIC_CHANGE", "L1"),
            ("NO_ARCH_BOUNDARY_VIOLATIONS", "L2"),
            ("DRIFT_PASS", "L1"),
            ("TESTS_PASS", "L1"),
        ],
    )
    def test_l3_gates_route_correctly(self, gate: str, expected_layer: str) -> None:
        """L3 gates route to the correct target layer."""
        ctx = DemotionContext(active_layer="L3", gate=gate)
        result = triage(ctx)
        assert result.target_layer == expected_layer


class TestTriageFinding:
    """Tests for the triage_finding() convenience function."""

    def test_basic_finding_dict(self) -> None:
        """triage_finding() constructs context from finding dict and routes."""
        finding = {
            "category": "logic",
            "required_change_type": "behavior_change",
            "location": {"file": "calc.py"},
        }
        result = triage_finding(finding, active_layer="L3", source_layer="L3")
        assert result.target_layer == "L1"
        assert result.confidence >= 0.9

    def test_finding_without_location(self) -> None:
        """triage_finding() handles missing location gracefully."""
        finding = {"category": "style"}
        result = triage_finding(finding, active_layer="L3", source_layer="L3")
        assert result.target_layer == "L3"

    def test_finding_with_governance_category(self) -> None:
        """triage_finding() with GOVERNANCE blocks in current layer."""
        finding = {"category": "GOVERNANCE", "location": {}}
        result = triage_finding(finding, active_layer="L2", source_layer="L2")
        assert result.target_layer == "L2"

    def test_finding_required_change_takes_priority(self) -> None:
        """required_change_type takes priority over category in triage_finding()."""
        finding = {
            "category": "style",
            "required_change_type": "behavior_change",
            "location": {},
        }
        result = triage_finding(finding, active_layer="L3", source_layer="L3")
        assert result.target_layer == "L1"


# ======================================================================
# GapExplorationStep layer dispatch
# ======================================================================


class TestGapExplorationStepLayerDispatch:
    """Tests for GapExplorationStep dispatching by ctx.layer."""

    def test_l1_calls_explore_l1(self, tmp_path: Path) -> None:
        """At L1, GapExplorationStep calls _explore_l1 (compliance scan)."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "main.py", "# SPEC: implement this\ndef foo(): pass\n")

        ctx = _make_ctx(layer="l1", slice_root=str(slice_root))
        bundle = _make_bundle()

        step = GapExplorationStep()
        with patch.object(step, "_explore_l1", wraps=step._explore_l1) as mock_l1:
            result = step.run(ctx, bundle)

        mock_l1.assert_called_once()
        assert result.status == "OK"

    def test_l2_calls_explore_l2(self, tmp_path: Path) -> None:
        """At L2, GapExplorationStep calls _explore_l2 (LLM architecture gap detection)."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "app.py", "class Router: pass\n")

        ctx = _make_ctx(
            layer="l2",
            slice_root=str(slice_root),
            workspace_root=str(tmp_path),
        )
        bundle = _make_bundle()

        agent_response = json.dumps({"gaps": [
            {"kind": "unconsumed_pin", "component_id": "auth", "file": "app.py",
             "description": "Pin not consumed", "expected": "Wire to Router"},
        ]})

        step = GapExplorationStep()
        with patch(
            "spec_manager.orchestration.promotion_loop.run_agent",
            return_value=agent_response,
            create=True,
        ), patch(
            "spec_manager.core.agent_utils.run_agent",
            return_value=agent_response,
        ), patch(
            "spec_manager.core.json_extraction._extract_json_payload",
            return_value=agent_response,
        ), patch(
            "spec_manager.refinement.formats._strip_code_fences",
            side_effect=lambda x: x,
        ):
            result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert len(bundle.gaps.open_gaps) >= 1
        assert bundle.gaps.open_gaps[0]["kind"] == "unconsumed_pin"

    def test_l3_calls_explore_l3(self, tmp_path: Path) -> None:
        """At L3, GapExplorationStep calls _explore_l3 (quality reviewers)."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "utils.py", "def helper():\n    x=1\n")

        ctx = _make_ctx(
            layer="l3",
            slice_root=str(slice_root),
            workspace_root=str(tmp_path),
        )
        bundle = _make_bundle()

        reviewer_response = json.dumps({"findings": [
            {"description": "Unused variable x", "severity": "MINOR",
             "category": "style", "required_change_type": "refactor_only"},
        ]})

        step = GapExplorationStep()
        with patch(
            "spec_manager.core.agent_utils.run_agent",
            return_value=reviewer_response,
        ), patch(
            "spec_manager.core.json_extraction._extract_json_payload",
            return_value=reviewer_response,
        ), patch(
            "spec_manager.refinement.formats._strip_code_fences",
            side_effect=lambda x: x,
        ):
            result = step.run(ctx, bundle)

        assert result.status == "OK"
        # 4 reviewers each produce 1 finding for 1 file = 4 gaps
        assert len(bundle.gaps.open_gaps) == 4
        assert all(g["kind"] == "quality_finding" for g in bundle.gaps.open_gaps)

    def test_l2_empty_slice_returns_no_gaps(self, tmp_path: Path) -> None:
        """At L2, an empty slice directory produces no gaps."""
        slice_root = tmp_path / "empty_slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l2", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()

        step = GapExplorationStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.gaps.open_gaps == []

    def test_l3_empty_slice_returns_no_gaps(self, tmp_path: Path) -> None:
        """At L3, an empty slice directory produces no gaps."""
        slice_root = tmp_path / "empty_slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()

        step = GapExplorationStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.gaps.open_gaps == []


# ======================================================================
# PlanStep layer dispatch
# ======================================================================


class TestPlanStepLayerDispatch:
    """Tests for PlanStep dispatching by ctx.layer."""

    def test_l1_gaps_produce_function_implementation_intentions(self) -> None:
        """L1 gaps produce function implementation intentions."""
        ctx = _make_ctx(layer="l1")
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[
            {"file": "auth.py", "description": "stub function login()"},
            {"file": "db.py", "description": "missing connect()"},
        ])

        step = PlanStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert len(bundle.plan.intentions) == 2
        assert bundle.plan.intentions[0]["target_file"] == "auth.py"
        assert "Implement:" in bundle.plan.intentions[0]["approach"]
        assert "stub function login()" in bundle.plan.intentions[0]["approach"]

    def test_l2_gaps_produce_wiring_intentions(self) -> None:
        """L2 gaps produce wiring intentions with layer_constraint=wiring_only."""
        ctx = _make_ctx(layer="l2")
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[
            {"file": "router.py", "component_id": "auth-router",
             "description": "unconsumed pin login_handler"},
        ])

        step = PlanStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert len(bundle.plan.intentions) == 1
        intention = bundle.plan.intentions[0]
        assert intention["layer_constraint"] == "wiring_only"
        assert "Wire:" in intention["approach"]
        assert intention["component_id"] == "auth-router"
        assert "no inlined logic" in intention["acceptance_criteria"]

    def test_l3_gaps_produce_refactor_intentions_grouped_by_file(self) -> None:
        """L3 gaps produce refactor intentions grouped by file, sorted by severity."""
        ctx = _make_ctx(layer="l3")
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[
            {"file": "utils.py", "description": "long method", "severity": "MAJOR"},
            {"file": "utils.py", "description": "unused import", "severity": "MINOR"},
            {"file": "auth.py", "description": "deep nesting", "severity": "BLOCKER"},
        ])

        step = PlanStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        # Two unique files -> two intentions
        assert len(bundle.plan.intentions) == 2
        # Sorted by file name
        files = [i["target_file"] for i in bundle.plan.intentions]
        assert files == sorted(files)

        # Each intention has refactor_only constraint and finding_count
        for intention in bundle.plan.intentions:
            assert intention["layer_constraint"] == "refactor_only"
            assert intention["finding_count"] >= 1
            assert "No behavior change" in intention["acceptance_criteria"]

    def test_l3_plan_sorts_minor_first(self) -> None:
        """L3 plan groups findings by file and sorts MINOR before MAJOR."""
        ctx = _make_ctx(layer="l3")
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[
            {"file": "x.py", "description": "major issue", "severity": "MAJOR"},
            {"file": "x.py", "description": "minor issue", "severity": "MINOR"},
        ])

        step = PlanStep()
        step.run(ctx, bundle)

        assert len(bundle.plan.intentions) == 1
        approach = bundle.plan.intentions[0]["approach"]
        # The approach should list minor first (since MINOR sorts before MAJOR)
        minor_pos = approach.find("minor issue")
        major_pos = approach.find("major issue")
        assert minor_pos < major_pos, "MINOR should come before MAJOR in approach text"

    def test_no_gaps_produces_empty_plan_all_layers(self) -> None:
        """PlanStep with no gaps produces empty intentions at all layers."""
        for layer in ("l1", "l2", "l3"):
            ctx = _make_ctx(layer=layer)
            bundle = _make_bundle()
            bundle.gaps = GapReportRef(open_gaps=[])

            step = PlanStep()
            result = step.run(ctx, bundle)

            assert result.status == "OK"
            assert bundle.plan.intentions == []


# ======================================================================
# AnalyzeStep layer dispatch
# ======================================================================


class TestAnalyzeStepLayerDispatch:
    """Tests for AnalyzeStep dispatching by ctx.layer."""

    def test_l3_produces_line_and_function_metrics(self, tmp_path: Path) -> None:
        """At L3, AnalyzeStep produces line/function metrics without external deps."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(
            slice_root, "module_a.py",
            "def foo():\n    pass\n\ndef bar():\n    return 1\n"
        )
        _write_py_file(
            slice_root, "module_b.py",
            "class Thing:\n    def method(self):\n        pass\n"
        )

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()

        step = AnalyzeStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.source_index.path == "quality_metrics.index.json"
        assert len(bundle.source_index.entries) == 2

        # Check metrics for module_a.py
        entry_a = next(e for e in bundle.source_index.entries if e["path"] == "module_a.py")
        assert int(entry_a["functions"]) == 2
        assert int(entry_a["lines"]) > 0

        # Check metrics for module_b.py (def method counts as function)
        entry_b = next(e for e in bundle.source_index.entries if e["path"] == "module_b.py")
        assert int(entry_b["functions"]) == 1

    def test_l3_empty_slice_returns_ok(self, tmp_path: Path) -> None:
        """At L3, an empty slice produces no entries but still returns OK."""
        slice_root = tmp_path / "empty"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root))
        bundle = _make_bundle()

        step = AnalyzeStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert bundle.source_index.entries == []

    def test_l3_skips_hidden_directories(self, tmp_path: Path) -> None:
        """At L3, files in hidden directories are skipped."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        hidden = slice_root / ".hidden"
        hidden.mkdir()
        _write_py_file(hidden, "secret.py", "def secret(): pass\n")
        _write_py_file(slice_root, "visible.py", "def visible(): pass\n")

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root))
        bundle = _make_bundle()

        step = AnalyzeStep()
        step.run(ctx, bundle)

        paths = [e["path"] for e in bundle.source_index.entries]
        assert "visible.py" in paths
        assert all(".hidden" not in p for p in paths)

    def test_nonexistent_slice_root_returns_ok(self) -> None:
        """AnalyzeStep with nonexistent slice_root returns OK (no work to do)."""
        ctx = _make_ctx(layer="l3", slice_root="/nonexistent/path")
        bundle = _make_bundle()

        step = AnalyzeStep()
        result = step.run(ctx, bundle)

        assert result.status == "OK"


# ======================================================================
# VerifyStep
# ======================================================================


class TestVerifyStep:
    """Tests for VerifyStep layer-aware verification."""

    def _patch_run_agent_json(self, response_dict: dict[str, Any]):
        """Return a context manager that patches the agent call chain to return *response_dict*."""
        response_str = json.dumps(response_dict)
        return (
            patch("spec_manager.core.agent_utils.run_agent", return_value=response_str),
            patch("spec_manager.core.json_extraction._extract_json_payload", return_value=response_str),
            patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x),
        )

    def test_l1_calls_agent_and_handles_empty_response(self, tmp_path: Path) -> None:
        """At L1, VerifyStep calls the verifier agent; empty findings means OK."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l1", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle(workspace_root=str(tmp_path))

        governance_resp = {"status": "PASS", "findings": []}
        l1_resp = {"findings": []}

        p1, p2, p3 = self._patch_run_agent_json(governance_resp)
        # We need to handle two separate calls, so we use side_effect
        agent_responses = [json.dumps(governance_resp), json.dumps(l1_resp)]

        with patch("spec_manager.core.agent_utils.run_agent", side_effect=agent_responses), \
             patch("spec_manager.core.json_extraction._extract_json_payload", side_effect=agent_responses), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = VerifyStep()
            result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert result.notes_path is not None

    def test_l2_calls_agent_and_handles_findings(self, tmp_path: Path) -> None:
        """At L2, VerifyStep calls the verifier agent; MAJOR finding triggers RETRY."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l2", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle(workspace_root=str(tmp_path))

        governance_resp = json.dumps({"status": "PASS", "findings": []})
        l2_resp = json.dumps({"findings": [
            {"dimension": "PIN_COVERAGE", "category": "architecture",
             "severity": "MAJOR", "required_change_type": "wiring_only",
             "location": {"file": "router.py"}, "evidence": "orphan pin"},
        ]})

        with patch("spec_manager.core.agent_utils.run_agent", side_effect=[governance_resp, l2_resp]), \
             patch("spec_manager.core.json_extraction._extract_json_payload", side_effect=[governance_resp, l2_resp]), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = VerifyStep()
            result = step.run(ctx, bundle)

        # architecture category + wiring_only -> creates a demotion ticket -> RETRY
        assert result.status == "RETRY"
        assert len(result.emitted_tickets) >= 1

    def test_l3_calls_agent_and_handles_findings(self, tmp_path: Path) -> None:
        """At L3, VerifyStep calls the verifier agent; BLOCKER triggers RETRY."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle(workspace_root=str(tmp_path))

        governance_resp = json.dumps({"status": "PASS", "findings": []})
        l3_resp = json.dumps({"findings": [
            {"dimension": "CORRECTNESS", "category": "logic",
             "severity": "BLOCKER", "required_change_type": "behavior_change",
             "location": {"file": "calc.py"}, "evidence": "off-by-one"},
        ]})

        with patch("spec_manager.core.agent_utils.run_agent", side_effect=[governance_resp, l3_resp]), \
             patch("spec_manager.core.json_extraction._extract_json_payload", side_effect=[governance_resp, l3_resp]), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = VerifyStep()
            result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert any(t.target_layer == "L1" for t in result.emitted_tickets)

    def test_governance_fail_returns_retry_with_tickets(self, tmp_path: Path) -> None:
        """Governance FAIL status causes RETRY with demotion tickets."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l2", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle(workspace_root=str(tmp_path))

        governance_resp = json.dumps({
            "status": "FAIL",
            "findings": [
                {"severity": "BLOCKER", "evidence": "Missing oversight receipt",
                 "location": {"file": "deploy.py"}, "required_change_type": "refactor_only"},
            ],
        })

        with patch("spec_manager.core.agent_utils.run_agent", return_value=governance_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=governance_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = VerifyStep()
            result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert "governance FAIL" in result.error

    def test_no_findings_returns_ok(self, tmp_path: Path) -> None:
        """VerifyStep returns OK when there are no findings at all."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l1", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle(workspace_root=str(tmp_path))

        empty_resp = json.dumps({"status": "PASS", "findings": []})

        with patch("spec_manager.core.agent_utils.run_agent", return_value=empty_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=empty_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = VerifyStep()
            result = step.run(ctx, bundle)

        assert result.status == "OK"

    def test_blocker_finding_returns_retry_with_demotion_tickets(self, tmp_path: Path) -> None:
        """A BLOCKER-severity finding in verification triggers RETRY with demotion tickets."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()

        ctx = _make_ctx(layer="l1", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle(workspace_root=str(tmp_path))

        governance_resp = json.dumps({"status": "PASS", "findings": []})
        l1_resp = json.dumps({"findings": [
            {"dimension": "CONNECTIVITY", "category": "architecture",
             "severity": "BLOCKER", "required_change_type": "wiring_only",
             "location": {"file": "api.py"}, "evidence": "orphan dependency"},
        ]})

        with patch("spec_manager.core.agent_utils.run_agent", side_effect=[governance_resp, l1_resp]), \
             patch("spec_manager.core.json_extraction._extract_json_payload", side_effect=[governance_resp, l1_resp]), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = VerifyStep()
            result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert len(result.emitted_tickets) >= 1
        assert result.notes_path is not None

    def test_nonexistent_slice_returns_ok(self) -> None:
        """VerifyStep with no workspace or slice returns OK gracefully."""
        ctx = _make_ctx(layer="l1", slice_root="", workspace_root="")
        bundle = _make_bundle()

        step = VerifyStep()
        result = step.run(ctx, bundle)

        # With empty workspace, run_agent_json returns {} which means no findings
        assert result.status == "OK"


# ======================================================================
# PromoteStep layer dispatch
# ======================================================================


class TestPromoteStepL2:
    """Tests for PromoteStep at L2."""

    def test_l2_gate_pass(self, tmp_path: Path) -> None:
        """L2 promotion: all gates pass yields OK."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "router.py", "class Router:\n    pass\n")

        ctx = _make_ctx(layer="l2", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()

        gate_resp = json.dumps({"gates": [
            {"gate_id": "NO_INLINED_ATOM_LOGIC", "passed": True, "summary": "Clean"},
            {"gate_id": "FUNCTION_RECOMPOSITION", "passed": True, "summary": "OK"},
            {"gate_id": "PIN_CONSUMPTION_COVERAGE", "passed": True, "summary": "OK"},
            {"gate_id": "EDGE_REALIZATION", "passed": True, "summary": "OK"},
            {"gate_id": "NO_ORPHAN_COMPONENTS", "passed": True, "summary": "OK"},
            {"gate_id": "EVENT_HANDLER_COVERAGE", "passed": True, "summary": "OK"},
            {"gate_id": "CONFIG_EXTERNALIZATION", "passed": True, "summary": "OK"},
            {"gate_id": "ARCH_DRIFT_PASS", "passed": True, "summary": "OK"},
        ]})

        with patch("spec_manager.core.agent_utils.run_agent", return_value=gate_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=gate_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = PromoteStep()
            result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert len(bundle.gates.gates) == 8
        assert all(g["passed"] for g in bundle.gates.gates)

    def test_l2_gate_fail_wiring_only(self, tmp_path: Path) -> None:
        """L2 promotion: a failed gate with wiring_only retries at L2."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "router.py", "class Router: pass\n")

        ctx = _make_ctx(layer="l2", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()

        gate_resp = json.dumps({"gates": [
            {"gate_id": "PIN_CONSUMPTION_COVERAGE", "passed": False,
             "summary": "3 pins unconsumed", "required_change_type": "wiring_only"},
        ]})

        with patch("spec_manager.core.agent_utils.run_agent", return_value=gate_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=gate_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = PromoteStep()
            result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert len(result.emitted_tickets) >= 1
        # wiring_only -> target L2
        assert result.emitted_tickets[0].target_layer == "L2"

    def test_l2_gate_fail_behavior_change_demotes_to_l1(self, tmp_path: Path) -> None:
        """L2 promotion: a failed gate with behavior_change demotes to L1."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "handler.py", "def handle(): pass\n")

        ctx = _make_ctx(layer="l2", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()

        gate_resp = json.dumps({"gates": [
            {"gate_id": "NO_INLINED_ATOM_LOGIC", "passed": False,
             "summary": "Business logic in handler.py",
             "required_change_type": "behavior_change"},
        ]})

        with patch("spec_manager.core.agent_utils.run_agent", return_value=gate_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=gate_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = PromoteStep()
            result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert len(result.emitted_tickets) >= 1
        assert result.emitted_tickets[0].target_layer == "L1"


class TestPromoteStepL3:
    """Tests for PromoteStep at L3."""

    def test_l3_open_quality_gaps_cause_retry(self, tmp_path: Path) -> None:
        """L3 promotion: open quality findings cause RETRY."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "a.py", "x = 1\n")

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[
            {"kind": "quality_finding", "file": "a.py", "category": "style",
             "severity": "MINOR", "description": "unused variable"},
        ])

        step = PromoteStep()
        result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert "quality findings still open" in result.error

    def test_l3_logic_finding_demotes_to_l1(self, tmp_path: Path) -> None:
        """L3 promotion: logic/correctness quality finding demotes to L1."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "calc.py", "def add(a, b): return a - b\n")

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[
            {"kind": "quality_finding", "file": "calc.py", "category": "logic",
             "severity": "BLOCKER", "description": "Incorrect subtraction"},
        ])

        step = PromoteStep()
        result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert len(result.emitted_tickets) >= 1
        assert result.emitted_tickets[0].target_layer == "L1"

    def test_l3_architecture_finding_demotes_to_l2(self, tmp_path: Path) -> None:
        """L3 promotion: architecture quality finding demotes to L2."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "api.py", "class Api: pass\n")

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[
            {"kind": "quality_finding", "file": "api.py", "category": "architecture",
             "severity": "MAJOR", "description": "Cross-boundary call"},
        ])

        step = PromoteStep()
        result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert len(result.emitted_tickets) >= 1
        assert result.emitted_tickets[0].target_layer == "L2"

    def test_l3_no_gaps_and_refactor_only_diff_passes(self, tmp_path: Path) -> None:
        """L3 promotion: no quality gaps + refactor_only diff-impact passes."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "clean.py", "def clean(): return True\n")

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[])  # no quality gaps

        diff_resp = json.dumps({
            "impact": "refactor_only",
            "confidence": 0.95,
            "evidence": "Only rename changes detected",
        })

        with patch("spec_manager.core.agent_utils.run_agent", return_value=diff_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=diff_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = PromoteStep()
            result = step.run(ctx, bundle)

        assert result.status == "OK"
        assert len(bundle.gates.gates) == 1
        assert bundle.gates.gates[0]["gate_id"] == "DIFF_IMPACT_CLASSIFIER"
        assert bundle.gates.gates[0]["passed"] is True

    def test_l3_behavior_change_diff_demotes_to_l1(self, tmp_path: Path) -> None:
        """L3 promotion: diff-impact=behavior_change demotes to L1."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "service.py", "def serve(): pass\n")

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[])

        diff_resp = json.dumps({
            "impact": "behavior_change",
            "confidence": 0.9,
            "evidence": "New endpoint added",
        })

        with patch("spec_manager.core.agent_utils.run_agent", return_value=diff_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=diff_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = PromoteStep()
            result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert len(result.emitted_tickets) == 1
        assert result.emitted_tickets[0].target_layer == "L1"
        assert "NO_LOGIC_CHANGE" in result.error

    def test_l3_wiring_only_diff_demotes_to_l2(self, tmp_path: Path) -> None:
        """L3 promotion: diff-impact=wiring_only demotes to L2."""
        slice_root = tmp_path / "slice"
        slice_root.mkdir()
        _write_py_file(slice_root, "routes.py", "def route(): pass\n")

        ctx = _make_ctx(layer="l3", slice_root=str(slice_root), workspace_root=str(tmp_path))
        bundle = _make_bundle()
        bundle.gaps = GapReportRef(open_gaps=[])

        diff_resp = json.dumps({
            "impact": "wiring_only",
            "confidence": 0.85,
            "evidence": "Route registration changed",
        })

        with patch("spec_manager.core.agent_utils.run_agent", return_value=diff_resp), \
             patch("spec_manager.core.json_extraction._extract_json_payload", return_value=diff_resp), \
             patch("spec_manager.refinement.formats._strip_code_fences", side_effect=lambda x: x):
            step = PromoteStep()
            result = step.run(ctx, bundle)

        assert result.status == "RETRY"
        assert len(result.emitted_tickets) == 1
        assert result.emitted_tickets[0].target_layer == "L2"
        assert "NO_ARCH_BOUNDARY_VIOLATIONS" in result.error

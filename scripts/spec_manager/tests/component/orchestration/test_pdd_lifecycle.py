"""Component tests for PddLifecycle orchestrator.

Tests the L1 → L2 → L3 layer pipeline with typed refinement.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.orchestration import pdd_lifecycle as lifecycle_module
from spec_manager.orchestration.pdd_lifecycle import PddLifecycle
from spec_manager.refinement.workspace.state import Phase


@pytest.fixture
def mock_manager(tmp_path: Path) -> MagicMock:
    """Create a mock MagicMock with a temporary workspace."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir(parents=True, exist_ok=True)

    libraries_dir = run_dir / "libraries"
    libraries_dir.mkdir(parents=True, exist_ok=True)

    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    spec_snapshot_dir = run_dir / "spec_snapshot"
    spec_snapshot_dir.mkdir(parents=True, exist_ok=True)

    manager = MagicMock()
    manager.workspace_path = run_dir
    manager.run_id = "test-run"
    manager.structure = MagicMock()
    manager.structure.root = run_dir
    manager.structure.libraries_dir = libraries_dir
    manager.structure.spec_snapshot_dir = spec_snapshot_dir

    return manager


@pytest.fixture
def mock_manager_with_libraries(mock_manager: MagicMock) -> MagicMock:
    """Create a MagicMock with sample library directories and code."""
    libraries_dir = mock_manager.structure.libraries_dir
    spec_snapshot_dir = mock_manager.structure.spec_snapshot_dir

    # Library 1: with details and charter
    lib1_dir = libraries_dir / "lib1-test-library"
    lib1_dir.mkdir(parents=True, exist_ok=True)
    details1 = lib1_dir / "details"
    details1.mkdir(parents=True, exist_ok=True)
    (details1 / "algorithms.md").write_text(
        "# Algorithms\n\nSettlement netting and gross processing.",
        encoding="utf-8",
    )
    (details1 / "shapes.md").write_text(
        "# Shapes\n\nSettlementInstruction dataclass.",
        encoding="utf-8",
    )
    (lib1_dir / "charter.md").write_text(
        "# Charter 1\n\nOriginal requirements for library 1.",
        encoding="utf-8",
    )

    # Library 2: with details only (no charter)
    lib2_dir = libraries_dir / "lib2-another-library"
    lib2_dir.mkdir(parents=True, exist_ok=True)
    details2 = lib2_dir / "details"
    details2.mkdir(parents=True, exist_ok=True)
    (details2 / "algorithms.md").write_text(
        "# Algorithms\n\nRisk monitoring and exposure calculation.",
        encoding="utf-8",
    )

    # Library 3: directory only (no details)
    lib3_dir = libraries_dir / "lib3-incomplete"
    lib3_dir.mkdir(parents=True, exist_ok=True)

    # Code in spec_snapshot (code IS the spec)
    (spec_snapshot_dir / "settlement_processor.py").write_text(
        '"""Settlement netting and gross processing."""\n\nclass SettlementProcessor:\n    pass\n',
        encoding="utf-8",
    )
    (spec_snapshot_dir / "risk_engine.py").write_text(
        '"""Risk monitoring engine."""\n\nclass RiskEngine:\n    pass\n',
        encoding="utf-8",
    )

    return mock_manager


class TestPddLifecycleInit:
    """Test PddLifecycle initialization."""

    def test_default_initialization(self, mock_manager: MagicMock) -> None:
        """Test default initialization parameters."""
        lifecycle = PddLifecycle(mock_manager)

        assert lifecycle.manager is mock_manager
        assert lifecycle.mode == "interactive"
        assert lifecycle.use_research is False
        assert lifecycle.use_evidence_store is False
        assert lifecycle.steering_path is None
        assert lifecycle.max_refinement_iterations == 5

    def test_custom_initialization(self, mock_manager: MagicMock, tmp_path: Path) -> None:
        """Test initialization with custom parameters."""
        steering_file = tmp_path / "steering.json"
        steering_file.write_text("{}", encoding="utf-8")

        lifecycle = PddLifecycle(
            mock_manager,
            mode="auto",
            use_research=True,
            use_evidence_store=True,
            steering_path=steering_file,
            max_refinement_iterations=10,
        )

        assert lifecycle.mode == "auto"
        assert lifecycle.use_research is True
        assert lifecycle.use_evidence_store is True
        assert lifecycle.steering_path == steering_file
        assert lifecycle.max_refinement_iterations == 10

    @patch("spec_manager.orchestration.pdd_lifecycle.PddOrchestrator")
    def test_orchestrator_created(
        self,
        mock_orchestrator_class: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that PddOrchestrator is created during init."""
        lifecycle = PddLifecycle(mock_manager)

        mock_orchestrator_class.assert_called_once_with(mock_manager)
        assert lifecycle.orchestrator == mock_orchestrator_class.return_value


class TestPddLifecycleRun:
    """Test the complete lifecycle run method."""

    @patch.object(PddLifecycle, "_request_release_signoff")
    @patch.object(PddLifecycle, "_run_governance_check")
    @patch.object(PddLifecycle, "_request_l2_checkpoint")
    @patch.object(PddLifecycle, "_run_l1_with_approval")
    @patch.object(PddLifecycle, "_run_layer")
    @patch.object(PddLifecycle, "_run_transition")
    @patch.object(PddLifecycle, "_run_intake")
    @patch.object(PddLifecycle, "qa")
    def test_run_calls_all_layers(
        self,
        mock_qa: MagicMock,
        mock_intake: MagicMock,
        mock_transition: MagicMock,
        mock_layer: MagicMock,
        mock_l1_approval: MagicMock,
        mock_l2_checkpoint: MagicMock,
        mock_governance: MagicMock,
        mock_release_signoff: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that run() calls intake, L1, transitions, L2, L3, QA."""
        mock_intake.return_value = {"extraction": "done"}
        mock_l1_approval.return_value = (
            {"layer": "l1", "slices": {}},
            {"approved": True, "iteration": 1},
        )
        mock_transition.return_value = {"refinement": {}, "from": "l1", "to": "l2"}
        mock_layer.return_value = {"layer": "l2", "slices": {}}
        mock_qa.return_value = {"pass_rate": 1.0}
        mock_l2_checkpoint.return_value = {"approved": True, "mode": "auto"}
        mock_governance.return_value = {"passed": True}
        mock_release_signoff.return_value = {"approved": True, "mode": "auto"}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.run()

        # Verify all phases called
        mock_intake.assert_called_once()
        mock_l1_approval.assert_called_once()
        assert mock_transition.call_count == 2  # L1→L2 and L2→L3
        assert mock_layer.call_count == 2  # L2 and L3
        mock_qa.assert_called_once()

        # Verify transition args
        transition_calls = mock_transition.call_args_list
        assert transition_calls[0].args == ("l1", "l2")
        assert transition_calls[1].args == ("l2", "l3")

        # Verify layer args
        layer_calls = mock_layer.call_args_list
        assert layer_calls[0].args == ("l2",)
        assert layer_calls[1].args == ("l3",)

        # Verify result structure
        assert result["intake"] == {"extraction": "done"}
        assert result["approval"]["approved"] is True
        assert result["qa"] == {"pass_rate": 1.0}

    @patch.object(PddLifecycle, "_request_release_signoff")
    @patch.object(PddLifecycle, "_run_governance_check")
    @patch.object(PddLifecycle, "_request_l2_checkpoint")
    @patch.object(PddLifecycle, "_run_l1_with_approval")
    @patch.object(PddLifecycle, "_run_layer")
    @patch.object(PddLifecycle, "_run_transition")
    @patch.object(PddLifecycle, "_run_intake")
    @patch.object(PddLifecycle, "qa")
    def test_run_with_worktree_manager(
        self,
        mock_qa: MagicMock,
        mock_intake: MagicMock,
        mock_transition: MagicMock,
        mock_layer: MagicMock,
        mock_l1_approval: MagicMock,
        mock_l2_checkpoint: MagicMock,
        mock_governance: MagicMock,
        mock_release_signoff: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that run() calls setup_layers and cleanup when worktree manager exists."""
        mock_intake.return_value = {}
        mock_l1_approval.return_value = ({}, {"approved": True})
        mock_transition.return_value = {}
        mock_layer.return_value = {}
        mock_qa.return_value = {}
        mock_l2_checkpoint.return_value = {"approved": True, "mode": "auto"}
        mock_governance.return_value = {"passed": True}
        mock_release_signoff.return_value = {"approved": True, "mode": "auto"}

        mock_wm = MagicMock()
        mock_wm.setup_layers.return_value = {"base_ref": "HEAD", "worktrees": []}
        mock_wm.cleanup.return_value = {"removed": []}

        lifecycle = PddLifecycle(mock_manager, worktree_manager=mock_wm)
        result = lifecycle.run()

        mock_wm.setup_layers.assert_called_once()
        mock_wm.cleanup.assert_called_once()
        assert "setup" in result
        assert "cleanup" in result


class TestSection10MigrationChecklistArtifact:
    """Checklist artifact coverage for section-10 lifecycle integration."""

    @patch.object(PddLifecycle, "_request_release_signoff")
    @patch.object(PddLifecycle, "_run_governance_check")
    @patch.object(PddLifecycle, "_request_l2_checkpoint")
    @patch.object(PddLifecycle, "_run_l1_with_approval")
    @patch.object(PddLifecycle, "_run_layer")
    @patch.object(PddLifecycle, "_run_transition")
    @patch.object(PddLifecycle, "_run_intake")
    @patch.object(PddLifecycle, "qa")
    def test_run_emits_checklist_artifact_with_canonical_shape(
        self,
        mock_qa: MagicMock,
        mock_intake: MagicMock,
        mock_transition: MagicMock,
        mock_layer: MagicMock,
        mock_l1_approval: MagicMock,
        mock_l2_checkpoint: MagicMock,
        mock_governance: MagicMock,
        mock_release_signoff: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        mock_intake.return_value = {"status": "COMPLETED"}
        mock_l1_approval.return_value = (
            {"layer": "l1", "slices": {}},
            {"approved": True, "iteration": 1, "mode": "interactive"},
        )
        mock_transition.return_value = {"refinement": {}, "from": "l1", "to": "l2"}
        mock_layer.return_value = {"layer": "l2", "slices": {}}
        mock_qa.return_value = {"pass_rate": 1.0}
        mock_l2_checkpoint.return_value = {"approved": True, "mode": "interactive"}
        mock_governance.return_value = {"passed": True}
        mock_release_signoff.return_value = {"approved": True, "mode": "interactive"}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.run()

        checklist_output = result["section10_migration_checklist"]
        checklist_path = Path(checklist_output["path"])
        assert checklist_path.exists()

        payload = json.loads(checklist_path.read_text(encoding="utf-8"))
        assert payload["artifact"] == "section10_migration_checklist"
        assert payload["version"] == 1
        assert payload["section"] == "10"
        assert payload["run_id"] == mock_manager.run_id
        assert payload["mode"] == "interactive"

        assert [item["id"] for item in payload["prechecks"]] == [
            "checkpoint_taxonomy_coverage",
            "checkpoint_key_set",
            "user_question_store_path",
            "planner_update_store_path",
        ]
        assert [item["checkpoint"] for item in payload["migration_order"]] == [
            "l1_approval",
            "l2_checkpoint",
            "release_signoff",
        ]
        assert [item["taxonomy"] for item in payload["migration_order"]] == [
            "VALIDATION",
            "SCOPE",
            "TRADEOFF",
        ]
        assert payload["rollback"][0]["id"] == "resume_from_run_state"
        assert payload["acceptance_status"]["status"] == "COMPLETE"
        assert checklist_output["acceptance_status"] == "COMPLETE"

    @patch.object(PddLifecycle, "_run_l1_with_approval")
    @patch.object(PddLifecycle, "_run_intake")
    def test_run_waiting_updates_checklist_status(
        self,
        mock_intake: MagicMock,
        mock_l1_approval: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        mock_intake.return_value = {"status": "COMPLETED"}
        mock_l1_approval.return_value = (
            {"layer": "l1", "slices": {}},
            {
                "approved": False,
                "mode": "interactive",
                "status": "WAITING",
                "checkpoint": "l1_approval",
            },
        )

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        result = lifecycle.run()

        assert result["status"] == "WAITING"
        assert result["waiting_reason"] == "l1_approval"

        checklist_path = Path(result["section10_migration_checklist"]["path"])
        payload = json.loads(checklist_path.read_text(encoding="utf-8"))
        statuses = {step["checkpoint"]: step["status"] for step in payload["migration_order"]}
        assert statuses["l1_approval"] == "WAITING"
        assert statuses["l2_checkpoint"] == "PENDING"
        assert statuses["release_signoff"] == "PENDING"
        assert payload["acceptance_status"]["status"] == "IN_PROGRESS"
        assert result["section10_migration_checklist"]["acceptance_status"] == "IN_PROGRESS"


class TestRunLayer:
    """Test the _run_layer method."""

    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_library_refinement")
    def test_l1_layer(
        self,
        mock_lib_refine: MagicMock,
        mock_slices: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test _run_layer('l1') calls library refinement + slices."""
        mock_lib_refine.side_effect = [
            {"refined": True},
            {"refined": False},
        ]
        mock_slices.return_value = {"all_complete": True}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_layer("l1")

        assert result["layer"] == "l1"
        assert result["entry_refinement"] == {"refined": True}
        assert result["slices"] == {"all_complete": True}
        assert result["exit_refinement"] == {"refined": False}
        assert mock_lib_refine.call_count == 2
        mock_slices.assert_called_once_with("l1")

    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_architectural_refinement")
    def test_l2_layer(
        self,
        mock_arch_refine: MagicMock,
        mock_slices: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test _run_layer('l2') calls architectural refinement + slices."""
        mock_arch_refine.return_value = {"candidates_proposed": 3}
        mock_slices.return_value = {"all_complete": True}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_layer("l2")

        assert result["layer"] == "l2"
        assert mock_arch_refine.call_count == 2
        mock_slices.assert_called_once_with("l2")

    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_code_quality_refinement")
    def test_l3_layer(
        self,
        mock_cq_refine: MagicMock,
        mock_slices: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test _run_layer('l3') calls code quality refinement + slices."""
        mock_cq_refine.return_value = {"files_reviewed": 2}
        mock_slices.return_value = {"all_complete": True}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_layer("l3")

        assert result["layer"] == "l3"
        assert mock_cq_refine.call_count == 2
        mock_slices.assert_called_once_with("l3")


class TestRunTransition:
    """Test the _run_transition method."""

    @patch.object(PddLifecycle, "_run_governance_check")
    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_architectural_refinement")
    def test_l1_to_l2_no_demotions(
        self,
        mock_arch_refine: MagicMock,
        mock_slices: MagicMock,
        mock_governance: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test L1→L2 transition without demotions."""
        mock_arch_refine.return_value = {"demotion_tickets": 0}
        mock_governance.return_value = {"passed": True}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_transition("l1", "l2")

        assert result["from"] == "l1"
        assert result["to"] == "l2"
        mock_arch_refine.assert_called_once()
        mock_slices.assert_not_called()  # No rework needed
        assert result["transition_stuck"] is False

    @patch.object(PddLifecycle, "_run_governance_check")
    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_architectural_refinement")
    def test_l1_to_l2_with_demotions(
        self,
        mock_arch_refine: MagicMock,
        mock_slices: MagicMock,
        mock_governance: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test L1→L2 transition with demotions triggers L1 rework."""
        # First call has demotions, second call (after rework) has none
        mock_arch_refine.side_effect = [
            {"demotion_tickets": 2},
            {"demotion_tickets": 0},
        ]
        mock_slices.return_value = {"all_complete": True}
        mock_governance.return_value = {"passed": True}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_transition("l1", "l2")

        assert mock_arch_refine.call_count == 2
        mock_slices.assert_called_once_with("l1")  # Rework at L1
        assert "rework_rounds" in result
        assert len(result["rework_rounds"]) == 2
        assert "rework" in result["rework_rounds"][0]  # First round had rework

    @patch.object(PddLifecycle, "_run_governance_check")
    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_code_quality_refinement")
    def test_l2_to_l3_transition(
        self,
        mock_cq_refine: MagicMock,
        mock_slices: MagicMock,
        mock_governance: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test L2→L3 transition calls code quality refinement."""
        mock_cq_refine.return_value = {"demotion_tickets": 0}
        mock_governance.return_value = {"passed": True}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_transition("l2", "l3")

        assert result["from"] == "l2"
        assert result["to"] == "l3"
        mock_cq_refine.assert_called_once()

    @patch.object(PddLifecycle, "_run_readiness_ci")
    @patch.object(PddLifecycle, "_run_governance_check")
    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_architectural_refinement")
    def test_transition_propagates_with_worktree_manager(
        self,
        mock_arch_refine: MagicMock,
        mock_slices: MagicMock,
        mock_governance: MagicMock,
        mock_readiness_ci: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that transition propagates clean → next dirty."""
        mock_arch_refine.return_value = {"demotion_tickets": 0}
        mock_governance.return_value = {"passed": True}
        mock_readiness_ci.return_value = {"passed": True}

        mock_wm = MagicMock()
        prop_result = MagicMock()
        prop_result.success = True
        prop_result.from_layer = "l1"
        prop_result.to_layer = "l2"
        prop_result.error = ""
        mock_wm.propagate_clean_to_next_layer.return_value = prop_result

        lifecycle = PddLifecycle(mock_manager, worktree_manager=mock_wm)
        result = lifecycle._run_transition("l1", "l2")

        mock_wm.propagate_clean_to_next_layer.assert_called_once_with("l1")
        assert result["propagation"]["success"] is True


class TestDiscoverSlices:
    """Test the _discover_slices method."""

    def test_l1_discovers_libraries(self, mock_manager_with_libraries: MagicMock) -> None:
        """Test L1 discovers slices from libraries."""
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        slices = lifecycle._discover_slices("l1")

        assert len(slices) == 3  # lib1, lib2, lib3
        assert slices[0].slice_id == "lib1-test-library"
        assert slices[0].layer == "l1"
        assert slices[1].slice_id == "lib2-another-library"
        assert slices[2].slice_id == "lib3-incomplete"

    def test_l2_discovers_arch_components(self, mock_manager_with_libraries: MagicMock) -> None:
        """Test L2 discovers architectural component slices."""
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        slices = lifecycle._discover_slices("l2")

        assert len(slices) == 3
        assert slices[0].slice_id == "arch-lib1-test-library"
        assert slices[0].layer == "l2"

    def test_l3_discovers_code_files(self, mock_manager_with_libraries: MagicMock) -> None:
        """Test L3 discovers code file slices."""
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        slices = lifecycle._discover_slices("l3")

        assert len(slices) == 2  # settlement_processor.py, risk_engine.py
        assert all(s.layer == "l3" for s in slices)
        slice_ids = {s.slice_id for s in slices}
        assert "cq-settlement_processor" in slice_ids
        assert "cq-risk_engine" in slice_ids

    def test_l1_no_libraries(self, mock_manager: MagicMock) -> None:
        """Test L1 returns empty when no libraries dir."""
        mock_manager.structure.libraries_dir.rmdir()
        lifecycle = PddLifecycle(mock_manager)
        slices = lifecycle._discover_slices("l1")
        assert slices == []


class TestPhase0BoundaryReentry:
    """Test deterministic Phase 0 boundary re-entry selection."""

    def test_run_intake_triggers_phase0_when_libraries_missing(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """If libraries are missing, intake must deterministically run Phase 0."""
        (mock_manager.structure.spec_snapshot_dir / "spec.md").write_text(
            "# Spec\n\nBaseline text.",
            encoding="utf-8",
        )

        lifecycle = PddLifecycle(mock_manager)
        lifecycle.orchestrator.run_phase = MagicMock(return_value={"extraction": "done"})

        result = lifecycle._run_intake()

        lifecycle.orchestrator.run_phase.assert_called_once_with(Phase.EXTRACTION)
        assert result["status"] == "COMPLETED"
        assert "LIBRARIES_MISSING" in result["trigger_reasons"]

        state_path = mock_manager.workspace_path / ".pdd_runs" / mock_manager.run_id / "intake"
        saved = json.loads((state_path / "phase0_state.json").read_text(encoding="utf-8"))
        assert saved["status"] == "COMPLETED"
        assert "LIBRARIES_MISSING" in saved["trigger_reasons"]

    def test_run_intake_skips_when_no_boundary_trigger(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """If signatures and queue are unchanged, intake should skip deterministically."""
        lib_dir = mock_manager.structure.libraries_dir / "lib-a"
        lib_dir.mkdir(parents=True, exist_ok=True)
        (mock_manager.structure.spec_snapshot_dir / "spec.md").write_text(
            "# Spec\n\nStable.",
            encoding="utf-8",
        )
        system_dir = mock_manager.structure.root / "system"
        system_dir.mkdir(parents=True, exist_ok=True)
        intent_path = system_dir / "intent.md"
        intent_path.write_text("# Intent\n\nStable.", encoding="utf-8")

        lifecycle = PddLifecycle(mock_manager)
        snapshot_sig = lifecycle._directory_signature(mock_manager.structure.spec_snapshot_dir)
        intent_sig = lifecycle._content_signature(intent_path)
        state_path = mock_manager.workspace_path / ".pdd_runs" / mock_manager.run_id / "intake"
        state_path.mkdir(parents=True, exist_ok=True)
        (state_path / "phase0_state.json").write_text(
            json.dumps(
                {
                    "status": "COMPLETED",
                    "snapshot_signature": snapshot_sig,
                    "system_intent_signature": intent_sig,
                    "trigger_reasons": [],
                }
            ),
            encoding="utf-8",
        )

        lifecycle.orchestrator.run_phase = MagicMock(return_value={"extraction": "done"})
        result = lifecycle._run_intake()

        lifecycle.orchestrator.run_phase.assert_not_called()
        assert result["status"] == "SKIPPED"
        assert result["trigger_reasons"] == []

        saved = json.loads((state_path / "phase0_state.json").read_text(encoding="utf-8"))
        assert saved["status"] == "SKIPPED"
        assert saved["trigger_reasons"] == []

    def test_run_intake_triggers_phase0_on_system_intent_signature_drift(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Intent signature drift must trigger Phase 0 boundary regeneration."""
        lib_dir = mock_manager.structure.libraries_dir / "lib-a"
        lib_dir.mkdir(parents=True, exist_ok=True)
        (mock_manager.structure.spec_snapshot_dir / "spec.md").write_text(
            "# Spec\n\nStable.",
            encoding="utf-8",
        )
        system_dir = mock_manager.structure.root / "system"
        system_dir.mkdir(parents=True, exist_ok=True)
        intent_path = system_dir / "intent.md"
        intent_path.write_text("# Intent\n\nOld.", encoding="utf-8")

        lifecycle = PddLifecycle(mock_manager)
        snapshot_sig = lifecycle._directory_signature(mock_manager.structure.spec_snapshot_dir)
        previous_intent_sig = lifecycle._content_signature(intent_path)

        state_path = mock_manager.workspace_path / ".pdd_runs" / mock_manager.run_id / "intake"
        state_path.mkdir(parents=True, exist_ok=True)
        (state_path / "phase0_state.json").write_text(
            json.dumps(
                {
                    "status": "COMPLETED",
                    "snapshot_signature": snapshot_sig,
                    "system_intent_signature": previous_intent_sig,
                    "trigger_reasons": [],
                }
            ),
            encoding="utf-8",
        )

        intent_path.write_text("# Intent\n\nNew content.", encoding="utf-8")

        lifecycle.orchestrator.run_phase = MagicMock(return_value={"extraction": "done"})
        result = lifecycle._run_intake()

        lifecycle.orchestrator.run_phase.assert_called_once_with(Phase.EXTRACTION)
        assert result["status"] == "COMPLETED"
        assert "SYSTEM_INTENT_SIGNATURE_CHANGED" in result["trigger_reasons"]

        saved = json.loads((state_path / "phase0_state.json").read_text(encoding="utf-8"))
        assert saved["status"] == "COMPLETED"
        assert "SYSTEM_INTENT_SIGNATURE_CHANGED" in saved["trigger_reasons"]


class TestPddLifecycleQA:
    """Test the QA eval method."""

    @patch("spec_manager.refinement.evals.runner.EvalRunner")
    @patch("spec_manager.refinement.evals.runner.EvalConfig")
    def test_qa_runs_eval_runner(
        self,
        mock_config_class: MagicMock,
        mock_runner_class: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that qa() runs EvalRunner with use_judge=True."""
        mock_report = MagicMock()
        mock_report.pass_rate = 0.85
        mock_report.total_phases = 10
        mock_report.phases_passed = 8

        mock_result1 = MagicMock()
        mock_result1.phase = "phase1"
        mock_result1.passed = True
        mock_result1.detail_metrics = MagicMock(recall=0.9, precision=0.95)

        mock_result2 = MagicMock()
        mock_result2.phase = "phase2"
        mock_result2.passed = False
        mock_result2.detail_metrics = None

        mock_report.results = [mock_result1, mock_result2]

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_report
        mock_runner_class.return_value = mock_runner

        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.qa()

        mock_config_class.assert_called_once_with(use_judge=True)
        mock_runner_class.assert_called_once_with(mock_config)
        mock_runner.run.assert_called_once()

        assert result["pass_rate"] == 0.85
        assert result["total_phases"] == 10
        assert result["phases_passed"] == 8
        assert len(result["results"]) == 2

    @patch("spec_manager.refinement.evals.runner.EvalRunner")
    @patch("spec_manager.refinement.evals.runner.EvalConfig")
    def test_qa_handles_exception(
        self,
        mock_config_class: MagicMock,
        mock_runner_class: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that qa() handles exceptions gracefully."""
        mock_runner = MagicMock()
        mock_runner.run.side_effect = RuntimeError("Eval failed")
        mock_runner_class.return_value = mock_runner

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.qa()

        assert "error" in result
        assert "Eval failed" in result["error"]


class TestLibraryRefinement:
    """Test the _library_refinement method."""

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_library_refinement_success(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _library_refinement with multiple libraries."""
        mock_workflow = MagicMock()
        mock_workflow.run.side_effect = [
            "# Library 1\n\nRefined output 1.",
            "# Library 2\n\nRefined output 2.",
        ]
        mock_workflow_class.return_value = mock_workflow

        lifecycle = PddLifecycle(mock_manager_with_libraries, mode="interactive")
        result = lifecycle._library_refinement()

        assert mock_workflow_class.call_count == 2
        assert mock_workflow.run.call_count == 2

        assert "lib1-test-library" in result
        assert result["lib1-test-library"]["refined"] is True
        assert "lib2-another-library" in result
        assert result["lib2-another-library"]["refined"] is True
        assert "lib3-incomplete" in result
        assert result["lib3-incomplete"]["skipped"] == "no content found"

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_library_refinement_no_changes(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _library_refinement when content doesn't change."""
        mock_workflow = MagicMock()
        mock_workflow.run.side_effect = lambda content: content
        mock_workflow_class.return_value = mock_workflow

        lifecycle = PddLifecycle(mock_manager_with_libraries, mode="interactive")
        result = lifecycle._library_refinement()

        assert result["lib1-test-library"]["refined"] is False

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_library_refinement_interactive_mode_disables_prompt_helper(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Core lifecycle never enables InteractiveWorkflow prompt helper."""
        mock_workflow = MagicMock()
        mock_workflow.run.side_effect = ["refined 1", "refined 2"]
        mock_workflow_class.return_value = mock_workflow

        lifecycle = PddLifecycle(mock_manager_with_libraries, mode="interactive")
        lifecycle._library_refinement()

        assert mock_workflow_class.call_count == 2
        first_call_kwargs = mock_workflow_class.call_args_list[0].kwargs
        assert first_call_kwargs["interactive"] is False

    def test_library_refinement_no_libraries_dir(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _library_refinement when libraries directory doesn't exist."""
        mock_manager.structure.libraries_dir.rmdir()

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._library_refinement()

        assert "note" in result
        assert "No libraries directory" in result["note"]

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_library_refinement_respects_mode(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _library_refinement passes correct mode to InteractiveWorkflow."""
        steering_file = tmp_path / "steering.json"
        steering_file.write_text("{}", encoding="utf-8")

        lifecycle = PddLifecycle(
            mock_manager_with_libraries,
            mode="steering",
            use_research=True,
            use_evidence_store=True,
            steering_path=steering_file,
            max_refinement_iterations=3,
        )

        mock_workflow = MagicMock()
        mock_workflow.run.return_value = "refined spec"
        mock_workflow_class.return_value = mock_workflow

        lifecycle._library_refinement()

        assert mock_workflow_class.call_count == 2
        call_kwargs = mock_workflow_class.call_args_list[0][1]
        assert call_kwargs["workspace"] == mock_manager_with_libraries.workspace_path
        assert call_kwargs["interactive"] is False
        assert call_kwargs["steering_path"] == steering_file
        assert call_kwargs["use_research"] is True
        assert call_kwargs["use_evidence_store"] is True
        assert call_kwargs["max_iterations"] == 3


class TestCheckAlignment:
    """Test the _check_alignment internal method."""

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_check_alignment_with_charter(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _check_alignment with libraries that have charters."""
        mock_run_agent.return_value = json.dumps(
            {
                "drift_findings": [
                    {"type": "requirement_drift", "severity": "high"},
                ],
                "reward_hacking_findings": [
                    {"type": "reward_hack", "severity": "medium"},
                ],
            }
        )

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._check_alignment()

        mock_run_agent.assert_called_once()
        call_kwargs = mock_run_agent.call_args[1]
        assert call_kwargs["agent_name"] == "opus-alignment-checker"
        assert "Charter:" in call_kwargs["prompt"]
        assert "Current Code:" in call_kwargs["prompt"]

        assert result["libraries_checked"] == 1
        assert result["drift_findings"] == 1
        assert result["reward_hacking_findings"] == 1
        assert len(result["errors"]) == 0

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_check_alignment_no_charter_skipped(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _check_alignment skips libraries without charters."""
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        lifecycle._check_alignment()

        # Only lib1 has charter
        assert mock_run_agent.call_count == 1

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_check_alignment_handles_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _check_alignment handles agent errors gracefully."""
        mock_run_agent.side_effect = RuntimeError("Agent failed")

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._check_alignment()

        assert len(result["errors"]) == 1
        assert result["errors"][0]["lib_id"] == "lib1-test-library"

    def test_check_alignment_no_libraries_dir(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _check_alignment when libraries directory doesn't exist."""
        mock_manager.structure.libraries_dir.rmdir()

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._check_alignment()

        assert "note" in result


class TestGenerateOverview:
    """Test the _generate_overview internal method."""

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_generate_overview_success(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _generate_overview with multiple libraries."""
        mock_run_agent.side_effect = [
            "Overview for library 1 in markdown format.",
            "Overview for library 2 in markdown format.",
        ]

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._generate_overview()

        assert mock_run_agent.call_count == 2
        assert result["libraries_processed"] == 2
        assert len(result["errors"]) == 0

        overview_path = mock_manager_with_libraries.structure.root / "reports" / "overview.md"
        assert overview_path.exists()

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_generate_overview_handles_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _generate_overview handles agent errors gracefully."""
        mock_run_agent.side_effect = [
            "Overview for library 1.",
            RuntimeError("Agent failed for lib2"),
        ]

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._generate_overview()

        assert result["libraries_processed"] == 1
        assert len(result["errors"]) == 1

    def test_generate_overview_no_libraries_dir(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _generate_overview when libraries directory doesn't exist."""
        mock_manager.structure.libraries_dir.rmdir()

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._generate_overview()

        assert "note" in result


class TestArchitecturalRefinement:
    """Test the _architectural_refinement method."""

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_architectural_refinement_proposes_candidates(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _architectural_refinement proposes candidates and emits tickets."""
        mock_run_agent.return_value = json.dumps(
            {
                "candidates": [
                    {"name": "Microservices", "components": ["A", "B"]},
                    {"name": "Monolithic", "components": ["C"]},
                    {"name": "Hybrid", "components": ["D", "E", "F"]},
                ],
                "issues": [
                    {
                        "severity": "MAJOR",
                        "file": "risk_engine.py",
                        "description": "Missing error handling",
                    },
                ],
            }
        )

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._architectural_refinement()

        mock_run_agent.assert_called_once()
        assert result["candidates_proposed"] == 3
        assert result["demotion_tickets"] == 1

        # Verify demotion tickets written
        tickets_path = (
            mock_manager_with_libraries.structure.root
            / "reports"
            / "architecture_demotion_tickets.json"
        )
        assert tickets_path.exists()
        tickets_data = json.loads(tickets_path.read_text(encoding="utf-8"))
        assert tickets_data[0]["source"] == "ARCH_GATE"

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_architectural_refinement_handles_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _architectural_refinement handles agent errors gracefully."""
        mock_run_agent.side_effect = RuntimeError("Architecture proposal failed")

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._architectural_refinement()

        assert "error" in result

    def test_architectural_refinement_no_code(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _architectural_refinement when no code exists."""
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._architectural_refinement()

        assert "note" in result
        assert "No code found" in result["note"]


class TestCodeQualityRefinement:
    """Test the _code_quality_refinement method."""

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_code_quality_refinement_runs_all_reviewers(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _code_quality_refinement runs all 4 reviewers for each file."""
        # 4 reviewers * 2 files = 8 calls
        mock_run_agent.side_effect = [
            json.dumps({"findings": [{"issue": "clarity issue 1"}]}),
            json.dumps({"findings": [{"issue": "completeness issue 1"}]}),
            json.dumps({"findings": [{"issue": "consistency issue 1"}]}),
            json.dumps({"findings": [{"issue": "correctness issue 1"}]}),
            json.dumps({"findings": [{"issue": "clarity issue 2"}]}),
            json.dumps({"findings": [{"issue": "completeness issue 2"}]}),
            json.dumps({"findings": []}),
            json.dumps({"findings": [{"issue": "correctness issue 2"}]}),
        ]

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._code_quality_refinement()

        assert mock_run_agent.call_count == 8
        assert result["files_reviewed"] == 2
        assert result["total_findings"] == 7

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_code_quality_refinement_handles_reviewer_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _code_quality_refinement handles individual reviewer errors."""
        mock_run_agent.side_effect = [
            json.dumps({"findings": [{"issue": "finding 1"}]}),
            RuntimeError("Reviewer failed"),
            json.dumps({"findings": [{"issue": "finding 2"}]}),
            json.dumps({"findings": [{"issue": "finding 3"}]}),
            json.dumps({"findings": [{"issue": "finding 4"}]}),
            json.dumps({"findings": [{"issue": "finding 5"}]}),
            json.dumps({"findings": [{"issue": "finding 6"}]}),
            json.dumps({"findings": [{"issue": "finding 7"}]}),
        ]

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._code_quality_refinement()

        assert result["total_findings"] == 7

    def test_code_quality_refinement_no_code(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _code_quality_refinement when no code exists."""
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._code_quality_refinement()

        assert "note" in result
        assert "No code found" in result["note"]


class TestL1WithApproval:
    """Test the _run_l1_with_approval method and approval loop."""

    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_auto_mode_auto_approves(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that auto mode auto-approves without prompting."""
        mock_layer.return_value = {"layer": "l1", "slices": {}}
        mock_overview.return_value = {"overview_path": "/path"}
        mock_align.return_value = {"libraries_checked": 0}

        lifecycle = PddLifecycle(mock_manager, mode="auto")
        l1_result, approval = lifecycle._run_l1_with_approval()

        assert approval["approved"] is True
        assert approval["mode"] == "auto"
        mock_layer.assert_called_once_with("l1")

    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_steering_mode_auto_approves(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that steering mode auto-approves."""
        mock_layer.return_value = {"layer": "l1"}
        mock_overview.return_value = {}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="steering")
        l1_result, approval = lifecycle._run_l1_with_approval()

        assert approval["approved"] is True
        assert approval["mode"] == "steering"

    @patch("builtins.input", side_effect=AssertionError("input fallback should not be used"))
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_interactive_mode_returns_waiting_without_input(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Interactive mode emits a lifecycle signal and returns WAITING."""
        mock_layer.return_value = {"layer": "l1", "slices": {}}
        mock_overview.return_value = {"overview_path": "/some/path/overview.md"}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        _, approval = lifecycle._run_l1_with_approval()

        assert approval["approved"] is False
        assert approval["mode"] == "interactive"
        assert approval["status"] == "WAITING"
        assert approval["checkpoint"] == "l1_approval"
        mock_layer.assert_called_once_with("l1")
        mock_input.assert_not_called()

        signal_path = (
            mock_manager.workspace_path
            / ".pdd_runs"
            / mock_manager.run_id
            / "coordination"
            / "user_questions.jsonl"
        )
        assert signal_path.exists()
        lines = signal_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["source"]["kind"] == "PDD_LIFECYCLE"
        assert payload["source"]["signal_id"] == "l1_approval"
        assert payload["question"]["taxonomy_hint"] == "VALIDATION"


class TestInteractiveCheckpointSignals:
    """Interactive lifecycle checkpoints use signal emission, never input()."""

    def test_lifecycle_checkpoint_taxonomy_uses_canonical_categories(self) -> None:
        assert lifecycle_module._LIFECYCLE_CHECKPOINT_TAXONOMY == {
            "l1_approval": "VALIDATION",
            "l2_checkpoint": "SCOPE",
            "release_signoff": "TRADEOFF",
        }
        assert set(lifecycle_module._LIFECYCLE_CHECKPOINT_TAXONOMY.values()) == {
            "VALIDATION",
            "SCOPE",
            "TRADEOFF",
        }

    @patch("builtins.input", side_effect=AssertionError("input fallback should not be used"))
    def test_l2_checkpoint_emits_waiting_signal_without_input(
        self,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        result = lifecycle._request_l2_checkpoint({"slices": []})

        assert result["approved"] is False
        assert result["status"] == "WAITING"
        assert result["checkpoint"] == "l2_checkpoint"
        mock_input.assert_not_called()

        signal_path = (
            mock_manager.workspace_path
            / ".pdd_runs"
            / mock_manager.run_id
            / "coordination"
            / "user_questions.jsonl"
        )
        lines = signal_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["source"]["signal_id"] == "l2_checkpoint"
        assert payload["source"]["kind"] == "PDD_LIFECYCLE"
        assert payload["question"]["taxonomy_hint"] == "SCOPE"

    @patch("builtins.input", side_effect=AssertionError("input fallback should not be used"))
    def test_release_signoff_emits_waiting_signal_without_input(
        self,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        result = lifecycle._request_release_signoff(
            {
                "scorecard": {"overall_pass": True},
                "final_governance": {"passed": True, "error": ""},
            }
        )

        assert result["approved"] is False
        assert result["status"] == "WAITING"
        assert result["checkpoint"] == "release_signoff"
        mock_input.assert_not_called()

        signal_path = (
            mock_manager.workspace_path
            / ".pdd_runs"
            / mock_manager.run_id
            / "coordination"
            / "user_questions.jsonl"
        )
        lines = signal_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["source"]["signal_id"] == "release_signoff"
        assert payload["source"]["kind"] == "PDD_LIFECYCLE"
        assert payload["question"]["taxonomy_hint"] == "TRADEOFF"

    def test_emit_checkpoint_signal_rejects_unknown_checkpoint(
        self,
        mock_manager: MagicMock,
    ) -> None:
        lifecycle = PddLifecycle(mock_manager, mode="interactive")

        with pytest.raises(ValueError, match="Unknown lifecycle checkpoint"):
            lifecycle._emit_checkpoint_signal(
                checkpoint="legacy_checkpoint",
                layer="l1",
                question_text="Should we proceed?",
                canonical_key_hint="lifecycle.legacy.checkpoint",
            )


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_libraries_directory(self, mock_manager: MagicMock) -> None:
        """Test handling of empty libraries directory."""
        lifecycle = PddLifecycle(mock_manager)

        refine_result = lifecycle._library_refinement()
        align_result = lifecycle._check_alignment()
        overview_result = lifecycle._generate_overview()
        arch_result = lifecycle._architectural_refinement()
        quality_result = lifecycle._code_quality_refinement()

        assert len(refine_result) == 0 or "note" in refine_result
        assert align_result["libraries_checked"] == 0
        assert overview_result["libraries_processed"] == 0
        assert "note" in arch_result
        assert "note" in quality_result

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_library_with_empty_details(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test handling of library with empty details directory."""
        lib_dir = mock_manager_with_libraries.structure.libraries_dir / "lib4-empty"
        lib_dir.mkdir(parents=True, exist_ok=True)
        details_dir = lib_dir / "details"
        details_dir.mkdir(parents=True, exist_ok=True)

        mock_workflow = MagicMock()
        mock_workflow.run.return_value = "refined"
        mock_workflow_class.return_value = mock_workflow

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._library_refinement()

        assert "lib4-empty" in result

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_file_not_directory_in_libraries(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test handling of files (not directories) in libraries directory."""
        (mock_manager_with_libraries.structure.libraries_dir / "not_a_dir.txt").write_text(
            "This is a file, not a directory", encoding="utf-8"
        )

        mock_workflow = MagicMock()
        mock_workflow.run.return_value = "refined spec"
        mock_workflow_class.return_value = mock_workflow

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._library_refinement()

        assert "not_a_dir.txt" not in result
        assert "lib1-test-library" in result

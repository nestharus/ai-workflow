"""Component tests for PddLifecycle orchestrator.

Tests the L1 → L2 → L3 layer pipeline with typed refinement.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.orchestration.pdd_lifecycle import PddLifecycle


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
        mock_manager: MagicMock,
    ) -> None:
        """Test that run() calls setup_layers and cleanup when worktree manager exists."""
        mock_intake.return_value = {}
        mock_l1_approval.return_value = ({}, {"approved": True})
        mock_transition.return_value = {}
        mock_layer.return_value = {}
        mock_qa.return_value = {}

        mock_wm = MagicMock()
        mock_wm.setup_layers.return_value = {"base_ref": "HEAD", "worktrees": []}
        mock_wm.cleanup.return_value = {"removed": []}

        lifecycle = PddLifecycle(mock_manager, worktree_manager=mock_wm)
        result = lifecycle.run()

        mock_wm.setup_layers.assert_called_once()
        mock_wm.cleanup.assert_called_once()
        assert "setup" in result
        assert "cleanup" in result


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

    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_architectural_refinement")
    def test_l1_to_l2_no_demotions(
        self,
        mock_arch_refine: MagicMock,
        mock_slices: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test L1→L2 transition without demotions."""
        mock_arch_refine.return_value = {"demotion_tickets": 0}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_transition("l1", "l2")

        assert result["from"] == "l1"
        assert result["to"] == "l2"
        mock_arch_refine.assert_called_once()
        mock_slices.assert_not_called()  # No rework needed

    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_architectural_refinement")
    def test_l1_to_l2_with_demotions(
        self,
        mock_arch_refine: MagicMock,
        mock_slices: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test L1→L2 transition with demotions triggers L1 rework."""
        mock_arch_refine.return_value = {"demotion_tickets": 2}
        mock_slices.return_value = {"all_complete": True}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_transition("l1", "l2")

        mock_arch_refine.assert_called_once()
        mock_slices.assert_called_once_with("l1")  # Rework at L1
        assert "rework" in result

    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_code_quality_refinement")
    def test_l2_to_l3_transition(
        self,
        mock_cq_refine: MagicMock,
        mock_slices: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test L2→L3 transition calls code quality refinement."""
        mock_cq_refine.return_value = {"demotion_tickets": 0}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._run_transition("l2", "l3")

        assert result["from"] == "l2"
        assert result["to"] == "l3"
        mock_cq_refine.assert_called_once()

    @patch.object(PddLifecycle, "_run_slices_at_layer")
    @patch.object(PddLifecycle, "_architectural_refinement")
    def test_transition_propagates_with_worktree_manager(
        self,
        mock_arch_refine: MagicMock,
        mock_slices: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that transition propagates clean → next dirty."""
        mock_arch_refine.return_value = {"demotion_tickets": 0}

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

    @patch("builtins.input", return_value="a")
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_interactive_mode_approve(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that interactive mode with 'a' input approves."""
        mock_layer.return_value = {"layer": "l1", "overview": {}}
        mock_overview.return_value = {"overview_path": "/some/path/overview.md"}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        l1_result, approval = lifecycle._run_l1_with_approval()

        assert approval["approved"] is True
        assert approval["mode"] == "interactive"

    @patch("builtins.input", return_value="")
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_interactive_mode_empty_input_approves(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that empty input (just Enter) approves."""
        mock_layer.return_value = {"layer": "l1"}
        mock_overview.return_value = {}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        l1_result, approval = lifecycle._run_l1_with_approval()

        assert approval["approved"] is True

    @patch("builtins.input", side_effect=["f", "needs more detail", "a"])
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_interactive_mode_feedback_then_approve(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test feedback loop: feedback on first iteration, approve on second."""
        mock_layer.return_value = {"layer": "l1"}
        mock_overview.return_value = {}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        l1_result, approval = lifecycle._run_l1_with_approval()

        assert mock_layer.call_count == 2
        assert approval["approved"] is True
        assert approval["iteration"] == 2

    @patch("builtins.input", side_effect=EOFError)
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_interactive_mode_eof_approves(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that EOFError (non-interactive terminal) auto-approves."""
        mock_layer.return_value = {"layer": "l1"}
        mock_overview.return_value = {}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        l1_result, approval = lifecycle._run_l1_with_approval()

        assert approval["approved"] is True

    @patch("builtins.input", return_value="q")
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_interactive_mode_quit_raises(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that 'q' input raises KeyboardInterrupt."""
        mock_layer.return_value = {"layer": "l1"}
        mock_overview.return_value = {}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        with pytest.raises(KeyboardInterrupt):
            lifecycle._run_l1_with_approval()

    @patch(
        "builtins.input",
        side_effect=["f", "fix this", "f", "fix that", "f", "fix more"],
    )
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_max_iterations_auto_approves(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that max iterations reached leads to auto-approval."""
        mock_layer.return_value = {"layer": "l1"}
        mock_overview.return_value = {}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive", max_approval_iterations=3)
        l1_result, approval = lifecycle._run_l1_with_approval()

        assert approval["approved"] is True
        assert approval["auto_approved"] is True
        assert approval["reason"] == "max_iterations_reached"
        assert mock_layer.call_count == 3

    @patch("builtins.input", side_effect=["f", "feedback text"])
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_run_layer")
    def test_feedback_written_to_file(
        self,
        mock_layer: MagicMock,
        mock_overview: MagicMock,
        mock_align: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that feedback is written to reports directory."""
        mock_layer.return_value = {"layer": "l1"}
        mock_overview.return_value = {}
        mock_align.return_value = {}

        lifecycle = PddLifecycle(mock_manager, mode="interactive", max_approval_iterations=1)
        l1_result, approval = lifecycle._run_l1_with_approval()

        feedback_path = mock_manager.structure.root / "reports" / "feedback_iteration_1.txt"
        assert feedback_path.exists()
        assert feedback_path.read_text(encoding="utf-8") == "feedback text"


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

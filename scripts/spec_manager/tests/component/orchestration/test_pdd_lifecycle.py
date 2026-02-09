"""Component tests for PddLifecycle orchestrator.

Tests the 4-phase PDD lifecycle: Build -> QA -> Architecture -> Code Quality.
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

    # Create minimal workspace structure
    libraries_dir = run_dir / "libraries"
    libraries_dir.mkdir(parents=True, exist_ok=True)

    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Create mock manager with proper structure
    manager = MagicMock()
    manager.workspace_path = run_dir
    manager.structure = MagicMock()
    manager.structure.root = run_dir
    manager.structure.libraries_dir = libraries_dir

    return manager


@pytest.fixture
def mock_manager_with_libraries(mock_manager: MagicMock) -> MagicMock:
    """Create a MagicMock with sample library directories and specs."""
    libraries_dir = mock_manager.structure.libraries_dir
    
    # Library 1: with spec and charter
    lib1_dir = libraries_dir / "lib1-test-library"
    lib1_dir.mkdir(parents=True, exist_ok=True)
    (lib1_dir / "spec.md").write_text(
        "# Library 1\n\nThis is a test library spec.",
        encoding="utf-8"
    )
    (lib1_dir / "charter.md").write_text(
        "# Charter 1\n\nOriginal requirements for library 1.",
        encoding="utf-8"
    )
    
    # Library 2: with spec only (no charter)
    lib2_dir = libraries_dir / "lib2-another-library"
    lib2_dir.mkdir(parents=True, exist_ok=True)
    (lib2_dir / "spec.md").write_text(
        "# Library 2\n\nAnother test library spec.",
        encoding="utf-8"
    )
    
    # Library 3: directory only (no spec)
    lib3_dir = libraries_dir / "lib3-incomplete"
    lib3_dir.mkdir(parents=True, exist_ok=True)
    
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

    @patch.object(PddLifecycle, "build_with_approval")
    @patch.object(PddLifecycle, "qa")
    @patch.object(PddLifecycle, "architecture")
    @patch.object(PddLifecycle, "code_quality")
    def test_run_calls_all_phases(
        self,
        mock_code_quality: MagicMock,
        mock_architecture: MagicMock,
        mock_qa: MagicMock,
        mock_build_with_approval: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that run() calls all 4 lifecycle phases in order."""
        # Setup return values
        mock_build_with_approval.return_value = (
            {"status": "build_complete"},
            {"approved": True, "iteration": 1},
        )
        mock_qa.return_value = {"status": "qa_complete"}
        mock_architecture.return_value = {"status": "architecture_complete"}
        mock_code_quality.return_value = {"status": "quality_complete"}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.run()

        # Verify all phases called in order
        mock_build_with_approval.assert_called_once()
        mock_qa.assert_called_once()
        mock_architecture.assert_called_once()
        mock_code_quality.assert_called_once()

        # Verify result structure
        assert result["build"] == {"status": "build_complete"}
        assert result["approval"]["approved"] is True
        assert result["qa"] == {"status": "qa_complete"}
        assert result["architecture"] == {"status": "architecture_complete"}
        assert result["code_quality"] == {"status": "quality_complete"}


class TestPddLifecycleBuild:
    """Test the build phase."""

    @patch.object(PddLifecycle, "_generate_overview")
    @patch.object(PddLifecycle, "_check_alignment")
    @patch.object(PddLifecycle, "_refine_libraries")
    @patch("spec_manager.orchestration.pdd_lifecycle.PddOrchestrator")
    def test_build_calls_all_steps(
        self,
        mock_orchestrator_class: MagicMock,
        mock_refine: MagicMock,
        mock_align: MagicMock,
        mock_overview: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that build() calls all 4 build steps in order."""
        # Setup mock orchestrator
        mock_orchestrator = MagicMock()
        mock_orchestrator.run.return_value = {"phase": "pipeline_complete"}
        mock_orchestrator_class.return_value = mock_orchestrator
        
        # Setup return values
        mock_refine.return_value = {"refined": 2}
        mock_align.return_value = {"aligned": True}
        mock_overview.return_value = {"overview": "generated"}
        
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.build()
        
        # Verify all steps called
        mock_orchestrator.run.assert_called_once()
        mock_refine.assert_called_once()
        mock_align.assert_called_once()
        mock_overview.assert_called_once()
        
        # Verify result structure
        assert result["pipeline"] == {"phase": "pipeline_complete"}
        assert result["refinement"] == {"refined": 2}
        assert result["alignment"] == {"aligned": True}
        assert result["overview"] == {"overview": "generated"}


class TestPddLifecycleQA:
    """Test the QA phase."""

    @patch("spec_manager.refinement.evals.runner.EvalRunner")
    @patch("spec_manager.refinement.evals.runner.EvalConfig")
    def test_qa_runs_eval_runner(
        self,
        mock_config_class: MagicMock,
        mock_runner_class: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that qa() runs EvalRunner with use_judge=True."""
        # Setup mock report
        mock_report = MagicMock()
        mock_report.pass_rate = 0.85
        mock_report.total_phases = 10
        mock_report.phases_passed = 8
        
        # Setup mock results
        mock_result1 = MagicMock()
        mock_result1.phase = "phase1"
        mock_result1.passed = True
        mock_result1.detail_metrics = MagicMock(recall=0.9, precision=0.95)
        
        mock_result2 = MagicMock()
        mock_result2.phase = "phase2"
        mock_result2.passed = False
        mock_result2.detail_metrics = None
        
        mock_report.results = [mock_result1, mock_result2]
        
        # Setup mock runner
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_report
        mock_runner_class.return_value = mock_runner
        
        # Setup mock config
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.qa()
        
        # Verify EvalConfig created with use_judge=True
        mock_config_class.assert_called_once_with(use_judge=True)
        
        # Verify EvalRunner created with config
        mock_runner_class.assert_called_once_with(mock_config)
        
        # Verify runner.run() called
        mock_runner.run.assert_called_once()
        
        # Verify result structure
        assert result["pass_rate"] == 0.85
        assert result["total_phases"] == 10
        assert result["phases_passed"] == 8
        assert len(result["results"]) == 2
        assert result["results"][0]["phase"] == "phase1"
        assert result["results"][0]["passed"] is True
        assert result["results"][0]["recall"] == 0.9
        assert result["results"][0]["precision"] == 0.95
        assert result["results"][1]["phase"] == "phase2"
        assert result["results"][1]["passed"] is False
        assert result["results"][1]["recall"] is None

    @patch("spec_manager.refinement.evals.runner.EvalRunner")
    @patch("spec_manager.refinement.evals.runner.EvalConfig")
    def test_qa_handles_exception(
        self,
        mock_config_class: MagicMock,
        mock_runner_class: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that qa() handles exceptions gracefully."""
        # Setup mock runner to raise exception
        mock_runner = MagicMock()
        mock_runner.run.side_effect = RuntimeError("Eval failed")
        mock_runner_class.return_value = mock_runner
        
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.qa()
        
        assert "error" in result
        assert "Eval failed" in result["error"]


class TestRefineLibraries:
    """Test the _refine_libraries internal method."""

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_refine_libraries_success(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _refine_libraries with multiple libraries."""
        # Setup mock workflow
        mock_workflow = MagicMock()
        mock_workflow.run.side_effect = [
            "# Library 1\n\nRefined spec 1.",
            "# Library 2\n\nRefined spec 2.",
        ]
        mock_workflow_class.return_value = mock_workflow
        
        lifecycle = PddLifecycle(mock_manager_with_libraries, mode="interactive")
        result = lifecycle._refine_libraries()
        
        # Verify workflow created twice (for lib1 and lib2, not lib3 which has no spec)
        assert mock_workflow_class.call_count == 2
        
        # Verify workflow.run() called twice
        assert mock_workflow.run.call_count == 2
        
        # Verify result structure
        assert "lib1-test-library" in result
        assert result["lib1-test-library"]["refined"] is True
        assert "lib2-another-library" in result
        assert result["lib2-another-library"]["refined"] is True
        assert "lib3-incomplete" in result
        assert result["lib3-incomplete"]["skipped"] == "no spec.md"

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_refine_libraries_no_changes(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _refine_libraries when spec doesn't change."""
        # Read original specs
        lib1_path = mock_manager_with_libraries.structure.libraries_dir / "lib1-test-library" / "spec.md"
        original_spec = lib1_path.read_text(encoding="utf-8")
        
        # Setup mock workflow to return same content
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = original_spec
        mock_workflow_class.return_value = mock_workflow
        
        lifecycle = PddLifecycle(mock_manager_with_libraries, mode="interactive")
        result = lifecycle._refine_libraries()
        
        # Verify no change detected
        assert result["lib1-test-library"]["refined"] is False

    def test_refine_libraries_no_libraries_dir(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _refine_libraries when libraries directory doesn't exist."""
        # Remove libraries directory
        mock_manager.structure.libraries_dir.rmdir()
        
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._refine_libraries()
        
        assert "note" in result
        assert "No libraries directory" in result["note"]

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_refine_libraries_respects_mode(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test that _refine_libraries passes correct mode to InteractiveWorkflow."""
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
        
        # Setup mock workflow
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = "refined spec"
        mock_workflow_class.return_value = mock_workflow
        
        lifecycle._refine_libraries()
        
        # Verify InteractiveWorkflow called with correct parameters
        assert mock_workflow_class.call_count == 2
        call_kwargs = mock_workflow_class.call_args_list[0][1]
        assert call_kwargs["workspace"] == mock_manager_with_libraries.workspace_path
        assert call_kwargs["interactive"] is False  # mode is "steering", not "interactive"
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
        # Setup mock agent response
        mock_run_agent.return_value = json.dumps({
            "drift_findings": [
                {"type": "requirement_drift", "severity": "high"},
            ],
            "reward_hacking_findings": [
                {"type": "reward_hack", "severity": "medium"},
            ],
        })
        
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._check_alignment()
        
        # Verify run_agent called once (only lib1 has charter)
        mock_run_agent.assert_called_once()
        call_kwargs = mock_run_agent.call_args[1]
        assert call_kwargs["agent_name"] == "opus-alignment-checker"
        assert "Charter:" in call_kwargs["prompt"]
        assert "Current Spec:" in call_kwargs["prompt"]
        assert call_kwargs["workspace"] == mock_manager_with_libraries.workspace_path
        
        # Verify result structure
        assert result["libraries_checked"] == 1
        assert result["drift_findings"] == 1
        assert result["reward_hacking_findings"] == 1
        assert len(result["errors"]) == 0
        
        # Verify report written
        report_path = mock_manager_with_libraries.structure.root / "reports" / "alignment_report.json"
        assert report_path.exists()
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        assert report_data["libraries_checked"] == 1

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_check_alignment_no_charter_skipped(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _check_alignment skips libraries without charters."""
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._check_alignment()
        
        # Only lib1 has charter, so only 1 call
        assert mock_run_agent.call_count == 1

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_check_alignment_handles_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _check_alignment handles agent errors gracefully."""
        # Setup mock agent to raise exception
        mock_run_agent.side_effect = RuntimeError("Agent failed")
        
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._check_alignment()
        
        # Verify error captured
        assert len(result["errors"]) == 1
        assert result["errors"][0]["lib_id"] == "lib1-test-library"
        assert "Agent failed" in result["errors"][0]["error"]

    def test_check_alignment_no_libraries_dir(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _check_alignment when libraries directory doesn't exist."""
        # Remove libraries directory
        mock_manager.structure.libraries_dir.rmdir()
        
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._check_alignment()
        
        assert "note" in result
        assert "No libraries directory" in result["note"]


class TestGenerateOverview:
    """Test the _generate_overview internal method."""

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_generate_overview_success(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _generate_overview with multiple libraries."""
        # Setup mock agent responses
        mock_run_agent.side_effect = [
            "Overview for library 1 in markdown format.",
            "Overview for library 2 in markdown format.",
        ]
        
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._generate_overview()
        
        # Verify run_agent called twice (lib1 and lib2 have specs)
        assert mock_run_agent.call_count == 2
        
        # Verify first call
        call_kwargs = mock_run_agent.call_args_list[0][1]
        assert call_kwargs["agent_name"] == "opus-overview-writer"
        assert "Library ID: lib1-test-library" in call_kwargs["prompt"]
        assert call_kwargs["workspace"] == mock_manager_with_libraries.workspace_path
        
        # Verify result
        assert result["libraries_processed"] == 2
        assert len(result["errors"]) == 0
        
        # Verify overview file written
        overview_path = mock_manager_with_libraries.structure.root / "reports" / "overview.md"
        assert overview_path.exists()
        content = overview_path.read_text(encoding="utf-8")
        assert "# Project Overview" in content
        assert "## lib1-test-library" in content
        assert "## lib2-another-library" in content

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_generate_overview_handles_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test _generate_overview handles agent errors gracefully."""
        # First call succeeds, second fails
        mock_run_agent.side_effect = [
            "Overview for library 1.",
            RuntimeError("Agent failed for lib2"),
        ]
        
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._generate_overview()
        
        # Verify partial success
        assert result["libraries_processed"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["lib_id"] == "lib2-another-library"

    def test_generate_overview_no_libraries_dir(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test _generate_overview when libraries directory doesn't exist."""
        # Remove libraries directory
        mock_manager.structure.libraries_dir.rmdir()
        
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._generate_overview()
        
        assert "note" in result
        assert "No libraries directory" in result["note"]


class TestArchitecture:
    """Test the architecture phase."""

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_architecture_proposes_candidates(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test architecture() proposes architecture candidates."""
        # Setup mock agent response
        mock_run_agent.return_value = json.dumps({
            "candidates": [
                {"name": "Microservices", "components": ["A", "B"]},
                {"name": "Monolithic", "components": ["C"]},
                {"name": "Hybrid", "components": ["D", "E", "F"]},
            ]
        })
        
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle.architecture()
        
        # Verify run_agent called
        mock_run_agent.assert_called_once()
        call_kwargs = mock_run_agent.call_args[1]
        assert call_kwargs["agent_name"] == "opus-architecture-proposer"
        assert "library specs" in call_kwargs["prompt"]
        assert call_kwargs["workspace"] == mock_manager_with_libraries.workspace_path
        
        # Verify result
        assert result["candidates_proposed"] == 3
        assert result["proposals_path"] == "reports/architecture_proposals.json"
        
        # Verify proposals written
        proposals_path = mock_manager_with_libraries.structure.root / "reports" / "architecture_proposals.json"
        assert proposals_path.exists()
        proposals_data = json.loads(proposals_path.read_text(encoding="utf-8"))
        assert len(proposals_data["candidates"]) == 3

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_architecture_handles_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test architecture() handles agent errors gracefully."""
        # Setup mock agent to raise exception
        mock_run_agent.side_effect = RuntimeError("Architecture proposal failed")
        
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle.architecture()
        
        assert "error" in result
        assert "Architecture proposal failed" in result["error"]

    def test_architecture_no_libraries(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test architecture() when no library specs exist."""
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.architecture()
        
        assert "note" in result
        assert "No library specs found" in result["note"]


class TestCodeQuality:
    """Test the code_quality phase."""

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_code_quality_runs_all_reviewers(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test code_quality() runs all 4 reviewers for each library."""
        # Setup mock agent responses (4 reviewers * 2 libraries = 8 calls)
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
        result = lifecycle.code_quality()
        
        # Verify run_agent called 8 times (4 reviewers * 2 libraries)
        assert mock_run_agent.call_count == 8
        
        # Verify reviewer names used
        reviewer_names = {call[1]["agent_name"] for call in mock_run_agent.call_args_list}
        assert reviewer_names == {
            "chatgpt-clarity-reviewer",
            "chatgpt-completeness-reviewer",
            "chatgpt-consistency-reviewer",
            "chatgpt-correctness-reviewer",
        }
        
        # Verify result
        assert result["libraries_reviewed"] == 2
        assert result["total_findings"] == 7
        assert result["report_path"] == "reports/code_quality_report.json"
        
        # Verify report written
        report_path = mock_manager_with_libraries.structure.root / "reports" / "code_quality_report.json"
        assert report_path.exists()
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        assert len(report_data["findings"]) == 7
        
        # Verify findings have lib_id and reviewer
        for finding in report_data["findings"]:
            assert "lib_id" in finding
            assert "reviewer" in finding

    @patch("spec_manager.core.agent_utils.run_agent")
    def test_code_quality_handles_reviewer_error(
        self,
        mock_run_agent: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test code_quality() handles individual reviewer errors gracefully."""
        # Setup mock agent responses with one failure
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
        result = lifecycle.code_quality()
        
        # Should still have 7 findings despite one error
        assert result["total_findings"] == 7

    def test_code_quality_no_libraries(
        self,
        mock_manager: MagicMock,
    ) -> None:
        """Test code_quality() when no library specs exist."""
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.code_quality()
        
        assert "note" in result
        assert "No library specs found" in result["note"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_libraries_directory(self, mock_manager: MagicMock) -> None:
        """Test handling of empty libraries directory."""
        lifecycle = PddLifecycle(mock_manager)

        # All methods should handle empty libraries gracefully
        refine_result = lifecycle._refine_libraries()
        align_result = lifecycle._check_alignment()
        overview_result = lifecycle._generate_overview()
        arch_result = lifecycle.architecture()
        quality_result = lifecycle.code_quality()

        # Verify graceful handling
        # refine_result is empty dict when no libraries
        assert len(refine_result) == 0 or "note" in refine_result

        # align_result returns structure with zero counts
        assert align_result["libraries_checked"] == 0
        assert align_result["drift_findings"] == 0

        # overview_result returns structure with zero counts
        assert overview_result["libraries_processed"] == 0

        # arch_result and quality_result return note when no libraries
        assert "note" in arch_result
        assert "note" in quality_result

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_library_with_empty_spec(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test handling of library with empty spec file."""
        # Create library with empty spec
        lib_dir = mock_manager_with_libraries.structure.libraries_dir / "lib4-empty"
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "spec.md").write_text("", encoding="utf-8")
        
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = ""
        mock_workflow_class.return_value = mock_workflow
        
        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._refine_libraries()
        
        # Should process the empty spec
        assert "lib4-empty" in result

    @patch("spec_manager.refinement.interactive.workflow.InteractiveWorkflow")
    def test_file_not_directory_in_libraries(
        self,
        mock_workflow_class: MagicMock,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test handling of files (not directories) in libraries directory."""
        # Create a file in libraries directory
        (mock_manager_with_libraries.structure.libraries_dir / "not_a_dir.txt").write_text(
            "This is a file, not a directory",
            encoding="utf-8"
        )

        # Setup mock workflow
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = "refined spec"
        mock_workflow_class.return_value = mock_workflow

        lifecycle = PddLifecycle(mock_manager_with_libraries)
        result = lifecycle._refine_libraries()

        # Should skip the file and only process directories
        assert "not_a_dir.txt" not in result
        assert "lib1-test-library" in result


class TestBuildWithApproval:
    """Test the build_with_approval method and approval loop."""

    @patch.object(PddLifecycle, "build")
    def test_auto_mode_auto_approves(
        self,
        mock_build: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that auto mode auto-approves without prompting."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(mock_manager, mode="auto")
        build_result, approval = lifecycle.build_with_approval()

        assert approval["approved"] is True
        assert approval["mode"] == "auto"
        mock_build.assert_called_once()

    @patch.object(PddLifecycle, "build")
    def test_steering_mode_auto_approves(
        self,
        mock_build: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that steering mode auto-approves without prompting."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(mock_manager, mode="steering")
        build_result, approval = lifecycle.build_with_approval()

        assert approval["approved"] is True
        assert approval["mode"] == "steering"

    @patch("builtins.input", return_value="a")
    @patch.object(PddLifecycle, "build")
    def test_interactive_mode_approve(
        self,
        mock_build: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that interactive mode with 'a' input approves."""
        mock_build.return_value = {
            "pipeline": {},
            "overview": {"overview_path": "/some/path/overview.md"},
        }

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        build_result, approval = lifecycle.build_with_approval()

        assert approval["approved"] is True
        assert approval["mode"] == "interactive"

    @patch("builtins.input", return_value="")
    @patch.object(PddLifecycle, "build")
    def test_interactive_mode_empty_input_approves(
        self,
        mock_build: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that empty input (just Enter) approves."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        build_result, approval = lifecycle.build_with_approval()

        assert approval["approved"] is True

    @patch("builtins.input", side_effect=["f", "needs more detail", "a"])
    @patch.object(PddLifecycle, "build")
    def test_interactive_mode_feedback_then_approve(
        self,
        mock_build: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test feedback loop: feedback on first iteration, approve on second."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        build_result, approval = lifecycle.build_with_approval()

        # Should have called build twice (feedback + approve)
        assert mock_build.call_count == 2
        assert approval["approved"] is True
        assert approval["iteration"] == 2

    @patch("builtins.input", side_effect=EOFError)
    @patch.object(PddLifecycle, "build")
    def test_interactive_mode_eof_approves(
        self,
        mock_build: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that EOFError (non-interactive terminal) auto-approves."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        build_result, approval = lifecycle.build_with_approval()

        assert approval["approved"] is True

    @patch("builtins.input", return_value="q")
    @patch.object(PddLifecycle, "build")
    def test_interactive_mode_quit_raises(
        self,
        mock_build: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that 'q' input raises KeyboardInterrupt."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(mock_manager, mode="interactive")
        with pytest.raises(KeyboardInterrupt):
            lifecycle.build_with_approval()

    @patch("builtins.input", side_effect=["f", "fix this", "f", "fix that", "f", "fix more"])
    @patch.object(PddLifecycle, "build")
    def test_max_iterations_auto_approves(
        self,
        mock_build: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that max iterations reached leads to auto-approval."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(
            mock_manager, mode="interactive", max_approval_iterations=3
        )
        build_result, approval = lifecycle.build_with_approval()

        assert approval["approved"] is True
        assert approval["auto_approved"] is True
        assert approval["reason"] == "max_iterations_reached"
        assert mock_build.call_count == 3

    @patch("builtins.input", side_effect=["f", "feedback text"])
    @patch.object(PddLifecycle, "build")
    def test_feedback_written_to_file(
        self,
        mock_build: MagicMock,
        mock_input: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that feedback is written to reports directory."""
        mock_build.return_value = {"pipeline": {}, "overview": {}}

        lifecycle = PddLifecycle(
            mock_manager, mode="interactive", max_approval_iterations=1
        )
        build_result, approval = lifecycle.build_with_approval()

        feedback_path = mock_manager.structure.root / "reports" / "feedback_iteration_1.txt"
        assert feedback_path.exists()
        assert feedback_path.read_text(encoding="utf-8") == "feedback text"


class TestSetupLibraryWorktrees:
    """Test the _setup_library_worktrees method."""

    def test_no_worktree_manager(self, mock_manager: MagicMock) -> None:
        """Test with no worktree manager configured."""
        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle._setup_library_worktrees()

        assert "note" in result

    def test_no_libraries_dir(self, mock_manager: MagicMock) -> None:
        """Test with no libraries directory."""
        mock_manager.structure.libraries_dir.rmdir()

        mock_wm = MagicMock()
        lifecycle = PddLifecycle(mock_manager, worktree_manager=mock_wm)
        result = lifecycle._setup_library_worktrees()

        assert "note" in result

    def test_creates_worktrees_per_library(
        self,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test that worktrees are created for each library directory."""
        mock_wm = MagicMock()
        mock_wm.setup.return_value = {"root_path": "/root", "clean_path": "/clean"}
        mock_wm.create_library_worktree.return_value = Path("/tmp/wt")

        lifecycle = PddLifecycle(
            mock_manager_with_libraries, worktree_manager=mock_wm
        )
        result = lifecycle._setup_library_worktrees()

        mock_wm.setup.assert_called_once()
        # 3 lib dirs exist (lib1, lib2, lib3)
        assert mock_wm.create_library_worktree.call_count == 3
        assert result["libraries_created"] == 3

    def test_handles_worktree_creation_error(
        self,
        mock_manager_with_libraries: MagicMock,
    ) -> None:
        """Test error handling when worktree creation fails."""
        mock_wm = MagicMock()
        mock_wm.setup.return_value = {"root_path": "/root", "clean_path": "/clean"}
        mock_wm.create_library_worktree.side_effect = RuntimeError("git failed")

        lifecycle = PddLifecycle(
            mock_manager_with_libraries, worktree_manager=mock_wm
        )
        result = lifecycle._setup_library_worktrees()

        assert result["libraries_created"] == 0
        assert len(result["errors"]) == 3


class TestRunWithWorktrees:
    """Test run() with worktree manager integration."""

    @patch.object(PddLifecycle, "build_with_approval")
    @patch.object(PddLifecycle, "qa")
    @patch.object(PddLifecycle, "architecture")
    @patch.object(PddLifecycle, "code_quality")
    def test_run_cleans_up_worktrees(
        self,
        mock_cq: MagicMock,
        mock_arch: MagicMock,
        mock_qa: MagicMock,
        mock_bwa: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that run() calls worktree cleanup."""
        mock_bwa.return_value = ({}, {"approved": True})
        mock_qa.return_value = {}
        mock_arch.return_value = {}
        mock_cq.return_value = {}

        mock_wm = MagicMock()
        mock_wm.cleanup.return_value = {"removed": ["root", "clean"]}

        lifecycle = PddLifecycle(mock_manager, worktree_manager=mock_wm)
        result = lifecycle.run()

        mock_wm.cleanup.assert_called_once()
        assert "cleanup" in result

    @patch.object(PddLifecycle, "build_with_approval")
    @patch.object(PddLifecycle, "qa")
    @patch.object(PddLifecycle, "architecture")
    @patch.object(PddLifecycle, "code_quality")
    def test_run_without_worktrees_no_cleanup(
        self,
        mock_cq: MagicMock,
        mock_arch: MagicMock,
        mock_qa: MagicMock,
        mock_bwa: MagicMock,
        mock_manager: MagicMock,
    ) -> None:
        """Test that run() without worktree manager skips cleanup."""
        mock_bwa.return_value = ({}, {"approved": True})
        mock_qa.return_value = {}
        mock_arch.return_value = {}
        mock_cq.return_value = {}

        lifecycle = PddLifecycle(mock_manager)
        result = lifecycle.run()

        assert "cleanup" not in result

"""Tests for branch lifecycle workflow integration.

Covers the full cycle from init through analysis generation,
including Phase enum additions, workflow functions, CLI wiring,
workspace initialization integration, and edit-in-place connection.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from spec_manager.branches.types import AtomDescriptor, AtomKind
from spec_manager.refinement.workspace.state import (
    Phase,
    PhaseStatus,
    WorkspaceState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PYTHON_FILE = textwrap.dedent("""\
    def compute_total(items: list[dict]) -> float:
        \"\"\"Sum item prices.\"\"\"
        return sum(item["price"] for item in items)

    def validate_order(order: dict) -> bool:
        \"\"\"Check order validity.\"\"\"
        return bool(order.get("items"))

    class OrderProcessor:
        def process(self, order: dict) -> dict:
            \"\"\"Process an order.\"\"\"
            total = compute_total(order["items"])
            return {"total": total, "valid": validate_order(order)}
""")


STUB_PYTHON_FILE = textwrap.dedent("""\
    def not_implemented_yet(data: dict) -> dict:
        \"\"\"Stub function.\"\"\"
        raise NotImplementedError

    def placeholder(x: int) -> int:
        \"\"\"Another stub.\"\"\"
        pass
""")


@pytest.fixture()
def sample_source_dir(tmp_path: Path) -> Path:
    """Create a temporary source directory with sample Python files."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "orders.py").write_text(SAMPLE_PYTHON_FILE, encoding="utf-8")
    (src / "stubs.py").write_text(STUB_PYTHON_FILE, encoding="utf-8")
    return src


@pytest.fixture()
def workspace_dir(tmp_path: Path) -> Path:
    """Create a minimal workspace directory with state.json."""
    ws = tmp_path / "test-run"
    ws.mkdir(parents=True)
    # Create required directories
    (ws / "spec_snapshot").mkdir()
    (ws / "spec_snapshot" / "dummy.md").write_text("# Spec", encoding="utf-8")
    (ws / "manifest").mkdir()
    (ws / "branches").mkdir()
    # Create a minimal state file
    state = WorkspaceState(run_id="test-run", input_folder=".")
    state.save(ws / "state.json")
    return ws


# ---------------------------------------------------------------------------
# Plan 1: Phase Enum Tests
# ---------------------------------------------------------------------------


class TestPhaseEnum:
    """Tests for branch Phase enum values."""

    def test_branch_init_exists(self) -> None:
        assert Phase.BRANCH_INIT.value == "branch_init"

    def test_branch_gaps_exists(self) -> None:
        assert Phase.BRANCH_GAPS.value == "branch_gaps"

    def test_branch_promote_exists(self) -> None:
        assert Phase.BRANCH_PROMOTE.value == "branch_promote"

    def test_branch_analyze_exists(self) -> None:
        assert Phase.BRANCH_ANALYZE.value == "branch_analyze"

    def test_get_next_phase_excludes_branch_phases(self) -> None:
        """Branch phases should NOT appear in get_next_phase() auto-sequence."""
        state = WorkspaceState(run_id="test", input_folder=".")
        # Complete all standard phases
        standard_phases = [
            Phase.INIT,
            Phase.SECTIONIZATION,
            Phase.SUMMARIZATION,
            Phase.LIBRARY_SYNTHESIS,
            Phase.EVIDENCE_EXPANSION,
            Phase.SPEC_BUILDING,
            Phase.SPEC_STABILIZATION,
            Phase.ALIGNMENT_CHECK,
            Phase.OVERVIEW_GENERATION,
            Phase.QA_EVALUATION,
            Phase.SUBLIBRARY_DETECTION,
            Phase.ARCHITECTURE_PROPOSAL,
            Phase.ARCHITECTURE_SELECTION,
            Phase.ARCHITECTURE_MAPPING,
            Phase.LIBRARY_STRUCTURE_REVIEW,
            Phase.INTERFACES,
            Phase.QUALITY_GATES,
            Phase.TASKS,
            Phase.IMPLEMENTATION,
            Phase.AUDIT,
        ]
        for phase in standard_phases:
            state.complete_phase(phase)
        # After completing all standard phases, get_next_phase should return None
        # (it should NOT return any BRANCH_* phase)
        assert state.get_next_phase() is None

    def test_branch_phases_initialized_in_workspace_state(self) -> None:
        """WorkspaceState.__post_init__ should initialize branch phase results."""
        state = WorkspaceState(run_id="test", input_folder=".")
        for phase_value in ["branch_init", "branch_gaps", "branch_promote", "branch_analyze"]:
            assert phase_value in state.phases
            assert state.phases[phase_value].status == PhaseStatus.NOT_STARTED


# ---------------------------------------------------------------------------
# Plan 2: Branch Workflow Module Tests
# ---------------------------------------------------------------------------


class TestBranchWorkflowInit:
    """Tests for run_branch_init workflow function."""

    def test_init_without_source_dir(self, workspace_dir: Path) -> None:
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_init

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = True
            manager.branches.initialize.return_value = []
            manager.branches.save.return_value = None

            result = run_branch_init("test-run", source_dir=None)

        assert result["success"] is True
        outputs = result["outputs"]
        assert outputs["branch_initialized"] is True
        assert outputs["atom_count"] == 0

    def test_init_with_source_dir(self, workspace_dir: Path, sample_source_dir: Path) -> None:
        from spec_manager.branches.collapse import CollapseResult
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_init

        # Create a mock CollapseResult
        atom1 = AtomDescriptor(
            atom_id="orders.py:compute_total",
            kind=AtomKind.ALGORITHM,
            file_path="orders.py",
            function_name="compute_total",
            signature="(items: list[dict]) -> float",
            content_hash="abc123",
            introduced_by="collapse",
        )
        collapse_result = CollapseResult(
            extracted_atoms=[atom1],
            extracted_stores=[],
            extracted_shapes=[],
            architectural_remnants=[],
            ambiguous_code=[],
            warnings=[],
        )

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = True
            manager.branches.initialize.return_value = []
            manager.branches.collapse_codebase.return_value = collapse_result
            manager.branches.register_atom.return_value = None
            manager.branches.save.return_value = None

            result = run_branch_init("test-run", source_dir=sample_source_dir)

        assert result["success"] is True
        outputs = result["outputs"]
        assert outputs["atom_count"] == 1
        assert outputs["atom_count_by_kind"]["algorithm"] == 1

    def test_init_fails_when_not_initialized(self) -> None:
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_init

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = False

            with pytest.raises(RuntimeError, match="Workspace not initialized"):
                run_branch_init("test-run")


class TestBranchWorkflowGaps:
    """Tests for run_branch_gaps workflow function."""

    def test_gaps_prerequisite_check(self) -> None:
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_gaps

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = True
            manager.state = WorkspaceState(run_id="test", input_folder=".")

            with pytest.raises(RuntimeError, match="BRANCH_INIT must be completed"):
                run_branch_gaps("test-run")

    def test_gaps_after_init(self, tmp_path: Path) -> None:
        from spec_manager.branches.gap_detection import GapItem
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_gaps

        with (
            patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr,
            patch("spec_manager.branches.gap_detection.GapDetector") as mock_detector_cls,
        ):
            manager = mock_mgr.return_value
            manager.is_initialized = True
            state = WorkspaceState(run_id="test", input_folder=".")
            state.complete_phase(Phase.BRANCH_INIT)
            manager.state = state

            # Set up analysis dir
            analysis_dir = tmp_path / "analysis"
            analysis_dir.mkdir()
            manager.branches.layout.analysis_dir.return_value = analysis_dir
            manager.branches.layout.algorithmic_dir.return_value = tmp_path / "algo"

            # Mock gap detector
            mock_detector = mock_detector_cls.return_value
            mock_detector.scan_branch.return_value = [
                GapItem(file="test.py", line=1, text="stub", gap_type="stub_function"),
            ]

            result = run_branch_gaps("test-run")

        assert result["success"] is True
        outputs = result["outputs"]
        assert outputs["total_gaps"] == 1
        assert outputs["gaps_by_type"]["stub_function"] == 1

        # Verify gap report was written
        gap_report = json.loads((analysis_dir / "gap_report.json").read_text())
        assert len(gap_report) == 1


class TestBranchWorkflowPromote:
    """Tests for run_branch_promote workflow function."""

    def test_promote_prerequisite_check(self) -> None:
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_promote

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = True
            manager.state = WorkspaceState(run_id="test", input_folder=".")

            with pytest.raises(RuntimeError, match="BRANCH_INIT must be completed"):
                run_branch_promote("test-run")

    def test_promote_skip_compliance(self) -> None:
        from spec_manager.branches.promotion import PromotionResult
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_promote

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = True
            state = WorkspaceState(run_id="test", input_folder=".")
            state.complete_phase(Phase.BRANCH_INIT)
            manager.state = state

            manager.branches.promote.return_value = PromotionResult(
                success=True,
                promoted_atoms=["atom1"],
                skipped_atoms=[],
                compliance_result=None,
                pin_ids_created=["PIN-0001"],
            )
            manager.branches.save.return_value = None

            result = run_branch_promote("test-run", skip_compliance=True)

        assert result["success"] is True
        outputs = result["outputs"]
        assert outputs["promoted_count"] == 1
        assert outputs["new_pin_ids"] == ["PIN-0001"]


class TestBranchWorkflowAnalyze:
    """Tests for run_branch_analyze workflow function."""

    def test_analyze_prerequisite_check(self) -> None:
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_analyze

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = True
            manager.state = WorkspaceState(run_id="test", input_folder=".")

            with pytest.raises(RuntimeError, match="BRANCH_INIT must be completed"):
                run_branch_analyze("test-run")

    def test_analyze_after_init(self, tmp_path: Path) -> None:
        from spec_manager.branches.analysis import AnalysisReport
        from spec_manager.refinement.workflows.branch_lifecycle import run_branch_analyze

        with patch("spec_manager.refinement.workflows.branch_lifecycle._get_manager") as mock_mgr:
            manager = mock_mgr.return_value
            manager.is_initialized = True
            state = WorkspaceState(run_id="test", input_folder=".")
            state.complete_phase(Phase.BRANCH_INIT)
            manager.state = state

            analysis_dir = tmp_path / "analysis"
            analysis_dir.mkdir()
            manager.branches.layout.analysis_dir.return_value = analysis_dir

            manager.branches.regenerate_analysis.return_value = AnalysisReport(
                generated_at="2024-01-01T00:00:00",
                atoms=[],
                orphaned_architectural=[],
                disconnected_subgraphs=[],
                store_touch_edges=[],
            )

            result = run_branch_analyze("test-run")

        assert result["success"] is True
        outputs = result["outputs"]
        assert outputs["atom_count"] == 0
        assert outputs["orphaned_count"] == 0


# ---------------------------------------------------------------------------
# Plan 4: Workspace Initialization Integration Tests
# ---------------------------------------------------------------------------


class TestWorkspaceInitBranches:
    """Tests for branch auto-initialization during workspace init."""

    def test_initialize_creates_branch_layout(self, tmp_path: Path) -> None:
        """WorkspaceManager.initialize() should create branch subdirectories."""
        from spec_manager.refinement.workspace import WorkspaceManager

        input_folder = tmp_path / "input"
        input_folder.mkdir()
        (input_folder / "test.md").write_text("# Test spec", encoding="utf-8")

        run_id = "test-branch-init"

        def _resolve(*parts: str) -> Path:
            return tmp_path / Path(*parts)

        with (
            patch(
                "spec_manager.refinement.workspace.manager.resolve_from_root",
                side_effect=_resolve,
            ),
            patch(
                "spec_manager.core.project_root.resolve_from_root",
                side_effect=_resolve,
            ),
        ):
            manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)
            manager.initialize()
            run_root = manager.structure.root

        # Verify branch layout was created
        branches_dir = run_root / "branches"
        assert branches_dir.exists()
        assert (branches_dir / "atoms").exists()
        assert (branches_dir / "algorithmic").exists()
        assert (branches_dir / "architectural").exists()
        assert (branches_dir / "analysis").exists()

    def test_branches_is_initialized_after_workspace_init(self, tmp_path: Path) -> None:
        """manager.branches.is_initialized() should return True after init."""
        from spec_manager.refinement.workspace import WorkspaceManager

        input_folder = tmp_path / "input"
        input_folder.mkdir()
        (input_folder / "test.md").write_text("# Test spec", encoding="utf-8")

        run_id = "test-branch-check"

        def _resolve(*parts: str) -> Path:
            return tmp_path / Path(*parts)

        with (
            patch(
                "spec_manager.refinement.workspace.manager.resolve_from_root",
                side_effect=_resolve,
            ),
            patch(
                "spec_manager.core.project_root.resolve_from_root",
                side_effect=_resolve,
            ),
        ):
            manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)
            manager.initialize()
            assert manager.branches.is_initialized()


# ---------------------------------------------------------------------------
# Plan 6: Phase State Tracking Tests
# ---------------------------------------------------------------------------


class TestBranchPhaseStateTracking:
    """Tests for phase state tracking in branch operations."""

    def test_start_phase_updates_state(self) -> None:
        state = WorkspaceState(run_id="test", input_folder=".")
        state.start_phase(Phase.BRANCH_INIT)
        result = state.phases[Phase.BRANCH_INIT.value]
        assert result.status == PhaseStatus.IN_PROGRESS
        assert result.started_at is not None

    def test_complete_phase_updates_state(self) -> None:
        state = WorkspaceState(run_id="test", input_folder=".")
        state.start_phase(Phase.BRANCH_INIT)
        state.complete_phase(Phase.BRANCH_INIT, outputs={"test": True})
        result = state.phases[Phase.BRANCH_INIT.value]
        assert result.status == PhaseStatus.COMPLETED
        assert result.completed_at is not None
        assert result.outputs == {"test": True}

    def test_fail_phase_updates_state(self) -> None:
        state = WorkspaceState(run_id="test", input_folder=".")
        state.start_phase(Phase.BRANCH_GAPS)
        state.fail_phase(Phase.BRANCH_GAPS, "test error")
        result = state.phases[Phase.BRANCH_GAPS.value]
        assert result.status == PhaseStatus.FAILED
        assert result.error == "test error"

    def test_resume_from_gaps(self) -> None:
        """After completing BRANCH_INIT, BRANCH_GAPS can start."""
        state = WorkspaceState(run_id="test", input_folder=".")
        state.complete_phase(Phase.BRANCH_INIT)
        # BRANCH_GAPS should still be NOT_STARTED
        assert state.phases[Phase.BRANCH_GAPS.value].status == PhaseStatus.NOT_STARTED
        # Can start it independently
        state.start_phase(Phase.BRANCH_GAPS)
        assert state.phases[Phase.BRANCH_GAPS.value].status == PhaseStatus.IN_PROGRESS

    def test_serialization_round_trip(self) -> None:
        """Branch phase states survive to_dict/from_dict round trip."""
        state = WorkspaceState(run_id="test", input_folder=".")
        state.complete_phase(Phase.BRANCH_INIT, outputs={"atoms": 5})
        state.start_phase(Phase.BRANCH_GAPS)

        data = state.to_dict()
        restored = WorkspaceState.from_dict(data)

        assert restored.phases["branch_init"].status == PhaseStatus.COMPLETED
        assert restored.phases["branch_init"].outputs == {"atoms": 5}
        assert restored.phases["branch_gaps"].status == PhaseStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Plan 6: CLI Argument Parsing Tests
# ---------------------------------------------------------------------------


class TestBranchesCLIParsing:
    """Tests for branches CLI argument parsing."""

    def test_branches_init_parses(self) -> None:
        """Branches init should parse run_id and optional flags."""
        # Quick smoke test that the parser works
        from spec_manager.cli import main

        # We test parsing by importing the parser setup code
        # Just verify help does not crash
        with pytest.raises(SystemExit) as exc_info:
            import sys

            old_argv = sys.argv
            sys.argv = ["spec-manager", "branches", "init", "--help"]
            try:
                main()
            finally:
                sys.argv = old_argv
        assert exc_info.value.code == 0

    def test_branches_status_parses(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            import sys

            old_argv = sys.argv
            sys.argv = ["spec-manager", "branches", "status", "--help"]
            try:
                from spec_manager.cli import main

                main()
            finally:
                sys.argv = old_argv
        assert exc_info.value.code == 0

    def test_branches_run_parses(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            import sys

            old_argv = sys.argv
            sys.argv = ["spec-manager", "branches", "run", "--help"]
            try:
                from spec_manager.cli import main

                main()
            finally:
                sys.argv = old_argv
        assert exc_info.value.code == 0

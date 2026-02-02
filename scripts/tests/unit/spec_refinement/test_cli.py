from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from spec_manager.refinement.workspace import Phase, WorkspaceManager

from scripts.spec_refinement.cli import main


def _setup_initialized_workspace(fs, monkeypatch, run_id: str = "run1") -> WorkspaceManager:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id=run_id, input_folder=input_dir)
    manager.initialize(force=True)
    return manager


def test_init_creates_workspace(fs, monkeypatch) -> None:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")

    exit_code = main(["init", "test_run", str(input_dir)])
    assert exit_code == 0
    assert Path("runs/test_run/state.json").exists()


def test_init_missing_input_folder(fs, monkeypatch) -> None:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")

    exit_code = main(["init", "test_run", "/repo/nonexistent"])
    assert exit_code == 1


def test_status_uninitialized(fs, monkeypatch) -> None:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")

    exit_code = main(["status", "test_run"])
    assert exit_code == 1


def test_status_initialized(fs, monkeypatch) -> None:
    _setup_initialized_workspace(fs, monkeypatch)

    exit_code = main(["status", "run1"])
    assert exit_code == 0


def test_gaps_list_no_gaps(fs, monkeypatch) -> None:
    _setup_initialized_workspace(fs, monkeypatch)

    exit_code = main(["gaps", "list", "run1"])
    assert exit_code == 0


def test_spec_summarize_dispatches(fs, monkeypatch) -> None:
    _setup_initialized_workspace(fs, monkeypatch)

    with patch("scripts.spec_refinement.cli.summarize_all") as mock_summarize:
        mock_summarize.return_value = {
            "summaries_written": 1,
            "files_processed": 1,
            "errors": [],
            "issues": [],
        }
        exit_code = main(["spec", "summarize", "run1", "--sequential"])

    assert exit_code == 0
    mock_summarize.assert_called_once_with("run1", parallel=False)


def test_spec_synthesize_dispatches(fs, monkeypatch) -> None:
    manager = _setup_initialized_workspace(fs, monkeypatch)
    manager.start_phase(Phase.SUMMARIZATION)
    manager.complete_phase(Phase.SUMMARIZATION, outputs={"summaries_count": 1})

    with patch("scripts.spec_refinement.cli.synthesize_libraries") as mock_synth:
        mock_synth.return_value = {
            "libraries_created": 1,
            "issues": [],
        }
        exit_code = main(["spec", "synthesize", "run1"])

    assert exit_code == 0
    mock_synth.assert_called_once_with("run1")


def test_spec_expand_evidence_dispatches(fs, monkeypatch) -> None:
    manager = _setup_initialized_workspace(fs, monkeypatch)
    manager.start_phase(Phase.LIBRARY_SYNTHESIS)
    manager.complete_phase(Phase.LIBRARY_SYNTHESIS, outputs={"libraries_count": 1})

    with patch(
        "scripts.spec_refinement.workflows.evidence_expansion.expand_evidence"
    ) as mock_expand:
        mock_expand.return_value = {
            "libraries_expanded": 1,
            "evidence_sources_added": 3,
            "errors": [],
            "issues": [],
        }
        exit_code = main(["spec", "expand-evidence", "run1"])

    assert exit_code == 0


def test_spec_build_specs_dispatches(fs, monkeypatch) -> None:
    manager = _setup_initialized_workspace(fs, monkeypatch)
    manager.start_phase(Phase.LIBRARY_SYNTHESIS)
    manager.complete_phase(Phase.LIBRARY_SYNTHESIS, outputs={"libraries_count": 1})
    manager.start_phase(Phase.EVIDENCE_EXPANSION)
    manager.complete_phase(Phase.EVIDENCE_EXPANSION, outputs={"libraries_expanded": 1})

    with patch("scripts.spec_refinement.workflows.spec_building.build_specs") as mock_build:
        mock_build.return_value = {
            "libraries_built": 1,
            "total_iterations": 2,
            "converged_count": 1,
            "errors": [],
            "issues": [],
        }
        exit_code = main(["spec", "build-specs", "run1", "--max-iterations", "3"])

    assert exit_code == 0


def test_spec_summarize_runtime_error(fs, monkeypatch) -> None:
    _setup_initialized_workspace(fs, monkeypatch)

    with patch("scripts.spec_refinement.cli.summarize_all") as mock_summarize:
        mock_summarize.side_effect = RuntimeError("Workspace not initialized")
        exit_code = main(["spec", "summarize", "run1"])

    assert exit_code == 1


def test_spec_synthesize_with_error_result(fs, monkeypatch) -> None:
    _setup_initialized_workspace(fs, monkeypatch)

    with patch("scripts.spec_refinement.cli.synthesize_libraries") as mock_synth:
        mock_synth.return_value = {
            "error": "Synthesis failed",
            "libraries_created": 0,
            "issues": [],
        }
        exit_code = main(["spec", "synthesize", "run1"])

    assert exit_code == 1


def test_init_force_flag(fs, monkeypatch) -> None:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")

    exit_code1 = main(["init", "run_force", str(input_dir)])
    assert exit_code1 == 0

    exit_code2 = main(["init", "run_force", str(input_dir), "--force"])
    assert exit_code2 == 0


def test_gap_resolve_invalid_type(fs, monkeypatch) -> None:
    _setup_initialized_workspace(fs, monkeypatch)
    exit_code = main(["gap", "resolve", "run1", "GAP-nonexistent", "integrate", "--notes", "test"])
    assert exit_code == 1


def test_gap_investigate_not_found(fs, monkeypatch) -> None:
    _setup_initialized_workspace(fs, monkeypatch)
    exit_code = main(["gap", "investigate", "run1", "GAP-nonexistent"])
    assert exit_code == 1

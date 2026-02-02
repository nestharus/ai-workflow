from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from scripts.spec_refinement.workflows.summarization import summarize_all


def _make_summary_output(file_id: str, section: str) -> str:
    return (
        f"# File Summary: {file_id}\n"
        f"File ID: {file_id}\n\n"
        "## Algorithms\n"
        f"- Algo | Does something | Evidence: [{file_id}::{section}]\n\n"
        "## Components\n"
        f"- Component | Holds data | Evidence: [{file_id}::{section}]\n\n"
        "## Workflows\n"
        f"- Workflow | Runs tasks | Evidence: [{file_id}::{section}]\n\n"
        "## Candidate Responsibilities\n"
        f"- Owns spec updates | Evidence: [{file_id}::{section}]\n\n"
        "## Dependencies\n"
        "- dep-one\n\n"
        "## Evidence Map\n"
        f"- {section}: [{file_id}::{section}]\n"
    )


def _fake_run_agent(outputs: dict[str, str], failures: set[str] | None = None):
    failures = failures or set()

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        match = re.search(r"File ID: (F\d{4})", prompt)
        if not match:
            raise RuntimeError("Missing file id in prompt")
        file_id = match.group(1)
        if file_id in failures:
            raise RuntimeError("Agent error")
        return outputs[file_id]

    return _run_agent


def _setup_workspace(fs, monkeypatch) -> Path:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    (input_dir / "b.md").write_text("## Details\n[DETAILS]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    issues = manager.initialize(force=True)
    assert issues == []
    return input_dir


def test_summarize_all_success(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    outputs = {
        "F0001": _make_summary_output("F0001", "INTRO"),
        "F0002": _make_summary_output("F0002", "DETAILS"),
    }

    with patch(
        "scripts.spec_refinement.workflows.summarization.run_agent",
        side_effect=_fake_run_agent(outputs),
    ):
        result = summarize_all("run1", parallel=False)

    summary_dir = Path("/repo/runs/run1/summaries")
    assert (summary_dir / "F0001.what.md").exists()
    assert (summary_dir / "F0002.what.md").exists()
    assert result["summaries_written"] == 2
    assert result["files_processed"] == 2

    manager = WorkspaceManager(run_id="run1", input_folder=Path("."))
    assert manager.state.phases[Phase.SUMMARIZATION.value].status == PhaseStatus.COMPLETED


def test_summarize_all_parallel(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    outputs = {
        "F0001": _make_summary_output("F0001", "INTRO"),
        "F0002": _make_summary_output("F0002", "DETAILS"),
    }

    with patch(
        "scripts.spec_refinement.workflows.summarization.run_agent",
        side_effect=_fake_run_agent(outputs),
    ):
        result = summarize_all("run1", parallel=True)

    assert result["summaries_written"] == 2
    assert result["files_processed"] == 2


def test_summarize_all_partial_failure(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    outputs = {
        "F0001": _make_summary_output("F0001", "INTRO"),
        "F0002": _make_summary_output("F0002", "DETAILS"),
    }

    with patch(
        "scripts.spec_refinement.workflows.summarization.run_agent",
        side_effect=_fake_run_agent(outputs, failures={"F0002"}),
    ):
        result = summarize_all("run1", parallel=False)

    assert result["summaries_written"] == 1
    assert result["files_processed"] == 2
    assert result["errors"]

    manager = WorkspaceManager(run_id="run1", input_folder=Path("."))
    assert manager.state.phases[Phase.SUMMARIZATION.value].status == PhaseStatus.COMPLETED


def test_summarize_all_phase_tracking(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    outputs = {
        "F0001": _make_summary_output("F0001", "INTRO"),
        "F0002": _make_summary_output("F0002", "DETAILS"),
    }

    with patch(
        "scripts.spec_refinement.workflows.summarization.run_agent",
        side_effect=_fake_run_agent(outputs),
    ):
        summarize_all("run1", parallel=False)

    manager = WorkspaceManager(run_id="run1", input_folder=Path("."))
    phase = manager.state.phases[Phase.SUMMARIZATION.value]
    assert phase.status == PhaseStatus.COMPLETED
    assert phase.started_at is not None
    assert phase.completed_at is not None

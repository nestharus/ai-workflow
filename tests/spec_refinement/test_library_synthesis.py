from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.spec_refinement.workflows.library_synthesis import synthesize_libraries
from scripts.spec_refinement.workspace import Phase, WorkspaceManager


def _library_output(evidence_section: str = "INTRO") -> str:
    return (
        "## Library Index\n"
        "- lib_001: Core Workflow Library\n\n"
        "## Library Charters\n"
        "### lib_001\n"
        "#### Intent\n"
        "Own core workflow responsibilities.\n\n"
        "#### Boundaries\n"
        "Includes orchestrator and runner coordination.\n\n"
        "#### Responsibilities\n"
        "- Handle phase transitions\n"
        "- Coordinate summaries\n\n"
        "#### Evidence\n"
        f"- [file_001::{evidence_section}]\n\n"
        "#### Overlap Resolutions\n"
        "- Workflow vs orchestration -> Assign to lib_001\n"
    )


class DummyRunner:
    def __init__(self, output: str) -> None:
        self.output = output

    def run(self, prompt: str) -> str:
        return self.output


def _setup_workspace(fs, monkeypatch, summarize: bool = True) -> WorkspaceManager:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)

    if summarize:
        manager.start_phase(Phase.SUMMARIZATION)
        manager.complete_phase(Phase.SUMMARIZATION, outputs={"summaries_count": 1})
        summary_path = manager.structure.summaries_dir / "file_001.what.md"
        summary_path.write_text("# Summary\n", encoding="utf-8")

    return manager


def test_synthesize_libraries_success(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with patch(
        "scripts.spec_refinement.workflows.library_synthesis.AgentRunner.from_agent_name",
        return_value=DummyRunner(_library_output()),
    ):
        result = synthesize_libraries("run1", Path("/repo/.tasks.yaml"))

    libraries_dir = Path("/repo/runs/run1/libraries")
    assert (libraries_dir / "library_index.md").exists()

    lib_dir = libraries_dir / "lib_001"
    assert (lib_dir / "charter.md").exists()
    assert (lib_dir / "evidence.json").exists()
    assert (lib_dir / "gaps.md").exists()
    assert (lib_dir / "decisions.md").exists()

    assert result["libraries_created"] == 1


def test_synthesize_libraries_overlap_resolution(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with patch(
        "scripts.spec_refinement.workflows.library_synthesis.AgentRunner.from_agent_name",
        return_value=DummyRunner(_library_output()),
    ):
        synthesize_libraries("run1", Path("/repo/.tasks.yaml"))

    charter_path = Path("/repo/runs/run1/libraries/lib_001/charter.md")
    charter = charter_path.read_text(encoding="utf-8")
    assert "Overlap Resolutions" in charter
    assert "->" in charter


def test_synthesize_libraries_evidence_validation(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with patch(
        "scripts.spec_refinement.workflows.library_synthesis.AgentRunner.from_agent_name",
        return_value=DummyRunner(_library_output("UNKNOWN")),
    ):
        result = synthesize_libraries("run1", Path("/repo/.tasks.yaml"))

    assert any(issue["type"] == "unknown_section_reference" for issue in result["issues"])


def test_synthesize_libraries_phase_dependency(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch, summarize=False)

    try:
        synthesize_libraries("run1", Path("/repo/.tasks.yaml"))
    except RuntimeError as exc:
        assert "Summarization phase" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when summarization is incomplete")

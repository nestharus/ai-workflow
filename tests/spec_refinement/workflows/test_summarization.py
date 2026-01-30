from __future__ import annotations

from pathlib import Path

from scripts.spec_refinement.workflows.summarization import _validate_evidence_pointers
from scripts.spec_refinement.workspace import WorkspaceManager


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    specs_dir = base / "specs"
    fs.create_dir(specs_dir)
    (specs_dir / "alpha.md").write_text(
        "# Alpha\n\n## Intro\nDetails.\n\n## User Requirements\nNeeds.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("specs"))
    issues = manager.initialize(force=True)
    assert issues == []
    return manager


def test_validate_evidence_pointers_basename_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha.md::INTRO]"
    issues = _validate_evidence_pointers(content, manager, "file_001")

    assert issues == []


def test_validate_evidence_pointers_stem_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha::INTRO]"
    issues = _validate_evidence_pointers(content, manager, "file_001")

    assert issues == []


def test_validate_evidence_pointers_case_insensitive_section(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [file_001::intro]"
    issues = _validate_evidence_pointers(content, manager, "file_001")

    assert issues == []


def test_validate_evidence_pointers_separator_normalization(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [file_001::user-requirements]"
    issues = _validate_evidence_pointers(content, manager, "file_001")

    assert issues == []

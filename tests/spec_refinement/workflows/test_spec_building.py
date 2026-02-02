from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from spec_manager.refinement.workflows.spec_building import _validate_spec_citations
from spec_manager.refinement.workspace import WorkspaceManager


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


def _stub_manager(
    file_manifest: dict[str, dict[str, str]],
    section_manifest: dict[str, list[str]],
    spec_snapshot_dir: Path,
) -> SimpleNamespace:
    state = SimpleNamespace(file_manifest=file_manifest, section_manifest=section_manifest)
    structure = SimpleNamespace(spec_snapshot_dir=spec_snapshot_dir)

    def _read_file_sections(file_id: str) -> dict[str, list[dict[str, str]]]:
        sections = section_manifest.get(file_id, [])
        return {
            "sections": [
                {"section_id": label, "label": label}
                for label in sections
                if isinstance(label, str)
            ]
        }

    return SimpleNamespace(
        state=state,
        structure=structure,
        read_file_sections=_read_file_sections,
    )


def test_validate_spec_citations_basename_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha.md::INTRO]"
    issues = _validate_spec_citations(content, manager, "LIB-0001")

    assert issues == []


def test_validate_spec_citations_stem_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha::INTRO]"
    issues = _validate_spec_citations(content, manager, "LIB-0001")

    assert issues == []


def test_validate_spec_citations_case_insensitive_section(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [F0001::intro]"
    issues = _validate_spec_citations(content, manager, "LIB-0001")

    assert issues == []


def test_validate_spec_citations_separator_normalization(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [F0001::user-requirements]"
    issues = _validate_spec_citations(content, manager, "LIB-0001")

    assert issues == []


def test_validate_spec_citations_basename_and_normalized_section() -> None:
    file_path = Path("/work/specs/nested/alpha.md")
    spec_snapshot_dir = file_path.parents[1]
    relpath = file_path.relative_to(spec_snapshot_dir).as_posix()
    manager = _stub_manager(
        {"F0001": {"relpath": relpath, "sha256": "0" * 64}},
        {"F0001": ["INTRO", "User Requirements"]},
        spec_snapshot_dir,
    )

    content = "Evidence: [alpha.md::intro]\nEvidence: [alpha::user-requirements]"
    issues = _validate_spec_citations(content, manager, "LIB-0001")

    assert issues == []


def test_validate_spec_citations_invalid_section_reports_issue() -> None:
    file_path = Path("/work/specs/nested/alpha.md")
    spec_snapshot_dir = file_path.parents[1]
    relpath = file_path.relative_to(spec_snapshot_dir).as_posix()
    manager = _stub_manager(
        {"F0001": {"relpath": relpath, "sha256": "0" * 64}},
        {"F0001": ["INTRO", "User Requirements"]},
        spec_snapshot_dir,
    )

    content = "Evidence: [alpha::missing-section]"
    issues = _validate_spec_citations(content, manager, "LIB-0001")

    assert any(issue["type"] == "unknown_section_reference" for issue in issues)

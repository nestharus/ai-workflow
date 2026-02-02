from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from spec_manager.refinement.workflows.summarization import _validate_evidence_pointers
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

    # Write per-file sections manifest with canonical section IDs
    sections_file = manager.structure.manifest_sections_dir / "F0001.sections.json"
    sections_data = {
        "file_id": "F0001",
        "sections": [
            {"section_id": "SEC-F0001-0001", "start_line": 1, "end_line": 4, "label": "Intro"},
            {
                "section_id": "SEC-F0001-0002",
                "start_line": 5,
                "end_line": 7,
                "label": "User Requirements",
            },
        ],
        "total_lines": 7,
    }
    sections_file.write_text(json.dumps(sections_data), encoding="utf-8")
    return manager


def _stub_manager(
    file_manifest: dict[str, dict[str, str]],
    sections_by_file: dict[str, list[dict[str, str]]],
    spec_snapshot_dir: Path,
) -> SimpleNamespace:
    state = SimpleNamespace(file_manifest=file_manifest)
    structure = SimpleNamespace(spec_snapshot_dir=spec_snapshot_dir)

    def _read_file_sections(file_id: str) -> dict[str, Any] | None:
        sections = sections_by_file.get(file_id)
        if sections is None:
            return None
        return {"sections": sections}

    return SimpleNamespace(
        state=state,
        structure=structure,
        read_file_sections=_read_file_sections,
    )


def test_validate_evidence_pointers_basename_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha.md::SEC-F0001-0001]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert issues == []


def test_validate_evidence_pointers_stem_reference(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [alpha::SEC-F0001-0002]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert issues == []


def test_validate_evidence_pointers_legacy_label_rejected(fs, monkeypatch) -> None:
    """Legacy labels like 'intro' or 'INTRO' are flagged as unknown."""
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [F0001::intro]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert any(issue["type"] == "unknown_section_reference" for issue in issues)


def test_validate_evidence_pointers_normalized_label_rejected(fs, monkeypatch) -> None:
    """Normalized labels like 'user-requirements' are flagged as unknown."""
    manager = _setup_workspace(fs, monkeypatch)

    content = "Evidence: [F0001::user-requirements]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert any(issue["type"] == "unknown_section_reference" for issue in issues)


def test_validate_evidence_pointers_section_id_with_different_file_refs() -> None:
    """Canonical section IDs are accepted via basename and stem file refs."""
    file_path = Path("/work/specs/nested/alpha.md")
    spec_snapshot_dir = file_path.parents[1]
    relpath = file_path.relative_to(spec_snapshot_dir).as_posix()
    manager = _stub_manager(
        {"F0001": {"relpath": relpath, "sha256": "0" * 64}},
        {
            "F0001": [
                {"section_id": "SEC-F0001-0001", "label": "INTRO"},
                {"section_id": "SEC-F0001-0002", "label": "User Requirements"},
            ]
        },
        spec_snapshot_dir,
    )

    content = "Evidence: [alpha.md::SEC-F0001-0001]\nEvidence: [alpha::SEC-F0001-0002]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert issues == []


def test_validate_evidence_pointers_invalid_section_reports_issue() -> None:
    file_path = Path("/work/specs/nested/alpha.md")
    spec_snapshot_dir = file_path.parents[1]
    relpath = file_path.relative_to(spec_snapshot_dir).as_posix()
    manager = _stub_manager(
        {"F0001": {"relpath": relpath, "sha256": "0" * 64}},
        {
            "F0001": [
                {"section_id": "SEC-F0001-0001", "label": "INTRO"},
                {"section_id": "SEC-F0001-0002", "label": "User Requirements"},
            ]
        },
        spec_snapshot_dir,
    )

    content = "Evidence: [alpha::missing-section]"
    issues = _validate_evidence_pointers(content, manager, "F0001")

    assert any(issue["type"] == "unknown_section_reference" for issue in issues)

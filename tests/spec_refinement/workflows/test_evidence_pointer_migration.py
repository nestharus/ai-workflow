from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec_manager.refinement.formats import (
    LibraryCharter,
    build_evidence_pointer,
    migrate_evidence_json,
    migrate_pointers_to_new_format,
)
from spec_manager.refinement.workflows.library_synthesis import _format_charter, _validate_evidence_sources
from spec_manager.refinement.workspace import WorkspaceManager


def _setup_workspace(fs, monkeypatch) -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    specs_dir = base / "specs"
    fs.create_dir(specs_dir)
    (specs_dir / "alpha.md").write_text("# Alpha\n\n## Intro\nDetails.\n", encoding="utf-8")
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id="run_001", input_folder=Path("specs"))
    issues = manager.initialize(force=True)
    assert issues == []

    sections_payload = {
        "sections": [
            {
                "section_id": "SEC-F0001-0001",
                "label": "INTRO",
            }
        ]
    }
    manager.structure.manifest_sections_dir.mkdir(parents=True, exist_ok=True)
    (manager.structure.manifest_sections_dir / "F0001.sections.json").write_text(
        json.dumps(sections_payload),
        encoding="utf-8",
    )
    manager.state.section_manifest["F0001"] = ["SEC-F0001-0001"]
    return manager


def test_build_evidence_pointer_new_format() -> None:
    file_manifest = {"F0001": {"relpath": "specs/alpha.md", "sha256": "0" * 64}}
    pointer = build_evidence_pointer("F0001", "SEC-F0001-0001", file_manifest)
    assert pointer == "[spec_snapshot/specs/alpha.md::SEC-F0001-0001]"


def test_build_evidence_pointer_missing_relpath() -> None:
    file_manifest = {"F0001": {"sha256": "0" * 64}}
    with pytest.raises(KeyError, match="Missing relpath"):
        build_evidence_pointer("F0001", "SEC-F0001-0001", file_manifest)


def test_migrate_pointers_legacy_to_new(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    relpath = manager.state.file_manifest["F0001"]["relpath"]

    content = "Evidence:\n- [F0001::INTRO]\n"
    migrated = migrate_pointers_to_new_format(content, manager)

    assert f"[spec_snapshot/{relpath}::SEC-F0001-0001]" in migrated


def test_validate_evidence_sources_accepts_both_formats(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    relpath = manager.state.file_manifest["F0001"]["relpath"]

    charter = LibraryCharter(
        lib_id="lib_001",
        intent="A",
        boundaries="B",
        responsibilities=[],
        evidence_sources=[
            {"file_id": "F0001", "sections": ["SEC-F0001-0001"]},
            {"file_id": f"spec_snapshot/{relpath}", "sections": ["SEC-F0001-0001"]},
        ],
        overlap_resolutions=[],
    )

    issues = _validate_evidence_sources([charter], manager)
    assert issues == []


def test_migrate_evidence_json_validates_structure(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    lib_dir = manager.structure.libraries_dir / "lib_001"
    lib_dir.mkdir(parents=True, exist_ok=True)

    evidence_path = lib_dir / "evidence.json"
    evidence_path.write_text(
        json.dumps({"sources": [{"file_id": "F0001", "sections": ["SEC-F0001-0001"]}]}),
        encoding="utf-8",
    )

    report = migrate_evidence_json(evidence_path, manager)

    assert report["migrated"] is True
    assert report["sources_count"] == 1
    assert report["issues"] == []


def test_charter_formatting_uses_new_format(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    relpath = manager.state.file_manifest["F0001"]["relpath"]

    charter = LibraryCharter(
        lib_id="lib_001",
        intent="Core",
        boundaries="",
        responsibilities=["Handle workflow"],
        evidence_sources=[{"file_id": "F0001", "sections": ["SEC-F0001-0001"]}],
        overlap_resolutions=[],
    )

    content = _format_charter(charter, manager)

    assert f"[spec_snapshot/{relpath}::SEC-F0001-0001]" in content

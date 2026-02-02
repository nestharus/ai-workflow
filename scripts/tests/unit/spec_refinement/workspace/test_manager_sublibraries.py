from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.refinement.workspace import WorkspaceManager


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceManager:
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "spec.md").write_text("# Spec\n\n## Intro\nContent\n", encoding="utf-8")
    workspace = WorkspaceManager(run_id="run1", input_folder=input_dir)
    workspace.initialize()
    return workspace


def test_get_sublibrary_path(manager: WorkspaceManager) -> None:
    expected = manager.structure.libraries_dir / "lib_001" / "sublibraries" / "sub_001"
    assert manager.get_sublibrary_path("lib_001", "sub_001") == expected


def test_list_sublibraries(manager: WorkspaceManager) -> None:
    sub_dir = manager.structure.libraries_dir / "lib_001" / "sublibraries"
    (sub_dir / "sub_001").mkdir(parents=True)
    (sub_dir / "sub_002").mkdir(parents=True)

    assert manager.list_sublibraries("lib_001") == ["sub_001", "sub_002"]


def test_get_all_libraries_recursive(manager: WorkspaceManager) -> None:
    lib_dir = manager.structure.libraries_dir / "lib_001"
    sub_dir = lib_dir / "sublibraries" / "sub_001"
    nested_dir = sub_dir / "sublibraries" / "sub_sub_001"
    nested_dir.mkdir(parents=True)

    libraries = manager.get_all_libraries_recursive()
    assert libraries["lib_001"] == lib_dir
    assert libraries["lib_001/sub_001"] == sub_dir
    assert libraries["lib_001/sub_001/sub_sub_001"] == nested_dir

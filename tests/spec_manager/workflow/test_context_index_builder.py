from __future__ import annotations

import json
from pathlib import Path

from pyfakefs.fake_filesystem import FakeFilesystem
from spec_manager.workflow.context import (
    ContextIndex,
    ContextIndexBuilder,
)


def _setup_workspace(fs: FakeFilesystem) -> tuple[Path, Path]:
    workspace = Path("/workspace")
    spec_folder = Path("/spec")
    fs.create_dir(str(workspace))
    fs.create_dir(str(spec_folder))
    return workspace, spec_folder


def test_build_from_empty_manifests(fs: FakeFilesystem) -> None:
    workspace, spec_folder = _setup_workspace(fs)
    builder = ContextIndexBuilder(workspace=workspace, spec_folder=spec_folder)

    index = builder.build_from_manifests()

    assert index._index == {}
    assert index._strata == []


def test_build_from_terms_manifest(fs: FakeFilesystem) -> None:
    workspace, spec_folder = _setup_workspace(fs)
    terms_dir = spec_folder / "manifest" / "terms"
    fs.create_dir(str(terms_dir))
    terms_file = terms_dir / "p1.terms.json"

    payload = {
        "file_id": "p1",
        "section_terms": [{"section_id": "s1", "terms": ["Alpha", "Beta"], "confidence": 0.9}],
        "global_terms": ["Gamma"],
    }
    terms_file.write_text(json.dumps(payload), encoding="utf-8")

    builder = ContextIndexBuilder(workspace=workspace, spec_folder=spec_folder)
    index = builder.build_from_manifests()

    assert "alpha" in index._index
    assert "beta" in index._index
    assert "gamma" in index._index
    for term in ("alpha", "beta", "gamma"):
        assert index._index[term][0]["type"] == "term"
        assert index._index[term][0]["path"] == str(terms_file)


def test_build_from_sections_manifest(fs: FakeFilesystem) -> None:
    workspace, spec_folder = _setup_workspace(fs)
    sections_dir = spec_folder / "manifest" / "sections"
    fs.create_dir(str(sections_dir))
    sections_file = sections_dir / "p1.sections.json"

    payload = {
        "file_id": "p1",
        "sections": [{"section_id": "s1", "start_line": 1, "end_line": 5, "label": "Overview"}],
        "total_lines": 10,
    }
    sections_file.write_text(json.dumps(payload), encoding="utf-8")

    builder = ContextIndexBuilder(workspace=workspace, spec_folder=spec_folder)
    index = builder.build_from_manifests()

    assert "s1" in index._index
    assert "overview" in index._index
    assert index._index["s1"][0]["type"] == "section"
    assert index._index["overview"][0]["type"] == "section"
    assert index._index["s1"][0]["path"] == str(sections_file)


def test_save_and_load_context_index(fs: FakeFilesystem) -> None:
    workspace, _spec_folder = _setup_workspace(fs)
    index = ContextIndex(workspace)
    index._index = {
        "alpha": [
            {
                "path": "p1.md",
                "position": 0,
                "context": "alpha",
                "priority": 10,
                "type": "term",
            }
        ]
    }
    index._strata = [
        {
            "path": "p1.md",
            "content": "alpha",
            "priority": 10,
            "type": "patch",
        }
    ]

    output_path = workspace / "indexes" / "context_index.json"
    index.save(output_path)

    loaded = ContextIndex.load(output_path, workspace)

    assert loaded.to_dict() == index.to_dict()


def test_merge_manifest_index_with_patch_index(fs: FakeFilesystem) -> None:
    workspace, spec_folder = _setup_workspace(fs)
    terms_dir = spec_folder / "manifest" / "terms"
    fs.create_dir(str(terms_dir))
    terms_file = terms_dir / "p1.terms.json"

    payload = {
        "file_id": "p1",
        "section_terms": [{"section_id": "s1", "terms": ["Alpha"], "confidence": 0.9}],
        "global_terms": ["Beta"],
    }
    terms_file.write_text(json.dumps(payload), encoding="utf-8")

    patch_index = ContextIndex(workspace)
    patch_index._add_to_index("alpha", "patch.md", 0, "alpha", 50, "declared_id")

    builder = ContextIndexBuilder(workspace=workspace, spec_folder=spec_folder)
    manifest_index = builder.build_from_manifests()

    for term, locations in manifest_index._index.items():
        if term not in patch_index._index:
            patch_index._index[term] = []
        patch_index._index[term].extend(locations)

    assert "alpha" in patch_index._index
    assert "beta" in patch_index._index
    assert len(patch_index._index["alpha"]) == 2

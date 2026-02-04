from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.refinement.formats import normalize_compound_pointers
from spec_manager.refinement.validation_utils import (
    build_section_alias_map,
    strip_invalid_file_pointers,
)
from spec_manager.refinement.workflows.spec_stabilization import (
    normalize_decisions_pointers,
    normalize_spec_pointers,
)


def _find_file_id_by_name(manager, filename: str) -> str:
    for file_id, entry in manager.state.file_manifest.items():
        if Path(entry["relpath"]).name == filename:
            return file_id
    raise AssertionError(f"File not found for {filename}")


def _section_id_for_label(manager, file_id: str, label: str) -> str:
    sections_data = manager.read_file_sections(file_id) or {}
    for entry in sections_data.get("sections", []):
        if entry.get("label") == label:
            return entry.get("section_id")
    raise AssertionError(f"Label not found: {label}")


@pytest.fixture
def setup_pointer_migration_workspace(spec_refinement_workspace):
    def _factory():
        manager, manifest = spec_refinement_workspace(run_id="run_ptr_001")
        return manager, manifest

    return _factory


def test_normalize_spec_pointers_converts_legacy_format(setup_pointer_migration_workspace) -> None:
    manager, manifest = setup_pointer_migration_workspace()
    file_id = _find_file_id_by_name(manager, "alpha.md")
    relpath = manager.state.file_manifest[file_id]["relpath"]
    section_id = _section_id_for_label(manager, file_id, "INTRO")
    alias_map = build_section_alias_map({file_id: manifest[file_id]["section_labels"]})
    spec_content = "Evidence: [F0001::INTRO]"

    migrated = normalize_spec_pointers(spec_content, manager, alias_map)

    assert f"[spec_snapshot/{relpath}::{section_id}]" in migrated


def test_normalize_spec_pointers_handles_multiple_pointers(
    setup_pointer_migration_workspace,
) -> None:
    manager, manifest = setup_pointer_migration_workspace()
    file_id = _find_file_id_by_name(manager, "alpha.md")
    relpath = manager.state.file_manifest[file_id]["relpath"]
    intro_id = _section_id_for_label(manager, file_id, "INTRO")
    reqs_id = _section_id_for_label(manager, file_id, "REQS")
    alias_map = build_section_alias_map({file_id: manifest[file_id]["section_labels"]})

    spec_content = "Evidence: [F0001::INTRO], [F0001::REQS]"
    migrated = normalize_spec_pointers(spec_content, manager, alias_map)

    assert f"[spec_snapshot/{relpath}::{intro_id}]" in migrated
    assert f"[spec_snapshot/{relpath}::{reqs_id}]" in migrated


def test_normalize_decisions_pointers_converts_legacy_format(
    setup_pointer_migration_workspace,
) -> None:
    manager, manifest = setup_pointer_migration_workspace()
    file_id = _find_file_id_by_name(manager, "alpha.md")
    relpath = manager.state.file_manifest[file_id]["relpath"]
    section_id = _section_id_for_label(manager, file_id, "INTRO")
    alias_map = build_section_alias_map({file_id: manifest[file_id]["section_labels"]})

    decisions_content = "- Decision context [F0001::INTRO]"
    migrated = normalize_decisions_pointers(decisions_content, manager, alias_map)

    assert f"[spec_snapshot/{relpath}::{section_id}]" in migrated


def test_normalize_spec_pointers_preserves_multi_hop(setup_pointer_migration_workspace) -> None:
    manager, _ = setup_pointer_migration_workspace()
    spec_content = "Evidence: [LIB-0001::spec.md::REQ-LIB-0001-0001]"

    migrated = normalize_spec_pointers(spec_content, manager)

    assert migrated == spec_content


def test_normalize_spec_pointers_preserves_derived_pointers(
    setup_pointer_migration_workspace,
) -> None:
    manager, _ = setup_pointer_migration_workspace()
    spec_content = "Evidence: [LIB-0002::decisions.md::DEC-LIB-0002-0001]"

    migrated = normalize_spec_pointers(spec_content, manager)

    assert migrated == spec_content


def test_pointer_migration_resolves_section_aliases(setup_pointer_migration_workspace) -> None:
    manager, manifest = setup_pointer_migration_workspace()
    file_id = _find_file_id_by_name(manager, "alpha.md")
    relpath = manager.state.file_manifest[file_id]["relpath"]
    section_id = _section_id_for_label(manager, file_id, "INTRO")
    alias_map = build_section_alias_map({file_id: manifest[file_id]["section_labels"]})

    spec_content = "Evidence: [F0001::intro]"
    migrated = normalize_spec_pointers(spec_content, manager, alias_map)

    assert f"[spec_snapshot/{relpath}::{section_id}]" in migrated


def test_pointer_migration_handles_normalized_labels(setup_pointer_migration_workspace) -> None:
    manager, manifest = setup_pointer_migration_workspace()
    file_id = _find_file_id_by_name(manager, "alpha.md")
    relpath = manager.state.file_manifest[file_id]["relpath"]
    section_id = _section_id_for_label(manager, file_id, "USER_REQUIREMENTS")
    alias_map = build_section_alias_map({file_id: manifest[file_id]["section_labels"]})

    spec_content = "Evidence: [F0001::USER_REQUIREMENTS]"
    migrated = normalize_spec_pointers(spec_content, manager, alias_map)

    assert f"[spec_snapshot/{relpath}::{section_id}]" in migrated


def test_normalize_pointers_handles_invalid_file_refs(
    setup_pointer_migration_workspace,
) -> None:
    manager, _ = setup_pointer_migration_workspace()
    content = "Evidence: [F9999::MISSING] and [LIB-0001::spec.md::REQ-LIB-0001-0001]"

    cleaned = strip_invalid_file_pointers(
        content, manager.state.file_manifest, allow_multi_hop=False
    )
    cleaned_multi = strip_invalid_file_pointers(
        content, manager.state.file_manifest, allow_multi_hop=True
    )

    assert "[F9999::MISSING]" not in cleaned
    assert "[LIB-0001::spec.md::REQ-LIB-0001-0001]" not in cleaned
    assert "[F9999::MISSING]" not in cleaned_multi
    assert "[LIB-0001::spec.md::REQ-LIB-0001-0001]" in cleaned_multi


def test_normalize_pointers_handles_compound_citations(setup_pointer_migration_workspace) -> None:
    manager, manifest = setup_pointer_migration_workspace()
    file_id = _find_file_id_by_name(manager, "alpha.md")
    relpath = manager.state.file_manifest[file_id]["relpath"]
    intro_id = _section_id_for_label(manager, file_id, "INTRO")
    reqs_id = _section_id_for_label(manager, file_id, "REQS")
    alias_map = build_section_alias_map({file_id: manifest[file_id]["section_labels"]})

    spec_content = "Evidence: [F0001::INTRO, F0001::REQS]"
    normalized = normalize_compound_pointers(spec_content)
    migrated = normalize_spec_pointers(normalized, manager, alias_map)

    assert f"[spec_snapshot/{relpath}::{intro_id}]" in migrated
    assert f"[spec_snapshot/{relpath}::{reqs_id}]" in migrated


def test_normalize_pointers_preserves_non_pointer_brackets(
    setup_pointer_migration_workspace,
) -> None:
    manager, _ = setup_pointer_migration_workspace()
    spec_content = "Note: [optional parameter]"

    migrated = normalize_spec_pointers(spec_content, manager)

    assert migrated == spec_content


def test_normalize_pointers_uses_workspace_manifests(setup_pointer_migration_workspace) -> None:
    manager, _ = setup_pointer_migration_workspace()
    file_id = sorted(manager.state.file_manifest.keys())[0]
    relpath = manager.state.file_manifest[file_id]["relpath"]
    sections_data = manager.read_file_sections(file_id) or {}
    first_label = sections_data.get("sections", [])[0]["label"]
    first_section_id = sections_data.get("sections", [])[0]["section_id"]

    spec_content = f"Evidence: [{file_id}::{first_label}]"
    migrated = normalize_spec_pointers(spec_content, manager)

    assert f"[spec_snapshot/{relpath}::{first_section_id}]" in migrated

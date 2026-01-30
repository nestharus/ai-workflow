from __future__ import annotations

from pathlib import Path

from scripts.spec_refinement.workflows.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    resolve_section_reference,
)


def test_build_file_id_lookup_basic(tmp_path) -> None:
    alpha_path = tmp_path / "specs" / "alpha.md"
    alpha_path.parent.mkdir(parents=True, exist_ok=True)
    alpha_path.write_text("# Alpha\n", encoding="utf-8")

    file_manifest = {"file_001": str(alpha_path)}
    lookup = build_file_id_lookup(file_manifest)

    assert lookup["file_001"] == "file_001"
    assert lookup[str(alpha_path)] == "file_001"
    assert lookup[alpha_path.name] == "file_001"
    assert lookup[alpha_path.stem] == "file_001"


def test_build_file_id_lookup_collision(tmp_path) -> None:
    alpha_one = tmp_path / "specs" / "alpha.md"
    alpha_two = tmp_path / "docs" / "alpha.md"
    alpha_one.parent.mkdir(parents=True, exist_ok=True)
    alpha_two.parent.mkdir(parents=True, exist_ok=True)
    alpha_one.write_text("# Alpha\n", encoding="utf-8")
    alpha_two.write_text("# Alpha Two\n", encoding="utf-8")

    file_manifest = {
        "file_001": str(alpha_one),
        "file_002": str(alpha_two),
    }
    lookup = build_file_id_lookup(file_manifest)

    assert lookup[alpha_one.name] == "file_001"
    assert lookup[alpha_one.stem] == "file_001"
    assert lookup["file_002"] == "file_002"
    assert lookup[str(alpha_two)] == "file_002"


def test_build_section_alias_map_normalization() -> None:
    section_manifest = {
        "file_001": ["INTRO", "User Requirements"],
        "file_002": ["User-Requirements"],
    }
    alias_map = build_section_alias_map(section_manifest)

    assert alias_map["file_001"]["intro"] == "INTRO"
    assert alias_map["file_001"]["user_requirements"] == "User Requirements"
    assert alias_map["file_002"]["user_requirements"] == "User-Requirements"


def test_build_section_alias_map_collision() -> None:
    section_manifest = {"file_001": ["USER_REQUIREMENTS", "User Requirements"]}
    alias_map = build_section_alias_map(section_manifest)

    assert alias_map["file_001"]["user_requirements"] == "USER_REQUIREMENTS"


def test_resolve_section_reference_exact_match() -> None:
    alias_map = build_section_alias_map({"file_001": ["INTRO"]})

    assert resolve_section_reference("INTRO", "file_001", alias_map) == "INTRO"


def test_resolve_section_reference_case_insensitive() -> None:
    alias_map = build_section_alias_map({"file_001": ["INTRO"]})

    assert resolve_section_reference("intro", "file_001", alias_map) == "INTRO"


def test_resolve_section_reference_separator_normalization() -> None:
    alias_map = build_section_alias_map({"file_001": ["USER_REQUIREMENTS"]})

    assert (
        resolve_section_reference("user-requirements", "file_001", alias_map)
        == "USER_REQUIREMENTS"
    )


def test_resolve_section_reference_unknown() -> None:
    alias_map = build_section_alias_map({"file_001": ["INTRO"]})

    assert resolve_section_reference("unknown", "file_001", alias_map) is None

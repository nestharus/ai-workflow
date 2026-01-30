from __future__ import annotations

from pathlib import Path

from scripts.spec_refinement.workflows.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    resolve_section_reference,
    strip_invalid_file_pointers,
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
        resolve_section_reference("user-requirements", "file_001", alias_map) == "USER_REQUIREMENTS"
    )


def test_resolve_section_reference_unknown() -> None:
    alias_map = build_section_alias_map({"file_001": ["INTRO"]})

    assert resolve_section_reference("unknown", "file_001", alias_map) is None


def test_strip_invalid_file_pointers_preserves_valid() -> None:
    content = "See [file_001::INTRO] for details."
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers(content, file_manifest) == content


def test_strip_invalid_file_pointers_removes_unknown() -> None:
    content = "See [file_999::INTRO] for details."
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers(content, file_manifest) == "See for details."


def test_strip_invalid_file_pointers_removes_multi_hop_without_manifest() -> None:
    content = "See [lib_001::spec.md::REQS] for details."
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers(content, file_manifest) == "See for details."


def test_strip_invalid_file_pointers_removes_derived() -> None:
    content = "A [charter::INTENT] B [libraries/lib_001/spec.md::REQS] C"
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers(content, file_manifest) == "A B C"


def test_strip_invalid_file_pointers_collapses_whitespace() -> None:
    content = "Alpha  [file_999::INTRO]   beta"
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers(content, file_manifest) == "Alpha beta"


def test_strip_invalid_file_pointers_preserves_newlines() -> None:
    content = "Alpha [file_999::INTRO] \nBeta"
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers(content, file_manifest) == "Alpha\nBeta"


def test_strip_invalid_file_pointers_mixed_valid_invalid() -> None:
    content = "A [file_001::INTRO] B [file_999::INTRO] C"
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers(content, file_manifest) == "A [file_001::INTRO] B C"


def test_strip_invalid_file_pointers_handles_empty_and_none() -> None:
    file_manifest = {"file_001": "docs/intro.md"}

    assert strip_invalid_file_pointers("", file_manifest) == ""
    assert strip_invalid_file_pointers("No pointers here.", file_manifest) == "No pointers here."

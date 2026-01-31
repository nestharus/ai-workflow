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

    file_manifest = {"F0001": {"relpath": "specs/alpha.md", "sha256": "0" * 64}}
    lookup = build_file_id_lookup(file_manifest, tmp_path)

    assert lookup["F0001"] == "F0001"
    assert lookup["specs/alpha.md"] == "F0001"
    assert lookup[str(alpha_path.resolve())] == "F0001"
    assert lookup[alpha_path.name] == "F0001"
    assert lookup[alpha_path.stem] == "F0001"


def test_build_file_id_lookup_collision(tmp_path) -> None:
    alpha_one = tmp_path / "specs" / "alpha.md"
    alpha_two = tmp_path / "docs" / "alpha.md"
    alpha_one.parent.mkdir(parents=True, exist_ok=True)
    alpha_two.parent.mkdir(parents=True, exist_ok=True)
    alpha_one.write_text("# Alpha\n", encoding="utf-8")
    alpha_two.write_text("# Alpha Two\n", encoding="utf-8")

    file_manifest = {
        "F0001": {"relpath": "specs/alpha.md", "sha256": "0" * 64},
        "F0002": {"relpath": "docs/alpha.md", "sha256": "0" * 64},
    }
    lookup = build_file_id_lookup(file_manifest, tmp_path)

    assert lookup[alpha_one.name] == "F0001"
    assert lookup[alpha_one.stem] == "F0001"
    assert lookup["F0002"] == "F0002"
    assert lookup[str(alpha_two.resolve())] == "F0002"


def test_build_section_alias_map_normalization() -> None:
    section_manifest = {
        "F0001": ["INTRO", "User Requirements"],
        "F0002": ["User-Requirements"],
    }
    alias_map = build_section_alias_map(section_manifest)

    assert alias_map["F0001"]["intro"] == "INTRO"
    assert alias_map["F0001"]["user_requirements"] == "User Requirements"
    assert alias_map["F0002"]["user_requirements"] == "User-Requirements"


def test_build_section_alias_map_collision() -> None:
    section_manifest = {"F0001": ["USER_REQUIREMENTS", "User Requirements"]}
    alias_map = build_section_alias_map(section_manifest)

    assert alias_map["F0001"]["user_requirements"] == "USER_REQUIREMENTS"


def test_resolve_section_reference_exact_match() -> None:
    alias_map = build_section_alias_map({"F0001": ["INTRO"]})

    assert resolve_section_reference("INTRO", "F0001", alias_map) == "INTRO"


def test_resolve_section_reference_case_insensitive() -> None:
    alias_map = build_section_alias_map({"F0001": ["INTRO"]})

    assert resolve_section_reference("intro", "F0001", alias_map) == "INTRO"


def test_resolve_section_reference_separator_normalization() -> None:
    alias_map = build_section_alias_map({"F0001": ["USER_REQUIREMENTS"]})

    assert resolve_section_reference("user-requirements", "F0001", alias_map) == "USER_REQUIREMENTS"


def test_resolve_section_reference_unknown() -> None:
    alias_map = build_section_alias_map({"F0001": ["INTRO"]})

    assert resolve_section_reference("unknown", "F0001", alias_map) is None


def test_strip_invalid_file_pointers_preserves_valid() -> None:
    content = "See [F0001::INTRO] for details."
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == content


def test_strip_invalid_file_pointers_removes_unknown() -> None:
    content = "See [F0999::INTRO] for details."
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == "See for details."


def test_strip_invalid_file_pointers_removes_multi_hop_without_manifest() -> None:
    content = "See [lib_001::spec.md::REQS] for details."
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == "See for details."


def test_strip_invalid_file_pointers_removes_derived() -> None:
    content = "A [charter::INTENT] B [libraries/lib_001/spec.md::REQS] C"
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == "A B C"


def test_strip_invalid_file_pointers_collapses_whitespace() -> None:
    content = "Alpha  [F0999::INTRO]   beta"
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == "Alpha beta"


def test_strip_invalid_file_pointers_preserves_newlines() -> None:
    content = "Alpha [F0999::INTRO] \nBeta"
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == "Alpha\nBeta"


def test_strip_invalid_file_pointers_mixed_valid_invalid() -> None:
    content = "A [F0001::INTRO] B [F0999::INTRO] C"
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == "A [F0001::INTRO] B C"


def test_strip_invalid_file_pointers_handles_empty_and_none() -> None:
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers("", file_manifest) == ""
    assert strip_invalid_file_pointers("No pointers here.", file_manifest) == "No pointers here."

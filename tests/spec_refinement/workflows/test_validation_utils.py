from __future__ import annotations

from pathlib import Path

from spec_manager.refinement.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
    fix_cross_file_section_pointers,
    resolve_section_reference,
    strip_invalid_file_pointers,
    strip_invalid_section_pointers,
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
    content = "See [LIB-0001::spec.md::REQS] for details."
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}

    assert strip_invalid_file_pointers(content, file_manifest) == "See for details."


def test_strip_invalid_file_pointers_removes_derived() -> None:
    content = "A [charter::INTENT] B [libraries/LIB-0001/spec.md::REQS] C"
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


def test_fix_cross_file_section_pointers_rewrites_mismatched() -> None:
    file_manifest = {
        "F0001": {"relpath": "math/base.md", "sha256": "0" * 64},
        "F0002": {"relpath": "math/recurrence.md", "sha256": "0" * 64},
    }
    content = "See [spec_snapshot/math/base.md::SEC-F0002-0001] for details."
    result = fix_cross_file_section_pointers(content, file_manifest)
    assert result == "See [spec_snapshot/math/recurrence.md::SEC-F0002-0001] for details."


def test_fix_cross_file_section_pointers_preserves_correct() -> None:
    file_manifest = {
        "F0001": {"relpath": "math/base.md", "sha256": "0" * 64},
    }
    content = "See [spec_snapshot/math/base.md::SEC-F0001-0001] for details."
    result = fix_cross_file_section_pointers(content, file_manifest)
    assert result == content


def test_fix_cross_file_section_pointers_no_pointers() -> None:
    file_manifest = {"F0001": {"relpath": "docs/intro.md", "sha256": "0" * 64}}
    assert (
        fix_cross_file_section_pointers("No pointers here.", file_manifest) == "No pointers here."
    )


def test_fix_cross_file_section_pointers_unknown_section_file() -> None:
    file_manifest = {
        "F0001": {"relpath": "math/base.md", "sha256": "0" * 64},
    }
    # SEC-F9999 doesn't exist in manifest, should be left unchanged
    content = "See [spec_snapshot/math/base.md::SEC-F9999-0001] for details."
    result = fix_cross_file_section_pointers(content, file_manifest)
    assert result == content


def test_fix_cross_file_section_pointers_multiple_replacements() -> None:
    file_manifest = {
        "F0001": {"relpath": "a.md", "sha256": "0" * 64},
        "F0002": {"relpath": "b.md", "sha256": "0" * 64},
        "F0003": {"relpath": "c.md", "sha256": "0" * 64},
    }
    content = "[spec_snapshot/a.md::SEC-F0002-0001] and [spec_snapshot/c.md::SEC-F0001-0003]"
    result = fix_cross_file_section_pointers(content, file_manifest)
    assert result == (
        "[spec_snapshot/b.md::SEC-F0002-0001] and [spec_snapshot/a.md::SEC-F0001-0003]"
    )


def test_strip_invalid_section_pointers_removes_nonexistent() -> None:
    manifest = {"F0001": {"relpath": "a.md", "sha256": "0" * 64}}

    def _section_reader(file_id: str):
        if file_id == "F0001":
            return {"sections": [{"section_id": "SEC-F0001-0001"}]}
        return None

    content = "Text [spec_snapshot/a.md::SEC-F0001-0001] and [spec_snapshot/a.md::SEC-F0001-9999]"
    result = strip_invalid_section_pointers(content, manifest, _section_reader)
    assert "[spec_snapshot/a.md::SEC-F0001-0001]" in result
    assert "SEC-F0001-9999" not in result


def test_strip_invalid_section_pointers_preserves_all_valid() -> None:
    manifest = {"F0001": {"relpath": "a.md", "sha256": "0" * 64}}

    def _section_reader(file_id: str):
        if file_id == "F0001":
            return {
                "sections": [{"section_id": "SEC-F0001-0001"}, {"section_id": "SEC-F0001-0002"}]
            }
        return None

    content = "[spec_snapshot/a.md::SEC-F0001-0001] and [spec_snapshot/a.md::SEC-F0001-0002]"
    result = strip_invalid_section_pointers(content, manifest, _section_reader)
    assert result == content

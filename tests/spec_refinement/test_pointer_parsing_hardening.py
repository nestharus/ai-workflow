from __future__ import annotations

from spec_manager.refinement.formats import parse_evidence_pointer
from spec_manager.refinement.workflows.sublibrary_detection import _validate_sublibrary_proposal


def _build_sublibrary_proposal(pointer: str) -> dict[str, object]:
    return {
        "sub_lib_id": "SUBLIB-0001",
        "charter": "Focused charter for testing.",
        "evidence_partition": [pointer],
    }


def test_parse_evidence_pointer_accepts_new_format() -> None:
    result = parse_evidence_pointer("[spec_snapshot/requirements.md::SEC-F0001-0001]")

    assert result is not None
    assert result["format"] == "new"
    assert result["file_ref"] == "requirements.md"
    assert result["section_ref"] == "SEC-F0001-0001"


def test_parse_evidence_pointer_accepts_legacy_format() -> None:
    result = parse_evidence_pointer("[F0001::INTRO]")

    assert result is not None
    assert result["format"] == "legacy"
    assert result["file_ref"] == "F0001"
    assert result["section_ref"] == "INTRO"


def test_parse_evidence_pointer_accepts_multi_hop_when_allowed() -> None:
    result = parse_evidence_pointer(
        "[LIB-0001::spec.md::DTL-LIB-0001-0003]",
        allow_multi_hop=True,
    )

    assert result is not None
    assert result["file_ref"] == "LIB-0001"
    assert result["intermediate"] == "spec.md"
    assert result["section_ref"] == "DTL-LIB-0001-0003"


def test_parse_evidence_pointer_rejects_multi_hop_when_disallowed() -> None:
    result = parse_evidence_pointer(
        "[LIB-0001::spec.md::DTL-LIB-0001-0003]",
        allow_multi_hop=False,
    )

    assert result is None


def test_parse_evidence_pointer_handles_unbracket_legacy_format() -> None:
    result = parse_evidence_pointer("F0001::INTRO")

    assert result is not None
    assert result["format"] == "legacy"


def test_parse_evidence_pointer_returns_none_for_malformed() -> None:
    result = parse_evidence_pointer("invalid-pointer")

    assert result is None


def test_parse_evidence_pointer_returns_none_for_empty_string() -> None:
    result = parse_evidence_pointer("")

    assert result is None


def test_sublibrary_validation_rejects_malformed_pointer(spec_refinement_workspace, fs) -> None:
    manager, _ = spec_refinement_workspace()
    proposal = _build_sublibrary_proposal("not-a-pointer")

    issues = _validate_sublibrary_proposal(manager, "LIB-0001", proposal, 0.2)

    assert any(
        issue.get("type") == "malformed_evidence_pointer"
        and "Evidence pointer format is invalid" in issue.get("message", "")
        for issue in issues
    )


def test_sublibrary_validation_accepts_new_format_pointer(spec_refinement_workspace, fs) -> None:
    manager, _ = spec_refinement_workspace()
    first_file_id = sorted(manager.state.file_manifest)[0]
    first_section_id = manager.state.section_manifest[first_file_id][0]
    relpath = manager.state.file_manifest[first_file_id]["relpath"]
    proposal = _build_sublibrary_proposal(f"[spec_snapshot/{relpath}::{first_section_id}]")

    issues = _validate_sublibrary_proposal(manager, "LIB-0001", proposal, 0.2)

    assert issues == []


def test_sublibrary_validation_accepts_legacy_format_pointer(spec_refinement_workspace, fs) -> None:
    manager, _ = spec_refinement_workspace()
    first_file_id = sorted(manager.state.file_manifest)[0]
    first_section_id = manager.state.section_manifest[first_file_id][0]
    proposal = _build_sublibrary_proposal(f"[{first_file_id}::{first_section_id}]")

    issues = _validate_sublibrary_proposal(manager, "LIB-0001", proposal, 0.2)

    assert issues == []

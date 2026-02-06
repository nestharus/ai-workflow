from __future__ import annotations

import pytest
from pydantic import ValidationError
from spec_manager.schemas.review_actions import (
    ELEMENT_ID_RE,
    MULTI_HOP_POINTER_RE,
    SOURCE_POINTER_RE,
    ReviewAction,
    validate_pointer_format,
    validate_pointer_references,
)


def _setup_libraries(manager, lib_ids: list[str]) -> None:
    for lib_id in lib_ids:
        manager.state.register_library_id(lib_id)


def test_validate_pointer_format_multi_hop_spec() -> None:
    assert validate_pointer_format("[LIB-0001::spec.md::DTL-LIB-0001-0001]") is True


def test_validate_pointer_format_multi_hop_charter() -> None:
    assert validate_pointer_format("[LIB-0001::charter.md::OVERVIEW]") is True


def test_validate_pointer_format_multi_hop_analysis() -> None:
    assert validate_pointer_format("[LIB-0001::analysis.md::ANL-LIB-0001-0001]") is True


def test_validate_pointer_format_library_doc() -> None:
    assert validate_pointer_format("[LIB-0001::spec.md]") is True


def test_validate_pointer_format_source_pointer() -> None:
    assert validate_pointer_format("[spec_snapshot/alpha.md::SEC-F0001-0001]") is True


def test_validate_pointer_format_invalid_no_brackets() -> None:
    assert validate_pointer_format("LIB-0001::spec.md::DTL") is False


def test_validate_pointer_format_invalid_single_colon() -> None:
    assert validate_pointer_format("[LIB-0001:spec.md]") is False


def test_validate_pointer_format_invalid_lib_id() -> None:
    assert validate_pointer_format("[LIB-1::spec.md::DTL]") is False


def test_validate_pointer_references_valid_multi_hop(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _setup_libraries(manager, ["LIB-0001"])

    valid, error = validate_pointer_references(
        "[LIB-0001::spec.md::DTL-LIB-0001-0001]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is True
    assert error is None


def test_validate_pointer_references_unknown_library(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _setup_libraries(manager, ["LIB-0001"])

    valid, error = validate_pointer_references(
        "[LIB-9999::spec.md::DTL-LIB-9999-0001]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is False
    assert "Unknown library id" in (error or "")


def test_validate_pointer_references_unknown_spec_file(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _setup_libraries(manager, ["LIB-0001"])

    valid, error = validate_pointer_references(
        "[LIB-0001::unknown.md::DTL-LIB-0001-0001]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is False
    assert "Unknown spec file" in (error or "")


def test_validate_pointer_references_invalid_section_ref(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _setup_libraries(manager, ["LIB-0001"])

    valid, error = validate_pointer_references(
        "[LIB-0001::spec.md::INVALID-REF]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is False
    assert "Invalid section reference" in (error or "")


def test_validate_pointer_references_valid_source_pointer(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    file_id = next(iter(manager.state.file_manifest))
    relpath = manager.state.file_manifest[file_id]["relpath"]
    section_id = manager.state.section_manifest[file_id][0]

    valid, error = validate_pointer_references(
        f"[spec_snapshot/{relpath}::{section_id}]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is True
    assert error is None


def test_validate_pointer_references_unknown_file_ref(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()

    valid, error = validate_pointer_references(
        "[spec_snapshot/unknown.md::SEC-F0001-0001]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is False
    assert "Unknown file reference" in (error or "")


def test_validate_pointer_references_library_doc_pointer(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _setup_libraries(manager, ["LIB-0001"])

    valid, error = validate_pointer_references(
        "[LIB-0001::charter.md]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is True
    assert error is None


def test_element_id_regex_valid_detail() -> None:
    assert ELEMENT_ID_RE.fullmatch("DTL-LIB-0001-0001")


def test_element_id_regex_valid_constraint() -> None:
    assert ELEMENT_ID_RE.fullmatch("CON-LIB-0001-0001")


def test_element_id_regex_valid_analysis() -> None:
    assert ELEMENT_ID_RE.fullmatch("ANL-LIB-0001-0001")


def test_element_id_regex_invalid_format() -> None:
    assert ELEMENT_ID_RE.fullmatch("DTL-0001") is None


def test_element_id_regex_invalid_lib_id() -> None:
    assert ELEMENT_ID_RE.fullmatch("DTL-LIB-1-0001") is None


def test_review_action_validates_all_pointers(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _setup_libraries(manager, ["LIB-0001"])
    file_id = next(iter(manager.state.file_manifest))
    relpath = manager.state.file_manifest[file_id]["relpath"]
    section_id = manager.state.section_manifest[file_id][0]

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "merge",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": [],
            "summary": "Merge",
            "rationale": "Rationale",
            "evidence": [
                "[LIB-0001::spec.md::DTL-LIB-0001-0001]",
                f"[spec_snapshot/{relpath}::{section_id}]",
                "[LIB-0001::charter.md]",
            ],
        }
    )

    for pointer in action.evidence:
        valid, error = validate_pointer_references(
            pointer,
            manager.state.file_manifest,
            manager.allocated_library_ids,
        )
        assert valid is True
        assert error is None


def test_review_action_rejects_invalid_pointer_in_evidence() -> None:
    with pytest.raises(ValidationError):
        ReviewAction.model_validate(
            {
                "action_id": "ACT-0001",
                "type": "merge",
                "status": "proposed",
                "source_libs": ["LIB-0001"],
                "target_libs": [],
                "elements": [],
                "summary": "Merge",
                "rationale": "Rationale",
                "evidence": ["[INVALID]"],
            }
        )


def test_validate_pointer_references_with_file_manifest(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    file_id = next(iter(manager.state.file_manifest))
    section_id = manager.state.section_manifest[file_id][0]

    valid, error = validate_pointer_references(
        f"[spec_snapshot/{file_id}::{section_id}]",
        manager.state.file_manifest,
        manager.allocated_library_ids,
    )

    assert valid is True
    assert error is None

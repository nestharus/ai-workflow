from __future__ import annotations

from pathlib import Path

from scripts.spec_refinement.workflows.spec_patches import (
    VALID_SPEC_SECTIONS,
    PatchOperation,
    SpecDocument,
    apply_patch,
    parse_patch_json,
    render_spec,
    validate_patch_citations,
    validate_patch_operation,
)
from scripts.spec_refinement.workflows.validation_utils import (
    build_file_id_lookup,
    build_section_alias_map,
)


def test_parse_patch_json_extracts_operations() -> None:
    output = (
        "Note:\n```json\n"
        '[{"op": "add", "section": "Requirements", '
        '"bullet_index": null, "content": "Add thing", '
        '"citations": ["[F0001::INTRO]"]}]\n```'
    )
    patch_set = parse_patch_json(output)

    assert patch_set.operations
    operation = patch_set.operations[0]
    assert operation.op == "add"
    assert operation.section == "Requirements"
    assert operation.citations == ["[F0001::INTRO]"]


def test_apply_patch_add_edit_move() -> None:
    content = (
        "# Library Spec: lib_001\n\n"
        "## Intent\nOwn keyword behaviors.\n\n"
        "## Requirements\n"
        "- First requirement [F0001::INTRO]\n"
        "- Second requirement [F0001::INTRO]\n\n"
        "## Decisions Needed\n"
        "- Pending question [F0001::INTRO]\n"
    )
    spec_doc = SpecDocument(content)

    apply_patch(
        spec_doc,
        PatchOperation(
            op="add",
            section="Requirements",
            bullet_index=None,
            content="Third requirement",
            citations=["[F0001::INTRO]"],
        ),
    )
    apply_patch(
        spec_doc,
        PatchOperation(
            op="edit",
            section="Requirements",
            bullet_index=0,
            content="Updated requirement",
            citations=["[F0001::INTRO]"],
        ),
    )
    apply_patch(
        spec_doc,
        PatchOperation(
            op="move",
            section="Decisions Needed",
            source_section="Requirements",
            bullet_index=1,
            content="",
            citations=[],
        ),
    )

    rendered = render_spec(spec_doc, "lib_001")
    assert "- Updated requirement [F0001::INTRO]" in rendered
    assert "- Third requirement [F0001::INTRO]" in rendered
    decisions_block = rendered.split("## Decisions Needed", 1)[1]
    assert "Second requirement" in decisions_block


def test_validate_patch_citations() -> None:
    file_manifest = {"F0001": {"relpath": "alpha.md", "sha256": "0" * 64}}
    section_manifest = {"F0001": ["INTRO", "DETAILS"]}
    file_id_lookup = build_file_id_lookup(file_manifest, Path("/work/specs"))
    section_alias_map = build_section_alias_map(section_manifest)

    operations = [
        PatchOperation(
            op="add",
            section="Requirements",
            bullet_index=None,
            content="New requirement",
            citations=["[F0001::INTRO]"],
        )
    ]
    issues = validate_patch_citations(
        operations,
        file_id_lookup,
        section_alias_map,
        lib_id="lib_001",
    )
    assert issues == []

    invalid_ops = [
        PatchOperation(
            op="add",
            section="Requirements",
            bullet_index=None,
            content="Bad requirement",
            citations=["[F0999::INTRO]", "[F0001::MISSING]"],
        )
    ]
    issues = validate_patch_citations(
        invalid_ops,
        file_id_lookup,
        section_alias_map,
        lib_id="lib_001",
    )
    issue_types = {issue["type"] for issue in issues}
    assert "unknown_file_reference" in issue_types
    assert "unknown_section_reference" in issue_types


def test_patch_operations_forbid_delete() -> None:
    operation = PatchOperation(
        op="delete",  # type: ignore[arg-type]
        section=VALID_SPEC_SECTIONS[0],
        bullet_index=None,
        content="",
        citations=[],
    )
    errors = validate_patch_operation(operation, VALID_SPEC_SECTIONS)
    assert any("Invalid op" in error for error in errors)

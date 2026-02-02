from __future__ import annotations

from spec_manager.refinement.workflows.spec_building import (
    _build_full_spec_prompt_for_metrics,
    _build_patch_prompt,
)


def test_patch_prompt_reduces_context() -> None:
    lib_id = "lib_001"
    charter_content = (
        "# Library Charter: lib_001\n\n## Intent\nTest intent.\n\n## Boundaries\nTest.\n"
    )
    spec_content = "# Library Spec: lib_001\n\n## Requirements\n" + "".join(
        f"- Requirement {i} [F0001::INTRO]\n" for i in range(30)
    )
    file_content = "## Intro\nDetails.\n"
    evidence_sections = ["INTRO"]
    valid_sections = ["INTRO"]
    valid_file_ids = ["F0001"]

    patch_prompt = _build_patch_prompt(
        lib_id,
        charter_content,
        spec_content,
        "F0001",
        file_content,
        evidence_sections,
        valid_sections,
        valid_file_ids,
        gaps=None,
    )
    legacy_prompt = _build_full_spec_prompt_for_metrics(
        lib_id,
        charter_content,
        spec_content,
        "F0001",
        file_content,
        evidence_sections,
        valid_sections,
        gaps=None,
    )

    assert len(patch_prompt) < len(legacy_prompt)

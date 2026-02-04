from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.schemas.patch_output import (
    PatchOutputSchema,
    read_patch_output_json,
    write_patch_output_json,
)


def _create_valid_patch() -> str:
    return (
        "diff --git a/file.txt b/file.txt\n"
        "index 0000000..1111111 100644\n"
        "--- a/file.txt\n"
        "+++ b/file.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )


def test_patch_output_valid() -> None:
    output = PatchOutputSchema.model_validate({"patch": _create_valid_patch()})
    assert "diff --git" in output.patch


def test_patch_output_empty_patch() -> None:
    with pytest.raises(ValidationError):
        PatchOutputSchema.model_validate({"patch": ""})


def test_patch_output_missing_diff_header() -> None:
    with pytest.raises(ValidationError):
        PatchOutputSchema.model_validate({"patch": "@@ -1 +1 @@\n-old\n+new"})


def test_patch_output_json_round_trip(fs) -> None:
    output = PatchOutputSchema.model_validate({"patch": _create_valid_patch()})
    output_path = Path("/work/patch_output.json")
    write_patch_output_json(output, output_path)

    loaded = read_patch_output_json(output_path)
    assert loaded.patch == output.patch

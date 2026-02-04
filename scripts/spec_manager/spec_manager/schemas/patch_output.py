"""Schemas and helpers for patch output artifacts.

Example:
    output = PatchOutputSchema(patch="diff --git a/file.txt b/file.txt\n...")
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, field_validator


class PatchOutputSchema(BaseModel):
    """Schema for LLM-generated patch outputs."""

    patch: str

    @field_validator("patch")
    @classmethod
    def validate_patch(cls, value: str) -> str:
        """Ensure patch content is non-empty and contains unified diff markers.

        Args:
            value: Patch string.

        Returns:
            The validated patch string.

        Raises:
            ValueError: When the patch is empty or missing diff markers.

        Example:
            PatchOutputSchema(patch="diff --git a/file.txt b/file.txt\n...")
        """
        if not value.strip():
            raise ValueError("patch must be non-empty")
        if "diff --git" not in value:
            raise ValueError("patch must contain unified diff markers")
        return value


def write_patch_output_json(output: PatchOutputSchema, output_path: Path) -> None:
    """Write a patch output JSON file to disk.

    Args:
        output: PatchOutputSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_patch_output_json(output, Path("reports/patch_output.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = output.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_patch_output_json(input_path: Path) -> PatchOutputSchema:
    """Read and validate a patch output JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated PatchOutputSchema instance.

    Example:
        output = read_patch_output_json(Path("reports/patch_output.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return PatchOutputSchema.model_validate(json.loads(content))


__all__ = [
    "PatchOutputSchema",
    "read_patch_output_json",
    "write_patch_output_json",
]

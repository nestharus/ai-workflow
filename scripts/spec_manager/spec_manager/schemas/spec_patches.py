"""Schemas for spec patch structured output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SpecPatchOp(BaseModel):
    """Operation to apply to a spec file section."""

    op: Literal["add", "move", "edit"]
    section: str
    bullet_index: int | None = None
    source_section: str | None = None
    content: str
    citations: list[str]


class SpecPatchOutput(BaseModel):
    """Structured output containing patches for a spec file."""

    file_id: str
    lib_id: str
    patches: list[SpecPatchOp]

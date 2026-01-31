"""Schemas for spec patch structured output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SpecPatchOp(BaseModel):
    op: Literal["add", "move", "edit"]
    section: str
    bullet_index: int | None = None
    content: str
    citations: list[str]


class SpecPatchOutput(BaseModel):
    file_id: str
    lib_id: str
    patches: list[SpecPatchOp]

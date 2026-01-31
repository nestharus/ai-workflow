"""Schemas for architecture brief extraction output."""

from __future__ import annotations

from pydantic import BaseModel


class ArchitectureBrief(BaseModel):
    lib_id: str
    intent: str
    boundaries: str
    dependencies: list[str]
    constraints: list[str]
    interfaces: list[str]

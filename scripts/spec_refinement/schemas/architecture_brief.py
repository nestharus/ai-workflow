"""Schemas for architecture brief extraction output."""

from __future__ import annotations

from pydantic import BaseModel


class ArchitectureBriefEntry(BaseModel):
    """Entry representing an architecture constraint or interface."""

    type: str
    description: str
    citation: str


class ArchitectureBrief(BaseModel):
    """Brief architectural characterization of a library."""

    lib_id: str
    intent: str
    boundaries: str
    dependencies: list[str]
    constraints: list[ArchitectureBriefEntry]
    interfaces: list[ArchitectureBriefEntry]

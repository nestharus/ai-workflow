"""Schemas for hollowed-out spec evidence store."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ParagraphKind(str, Enum):
    """Classification of a paragraph within a spec section."""

    PROSE = "PROSE"
    BULLET_LIST = "BULLET_LIST"
    CODE_BLOCK = "CODE_BLOCK"
    TABLE = "TABLE"
    HEADING = "HEADING"


class HollowedParagraph(BaseModel):
    """A single searchable paragraph from a hollowed-out spec.

    Attributes:
        paragraph_id: Unique ID (HPARA-{lib_id}-{ordinal:04d})
        section_path: Dot-separated section hierarchy (e.g. "Details.Authentication")
        kind: Classification of content type
        text: Full text of the paragraph
        keywords: Extracted keywords for search
        entity_refs: Entity IDs referenced in this paragraph
        line_start: Start line in the original spec.md
        line_end: End line in the original spec.md
    """

    paragraph_id: str
    section_path: str
    kind: ParagraphKind
    text: str
    keywords: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)


class HollowedSection(BaseModel):
    """A section skeleton from the hollowed-out spec.

    Attributes:
        section_id: Section identifier
        heading: Section heading text
        level: Heading level (1-6)
        summary: One-sentence summary of the section
        paragraph_ids: IDs of paragraphs in this section
        child_section_ids: IDs of nested subsections
    """

    section_id: str
    heading: str
    level: int = Field(ge=1, le=6)
    summary: str = ""
    paragraph_ids: list[str] = Field(default_factory=list)
    child_section_ids: list[str] = Field(default_factory=list)


class HollowedSpec(BaseModel):
    """A hollowed-out complete spec with searchable evidence.

    Attributes:
        schema_version: Schema version
        lib_id: Library ID this spec belongs to
        spec_hash: SHA-256 of the original spec.md content
        hollowed_at: ISO8601 timestamp
        sections: Ordered list of section skeletons
        paragraphs: All paragraphs indexed by paragraph_id
        entity_index: Mapping of entity name -> list of paragraph_ids
        keyword_index: Mapping of keyword -> list of paragraph_ids
    """

    schema_version: str = "1.0"
    lib_id: str
    spec_hash: str
    hollowed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sections: list[HollowedSection] = Field(default_factory=list)
    paragraphs: dict[str, HollowedParagraph] = Field(default_factory=dict)
    entity_index: dict[str, list[str]] = Field(default_factory=dict)
    keyword_index: dict[str, list[str]] = Field(default_factory=dict)

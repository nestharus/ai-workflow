"""Schemas for Phase 1 file manifest structure."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class FileManifestEntry(BaseModel):
    file_id: str
    relpath: str
    sha256: str = Field(min_length=64, max_length=64)
    line_count: int = Field(ge=0)
    created_at: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value


class FilesManifest(BaseModel):
    schema_version: str = "1.0"
    files: dict[str, FileManifestEntry]
    run_id: str
    created_at: str

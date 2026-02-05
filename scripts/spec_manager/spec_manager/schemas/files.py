"""Schemas for Phase 1 file manifest structure.

Schema Version History:
- 1.0: Original format with file_id
- 2.0: Added file_uid (rename from file_id) and rev_id for revision tracking
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class FileManifestEntry(BaseModel):
    """Entry in the file manifest (v2.0 schema).

    Attributes:
        file_uid: Stable file identifier (F####)
        rev_id: Revision identifier (R####)
        relpath: Relative path (POSIX-normalized)
        sha256: Content hash (64 hex chars)
        line_count: Number of lines in file
        created_at: ISO8601 timestamp
    """

    file_uid: str
    rev_id: str
    relpath: str
    sha256: str = Field(min_length=64, max_length=64)
    line_count: int = Field(ge=0)
    created_at: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        """Validate SHA256 format."""
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value

    @field_validator("file_uid")
    @classmethod
    def validate_file_uid(cls, value: str) -> str:
        """Validate file_uid format (F####)."""
        if not re.fullmatch(r"F\d{4}", value):
            raise ValueError("file_uid must match F#### pattern")
        return value

    @field_validator("rev_id")
    @classmethod
    def validate_rev_id(cls, value: str) -> str:
        """Validate rev_id format (R####)."""
        if not re.fullmatch(r"R\d{4}", value):
            raise ValueError("rev_id must match R#### pattern")
        return value


class LegacyFileManifestEntry(BaseModel):
    """Legacy entry in the file manifest (v1.0 schema).

    This model supports reading manifests created before the revision
    tracking update. Use FileManifestEntry for new manifests.
    """

    file_id: str
    relpath: str
    sha256: str = Field(min_length=64, max_length=64)
    line_count: int = Field(ge=0)
    created_at: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        """Validate SHA256 format."""
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value


class FilesManifest(BaseModel):
    """File manifest container (v2.0 schema).

    Attributes:
        schema_version: Schema version (2.0 for revision tracking)
        files: Map of file_uid to entry
        run_id: Current run identifier
        created_at: ISO8601 timestamp
    """

    schema_version: str = "2.0"
    files: dict[str, FileManifestEntry]
    run_id: str
    created_at: str


class LegacyFilesManifest(BaseModel):
    """Legacy file manifest container (v1.0 schema).

    This model supports reading manifests created before the revision
    tracking update.
    """

    schema_version: str = "1.0"
    files: dict[str, LegacyFileManifestEntry]
    run_id: str
    created_at: str


def is_legacy_manifest(manifest_data: dict[str, object]) -> bool:
    """Check if manifest data is in legacy format.

    Args:
        manifest_data: Dictionary of manifest fields

    Returns:
        True if legacy format (schema_version 1.0 or missing rev_id in entries)
    """
    version = manifest_data.get("schema_version", "1.0")
    if version == "1.0":
        return True
    files = manifest_data.get("files", {})
    if isinstance(files, dict) and files:
        first_entry = next(iter(files.values()), {})
        if isinstance(first_entry, dict):
            return "rev_id" not in first_entry
    return False

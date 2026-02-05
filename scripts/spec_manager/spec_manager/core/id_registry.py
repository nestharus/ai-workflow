"""Persistent ID registries for stable file and revision identification.

This module implements ALG-CORE-0001 (AllocateFileUid) and ALG-CORE-0002 (AllocateRevisionId)
from the design specification. The registries provide:

- FileUidRegistry: Stable F#### identifiers that persist across runs
- RevisionRegistry: Content-based R#### revision identifiers per file

Storage: `runs/_registry/file_uids.json` and `runs/_registry/revisions.json`
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class FileUidEntry:
    """Entry in the file UID registry (DS-CORE-0003)."""

    file_uid: str  # F####
    canonical_path: str  # Relative path (POSIX-normalized)
    first_seen_run_id: str
    created_at: str  # ISO8601

    def to_dict(self) -> dict[str, str]:
        """Serialize entry to dictionary."""
        return {
            "file_uid": self.file_uid,
            "canonical_path": self.canonical_path,
            "first_seen_run_id": self.first_seen_run_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> FileUidEntry:
        """Deserialize entry from dictionary."""
        return cls(
            file_uid=data["file_uid"],
            canonical_path=data["canonical_path"],
            first_seen_run_id=data["first_seen_run_id"],
            created_at=data["created_at"],
        )


@dataclass
class FileUidRegistry:
    """Registry for persistent file UID allocation (ALG-CORE-0001).

    File UIDs persist across runs, ensuring that adding/removing files
    does not change existing IDs. The registry is keyed by canonical
    (POSIX-normalized) relative paths.
    """

    entries: dict[str, FileUidEntry] = field(default_factory=dict)  # keyed by canonical_path
    next_seq: int = 1

    def allocate(self, canonical_path: str, run_id: str) -> str:
        """Allocate or retrieve a file UID for the given path.

        ALG-CORE-0001 implementation: Returns existing UID if path is known,
        otherwise allocates a new sequential UID.

        Args:
            canonical_path: POSIX-normalized relative path
            run_id: Current run identifier

        Returns:
            File UID in F#### format
        """
        if canonical_path in self.entries:
            return self.entries[canonical_path].file_uid

        file_uid = f"F{self.next_seq:04d}"
        self.entries[canonical_path] = FileUidEntry(
            file_uid=file_uid,
            canonical_path=canonical_path,
            first_seen_run_id=run_id,
            created_at=datetime.now().isoformat(),
        )
        self.next_seq += 1
        return file_uid

    def get_uid(self, canonical_path: str) -> str | None:
        """Get file UID for a path without allocating.

        Returns:
            File UID if path is registered, None otherwise
        """
        entry = self.entries.get(canonical_path)
        return entry.file_uid if entry else None

    def get_path(self, file_uid: str) -> str | None:
        """Get canonical path for a file UID.

        Returns:
            Canonical path if UID is registered, None otherwise
        """
        for entry in self.entries.values():
            if entry.file_uid == file_uid:
                return entry.canonical_path
        return None

    def to_dict(self) -> dict[str, object]:
        """Serialize registry to dictionary for JSON storage."""
        return {
            "schema_version": "1.0",
            "next_seq": self.next_seq,
            "entries": {
                path: entry.to_dict() for path, entry in self.entries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> FileUidRegistry:
        """Deserialize registry from dictionary."""
        entries_data = data.get("entries", {})
        if not isinstance(entries_data, dict):
            entries_data = {}
        entries = {
            path: FileUidEntry.from_dict(entry_data)
            for path, entry_data in entries_data.items()
            if isinstance(entry_data, dict)
        }
        next_seq = data.get("next_seq", 1)
        if not isinstance(next_seq, int):
            next_seq = 1
        return cls(entries=entries, next_seq=next_seq)

    def save(self, path: Path) -> None:
        """Save registry to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> FileUidRegistry:
        """Load registry from JSON file, or create empty if not exists."""
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


@dataclass
class RevisionEntry:
    """Entry in the revision registry."""

    rev_id: str  # R####
    file_uid: str
    sha256: str  # Content hash
    created_at: str  # ISO8601

    def to_dict(self) -> dict[str, str]:
        """Serialize entry to dictionary."""
        return {
            "rev_id": self.rev_id,
            "file_uid": self.file_uid,
            "sha256": self.sha256,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> RevisionEntry:
        """Deserialize entry from dictionary."""
        return cls(
            rev_id=data["rev_id"],
            file_uid=data["file_uid"],
            sha256=data["sha256"],
            created_at=data["created_at"],
        )


@dataclass
class RevisionRegistry:
    """Registry for content-based revision tracking (ALG-CORE-0002).

    Revisions are tracked per file_uid, keyed by content hash. This enables
    cross-revision atom matching via stable fingerprints.

    CON-0001 Compliance: Revisions are append-only. Once a revision entry
    exists, it is never mutated or removed.
    """

    entries: dict[str, list[RevisionEntry]] = field(default_factory=dict)  # keyed by file_uid

    def allocate(self, file_uid: str, sha256: str) -> str:
        """Allocate or retrieve a revision ID for the given content hash.

        ALG-CORE-0002 implementation (CON-0001 compliant):
        - Returns existing rev_id if content unchanged
        - Allocates new revision (append-only) for new content

        Args:
            file_uid: File UID (F####)
            sha256: Content hash of the file

        Returns:
            Revision ID in R#### format
        """
        revisions = self.entries.get(file_uid, [])

        # Return existing rev_id if content unchanged
        for rev in revisions:
            if rev.sha256 == sha256:
                return rev.rev_id

        # Allocate new revision (append-only per CON-0001)
        next_seq = len(revisions) + 1
        rev_id = f"R{next_seq:04d}"

        new_rev = RevisionEntry(
            rev_id=rev_id,
            file_uid=file_uid,
            sha256=sha256,
            created_at=datetime.now().isoformat(),
        )
        self.entries.setdefault(file_uid, []).append(new_rev)
        return rev_id

    def get_revision(self, file_uid: str, sha256: str) -> str | None:
        """Get revision ID for content hash without allocating.

        Returns:
            Revision ID if content hash is registered, None otherwise
        """
        revisions = self.entries.get(file_uid, [])
        for rev in revisions:
            if rev.sha256 == sha256:
                return rev.rev_id
        return None

    def get_latest_revision(self, file_uid: str) -> str | None:
        """Get the latest revision ID for a file.

        Returns:
            Latest revision ID, or None if no revisions exist
        """
        revisions = self.entries.get(file_uid, [])
        if not revisions:
            return None
        return revisions[-1].rev_id

    def get_all_revisions(self, file_uid: str) -> list[RevisionEntry]:
        """Get all revisions for a file.

        Returns:
            List of revision entries in chronological order
        """
        return list(self.entries.get(file_uid, []))

    def to_dict(self) -> dict[str, object]:
        """Serialize registry to dictionary for JSON storage."""
        return {
            "schema_version": "1.0",
            "entries": {
                file_uid: [rev.to_dict() for rev in revisions]
                for file_uid, revisions in self.entries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RevisionRegistry:
        """Deserialize registry from dictionary."""
        entries_data = data.get("entries", {})
        if not isinstance(entries_data, dict):
            entries_data = {}
        entries: dict[str, list[RevisionEntry]] = {}
        for file_uid, revisions_data in entries_data.items():
            if isinstance(revisions_data, list):
                entries[file_uid] = [
                    RevisionEntry.from_dict(rev_data)
                    for rev_data in revisions_data
                    if isinstance(rev_data, dict)
                ]
        return cls(entries=entries)

    def save(self, path: Path) -> None:
        """Save registry to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> RevisionRegistry:
        """Load registry from JSON file, or create empty if not exists."""
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

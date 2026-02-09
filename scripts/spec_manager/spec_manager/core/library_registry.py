"""Library ID allocator for stable library identification (ALG-CORE-0006).

Provides:
- LibraryEntry: A single library registry entry
- LibraryIdAllocator: Allocates and persists stable LIB-#### identifiers
- generate_stability_key: Generates deterministic stability keys from inputs
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class LibraryEntry:
    """An entry in the library ID registry.

    Attributes:
        lib_id: Stable library identifier (LIB-####)
        stability_key: Deterministic key for idempotent allocation
        name: Human-readable library name
        created_at: ISO8601 creation timestamp
    """

    lib_id: str
    stability_key: str
    name: str
    created_at: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialize entry to dictionary."""
        return {
            "lib_id": self.lib_id,
            "stability_key": self.stability_key,
            "name": self.name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> LibraryEntry:
        """Deserialize entry from dictionary."""
        return cls(
            lib_id=data["lib_id"],
            stability_key=data["stability_key"],
            name=data["name"],
            created_at=data.get("created_at", ""),
        )


@dataclass
class LibraryIdAllocator:
    """Allocates and persists stable LIB-#### identifiers (ALG-CORE-0006).

    Library IDs are allocated based on stability keys, ensuring idempotent
    allocation: the same stability key always maps to the same LIB-#### ID.

    Attributes:
        entries: Mapping from stability_key to LibraryEntry
        next_seq: Next sequence number for allocation
    """

    entries: dict[str, LibraryEntry] = field(default_factory=dict)
    next_seq: int = 1

    def allocate_library_id(self, stability_key: str, name: str) -> tuple[str, bool]:
        """Allocate or retrieve a library ID for the given stability key.

        Args:
            stability_key: Deterministic key for idempotent allocation
            name: Human-readable library name

        Returns:
            Tuple of (lib_id, is_new) where is_new indicates first allocation
        """
        if stability_key in self.entries:
            entry = self.entries[stability_key]
            entry.name = name
            return entry.lib_id, False

        lib_id = f"LIB-{self.next_seq:04d}"
        self.entries[stability_key] = LibraryEntry(
            lib_id=lib_id,
            stability_key=stability_key,
            name=name,
            created_at=datetime.now().isoformat(),
        )
        self.next_seq += 1
        return lib_id, True

    def get_lib_id(self, stability_key: str) -> str | None:
        """Get library ID for a stability key without allocating.

        Args:
            stability_key: The stability key to look up

        Returns:
            Library ID if found, None otherwise
        """
        entry = self.entries.get(stability_key)
        return entry.lib_id if entry else None

    def get_entry_by_lib_id(self, lib_id: str) -> LibraryEntry | None:
        """Get entry by library ID.

        Args:
            lib_id: The library ID to look up

        Returns:
            LibraryEntry if found, None otherwise
        """
        for entry in self.entries.values():
            if entry.lib_id == lib_id:
                return entry
        return None

    def get_all_lib_ids(self) -> list[str]:
        """Get all library IDs in allocation order.

        Returns:
            List of library IDs sorted by sequence number
        """
        entries_sorted = sorted(self.entries.values(), key=lambda e: e.lib_id)
        return [e.lib_id for e in entries_sorted]

    def to_dict(self) -> dict[str, Any]:
        """Serialize allocator to dictionary for JSON storage."""
        return {
            "schema_version": "1.0",
            "next_seq": self.next_seq,
            "entries": {
                key: entry.to_dict() for key, entry in self.entries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LibraryIdAllocator:
        """Deserialize allocator from dictionary."""
        entries_data = data.get("entries", {})
        if not isinstance(entries_data, dict):
            entries_data = {}
        entries = {
            key: LibraryEntry.from_dict(entry_data)
            for key, entry_data in entries_data.items()
            if isinstance(entry_data, dict)
        }
        next_seq = data.get("next_seq", 1)
        if not isinstance(next_seq, int):
            next_seq = 1
        return cls(entries=entries, next_seq=next_seq)

    def save(self, path: Path) -> None:
        """Save allocator state to JSON file.

        Args:
            path: File path to write to
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> LibraryIdAllocator:
        """Load allocator state from JSON file, or create empty if not exists.

        Args:
            path: File path to read from

        Returns:
            LibraryIdAllocator instance
        """
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


def generate_stability_key(
    *,
    seed_entity_ids: list[str] | None = None,
    seed_atom_ids: list[str] | None = None,
    proposed_name: str | None = None,
) -> str:
    """Generate a deterministic stability key from various inputs.

    Priority order:
    1. Entity IDs (ENT:sorted_ids)
    2. Atom IDs (ATOM:sorted_ids)
    3. Proposed name (NAME:normalized_name)
    4. EMPTY if no inputs

    Args:
        seed_entity_ids: Entity IDs to use as key basis
        seed_atom_ids: Atom IDs to use as key basis
        proposed_name: Proposed library name to use as key basis

    Returns:
        Stability key string
    """
    if seed_entity_ids:
        sorted_ids = sorted(seed_entity_ids)
        return f"ENT:{('|').join(sorted_ids)}"

    if seed_atom_ids:
        sorted_ids = sorted(seed_atom_ids)
        return f"ATOM:{('|').join(sorted_ids)}"

    if proposed_name:
        normalized = re.sub(r"\s+", "_", proposed_name.strip().lower())
        return f"NAME:{normalized}"

    return "EMPTY"

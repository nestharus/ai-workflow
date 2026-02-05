"""Library ID allocator and registry (ALG-CORE-0006).

This module implements stable library ID allocation based on stability keys,
ensuring idempotent ID generation across discovery iterations.

Design References:
- ALG-CORE-0006: AllocateLibraryId
- CON-0008: Stable IDs
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Library ID pattern: LIB-####
_LIB_ID_PATTERN = re.compile(r"^LIB-\d{4}$")


@dataclass
class LibraryEntry:
    """An entry in the library registry.

    Attributes:
        lib_id: Unique library identifier (LIB-####)
        stability_key: Key used to ensure stable allocation
        name: Display name for the library
        created_at: ISO8601 timestamp when first created
    """

    lib_id: str
    stability_key: str
    name: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "lib_id": self.lib_id,
            "stability_key": self.stability_key,
            "name": self.name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryEntry":
        """Deserialize from dictionary."""
        return cls(
            lib_id=data["lib_id"],
            stability_key=data["stability_key"],
            name=data["name"],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class LibraryIdAllocator:
    """Library ID allocator with stability key support (ALG-CORE-0006).

    Allocates library IDs deterministically based on stability keys,
    ensuring the same stability_key always maps to the same lib_id.

    Attributes:
        entries: Dictionary mapping stability_key to LibraryEntry
        next_seq: Next sequence number to allocate
    """

    entries: dict[str, LibraryEntry] = field(default_factory=dict)
    next_seq: int = 1

    def allocate_library_id(
        self,
        stability_key: str,
        name: str = "",
    ) -> tuple[str, bool]:
        """Allocate a library ID for the given stability key (ALG-CORE-0006).

        If the stability_key has been seen before, returns the existing lib_id.
        Otherwise, allocates a new lib_id.

        Args:
            stability_key: Key ensuring stable ID allocation
            name: Display name for the library

        Returns:
            Tuple of (lib_id, is_new) where is_new indicates if newly allocated
        """
        # Check for existing allocation
        if stability_key in self.entries:
            entry = self.entries[stability_key]
            # Update name if provided and different
            if name and entry.name != name:
                entry.name = name
            return entry.lib_id, False

        # Allocate new ID
        lib_id = f"LIB-{self.next_seq:04d}"
        self.next_seq += 1

        entry = LibraryEntry(
            lib_id=lib_id,
            stability_key=stability_key,
            name=name or f"Library {lib_id}",
        )
        self.entries[stability_key] = entry

        return lib_id, True

    def get_lib_id(self, stability_key: str) -> str | None:
        """Get the lib_id for a stability key, if it exists.

        Args:
            stability_key: The stability key to look up

        Returns:
            The lib_id if found, None otherwise
        """
        entry = self.entries.get(stability_key)
        return entry.lib_id if entry else None

    def get_entry_by_lib_id(self, lib_id: str) -> LibraryEntry | None:
        """Get the entry for a lib_id.

        Args:
            lib_id: The library ID to look up

        Returns:
            The LibraryEntry if found, None otherwise
        """
        for entry in self.entries.values():
            if entry.lib_id == lib_id:
                return entry
        return None

    def get_all_lib_ids(self) -> list[str]:
        """Get all allocated library IDs.

        Returns:
            List of lib_ids in allocation order
        """
        # Sort by lib_id to get allocation order
        return sorted(
            [entry.lib_id for entry in self.entries.values()],
            key=lambda x: int(x.split("-")[1]),
        )

    def to_dict(self) -> dict:
        """Serialize allocator state to dictionary."""
        return {
            "schema_version": "1.0",
            "next_seq": self.next_seq,
            "entries": {key: entry.to_dict() for key, entry in self.entries.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryIdAllocator":
        """Deserialize allocator state from dictionary."""
        allocator = cls()
        allocator.next_seq = data.get("next_seq", 1)
        allocator.entries = {
            key: LibraryEntry.from_dict(entry_data)
            for key, entry_data in data.get("entries", {}).items()
        }
        return allocator

    def save(self, path: Path) -> None:
        """Save allocator state to JSON file.

        Args:
            path: Path to save the state
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "LibraryIdAllocator":
        """Load allocator state from JSON file.

        Args:
            path: Path to load from

        Returns:
            LibraryIdAllocator with loaded state (or empty if file missing)
        """
        if not path.exists():
            return cls()

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return cls.from_dict(data)


def generate_stability_key(
    seed_entity_ids: list[str] | None = None,
    seed_atom_ids: list[str] | None = None,
    proposed_name: str | None = None,
) -> str:
    """Generate a stability key from various inputs.

    The stability key ensures that the same conceptual library always
    gets the same lib_id, even across discovery iterations.

    Priority:
    1. Sorted entity IDs if provided
    2. Sorted atom IDs if provided
    3. Proposed name as fallback

    Args:
        seed_entity_ids: Entity IDs defining the library
        seed_atom_ids: Atom IDs defining the library
        proposed_name: Proposed name as fallback

    Returns:
        A stability key string
    """
    if seed_entity_ids:
        return "ENT:" + "|".join(sorted(seed_entity_ids))
    if seed_atom_ids:
        return "ATOM:" + "|".join(sorted(seed_atom_ids))
    if proposed_name:
        return "NAME:" + proposed_name.lower().replace(" ", "_")
    return "EMPTY"

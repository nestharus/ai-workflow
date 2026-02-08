"""Shared atom registry (single source of truth).

Manages atom descriptors, content hashes, and provides lookup by
atom_id, kind, or vertical slice. Persists as JSON at the
``__registry__.json`` path defined by :class:`BranchLayout`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .layout import BranchLayout
from .types import AtomDescriptor, AtomKind


class AtomRegistry:
    """Registry of all atom functions (single source of truth).

    Manages atom descriptors, content hashes, and provides lookup by
    atom_id, kind, or vertical slice.
    """

    def __init__(self, layout: BranchLayout) -> None:
        self._layout = layout
        self._atoms: dict[str, AtomDescriptor] = {}

    def register(self, descriptor: AtomDescriptor) -> None:
        """Register an atom descriptor.

        Args:
            descriptor: The atom to register.
        """
        self._atoms[descriptor.atom_id] = descriptor

    def unregister(self, atom_id: str) -> None:
        """Remove an atom from the registry.

        Args:
            atom_id: ID of the atom to remove.

        Raises:
            KeyError: If the atom is not registered.
        """
        if atom_id not in self._atoms:
            raise KeyError(f"Atom not registered: {atom_id}")
        del self._atoms[atom_id]

    def get(self, atom_id: str) -> AtomDescriptor | None:
        """Look up an atom by ID.

        Args:
            atom_id: ID of the atom to look up.

        Returns:
            The descriptor, or ``None`` if not found.
        """
        return self._atoms.get(atom_id)

    def list_all(self) -> list[AtomDescriptor]:
        """Return all registered atoms."""
        return list(self._atoms.values())

    def list_by_kind(self, kind: AtomKind) -> list[AtomDescriptor]:
        """Return all atoms of a given kind.

        Args:
            kind: The atom kind to filter by.
        """
        return [a for a in self._atoms.values() if a.kind == kind]

    def list_by_slice(self, slice_id: str) -> list[AtomDescriptor]:
        """Return all atoms belonging to a vertical slice.

        Args:
            slice_id: The slice ID to filter by.
        """
        return [a for a in self._atoms.values() if a.vertical_slice == slice_id]

    def detect_changes(self) -> list[tuple[str, str, str]]:
        """Compare content hashes to detect modified atoms.

        Re-hashes the atom file on disk and compares against the stored
        ``content_hash`` in each descriptor.

        Returns:
            List of ``(atom_id, old_hash, new_hash)`` for atoms whose
            file has changed.
        """
        changes: list[tuple[str, str, str]] = []
        for atom in self._atoms.values():
            file_path = self._layout.atoms_dir / atom.file_path
            if not file_path.exists():
                continue
            new_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if new_hash != atom.content_hash:
                changes.append((atom.atom_id, atom.content_hash, new_hash))
        return changes

    def save(self) -> None:
        """Persist the registry to disk as JSON."""
        self._layout.atoms_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "atoms": {aid: desc.to_dict() for aid, desc in self._atoms.items()},
        }
        self._layout.atom_registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, layout: BranchLayout) -> AtomRegistry:
        """Load the registry from disk.

        If the registry file does not exist, returns an empty registry.

        Args:
            layout: The branch layout with path information.
        """
        registry = cls(layout)
        if not layout.atom_registry_path.exists():
            return registry
        raw = json.loads(layout.atom_registry_path.read_text(encoding="utf-8"))
        for atom_data in raw.get("atoms", {}).values():
            registry.register(AtomDescriptor.from_dict(atom_data))
        return registry

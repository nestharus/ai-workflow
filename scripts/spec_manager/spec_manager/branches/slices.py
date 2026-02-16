"""Vertical and horizontal slice navigation (design doc Section 9).

Implements the recursive vertical/horizontal slice structure:
- Vertical slices = components with state/lifecycle
- Horizontal layers = algorithms, stores, shapes within a vertical
- Navigation: down (strip architecture), up (see deployment), across (siblings)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .atoms import AtomRegistry
from .layout import BranchLayout
from .pins import PinRegistry
from .types import (
    AtomDescriptor,
    AtomKind,
    BranchKind,
    PinProjection,
    VerticalSlice,
)


@dataclass
class HorizontalLayer:
    """A horizontal layer within a vertical slice.

    The base horizontal layers are: algorithms, stores, shapes.
    Architecture adds: events, middleware, routing, infrastructure.

    Attributes:
        layer_id: Unique identifier for this layer.
        name: Human-readable name.
        branch_kind: Which branch this layer belongs to.
        item_ids: Atom IDs or file paths in this layer.
    """

    layer_id: str
    name: str
    branch_kind: BranchKind
    item_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "layer_id": self.layer_id,
            "name": self.name,
            "branch_kind": self.branch_kind.value,
            "item_ids": self.item_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HorizontalLayer:
        """Deserialize from dictionary."""
        return cls(
            layer_id=data["layer_id"],
            name=data["name"],
            branch_kind=BranchKind(data["branch_kind"]),
            item_ids=data.get("item_ids", []),
        )


class SliceNavigator:
    """Navigate the vertical/horizontal slice structure.

    Provides:
    - Down: strip architecture, see business logic
    - Up: see how business logic is deployed
    - Across: see component boundaries

    Pin-functions are the navigation mechanism.
    """

    def __init__(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> None:
        self._layout = layout
        self._atom_registry = atom_registry
        self._pin_registry = pin_registry
        self._slices: dict[str, VerticalSlice] = {}
        self._next_slice_number: int = 1

    # ---- Vertical slice management ----

    def create_slice(self, name: str, parent_slice_id: str | None = None) -> VerticalSlice:
        """Create a new vertical slice.

        Args:
            name: Human-readable name for the slice.
            parent_slice_id: Parent slice ID, or ``None`` for root.

        Returns:
            The created VerticalSlice.

        Raises:
            KeyError: If the parent slice does not exist.
        """
        slice_id = f"VS-{self._next_slice_number:04d}"
        self._next_slice_number += 1

        if parent_slice_id is not None and parent_slice_id not in self._slices:
            raise KeyError(f"Parent slice not found: {parent_slice_id}")

        vs = VerticalSlice(
            slice_id=slice_id,
            name=name,
            parent_slice_id=parent_slice_id,
        )
        self._slices[slice_id] = vs

        # Add to parent's children list
        if parent_slice_id is not None:
            self._slices[parent_slice_id].children.append(slice_id)

        return vs

    def get_slice(self, slice_id: str) -> VerticalSlice | None:
        """Get a vertical slice by ID."""
        return self._slices.get(slice_id)

    def remove_slice(self, slice_id: str) -> None:
        """Remove a vertical slice.

        Args:
            slice_id: The slice ID to remove.

        Raises:
            KeyError: If the slice does not exist.
            ValueError: If the slice has child slices.
        """
        vs = self._slices.get(slice_id)
        if vs is None:
            raise KeyError(f"Slice not found: {slice_id}")
        if vs.children:
            raise ValueError(
                f"Cannot remove slice '{slice_id}' while it has children: {', '.join(vs.children)}"
            )

        if vs.parent_slice_id is not None:
            parent = self._slices.get(vs.parent_slice_id)
            if parent is not None:
                parent.children = [cid for cid in parent.children if cid != slice_id]

        del self._slices[slice_id]

    def snapshot_state(self) -> dict[str, Any]:
        """Capture complete slice navigator state for rollback/replay."""
        return {
            "next_slice_number": self._next_slice_number,
            "slices": [vs.to_dict() for vs in self._slices.values()],
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore slice navigator state from a prior snapshot."""
        raw_slices = state.get("slices", [])
        restored: dict[str, VerticalSlice] = {}
        for raw_slice in raw_slices:
            vs = VerticalSlice.from_dict(raw_slice)
            restored[vs.slice_id] = vs
        self._slices = restored
        next_number = state.get("next_slice_number")
        if isinstance(next_number, int) and next_number > 0:
            self._next_slice_number = next_number
        else:
            self._next_slice_number = len(self._slices) + 1

    def list_root_slices(self) -> list[VerticalSlice]:
        """List all root-level vertical slices (no parent)."""
        return [vs for vs in self._slices.values() if vs.parent_slice_id is None]

    def list_children(self, slice_id: str) -> list[VerticalSlice]:
        """List direct children of a vertical slice.

        Args:
            slice_id: The parent slice ID.

        Returns:
            List of child VerticalSlice objects.
        """
        parent = self._slices.get(slice_id)
        if parent is None:
            return []
        return [self._slices[cid] for cid in parent.children if cid in self._slices]

    def list_all_slices(self) -> list[VerticalSlice]:
        """Return all known slices.

        This is the public projection for callers that need global
        slice context without depending on internal storage layout.
        """
        return list(self._slices.values())

    def add_atom_to_slice(self, slice_id: str, atom_id: str) -> None:
        """Add an atom to a vertical slice.

        Args:
            slice_id: The slice to add the atom to.
            atom_id: The atom ID to add.

        Raises:
            KeyError: If the slice does not exist.
        """
        vs = self._slices.get(slice_id)
        if vs is None:
            raise KeyError(f"Slice not found: {slice_id}")
        if atom_id not in vs.atom_ids:
            vs.atom_ids.append(atom_id)

    def add_store_to_slice(self, slice_id: str, store_id: str) -> None:
        """Add a store to a vertical slice.

        Args:
            slice_id: The slice to add the store to.
            store_id: The store ID to add.

        Raises:
            KeyError: If the slice does not exist.
        """
        vs = self._slices.get(slice_id)
        if vs is None:
            raise KeyError(f"Slice not found: {slice_id}")
        if store_id not in vs.store_ids:
            vs.store_ids.append(store_id)

    # ---- Horizontal layer access ----

    def get_horizontal_layers(self, slice_id: str) -> list[HorizontalLayer]:
        """Get all horizontal layers for a vertical slice.

        Returns algorithmic layers (algorithms, stores, shapes) and
        architectural layers (services, events, middleware, infrastructure)
        for the atoms in this slice.

        Args:
            slice_id: The vertical slice to query.

        Returns:
            List of HorizontalLayer objects.
        """
        vs = self._slices.get(slice_id)
        if vs is None:
            return []

        layers: list[HorizontalLayer] = []

        # Algorithmic layers
        algo_atoms = [
            aid
            for aid in vs.atom_ids
            if (a := self._atom_registry.get(aid)) and a.kind == AtomKind.ALGORITHM
        ]
        if algo_atoms:
            layers.append(
                HorizontalLayer(
                    layer_id=f"{slice_id}:algorithms",
                    name="Algorithms",
                    branch_kind=BranchKind.ALGORITHMIC,
                    item_ids=algo_atoms,
                )
            )

        store_atoms = [
            aid
            for aid in vs.atom_ids
            if (a := self._atom_registry.get(aid)) and a.kind == AtomKind.STORE
        ]
        if store_atoms:
            layers.append(
                HorizontalLayer(
                    layer_id=f"{slice_id}:stores",
                    name="Stores",
                    branch_kind=BranchKind.ALGORITHMIC,
                    item_ids=store_atoms,
                )
            )

        shape_atoms = [
            aid
            for aid in vs.atom_ids
            if (a := self._atom_registry.get(aid)) and a.kind == AtomKind.SHAPE
        ]
        if shape_atoms:
            layers.append(
                HorizontalLayer(
                    layer_id=f"{slice_id}:shapes",
                    name="Shapes",
                    branch_kind=BranchKind.ALGORITHMIC,
                    item_ids=shape_atoms,
                )
            )

        # Architectural layers from pins
        arch_locations: dict[str, list[str]] = {
            "services": [],
            "events": [],
            "middleware": [],
            "infrastructure": [],
        }

        for atom_id in vs.atom_ids:
            pins = self._pin_registry.get_architectural_locations(atom_id)
            for pin in pins:
                loc = pin.architectural_location
                for category in arch_locations:
                    if loc.startswith(f"{category}/"):
                        arch_locations[category].append(pin.pin_id)
                        break

        for category, pin_ids in arch_locations.items():
            if pin_ids:
                layers.append(
                    HorizontalLayer(
                        layer_id=f"{slice_id}:{category}",
                        name=category.title(),
                        branch_kind=BranchKind.ARCHITECTURAL,
                        item_ids=pin_ids,
                    )
                )

        return layers

    # ---- Navigation ----

    def navigate_down(self, atom_id: str) -> AtomDescriptor:
        """From any layer, navigate down to the algorithmic atom.

        Args:
            atom_id: The atom ID to navigate to.

        Returns:
            The AtomDescriptor for the atom.

        Raises:
            KeyError: If the atom is not found.
        """
        descriptor = self._atom_registry.get(atom_id)
        if descriptor is None:
            raise KeyError(f"Atom not found: {atom_id}")
        return descriptor

    def navigate_up(self, atom_id: str) -> list[PinProjection]:
        """From an atom, navigate up to all architectural locations.

        Args:
            atom_id: The atom to trace upward.

        Returns:
            List of PinProjection records for architectural locations.
        """
        return self._pin_registry.get_architectural_locations(atom_id)

    def navigate_across(self, slice_id: str) -> list[VerticalSlice]:
        """From a vertical slice, see sibling components.

        Args:
            slice_id: The slice to find siblings for.

        Returns:
            List of sibling VerticalSlice objects (same parent).
        """
        vs = self._slices.get(slice_id)
        if vs is None:
            return []

        if vs.parent_slice_id is None:
            # Root slices: siblings are all other root slices
            return [
                s
                for s in self._slices.values()
                if s.parent_slice_id is None and s.slice_id != slice_id
            ]
        else:
            parent = self._slices.get(vs.parent_slice_id)
            if parent is None:
                return []
            return [
                self._slices[cid]
                for cid in parent.children
                if cid != slice_id and cid in self._slices
            ]

    # ---- Store monogamy enforcement (design doc Section 9) ----

    def validate_store_monogamy(self) -> list[str]:
        """Ensure every store lives inside exactly one vertical slice.

        Returns:
            List of violation descriptions. Empty if valid.
        """
        store_owners: dict[str, list[str]] = {}
        for vs in self._slices.values():
            for store_id in vs.store_ids:
                store_owners.setdefault(store_id, []).append(vs.slice_id)

        violations: list[str] = []
        for store_id, owners in store_owners.items():
            if len(owners) > 1:
                violations.append(f"Store {store_id} owned by multiple slices: {', '.join(owners)}")

        return violations

    # ---- Persistence ----

    def save(self) -> None:
        """Persist slices to disk as JSON."""
        self._layout.branches_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "slices": {sid: vs.to_dict() for sid, vs in self._slices.items()},
            "next_slice_number": self._next_slice_number,
        }
        self._layout.slices_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(
        cls,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> SliceNavigator:
        """Load slices from disk.

        If the file does not exist, returns an empty navigator.

        Args:
            layout: The branch layout with path information.
            atom_registry: The atom registry.
            pin_registry: The pin registry.
        """
        nav = cls(layout, atom_registry, pin_registry)
        if not layout.slices_path.exists():
            return nav
        raw = json.loads(layout.slices_path.read_text(encoding="utf-8"))
        nav._next_slice_number = raw.get("next_slice_number", 1)
        for vs_data in raw.get("slices", {}).values():
            vs = VerticalSlice.from_dict(vs_data)
            nav._slices[vs.slice_id] = vs
        return nav

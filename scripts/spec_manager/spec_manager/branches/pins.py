"""Pin registry and projection tracking.

Tracks how atoms are used in the architectural branch, supporting all
four projection types and enabling change propagation queries.  Provides
forward trace (atom -> locations), backward trace (location -> atom),
drift detection, and coverage analysis.

Note on canonical alternatives:
    - For O(1) indexed lookups see ``core.pin_registry.PinRegistryIndex``.
    - For production drift detection see ``projection.lineage.drift_detector``.
    - For change propagation see ``projection.pin_propagation``.

This module keeps its own implementations because they operate on the
branches-specific ``AtomRegistry`` and ``PinProjection`` data models,
and the registry sizes within the branch facade are small enough that
O(n) scans are acceptable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .atoms import AtomRegistry
from .layout import BranchLayout
from .types import PinProjection, ProjectionType


@dataclass
class DriftReport:
    """Report of detected drift between branches."""

    pin_id: str
    atom_id: str
    drift_type: str  # "atom_changed", "wrapper_changed", "aggregation_invalidated"
    architectural_location: str
    projection_type: ProjectionType
    details: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "pin_id": self.pin_id,
            "atom_id": self.atom_id,
            "drift_type": self.drift_type,
            "architectural_location": self.architectural_location,
            "projection_type": self.projection_type.value,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriftReport:
        """Deserialize from dictionary."""
        return cls(
            pin_id=data["pin_id"],
            atom_id=data["atom_id"],
            drift_type=data["drift_type"],
            architectural_location=data["architectural_location"],
            projection_type=ProjectionType(data["projection_type"]),
            details=data["details"],
        )

    def to_canonical_dict(self) -> dict[str, Any]:
        """Convert to a dict compatible with ``projection.lineage.drift_detector`` output.

        This is an interop helper for integrating branches drift
        detection results with the canonical drift pipeline.
        """
        return {
            "pin_id": self.pin_id,
            "atom_id": self.atom_id,
            "drift_type": self.drift_type,
            "location": self.architectural_location,
            "projection_type": self.projection_type.value,
            "details": self.details,
        }


class PinRegistry:
    """Registry of all pin-functions mapping atoms to architectural locations.

    Provides:
    - Forward trace: atom_id -> all architectural locations
    - Backward trace: architectural_location -> originating atom
    - Change propagation: given a changed atom, list affected pins
    - Drift detection: compare wrapper hashes for non-pass-through pins
    """

    def __init__(self, layout: BranchLayout) -> None:
        self._layout = layout
        self._pins: dict[str, PinProjection] = {}
        self._next_pin_number: int = 1

    # ---- Registration ----

    def register_pin(self, pin: PinProjection) -> None:
        """Register a pin-function.

        Args:
            pin: The pin to register.
        """
        self._pins[pin.pin_id] = pin
        # Track highest pin number seen for allocation
        num = self._parse_pin_number(pin.pin_id)
        if num is not None and num >= self._next_pin_number:
            self._next_pin_number = num + 1

    def unregister_pin(self, pin_id: str) -> None:
        """Remove a pin from the registry.

        Args:
            pin_id: ID of the pin to remove.

        Raises:
            KeyError: If the pin is not registered.
        """
        if pin_id not in self._pins:
            raise KeyError(f"Pin not registered: {pin_id}")
        del self._pins[pin_id]

    def get_pin(self, pin_id: str) -> PinProjection | None:
        """Look up a pin by ID."""
        return self._pins.get(pin_id)

    def list_all(self) -> list[PinProjection]:
        """Return all registered pins."""
        return list(self._pins.values())

    # ---- Forward trace (design doc Section 11) ----
    # Note: For O(1) forward trace see core.pin_registry.PinRegistryIndex

    def get_architectural_locations(self, atom_id: str) -> list[PinProjection]:
        """All architectural locations importing this atom.

        Args:
            atom_id: The atom to look up.

        Returns:
            List of PinProjection records referencing this atom.
        """
        return [p for p in self._pins.values() if p.atom_id == atom_id]

    # ---- Backward trace ----
    # Note: For O(1) backward trace see core.pin_registry.PinRegistryIndex

    def get_atom_for_location(self, architectural_location: str) -> PinProjection | None:
        """Which atom does this architectural location use?

        Args:
            architectural_location: A ``file:class.method`` string.

        Returns:
            The PinProjection at this location, or ``None``.
        """
        for pin in self._pins.values():
            if pin.architectural_location == architectural_location:
                return pin
        return None

    # ---- Change propagation (design doc Section 5) ----

    def get_affected_pins(self, changed_atom_ids: list[str]) -> dict[str, list[PinProjection]]:
        """For each changed atom, return affected pins.

        Pass-through pins propagate automatically.  Wrapping/aggregation
        pins need manual verification.

        Args:
            changed_atom_ids: List of atom IDs that changed.

        Returns:
            Dict mapping atom_id -> list of PinProjection that reference it.
        """
        result: dict[str, list[PinProjection]] = {}
        for atom_id in changed_atom_ids:
            pins = self.get_architectural_locations(atom_id)
            if pins:
                result[atom_id] = pins
        return result

    # ---- Drift detection (design doc Section 11) ----

    def detect_drift(self, atom_registry: AtomRegistry) -> list[DriftReport]:
        """Compare wrapper hashes and atom content hashes to find drift.

        For pass-through: drift if atom changed (detected via atom_registry).
        For wrapping/projection: drift if wrapper_hash changed OR atom changed.
        For aggregation: drift if any aggregated atom changed.

        Args:
            atom_registry: The atom registry to check hashes against.

        Returns:
            List of detected drift reports.
        """
        changes = atom_registry.detect_changes()
        changed_ids = {atom_id for atom_id, _, _ in changes}
        change_lookup = {atom_id: (old, new) for atom_id, old, new in changes}

        reports: list[DriftReport] = []
        for pin in self._pins.values():
            if pin.atom_id in changed_ids:
                old_hash, new_hash = change_lookup[pin.atom_id]
                if pin.projection_type == ProjectionType.PASS_THROUGH:
                    reports.append(
                        DriftReport(
                            pin_id=pin.pin_id,
                            atom_id=pin.atom_id,
                            drift_type="atom_changed",
                            architectural_location=pin.architectural_location,
                            projection_type=pin.projection_type,
                            details=f"Atom hash changed: {old_hash[:8]}.. -> {new_hash[:8]}..",
                        )
                    )
                elif pin.projection_type in (
                    ProjectionType.SLICE,
                    ProjectionType.AGGREGATION,
                ):
                    drift_type = (
                        "aggregation_invalidated"
                        if pin.projection_type == ProjectionType.AGGREGATION
                        else "atom_changed"
                    )
                    reports.append(
                        DriftReport(
                            pin_id=pin.pin_id,
                            atom_id=pin.atom_id,
                            drift_type=drift_type,
                            architectural_location=pin.architectural_location,
                            projection_type=pin.projection_type,
                            details=f"Atom hash changed: {old_hash[:8]}.. -> {new_hash[:8]}..",
                        )
                    )
        return reports

    # ---- Coverage analysis ----

    def get_unpinned_atoms(self, atom_registry: AtomRegistry) -> list[str]:
        """Atoms with no architectural usage (not yet projected).

        Args:
            atom_registry: The atom registry to check against.

        Returns:
            List of atom IDs that have no pins.
        """
        pinned = {p.atom_id for p in self._pins.values()}
        return [a.atom_id for a in atom_registry.list_all() if a.atom_id not in pinned]

    def get_orphaned_architectural_code(self) -> list[str]:
        """Architectural locations with no pin (undocumented/orphaned).

        This is a placeholder -- in a real system it would scan the
        architectural branch for code not covered by any pin.  Here we
        simply return an empty list since we track only known pins.
        """
        return []

    # ---- ID allocation ----

    def allocate_pin_id(self) -> str:
        """Allocate the next PIN-#### identifier."""
        pin_id = f"PIN-{self._next_pin_number:04d}"
        self._next_pin_number += 1
        return pin_id

    # ---- Persistence ----

    def save(self) -> None:
        """Persist the registry to disk as JSON."""
        self._layout.branches_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "pins": {pid: p.to_dict() for pid, p in self._pins.items()},
            "next_pin_number": self._next_pin_number,
        }
        self._layout.pin_registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, layout: BranchLayout) -> PinRegistry:
        """Load the registry from disk.

        If the file does not exist, returns an empty registry.

        Args:
            layout: The branch layout with path information.
        """
        registry = cls(layout)
        if not layout.pin_registry_path.exists():
            return registry
        raw = json.loads(layout.pin_registry_path.read_text(encoding="utf-8"))
        registry._next_pin_number = raw.get("next_pin_number", 1)
        for pin_data in raw.get("pins", {}).values():
            registry.register_pin(PinProjection.from_dict(pin_data))
        return registry

    # ---- Helpers ----

    @staticmethod
    def _parse_pin_number(pin_id: str) -> int | None:
        """Extract the numeric part from a PIN-#### identifier."""
        if pin_id.startswith("PIN-") and len(pin_id) == 8:
            try:
                return int(pin_id[4:])
            except ValueError:
                return None
        return None

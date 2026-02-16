"""Runtime registry for efficient pin-function queries.

Provides in-memory indexes for O(1) lookups by function name, file path,
and pin_func_id, plus forward/reverse import graph traversal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import (
        ImportEdge,
        MicroAddress,
        PinFunction,
        PinFunctionRegistry,
    )


@dataclass(frozen=True)
class PinRelationshipSignature:
    """Normalized relationship signature for pin-to-architecture edges."""

    pin_func_id: str
    arch_location: str
    arch_file_path: str
    arch_line: int
    projection_type: str
    is_direct_import: bool
    confidence: float


@dataclass(frozen=True)
class PinRegistrySnapshot:
    """Structural baseline snapshot used for low-level drift comparison."""

    pin_signatures: dict[str, tuple[str, ...]] = field(default_factory=dict)
    relationships_by_pin: dict[str, tuple[PinRelationshipSignature, ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class PinRegistryDrift:
    """Structural drift report between baseline and current registry snapshots."""

    added_pin_func_ids: list[str] = field(default_factory=list)
    removed_pin_func_ids: list[str] = field(default_factory=list)
    changed_pin_func_ids: list[str] = field(default_factory=list)
    changed_relationship_pin_func_ids: list[str] = field(default_factory=list)
    added_relationships: list[PinRelationshipSignature] = field(default_factory=list)
    removed_relationships: list[PinRelationshipSignature] = field(default_factory=list)

    def has_drift(self) -> bool:
        """Return True when any structural drift was detected."""
        return any(
            (
                self.added_pin_func_ids,
                self.removed_pin_func_ids,
                self.changed_pin_func_ids,
                self.changed_relationship_pin_func_ids,
                self.added_relationships,
                self.removed_relationships,
            )
        )


@dataclass
class PinRegistryIndex:
    """In-memory index for efficient pin-function queries.

    Provides O(1) lookups by function name, file path, and pin_func_id.
    Provides forward/reverse import graph traversal.
    """

    _by_pin: dict[str, list[ImportEdge]] = field(default_factory=dict)
    _by_arch_location: dict[str, list[ImportEdge]] = field(default_factory=dict)
    _by_name: dict[str, PinFunction] = field(default_factory=dict)
    _by_id: dict[str, PinFunction] = field(default_factory=dict)

    def get_importers(self, pin_func_id: str) -> list[ImportEdge]:
        """Get all import edges for a given pin-function.

        Args:
            pin_func_id: The pin-function ID to look up.

        Returns:
            List of ImportEdge objects where this pin-function is imported.
        """
        return list(self._by_pin.get(pin_func_id, []))

    def get_pin_functions_for_arch(self, arch_location: str) -> list[ImportEdge]:
        """Get all import edges for a given architectural location.

        Args:
            arch_location: The architectural location (e.g. "file:class.method").

        Returns:
            List of ImportEdge objects for pin-functions used at this location.
        """
        return list(self._by_arch_location.get(arch_location, []))

    def get_by_name(self, function_name: str) -> PinFunction | None:
        """Look up a pin-function by its function name.

        Args:
            function_name: The Python qualified name of the function.

        Returns:
            The PinFunction if found, None otherwise.
        """
        return self._by_name.get(function_name)

    def get_by_id(self, pin_func_id: str) -> PinFunction | None:
        """Look up a pin-function by its ID.

        Args:
            pin_func_id: The pin-function ID (e.g. "PFUNC-0001").

        Returns:
            The PinFunction if found, None otherwise.
        """
        return self._by_id.get(pin_func_id)

    def resolve_micro_address(self, addr: MicroAddress) -> PinFunction | None:
        """Resolve a micro-address to the target pin-function.

        Supports three addressing modes:
        - Function-level: just pin_func_id
        - Line-range: pin_func_id + line_start/line_end (validates range)
        - Call-site: composition_func + callee pin_func_id

        Args:
            addr: The MicroAddress to resolve.

        Returns:
            The target PinFunction if found and address is valid, None otherwise.
        """
        pin_func = self._by_id.get(addr.pin_func_id)
        if pin_func is None:
            return None

        # For call-site addressing, validate the composition function exists
        if addr.composition_func is not None:
            comp_func = self._by_name.get(addr.composition_func)
            if comp_func is None:
                return None

        # For line-range addressing, validate the range is within function bounds
        if addr.line_start is not None and addr.line_end is not None:
            func_length = pin_func.line_end - pin_func.line_start + 1
            if addr.line_start < 1 or addr.line_end > func_length:
                return None
            if addr.line_start > addr.line_end:
                return None

        return pin_func

    def get_affected_locations(self, changed_pin_func_ids: list[str]) -> list[ImportEdge]:
        """Get all architectural locations affected by changes to the given pin-functions.

        Args:
            changed_pin_func_ids: List of pin-function IDs that have changed.

        Returns:
            List of ImportEdge objects for all affected architectural locations.
        """
        affected: list[ImportEdge] = []
        seen_edge_ids: set[str] = set()
        for pid in changed_pin_func_ids:
            for edge in self._by_pin.get(pid, []):
                if edge.edge_id not in seen_edge_ids:
                    seen_edge_ids.add(edge.edge_id)
                    affected.append(edge)
        return affected

    @staticmethod
    def _pin_signature(pin_func: PinFunction) -> tuple[str, ...]:
        return (
            pin_func.function_name,
            pin_func.module_path,
            pin_func.file_path,
            str(pin_func.line_start),
            str(pin_func.line_end),
            pin_func.signature,
            pin_func.content_hash,
        )

    @staticmethod
    def _relationship_signature(edge: ImportEdge) -> PinRelationshipSignature:
        projection = getattr(edge.projection_type, "value", edge.projection_type)
        return PinRelationshipSignature(
            pin_func_id=edge.pin_func_id,
            arch_location=edge.arch_location,
            arch_file_path=edge.arch_file_path,
            arch_line=edge.arch_line,
            projection_type=str(projection),
            is_direct_import=edge.is_direct_import,
            confidence=float(edge.confidence),
        )

    @staticmethod
    def _relationship_sort_key(signature: PinRelationshipSignature) -> tuple[object, ...]:
        return (
            signature.pin_func_id,
            signature.arch_location,
            signature.arch_file_path,
            signature.arch_line,
            signature.projection_type,
            signature.is_direct_import,
            signature.confidence,
        )

    def snapshot(self) -> PinRegistrySnapshot:
        """Capture a structural snapshot suitable for drift comparison."""
        all_pin_ids = set(self._by_id) | set(self._by_pin)
        pin_signatures: dict[str, tuple[str, ...]] = {}
        relationships_by_pin: dict[str, tuple[PinRelationshipSignature, ...]] = {}

        for pin_func_id in all_pin_ids:
            pin_func = self._by_id.get(pin_func_id)
            if pin_func is not None:
                pin_signatures[pin_func_id] = self._pin_signature(pin_func)

            relationship_set = {
                self._relationship_signature(edge) for edge in self._by_pin.get(pin_func_id, [])
            }
            relationships_by_pin[pin_func_id] = tuple(
                sorted(relationship_set, key=self._relationship_sort_key)
            )

        return PinRegistrySnapshot(
            pin_signatures=pin_signatures,
            relationships_by_pin=relationships_by_pin,
        )

    @staticmethod
    def _coerce_snapshot(
        baseline: PinRegistrySnapshot | PinRegistryIndex | PinFunctionRegistry,
    ) -> PinRegistrySnapshot:
        if isinstance(baseline, PinRegistrySnapshot):
            return baseline
        if isinstance(baseline, PinRegistryIndex):
            return baseline.snapshot()
        if hasattr(baseline, "pin_functions") and hasattr(baseline, "import_edges"):
            return PinRegistryIndex.from_registry(baseline).snapshot()
        raise TypeError(
            "baseline must be PinRegistrySnapshot, PinRegistryIndex, or PinFunctionRegistry"
        )

    @staticmethod
    def _flatten_relationships(
        snapshot: PinRegistrySnapshot,
    ) -> set[PinRelationshipSignature]:
        flattened: set[PinRelationshipSignature] = set()
        for relationships in snapshot.relationships_by_pin.values():
            flattened.update(relationships)
        return flattened

    def detect_drift(
        self,
        baseline: PinRegistrySnapshot | PinRegistryIndex | PinFunctionRegistry,
    ) -> PinRegistryDrift:
        """Compare current index against a baseline snapshot and return structural drift."""
        baseline_snapshot = self._coerce_snapshot(baseline)
        current_snapshot = self.snapshot()

        baseline_pin_ids = set(baseline_snapshot.pin_signatures)
        current_pin_ids = set(current_snapshot.pin_signatures)
        added_pin_func_ids = sorted(current_pin_ids - baseline_pin_ids)
        removed_pin_func_ids = sorted(baseline_pin_ids - current_pin_ids)

        common_pin_ids = baseline_pin_ids & current_pin_ids
        changed_pin_func_ids = sorted(
            pin_func_id
            for pin_func_id in common_pin_ids
            if baseline_snapshot.pin_signatures.get(pin_func_id)
            != current_snapshot.pin_signatures.get(pin_func_id)
        )

        relationship_pin_ids = set(baseline_snapshot.relationships_by_pin) | set(
            current_snapshot.relationships_by_pin
        )
        changed_relationship_pin_func_ids = sorted(
            pin_func_id
            for pin_func_id in relationship_pin_ids
            if baseline_snapshot.relationships_by_pin.get(pin_func_id, ())
            != current_snapshot.relationships_by_pin.get(pin_func_id, ())
        )

        baseline_relationships = self._flatten_relationships(baseline_snapshot)
        current_relationships = self._flatten_relationships(current_snapshot)
        added_relationships = sorted(
            current_relationships - baseline_relationships,
            key=self._relationship_sort_key,
        )
        removed_relationships = sorted(
            baseline_relationships - current_relationships,
            key=self._relationship_sort_key,
        )

        return PinRegistryDrift(
            added_pin_func_ids=added_pin_func_ids,
            removed_pin_func_ids=removed_pin_func_ids,
            changed_pin_func_ids=changed_pin_func_ids,
            changed_relationship_pin_func_ids=changed_relationship_pin_func_ids,
            added_relationships=added_relationships,
            removed_relationships=removed_relationships,
        )

    @classmethod
    def from_registry(cls, registry: PinFunctionRegistry) -> PinRegistryIndex:
        """Build an index from a PinFunctionRegistry.

        Args:
            registry: The serialized registry to index.

        Returns:
            A PinRegistryIndex with all lookup tables populated.
        """
        index = cls()

        # Index pin-functions by name and ID
        for pf in registry.pin_functions:
            index._by_name[pf.function_name] = pf
            index._by_id[pf.pin_func_id] = pf

        # Index import edges by pin_func_id and arch_location
        for edge in registry.import_edges:
            if edge.pin_func_id not in index._by_pin:
                index._by_pin[edge.pin_func_id] = []
            index._by_pin[edge.pin_func_id].append(edge)

            if edge.arch_location not in index._by_arch_location:
                index._by_arch_location[edge.arch_location] = []
            index._by_arch_location[edge.arch_location].append(edge)

        return index


__all__ = [
    "PinRegistryDrift",
    "PinRegistryIndex",
    "PinRegistrySnapshot",
    "PinRelationshipSignature",
]

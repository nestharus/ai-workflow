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
    "PinRegistryIndex",
]

"""Layer management utilities for planner state machines.

Handles layer ordering, depth computation, and unit grouping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.planner.state import DesignState


class LayerManager:
    """Manages layer ordering and unit grouping.

    Layers are numbered from 0 (root) to N (deepest atomics).
    Each layer contains unit IDs at that depth.
    """

    def __init__(self, state: DesignState) -> None:
        """Initialize layer manager.

        Args:
            state: The design state to manage
        """
        self.state = state

    def get_pending_units_at_layer(self, layer: int) -> list[str]:
        """Get all pending unit IDs at a specific layer.

        Args:
            layer: Layer number to query

        Returns:
            List of unit IDs with status='pending' at this layer
        """
        if layer not in self.state.layers:
            return []

        return [
            uid
            for uid in self.state.layers[layer]
            if uid in self.state.units and self.state.units[uid].status == "pending"
        ]

    def get_units_at_layer(self, layer: int) -> list[str]:
        """Get all unit IDs at a specific layer.

        Args:
            layer: Layer number to query

        Returns:
            List of all unit IDs at this layer
        """
        return self.state.layers.get(layer, [])

    def compute_unit_depth(self, unit_id: str) -> int:
        """Compute the depth of a unit based on its ID.

        Depth is determined by the number of dots in the ID:
        - root = 0
        - root.api = 1
        - root.api.validate = 2

        Args:
            unit_id: The unit ID to compute depth for

        Returns:
            Depth (layer number) of the unit
        """
        return unit_id.count(".")

    def add_units_to_layer(self, unit_ids: list[str]) -> None:
        """Add units to their appropriate layers based on depth.

        Args:
            unit_ids: List of unit IDs to add
        """
        for unit_id in unit_ids:
            depth = self.compute_unit_depth(unit_id)
            if depth not in self.state.layers:
                self.state.layers[depth] = []
            if unit_id not in self.state.layers[depth]:
                self.state.layers[depth].append(unit_id)

    def remove_unit_from_layer(self, unit_id: str) -> None:
        """Remove a unit from its layer.

        Args:
            unit_id: The unit ID to remove
        """
        depth = self.compute_unit_depth(unit_id)
        if depth in self.state.layers and unit_id in self.state.layers[depth]:
            self.state.layers[depth].remove(unit_id)

    def get_max_layer(self) -> int:
        """Get the deepest layer number.

        Returns:
            Maximum layer number, or 0 if no layers exist
        """
        return max(self.state.layers.keys()) if self.state.layers else 0

    def get_min_layer(self) -> int:
        """Get the shallowest layer number.

        Returns:
            Minimum layer number, or 0 if no layers exist
        """
        return min(self.state.layers.keys()) if self.state.layers else 0

    def get_units_grouped_by_file(self, unit_ids: list[str]) -> dict[str, list[str]]:
        """Group unit IDs by their target file for execution scheduling.

        Units targeting the same file should run sequentially.
        Units targeting different files can run in parallel.

        Args:
            unit_ids: List of unit IDs to group

        Returns:
            Dict mapping file path to list of unit IDs
        """
        file_groups: dict[str, list[str]] = {}
        no_file: list[str] = []

        for uid in unit_ids:
            unit = self.state.units.get(uid)
            if unit and unit.plan and unit.plan.target_file:
                target_file = unit.plan.target_file
                if target_file not in file_groups:
                    file_groups[target_file] = []
                file_groups[target_file].append(uid)
            else:
                no_file.append(uid)

        # Units without target file go in their own group
        if no_file:
            file_groups["__no_file__"] = no_file

        return file_groups

    def get_atomic_units(self) -> list[str]:
        """Get all atomic unit IDs.

        Returns:
            List of unit IDs with status='atomic'
        """
        return [uid for uid, unit in self.state.units.items() if unit.status == "atomic"]

    def get_decomposed_units(self) -> list[str]:
        """Get all decomposed unit IDs.

        Returns:
            List of unit IDs with status='decomposed'
        """
        return [
            uid for uid, unit in self.state.units.items() if unit.status == "decomposed"
        ]

    def get_leaf_units(self) -> list[str]:
        """Get all leaf unit IDs (units with no children).

        Returns:
            List of unit IDs that have no children
        """
        return [uid for uid, unit in self.state.units.items() if not unit.children]

    def all_leaves_atomic(self) -> bool:
        """Check if all leaf units are atomic.

        Returns:
            True if every leaf unit has status='atomic'
        """
        for unit in self.state.units.values():
            if not unit.children and unit.status != "atomic":
                return False
        return True

    def rebuild_layers(self) -> None:
        """Rebuild layer mapping from unit IDs.

        Clears existing layers and rebuilds based on unit depths.
        """
        self.state.layers = {}
        for unit_id in self.state.units:
            depth = self.compute_unit_depth(unit_id)
            if depth not in self.state.layers:
                self.state.layers[depth] = []
            self.state.layers[depth].append(unit_id)

    def get_parent_chain(self, unit_id: str) -> list[str]:
        """Get the chain of parent unit IDs from root to this unit.

        Args:
            unit_id: The unit ID to trace

        Returns:
            List of parent IDs from root to immediate parent
        """
        chain: list[str] = []
        current_id = unit_id

        while True:
            unit = self.state.units.get(current_id)
            if not unit or not unit.parent:
                break
            chain.insert(0, unit.parent)
            current_id = unit.parent

        return chain

    def get_siblings(self, unit_id: str) -> list[str]:
        """Get sibling unit IDs (same parent, excluding self).

        Args:
            unit_id: The unit ID to find siblings for

        Returns:
            List of sibling unit IDs
        """
        unit = self.state.units.get(unit_id)
        if not unit or not unit.parent:
            return []

        parent = self.state.units.get(unit.parent)
        if not parent:
            return []

        return [uid for uid in parent.children if uid != unit_id]

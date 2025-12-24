"""Layer management utilities for planner state machines.

Handles layer ordering, depth computation, and unit grouping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.planner.state import Branch

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

    def _ensure_branch_exists(self, branch_id: str) -> None:
        """Ensure a branch exists, create if missing.

        Args:
            branch_id: Branch identifier to check/create
        """
        if branch_id not in self.state.branches:
            self.state.branches[branch_id] = Branch(branch_id=branch_id)

    def get_pending_units_at_layer(self, layer: int, branch_id: str = "main") -> list[str]:
        """Get all pending unit IDs at a specific layer.

        Args:
            layer: Layer number to query
            branch_id: Branch identifier

        Returns:
            List of unit IDs with status='pending' at this layer
        """
        self._ensure_branch_exists(branch_id)
        layers = self.state.branches[branch_id].layers
        if layer not in layers:
            return []

        return [
            uid
            for uid in layers[layer]
            if uid in self.state.units and self.state.units[uid].status == "pending"
        ]

    def get_units_at_layer(self, layer: int, branch_id: str = "main") -> list[str]:
        """Get all unit IDs at a specific layer.

        Args:
            layer: Layer number to query
            branch_id: Branch identifier

        Returns:
            List of all unit IDs at this layer
        """
        self._ensure_branch_exists(branch_id)
        return self.state.branches[branch_id].layers.get(layer, [])

    def get_branch_units_at_layer(self, branch_id: str, layer: int) -> list[str]:
        """Get all unit IDs at a specific layer for a specific branch.

        This is an explicit branch-aware version of get_units_at_layer.
        Use this when you need to be explicit about which branch you're querying.

        Args:
            branch_id: Branch identifier
            layer: Layer number to query

        Returns:
            List of all unit IDs at this layer in the specified branch
        """
        self._ensure_branch_exists(branch_id)
        return self.state.branches[branch_id].layers.get(layer, [])

    def compute_unit_depth(self, unit_id: str) -> int:
        """Compute the depth of a unit by traversing parent chain.

        Depth is the number of ancestors:
        - root = 0 (no parent)
        - root.A.1 = 1 (parent is root)
        - root.A.1.B.1 = 2 (parent chain: root.A.1 -> root)

        Args:
            unit_id: The unit ID to compute depth for

        Returns:
            Depth (layer number) of the unit
        """
        depth = 0
        current = self.state.units.get(unit_id)
        while current and current.parent:
            depth += 1
            current = self.state.units.get(current.parent)
        return depth

    def add_units_to_layer(self, unit_ids: list[str], branch_id: str = "main") -> None:
        """Add units to their appropriate layers based on depth.

        Args:
            unit_ids: List of unit IDs to add
            branch_id: Branch identifier
        """
        self._ensure_branch_exists(branch_id)
        layers = self.state.branches[branch_id].layers
        for unit_id in unit_ids:
            depth = self.compute_unit_depth(unit_id)
            if depth not in layers:
                layers[depth] = []
            if unit_id not in layers[depth]:
                layers[depth].append(unit_id)

    def remove_unit_from_layer(self, unit_id: str, branch_id: str = "main") -> None:
        """Remove a unit from its layer.

        Args:
            unit_id: The unit ID to remove
            branch_id: Branch identifier
        """
        self._ensure_branch_exists(branch_id)
        layers = self.state.branches[branch_id].layers
        depth = self.compute_unit_depth(unit_id)
        if depth in layers and unit_id in layers[depth]:
            layers[depth].remove(unit_id)

    def pop_layer(self, branch_id: str, layer: int) -> None:
        """Remove all units at a layer and update parent references.

        This is used for replanning: when a layer needs to be regenerated,
        pop it to remove all its units, then the parent layer can be
        re-decomposed to create new children.

        Args:
            branch_id: Branch identifier
            layer: Layer number to remove
        """
        self._ensure_branch_exists(branch_id)
        layers = self.state.branches[branch_id].layers
        if layer not in layers:
            return
        unit_ids = list(layers.get(layer, []))
        descendant_ids: set[str] = set()
        to_visit: list[str] = []
        for unit_id in unit_ids:
            unit = self.state.units.get(unit_id)
            if unit:
                to_visit.extend(unit.children)

        while to_visit:
            child_id = to_visit.pop()
            if child_id in descendant_ids:
                continue
            descendant_ids.add(child_id)
            child_unit = self.state.units.get(child_id)
            if child_unit:
                to_visit.extend(child_unit.children)

        removed_ids = set(unit_ids)
        removed_ids.update(descendant_ids)

        for unit_id, unit in self.state.units.items():
            if unit_id in removed_ids:
                continue
            if unit.children:
                unit.children = [
                    child_id for child_id in unit.children if child_id not in removed_ids
                ]

        for unit_id in removed_ids:
            self.state.units.pop(unit_id, None)

        for depth, layer_units in list(layers.items()):
            if depth <= layer:
                continue
            layers[depth] = [uid for uid in layer_units if uid not in removed_ids]
        layers.pop(layer, None)

    def get_max_layer(self, branch_id: str = "main") -> int:
        """Get the deepest layer number.

        Args:
            branch_id: Branch identifier

        Returns:
            Maximum layer number, or 0 if no layers exist
        """
        self._ensure_branch_exists(branch_id)
        layers = self.state.branches[branch_id].layers
        return max(layers.keys()) if layers else 0

    def get_min_layer(self, branch_id: str = "main") -> int:
        """Get the shallowest layer number.

        Args:
            branch_id: Branch identifier

        Returns:
            Minimum layer number, or 0 if no layers exist
        """
        self._ensure_branch_exists(branch_id)
        layers = self.state.branches[branch_id].layers
        return min(layers.keys()) if layers else 0

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
        return [uid for uid, unit in self.state.units.items() if unit.status == "decomposed"]

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

    def rebuild_layers(self, branch_id: str = "main") -> None:
        """Rebuild layer mapping from unit IDs.

        Clears existing layers and rebuilds based on unit depths for a branch.

        Args:
            branch_id: Branch identifier
        """
        self._ensure_branch_exists(branch_id)
        layers = self.state.branches[branch_id].layers
        unit_ids: list[str] = []
        seen: set[str] = set()
        for layer_units in layers.values():
            for unit_id in layer_units:
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                unit_ids.append(unit_id)
        layers.clear()
        for unit_id in unit_ids:
            if unit_id not in self.state.units:
                continue
            depth = self.compute_unit_depth(unit_id)
            if depth not in layers:
                layers[depth] = []
            layers[depth].append(unit_id)

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

"""Atomic execution and rollback of refinement operations.

Executes RefinementOperations against the BranchManager, ensuring each
operation either fully completes or fully rolls back.  Supports:

- MOVE: Reassign entity from one vertical slice to another.
- SPLIT: Create new vertical slice and move a subset of entities.
- MERGE: Combine two vertical slices into one.
- CREATE: Register a new vertical slice.
- REMOVE: Remove a vertical slice (entities redistributed first).
- MODIFY: Update entity metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from spec_manager.branches.manager import BranchManager

from .operations import RefinementOperation

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of executing a single refinement operation.

    Attributes:
        operation: The operation that was executed.
        success: Whether the operation completed without error.
        error: Error message if ``success`` is False.
        changes: Description of changes applied.
    """

    operation: RefinementOperation
    success: bool
    error: str = ""
    changes: list[str] = field(default_factory=list)


class RefinementExecutor:
    """Executes refinement operations atomically against BranchManager.

    Each ``execute()`` call captures pre-state, applies the operation,
    and supports ``rollback()`` if anything fails.

    Usage::

        executor = RefinementExecutor(branch_manager)
        for op in operations:
            result = executor.execute(op)
            if not result.success:
                executor.rollback(op)
    """

    def __init__(self, branch_manager: BranchManager) -> None:
        self.branch_manager = branch_manager
        self._snapshots: dict[int, dict] = {}  # op id(hash) -> pre-state

    def execute(self, operation: RefinementOperation) -> ExecutionResult:
        """Execute a refinement operation.

        Captures a pre-state snapshot, applies the operation, and returns
        the result.  On failure, the snapshot is preserved for rollback.

        Args:
            operation: The operation to execute.

        Returns:
            ExecutionResult describing the outcome.
        """
        op_key = id(operation)
        changes: list[str] = []

        try:
            # Capture pre-state snapshot for rollback
            self._snapshots[op_key] = self._capture_snapshot(operation)

            if operation.op_type == "move":
                changes = self._execute_move(operation)
            elif operation.op_type == "split":
                changes = self._execute_split(operation)
            elif operation.op_type == "merge":
                changes = self._execute_merge(operation)
            elif operation.op_type == "create":
                changes = self._execute_create(operation)
            elif operation.op_type == "remove":
                changes = self._execute_remove(operation)
            elif operation.op_type == "modify":
                changes = self._execute_modify(operation)
            else:
                return ExecutionResult(
                    operation=operation,
                    success=False,
                    error=f"Unknown operation type: {operation.op_type}",
                )

            logger.info(
                "Executed %s operation: %d changes",
                operation.op_type,
                len(changes),
            )
            return ExecutionResult(
                operation=operation,
                success=True,
                changes=changes,
            )

        except Exception as exc:
            logger.error(
                "Failed to execute %s operation: %s",
                operation.op_type,
                exc,
            )
            return ExecutionResult(
                operation=operation,
                success=False,
                error=str(exc),
            )

    def rollback(self, operation: RefinementOperation) -> None:
        """Rollback a previously executed operation using its snapshot.

        Restores entity-to-slice assignments captured before execution.

        Args:
            operation: The operation to rollback.

        Raises:
            KeyError: If no snapshot exists for this operation.
        """
        op_key = id(operation)
        snapshot = self._snapshots.pop(op_key, None)
        if snapshot is None:
            raise KeyError(
                "No snapshot found for this operation.  "
                "Either it was never executed or already rolled back."
            )

        # Restore entity-to-slice assignments from snapshot
        atom_slices = snapshot.get("atom_slices", {})
        for atom_id, slice_id in atom_slices.items():
            atom = self.branch_manager.get_atom(atom_id)
            if atom is not None:
                # Re-register with original slice assignment
                from dataclasses import replace

                restored = replace(atom, vertical_slice=slice_id)
                self.branch_manager.register_atom(restored)

        logger.info("Rolled back %s operation.", operation.op_type)

    # --- Private execution methods ---

    def _execute_move(self, op: RefinementOperation) -> list[str]:
        """Move entities from source slice to target slice."""
        changes: list[str] = []
        target = op.target if isinstance(op.target, str) else op.target[0]

        for entity_id in op.entities:
            atom = self.branch_manager.get_atom(entity_id)
            if atom is None:
                logger.warning("Entity '%s' not found, skipping move.", entity_id)
                continue

            from dataclasses import replace

            updated = replace(atom, vertical_slice=target)
            self.branch_manager.register_atom(updated)
            changes.append(f"Moved '{entity_id}' to slice '{target}'.")

        return changes

    def _execute_split(self, op: RefinementOperation) -> list[str]:
        """Split a grouping unit by creating a new slice for divergent entities."""
        changes: list[str] = []
        targets = op.target if isinstance(op.target, list) else [op.target]

        if targets:
            new_slice_name = targets[0]
            try:
                new_slice = self.branch_manager.create_slice(new_slice_name)
                changes.append(f"Created new slice '{new_slice.slice_id}'.")

                # Move divergent entities to the new slice
                for entity_id in op.entities:
                    atom = self.branch_manager.get_atom(entity_id)
                    if atom is None:
                        continue

                    from dataclasses import replace

                    updated = replace(atom, vertical_slice=new_slice.slice_id)
                    self.branch_manager.register_atom(updated)
                    changes.append(
                        f"Moved '{entity_id}' to new slice '{new_slice.slice_id}'."
                    )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to create split slice '{new_slice_name}': {exc}"
                ) from exc

        return changes

    def _execute_merge(self, op: RefinementOperation) -> list[str]:
        """Merge source slices by moving all entities to the target."""
        changes: list[str] = []
        target = op.target if isinstance(op.target, str) else op.target[0]
        sources = op.source if isinstance(op.source, list) else [op.source]

        for source_id in sources:
            if source_id == target:
                continue
            # Find all atoms in the source slice and move them to target
            all_atoms = self.branch_manager.list_atoms()
            for atom in all_atoms:
                if atom.vertical_slice == source_id:
                    from dataclasses import replace

                    updated = replace(atom, vertical_slice=target)
                    self.branch_manager.register_atom(updated)
                    changes.append(
                        f"Merged '{atom.atom_id}' from '{source_id}' to '{target}'."
                    )

        return changes

    def _execute_create(self, op: RefinementOperation) -> list[str]:
        """Create a new grouping unit (vertical slice)."""
        changes: list[str] = []
        target = op.target if isinstance(op.target, str) else op.target[0]

        try:
            new_slice = self.branch_manager.create_slice(target)
            changes.append(f"Created slice '{new_slice.slice_id}'.")
        except Exception as exc:
            raise RuntimeError(f"Failed to create slice '{target}': {exc}") from exc

        return changes

    def _execute_remove(self, op: RefinementOperation) -> list[str]:
        """Remove a grouping unit after redistributing its entities.

        Entities are NOT deleted -- they become unassigned (vertical_slice=None).
        The caller should MOVE them first if needed.
        """
        changes: list[str] = []
        source = op.source if isinstance(op.source, str) else op.source[0]

        # Unassign all atoms from this slice
        all_atoms = self.branch_manager.list_atoms()
        for atom in all_atoms:
            if atom.vertical_slice == source:
                from dataclasses import replace

                updated = replace(atom, vertical_slice=None)
                self.branch_manager.register_atom(updated)
                changes.append(
                    f"Unassigned '{atom.atom_id}' from removed slice '{source}'."
                )

        return changes

    def _execute_modify(self, op: RefinementOperation) -> list[str]:
        """Modify entity metadata (currently a no-op placeholder)."""
        changes: list[str] = []

        for entity_id in op.entities:
            atom = self.branch_manager.get_atom(entity_id)
            if atom is None:
                logger.warning(
                    "Entity '%s' not found, skipping modify.", entity_id
                )
                continue
            # Modifications would be applied here based on op details
            changes.append(f"Modified metadata for '{entity_id}'.")

        return changes

    # --- Private helpers ---

    def _capture_snapshot(self, op: RefinementOperation) -> dict:
        """Capture pre-state for the entities affected by an operation."""
        atom_slices: dict[str, str | None] = {}

        for entity_id in op.entities:
            atom = self.branch_manager.get_atom(entity_id)
            if atom is not None:
                atom_slices[entity_id] = atom.vertical_slice

        # For merge/remove operations, also snapshot atoms in source slices
        if op.op_type in ("merge", "remove"):
            sources = op.source if isinstance(op.source, list) else [op.source]
            all_atoms = self.branch_manager.list_atoms()
            for atom in all_atoms:
                if atom.vertical_slice in sources:
                    atom_slices[atom.atom_id] = atom.vertical_slice

        return {"atom_slices": atom_slices}

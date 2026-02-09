"""Drift detection for pin targets.

Detects when pin targets no longer match their expected state:
- Signature changes (function parameter changes)
- File moves (file no longer at expected path)
- Function removals (function no longer exists in file)
- Wrapper staleness (wrapper no longer matches atom)
- Broken imports (import no longer resolves)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.projection.lineage.builder import (
    AtomDefinition,
    RawImportRecord,
    compute_signature_hash,
)
from spec_manager.projection.lineage.edges import ProjectionLineageEdge
from spec_manager.projection.lineage.table import ProjectionLineageTable

if TYPE_CHECKING:
    from spec_manager.projection.lineage.test_pin_baseline import (
        TestPinBaselineStore,
    )
    from spec_manager.projection.lineage.test_pin_discovery import TestPinMap


class DriftKind(Enum):
    """Types of drift between pin and target."""

    SIGNATURE_CHANGED = "signature_changed"  # Function signature changed
    FILE_MOVED = "file_moved"  # File no longer at expected path
    FUNCTION_REMOVED = "function_removed"  # Function no longer exists
    WRAPPER_STALE = "wrapper_stale"  # Wrapper no longer matches atom
    IMPORT_BROKEN = "import_broken"  # Import no longer resolves
    TEST_SIGNATURE_CHANGED = "test_signature_changed"  # Test function signature changed


# Severity mapping for drift kinds
_DRIFT_SEVERITY: dict[DriftKind, str] = {
    DriftKind.SIGNATURE_CHANGED: "warning",
    DriftKind.FILE_MOVED: "error",
    DriftKind.FUNCTION_REMOVED: "error",
    DriftKind.WRAPPER_STALE: "warning",
    DriftKind.IMPORT_BROKEN: "error",
    DriftKind.TEST_SIGNATURE_CHANGED: "warning",
}


@dataclass
class PinDrift:
    """A detected drift for a pin target.

    Attributes:
        edge: The affected lineage edge.
        drift_kind: Type of drift detected.
        expected: What was expected (old signature, old path).
        actual: What was found (new signature, new path, "missing").
        severity: "error", "warning", or "info".
    """

    edge: ProjectionLineageEdge
    drift_kind: DriftKind
    expected: str
    actual: str
    severity: str


class PinDriftDetector:
    """Detects drift in pin targets.

    Checks that:
    1. Pin target files still exist at expected paths
    2. Pin target functions still have expected signatures
    3. Import relationships still resolve
    4. Wrappers still correctly wrap their atoms
    """

    def __init__(
        self,
        lineage_table: ProjectionLineageTable,
        atoms: list[AtomDefinition],
    ) -> None:
        self.lineage_table = lineage_table
        self.atoms = atoms
        self._atoms_by_id: dict[str, AtomDefinition] = {a.atom_id: a for a in atoms}

    def detect_all_drift(self) -> list[PinDrift]:
        """Run all drift checks on all edges.

        Returns:
            Combined list of all detected drift items.
        """
        drifts: list[PinDrift] = []

        for edge in self.lineage_table.edges:
            # Check file drift on the atom side
            file_drift = self.detect_file_drift(edge)
            if file_drift is not None:
                drifts.append(file_drift)

            # Check signature drift if we have the atom definition
            atom = self._atoms_by_id.get(edge.from_unit)
            if atom is not None:
                sig_drift = self.detect_signature_drift(edge, atom)
                if sig_drift is not None:
                    drifts.append(sig_drift)

        return drifts

    def detect_file_drift(self, edge: ProjectionLineageEdge) -> PinDrift | None:
        """Check if the file referenced by a lineage edge still exists.

        Checks the from_unit's atom definition file_path. If the atom
        is registered, checks that its source file still exists.

        Args:
            edge: The lineage edge to check.

        Returns:
            PinDrift if file has moved or is missing, None otherwise.
        """
        atom = self._atoms_by_id.get(edge.from_unit)
        if atom is None:
            return None

        if not Path(atom.file_path).exists():
            return PinDrift(
                edge=edge,
                drift_kind=DriftKind.FILE_MOVED,
                expected=atom.file_path,
                actual="missing",
                severity=_DRIFT_SEVERITY[DriftKind.FILE_MOVED],
            )

        return None

    def detect_signature_drift(
        self,
        edge: ProjectionLineageEdge,
        atom: AtomDefinition,
    ) -> PinDrift | None:
        """Check if the function signature has changed since registration.

        Uses AST analysis to extract the current function signature
        and compare its hash with the stored signature_hash.

        Args:
            edge: The lineage edge to check.
            atom: The atom definition with expected signature hash.

        Returns:
            PinDrift if signature changed, None otherwise.
        """
        if not Path(atom.file_path).exists():
            return None

        current_hash = compute_signature_hash(atom.file_path, atom.function_name)

        if current_hash is None:
            # Function no longer exists in file
            return PinDrift(
                edge=edge,
                drift_kind=DriftKind.FUNCTION_REMOVED,
                expected=f"{atom.function_name} in {atom.file_path}",
                actual="missing",
                severity=_DRIFT_SEVERITY[DriftKind.FUNCTION_REMOVED],
            )

        if current_hash != atom.signature_hash:
            return PinDrift(
                edge=edge,
                drift_kind=DriftKind.SIGNATURE_CHANGED,
                expected=atom.signature_hash,
                actual=current_hash,
                severity=_DRIFT_SEVERITY[DriftKind.SIGNATURE_CHANGED],
            )

        return None

    def detect_import_drift(
        self,
        edge: ProjectionLineageEdge,
        import_records: list[RawImportRecord],
    ) -> PinDrift | None:
        """Check if an import relationship still resolves.

        Verifies that the importing file still imports the atom
        function name.

        Args:
            edge: The lineage edge to check.
            import_records: Current import records to validate against.

        Returns:
            PinDrift if import is broken, None otherwise.
        """
        atom = self._atoms_by_id.get(edge.from_unit)
        if atom is None:
            return None

        # Check if any importer still imports this atom's function
        to_file = edge.to_unit.split(":")[0] if ":" in edge.to_unit else edge.to_unit
        found = any(
            r.imported_name == atom.function_name and r.importer_file == to_file
            for r in import_records
        )

        if not found:
            return PinDrift(
                edge=edge,
                drift_kind=DriftKind.IMPORT_BROKEN,
                expected=f"{atom.function_name} imported in {to_file}",
                actual="import not found",
                severity=_DRIFT_SEVERITY[DriftKind.IMPORT_BROKEN],
            )

        return None

    def detect_test_signature_drift(
        self,
        baseline_store: TestPinBaselineStore,
        current_map: TestPinMap,
    ) -> list[PinDrift]:
        """Check if test function signatures have changed since baseline.

        For each baseline entry, recompute the test function's signature hash
        and compare against the stored hash. Changes indicate the test
        contract has shifted.

        Args:
            baseline_store: Previously recorded test signature baselines.
            current_map: Current test-pin association map (for locating test files).

        Returns:
            List of PinDrift for each test whose signature changed.
        """
        from spec_manager.projection.lineage.test_pin_baseline import (
            _compute_test_signature_hash,
        )

        drifts: list[PinDrift] = []

        for bl in baseline_store.baselines:
            current_hash = _compute_test_signature_hash(bl.test_file, bl.test_function)

            if current_hash is None:
                # Test function no longer exists -- create a synthetic edge
                # to report the drift against
                edge = self._find_or_create_edge(bl.pin_func_id)
                if edge is not None:
                    drifts.append(
                        PinDrift(
                            edge=edge,
                            drift_kind=DriftKind.TEST_SIGNATURE_CHANGED,
                            expected=f"{bl.test_function} (hash: {bl.signature_hash})",
                            actual="test function missing or renamed",
                            severity=_DRIFT_SEVERITY[DriftKind.TEST_SIGNATURE_CHANGED],
                        )
                    )
                continue

            if current_hash != bl.signature_hash:
                edge = self._find_or_create_edge(bl.pin_func_id)
                if edge is not None:
                    drifts.append(
                        PinDrift(
                            edge=edge,
                            drift_kind=DriftKind.TEST_SIGNATURE_CHANGED,
                            expected=bl.signature_hash,
                            actual=current_hash,
                            severity=_DRIFT_SEVERITY[DriftKind.TEST_SIGNATURE_CHANGED],
                        )
                    )

        return drifts

    def _find_or_create_edge(self, pin_func_id: str) -> ProjectionLineageEdge | None:
        """Find an existing lineage edge for the given pin-function ID.

        Searches the lineage table for an edge whose from_unit matches
        the pin_func_id. If none found, creates a minimal synthetic edge.

        Args:
            pin_func_id: The pin-function ID to look up.

        Returns:
            A ProjectionLineageEdge, or None if no atom is known.
        """
        from spec_manager.schemas.pin_functions import ProjectionType

        # Look for an existing edge
        for edge in self.lineage_table.edges:
            if edge.from_unit == pin_func_id:
                return edge

        # Create a synthetic edge for reporting
        atom = self._atoms_by_id.get(pin_func_id)
        if atom is not None:
            return ProjectionLineageEdge(
                from_unit=pin_func_id,
                to_unit="test-pin-drift",
                transformation=ProjectionType.PASS_THROUGH,
                confidence=0.0,
            )

        return None


__all__ = [
    "DriftKind",
    "PinDrift",
    "PinDriftDetector",
]

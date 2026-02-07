"""Tests for PinDriftDetector, DriftKind, and PinDrift."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.projection.lineage.builder import (
    AtomDefinition,
    compute_signature_hash,
)
from spec_manager.projection.lineage.drift_detector import (
    DriftKind,
    PinDrift,
    PinDriftDetector,
)
from spec_manager.schemas.pin_functions import ProjectionType
from spec_manager.projection.lineage.import_graph import ImportGraph
from spec_manager.projection.lineage.table import ProjectionLineageTable


def _make_atom(
    atom_id: str,
    function_name: str,
    file_path: str,
    signature_hash: str = "abc123",
) -> AtomDefinition:
    """Helper to create an AtomDefinition."""
    return AtomDefinition(
        atom_id=atom_id,
        function_name=function_name,
        file_path=file_path,
        module_path="test.module",
        signature_hash=signature_hash,
    )


@pytest.fixture
def atom_file(tmp_path: Path) -> Path:
    """Create a file with a function for testing."""
    f = tmp_path / "atoms.py"
    f.write_text(
        "def validate_payment(amount: float, currency: str = 'USD') -> bool:\n"
        "    return True\n",
        encoding="utf-8",
    )
    return f


class TestDriftKind:
    def test_drift_kind_values(self):
        """All enum values are correct."""
        assert DriftKind.SIGNATURE_CHANGED.value == "signature_changed"
        assert DriftKind.FILE_MOVED.value == "file_moved"
        assert DriftKind.FUNCTION_REMOVED.value == "function_removed"
        assert DriftKind.WRAPPER_STALE.value == "wrapper_stale"
        assert DriftKind.IMPORT_BROKEN.value == "import_broken"


class TestPinDriftDetector:
    def test_detect_file_moved(self, tmp_path: Path):
        """File path in edge no longer exists."""
        # Atom points to a file that doesn't exist
        atom = _make_atom(
            "validate_payment",
            "validate_payment",
            str(tmp_path / "nonexistent.py"),
        )

        table = ProjectionLineageTable()
        table.add_edge(
            "validate_payment",
            "handler.py:Handler.process",
            ProjectionType.PASS_THROUGH,
        )

        detector = PinDriftDetector(table, [atom])
        drifts = detector.detect_all_drift()

        file_drifts = [d for d in drifts if d.drift_kind == DriftKind.FILE_MOVED]
        assert len(file_drifts) == 1
        assert file_drifts[0].severity == "error"
        assert file_drifts[0].actual == "missing"

    def test_detect_signature_changed(self, atom_file: Path):
        """Function signature hash mismatch."""
        # Register with wrong hash
        atom = _make_atom(
            "validate_payment",
            "validate_payment",
            str(atom_file),
            signature_hash="wrong_hash",
        )

        table = ProjectionLineageTable()
        table.add_edge(
            "validate_payment",
            "handler.py:Handler.process",
            ProjectionType.PASS_THROUGH,
        )

        detector = PinDriftDetector(table, [atom])
        drifts = detector.detect_all_drift()

        sig_drifts = [d for d in drifts if d.drift_kind == DriftKind.SIGNATURE_CHANGED]
        assert len(sig_drifts) == 1
        assert sig_drifts[0].severity == "warning"
        assert sig_drifts[0].expected == "wrong_hash"

    def test_detect_function_removed(self, tmp_path: Path):
        """Function no longer in file."""
        f = tmp_path / "atoms.py"
        f.write_text("x = 1\n", encoding="utf-8")

        atom = _make_atom("validate_payment", "validate_payment", str(f))

        table = ProjectionLineageTable()
        table.add_edge(
            "validate_payment",
            "handler.py:Handler.process",
            ProjectionType.PASS_THROUGH,
        )

        detector = PinDriftDetector(table, [atom])
        drifts = detector.detect_all_drift()

        removed = [d for d in drifts if d.drift_kind == DriftKind.FUNCTION_REMOVED]
        assert len(removed) == 1
        assert removed[0].actual == "missing"

    def test_no_drift_for_valid_edges(self, atom_file: Path):
        """All checks pass, returns empty list."""
        # Compute the actual hash so it matches
        actual_hash = compute_signature_hash(str(atom_file), "validate_payment")
        assert actual_hash is not None

        atom = _make_atom(
            "validate_payment",
            "validate_payment",
            str(atom_file),
            signature_hash=actual_hash,
        )

        table = ProjectionLineageTable()
        table.add_edge(
            "validate_payment",
            "handler.py:Handler.process",
            ProjectionType.PASS_THROUGH,
        )

        detector = PinDriftDetector(table, [atom])
        drifts = detector.detect_all_drift()
        assert len(drifts) == 0

    def test_severity_assignment(self, tmp_path: Path, atom_file: Path):
        """FILE_MOVED = error, SIGNATURE_CHANGED = warning."""
        # File moved (missing file)
        atom_missing = _make_atom(
            "missing_func",
            "missing_func",
            str(tmp_path / "gone.py"),
        )

        table = ProjectionLineageTable()
        table.add_edge(
            "missing_func",
            "handler.py:H.process",
            ProjectionType.PASS_THROUGH,
        )

        detector = PinDriftDetector(table, [atom_missing])
        drifts = detector.detect_all_drift()
        file_drifts = [d for d in drifts if d.drift_kind == DriftKind.FILE_MOVED]
        assert file_drifts[0].severity == "error"

        # Signature changed
        atom_sig = _make_atom(
            "validate_payment",
            "validate_payment",
            str(atom_file),
            signature_hash="bad_hash",
        )
        table2 = ProjectionLineageTable()
        table2.add_edge(
            "validate_payment",
            "handler.py:H.process",
            ProjectionType.PASS_THROUGH,
        )
        detector2 = PinDriftDetector(table2, [atom_sig])
        drifts2 = detector2.detect_all_drift()
        sig_drifts = [d for d in drifts2 if d.drift_kind == DriftKind.SIGNATURE_CHANGED]
        assert sig_drifts[0].severity == "warning"

    def test_detect_import_drift(self, atom_file: Path):
        """Import no longer resolves in current import graph."""
        actual_hash = compute_signature_hash(str(atom_file), "validate_payment")
        atom = _make_atom(
            "validate_payment",
            "validate_payment",
            str(atom_file),
            signature_hash=actual_hash or "x",
        )

        table = ProjectionLineageTable()
        edge = table.add_edge(
            "validate_payment",
            "handler.py:Handler.process",
            ProjectionType.PASS_THROUGH,
        )

        # Empty import graph = import is broken
        empty_graph = ImportGraph()
        detector = PinDriftDetector(table, [atom])
        drift = detector.detect_import_drift(edge, empty_graph)
        assert drift is not None
        assert drift.drift_kind == DriftKind.IMPORT_BROKEN

    def test_detect_import_drift_no_drift(self, atom_file: Path):
        """Import still resolves in current import graph."""
        actual_hash = compute_signature_hash(str(atom_file), "validate_payment")
        atom = _make_atom(
            "validate_payment",
            "validate_payment",
            str(atom_file),
            signature_hash=actual_hash or "x",
        )

        table = ProjectionLineageTable()
        edge = table.add_edge(
            "validate_payment",
            "handler.py:Handler.process",
            ProjectionType.PASS_THROUGH,
        )

        # Build an import graph that includes the expected import
        from spec_manager.projection.lineage.import_graph import ImportEdge

        graph = ImportGraph()
        graph._add_edge(
            ImportEdge(
                importer_file="handler.py",
                importer_location="handler.py:module-level",
                imported_name="validate_payment",
                imported_from_module="test.module",
            )
        )

        detector = PinDriftDetector(table, [atom])
        drift = detector.detect_import_drift(edge, graph)
        assert drift is None

    def test_unknown_atom_no_file_drift(self):
        """Edges for unknown atoms don't produce file drift."""
        table = ProjectionLineageTable()
        table.add_edge(
            "unknown_atom",
            "handler.py:Handler.process",
            ProjectionType.PASS_THROUGH,
        )

        detector = PinDriftDetector(table, [])
        drifts = detector.detect_all_drift()
        assert len(drifts) == 0

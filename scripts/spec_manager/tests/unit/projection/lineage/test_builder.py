"""Tests for LineageBuilder and AtomDefinition."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.projection.lineage.builder import (
    AtomDefinition,
    LineageBuilder,
    compute_signature_hash,
)
from spec_manager.projection.lineage.import_graph import ImportEdge, ImportGraph
from spec_manager.schemas.pin_functions import ProjectionType


def _make_atom(
    atom_id: str,
    function_name: str,
    file_path: str = "/atoms.py",
    module_path: str = "atoms",
) -> AtomDefinition:
    """Helper to create an AtomDefinition with defaults."""
    return AtomDefinition(
        atom_id=atom_id,
        function_name=function_name,
        file_path=file_path,
        module_path=module_path,
        signature_hash="abc123",
    )


def _make_import_edge(
    importer_file: str,
    imported_name: str,
    imported_from_module: str = "atoms",
    line_no: int = 1,
) -> ImportEdge:
    """Helper to create an ImportEdge with defaults."""
    return ImportEdge(
        importer_file=importer_file,
        importer_location=f"{importer_file}:module-level",
        imported_name=imported_name,
        imported_from_module=imported_from_module,
        line_no=line_no,
    )


@pytest.fixture
def handler_file(tmp_path: Path) -> Path:
    """Create a file with event handler pattern."""
    f = tmp_path / "handler.py"
    f.write_text(
        "from atoms import validate_payment\n"
        "\n"
        "class PaymentHandler(EventHandler):\n"
        "    def handle(self, event):\n"
        "        validate_payment(event.amount)\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def middleware_file(tmp_path: Path) -> Path:
    """Create a file with middleware pattern."""
    f = tmp_path / "mw.py"
    f.write_text(
        "from atoms import calc_tax\n"
        "\n"
        "class TaxMiddleware(Middleware):\n"
        "    def process(self, request):\n"
        "        calc_tax(request.rate)\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def plain_file(tmp_path: Path) -> Path:
    """Create a file with no handler pattern (plain import)."""
    f = tmp_path / "service.py"
    f.write_text(
        "from atoms import validate_payment\n\ndef process():\n    validate_payment(100)\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def retry_file(tmp_path: Path) -> Path:
    """Create a file with retry decorator pattern."""
    f = tmp_path / "resilient.py"
    f.write_text(
        "from atoms import validate_payment\n"
        "\n"
        "@retry\n"
        "def safe_validate(amount):\n"
        "    validate_payment(amount)\n",
        encoding="utf-8",
    )
    return f


class TestLineageBuilder:
    def test_direct_import_classified_as_pass_through(self, plain_file: Path):
        """Direct function call = PASS_THROUGH."""
        graph = ImportGraph()
        edge = _make_import_edge(str(plain_file), "validate_payment")
        graph._add_edge(edge)

        atoms = [_make_atom("validate_payment", "validate_payment")]
        builder = LineageBuilder(graph, atoms)
        table = builder.build_lineage()

        assert len(table.edges) == 1
        assert table.edges[0].transformation == ProjectionType.PASS_THROUGH
        assert table.edges[0].confidence == 1.0

    def test_event_handler_classified_as_event_bridge(self, handler_file: Path):
        """Import in handler class = EVENT_BRIDGE."""
        graph = ImportGraph()
        edge = _make_import_edge(str(handler_file), "validate_payment")
        graph._add_edge(edge)

        atoms = [_make_atom("validate_payment", "validate_payment")]
        builder = LineageBuilder(graph, atoms)
        table = builder.build_lineage()

        assert len(table.edges) == 1
        assert table.edges[0].transformation == ProjectionType.EVENT_BRIDGE
        assert table.edges[0].confidence == 0.9

    def test_middleware_classified_as_middleware_wrap(self, middleware_file: Path):
        """Import in middleware class = MIDDLEWARE_WRAP."""
        graph = ImportGraph()
        edge = _make_import_edge(str(middleware_file), "calc_tax")
        graph._add_edge(edge)

        atoms = [_make_atom("calc_tax", "calc_tax")]
        builder = LineageBuilder(graph, atoms)
        table = builder.build_lineage()

        assert len(table.edges) == 1
        assert table.edges[0].transformation == ProjectionType.MIDDLEWARE_WRAP

    def test_retry_classified_as_retry_decorate(self, retry_file: Path):
        """Import in retry-decorated function = RETRY_DECORATE."""
        graph = ImportGraph()
        edge = _make_import_edge(str(retry_file), "validate_payment")
        graph._add_edge(edge)

        atoms = [_make_atom("validate_payment", "validate_payment")]
        builder = LineageBuilder(graph, atoms)
        table = builder.build_lineage()

        assert len(table.edges) == 1
        assert table.edges[0].transformation == ProjectionType.RETRY_DECORATE
        assert table.edges[0].confidence == 0.9

    def test_no_matching_atom_skipped(self, plain_file: Path):
        """Imports not matching any atom are ignored."""
        graph = ImportGraph()
        edge = _make_import_edge(str(plain_file), "unknown_function")
        graph._add_edge(edge)

        atoms = [_make_atom("validate_payment", "validate_payment")]
        builder = LineageBuilder(graph, atoms)
        table = builder.build_lineage()

        assert len(table.edges) == 0

    def test_multiple_atoms_in_handler_classified_as_smear(self, tmp_path: Path):
        """Multiple atoms imported in same file = SMEAR."""
        f = tmp_path / "aggregator.py"
        f.write_text(
            "from atoms import validate_payment\n"
            "from atoms import calc_tax\n"
            "\n"
            "def aggregate():\n"
            "    validate_payment(100)\n"
            "    calc_tax(0.2)\n",
            encoding="utf-8",
        )

        graph = ImportGraph()
        graph._add_edge(_make_import_edge(str(f), "validate_payment"))
        graph._add_edge(_make_import_edge(str(f), "calc_tax"))

        atoms = [
            _make_atom("validate_payment", "validate_payment"),
            _make_atom("calc_tax", "calc_tax"),
        ]
        builder = LineageBuilder(graph, atoms)
        table = builder.build_lineage()

        assert len(table.edges) == 2
        for e in table.edges:
            assert e.transformation == ProjectionType.SMEAR
            assert e.confidence == 0.8

    def test_confidence_scoring(self, handler_file: Path, plain_file: Path):
        """Direct import = 1.0, handler patterns = 0.9."""
        # Direct import (plain file)
        graph1 = ImportGraph()
        graph1._add_edge(_make_import_edge(str(plain_file), "validate_payment"))
        atoms = [_make_atom("validate_payment", "validate_payment")]
        builder1 = LineageBuilder(graph1, atoms)
        table1 = builder1.build_lineage()
        assert table1.edges[0].confidence == 1.0

        # Handler pattern
        graph2 = ImportGraph()
        graph2._add_edge(_make_import_edge(str(handler_file), "validate_payment"))
        builder2 = LineageBuilder(graph2, atoms)
        table2 = builder2.build_lineage()
        assert table2.edges[0].confidence == 0.9


class TestAtomDefinition:
    def test_roundtrip_serialization(self):
        """to_dict/from_dict roundtrip preserves fields."""
        atom = AtomDefinition(
            atom_id="validate_payment",
            function_name="validate_payment",
            file_path="/src/atoms.py",
            module_path="src.atoms",
            signature_hash="abc123",
        )
        data = atom.to_dict()
        restored = AtomDefinition.from_dict(data)
        assert restored.atom_id == atom.atom_id
        assert restored.function_name == atom.function_name
        assert restored.file_path == atom.file_path
        assert restored.module_path == atom.module_path
        assert restored.signature_hash == atom.signature_hash


class TestComputeSignatureHash:
    def test_compute_known_function(self, tmp_path: Path):
        """Computes hash for a known function."""
        f = tmp_path / "funcs.py"
        f.write_text(
            "def validate_payment(amount: float, currency: str = 'USD') -> bool:\n"
            "    return True\n",
            encoding="utf-8",
        )
        h = compute_signature_hash(str(f), "validate_payment")
        assert h is not None
        assert len(h) == 32  # MD5 hex digest

    def test_compute_missing_function_returns_none(self, tmp_path: Path):
        """Returns None for function not in file."""
        f = tmp_path / "empty.py"
        f.write_text("x = 1\n", encoding="utf-8")
        h = compute_signature_hash(str(f), "nonexistent")
        assert h is None

    def test_compute_missing_file_returns_none(self):
        """Returns None for nonexistent file."""
        h = compute_signature_hash("/nonexistent/path.py", "func")
        assert h is None

    def test_signature_changes_alter_hash(self, tmp_path: Path):
        """Different signatures produce different hashes."""
        f = tmp_path / "funcs.py"
        f.write_text("def f(a: int) -> bool: pass\n", encoding="utf-8")
        h1 = compute_signature_hash(str(f), "f")

        f.write_text("def f(a: int, b: str) -> bool: pass\n", encoding="utf-8")
        h2 = compute_signature_hash(str(f), "f")

        assert h1 != h2

"""Tests for ImportGraph and ImportEdge."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.projection.lineage.import_graph import ImportEdge, ImportGraph


@pytest.fixture
def tmp_py_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with sample Python files."""
    pkg = tmp_path / "sample_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    # Module with from-import
    (pkg / "consumer.py").write_text(
        "from sample_pkg.atoms import validate_payment, calc_tax\nfrom os.path import join\n",
        encoding="utf-8",
    )

    # Module with plain import
    (pkg / "plain_consumer.py").write_text(
        "import json\nimport os\n",
        encoding="utf-8",
    )

    # Module with aliased imports
    (pkg / "aliased_consumer.py").write_text(
        "import numpy as np\nfrom sample_pkg.atoms import validate_payment as vp\n",
        encoding="utf-8",
    )

    # Atom definitions
    (pkg / "atoms.py").write_text(
        "def validate_payment(amount): pass\ndef calc_tax(rate): pass\n",
        encoding="utf-8",
    )

    # A __pycache__ directory with a file (should be excluded)
    pycache = pkg / "__pycache__"
    pycache.mkdir()
    (pycache / "consumer.cpython-311.pyc").write_text("compiled", encoding="utf-8")
    # Also put a .py file in pycache (unlikely but tests the exclude)
    (pycache / "stale.py").write_text("import os\n", encoding="utf-8")

    return pkg


class TestImportEdge:
    def test_roundtrip_serialization(self):
        """Serialization preserves all fields."""
        edge = ImportEdge(
            importer_file="/a/b.py",
            importer_location="/a/b.py:module-level",
            imported_name="validate_payment",
            imported_from_module="atoms",
            imported_from_file="/a/atoms.py",
            line_no=5,
            is_direct=True,
        )
        data = edge.to_dict()
        restored = ImportEdge.from_dict(data)
        assert restored.importer_file == edge.importer_file
        assert restored.imported_name == edge.imported_name
        assert restored.imported_from_module == edge.imported_from_module
        assert restored.line_no == edge.line_no
        assert restored.is_direct == edge.is_direct


class TestImportGraph:
    def test_analyze_import_from(self, tmp_py_dir: Path):
        """Parses 'from module import name' correctly."""
        graph = ImportGraph.build_from_files([tmp_py_dir / "consumer.py"])
        edges = graph.edges
        names = {e.imported_name for e in edges}
        assert "validate_payment" in names
        assert "calc_tax" in names
        assert "join" in names
        # Check that module is recorded
        vp_edges = [e for e in edges if e.imported_name == "validate_payment"]
        assert vp_edges[0].imported_from_module == "sample_pkg.atoms"

    def test_analyze_import(self, tmp_py_dir: Path):
        """Parses 'import module' correctly."""
        graph = ImportGraph.build_from_files([tmp_py_dir / "plain_consumer.py"])
        names = {e.imported_name for e in graph.edges}
        assert "json" in names
        assert "os" in names

    def test_analyze_aliased_import(self, tmp_py_dir: Path):
        """Handles 'import X as Y' and 'from X import Y as Z'."""
        graph = ImportGraph.build_from_files([tmp_py_dir / "aliased_consumer.py"])
        names = {e.imported_name for e in graph.edges}
        # Aliased names should use the alias
        assert "np" in names
        assert "vp" in names
        # Original names should NOT be the imported_name
        assert "numpy" not in names
        assert "validate_payment" not in names

    def test_importers_of(self, tmp_py_dir: Path):
        """Given files that import validate_payment, returns all importers."""
        graph = ImportGraph.build_from_directory(tmp_py_dir)
        importers = graph.importers_of("validate_payment")
        # consumer.py imports validate_payment (aliased_consumer uses alias 'vp')
        assert len(importers) == 1
        assert "consumer.py" in importers[0].importer_file

    def test_imports_in(self, tmp_py_dir: Path):
        """Returns all imports for a given file."""
        graph = ImportGraph.build_from_directory(tmp_py_dir)
        consumer_path = str(tmp_py_dir / "consumer.py")
        imports = graph.imports_in(consumer_path)
        assert len(imports) == 3  # validate_payment, calc_tax, join

    def test_build_from_directory_excludes_pycache(self, tmp_py_dir: Path):
        """Skips __pycache__ directories."""
        graph = ImportGraph.build_from_directory(tmp_py_dir)
        for edge in graph.edges:
            assert "__pycache__" not in edge.importer_file

    def test_resolve_module_to_file(self, tmp_py_dir: Path):
        """Resolves dotted module path to actual file."""
        graph = ImportGraph()
        # The sample_pkg directory is at tmp_py_dir
        parent = tmp_py_dir.parent
        result = graph.resolve_module_to_file("sample_pkg.atoms", [parent])
        assert result is not None
        assert result.endswith("atoms.py")

    def test_resolve_module_to_package(self, tmp_py_dir: Path):
        """Resolves module path to package __init__.py."""
        graph = ImportGraph()
        parent = tmp_py_dir.parent
        result = graph.resolve_module_to_file("sample_pkg", [parent])
        assert result is not None
        assert result.endswith("__init__.py")

    def test_resolve_module_not_found(self, tmp_py_dir: Path):
        """Returns None for unresolvable module."""
        graph = ImportGraph()
        result = graph.resolve_module_to_file("nonexistent.module", [tmp_py_dir])
        assert result is None

    def test_graph_roundtrip_serialization(self, tmp_py_dir: Path):
        """Serialization preserves all edges."""
        graph = ImportGraph.build_from_directory(tmp_py_dir)
        data = graph.to_dict()
        restored = ImportGraph.from_dict(data)
        assert len(restored.edges) == len(graph.edges)
        for orig, rest in zip(graph.edges, restored.edges, strict=False):
            assert orig.importer_file == rest.importer_file
            assert orig.imported_name == rest.imported_name
            assert orig.imported_from_module == rest.imported_from_module
            assert orig.line_no == rest.line_no

    def test_build_from_files_skips_missing(self, tmp_path: Path):
        """build_from_files skips files that don't exist."""
        missing = tmp_path / "nonexistent.py"
        graph = ImportGraph.build_from_files([missing])
        assert len(graph.edges) == 0

    def test_syntax_error_file_skipped(self, tmp_path: Path):
        """Files with syntax errors are skipped without raising."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(:\n", encoding="utf-8")
        graph = ImportGraph.build_from_files([bad_file])
        assert len(graph.edges) == 0

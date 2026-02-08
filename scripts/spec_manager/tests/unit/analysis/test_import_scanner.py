"""Tests for the import scanner engine."""

from __future__ import annotations

from pathlib import Path

from spec_manager.analysis.import_scanner import (
    build_atom_registry,
    scan_directory_imports,
    scan_file_imports,
)


class TestScanFileImports:
    """Test scan_file_imports with various import patterns."""

    def test_simple_from_import(self, tmp_path: Path) -> None:
        """Detect a simple ``from atoms.payment import validate_payment``."""
        arch_file = tmp_path / "handler.py"
        arch_file.write_text(
            "from atoms.payment import validate_payment\n"
            "\n"
            "def process(data):\n"
            "    return validate_payment(data)\n",
            encoding="utf-8",
        )
        hits = scan_file_imports(arch_file, {"validate_payment"})
        assert len(hits) == 1
        assert hits[0].atom_name == "validate_payment"
        assert hits[0].arch_file == str(arch_file)

    def test_module_level_import(self, tmp_path: Path) -> None:
        """Detect ``import atoms.payment`` followed by attribute access."""
        arch_file = tmp_path / "handler.py"
        arch_file.write_text(
            "import atoms.payment\n"
            "\n"
            "def process(data):\n"
            "    return atoms.payment.validate_payment(data)\n",
            encoding="utf-8",
        )
        # The tail of "atoms.payment" is "payment", not "validate_payment",
        # so this should NOT produce a hit for "validate_payment" via the
        # import-level detection (it only checks tail of module names).
        hits = scan_file_imports(arch_file, {"validate_payment"})
        assert len(hits) == 0

    def test_aliased_import(self, tmp_path: Path) -> None:
        """Detect ``from atoms import validate_payment as vp``."""
        arch_file = tmp_path / "handler.py"
        arch_file.write_text(
            "from atoms import validate_payment as vp\n\ndef handler():\n    return vp(42)\n",
            encoding="utf-8",
        )
        hits = scan_file_imports(arch_file, {"validate_payment"})
        assert len(hits) == 1
        assert hits[0].atom_name == "validate_payment"

    def test_no_matches_returns_empty(self, tmp_path: Path) -> None:
        """No atom imports yields empty list."""
        arch_file = tmp_path / "helper.py"
        arch_file.write_text("import os\n\nprint(os.getcwd())\n", encoding="utf-8")
        hits = scan_file_imports(arch_file, {"validate_payment"})
        assert hits == []

    def test_syntax_error_handled_gracefully(self, tmp_path: Path) -> None:
        """Files with syntax errors do not crash the scanner."""
        arch_file = tmp_path / "broken.py"
        arch_file.write_text("def broken(\n", encoding="utf-8")
        hits = scan_file_imports(arch_file, {"validate_payment"})
        assert hits == []

    def test_multiple_imports_in_one_file(self, tmp_path: Path) -> None:
        """Multiple atom imports from the same file produce multiple hits."""
        arch_file = tmp_path / "pipeline.py"
        arch_file.write_text(
            "from atoms import validate_payment, compute_tax\n"
            "\n"
            "def run():\n"
            "    validate_payment({})\n"
            "    compute_tax(100)\n",
            encoding="utf-8",
        )
        hits = scan_file_imports(arch_file, {"validate_payment", "compute_tax"})
        assert len(hits) == 2
        atom_names = {h.atom_name for h in hits}
        assert atom_names == {"validate_payment", "compute_tax"}


class TestScanDirectoryImports:
    """Test scan_directory_imports aggregation."""

    def test_aggregates_across_files(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text(
            "from atoms import validate_payment\n\nvalidate_payment()\n",
            encoding="utf-8",
        )
        file_b = tmp_path / "b.py"
        file_b.write_text(
            "from atoms import compute_tax\n\ncompute_tax()\n",
            encoding="utf-8",
        )

        hits = scan_directory_imports(tmp_path, {"validate_payment", "compute_tax"})
        assert len(hits) == 2

    def test_exclude_patterns(self, tmp_path: Path) -> None:
        """Excluded patterns are skipped."""
        (tmp_path / "tests").mkdir()
        test_file = tmp_path / "tests" / "test_x.py"
        test_file.write_text(
            "from atoms import validate_payment\n",
            encoding="utf-8",
        )
        src_file = tmp_path / "handler.py"
        src_file.write_text(
            "from atoms import validate_payment\n\nvalidate_payment()\n",
            encoding="utf-8",
        )

        hits = scan_directory_imports(tmp_path, {"validate_payment"}, exclude_patterns=["tests/*"])
        assert len(hits) == 1
        assert "handler.py" in hits[0].arch_file


class TestBuildAtomRegistry:
    """Test build_atom_registry extraction."""

    def test_extracts_function_signatures(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "payment.py"
        atom_file.write_text(
            "def validate_payment(amount: float, currency: str) -> bool:\n"
            '    """Validate a payment."""\n'
            "    return amount > 0\n"
            "\n"
            "def compute_tax(amount: float) -> float:\n"
            "    return amount * 0.1\n",
            encoding="utf-8",
        )

        registry = build_atom_registry(tmp_path)
        assert "validate_payment" in registry
        assert "compute_tax" in registry

        vp = registry["validate_payment"]
        assert vp["file"] == str(atom_file)
        assert "amount: float" in vp["params"]
        assert "currency: str" in vp["params"]
        assert vp["return_type"] == "bool"

    def test_skips_private_functions(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "helpers.py"
        atom_file.write_text(
            "def _private_helper():\n    pass\n"
            "\ndef __dunder_method():\n    pass\n"
            "\ndef public_func():\n    pass\n",
            encoding="utf-8",
        )
        registry = build_atom_registry(tmp_path)
        assert "_private_helper" not in registry
        assert "__dunder_method" not in registry
        assert "public_func" in registry

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        registry = build_atom_registry(tmp_path / "nonexistent")
        assert registry == {}

    def test_handles_no_type_annotations(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "simple.py"
        atom_file.write_text(
            "def process(data):\n    return data\n",
            encoding="utf-8",
        )
        registry = build_atom_registry(tmp_path)
        assert "process" in registry
        assert registry["process"]["params"] == ["data"]
        assert registry["process"]["return_type"] == ""

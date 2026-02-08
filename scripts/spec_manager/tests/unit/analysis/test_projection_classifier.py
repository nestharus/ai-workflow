"""Tests for projection type classification."""

from __future__ import annotations

from spec_manager.analysis.import_scanner import ImportHit
from spec_manager.analysis.projection_classifier import (
    classify_all_imports,
    classify_import,
    detect_introductions,
)
from spec_manager.schemas.lineage import LineageEdge


class TestClassifyImport:
    """Test classify_import for each projection type."""

    def test_pass_through_direct_return(self) -> None:
        """Pass-through: function directly returns the atom call result."""
        hit = ImportHit(
            atom_name="validate_payment",
            arch_file="handler.py",
            arch_location="handler.py:process",
            import_statement="from atoms import validate_payment",
            usage_sites=["4"],
        )
        source = (
            "from atoms import validate_payment\n"
            "\n"
            "def process(data):\n"
            "    return validate_payment(data)\n"
        )
        edge = classify_import(hit, source, {"validate_payment"})
        assert edge.transformation == "pass_through"
        assert edge.from_atom == "validate_payment"

    def test_wrap_with_transform(self) -> None:
        """Wrap: function calls atom but transforms the result."""
        hit = ImportHit(
            atom_name="compute_tax",
            arch_file="billing.py",
            arch_location="billing.py:apply_tax",
            import_statement="from atoms import compute_tax",
            usage_sites=["4"],
        )
        source = (
            "from atoms import compute_tax\n"
            "\n"
            "def apply_tax(amount):\n"
            "    tax = compute_tax(amount)\n"
            "    return {'amount': amount, 'tax': tax, 'total': amount + tax}\n"
        )
        edge = classify_import(hit, source, {"compute_tax"})
        assert edge.transformation == "middleware_wrap"

    def test_smear_multiple_atom_calls(self) -> None:
        """Smear: function calls multiple atoms and combines results."""
        hit = ImportHit(
            atom_name="validate_payment",
            arch_file="pipeline.py",
            arch_location="pipeline.py:run_pipeline",
            import_statement="from atoms import validate_payment, compute_tax",
            usage_sites=["5"],
        )
        source = (
            "from atoms import validate_payment, compute_tax\n"
            "\n"
            "def run_pipeline(data):\n"
            "    valid = validate_payment(data)\n"
            "    tax = compute_tax(data['amount'])\n"
            "    return {'valid': valid, 'tax': tax}\n"
        )
        edge = classify_import(hit, source, {"validate_payment", "compute_tax"})
        assert edge.transformation == "smear"

    def test_syntax_error_yields_wrap_with_low_confidence(self) -> None:
        """Unparseable source falls back to wrap with low confidence."""
        hit = ImportHit(
            atom_name="x",
            arch_file="broken.py",
            arch_location="broken.py",
            import_statement="from atoms import x",
        )
        edge = classify_import(hit, "def broken(\n", {"x"})
        assert edge.transformation == "middleware_wrap"
        assert edge.confidence == 0.5

    def test_no_usage_sites_defaults_to_wrap(self) -> None:
        """When there are no usage sites, classification defaults to wrap."""
        hit = ImportHit(
            atom_name="validate_payment",
            arch_file="handler.py",
            arch_location="handler.py",
            import_statement="from atoms import validate_payment",
            usage_sites=[],
        )
        source = "from atoms import validate_payment\n"
        edge = classify_import(hit, source, {"validate_payment"})
        # Without usage sites we cannot detect pass-through or smear,
        # so the default middleware_wrap is acceptable.
        assert edge.transformation == "middleware_wrap"


class TestClassifyAllImports:
    """Test batch classification."""

    def test_processes_batch(self) -> None:
        hits = [
            ImportHit(
                atom_name="validate_payment",
                arch_file="handler.py",
                arch_location="handler.py:process",
                import_statement="from atoms import validate_payment",
                usage_sites=["3"],
            ),
            ImportHit(
                atom_name="compute_tax",
                arch_file="billing.py",
                arch_location="billing.py:calc",
                import_statement="from atoms import compute_tax",
                usage_sites=["3"],
            ),
        ]
        sources = {
            "handler.py": (
                "from atoms import validate_payment\n"
                "def process(d):\n"
                "    return validate_payment(d)\n"
            ),
            "billing.py": (
                "from atoms import compute_tax\ndef calc(a):\n    return compute_tax(a)\n"
            ),
        }
        edges = classify_all_imports(hits, sources, {"validate_payment", "compute_tax"})
        assert len(edges) == 2
        assert all(isinstance(e, LineageEdge) for e in edges)


class TestDetectIntroductions:
    """Test introduction detection."""

    def test_finds_files_with_no_imports(self) -> None:
        arch_files = ["src/handler.py", "src/utils.py", "src/helpers.py"]
        edges = [
            LineageEdge(
                from_atom="validate_payment",
                to_location="src/handler.py:process",
                transformation="pass_through",
            )
        ]
        intros = detect_introductions(arch_files, edges)
        assert "src/utils.py" in intros
        assert "src/helpers.py" in intros
        assert "src/handler.py" not in intros

    def test_no_introductions_when_all_covered(self) -> None:
        arch_files = ["a.py", "b.py"]
        edges = [
            LineageEdge(
                from_atom="x",
                to_location="a.py:func_a",
                transformation="middleware_wrap",
            ),
            LineageEdge(
                from_atom="y",
                to_location="b.py:func_b",
                transformation="pass_through",
            ),
        ]
        intros = detect_introductions(arch_files, edges)
        assert intros == []

    def test_empty_inputs(self) -> None:
        intros = detect_introductions([], [])
        assert intros == []

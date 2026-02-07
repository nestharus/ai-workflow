"""Tests for pin-function orchestrator (Plan 5)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from spec_manager.pin_functions.orchestrator import (
    PinFunctionConfig,
    PinFunctionOrchestrator,
)
from spec_manager.schemas.pin_functions import PinFunctionRegistry


def _setup_fixture_project(root: Path) -> None:
    """Set up a fixture project with known atoms and architectural files."""
    # Create atom files
    atoms_dir = root / "atoms"
    atoms_dir.mkdir(parents=True)

    (atoms_dir / "__init__.py").write_text("", encoding="utf-8")

    (atoms_dir / "payment.py").write_text(
        textwrap.dedent("""\
        def validate_payment(data: dict) -> bool:
            \"\"\"Validate a payment transaction.\"\"\"
            return data.get("amount", 0) > 0

        def compute_tax(amount: float, rate: float = 0.1) -> float:
            \"\"\"Compute tax for an amount.\"\"\"
            return amount * rate
        """),
        encoding="utf-8",
    )

    (atoms_dir / "shipping.py").write_text(
        textwrap.dedent("""\
        def estimate_shipping(weight: float, distance: float) -> float:
            \"\"\"Estimate shipping cost.\"\"\"
            return weight * 0.5 + distance * 0.1
        """),
        encoding="utf-8",
    )

    # Create architectural files
    services_dir = root / "services"
    services_dir.mkdir(parents=True)

    (services_dir / "__init__.py").write_text("", encoding="utf-8")

    (services_dir / "payment_handler.py").write_text(
        textwrap.dedent("""\
        from atoms.payment import validate_payment, compute_tax

        def handle_payment(event):
            if validate_payment(event.data):
                tax = compute_tax(event.data["amount"])
                return {"status": "ok", "tax": tax}
            return {"status": "invalid"}
        """),
        encoding="utf-8",
    )

    (services_dir / "shipping_handler.py").write_text(
        textwrap.dedent("""\
        from atoms.shipping import estimate_shipping

        def handle_shipping(order):
            cost = estimate_shipping(order.weight, order.distance)
            return {"shipping_cost": cost}
        """),
        encoding="utf-8",
    )


class TestScan:
    """Tests for full scan on a fixture project."""

    def test_scan_finds_atoms(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.algorithmic_roots = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        # Should find validate_payment, compute_tax, estimate_shipping
        func_names = {pf.function_name for pf in registry.pin_functions}
        assert "validate_payment" in func_names
        assert "compute_tax" in func_names
        assert "estimate_shipping" in func_names

    def test_scan_finds_import_edges(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.algorithmic_roots = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        # Should find edges for the imports
        assert len(registry.import_edges) >= 1

    def test_scan_empty_project(self, tmp_path):
        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        assert len(registry.pin_functions) == 0
        assert len(registry.import_edges) == 0


class TestDiff:
    """Tests for diff detection between two registries."""

    def test_diff_detects_modification(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.architectural_roots = ["services"]
        config.import_graph.algorithmic_roots = ["atoms"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)

        # Save initial registry
        registry = orchestrator.scan()
        save_path = orchestrator.save_registry(registry)

        # Modify a function
        payment_file = tmp_path / "atoms" / "payment.py"
        payment_file.write_text(
            textwrap.dedent("""\
            def validate_payment(data: dict) -> bool:
                \"\"\"Validate a payment transaction.\"\"\"
                return data.get("amount", 0) > 0 and data.get("currency") is not None

            def compute_tax(amount: float, rate: float = 0.1) -> float:
                \"\"\"Compute tax for an amount.\"\"\"
                return amount * rate
            """),
            encoding="utf-8",
        )

        # Diff should detect the change
        report = orchestrator.diff(save_path)
        assert len(report.changes) >= 1

        modified_names = {c.function_name for c in report.changes if c.change_type == "modified"}
        assert "validate_payment" in modified_names


class TestQuery:
    """Tests for query commands."""

    def test_query_importers(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.algorithmic_roots = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        edges = orchestrator.query_importers("validate_payment")

        # Should find at least one importer
        assert len(edges) >= 1

    def test_query_importers_not_found(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.architectural_roots = ["services"]
        config.import_graph.algorithmic_roots = ["atoms"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        edges = orchestrator.query_importers("nonexistent_func")

        assert edges == []

    def test_query_pin_functions_for_file(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.algorithmic_roots = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)

        # Get the actual file path as it would appear in edges
        handler_path = str(tmp_path / "services" / "payment_handler.py")
        pin_funcs = orchestrator.query_pin_functions_for(handler_path)

        # Should find validate_payment and compute_tax
        func_names = {pf.function_name for pf in pin_funcs}
        # At least one of the two functions should be found
        assert len(func_names) >= 1


class TestSaveRegistry:
    """Tests for saving and loading registries."""

    def test_save_creates_file(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.architectural_roots = ["services"]
        config.import_graph.algorithmic_roots = ["atoms"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        path = orchestrator.save_registry(registry)
        assert path.exists()

        # Should be valid JSON
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "schema_version" in data
        assert "pin_functions" in data
        assert "import_edges" in data

    def test_saved_registry_can_be_loaded(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.architectural_roots = ["services"]
        config.import_graph.algorithmic_roots = ["atoms"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        path = orchestrator.save_registry(registry)
        loaded = PinFunctionRegistry.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        assert len(loaded.pin_functions) == len(registry.pin_functions)


class TestAnalysisFile:
    """Tests for analysis file generation."""

    def test_analysis_contains_expected_sections(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.algorithmic_roots = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        report = orchestrator.generate_analysis_file()

        assert "# Pin-Function Analysis Report" in report
        assert "## Summary" in report
        assert "## Pin-Functions" in report
        assert "Total pin-functions:" in report

    def test_analysis_lists_functions(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.algorithmic_roots = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        report = orchestrator.generate_analysis_file()

        assert "validate_payment" in report
        assert "compute_tax" in report
        assert "estimate_shipping" in report

    def test_analysis_empty_project(self, tmp_path):
        config = PinFunctionConfig()
        config.extraction.atom_directories = ["atoms"]
        config.import_graph.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        report = orchestrator.generate_analysis_file()

        assert "Total pin-functions: 0" in report

"""Tests for pin-function orchestrator (Plan 5)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

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
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        # Should find validate_payment, compute_tax, estimate_shipping
        func_names = {pf.function_name for pf in registry.pin_functions}
        assert "validate_payment" in func_names
        assert "compute_tax" in func_names
        assert "estimate_shipping" in func_names

    def test_scan_produces_no_edges(self, tmp_path):
        """Filesystem scan no longer produces edges — edges are LLM-sourced only."""
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        assert len(registry.pin_functions) >= 1
        assert len(registry.import_edges) == 0

    def test_scan_mode_proposals_only(self, tmp_path):
        """Proposals-only mode produces pins and edges from proposals."""
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)

        pin_proposals = [
            {
                "function_name": "proposed_func",
                "module_path": "atoms.proposed",
                "file_path": str(tmp_path / "atoms" / "proposed.py"),
                "line_start": 1,
                "line_end": 3,
                "signature": "(x: int) -> int",
            }
        ]
        edge_proposals = [
            {
                "pin_func_id": "PFUNC-P-0001",
                "arch_location": "services/handler.py:do_work",
                "arch_file_path": str(tmp_path / "services" / "handler.py"),
                "arch_line": 5,
                "projection_type": "pass_through",
            }
        ]

        registry = orchestrator.scan(
            mode="proposals",
            pin_proposals=pin_proposals,
            edge_proposals=edge_proposals,
        )

        func_names = {pf.function_name for pf in registry.pin_functions}
        assert "proposed_func" in func_names
        assert len(registry.import_edges) == 1
        assert registry.import_edges[0].arch_location == "services/handler.py:do_work"

    def test_scan_mode_both_merges(self, tmp_path):
        """Both mode: scan pins + proposal edges merged together."""
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)

        # First do a scan to get a pin_func_id
        scan_only = orchestrator.scan(mode="scan")
        assert len(scan_only.pin_functions) >= 1
        first_pin_id = scan_only.pin_functions[0].pin_func_id

        # Now do "both" with edge proposals referencing scanned pin
        edge_proposals = [
            {
                "pin_func_id": first_pin_id,
                "arch_location": "services/payment_handler.py:handle_payment",
                "arch_file_path": str(tmp_path / "services" / "payment_handler.py"),
                "arch_line": 3,
                "projection_type": "pass_through",
            }
        ]

        # New orchestrator to reset edge counter
        orchestrator2 = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator2.scan(mode="both", edge_proposals=edge_proposals)

        assert len(registry.pin_functions) >= 1
        assert len(registry.import_edges) == 1
        assert registry.import_edges[0].pin_func_id == first_pin_id

    def test_scan_empty_project(self, tmp_path):
        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        assert len(registry.pin_functions) == 0
        assert len(registry.import_edges) == 0


class TestDiff:
    """Tests for diff detection between two registries."""

    def test_diff_detects_modification(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.architectural_roots = ["services"]
        config.algorithmic_roots = ["atoms"]

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
    """Tests for query commands.

    Since scan no longer produces edges, query methods only find results
    when edges have been provided via proposals.  Without proposals,
    ``query_importers`` and ``query_pin_functions_for`` return empty.
    """

    def test_query_importers_no_edges(self, tmp_path):
        """Without proposals, query_importers returns empty (scan has no edges)."""
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        edges = orchestrator.query_importers("validate_payment")

        assert edges == []

    def test_query_importers_not_found(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.architectural_roots = ["services"]
        config.algorithmic_roots = ["atoms"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        edges = orchestrator.query_importers("nonexistent_func")

        assert edges == []

    def test_query_pin_functions_for_file_no_edges(self, tmp_path):
        """Without proposals, query_pin_functions_for returns empty."""
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)

        handler_path = str(tmp_path / "services" / "payment_handler.py")
        pin_funcs = orchestrator.query_pin_functions_for(handler_path)

        assert len(pin_funcs) == 0


class TestSaveRegistry:
    """Tests for saving and loading registries."""

    def test_save_creates_file(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.architectural_roots = ["services"]
        config.algorithmic_roots = ["atoms"]

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
        config.atom_directories = ["atoms"]
        config.architectural_roots = ["services"]
        config.algorithmic_roots = ["atoms"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        registry = orchestrator.scan()

        path = orchestrator.save_registry(registry)
        loaded = PinFunctionRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))
        assert len(loaded.pin_functions) == len(registry.pin_functions)


class TestAnalysisFile:
    """Tests for analysis file generation."""

    def test_analysis_contains_expected_sections(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        report = orchestrator.generate_analysis_file()

        assert "# Pin-Function Analysis Report" in report
        assert "## Summary" in report
        assert "## Pin-Functions" in report
        assert "Total pin-functions:" in report

    def test_analysis_lists_functions(self, tmp_path):
        _setup_fixture_project(tmp_path)

        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.algorithmic_roots = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        report = orchestrator.generate_analysis_file()

        assert "validate_payment" in report
        assert "compute_tax" in report
        assert "estimate_shipping" in report

    def test_analysis_empty_project(self, tmp_path):
        config = PinFunctionConfig()
        config.atom_directories = ["atoms"]
        config.architectural_roots = ["services"]

        orchestrator = PinFunctionOrchestrator(tmp_path, config=config)
        report = orchestrator.generate_analysis_file()

        assert "Total pin-functions: 0" in report

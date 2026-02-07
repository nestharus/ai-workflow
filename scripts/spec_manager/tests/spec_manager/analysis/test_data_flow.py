"""Tests for data flow summary extraction."""

from __future__ import annotations

from pathlib import Path

from spec_manager.analysis.data_flow import extract_all_data_flows, extract_data_flow


class TestExtractDataFlow:
    """Test extract_data_flow for individual atoms."""

    def test_captures_typed_parameters(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "payment.py"
        atom_file.write_text(
            "def validate_payment(amount: float, currency: str) -> bool:\n"
            '    """Validate a payment."""\n'
            "    return amount > 0\n",
            encoding="utf-8",
        )
        flow = extract_data_flow("validate_payment", atom_file)
        assert flow.atom_id == "validate_payment"
        assert "amount: float" in flow.signals_in
        assert "currency: str" in flow.signals_in
        assert flow.signals_out == ["bool"]

    def test_captures_return_type(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "tax.py"
        atom_file.write_text(
            "def compute_tax(amount: float) -> float:\n"
            "    return amount * 0.1\n",
            encoding="utf-8",
        )
        flow = extract_data_flow("compute_tax", atom_file)
        assert flow.signals_out == ["float"]

    def test_detects_store_access_via_definitions(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "repo.py"
        atom_file.write_text(
            "def save_record(record: dict) -> None:\n"
            "    pass\n",
            encoding="utf-8",
        )
        store_defs = {"user_db": ["save_record", "load_record"]}
        flow = extract_data_flow("save_record", atom_file, store_definitions=store_defs)
        assert "user_db" in flow.stores_touched

    def test_handles_no_type_annotations(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "simple.py"
        atom_file.write_text(
            "def process(data):\n    return data\n",
            encoding="utf-8",
        )
        flow = extract_data_flow("process", atom_file)
        assert flow.signals_in == ["data"]
        assert flow.signals_out == []

    def test_function_not_found(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "other.py"
        atom_file.write_text("def other_func():\n    pass\n", encoding="utf-8")
        flow = extract_data_flow("nonexistent", atom_file)
        assert flow.atom_id == "nonexistent"
        assert flow.signals_in == []

    def test_file_not_found(self, tmp_path: Path) -> None:
        flow = extract_data_flow("x", tmp_path / "missing.py")
        assert flow.atom_id == "x"
        assert flow.signals_in == []

    def test_heuristic_store_detection(self, tmp_path: Path) -> None:
        atom_file = tmp_path / "cached.py"
        atom_file.write_text(
            "def fetch_data(key: str) -> dict:\n"
            "    return cache.get(key)\n",
            encoding="utf-8",
        )
        flow = extract_data_flow("fetch_data", atom_file)
        assert "cache.get" in flow.stores_touched


class TestExtractAllDataFlows:
    """Test batch extraction."""

    def test_processes_batch(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text(
            "def func_a(x: int) -> int:\n    return x + 1\n",
            encoding="utf-8",
        )
        file_b = tmp_path / "b.py"
        file_b.write_text(
            "def func_b(y: str) -> str:\n    return y.upper()\n",
            encoding="utf-8",
        )
        registry = {
            "func_a": {"file": str(file_a), "params": ["x: int"], "return_type": "int"},
            "func_b": {"file": str(file_b), "params": ["y: str"], "return_type": "str"},
        }
        flows = extract_all_data_flows(registry)
        assert "func_a" in flows
        assert "func_b" in flows
        assert flows["func_a"].signals_in == ["x: int"]
        assert flows["func_b"].signals_out == ["str"]

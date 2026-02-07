"""Tests for the analysis file generator orchestrator."""

from __future__ import annotations

from pathlib import Path

from spec_manager.analysis.generator import (
    generate_analysis_file,
    read_analysis_json,
    write_analysis_json,
)
from spec_manager.schemas.lineage import AnalysisFileSchema


class TestGenerateAnalysisFile:
    """Test the core generate_analysis_file orchestrator."""

    def _setup_fixture(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a minimal fixture: one algorithmic file, one architectural file."""
        algo_dir = tmp_path / "algorithmic"
        algo_dir.mkdir()
        algo_file = algo_dir / "payment.py"
        algo_file.write_text(
            "def validate_payment(amount: float) -> bool:\n"
            '    """Validate a payment amount."""\n'
            "    return amount > 0\n",
            encoding="utf-8",
        )

        arch_dir = tmp_path / "architectural"
        arch_dir.mkdir()
        arch_file = arch_dir / "handler.py"
        arch_file.write_text(
            "from payment import validate_payment\n"
            "\n"
            "def process(data):\n"
            "    return validate_payment(data['amount'])\n",
            encoding="utf-8",
        )

        return algo_dir, arch_dir

    def test_minimal_fixture(self, tmp_path: Path) -> None:
        algo_dir, arch_dir = self._setup_fixture(tmp_path)

        analysis = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-001",
        )

        assert analysis.run_id == "test-001"
        assert analysis.generated_at != ""
        assert len(analysis.atoms) == 1
        assert analysis.atoms[0].atom_id == "validate_payment"
        assert analysis.atoms[0].atom_file == str(algo_dir / "payment.py")

    def test_unimplemented_atom_detection(self, tmp_path: Path) -> None:
        """An atom with no architectural imports is flagged unimplemented."""
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        (algo_dir / "orphan.py").write_text(
            "def lonely_atom(x: int) -> int:\n    return x\n",
            encoding="utf-8",
        )

        arch_dir = tmp_path / "arch"
        arch_dir.mkdir()
        (arch_dir / "empty.py").write_text(
            "# No atom imports here\npass\n",
            encoding="utf-8",
        )

        analysis = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-unimpl",
        )

        assert len(analysis.atoms) == 1
        assert analysis.atoms[0].is_unimplemented is True
        assert analysis.summary["unimplemented_atoms"] == 1

    def test_orphaned_architecture_detection(self, tmp_path: Path) -> None:
        """Architectural files with no atom imports appear in orphaned list."""
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        (algo_dir / "atom.py").write_text(
            "def my_atom() -> None:\n    pass\n",
            encoding="utf-8",
        )

        arch_dir = tmp_path / "arch"
        arch_dir.mkdir()
        (arch_dir / "orphan.py").write_text(
            "def standalone_function():\n    return 42\n",
            encoding="utf-8",
        )

        analysis = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-orphan",
        )

        assert len(analysis.orphaned_architecture) >= 1
        orphan_locations = [o.location for o in analysis.orphaned_architecture]
        assert any("orphan.py" in loc for loc in orphan_locations)

    def test_summary_statistics(self, tmp_path: Path) -> None:
        algo_dir, arch_dir = self._setup_fixture(tmp_path)

        analysis = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-stats",
        )

        summary = analysis.summary
        assert "total_atoms" in summary
        assert "implemented_atoms" in summary
        assert "unimplemented_atoms" in summary
        assert "total_lineage_edges" in summary
        assert summary["total_atoms"] == 1

    def test_empty_inputs_produce_valid_schema(self, tmp_path: Path) -> None:
        algo_dir = tmp_path / "empty_algo"
        algo_dir.mkdir()
        arch_dir = tmp_path / "empty_arch"
        arch_dir.mkdir()

        analysis = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-empty",
        )

        assert analysis.atoms == []
        assert analysis.orphaned_architecture == []
        assert analysis.summary["total_atoms"] == 0

    def test_idempotency(self, tmp_path: Path) -> None:
        """Running the generator twice with unchanged inputs produces identical output."""
        algo_dir, arch_dir = self._setup_fixture(tmp_path)

        analysis1 = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-idem",
        )
        analysis2 = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-idem",
        )

        # Compare everything except generated_at (timestamps differ).
        dump1 = analysis1.model_dump()
        dump2 = analysis2.model_dump()
        dump1.pop("generated_at")
        dump2.pop("generated_at")
        assert dump1 == dump2


class TestJsonRoundTrip:
    """Test JSON serialization and deserialization."""

    def test_write_and_read(self, tmp_path: Path) -> None:
        schema = AnalysisFileSchema(
            run_id="test-rt",
            generated_at="2025-01-01T00:00:00Z",
            summary={"total_atoms": 5, "implemented_atoms": 3},
        )
        json_path = tmp_path / "analysis.json"
        write_analysis_json(schema, json_path)
        restored = read_analysis_json(json_path)

        assert restored.run_id == "test-rt"
        assert restored.generated_at == "2025-01-01T00:00:00Z"
        assert restored.summary["total_atoms"] == 5

    def test_round_trip_preserves_nested_data(self, tmp_path: Path) -> None:
        from spec_manager.schemas.lineage import (
            AtomAnalysisEntry,
            LineageEdge,
            OrphanedArchEntry,
        )

        schema = AnalysisFileSchema(
            run_id="test-nested",
            generated_at="2025-06-01T12:00:00Z",
            atoms=[
                AtomAnalysisEntry(
                    atom_id="validate_payment",
                    atom_file="atoms/payment.py",
                    forward_traces=[
                        LineageEdge(
                            from_atom="validate_payment",
                            to_location="src/h.py:proc",
                            transformation="pass_through",
                            confidence=0.99,
                        )
                    ],
                    is_unimplemented=False,
                )
            ],
            orphaned_architecture=[
                OrphanedArchEntry(
                    location="src/orphan.py",
                    description="Unknown",
                    suggested_action="investigate",
                )
            ],
            summary={"total_atoms": 1},
        )

        json_path = tmp_path / "nested.json"
        write_analysis_json(schema, json_path)
        restored = read_analysis_json(json_path)

        assert restored == schema

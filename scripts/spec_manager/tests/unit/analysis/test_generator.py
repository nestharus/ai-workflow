"""Tests for the analysis file generator (JSON persistence)."""

from __future__ import annotations

from pathlib import Path

from spec_manager.analysis.generator import (
    generate_analysis_file,
    read_analysis_json,
    write_analysis_json,
)
from spec_manager.schemas.lineage import AnalysisFileSchema


class TestGenerateAnalysisFile:
    """Test that generate_analysis_file returns a valid minimal schema."""

    def test_returns_valid_schema(self, tmp_path: Path) -> None:
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        arch_dir = tmp_path / "arch"
        arch_dir.mkdir()

        analysis = generate_analysis_file(
            algorithmic_dir=algo_dir,
            architectural_dir=arch_dir,
            run_id="test-001",
        )

        assert analysis.run_id == "test-001"
        assert analysis.generated_at != ""
        assert analysis.atoms == []
        assert analysis.orphaned_architecture == []
        assert analysis.summary["total_atoms"] == 0

    def test_idempotency(self, tmp_path: Path) -> None:
        algo_dir = tmp_path / "algo"
        algo_dir.mkdir()
        arch_dir = tmp_path / "arch"
        arch_dir.mkdir()

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

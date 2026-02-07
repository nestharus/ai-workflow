"""Tests for provenance tracking."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.provenance import (
    AtomProvenance,
    ProvenanceRegistry,
    check_provenance_complete,
    update_provenance_from_registry,
)
from spec_manager.schemas.pin_functions import PinFunction, PinFunctionRegistry


def _make_pin_func(pin_id: str, name: str, content_hash: str) -> PinFunction:
    return PinFunction(
        pin_func_id=pin_id,
        function_name=name,
        module_path=f"atoms.{name}",
        file_path=f"atoms/{name}.py",
        line_start=1,
        line_end=10,
        signature=f"def {name}()",
        docstring=f"Doc for {name}",
        content_hash=content_hash,
    )


def _make_registry(*pin_funcs: PinFunction) -> PinFunctionRegistry:
    return PinFunctionRegistry(
        schema_version="1.0",
        pin_functions=list(pin_funcs),
        import_edges=[],
        created_at="2024-01-01T00:00:00Z",
    )


class TestAtomProvenance:
    def test_add_modification(self) -> None:
        prov = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="compute",
            file_path="atoms/compute.py",
            introduced_by="plan_001",
        )
        prov.add_modification("plan_002")
        assert prov.modified_by == ["plan_002"]

    def test_add_modification_deduplicates(self) -> None:
        prov = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="compute",
            file_path="atoms/compute.py",
            introduced_by="plan_001",
        )
        prov.add_modification("plan_002")
        prov.add_modification("plan_002")
        assert prov.modified_by == ["plan_002"]

    def test_to_dict(self) -> None:
        prov = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="compute",
            file_path="atoms/compute.py",
            introduced_by="plan_001",
            modified_by=["plan_002"],
            source_location="evidence:E001",
            content_hash="abc123",
            created_at="2024-01-01T00:00:00Z",
            last_modified_at="2024-01-02T00:00:00Z",
        )
        d = prov.to_dict()
        assert d["pin_func_id"] == "PFUNC-0001"
        assert d["introduced_by"] == "plan_001"
        assert d["modified_by"] == ["plan_002"]
        assert d["source_location"] == "evidence:E001"

    def test_from_dict(self) -> None:
        data = {
            "pin_func_id": "PFUNC-0001",
            "function_name": "compute",
            "file_path": "atoms/compute.py",
            "introduced_by": "plan_001",
            "modified_by": ["plan_002"],
            "source_location": "evidence:E001",
            "content_hash": "abc123",
            "created_at": "2024-01-01T00:00:00Z",
            "last_modified_at": "2024-01-02T00:00:00Z",
        }
        prov = AtomProvenance.from_dict(data)
        assert prov.pin_func_id == "PFUNC-0001"
        assert prov.introduced_by == "plan_001"
        assert prov.modified_by == ["plan_002"]

    def test_roundtrip(self) -> None:
        prov = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="compute",
            file_path="atoms/compute.py",
            introduced_by="plan_001",
            modified_by=["plan_002", "plan_003"],
            source_location="evidence:E001",
            content_hash="abc123",
        )
        restored = AtomProvenance.from_dict(prov.to_dict())
        assert restored.pin_func_id == prov.pin_func_id
        assert restored.introduced_by == prov.introduced_by
        assert restored.modified_by == prov.modified_by
        assert restored.source_location == prov.source_location


class TestProvenanceRegistry:
    def test_get_existing(self) -> None:
        registry = ProvenanceRegistry()
        prov = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="compute",
            file_path="a.py",
            introduced_by="plan_001",
        )
        registry.upsert(prov)
        result = registry.get("PFUNC-0001")
        assert result is not None
        assert result.function_name == "compute"

    def test_get_missing(self) -> None:
        registry = ProvenanceRegistry()
        assert registry.get("PFUNC-9999") is None

    def test_upsert_overwrite(self) -> None:
        registry = ProvenanceRegistry()
        prov1 = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="v1",
            file_path="a.py",
            introduced_by="plan_001",
        )
        prov2 = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="v2",
            file_path="a.py",
            introduced_by="plan_001",
        )
        registry.upsert(prov1)
        registry.upsert(prov2)
        assert registry.get("PFUNC-0001").function_name == "v2"

    def test_to_dict_from_dict(self) -> None:
        registry = ProvenanceRegistry()
        prov = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="compute",
            file_path="a.py",
            introduced_by="plan_001",
        )
        registry.upsert(prov)
        d = registry.to_dict()
        restored = ProvenanceRegistry.from_dict(d)
        assert "PFUNC-0001" in restored.records
        assert restored.records["PFUNC-0001"].function_name == "compute"

    def test_save_and_load(self, tmp_path: Path) -> None:
        registry = ProvenanceRegistry()
        prov = AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="compute",
            file_path="a.py",
            introduced_by="plan_001",
            content_hash="abc123",
        )
        registry.upsert(prov)

        path = tmp_path / "sub" / "provenance.json"
        registry.save(path)
        assert path.exists()

        loaded = ProvenanceRegistry.load(path)
        assert "PFUNC-0001" in loaded.records
        assert loaded.records["PFUNC-0001"].content_hash == "abc123"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.json"
        loaded = ProvenanceRegistry.load(path)
        assert len(loaded.records) == 0

    def test_serialization_json_roundtrip(self) -> None:
        registry = ProvenanceRegistry()
        for i in range(3):
            prov = AtomProvenance(
                pin_func_id=f"PFUNC-{i:04d}",
                function_name=f"func_{i}",
                file_path=f"atoms/func_{i}.py",
                introduced_by="initial_scan",
            )
            registry.upsert(prov)

        serialized = json.dumps(registry.to_dict())
        deserialized = json.loads(serialized)
        restored = ProvenanceRegistry.from_dict(deserialized)
        assert len(restored.records) == 3


class TestUpdateProvenanceFromRegistry:
    def test_new_functions_get_introduced_by(self) -> None:
        pf1 = _make_pin_func("PFUNC-0001", "func_a", "hash_a")
        pf2 = _make_pin_func("PFUNC-0002", "func_b", "hash_b")
        pin_registry = _make_registry(pf1, pf2)
        existing = ProvenanceRegistry()

        updated = update_provenance_from_registry(
            pin_registry, existing, modifier="initial_scan"
        )

        assert "PFUNC-0001" in updated.records
        assert "PFUNC-0002" in updated.records
        assert updated.records["PFUNC-0001"].introduced_by == "initial_scan"
        assert updated.records["PFUNC-0002"].introduced_by == "initial_scan"
        assert updated.records["PFUNC-0001"].content_hash == "hash_a"

    def test_changed_function_gets_modification(self) -> None:
        pf1 = _make_pin_func("PFUNC-0001", "func_a", "hash_a_v2")
        pin_registry = _make_registry(pf1)

        existing = ProvenanceRegistry()
        existing.upsert(AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="func_a",
            file_path="atoms/func_a.py",
            introduced_by="initial_scan",
            content_hash="hash_a_v1",
        ))

        updated = update_provenance_from_registry(
            pin_registry, existing, modifier="plan_002"
        )

        record = updated.get("PFUNC-0001")
        assert record is not None
        assert record.introduced_by == "initial_scan"  # Unchanged
        assert "plan_002" in record.modified_by
        assert record.content_hash == "hash_a_v2"

    def test_unchanged_function_not_modified(self) -> None:
        pf1 = _make_pin_func("PFUNC-0001", "func_a", "hash_a")
        pin_registry = _make_registry(pf1)

        existing = ProvenanceRegistry()
        existing.upsert(AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="func_a",
            file_path="atoms/func_a.py",
            introduced_by="initial_scan",
            content_hash="hash_a",
        ))

        updated = update_provenance_from_registry(
            pin_registry, existing, modifier="plan_002"
        )

        record = updated.get("PFUNC-0001")
        assert record is not None
        assert record.modified_by == []


class TestCheckProvenanceComplete:
    def test_all_have_provenance_passes(self) -> None:
        pf1 = _make_pin_func("PFUNC-0001", "func_a", "hash_a")
        pin_registry = _make_registry(pf1)

        prov_registry = ProvenanceRegistry()
        prov_registry.upsert(AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="func_a",
            file_path="atoms/func_a.py",
            introduced_by="initial_scan",
        ))

        gate_spec = GateSpec(gate_id=GateId.PROVENANCE_COMPLETE)
        result = check_provenance_complete(pin_registry, prov_registry, gate_spec)
        assert result.passed is True

    def test_missing_provenance_fails(self) -> None:
        pf1 = _make_pin_func("PFUNC-0001", "func_a", "hash_a")
        pin_registry = _make_registry(pf1)
        prov_registry = ProvenanceRegistry()

        gate_spec = GateSpec(gate_id=GateId.PROVENANCE_COMPLETE)
        result = check_provenance_complete(pin_registry, prov_registry, gate_spec)
        assert result.passed is False
        assert len(result.findings) == 1

    def test_require_source_location(self) -> None:
        pf1 = _make_pin_func("PFUNC-0001", "func_a", "hash_a")
        pin_registry = _make_registry(pf1)

        prov_registry = ProvenanceRegistry()
        prov_registry.upsert(AtomProvenance(
            pin_func_id="PFUNC-0001",
            function_name="func_a",
            file_path="atoms/func_a.py",
            introduced_by="initial_scan",
            source_location="",  # Empty
        ))

        gate_spec = GateSpec(
            gate_id=GateId.PROVENANCE_COMPLETE,
            params={"require_source_location": True},
        )
        result = check_provenance_complete(pin_registry, prov_registry, gate_spec)
        assert result.passed is False

    def test_empty_registry_passes(self) -> None:
        pin_registry = _make_registry()
        prov_registry = ProvenanceRegistry()

        gate_spec = GateSpec(gate_id=GateId.PROVENANCE_COMPLETE)
        result = check_provenance_complete(pin_registry, prov_registry, gate_spec)
        assert result.passed is True
        assert result.score == 1.0

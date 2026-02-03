from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.schemas.edge_list import (
    EdgeListSchema,
    EdgeSchema,
    allocate_edge_id,
    read_edge_list_json,
    validate_edge_references,
    write_edge_list_json,
)


def _create_edge(
    *,
    edge_id: str = "EDGE-LIB-0001-LIB-0002",
    consumer_lib: str = "LIB-0001",
    provider_lib: str = "LIB-0002",
) -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "consumer_lib": consumer_lib,
        "provider_lib": provider_lib,
        "kind": "api",
        "consumer_elements": ["REQ-LIB-0001-0001"],
        "provider_elements": ["INV-LIB-0002-0001"],
        "summary": "Consumer depends on provider API.",
        "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
    }


def test_edge_schema_valid() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    assert edge.edge_id == "EDGE-LIB-0001-LIB-0002"


def test_edge_schema_invalid_edge_id() -> None:
    payload = _create_edge(edge_id="EDGE-0001-0002")
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)


def test_edge_schema_invalid_lib_id() -> None:
    payload = _create_edge(consumer_lib="LIB-1")
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)


def test_edge_schema_mismatched_consumer_in_edge_id() -> None:
    payload = _create_edge(edge_id="EDGE-LIB-0003-LIB-0002", consumer_lib="LIB-0001")
    with pytest.raises(ValidationError, match="consumer segment"):
        EdgeSchema.model_validate(payload)


def test_edge_schema_mismatched_provider_in_edge_id() -> None:
    payload = _create_edge(edge_id="EDGE-LIB-0001-LIB-0003", provider_lib="LIB-0002")
    with pytest.raises(ValidationError, match="provider segment"):
        EdgeSchema.model_validate(payload)


def test_edge_schema_invalid_element_id() -> None:
    payload = _create_edge()
    payload["consumer_elements"] = ["REQ-0001"]
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)


def test_edge_schema_invalid_evidence_pointer() -> None:
    payload = _create_edge()
    payload["evidence"] = ["NOT-A-POINTER"]
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)


def test_edge_list_schema_valid() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    report = EdgeListSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges=[edge],
    )
    assert report.edges[0].edge_id == edge.edge_id


def test_edge_list_schema_rejects_duplicate_ids() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    with pytest.raises(ValidationError):
        EdgeListSchema(
            run_id="run_001",
            generated_at="2024-01-01T00:00:00",
            edges=[edge, edge],
        )


def test_edge_list_schema_invalid_generated_at() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    with pytest.raises(ValidationError):
        EdgeListSchema(
            run_id="run_001",
            generated_at="2024-01-01",
            edges=[edge],
        )


def test_allocate_edge_id_valid() -> None:
    assert allocate_edge_id("LIB-0001", "LIB-0002") == "EDGE-LIB-0001-LIB-0002"


def test_allocate_edge_id_invalid() -> None:
    with pytest.raises(ValueError):
        allocate_edge_id("LIB-1", "LIB-0002")


def test_validate_edge_references_valid() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    is_valid, errors = validate_edge_references(
        edge,
        {"LIB-0001", "LIB-0002"},
        {
            "LIB-0001": {"REQ-LIB-0001-0001"},
            "LIB-0002": {"INV-LIB-0002-0001"},
        },
    )
    assert is_valid is True
    assert errors == []


def test_validate_edge_references_missing_consumer_lib() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    is_valid, errors = validate_edge_references(
        edge,
        {"LIB-0002"},
        {
            "LIB-0001": {"REQ-LIB-0001-0001"},
            "LIB-0002": {"INV-LIB-0002-0001"},
        },
    )
    assert is_valid is False
    assert any("consumer library" in error for error in errors)


def test_validate_edge_references_missing_provider_lib() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    is_valid, errors = validate_edge_references(
        edge,
        {"LIB-0001"},
        {
            "LIB-0001": {"REQ-LIB-0001-0001"},
            "LIB-0002": {"INV-LIB-0002-0001"},
        },
    )
    assert is_valid is False
    assert any("provider library" in error for error in errors)


def test_validate_edge_references_missing_consumer_elements() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    is_valid, errors = validate_edge_references(
        edge,
        {"LIB-0001", "LIB-0002"},
        {"LIB-0001": set(), "LIB-0002": {"INV-LIB-0002-0001"}},
    )
    assert is_valid is False
    assert any("Missing consumer elements" in error for error in errors)


def test_validate_edge_references_missing_provider_elements() -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    is_valid, errors = validate_edge_references(
        edge,
        {"LIB-0001", "LIB-0002"},
        {"LIB-0001": {"REQ-LIB-0001-0001"}, "LIB-0002": set()},
    )
    assert is_valid is False
    assert any("Missing provider elements" in error for error in errors)


def test_edge_list_json_round_trip(fs) -> None:
    edge = EdgeSchema.model_validate(_create_edge())
    report = EdgeListSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges=[edge],
    )
    output_path = Path("/work/edge_list.json")
    write_edge_list_json(report, output_path)

    loaded = read_edge_list_json(output_path)
    assert loaded.run_id == report.run_id
    assert loaded.edges[0].edge_id == edge.edge_id

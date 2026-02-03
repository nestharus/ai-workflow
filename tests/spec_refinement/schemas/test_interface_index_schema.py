from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.schemas.edge_list import (
    EdgeSchema,
    InterfaceIndexSchema,
    build_interface_index,
    read_interface_index_json,
    write_interface_index_json,
)


def _create_edge(
    *,
    edge_id: str,
    consumer_lib: str,
    provider_lib: str,
) -> EdgeSchema:
    return EdgeSchema.model_validate(
        {
            "edge_id": edge_id,
            "consumer_lib": consumer_lib,
            "provider_lib": provider_lib,
            "kind": "api",
            "consumer_elements": [f"REQ-{consumer_lib}-0001"],
            "provider_elements": [f"REQ-{provider_lib}-0001"],
            "summary": "Dependency summary.",
            "evidence": [f"[{consumer_lib}::spec.md::REQ-{consumer_lib}-0001]"],
        }
    )


def test_interface_index_schema_valid() -> None:
    index = InterfaceIndexSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges_by_consumer={"LIB-0001": ["EDGE-LIB-0001-LIB-0002"]},
        edges_by_provider={"LIB-0002": ["EDGE-LIB-0001-LIB-0002"]},
        contract_files={
            "EDGE-LIB-0001-LIB-0002": {
                "markdown": "libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.md",
                "json": "libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.json",
            }
        },
    )
    assert index.run_id == "run_001"


def test_interface_index_schema_invalid_generated_at() -> None:
    with pytest.raises(ValidationError):
        InterfaceIndexSchema(
            run_id="run_001",
            generated_at="2024-01-01",
            edges_by_consumer={},
            edges_by_provider={},
            contract_files={},
        )


def test_build_interface_index() -> None:
    edges = [
        _create_edge(
            edge_id="EDGE-LIB-0001-LIB-0002",
            consumer_lib="LIB-0001",
            provider_lib="LIB-0002",
        ),
        _create_edge(
            edge_id="EDGE-LIB-0002-LIB-0003",
            consumer_lib="LIB-0002",
            provider_lib="LIB-0003",
        ),
    ]
    index = build_interface_index(edges, "run_001", Path("/work"))

    assert index.edges_by_consumer == {
        "LIB-0001": ["EDGE-LIB-0001-LIB-0002"],
        "LIB-0002": ["EDGE-LIB-0002-LIB-0003"],
    }
    assert index.edges_by_provider == {
        "LIB-0002": ["EDGE-LIB-0001-LIB-0002"],
        "LIB-0003": ["EDGE-LIB-0002-LIB-0003"],
    }
    assert index.contract_files["EDGE-LIB-0001-LIB-0002"]["markdown"] == (
        "/work/libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.md"
    )
    assert index.contract_files["EDGE-LIB-0001-LIB-0002"]["json"] == (
        "/work/libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.json"
    )


def test_interface_index_json_round_trip(fs) -> None:
    index = InterfaceIndexSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges_by_consumer={"LIB-0001": ["EDGE-LIB-0001-LIB-0002"]},
        edges_by_provider={"LIB-0002": ["EDGE-LIB-0001-LIB-0002"]},
        contract_files={
            "EDGE-LIB-0001-LIB-0002": {
                "markdown": "libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.md",
                "json": "libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.json",
            }
        },
    )
    output_path = Path("/work/interface_index.json")
    write_interface_index_json(index, output_path)

    loaded = read_interface_index_json(output_path)
    assert loaded.edges_by_consumer["LIB-0001"] == ["EDGE-LIB-0001-LIB-0002"]

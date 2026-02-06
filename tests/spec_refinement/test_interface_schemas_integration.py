from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.refinement.formats import parse_evidence_pointer
from spec_manager.schemas.edge_list import (
    EdgeListSchema,
    EdgeSchema,
    build_interface_index,
    read_edge_list_json,
    read_interface_index_json,
    validate_contract_completeness,
    validate_edge_list_completeness,
    write_edge_list_json,
    write_interface_index_json,
)
from spec_manager.schemas.interface_contract import (
    InterfaceContractSchema,
    read_interface_contract_json,
    write_interface_contract_json,
    write_interface_contract_markdown,
)
from spec_manager.schemas.spec_indexes import SpecElement, SpecIndex


def _build_spec_index(lib_id: str, element_ids: list[str]) -> SpecIndex:
    elements: list[SpecElement] = []
    for index, element_id in enumerate(element_ids, start=1):
        if element_id.startswith("DTL-"):
            kind = "detail"
        elif element_id.startswith("CON-"):
            kind = "constraint"
        else:
            kind = "detail"
        elements.append(
            SpecElement(
                element_id=element_id,
                kind=kind,
                section=f"Section {index}",
                text="Element text.",
                raw_line="- Element text.",
            )
        )
    return SpecIndex(
        lib_id=lib_id,
        generated_at="2024-01-01T00:00:00",
        spec_path=f"libraries/{lib_id}/spec.md",
        elements=elements,
    )


def _build_edge(
    edge_id: str,
    consumer_lib: str,
    provider_lib: str,
    consumer_element: str,
    provider_element: str,
) -> EdgeSchema:
    return EdgeSchema.model_validate(
        {
            "edge_id": edge_id,
            "consumer_lib": consumer_lib,
            "provider_lib": provider_lib,
            "kind": "api",
            "consumer_elements": [consumer_element],
            "provider_elements": [provider_element],
            "summary": "Edge summary.",
            "evidence": [f"[{consumer_lib}::spec.md::{consumer_element}]"],
        }
    )


def test_interface_schema_workflow_round_trip(fs) -> None:
    edges = [
        _build_edge(
            "EDGE-LIB-0001-LIB-0002",
            "LIB-0001",
            "LIB-0002",
            "DTL-LIB-0001-0001",
            "DTL-LIB-0002-0001",
        ),
        _build_edge(
            "EDGE-LIB-0002-LIB-0003",
            "LIB-0002",
            "LIB-0003",
            "DTL-LIB-0002-0002",
            "DTL-LIB-0003-0001",
        ),
    ]

    edge_list = EdgeListSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges=edges,
    )

    spec_indexes = {
        "LIB-0001": _build_spec_index("LIB-0001", ["DTL-LIB-0001-0001"]),
        "LIB-0002": _build_spec_index(
            "LIB-0002",
            ["DTL-LIB-0002-0001", "DTL-LIB-0002-0002"],
        ),
        "LIB-0003": _build_spec_index("LIB-0003", ["DTL-LIB-0003-0001"]),
    }

    errors = validate_edge_list_completeness(edge_list, set(spec_indexes), spec_indexes)
    assert errors == []

    index = build_interface_index(edge_list.edges, edge_list.run_id, Path("/work"))

    edge_list_path = Path("/work/edge_list.json")
    index_path = Path("/work/interface_index.json")
    write_edge_list_json(edge_list, edge_list_path)
    write_interface_index_json(index, index_path)

    for edge in edge_list.edges:
        contract = InterfaceContractSchema.model_validate(
            {
                "edge_id": edge.edge_id,
                "consumer_lib": edge.consumer_lib,
                "provider_lib": edge.provider_lib,
                "contract_version": "v1",
                "provided": [
                    {
                        "name": "PrimaryInterface",
                        "type": "http",
                        "requirements": edge.provider_elements,
                        "details": "Contract details.",
                        "acceptance": ["Returns expected payload"],
                        "citations": edge.evidence,
                    }
                ],
                "consumed_by": [
                    {
                        "consumer_requirement": edge.consumer_elements[0],
                        "expectations": ["Availability 99.9%"],
                        "citations": edge.evidence,
                    }
                ],
                "open_questions": [],
            }
        )
        contract_paths = index.contract_files[edge.edge_id]
        contract_json_path = Path(contract_paths["json"])
        contract_md_path = Path(contract_paths["markdown"])
        write_interface_contract_json(contract, contract_json_path)
        write_interface_contract_markdown(contract, contract_md_path)

        loaded = read_interface_contract_json(contract_json_path)
        assert loaded.edge_id == contract.edge_id

        completeness_errors = validate_contract_completeness(
            contract,
            set(spec_indexes),
            spec_indexes,
        )
        assert completeness_errors == []

    loaded_edge_list = read_edge_list_json(edge_list_path)
    loaded_index = read_interface_index_json(index_path)

    assert loaded_edge_list.run_id == edge_list.run_id
    assert loaded_index.edges_by_consumer["LIB-0001"] == ["EDGE-LIB-0001-LIB-0002"]


def test_interface_schema_validation_errors() -> None:
    edge = _build_edge(
        "EDGE-LIB-0001-LIB-0002",
        "LIB-0001",
        "LIB-0002",
        "DTL-LIB-0001-0001",
        "DTL-LIB-0002-0001",
    )
    edge_list = EdgeListSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges=[edge],
    )
    spec_indexes = {
        "LIB-0001": _build_spec_index("LIB-0001", ["DTL-LIB-0001-0001"]),
        "LIB-0002": _build_spec_index("LIB-0002", ["DTL-LIB-0002-0001"]),
    }

    errors_missing_lib = validate_edge_list_completeness(
        edge_list,
        {"LIB-0001"},
        spec_indexes,
    )
    assert errors_missing_lib

    errors_missing_element = validate_edge_list_completeness(
        edge_list,
        {"LIB-0001", "LIB-0002"},
        {
            "LIB-0001": _build_spec_index("LIB-0001", []),
            "LIB-0002": _build_spec_index("LIB-0002", ["DTL-LIB-0002-0001"]),
        },
    )
    assert errors_missing_element

    invalid_contract = {
        "edge_id": "EDGE-LIB-0001-LIB-0002",
        "consumer_lib": "LIB-0001",
        "provider_lib": "LIB-0002",
        "contract_version": "v1",
        "provided": [
            {
                "name": "Invalid",
                "type": "http",
                "requirements": ["DTL-LIB-0002-0001"],
                "details": "Details",
                "acceptance": [],
                "citations": ["NOT-A-POINTER"],
            }
        ],
        "consumed_by": [
            {
                "consumer_requirement": "DTL-LIB-0001-0001",
                "expectations": [],
                "citations": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
            }
        ],
        "open_questions": [],
    }
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(invalid_contract)


def test_multi_hop_pointer_validation() -> None:
    pointers = [
        "[LIB-0001::spec.md::DTL-LIB-0001-0003]",
        "[LIB-0002::charter.md::Intent]",
        "[spec_snapshot/file.md::SEC-F0001-0001]",
    ]
    for pointer in pointers:
        assert parse_evidence_pointer(pointer, allow_multi_hop=True) is not None

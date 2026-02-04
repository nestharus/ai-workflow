from __future__ import annotations

import pytest
from pydantic import ValidationError
from spec_manager.schemas.edge_list import (
    EdgeListSchema,
    EdgeSchema,
    validate_contract_completeness,
    validate_edge_references,
)
from spec_manager.schemas.interface_contract import InterfaceContractSchema, validate_contract_references

pytestmark = [pytest.mark.interfaces, pytest.mark.contract_validation]


def _make_valid_edge() -> EdgeSchema:
    payload = {
        "edge_id": "EDGE-LIB-0001-LIB-0002",
        "consumer_lib": "LIB-0001",
        "provider_lib": "LIB-0002",
        "kind": "api",
        "consumer_elements": ["REQ-LIB-0001-0001"],
        "provider_elements": ["REQ-LIB-0002-0001"],
        "summary": "Consumer uses provider API.",
        "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
    }
    return EdgeSchema.model_validate(payload)


def _make_valid_contract() -> InterfaceContractSchema:
    payload = {
        "edge_id": "EDGE-LIB-0001-LIB-0002",
        "consumer_lib": "LIB-0001",
        "provider_lib": "LIB-0002",
        "contract_version": "v1",
        "provided": [
            {
                "name": "Primary API",
                "type": "http",
                "requirements": ["REQ-LIB-0002-0001"],
                "details": "Provides primary endpoint.",
                "acceptance": ["Returns expected payload"],
                "citations": ["[LIB-0002::spec.md::REQ-LIB-0002-0001]"],
            }
        ],
        "consumed_by": [
            {
                "consumer_requirement": "REQ-LIB-0001-0001",
                "expectations": ["Latency under 200ms"],
                "citations": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            }
        ],
        "open_questions": ["DEC-LIB-0001-0001"],
    }
    return InterfaceContractSchema.model_validate(payload)


def _make_element_lookup(libraries: dict[str, list[str]]) -> dict[str, set[str]]:
    return {lib_id: set(elements) for lib_id, elements in libraries.items()}


def test_edge_schema_validates_edge_id_format() -> None:
    payload = _make_valid_edge().model_dump()
    payload["edge_id"] = "EDGE-0001-0002"
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)

    valid = EdgeSchema.model_validate(_make_valid_edge().model_dump())
    assert valid.edge_id == "EDGE-LIB-0001-LIB-0002"


def test_edge_schema_validates_library_ids() -> None:
    payload = _make_valid_edge().model_dump()
    payload["consumer_lib"] = "LIB-1"
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)


def test_edge_schema_validates_element_ids() -> None:
    payload = _make_valid_edge().model_dump()
    payload["consumer_elements"] = ["REQ-0001"]
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)

    valid = EdgeSchema.model_validate(_make_valid_edge().model_dump())
    assert valid.consumer_elements == ["REQ-LIB-0001-0001"]


def test_edge_schema_validates_evidence_pointers() -> None:
    payload = _make_valid_edge().model_dump()
    payload["evidence"] = ["NOT-A-POINTER"]
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)

    payload["evidence"] = ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"]
    edge = EdgeSchema.model_validate(payload)
    assert edge.evidence


def test_edge_schema_validates_edge_id_matches_libs() -> None:
    payload = _make_valid_edge().model_dump()
    payload["edge_id"] = "EDGE-LIB-0003-LIB-0002"
    with pytest.raises(ValidationError, match="consumer segment"):
        EdgeSchema.model_validate(payload)


def test_edge_list_validates_unique_edge_ids() -> None:
    edge = _make_valid_edge()
    with pytest.raises(ValidationError):
        EdgeListSchema(
            run_id="run_001",
            generated_at="2024-01-01T00:00:00",
            edges=[edge, edge],
        )


def test_validate_edge_references_checks_library_existence() -> None:
    edge = _make_valid_edge()
    element_lookup = _make_element_lookup(
        {
            "LIB-0001": ["REQ-LIB-0001-0001"],
            "LIB-0002": ["REQ-LIB-0002-0001"],
        }
    )
    is_valid, errors = validate_edge_references(
        edge,
        {"LIB-0002"},
        element_lookup,
    )
    assert is_valid is False
    assert any("Unknown consumer library" in error for error in errors)


def test_validate_edge_references_checks_element_existence() -> None:
    edge = _make_valid_edge()
    element_lookup = _make_element_lookup(
        {
            "LIB-0001": [],
            "LIB-0002": ["REQ-LIB-0002-0001"],
        }
    )
    is_valid, errors = validate_edge_references(
        edge,
        {"LIB-0001", "LIB-0002"},
        element_lookup,
    )
    assert is_valid is False
    assert any("Missing consumer elements" in error for error in errors)


def test_contract_schema_validates_provided_interfaces() -> None:
    payload = _make_valid_contract().model_dump()
    payload["provided"][0]["requirements"] = ["REQ-1"]
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(payload)


def test_contract_schema_validates_consumed_interfaces() -> None:
    payload = _make_valid_contract().model_dump()
    payload["consumed_by"][0]["consumer_requirement"] = "REQ-1"
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(payload)


def test_contract_schema_validates_open_questions() -> None:
    payload = _make_valid_contract().model_dump()
    payload["open_questions"] = ["REQ-1"]
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(payload)


def test_contract_schema_validates_citations() -> None:
    payload = _make_valid_contract().model_dump()
    payload["provided"][0]["citations"] = ["INVALID"]
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(payload)

    payload = _make_valid_contract().model_dump()
    payload["provided"][0]["citations"] = ["[LIB-0002::spec.md::REQ-LIB-0002-0001]"]
    contract = InterfaceContractSchema.model_validate(payload)
    assert contract.provided[0].citations


def test_validate_contract_references_checks_requirements() -> None:
    contract = _make_valid_contract()
    is_valid, errors = validate_contract_references(
        contract,
        {"LIB-0001", "LIB-0002"},
        {
            "LIB-0001": {"REQ-LIB-0001-0001", "DEC-LIB-0001-0001"},
            "LIB-0002": set(),
        },
    )
    assert is_valid is False
    assert any("Missing provider requirements" in error for error in errors)


def test_validate_contract_completeness_requires_provided() -> None:
    contract = _make_valid_contract()
    contract.provided = []
    errors = validate_contract_completeness(
        contract,
        {"LIB-0001", "LIB-0002"},
        {
            "LIB-0001": {"elements": [{"element_id": "REQ-LIB-0001-0001"}]},
            "LIB-0002": {"elements": [{"element_id": "REQ-LIB-0002-0001"}]},
        },
    )
    assert any("At least one provided interface" in error["message"] for error in errors)


def test_validate_contract_completeness_requires_consumed_by() -> None:
    contract = _make_valid_contract()
    contract.consumed_by = []
    errors = validate_contract_completeness(
        contract,
        {"LIB-0001", "LIB-0002"},
        {
            "LIB-0001": {"elements": [{"element_id": "REQ-LIB-0001-0001"}]},
            "LIB-0002": {"elements": [{"element_id": "REQ-LIB-0002-0001"}]},
        },
    )
    assert any("At least one consumer entry" in error["message"] for error in errors)


def test_multi_hop_pointer_validation_allows_library_references() -> None:
    payload = _make_valid_edge().model_dump()
    payload["evidence"] = ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"]
    edge = EdgeSchema.model_validate(payload)
    assert edge.evidence


def test_compound_pointer_validation_rejects_compound_format() -> None:
    payload = _make_valid_edge().model_dump()
    payload["evidence"] = ["[F0001::INTRO, F0001::REQS]"]
    with pytest.raises(ValidationError):
        EdgeSchema.model_validate(payload)

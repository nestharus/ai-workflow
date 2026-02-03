from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from spec_manager.schemas.interface_contract import (
    ConsumedInterface,
    InterfaceContractSchema,
    ProvidedInterface,
    read_interface_contract_json,
    validate_contract_references,
    write_interface_contract_json,
    write_interface_contract_markdown,
)


def _create_provided() -> dict[str, object]:
    return {
        "name": "ListItems",
        "type": "http",
        "requirements": ["REQ-LIB-0002-0001"],
        "details": "Lists items from the catalog.",
        "acceptance": ["Returns 200 with items"],
        "citations": ["[LIB-0002::spec.md::REQ-LIB-0002-0001]"],
    }


def _create_consumed() -> dict[str, object]:
    return {
        "consumer_requirement": "REQ-LIB-0001-0001",
        "expectations": ["Latency under 100ms"],
        "citations": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
    }


def _create_contract() -> dict[str, object]:
    return {
        "edge_id": "EDGE-LIB-0001-LIB-0002",
        "consumer_lib": "LIB-0001",
        "provider_lib": "LIB-0002",
        "contract_version": "v1",
        "provided": [_create_provided()],
        "consumed_by": [_create_consumed()],
        "open_questions": ["DEC-LIB-0001-0001"],
    }


def test_provided_interface_valid() -> None:
    interface = ProvidedInterface.model_validate(_create_provided())
    assert interface.type == "http"


def test_provided_interface_invalid_requirement() -> None:
    payload = _create_provided()
    payload["requirements"] = ["REQ-1"]
    with pytest.raises(ValidationError):
        ProvidedInterface.model_validate(payload)


def test_provided_interface_invalid_citation() -> None:
    payload = _create_provided()
    payload["citations"] = ["INVALID"]
    with pytest.raises(ValidationError):
        ProvidedInterface.model_validate(payload)


def test_consumed_interface_valid() -> None:
    interface = ConsumedInterface.model_validate(_create_consumed())
    assert interface.consumer_requirement == "REQ-LIB-0001-0001"


def test_consumed_interface_invalid_requirement() -> None:
    payload = _create_consumed()
    payload["consumer_requirement"] = "REQ-1"
    with pytest.raises(ValidationError):
        ConsumedInterface.model_validate(payload)


def test_interface_contract_valid() -> None:
    contract = InterfaceContractSchema.model_validate(_create_contract())
    assert contract.edge_id == "EDGE-LIB-0001-LIB-0002"


def test_interface_contract_invalid_edge_id() -> None:
    payload = _create_contract()
    payload["edge_id"] = "EDGE-0001-0002"
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(payload)


def test_interface_contract_invalid_lib_id() -> None:
    payload = _create_contract()
    payload["consumer_lib"] = "LIB-1"
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(payload)


def test_interface_contract_mismatched_consumer_in_edge_id() -> None:
    payload = _create_contract()
    payload["edge_id"] = "EDGE-LIB-0003-LIB-0002"
    with pytest.raises(ValidationError, match="consumer segment"):
        InterfaceContractSchema.model_validate(payload)


def test_interface_contract_mismatched_provider_in_edge_id() -> None:
    payload = _create_contract()
    payload["edge_id"] = "EDGE-LIB-0001-LIB-0003"
    with pytest.raises(ValidationError, match="provider segment"):
        InterfaceContractSchema.model_validate(payload)


def test_interface_contract_invalid_decision_id() -> None:
    payload = _create_contract()
    payload["open_questions"] = ["DEC-1"]
    with pytest.raises(ValidationError):
        InterfaceContractSchema.model_validate(payload)


def test_validate_contract_references_valid() -> None:
    contract = InterfaceContractSchema.model_validate(_create_contract())
    is_valid, errors = validate_contract_references(
        contract,
        {"LIB-0001", "LIB-0002"},
        {
            "LIB-0001": {"REQ-LIB-0001-0001", "DEC-LIB-0001-0001"},
            "LIB-0002": {"REQ-LIB-0002-0001"},
        },
    )
    assert is_valid is True
    assert errors == []


def test_validate_contract_references_missing_provider_requirements() -> None:
    contract = InterfaceContractSchema.model_validate(_create_contract())
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


def test_validate_contract_references_missing_consumer_requirements() -> None:
    contract = InterfaceContractSchema.model_validate(_create_contract())
    is_valid, errors = validate_contract_references(
        contract,
        {"LIB-0001", "LIB-0002"},
        {
            "LIB-0001": {"DEC-LIB-0001-0001"},
            "LIB-0002": {"REQ-LIB-0002-0001"},
        },
    )
    assert is_valid is False
    assert any("Missing consumer requirements" in error for error in errors)


def test_interface_contract_json_round_trip(fs) -> None:
    contract = InterfaceContractSchema.model_validate(_create_contract())
    output_path = Path("/work/contract.json")
    write_interface_contract_json(contract, output_path)

    loaded = read_interface_contract_json(output_path)
    assert loaded.edge_id == contract.edge_id
    assert loaded.consumer_lib == contract.consumer_lib


def test_interface_contract_markdown_output(fs) -> None:
    contract = InterfaceContractSchema.model_validate(_create_contract())
    output_path = Path("/work/contract.md")
    write_interface_contract_markdown(contract, output_path)

    content = output_path.read_text(encoding="utf-8")
    assert "## Purpose" in content
    assert "## Provided Interfaces" in content
    assert "## Consumed By" in content
    assert "## Data Contract" in content
    assert "## Operational Concerns" in content
    assert "## Open Questions" in content
    assert "## Evidence" in content
